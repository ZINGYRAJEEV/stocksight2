"""BTST Screener — Buy Today, Sell Tomorrow (close-strength EOD scan)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from btst_screener import (
    META,
    BtstFilters,
    ist_session_hint,
    scan_btst,
    universe_options,
)
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
    stock_sight_overlay_column_config,
)

IST = ZoneInfo("Asia/Kolkata")

_GRADE_STYLE = {
    "A": "background-color:#dcfce7;color:#166534;font-weight:700;",
    "B": "background-color:#fef9c3;color:#854d0e;font-weight:600;",
}


def _rules_panel() -> None:
    with st.expander("📖 BTST methodology & rules", expanded=True):
        st.markdown(
            """
**Edge:** Stocks that **close in the top quartile** of the day's range on **≥1.8× volume**
tend to continue into the **next morning** (9:15–9:45 AM IST). Expectancy is small (~1%/trade)
but repeatable with discipline.

| Phase | Rule |
|-------|------|
| **Scan** | **2:45–3:20 PM IST** on today's daily bar |
| **Entry** | **3:25–3:28 PM** — Grade **A** (full size) or **B** (half size) |
| **Exit** | Book on gap-up open; **100% flat by 10:00 AM** next day |
| **Stop** | **−1.5%** from entry or below **prior day low** |

**Grade A:** Score ≥ 70 · CPR ≥ 75% · Vol ≥ 1.8× · Green day · RSI 50–78

**Grade B:** Score ≥ 55 · CPR ≥ 60% · Vol ≥ 1.4×

