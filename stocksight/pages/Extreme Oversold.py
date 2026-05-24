"""Extreme Oversold — deep capitulation candidates. For contrarians; see in-page Who/What banner."""
import streamlit as st
from screener import UNIVERSES
from signals import scan_extreme_oversold
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

safe_set_page_config(page_title="Extreme Oversold | StockSight", page_icon="⚡", layout="wide")
inject_css()

SCENARIO = "extreme_oversold"

scenario_header(SCENARIO)
render_watchlist_panel("eos_wl")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="eos_universe")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>PE</b> Any · <b>Volume</b> ≥ 2× avg · <b>RSI</b> &lt; 25 (extreme)<br>
+ Green candle OR RSI ticking up · <b>Signal</b> CAUTIOUS BUY · <b>Timeframe</b> Speculative swing
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", 5.0, 300.0, 300.0, 0.5, key="eos_pe")
        vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 2.0, 0.1, key="eos_vol")
        rsi_max = st.slider("RSI Ceiling (14)", 5, 40, 25, 1, key="eos_rsi")

adv = scenario_advanced_panel("eos_adv")

scan_progress = st.empty()
run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_extreme_oversold")
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
    results = scan_extreme_oversold(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_max=rsi_max,
        progress_cb=cb,
        **scan_kw,
    )
    maybe_enrich_news(results, adv.get("fetch_news", False))
    log_scenario_scan(SCENARIO, universe, results)
    notify_watchlist_alerts(results, scenario_page_alert_hint(SCENARIO))
    prog.empty()
    scan_progress.empty()
    st.session_state["eos_results"] = results

results = st.session_state.get("eos_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN NOW** to find extreme oversold candidates.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Speculative Plans")
    pf_sz = float(adv.get("portfolio_for_sizing", 0.0) or 0.0)
    signal_results_download(results, SCENARIO, button_key="eos_dl")

    st.warning(
        "⚡ These stocks are in deep distress. **Require a positive news catalyst** before entering. "
        "Use small position sizes — this could be a value opportunity OR a falling knife."
    )

    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_extreme_oversold")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO, portfolio_value=pf_sz, risk_pct=float(adv.get("risk_pct_per_trade", 1.0) or 1.0))
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Always check news, management commentary, and fundamentals before entering.")

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#e8f7ef;'>
    <div style='font-size:1rem; font-weight:600;'>Extreme Oversold — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Finds deeply oversold stocks with extreme RSI and a potential early recovery signal.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        Current thresholds: max PE ≤ {pe_max}, volume ≥ {vol_min}× avg, RSI below {rsi_max}.
    </div>
</div>
""",
    unsafe_allow_html=True,
)
