"""Streamlit UI — Algo Strategy Hub (multi-horizon best-stock selector)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from algo_selector import (
    ALGO_STRATEGY_CATALOG,
    HORIZON_META,
    HORIZONS,
    picks_to_dataframe,
    run_algo_selection,
)
from intraday import INTRADAY_UNIVERSES_BY_MARKET, MARKET_LABEL, resolve_universe
from ui_components import (
    inject_css,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    safe_set_page_config,
)
from quality_gate import render_quality_gate_legend
from paper_trading_page import render_paper_trading_panel

try:
    from screener import UNIVERSES
except ImportError:
    from .screener import UNIVERSES  # type: ignore[no-redef]


def render_algo_strategy_hub_page() -> None:
    safe_set_page_config(page_title="Algo Strategy Hub | StockSight", page_icon="🤖", layout="wide")
    inject_css()

    st.markdown("### 🤖 Algo Strategy Hub")
    page_audience_note(
        "Traders and investors who want **one screen** to rank the best names for "
        "**intraday, weekly, monthly, and long-term** horizons using pattern + regime logic.",
        "Maps VWAP/ORB/momentum/ATH-style setups to existing StockSight scanners. "
        "Intraday picks use the same **Unified score** as the Intraday Screener (gate + score/120 + timing + confluence + regime). "
        "For **swing / position** Stage 2 + VCP setups (Minervini-style), use **Stage 2 + VCP Screener** in the sidebar. "
        "For **VWAP / RVOL / Volume Profile** (intraday or swing), use **Volume Gravity**. "
        "**Does not auto-trade** — SEBI requires broker-hosted algos with exchange approval and Algo IDs.",
    )

    with st.expander("📜 Regulatory & design context (SEBI / global)", expanded=False):
        st.markdown(
            """
**India (SEBI, from 2025 framework):** Live algos need exchange certification, **Algo ID** on every order,
broker-owned hosting (no open retail APIs for black-box deployment), **kill switch**, order throttles,
and static IP whitelisting.

**What this hub does (white-box):**
- Detects **market regime** (gap mood + session volume curve).
- Runs your existing **intraday / weekly / monthly / long-term** scans.
- Ranks picks with **Quality Gate**-style scoring and pattern labels (VWAP, ORB, grid-range, ATH, etc.).

