import re
from typing import TypedDict

# Hardcoded fallback — used when sire_rankings table has no entry for a sire
NH_SIRE_SCORES: dict[str, float] = {
    "Flemensfirth": 9.5,
    "Presenting": 9.0,
    "Oscar": 9.0,
    "King's Theatre": 9.0,
    "Mahler": 8.5,
    "Milan": 8.5,
    "Robin des Champs": 8.5,
    "Stowaway": 8.5,
    "Kayf Tara": 8.5,
    "Yeats": 8.0,
    "Walk In The Park": 8.0,
    "Galiway": 7.5,
    "Getaway": 7.5,
    "Doyen": 7.5,
    "Authorized": 7.5,
    "High Chaparral": 7.5,
    "Westerner": 7.5,
    "Shantou": 7.5,
    "Midnight Legend": 7.5,
    "Mount Nelson": 7.5,
    "Shirocco": 7.5,
    "Galileo": 7.0,
    "Dylan Thomas": 7.0,
    "Gold Well": 7.0,
    "Jeremy": 7.0,
    "Beneficial": 7.0,
    "Kalanisi": 7.0,
    "Scorpion": 7.0,
    "Black Sam Bellamy": 7.0,
    "Dr Massini": 7.0,
    "Montjeu": 7.0,
    "Luso": 7.0,
    "Sadler's Wells": 7.0,
    "Strong Gale": 7.0,
    "Roselier": 7.0,
    "Old Vic": 6.5,
    "Bob Back": 6.5,
    "Be My Native": 6.5,
    "Hernando": 6.5,
    "Daylami": 6.5,
    "Winged Love": 6.5,
    "Indian River": 6.5,
    "Saddlers' Hall": 6.5,
    "Witness Box": 6.5,
    "Good Thyne": 6.0,
    "Phardante": 6.0,
    "Accordion": 6.0,
    "Great Palm": 6.0,
    "Definite Article": 6.0,
    "Be My Chief": 6.0,
    "Blueprint": 5.5,
}

_DEFAULT_SCORE = 4.0
_rankings: dict[str, dict] = {}  # loaded from DB/API before each scrape run

# ---------------------------------------------------------------------------
# Nick matrix — documented sire × dam-sire crosses
# Score 0-10; bonus = score * 0.7 pts added to final 0-100 score (max +7 pts)
# Sources: StallionGuide Nick Picking (Boyce 2024), Hot Crosses (Boyce 2025),
#          sale evidence from TIDK / Arkle Sale results
# ---------------------------------------------------------------------------
_NH_NICK_MATRIX: dict[tuple[str, str], tuple[float, str]] = {
    # --- NH-specific elite crosses ---
    ("Walk In The Park", "Stowaway"):       (9.8, "Elite NH nick — €285k TIDK 2025 topper; Jonbon; multiple Cheltenham Gr.1 winners"),
    ("No Risk At All", "Presenting"):       (9.6, "Elite — Brighterdaysahead 5× Gr.1; Burrows Saint Irish GN; Allaho 2× Ryanair Chase"),
    ("Blue Bresil", "Flemensfirth"):        (9.4, "Elite — multiple graded NH winners; dominant TIDK Gr.1 production"),
    ("Walk In The Park", "Oscar"):          (9.2, "Strong — Energumene family; consistent graded winner cross in IRE"),
    ("Kapgarde", "Flemensfirth"):           (9.1, "Strong — Clan Des Obeaux 2× King George; Isaac Des Obeaux Gr.1"),
    ("Getaway", "Presenting"):              (8.5, "Strong — consistent NH cross IRE/FR; stamina on stamina"),
    ("Golden Horn", "Galileo"):             (8.2, "Developing NH — 30% BTH from 20 runners; 2026/27 crop defining"),
    ("Nathaniel", "Galileo"):               (7.9, "Promising — You Wear It Well Gr.2 Cheltenham; NH mares hurdle production"),
    ("Soldier Of Fortune", "Flemensfirth"): (7.8, "Useful — proven staying chase cross"),
    ("Yeats", "Galileo"):                   (7.6, "Useful — staying hurdle/chase profile; consistent NH cross"),
    ("Poet's Word", "Sea The Stars"):       (7.7, "Emerging — Sea The Stars daughters 6.8% SW/Rnrs as BM sire; first crops strong"),
    ("Crystal Ocean", "Presenting"):        (7.5, "Emerging — Galvin family; stamina-on-stamina staying chase cross"),
    ("Mahler", "Presenting"):               (7.5, "Solid NH cross — both sires proven staying NH bloodlines"),
    ("Milan", "Flemensfirth"):              (7.5, "Solid NH cross — consistent graded NH production in IRE"),
    # --- Flat/NH dual-purpose crosses from STG Nick Picking data ---
    ("Night of Thunder", "Pivotal"):        (9.5, "Elite flat — 50% BTW 6 runners; Flight Plan Gr.2, Molatham Gr.3"),
    ("Kingman", "Selkirk"):                 (9.0, "Strong flat — 30.8% BTH, 23.1% BTW; Kinross dual Gr.1, Epictetus Gr.3"),
    ("Too Darn Hot", "Shamardal"):          (8.5, "Strong flat — 23.5% BTW; Too Darn Discreet Aus Gr.2"),
    ("Night of Thunder", "Dansili"):        (8.5, "Strong flat — 30.8% BTH, 30.8% BTW; Vespertilio Gr.2"),
    ("Kingman", "Sea The Stars"):           (8.0, "Strong flat — 26.7% BTH, 26.7% BTW; Technical Analysis US Gr.2"),
    ("Australia", "Acclamation"):           (8.0, "Good flat — 30.8% BTH, 23.1% BTW; Broome Gr.1, Point Lonsdale Gr.2"),
    ("Dubawi", "Galileo"):                  (7.5, "Good flat — 130 runners, 18.5% BTW; Henry Longfellow Gr.1"),
    ("Kingman", "Galileo"):                 (7.5, "Good flat — 23.0% BTH, 14.8% BTW; Commissioning Gr.1 Fillies Mile"),
}


