"""Streamlit page — Stage 2 + VCP momentum screener."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from scan_history_store import append_scan_record
from stage2_momentum import META, Stage2ScanFilters, scan_stage2_momentum
from stage2_momentum_ui import (
    no_results_state,
    render_education_panels,
    results_to_dataframe,
    stage2_header,
    stage2_results_table,
)
from screener import UNIVERSES
from ui_components import (
    inject_css,
    page_audience_note,
    render_watchlist_panel,
    safe_set_page_config,
)


def render_stage2_momentum_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()
    stage2_header()
    page_audience_note(META["audience"], META["purpose"])
    render_education_panels()
    render_watchlist_panel("s2_wl")

    key = "s2"
    session_results = f"{key}_results"
    session_stats = f"{key}_stats"
    session_at = f"{key}_at"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
        with c1:
            st.markdown("#### Settings")
            universe = st.selectbox(
                "Stock universe",
                list(UNIVERSES.keys()),
                key=f"{key}_universe",
                help="Broader lists find more Stage 2 names but take longer (2y history per symbol).",
            )
            st.caption("Uses **daily** Yahoo data (~2 years) for 50/150/200-day MAs.")
        with c2:
            st.markdown("#### What we scan for")
            st.markdown(
                """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>Stage 2</b> Trend Template (6–8 rules) · <b>VCP</b> tightening pullbacks<br>
<b>RS</b> vs Nifty / SPY within this scan · <b>Pivot</b> distance & volume dry-up
</div>
""",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown("#### Quick filters")
            min_trend = st.slider(
                "Min Trend Template passes (of 7 technical)",
                4,
                7,
                6,
                1,
                key=f"{key}_min_trend",
                help="RS is scored separately; 7 technical checks before RS is added.",
            )
            min_vcp = st.slider("Min VCP score", 0, 80, 35, 5, key=f"{key}_min_vcp")
            min_rs = st.slider("Min RS rank in scan", 50, 95, 70, 5, key=f"{key}_min_rs")

    with st.expander("⚙ Advanced filters", expanded=False):
        a1, a2, a3 = st.columns(3)
        with a1:
            min_above_low = st.slider("Min % above 52w low", 15, 50, 25, 5, key=f"{key}_above_low")
            max_below_high = st.slider("Max % below 52w high", 5, 40, 25, 5, key=f"{key}_below_high")
        with a2:
            require_tight = st.checkbox("Require tightening pullbacks", value=False, key=f"{key}_tight")
            require_dry = st.checkbox("Require volume dry-up", value=False, key=f"{key}_dry")
            stage2_only = st.checkbox("Stage 2 label only", value=False, key=f"{key}_s2only")
        with a3:
            min_brk_vol = st.slider(
                "Min today vol vs 50d avg (breakout confirm)",
                0.0,
                2.5,
                0.0,
                0.1,
                key=f"{key}_brkvol",
                help="0 = off. Use ~1.4+ only when hunting live breakouts.",
            )

    scan_slot = st.empty()
    run = st.button("▶  RUN STAGE 2 + VCP SCAN", use_container_width=True, key=f"{key}_run")
    st.caption(
        "Swing / position timeframe (weeks–months). Not intraday. "
        "Allow extra time on **Nifty 500** — each symbol loads ~2 years of daily bars."
    )

    if run:
        flt = Stage2ScanFilters(
            min_trend_pass=int(min_trend),
            min_vcp_score=float(min_vcp),
            min_rs_rank=float(min_rs),
            min_pct_above_52w_low=float(min_above_low),
            max_pct_below_52w_high=float(max_below_high),
            require_vcp_tightening=require_tight,
            require_volume_dryup=require_dry,
            min_breakout_vol_ratio=float(min_brk_vol),
            stage2_only=stage2_only,
        )
        prog = scan_slot.progress(0, text="Initialising…")

        def cb(i: int, t: int, sym: str) -> None:
            prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {sym}… ({i}/{t})")

        results, stats = scan_stage2_momentum(universe, flt, progress_cb=cb)
        prog.progress(100, text="Scan complete")
        st.session_state[session_results] = results
        st.session_state[session_stats] = stats
        st.session_state[session_at] = datetime.now().strftime("%d %b %Y %H:%M")
        append_scan_record(
            META["id"],
            universe,
            [r.raw_ticker for r in results],
            meta={"elapsed_sec": stats.scan_elapsed_sec, "matched": len(results)},
        )

    results = st.session_state.get(session_results, [])
    stats = st.session_state.get(session_stats)
    scan_at = st.session_state.get(session_at)

    if stats is not None:
        st.caption(
            f"Scanned **{stats.tickers_scanned}** symbols · "
            f"**{stats.tickers_matched}** matches · "
            f"{stats.no_data} no data · "
            f"{stats.scan_elapsed_sec:.1f}s"
        )

    if not results:
        if scan_at:
            no_results_state()
        else:
            st.info("👆 Choose a universe, set filters, then run **RUN STAGE 2 + VCP SCAN**.")
        return

    st.success(f"**{len(results)}** Stage 2 / VCP candidate(s)" + (f" · {scan_at}" if scan_at else ""))
    st.markdown(
        "Click a row for chart research below. Rows are sorted by **Rank score** "
        "(Composite×0.45 + RS×0.20 + VCP×0.15 + pivot/volume/action bonuses). "
        "Always confirm the base on TradingView before risking capital."
    )

    stage2_results_table(results, scan_at=scan_at, key_prefix=key)

    csv_df = results_to_dataframe(results)
    st.download_button(
        "⬇ Download results CSV",
        data=csv_df.to_csv(index=False).encode("utf-8"),
        file_name=f"stocksight_stage2_vcp_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        key=f"{key}_dl",
    )
