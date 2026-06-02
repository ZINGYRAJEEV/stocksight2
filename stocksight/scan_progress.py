"""
Live scan status + API speed benchmark helpers for Streamlit screeners.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Optional

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]


@dataclass
class ScanLiveState:
    """Mutable state updated by scan progress callbacks."""

    index: int = 0
    total: int = 0
    ticker: str = ""
    stage: str = ""
    message: str = ""
    data_source: str = "auto"
    elapsed_sec: float = 0.0
    eta_sec: Optional[float] = None
    last_ms: float = 0.0
    last_bar_source: str = ""
    last_outcome: str = ""
    matched: int = 0
    no_data: int = 0
    filtered: int = 0
    started_at: float = field(default_factory=perf_counter)

    def tick(
        self,
        index: int,
        total: int,
        ticker: str,
        *,
        stage: str = "",
        message: str = "",
        data_source: str = "",
        last_ms: float = 0.0,
        last_bar_source: str = "",
        last_outcome: str = "",
        matched: Optional[int] = None,
        no_data: Optional[int] = None,
        filtered: Optional[int] = None,
    ) -> None:
        self.index = index
        self.total = total
        self.ticker = ticker
        if stage:
            self.stage = stage
        if message:
            self.message = message
        if data_source:
            self.data_source = data_source
        self.elapsed_sec = perf_counter() - self.started_at
        if index > 0 and total > 0:
            self.eta_sec = (self.elapsed_sec / index) * max(0, total - index)
        else:
            self.eta_sec = None
        if last_ms:
            self.last_ms = last_ms
        if last_bar_source:
            self.last_bar_source = last_bar_source
        if last_outcome:
            self.last_outcome = last_outcome
        if matched is not None:
            self.matched = matched
        if no_data is not None:
            self.no_data = no_data
        if filtered is not None:
            self.filtered = filtered


_STAGE_LABELS = {
    "fetch": "Fetching bars + daily",
    "evaluate": "Evaluating strategies",
    "done": "Ticker complete",
    "skip": "Skipped",
    "gap_scan": "Gap scan",
    "phase": "Phase",
    "benchmark": "Benchmark",
}


def _fmt_eta(sec: Optional[float]) -> str:
    if sec is None or sec < 0:
        return "—"
    if sec < 60:
        return f"{sec:.0f}s"
    return f"{int(sec // 60)}m {int(sec % 60)}s"


def render_live_scan_status(state: ScanLiveState, *, detail_slot: Any) -> None:
    """Render the live status block into a Streamlit empty() slot."""
    if st is None or detail_slot is None:
        return
    pct = int(state.index / max(state.total, 1) * 100)
    stage_txt = _STAGE_LABELS.get(state.stage, state.stage or "Working")
    api = {"auto": "Auto", "breeze": "ICICI Breeze", "yahoo": "Yahoo Finance"}.get(
        state.data_source, state.data_source
    )
    bar_note = ""
    if state.last_bar_source:
        bar_note = f" · bars: <b>{html.escape(state.last_bar_source)}</b>"
    outcome_note = ""
    if state.last_outcome:
        outcome_note = f" · last: <code>{html.escape(state.last_outcome)}</code>"
    msg = html.escape(state.message) if state.message else ""
    detail_slot.markdown(
        f"""
<div style="font-family:'IBM Plex Mono',monospace;font-size:0.82rem;
            background:#0f1a24;border:1px solid #1e3a4f;border-radius:8px;padding:12px 14px;">
  <div style="color:#7ec8e3;margin-bottom:6px;"><b style="color:#e8f4fc;">Scan in progress</b> · {pct}% · API: {html.escape(api)}</div>
  <div style="color:#c5e8f7;">
    <b>{html.escape(state.ticker or "—")}</b> ({state.index}/{state.total})
    · <span style="color:#8fd4ff;">{html.escape(stage_txt)}</span>
    {bar_note}{outcome_note}
  </div>
  {f'<div style="color:#9ab;margin-top:4px;">{msg}</div>' if msg else ''}
  <div style="color:#6a9fb8;margin-top:8px;display:flex;gap:16px;flex-wrap:wrap;">
    <span>Elapsed <b>{state.elapsed_sec:.1f}s</b></span>
    <span>ETA <b>{_fmt_eta(state.eta_sec)}</b></span>
    <span>Last fetch <b>{state.last_ms:.0f} ms</b></span>
    <span>Matched <b>{state.matched}</b></span>
    <span>No data <b>{state.no_data}</b></span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def make_streamlit_scan_callback(
    progress_bar: Any,
    detail_slot: Any,
    *,
    state: ScanLiveState,
    status_widget: Any = None,
    activity_slot: Any = None,
    session_log_key: str = "scan_activity_log",
    max_log_lines: int = 12,
) -> Callable[..., None]:
    """Build a progress callback compatible with scan_intraday extended kwargs."""

    def _append_log(line: str) -> None:
        if st is None:
            return
        log: list[str] = list(st.session_state.get(session_log_key, []))
        log.append(line)
        st.session_state[session_log_key] = log[-max_log_lines:]
        if activity_slot is not None:
            activity_slot.code("\n".join(st.session_state[session_log_key]), language=None)

    def cb(index: int, total: int, ticker: str, **kwargs: Any) -> None:
        # Phase-only pings (0/1) should not overwrite a real scan progress bar.
        stage_raw = str(kwargs.get("stage") or "")
        if stage_raw == "phase" and total <= 1 and not ticker:
            msg = str(kwargs.get("message") or "Starting…")
            if status_widget is not None:
                status_widget.update(label=msg)
            _append_log(msg)
            return

        state.tick(
            index,
            total,
            ticker,
            stage=stage_raw,
            message=str(kwargs.get("message") or ""),
            data_source=str(kwargs.get("data_source") or state.data_source),
            last_ms=float(kwargs.get("last_ms") or 0.0),
            last_bar_source=str(kwargs.get("last_bar_source") or ""),
            last_outcome=str(kwargs.get("last_outcome") or ""),
            matched=kwargs.get("matched"),
            no_data=kwargs.get("no_data"),
            filtered=kwargs.get("filtered"),
        )
        pct = int(index / max(total, 1) * 100)
        stage = _STAGE_LABELS.get(state.stage, state.stage or "Scanning")
        label = f"{stage}: {ticker} ({index}/{total})" if ticker else f"{stage} ({index}/{total})"
        progress_bar.progress(pct, text=label)
        render_live_scan_status(state, detail_slot=detail_slot)
        if status_widget is not None:
            status_widget.update(label=label)
        _append_log(label)

    return cb
