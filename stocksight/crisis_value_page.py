"""Crisis Value Screener — Streamlit UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from crisis_value import (
    META,
    CrisisValueFilters,
    scan_crisis_value,
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


def _score_style(series: pd.Series) -> list[str]:
    styles: list[str] = []
    for v in series:
        try:
            x = float(v)
        except (TypeError, ValueError):
            styles.append("")
            continue
        if x >= 75:
            styles.append("background-color:#dcfce7;color:#166534;font-weight:700;")
        elif x >= 60:
            styles.append("background-color:#ecfdf5;color:#047857;")
        elif x >= 45:
            styles.append("background-color:#fef9c3;color:#854d0e;")
        else:
            styles.append("")
    return styles


def _results_df(results: list) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        rows.append(
            {
                "S.No.": i,
                "Ticker": r.ticker,
                "Crisis score": r.crisis_score,
                "Stability": r.stability_score,
                "E/P divergence %": r.eps_price_divergence_pct,
                "Drawdown 52w %": r.drawdown_52w_pct,
                "Drawdown 3y %": r.drawdown_3y_pct,
                "Earnings CAGR %": r.earnings_cagr_pct,
                "Price 3y %": r.price_return_3y_pct,
                "Max EPS drop %": r.max_yoy_drop_pct,
                "Positive yrs %": r.positive_year_pct,
                "Earnings yrs": r.earnings_years,
                "P/E": r.pe,
                "ROE %": r.roe_pct,
                "D/E": r.debt_equity,
                "Verdict": r.verdict,
                "Action": r.action,
                "Sector": r.sector,
                "Mar Cap": r.market_cap_display,
                "Thesis": r.thesis,
                "Raw": r.raw_ticker,
                **{k: v for k, v in r.links.items()},
            }
        )
    return pd.DataFrame(rows)


def _render_framework() -> None:
    with st.expander("📘 What is a 2008-style setup?", expanded=True):
        st.markdown(
            """
In **2008**, many profitable companies saw share prices collapse **40–70%** while **annual earnings**
barely dipped — the market priced in depression; fundamentals recovered first.

This screener looks for a similar **fear vs. fundamentals** gap today:

| Signal | Meaning |
|--------|---------|
| **Earnings stability** | Positive EPS/net income across years; limited YoY drops |
| **Price dislocation** | Stock well below 52-week / 3-year highs |
| **E/P divergence** | Earnings CAGR **minus** 3-year price return — large positive = market lagging earnings |
| **Quality filter** | ROE, debt, and P/E caps avoid broken balance sheets |

