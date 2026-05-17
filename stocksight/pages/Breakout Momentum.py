"""Page: Breakout Momentum — PE 5–50, Vol ≥3×, RSI 50–65 rising"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_breakout_momentum
from ui_components import (
    inject_css,
    scenario_header,
    trade_plan_card,
    results_table,
    no_results_state,
    safe_set_page_config,
    scenario_advanced_panel,
    maybe_enrich_news,
    render_watchlist_panel,
    signal_results_download,
    log_scenario_scan,
    notify_watchlist_alerts,
    scenario_page_alert_hint,
)

safe_set_page_config(page_title="Breakout Momentum | StockSight", page_icon="🚀", layout="wide")
inject_css()

SCENARIO = "breakout_momentum"

scenario_header(SCENARIO)
render_watchlist_panel("bm_wl")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="bm_universe")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>PE</b> 5 – 50 · <b>Volume</b> ≥ 3× avg · <b>RSI</b> 50 – 65 (rising)<br>
<b>Price</b> above 20-day MA · <b>Signal</b> BUY on break · <b>Timeframe</b> 1–8 weeks
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", 5.0, 50.0, 50.0, 0.5, key="bm_pe")
        vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 3.0, 0.1, key="bm_vol")
        rsi_range = st.slider("RSI Range (14)", 30, 80, (50, 65), 1, key="bm_rsi")

adv = scenario_advanced_panel("bm_adv")

scan_progress = st.empty()
run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_breakout_momentum")
st.caption("Pick universe and thresholds, then scan. Progress appears in the bar above while each symbol is processed.")

if run:
    prog = scan_progress.progress(0, text="Initialising…")

    def cb(i, t, s):
        prog.progress(int(i / t * 100), text=f"Scanning {s}… ({i}/{t})")

    scan_kw = {
        "sector_filter": adv["sector_filter"],
        "interval_key": adv["interval_key"],
        "require_macd_bullish": adv["require_macd_bullish"],
        "require_bb_touch_lower": adv["require_bb_touch_lower"],
        "require_weekly_confirm": adv["require_weekly_confirm"],
        "weekly_macd_confirm": adv["weekly_macd_confirm"],
        "exclude_earnings_within_days": int(adv["exclude_earnings_within_days"]),
        "skip_bearish_divergence_buy": adv["skip_bearish_divergence_buy"],
        "min_rs_vs_bench": adv["min_rs_vs_bench"],
        "require_stoch_cross_up": adv["require_stoch_cross_up"],
        "require_stoch_cross_down": adv["require_stoch_cross_down"],
    }
    results = scan_breakout_momentum(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=rsi_range[0],
        rsi_max=rsi_range[1],
        progress_cb=cb,
        **scan_kw,
    )
    maybe_enrich_news(results, adv.get("fetch_news", False))
    log_scenario_scan(SCENARIO, universe, results)
    notify_watchlist_alerts(results, scenario_page_alert_hint(SCENARIO))
    prog.empty()
    scan_progress.empty()
    st.session_state["bm_results"] = results

results = st.session_state.get("bm_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN NOW** to find breakout candidates.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Trade Plans")
    pf_sz = float(adv.get("portfolio_for_sizing", 0.0) or 0.0)
    signal_results_download(results, SCENARIO, button_key="bm_dl")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_breakout_momentum")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO, portfolio_value=pf_sz, risk_pct=float(adv.get("risk_pct_per_trade", 1.0) or 1.0))
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Higher volume threshold reduces false breakouts but misses early moves.")

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>Breakout Momentum — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Finds strong breakout candidates with high volume and rising RSI. Adjust the filters to tune breakout sensitivity.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        Current thresholds: max PE ≤ {pe_max}, volume ≥ {vol_min}× avg, RSI between {rsi_range[0]} and {rsi_range[1]}.
    </div>
</div>
""",
    unsafe_allow_html=True,
)
