"""Streamlit UI — Intraday Autopilot control panel."""

from __future__ import annotations

import html
from datetime import timedelta

import pandas as pd
import streamlit as st

from intraday import DATA_SOURCE_OPTIONS, market_session_window, session_window_now
from intraday_autopilot import (
    NSE_PHASES,
    US_PHASES,
    AutopilotConfig,
    data_source_recommendation,
    resolve_phase,
    run_autopilot_tick,
    set_kill_switch,
)
from intraday_autopilot_store import load_state
try:
    from scan_progress import ScanLiveState, make_streamlit_scan_callback, render_live_scan_status
except ImportError:
    from .scan_progress import (  # type: ignore[no-redef]
        ScanLiveState,
        make_streamlit_scan_callback,
        render_live_scan_status,
    )
from ui_components import inject_css, page_audience_note, safe_set_page_config

_DATA_LABELS = {
    "auto": "Auto — Breeze if connected, else Yahoo",
    "breeze": "ICICI Breeze only (live NSE, order-ready)",
    "yahoo": "Yahoo only (faster scans, paper testing)",
}


def _render_runtime_panel(state: dict) -> None:
    rt = state.get("runtime") or {}
    status = str(rt.get("status") or "idle")
    if status == "idle" and not rt.get("ticker"):
        st.caption(f"Status: **{status}** — {rt.get('message', 'Ready for next tick')}")
        return
    pct = 0
    idx = int(rt.get("index") or 0)
    tot = int(rt.get("total") or 0)
    if tot > 0:
        pct = int(idx / tot * 100)
    api = _DATA_LABELS.get(str(rt.get("data_source") or ""), rt.get("data_source", "—"))
    st.markdown(
        f"""
<div style="font-family:'IBM Plex Mono',monospace;font-size:0.82rem;background:#1a1520;
            border:1px solid #3d2a4f;border-radius:8px;padding:12px 14px;">
  <b style="color:#f0e6ff;">Autopilot runtime</b> · {html.escape(status)} · {pct}%<br>
  <span style="color:#d4c4e8;">
    {html.escape(str(rt.get('market', '—')))} · {html.escape(str(rt.get('phase_label') or rt.get('phase_id', '—')))}
    · API: {html.escape(str(api))}
  </span><br>
  <span style="color:#b8a8cc;">
    {html.escape(str(rt.get('ticker', '')))} ({idx}/{tot})
    {(' · ' + html.escape(str(rt.get('stage')))) if rt.get('stage') else ''}
  </span>
</div>
""",
        unsafe_allow_html=True,
    )


def _summarize_tick_out(out: dict) -> str:
    lines: list[str] = []
    for mkt, tick in (out.get("markets") or {}).items():
        if not isinstance(tick, dict):
            continue
        phase = tick.get("phase_label") or tick.get("phase", "—")
        if tick.get("skipped"):
            lines.append(f"**{mkt}**: skipped — `{tick['skipped']}` (phase: {phase})")
        elif tick.get("square_off"):
            lines.append(f"**{mkt}**: square-off — {len(tick.get('square_off') or [])} action(s)")
        elif tick.get("gaps") is not None:
            lines.append(
                f"**{mkt}**: gap scan — {tick.get('gaps', 0)} gaps · "
                f"watchlist {len(tick.get('watchlist') or [])} · API `{tick.get('data_source', '—')}`"
            )
        elif tick.get("scanned") is not None:
            elapsed = tick.get("scan_elapsed_sec", "—")
            lines.append(
                f"**{mkt}**: strategy scan — {tick.get('scanned')} tickers · "
                f"{tick.get('matches', 0)} matches · {tick.get('executed', [])} · "
                f"{elapsed}s · Breeze bars {tick.get('bars_from_breeze', 0)} / "
                f"Yahoo {tick.get('bars_from_yahoo', 0)}"
            )
        elif tick.get("mode") == "manage_only":
            lines.append(f"**{mkt}**: manage-only (no new entries) · {phase}")
        else:
            lines.append(f"**{mkt}**: {phase} — {tick}")
    return "\n\n".join(lines) if lines else "No market results."


def _build_config_from_sidebar() -> AutopilotConfig:
    mode = st.session_state.get("ap_mode", "paper")
    markets = tuple(st.session_state.get("ap_mkts", ("NSE", "US")))
    return AutopilotConfig(
        mode=mode,
        markets=markets,
        min_gate_score=int(st.session_state.get("ap_gate", 58)),
        data_source_nse=str(st.session_state.get("ap_ds_nse", "auto")),
        data_source_us="yahoo",
        max_intraday_tickers=int(st.session_state.get("ap_max_tickers", 60)),
    )


