"""
Live NSE Screener — auto-refreshing Healthy Dip scan (same engine as Flask dashboard).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from live_screener.engine import PRESETS, ScanConfig, run_healthy_dip_scan  # noqa: E402
from screener import NIFTY_BENCHMARK, index_regime  # noqa: E402
from ui_components import safe_set_page_config  # noqa: E402

safe_set_page_config(page_title="Live NSE Screener | StockSight", page_icon="📡", layout="wide")

st.markdown("""
<style>
  section.main, section.main .block-container {
    background: #0a1210; color: #e8f7ef;
  }
  .live-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.8rem; color: #25d366; font-weight: 700;
  }
  .pass-chip {
    display: inline-block; background: #0f2a22; border: 1px solid #25d366;
    color: #25d366; border-radius: 4px; padding: 2px 8px; font-size: 0.7rem;
    margin-right: 4px;
  }
</style>
""", unsafe_allow_html=True)

if "live_nse_rows" not in st.session_state:
    st.session_state.live_nse_rows = []
if "live_nse_last_run" not in st.session_state:
    st.session_state.live_nse_last_run = None
if "live_nse_running" not in st.session_state:
    st.session_state.live_nse_running = False

st.markdown('<div class="live-title">📡 Live NSE Screener</div>', unsafe_allow_html=True)
st.caption(
    "Automatically scans NSE universes for **Healthy Dip** criteria (ROE, debt, P/E, 52w drawdown, RSI, 200-DMA). "
    "Standalone dashboard: `python run_live_screener.py` → http://127.0.0.1:5000"
)

with st.container(border=True):
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        preset = st.selectbox(
            "Preset",
            list(PRESETS.keys()),
            format_func=lambda k: PRESETS[k]["label"],
            key="live_nse_preset",
        )
    with c2:
        auto = st.checkbox("Auto-refresh (5 min)", value=True, key="live_nse_auto")
        explain = st.checkbox("Why it fell", value=True, key="live_nse_explain")
    with c3:
        run = st.button("▶ Scan now", use_container_width=True, key="live_nse_run")
        st.link_button("Open Flask dashboard", "http://127.0.0.1:5000", use_container_width=True)

p = PRESETS[preset]
st.info(f"Universe: **{p['universe']}** · {p['label']}")

reg = index_regime(NIFTY_BENCHMARK)
if reg.get("error"):
    st.caption(f"Nifty regime: {reg['error']}")
else:
    flag = "above" if reg.get("above_ma") else "below"
    st.caption(
        f"Nifty (^NSEI): {reg.get('price')} vs 200-DMA {reg.get('ma')} "
        f"(price {flag} MA, {reg.get('pct_vs_ma'):+.1f}% vs MA)"
    )


def _do_scan() -> None:
    st.session_state.live_nse_running = True
    prog = st.progress(0, text="Starting NSE scan…")
    status = st.empty()

    def cb(i: int, t: int, sym: str) -> None:
        pct = int(i / max(t, 1) * 100)
        prog.progress(pct, text=f"Scanning {sym}… ({i}/{t})")
        status.caption(f"Processing **{sym}** — matches so far depend on filters.")

    cfg = ScanConfig(preset=preset, explain_fall=explain)
    rows = run_healthy_dip_scan(cfg, progress_cb=cb)
    prog.progress(100, text="Done")
    status.empty()
    st.session_state.live_nse_rows = rows
    st.session_state.live_nse_last_run = datetime.now()
    st.session_state.live_nse_running = False


if run and not st.session_state.live_nse_running:
    _do_scan()

if auto and st.session_state.live_nse_last_run and not st.session_state.live_nse_running:
    elapsed = (datetime.now() - st.session_state.live_nse_last_run).total_seconds()
    if elapsed >= 300:
        _do_scan()
    else:
        st.caption(f"⏱ Next auto-scan in {int(300 - elapsed)}s")

rows = st.session_state.live_nse_rows
if not rows and st.session_state.live_nse_last_run is None:
    st.warning("Click **Scan now** or wait for auto-refresh to populate live matches.")
elif not rows:
    st.warning("No names passed all filters this run.")
else:
    st.success(f"**{len(rows)}** stocks meet all Healthy Dip conditions (highlighted).")
    if st.session_state.live_nse_last_run:
        st.caption(f"Last run: {st.session_state.live_nse_last_run.strftime('%H:%M:%S %d %b %Y')}")

    df = pd.DataFrame(rows)
    show_cols = [
        "ticker", "price", "roe_pct", "debt_equity", "pe",
        "drawdown_52w_pct", "rsi", "pct_vs_ma200", "fall_context", "sector",
    ]
    show_cols = [c for c in show_cols if c in df.columns]
    display = df[show_cols].copy()
    display.columns = [
        "Ticker", "Price", "ROE %", "D/E", "P/E", "↓52w %", "RSI", "vs 200MA %",
        "Why it fell", "Sector",
    ][: len(show_cols)]

    def _highlight(row: pd.Series):
        if bool(df.loc[row.name, "all_conditions_met"]):
            return ["background-color: #0f2a22"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display.style.apply(_highlight, axis=1),  # type: ignore[arg-type]
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Raw links & criteria flags"):
        st.dataframe(
            df[["ticker", "all_conditions_met", "criteria", "yahoo", "research", "chart"]],
            use_container_width=True,
            hide_index=True,
        )

st.caption("⚠️ Educational only · Yahoo Finance data · Not financial advice.")
