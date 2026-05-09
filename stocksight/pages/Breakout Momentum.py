"""Page: Breakout Momentum — PE 5–50, Vol ≥3×, RSI 50–65 rising"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_breakout_momentum
from ui_components import inject_css, scenario_header, trade_plan_card, results_table, no_results_state

st.set_page_config(page_title="Breakout Momentum | StockSight", page_icon="🚀", layout="wide")
inject_css()

SCENARIO = "breakout_momentum"

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()))
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.72rem; color:#a3d8b8; line-height:1.9;'>
    <b>Criteria</b><br>
    PE: 5 – 50<br>
    Volume: ≥ 3× avg<br>
    RSI: 50 – 65 (rising)<br>
    Price: above 20-day MA<br><br>
    <b>Signal</b><br>
    BUY on break above resistance<br><br>
    <b>Timeframe</b><br>
    Momentum · 1–8 weeks
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### Filters")
    pe_max = st.slider("Max PE Ratio", 5.0, 50.0, 50.0, 0.5)
    vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 3.0, 0.1)
    rsi_range = st.slider("RSI Range (14)", 30, 80, (50, 65), 1)

scenario_header(SCENARIO)

st.markdown(f"""
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
""", unsafe_allow_html=True)

run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_breakout_momentum")

if run:
    prog = st.progress(0, text="Initialising…")
    def cb(i, t, s): prog.progress(int(i/t*100), text=f"Scanning {s}… ({i}/{t})")
    results = scan_breakout_momentum(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=rsi_range[0],
        rsi_max=rsi_range[1],
        progress_cb=cb,
    )
    prog.empty()
    st.session_state["bm_results"]  = results
    st.session_state["bm_universe"] = universe

results = st.session_state.get("bm_results", None)

if results is None:
    st.info("👆 Select your universe and click **SCAN NOW** to find breakout candidates.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Trade Plans")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_breakout_momentum")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO)
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Higher volume threshold reduces false breakouts but misses early moves.")
