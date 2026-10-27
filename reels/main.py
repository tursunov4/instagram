"""Kunlik "Arzoni qayerda?" reels: narx -> matn -> ovoz -> video -> Instagram.

Ishlatish:
  python reels/main.py              # to'liq: yasaydi va joylaydi
  python reels/main.py --dry-run    # faqat video yasaydi (out/ papkaga)
  python reels/main.py --no-tts --offline --dry-run   # internetsiz sinov
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audio  # noqa: E402
import content  # noqa: E402
import render  # noqa: E402
import scrape  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))


def load_state():
    p = DATA / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"history": []}


def save_state(state):
    state["history"] = state["history"][-120:]
    (DATA / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="joylamasdan faqat video yasash")
    ap.add_argument("--force", action="store_true", help="bugun chiqqan bo'lsa ham qayta yasash")
    ap.add_argument("--offline", action="store_true", help="saytga kirmasdan keshdagi narxlar")
    ap.add_argument("--no-tts", action="store_true", help="ovozsiz (sinov uchun)")
    ap.add_argument("--product", help="aniq mahsulot nomi (sinov uchun)")
    ap.add_argument("--out", default=str(ROOT / "out"))
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    state = load_state()
    if not a.force and not a.dry_run and any(h["date"] == today for h in state["history"]):
        print("Bugungi video allaqachon chiqqan — o'tkazib yuborildi.")
        return

    # 1) narxlar
    if a.offline:
        data, src = json.loads((DATA / "latest.json").read_text(encoding="utf-8")), "cache"
    else:
        data, src = scrape.get_prices(DATA / "latest.json", debug_dir=out)
    print(f"Narxlar: {data['date']} ({src}), {len(data['products'])} ta mahsulot")

    # 2) mahsulot va matnlar
    if a.product:
        product = next(p for p in data["products"] if a.product.lower() in p["name"].lower())
    else:
        product = content.pick(data, state)
    plan = content.build(product, data, seed=today)
    print("Bugungi mahsulot:", plan["product"], "| Claude:", plan["llm"])
    for k, (v, _) in plan["lines"].items():
        print(f"  {k:6s} {content.uz(v)}")

    # 3) ovoz
    voice = os.environ.get("TTS_VOICE", "uz-UZ-MadinaNeural")
    rate = os.environ.get("TTS_RATE", "+6%")
    sigs, durs, tts_used = {}, {}, None
    for k, (v, _) in plan["lines"].items():
        if a.no_tts:
            durs[k] = 0.9 + len(v) / 15.0
            continue
        try:
            mp3 = out / f"v_{k}.mp3"
            tts_used = audio.tts(content.uz(v), str(mp3), voice, rate)
            sigs[k] = audio.load(str(mp3))
            durs[k] = len(sigs[k]) / audio.SR
        except Exception as e:  # noqa: BLE001
            print(f"OGOHLANTIRISH: ovoz yaratilmadi ({k}): {e}")
            durs[k] = 0.9 + len(v) / 15.0
    print("Ovoz xizmati:", tts_used or "yo'q (faqat musiqa)")

    # 4) video
    scenes, vstart, T = render.timeline(durs)
    subs = render.subtitles(plan, vstart, durs)
    wav = out / "mix.wav"
    audio.mix(T, [(vstart[k], s) for k, s in sigs.items()], render.sfx_events(scenes, plan), str(wav))
    mp4, cover = out / f"reel_{today}.mp4", out / f"cover_{today}.jpg"
    render.render(plan, scenes, subs, T, wav, mp4, cover)
    (out / "caption.txt").write_text(plan["caption"], encoding="utf-8")
    print(f"Video tayyor: {mp4} ({T:.1f} s, {mp4.stat().st_size / 1e6:.1f} MB)")

    backend = os.environ.get("PUBLISHER", "instagram")
    need = "METRICOOL_TOKEN" if backend == "metricool" else "IG_ACCESS_TOKEN"
    if not a.dry_run and not os.environ.get(need):
        print(f"{need} hali kiritilmagan — video yasaldi, lekin Instagram'ga chiqarilmadi.")
        a.dry_run = True
    if a.dry_run:
        print("Sinov rejimi: joylanmadi.\n\n" + plan["caption"])
        return

    # 5) joylash
    import publish

    sha = publish.push_media([mp4, cover])
    url = publish.public_url(sha, mp4.name)
    publish.wait_public(url)
    if backend == "metricool":
        media_id = publish.metricool_publish(url, plan["caption"])
    else:
        media_id = publish.instagram_publish(url, plan["caption"])
        publish.refresh_instagram_token()

    # 6) holatni saqlash
    if state.get("data_date") != data["date"]:
        state["data_date"], state["used"] = data["date"], []
    state["used"].append(plan["product"])
    state["history"].append({"date": today, "product": plan["product"], "data_date": data["date"],
                             "media_id": media_id, "voice": tts_used})
    save_state(state)
    print("Tayyor ✔")


if __name__ == "__main__":
    main()
