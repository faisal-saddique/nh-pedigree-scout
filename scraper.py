"""
Scraper for Tattersalls and Goffs NH sale catalogues.

Goffs: all lot data is in data-* attributes on the main catalogue page (SSR).
       Cloudflare bypass — two backends, switchable via .env:
         SCRAPER_BACKEND=scrapedo  (default) — requires SCRAPEDO_TOKEN
         SCRAPER_BACKEND=nodriver  — opens real Chrome briefly, no token needed

Tattersalls (.com and .ie): 4DCGI backend with session cookies.
       Two-step fetch: seed session → fetch resultframe lot data.
       No Scrape.do needed — standard HTTP with cookie handling.
       Supports tattersalls.com (UK flat) and tattersalls.ie (Irish NH/store).
"""

import asyncio
import os
import re
import httpx
from bs4 import BeautifulSoup
from scorer import detect_discipline, score_lot_for_discipline

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-GB,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_YEAR_RE = re.compile(r"\b(20[012]\d|199\d)\b")
_COLOR_SEX_RE = re.compile(r"\b[A-Za-z]{1,3}\.(G|F|C|M|R|H)\b")
_T_SEX_MAP = {"G": "Gelding", "F": "Filly", "C": "Colt", "M": "Mare", "R": "Rig", "H": "Horse"}
_G_SEX_MAP = {"G": "Gelding", "F": "Filly", "C": "Colt", "M": "Mare", "R": "Rig", "S": "Stallion"}
# Sale code → data URL: insert space before last 2 digits (the year)
_SALE_CODE_RE = re.compile(r"/4DCGI/Sale/([A-Z0-9]+)/", re.IGNORECASE)


