"""Videoni ochiq havolaga joylash va Instagram'ga chiqarish.

Video GitHub'dagi alohida `media` tarmog'iga (faqat bugungi fayl, tarix saqlanmaydi)
yuklanadi va jsDelivr CDN orqali ochiq havola olinadi. Keyin:
  PUBLISHER=instagram -> Instagram API (bepul, Meta tokeni kerak)
  PUBLISHER=metricool -> Metricool API (faqat Advanced/Custom tarif)
"""
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copy2
from zoneinfo import ZoneInfo

import requests


def _run(cmd, cwd=None, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def push_media(files, branch="media"):
    """Fayllarni `media` tarmog'iga yangi (tarixsiz) commit qilib yuboradi -> commit SHA."""
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    with tempfile.TemporaryDirectory() as d:
        _run(["git", "init", "-q", "-b", branch], d)
        _run(["git", "config", "user.name", "arzoni-bot"], d)
        _run(["git", "config", "user.email", "arzoni-bot@users.noreply.github.com"], d)
        for f in files:
            copy2(f, Path(d) / Path(f).name)
        _run(["git", "add", "."], d)
        _run(["git", "commit", "-q", "-m", f"media {datetime.now(timezone.utc):%Y-%m-%d}"], d)
        _run(["git", "push", "-q", "--force",
              f"https://x-access-token:{token}@github.com/{repo}.git", f"{branch}:{branch}"], d)
        return _run(["git", "rev-parse", "HEAD"], d)


def public_url(sha, name):
    repo = os.environ["GITHUB_REPOSITORY"]
    if os.environ.get("MEDIA_HOST", "jsdelivr") == "raw":
        return f"https://raw.githubusercontent.com/{repo}/{sha}/{name}"
    return f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{name}"


def wait_public(url, tries=24):
    for i in range(tries):
        try:
            r = requests.head(url, timeout=30, allow_redirects=True)
            if r.status_code == 200 and int(r.headers.get("content-length", "1")) > 0:
                print("Ochiq havola tayyor:", url, r.headers.get("content-type"))
                return
        except requests.RequestException:
            pass
        time.sleep(10)
    raise RuntimeError(f"Video havolasi ochilmadi: {url}")


# ------------------------------------------------------------------ Instagram API
def _ig(method, path, **params):
    ver = os.environ.get("IG_API_VERSION", "v23.0")
    r = requests.request(method, f"https://graph.instagram.com/{ver}/{path}", params=params, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram API xatosi ({path}): {r.text[:500]}")
    return r.json()


def instagram_publish(video_url, caption, thumb_ms=1400):
    tok = os.environ["IG_ACCESS_TOKEN"]
    uid = _ig("GET", "me", fields="user_id,username", access_token=tok)
    user_id = uid.get("user_id") or uid["id"]
    print("Instagram akkaunt:", uid.get("username"))
    c = _ig("POST", f"{user_id}/media", media_type="REELS", video_url=video_url, caption=caption,
            share_to_feed="true", thumb_offset=str(thumb_ms), access_token=tok)
    cid = c["id"]
    for _ in range(60):  # 10 daqiqagacha kutamiz
        st = _ig("GET", cid, fields="status_code,status", access_token=tok)
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram videoni qabul qilmadi: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram videoni 10 daqiqada qayta ishlab bo'lmadi")
    res = _ig("POST", f"{user_id}/media_publish", creation_id=cid, access_token=tok)
    print("Instagram'ga chiqdi, media id:", res["id"])
    return res["id"]


def refresh_instagram_token():
    """Token 60 kun yashaydi: har gal yangilab, GitHub secret'ga qayta yozib qo'yamiz."""
    tok = os.environ.get("IG_ACCESS_TOKEN")
    pat = os.environ.get("GH_PAT")
    if not tok:
        return
    try:
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": tok}, timeout=60)
        r.raise_for_status()
        new = r.json()["access_token"]
        print(f"::add-mask::{new}")
        days = r.json().get("expires_in", 0) // 86400
        print(f"Instagram token yangilandi ({days} kun amal qiladi)")
    except Exception as e:  # noqa: BLE001
        print("OGOHLANTIRISH: token yangilanmadi:", str(e).replace(tok, "***")[:300])
        return
    if not pat:
        print("OGOHLANTIRISH: GH_PAT yo'q — yangi token saqlanmadi, 60 kundan keyin qo'lda yangilash kerak")
        return
    env = dict(os.environ, GH_TOKEN=pat)
    subprocess.run(["gh", "secret", "set", "IG_ACCESS_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"],
                    "--body", new], env=env, check=True, capture_output=True)
    print("Yangi token GitHub secret'ga yozildi")


# ------------------------------------------------------------------ Metricool API
def metricool_publish(video_url, caption):
    base = "https://app.metricool.com/api"
    params = {"userId": os.environ["METRICOOL_USER_ID"], "blogId": os.environ["METRICOOL_BLOG_ID"]}
    headers = {"X-Mc-Auth": os.environ["METRICOOL_TOKEN"], "Content-Type": "application/json"}
    media = video_url
    try:
        r = requests.get(f"{base}/actions/normalize/image/url", params=dict(params, url=video_url),
                         headers=headers, timeout=120)
        if r.ok:
            body = r.json() if "json" in r.headers.get("content-type", "") else r.text
            if isinstance(body, str) and body.startswith("http"):
                media = body.strip('"')
    except Exception as e:  # noqa: BLE001
        print("Metricool normalize ishlamadi, asl havola ishlatiladi:", e)
    tz = os.environ.get("TIMEZONE", "Asia/Tashkent")
    when = datetime.now(ZoneInfo(tz)) + timedelta(minutes=10)
    post = {
        "publicationDate": {"dateTime": when.strftime("%Y-%m-%dT%H:%M:%S"), "timezone": tz},
        "text": caption,
        "providers": [{"network": "instagram"}],
        "instagramData": {"type": "REEL", "showReelOnFeed": True},
        "media": [media],
        "autoPublish": True, "draft": False, "shortener": False,
        "saveExternalMediaFiles": True,
    }
    r = requests.post(f"{base}/v2/scheduler/posts", params=params, headers=headers, json=post, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"Metricool API xatosi: {r.status_code} {r.text[:500]}")
    print("Metricool'ga rejalashtirildi:", when.strftime("%H:%M"))
    try:
        return str(r.json()["data"]["id"])
    except Exception:  # noqa: BLE001
        return "metricool"
