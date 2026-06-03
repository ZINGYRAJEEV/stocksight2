"""Streamlit UI — IntraBot intraday automation screener + event log."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from intraday import DATA_SOURCE_OPTIONS, session_window_now
from intrabot.config import IntraBotConfig, RISK
from intrabot.engine import run_intrabot_tick
from intrabot.scheduler import resolve_phase, schedule_table
from intrabot.store import load_state, save_state
try:
    from scan_progress import ScanLiveState, make_streamlit_scan_callback, render_live_scan_status
except ImportError:
    from .scan_progress import (  # type: ignore[no-redef]
        ScanLiveState,
        make_streamlit_scan_callback,
        render_live_scan_status,
    )
from ui_components import inject_css, page_audience_note, safe_set_page_config


def _cfg_from_ui() -> IntraBotConfig:
    return IntraBotConfig(
        paper_trade=st.session_state.get("ib_paper", True),
        markets=tuple(st.session_state.get("ib_mkts", ("NSE", "US"))),
        data_source_nse=st.session_state.get("ib_ds", "auto"),
        max_scan_tickers=int(st.session_state.get("ib_max_t", 60)),
        mood_shortlist_size=int(st.session_state.get("ib_mood_n", 3)),
        monitor_interval_sec=int(st.session_state.get("ib_mon_iv", 60)),
        force_phase=st.session_state.get("ib_force", "") or "",
        kill_switch=bool(st.session_state.get("ib_kill", False)),
        risk=RISK,
    )


def _run_tick_ui(cfg: IntraBotConfig, mode: str = "auto") -> dict:
    st.session_state["ib_activity"] = []
    live_detail = st.empty()
    activity = st.empty()
    prog = st.progress(0, text="IntraBot starting…")
    live = ScanLiveState(data_source=cfg.data_source_nse)
    cb = make_streamlit_scan_callback(
        prog, live_detail, state=live, activity_slot=activity, session_log_key="ib_activity",
    )
    with st.status("IntraBot running…", expanded=True) as status:
        out = run_intrabot_tick(cfg, mode=mode, progress_cb=cb)
        status.update(label="IntraBot tick complete", state="complete")
    if live.total > 0:
        render_live_scan_status(live, detail_slot=live_detail)
    else:
        prog.progress(100, text="Tick complete")
    return out


def render_intrabot_page() -> None:
    safe_set_page_config(page_title="IntraBot | StockSight", page_icon="🤖", layout="wide")
    inject_css()

    st.markdown("### 🤖 IntraBot — Intraday Automation Engine")
    page_audience_note(
        "Fully automated intraday scanner + trader for **NSE (Nifty)** and **US (NYSE)**. "
        "Paper mode by default; plug in Breeze / Alpaca keys for live.",
        "Follows the **CEST/IST session playbook**: gap → ORB → VWAP → square-off. "
        "Event log records every scan, order, trail stop, and halt.",
    )

    state = load_state()
    rt = state.get("runtime") or {}
    if rt:
        st.caption(
            f"Runtime: **{rt.get('status', '—')}** · {rt.get('market', '')} · "
            f"{rt.get('phase_label', rt.get('message', ''))}"
        )

    c1, c2 = st.columns(2)
    with c1:
        st.caption(session_window_now("NSE"))
        ph = resolve_phase("NSE")
        st.caption(f"NSE phase: **{ph.label}** (`{ph.id}`)")
    with c2:
        st.caption(session_window_now("US"))
        phu = resolve_phase("US")
        st.caption(f"US phase: **{phu.label}** (`{phu.id}`)")

    with st.container(border=True):
        st.markdown("#### Controls")
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.toggle("Paper trade (default)", value=True, key="ib_paper")
            st.toggle("Kill switch", value=bool(state.get("kill_switch")), key="ib_kill")
        with r2:
            st.multiselect("Markets", ("NSE", "US"), default=("NSE", "US"), key="ib_mkts")
            st.selectbox(
                "Tick mode",
                ("auto", "scan", "monitor"),
                format_func=lambda x: {"auto": "Full tick + monitor", "scan": "Scan only", "monitor": "Position monitor"}[x],
                key="ib_mode",
            )
        with r3:
            phases = ["", "gap_scan", "mood", "open_scan", "orb", "vwap_ath", "afternoon", "square_off", "us_gap", "us_square_off"]
            st.selectbox("Force phase", phases, key="ib_force")
            st.slider("Max scan tickers", 20, 120, 60, key="ib_max_t")
        with r4:
            st.radio("NSE data API", DATA_SOURCE_OPTIONS, horizontal=True, key="ib_ds")
            st.slider("Mood shortlist size", 1, 8, 3, key="ib_mood_n")

        st.markdown("##### Risk (config.py defaults)")
        rk1, rk2, rk3, rk4, rk5 = st.columns(5)
        rk1.metric("Capital / trade", f"{RISK.capital_per_trade_pct}%")
        rk2.metric("Max positions", RISK.max_open_positions)
        rk3.metric("Stop / Target R:R", f"{RISK.stop_loss_pct}% / 1:{RISK.target_rr}")
        rk4.metric("Trail after", f"+{RISK.trail_stop_after_pct}%")
        rk5.metric("Daily loss halt", f"-{RISK.max_daily_loss_pct}%")

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("▶ Run IntraBot tick", type="primary", use_container_width=True):
                cfg = _cfg_from_ui()
                state["kill_switch"] = cfg.kill_switch
                out = _run_tick_ui(cfg, mode=st.session_state.get("ib_mode", "auto"))
                st.session_state["ib_last"] = out
                st.success("Tick finished — see event log below.")
        with b2:
            st.number_input("Monitor interval (sec)", 30, 300, 60, key="ib_mon_iv")
            st.checkbox("Continuous IntraBot (this tab)", key="ib_continuous")
        with b3:
            if st.button("Clear event log", use_container_width=True):
                state = load_state()
                state["log"] = []
                save_state(state)
                st.rerun()

    if st.session_state.get("ib_continuous"):
        iv = max(30, int(st.session_state.get("ib_mon_iv", 60)))

        @st.fragment(run_every=timedelta(seconds=iv))
        def _loop() -> None:
            if not st.session_state.get("ib_continuous"):
                return
            cfg = _cfg_from_ui()
            _run_tick_ui(cfg, mode="auto")

        _loop()
        st.info(f"Continuous mode — tick + monitor every **{iv}s**. Keep this tab open.")

    if st.session_state.get("ib_last"):
        with st.expander("Last tick JSON", expanded=False):
            st.json(st.session_state["ib_last"])

    st.markdown("#### 📜 Event log")
    state = load_state()
    log = state.get("log", [])
    if log:
        df = pd.DataFrame(log[::-1])
        show_cols = [c for c in ("at", "level", "market", "event", "message") if c in df.columns]
        st.dataframe(df[show_cols] if show_cols else df, use_container_width=True, hide_index=True, height=420)
    else:
        st.caption("No events yet — run a tick to populate the log.")

    t1, t2 = st.tabs(["NSE schedule (IST)", "US schedule (ET)"])
    with t1:
        st.dataframe(pd.DataFrame(schedule_table("NSE")), hide_index=True, use_container_width=True)
    with t2:
        st.dataframe(pd.DataFrame(schedule_table("US")), hide_index=True, use_container_width=True)

    with st.expander("Architecture", expanded=False):
        st.markdown(
            """
```
intrabot/
├── config.py          ← Risk + broker keys
├── data_fetcher.py    ← yfinance / Breeze bars + RSI, EMA, VWAP, ATR
├── strategies.py      ← 6 scanners (via intraday engine)
├── risk_manager.py    ← Sizing, trailing stops, daily halt
├── executor.py        ← Paper / Breeze / Alpaca stub
├── alerts.py          ← Log + webhook
├── scheduler.py       ← Session phases
└── engine.py          ← Orchestrator

CLI: python scripts/run_intrabot.py --loop
```
"""
        )
