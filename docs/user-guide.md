# NH Pedigree Scout — User Guide

## What it does

Scrapes a Tattersalls or Goffs sale catalogue, scores every lot's pedigree (0–100), fetches dam records from PDFs, pulls historical hammer prices for the sire, and runs an AI analysis that outputs pros/cons and an estimated price.

Supports both **National Hunt** (store horses, pointers) and **Flat** (yearlings, breeze-ups) lots. Discipline is detected automatically per lot from the sire's rankings.

---

## Quick start

1. Open the app in your browser.
2. Paste a catalogue URL in the **Catalogue URL** box (sidebar).
3. Click **Scrape & Analyse**.
4. The app scrapes, scores, fetches dam records (Goffs only), then runs AI analysis — progress bars show each stage.
5. The dashboard appears automatically when done.

To reload a previous sale, pick it from the **Previous Sales** dropdown and click **Load**.

---

## Supported sites

| Site | URL pattern | Notes |
|------|-------------|-------|
| Tattersalls | `https://www.tattersalls.com/sales-catalogue.php?sale=...` | Main and Irish sales |
| Tattersalls IE | `https://www.tattersalls.ie/sales/.../4DCGI/Sale/.../Main/Lots` | P2P and store sales |
| Goffs (IRE) | `https://www.goffs.com/sale/IRE/...` | NH and Flat yearling |
| Goffs (UK) | `https://www.goffs.com/sale/UK/...` | UK store sales |
| GoffsGo | `https://www.goffs.com/sale/GoffsGo/...` | Online sales |

---

## Dashboard tabs

- **Lot Browser** — filter by name/sire/sex/score; click any row to expand full detail
- **⭐ My Favourites** — lots you've saved with ☆ Save
- **Sire Leaderboard** — top 20 sires by average score in this sale
- **Price vs Score** — scatter plot of AI estimated price against pedigree score

---

## Score breakdown

Click **Score breakdown** on any lot to see:

- **Sire (50%)** — live ranking + BT% for NH, flat rank for Flat
- **Dam's Sire (30%)** — BroodmareSire ranking for NH, flat rank for Flat
- **2nd Dam's Sire (20%)** — same logic
- **Nick bonus** — documented elite sire × dam's sire pairings add up to +10 pts

---

## Loading historical sale results

Hammer prices from past sales power the **Historical prices** comparables shown per lot.

To add a completed sale:
1. Expand **📊 Historical Sales Data** in the sidebar.
2. Paste the sale URL (e.g. `https://www.goffs.com/sale/IRE/Arkle-Sale-2025`).
3. Click **Load Sale Results**.

Pre-loaded historical data: 26 Goffs NH sales (2022–2025) and 13 Goffs Flat sales (Orby Book 1/2, Autumn Yearling/HIT, Classic Breeze-Up — 2022–2025).