def _nick_lookup(sire: str | None, dam_sire: str | None) -> tuple[float, str]:
    """Return (nick_score 0-10, description). 0.0 if no documented match."""
    if not sire or not dam_sire:
        return (0.0, "")
    s = _normalise(sire).lower()
    d = _normalise(dam_sire).lower()
    for (ms, md), (score, desc) in _NH_NICK_MATRIX.items():
        if _normalise(ms).lower() == s and _normalise(md).lower() == d:
            return (score, desc)
    return (0.0, "")


def _bm_tier(rank: int | None) -> str:
    """Human-readable NH BM tier label based on StallionGuide rank."""
    if not rank:
        return "Unranked"
    if rank <= 8:
        return "T1 — Elite BM sire"
    if rank <= 18:
        return "T2 — Strong BM sire"
    if rank <= 35:
        return "T3 — Useful BM sire"
    return "T4 — Developing BM sire"


class ScoreBreakdown(TypedDict):
    sire_name: str
    sire_contribution: float
    sire_nh_rank: int | None
    sire_nh_fr_rank: int | None
    sire_nh_bt_pct: float | None
    sire_nh_awd: float | None
    sire_source: str
    dam_sire_name: str
    dam_sire_contribution: float
    dam_sire_nh_bm_rank: int | None
    dam_sire_bm_tier: str
    dam_sire_source: str
    second_dam_sire_name: str
    second_dam_sire_contribution: float
    second_dam_sire_source: str
    nick_score: float
    nick_bonus: float
    nick_description: str
    base_score: float
    total: float


def load_rankings(rankings: dict[str, dict]) -> None:
    """Populate module-level rankings cache. Call before scraping."""
    global _rankings
    _rankings = rankings


def _clean(name) -> str | None:
    """Convert NaN/non-string/empty to None; strip whitespace from strings."""
    if name is None:
        return None
    if not isinstance(name, str):
        try:
            import math
            if math.isnan(name):
                return None
        except (TypeError, ValueError):
            pass
        return None
    name = name.strip()
    return name if name else None


def _normalise(name: str) -> str:
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", name.strip())


def _rank_to_score(rank: int) -> float:
    """Rank 1 → 10.0, Rank 50 → 4.0, linear."""
    return round(max(4.0, 10.0 - (rank - 1) * 6.0 / 49), 2)


def _row_for(name: str) -> dict | None:
    if not _rankings:
        return None
    key = _normalise(name)
    row = _rankings.get(key)
    if not row:
        kl = key.lower()
        row = next((v for k, v in _rankings.items() if k.lower() == kl), None)
    return row


def _best_nh_rank(row: dict) -> int | None:
    """Return the best (lowest number) NH rank across GB/IRE and France."""
    ranks = [r for r in (row.get("nh_rank"), row.get("nh_fr_rank")) if r]
    return min(ranks) if ranks else None


