"""
StockSight — Real-time Fundamental + Momentum Screener
This page provides the main StockSight screener with a top-of-page Scan Now button.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from screener import screen_stocks, UNIVERSES

st.set_page_config(
    page_title="StockSight | Smart Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

  html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background-color: #0d1f18;
    color: #e8f7ef;
  }
  .main-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2.4rem;
    font-weight: 600;
    letter-spacing: -0.5px;
    color: #25d366;
    margin-bottom: 0;
  }
  .sub-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85rem;
    color: #b8e7c7;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 2px;
  }
  .metric-card {
    background: #122f25;
    border: 1px solid #1a3b31;
    border-radius: 8px;
    padding: 16px 20px;
    text-align: center;
  }
  .metric-value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2rem;
    font-weight: 600;
    color: #25d366;
  }
  .metric-label {
    font-size: 0.75rem;
    color: #b8e7c7;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 4px;
  }
  .stButton > button {
    background: linear-gradient(135deg, #25d366, #1aa34b);
    color: #000;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 0.82rem;
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    letter-spacing: 1px;
    text-transform: uppercase;
    cursor: pointer;
    width: 100%;
    transition: opacity 0.2s;
  }
  .stButton > button:hover { opacity: 0.92; }
  [data-testid="stSidebar"] {
    background-color: #ffffff;
    border-right: 1px solid #d4d4d4;
    color: #111827;
  }
  [data-testid="stSidebar"] label {
    color: #111827 !important;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .stProgress > div > div { background-color: #25d366; }
  hr { border-color: #16412f !important; margin: 8px 0; }
  .timestamp {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: #b8e7c7;
    margin-top: 6px;
  }
  .status-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #25d366;
    margin-right: 6px;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.3; }
  }
</style>
""", unsafe_allow_html=True)

if "app1_results_df" not in st.session_state:
    st.session_state.app1_results_df = pd.DataFrame()
if "app1_last_run" not in st.session_state:
    st.session_state.app1_last_run = None
if "app1_is_running" not in st.session_state:
    st.session_state.app1_is_running = False

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown('<div class="main-title">📈 StockSight</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Real-time Fundamental + Momentum Screener</div>', unsafe_allow_html=True)
with col_h2:
    if st.session_state.app1_last_run:
        ts = st.session_state.app1_last_run.strftime("%H:%M:%S  %d %b %Y")
        st.markdown(f'<div class="timestamp"><span class="status-dot"></span>Last run: {ts}</div>', unsafe_allow_html=True)

st.markdown("---")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), key="app1_universe")
        auto_refresh = st.checkbox("Auto-refresh (60s)", value=False, key="app1_autorefresh")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#2e5070; line-height:1.6;'>
<b style='color:#a3d8b8;">Data source</b><br>
Yahoo Finance via yfinance<br><br>
<b style='color:#a3d8b8;">Scoring</b><br>
PE (40pts) + Vol (30pts) + RSI (30pts)<br><br>
<b style='color:#a3d8b8;">Indicators</b><br>
RSI-14 · 20-day avg volume · Trailing PE
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", min_value=5.0, max_value=50.0, value=30.0, step=0.5, key="app1_pe")
        vol_mult = st.slider("Min Volume Spike (×avg)", min_value=1.0, max_value=10.0, value=1.5, step=0.1, key="app1_vol")
        rsi_min = st.slider("Min RSI (14)", min_value=30.0, max_value=80.0, value=50.0, step=1.0, key="app1_rsi")

scan_progress_ph = st.empty()
scan_status_ph = st.empty()
run_app1 = st.button("▶  SCAN NOW", use_container_width=True, key="app1_scan_now")
st.caption(
    "Runs the full universe with your thresholds. Larger universes take longer; progress and status show in the slots above."
)


def run_stock_scan(progress_ph, status_ph):
    st.session_state.app1_is_running = True
    progress_bar = progress_ph.progress(0, text="Initialising…")
    status_text = status_ph

    def on_progress(current, total, ticker):
        pct = int(current / total * 100)
        progress_bar.progress(pct, text=f"Scanning {ticker}… ({current}/{total})")
        status_text.markdown(f'<div class="timestamp">⚡ {ticker}</div>', unsafe_allow_html=True)

    df = screen_stocks(
        universe_name=universe,
        pe_threshold=pe_max,
        vol_multiplier=vol_mult,
        rsi_min=rsi_min,
        progress_callback=on_progress,
    )

    progress_ph.empty()
    status_ph.empty()
    st.session_state.app1_results_df = df
    st.session_state.app1_last_run = datetime.now()
    st.session_state.app1_is_running = False


if run_app1:
    run_stock_scan(scan_progress_ph, scan_status_ph)

if auto_refresh and st.session_state.app1_last_run:
    elapsed = (datetime.now() - st.session_state.app1_last_run).total_seconds()
    if elapsed >= 60:
        st.rerun()
    else:
        remaining = int(60 - elapsed)
        st.caption(f"⏱ Auto-refresh in {remaining}s")

st.markdown("---")

df = st.session_state.app1_results_df
if df.empty and st.session_state.app1_last_run is None:
    st.info("👆 Adjust filters if needed, then click **SCAN NOW** to populate the results table here.")
elif df.empty and st.session_state.app1_last_run is not None:
    st.warning("⚠️ No stocks passed the current filter combination. Try relaxing the thresholds.")
else:
    total_scanned = len(UNIVERSES[universe])
    passed = len(df)
    avg_score = df["Score"].mean()
    top_ticker = df.iloc[0]["Ticker"] if passed > 0 else "—"

    m1, m2, m3, m4 = st.columns(4)
    metrics = [
        (m1, str(total_scanned), "Stocks Scanned"),
        (m2, str(passed), "Passed Filters"),
        (m3, f"{avg_score:.1f}", "Avg Score"),
        (m4, top_ticker, "Top Pick"),
    ]
    for col, val, lbl in metrics:
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{val}</div>
                <div class="metric-label">{lbl}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Results")
    st.dataframe(df, use_container_width=True, hide_index=False, height=min(620, 60 + len(df) * 40))
    csv = df.to_csv(index=False)
    st.download_button(label="⬇ Download Results as CSV", data=csv, file_name=f"stocksight_app1_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")

st.markdown("---")
st.markdown(
    """
<div style='background:#122f25; border:1px solid #1a3b31; border-radius:8px; padding:18px 20px; margin-bottom:8px;'>
    <div style='font-size:1rem; font-weight:600; color:#e8f7ef;'>About this screener</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.9rem; line-height:1.55;'>
        StockSight ranks stocks that pass PE, relative volume, and RSI gates. Use <b>SCAN NOW</b> after tuning filters.
        Links open in a new tab.
    </div>
    <div style='margin-top:14px; font-size:0.72rem; color:#7abeac; line-height:1.9;'>
    <a href='https://finance.yahoo.com/' target='_blank' style='color:#00e5a0; text-decoration:none;'>📊 Yahoo Finance</a>
    &nbsp;·&nbsp;
    <a href='https://www.moneycontrol.com/' target='_blank' style='color:#00e5a0; text-decoration:none;'>📈 Moneycontrol</a>
    &nbsp;·&nbsp;
    <a href='https://www.tradingview.com/' target='_blank' style='color:#00e5a0; text-decoration:none;'>📉 TradingView</a>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("""
<div style='margin-top: 40px; padding-top: 16px; border-top: 1px solid #1a3b31;
            font-size: 0.72rem; color: #2e4060; text-align: center;'>
    StockSight · Data via Yahoo Finance (yfinance) · For educational purposes only. Not financial advice.
</div>
""", unsafe_allow_html=True)
