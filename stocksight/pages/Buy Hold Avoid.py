"""Page: Buy / Hold / Avoid Decision Chart — Composite Score Guidance"""
import streamlit as st
import pandas as pd
from urllib.parse import quote_plus
from screener import UNIVERSES, screen_stocks
from ui_components import inject_css

st.set_page_config(page_title="Buy / Hold / Avoid | StockSight", page_icon="📊", layout="wide")
inject_css()

st.markdown("""
<style>
.chart-card {
    background:#122f25;
    border:1px solid #1a3b31;
    border-radius:12px;
    padding:20px;
    margin-bottom:20px;
}
.chart-title {
    font-size:1.15rem;
    font-weight:700;
    margin-bottom:10px;
    color:#e8f7ef;
}
.chart-subtitle {
    color:#a3d8b8;
    margin-bottom:16px;
    line-height:1.6;
}
.metric-block {
    background:#16352c;
    border:1px solid #1a3b31;
    border-radius:8px;
    padding:16px;
}
.metric-label {
    color:#a3d8b8;
    font-size:0.78rem;
    letter-spacing:1px;
    text-transform:uppercase;
    margin-bottom:8px;
}
.metric-value {
    font-family:'IBM Plex Mono', monospace;
    font-size:1.1rem;
    color:#e8f7ef;
    margin-bottom:8px;
}
.range-pill {
    display:inline-block;
    padding:6px 10px;
    border-radius:999px;
    font-size:0.78rem;
    margin-right:6px;
    margin-top:6px;
    color:#fff;
}
.bad {
    background:#e05252;
}
.ok {
    background:#f0b429;
}
.good {
    background:#25d366;
}
.table-block {
    width:100%;
    border-collapse:collapse;
    margin-top:12px;
}
.table-block th,
.table-block td {
    border:1px solid #1a3b31;
    padding:12px 14px;
    color:#e8f7ef;
}
.table-block th {
    background:#16352c;
    color:#a3d8b8;
    text-transform:uppercase;
    font-size:0.78rem;
}
.heatbar {
    display:flex;
    height:36px;
    border-radius:10px;
    overflow:hidden;
    margin-top:12px;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.05);
}
.heat-segment {
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:0.82rem;
    font-weight:700;
    letter-spacing:0.2px;
    color:#111827;
}
.news-links {
    display:flex;
    flex-wrap:wrap;
    gap:10px;
    margin-top:12px;
}
.news-link {
    background:#16352c;
    border:1px solid #1a3b31;
    border-radius:8px;
    padding:10px 12px;
    color:#a3d8b8;
    text-decoration:none;
    font-size:0.85rem;
}
.news-link:hover {
    border-color:#25d366;
    color:#e8f7ef;
}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Stock list filter")
    universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), index=0)
    action_zone = st.selectbox(
        "Composite Action Zone",
        ["All", "Strong Buy", "Buy / Watch", "Neutral / Wait", "Avoid"],
        index=0,
    )
    ticker_filter = st.text_input("Ticker contains", value="")
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.82rem; color:#a3d8b8; line-height:1.6;'>
    Run the universe scan to build a stock list showing PE, volume ratio, RSI, composite score, and instant research links.
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    fetch_btn = st.button("▶  FETCH STOCK LIST", use_container_width=True)

st.markdown("""
<div class='chart-card'>
    <div class='chart-title'>📌 Composite Score Overview</div>
    <div class='chart-subtitle'>Composite Score = <strong>30% PE</strong> + <strong>40% Volume Spike</strong> + <strong>30% RSI</strong>. This page combines score guidance with an indicator-led stock list.</div>
</div>
""", unsafe_allow_html=True)

# Indicator Zones
st.markdown("""
<div class='chart-card'>
    <div class='chart-title'>1. Indicator Zones</div>
    <div class='chart-subtitle'>Each indicator is scored from 0–100 and then weighted into the composite score.</div>
    <div style='display:flex; gap:18px; flex-wrap:wrap;'>
        <div class='metric-block' style='flex:1; min-width:220px;'>
            <div class='metric-label'>PE Ratio (Valuation — 30%)</div>
            <div class='metric-value'>Cheap = Good | Fair = Neutral | Expensive = Bad</div>
            <div class='range-pill good'>0–40</div>
            <div class='range-pill ok'>40–70</div>
            <div class='range-pill bad'>70–100</div>
        </div>
        <div class='metric-block' style='flex:1; min-width:220px;'>
            <div class='metric-label'>Volume Spike (Momentum — 40%)</div>
            <div class='metric-value'>Weak = Bad | Moderate = OK | Strong = Great</div>
            <div class='range-pill bad'>0–40</div>
            <div class='range-pill ok'>40–70</div>
            <div class='range-pill good'>70–100</div>
        </div>
        <div class='metric-block' style='flex:1; min-width:220px;'>
            <div class='metric-label'>RSI (Momentum Turning — 30%)</div>
            <div class='metric-value'>Oversold = Good | Neutral = OK | Overbought = Bad</div>
            <div class='range-pill good'>0–30</div>
            <div class='range-pill ok'>30–60</div>
            <div class='range-pill bad'>60–100</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Composite Score Heatmap
st.markdown("""
<div class='chart-card'>
    <div class='chart-title'>2. Composite Score Heatmap</div>
    <div class='chart-subtitle'>Use the heatmap to see the zone your combined score falls into.</div>
    <table class='table-block'>
        <thead>
            <tr><th>Composite Score Range</th><th>Meaning</th></tr>
        </thead>
        <tbody>
            <tr><td>80–100</td><td>Strong Buy (ideal setup)</td></tr>
            <tr><td>60–79</td><td>Buy / Watch for entry</td></tr>
            <tr><td>40–59</td><td>Neutral / Wait</td></tr>
            <tr><td>0–39</td><td>Avoid (bad setup)</td></tr>
        </tbody>
    </table>
    <div class='heatbar'>
        <div class='heat-segment' style='flex:20; background:#e05252; color:#fff;'>BAD</div>
        <div class='heat-segment' style='flex:20; background:#ffb347; color:#111827;'>WEAK</div>
        <div class='heat-segment' style='flex:20; background:#f0b429; color:#111827;'>OK</div>
        <div class='heat-segment' style='flex:20; background:#25d366;'>GOOD</div>
        <div class='heat-segment' style='flex:20; background:#1aa34b; color:#fff;'>STRONG BUY</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Decision Chart
st.markdown("""
<div class='chart-card'>
    <div class='chart-title'>3. Buy / Hold / Avoid Decision Chart</div>
    <div class='chart-subtitle'>This matrix shows the most reliable action for each indicator combination.</div>
    <table class='table-block'>
        <thead>
            <tr>
                <th>PE Score</th>
                <th>Volume Spike Score</th>
                <th>RSI Score</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
            <tr><td>Low / Medium</td><td>Strong (70–100)</td><td>30–60</td><td>BUY</td></tr>
            <tr><td>Low / Medium</td><td>Medium (40–70)</td><td>30–50</td><td>WATCH / POSSIBLE BUY</td></tr>
            <tr><td>High</td><td>Strong</td><td>30–50</td><td>CAUTION / MAYBE</td></tr>
            <tr><td>Any</td><td>Weak (0–40)</td><td>Any</td><td>AVOID</td></tr>
            <tr><td>Any</td><td>Any</td><td>> 70</td><td>AVOID (Overbought)</td></tr>
        </tbody>
    </table>
</div>
""", unsafe_allow_html=True)

# Perfect Buy Setup
st.markdown("""
<div class='chart-card'>
    <div class='chart-title'>⭐ The Perfect Buy Setup</div>
    <div class='chart-subtitle'>All three indicators are aligned for a strong, high-confidence buy.</div>
    <div style='display:grid; grid-template-columns:repeat(3, minmax(200px, 1fr)); gap:14px;'>
        <div class='metric-block'>
            <div class='metric-label'>PE</div>
            <div class='metric-value'>40–70</div>
            <div style='color:#a3d8b8; font-size:0.82rem;'>Fair or undervalued</div>
        </div>
        <div class='metric-block'>
            <div class='metric-label'>Volume</div>
            <div class='metric-value'>70–100</div>
            <div style='color:#a3d8b8; font-size:0.82rem;'>Big spike → institutions buying</div>
        </div>
        <div class='metric-block'>
            <div class='metric-label'>RSI</div>
            <div class='metric-value'>30–50</div>
            <div style='color:#a3d8b8; font-size:0.82rem;'>Momentum turning up</div>
        </div>
    </div>
    <div style='margin-top:14px; color:#e8f7ef; font-size:0.95rem;'>
        → Composite Score usually 75–90 → <strong>STRONG BUY ZONE</strong>
    </div>
</div>
""", unsafe_allow_html=True)

# Example Composite Score
st.markdown("""
<div class='chart-card'>
    <div class='chart-title'>📊 Example Composite Score Chart</div>
    <div class='chart-subtitle'>A weighted example showing how each indicator contributes to the final score.</div>
    <table class='table-block'>
        <thead>
            <tr><th>Indicator</th><th>Score</th><th>Weight</th><th>Weighted Value</th></tr>
        </thead>
        <tbody>
            <tr><td>PE</td><td>60</td><td>0.30</td><td>18</td></tr>
            <tr><td>Volume</td><td>85</td><td>0.40</td><td>34</td></tr>
            <tr><td>RSI</td><td>50</td><td>0.30</td><td>15</td></tr>
            <tr><td><strong>Total</strong></td><td colspan='2'></td><td><strong>67</strong></td></tr>
        </tbody>
    </table>
    <div style='margin-top:18px; color:#e8f7ef; font-size:0.95rem;'>
        <div style='font-family:"IBM Plex Mono", monospace; color:#25d366; font-size:0.98rem; margin-bottom:10px;'>Composite Score: 67 → BUY ZONE</div>
        <div style='background:#16352c; border:1px solid #1a3b31; border-radius:10px; padding:14px;'>
            <div style='height:14px; background:#1a3b31; border-radius:8px; overflow:hidden;'>
                <div style='width:67%; height:100%; background:linear-gradient(90deg,#25d366,#1aa34b);'></div>
            </div>
            <div style='display:flex; justify-content:space-between; margin-top:8px; font-size:0.82rem; color:#a3d8b8;'>
                <span>0</span><span>20</span><span>40</span><span>60</span><span>80</span><span>100</span>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Stock list filter + news links
if "bha_results" not in st.session_state:
    st.session_state.bha_results = pd.DataFrame()

if fetch_btn:
    progress_bar = st.progress(0, text="Scanning universe…")
    status = st.empty()

    def progress_cb(count, total, ticker):
        pct = int(count / total * 100)
        progress_bar.progress(pct, text=f"Scanning {ticker}… ({count}/{total})")
        status.markdown(f"<div style='color:#a3d8b8;'>Loaded {count}/{total} tickers</div>", unsafe_allow_html=True)

    with st.spinner("Fetching stock metrics from Yahoo Finance…"):
        df = screen_stocks(
            universe_name=universe,
            pe_threshold=400.0,
            vol_multiplier=0.0,
            rsi_min=0.0,
            progress_callback=progress_cb,
        )

    progress_bar.empty()
    status.empty()
    st.session_state.bha_results = df
else:
    df = st.session_state.bha_results

if df is None or df.empty:
    st.markdown("""
    <div class='chart-card'>
        <div class='chart-title'>📌 Stock List Not Loaded</div>
        <div class='chart-subtitle'>Click <strong>FETCH STOCK LIST</strong> in the sidebar to load current PE, volume, RSI, composite score, and research links for your chosen universe.</div>
    </div>
    """, unsafe_allow_html=True)
else:
    df = df.copy()
    df["Action"] = df["Score"].apply(
        lambda score: "Strong Buy" if score >= 80 else
                      "Buy / Watch" if score >= 60 else
                      "Neutral / Wait" if score >= 40 else
                      "Avoid"
    )
    df["BusinessLine"] = df["Ticker"].apply(
        lambda ticker: f"https://www.thehindubusinessline.com/search/?q={quote_plus(ticker.replace('.NS', '').replace('.BO', ''))}"
    )

    if ticker_filter:
        df = df[df["Ticker"].str.contains(ticker_filter.upper(), na=False)]

    if action_zone != "All":
        df = df[df["Action"] == action_zone]

    if df.empty:
        st.markdown("""
        <div class='chart-card'>
            <div class='chart-title'>⚠️ No matching stocks</div>
            <div class='chart-subtitle'>No stocks matched the current filter combination. Try a broader action zone or remove the ticker filter.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class='chart-card'>
            <div class='chart-title'>📋 Stock List with Composite Score & Indicators</div>
            <div class='chart-subtitle'>This table shows right-now PE, volume spike, RSI, composite score, and direct research links.</div>
        </div>
        """, unsafe_allow_html=True)

        display_cols = [
            "Ticker", "Price", "PE Ratio", "Volume Ratio", "RSI", "Score", "Action",
            "Yahoo Finance", "Moneycontrol", "BusinessLine"
        ]
        visible_cols = [col for col in display_cols if col in df.columns]

        col_cfg = {
            "Price": st.column_config.NumberColumn("Price", format="%.2f"),
            "PE Ratio": st.column_config.NumberColumn("PE Ratio", format="%.2f"),
            "Volume Ratio": st.column_config.NumberColumn("Volume Ratio", format="%.2f"),
            "RSI": st.column_config.NumberColumn("RSI", format="%.2f"),
            "Score": st.column_config.NumberColumn("Score", format="%.1f"),
            "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Open ↗"),
            "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="Open ↗"),
            "BusinessLine": st.column_config.LinkColumn("BusinessLine", display_text="Open ↗"),
        }

        st.dataframe(
            df[visible_cols],
            use_container_width=True,
            column_config=col_cfg,
            hide_index=False,
            height=min(600, 60 + len(df) * 38),
        )

        selected_ticker = st.selectbox(
            "Preview news links for",
            options=df["Ticker"].tolist(),
            index=0,
            help="Pick a ticker to open Yahoo Finance news, Moneycontrol search, or BusinessLine headlines.",
        )

        if selected_ticker:
            clean_ticker = selected_ticker.replace(".NS", "").replace(".BO", "")
            news_links = {
                "Yahoo Finance News": f"https://finance.yahoo.com/quote/{clean_ticker}/news",
                "Moneycontrol Search": f"https://www.moneycontrol.com/india/stockpricequote/search?q={quote_plus(clean_ticker)}",
                "BusinessLine Search": f"https://www.thehindubusinessline.com/search/?q={quote_plus(clean_ticker)}",
            }
            st.markdown("""
            <div class='chart-card'>
                <div class='chart-title'>📰 Quick News Links</div>
                <div class='chart-subtitle'>Open the latest newsroom for the selected ticker.</div>
                <div class='news-links'>
            """, unsafe_allow_html=True)

            for label, url in news_links.items():
                st.markdown(f"<a class='news-link' href='{url}' target='_blank'>{label} ↗</a>", unsafe_allow_html=True)

            st.markdown("""
                </div>
            </div>
            """, unsafe_allow_html=True)
