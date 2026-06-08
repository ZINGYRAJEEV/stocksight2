"""Intraday Fast Movers — live speed leaderboard."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from fast_movers import (
    DATA_SOURCE_LABELS,
    DATA_SOURCE_OPTIONS,
    META,
    FastMoverFilters,
    scan_fast_movers,
    universe_options,
)
from intraday import MARKET_LABEL, MARKETS, market_session_window
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
)


def _speed_style(series: pd.Series) -> list[str]:
    styles = []
    for v in series:
        s = str(v)
        if "Blazing" in s:
            styles.append("background-color:#fee2e2;color:#991b1b;font-weight:700;")
        elif "Fast" in s:
            styles.append("background-color:#ffedd5;color:#9a3412;font-weight:600;")
        elif "Moving" in s:
            styles.append("background-color:#fef9c3;color:#854d0e;")
        else:
            styles.append("")
    return styles


def _move_style(series: pd.Series) -> list[str]:
    styles = []
    for v in series:
        try:
            x = float(v)
        except (TypeError, ValueError):
            styles.append("")
            continue
        if x >= 0.5:
            styles.append("background-color:#dcfce7;color:#166534;font-weight:600;")
        elif x >= 0.15:
            styles.append("background-color:#ecfdf5;color:#047857;")
        elif x <= -0.5:
            styles.append("background-color:#fee2e2;color:#991b1b;font-weight:600;")
        elif x <= -0.15:
            styles.append("background-color:#fef2f2;color:#b91c1c;")
        else:
            styles.append("")
    return styles


def _results_df(results: list) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        rows.append(
            {
                "Rank": i,
                "Ticker": r.ticker,
                "Speed": r.speed_tier,
                "Score": r.speed_score,
                "Direction": r.direction,
                "vs Open %": r.pct_vs_open,
                "vs Prev %": r.pct_vs_prev_close,
                "5m %": r.move_5m_pct,
                "15m %": r.move_15m_pct,
                "30m %": r.move_30m_pct,
                "Vel/5m": r.velocity_5m,
                "Vol×": r.vol_ratio,
                "Vol accel": r.vol_accel,
                "vs VWAP %": r.pct_vs_vwap,
                "RSI": r.rsi,
                "Price": r.price,
                "Sector": r.sector,
                "Bars": r.bar_interval,
                "Action": r.action,
                "Raw": r.raw_ticker,
                **{k: v for k, v in r.links.items()},
            }
        )
    return pd.DataFrame(rows)


def render_fast_movers_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.html(f"""
    <div style='background:#1c1917; border:1px solid #44403c; border-left:4px solid #facc15;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#fafaf9;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#fde68a; margin-top:6px;'>
            Who is moving fastest right now — session %, short-window velocity, volume surge
        </div>
    </div>
    """)

    page_audience_note(META["audience"], META["purpose"])
    render_watchlist_panel("fm_wl")

    key = "fastmov"
    session_results = f"{key}_results"
    session_at = f"{key}_at"
    session_stats = f"{key}_stats"

    try:
        from breeze_data import breeze_configured, breeze_status_message

        breeze_ok = breeze_configured()
        breeze_msg = breeze_status_message()
    except Exception:
        breeze_ok = False
        breeze_msg = ""

    m1, m2 = st.columns(2)
    with m1:
        market = st.radio(
            "Market",
            MARKETS,
            format_func=lambda m: MARKET_LABEL.get(m, m),
            horizontal=True,
            key=f"{key}_market",
        )
    with m2:
        sess = market_session_window(market)
        st.metric("Session", sess.get("window", "—"))
        st.caption(f"{sess.get('market_local_str', '')} · {sess.get('tip', '')}")

    ds_default = st.session_state.get(f"{key}_ds", "auto")
    if ds_default not in DATA_SOURCE_OPTIONS:
        ds_default = "auto"
    data_source = st.radio(
        "Intraday data API",
        DATA_SOURCE_OPTIONS,
        format_func=lambda k: DATA_SOURCE_LABELS[k],
        index=list(DATA_SOURCE_OPTIONS).index(ds_default),
        key=f"{key}_data_api",
        horizontal=True,
    )
    if data_source in ("auto", "breeze") and breeze_ok:
        st.caption(f"✓ {breeze_msg}")
    elif data_source == "breeze":
        st.warning("Breeze not connected — use Auto or refresh token in sidebar.")

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        uni_opts = universe_options(market)
        default_uni = next((u for u in ("Nifty 50 (fast)", "Nifty 50 (NSE)") if u in uni_opts), uni_opts[0])
        with c1:
            universe = st.selectbox(
                "Universe",
                uni_opts,
                index=uni_opts.index(default_uni) if default_uni in uni_opts else 0,
                key=f"{key}_uni",
            )
            direction = st.selectbox(
                "Direction filter",
                ("any", "up", "down"),
                format_func=lambda d: {"any": "All movers", "up": "Up burst only", "down": "Down dump only"}[d],
                key=f"{key}_dir",
            )
        with c2:
            min_score = st.slider("Min speed score", 10, 80, 30, key=f"{key}_minsc")
            min_vol = st.slider("Min volume ratio", 0.5, 3.0, 1.0, 0.1, key=f"{key}_minvol")
        with c3:
            max_n = st.slider("Max tickers", 20, 120, 60, key=f"{key}_maxn")
            auto_refresh = st.checkbox("Auto-refresh (90s)", value=False, key=f"{key}_auto")
            refresh_sec = 90

    flt = FastMoverFilters(
        universe=universe,
        market=market,
        data_source=data_source,
        min_speed_score=float(min_score),
        min_vol_ratio=float(min_vol),
        direction=direction,
        max_tickers=int(max_n),
    )

    def _run_scan() -> None:
        prog = st.progress(0, text="Scanning fast movers…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(min(99, int(100 * i / max(total, 1))), text=f"{sym} ({i}/{total})")

        results, stats = scan_fast_movers(flt, progress_cb=_cb)
        prog.progress(100, text="Done")
        st.session_state[session_results] = results
        st.session_state[session_stats] = stats
        st.session_state[session_at] = datetime.now()
        append_scan_record("fast_movers", universe, [r.raw_ticker for r in results], meta={"market": market})

    if st.button("⚡ SCAN FAST MOVERS", type="primary", key=f"{key}_run"):
        _run_scan()
        st.rerun()

    last_at: datetime | None = st.session_state.get(session_at)
    if auto_refresh:
        if last_at is None:
            _run_scan()
            st.rerun()
        else:
            elapsed = (datetime.now() - last_at).total_seconds()
            if elapsed >= refresh_sec:
                _run_scan()
                st.rerun()
            else:
                st.caption(f"⏱ Next refresh in **{int(refresh_sec - elapsed)}s**")

    results = st.session_state.get(session_results, [])
    stats = st.session_state.get(session_stats)

    if stats:
        st.caption(
            f"Scanned **{stats.tickers_scanned}** · movers **{stats.tickers_matched}** · "
            f"{stats.scan_elapsed_sec:.1f}s · API **{DATA_SOURCE_LABELS.get(stats.data_source, stats.data_source)}**"
            + (f" · {last_at.strftime('%H:%M:%S')}" if last_at else "")
        )

    with st.expander("📖 How to read this page", expanded=False):
        st.markdown(
            """
