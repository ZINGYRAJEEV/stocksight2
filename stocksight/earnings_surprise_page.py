"""Earnings Surprise — unpriced quarterly jump screener UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from earnings_surprise_screener import (
    META,
    RANK_BY_OPTIONS,
    EarningsSurpriseFilters,
    SCAN_SOURCES,
    result_to_row,
    scan_earnings_surprise,
    sort_earnings_surprise_results,
)
from quality_gate import quality_gate_column_config
from scan_history_store import append_scan_record
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
)
from session_utils import deduplicate_scan_results
from stock_analysis_framework import StockAnalysisFramework


def _rules_panel() -> None:
    with st.expander("📖 How this screen works", expanded=True):
        st.markdown(
            """
**Thesis:** When revenue and profit **jump sharply quarter-on-quarter**, the market often lags —
especially if the stock is **not near 52-week highs** and **hasn't rallied** in the last 1–3 months.

**Three pillars**

| Pillar | What we check |
|--------|----------------|
| **Earnings jump** | QoQ sales % and QoQ profit % (latest reported quarter vs prior quarter) |
| **Bright future** | ROCE, YoY quarterly growth proxies (sales & profit) |
| **Price asleep** | Near/below 200-DMA, below 52w high, capped 3M return, reasonable PEG |

**Data:** Yahoo `quarterly_financials` / `quarterly_income_stmt` for QoQ; Yahoo `info` for YoY growth & ROCE.
**Always cross-check** quarterly results on [Screener.in](https://www.screener.in) before acting.

**Not the same as:** Multibagger / Volume-Led screens — those use **YoY** quarterly fields, not **QoQ** jumps.
"""
        )
        st.code(
            "\n".join(
                [
                    "QoQ sales jump > 10% AND",
                    "QoQ profit jump > 15% AND",
                    "QoQ profit > QoQ sales (operating leverage) AND",
                    "ROCE > 12% AND",
                    "YoY qtr sales & profit growth positive AND",
                    "Price within 12% of 200-DMA AND",
                    "At least 5% below 52-week high AND",
                    "3-month return < 18% AND",
                    "PEG < 2.5",
                ]
            ),
            language="sql",
        )


def render_earnings_surprise_page() -> None:
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

    key = "esur"
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
            st.markdown("#### Earnings jump (QoQ)")
            min_qs = st.slider("Min QoQ sales jump %", 5.0, 40.0, 10.0, 1.0, key=f"{key}_qoq_s")
            min_qp = st.slider("Min QoQ profit jump %", 5.0, 60.0, 15.0, 1.0, key=f"{key}_qoq_p")
            profit_beats = st.checkbox(
                "QoQ profit jump > sales jump",
                value=True,
                key=f"{key}_lev",
            )
        with c3:
            st.markdown("#### Price still asleep")
            max_ma = st.slider("Max vs 200-DMA %", 0.0, 25.0, 12.0, 1.0, key=f"{key}_ma")
            min_dd = st.slider("Min below 52w high %", 0.0, 35.0, 5.0, 1.0, key=f"{key}_dd")
            max_r3 = st.slider("Max 3-month return %", 0.0, 40.0, 18.0, 1.0, key=f"{key}_r3")
            max_peg = st.slider("Max PEG", 0.5, 4.0, 2.5, 0.1, key=f"{key}_peg")

    with st.container(border=True):
        q1, q2, q3 = st.columns(3)
        with q1:
            min_roce = st.slider("Min ROCE %", 5.0, 35.0, 12.0, 0.5, key=f"{key}_roce")
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 300.0, 50.0, key=f"{key}_mcap")
        with q2:
            min_yoy_s = st.slider("Min YoY qtr sales %", 0.0, 40.0, 8.0, 1.0, key=f"{key}_yoy_s")
            min_yoy_p = st.slider("Min YoY qtr profit %", 0.0, 60.0, 12.0, 1.0, key=f"{key}_yoy_p")
            require_quality = st.checkbox("Require YoY quality gates", value=True, key=f"{key}_qual")
        with q3:
            max_de = st.slider("Max debt/equity", 0.0, 2.0, 1.0, 0.05, key=f"{key}_de")
            st.caption(
                "Loosen **Max vs 200-DMA** or **Max 3M return** if you get zero hits. "
                "Tighten for stricter 'hidden gem' lists."
            )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan")
    st.caption("QoQ uses the **two most recent reported quarters** on Yahoo — verify dates in the results table.")

    flt = EarningsSurpriseFilters(
        min_qoq_sales_pct=min_qs,
        min_qoq_profit_pct=min_qp,
        require_profit_beats_sales_qoq=profit_beats,
        min_roce_pct=min_roce,
        min_qtr_sales_yoy_pct=min_yoy_s,
        min_qtr_profit_yoy_pct=min_yoy_p,
        require_future_quality=require_quality,
        max_pct_vs_ma200=max_ma,
        min_drawdown_52w_pct=min_dd,
        max_return_3m_pct=max_r3,
        max_peg=max_peg,
        max_debt_equity=max_de,
        min_market_cap_cr=min_mcap,
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        hits = scan_earnings_surprise(universe, filters=flt, progress_cb=cb)
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
            metrics = [(r.ticker, r.raw_ticker, float(r.price), None) for r in hits]
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
            "or relax **QoQ thresholds**, **Max 3M return**, or **Max vs 200-DMA**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    ensure_session_choice(rank_key, rank_choices, "surprise")
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_earnings_surprise_results(results, rank_by=rank_by)

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
            "Surprise": st.column_config.NumberColumn(format="%.1f"),
            "QoQ sales %": st.column_config.NumberColumn(format="%.1f"),
            "QoQ profit %": st.column_config.NumberColumn(format="%.1f"),
            "YoY sales %": st.column_config.NumberColumn(format="%.1f"),
            "YoY profit %": st.column_config.NumberColumn(format="%.1f"),
            "PEG": st.column_config.NumberColumn(format="%.2f"),
            "vs 200-DMA %": st.column_config.NumberColumn(format="%+.2f"),
            "Below 52w high %": st.column_config.NumberColumn(format="%.1f"),
            "1M return %": st.column_config.NumberColumn(format="%+.1f"),
            "3M return %": st.column_config.NumberColumn(format="%+.1f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "P/E": st.column_config.NumberColumn(format="%.2f"),
            "D/E": st.column_config.NumberColumn(format="%.3f"),
            "ROCE %": st.column_config.TextColumn("ROCE %"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "Raw": None,
            "Notes": None,
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
    )

    with st.expander("Pass criteria notes (per stock)", expanded=False):
        for r in results[:25]:
            st.markdown(f"**{r.label}** ({r.latest_q} vs {r.prior_q}): {' · '.join(r.pass_notes)}")

    st.caption(
        "* ROCE from ROE when Yahoo omits ROCE. YoY % = Yahoo quarterly YoY proxies. "
        "QoQ % = computed from Yahoo quarterly P&L. Educational only — not investment advice."
    )
