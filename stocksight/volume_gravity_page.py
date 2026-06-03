"""Streamlit page — Volume Gravity (VWAP / RVOL / POC / ORB)."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from scan_history_store import append_scan_record
from volume_gravity import (
    META,
    MODES,
    MARKETS,
    VolumeGravityFilters,
    scan_volume_gravity,
    universe_options,
)
from volume_gravity_ui import (
    no_results_state,
    render_education_panels,
    results_to_dataframe,
    volume_gravity_header,
    volume_gravity_table,
)
from ui_components import (
    inject_css,
    page_audience_note,
    render_watchlist_panel,
    safe_set_page_config,
)

try:
    from intraday import DATA_SOURCE_OPTIONS, MARKET_LABEL
except ImportError:
    from .intraday import DATA_SOURCE_OPTIONS, MARKET_LABEL  # type: ignore[no-redef]

_DATA_LABELS = {"auto": "Auto (Breeze if available)", "breeze": "ICICI Breeze", "yahoo": "Yahoo Finance"}


def render_volume_gravity_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()
    volume_gravity_header()
    page_audience_note(META["audience"], META["purpose"])
    render_education_panels()
    render_watchlist_panel("vg_wl")

    key = "vg"
    session_results = f"{key}_results"
    session_stats = f"{key}_stats"
    session_at = f"{key}_at"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.0, 1.1])
        with c1:
            st.markdown("#### Mode & market")
            mode = st.radio(
                "Timeframe",
                MODES,
                format_func=lambda m: "⚡ Intraday (today’s session)" if m == "intraday" else "📅 Swing (daily POC/VA)",
                horizontal=True,
                key=f"{key}_mode",
            )
            market = st.radio(
                "Market",
                MARKETS,
                format_func=lambda m: MARKET_LABEL.get(m, m),
                horizontal=True,
                key=f"{key}_market",
            )
            uni_opts = universe_options(mode, market)
            universe = st.selectbox("Universe", uni_opts, key=f"{key}_universe")
        with c2:
            st.markdown("#### Handbook filters")
            min_gap = st.slider("Min |gap| % (Gap & Go)", 0.0, 8.0, 2.0, 0.5, key=f"{key}_gap")
            min_rvol = st.slider("Min RVOL (rel. volume)", 1.0, 6.0, 2.0, 0.5, key=f"{key}_rvol")
            min_score = st.slider("Min gravity score", 20, 85, 45, 5, key=f"{key}_score")
        with c3:
            st.markdown("#### Setups to include")
            st.multiselect(
                "Setup types",
                ["GAP_GO", "VWAP_HOLD", "ORB_VWAP", "POC_BREAKOUT", "WATCH"],
                default=["GAP_GO", "VWAP_HOLD", "ORB_VWAP", "POC_BREAKOUT", "WATCH"],
                format_func=lambda s: {
                    "GAP_GO": "Gap & Go",
                    "VWAP_HOLD": "VWAP hold",
                    "ORB_VWAP": "ORB + VWAP",
                    "POC_BREAKOUT": "POC breakout",
                    "WATCH": "Volume watch",
                }.get(s, s),
                key=f"{key}_setups",
            )
            require_vwap = st.checkbox("Longs only — price above VWAP", value=False, key=f"{key}_vwap")

    with st.expander("⚙ Advanced", expanded=False):
        data_source = "yahoo"
        if mode == "intraday" and market == "NSE":
            data_source = st.selectbox(
                "Intraday data API",
                DATA_SOURCE_OPTIONS,
                format_func=lambda x: _DATA_LABELS.get(x, x),
                key=f"{key}_ds",
            )
        else:
            st.caption("Swing mode uses **daily Yahoo** bars. US intraday uses Yahoo.")

    scan_slot = st.empty()
    run = st.button("▶  RUN VOLUME GRAVITY SCAN", use_container_width=True, key=f"{key}_run")
    if mode == "intraday":
        st.caption(
            "Best after **9:45 AM IST** (ORB formed) or **10:30 AM** for VWAP pullbacks. "
            "US: after **9:45 AM ET**."
        )
    else:
        st.caption("Swing mode maps **20–40 day** volume profile and **20-day VWAP** on daily bars.")

    if run:
        setups = tuple(st.session_state.get(f"{key}_setups", ("GAP_GO", "VWAP_HOLD", "ORB_VWAP", "POC_BREAKOUT", "WATCH")))
        flt = VolumeGravityFilters(
            min_gap_pct=float(min_gap),
            min_rvol=float(min_rvol),
            min_gravity_score=float(min_score),
            require_above_vwap_long=bool(require_vwap),
            setups=setups,
        )
        ds = st.session_state.get(f"{key}_ds", "auto") if mode == "intraday" else "yahoo"
        prog = scan_slot.progress(0, text="Initialising…")

        def cb(i: int, t: int, sym: str) -> None:
            prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {sym}… ({i}/{t})")

        results, stats = scan_volume_gravity(
            universe,
            mode,
            market=market,
            filters=flt,
            progress_cb=cb,
            data_source=ds,
        )
        prog.progress(100, text="Done")
        st.session_state[session_results] = results
        st.session_state[session_stats] = stats
        st.session_state[session_at] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{key}_scan_market"] = market
        append_scan_record(
            META["id"],
            universe,
            [r.raw_ticker for r in results],
            meta={"mode": mode, "market": market, "matched": len(results)},
        )

    results = st.session_state.get(session_results, [])
    stats = st.session_state.get(session_stats)
    scan_at = st.session_state.get(session_at)
    scan_market = st.session_state.get(f"{key}_scan_market", market)

    if stats is not None:
        st.caption(
            f"**{stats.tickers_matched}** matches · **{stats.tickers_scanned}** scanned · "
            f"{stats.no_data} no data · {stats.scan_elapsed_sec:.1f}s · mode **{stats.mode}**"
        )

    if not results:
        if scan_at:
            no_results_state(mode)
        else:
            st.info("👆 Pick **Intraday** or **Swing**, set filters, and run the scan.")
        return

    st.success(
        f"**{len(results)}** volume-gravity setup(s) · {mode} · {scan_at or ''}"
    )
    volume_gravity_table(results, scan_at=scan_at, key_prefix=key, market=scan_market)

    st.download_button(
        "⬇ Download CSV",
        data=results_to_dataframe(results).to_csv(index=False).encode("utf-8"),
        file_name=f"stocksight_volume_gravity_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        key=f"{key}_dl",
    )
