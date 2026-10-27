"""narxtahlil.uz/supermarkets/ sahifasidan supermarket narxlarini olish.

Avval oddiy so'rov bilan urinadi; jadval topilmasa (sahifa JavaScript bilan
chizilsa) Chromium orqali ochadi. Ikkalasi ham ishlamasa, oxirgi muvaffaqiyatli
ma'lumot (data/latest.json) ishlatiladi, shunda video baribir chiqadi.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.narxtahlil.uz/supermarkets/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "uz,ru;q=0.8,en;q=0.6",
}
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b")
NUM_RE = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+")


def _price(text):
    text = text.strip()
    if not text or text in "—–-":
        return None
    m = NUM_RE.search(text)
    if not m:
        return None
    value = int(re.sub(r"\D", "", m.group(0)))
    return value if value > 0 else None


def _latest_date(soup):
    dates = []
    for m in DATE_RE.finditer(soup.get_text(" ")):
        try:
            dates.append(datetime(int(m[3]), int(m[2]), int(m[1])))
        except ValueError:
            pass
    return max(dates).strftime("%d.%m.%Y") if dates else None


def parse_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        head = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if not head or not head[0].lower().startswith("mahsulot"):
            continue
        i_unit = next((i for i, h in enumerate(head) if h.lower().startswith("birlik")), 1)
        i_end = next((i for i, h in enumerate(head) if h.lower().startswith("farq")), len(head))
        # "Baraka 3 4" -> "Baraka" (oxiridagi hisoblagich raqamlarni olib tashlaymiz)
        stores = [re.sub(r"[\d\s]+$", "", h).strip() for h in head[i_unit + 1:i_end]]
        products = []
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < i_end:
                continue
            lines = [x.strip() for x in cells[0].get_text("\n").split("\n") if x.strip()]
            if not lines:
                continue
            prices = {}
            for store, cell in zip(stores, cells[i_unit + 1:i_end]):
                p = _price(cell.get_text(" ", strip=True))
                if p:
                    prices[store] = p
            if prices:
                products.append({
                    "name": lines[0],
                    "category": lines[-1] if len(lines) > 1 else "",
                    "unit": cells[i_unit].get_text(" ", strip=True) or "1 kg",
                    "prices": prices,
                })
        if products:
            return {"date": _latest_date(soup), "stores": stores, "products": products}
    return None


def _fetch_plain():
    r = requests.get(URL, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r.text


def _fetch_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
        from playwright.sync_api import sync_playwright
    subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                   check=True, capture_output=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="uz-UZ", user_agent=HEADERS["User-Agent"])
        page.goto(URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_selector("table tr td", timeout=60_000)
        html = page.content()
        browser.close()
        return html


def get_prices(cache_path, debug_dir=None):
    """(ma'lumot, manba) qaytaradi: manba = 'live' yoki 'cache'."""
    cache_path = Path(cache_path)
    errors = []
    for fetch in (_fetch_plain, _fetch_browser):
        html = None
        try:
            html = fetch()
            data = parse_html(html)
            if data and len(data["products"]) >= 5:
                if not data["date"]:
                    data["date"] = datetime.now().strftime("%d.%m.%Y")
                cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                return data, "live"
            errors.append(f"{fetch.__name__}: narx jadvali topilmadi")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fetch.__name__}: {e}")
        if html and debug_dir:
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            (Path(debug_dir) / f"page{fetch.__name__}.html").write_text(html, encoding="utf-8")
    print("OGOHLANTIRISH: saytdan o'qib bo'lmadi ->", " | ".join(errors))
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8")), "cache"
    raise RuntimeError("Narxlar olinmadi va keshda ham yo'q: " + " | ".join(errors))
