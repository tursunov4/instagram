"""1080x1920 Reels kadrlarini chizish va ffmpeg bilan videoga yig'ish."""
import functools
import math
import os
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from content import fmt, join_uz, uz

W, H, FPS = 1080, 1920, 30
ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = Path(os.environ.get("FONT_DIR", ROOT / "fonts"))
LOGO = ROOT / "assets" / "logo.png"
DEJAVU = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]

NAVY_T, NAVY_B = (12, 45, 80), (17, 80, 124)
YEL, CYAN, WHITE = (248, 199, 1), (0, 190, 219), (255, 255, 255)
MUTED, INK = (170, 198, 222), (8, 30, 56)
GREEN, RED, BAR = (46, 204, 113), (255, 92, 92), (52, 120, 178)


# ------------------------------------------------------------------ asboblar
@functools.lru_cache(None)
def F(weight, size):
    if weight == "logo":
        for p in DEJAVU:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        weight = "Black"
    return ImageFont.truetype(str(FONT_DIR / f"Montserrat-{weight}.ttf"), size)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(x):
    return 1 - (1 - x) ** 3


def ease_back(x, s=1.6):
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def fit(text, weight, size, maxw, minsize=24):
    while size > minsize and F(weight, size).getlength(text) > maxw:
        size -= 2
    return size


@functools.lru_cache(4096)
def text_im(text, weight, size, fill):
    f = F(weight, size)
    asc, desc = f.getmetrics()
    pad = 10
    im = Image.new("RGBA", (int(math.ceil(f.getlength(text))) + 2 * pad, asc + desc + 2 * pad))
    ImageDraw.Draw(im).text((pad, pad + asc), text, font=f, fill=fill, anchor="ls")
    return im


@functools.lru_cache(512)
def rrect(w, h, r, fill):
    s = 3
    m = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=r * s, fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    if len(fill) == 4:
        m = m.point([int(i * fill[3] / 255) for i in range(256)])
    im = Image.new("RGBA", (w, h), fill[:3] + (255,))
    im.putalpha(m)
    return im


def with_alpha(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point([int(i * a) for i in range(256)]))
    return im


def put(fr, im, x, y, anchor="mm", alpha=1.0, scale=1.0):
    if alpha <= 0.01 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.005:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    im = with_alpha(im, alpha)
    ax = {"l": 0, "m": 0.5, "r": 1}[anchor[0]]
    ay = {"t": 0, "m": 0.5, "b": 1}[anchor[1]]
    x0, y0 = int(round(x - im.width * ax)), int(round(y - im.height * ay))
    cx0, cy0 = max(0, -x0), max(0, -y0)
    cx1, cy1 = min(im.width, W - x0), min(im.height, H - y0)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    if (cx0, cy0, cx1, cy1) != (0, 0, im.width, im.height):
        im = im.crop((cx0, cy0, cx1, cy1))
    fr.alpha_composite(im, (x0 + cx0, y0 + cy0))


# ------------------------------------------------------------------ brend elementlari
@functools.lru_cache(16)
def pin(h, color=GREEN):
    s = 4
    w = int(h * 0.74)
    big = Image.new("RGBA", (w * s, h * s))
    d = ImageDraw.Draw(big)
    r = w * s / 2
    d.ellipse((0, 0, w * s - 1, w * s - 1), fill=color)
    d.polygon([(r * 0.22, r * 1.45), (w * s - r * 0.22, r * 1.45), (r, h * s - 1)], fill=color)
    ir = r * 0.52
    d.ellipse((r - ir, r - ir, r + ir, r + ir), fill=WHITE)
    a = ir * 0.62  # pastga strelka = "arzon"
    d.rectangle((r - a * 0.22, r - a * 0.9, r + a * 0.22, r + a * 0.15), fill=color)
    d.polygon([(r - a * 0.62, r + 0.0), (r + a * 0.62, r + 0.0), (r, r + a * 0.85)], fill=color)
    return big.resize((w, h), Image.LANCZOS)


@functools.lru_cache(8)
def lockup(size):
    """ARZONI / qayerda + pin (logo.png bo'lsa — o'sha ishlatiladi)."""
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGBA")
        k = size * 2.4 / lg.height
        return lg.resize((int(lg.width * k), int(lg.height * k)), Image.LANCZOS)
    fa = F("logo", size)
    wa, wq = fa.getlength("ARZONI"), fa.getlength("qayerda")
    p = pin(int(size * 1.15))
    gap = int(size * 0.12)
    w = int(max(wa, wq + gap + p.width)) + 20
    im = Image.new("RGBA", (w, int(size * 2.35) + 20))
    d = ImageDraw.Draw(im)
    d.text((w / 2, 10 + size * 0.95), "ARZONI", font=fa, fill=YEL, anchor="ms")
    qx = w / 2 - (wq + gap + p.width) / 2
    by = 10 + size * 2.1
    d.text((qx, by), "qayerda", font=fa, fill=WHITE, anchor="ls")
    im.alpha_composite(p, (int(qx + wq + gap), int(by - p.height * 0.95)))
    return im


