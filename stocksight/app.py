"""
Overview — StockSight Home / Strategy Dashboard
Run with: streamlit run Overview.py
"""

import streamlit as st
from screener import UNIVERSES

st.set_page_config(
    page_title="Overview | StockSight",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
:root {
    color-scheme: light;
    --app-bg: #f8fafc;
    --app-text: #111827;
    --button-bg: linear-gradient(135deg,#25d366,#1aa34b);
}
@media (prefers-color-scheme: dark) {
    :root {
        color-scheme: dark;
        --app-bg: #0d1f18;
        --app-text: #e8f7ef;
    }
}
html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background-color: var(--app-bg);
    color: var(--app-text);
}
.stButton > button {
    background: var(--button-bg);
    color: #000; font-family:'IBM Plex Mono',monospace;
    font-weight:700; font-size:0.82rem; border:none;
    border-radius:6px; padding:10px 24px; letter-spacing:1px;
    text-transform:uppercase; cursor:pointer; width:100%;
}
[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #d4d4d4; color:#111827; }
[data-testid="stSidebar"] label { color:#111827 !important; font-size:0.8rem; }
hr { border-color:#d4d4d4 !important; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style='margin-bottom:24px;'>
    <div style='font-family:"IBM Plex Mono",monospace; font-size:2.4rem;
                font-weight:700; color:#00e5a0; letter-spacing:-0.5px;'>
        📈 StockSight
    </div>
    <div style='font-family:"IBM Plex Mono",monospace; font-size:0.82rem;
                color:#4a7a9b; letter-spacing:2.5px; text-transform:uppercase; margin-top:3px;'>
        Real-time Signal Screener — Know Exactly When to Buy & Sell
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Strategy Map ──────────────────────────────────────────────────────────────
st.markdown("### 🗺️ Signal Strategy Map")
st.caption("Six scenarios covering the full market cycle. Click a page in the sidebar to run any screen.")

STRATEGY_CARDS = [
    {
        "emoji": "📉", "title": "Oversold Bounce",
        "signal": "BUY", "sig_color": "#00e5a0", "sig_bg": "#0a2e1e",
        "pe": "5 – 50", "vol": "≥ 2×", "rsi": "30 – 40 ↑",
        "timeframe": "Swing · 3–21 days",
        "edge": "Enter panic-sold stocks showing first reversal signs.",
        "color": "#00e5a0",
    },
    {
        "emoji": "🚀", "title": "Breakout Momentum",
        "signal": "BUY", "sig_color": "#00e5a0", "sig_bg": "#0a2e1e",
        "pe": "5 – 50", "vol": "≥ 3×", "rsi": "50 – 65 ↑",
        "timeframe": "Momentum · 1–8 weeks",
        "edge": "High-volume breakouts above resistance with RSI confirmation.",
        "color": "#4db8ff",
    },
    {
        "emoji": "💎", "title": "Value + Technical",
        "signal": "BUY", "sig_color": "#00e5a0", "sig_bg": "#0a2e1e",
        "pe": "5 – 15", "vol": "1.5 – 2×", "rsi": "40 – 55",
        "timeframe": "Long · 1–6 months",
        "edge": "Undervalued names pulling back to MA — slow but high conviction.",
        "color": "#f0b429",
    },
    {
        "emoji": "🔴", "title": "Overbought / Exit",
        "signal": "SELL", "sig_color": "#ff4d4d", "sig_bg": "#2e0a0a",
        "pe": "Any", "vol": "≥ 2×", "rsi": "> 75",
        "timeframe": "Short term · Days",
        "edge": "RSI extreme + volume spike = exhaustion. Tighten stops, take profits.",
        "color": "#ff4d4d",
    },
    {
        "emoji": "⚡", "title": "Extreme Oversold",
        "signal": "CAUTIOUS BUY", "sig_color": "#ff9d42", "sig_bg": "#2e1a00",
        "pe": "Any", "vol": "≥ 2×", "rsi": "< 25",
        "timeframe": "Speculative Swing",
        "edge": "Deep distress with green candle — require catalyst before entry.",
        "color": "#ff9d42",
    },
    {
        "emoji": "⏸️", "title": "Volume — No Confirm",
        "signal": "WAIT", "sig_color": "#a0a0a0", "sig_bg": "#1a1a1a",
        "pe": "Any", "vol": "≥ 2×", "rsi": "Ambiguous",
        "timeframe": "Intraday to Swing",
        "edge": "Volume without RSI direction = noise. Watchlist only.",
        "color": "#a0a0a0",
    },
]

col_pairs = [STRATEGY_CARDS[i:i+3] for i in range(0, 6, 3)]
for trio in col_pairs:
    cols = st.columns(3)
    for col, card in zip(cols, trio):
        with col:
            st.markdown(f"""
            <div style='background:#0f1724; border:1px solid #1c2e44;
                        border-top:3px solid {card["color"]};
                        border-radius:8px; padding:18px 16px; height:100%;
                        margin-bottom:14px;'>
                <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                    <span style='font-size:1.6rem;'>{card["emoji"]}</span>
                    <span style='font-size:9px; background:{card["sig_bg"]}; color:{card["sig_color"]};
                                 border:1px solid {card["sig_color"]}55; border-radius:12px;
                                 padding:2px 9px; font-weight:700; letter-spacing:1px;
                                 font-family:"IBM Plex Mono",monospace;'>
                        {card["signal"]}
                    </span>
                </div>
                <div style='font-family:"IBM Plex Mono",monospace; font-weight:700;
                            color:#fff; font-size:0.95rem; margin:10px 0 6px;'>
                    {card["title"]}
                </div>
                <div style='font-size:0.72rem; color:#5a8090; margin-bottom:12px;'>
                    {card["edge"]}
                </div>
                <div style='display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;'>
                    <span style='font-size:9px; background:#0a1525; border:1px solid #1c2e44;
                                 color:#7fa8c4; border-radius:4px; padding:2px 7px;'>
                        PE {card["pe"]}
                    </span>
                    <span style='font-size:9px; background:#0a1525; border:1px solid #1c2e44;
                                 color:#7fa8c4; border-radius:4px; padding:2px 7px;'>
                        Vol {card["vol"]}
                    </span>
                    <span style='font-size:9px; background:#0a1525; border:1px solid #1c2e44;
                                 color:#7fa8c4; border-radius:4px; padding:2px 7px;'>
                        RSI {card["rsi"]}
                    </span>
                </div>
                <div style='font-size:9px; color:#4a7a9b; font-family:"IBM Plex Mono",monospace;
                            border-top:1px solid #1c2e44; padding-top:8px; margin-top:4px;'>
                    ⏱ {card["timeframe"]}
                </div>
            </div>
            """, unsafe_allow_html=True)

st.markdown("---")

# ── How it works ──────────────────────────────────────────────────────────────
st.markdown("### 📖 How Trade Plans Are Generated")

c1, c2, c3, c4 = st.columns(4)
steps = [
    ("1", "Screen", "#00e5a0",
     "Each page scans your chosen universe (Nifty 50/500 or S&P 500) using scenario-specific PE, Volume, and RSI filters."),
    ("2", "Detect", "#4db8ff",
     "For each passing stock, candle patterns, RSI direction, and price-vs-MA are checked to confirm signal quality."),
    ("3", "Calculate", "#f0b429",
     "Entry, Stop Loss (below swing low), and three Targets (1×/2×/3× risk) are computed automatically from live price data."),
    ("4", "Act", "#ff9d42",
     "Each card shows Confidence (High/Med/Low), Timeframe, and direct links to Yahoo Finance, Moneycontrol, and TradingView."),
]
for col, (num, title, color, desc) in zip([c1, c2, c3, c4], steps):
    with col:
        st.markdown(f"""
        <div style='background:#0f1724; border:1px solid #1c2e44; border-radius:8px;
                    padding:16px; text-align:center;'>
            <div style='font-family:"IBM Plex Mono",monospace; font-size:1.8rem;
                        color:{color}; font-weight:700;'>{num}</div>
            <div style='font-weight:600; color:#c8d8e8; margin:6px 0 8px;'>{title}</div>
            <div style='font-size:0.75rem; color:#5a8090; line-height:1.6;'>{desc}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# ── Quick-start ───────────────────────────────────────────────────────────────
st.markdown("### 🚀 Quick Start")
st.markdown("""
Use the **sidebar** to navigate to any of the 6 signal pages. There is also a new **Buy / Hold / Avoid Decision Guide** page in the Streamlit page menu with indicator zones, composite score heatmap, and action rules.
- Lets you choose your stock universe (Nifty 50, Nifty 500, or S&P 500)
- Has a one-click **SCAN NOW** button
- Shows results as **Cards** (full trade plan per stock) or **Table** (compact overview)
- Every matched stock has live links to Yahoo Finance, Moneycontrol/MarketWatch, and TradingView
""")

st.markdown("""
<div style='background:#0f1724; border:1px solid #1c3550; border-radius:8px;
            padding:14px 18px; margin-top:12px; font-size:0.78rem; color:#5a8090;'>
    ⚠️ <b style='color:#7fa8c4;'>Disclaimer:</b> StockSight is for educational and informational purposes only.
    Nothing here constitutes financial advice. Always do your own research, check news, and consult
    a registered financial advisor before making investment decisions.
</div>
""", unsafe_allow_html=True)
