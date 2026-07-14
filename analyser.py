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
You are an expert bloodstock advisor with 20 years of experience at Tattersalls and Goffs sales
in Ireland and the UK. You specialise in both National Hunt (NH) store horse breeding and Flat
racing yearling and store horse assessment.

Each lot is tagged [NH] or [FLAT] at the start of its description.

For [NH] lots:
- Consider the sire's NH record and reputation for producing jumpers and chasers
- Assess the dam line for NH stamina, jumping ability and point-to-point potential
- Factor in sex (geldings sell well for NH; fillies carry breeding premium)
- Estimate sale price in GBP for the NH/point-to-point store horse market (typical range £2,000–£60,000)

For [FLAT] lots:
- Consider the sire's Flat record, Classic potential and distance aptitude
- Assess the dam line for speed, turf/all-weather preference and sprint vs staying profile
- Factor in sex (colts carry stud premium; fillies carry breeding premium)
- Estimate sale price in GBP for the Flat yearling/store market (typical range £5,000–£200,000)

The pedigree score (0–100) is a quantitative sire index on the relevant scale (NH or Flat).
Be concise and practical, as if advising a buyer at the ring.

Format your summary exactly as:
Pros: [1-2 key positives]
Cons: [1-2 key risks or negatives]
Est. Price: £[low]-£[high]
""".strip()

# Breeze-Up sales are pre-trained 2-year-olds, not yearlings or store horses.
# They command a 5-15x premium over the same sire's yearling price.
# Historical comparable data in the system comes from yearling sales (Orby, HIT) and will
# UNDERESTIMATE breeze-up hammer prices. Ignore those comparables for price calibration.
_BREEZE_UP_SYSTEM_PROMPT = """
You are an expert bloodstock advisor specialising in breeze-up sales at Goffs and Tattersalls.

These lots are PRE-TRAINED 2-YEAR-OLDS that have undergone professional breaking and early
conditioning. They are NOT yearlings or store horses. Breeze-up prices command a substantial
training premium — typically 5-15x what the same sire's unbroken yearling would fetch at a
yearling sale. Any historical comparable data shown reflects yearling sale prices and will
significantly underestimate breeze-up hammer prices; use it only as a very rough directional
signal, not as a price anchor.

Each lot is tagged [NH] or [FLAT]. At a breeze-up sale nearly all lots will be [FLAT].

