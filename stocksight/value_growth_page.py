"""Value Growth — low P/E, high EPS, solid profit compounding (Screener.in)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from value_growth_screener import (
    META,
    RANK_OPTIONS,
    ValueGrowthFilters,
    SCAN_SOURCES,
    result_to_row,
    scan_value_growth,
    sort_value_growth_results,
)
from pe_history_ui import render_pe_history_panel
from quality_gate import quality_gate_column_config
from scan_history_store import append_scan_record
from screener_session_ui import render_screener_session_panel
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_historical_detail_panel,
    render_watchlist_panel,
    safe_set_page_config,
)
from session_utils import deduplicate_scan_results
from stock_analysis_framework import StockAnalysisFramework


def _rules_panel() -> None:
    with st.expander("📖 How this screen works", expanded=True):
        st.markdown(
            """
**Thesis:** **GARP-style** hunting — stocks that are **not expensive on P/E**, earn **meaningful trailing EPS**,
and show **solid profit compounding** on Screener.in.

**Three pillars**

| Pillar | Screener.in field |
|--------|-------------------|
| **Low P/E** | Top ratios → **Stock P/E** |
| **High EPS** | P&L → **EPS in Rs** (latest Mar FY) |
| **Forward growth proxy** | **Compounded Profit Growth** (3Y / TTM) — not broker estimates |

**PEG proxy** = P/E ÷ profit growth 3Y (or TTM when 3Y missing). Lower is cheaper per unit of growth.

