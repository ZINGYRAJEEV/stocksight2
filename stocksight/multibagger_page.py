"""Multibagger theme page — fundamental growth + quality gates on NSE."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from multibagger import (
    DEFAULT_FILTERS,
    SCAN_SOURCES,
    MultibaggerFilters,
    ProvenMultibaggerFilters,
    scan_multibagger,
    scan_proven_multibaggers,
)
from screener import decision_from_metrics
from scan_history_store import append_scan_record
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    render_decision_matrix_legend,
    render_watchlist_panel,
    safe_set_page_config,
)


def render_multibagger_page() -> None:
    safe_set_page_config(
        page_title="Multibagger Theme | StockSight",
        page_icon="🌱",
        layout="wide",
    )
    inject_css()

    st.markdown("### 🌱 Multibagger theme")
    page_audience_note(
        "Fundamental investors hunting high growth + quality on NSE (small/mid cap or ROCE-led lists).",
        "Filters on quarterly sales/profit growth, ROCE, optional debt and market-cap gates; "
        "outputs a ranked table with Yahoo links. Use **ROCE leaders** preset first, then **Small-cap strict** if needed.",
    )
    st.caption(
        "Columns: **Qtr Sales Var %**, **Qtr Profit Var %**, **ROCE %**, **Mar Cap (cr)** — Yahoo proxies."
    )

    st.markdown("""
<div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #25d366;
            border-radius:8px; padding:16px 20px; margin-bottom:16px;'>
    <div style='font-size:0.9rem; color:#e8f7ef; line-height:1.65;'>
        <b>Default reference filters</b><br>
        Qtr Sales Var &gt; 30% · Qtr Profit Var &gt; 40% · ROCE &gt; 15% ·
        optional: D/E &lt; 0.5 · Mkt cap &lt; ₹5,000 cr
    </div>
    <div style='margin-top:10px; font-size:0.75rem; color:#a3d8b8;'>
        Large caps (e.g. Nestle, ICICI AMC) pass ROCE-led preset — turn off
        <b>Apply market cap filter</b> for the small-cap preset.
    </div>
</div>
""", unsafe_allow_html=True)

    key = "mb"
    session_key = f"{key}_results"

    _presets = ["ROCE leaders", "Small-cap strict"]
    # Renamed presets leave stale session values → Streamlit KeyError on Cloud.
    _legacy = {
        "ROCE leaders (like Screener export)": "ROCE leaders",
        "Small-cap strict (Screener.in)": "Small-cap strict",
    }
    legacy_key = f"{key}_preset"
    if st.session_state.get(legacy_key) in _legacy:
        st.session_state[legacy_key] = _legacy[st.session_state[legacy_key]]
    ensure_session_choice(legacy_key, _presets, _presets[0])
    preset = st.radio(
        "Filter preset",
        _presets,
        horizontal=True,
        key=legacy_key,
    )
    small_cap = preset == "Small-cap strict"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
        with c1:
            st.markdown("#### Settings")
            ensure_session_choice(f"{key}_universe", list(SCAN_SOURCES), SCAN_SOURCES[0])
            universe = st.selectbox(
                "Stock Universe (NSE)",
                SCAN_SOURCES,
                key=f"{key}_universe",
            )
        with c2:
            st.markdown("#### Criteria")
            st.markdown(
                """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>Qtr sales var</b> · <b>Qtr profit var</b> · <b>ROCE</b> from Yahoo<br>
