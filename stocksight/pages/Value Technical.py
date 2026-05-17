"""Page: Value + Technical — PE 5–15, Vol 1.5–2×, RSI 40–55, near MA"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_value_technical
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

safe_set_page_config(page_title="Value + Technical | StockSight", page_icon="💎", layout="wide")
inject_css()

SCENARIO = "value_technical"

scenario_header(SCENARIO)
render_watchlist_panel("vt_wl")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="vt_universe")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>PE</b> 5 – 15 · <b>Volume</b> 1.5× – 2× avg · <b>RSI</b> 40 – 55<br>
<b>Price</b> within 4% of 20-day MA · <b>Signal</b> BUY on pullback · <b>Timeframe</b> 1–6 months
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", 5.0, 50.0, 15.0, 0.5, key="vt_pe")
        vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 1.5, 0.1, key="vt_vol")
        rsi_range = st.slider("RSI Range (14)", 30, 80, (40, 55), 1, key="vt_rsi")

adv = scenario_advanced_panel("vt_adv")

scan_progress = st.empty()
run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_value_technical")
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
    results = scan_value_technical(
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
    st.session_state["vt_results"] = results

results = st.session_state.get("vt_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN NOW** to find value + technical setups.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Trade Plans")
    pf_sz = float(adv.get("portfolio_for_sizing", 0.0) or 0.0)
    signal_results_download(results, SCENARIO, button_key="vt_dl")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_value_technical")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO, portfolio_value=pf_sz, risk_pct=float(adv.get("risk_pct_per_trade", 1.0) or 1.0))
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Best suited for patient investors with 1–6 month horizon.")

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>Value + Technical — what this page does</div>
    <div style='margin-top:10px; color:#7fa8c4; font-size:0.92rem;'>
        Finds undervalued stocks with technical support and a conservative RSI range. Tune the sliders for more or fewer candidates.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        Current thresholds: max PE ≤ {pe_max}, volume ≥ {vol_min}× avg, RSI between {rsi_range[0]} and {rsi_range[1]}.
    </div>
</div>
""",
    unsafe_allow_html=True,
)
