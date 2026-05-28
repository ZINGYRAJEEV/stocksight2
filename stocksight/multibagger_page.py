"""Multibagger theme page — fundamental growth + quality gates on NSE."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from multibagger import (
    DEFAULT_FILTERS,
    LEGACY_CURATED_KEY,
    SCAN_SOURCES,
    MultibaggerFilters,
    ProvenMultibaggerFilters,
    is_us_source,
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
    render_clickable_scan_table,
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
        "Fundamental investors hunting high growth + quality on **NSE or US** universes (small/mid cap or ROCE-led).",
        "Filters on quarterly sales/profit growth, ROCE, optional debt and market-cap gates; "
        "outputs a ranked table with Yahoo / Google / research links. "
        "Use **ROCE leaders** preset first, then **Small-cap strict** if needed.",
    )
    st.caption(
        "Columns: **Qtr Sales Var %**, **Qtr Profit Var %**, **ROCE %**, **Mar Cap** (₹ Cr for NSE, $ B for US) — Yahoo proxies."
    )

    st.markdown("""
<div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #25d366;
            border-radius:8px; padding:16px 20px; margin-bottom:16px;'>
    <div style='font-size:0.9rem; color:#e8f7ef; line-height:1.65;'>
        <b>Default reference filters</b><br>
        Qtr Sales Var &gt; 30% · Qtr Profit Var &gt; 40% · ROCE &gt; 15% ·
        optional: D/E &lt; 0.5 · Mkt cap &lt; ₹5,000 cr (NSE) / $100 B (US)
    </div>
    <div style='margin-top:10px; font-size:0.75rem; color:#a3d8b8;'>
        Large caps (e.g. Nestle, ICICI AMC, AAPL, MSFT) pass ROCE-led preset — turn off
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
            # Migrate any legacy curated-key in session state to the new label.
            uni_key = f"{key}_universe"
            if st.session_state.get(uni_key) == LEGACY_CURATED_KEY:
                st.session_state[uni_key] = SCAN_SOURCES[0]
            ensure_session_choice(uni_key, list(SCAN_SOURCES), SCAN_SOURCES[0])
            universe = st.selectbox(
                "Stock Universe (NSE / US)",
                SCAN_SOURCES,
                key=uni_key,
                help="Pick an NSE list (curated / Nifty) or a US list (curated / S&P 500).",
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
            us_universe = is_us_source(universe)
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
            if us_universe:
                max_cap_usd_bn = st.slider(
                    "Max market cap ($ billion)",
                    1.0,
                    5000.0,
                    float(DEFAULT_FILTERS["max_market_cap_usd_bn"]),
                    1.0,
                    key=f"{key}_cap_usd",
                    disabled=not apply_mcap,
                    help="US universe — caps measured in USD billions (e.g. AAPL ≈ $3 T, COST ≈ $400 B).",
                )
                max_cap = float(DEFAULT_FILTERS["max_market_cap_cr"])
            else:
                max_cap = st.slider(
                    "Max market cap (₹ crore)",
                    500.0,
                    300000.0,
                    float(DEFAULT_FILTERS["max_market_cap_cr"]),
                    500.0,
                    key=f"{key}_cap",
                    disabled=not apply_mcap,
                )
                max_cap_usd_bn = float(DEFAULT_FILTERS["max_market_cap_usd_bn"])
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
        max_market_cap_usd_bn=max_cap_usd_bn,
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
            row = {
                "S.No.": rank,
                "Name": r.label,
                "Ticker": r.ticker,
                "Raw": r.raw_ticker,
                "Currency": r.currency or "INR",
                "Decision": decision,
                "Composite": composite if composite == composite else fit,
                "Matrix note": matrix_note,
                "CMP": r.price,
                "P/E": r.pe,
                "Mar Cap": r.market_cap_display or "",
                "Mar Cap Rs.Cr.": r.market_cap_cr,
                "Mar Cap $B": r.market_cap_usd_bn,
                "Div Yld %": r.div_yield_pct,
                "Qtr Profit Var %": r.qtr_profit_var_pct,
                "Qtr Sales Var %": r.qtr_sales_var_pct,
                "ROCE %": roce_lbl,
                "52w High": r.week52_high,
                "D/E": r.debt_equity,
            }
            # Include only the links available for this ticker (Moneycontrol for NSE, MarketWatch for US).
            for link_name, link_url in (r.links or {}).items():
                row[link_name] = link_url
            rows.append(row)

        df = pd.DataFrame(rows)
        # Drop fully-empty columns (e.g. "Mar Cap Rs.Cr." disappears for a US-only scan).
        df = df.dropna(axis=1, how="all")
        for empty_str_col in ("Mar Cap",):
            if empty_str_col in df.columns and not df[empty_str_col].astype(str).str.strip().any():
                df = df.drop(columns=[empty_str_col])

        col_cfg = filter_column_config(
            df,
            {
                "Decision": st.column_config.TextColumn("Decision", width="medium"),
                "Matrix note": st.column_config.TextColumn("Matrix note", width="large"),
                "Composite": st.column_config.NumberColumn(format="%.1f"),
                "CMP": st.column_config.NumberColumn(format="%.2f"),
                "P/E": st.column_config.NumberColumn(format="%.2f"),
                "Mar Cap": st.column_config.TextColumn("Mar Cap", help="Market cap in native units (₹ Cr / $ B / $ T)."),
                "Mar Cap Rs.Cr.": st.column_config.NumberColumn("Mar Cap (₹ Cr)", format="%.2f"),
                "Mar Cap $B": st.column_config.NumberColumn("Mar Cap ($ B)", format="%.2f"),
                "Div Yld %": st.column_config.NumberColumn(format="%.2f"),
                "Qtr Profit Var %": st.column_config.NumberColumn(format="%.1f"),
                "Qtr Sales Var %": st.column_config.NumberColumn(format="%.1f"),
                "52w High": st.column_config.NumberColumn(format="%.2f"),
                "D/E": st.column_config.NumberColumn(format="%.3f"),
                "Currency": st.column_config.TextColumn("Cur", width="small"),
                "Raw": None,  # hide internal raw-ticker column from the table
                "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
                "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
                "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
                "MarketWatch": st.column_config.LinkColumn("MarketWatch", display_text="MW ↗"),
                "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
            },
        )
        from ui_components import prepare_scan_results_df

        df = prepare_scan_results_df(
            df,
            universe_name=last_uni,
            cache_key_prefix=f"{key}_results",
            raw_ticker_col="Raw",
        )
        render_clickable_scan_table(
            df,
            key_prefix=f"{key}_results",
            universe_name=last_uni,
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
    st.info(
        "Looking for stocks that already delivered **500%+ returns** and are still healthy? "
        "Open the **🏆 Proven Multibaggers** page from the sidebar."
    )
    st.markdown("---")
    st.caption("⚠️ Educational only — confirm fundamentals on Yahoo Finance before investing.")


def render_proven_multibaggers_page() -> None:
    """Dedicated page wrapper for the Proven Multibaggers scan."""
    safe_set_page_config(
        page_title="Proven Multibaggers | StockSight",
        page_icon="🏆",
        layout="wide",
    )
    inject_css()

    st.markdown("### 🏆 Proven Multibaggers")
    page_audience_note(
        "Long-term investors who want **NSE or US** stocks that already became multibaggers and are *still* working.",
        "Filters Yahoo Finance daily history for **N-year total return ≥ X%** (default **500% over 5 years**), "
        "then keeps only names that are currently in a healthy trend "
        "(above 200-DMA · controlled 52w drawdown · RSI in band). Educational only.",
    )

    st.markdown("""
<div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #25d366;
            border-radius:8px; padding:16px 20px; margin-bottom:16px;'>
    <div style='font-size:0.9rem; color:#e8f7ef; line-height:1.65;'>
        <b>Default screen:</b> 5-year return ≥ 500% (6×) ·
        price above 200-DMA · drawdown from 52w high ≤ 25% · RSI 45–75 ·
        market cap ≥ ₹500 Cr (NSE) / ≥ $1 B (US).
    </div>
    <div style='margin-top:10px; font-size:0.75rem; color:#a3d8b8;'>
        Use <b>Curated NSE</b> or <b>Curated US</b> first (fast). Nifty 500 / S&P 500 take several minutes.
        Past performance does <b>not</b> guarantee future returns — always confirm fundamentals and news.
    </div>
</div>
""", unsafe_allow_html=True)

    render_proven_multibaggers_section()


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
            uni_key = f"{key}_universe"
            if st.session_state.get(uni_key) == LEGACY_CURATED_KEY:
                st.session_state[uni_key] = SCAN_SOURCES[0]
            ensure_session_choice(uni_key, list(SCAN_SOURCES), SCAN_SOURCES[0])
            universe = st.selectbox(
                "Stock Universe (NSE / US)",
                SCAN_SOURCES,
                key=uni_key,
                help="NSE: Curated, Nifty 50, Nifty 500. US: Curated mega/large-cap or S&P 500.",
            )
            us_universe = is_us_source(universe)
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
            if us_universe:
                min_mcap_usd_bn = st.slider(
                    "Min market cap ($ billion)",
                    0.0, 500.0, 1.0, 0.5,
                    key=f"{key}_mcap_usd",
                    help="US universe — filter out micro-caps. 1 = $1 B floor.",
                )
                min_mcap = 0.0
            else:
                min_mcap = st.slider(
                    "Min market cap (₹ crore)",
                    0.0, 50000.0, 500.0, 100.0,
                    key=f"{key}_mcap",
                    help="Filter out micro-cap noise / illiquid names.",
                )
                min_mcap_usd_bn = 1.0

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
            min_market_cap_usd_bn=float(min_mcap_usd_bn),
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
        row = {
            "S.No.": rank,
            "Name": r.label,
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Currency": r.currency or "INR",
            "Sector": r.sector,
            "CMP": r.price,
            f"~{r.lookback_years}y Return %": r.past_return_pct,
            "↓52w High %": r.drawdown_from_52w_high_pct,
            "vs 200-DMA %": r.pct_vs_ma200,
            "RSI": r.rsi,
            "P/E": r.pe,
            "ROCE %": r.roce_pct,
            "Qtr Profit Var %": r.qtr_profit_var_pct,
            "Mar Cap": r.market_cap_display or "",
            "Mar Cap Rs.Cr.": r.market_cap_cr,
            "Mar Cap $B": r.market_cap_usd_bn,
            "52w High": r.week52_high,
            "Fit Score": r.fit_score,
        }
        for link_name, link_url in (r.links or {}).items():
            row[link_name] = link_url
        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.dropna(axis=1, how="all")
    for empty_str_col in ("Mar Cap",):
        if empty_str_col in df.columns and not df[empty_str_col].astype(str).str.strip().any():
            df = df.drop(columns=[empty_str_col])

    return_col = next((c for c in df.columns if c.endswith("y Return %")), "Return %")
    col_cfg = filter_column_config(
        df,
        {
            "CMP": st.column_config.NumberColumn(format="%.2f"),
            "Currency": st.column_config.TextColumn("Cur", width="small"),
            "Raw": None,
            return_col: st.column_config.NumberColumn(format="%.0f%%"),
            "↓52w High %": st.column_config.NumberColumn(format="%.1f"),
            "vs 200-DMA %": st.column_config.NumberColumn(format="%+.1f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "P/E": st.column_config.NumberColumn(format="%.2f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "Qtr Profit Var %": st.column_config.NumberColumn(format="%.1f"),
            "Mar Cap": st.column_config.TextColumn("Mar Cap", help="Native units (₹ Cr / $ B / $ T)."),
            "Mar Cap Rs.Cr.": st.column_config.NumberColumn("Mar Cap (₹ Cr)", format="%.0f"),
            "Mar Cap $B": st.column_config.NumberColumn("Mar Cap ($ B)", format="%.2f"),
            "52w High": st.column_config.NumberColumn(format="%.2f"),
            "Fit Score": st.column_config.ProgressColumn("Fit Score", format="%.0f", min_value=0, max_value=100),
            "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
            "MarketWatch": st.column_config.LinkColumn("MarketWatch", display_text="MW ↗"),
            "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
        },
    )
    from ui_components import prepare_scan_results_df

    df = prepare_scan_results_df(
        df,
        universe_name=last_uni,
        cache_key_prefix=f"{key}_proven",
        raw_ticker_col="Raw",
    )
    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
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