def _run_tick_with_ui(cfg: AutopilotConfig, phase_override: str | None) -> dict:
    """Run tick with live UI — do not wrap in st.spinner (it hides progress updates)."""
    st.session_state["ap_scan_activity_log"] = []

    live_detail = st.empty()
    activity = st.empty()
    prog = st.progress(0, text="Autopilot starting…")
    live_state = ScanLiveState(data_source=cfg.data_source_nse)

    with st.status("Autopilot tick running…", expanded=True) as status:
        cb = make_streamlit_scan_callback(
            prog,
            live_detail,
            state=live_state,
            status_widget=status,
            activity_slot=activity,
            session_log_key="ap_scan_activity_log",
        )
        out = run_autopilot_tick(cfg, phase_override=phase_override, progress_cb=cb, persist_runtime=True)
        status.update(label="Autopilot tick complete", state="complete")

    # Keep last real scan position on the bar (do not overwrite with fake 1/1).
    if live_state.total > 0 and live_state.index > 0:
        prog.progress(
            100,
            text=f"Done — {live_state.ticker or 'scan'} ({live_state.index}/{live_state.total})",
        )
        live_state.message = "Autopilot tick finished"
        live_state.stage = "done"
        render_live_scan_status(live_state, detail_slot=live_detail)
    else:
        prog.progress(100, text="Tick finished (no ticker scan this phase)")
        live_detail.info(
            "No per-ticker scan ran for this tick. "
            "Use **Force phase** → e.g. `opening`, `orb`, or `gap_scan` during market hours, "
            "or check if session is closed / phase is manage-only / square-off."
        )

    return out