def _fetch(url: str, scrapedo_token: str | None = None, render: bool = False) -> str:
    if scrapedo_token:
        params: dict = {"token": scrapedo_token, "url": url}
        if render:
            params["render"] = "true"
        resp = httpx.get("https://api.scrape.do", params=params, timeout=60, follow_redirects=True)
    else:
        resp = httpx.get(url, headers=_HEADERS, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _fetch_goffs_nodriver(url: str) -> str:
    """Bypass Cloudflare using real Chrome via nodriver. Opens a visible browser briefly."""
    import nodriver as uc  # lazy import — only needed when SCRAPER_BACKEND=nodriver

    async def _run() -> str:
        browser = await uc.start(headless=False)
        page = await browser.get(url)
        for _ in range(15):
            await asyncio.sleep(1)
            content = await page.get_content()
            if "data-lotnumber" in content:
                break
        else:
            content = await page.get_content()
        try:
            await browser.stop()
        except Exception:
            pass
        return content

    return uc.loop().run_until_complete(_run())


def fetch_lot_pdf_text(lot_url: str, scrapedo_token: str | None = None) -> tuple[str | None, str | None]:
    """
    Fetch a Goffs individual lot page, extract the pedigree PDF URL and return
    the PDF text (via Filestack CDN — free, no Scrape.do credit needed for PDF).

    Returns (pdf_url, pdf_text). Both None on failure.
    Uses 1 Scrape.do credit for the lot page HTML fetch.
    """
    from pdf_parser import filestack_txt_url, fetch_pdf_text
    try:
        html = _fetch(lot_url, scrapedo_token)
    except Exception:
        return None, None

    txt_url = filestack_txt_url(html)
    if not txt_url:
        return None, None

    # Extract raw PDF URL from the Filestack URL
    import re
    pdf_url_m = re.search(r'(https://media\.goffs\.com/[^\s"\']+\.pdf)', txt_url)
    pdf_url = pdf_url_m.group(1) if pdf_url_m else txt_url

    text = fetch_pdf_text(txt_url)
    return pdf_url, text


def _parse_catalogueUpdates(html: str) -> str | None:
    """Extract all Catalogue Updates text from a Tattersalls Entry/Lot page."""
    soup = BeautifulSoup(html, "lxml")
    updates = soup.find_all("div", class_="catalogueUpdate")
    if not updates:
        return None
    parts = []
    for div in updates:
        date_span = div.find("span", class_="catalogueUpdateDate")
        if date_span:
            date_span.decompose()
        text = div.get_text(" ", strip=True).strip()
        if text:
            parts.append(text)
    return " | ".join(parts) if parts else None


def fetch_hit_entry_form(tld: str, sale_code: str, lot_number: str) -> str | None:
    """
    Fetch /4DCGI/Entry/Lot/{sale_code}/{lot_number} and extract all Catalogue
    Updates text: form summary, wins, BHA rating, recent run.
    Requires 4D session cookie — seeds session via shell page first.
    Returns concatenated text or None if no updates found.
    """
    base = f"https://secure.tattersalls.{tld}"
    shell_url = f"{base}/4DCGI/Sale/{sale_code}/Main/Lots"
    entry_url = f"{base}/4DCGI/Entry/Lot/{sale_code}/{lot_number}"
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as client:
            client.get(shell_url)
            r = client.get(entry_url)
            r.raise_for_status()
        return _parse_catalogueUpdates(r.text)
    except Exception:
        return None


def fetch_hit_form_batch(
    tld: str, sale_code: str, lots: list[dict], max_workers: int = 8
) -> dict[int, str]:
    """
    Parallel-fetch Catalogue Updates for all HIT lots.
    Returns {lot_id: form_notes} for lots that have catalogue updates.
    Each thread seeds its own 4D session.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[int, str] = {}

    def _fetch_one(lot: dict) -> tuple[int, str | None]:
        return lot["id"], fetch_hit_entry_form(tld, sale_code, lot["lot_number"])

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, lot): lot for lot in lots}
        for future in as_completed(futures):
            lot_id, form = future.result()
            if form:
                results[lot_id] = form

    return results


def detect_site(url: str) -> str:
    if "tattersalls.com" in url or "tattersalls.ie" in url:
        return "tattersalls"
    if "goffs.com" in url:
        return "goffs"
    raise ValueError(f"Unsupported catalogue URL: {url}")


def scrape_catalogue(url: str) -> tuple[str, list[dict]]:
    """Return (sale_name, lots). Dispatches to the correct site scraper."""
    site = detect_site(url)
    token = os.getenv("SCRAPEDO_TOKEN")
    if site == "tattersalls":
        return scrape_tattersalls(url)
    return scrape_goffs(url, token)


# ---------------------------------------------------------------------------
# Goffs — single page, data-* attributes, no JS rendering needed
# ---------------------------------------------------------------------------

def scrape_goffs(url: str, scrapedo_token: str | None = None) -> tuple[str, list[dict]]:
    """
    All lot data lives in data-* attributes on either:
      - <a class="lot-table__lot">  (main Goffs sales — Arkle, Summer, etc.)
      - <a class="goffs-365-catalogue__card">  (GoffsGo online sales)
    Backend chosen via SCRAPER_BACKEND env var (scrapedo|nodriver).
    """
    backend = os.getenv("SCRAPER_BACKEND", "scrapedo").lower()
    if backend == "nodriver":
        html = _fetch_goffs_nodriver(url)
    else:
        html = _fetch(url, scrapedo_token)
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.select_one("title")
    sale_name = title_tag.get_text(strip=True) if title_tag else "Goffs Sale"

    # Determine currency from URL region
    if "/sale/IRE/" in url:
        currency = "EUR"
    else:
        currency = "GBP"  # UK and GoffsGo sales priced in GBP

    lot_tags = soup.select("a.lot-table__lot")
    if lot_tags:
        lots = [l for tag in lot_tags if (l := _parse_goffs_data_attrs(tag, currency))]
    else:
        # GoffsGo format
        card_tags = soup.select("a.goffs-365-catalogue__card")
        lots = [l for tag in card_tags if (l := _parse_goffs365_card(tag, currency))]

    return sale_name, lots


def _parse_goffs_data_attrs(tag, currency: str = "EUR") -> dict | None:
    lot_number = tag.get("data-lotnumber", "").strip()
    if not lot_number:
        return None

    withdrawn = tag.get("data-withdrawn", "false").lower() == "true"
    if withdrawn:
        return None

    sire = tag.get("data-sirename") or None
    dam = tag.get("data-damname") or None
    dam_sire = tag.get("data-damsire") or None

    sex_code = tag.get("data-sex", "").strip().upper()
    sex = _G_SEX_MAP.get(sex_code)

    yob_raw = tag.get("data-yearofbirth", "").strip()
    year_of_birth = int(yob_raw) if yob_raw.isdigit() else None

    discipline = detect_discipline(sire)
    pedigree_score = score_lot_for_discipline(sire, dam_sire, None, discipline)

    # Price / outcome (populated on completed/live sales)
    price_raw = tag.get("data-price", "").strip()
    price = int(price_raw) if price_raw and price_raw.isdigit() and int(price_raw) > 0 else None

    sold = tag.get("data-sold", "false").lower() == "true"
    notsold = tag.get("data-notsold", "false").lower() == "true"
    vendorsale = tag.get("data-vendorsale", "false").lower() == "true"
    purchaser = tag.get("data-purchaser") or None

    if vendorsale:
        outcome = "vendor_sale"
    elif notsold:
        outcome = "not_sold"
    elif sold:
        outcome = "sold"
    else:
        outcome = None  # upcoming / not yet offered

    return {
        "lot_number": lot_number,
        "horse_name": tag.get("data-lotname") or None,
        "year_of_birth": year_of_birth,
        "sex": sex,
        "sire": sire,
        "dam": dam,
        "dam_sire": dam_sire,
        "second_dam_sire": None,
        "discipline": discipline,
        "pedigree_score": pedigree_score,
        "price": price,
        "currency": currency,
        "outcome": outcome,
        "purchaser": purchaser,
    }


def _parse_goffs365_card(tag, currency: str = "GBP") -> dict | None:
    """Parse a GoffsGo <a class='goffs-365-catalogue__card'> element."""
    lot_number = tag.get("data-lotnumber", "").strip()
    if not lot_number:
        return None

    withdrawn = tag.get("data-iswithdrawn", "false").lower() == "true"
    if withdrawn:
        return None

    sire = tag.get("data-sirename") or None
    dam = tag.get("data-damname") or None
    dam_sire = tag.get("data-damsire") or None

    sex_code = tag.get("data-sex", "").strip().upper()
    sex = _G_SEX_MAP.get(sex_code)

    yob_raw = tag.get("data-yearofbirth", "").strip()
    year_of_birth = int(yob_raw) if yob_raw.isdigit() else None

    discipline = detect_discipline(sire)
    pedigree_score = score_lot_for_discipline(sire, dam_sire, None, discipline)

    price_raw = tag.get("data-price", "").strip()
    price = int(price_raw) if price_raw and price_raw.isdigit() and int(price_raw) > 0 else None

    vendor = tag.get("data-isvendorsale", "false").lower() == "true"
    reserve_met = tag.get("data-isreservemet", "false").lower() == "true"
    auction_state = tag.get("data-auctionstate", "").lower()
    purchaser = tag.get("data-purchaser") or None

    if vendor:
        outcome = "vendor_sale"
    elif auction_state == "closed" and not reserve_met:
        outcome = "not_sold"
    elif reserve_met:
        outcome = "sold"
    else:
        outcome = None

    return {
        "lot_number": lot_number,
        "horse_name": tag.get("data-lotname") or None,
        "year_of_birth": year_of_birth,
        "sex": sex,
        "sire": sire,
        "dam": dam,
        "dam_sire": dam_sire,
        "second_dam_sire": None,
        "discipline": discipline,
        "pedigree_score": pedigree_score,
        "price": price,
        "currency": currency,
        "outcome": outcome,
        "purchaser": purchaser,
    }


# ---------------------------------------------------------------------------
# Tattersalls — 4DCGI two-step session, resultframe lot table
# ---------------------------------------------------------------------------

def scrape_tattersalls(url: str, _currency: str | None = None) -> tuple[str, list[dict]]:
    """
    Works for tattersalls.com and tattersalls.ie.

    URL structure Craig pastes:
      https://www.tattersalls.ie/sales/{slug}/4DCGI/Sale/{CODE}/Main/...

    Steps:
      1. Extract sale code and TLD from URL
      2. Seed session cookie via shell page (4D requires this)
      3. Fetch resultframe data page: /4DCGI/Sale/{CODE_WITH_SPACE}
      4. Parse lot rows (two formats: named-horse BY/EX, or sire/dam)
    """
    tld = "ie" if "tattersalls.ie" in url else "com"
    currency = _currency or ("EUR" if tld == "ie" else "GBP")
    secure_base = f"https://secure.tattersalls.{tld}"

    m = _SALE_CODE_RE.search(url)
    if not m:
        raise ValueError(f"Cannot extract sale code from URL: {url}")
    sale_code = m.group(1).upper()

    # Insert space before last 2-digit year: DBY25 → DBY 25, P2P26 → P2P 26
    data_code = re.sub(r"(\d{2})$", r" \1", sale_code)
    shell_url = f"{secure_base}/4DCGI/Sale/{sale_code}/Main/Lots"
    data_url = f"{secure_base}/4DCGI/Sale/{data_code.replace(' ', '%20')}"

    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30) as client:
        client.get(shell_url)       # first request seeds the session cookie
        shell_r = client.get(shell_url)
        data_r = client.get(data_url)

    # Sale name from shell page heading
    shell_soup = BeautifulSoup(shell_r.text, "lxml")
    heading = shell_soup.select_one(".sale-header__heading, h1, h2")
    sale_name = heading.get_text(strip=True) if heading else f"Tattersalls {sale_code}"

    # Parse lots from resultframe data
    soup = BeautifulSoup(data_r.text, "lxml")
    lot_table = next(
        (t for t in soup.find_all("table") if t.find(class_="lot")),
        None,
    )
    if not lot_table:
        return sale_name, []

    # Infer fallback YOB from sale code year (e.g. SOM25 → 2025 → yearlings born 2024)
    year_digits = re.search(r"(\d{2})$", sale_code)
    fallback_yob = (2000 + int(year_digits.group(1)) - 1) if year_digits else None

    lots = []
    for row in lot_table.find_all("tr"):
        lot = _parse_tattersalls_row(row, fallback_yob, currency)
        if lot:
            lots.append(lot)
    return sale_name, lots


def _parse_tattersalls_row(row, fallback_yob: int | None = None, currency: str = "EUR") -> dict | None:
    lot_td = row.find("td", class_="lot")
    if not lot_td:
        return None

    lot_link = lot_td.find("a", class_="ll")
    if not lot_link:
        return None
    lot_number = lot_link.get_text(strip=True)
    if not lot_number:
        return None
    # Draft catalogues show "Draft" as display text but have unique ID in onclick
    # e.g. goToLot("P2P26","Draft.Z48") — use that as stable lot identifier
    if lot_number == "Draft":
        onclick = lot_link.get("onclick", "")
        m = re.search(r'goToLot\("[^"]+",\s*"([^"]+)"\)', onclick)
        if m:
            lot_number = m.group(1)

    tdh = row.find("td", class_="tdh")
    if not tdh:
        return None

    hn_tags = tdh.find_all("a", class_="hn")

    if len(hn_tags) >= 2:
        # Store/yearling format: first hn = sire, second hn = dam
        sire = hn_tags[0].get_text(strip=True) or None
        dam = hn_tags[1].get_text(strip=True) or None
        horse_name = None
    elif len(hn_tags) == 1:
        # Named-horse format (P2P/HIT): hn = horse name, BY/EX spans = sire/dam
        horse_name = hn_tags[0].get_text(strip=True) or None
        sire = None
        dam = None
        for span in tdh.find_all("span", class_="keepTogether"):
            small = span.find("span", class_="small")
            if not small:
                continue
            label = small.get_text(strip=True).upper()
            # Text value = span text minus the BY/EX label
            val = span.get_text(" ", strip=True)
            val = val[len(small.get_text(strip=True)):].strip()
            if label == "BY":
                sire = val or None
            elif label == "EX":
                dam = val or None
    else:
        return None

    tdh_text = tdh.get_text(" ", strip=True)

    year_m = _YEAR_RE.search(tdh_text)
    year_of_birth = int(year_m.group(1)) if year_m else fallback_yob

    sex_m = _COLOR_SEX_RE.search(tdh_text)
    sex = _T_SEX_MAP.get(sex_m.group(1)) if sex_m else None

    # Lot type (HIT / HOT / P2P etc.) from <span class="ht"> inside tdh
    ht_span = tdh.find("span", class_="ht")
    lot_type = ht_span.get_text(strip=True) if ht_span else None

    # Trainer — 4th td (index 3) in named-horse rows; absent in yearling/store rows
    all_tds = row.find_all("td")
    trainer = None
    if len(hn_tags) == 1 and len(all_tds) >= 4:
        # col2type td may or may not be present; find trainer by position after lot+tdh+type
        # Columns: lot(0) | tdh(1) | col2type(2) | trainer(3) | vendor/buyer(4) | price(5)
        trainer_td = all_tds[3] if len(all_tds) > 3 else None
        if trainer_td and trainer_td.get("class", []) not in [["lot"], ["price"]]:
            trainer = trainer_td.get_text(strip=True) or None

    # Price and outcome — only present on completed sales (td class="price" exists)
    price = None
    outcome = None
    purchaser = None
    price_td = row.find("td", class_="price")
    if price_td:
        price_text = price_td.get_text(strip=True).replace(",", "").replace(".", "")
        price = int(price_text) if price_text.isdigit() else None
        price_idx = all_tds.index(price_td)
        if price_idx >= 1:
            purchaser_text = all_tds[price_idx - 1].get_text(strip=True)
            if "Withdrawn" in purchaser_text:
                outcome = "withdrawn"
            elif "Not Sold" in purchaser_text:
                outcome = "not_sold"
            elif purchaser_text.lower() == "vendor":
                outcome = "vendor_sale"
            else:
                outcome = "sold"
                purchaser = purchaser_text or None

    discipline = detect_discipline(sire)
    return {
        "lot_number": lot_number,
        "horse_name": horse_name,
        "year_of_birth": year_of_birth,
        "sex": sex,
        "sire": sire,
        "dam": dam,
        "dam_sire": None,
        "second_dam_sire": None,
        "discipline": discipline,
        "pedigree_score": score_lot_for_discipline(sire, None, None, discipline),
        "lot_type": lot_type,
        "trainer": trainer,
        "price": price,
        "currency": currency,
        "outcome": outcome,
        "purchaser": purchaser,
    }
