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
"""


def _conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def init_db() -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(_DDL)
        cur.execute("ALTER TABLE lots ADD COLUMN IF NOT EXISTS is_favourite BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE sire_rankings ADD COLUMN IF NOT EXISTS nh_fr_rank INTEGER")


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