def render_intraday_autopilot_page() -> None:
    safe_set_page_config(page_title="Intraday Autopilot | StockSight", page_icon="🤖", layout="wide")
    inject_css()

    st.markdown("### 🤖 Intraday Autopilot")
    page_audience_note(
        "Traders who want a **continuous schedule** (gap → ORB → VWAP → square-off) on NSE + US.",
        "Runs six intraday strategies on a **time-based playbook**. Choose **ICICI Breeze** or **Yahoo** "
        "for scans. Default is **paper**; live orders need Breeze + env flags. "
        "**Not SEBI-certified algo deployment.**",
    )

    st.warning(
        "Autopilot can place **paper** or **live** orders. Start with **dry_run**, then **paper**, "
        "for weeks before live. India: broker-hosted algos + Algo ID required for production."
    )

    state = load_state()
    _render_runtime_panel(state)

    c1, c2 = st.columns(2)
    with c1:
        st.caption(session_window_now("NSE"))
        nse_ph = resolve_phase("NSE")
        st.caption(f"Phase: **{nse_ph.label}** (`{nse_ph.id}`) · strategies: `{','.join(nse_ph.strategies) or '—'}`")
    with c2:
        st.caption(session_window_now("US"))
        us_ph = resolve_phase("US")
        st.caption(f"Phase: **{us_ph.label}** (`{us_ph.id}`)")

    ks = st.toggle("🛑 Kill switch (blocks all autopilot actions)", value=bool(state.get("kill_switch")))
    if ks != state.get("kill_switch"):
        set_kill_switch(ks)
        state = load_state()

    with st.container(border=True):
        st.markdown("#### Controls")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.selectbox("Mode", ("dry_run", "paper", "live"), index=1, key="ap_mode")
        with m2:
            st.multiselect("Markets", ("NSE", "US"), default=("NSE", "US"), key="ap_mkts")
        with m3:
            st.slider("Min gate score", 40, 85, 58, key="ap_gate")
        with m4:
            st.selectbox(
                "Force phase (optional)",
                ["auto"] + [p.id for p in NSE_PHASES],
                key="ap_phase",
            )

        st.markdown("##### Market data API (NSE scans)")
        ds_col1, ds_col2 = st.columns([1.2, 1.0])
        with ds_col1:
            st.radio(
                "NSE intraday data",
                options=DATA_SOURCE_OPTIONS,
                format_func=lambda k: _DATA_LABELS[k],
                horizontal=True,
                key="ap_ds_nse",
            )
        with ds_col2:
            cfg_preview = _build_config_from_sidebar()
            st.caption(data_source_recommendation(cfg_preview))
            if cfg_preview.mode == "live" and st.session_state.get("ap_ds_nse") == "yahoo":
                st.warning("Live mode with Yahoo: signals only — orders still use Breeze.")

        st.slider("Max tickers per scan", 20, 120, 60, step=10, key="ap_max_tickers")

        tick_col1, tick_col2 = st.columns(2)
        with tick_col1:
            run_clicked = st.button(
                "▶ Run one autopilot tick", type="primary", use_container_width=True, key="ap_run",
            )
        with tick_col2:
            st.number_input(
                "Continuous interval (seconds)",
                min_value=60,
                max_value=900,
                value=int(st.session_state.get("ap_interval", 300)),
                step=30,
                key="ap_interval",
            )
            st.checkbox(
                "🔄 Continuous autopilot (this browser tab)",
                value=bool(st.session_state.get("ap_continuous", False)),
                key="ap_continuous",
                help="Runs one tick every interval while this page stays open. "
                "For 24/7 use scripts/run_autopilot.py --loop instead.",
            )

    if run_clicked:
        cfg = _build_config_from_sidebar()
        ph = None if st.session_state.get("ap_phase") == "auto" else st.session_state.get("ap_phase")
        out = _run_tick_with_ui(cfg, ph)
        st.session_state["ap_last_out"] = out
        st.success("Tick complete.")
        st.markdown(_summarize_tick_out(out))

    if st.session_state.get("ap_continuous"):
        interval = max(60, int(st.session_state.get("ap_interval", 300)))

        @st.fragment(run_every=timedelta(seconds=interval))
        def _continuous_tick() -> None:
            if not st.session_state.get("ap_continuous"):
                return
            state_now = load_state()
            if state_now.get("kill_switch"):
                st.error("Kill switch is ON — continuous run paused.")
                return
            cfg = _build_config_from_sidebar()
            ph = None if st.session_state.get("ap_phase") == "auto" else st.session_state.get("ap_phase")
            st.caption(f"Continuous tick · every **{interval}s** · mode **{cfg.mode}** · API **{cfg.data_source_nse}**")
            out = _run_tick_with_ui(cfg, ph)
            st.session_state["ap_last_out"] = out
            st.markdown(_summarize_tick_out(out))
            _render_runtime_panel(load_state())

        _continuous_tick()
        st.info(
            f"Continuous mode active — next tick in ~**{interval}** seconds. "
            "Keep this tab open. Phase follows the **IST/ET schedule** automatically."
        )

    state = load_state()
    _render_runtime_panel(state)

    if st.session_state.get("ap_last_out"):
        with st.expander("Last tick result (JSON)", expanded=False):
            st.json(st.session_state["ap_last_out"])

    st.markdown("#### Day state")
    for mk in ("NSE", "US"):
        ms = state.get("markets", {}).get(mk, {})
        sess = market_session_window(mk)
        st.markdown(
            f"**{mk}** — regime: `{ms.get('regime', '—')}` · trades today: {ms.get('trades_today', 0)} "
            f"· session: {'open' if sess.get('is_open') else 'closed'}"
        )
        wl = ms.get("priority_watchlist") or []
        if wl:
            st.caption("Priority watchlist: " + ", ".join(wl[:8]))

    with st.expander("NSE schedule (IST) — intraday playbook", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": p.id,
                        "label": p.label,
                        "start": f"{p.start_mins // 60:02d}:{p.start_mins % 60:02d}",
                        "end": f"{p.end_mins // 60:02d}:{p.end_mins % 60:02d}",
                        "strategies": ",".join(p.strategies) or "—",
                        "new entries": p.allow_new_entries,
                    }
                    for p in NSE_PHASES
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    with st.expander("US schedule (ET)", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": p.id,
                        "label": p.label,
                        "start": f"{p.start_mins // 60:02d}:{p.start_mins % 60:02d}",
                        "end": f"{p.end_mins // 60:02d}:{p.end_mins % 60:02d}",
                        "strategies": ",".join(p.strategies) or "—",
                        "new entries": p.allow_new_entries,
                    }
                    for p in US_PHASES
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("Event log (last 50)", expanded=False):
        log = state.get("log", [])[-50:]
        st.dataframe(pd.DataFrame(log) if log else pd.DataFrame(), hide_index=True)

    st.markdown("---")
    st.markdown(
        """
**API choice**

| Goal | NSE data API |
|------|----------------|
| Fast paper / dry-run testing | **Yahoo** |
| Live MIS orders aligned with broker | **Auto** or **Breeze** |
| Breeze token expired | **Yahoo** or refresh token (sidebar) |

**Tip:** If progress shows *no ticker scan*, your clock phase may be **EOD**, **lunch (manage-only)**, or **market closed**.  
Force phase **`gap_scan`** or **`opening`** to test a full scan with live progress.

**Continuous job (local):**
```bat
python scripts\\run_autopilot.py --loop --interval 300 --mode paper --data-source-nse auto
```
"""
    )
