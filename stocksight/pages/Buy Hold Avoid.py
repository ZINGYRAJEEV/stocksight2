"""Buy / Hold / Avoid — composite score zones and action rules. Use after other screens; for decision-making, not discovery."""
import html
from datetime import datetime
from urllib.parse import quote_plus

import streamlit as st
import pandas as pd
from scan_history_store import append_scan_record
from screener import UNIVERSES, screen_stocks
from ui_components import (
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_screen_df,
    page_audience_note,
    render_clickable_scan_table,
    render_decision_matrix_legend,
    render_watchlist_panel,
    safe_set_page_config,
)

safe_set_page_config(page_title="Buy / Hold / Avoid | StockSight", page_icon="📊", layout="wide")
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
section.main div[data-baseweb="select"] > div,
section.main div[data-baseweb="select"] > div > div {
    background-color: #ffffff !important;
    color: #111827 !important;
    border-color: #cbd5e1 !important;
}
section.main div[data-baseweb="select"] input,
section.main div[data-baseweb="select"] span,
section.main div[data-baseweb="select"] [role="combobox"] {
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
}
section.main [data-testid="stSelectbox"] label,
section.main [data-testid="stTextInput"] label {
    color: #111827 !important;
}
section.main [data-testid="stTextInput"] input {
    background-color: #ffffff !important;
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("## 📊 Buy / Hold / Avoid Decision Guide", unsafe_allow_html=True)
page_audience_note(
    "Investors who already have a shortlist and need a single composite view before acting—use **after** StockSight or scenario scans.",
    "Loads a full universe with **6-group composite**, **Quality Gate A–D**, and **Buy / Watch · Neutral · Skip** decisions. "
    "and supports filters, cards, and news links. This is the final decision layer, not a discovery screener.",
)
st.markdown("---")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.15])
    with c1:
        st.markdown("#### Settings")
        universe = st.selectbox("Stock Universe", list(UNIVERSES.keys()), index=0, key="bha_universe")
    with c2:
        st.markdown("#### Criteria")
        st.markdown(
            """
<div style='font-size:0.82rem; color:#4a5568; line-height:1.6;'>
Run the universe fetch to build a list with PE, volume ratio, RSI, composite score, and research links.
Use the filters column to narrow the table after the list loads.
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        action_zone = st.selectbox(
            "Final decision",
            ["All", "Buy / Watch", "Neutral", "Skip"],
            index=0,
            key="bha_action",
        )
        ticker_filter = st.text_input("Ticker contains", value="", key="bha_ticker")

render_watchlist_panel("bha_wl")

bha_fetch_progress = st.empty()
bha_fetch_status = st.empty()
fetch_btn = st.button("▶  FETCH STOCK LIST", use_container_width=True, key="bha_fetch")
st.caption(
    "Loads the full universe from Yahoo Finance (can take a while). Progress and status show in the slots above the button; then narrow rows with filters."
)

st.markdown("---")

# Stock list filter + news links
if "bha_results" not in st.session_state:
    st.session_state.bha_results = pd.DataFrame()

if fetch_btn:
    progress_bar = bha_fetch_progress.progress(0, text="Scanning universe…")
    status = bha_fetch_status

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

    try:
        syms_out: list[str] = []
        if not df.empty and "Ticker" in df.columns:
            for t in df["Ticker"].astype(str).tolist():
                syms_out.append(f"{t}.NS" if "NSE" in universe else t)
        append_scan_record("BuyHoldAvoid", universe, syms_out, meta={"rows": int(len(df.index))})
    except Exception:
        pass
    try:
        notify_watchlist_alerts_screen_df(df, universe, "Buy / Hold / Avoid")
    except Exception:
        pass

    bha_fetch_progress.empty()
    bha_fetch_status.empty()
    st.session_state.bha_results = df
else:
    df = st.session_state.bha_results

if df is None or df.empty:
    st.html("""
    <div class='chart-card'>
        <div class='chart-title'>📌 Stock List Not Loaded</div>
        <div class='chart-subtitle'>Click <strong>FETCH STOCK LIST</strong> above to load current PE, volume, RSI, composite score, and research links for your chosen universe.</div>
    </div>
    """)
else:
    df = df.copy()
    if "Action" not in df.columns and "Decision" in df.columns:
        df["Action"] = df["Decision"]
    df["BusinessLine"] = df["Ticker"].apply(
        lambda ticker: f"https://www.thehindubusinessline.com/search/?q={quote_plus(ticker.replace('.NS', '').replace('.BO', ''))}"
    )

    def _google_finance_url(ticker: str) -> str:
        t = str(ticker)
        clean = t.replace(".NS", "").replace(".BO", "")
        if t.endswith(".NS"):
            return f"https://www.google.com/finance/quote/{clean}:NSE"
        if t.endswith(".BO"):
            return f"https://www.google.com/finance/quote/{clean}:BOM"
        return f"https://www.google.com/finance/quote/{clean}:NASDAQ"

    df["Google Finance"] = df["Ticker"].apply(_google_finance_url)

    if ticker_filter:
        df = df[df["Ticker"].str.contains(ticker_filter.upper(), na=False)]

    if action_zone != "All":
        df = df[df["Decision"] == action_zone]

    if df.empty:
        st.html("""
        <div class='chart-card'>
            <div class='chart-title'>⚠️ No matching stocks</div>
            <div class='chart-subtitle'>No stocks matched the current filter combination. Try a broader action zone or remove the ticker filter.</div>
        </div>
        """)
    else:
        st.html("""
        <div class='chart-card'>
            <div class='chart-title'>📋 Stock List with Composite Score & Indicators</div>
            <div class='chart-subtitle'>This view shows PE, volume spike, RSI, composite score, and direct research links.</div>
        </div>
        """)

        view = st.radio(
            "View",
            ["Table", "Cards"],
            horizontal=True,
            label_visibility="collapsed",
            key="bha_view",
        )

        def _confidence_label(score: float):
            if score >= 80:
                return "HIGH CONFIDENCE", "#25d366"
            if score >= 60:
                return "MEDIUM CONFIDENCE", "#f0b429"
            if score >= 40:
                return "LOW CONFIDENCE", "#f2cf6b"
            return "AVOID", "#e05252"

        def _action_note(action: str):
            return {
                "Strong Buy": "Strong composite signal. Momentum and valuation are aligned.",
                "Buy / Watch": "Watch for confirmation before entering. Setup is constructive.",
                "Neutral / Wait": "Wait for a cleaner setup or pullback before committing.",
                "Avoid": "Avoid until indicators improve and the trend shows strength.",
            }.get(action, "Review the indicator scores before taking action.")

        if view == "Cards":
            for _, row in df.iterrows():
                label, color = _confidence_label(row["Score"])
                note = _action_note(row["Action"])
                links_html = " &nbsp;".join([
                    f'<a href="{html.escape(str(row[col]), quote=True)}" target="_blank" '
                    f'style="color:#4db8ff; font-size:0.72rem; text-decoration:none; border:1px solid #4db8ff33; '
                    f'border-radius:4px; padding:2px 8px;">{html.escape(col)} ↗</a>'
                    for col in ["Yahoo Finance", "Google Finance", "Moneycontrol", "BusinessLine"]
                    if col in row and pd.notna(row[col]) and row[col]
                ])
                safe_ticker = html.escape(str(row["Ticker"]))
                safe_action = html.escape(str(row["Action"]))
                safe_label = html.escape(label)
                safe_note = html.escape(note)
                st.html(f"""
                <div style='background:#122f25; border:1px solid #1a3b31;
                            border-left:4px solid {color};
                            border-radius:8px; padding:16px 18px; margin-bottom:14px;'>

                    <div style='display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:8px;'>
                        <div>
                            <span style='font-family:"IBM Plex Mono",monospace; font-size:1.2rem;
                                          font-weight:700; color:#e8f7ef;'>{safe_ticker}</span>
                            <span style='font-family:"IBM Plex Mono",monospace; font-size:1.1rem;
                                          color:#a3d8b8; margin-left:12px;'>{row["Price"]:.2f}</span>
                        </div>
                        <div style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                            <span style='font-size:9px; background:{color}22; border:1px solid {color}55;
                                          color:{color}; border-radius:12px; padding:2px 10px;
                                          font-weight:700; letter-spacing:1px;'>
                                {safe_label}
                            </span>
                            <span style='font-size:9px; color:#a3d8b8; font-family:"IBM Plex Mono",monospace;'>
                                {safe_action}
                            </span>
                        </div>
                    </div>

                    <div style='display:flex; gap:20px; margin-top:10px; flex-wrap:wrap;
                                font-family:"IBM Plex Mono",monospace; font-size:0.78rem;'>
                        <span><span style='color:#a3d8b8;'>PE  </span>{row["PE Ratio"]:.1f}×</span>
                        <span><span style='color:#a3d8b8;'>VOL </span>{row["Volume Ratio"]:.2f}×&nbsp;avg</span>
                        <span><span style='color:#a3d8b8;'>RSI </span>{row["RSI"]:.1f}</span>
                    </div>

                    <div style='margin-top:8px;'><span style="color:#25d366; font-size:0.72rem;">● Composite score</span> &nbsp;
                        <span style="color:#4db8ff; font-size:0.72rem;">Score {row["Score"]:.1f}</span>
                    </div>

                    <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
                        <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                                    padding:8px 10px; border:1px solid #1c3020;'>
                            <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                                        text-transform:uppercase;'>PE</div>
                            <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                                        color:#e8f7ef; font-weight:700;'>{row["PE Ratio"]:.1f}×</div>
                        </div>
                        <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                                    padding:8px 10px; border:1px solid #1c3020;'>
                            <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                                        text-transform:uppercase;'>Volume</div>
                            <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                                        color:#e8f7ef; font-weight:700;'>{row["Volume Ratio"]:.2f}×</div>
                        </div>
                        <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                                    padding:8px 10px; border:1px solid #1c3020;'>
                            <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                                        text-transform:uppercase;'>RSI</div>
                            <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                                        color:#e8f7ef; font-weight:700;'>{row["RSI"]:.1f}</div>
                        </div>
                    </div>

                    <div style='margin-top:12px; font-size:0.75rem; color:#7abeac;
                                border-top:1px solid #1a3b31; padding-top:8px;'>
                        💡 {safe_note}
                    </div>

                    <div style='margin-top:10px;'>{links_html}</div>
                </div>
                """)
        else:
            df_table = df.copy()
            df_table["Confidence"] = df_table["Score"].apply(
                lambda sc: _confidence_label(float(sc))[0] if pd.notna(sc) else "—"
            )

            display_cols = [
                "Ticker", "Decision", "Composite", "Matrix note",
                "Price", "PE Ratio", "Volume Ratio", "RSI", "Score",
                "Confidence", "Action",
                "Yahoo Finance", "Google Finance", "Moneycontrol", "BusinessLine",
            ]
            visible_cols = [col for col in display_cols if col in df_table.columns]

            col_cfg = {
                "Decision": st.column_config.TextColumn("Decision", width="medium"),
                "Matrix note": st.column_config.TextColumn("Matrix note", width="large"),
                "Composite": st.column_config.NumberColumn("Composite", format="%.1f"),
                "Price": st.column_config.NumberColumn("Price", format="%.2f"),
                "PE Ratio": st.column_config.NumberColumn("PE Ratio", format="%.2f"),
                "Volume Ratio": st.column_config.NumberColumn("Volume Ratio", format="%.2f"),
                "RSI": st.column_config.NumberColumn("RSI", format="%.2f"),
                "Score": st.column_config.NumberColumn("Score", format="%.1f"),
                "Confidence": st.column_config.TextColumn("Confidence", width="medium"),
                "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
                "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
                "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
                "BusinessLine": st.column_config.LinkColumn("BusinessLine", display_text="BL ↗"),
            }

            render_clickable_scan_table(
                df_table[visible_cols],
                key_prefix="bha_results",
                universe_name="NSE",
                column_config=filter_column_config(df_table[visible_cols], col_cfg),
                hide_index=False,
                height=min(600, 60 + len(df_table) * 38),
            )
            csv = df_table[visible_cols].to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇ Download Buy/Hold/Avoid CSV",
                csv,
                file_name=f"stocksight_bha_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                key="bha_dl_csv",
            )
            render_decision_matrix_legend()

        selected_ticker = st.selectbox(
            "Preview news links for",
            options=df["Ticker"].tolist(),
            index=0,
            help="Pick a ticker to open Yahoo Finance news, Moneycontrol search, or BusinessLine headlines.",
        )

        if selected_ticker:
            clean_ticker = selected_ticker.replace(".NS", "").replace(".BO", "")
            if selected_ticker.endswith(".NS"):
                gf_exchange = "NSE"
            elif selected_ticker.endswith(".BO"):
                gf_exchange = "BOM"
            else:
                gf_exchange = "NASDAQ"
            news_links = {
                "Yahoo Finance News": f"https://finance.yahoo.com/quote/{clean_ticker}/news",
                "Google Finance": f"https://www.google.com/finance/quote/{clean_ticker}:{gf_exchange}",
                "Moneycontrol Search": f"https://www.moneycontrol.com/india/stockpricequote/search?q={quote_plus(clean_ticker)}",
                "BusinessLine Search": f"https://www.thehindubusinessline.com/search/?q={quote_plus(clean_ticker)}",
            }
            news_anchor_html = "".join(
                f"<a class='news-link' href='{html.escape(url, quote=True)}' target='_blank'>"
                f"{html.escape(label)} ↗</a>"
                for label, url in news_links.items()
            )
            st.html(f"""
            <div class='chart-card'>
                <div class='chart-title'>📰 Quick News Links</div>
                <div class='chart-subtitle'>Open the latest newsroom for the selected ticker.</div>
                <div class='news-links'>{news_anchor_html}</div>
            </div>
            """)

st.markdown("---")

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

