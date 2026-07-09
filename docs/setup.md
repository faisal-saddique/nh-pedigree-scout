# Setup & Configuration

## Requirements

- Python 3.11+
- PostgreSQL database (Supabase recommended)
- Scrape.do API token (for Goffs lot PDFs)
- Google Gemini API key (default LLM) or alternative

## Environment variables

Create a `.env` file in the project root:

```env
# Required
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Required for Goffs PDF dam records
SCRAPEDO_TOKEN=your_scrapedo_token

# LLM (default: Google Gemini 2.5 Flash)
GOOGLE_API_KEY=your_google_api_key

# Optional overrides
LLM_MODEL=google:gemini-2.5-flash   # or groq:llama-3.3-70b-versatile
LLM_BATCH_SIZE=10                    # lots per AI batch
```

## Install & run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the app
streamlit run app.py --server.port 8502
```

## Load historical data

Run once after setup to populate hammer prices for comparable analysis:

```bash
# NH sales (Goffs NH, 2022–2025) — ~26 sales
python seed_historical.py

# Flat sales (Goffs Orby/HIT/Breeze-Up, 2022–2025) — ~13 sales
python seed_historical_flat.py
```

Both scripts skip already-loaded sales so are safe to re-run.

## Database

The app auto-creates tables on first run (`init_db()`). No manual migration needed.

Key tables:
- `sales` — scraped catalogues
- `lots` — individual horse entries (includes `discipline` column: `'nh'` or `'flat'`)
- `historical_lots` — completed-sale hammer prices for comparables
- `sire_rankings` — cached Stallion Guide rankings (refreshed on each scrape)
