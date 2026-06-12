"""
One-shot script to bulk-seed historical_lots from 26 confirmed Goffs NH sales.
Run: .venv/bin/python3 seed_historical.py
"""
import os, sys, time
sys.path.insert(0, ".")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from scraper import scrape_goffs
from db import upsert_historical_lots, has_historical_sale

TOKEN = os.environ["SCRAPEDO_TOKEN"]

SALES = [
    # --- Goffs IRE: Arkle Sale (main autumn NH sale) ---
    "https://www.goffs.com/sale/IRE/Arkle-Sale-2025",
    "https://www.goffs.com/sale/IRE/Arkle-Sale-Part-2-2025",
    "https://www.goffs.com/sale/IRE/arkle-sale-part-1-2024",
    "https://www.goffs.com/sale/IRE/arkle-sale-part-2-2024",
    "https://www.goffs.com/sale/IRE/arkle-sale-part1-2023",
    "https://www.goffs.com/sale/IRE/arkle-sale-part2-2023",
    # --- Goffs IRE: December National Hunt Sale ---
    "https://www.goffs.com/sale/IRE/december-nh-sale-2024",
    "https://www.goffs.com/sale/IRE/december-national-hunt-sale-2023",
    "https://www.goffs.com/sale/IRE/december-national-hunt-sale-2022",
    "https://www.goffs.com/sale/IRE/december-nh-sale-2021",
    "https://www.goffs.com/sale/IRE/december-nh-sale-2020",
    # --- Goffs IRE: Land Rover Sale (June NH) ---
    "https://www.goffs.com/sale/IRE/land-rover-sale-2022-part-1",
    "https://www.goffs.com/sale/IRE/land-rover-sale-part-2-2022",
    "https://www.goffs.com/sale/IRE/land-rover-sale-2021",
    "https://www.goffs.com/sale/IRE/land-rover-sale-2021-part-2",
    "https://www.goffs.com/sale/IRE/land-rover-sale-2020",
    "https://www.goffs.com/sale/IRE/land-rover-sale-2020-part-1",
    # --- Goffs IRE: Sportsman's Sale ---
    "https://www.goffs.com/sale/IRE/sportsmans-sale-2022",
    "https://www.goffs.com/sale/IRE/sportsmans-sale-2021",
    "https://www.goffs.com/sale/IRE/sportsmans-sale-2020",
    # --- Goffs UK: Summer Sale ---
    "https://www.goffs.com/sale/UK/Summer-Sale-2025",
    "https://www.goffs.com/sale/UK/Summer-Sale-2024",
    # --- Goffs UK: Spring Store Sale ---
    "https://www.goffs.com/sale/UK/spring-store-sale-2025",
    "https://www.goffs.com/sale/UK/spring-store-sale-2024",
    "https://www.goffs.com/sale/UK/spring-store-sale-2023",
    # --- Goffs UK: Autumn NH Foal Sale ---
    "https://www.goffs.com/sale/UK/autumn-nh-foal-sale-2023",
]

def run():
    total_upserted = 0
    skipped = 0
    failed = []

    for i, url in enumerate(SALES, 1):
        if has_historical_sale(url):
            print(f"[{i:02d}/{len(SALES)}] SKIP (already loaded)  {url}")
            skipped += 1
            continue

        print(f"[{i:02d}/{len(SALES)}] Scraping ...  {url}")
        try:
            sale_name, lots = scrape_goffs(url, TOKEN)
            sold = [l for l in lots if l.get("outcome") == "sold" and l.get("price")]
            n = upsert_historical_lots(url, sale_name, lots)
            total_upserted += n
            print(f"           → {sale_name}: {len(lots)} lots, {len(sold)} sold, {n} upserted")
        except Exception as e:
            print(f"           ✗ FAILED: {e}")
            failed.append(url)

        # Be polite: 1s between requests
        if i < len(SALES):
            time.sleep(1)

    print(f"\n=== Done ===")
    print(f"Upserted: {total_upserted} lots | Skipped: {skipped} sales | Failed: {len(failed)}")
    if failed:
        print("Failed URLs:")
        for u in failed:
            print(f"  {u}")

if __name__ == "__main__":
    run()
