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
""".strip()


class LotResult(BaseModel):
    lot_number: str = Field(description="Lot number exactly as provided")
    estimated_price_gbp: int = Field(description="Estimated sale price in GBP as a whole number")
    summary: str = Field(description="2-3 sentence expert assessment of NH potential and price justification")


class BatchResult(BaseModel):
    results: list[LotResult]


_batch_agent = Agent(_MODEL, output_type=BatchResult, system_prompt=_SYSTEM_PROMPT)


def _lot_block(lot: dict) -> str:
    return (
        f"Lot {lot['lot_number']}: {lot.get('horse_name') or 'Unnamed'} | "
        f"YOB: {lot.get('year_of_birth') or '?'} | Sex: {lot.get('sex') or '?'} | "
        f"Sire: {lot.get('sire') or '?'} | Dam: {lot.get('dam') or '?'} | "
        f"Dam's sire: {lot.get('dam_sire') or '?'} | "
        f"NH score: {lot.get('pedigree_score', 0):.1f}/100"
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
