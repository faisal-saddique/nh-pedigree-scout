import os
import psycopg2
import psycopg2.extras
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

_DDL = """
CREATE TABLE IF NOT EXISTS sales (
    id          SERIAL PRIMARY KEY,
    url         TEXT UNIQUE NOT NULL,
    name        TEXT,
    scraped_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lots (
    id                  SERIAL PRIMARY KEY,
    sale_id             INT REFERENCES sales(id) ON DELETE CASCADE,
    lot_number          TEXT NOT NULL,
    horse_name          TEXT,
    year_of_birth       INT,
    sex                 TEXT,
    sire                TEXT,
    dam                 TEXT,
    dam_sire            TEXT,
    second_dam_sire     TEXT,
    pedigree_score      FLOAT,
    estimated_price_gbp INT,
    ai_summary          TEXT,
    analysed_at         TIMESTAMP,
    UNIQUE (sale_id, lot_number)
);

CREATE TABLE IF NOT EXISTS sire_rankings (
    name         TEXT PRIMARY KEY,
    nh_rank      INTEGER,
    nh_winners   INTEGER,
    nh_bt_pct    REAL,
    nh_awd       REAL,
    flat_rank    INTEGER,
    flat_winners INTEGER,
    flat_bt_pct  REAL,
    nh_fr_rank   INTEGER,
    nh_bm_rank   INTEGER,
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS historical_lots (
    id            SERIAL PRIMARY KEY,
    sale_url      TEXT NOT NULL,
    sale_name     TEXT,
    lot_number    TEXT,
    sire          TEXT,
    dam           TEXT,
    sex           TEXT,
    year_of_birth INT,
    price         INT,
    currency      TEXT DEFAULT 'EUR',
    outcome       TEXT,
    created_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE(sale_url, lot_number)
);
"""


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_db() -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("ALTER TABLE lots ADD COLUMN IF NOT EXISTS is_favourite BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE sire_rankings ADD COLUMN IF NOT EXISTS nh_fr_rank INTEGER")
        cur.execute("ALTER TABLE lots ADD COLUMN IF NOT EXISTS dam_records JSONB")
        cur.execute("ALTER TABLE lots ADD COLUMN IF NOT EXISTS dam_production_score FLOAT")
        cur.execute("ALTER TABLE lots ADD COLUMN IF NOT EXISTS pdf_url TEXT")
        cur.execute("ALTER TABLE lots ADD COLUMN IF NOT EXISTS pdf_scraped_at TIMESTAMP")


def upsert_sale(url: str, name: str) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sales (url, name) VALUES (%s, %s)
            ON CONFLICT (url) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (url, name),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def upsert_lots(sale_id: int, lots: list[dict]) -> None:
    with _conn() as conn, conn.cursor() as cur:
        for lot in lots:
            cur.execute(
                """
                INSERT INTO lots (
                    sale_id, lot_number, horse_name, year_of_birth, sex,
                    sire, dam, dam_sire, second_dam_sire, pedigree_score
                ) VALUES (
                    %(sale_id)s, %(lot_number)s, %(horse_name)s, %(year_of_birth)s, %(sex)s,
                    %(sire)s, %(dam)s, %(dam_sire)s, %(second_dam_sire)s, %(pedigree_score)s
                )
                ON CONFLICT (sale_id, lot_number) DO UPDATE SET
                    horse_name      = EXCLUDED.horse_name,
                    year_of_birth   = EXCLUDED.year_of_birth,
                    sex             = EXCLUDED.sex,
                    sire            = EXCLUDED.sire,
                    dam             = EXCLUDED.dam,
                    dam_sire        = EXCLUDED.dam_sire,
                    second_dam_sire = EXCLUDED.second_dam_sire,
                    pedigree_score  = EXCLUDED.pedigree_score
                """,
                {**lot, "sale_id": sale_id},
            )


def update_lot_pdf_data(lot_id: int, dam_records: dict, dam_production_score: float, pdf_url: str) -> None:
    import json
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE lots
            SET dam_records = %s,
                dam_production_score = %s,
                pdf_url = %s,
                pdf_scraped_at = NOW()
            WHERE id = %s
            """,
            (json.dumps({str(k): v for k, v in dam_records.items()}), dam_production_score, pdf_url, lot_id),
        )


def get_lots_without_pdf(sale_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM lots WHERE sale_id = %s AND pdf_scraped_at IS NULL ORDER BY lot_number::int NULLS LAST",
                (sale_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def update_lot_analysis(lot_id: int, estimated_price_gbp: int, ai_summary: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE lots
            SET estimated_price_gbp = %s, ai_summary = %s, analysed_at = NOW()
            WHERE id = %s
            """,
            (estimated_price_gbp, ai_summary, lot_id),
        )