For [FLAT] lots:
- Assess the sire's speed/precocity profile (2yo winners, sprint-classic distances)
- Consider the dam line for early maturity, turf speed and 2yo winning ability
- Factor in sex (colts carry stud premium at breeze-up; fillies slightly softer market)
- The breeze-up market is driven by precocity, physique and the gallop (you don't see it, but factor in that buyers will have watched the horse move)
- Estimate sale price in GBP. Typical range at Goffs Classic Breeze-Up: £15,000–£600,000
  - Budget lots (unfashionable sire, moderate dam line): £15,000–£40,000
  - Mid-market (solid sire, decent dam line): £40,000–£120,000
  - Top lots (elite sire, strong family): £120,000–£400,000+
  - Outstanding (Frankel, Wootton Bassett, Palace Pier, top families): £250,000–£600,000+

For [NH] lots (rare at breeze-up):
- Estimate sale price in GBP for the NH store market (typical range £5,000–£40,000)

The pedigree score (0–100) is a quantitative flat sire index.
Be concise and practical, as if advising a buyer at the ring.

Format your summary exactly as:
Pros: [1-2 key positives]
Cons: [1-2 key risks or negatives]
Est. Price: £[low]-£[high]
""".strip()


class LotResult(BaseModel):
    lot_number: str = Field(description="Lot number exactly as provided")
    estimated_price_gbp: int = Field(description="Estimated sale price in GBP as a whole number (midpoint of range)")
    summary: str = Field(description="Pros/Cons assessment in the format: 'Pros: ... Cons: ... Est. Price: £x-£y'")


class BatchResult(BaseModel):
    results: list[LotResult]


_HIT_SYSTEM_PROMPT = """
You are an expert bloodstock advisor specialising in Horses In Training (HIT) sales at Tattersalls,
Goffs and Tattersalls Ireland.

CRITICAL: These are TRAINED HORSES that have already raced or been prepared for racing. They are
NOT yearlings or store horses. Pricing is driven almost entirely by race record, not pedigree.

Pricing hierarchy (most to least important):
1. Race record — wins, placings, class of races, earnings. A horse with 3 wins at a decent level
   is worth far more than an unraced horse by Frankel. A horse by a cheap sire that won a Listed
   race commands a major premium over an elite-sired horse with nothing on the clock.
2. Age and soundness — younger horses with potential command more; older horses with problems
   are heavily discounted.
3. Trainer — a horse from a top trainer (Aidan O'Brien, John Gosden, William Haggas etc.) signals
   quality even if form figures are modest.
4. Pedigree — secondary only. A famous sire adds modest premium but does not overcome a poor
   race record. An unfashionable sire does not prevent a horse with a strong record from selling well.

IMPORTANT: Any historical comparable prices shown reflect YEARLING sale prices, NOT HIT sale prices.
A Frankel yearling may fetch £500,000; a Frankel horse in training with poor form may fetch £3,000.
Ignore the comparable prices as a price anchor — use them only as a distant signal.

The pedigree score (0–100) is a sire quality index and is a WEAK signal at HIT sales. Do not let
it dominate your estimate.

Typical price ranges at a Tattersalls Guineas HIT Sale:
- Most lots (average form, unfashionable connections): £1,000–£10,000
- Decent form or top trainer: £10,000–£40,000
- Multiple winners or Listed/Group class: £40,000–£100,000+
- Elite proven performers: £80,000–£200,000+

Each lot is tagged [HIT] or [FLAT] (by discipline based on sire) but this is less meaningful
than usual — focus on the horse's own record, not the sire's racing category.

Lot description includes trainer where known — factor this in.

Format your summary exactly as:
Pros: [1-2 key positives]
Cons: [1-2 key risks or negatives]
Est. Price: £[low]-£[high]
""".strip()

_batch_agent = Agent(_MODEL, output_type=BatchResult, system_prompt=_SYSTEM_PROMPT)
_breeze_up_agent = Agent(_MODEL, output_type=BatchResult, system_prompt=_BREEZE_UP_SYSTEM_PROMPT)
_hit_agent = Agent(_MODEL, output_type=BatchResult, system_prompt=_HIT_SYSTEM_PROMPT)


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


def _lot_block(lot: dict, sale_type: str = "standard") -> str:
    dam_line = _dam_summary(lot.get("dam_records"))
    comp_line = _comp_summary(lot.get("historical_comps"))
    trainer = lot.get("trainer")
    lot_type = lot.get("lot_type")
    tag = (lot_type or (lot.get('discipline') or 'nh')).upper()
    block = (
        f"[{tag}] "
        f"Lot {lot['lot_number']}: {lot.get('horse_name') or 'Unnamed'} | "
        f"YOB: {lot.get('year_of_birth') or '?'} | Sex: {lot.get('sex') or '?'} | "
        f"Sire: {lot.get('sire') or '?'} | Dam: {lot.get('dam') or '?'} | "
    )
    if sale_type == "hit":
        if trainer:
            block += f"Trainer: {trainer} | "
        block += f"Sire pedigree score (secondary signal): {lot.get('pedigree_score', 0):.1f}/100"
    else:
        block += (
            f"Dam's sire: {lot.get('dam_sire') or '?'} | "
            f"Pedigree score: {lot.get('pedigree_score', 0):.1f}/100"
        )
    if dam_line:
        block += f" | Dam lines: {dam_line}"
    if comp_line:
        block += f" | Historical prices: {comp_line}"
    return block


def analyse_batch(lots: list[dict], sale_type: str = "standard") -> list[LotResult]:
    """Analyse a batch of lots in one LLM call. Returns results in same order as input."""
    if sale_type == "breeze_up":
        agent = _breeze_up_agent
    elif sale_type == "hit":
        agent = _hit_agent
    else:
        agent = _batch_agent
    prompt = (
        f"Analyse these {len(lots)} sale lots. "
        "For each, provide lot_number (exact), estimated_price_gbp, and summary.\n\n"
        + "\n".join(_lot_block(l, sale_type=sale_type) for l in lots)
    )
    result = agent.run_sync(prompt)
    # Normalise lot_number — model sometimes returns "Lot 756" instead of "756"
    for r in result.output.results:
        r.lot_number = r.lot_number.strip().removeprefix("Lot").strip()
    # Re-order to match input order in case model shuffles them
    order = {l["lot_number"]: i for i, l in enumerate(lots)}
    return sorted(result.output.results, key=lambda r: order.get(r.lot_number, 999))


_BATCH_DELAY = 4.0  # seconds between batches — respect 15 RPM free tier


def analyse_lots(
    lots: list[dict],
    on_batch: Callable[[int, int], None] | None = None,
    sale_type: str = "standard",
) -> dict[str, LotResult]:
    """
    Analyse all lots in batches of LLM_BATCH_SIZE.
    sale_type: 'breeze_up' uses the breeze-up specialist prompt; anything else uses standard.
    Calls on_batch(done, total) after each batch for progress updates.
    Returns {lot_number: LotResult}.
    """
    results: dict[str, LotResult] = {}
    chunks = [lots[i: i + _BATCH_SIZE] for i in range(0, len(lots), _BATCH_SIZE)]
    done = 0
    for i, chunk in enumerate(chunks):
        try:
            batch_results = analyse_batch(chunk, sale_type=sale_type)
        except Exception:
            # Retry once with half-sized sub-batches before giving up
            mid = len(chunk) // 2
            sub_chunks = [chunk[:mid], chunk[mid:]] if mid else [chunk]
            batch_results = []
            for sub in sub_chunks:
                if not sub:
                    continue
                try:
                    batch_results.extend(analyse_batch(sub, sale_type=sale_type))
                except Exception:
                    pass  # skip un-parseable sub-batch rather than crash entire run
        for r in batch_results:
            results[r.lot_number] = r
        done += len(chunk)
        if on_batch:
            on_batch(done, len(lots))
        if i < len(chunks) - 1:
            time.sleep(_BATCH_DELAY)
    return results
