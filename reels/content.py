"""Kunlik mahsulotni tanlash va ovoz/subtitr/caption matnlarini tayyorlash.

Narxlar va raqamlar har doim shablondan chiqadi (aniqlik uchun). Claude faqat
qiziqtiruvchi boshlanish (hook), yakuniy chaqiriq va caption kirish qismini
yozadi; javobi qoidalarga to'g'ri kelmasa, tayyor shablon ishlatiladi.
"""
import json
import os
import random
import re

import requests

# ------------------------------------------------------------------ matn yordamchilari
APOS = "'’‘`ʻʼ"


def apos(s):
    """Har xil apostroflarni oddiy ' ga keltiradi (solishtirish uchun)."""
    return re.sub(f"[{APOS}]", "'", s)


def uz(s):
    """To'g'ri o'zbek imlosi: o'/g' -> oʻ/gʻ, qolgan ' -> ʼ (tutuq belgisi)."""
    s = re.sub(r"([oOgG])'", "\\1ʻ", apos(s))
    return s.replace("'", "ʼ")


def fmt(n):
    return f"{int(n):,}".replace(",", " ")


ONES = ["", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"]
TENS = ["", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson"]


def _under_1000(n):
    h, r = divmod(n, 100)
    t, o = divmod(r, 10)
    parts = []
    if h:
        parts.append("yuz" if h == 1 else f"{ONES[h]} yuz")
    if t:
        parts.append(TENS[t])
    if o:
        parts.append(ONES[o])
    return " ".join(parts)


def num_words(n):
    """12500 -> "o'n ikki ming besh yuz" (ovoz uchun)."""
    n = int(n)
    if n == 0:
        return "nol"
    mln, rest = divmod(n, 1_000_000)
    th, r = divmod(rest, 1000)
    parts = []
    if mln:
        parts.append(f"{_under_1000(mln)} million")
    if th:
        parts.append("ming" if th == 1 else f"{_under_1000(th)} ming")
    if r:
        parts.append(_under_1000(r))
    return " ".join(parts)


def join_uz(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " va " + items[-1]


# ------------------------------------------------------------------ mahsulot nomlari
# Oddiy odamga tushunarli nomlar: (ekrandagi nom, ovozdagi nom)
FRIENDLY = {
    "bug'doy uni (1-nav)": ("Un (1-nav)", "birinchi nav un"),
    "bug'doy uni (oliy nav)": ("Un (oliy nav)", "oliy nav un"),
    "guruch (alanga)": ("Alanga guruch", "alanga guruch"),
    "guruch (lazer)": ("Lazer guruch", "lazer guruch"),
    "lahm (mol go'shti)": ("Mol go'shti (lahm)", "lahm mol go'shti"),
    "muzlatilgan go'sht (import)": ("Muzlatilgan go'sht", "muzlatilgan go'sht"),
    "qiyma (farsh)": ("Qiyma", "qiyma"),
    "sarpanja (mol go'shti)": ("Sarpanja", "sarpanja go'sht"),
    "qo'y go'shti (son qismi)": ("Qo'y go'shti", "qo'y go'shti"),
    "parranda go'shti (boldiri)": ("Tovuq boldiri", "tovuq boldiri"),
    "parranda go'shti (butun)": ("Butun tovuq", "butun tovuq"),
    "sabzi (sariq)": ("Sariq sabzi", "sariq sabzi"),
    "pomidor (qizil)": ("Pomidor", "pomidor"),
    "bodring (orzu)": ("Bodring", "bodring"),
}

# Tejashni ko'rsatish uchun odatiy xarid miqdori (toifa bo'yicha)
QTY = {"sabzavot": 3, "meva": 3, "go'sht": 2, "don": 5, "yog'": 2}

UNITS = {  # birlik: (ovozda "bir kilosi", "uch kilo olsangiz", ekranda)
    "kg": ("kilosi", "kilo", "kg"),
    "litr": ("litri", "litr", "litr"),
    "l": ("litri", "litr", "litr"),
    "dona": ("donasi", "dona", "dona"),
}


def names(product):
    key = apos(product["name"]).lower().strip()
    if key in FRIENDLY:
        return FRIENDLY[key]
    short = re.sub(r"\s*\(.*?\)\s*", " ", product["name"]).strip()
    return product["name"], short.lower()


def parse_unit(unit):
    m = re.match(r"\s*(\d+)?\s*([^\d\s]+)", unit or "")
    amount = int(m.group(1)) if m and m.group(1) else 1
    word = (m.group(2).lower() if m else "kg").rstrip(".")
    return amount, UNITS.get(word, UNITS["kg"])


def qty_for(category):
    c = apos(category).lower()
    return next((q for k, q in QTY.items() if k in c), 3)


# ------------------------------------------------------------------ tanlash
def spread(p):
    v = list(p["prices"].values())
    return max(v) / min(v) - 1


def pick(data, state):
    """Bu hafta hali ko'rsatilmagan, narx farqi eng katta mahsulot."""
    prods = data["products"]
    good = [p for p in prods if len(p["prices"]) >= 3 and spread(p) >= 0.04]
    if not good:
        good = [p for p in prods if len(p["prices"]) >= 2 and spread(p) > 0]
    good.sort(key=spread, reverse=True)
    used = state.get("used", []) if state.get("data_date") == data["date"] else []
    hist = state.get("history", [])
    last = hist[-1]["product"] if hist else None
    cands = [p for p in good if p["name"] not in used and p["name"] != last]
    if not cands:  # hafta mahsulotlari tugasa — qaytadan aylanadi
        cands = [p for p in good if p["name"] != last] or good
    return cands[0]


# ------------------------------------------------------------------ Claude
BANNED = ["savat", "narsa", "inflyatsiya", "indeks", "tahlil", "iste'mol", "dinamika"]

HOOKS = [
    "{N} qayerda arzon? Hozir ko'rsataman!",
    "{N} olishdan oldin buni ko'ring!",
    "{N} uchun ortiqcha pul to'lamang!",
    "{N}ni qayerdan olgan ma'qul? Qarang!",
    "Bir xil {n}, narxi esa har xil!",
]
OUTROS = [
    "Obuna bo'ling, har kuni arzonini topib beramiz!",
    "Foydali bo'lsa, yaqinlaringizga yuboring!",
    "Obuna bo'ling va pulingizni tejang!",
]
INTROS = [
    "{N} olmoqchimisiz? Avval narxlarni solishtiring 👇",
    "Bir xil {n} — har xil narx. Qayerda arzonligini ko'ring 👇",
    "{N} qayerda arzon? Bu haftaning narxlari 👇",
]

SYSTEM = """Sen "Arzoni qayerda?" Instagram sahifasi uchun qisqa reels matnlarini yozasan.
Tomoshabinlar oddiy odamlar: so'zlar juda sodda, kundalik, jonli bo'lsin.
Faqat o'zbek tilida, lotin yozuvida yoz. Faqat JSON qaytar, boshqa hech narsa yozma."""

PROMPT = """Mahsulot: {name}
Eng arzon do'kon: {cheap}. Eng qimmat do'kon: {dear}. Farq: taxminan {pct}%.

Quyidagi JSON ni yoz:
{{"hook": "...", "outro": "...", "caption_intro": "..."}}

Qoidalar:
- hook: videoning birinchi gapi, 4-10 so'z, diqqatni tortsin, mahsulot nomi ("{name_short}") albatta bo'lsin. Savol yoki qiziqtiruvchi gap.
- outro: oxirgi gap, 4-9 so'z, obuna bo'lishga yoki do'stlarga yuborishga chaqirsin.
- caption_intro: Instagram izohining birinchi 1-2 gapi, 160 belgidan oshmasin, 1-2 ta emoji mumkin.
- Hech qayerda raqam yozma (narxlarni videoning o'zi aytadi).
- Do'konlar sonini aytma.
- Bu so'zlarni ishlatma: savat, narsa (o'rniga "mahsulot"), inflyatsiya, indeks, tahlil, iste'mol.
- Ovozda o'qiladi: qisqa, ravon, oddiy gaplar."""


def _valid(text, max_words, max_chars=200, need=None):
    if not isinstance(text, str):
        return False
    t = apos(text).lower()
    words = t.split()
    return (
        2 <= len(words) <= max_words
        and len(text) <= max_chars
        and not re.search(r"\d", t)
        and not any(b in t for b in BANNED)
        and (need is None or need in t)
    )


def claude_lines(name_disp, name_voice, facts):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
    prompt = PROMPT.format(name=name_disp, name_short=name_voice, cheap=facts["cheap"],
                           dear=facts["dear"], pct=facts["pct"])
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 500, "system": SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
        out = json.loads(text)
    except Exception as e:  # noqa: BLE001
        print("Claude javobi ishlatilmadi:", e)
        return None
    need = apos(name_voice).lower().split()[0]
    ok = {
        "hook": _valid(out.get("hook"), 10, 90, need),
        "outro": _valid(out.get("outro"), 9, 70),
        "caption_intro": _valid(out.get("caption_intro"), 40, 180),
    }
    print("Claude matnlari:", out, "| tekshiruv:", ok)
    return {k: v.strip() for k, v in out.items() if ok.get(k)}


# ------------------------------------------------------------------ reja
def build(product, data, seed):
    rnd = random.Random(seed)
    disp, voice = names(product)
    amount, (u_of, u_qty, u_disp) = parse_unit(product["unit"])
    rows = sorted(product["prices"].items(), key=lambda kv: kv[1])
    lo, hi = rows[0][1], rows[-1][1]
    cheap = [s for s, v in rows if v == lo]
    dear = [s for s, v in rows if v == hi]
    diff = hi - lo
    pct = round((hi / lo - 1) * 100)
    qty = qty_for(product.get("category", ""))
    save = diff * qty
    unit_voice = f"{num_words(amount)} {u_of}"
    unit_label = f"{amount} {u_disp}"

    facts = {"cheap": join_uz(cheap), "dear": join_uz(dear), "pct": pct}
    llm = claude_lines(disp, voice, facts) or {}
    fill = {"N": voice.capitalize(), "n": voice}
    hook = llm.get("hook") or rnd.choice(HOOKS).format(**fill)
    outro = llm.get("outro") or rnd.choice(OUTROS)
    intro = llm.get("caption_intro") or rnd.choice(INTROS).format(**fill)

    lines = {
        "hook": (hook, hook),
        "cheap": (f"Eng arzoni — {join_uz(cheap)}da: {unit_voice} {num_words(lo)} so'm.",
                  f"Eng arzoni — {join_uz(cheap)}da: {fmt(lo)} so'm"),
        "dear": (f"Eng qimmati — {join_uz(dear)}da: {num_words(hi)} so'm.",
                 f"Eng qimmati — {join_uz(dear)}da: {fmt(hi)} so'm"),
        "diff": (f"Farqi — {num_words(diff)} so'm!", f"Farqi — {fmt(diff)} so'm!"),
        "save": (f"{num_words(qty).capitalize()} {u_qty} olsangiz, {num_words(save)} so'm tejaysiz!",
                 f"{qty} {u_disp} olsangiz — {fmt(save)} so'm tejaysiz!"),
        "outro": (outro, outro),
    }

    tag = re.sub(r"[^a-z]", "", apos(voice).lower().replace(" ", ""))
    price_lines = []
    for s, v in rows:
        mark = "✅" if v == lo else ("❌" if v == hi else "▫️")
        price_lines.append(uz(f"{mark} {s} — {fmt(v)} so'm"))
    caption = "\n".join([
        uz(intro), "",
        f"📍 {uz(disp)} ({unit_label}) — {data['date']} narxlari:",
        *price_lines, "",
        uz(f"Farq: {fmt(diff)} so'm ({pct}%). {qty} {u_disp} olsangiz — {fmt(save)} so'm tejaysiz."),
        uz("Manba: narxtahlil.uz (O'zbekiston Respublikasi Markaziy banki)"), "",
        f"#arzoniqayerda #narxlar #supermarket #tejash #oziqovqat #{tag}",
    ])

    return {
        "product": product["name"],
        "display_name": disp,
        "unit_label": unit_label,
        "date": data["date"],
        "rows": [(s, v, "cheap" if v == lo else ("dear" if v == hi else "")) for s, v in rows],
        "diff": diff, "pct": pct, "qty": qty, "qty_unit": u_disp, "save": save,
        "cheap": cheap, "dear": dear,
        "lines": lines,
        "caption": caption,
        "llm": bool(llm),
    }
