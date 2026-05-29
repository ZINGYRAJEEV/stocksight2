"""Long-Term ATH — true all-time-high breakouts on the monthly chart with quality fundamentals. Educational only."""
import streamlit as st
from screener import UNIVERSES
from signals import scan_monthly_ath_longterm
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

safe_set_page_config(page_title="Long-Term ATH | StockSight", page_icon="🚀", layout="wide")
inject_css()

SCENARIO = "monthly_ath_longterm"

scenario_header(SCENARIO)
render_watchlist_panel("ltath_wl")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="ltath_universe")
        st.caption("Long-term tier scans the broad **Nifty 500 / S&P 500** universe.")
    with c2:
        st.markdown("#### Criteria (monthly chart)")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>Price</b> at / within X% of all-time high · <b>Trend</b> above 200-DMA<br>
<b>RSI</b> 55 – 85 · <b>Quality</b> ROE ≥ 15% · D/E ≤ 0.5 · <b>Signal</b> BUY on monthly close above ATH
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        near_pct = st.slider("Max % below all-time high", 0.0, 15.0, 5.0, 0.5, key="ltath_near")
        rsi_range = st.slider("Monthly RSI (14) band", 40, 95, (55, 85), 1, key="ltath_rsi")
        vol_min = st.slider("Min Volume (×12-month avg)", 0.0, 3.0, 1.0, 0.1, key="ltath_vol")

with st.expander("⚙ Fundamental & trend filters", expanded=False):
    a1, a2, a3 = st.columns(3)
    with a1:
        apply_fund = st.checkbox("Apply quality fundamentals", value=True, key="ltath_fund")
    with a2:
        min_roe = st.slider("Min ROE %", 0.0, 40.0, 15.0, 1.0, key="ltath_roe")
    with a3:
        max_de = st.slider("Max Debt/Equity", 0.0, 2.0, 0.5, 0.1, key="ltath_de")
    b1, b2 = st.columns(2)
    with b1:
        require_200 = st.checkbox("Require price above 200-DMA", value=True, key="ltath_200")
    with b2:
        fetch_news = st.checkbox("Fetch recent news for matches", value=True, key="ltath_news")
    sector_filter = st.text_input("Sector contains (optional)", value="", key="ltath_sector")

scan_progress = st.empty()
run = st.button("▶  SCAN LONG-TERM ATH", use_container_width=True, key="scan_now_longterm_ath")
st.caption("Long-term scans fetch monthly history + fundamentals — allow a little extra time per symbol.")

if run:
    prog = scan_progress.progress(0, text="Initialising…")

    def cb(i, t, s):
        prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {s}… ({i}/{t})")

    results = scan_monthly_ath_longterm(
        universe,
        near_pct=near_pct,
        rsi_min=float(rsi_range[0]),
        rsi_max=float(rsi_range[1]),
        vol_min=vol_min,
        min_roe_pct=min_roe,
        max_debt_equity=max_de,
        apply_fundamentals=apply_fund,
        require_above_200dma=require_200,
        sector_filter=sector_filter or None,
        progress_cb=cb,
    )
    maybe_enrich_news(results, fetch_news)
    log_scenario_scan(SCENARIO, universe, results)
    notify_watchlist_alerts(results, scenario_page_alert_hint(SCENARIO))
    prog.empty()
    scan_progress.empty()
    st.session_state["ltath_results"] = results
    if results:
        st.success(f"✅ {len(results)} long-term ATH leader(s) found in {universe}.")
    else:
        st.warning(
            "No long-term ATH leaders matched. Try raising **Max % below ATH**, lowering **Min ROE**, "
            "raising **Max Debt/Equity**, or turning off the fundamentals / 200-DMA gates."
        )

results = st.session_state.get("ltath_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN LONG-TERM ATH** to find all-time-high leaders.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Trade Plans")
    signal_results_download(results, SCENARIO, button_key="ltath_dl")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_longterm_ath")
    st.markdown("---")
    if view == "Cards":
        render_trade_plan_cards(results, SCENARIO)
    else:
        results_table(results, SCENARIO)
    st.markdown("---")
    st.caption("⚠️ Not financial advice. Verify fundamentals (ROE, debt, promoter holding) and macro context before investing.")

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>🚀 Long-Term ATH — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Finds <b>true all-time-high breakouts on the monthly chart</b> (within {near_pct:.0f}% of the ATH),
        trading <b>above the 200-DMA</b>, with strong monthly RSI{(" and quality fundamentals (ROE ≥ " + f"{min_roe:.0f}%, D/E ≤ {max_de:.1f})") if apply_fund else ""}.
        This is the <b>long-term tier</b> of the All-Time-High playbook — for price-discovery wealth compounders.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        <b>How to act:</b> enter on a <b>monthly close above the all-time high</b>, scale in over 2–3 tranches,
        trail a <b>wide 10–15% stop</b>, and hold for <b>30–100%+</b> while the trend and fundamentals stay intact.
        See the <b>ATH Strategy Playbook</b> page for the full rulebook and false-signal checklist.
    </div>
</div>
""",
    unsafe_allow_html=True,
)
