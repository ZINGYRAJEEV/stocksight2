"""Page: Overbought / Exit — Any PE, Vol ≥2×, RSI >75"""
import streamlit as st
from screener import UNIVERSES
from signals import scan_overbought_exit
from ui_components import inject_css, scenario_header, trade_plan_card, results_table, no_results_state, safe_set_page_config

safe_set_page_config(page_title="Overbought Exit | StockSight", page_icon="🔴", layout="wide")
inject_css()

SCENARIO = "overbought_exit"

scenario_header(SCENARIO)

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="oe_universe")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>PE</b> Any · <b>Volume</b> ≥ 2× avg · <b>RSI</b> &gt; 75 (extreme)<br>
<b>Signal</b> SELL / Tighten stops · <b>Timeframe</b> Short term · Days
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", 5.0, 300.0, 300.0, 0.5, key="oe_pe")
        vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 2.0, 0.1, key="oe_vol")
        rsi_range = st.slider("RSI Range (14)", 30, 100, (75, 100), 1, key="oe_rsi")

scan_progress = st.empty()
run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_overbought_exit")
st.caption("Pick universe and thresholds, then scan. Progress appears in the bar above while each symbol is processed.")

if run:
    prog = scan_progress.progress(0, text="Initialising…")

    def cb(i, t, s):
        prog.progress(int(i / t * 100), text=f"Scanning {s}… ({i}/{t})")

    results = scan_overbought_exit(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=rsi_range[0],
        rsi_max=rsi_range[1],
        progress_cb=cb,
    )
    prog.empty()
    scan_progress.empty()
    st.session_state["oe_results"] = results

results = st.session_state.get("oe_results", None)

if results is None:
    st.info("👆 Configure the panel above and click **SCAN NOW** to find overbought/exhaustion signals.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — Exit Plans")

    st.warning(
        "🔴 These stocks are showing exhaustion signals. **Do not open new long positions.** "
        "If holding, tighten your stop to breakeven and consider taking partial profits."
    )

    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_overbought_exit")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO)
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. RSI extremes can persist in strong trends — confirm with price action.")

st.markdown("---")
st.markdown(
    f"""
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
""",
    unsafe_allow_html=True,
)
