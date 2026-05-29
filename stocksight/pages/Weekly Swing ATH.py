"""Weekly Swing ATH — 52-week-high breakouts on the weekly chart. Educational only; see in-page playbook."""
import streamlit as st
from screener import UNIVERSES
from signals import scan_weekly_ath_swing
from ui_components import (
    inject_css,
    scenario_header,
    render_trade_plan_cards,
    results_table,
    no_results_state,
    safe_set_page_config,
    maybe_enrich_news,
    render_watchlist_panel,
    signal_results_download,
    log_scenario_scan,
    notify_watchlist_alerts,
    scenario_page_alert_hint,
)

safe_set_page_config(page_title="Weekly Swing ATH | StockSight", page_icon="🏔️", layout="wide")
inject_css()

SCENARIO = "weekly_ath_swing"

scenario_header(SCENARIO)
render_watchlist_panel("wkath_wl")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="wkath_universe")
        st.caption("Swing tier uses the **Nifty 500 / S&P 500** universe (broader than intraday).")
    with c2:
        st.markdown("#### Criteria (weekly chart)")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>Price</b> at / within X% of 52-week high · <b>Volume</b> ≥ 1.5× 20-week avg<br>
<b>RSI</b> 55 – 78 · <b>Trend</b> EMA 20 &gt; 50 · <b>Signal</b> BUY on weekly close above high
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        near_pct = st.slider("Max % below 52W high", 0.0, 10.0, 3.0, 0.5, key="wkath_near")
        vol_min = st.slider("Min Volume (×20-week avg)", 0.5, 5.0, 1.5, 0.1, key="wkath_vol")
        rsi_range = st.slider("Weekly RSI (14) band", 40, 90, (55, 78), 1, key="wkath_rsi")

with st.expander("⚙ Advanced filters", expanded=False):
    a1, a2, a3 = st.columns(3)
    with a1:
        require_ema = st.checkbox("Require EMA 20 > 50 alignment", value=True, key="wkath_ema")
    with a2:
        require_tight = st.checkbox("Require tight 8-week base", value=False, key="wkath_tight")
    with a3:
        max_base = st.slider("Max base width % (8 weeks)", 10.0, 50.0, 25.0, 1.0, key="wkath_base")
    sector_filter = st.text_input("Sector contains (optional)", value="", key="wkath_sector")
    fetch_news = st.checkbox("Fetch recent news for matches", value=True, key="wkath_news")

scan_progress = st.empty()
run = st.button("▶  SCAN WEEKLY ATH", use_container_width=True, key="scan_now_weekly_ath")
st.caption("Pick universe and thresholds, then scan. The progress bar above updates per symbol.")

if run:
    prog = scan_progress.progress(0, text="Initialising…")

    def cb(i, t, s):
        prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {s}… ({i}/{t})")

    results = scan_weekly_ath_swing(
        universe,
        near_pct=near_pct,
        vol_min=vol_min,
        rsi_min=float(rsi_range[0]),
        rsi_max=float(rsi_range[1]),
        require_ema_alignment=require_ema,
        require_tight_base=require_tight,
        max_base_width_pct=max_base,
        sector_filter=sector_filter or None,
        progress_cb=cb,
    )
    maybe_enrich_news(results, fetch_news)
    log_scenario_scan(SCENARIO, universe, results)
    notify_watchlist_alerts(results, scenario_page_alert_hint(SCENARIO))
    prog.empty()
    scan_progress.empty()
    st.session_state["wkath_results"] = results
    if results:
        st.success(f"✅ {len(results)} weekly ATH breakout(s) found in {universe}.")
    else:
        st.warning(
            "No weekly ATH breakouts matched. Try raising **Max % below 52W high**, "
            "lowering **Min Volume**, widening the **RSI band**, or turning off EMA alignment."
        )

results = st.session_state.get("wkath_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN WEEKLY ATH** to find weekly breakout candidates.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Trade Plans")
    signal_results_download(results, SCENARIO, button_key="wkath_dl")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_weekly_ath")
    st.markdown("---")
    if view == "Cards":
        render_trade_plan_cards(results, SCENARIO)
    else:
        results_table(results, SCENARIO)
    st.markdown("---")
    st.caption("⚠️ Not financial advice. Always confirm with the daily chart, sector trend, and news before entering.")

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>🏔️ Weekly Swing ATH — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Finds stocks <b>breaking (or within {near_pct:.0f}% of) their 52-week high</b> on the <b>weekly chart</b>,
        confirmed by volume ≥ {vol_min:.1f}× the 20-week average, RSI between {rsi_range[0]} and {rsi_range[1]},
        and an EMA 20 &gt; 50 uptrend. This is the <b>swing tier</b> of the All-Time-High playbook.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        <b>How to act:</b> enter on a <b>weekly close above the breakout level</b> (or a low-volume retest of it),
        place a <b>5–8% stop below the base</b>, and target <b>10–20%</b> (≥1:2 R:R). See the
        <b>ATH Strategy Playbook</b> page for the full rulebook and Go / No-Go checklist.
    </div>
</div>
""",
    unsafe_allow_html=True,
)