@functools.lru_cache(2)
def header():
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGBA")
        k = 76 / lg.height
        return lg.resize((int(lg.width * k), 76), Image.LANCZOS)
    size = 44
    fa = F("logo", size)
    w1, w2 = fa.getlength("ARZONI "), fa.getlength("qayerda")
    p = pin(int(size * 1.15))
    im = Image.new("RGBA", (int(w1 + w2 + 10 + p.width) + 24, int(size * 1.6)))
    d = ImageDraw.Draw(im)
    by = int(size * 1.2)
    d.text((12, by), "ARZONI ", font=fa, fill=YEL, anchor="ls")
    d.text((12 + w1, by), "qayerda", font=fa, fill=WHITE, anchor="ls")
    im.alpha_composite(p, (int(12 + w1 + w2 + 10), int(by - p.height * 0.95)))
    return im


@functools.lru_cache(1)
def background():
    t = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(NAVY_T) * (1 - t) + np.array(NAVY_B) * t).repeat(W, axis=1)
    bg = Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")
    return bg


@functools.lru_cache(4)
def glow(diam, color, a):
    im = Image.new("RGBA", (diam, diam))
    m = int(diam * 0.2)
    ImageDraw.Draw(im).ellipse((m, m, diam - m, diam - m), fill=color + (a,))
    return im.filter(ImageFilter.GaussianBlur(diam * 0.12))


