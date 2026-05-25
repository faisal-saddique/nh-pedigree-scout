"""
Fetch leading sire rankings from api.stallionguide.com (Kendo Grid JSON API).

Endpoints:
  LeadingSiresTableJumps_Read?id={year}1  — NH GB/IRE sires
  LeadingSiresTableJumps_Read?id={year}7  — NH France sires
  LeadingSiresTable_Read/{year}1          — Flat Europe sires
  LeadingSiresTable_Read?id={year}44      — NH Broodmare sires GB/IRE

Year suffix = current calendar year (2026 covers 2025-26 NH season and 2026 flat year).
"""
import datetime
import httpx

_API = "https://api.stallionguide.com/data"
_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://www.stallionguide.com/leading-sires/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
_BODY = b"take=200&skip=0&page=1&pageSize=200"


def _season_year() -> int:
    today = datetime.date.today()
    return today.year


def _post(client: httpx.Client, endpoint: str, id_: str, path: bool = False) -> list[dict]:
    url = f"{_API}/{endpoint}/{id_}" if path else f"{_API}/{endpoint}?id={id_}"
    resp = client.post(url, content=_BODY)
    resp.raise_for_status()
    return resp.json().get("Data", [])


def fetch_rankings() -> dict[str, dict]:
    """
    Fetch NH GB/IRE, NH France, Flat Europe, and NH Broodmare sire tables.
    Returns {sire_name: {nh_rank, nh_winners, nh_bt_pct, nh_awd,
                         nh_fr_rank, flat_rank, flat_winners, flat_bt_pct, nh_bm_rank}}.
    """
    year = _season_year()
    nh_ire_id = f"{year}1"   # NH GB/IRE
    nh_fr_id  = f"{year}7"   # NH France
    flat_id   = f"{year}1"   # Flat Europe
    bm_id     = f"{year}44"  # NH Broodmares GB/IRE

    combined: dict[str, dict] = {}

    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        for row in _post(client, "LeadingSiresTableJumps_Read", nh_ire_id):
            name = row["Sire"].strip()
            combined.setdefault(name, {}).update({
                "nh_rank": row["Rank"],
                "nh_winners": row["Winners"],
                "nh_bt_pct": row.get("BTWinnersToRunnersPer", 0.0),
                "nh_awd": row.get("AverageWinningDistance", 0.0),
            })

        for row in _post(client, "LeadingSiresTableJumps_Read", nh_fr_id):
            name = row["Sire"].strip()
            combined.setdefault(name, {})["nh_fr_rank"] = row["Rank"]

        for row in _post(client, "LeadingSiresTable_Read", flat_id, path=True):
            name = row["Sire"].strip()
            combined.setdefault(name, {}).update({
                "flat_rank": row["Rank"],
                "flat_winners": row["Winners"],
                "flat_bt_pct": row.get("BTWinnersToRunnersPer", 0.0),
            })

        for row in _post(client, "LeadingSiresTable_Read", bm_id):
            name = row["Sire"].strip()
            combined.setdefault(name, {})["nh_bm_rank"] = row["Rank"]

    return combined