Table columns from Yahoo Finance where data exists
</div>
""",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown("#### Filters")
            min_sales = st.slider(
                "Min Qtr Sales Var %",
                0.0,
                80.0,
                0.0 if not small_cap else 30.0,
                1.0,
                key=f"{key}_sales",
            )
            min_prof = st.slider(
                "Min Qtr Profit Var %",
                0.0,
                150.0,
                0.0 if not small_cap else 40.0,
                1.0,
                key=f"{key}_prof",
            )
            min_roce = st.slider(
                "Min ROCE %",
                0.0,
                200.0,
                float(DEFAULT_FILTERS["min_roce_pct"]),
                0.5,
                key=f"{key}_roce",
            )
            apply_mcap = st.checkbox(
                "Apply market cap filter",
                value=small_cap,
                key=f"{key}_mcap_on",
            )
            max_cap = st.slider(
                "Max market cap (₹ crore)",
                500.0,
                300000.0,
                float(DEFAULT_FILTERS["max_market_cap_cr"]),
                500.0,
                key=f"{key}_cap",
                disabled=not apply_mcap,
            )
            apply_de = st.checkbox(
                "Apply debt/equity filter",
                value=small_cap,
                key=f"{key}_de_on",
            )
            max_de = st.slider(
                "Max debt/equity (ratio)",
                0.0,
                2.0,
                float(DEFAULT_FILTERS["max_debt_equity"]),
                0.05,
                key=f"{key}_de",
                disabled=not apply_de,
            )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan")
    st.caption(
        "Use **Curated** first (~20 liquid names). **Nifty 500** takes several minutes and needs relaxed filters."
    )

    flt = MultibaggerFilters(
        min_qtr_sales_var_pct=min_sales,
        min_qtr_profit_var_pct=min_prof,
        max_debt_equity=max_de,
        max_market_cap_cr=max_cap,
        min_roce_pct=min_roce,
        apply_mcap_filter=apply_mcap,
        apply_de_filter=apply_de,
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        mb_results = scan_multibagger(universe, flt, progress_cb=cb)
        st.session_state[session_key] = mb_results
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe

        try:
            append_scan_record(
                "multibagger",
                universe,
                [r.raw_ticker for r in mb_results],
                meta={"matches": len(mb_results), "filters": flt.__dict__},
            )
        except Exception:
            pass
        try:
            metrics = [(r.ticker, r.raw_ticker, float(r.price), None) for r in mb_results]
            notify_watchlist_alerts_from_metrics(metrics, "Multibagger theme")
        except Exception:
            pass

        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)

    if results is None:
        st.info("👆 Choose **Curated** or Nifty universe, pick a preset, then click **SCAN NOW**.")
    elif not results:
        st.warning(
            "No names passed with current Yahoo data and filters. "
            "Try **ROCE leaders** preset, **Curated** universe, or lower Qtr Sales / Profit sliders."
        )
    else:
        st.caption(f"**{len(results)}** match(es) · {last_uni}" + (f" · {scan_at}" if scan_at else ""))

        rows = []
        for rank, r in enumerate(results, start=1):
            roce_lbl = f"{r.roce_pct:.1f}" + ("*" if r.roce_is_roe_proxy else "")
            fit = min(100.0, float(r.fit_score or 0))
            decision, composite, matrix_note = decision_from_metrics(
                r.pe, None, None, score=fit, signal_label="BUY", scenario_id="multibagger"
            )
            rows.append(
                {
                    "S.No.": rank,
                    "Name": r.label,
                    "Ticker": r.ticker,
                    "Decision": decision,
                    "Composite": composite if composite == composite else fit,
                    "Matrix note": matrix_note,
                    "CMP Rs.": r.price,
                    "P/E": r.pe,
                    "Mar Cap Rs.Cr.": r.market_cap_cr,
                    "Div Yld %": r.div_yield_pct,
                    "Qtr Profit Var %": r.qtr_profit_var_pct,
                    "Qtr Sales Var %": r.qtr_sales_var_pct,
                    "ROCE %": roce_lbl,
                    "52w High Rs.": r.week52_high,
                    "D/E": r.debt_equity,
                    "Yahoo Finance": r.links.get("Yahoo Finance", ""),
                }
            )

        df = pd.DataFrame(rows)
        col_cfg = filter_column_config(
            df,
            {
                "Decision": st.column_config.TextColumn("Decision", width="medium"),
                "Matrix note": st.column_config.TextColumn("Matrix note", width="large"),
                "Composite": st.column_config.NumberColumn(format="%.1f"),
                "CMP Rs.": st.column_config.NumberColumn(format="%.2f"),
                "P/E": st.column_config.NumberColumn(format="%.2f"),
                "Mar Cap Rs.Cr.": st.column_config.NumberColumn(format="%.2f"),
                "Div Yld %": st.column_config.NumberColumn(format="%.2f"),
                "Qtr Profit Var %": st.column_config.NumberColumn(format="%.1f"),
                "Qtr Sales Var %": st.column_config.NumberColumn(format="%.1f"),
                "52w High Rs.": st.column_config.NumberColumn(format="%.2f"),
                "D/E": st.column_config.NumberColumn(format="%.3f"),
                "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Open ↗"),
            },
        )
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg,
            height=min(560, 48 + len(df) * 38),
        )
        st.caption("* ROCE from ROE when Yahoo omits ROCE. Growth % = Yahoo quarterly YoY proxies.")

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇ Download results CSV",
            csv,
            file_name=f"stocksight_multibagger_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key=f"{key}_dl",
        )
        render_decision_matrix_legend()

    st.markdown("---")
    render_proven_multibaggers_section()
    st.markdown("---")
    st.caption("⚠️ Educational only — confirm fundamentals on Yahoo Finance before investing.")


def render_proven_multibaggers_section() -> None:
    """Find stocks that delivered 500%+ returns historically and are still trending up."""
    key = "pmb"
    session_key = f"{key}_results"

    st.markdown("### 🏆 Proven Multibaggers — past 500%+ returns, still healthy")
    st.caption(
        "Stocks whose price grew **≥ N×** over the lookback window **and** are still in a healthy "
        "trend (above 200-DMA, controlled drawdown, RSI in band). Educational only — past returns do not "
        "guarantee future returns."
    )

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.0, 1.0])
        with c1:
            ensure_session_choice(f"{key}_universe", list(SCAN_SOURCES), SCAN_SOURCES[0])
            universe = st.selectbox(
                "Stock Universe (NSE)",
                SCAN_SOURCES,
                key=f"{key}_universe",
                help="Use **Curated** first for a quick scan; Nifty 500 is several minutes.",
            )
            lookback_years = st.slider(
                "Lookback (years)",
                3, 10, 5, 1,
                key=f"{key}_years",
                help="Total return is measured over this many years of Yahoo daily history.",
            )
            min_return = st.slider(
                "Minimum past return %",
                100.0, 5000.0, 500.0, 50.0,
                key=f"{key}_ret",
                help="500% = 6× the original price (i.e. classic 'multibagger').",
            )
        with c2:
            st.markdown("**Current health gates**")
            max_dd = st.slider(
                "Max drawdown from 52w high %",
                5.0, 50.0, 25.0, 1.0,
                key=f"{key}_dd",
                help="Reject names that have already crashed off the 52w high beyond this.",
            )
            require_above_ma = st.checkbox(
                "Require price above 200-DMA",
                value=True,
                key=f"{key}_ma200",
            )
            rsi_lo, rsi_hi = st.slider(
                "RSI band (current)",
                10.0, 90.0, (45.0, 75.0), 1.0,
                key=f"{key}_rsi",
                help="Excludes deeply oversold (<rsi_lo) and overheated (>rsi_hi) names.",
            )
        with c3:
            st.markdown("**Quality floors**")
            min_mcap = st.slider(
                "Min market cap (₹ crore)",
                0.0, 50000.0, 500.0, 100.0,
                key=f"{key}_mcap",
                help="Filter out micro-cap noise / illiquid names.",
            )

    run = st.button("▶  SCAN PROVEN MULTIBAGGERS", use_container_width=True, key=f"{key}_scan")

    if run:
        flt = ProvenMultibaggerFilters(
            min_past_return_pct=float(min_return),
            lookback_years=int(lookback_years),
            max_drawdown_from_52w_high_pct=float(max_dd),
            rsi_min=float(rsi_lo),
            rsi_max=float(rsi_hi),
            require_above_ma200=bool(require_above_ma),
            min_market_cap_cr=float(min_mcap),
        )
        prog = st.progress(0, text="Initialising…")

        def cb(i: int, t: int, s: str) -> None:
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        pmb_results = scan_proven_multibaggers(universe, flt, progress_cb=cb)
        prog.empty()
        st.session_state[session_key] = pmb_results
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe

        try:
            append_scan_record(
                "multibagger_proven",
                universe,
                [r.raw_ticker for r in pmb_results],
                meta={
                    "matches": len(pmb_results),
                    "filters": flt.__dict__,
                },
            )
        except Exception:
            pass

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)

    if results is None:
        st.info(
            "👆 Adjust filters and click **SCAN PROVEN MULTIBAGGERS**. "
            "Default: 5-year return ≥ 500%, above 200-DMA, RSI 45–75, drawdown ≤ 25%."
        )
        return
    if not results:
        st.warning(
            "No names matched. Try **Curated** universe, longer lookback (7–10 years), "
            "lower past-return threshold (e.g. 300%), or widen the drawdown/RSI bands."
        )
        return

    st.success(
        f"**{len(results)}** stock(s) gave ≥ {min_return:.0f}% over ~{lookback_years}y "
        f"and are still in a healthy trend · {last_uni}"
        + (f" · {scan_at}" if scan_at else "")
    )

    rows = []
    for rank, r in enumerate(results, start=1):
        rows.append(
            {
                "S.No.": rank,
                "Name": r.label,
                "Ticker": r.ticker,
                "Sector": r.sector,
                "CMP Rs.": r.price,
                f"~{r.lookback_years}y Return %": r.past_return_pct,
                "↓52w High %": r.drawdown_from_52w_high_pct,
                "vs 200-DMA %": r.pct_vs_ma200,
                "RSI": r.rsi,
                "P/E": r.pe,
                "ROCE %": r.roce_pct,
                "Qtr Profit Var %": r.qtr_profit_var_pct,
                "Mar Cap Rs.Cr.": r.market_cap_cr,
                "52w High Rs.": r.week52_high,
                "Fit Score": r.fit_score,
                "Yahoo Finance": r.links.get("Yahoo Finance", ""),
            }
        )

    df = pd.DataFrame(rows)
    return_col = next((c for c in df.columns if c.endswith("y Return %")), "Return %")
    col_cfg = filter_column_config(
        df,
        {
            "CMP Rs.": st.column_config.NumberColumn(format="%.2f"),
            return_col: st.column_config.NumberColumn(format="%.0f%%"),
            "↓52w High %": st.column_config.NumberColumn(format="%.1f"),
            "vs 200-DMA %": st.column_config.NumberColumn(format="%+.1f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "P/E": st.column_config.NumberColumn(format="%.2f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "Qtr Profit Var %": st.column_config.NumberColumn(format="%.1f"),
            "Mar Cap Rs.Cr.": st.column_config.NumberColumn(format="%.0f"),
            "52w High Rs.": st.column_config.NumberColumn(format="%.2f"),
            "Fit Score": st.column_config.ProgressColumn("Fit Score", format="%.0f", min_value=0, max_value=100),
            "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Open ↗"),
        },
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
    )

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇ Download proven multibaggers CSV",
        csv,
        file_name=f"stocksight_proven_multibaggers_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"{key}_dl",
    )

    st.caption(
        "Past return = total Yahoo close-to-close % over the lookback window (adjusted). "
        "Healthy trend = above 200-DMA · RSI in band · controlled 52w drawdown. "
        "Always confirm fundamentals and news before buying — past performance is not a guarantee."
    )
