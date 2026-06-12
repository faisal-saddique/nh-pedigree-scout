import os
import time
from collections.abc import Callable
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from dotenv import load_dotenv

load_dotenv()

# Switch model and batch size via .env:
#   LLM_MODEL=google:gemini-2.5-flash   (default)
#   LLM_MODEL=groq:llama-3.3-70b-versatile
#   LLM_BATCH_SIZE=10                   (default)
_MODEL = os.getenv("LLM_MODEL", "google:gemini-2.5-flash")
_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "10"))

_SYSTEM_PROMPT = """
You are an expert National Hunt (NH) bloodstock advisor with 20 years of experience at Tattersalls
and Goffs sales in Ireland and the UK. You specialise in point-to-point and NH store horse breeding.

When assessing each lot:
- Consider the sire's NH record and reputation
- Assess the dam line for NH stamina and jumping ability
- Factor in sex (geldings and colts sell differently to fillies)
- Estimate sale price in GBP based on current NH store horse market (typical range £2,000–£60,000)
- Be concise and practical, as if advising a buyer at the ring

The pedigree score (0–100) is a quantitative NH sire index for quick reference.

Format your summary exactly as:
Pros: [1-2 key positives about pedigree, jumping potential, or value]
Cons: [1-2 key risks or negatives]
Est. Price: £[low]-£[high]
""".strip()


class LotResult(BaseModel):
    lot_number: str = Field(description="Lot number exactly as provided")
    estimated_price_gbp: int = Field(description="Estimated sale price in GBP as a whole number (midpoint of range)")
    summary: str = Field(description="Pros/Cons assessment in the format: 'Pros: ... Cons: ... Est. Price: £x-£y'")


class BatchResult(BaseModel):
    results: list[LotResult]


_batch_agent = Agent(_MODEL, output_type=BatchResult, system_prompt=_SYSTEM_PROMPT)


def _dam_summary(dam_records) -> str:
    """Build a concise dam line summary for the AI prompt."""
    if not dam_records:
        return ""
    import json
    if isinstance(dam_records, str):
        try:
            dam_records = json.loads(dam_records)
        except Exception:
            return ""
    lines = []
    labels = {"1": "1st dam", "2": "2nd dam", "3": "3rd dam", "4": "4th dam"}
    for key in ["1", "2", "3", "4"]:
        dam = dam_records.get(key) or dam_records.get(int(key))
        if not dam:
            continue
        name = dam.get("name") or "Unknown"
        wins = dam.get("own_wins", 0)
        gr1, gr2, gr3 = dam.get("gr1", 0), dam.get("gr2", 0), dam.get("gr3", 0)
        foals, runners, winners = dam.get("foals", 0), dam.get("runners", 0), dam.get("winners", 0)
        grade = ""
        if gr1:
            grade = f"Gr.1 performer"
        elif gr2:
            grade = f"Gr.2 performer"
        elif gr3:
            grade = f"Gr.3 performer"
        record = f"{wins}W" if wins else ("unraced" if dam.get("unraced") else "placed")
        prod = f"{foals}f/{runners}r/{winners}w" if foals else "no prod."
        lines.append(f"{labels[key]}: {name} ({record}{', ' + grade if grade else ''}) · {prod}")
    return " | ".join(lines)


def _comp_summary(comps: dict | None) -> str:
    """Format historical comparables for AI prompt."""
    if not comps:
        return ""
    sym = "£" if comps.get("currency") == "GBP" else "€"
    median = comps.get("median", 0)
    lo = comps.get("min_price", 0)
    hi = comps.get("max_price", 0)
    n = comps.get("count", 0)
    sales = ", ".join((comps.get("sale_names") or [])[:3])
    return f"sire median {sym}{median:,} (range {sym}{lo:,}–{sym}{hi:,}, N={n} sold, from: {sales})"


def _lot_block(lot: dict) -> str:
    dam_line = _dam_summary(lot.get("dam_records"))
    comp_line = _comp_summary(lot.get("historical_comps"))
    return (
        f"Lot {lot['lot_number']}: {lot.get('horse_name') or 'Unnamed'} | "
        f"YOB: {lot.get('year_of_birth') or '?'} | Sex: {lot.get('sex') or '?'} | "
        f"Sire: {lot.get('sire') or '?'} | Dam: {lot.get('dam') or '?'} | "
        f"Dam's sire: {lot.get('dam_sire') or '?'} | "
        f"NH score: {lot.get('pedigree_score', 0):.1f}/100"
        + (f" | Dam lines: {dam_line}" if dam_line else "")
        + (f" | Historical prices: {comp_line}" if comp_line else "")
    )


def analyse_batch(lots: list[dict]) -> list[LotResult]:
    """Analyse a batch of lots in one LLM call. Returns results in same order as input."""
    prompt = (
        f"Analyse these {len(lots)} NH sale lots. "
        "For each, provide lot_number (exact), estimated_price_gbp, and summary.\n\n"
        + "\n".join(_lot_block(l) for l in lots)
    )
    result = _batch_agent.run_sync(prompt)
    # Normalise lot_number — model sometimes returns "Lot 756" instead of "756"
    for r in result.output.results:
        r.lot_number = r.lot_number.strip().removeprefix("Lot").strip()
    # Re-order to match input order in case model shuffles them
    order = {l["lot_number"]: i for i, l in enumerate(lots)}
    return sorted(result.output.results, key=lambda r: order.get(r.lot_number, 999))


_BATCH_DELAY = 4.0  # seconds between batches — respect 15 RPM free tier


def analyse_lots(lots: list[dict], on_batch: Callable[[int, int], None] | None = None) -> dict[str, LotResult]:
    """
    Analyse all lots in batches of LLM_BATCH_SIZE.
    Calls on_batch(done, total) after each batch for progress updates.
    Returns {lot_number: LotResult}.
    """
    results: dict[str, LotResult] = {}
    chunks = [lots[i: i + _BATCH_SIZE] for i in range(0, len(lots), _BATCH_SIZE)]
    done = 0
    for i, chunk in enumerate(chunks):
        batch_results = analyse_batch(chunk)
        for r in batch_results:
            results[r.lot_number] = r
        done += len(chunk)
        if on_batch:
            on_batch(done, len(lots))
        if i < len(chunks) - 1:
            time.sleep(_BATCH_DELAY)
    return results
