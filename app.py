import time
import altair as alt
import streamlit as st
from dotenv import load_dotenv

import os
from analyser import analyse_lots
from db import (
    get_lots_df,
    get_sales,
    get_unanalysed_lots,
    init_db,
    update_lot_analysis,
    upsert_lots,
    upsert_sale,
)
from scraper import scrape_catalogue

load_dotenv()

st.set_page_config(page_title="NH Pedigree Scout", layout="wide")

# --- DB init ---
try:
    init_db()
except Exception as e:
    st.error(
        f"**Database connection failed:** {e}\n\n"
        "Set `DATABASE_URL=postgresql://user:pass@localhost/dbname` in your `.env` file."
    )
    st.stop()

# --- Session state ---
st.session_state.setdefault("current_sale_id", None)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("NH Pedigree Scout")
    st.caption("National Hunt pedigree analysis tool")
    st.divider()

    catalogue_url = st.text_input(
        "Catalogue URL",
        placeholder="https://www.tattersalls.com/sales-catalogue.php?sale=...",
        help="Paste a Tattersalls or Goffs catalogue URL and click Run.",
    )

    run_btn = st.button(
        "Scrape & Analyse",
        type="primary",
        disabled=not catalogue_url,
    )

    st.divider()

    # Past sales selector
    sales = get_sales()
    if sales:
        st.subheader("Previous Sales")
        sale_options = {s["id"]: s["name"] or s["url"] for s in sales}
        chosen_id = st.selectbox(
            "Load a previous sale",
            options=list(sale_options.keys()),
            format_func=lambda x: sale_options[x],
            label_visibility="collapsed",
        )
        if st.button("Load", key="load_sale"):
            st.session_state.current_sale_id = chosen_id

# ---------------------------------------------------------------------------
# Scrape + Analyse flow
# ---------------------------------------------------------------------------
if run_btn and catalogue_url:
    with st.status("Scraping catalogue...", expanded=True) as status:
        try:
            st.write("Fetching lots from catalogue page...")
            sale_name, lots = scrape_catalogue(catalogue_url)

            if not lots:
                status.update(label="No lots found", state="complete")
                st.warning(
                    f"No lots found in **{sale_name}**. "
                    "The catalogue may not be published yet — try again closer to the sale date."
                )
                st.stop()

            st.write(f"Found **{len(lots)} lots** — saving to database...")
            sale_id = upsert_sale(catalogue_url, sale_name)
            upsert_lots(sale_id, lots)

            st.session_state.current_sale_id = sale_id
            status.update(label=f"Scraped {len(lots)} lots from {sale_name}", state="complete")

        except Exception as e:
            status.update(label="Scrape failed", state="error")
            st.error(str(e))
            st.stop()

    # AI analysis
    unanalysed = get_unanalysed_lots(st.session_state.current_sale_id)
    if unanalysed:
        batch_size = int(os.getenv("LLM_BATCH_SIZE", "10"))
        model = os.getenv("LLM_MODEL", "google:gemini-2.5-flash")
        n_batches = -(-len(unanalysed) // batch_size)  # ceiling division
        progress = st.progress(0, text=f"Analysing {len(unanalysed)} lots in {n_batches} batches via {model}...")

        with st.status(f"Analysing lots...", expanded=True) as status:
            lot_map = {l["lot_number"]: l["id"] for l in unanalysed}
            _start = time.time()

            def on_batch(done: int, total: int) -> None:
                elapsed = time.time() - _start
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (total - done) / rate if rate > 0 else 0
                if remaining > 0:
                    m, s = divmod(int(remaining), 60)
                    eta = f"~{m}m {s:02d}s remaining" if m else f"~{s}s remaining"
                else:
                    eta = ""
                pct = done / total
                text = f"Analysed {done}/{total} lots" + (f" · {eta}" if eta else "") + "..."
                progress.progress(pct, text=text)
                st.write(f"Batch done — {done}/{total} lots analysed")

            try:
                results = analyse_lots(unanalysed, on_batch=on_batch)
                for lot_number, result in results.items():
                    lot_id = lot_map.get(lot_number)
                    if lot_id:
                        update_lot_analysis(lot_id, result.estimated_price_gbp, result.summary)
                progress.progress(1.0, text=f"Done — {len(results)} lots analysed")
                status.update(label=f"Analysis complete — {len(results)} lots done", state="complete")
            except Exception as e:
                status.update(label="Analysis failed", state="error")
                st.error(str(e))

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
sale_id = st.session_state.current_sale_id

if sale_id is None:
    st.info("Paste a catalogue URL in the sidebar and click **Scrape & Analyse** to get started.")
    st.stop()

df = get_lots_df(sale_id)

if df.empty:
    st.warning("No lots found for this sale.")
    st.stop()

# KPI row
analysed_count = int(df["analysed_at"].notna().sum())
avg_score = float(df["pedigree_score"].mean()) if not df["pedigree_score"].isna().all() else 0.0
avg_price = (
    int(df["estimated_price_gbp"].mean())
    if not df["estimated_price_gbp"].isna().all()
    else None
)

with st.container(horizontal=True):
    st.metric("Total Lots", len(df), border=True)
    st.metric("Analysed", analysed_count, border=True)
    st.metric("Avg Pedigree Score", f"{avg_score:.1f}/100", border=True)
    if avg_price:
        st.metric("Avg Est. Price", f"£{avg_price:,}", border=True)

st.divider()

tab_browser, tab_sires, tab_chart = st.tabs(["Lot Browser", "Sire Leaderboard", "Price vs Score"])

# ---------------------------------------------------------------------------
# Tab 1: Lot Browser
# ---------------------------------------------------------------------------
with tab_browser:
    col_search, col_sex = st.columns([3, 1])
    with col_search:
        search = st.text_input("Search by horse name, sire, or dam", placeholder="e.g. Flemensfirth")
    with col_sex:
        sexes = ["All"] + sorted(df["sex"].dropna().unique().tolist())
        sex_filter = st.selectbox("Sex", sexes)

    view = df.copy()
    if search:
        mask = (
            view["horse_name"].str.contains(search, case=False, na=False)
            | view["sire"].str.contains(search, case=False, na=False)
            | view["dam"].str.contains(search, case=False, na=False)
        )
        view = view[mask]
    if sex_filter != "All":
        view = view[view["sex"] == sex_filter]

    display_cols = [
        "lot_number", "horse_name", "year_of_birth", "sex",
        "sire", "dam", "dam_sire", "pedigree_score", "estimated_price_gbp",
    ]
    view = view[display_cols].rename(columns={
        "lot_number": "Lot",
        "horse_name": "Name",
        "year_of_birth": "YOB",
        "sex": "Sex",
        "sire": "Sire",
        "dam": "Dam",
        "dam_sire": "Dam's Sire",
        "pedigree_score": "Score",
        "estimated_price_gbp": "Est. Price (£)",
    })

    event = st.dataframe(
        view,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "Est. Price (£)": st.column_config.NumberColumn(format="£%d"),
        },
    )

    # Show AI summary for selected lot
    if event.selection.rows:
        selected_lot_num = view.iloc[event.selection.rows[0]]["Lot"]
        lot_row = df[df["lot_number"] == selected_lot_num].iloc[0]
        with st.container(border=True):
            st.subheader(f"Lot {lot_row['lot_number']}: {lot_row.get('horse_name') or 'Unnamed'}")
            cols = st.columns(4)
            cols[0].metric("NH Score", f"{lot_row['pedigree_score']:.1f}/100")
            if lot_row["estimated_price_gbp"]:
                cols[1].metric("Est. Price", f"£{lot_row['estimated_price_gbp']:,}")
            cols[2].metric("Sire", lot_row["sire"] or "—")
            cols[3].metric("Dam's Sire", lot_row["dam_sire"] or "—")
            if lot_row["ai_summary"]:
                st.markdown(f"**AI Assessment:** {lot_row['ai_summary']}")
            else:
                st.caption("AI analysis pending.")

