"""Page: Volume Spike — No RSI Confirmation. Hold / Wait."""
import streamlit as st
from screener import UNIVERSES
from signals import scan_volume_no_confirm
from ui_components import inject_css, scenario_header, trade_plan_card, results_table, no_results_state

st.set_page_config(page_title="Vol Spike — Wait | StockSight", page_icon="⏸️", layout="wide")
inject_css()

SCENARIO = "volume_no_confirm"

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()))
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.72rem; color:#a3d8b8; line-height:1.9;'>
    <b>Criteria</b><br>
    Volume: ≥ 2× avg<br>
    RSI: 25–50 or 65–75 (ambiguous)<br><br>
    <b>Signal</b><br>
    HOLD / WAIT for confirmation<br><br>
    <b>Action</b><br>
    Pre-calculate levels now.<br>
    Act only on next 1–3 bar confirm.
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### Filters")
    pe_max = st.slider("Max PE Ratio", 5.0, 300.0, 300.0, 0.5)
    vol_min = st.slider("Min Volume Spike (×avg)", 1.0, 10.0, 2.0, 0.1)
    rsi_range = st.slider("RSI Range (14)", 20, 80, (25, 75), 1)

scenario_header(SCENARIO)

st.markdown(f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#e8f7ef;'>
    <div style='font-size:1rem; font-weight:600;'>Volume No Confirm — what this page does</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Finds volume spikes without clear RSI confirmation. Use this screen to watch ambiguous setups and wait for follow-through.
    </div>
    <div style='margin-top:12px; font-size:0.88rem; color:#a0b8c8;'>
        Current thresholds: max PE ≤ {pe_max}, volume ≥ {vol_min}× avg, RSI between {rsi_range[0]} and {rsi_range[1]}.
    </div>
</div>
""", unsafe_allow_html=True)

run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_volume_no_confirm")

if run:
    prog = st.progress(0, text="Initialising…")
    def cb(i, t, s): prog.progress(int(i/t*100), text=f"Scanning {s}… ({i}/{t})")
    results = scan_volume_no_confirm(
        universe,
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=rsi_range[0],
        rsi_max=rsi_range[1],
        progress_cb=cb,
    )
    prog.empty()
    st.session_state["vnc_results"]  = results
    st.session_state["vnc_universe"] = universe

results = st.session_state.get("vnc_results", None)

if results is None:
    st.info("👆 Select your universe and click **SCAN NOW** to find ambiguous volume spikes to watchlist.")
elif not results:
    no_results_state(SCENARIO)
else:
    st.markdown(f"### 📋 {len(results)} stock(s) on Watchlist — Awaiting Confirmation")

    st.info("⏸️ **Do not act yet.** These stocks have unusual volume but no clear RSI direction. "
            "Add them to your watchlist and wait for 1–3 bars of price/RSI confirmation "
            "before treating them as a Buy or Sell signal.")

    view = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="view_volume_no_confirm")
    st.markdown("---")

    if view == "Cards":
        for r in results:
            trade_plan_card(r, SCENARIO)
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Not financial advice. Volume alone without direction is noise — patience is the edge here.")
