"""Multi-Bagger Patterns — Screener.in + Yahoo screener UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from multibagger import CURATED_NSE_LABEL, SCAN_SOURCES
from multibagger_patterns_screener import (
    META,
    RANK_OPTIONS,
    TAILWIND_KEYWORDS,
    MultibaggerPatternFilters,
    result_to_row,
    scan_multibagger_patterns,
    sort_mb_pattern_results,
)
from pe_history_ui import render_pe_history_panel
from quality_gate import quality_gate_column_config
from scan_history_store import append_scan_record
from screener_session_ui import render_screener_session_panel
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_historical_detail_panel,
    render_watchlist_panel,
    safe_set_page_config,
)
from session_utils import deduplicate_scan_results


def _playbook_panel() -> None:
    with st.expander("📖 Multi-bagger playbook (from your framework)", expanded=True):
        st.markdown(
            """
**Hunting ground:** Mid & small caps transitioning from *undiscovered* → *hyper-growth*.

| Pattern | What to look for |
|---------|------------------|
| **Hyper acceleration** | Sales doubling (100%+ YoY); profits 300%+ (operating leverage) |
| **Asset-light** | IT, AMC, fintech — scale without heavy capex |
| **Second-order / ancillary** | Suppliers in a hot value chain (springs, switchgear, components) |
| **Policy tailwind** | Defense (IDDDM), UPI/fintech, railways, smart meters |
| **Margin expansion** | Commodity → branded (e.g. sugar → premium spirits) |
| **Buy & Track** | Triangulate **P&L + Balance Sheet + Cash Flow** — reject channel dumping |