**Not a buy list** — verify on [Screener.in](https://www.screener.in) that earnings are **real** (not one-offs),
and that the price fall is **sentiment/cycle**, not permanent impairment.
"""
        )

    with st.expander("📐 How scores are built", expanded=False):
        st.markdown(
            """
**Stability score (0–100)** — positive earnings years, low volatility (CV), shallow max YoY drop, earnings CAGR.

**Crisis score** — stability (45%) + earnings/price divergence + drawdown depth + cheap P/E bonus.

**E/P divergence %** = 3-year **earnings CAGR** − 3-year **share price return**.
Example: earnings +8%/yr, price −20% over 3y → divergence ≈ **+28%** (classic undervaluation gap).
"""
        )

    with st.expander("⚠️ Limits (Yahoo data)", expanded=False):
        st.markdown(
            """
- Uses Yahoo **annual income statement** (typically 4–5 years) — not 15-year Screener history.
- **Cyclicals** can show smooth earnings at a peak — read the annual report.
- **Banks & insurers** may need manual adjustment for provisioning cycles.
- India names: cross-check ROE, debt, and EPS on **Screener.in** before acting.
"""
        )


def render_crisis_value_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.html(f"""
    <div style='background:#1c1917; border:1px solid #44403c; border-left:4px solid #f59e0b;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#fafaf9;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#d6d3d1; margin-top:6px;'>
            Steady earnings · fallen price · E/P divergence · 2008-style undervaluation hunt
        </div>
    </div>
    """)

    page_audience_note(META["audience"], META["purpose"])
    _render_framework()
    render_watchlist_panel("crisis_wl")

    key = "crisis"
    session_results = f"{key}_results"
    session_at = f"{key}_at"

    uni_opts = universe_options()
    default_uni = next((u for u in ("Nifty 50 (NSE)", "Nifty 500 (NSE)") if u in uni_opts), uni_opts[0])
    uni_idx = uni_opts.index(default_uni) if default_uni in uni_opts else 0

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.1, 1.0, 1.0])
        with c1:
            universe = st.selectbox("Universe", uni_opts, index=uni_idx, key=f"{key}_uni")
            min_years = st.slider("Min years of earnings data", 2, 5, 3, key=f"{key}_minyr")
            min_pos = st.slider("Min % positive earnings years", 60, 100, 100, key=f"{key}_minpos")
        with c2:
            min_dd52 = st.slider("Min 52w drawdown %", 10, 50, 20, key=f"{key}_dd52")
            min_div = st.slider("Min E/P divergence %", 0, 50, 15, key=f"{key}_div")
            max_pe = st.slider("Max P/E", 8.0, 40.0, 28.0, key=f"{key}_maxpe")
        with c3:
            min_roe = st.slider("Min ROE %", 0.0, 30.0, 12.0, key=f"{key}_minroe")
            max_de = st.slider("Max debt/equity", 0.0, 3.0, 1.2, 0.05, key=f"{key}_maxde")
            min_score = st.slider("Min crisis score", 30, 90, 55, key=f"{key}_minsc")
            max_n = st.slider("Max tickers to scan", 20, 150, 60, key=f"{key}_maxn")

        require_below_3y = st.checkbox(
            "Require 3y price return ≤ +5% (price still depressed)",
            value=True,
            key=f"{key}_below3y",
        )

    flt = CrisisValueFilters(
        universe=universe,
        min_earnings_years=int(min_years),
        min_positive_year_pct=float(min_pos),
        min_drawdown_52w_pct=float(min_dd52),
        min_eps_price_divergence_pct=float(min_div),
        max_pe=float(max_pe),
        min_roe_pct=float(min_roe),
        max_debt_equity=float(max_de),
        min_crisis_score=float(min_score),
        require_price_below_3y=bool(require_below_3y),
        max_tickers=int(max_n),
    )

    if st.button(f"🏦 RUN {META['nav_title'].upper()} SCAN", type="primary", key=f"{key}_run"):
        prog = st.progress(0, text="Starting crisis value scan…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(min(99, int(100 * i / max(total, 1))), text=f"Crisis: {sym} ({i}/{total})")

        results, stats = scan_crisis_value(flt, progress_cb=_cb)
        prog.progress(100, text="Done")
        st.session_state[session_results] = results
        st.session_state[f"{key}_stats"] = stats
        st.session_state[session_at] = datetime.now().strftime("%d %b %Y %H:%M:%S")
        append_scan_record(
            "crisis_value",
            universe,
            [r.raw_ticker for r in results],
        )

    results = st.session_state.get(session_results, [])
    stats = st.session_state.get(f"{key}_stats")
    scan_at = st.session_state.get(session_at)

    if stats:
        st.caption(
            f"Scanned **{stats.tickers_scanned}** · matched **{stats.tickers_matched}** · "
            f"skipped **{stats.no_data}** · {stats.scan_elapsed_sec:.1f}s"
            + (f" · {scan_at}" if scan_at else "")
        )

    if not results:
        st.info(
            "Run a scan to find stocks where **earnings stayed steady** but **price fell** — "
            "the classic crisis-value pattern. Try **Nifty 500** or loosen drawdown / divergence filters."
        )
        return

    df = _results_df(results)
    show_cols = [c for c in df.columns if c not in ("Raw", "Thesis")]
    styler = df[show_cols].style.apply(_score_style, subset=["Crisis score"])

    render_clickable_scan_table(
        df[show_cols],
        styler=styler,
        key_prefix=key,
        apply_stock_sight=False,
        column_config={
            **stock_sight_overlay_column_config(),
            "Crisis score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Stability": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "E/P divergence %": st.column_config.NumberColumn(format="%+.1f"),
            "Drawdown 52w %": st.column_config.NumberColumn(format="%.1f"),
            "Drawdown 3y %": st.column_config.NumberColumn(format="%.1f"),
            "Earnings CAGR %": st.column_config.NumberColumn(format="%+.1f"),
            "Price 3y %": st.column_config.NumberColumn(format="%+.1f"),
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "ROE %": st.column_config.NumberColumn(format="%.1f"),
            "D/E": st.column_config.NumberColumn(format="%.2f"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
        },
        caption="Sorted by **Crisis score** then **E/P divergence**. Green = strong 2008-style gap.",
        show_gate_legend=False,
    )

    with st.expander("📋 Thesis notes (matched stocks)", expanded=False):
        for r in results[:15]:
            st.markdown(f"**{r.ticker}** — {r.verdict} · *{r.action}*")
            st.caption(r.thesis)

    st.caption(
        "⚠️ Educational screener — Yahoo annual financials only. "
        "Confirm earnings quality and moat on Screener.in before investing."
    )
