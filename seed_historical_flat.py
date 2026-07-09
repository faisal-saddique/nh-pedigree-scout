"""
Seed historical_lots with Goffs flat yearling & HIT sales (Orby Book 1/2, Autumn HIT).
These provide real hammer prices for Flat-bred horses.
Run: .venv/bin/python3 seed_historical_flat.py
"""
import os, sys, time
sys.path.insert(0, ".")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from scraper import scrape_goffs
from db import upsert_historical_lots, has_historical_sale

TOKEN = os.environ["SCRAPEDO_TOKEN"]

FLAT_SALES = [
    # --- Goffs IRE: Orby Sale (premier flat yearling sale) ---
    "https://www.goffs.com/sale/IRE/orby-sale-2025",
    "https://www.goffs.com/sale/IRE/Orby-Book-2-2025",
    "https://www.goffs.com/sale/IRE/orby-book-1-2024",
    "https://www.goffs.com/sale/IRE/orby-book-2-2024",
    "https://www.goffs.com/sale/IRE/orby-sale-2023",
    "https://www.goffs.com/sale/IRE/orby-book-2",
    "https://www.goffs.com/sale/IRE/orby-sale-2022",
    # --- Goffs IRE: Autumn HIT Sale (flat yearlings) ---
    "https://www.goffs.com/sale/IRE/autumn-yearling-hit-sale-2025",
    "https://www.goffs.com/sale/IRE/autumn-yearling-hit-sale-2024",
    "https://www.goffs.com/sale/IRE/autumn-yearling-sale-2023",
    "https://www.goffs.com/sale/IRE/autumn-HIT-sale-2023",
    "https://www.goffs.com/sale/IRE/autumn-hit-yearling-sale",
    # --- Goffs IRE: Classic Breeze-Up Sale ---
    "https://www.goffs.com/sale/IRE/classic-breeze-up-sale-2025",
]


def run():
    total_upserted = 0
    skipped = 0
    failed = []

    for i, url in enumerate(FLAT_SALES, 1):
        if has_historical_sale(url):
            print(f"[{i:02d}/{len(FLAT_SALES)}] SKIP (already loaded)  {url}")
            skipped += 1
            continue

        print(f"[{i:02d}/{len(FLAT_SALES)}] Scraping ...  {url}")
        try:
            sale_name, lots = scrape_goffs(url, TOKEN)
            sold = [l for l in lots if l.get("outcome") == "sold" and l.get("price")]
            n = upsert_historical_lots(url, sale_name, lots)
            total_upserted += n
            print(f"           → {sale_name}: {len(lots)} lots, {len(sold)} sold, {n} upserted")
        except Exception as e:
            print(f"           ✗ FAILED: {e}")
            failed.append(url)

        if i < len(FLAT_SALES):
            time.sleep(1)

    print(f"\n=== Done ===")
    print(f"Upserted: {total_upserted} lots | Skipped: {skipped} sales | Failed: {len(failed)}")
    if failed:
        print("Failed URLs:")
        for u in failed:
            print(f"  {u}")


if __name__ == "__main__":
    run()
