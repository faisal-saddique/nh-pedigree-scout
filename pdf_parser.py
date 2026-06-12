"""
Parse pedigree PDF text (extracted via Filestack CDN) into structured dam records.

Filestack txt endpoint: https://cdn.filestackcontent.com/{KEY}/output=format:txt/{PDF_URL}
This gives clean UTF-8 text from Goffs and Tattersalls pedigree PDFs.

Each lot PDF contains sections: 1st dam / 2nd dam / 3rd dam / 4th dam.
Each section has: dam's own race record + production stats (foals / runners / winners).
"""
import re
import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# --- URL helpers ---

_PEDIGREE_IMG_RE = re.compile(
    r'id="PedigreeImage"\s+src="(https://cdn\.filestackcontent\.com/[^"]+)"'
)
_FILESTACK_KEY_RE = re.compile(r"https://cdn\.filestackcontent\.com/([^/]+)/")


def filestack_txt_url(lot_html: str) -> str | None:
    """Extract pedigree image URL from lot page HTML and switch to txt format."""
    m = _PEDIGREE_IMG_RE.search(lot_html)
    if not m:
        return None
    img_url = m.group(1)
    # Filestack URL: https://cdn.filestackcontent.com/KEY/TRANSFORMS/PDF_URL
    # Find where the embedded PDF URL begins
    pdf_start = img_url.find("https://media.goffs.com/")
    if pdf_start < 0:
        return None
    pdf_url = img_url[pdf_start:]
    key_m = _FILESTACK_KEY_RE.match(img_url)
    if not key_m:
        return None
    base = f"https://cdn.filestackcontent.com/{key_m.group(1)}/"
    return f"{base}output=format:txt/{pdf_url}"


def fetch_pdf_text(txt_url: str) -> str | None:
    """Fetch plaintext from a Filestack txt conversion URL. No auth needed."""
    try:
        r = httpx.get(txt_url, headers=_HEADERS, timeout=30, follow_redirects=True)
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception:
        pass
    return None


# --- Parser ---

_DAM_SPLIT = re.compile(r'\n(1st|2nd|3rd|4th) dam\n+', re.IGNORECASE)
_PROD_RE = re.compile(
    r'dam of (\d+) foals?'
    r'(?:;\s*(\d+) runners?)?'
    r'(?:;\s*(\d+) winners?)?',
    re.IGNORECASE,
)
_WINS_RE = re.compile(r'(\d+)\s+wins?', re.IGNORECASE)
_PRIZE_RE = re.compile(r'£([\d,]+)')
_GR_RE = {
    "gr1": re.compile(r'Gr\.1'),
    "gr2": re.compile(r'Gr\.2'),
    "gr3": re.compile(r'Gr\.3'),
    "listed": re.compile(r',\s*L\.'),
}


def parse_pedigree_pdf_text(text: str) -> dict[int, dict]:
    """
    Parse Goffs pedigree PDF text into dam records keyed by dam number (1-4).

    Each dam dict contains:
      name, unraced, own_wins, gr1, gr2, gr3, listed, prize_money,
      foals, runners, winners, winners_pct, raw_text
    """
    results: dict[int, dict] = {}
    parts = _DAM_SPLIT.split(text)
    # parts = [pre, '1st', section1, '2nd', section2, ...]

    _ORD = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
    i = 1
    while i < len(parts) - 1:
        dam_num = _ORD.get(parts[i].lower())
        if dam_num is not None:
            results[dam_num] = _parse_dam_section(parts[i + 1])
        i += 2

    return results


def _parse_dam_section(text: str) -> dict:
    text = text.strip()

    # Dam name = everything before the first ':'
    # Handle PDF line-wrap in name: "PERSIAN QUEEN\n(IRE):" → "PERSIAN QUEEN (IRE)"
    colon_idx = text.find(":")
    if colon_idx > 0:
        name = text[:colon_idx].replace("\n", " ").strip()
        remainder = text[colon_idx + 1:].strip()
    else:
        name = None
        remainder = text

    # Normalise line-wraps for reliable searching (PDF text wraps mid-phrase)
    flat = remainder.replace("\n", " ")

    # Own record = text before "dam of"
    dam_of_idx = flat.lower().find("dam of ")
    own_record = flat[:dam_of_idx].strip() if dam_of_idx >= 0 else flat[:600]

    # Grade/listed references in own record (wins + placings — quality signal)
    gr1 = len(_GR_RE["gr1"].findall(own_record))
    gr2 = len(_GR_RE["gr2"].findall(own_record))
    gr3 = len(_GR_RE["gr3"].findall(own_record))
    listed = len(_GR_RE["listed"].findall(own_record))

    # Own wins
    wins_m = _WINS_RE.search(own_record)
    own_wins = int(wins_m.group(1)) if wins_m else 0
    unraced = "unraced" in own_record.lower()

    # Prize money
    prize_m = _PRIZE_RE.search(own_record)
    prize_money = int(prize_m.group(1).replace(",", "")) if prize_m else 0

    # Production stats (run on flat text to avoid line-wrap breaks)
    prod_text = flat[dam_of_idx:] if dam_of_idx >= 0 else ""
    prod_m = _PROD_RE.search(prod_text)
    foals = int(prod_m.group(1)) if prod_m else 0
    runners = int(prod_m.group(2)) if (prod_m and prod_m.group(2)) else 0
    winners = int(prod_m.group(3)) if (prod_m and prod_m.group(3)) else 0
    winners_pct = round(winners / runners * 100, 1) if runners > 0 else 0.0

    return {
        "name": name,
        "unraced": unraced,
        "own_wins": own_wins,
        "gr1": gr1,
        "gr2": gr2,
        "gr3": gr3,
        "listed": listed,
        "prize_money": prize_money,
        "foals": foals,
        "runners": runners,
        "winners": winners,
        "winners_pct": winners_pct,
        "raw_text": text[:1200],
    }


# --- Scoring ---

def dam_quality_score(dam: dict) -> float:
    """Score a single dam 0-10 based on own record quality."""
    if dam["unraced"] and dam["own_wins"] == 0:
        base = 5.0
    elif dam["own_wins"] == 0:
        base = 6.0  # placed only
    elif dam["own_wins"] == 1:
        base = 6.5
    else:
        base = 7.0

    if dam["gr1"] > 0:
        base = max(base, 9.0)
    elif dam["gr2"] > 0:
        base = max(base, 8.0)
    elif dam["gr3"] > 0:
        base = max(base, 7.5)
    elif dam["listed"] > 0:
        base = max(base, 7.2)

    # Production bonus
    if dam["runners"] >= 3:
        pct = dam["winners_pct"]
        if pct >= 60:
            base += 1.0
        elif pct >= 40:
            base += 0.5

    return min(10.0, base)


def score_dam_production(dam_records: dict[int, dict]) -> float:
    """
    Weighted dam production score (0-10).
    Weights: 1st dam 40%, 2nd dam 30%, 3rd dam 20%, 4th dam 10%.
    """
    weights = {1: 0.40, 2: 0.30, 3: 0.20, 4: 0.10}
    total = 0.0
    weight_used = 0.0
    for dam_num, weight in weights.items():
        dam = dam_records.get(dam_num)
        if dam:
            total += dam_quality_score(dam) * weight
            weight_used += weight
    if weight_used == 0:
        return 5.0
    # Normalise to full 100% weighting even if some dams missing
    return round(total / weight_used, 2)