# ---------------------------------------------------------------------------
# Tab 2: Sire Leaderboard
# ---------------------------------------------------------------------------
with tab_sires:
    sire_stats = (
        df.groupby("sire", dropna=True)
        .agg(
            lots=("lot_number", "count"),
            avg_score=("pedigree_score", "mean"),
            avg_price=("estimated_price_gbp", "mean"),
        )
        .reset_index()
        .sort_values("avg_score", ascending=False)
        .head(20)
    )
    sire_stats["avg_score"] = sire_stats["avg_score"].round(1)
    sire_stats["avg_price"] = sire_stats["avg_price"].round(0).astype("Int64")

    col_chart, col_table = st.columns([2, 1])

    with col_chart:
        with st.container(border=True):
            st.subheader("Top 20 Sires by NH Score")
            chart = (
                alt.Chart(sire_stats)
                .mark_bar()
                .encode(
                    x=alt.X("avg_score:Q", title="Avg NH Score"),
                    y=alt.Y("sire:N", sort="-x", title=None),
                    tooltip=["sire", "lots", "avg_score", "avg_price"],
                )
            )
            st.altair_chart(chart)

    with col_table:
        with st.container(border=True):
            st.subheader("Sire Stats")
            st.dataframe(
                sire_stats.rename(columns={
                    "sire": "Sire",
                    "lots": "Lots",
                    "avg_score": "Avg Score",
                    "avg_price": "Avg Price (£)",
                }),
                hide_index=True,
                column_config={
                    "Avg Price (£)": st.column_config.NumberColumn(format="£%d"),
                },
            )

# ---------------------------------------------------------------------------
# Tab 3: Price vs Score
# ---------------------------------------------------------------------------
with tab_chart:
    plot_df = df.dropna(subset=["pedigree_score", "estimated_price_gbp"]).copy()

    if plot_df.empty:
        st.info("Run AI analysis to see the Price vs Score chart.")
    else:
        with st.container(border=True):
            st.subheader("Estimated Price vs NH Pedigree Score")
            scatter = (
                alt.Chart(plot_df)
                .mark_circle(size=80, opacity=0.7)
                .encode(
                    x=alt.X("pedigree_score:Q", title="NH Pedigree Score (0–100)"),
                    y=alt.Y("estimated_price_gbp:Q", title="Estimated Price (£)"),
                    color=alt.Color("sex:N", title="Sex"),
                    tooltip=[
                        alt.Tooltip("lot_number:N", title="Lot"),
                        alt.Tooltip("horse_name:N", title="Name"),
                        alt.Tooltip("sire:N", title="Sire"),
                        alt.Tooltip("pedigree_score:Q", title="Score", format=".1f"),
                        alt.Tooltip("estimated_price_gbp:Q", title="Est. Price (£)", format=","),
                    ],
                )
            )
            st.altair_chart(scatter)