**Skip BTST on:** expiry day, major macro events, exchange clarification names, weak closes.
"""
        )
        st.code(
            "\n".join(
                [
                    "CPR = (Close - Low) / (High - Low) × 100",
                    "Vol× = Today volume / 20-day average",
                    "Target T1: +2% (book 40%) · T2: +3.5% (book 40%) · Runner: exit 10:00 AM",
                    "Morning: Gap-up ≥1.5% → sell 50% at open",
                ]
            ),
            language="text",
        )


def _results_df(results: list) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        rows.append(
            {
                "Rank": i,
                "Grade": r.grade,
                "Ticker": r.ticker,
                "Score": r.btst_score,
                "CPR %": r.cpr_pct,
                "Vol×": r.vol_ratio,
                "Day %": r.pct_vs_prev_close,
                "RSI": r.rsi,
                "vs MA20 %": r.pct_vs_ma20,
                "Price": r.price,
                "Stop": r.stop_price,
                "T1 %": r.target_t1_pct,
                "T2 %": r.target_t2_pct,
                "Entry": r.entry_window,
                "Sector": r.sector,
                "Morning exit": r.morning_rule[:90] + ("…" if len(r.morning_rule) > 90 else ""),
                "Notes": " · ".join(r.pass_notes[:3]),
                "Raw": r.raw_ticker,
                **{k: v for k, v in r.links.items()},
            }
        )
    return pd.DataFrame(rows)


def _render_pick_card(r) -> None:
    st.markdown(f"#### {r.ticker} · Grade **{r.grade}** · Score **{r.btst_score:.0f}**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CPR (close strength)", f"{r.cpr_pct:.0f}%")
    c2.metric("Vol × 20D", f"{r.vol_ratio:.1f}")
    c3.metric("Day %", f"{r.pct_vs_prev_close:+.2f}%")
    c4.metric("RSI", f"{r.rsi:.1f}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"₹{r.price:,.2f}")
    c2.metric("Stop", f"₹{r.stop_price:,.2f}")
    c3.metric("Day range", f"₹{r.day_low:,.2f} – ₹{r.day_high:,.2f}")
    c4.metric("Prev close", f"₹{r.prev_close:,.2f}")

    st.success(f"**Entry:** {r.entry_window} · **T1** +{r.target_t1_pct}% · **T2** +{r.target_t2_pct}%")
    st.info(f"**Tomorrow morning:** {r.morning_rule}")
    if r.pass_notes:
        st.caption(" · ".join(r.pass_notes))


def render_btst_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    phase, hint = ist_session_hint()
    now_ist = datetime.now(tz=IST).strftime("%d %b %Y %H:%M IST")

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    if phase == "BTST_WINDOW":
        st.success(f"**{now_ist}** — {hint}")
    elif phase == "ENTRY_WINDOW":
        st.warning(f"**{now_ist}** — {hint}")
    else:
        st.caption(f"**{now_ist}** — {hint}")

    try:
        from breeze_data import breeze_configured, breeze_status_message

        if breeze_configured():
            st.caption(f"Data: **ICICI Breeze** · {breeze_status_message()}")
        else:
            st.caption("Data: **Yahoo Finance** (connect Breeze in sidebar for NSE-aligned OHLCV).")
    except ImportError:
        st.caption("Data: **Yahoo Finance**")

    render_watchlist_panel("btst_wl")
    key = "btst"
    session_results = f"{key}_results"
    session_stats = f"{key}_stats"

    uni_opts = universe_options("NSE")
    default_uni = next((u for u in ("Nifty 100 (medium)", "Nifty 500 (broad, slow)") if u in uni_opts), uni_opts[0])

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.1, 1.0, 1.0])
        with c1:
            universe = st.selectbox("Universe", uni_opts, index=uni_opts.index(default_uni), key=f"{key}_uni")
            max_tickers = st.slider("Max tickers to scan", 30, 200, 100, 10, key=f"{key}_max")
            grade_a_only = st.checkbox("Grade A only", value=False, key=f"{key}_ga")
        with c2:
            min_cpr_a = st.slider("Min CPR % (Grade A)", 65.0, 90.0, 75.0, 1.0, key=f"{key}_cpra")
            min_vol_a = st.slider("Min Vol× (Grade A)", 1.2, 3.0, 1.8, 0.1, key=f"{key}_vola")
            min_score_a = st.slider("Min score (Grade A)", 60.0, 85.0, 70.0, 1.0, key=f"{key}_sca")
        with c3:
            min_day_pct = st.slider("Min day % vs prev close", 0.5, 4.0, 1.5, 0.1, key=f"{key}_dpct")
            max_day_pct = st.slider("Max day % (avoid exhaustion)", 4.0, 12.0, 8.0, 0.5, key=f"{key}_xpct")
            data_src = st.selectbox(
                "OHLCV source",
                ("auto", "breeze", "yahoo"),
                format_func=lambda x: {"auto": "Auto (Breeze if connected)", "breeze": "Breeze only", "yahoo": "Yahoo only"}[x],
                key=f"{key}_ds",
            )

        run = st.button("🌙 Run BTST scan", type="primary", key=f"{key}_run")

    if run:
        flt = BtstFilters(
            min_pct_change=float(min_day_pct),
            max_pct_change=float(max_day_pct),
            min_cpr_grade_a=float(min_cpr_a),
            min_vol_ratio_a=float(min_vol_a),
            min_score_a=float(min_score_a),
            max_tickers=int(max_tickers),
            grade_a_only=grade_a_only,
            data_source=data_src,
        )
        prog = st.progress(0.0, text="Starting BTST scan…")
        status = st.empty()

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(i / max(total, 1), text=f"Scanning {sym} ({i}/{total})…")

        with st.spinner("Scanning close strength + volume…"):
            results, stats = scan_btst(universe, flt, progress_cb=_cb)

        prog.empty()
        status.empty()
        st.session_state[session_results] = results
        st.session_state[session_stats] = stats
        append_scan_record("btst", universe, [r.raw_ticker for r in results], meta={"grade_a": stats.grade_a})

    results = st.session_state.get(session_results) or []
    stats = st.session_state.get(session_stats)

    if not results and not run:
        st.info("Run a scan between **2:45–3:20 PM IST** for best results. Uses today's daily bar.")
        return

    if stats:
        st.success(
            f"**{len(results)}** actionable (Grade A/B) · scanned **{stats.tickers_scanned}** · "
            f"A={stats.grade_a} B={stats.grade_b} · hard-reject **{stats.failed_hard}** · "
            f"{stats.scan_elapsed_sec:.0f}s"
        )

    if not results:
        st.warning("No Grade A/B names passed all rules. Loosen CPR/volume sliders or widen universe.")
        return

    df = _results_df(results)
    show = [c for c in df.columns if c != "Raw"]
    styler = df[show].style.apply(
        lambda col: [_GRADE_STYLE.get(str(v), "") for v in col],
        subset=["Grade"],
    )

    render_clickable_scan_table(
        df[show],
        styler=styler,
        key_prefix=key,
        apply_stock_sight=False,
        column_config={
            **stock_sight_overlay_column_config(),
            "Grade": st.column_config.TextColumn("Grade", width="small"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "CPR %": st.column_config.NumberColumn(format="%.0f"),
            "Vol×": st.column_config.NumberColumn(format="%.1f"),
            "Day %": st.column_config.NumberColumn(format="%+.2f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "vs MA20 %": st.column_config.NumberColumn(format="%+.1f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "Stop": st.column_config.NumberColumn(format="₹%.2f"),
            "Morning exit": st.column_config.TextColumn(width="large"),
        },
        caption="Grade **A/B** only — sorted by grade then score. Click a row for chart.",
        show_gate_legend=False,
    )

    st.markdown("---")
    st.markdown("#### Morning exit card")
    labels = [f"{r.grade} · {r.ticker} (score {r.btst_score:.0f})" for r in results]
    pick = st.selectbox("Select pick", labels, key=f"{key}_pick")
    idx = labels.index(pick) if pick in labels else 0
    _render_pick_card(results[idx])