**Data:** **Screener.in** Mar FY Sales+, Net Profit, OPM, CFO (primary) · **Yahoo** PE, ROCE, price (secondary).
"""
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Company": "NPST", "Theme": "Fintech / UPI API", "Note": "Revenue & profit hyper-growth"},
                    {"Company": "RMC Switchgear", "Theme": "Smart-meter ancillary", "Note": "Beaten-down → orders"},
                    {"Company": "Zen Technologies", "Theme": "Defense / IDDDM", "Note": "Domestic sole vendor"},
                    {"Company": "Piccadily Agro", "Theme": "Product mix", "Note": "Sugar → premium spirits"},
                    {"Company": "Frontier Springs", "Theme": "Rail ancillary", "Note": "Springs per wagon"},
                    {"Company": "PG Electroplast", "Theme": "Contract mfg", "Note": "6× revenue growth"},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Case studies are illustrative — verify live numbers on Screener.in before investing.")

    with st.expander("🌊 Sector tailwind tags", expanded=False):
        for label, kws in TAILWIND_KEYWORDS.items():
            st.markdown(f"- **{label}:** {', '.join(kws[:6])}…")


def render_multibagger_patterns_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _playbook_panel()

    key = "mbp"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"
    nse_sources = [s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s]

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.05])
        with c1:
            st.markdown("#### Universe")
            uni_key = f"{key}_universe"
            ensure_session_choice(uni_key, nse_sources, nse_sources[0])
            quick_cols = st.columns(4)
            quick_map = [
                ("Curated", CURATED_NSE_LABEL),
                ("Nifty 50", "Nifty 50 (NSE)"),
                ("Nifty 500", "Nifty 500 (NSE)"),
                ("500+SM", "Nifty 500 + Small/Mid Movers (NSE)"),
            ]
            for col, (lbl, uni) in zip(quick_cols, quick_map):
                with col:
                    if st.button(lbl, key=f"{key}_q_{lbl}", use_container_width=True):
                        st.session_state[uni_key] = uni
                        st.rerun()
            universe = st.selectbox("Stock universe (NSE)", nse_sources, key=uni_key)
            max_res = st.slider("Max results", 10, 120, 50, 5, key=f"{key}_max")
        with c2:
            st.markdown("#### Acceleration (Screener YoY)")
            min_sales = st.slider("Min sales YoY %", 10.0, 200.0, 40.0, 5.0, key=f"{key}_sy")
            min_profit = st.slider("Min profit YoY %", 20.0, 400.0, 80.0, 10.0, key=f"{key}_py")
            profit_beats = st.checkbox("Profit YoY > Sales YoY", value=True, key=f"{key}_lev")
            min_roce = st.slider("Min ROCE %", 5.0, 40.0, 12.0, 0.5, key=f"{key}_roce")
        with c3:
            st.markdown("#### Cash & quality (anti dumping)")
            require_cash = st.checkbox("Require CFO / PAT ≥ threshold", value=True, key=f"{key}_cash")
            min_cfo = st.slider("Min CFO / PAT", 0.3, 1.5, 0.65, 0.05, key=f"{key}_cfo")
            min_opm_d = st.slider("Min OPM expansion (3Y pp)", 0.0, 15.0, 0.0, 0.5, key=f"{key}_opm")
            max_pe = st.slider("Max P/E", 10.0, 120.0, 80.0, 5.0, key=f"{key}_pe")

    with st.container(border=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            min_mcap = st.slider("Min mcap (₹ Cr)", 100.0, 3000.0, 200.0, 50.0, key=f"{key}_mcap_min")
            max_mcap = st.slider("Max mcap (₹ Cr)", 1000.0, 50_000.0, 25_000.0, 500.0, key=f"{key}_mcap_max")
        with f2:
            asset_light = st.checkbox("Prefer asset-light only", value=False, key=f"{key}_al")
            tailwind_only = st.checkbox("Require sector tailwind tag", value=False, key=f"{key}_tw")
            ancillary_only = st.checkbox("Ancillary / component plays only", value=False, key=f"{key}_anc")
        with f3:
            st.caption(
                "Screener fetch ~0.2s/stock — **Curated** or **Nifty 50** for first run. "
                "Nifty 500 can take 15–25 min. Use **Buy & Track**: re-scan after results."
            )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW (Screener + Yahoo)", use_container_width=True, key=f"{key}_scan")

    flt = MultibaggerPatternFilters(
        min_sales_yoy_pct=min_sales,
        min_profit_yoy_pct=min_profit,
        require_profit_beats_sales=profit_beats,
        min_cfo_to_pat=min_cfo,
        require_cash_backed=require_cash,
        min_opm_expansion_pp=min_opm_d,
        max_market_cap_cr=max_mcap,
        min_market_cap_cr=min_mcap,
        min_roce_pct=min_roce,
        max_pe=max_pe,
        prefer_asset_light=asset_light,
        tailwind_only=tailwind_only,
        ancillary_only=ancillary_only,
    )

    if run:
        prog = scan_progress.progress(0, text="Fetching Screener.in + Yahoo…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"{s} — Screener P&L & cash flow… ({i}/{t})")

        hits = scan_multibagger_patterns(universe, flt, progress_cb=cb, max_results=int(max_res))
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_uni"] = universe

        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits)},
            )
        except Exception:
            pass
        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    if results is None:
        st.info("👆 Pick universe and thresholds, then click **SCAN NOW**.")
        return

    rank_keys = list(RANK_OPTIONS.keys())
    ensure_session_choice(f"{key}_rank", rank_keys, "mb_score")
    rank_by = st.radio(
        "Rank by",
        rank_keys,
        format_func=lambda x: RANK_OPTIONS[x],
        horizontal=True,
        key=f"{key}_rank",
    )
    results = sort_mb_pattern_results(results, rank_by=rank_by)
    scan_at = st.session_state.get(f"{session_key}_at", "")
    last_uni = st.session_state.get(f"{session_key}_uni", universe)

    if not results:
        st.warning(
            "No matches — try **Curated** or **Nifty 50**, relax YoY thresholds, "
            "or turn off **Require CFO/PAT** (some Screener pages omit cash flow)."
        )
        return

    st.success(f"**{len(results)}** candidate(s) · {last_uni}" + (f" · {scan_at}" if scan_at else ""))

    chart_sel_key = f"{key}_chart_selected"

    def _on_chart_row_select(row: pd.Series) -> None:
        try:
            st.session_state[chart_sel_key] = str(row["Ticker"])
        except Exception:
            pass

    rows = []
    for i, r in enumerate(results, start=1):
        row = result_to_row(r, i)
        for link_name, link_url in (r.links or {}).items():
            row[link_name] = link_url
        rows.append(row)

    df = pd.DataFrame(rows)
    df = deduplicate_scan_results(df)
    df = prepare_scan_results_df(
        df,
        universe_name=last_uni,
        cache_key_prefix=f"{key}_results",
        raw_ticker_col="Raw",
    )

    col_cfg = filter_column_config(
        df,
        {
            **quality_gate_column_config(),
            "MB score": st.column_config.NumberColumn(format="%.1f"),
            "Sales YoY %": st.column_config.NumberColumn(format="%.1f"),
            "Profit YoY %": st.column_config.NumberColumn(format="%.1f"),
            "Sales CAGR 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "Profit CAGR 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "CFO/PAT": st.column_config.NumberColumn(format="%.2f"),
            "OPM %": st.column_config.NumberColumn(format="%.1f"),
            "OPM Δ 3Y pp": st.column_config.NumberColumn(format="%.1f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "P/E": st.column_config.NumberColumn(format="%.2f"),
            "1Y return %": st.column_config.NumberColumn(format="%+.1f"),
            "Below 52w %": st.column_config.NumberColumn(format="%.1f"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "Patterns": st.column_config.TextColumn(width="medium"),
            "Tailwinds": st.column_config.TextColumn(width="medium"),
            "Raw": None,
            "Notes": None,
            "Screener.in": st.column_config.LinkColumn(display_text="Screener ↗"),
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
        },
    )

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
        show_panel=False,
        on_row_select=_on_chart_row_select,
    )

    if not df.empty:
        st.markdown("---")
        render_historical_detail_panel(
            df,
            universe_name=last_uni,
            key_prefix=f"{key}_detail",
            selected_ticker=st.session_state.get(chart_sel_key),
        )
        sel = st.session_state.get(chart_sel_key)
        if sel:
            raw_sym = None
            hit = df[df["Ticker"].astype(str) == str(sel)]
            if not hit.empty and "Raw" in hit.columns:
                raw_sym = str(hit.iloc[0]["Raw"])
            render_pe_history_panel(
                display_ticker=str(sel),
                raw_ticker=raw_sym,
                key_prefix=f"{key}_pe",
            )
    elif not df.empty:
        st.caption("💡 Click a row above to load price chart and **historical P/E** (Screener EPS + Yahoo).")

    with st.expander("Pass notes (per stock)", expanded=False):
        for r in results[:20]:
            st.markdown(f"**{r.label}** ({r.data_source}): {' · '.join(r.pass_notes)}")

    st.download_button(
        "⬇ Download CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"stocksight_mb_patterns_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"{key}_dl",
    )

    st.caption(
        "Educational screener — not SEBI-registered advice. "
        "Confirm Sales+, PAT, and **Cash from Operations** on Screener.in before acting."
    )