**Data:** Screener.in consolidated page only — one fetch per stock. Start with **Curated** or **Nifty 50**.
"""
        )
        st.code(
            "\n".join(
                [
                    "Stock P/E ≤ max (default 22) AND",
                    "Trailing EPS ≥ min (default ₹8) AND",
                    "Compounded Profit Growth 3Y ≥ 12% AND",
                    "Compounded Profit Growth TTM ≥ 8% AND",
                    "ROCE ≥ 12% AND",
                    "Market cap within range",
                ]
            ),
            language="sql",
        )


def render_value_growth_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    enable_analysis = st.sidebar.checkbox(
        "Enable 7-Category Analysis (Beta)",
        value=True,
        help="Adds Valuation, Profitability, Growth, Financial Health scores",
    )

    key = "vgro"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.05])
        with c1:
            st.markdown("#### Universe")
            uni_key = f"{key}_universe"
            nse_sources = [s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s]
            ensure_session_choice(uni_key, nse_sources, nse_sources[0])
            universe = st.selectbox(
                "Stock universe (NSE)",
                nse_sources,
                key=uni_key,
                help="Start with Curated or Nifty 50; Nifty 500 takes several minutes.",
            )
        with c2:
            st.markdown("#### Value (P/E · EPS)")
            max_pe = st.slider("Max P/E", 8.0, 40.0, 22.0, 1.0, key=f"{key}_pe")
            min_eps = st.slider("Min trailing EPS (₹)", 2.0, 50.0, 8.0, 1.0, key=f"{key}_eps")
            min_roce = st.slider("Min ROCE %", 5.0, 35.0, 12.0, 0.5, key=f"{key}_roce")
        with c3:
            st.markdown("#### Growth (Screener compounded)")
            min_g3 = st.slider("Min profit growth 3Y %", 0.0, 40.0, 12.0, 1.0, key=f"{key}_g3")
            require_ttm = st.checkbox("Require TTM profit growth", value=True, key=f"{key}_ttm_req")
            min_gttm = st.slider("Min profit growth TTM %", 0.0, 40.0, 8.0, 1.0, key=f"{key}_gttm")

    with st.container(border=True):
        m1, m2 = st.columns(2)
        with m1:
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 300.0, 50.0, key=f"{key}_mcap_min")
        with m2:
            max_mcap = st.slider("Max market cap (₹ Cr)", 50_000.0, 1_000_000.0, 500_000.0, 25_000.0, key=f"{key}_mcap_max")
            st.caption("Relax **Max P/E** or **Min EPS** if you get zero hits on small universes.")

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan")
    st.caption(
        "Growth = Screener **Compounded Profit Growth** (historical compounding), not analyst forward EPS. "
        "Verify latest results on Screener.in before acting."
    )

    flt = ValueGrowthFilters(
        max_pe=max_pe,
        min_eps=min_eps,
        min_profit_growth_3y_pct=min_g3,
        min_profit_growth_ttm_pct=min_gttm,
        require_ttm_growth=require_ttm,
        min_roce_pct=min_roce,
        min_market_cap_cr=min_mcap,
        max_market_cap_cr=max_mcap,
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Screener.in {s}… ({i}/{t})")

        hits = scan_value_growth(universe, filters=flt, progress_cb=cb)
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe

        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits)},
            )
        except Exception:
            pass
        try:
            metrics = [(r.ticker, r.raw_ticker, float(r.price or 0), None) for r in hits if r.price]
            notify_watchlist_alerts_from_metrics(metrics, META["title"])
        except Exception:
            pass

        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)

    if results is None:
        st.info("👆 Pick universe and thresholds, then click **SCAN NOW**.")
        return

    if not results:
        st.warning(
            "No names passed with current filters. Try **Curated** or **Nifty 50**, "
            "or relax **Max P/E**, **Min EPS**, or **Min profit growth**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_OPTIONS.keys())
    ensure_session_choice(rank_key, rank_choices, "score")
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_value_growth_results(results, rank_by=rank_by)

    st.success(
        f"**{len(results)}** matches · {last_uni} · scanned {scan_at or '—'}"
    )

    rows = []
    for i, r in enumerate(results, start=1):
        row = result_to_row(r, i)
        for link_name, link_url in (r.links or {}).items():
            row[link_name] = link_url
        rows.append(row)

    df = pd.DataFrame(rows)
    df = deduplicate_scan_results(df)

    if enable_analysis and not df.empty:
        try:
            framework = StockAnalysisFramework()
            df = framework.enrich_dataframe(df)
        except Exception as exc:
            st.warning(f"Stock analysis framework error: {exc}")

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
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "P/E": st.column_config.NumberColumn(format="%.2f"),
            "EPS ₹": st.column_config.NumberColumn(format="₹%.2f"),
            "Profit 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "Profit TTM %": st.column_config.NumberColumn(format="%.1f"),
            "Profit 5Y %": st.column_config.NumberColumn(format="%.1f"),
            "Sales 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "PEG proxy": st.column_config.NumberColumn(format="%.2f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "ROE %": st.column_config.NumberColumn(format="%.1f"),
            "Price ₹": st.column_config.NumberColumn(format="₹%.2f"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "Raw": None,
            "Notes": None,
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
            "Screener.in": st.column_config.LinkColumn(display_text="Screener ↗"),
        },
    )

    chart_sel_key = f"{key}_chart_selected"

    def _on_chart_row_select(row: pd.Series) -> None:
        try:
            st.session_state[chart_sel_key] = str(row["Ticker"])
        except Exception:
            pass

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
        show_panel=False,
        on_row_select=_on_chart_row_select,
    )

    sel = st.session_state.get(chart_sel_key)
    if sel and not df.empty:
        st.markdown("---")
        render_historical_detail_panel(
            df,
            universe_name=last_uni,
            key_prefix=f"{key}_detail",
            selected_ticker=sel,
        )
        raw_sym = None
        hit = df[df["Ticker"].astype(str) == str(sel)]
        if not hit.empty and "Raw" in hit.columns:
            raw_sym = str(hit.iloc[0]["Raw"])
        render_pe_history_panel(
            display_ticker=str(sel),
            raw_ticker=raw_sym,
            key_prefix=f"{key}_pe",
            max_pe_hint=float(max_pe),
        )
    elif not df.empty:
        st.caption("💡 Click a row above to load price chart and **historical P/E** (Screener EPS + Yahoo).")

    with st.expander("Pass criteria notes (per stock)", expanded=False):
        for r in results[:25]:
            st.markdown(f"**{r.label}**: {' · '.join(r.pass_notes)}")

    st.caption(
        "* All fundamentals from Screener.in consolidated page. "
        "PEG proxy = P/E ÷ profit growth 3Y. Educational only — not investment advice."
    )
