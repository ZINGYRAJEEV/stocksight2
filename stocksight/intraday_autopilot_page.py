"""Streamlit UI — Intraday Autopilot control panel."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from intraday import market_session_window, session_window_now
from intraday_autopilot import (
    NSE_PHASES,
    US_PHASES,
    AutopilotConfig,
    resolve_phase,
    run_autopilot_tick,
    set_kill_switch,
)
from intraday_autopilot_store import load_state, save_state
from ui_components import inject_css, page_audience_note, safe_set_page_config


def render_intraday_autopilot_page() -> None:
    safe_set_page_config(page_title="Intraday Autopilot | StockSight", page_icon="🤖", layout="wide")
    inject_css()

    st.markdown("### 🤖 Intraday Autopilot")
    page_audience_note(
        "Traders who want a **continuous schedule** (gap → ORB → VWAP → square-off) on NSE + US.",
        "Runs your six strategies on a **time-based playbook**. Default is **paper trading** only. "
        "Live Breeze requires kill-switch off + env flags. **Not SEBI-certified algo deployment.**",
    )

    st.warning(
        "Autopilot can place **paper** or **live** orders. Start with **dry_run**, then **paper**, "
        "for weeks before considering live. India: broker-hosted algos + Algo ID required for production."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.caption(session_window_now("NSE"))
        st.caption(f"Phase: **{resolve_phase('NSE').label}** (`{resolve_phase('NSE').id}`)")
    with c2:
        st.caption(session_window_now("US"))
        st.caption(f"Phase: **{resolve_phase('US').label}** (`{resolve_phase('US').id}`)")

    state = load_state()
    ks = st.toggle("🛑 Kill switch (blocks all autopilot actions)", value=bool(state.get("kill_switch")))
    if ks != state.get("kill_switch"):
        set_kill_switch(ks)
        state = load_state()

    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            mode = st.selectbox("Mode", ("dry_run", "paper", "live"), index=1, key="ap_mode")
        with m2:
            markets = st.multiselect("Markets", ("NSE", "US"), default=("NSE", "US"), key="ap_mkts")
        with m3:
            min_gate = st.slider("Min gate score", 40, 85, 58, key="ap_gate")
        with m4:
            force_phase = st.selectbox(
                "Force phase (optional)",
                ["auto"] + [p.id for p in NSE_PHASES],
                key="ap_phase",
            )

        if st.button("▶ Run one autopilot tick", type="primary", use_container_width=True, key="ap_run"):
            cfg = AutopilotConfig(
                mode=mode,
                markets=tuple(markets),
                min_gate_score=min_gate,
            )
            ph = None if force_phase == "auto" else force_phase
            with st.spinner("Running autopilot…"):
                out = run_autopilot_tick(cfg, phase_override=ph)
            st.session_state["ap_last_out"] = out
            st.success("Tick complete.")

    if st.session_state.get("ap_last_out"):
        st.json(st.session_state["ap_last_out"])

    st.markdown("#### Day state")
    for mk in ("NSE", "US"):
        ms = state.get("markets", {}).get(mk, {})
        st.markdown(f"**{mk}** — regime: `{ms.get('regime', '—')}` · trades today: {ms.get('trades_today', 0)}")
        wl = ms.get("priority_watchlist") or []
        if wl:
            st.caption("Priority watchlist: " + ", ".join(wl[:8]))

    with st.expander("NSE schedule (IST)", expanded=False):
        st.dataframe(
            pd.DataFrame([{"id": p.id, "label": p.label, "start": p.start_mins, "end": p.end_mins,
                           "strategies": ",".join(p.strategies), "entries": p.allow_new_entries} for p in NSE_PHASES]),
            hide_index=True,
        )
    with st.expander("US schedule (ET)", expanded=False):
        st.dataframe(
            pd.DataFrame([{"id": p.id, "label": p.label, "start": p.start_mins, "end": p.end_mins,
                           "strategies": ",".join(p.strategies), "entries": p.allow_new_entries} for p in US_PHASES]),
            hide_index=True,
        )

    with st.expander("Event log (last 50)", expanded=False):
        log = state.get("log", [])[-50:]
        st.dataframe(pd.DataFrame(log) if log else pd.DataFrame(), hide_index=True)

    st.markdown("---")
    st.markdown(
        """
**Continuous job (local):**
```bat
python scripts\\run_autopilot.py --loop --interval 300 --mode paper
```

**GitHub Actions:** workflow `intraday-autopilot.yml` runs paper ticks on schedule.

**Live (only if you accept full risk):**
```bat
set AUTOPILOT_ENABLED=true
set AUTOPILOT_LIVE_CONFIRM=YES
python scripts\\run_autopilot.py --once --mode live --markets NSE
```
"""
    )
