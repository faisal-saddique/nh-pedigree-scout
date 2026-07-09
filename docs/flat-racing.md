# Flat Racing Support

## Overview

The app automatically detects whether each lot is a **Flat** or **NH** horse and applies the correct scoring engine, nick matrix, and AI prompt. Detection is per-lot (not per-sale), so a mixed sale with both NH and Flat horses is handled correctly.

---

## How discipline is detected

For each lot, the sire name is looked up in the live Stallion Guide rankings:

1. **Flat rank only** → `flat`
2. **Flat rank exists and is better (lower number) than NH rank** → `flat`
3. **No rankings data** → checked against a hardcoded flat-sire list (Frankel, Dubawi, Galileo, Kingman, Dark Angel, Siyouni, etc.)
4. **Anything else** → `nh`

The detected discipline is stored on each lot in the database. Re-scraping a sale updates it.

---

## Flat scoring

Same 50/30/20 weight structure as NH but uses flat-specific data:

| Component | NH | Flat |
|-----------|-----|------|
| Sire (50%) | `nh_rank` / NH pts | `flat_rank` / flat pts |
| Dam's Sire (30%) | BroodmareSire rank | flat rank |
| 2nd Dam's Sire (20%) | BroodmareSire rank | flat rank |
| Nick matrix | NH nick matrix | Flat nick matrix |

### Flat nick matrix highlights
- Night of Thunder × Pivotal — 9.5
- Kingman × Selkirk — 9.0
- Too Darn Hot × Shamardal — 8.5
- Frankel × Galileo — 8.5
- Kingman × Sea The Stars — 8.0

---

## UI differences for Flat lots

- Badge **🏇 Flat** shown next to lot title (NH lots show **🦘 NH**)
- Score breakdown shows **Flat rank** and **Flat BT%** instead of NH rank
- AI analysis uses the Flat prompt (Classic potential, speed/stamina profile, turf/AW, sprint vs staying)
- AI price range: **£5,000–£200,000** (vs £2,000–£60,000 for NH)
- Table **Type** column shows "flat" or "nh"

---

## Known limitations

- Lots scraped before the flat feature was deployed have `discipline = 'nh'` by default. Re-scrape to get correct detection.
- Discipline detection relies on the sire name matching the rankings. Misspelled or very obscure sires fall back to "nh".
- Goffs Flat yearling catalogues (Orby, Autumn HIT) are well supported. Tattersalls Flat catalogues also work but have been tested less.

---

## Historical flat data loaded

4,658 lots from 13 Goffs Flat sales (2022–2025):

| Sale | Years |
|------|-------|
| Orby Book 1 | 2022, 2023, 2024, 2025 |
| Orby Book 2 | 2022, 2023, 2024, 2025 |
| Autumn Yearling / HIT Sale | 2022, 2023, 2024, 2025 |
| Classic Breeze-Up | 2025 |

These power the **Historical prices** comparables for flat sires like Frankel, Dubawi, Galileo, Kingman, etc.
