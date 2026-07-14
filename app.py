import json
import time
import altair as alt
import streamlit as st
from dotenv import load_dotenv

import os
import scorer
from scorer import score_lot_with_breakdown
from analyser import analyse_lots
from db import (
    get_historical_sales,
    get_lots_df,
    delete_sale,
    get_lots_without_pdf,
    get_sales,
    get_sire_comparables,
    get_sire_rankings,
    get_unanalysed_lots,
    has_historical_sale,
    init_db,
    toggle_favourite,
    update_lot_analysis,
    update_lot_pdf_data,
    upsert_historical_lots,
    upsert_lots,
    upsert_sale,
    upsert_sire_rankings,
)
from scraper import detect_site, fetch_lot_pdf_text, scrape_catalogue, scrape_goffs, scrape_tattersalls
from stallionguide import fetch_rankings
from pdf_parser import parse_pedigree_pdf_text, score_dam_production

load_dotenv()

st.set_page_config(page_title="NH Pedigree Scout", layout="wide", page_icon="nh-pedigree-scout-logo.png")

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
    ).strip()

    run_btn = st.button(
        "Scrape & Analyse",
        type="primary",
        disabled=not catalogue_url,
    )

    st.divider()

    # Historical sales data
    with st.expander("📊 Historical Sales Data"):
        hist_sales = get_historical_sales()
        if hist_sales:
            st.caption(f"{sum(s['lot_count'] for s in hist_sales):,} lots across {len(hist_sales)} past sales loaded")
            for hs in hist_sales[:5]:
                st.caption(f"• {hs['sale_name'] or hs['sale_url']} ({hs['lot_count']} lots)")
        else:
            st.caption("No historical data loaded yet.")

        hist_url = st.text_input(
            "Past sale URL",
            placeholder="https://www.goffs.com/sale/IRE/Arkle-Sale-2025",
            key="hist_url_input",
            label_visibility="collapsed",
        )
        load_hist_btn = st.button("Load Sale Results", key="load_hist", disabled=not hist_url)

        with st.expander("Suggested past sales"):
            st.markdown(
                "**Goffs (Ireland — EUR)**\n"
                "- `https://www.goffs.com/sale/IRE/Arkle-Sale-2025`\n"
                "- `https://www.goffs.com/sale/IRE/Arkle-Sale-Part-2-2025`\n"
                "- `https://www.goffs.com/sale/IRE/Arkle-Sale-2024`\n"
                "- `https://www.goffs.com/sale/IRE/Arkle-Sale-Part-2-2024`\n"
                "- `https://www.goffs.com/sale/IRE/Arkle-Sale-2023`\n\n"
                "**Goffs (UK — GBP)**\n"
                "- `https://www.goffs.com/sale/UK/Summer-Sale-2025`\n"
                "- `https://www.goffs.com/sale/UK/Summer-Sale-2024`\n\n"
                "**GoffsGo (GBP)**\n"
                "- `https://www.goffs.com/sale/GoffsGo/GoffsGo-June-Sale`\n\n"
                "**Tattersalls IE (EUR — paste shell URL)**\n"
                "- Craig's URL format: `https://www.tattersalls.ie/sales/.../4DCGI/Sale/P2P26/Main/Lots`"
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
        def _do_load(sid):
            st.session_state.current_sale_id = sid

        def _do_delete(sid):
            delete_sale(sid)
            if st.session_state.current_sale_id == sid:
                st.session_state.current_sale_id = None

        col_load, col_del = st.columns([3, 1])
        col_load.button(
            "Load",
            key="load_sale",
            use_container_width=True,
            on_click=_do_load,
            args=(chosen_id,),
        )
        col_del.button(
            "🗑",
            key="del_sale",
            use_container_width=True,
            help="Delete this sale",
            on_click=_do_delete,
            args=(chosen_id,),
        )

# ---------------------------------------------------------------------------
# Load historical sale results
# ---------------------------------------------------------------------------
if load_hist_btn and hist_url:
    hist_url_clean = hist_url.strip()
    if has_historical_sale(hist_url_clean):
        st.sidebar.info(f"Already loaded: {hist_url_clean}")
    else:
        with st.sidebar.status("Loading historical sale...", expanded=True) as hist_status:
            try:
                site = detect_site(hist_url_clean)
                token = os.getenv("SCRAPEDO_TOKEN")
                if site == "goffs":
                    hist_name, hist_lots = scrape_goffs(hist_url_clean, token)
                else:
                    hist_name, hist_lots = scrape_tattersalls(hist_url_clean)
                n = upsert_historical_lots(hist_url_clean, hist_name, hist_lots)
                priced = sum(1 for l in hist_lots if l.get("price"))
                hist_status.update(
                    label=f"Loaded {n} priced lots from {hist_name}",
                    state="complete",
                )
            except Exception as e:
                hist_status.update(label="Failed", state="error")
                st.sidebar.error(str(e))

# ---------------------------------------------------------------------------
# Scrape + Analyse flow
# ---------------------------------------------------------------------------
if run_btn and catalogue_url:
    catalogue_url = catalogue_url.strip()
    with st.status("Scraping catalogue...", expanded=True) as status:
        try:
            st.write("Refreshing sire rankings from Stallion Guide...")
            try:
                rankings = fetch_rankings()
                upsert_sire_rankings(rankings)
                scorer.load_rankings(rankings)
                st.write(f"Rankings updated — {len(rankings)} sires loaded.")
            except Exception as rank_err:
                st.warning(f"Could not refresh rankings ({rank_err}). Using cached data.")
                scorer.load_rankings(get_sire_rankings())

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

            # Auto-store hammer prices if this is a completed sale
            priced_lots = [l for l in lots if l.get("price") and l.get("outcome") and l["outcome"] != "withdrawn"]
            if priced_lots:
                n_stored = upsert_historical_lots(catalogue_url, sale_name, priced_lots)
                st.write(f"Stored **{n_stored}** hammer prices in historical database.")

            st.session_state.current_sale_id = sale_id
            status.update(label=f"Scraped {len(lots)} lots from {sale_name}", state="complete")

        except Exception as e:
            status.update(label="Scrape failed", state="error")
            st.error(str(e))
            st.stop()

    # PDF dam records enrichment (Goffs only — needs individual lot pages via Scrape.do)
    if "goffs.com" in catalogue_url:
        pending_pdf = get_lots_without_pdf(st.session_state.current_sale_id)
        if pending_pdf:
            scrapedo_token = os.getenv("SCRAPEDO_TOKEN")
            n_pending = len(pending_pdf)
            pdf_progress = st.progress(0, text=f"Fetching dam records for {n_pending} lots via PDF...")

            with st.status("Enriching with dam records from PDFs...", expanded=True) as pdf_status:
                done_pdf = 0
                failed_pdf = 0
                _cat_base = catalogue_url.split("?")[0].rstrip("/")
                if "/lots" in _cat_base:
                    _cat_base = _cat_base.rsplit("/lots", 1)[0]

                for lot in pending_pdf:
                    lot_page_url = f"{_cat_base}/lots/{lot['lot_number']}"
                    pdf_url, pdf_text = fetch_lot_pdf_text(lot_page_url, scrapedo_token)
                    if pdf_text:
                        dam_recs = parse_pedigree_pdf_text(pdf_text)
                        prod_score = score_dam_production(dam_recs)
                        update_lot_pdf_data(lot["id"], dam_recs, prod_score, pdf_url or "")
                        done_pdf += 1
                    else:
                        failed_pdf += 1

                    pct = (done_pdf + failed_pdf) / n_pending
                    pdf_progress.progress(pct, text=f"Dam records: {done_pdf}/{n_pending} fetched...")

                label = f"Dam records fetched — {done_pdf} enriched"
                if failed_pdf:
                    label += f", {failed_pdf} skipped (withdrawn/no PDF)"
                pdf_status.update(label=label, state="complete")
            pdf_progress.progress(1.0, text="Dam records complete")

    # Detect sale type from URL for tailored AI prompt and comparables filtering
    _url_lower = catalogue_url.lower()
    if any(p in _url_lower for p in ("breeze-up", "breezeup", "breeze_up")):
        _sale_type = "breeze_up"
    elif any(p in _url_lower for p in ("horses-in-training", "horses_in_training", "hit-sale", "/ght", "/aht", "/mht")):
        _sale_type = "hit"
    else:
        _sale_type = "standard"

    # AI analysis
    unanalysed = get_unanalysed_lots(st.session_state.current_sale_id)
    if unanalysed:
        # Attach historical comparables per sire, filtered by sale type
        _comp_cache: dict = {}
        for lot in unanalysed:
            sire = lot.get("sire") or ""
            if sire not in _comp_cache:
                _comp_cache[sire] = get_sire_comparables(sire, sale_type=_sale_type)
            lot["historical_comps"] = _comp_cache[sire]

        batch_size = int(os.getenv("LLM_BATCH_SIZE", "10"))
        model = os.getenv("LLM_MODEL", "google:gemini-2.5-flash")
        n_batches = -(-len(unanalysed) // batch_size)  # ceiling division
        sale_type_label = " (Breeze-Up mode)" if _sale_type == "breeze_up" else " (HIT mode)" if _sale_type == "hit" else ""
        progress = st.progress(0, text=f"Analysing {len(unanalysed)} lots in {n_batches} batches via {model}{sale_type_label}...")

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
                results = analyse_lots(unanalysed, on_batch=on_batch, sale_type=_sale_type)
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

tab_browser, tab_favourites, tab_sires, tab_chart = st.tabs(["Lot Browser", "⭐ My Favourites", "Sire Leaderboard", "Price vs Score"])

# ---------------------------------------------------------------------------
# Tab 1: Lot Browser
# ---------------------------------------------------------------------------
def _lot_detail(lot_row, key_prefix: str = "") -> None:
    """Render the expanded lot detail panel with favourite toggle and score breakdown."""
    discipline = str(lot_row.get("discipline") or "nh").lower()
    disc_badge = "🏇 Flat" if discipline == "flat" else "🦘 NH"
    score_label = "Flat Score" if discipline == "flat" else "NH Score"

    with st.container(border=True):
        col_title, col_disc, col_fav = st.columns([4, 1, 1])
        with col_title:
            st.subheader(f"Lot {lot_row['lot_number']}: {lot_row.get('horse_name') or 'Unnamed'}")
        with col_disc:
            st.markdown(f"**{disc_badge}**")
        with col_fav:
            is_fav = bool(lot_row.get("is_favourite", False))
            label = "⭐ Saved" if is_fav else "☆ Save"
            if st.button(label, key=f"{key_prefix}fav_{lot_row['lot_number']}"):
                toggle_favourite(int(lot_row["id"]))
                st.rerun()

        _dam_prod = lot_row.get("dam_production_score")
        _has_prod = _dam_prod is not None and str(_dam_prod) not in ("nan", "None", "")
        n_cols = 5 if _has_prod else 4
        cols = st.columns(n_cols)
        cols[0].metric(score_label, f"{lot_row['pedigree_score']:.1f}/100")
        if lot_row["estimated_price_gbp"]:
            cols[1].metric("Est. Price", f"£{lot_row['estimated_price_gbp']:,}")
        if _has_prod:
            cols[2].metric("Dam Production", f"{float(_dam_prod):.1f}/10")
        def _disp(v): return v if isinstance(v, str) and v.strip() else "—"
        cols[-2].markdown(f"**Sire**\n\n{_disp(lot_row.get('sire'))}")
        cols[-1].markdown(f"**Dam's Sire**\n\n{_disp(lot_row.get('dam_sire'))}")

        # Score breakdown
        _, bd = score_lot_with_breakdown(
            lot_row.get("sire"),
            lot_row.get("dam_sire"),
            lot_row.get("second_dam_sire"),
            discipline=discipline,
        )
        with st.expander("Score breakdown"):
            b1, b2, b3, b4 = st.columns(4)

            if discipline == "flat":
                sire_rank_label = (
                    f"Flat rank #{bd['sire_flat_rank']}" if bd["sire_flat_rank"]
                    else "Not in live flat rankings"
                )
                bt_label = f" · {bd['sire_flat_bt_pct']:.1f}% BTW" if bd.get("sire_flat_bt_pct") else ""
            else:
                sire_rank_label = (
                    f"NH rank #{bd['sire_nh_rank']}" if bd["sire_nh_rank"]
                    else f"NH FR rank #{bd['sire_nh_fr_rank']}" if bd["sire_nh_fr_rank"]
                    else "Not in live rankings"
                )
                bt_label = f" · {bd['sire_nh_awd']:.1f}f avg" if bd["sire_nh_awd"] else ""
            b1.metric(
                "Sire (50%)",
                f"{bd['sire_contribution']:.1f} pts",
                help=f"{bd['sire_name']}\n{sire_rank_label}{bt_label}\nSource: {bd['sire_source']}",
            )

            if discipline == "flat":
                ds_rank_label = f"Flat rank #{bd['dam_sire_flat_rank']}" if bd["dam_sire_flat_rank"] else "Not in flat rankings"
                b2.metric(
                    "Dam's Sire (30%)",
                    f"{bd['dam_sire_contribution']:.1f} pts",
                    help=f"{bd['dam_sire_name']}\n{ds_rank_label}\nSource: {bd['dam_sire_source']}",
                )
            else:
                bm_rank_label = f"NH BM rank #{bd['dam_sire_nh_bm_rank']}" if bd["dam_sire_nh_bm_rank"] else "Not in BM rankings"
                b2.metric(
                    "Dam's Sire (30%)",
                    f"{bd['dam_sire_contribution']:.1f} pts",
                    help=f"{bd['dam_sire_name']}\n{bm_rank_label} · {bd['dam_sire_bm_tier']}\nSource: {bd['dam_sire_source']}",
                )

            b3.metric(
                "2nd Dam's Sire (20%)",
                f"{bd['second_dam_sire_contribution']:.1f} pts",
                help=f"{bd['second_dam_sire_name']}\nSource: {bd['second_dam_sire_source']}",
            )

            if bd["nick_score"] > 0:
                b4.metric(
                    "Nick bonus",
                    f"+{bd['nick_bonus']:.1f} pts",
                    help=f"{bd['sire_name']} × {bd['dam_sire_name']}\n{bd['nick_description']}",
                )
            else:
                b4.metric(
                    "Nick bonus",
                    "+0 pts",
                    help="No documented elite nick for this sire × dam's sire pairing." if lot_row.get("dam_sire") else "Dam's sire unknown — nick analysis unavailable.",
                )

            total_with_nick = round(min(100.0, bd["base_score"] + bd["nick_bonus"]), 1)
            if bd["nick_bonus"] > 0:
                st.caption(
                    f"Base score: {bd['base_score']:.1f} · Nick bonus: +{bd['nick_bonus']:.1f} · "
                    f"Adjusted: **{total_with_nick:.1f}/100** ✦ {bd['nick_description'].split(' — ')[0]}"
                )
            else:
                st.caption(
                    f"Sire {bd['sire_contribution']:.1f} + Dam's sire {bd['dam_sire_contribution']:.1f} + "
                    f"2nd dam's sire {bd['second_dam_sire_contribution']:.1f} = {bd['base_score']:.1f}/100"
                )

        # Dam records (from PDF enrichment)
        dam_records_raw = lot_row.get("dam_records")
        _has_dam_records = dam_records_raw is not None and dam_records_raw is not float("nan") and str(dam_records_raw) not in ("nan", "None", "")
        if _has_dam_records:
            dam_records = dam_records_raw if isinstance(dam_records_raw, dict) else json.loads(dam_records_raw)
            _dam_labels = {"1": "1st Dam", "2": "2nd Dam", "3": "3rd Dam", "4": "4th Dam"}
            with st.expander("Dam records (from PDF)"):
                for dam_key in ["1", "2", "3", "4"]:
                    dam = dam_records.get(dam_key)
                    if not dam:
                        continue
                    name = dam.get("name") or "Unknown"
                    label = _dam_labels[dam_key]

                    # Own record summary
                    if dam.get("unraced") and dam.get("own_wins", 0) == 0:
                        own_str = "Unraced"
                    elif dam.get("own_wins", 0) == 0:
                        own_str = "Placed only"
                    else:
                        own_str = f"{dam['own_wins']} win{'s' if dam['own_wins'] != 1 else ''}"
                        if dam.get("prize_money"):
                            own_str += f" · £{dam['prize_money']:,}"

                    grade_parts = []
                    if dam.get("gr1", 0) > 0:
                        grade_parts.append(f"Gr.1×{dam['gr1']}")
                    if dam.get("gr2", 0) > 0:
                        grade_parts.append(f"Gr.2×{dam['gr2']}")
                    if dam.get("gr3", 0) > 0:
                        grade_parts.append(f"Gr.3×{dam['gr3']}")
                    if dam.get("listed", 0) > 0:
                        grade_parts.append(f"L.×{dam['listed']}")
                    grade_str = " ".join(grade_parts) if grade_parts else ""

                    # Production
                    foals, runners, winners = dam.get("foals", 0), dam.get("runners", 0), dam.get("winners", 0)
                    if foals > 0:
                        pct = dam.get("winners_pct", 0)
                        prod_str = f"{foals} foals · {runners} runners · **{winners} winners** ({pct:.0f}%)"
                    else:
                        prod_str = "No production data"

                    st.markdown(
                        f"**{label}** — {name}\n\n"
                        f"Record: {own_str}{' · ' + grade_str if grade_str else ''}\n\n"
                        f"Production: {prod_str}"
                    )
                    if dam_key != "4":
                        st.divider()

                prod_score = lot_row.get("dam_production_score")
                if prod_score is not None:
                    st.caption(f"Dam production quality score: **{prod_score:.1f}/10**")

        # Historical price comparables
        sire = lot_row.get("sire")
        if sire:
            comps = get_sire_comparables(sire)
            if comps:
                sym = "£" if comps.get("currency") == "GBP" else "€"
                with st.expander(f"Historical prices — {sire}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Median (sold)", f"{sym}{comps['median']:,}")
                    c2.metric("Range", f"{sym}{comps['min_price']:,} – {sym}{comps['max_price']:,}")
                    c3.metric("Sold lots", comps["count"])
                    sales_str = ", ".join((comps.get("sale_names") or [])[:4])
                    st.caption(f"From: {sales_str}")

        if lot_row["ai_summary"]:
            st.markdown(lot_row["ai_summary"])
        else:
            st.caption("AI analysis pending.")


_DISPLAY_COLS = [
    "lot_number", "horse_name", "year_of_birth", "sex",
    "sire", "dam", "dam_sire", "discipline", "pedigree_score", "estimated_price_gbp",
]
_COL_LABELS = {
    "lot_number": "Lot", "horse_name": "Name", "year_of_birth": "YOB",
    "sex": "Sex", "sire": "Sire", "dam": "Dam", "dam_sire": "Dam's Sire",
    "discipline": "Type", "pedigree_score": "Score", "estimated_price_gbp": "Est. Price (£)",
}
_DF_CONFIG = {
    "Score": st.column_config.NumberColumn(format="%.1f"),
    "Est. Price (£)": st.column_config.NumberColumn(format="£%d"),
}


with tab_browser:
    # Primary search row
    s_col, sex_col = st.columns([4, 1])
    with s_col:
        search = st.text_input("Search", placeholder="Horse name, sire or dam...", label_visibility="collapsed")
    with sex_col:
        sexes = ["All"] + sorted(df["sex"].dropna().unique().tolist())
        sex_filter = st.selectbox("Sex", sexes, label_visibility="collapsed")

    with st.expander("More filters"):
        sire_col, score_col = st.columns(2)
        with sire_col:
            all_sires = sorted(df["sire"].dropna().unique().tolist())
            sire_filter = st.multiselect("Sire", all_sires, placeholder="All sires")
        with score_col:
            score_range = st.slider("Score", 0.0, 100.0, (0.0, 100.0), step=1.0)

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
    if sire_filter:
        view = view[view["sire"].isin(sire_filter)]
    view = view[
        view["pedigree_score"].isna()
        | ((view["pedigree_score"] >= score_range[0]) & (view["pedigree_score"] <= score_range[1]))
    ]

    event = st.dataframe(
        view[_DISPLAY_COLS].rename(columns=_COL_LABELS),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config=_DF_CONFIG,
    )

    if event.selection.rows:
        selected_lot_num = view[_DISPLAY_COLS].rename(columns=_COL_LABELS).iloc[event.selection.rows[0]]["Lot"]
        lot_row = df[df["lot_number"] == selected_lot_num].iloc[0]
        _lot_detail(lot_row, key_prefix="browser_")

# ---------------------------------------------------------------------------
# Tab 2: My Favourites
# ---------------------------------------------------------------------------
with tab_favourites:
    fav_df = df[df["is_favourite"] == True] if "is_favourite" in df.columns else df.iloc[0:0]
    if fav_df.empty:
        st.info("No favourites saved yet. Click ☆ Save on any lot to add it here.")
    else:
        fav_event = st.dataframe(
            fav_df[_DISPLAY_COLS].rename(columns=_COL_LABELS),
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config=_DF_CONFIG,
        )
        if fav_event.selection.rows:
            selected = fav_df[_DISPLAY_COLS].rename(columns=_COL_LABELS).iloc[fav_event.selection.rows[0]]["Lot"]
            lot_row = df[df["lot_number"] == selected].iloc[0]
            _lot_detail(lot_row, key_prefix="fav_")

# ---------------------------------------------------------------------------
# Tab 3: Sire Leaderboard
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
            st.subheader("Top 20 Sires by Score")
            chart = (
                alt.Chart(sire_stats)
                .mark_bar()
                .encode(
                    x=alt.X("avg_score:Q", title="Avg Score"),
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
            st.subheader("Estimated Price vs Pedigree Score")
            scatter = (
                alt.Chart(plot_df)
                .mark_circle(size=80, opacity=0.7)
                .encode(
                    x=alt.X("pedigree_score:Q", title="Pedigree Score (0–100)"),
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
