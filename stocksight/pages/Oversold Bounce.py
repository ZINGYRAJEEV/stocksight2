"""Page: Oversold Bounce — PE 5–50, Vol ≥2×, RSI 30–40 rising"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_oversold_bounce
from ui_components import inject_css, scenario_header, trade_plan_card, results_table, no_results_state, safe_set_page_config

safe_set_page_config(page_title="Oversold Bounce | StockSight", page_icon="📉", layout="wide")
inject_css()

SCENARIO = "oversold_bounce"

scenario_header(SCENARIO)

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="ob_universe")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>PE</b> 5 – 50 · <b>Volume</b> ≥ 2× avg · <b>RSI</b> 30 – 40 (rising)<br>
<b>Signal</b> BUY on green reversal · <b>Timeframe</b> Swing · 3–21 days
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", 5.0, 50.0, 50.0, 0.5, key="ob_pe")
        vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 2.0, 0.1, key="ob_vol")
        rsi_range = st.slider("RSI Range (14)", 30, 80, (30, 40), 1, key="ob_rsi")

scan_progress = st.empty()
run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_oversold_bounce")
st.caption("Pick universe and thresholds, then scan. Progress appears in the bar above while each symbol is processed.")

if run:
    prog = scan_progress.progress(0, text="Initialising…")

    def cb(i, t, s):
        prog.progress(int(i / t * 100), text=f"Scanning {s}… ({i}/{t})")

    results = scan_oversold_bounce(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=rsi_range[0],
        rsi_max=rsi_range[1],
        progress_cb=cb,
    )
    prog.empty()
    scan_progress.empty()
    st.session_state["ob_results"] = results

results = st.session_state.get("ob_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN NOW** to find oversold bounce candidates.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Trade Plans")
    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_oversold_bounce")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO)
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Always verify with news and fundamentals before entering.")

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>Oversold Bounce — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Finds oversold names with low PE, strong volume, and a rising RSI. Adjust the sliders to broaden or tighten the screen.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        Current thresholds: max PE ≤ {pe_max}, volume ≥ {vol_min}× avg, RSI between {rsi_range[0]} and {rsi_range[1]}.
    </div>
</div>
""",
    unsafe_allow_html=True,
)
