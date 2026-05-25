# NH Pedigree Scout

A National Hunt bloodstock analysis tool for Tattersalls and Goffs store horse sales.

Paste a catalogue URL, click **Scrape & Analyse**, and get every lot scored, priced, and assessed by AI within minutes.

## What it does

- **Scrapes** Tattersalls and Goffs catalogues automatically (handles Cloudflare-protected Goffs pages)
- **Scores** each lot 0–100 using live NH sire rankings pulled from Stallion Guide (NH GB/IRE + NH France + Broodmares)
- **AI analysis** via Gemini — produces a Pros/Cons summary and estimated price range for every lot
- **Lot Browser** — search by name, sire or dam; filter by sex, sire, score range; sort any column
- **My Favourites** — save lots with one click, persisted per sale
- **Sire Leaderboard** — top 20 sires in the sale by average NH score
- **Price vs Score chart** — scatter plot to spot value

## Live app

[https://nh-pedigree-scout.streamlit.app](https://nh-pedigree-scout.streamlit.app)

## Supported sale URLs

| Auction house | Example URL format |
|---|---|
| Tattersalls | `https://www.tattersalls.com/sales/[sale-name]/4DCGI/Sale/[CODE]/Main/Lots/` |
| Goffs | `https://www.goffs.com/sale/IRE/[Sale-Name-Year]` |

## Tech stack

- **Frontend** — Streamlit
- **Database** — PostgreSQL (Supabase)
- **AI** — Google Gemini 2.5 Flash via PydanticAI
- **Sire rankings** — Stallion Guide API (NH GB/IRE, NH France, Broodmares, Flat Europe)
- **Scraping** — httpx + BeautifulSoup (Tattersalls), Scrape.do (Goffs)

## Local setup

```bash
git clone https://github.com/faisal-saddique/nh-pedigree-scout
cd nh-pedigree-scout
uv sync
cp .env.example .env   # fill in your keys
streamlit run app.py
```

Required `.env` variables:

```
DATABASE_URL=postgresql://...
GOOGLE_API_KEY=...
SCRAPEDO_TOKEN=...
LLM_MODEL=google:gemini-2.5-flash
LLM_BATCH_SIZE=10
SCRAPER_BACKEND=scrapedo
```