def _lookup(name: str | None) -> float:
    if not name:
        return _DEFAULT_SCORE
    row = _row_for(name)
    if row:
        rank = _best_nh_rank(row)
        if rank:
            return _rank_to_score(rank)
    key = _normalise(name)
    return NH_SIRE_SCORES.get(key) or NH_SIRE_SCORES.get(key.title()) or _DEFAULT_SCORE


def _lookup_bm(name: str | None) -> float:
    """Dam sire lookup — uses NH broodmare rank, falls back to best NH sire rank."""
    if not name:
        return _DEFAULT_SCORE
    row = _row_for(name)
    if row:
        rank = row.get("nh_bm_rank") or _best_nh_rank(row)
        if rank:
            return _rank_to_score(rank)
    key = _normalise(name)
    return NH_SIRE_SCORES.get(key) or NH_SIRE_SCORES.get(key.title()) or _DEFAULT_SCORE


def score_lot(sire: str | None, dam_sire: str | None, second_dam_sire: str | None) -> float:
    """Return 0–100 NH pedigree score. Sire 50%, dam sire 30%, 2nd dam sire 20%."""
    s = _lookup(_clean(sire)) * 0.5
    ds = _lookup_bm(_clean(dam_sire)) * 0.3
    sds = _lookup(_clean(second_dam_sire)) * 0.2
    return round((s + ds + sds) * 10, 1)


def _score_source(name: str | None, row: dict | None, kind: str) -> str:
    if not name:
        return "Unknown sire — using default"
    if row:
        if kind == "bm" and row.get("nh_bm_rank"):
            return f"NH BM rank #{row['nh_bm_rank']} (StallionGuide)"
        if row.get("nh_rank"):
            return f"NH rank #{row['nh_rank']} (StallionGuide)"
        if row.get("nh_fr_rank"):
            return f"NH France rank #{row['nh_fr_rank']} (StallionGuide)"
    key = _normalise(name)
    if NH_SIRE_SCORES.get(key) or NH_SIRE_SCORES.get(key.title()):
        return "Historical hardcoded rating"
    return "Not in rankings — using default"


def score_lot_with_breakdown(
    sire: str | None,
    dam_sire: str | None,
    second_dam_sire: str | None,
) -> tuple[float, ScoreBreakdown]:
    """
    Returns (base_score, breakdown).
    base_score matches score_lot() exactly.
    nick_bonus is informational — shown in UI but not added to the stored score.
    """
    sire = _clean(sire)
    dam_sire = _clean(dam_sire)
    second_dam_sire = _clean(second_dam_sire)

    sire_raw = _lookup(sire)
    sire_row = _row_for(sire) if sire else None
    sire_contrib = round(sire_raw * 0.5 * 10, 1)

    ds_raw = _lookup_bm(dam_sire)
    ds_row = _row_for(dam_sire) if dam_sire else None
    ds_contrib = round(ds_raw * 0.3 * 10, 1)

    sds_raw = _lookup(second_dam_sire)
    sds_row = _row_for(second_dam_sire) if second_dam_sire else None
    sds_contrib = round(sds_raw * 0.2 * 10, 1)

    nick_score, nick_desc = _nick_lookup(sire, dam_sire)
    nick_bonus = round(nick_score * 0.7, 1)

    base = round((sire_raw * 0.5 + ds_raw * 0.3 + sds_raw * 0.2) * 10, 1)

    breakdown: ScoreBreakdown = {
        "sire_name": sire or "Unknown",
        "sire_contribution": sire_contrib,
        "sire_nh_rank": sire_row.get("nh_rank") if sire_row else None,
        "sire_nh_fr_rank": sire_row.get("nh_fr_rank") if sire_row else None,
        "sire_nh_bt_pct": sire_row.get("nh_bt_pct") if sire_row else None,
        "sire_nh_awd": sire_row.get("nh_awd") if sire_row else None,
        "sire_source": _score_source(sire, sire_row, "sire"),
        "dam_sire_name": dam_sire or "Unknown",
        "dam_sire_contribution": ds_contrib,
        "dam_sire_nh_bm_rank": ds_row.get("nh_bm_rank") if ds_row else None,
        "dam_sire_bm_tier": _bm_tier(ds_row.get("nh_bm_rank") if ds_row else None),
        "dam_sire_source": _score_source(dam_sire, ds_row, "bm"),
        "second_dam_sire_name": second_dam_sire or "Unknown",
        "second_dam_sire_contribution": sds_contrib,
        "second_dam_sire_source": _score_source(second_dam_sire, sds_row, "sire"),
        "nick_score": nick_score,
        "nick_bonus": nick_bonus,
        "nick_description": nick_desc,
        "base_score": base,
        "total": base,
    }
    return base, breakdown
