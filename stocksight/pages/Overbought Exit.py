"""Page: Overbought / Exit — Any PE, Vol ≥2×, RSI >75"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_overbought_exit
from ui_components import inject_css, scenario_header, trade_plan_card, results_table, no_results_state

st.set_page_config(page_title="Overbought Exit | StockSight", page_icon="🔴", layout="wide")
inject_css()

SCENARIO = "overbought_exit"

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()))
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.72rem; color:#a3d8b8; line-height:1.9;'>
    <b>Criteria</b><br>
    PE: Any<br>
    Volume: ≥ 2× avg<br>
    RSI: > 75 (extreme)<br><br>
    <b>Signal</b><br>
    SELL / Tighten stops<br><br>
    <b>Timeframe</b><br>
    Short term · Days
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### Filters")
    pe_max = st.slider("Max PE Ratio", 5.0, 300.0, 300.0, 0.5)
    vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 2.0, 0.1)
    rsi_range = st.slider("RSI Range (14)", 30, 100, (75, 100), 1)

scenario_header(SCENARIO)

st.markdown(f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>Overbought Exit — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Spots overbought or exhausted names where tightening stops or taking profits may be optimal.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        Current thresholds: max PE ≤ {pe_max}, volume ≥ {vol_min}× avg, RSI between {rsi_range[0]} and {rsi_range[1]}.
    </div>
</div>
""", unsafe_allow_html=True)

run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_overbought_exit")

if run:
    prog = st.progress(0, text="Initialising…")
    def cb(i, t, s): prog.progress(int(i/t*100), text=f"Scanning {s}… ({i}/{t})")
    results = scan_overbought_exit(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=rsi_range[0],
        rsi_max=rsi_range[1],
        progress_cb=cb,
    )
    prog.empty()
    st.session_state["oe_results"]  = results
    st.session_state["oe_universe"] = universe

results = st.session_state.get("oe_results", None)

if results is None:
    st.info("👆 Select your universe and click **SCAN NOW** to find overbought/exhaustion signals.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Exit Plans")

    st.warning("🔴 These stocks are showing exhaustion signals. **Do not open new long positions.** "
               "If holding, tighten your stop to breakeven and consider taking partial profits.")

    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_overbought_exit")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO)
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. RSI extremes can persist in strong trends — confirm with price action.")