| Column | Meaning |
|--------|---------|
| **Speed score** | Composite of session %, 15m move, volume ratio & acceleration |
| **5m / 15m / 30m %** | Short-window price change (last few bars) |
| **Vel/5m** | Average % move per 5-minute bar (recent) |
| **Vol×** | Latest bar volume vs recent average |
| **Vol accel** | Recent 3 bars vs prior 3 bars volume |
| **Direction** | Green burst / red dump / choppy from bar colours |

**🔥 Blazing** ≥75 · **⚡ Fast** ≥55 · **→ Moving** ≥35 · refresh every 90s during market hours.
"""
        )

    if not results:
        st.info("Click **SCAN FAST MOVERS** or enable auto-refresh during the session.")
        return

    df = _results_df(results)
    show = [c for c in df.columns if c != "Raw"]
    styler = df[show].style.apply(_speed_style, subset=["Speed"])
    for col in ("15m %", "5m %", "vs Open %"):
        if col in show:
            styler = styler.apply(_move_style, subset=[col])

    render_clickable_scan_table(
        df[show],
        styler=styler,
        key_prefix=key,
        column_config={
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "vs Open %": st.column_config.NumberColumn(format="%+.2f"),
            "vs Prev %": st.column_config.NumberColumn(format="%+.2f"),
            "5m %": st.column_config.NumberColumn(format="%+.2f"),
            "15m %": st.column_config.NumberColumn(format="%+.2f"),
            "30m %": st.column_config.NumberColumn(format="%+.2f"),
            "Vol×": st.column_config.NumberColumn(format="%.2f"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
        },
        caption="Sorted by **speed score** — fastest movers at the top. Click a row for chart.",
        show_gate_legend=False,
    )

    top_up = [r for r in results if "Up" in r.direction][:5]
    top_dn = [r for r in results if "Down" in r.direction][:5]
    tc1, tc2 = st.columns(2)
    with tc1:
        st.markdown("**🟢 Fastest up**")
        for r in top_up:
            st.caption(f"{r.ticker} · score {r.speed_score:.0f} · 15m {r.move_15m_pct:+.2f}% · vs open {r.pct_vs_open:+.2f}%")
    with tc2:
        st.markdown("**🔴 Fastest down**")
        for r in top_dn:
            st.caption(f"{r.ticker} · score {r.speed_score:.0f} · 15m {r.move_15m_pct:+.2f}% · vs open {r.pct_vs_open:+.2f}%")

    st.caption("⚠️ Speed ≠ trade signal — confirm with intraday screener / your plan. Not financial advice.")