def get_unanalysed_lots(sale_id: int) -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM lots WHERE sale_id = %s AND analysed_at IS NULL ORDER BY lot_number",
                (sale_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_lots_df(sale_id: int) -> pd.DataFrame:
    with _conn() as conn:
        return pd.read_sql(
            "SELECT * FROM lots WHERE sale_id = %s ORDER BY lot_number::int NULLS LAST",
            conn,
            params=(sale_id,),
        )


def toggle_favourite(lot_id: int) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE lots SET is_favourite = NOT is_favourite WHERE id = %s", (lot_id,))


def upsert_sire_rankings(rankings: dict[str, dict]) -> None:
    with _conn() as conn, conn.cursor() as cur:
        for name, r in rankings.items():
            cur.execute(
                """
                INSERT INTO sire_rankings
                    (name, nh_rank, nh_winners, nh_bt_pct, nh_awd,
                     nh_fr_rank, flat_rank, flat_winners, flat_bt_pct, nh_bm_rank, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (name) DO UPDATE SET
                    nh_rank=EXCLUDED.nh_rank, nh_winners=EXCLUDED.nh_winners,
                    nh_bt_pct=EXCLUDED.nh_bt_pct, nh_awd=EXCLUDED.nh_awd,
                    nh_fr_rank=EXCLUDED.nh_fr_rank,
                    flat_rank=EXCLUDED.flat_rank, flat_winners=EXCLUDED.flat_winners,
                    flat_bt_pct=EXCLUDED.flat_bt_pct, nh_bm_rank=EXCLUDED.nh_bm_rank,
                    updated_at=NOW()
                """,
                (
                    name, r.get("nh_rank"), r.get("nh_winners"), r.get("nh_bt_pct"),
                    r.get("nh_awd"), r.get("nh_fr_rank"), r.get("flat_rank"),
                    r.get("flat_winners"), r.get("flat_bt_pct"), r.get("nh_bm_rank"),
                ),
            )


def get_sire_rankings() -> dict[str, dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM sire_rankings")
            return {r["name"]: dict(r) for r in cur.fetchall()}


def get_sales() -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM sales ORDER BY scraped_at DESC")
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Historical lots (hammer prices from completed sales)
# ---------------------------------------------------------------------------

def upsert_historical_lots(sale_url: str, sale_name: str, lots: list[dict]) -> int:
    """Store completed-sale lots with hammer prices. Returns count inserted/updated."""
    count = 0
    with _conn() as conn, conn.cursor() as cur:
        for lot in lots:
            price = lot.get("price")
            outcome = lot.get("outcome")
            if not price or not outcome or outcome == "withdrawn":
                continue
            cur.execute(
                """
                INSERT INTO historical_lots
                    (sale_url, sale_name, lot_number, sire, dam, sex,
                     year_of_birth, price, currency, outcome)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (sale_url, lot_number) DO UPDATE SET
                    price    = EXCLUDED.price,
                    currency = EXCLUDED.currency,
                    outcome  = EXCLUDED.outcome
                """,
                (
                    sale_url, sale_name,
                    lot.get("lot_number"), lot.get("sire"), lot.get("dam"),
                    lot.get("sex"), lot.get("year_of_birth"),
                    price, lot.get("currency", "EUR"), outcome,
                ),
            )
            count += 1
    return count


def get_sire_comparables(sire_name: str) -> dict | None:
    """
    Return price stats for sold lots by this sire from historical data.
    Uses only outcome='sold' lots. Returns None if fewer than 3 data points.
    """
    if not sire_name:
        return None
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    currency,
                    COUNT(*)                                                         AS count,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price)::INT          AS median,
                    MIN(price)                                                        AS min_price,
                    MAX(price)                                                        AS max_price,
                    ARRAY_AGG(DISTINCT sale_name ORDER BY sale_name)                 AS sale_names
                FROM historical_lots
                WHERE LOWER(TRIM(sire)) = LOWER(TRIM(%s))
                  AND outcome = 'sold'
                  AND price > 0
                GROUP BY currency
                ORDER BY count DESC
                LIMIT 1
                """,
                (sire_name,),
            )
            row = cur.fetchone()
            if not row or row["count"] < 3:
                return None
            return dict(row)


def get_historical_sales() -> list[dict]:
    """Return list of distinct sales loaded into historical_lots with lot counts."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT sale_url, sale_name,
                       COUNT(*) AS lot_count,
                       MAX(created_at) AS loaded_at
                FROM historical_lots
                GROUP BY sale_url, sale_name
                ORDER BY loaded_at DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def has_historical_sale(url: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM historical_lots WHERE sale_url = %s LIMIT 1", (url,))
            return cur.fetchone() is not None
