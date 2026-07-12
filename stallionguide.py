"""
Fetch leading sire rankings from api.stallionguide.com (Kendo Grid JSON API).

NH endpoints (LeadingSiresTableJumps_Read):
  ?id={year}1   — NH GB/IRE sires (50)
  ?id={year}7   — NH France sires (50)

Flat endpoints (LeadingSiresTable_Read) — sale-specific IDs:
  Each numeric suffix maps to one Goffs flat sale table for that year.
  Suffixes 1-29 cover IRE/UK/FR flat sales (Orby, Breeze-Up, HIT, 2yo sprint sales, etc.)
  Suffix 44 covers the flat broodmare sires table (Galileo, Dubawi, Invincible Spirit…)
  We fetch ALL of them and keep the best (lowest) rank per sire so discipline detection
  covers the full ~355 flat sires that appear at any Goffs flat sale.

NH Broodmare endpoint (LeadingSiresTable_Read):
  ?id={year}44  — NH Broodmares GB/IRE

Year suffix = current calendar year (2026 covers 2025-26 NH season and 2026 flat year).
"""
import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

_API = "https://api.stallionguide.com/data"
_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://www.stallionguide.com/leading-sires/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
_BODY = "take=200&skip=0&page=1&pageSize=200"

# All flat sale suffix IDs that return data across a full year.
# Suffixes 1-29 = individual Goffs flat sales (Orby, Breeze-Up, HIT, 2yo sprints, FR flat…)
# Suffix 44 = flat broodmare sires (Galileo, Dubawi, Invincible Spirit…)
_FLAT_SUFFIXES = (*range(1, 30), 44)


def _season_year() -> int:
    today = datetime.date.today()
    return today.year


def _get(endpoint: str, id_: str) -> list[dict]:
    url = f"{_API}/{endpoint}?id={id_}"
    try:
        resp = requests.post(url, data=_BODY, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json().get("Data", [])
    except Exception:
        return []


def fetch_rankings() -> dict[str, dict]:
    """
    Fetch NH GB/IRE, NH France, ALL flat sale tables (suffixes 1-29 + 44), and NH BM sires.
    Returns {sire_name: {nh_rank, nh_winners, nh_bt_pct, nh_awd,
                         nh_fr_rank, flat_rank, flat_winners, flat_bt_pct, nh_bm_rank}}.

    For flat_rank, keeps the best (lowest) rank seen across all sale tables so that a sire
    appearing at a specialised sale (Breeze-Up, 2yo sprint) isn't missed.
    """
    year = _season_year()
    nh_ire_id = f"{year}1"   # NH GB/IRE
    nh_fr_id  = f"{year}7"   # NH France
    bm_id     = f"{year}44"  # NH Broodmares GB/IRE

    combined: dict[str, dict] = {}

    # NH GB/IRE
    for row in _get("LeadingSiresTableJumps_Read", nh_ire_id):
        name = row["Sire"].strip()
        combined.setdefault(name, {}).update({
            "nh_rank": row["Rank"],
            "nh_winners": row["Winners"],
            "nh_bt_pct": row.get("BTWinnersToRunnersPer", 0.0),
            "nh_awd": row.get("AverageWinningDistance", 0.0),
        })

    # NH France
    for row in _get("LeadingSiresTableJumps_Read", nh_fr_id):
        name = row["Sire"].strip()
        combined.setdefault(name, {})["nh_fr_rank"] = row["Rank"]

    # Flat — fetch all sale-specific tables in parallel.
    # Each thread uses its own requests.Session to avoid any shared-state issues.
    def _fetch_flat(suffix: int) -> list[dict]:
        flat_id = f"{year}{suffix}"
        url = f"{_API}/LeadingSiresTable_Read?id={flat_id}"
        try:
            with requests.Session() as s:
                resp = s.post(url, data=_BODY, headers=_HEADERS, timeout=12)
                resp.raise_for_status()
                return resp.json().get("Data", [])
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_flat, s): s for s in _FLAT_SUFFIXES}
        for future in as_completed(futures):
            for row in future.result():
                name = row["Sire"].strip()
                existing_rank = combined.get(name, {}).get("flat_rank")
                new_rank = row["Rank"]
                if existing_rank is None or new_rank < existing_rank:
                    combined.setdefault(name, {}).update({
                        "flat_rank": new_rank,
                        "flat_winners": row["Winners"],
                        "flat_bt_pct": row.get("BTWinnersToRunnersPer", 0.0),
                    })

    # NH Broodmare sires
    for row in _get("LeadingSiresTable_Read", bm_id):
        name = row["Sire"].strip()
        combined.setdefault(name, {})["nh_bm_rank"] = row["Rank"]

    return combined
