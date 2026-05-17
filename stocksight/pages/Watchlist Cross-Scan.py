"""Page: Watchlist Cross-Scan — run all six scenario scanners on saved watchlist symbols only."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from signals import cross_scan_watchlist, scenario_display_title, scenario_nav_key
from watchlist_store import load_watchlist
from ui_components import (
    inject_css,
    trade_plan_card,
    results_table,
    safe_set_page_config,
    scenario_advanced_panel,
    maybe_enrich_news,
    render_watchlist_panel,
    signal_results_download,
    log_scenario_scan,
    notify_watchlist_alerts,
)

PAGE_SCENARIO_ID = "watchlist_cross_scan"

safe_set_page_config(
    page_title="Watchlist Cross-Scan | StockSight",
    page_icon="📌",
    layout="wide",
)
inject_css()

st.markdown("### 📌 Watchlist cross-scan")
st.caption(
    "Runs the **six technical scenario modules** on symbols in your saved watchlist only, "
    "using each scenario's **default** PE / volume / RSI thresholds. "
    "Tune thresholds on individual scenario pages; use Advanced below for bar interval, sector, MACD/Bollinger, "
    "weekly confirmation, earnings window, and RSI divergence filters."
)

render_watchlist_panel("xc_wl")

wl_rows = load_watchlist()
syms = [str(r.get("raw_ticker") or "").strip() for r in wl_rows if str(r.get("raw_ticker") or "").strip()]

adv = scenario_advanced_panel("xc_adv")

scan_progress = st.empty()
run = st.button("▶  SCAN WATCHLIST", use_container_width=True, key="scan_now_watchlist_cross")
st.caption(
    f"**{len(syms)}** symbol(s) in watchlist. Progress updates while each ticker is evaluated "
    "(six passes — one per scenario module)."
)

if run:
    if not syms:
        st.warning("Watchlist is empty — use **★ Watchlist** on any trade card or add a ticker manually above.")
    else:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            denom = max(int(t), 1)
            prog.progress(min(int(i / denom * 100), 100), text=f"Scanning {s}… ({i}/{t})")

        merged = cross_scan_watchlist(
            syms,
            interval_key=adv["interval_key"],
            sector_filter=adv["sector_filter"],
            require_macd_bullish=adv["require_macd_bullish"],
            require_bb_touch_lower=adv["require_bb_touch_lower"],
            require_weekly_confirm=adv["require_weekly_confirm"],
            exclude_earnings_within_days=int(adv["exclude_earnings_within_days"]),
            skip_bearish_divergence_buy=adv["skip_bearish_divergence_buy"],
            min_rs_vs_bench=adv["min_rs_vs_bench"],
            require_stoch_cross_up=adv["require_stoch_cross_up"],
            require_stoch_cross_down=adv["require_stoch_cross_down"],
            weekly_macd_confirm=adv["weekly_macd_confirm"],
            progress_cb=cb,
        )
        maybe_enrich_news(merged, adv.get("fetch_news", False))
        log_scenario_scan(PAGE_SCENARIO_ID, "watchlist", merged)
        notify_watchlist_alerts(merged, "Watchlist Cross-Scan")
        prog.empty()
        scan_progress.empty()
        st.session_state["xc_results"] = merged

results = st.session_state.get("xc_results", None)

if results is None:
    st.info("👆 Save symbols to your watchlist, then click **SCAN WATCHLIST**.")
elif not results:
    st.info(
        "No matches — none of the six scenarios fired on your watchlist with current filters "
        "and default scenario thresholds."
    )
else:
    st.markdown(f"### 📋 {len(results)} match(es) across scenarios")

    summ = (
        pd.DataFrame(
            [
                {
                    "Ticker": r.ticker,
                    "Scenario": scenario_display_title(r.scenario_id),
                    "Signal": r.signal_label,
                }
                for r in results
            ]
        )
        .groupby("Ticker", as_index=False)
        .agg(Matching_scenarios=("Scenario", lambda s: ", ".join(sorted(set(s)))))
        .sort_values("Ticker")
    )
    st.markdown("**Per-symbol scenario hits**")
    st.dataframe(summ, use_container_width=True, hide_index=True, height=min(420, 48 + len(summ) * 38))

    pf_sz = float(adv.get("portfolio_for_sizing", 0.0) or 0.0)
    signal_results_download(
        results,
        PAGE_SCENARIO_ID,
        button_key="xc_dl",
        include_scenario=True,
    )

    view = st.radio(
        "View",
        ["Cards", "Table"],
        horizontal=True,
        label_visibility="collapsed",
        key="view_watchlist_cross",
    )
    st.markdown("---")

    if view == "Cards":
        by_ticker: dict[str, list] = {}
        for r in results:
            by_ticker.setdefault(r.ticker, []).append(r)
        for tkr in sorted(by_ticker.keys()):
            st.markdown(f"#### {tkr}")
            for r in sorted(by_ticker[tkr], key=lambda x: scenario_display_title(x.scenario_id)):
                trade_plan_card(
                    r,
                    scenario_nav_key(r.scenario_id),
                    portfolio_value=pf_sz,
                    risk_pct=float(adv.get("risk_pct_per_trade", 1.0) or 1.0),
                )
    else:
        results_table(results, PAGE_SCENARIO_ID, include_scenario=True)

    st.markdown("---")
    st.caption(
        "⚠️ Educational only — not financial advice. Same symbol may appear under multiple scenarios; "
        "resolve conflicts using fundamentals and your risk rules."
    )
