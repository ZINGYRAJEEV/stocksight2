"""Page: Extreme Oversold — Any PE, Vol ≥2×, RSI <25"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_extreme_oversold
from ui_components import inject_css, scenario_header, trade_plan_card, results_table, no_results_state

st.set_page_config(page_title="Extreme Oversold | StockSight", page_icon="⚡", layout="wide")
inject_css()

SCENARIO = "extreme_oversold"

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()))
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.72rem; color:#a3d8b8; line-height:1.9;'>
    <b>Criteria</b><br>
    PE: Any<br>
    Volume: ≥ 2× avg<br>
    RSI: < 25 (extreme)<br>
    + Green candle OR RSI ticking up<br><br>
    <b>Signal</b><br>
    CAUTIOUS BUY with catalyst<br><br>
    <b>Timeframe</b><br>
    Speculative Swing
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### Filters")
    pe_max = st.slider("Max PE Ratio", 5.0, 300.0, 300.0, 0.5)
    vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 2.0, 0.1)
    rsi_max = st.slider("RSI Ceiling (14)", 5, 40, 25, 1)

scenario_header(SCENARIO)

st.markdown(f"""
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
""", unsafe_allow_html=True)

run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_extreme_oversold")

if run:
    prog = st.progress(0, text="Initialising…")
    def cb(i, t, s): prog.progress(int(i/t*100), text=f"Scanning {s}… ({i}/{t})")
    results = scan_extreme_oversold(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_max=rsi_max,
        progress_cb=cb,
    )
    prog.empty()
    st.session_state["eos_results"]  = results
    st.session_state["eos_universe"] = universe

results = st.session_state.get("eos_results", None)

if results is None:
    st.info("👆 Select your universe and click **SCAN NOW** to find extreme oversold candidates.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Speculative Plans")

    st.warning("⚡ These stocks are in deep distress. **Require a positive news catalyst** before entering. "
               "Use small position sizes — this could be a value opportunity OR a falling knife.")

    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_extreme_oversold")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO)
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Always check news, management commentary, and fundamentals before entering.")