**What it does not do:** Place orders, run Martingale bots, or host HFT infrastructure.
Use **ICICI Breeze Screener → Live Trade** only after you review picks manually.
"""
        )
        st.dataframe(pd.DataFrame(ALGO_STRATEGY_CATALOG), use_container_width=True, hide_index=True)

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.0, 1.0])
        with c1:
            market = st.radio(
                "Market",
                ("NSE", "US"),
                format_func=lambda m: MARKET_LABEL.get(m, m),
                horizontal=True,
                key="algo_market",
            )
            uni_options = list(INTRADAY_UNIVERSES_BY_MARKET.get(market, {}).keys())
            if not uni_options:
                uni_options = list(UNIVERSES.keys())[:6]
            universe = st.selectbox("Universe", uni_options, key="algo_universe")
            n_tickers = len(resolve_universe(universe, market))
            st.caption(f"**{n_tickers}** symbols in universe")
        with c2:
            horizons = st.multiselect(
                "Horizons to scan",
                HORIZONS,
                default=list(HORIZONS),
                format_func=lambda h: HORIZON_META[h]["label"],
                key="algo_horizons",
            )
            top_n = st.slider("Top picks per horizon", 3, 15, 8, key="algo_topn")
            max_id = st.slider("Max tickers (intraday leg)", 30, 150, 80, 10, key="algo_max_id")
        with c3:
            data_source = st.selectbox(
                "Intraday data API",
                ("auto", "yahoo", "breeze"),
                format_func=lambda x: {
                    "auto": "Auto (Breeze if connected)",
                    "yahoo": "Yahoo only",
                    "breeze": "ICICI Breeze only",
                }[x],
                key="algo_ds",
            )
            st.caption("Weekly/monthly/long scans use daily/weekly bars (Yahoo).")

    run = st.button("▶  FIND BEST STOCKS (multi-horizon)", use_container_width=True, key="algo_run")

    if run:
        if not horizons:
            st.warning("Select at least one horizon.")
            return
        prog = st.progress(0, text="Detecting market regime…")
        status = st.empty()

        def cb(phase: str, cur: int, tot: int) -> None:
            pct = int(100 * cur / max(tot, 1))
            prog.progress(pct, text=f"Scanning **{phase}** ({cur}/{tot})…")
            status.caption(f"Phase: {phase}")

        with st.spinner("Running multi-horizon algo selection…"):
            report = run_algo_selection(
                universe,
                market=market,
                horizons=tuple(horizons),
                top_n=top_n,
                max_intraday_tickers=max_id,
                data_source=data_source,
                progress_cb=cb,
            )
        prog.empty()
        status.empty()
        st.session_state["algo_report"] = report
        st.session_state["algo_at"] = datetime.now().strftime("%d %b %Y %H:%M")

    report = st.session_state.get("algo_report")
    scan_at = st.session_state.get("algo_at")

    if report is None:
        st.info(
            "👆 Choose market, universe, and horizons, then click **FIND BEST STOCKS**. "
            "First run may take several minutes on large universes."
        )
        _render_horizon_guide()
        return

    st.success(
        f"Regime: **{report.regime.label}** — {report.regime.summary}"
        + (f" · {scan_at}" if scan_at else "")
    )
    st.caption(f"Session: {report.session_note}")

    if report.regime.avoid_patterns:
        st.warning(
            "Patterns to treat with caution now: "
            + ", ".join(report.regime.avoid_patterns)
        )

    tabs = st.tabs([HORIZON_META.get(h, {}).get("label", h) for h in horizons if h in report.picks_by_horizon])
    tab_i = 0
    all_rows: list[pd.DataFrame] = []

    for h in horizons:
        if h not in report.picks_by_horizon:
            continue
        picks = report.picks_by_horizon.get(h, [])
        with tabs[tab_i]:
            meta = HORIZON_META.get(h, {})
            st.markdown(
                f"**{meta.get('label', h)}** · bars: {meta.get('bars', '—')} · "
                f"hold: {meta.get('hold', '—')} · product: {meta.get('product', '—')}"
            )
            if not picks:
                st.warning("No picks this run — try a broader universe or another horizon.")
            else:
                df = picks_to_dataframe(picks)
                df = prepare_scan_results_df(
                    df,
                    market=report.market,
                    universe_name=report.universe,
                    cache_key_prefix=f"algo_{h}",
                    apply_quality_gate=False,
                )
                render_quality_gate_legend(profile="intraday" if h == "intraday" else "daily")
                render_clickable_scan_table(
                    df,
                    key_prefix=f"algo_{h}",
                    universe_name=report.universe,
                    market=report.market,
                    height=min(420, 48 + len(df) * 36),
                    caption="💡 Click a row for chart + research. Verify before any live order.",
                    show_gate_legend=False,
                )
                all_rows.append(df.assign(HorizonCode=h))
                with st.expander("Pick detail", expanded=False):
                    for p in picks:
                        st.markdown(
                            f"**#{p.rank} {p.ticker}** · {p.gate_band} · score {p.score}  \n"
                            f"Pattern: {p.pattern}  \n"
                            f"Style: {p.algo_style} · Regime: {p.regime_fit}  \n"
                            f"_{p.rationale}_"
                        )
        tab_i += 1

    if all_rows:
        st.markdown("---")
        combined = pd.concat(all_rows, ignore_index=True)
        csv = combined.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇ Download all horizon picks CSV",
            csv,
            file_name=f"stocksight_algo_hub_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key="algo_dl",
        )

    with st.expander("Scan stats", expanded=False):
        st.json(report.stats)

    all_picks: list = []
    for plist in report.picks_by_horizon.values():
        all_picks.extend(plist)
    render_paper_trading_panel(picks=all_picks, key_prefix="algo_paper", expanded=True)

    _render_horizon_guide()


def _render_horizon_guide() -> None:
    st.markdown("---")
    st.markdown("#### How horizons map to strategies")
    st.markdown(
        """
| Horizon | StockSight engines | Briefing pattern |
|---------|-------------------|------------------|
| **Intraday** | 6 intraday strategies + Quality Gate | VWAP, ORB/scalping, gap momentum |
| **Weekly** | Weekly ATH swing + breakout momentum | Trend / ATH breakout swing |
| **Monthly** | Weekly ATH (trend proxy) | Continuation before monthly confirmation |
| **Long-term** | Monthly ATH + value/technical | Quality compounders near ATH |

**Best practice:** Run at **market open** for intraday, **end of week** for weekly, and **month-end** for long-term legs.
"""
    )
