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
from ui_components import (  # noqa: E402
    filter_column_config,
    render_clickable_scan_table,
    safe_set_page_config,
)

safe_set_page_config(page_title="Live NSE Screener | StockSight", page_icon="📡", layout="wide")

st.markdown("""
<style>
  .live-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.8rem; color: #059669; font-weight: 700;
  }
  /* Styled dataframe: keep cell text readable on pass-row highlight */
  section.main [data-testid="stDataFrame"] td {
    color: #111827 !important;
  }
</style>
""", unsafe_allow_html=True)

_PASS_ROW_STYLE = "background-color: #d1fae5; color: #064e3b"

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
    n_pass = sum(1 for r in rows if r.get("all_conditions_met"))
    st.success(f"**{n_pass}** of **{len(rows)}** stocks meet all Healthy Dip conditions (highlighted).")
    if st.session_state.live_nse_last_run:
        st.caption(f"Last run: {st.session_state.live_nse_last_run.strftime('%H:%M:%S %d %b %Y')}")

    df = pd.DataFrame(rows)
    show_cols = [
        "ticker", "price", "roe_pct", "debt_equity", "pe",
        "drawdown_52w_pct", "rsi", "pct_vs_ma200", "fall_context", "sector",
    ]
    show_cols = [c for c in show_cols if c in df.columns]
    display = df[show_cols].copy()
    if "debt_equity" in display.columns:
        display["debt_equity"] = display["debt_equity"].apply(
            lambda v: "n/a" if v is None or (isinstance(v, float) and pd.isna(v)) else round(float(v), 2)
        )
    if "pct_vs_ma200" in display.columns:
        display["pct_vs_ma200"] = display["pct_vs_ma200"].apply(
            lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else round(float(v), 1)
        )
    display.columns = [
        "Ticker", "Price", "ROE %", "D/E", "P/E", "↓52w %", "RSI", "vs 200MA %",
        "Why it fell", "Sector",
    ][: len(show_cols)]

    # Enrich display with canonical link columns + matrix note so the pre-buy
    # research card can render clickable chips. These columns are hidden in the
    # visible table via column_config={col: None}.
    hidden_cols: list[str] = []
    for src, dst in (
        ("yahoo", "Yahoo Finance"),
        ("google", "Google Finance"),
        ("research", "Moneycontrol"),
        ("chart", "TradingView"),
        ("decision", "Decision"),
        ("matrix_note", "Matrix note"),
    ):
        if src in df.columns and dst not in display.columns:
            display[dst] = df[src].values
            hidden_cols.append(dst)
    hide_cfg = {c: None for c in hidden_cols}

    def _highlight(row: pd.Series):
        if bool(df.loc[row.name, "all_conditions_met"]):
            return [_PASS_ROW_STYLE] * len(row)
        return [""] * len(row)

    render_clickable_scan_table(
        display,
        key_prefix="live_nse_results",
        universe_name="NSE",
        hide_index=True,
        column_config=hide_cfg or None,
        styler=display.style.apply(_highlight, axis=1),  # type: ignore[arg-type]
    )

    csv_cols = [c for c in (*show_cols, "yahoo", "google", "research", "chart") if c in df.columns]
    csv_df = df[csv_cols].rename(
        columns={
            "yahoo": "Yahoo Finance",
            "google": "Google Finance",
            "research": "Research",
            "chart": "Chart",
        }
    )
    st.download_button(
        "⬇ Download Live NSE results CSV",
        csv_df.to_csv(index=False).encode("utf-8"),
        file_name=f"stocksight_live_nse_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="live_nse_dl_csv",
    )

    with st.expander("Raw links & criteria flags"):
        link_cols = [
            c
            for c in ("ticker", "all_conditions_met", "criteria", "yahoo", "google", "research", "chart")
            if c in df.columns
        ]
        links_df = df[link_cols].copy()
        for col in ("yahoo", "google", "research", "chart"):
            if col in links_df.columns:
                links_df[col] = links_df[col].apply(
                    lambda u: u if isinstance(u, str) and u.startswith("http") else None
                )
        links_df = links_df.rename(
            columns={
                "yahoo": "Yahoo Finance",
                "google": "Google Finance",
                "research": "Research",
                "chart": "Chart",
            },
        )
        link_col_cfg = {
            "ticker": st.column_config.TextColumn("Ticker", width="small"),
            "all_conditions_met": st.column_config.CheckboxColumn("All pass"),
            "criteria": st.column_config.TextColumn("Criteria", width="medium"),
            "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
            "Research": st.column_config.LinkColumn("Research", display_text="Research ↗"),
            "Chart": st.column_config.LinkColumn("Chart", display_text="Chart ↗"),
        }
        st.dataframe(
            links_df,
            use_container_width=True,
            hide_index=True,
            column_config=filter_column_config(links_df, link_col_cfg),
        )

st.caption("⚠️ Educational only · Yahoo Finance data · Not financial advice.")