def chip(text, weight="SemiBold", size=40, fg=MUTED, bg=(255, 255, 255, 30), padx=34, h=None):
    tx = text_im(text, weight, size, fg)
    h = h or int(size * 1.9)
    box = rrect(tx.width + 2 * padx, h, h // 2, bg).copy()
    box.alpha_composite(tx, (padx, (h - tx.height) // 2))
    return box


# ------------------------------------------------------------------ vaqt chizig'i
GAP = 0.22


def timeline(durs):
    """durs: {qator: sekund}. Sahnalar va ovoz boshlanish vaqtlari."""
    spec = [("hook", ["hook"], 3.0, 0.25, 0.5),
            ("bars", ["cheap", "dear"], 6.0, 0.7, 0.6),
            ("diff", ["diff", "save"], 4.8, 0.35, 0.7),
            ("outro", ["outro"], 3.2, 0.35, 1.1)]
    scenes, voices, t0 = [], {}, 0.0
    for name, keys, mn, lead, tail in spec:
        t, ev = lead, {}
        for k in keys:
            ev[k] = t
            voices[k] = t0 + t
            t += durs[k] + GAP
        D = max(mn, t - GAP + tail)
        scenes.append({"name": name, "start": t0, "dur": D, "ev": ev})
        t0 += D
    return scenes, voices, t0


def _sub_words(text):
    """Raqam guruhlari, "so'm" va tirelar bo'linib ketmasligi uchun."""
    nb = "\u00a0"
    text = re.sub(r"(?<=\d) (?=\d{3}\b)", nb, text)
    text = re.sub(r"(?<=\d) (?=so)", nb, text)
    text = text.replace(" —", nb + "—")
    return [w for w in text.split(" ") if w]


def subtitles(plan, voices, durs, maxc=20):
    subs = []
    for k, t0 in voices.items():
        chunks, cur = [], ""
        for w_ in _sub_words(uz(plan["lines"][k][1])):
            cur = f"{cur} {w_}".strip()
            if len(cur) >= maxc or w_.endswith((".", "!", "?", ":")):
                chunks.append(cur)
                cur = ""
        if cur:
            if chunks and len(cur) < 8:
                chunks[-1] += " " + cur
            else:
                chunks.append(cur)
        total = sum(len(c) for c in chunks)
        t = t0
        for c in chunks:
            d = durs[k] * len(c) / total
            subs.append((t, t + d, c.replace("\u00a0", " ")))
            t += d
    return subs


def sfx_events(scenes, plan):
    ev = []
    for sc in scenes:
        ev.append((max(0, sc["start"] - 0.12), "whoosh"))
        if sc["name"] == "bars":
            for i in range(len(plan["rows"])):
                ev.append((sc["start"] + 0.15 + i * 0.12 + 0.3, "pop"))
            ev.append((sc["start"] + sc["ev"]["cheap"], "ding"))
        if sc["name"] == "diff":
            ev.append((sc["start"] + sc["ev"]["save"], "ding"))
    return ev


# ------------------------------------------------------------------ sahnalar
def scene_alpha(t, D):
    return clamp(min(t / 0.3, (D - t) / 0.22))


def draw_hook(fr, t, D, p, ev, A):
    k = ease_back(prog(t, 0.0, 0.6))
    put(fr, pin(300), W / 2, 440 + 220 * k, "mm", A * prog(t, 0, 0.15))
    name = uz(p["display_name"]).upper()
    sz = fit(name, "Black", 150, 960)
    a1 = ease_out(prog(t, 0.25, 0.45))
    put(fr, text_im(name, "Black", sz, YEL), W / 2, 930 + 50 * (1 - a1), "mm", A * a1)
    a2 = ease_out(prog(t, 0.45, 0.45))
    put(fr, text_im("qayerda arzon?", "ExtraBold", 92, WHITE), W / 2, 1075 + 40 * (1 - a2), "mm", A * a2)
    a3 = ease_out(prog(t, 0.7, 0.4))
    put(fr, chip(f"{p['unit_label']}  •  {p['date']} narxlari"), W / 2, 1210, "mm", A * a3)


def draw_bars(fr, t, D, p, ev, A):
    put(fr, header(), W / 2, 150, "mm", A)
    name = uz(p["display_name"])
    put(fr, text_im(name, "ExtraBold", fit(name, "ExtraBold", 72, 940), YEL), W / 2, 300, "mm", A)
    put(fr, text_im(uz(f"{p['unit_label']} narxi, so'm"), "SemiBold", 42, MUTED), W / 2, 375, "mm", A)
    rows = p["rows"]
    n = len(rows)
    top, bottom = 450, 1270
    rh = min(135, (bottom - top) / n)
    top += max(0, (bottom - top) - rh * n) * 0.4  # kam do'kon bo'lsa — o'rtaroqqa
    bh = int(rh * 0.62)
    lo, hi = rows[0][1], rows[-1][1]
    x0, wmin, wmax = 330, 300, 600
    t_cheap, t_dear = ev["cheap"], ev["dear"]
    for i, (store, v, tag) in enumerate(rows):
        cy = top + rh * (i + 0.5)
        g = ease_out(prog(t, 0.15 + i * 0.12, 0.55))
        a = A * prog(t, 0.15 + i * 0.12, 0.12)
        sz = fit(store, "Bold", 46, 240)
        put(fr, text_im(store, "Bold", sz, WHITE), 300, cy, "rm", a)
        w = int(wmin + (v - lo) / max(1, hi - lo) * (wmax - wmin))
        color = GREEN if tag == "cheap" else RED if tag == "dear" else BAR
        pulse = 0
        if tag == "dear" and t > t_dear:
            pulse = max(0, math.sin((t - t_dear) * 9)) * math.exp(-(t - t_dear) * 1.6)
        bw = max(bh, int(w * g))
        bar = rrect(bw, bh, bh // 2, color)
        put(fr, bar, x0, cy, "lm", a, 1 + 0.05 * pulse)
        if g > 0.35:
            lab = text_im(fmt(v * g), "Bold", int(bh * 0.6), WHITE)
            put(fr, lab, x0 + bw - 18, cy, "rm", a)
        if tag == "cheap":
            k = prog(t, t_cheap, 0.35)
            if k > 0:
                put(fr, chip("ENG ARZON", "ExtraBold", 30, INK, YEL + (255,), 22, 52),
                    x0 + bw + 16, cy, "lm", A, ease_back(k))
        if tag == "dear":
            k = prog(t, t_dear, 0.35)
            if k > 0 and rh - bh > 34:
                put(fr, chip("ENG QIMMAT", "ExtraBold", 26, WHITE, RED + (255,), 18, 42),
                    x0 + bw, cy - bh / 2 - 4, "rb", A, ease_back(k))


@functools.lru_cache(64)
def price_card(store, price, color):
    w, h = 430, 150
    card = rrect(w, h, 34, color + (255,)).copy()
    s1 = text_im(store, "Bold", fit(store, "Bold", 36, w - 40), WHITE)
    s2 = text_im(uz(f"{fmt(price)} so'm"), "ExtraBold", 50, WHITE)
    card.alpha_composite(s1, ((w - s1.width) // 2, 14))
    card.alpha_composite(s2, ((w - s2.width) // 2, 66))
    return card


def draw_diff(fr, t, D, p, ev, A):
    put(fr, header(), W / 2, 150, "mm", A)
    put(fr, text_im("FARQ", "ExtraBold", 58, WHITE), W / 2, 330, "mm", A)
    k = ease_out(prog(t, 0.15, 0.9))
    big = f"+{fmt(p['diff'] * k)} " + uz("so'm")
    put(fr, text_im(big, "Black", fit(big, "Black", 150, 980), YEL), W / 2, 470, "mm", A)
    a = ease_out(prog(t, 0.35, 0.4))
    cheap, dear = ", ".join(p["cheap"]), ", ".join(p["dear"])
    put(fr, price_card(cheap, p["rows"][0][1], GREEN), W / 2 - 235, 680 + 30 * (1 - a), "mm", A * a)
    put(fr, price_card(dear, p["rows"][-1][1], RED), W / 2 + 235, 680 + 30 * (1 - a), "mm", A * a)
    put(fr, text_im(f"{join_uz(p['dear'])}da {p['pct']}% qimmatroq", "SemiBold", 42, MUTED), W / 2, 820, "mm", A * a)
    ks = prog(t, ev["save"], 0.45)
    if ks > 0:
        e = ease_back(ks)
        card = rrect(900, 330, 48, WHITE + (255,)).copy()
        l1 = text_im(f"{p['qty']} {p['qty_unit']} olsangiz", "SemiBold", 50, INK)
        txt = f"{fmt(p['save'])} " + uz("so'm")
        l2 = text_im(txt, "Black", fit(txt, "Black", 112, 840), (24, 160, 85))
        l3 = text_im("tejaysiz!", "ExtraBold", 54, INK)
        card.alpha_composite(l1, ((900 - l1.width) // 2, 22))
        card.alpha_composite(l2, ((900 - l2.width) // 2, 92))
        card.alpha_composite(l3, ((900 - l3.width) // 2, 236))
        put(fr, card, W / 2, 1090 + 60 * (1 - ease_out(ks)), "mm", A * clamp(ks * 2), 0.9 + 0.1 * e)


def draw_outro(fr, t, D, p, ev, A):
    k = ease_back(prog(t, 0.0, 0.55))
    put(fr, lockup(120), W / 2, 600, "mm", A * prog(t, 0, 0.2), 0.6 + 0.4 * k)
    a = ease_out(prog(t, 0.3, 0.4))
    put(fr, text_im(uz("Obuna bo'ling!"), "Black", 92, WHITE), W / 2, 930 + 30 * (1 - a), "mm", A * a)
    a = ease_out(prog(t, 0.5, 0.4))
    put(fr, text_im("Har kuni arzonini topamiz", "SemiBold", 46, MUTED), W / 2, 1030, "mm", A * a)
    put(fr, text_im("@arzoni_qayerdaa", "Bold", 52, CYAN), W / 2, 1120, "mm", A * a)
    a = ease_out(prog(t, 0.7, 0.4))
    put(fr, text_im("Manba: narxtahlil.uz", "Medium", 36, MUTED), W / 2, 1220, "mm", A * a)


DRAW = {"hook": draw_hook, "bars": draw_bars, "diff": draw_diff, "outro": draw_outro}


@functools.lru_cache(256)
def sub_im(text):
    sz = fit(text, "Bold", 52, 860)
    tx = text_im(text, "Bold", sz, WHITE)
    box = rrect(tx.width + 56, tx.height + 22, 26, INK + (200,)).copy()
    box.alpha_composite(tx, (28, 11))
    return box


def frame(t, scenes, plan, subs):
    fr = background().copy()
    put(fr, glow(900, CYAN, 40), 200 + 60 * math.sin(t * 0.5), 380 + 40 * math.cos(t * 0.4))
    put(fr, glow(800, YEL, 22), 900 + 50 * math.cos(t * 0.45), 1500 + 60 * math.sin(t * 0.35))
    for sc in scenes:
        lt = t - sc["start"]
        if 0 <= lt < sc["dur"]:
            DRAW[sc["name"]](fr, lt, sc["dur"], plan, sc["ev"], scene_alpha(lt, sc["dur"]))
    for s, e, text in subs:
        if s <= t < e:
            k = prog(t, s, 0.12)
            put(fr, sub_im(text), W / 2, 1380, "mm", k, 0.92 + 0.08 * k)
    return fr


def render(plan, scenes, subs, T, wav, out_mp4, cover_jpg, cover_t=1.4):
    n = int(T * FPS)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(wav),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(FPS * 2),
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-movflags", "+faststart", "-shortest", str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        t = i / FPS
        fr = frame(t, scenes, plan, subs)
        if i == int(cover_t * FPS):
            fr.convert("RGB").save(cover_jpg, quality=92)
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg xatosi")
