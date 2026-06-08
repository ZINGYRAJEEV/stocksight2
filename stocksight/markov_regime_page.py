"""Streamlit page — Markov Regime screener (Hedge Fund Method)."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from markov_regime import (
    META,
    MARKETS,
    MarkovRegimeFilters,
    analyze_ticker_markov,
    scan_markov_regime,
    universe_options,
)
from markov_regime_ui import (
    markov_regime_header,
    markov_regime_table,
    render_education_panels,
    render_matrix_detail,
    results_to_dataframe,
)
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_watchlist_panel,
    safe_set_page_config,
)

try:
    from intraday import MARKET_LABEL
except ImportError:
    from .intraday import MARKET_LABEL  # type: ignore[no-redef]


def render_markov_regime_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()
    markov_regime_header()
    page_audience_note(META["audience"], META["purpose"])
    render_education_panels()
    render_watchlist_panel("markov_wl")

    key = "markov"
    session_results = f"{key}_results"
    session_at = f"{key}_at"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.0, 1.05])
        with c1:
            st.markdown("#### Universe")
            market = st.radio(
                "Market",
                MARKETS,
                format_func=lambda m: MARKET_LABEL.get(m, m),
                horizontal=True,
                key=f"{key}_market",
            )
            uni_opts = universe_options(market)
            universe = st.selectbox("Universe", uni_opts, key=f"{key}_universe")
        with c2:
            st.markdown("#### State thresholds")
            lookback = st.slider("Lookback days", 10, 40, 20, key=f"{key}_lb")
            bull_thr = st.slider("Bull state: 20d return ≥ %", 2.0, 12.0, 5.0, 0.5, key=f"{key}_bull")
            bear_thr = st.slider("Bear state: 20d return ≤ %", -12.0, -2.0, -5.0, 0.5, key=f"{key}_bear")
        with c3:
            st.markdown("#### Signal filters")
            forecast_days = st.selectbox(
                "Forecast horizon (matrix power)",
                [1, 2, 3, 5],
                format_func=lambda d: f"{d}-day (P^{d})",
                key=f"{key}_horizon",
            )
            min_signal = st.slider("Min |signal| (Bull − Bear)", 0.0, 0.50, 0.05, 0.05, key=f"{key}_minsig")
            signal_side = st.radio(
                "Side",
                ("long", "short", "any"),
                format_func=lambda s: {"long": "Long bias", "short": "Short / avoid", "any": "Any strong"}[s],
                horizontal=True,
                key=f"{key}_side",
            )
            require_hmm = st.checkbox("Require HMM agreement", value=False, key=f"{key}_hmm")

    flt = MarkovRegimeFilters(
        lookback_days=int(lookback),
        bull_threshold_pct=float(bull_thr),
        bear_threshold_pct=float(bear_thr),
        forecast_days=int(forecast_days),
        min_signal=float(min_signal),
        require_hmm_agree=bool(require_hmm),
        signal_side=str(signal_side),
    )

    if st.button(f"🎲 RUN {META['nav_title'].upper()} SCAN", type="primary", key=f"{key}_run"):
        prog = st.progress(0, text="Starting Markov scan…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(
                min(99, int(100 * i / max(total, 1))),
                text=f"Markov: {sym} ({i}/{total})",
            )

        results, stats = scan_markov_regime(
            universe,
            market=market,
            filters=flt,
            progress_cb=_cb,
        )
        prog.progress(100, text="Scan complete")
        st.session_state[session_results] = results
        st.session_state[f"{key}_stats"] = stats
        st.session_state[session_at] = datetime.now().strftime("%d %b %Y %H:%M:%S")
        append_scan_record(
            "markov_regime",
            universe,
            [r.raw_ticker for r in results],
            meta={"market": market, "forecast_days": forecast_days},
        )

    results = st.session_state.get(session_results, [])
    stats = st.session_state.get(f"{key}_stats")
    scan_at = st.session_state.get(session_at)

    if stats:
        st.caption(
            f"Scanned **{stats.tickers_scanned}** · matched **{stats.tickers_matched}** · "
            f"no data **{stats.no_data}** · {stats.scan_elapsed_sec:.1f}s"
            + (f" · last run {scan_at}" if scan_at else "")
        )

    if not results:
        st.info("Run a scan to see Markov regime signals.")
        return

    df = results_to_dataframe(results)
    picked = markov_regime_table(df, key_prefix=key)

    with st.expander("🔬 Single-ticker deep dive (matrix + forecasts)", expanded=False):
        tickers = [r.ticker for r in results]
        pick = st.selectbox("Ticker", tickers, key=f"{key}_deep")
        raw = next((r.raw_ticker for r in results if r.ticker == pick), None)
        if raw:
            deep = analyze_ticker_markov(raw, flt, include_walk_forward=True)
            if deep:
                render_matrix_detail(deep)

    st.caption("⚠️ Educational quant framework only — not financial advice. Walk-forward acc is historical, not a guarantee.")
