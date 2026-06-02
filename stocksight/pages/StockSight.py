"""
StockSight — main fundamental + momentum screener (PE, volume, RSI, composite score).
For: active traders and investors who want one ranked list across Nifty 50/500 or S&P 500.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from screener import (
    screen_stocks,
    UNIVERSES,
    us_market_status_label,
    enrich_dataframe_yahoo_context,
)
from scan_history_store import append_scan_record
from market_sentiment import market_from_universe
from ui_components import (
    SCAN_CONFIRM_ACTION_COL,
    SCAN_NEWS_SCORE_COL,
    SCAN_TIER_REF_COL,
    SCAN_TOP_HEADLINE_COL,
    SCAN_TOP_TIER_COL,
    SCAN_RESULTS_NEWS_COL,
    filter_column_config,
    first_seen_label,
    notify_watchlist_alerts_screen_df,
    page_audience_note,
    prepare_scan_results_df,
    raw_symbol_from_screen_display,
    render_decision_matrix_legend,
    render_historical_detail_panel,
    render_watchlist_panel,
    safe_set_page_config,
)
try:
    from quality_gate import GATE_COL, dataframe_gate_styler, render_quality_gate_legend
except ImportError:
    from .quality_gate import GATE_COL, dataframe_gate_styler, render_quality_gate_legend  # type: ignore[no-redef]

safe_set_page_config(
    page_title="StockSight | Smart Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

  section.main,
  section.main .block-container {
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
  section.main [data-testid="stSelectbox"] label,
  section.main [data-testid="stTextInput"] label,
  section.main [data-testid="stSlider"] label {
    color: #b8e7c7 !important;
  }
  section.main div[data-baseweb="select"] > div,
  section.main div[data-baseweb="select"] > div > div {
    background-color: #16352c !important;
    color: #e8f7ef !important;
    border-color: #1a3b31 !important;
  }
  section.main div[data-baseweb="select"] input,
  section.main div[data-baseweb="select"] span,
  section.main div[data-baseweb="select"] [role="combobox"] {
    color: #e8f7ef !important;
    -webkit-text-fill-color: #e8f7ef !important;
  }
  section.main [data-testid="stTextInput"] input {
    background-color: #16352c !important;
    color: #e8f7ef !important;
    -webkit-text-fill-color: #e8f7ef !important;
    border-color: #1a3b31 !important;
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

page_audience_note(
    "Anyone building a daily or weekly shortlist—beginners can start with Nifty 50; active users can tune PE, volume, and RSI.",
    "Runs the core screen across your chosen universe, ranks by composite score, and shows table/cards with "
    "Yahoo / Moneycontrol / TradingView links, recent headlines (last 4 days) in the results table, and watchlist alerts.",
)

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
RSI-14 · Volume vs 20-bar avg · MACD hist · MA20 vs price · Bollinger %B · ATR14 · Next earnings (best-effort)<br>
Trailing PE via Yahoo Finance
</div>
""",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown("#### Filters")
        pe_max = st.slider("Max PE Ratio", min_value=5.0, max_value=50.0, value=30.0, step=0.5, key="app1_pe")
        vol_mult = st.slider("Min Volume Spike (×avg)", min_value=1.0, max_value=10.0, value=1.5, step=0.1, key="app1_vol")
        rsi_min = st.slider("Min RSI (14)", min_value=30.0, max_value=80.0, value=50.0, step=1.0, key="app1_rsi")

render_watchlist_panel("app1_wl")

with st.expander("Advanced screening — bars, sector, confirmations", expanded=False):
    interval_key = st.selectbox(
        "Bar interval",
        options=["1d", "1h", "15m"],
        format_func=lambda x: {"1d": "Daily", "1h": "1 Hour", "15m": "15 Minute"}[x],
        key="app1_interval",
    )
    sector_txt = st.text_input(
        "Sector contains (optional)",
        "",
        key="app1_sector",
        placeholder="e.g. Financial Services",
    )
    require_above_ma20 = st.checkbox(
        "Require close above MA20",
        value=False,
        key="app1_ma20",
    )
    require_macd_bullish = st.checkbox(
        "Require MACD histogram > 0",
        value=False,
        key="app1_macd",
    )
    exclude_earn_days = st.slider(
        "Exclude if earnings within N days (0 = off)",
        min_value=0,
        max_value=21,
        value=0,
        step=1,
        key="app1_exearn",
    )
    use_rs_filter = st.checkbox(
        "Require minimum RS vs benchmark (20-bar excess return vs Nifty/SPY)",
        value=False,
        key="app1_rs_use",
    )
    min_rs_pp = st.slider(
        "Min RS vs benchmark (percentage points)",
        min_value=-30.0,
        max_value=30.0,
        value=0.0,
        step=0.5,
        key="app1_rs_min",
    )
    fund_on = st.checkbox(
        "Enable Yahoo fundamental gates (ROE / debt / revenue growth)",
        value=False,
        key="app1_fund_on",
    )
    min_roe_pct_ui = st.slider("Min ROE %", min_value=0, max_value=40, value=8, key="app1_roe")
    max_de_ui = st.slider("Max debt/equity", min_value=0.0, max_value=400.0, value=250.0, step=5.0, key="app1_de")
    min_rev_ui = st.slider(
        "Min revenue growth %",
        min_value=-50.0,
        max_value=60.0,
        value=0.0,
        step=1.0,
        key="app1_rev",
    )

sector_filter_val = (sector_txt or "").strip() or ""

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
        interval_key=interval_key,
        sector_filter=sector_filter_val,
        require_above_ma20=require_above_ma20,
        require_macd_bullish=require_macd_bullish,
        exclude_earnings_within_days=int(exclude_earn_days),
        min_rs_vs_bench=float(min_rs_pp) if use_rs_filter else None,
        min_roe_pct=float(min_roe_pct_ui) if fund_on else None,
        max_debt_equity=float(max_de_ui) if fund_on else None,
        min_revenue_growth_pct=float(min_rev_ui) if fund_on else None,
    )

    try:
        syms_out: list[str] = []
        if not df.empty and "Ticker" in df.columns:
            for t in df["Ticker"].astype(str).tolist():
                if "NSE" in universe:
                    syms_out.append(f"{t}.NS")
                else:
                    syms_out.append(t)
        append_scan_record("StockSight", universe, syms_out, meta={"rows": int(len(df.index))})
    except Exception:
        pass

    try:
        notify_watchlist_alerts_screen_df(df, universe, "StockSight")
    except Exception:
        pass

    progress_ph.empty()
    status_ph.empty()
    st.session_state.app1_results_df = df
    st.session_state.app1_last_run = datetime.now()
    st.session_state.app1_is_running = False
    st.session_state.pop("app1_yahoo_cache_sig", None)


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

if universe == "S&P 500 (NYSE)":
    st.caption(us_market_status_label())

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
    display_df = df.copy()
    if "Ticker" in display_df.columns:

        insert_at = 1 if len(display_df.columns) >= 1 else 0
        display_df.insert(
            insert_at,
            "First seen",
            [
                first_seen_label(raw_symbol_from_screen_display(str(x), universe))
                for x in display_df["Ticker"].tolist()
            ],
        )
    display_df = prepare_scan_results_df(
        display_df,
        market=market_from_universe(universe),
        universe_name=universe,
        cache_key_prefix="app1",
        sort_by_gate=True,
    )

    _link_cols = (
        "Yahoo Finance",
        "Google Finance",
        "Moneycontrol",
        "MarketWatch",
        "TradingView",
    )
    col_cfg = filter_column_config(
        display_df,
        {
            "Market sentiment": st.column_config.TextColumn("Market sentiment", width="medium"),
            "Sentiment why": st.column_config.TextColumn("Sentiment why", width="large"),
            SCAN_RESULTS_NEWS_COL: st.column_config.TextColumn(SCAN_RESULTS_NEWS_COL, width="large"),
            SCAN_NEWS_SCORE_COL: st.column_config.ProgressColumn(SCAN_NEWS_SCORE_COL, min_value=0, max_value=100, format="%d"),
            SCAN_TOP_TIER_COL: st.column_config.TextColumn(SCAN_TOP_TIER_COL, width="small"),
            SCAN_TIER_REF_COL: st.column_config.TextColumn(SCAN_TIER_REF_COL, width="medium"),
            SCAN_TOP_HEADLINE_COL: st.column_config.TextColumn(SCAN_TOP_HEADLINE_COL, width="large"),
            SCAN_CONFIRM_ACTION_COL: st.column_config.TextColumn(SCAN_CONFIRM_ACTION_COL, width="medium"),
            "Decision": st.column_config.TextColumn("Decision", width="medium"),
            "Matrix note": st.column_config.TextColumn("Matrix note", width="large"),
            "Composite": st.column_config.NumberColumn("Composite", format="%.1f"),
            "Price": st.column_config.NumberColumn(format="%.2f"),
            "PE Ratio": st.column_config.NumberColumn(format="%.1f"),
            "Volume Ratio": st.column_config.NumberColumn(format="%.2f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "Quality Gate": st.column_config.TextColumn("Quality Gate", width="small"),
            "Gate score": st.column_config.ProgressColumn("Gate score", min_value=0, max_value=100, format="%d"),
            "Gate why": st.column_config.TextColumn("Gate why", width="large"),
            **{
                name: st.column_config.LinkColumn(name, display_text="Open ↗")
                for name in _link_cols
            },
        },
    )
    y1, y2 = st.columns(2)
    with y1:
        include_analyst_csv = st.checkbox(
            "Analyst recommendations (Yahoo)",
            value=True,
            key="app1_analyst_csv",
            help="Consensus, targets, rating mix.",
        )
    with y2:
        include_history_csv = st.checkbox(
            "Historical snapshot ~1y (Yahoo)",
            value=True,
            key="app1_history_csv",
            help="1M/3M/6M/1Y returns, 52w range, volume.",
        )

    export_df = display_df
    want_yahoo = include_analyst_csv or include_history_csv
    if want_yahoo:
        if len(display_df) > 60:
            st.warning("Yahoo columns skipped — more than 60 rows. Narrow filters or turn off checkboxes.")
        else:
            sig = (
                universe,
                tuple(display_df["Ticker"].astype(str).tolist()),
                include_analyst_csv,
                include_history_csv,
            )
            if st.session_state.get("app1_yahoo_cache_sig") != sig:
                with st.spinner("Fetching Yahoo analyst + historical data…"):
                    export_df = enrich_dataframe_yahoo_context(
                        display_df,
                        universe_name=universe,
                        ticker_col="Ticker",
                        include_analyst=include_analyst_csv,
                        include_history=include_history_csv,
                    )
                    st.session_state.app1_yahoo_cache_sig = sig
                    st.session_state.app1_export_df = export_df
            else:
                export_df = st.session_state.get("app1_export_df", display_df)

    show_df = export_df if want_yahoo and (
        "Historical snapshot" in export_df.columns or "Analyst recommendation" in export_df.columns
    ) else display_df

    table_col_cfg = dict(col_cfg)
    for text_col in ("Analyst recommendation", "Historical snapshot", "Historical detail"):
        if text_col in show_df.columns:
            table_col_cfg[text_col] = st.column_config.TextColumn(text_col, width="large")

    if GATE_COL in show_df.columns:
        render_quality_gate_legend(profile="daily")
    gate_note = " · 🟢/🟡/🟠/🔴 = Quality Gate" if GATE_COL in show_df.columns else ""
    st.caption(f"💡 Click any row to load its interactive chart in the panel below.{gate_note}")
    table_arg = dataframe_gate_styler(show_df) if GATE_COL in show_df.columns else show_df
    table_event = st.dataframe(
        table_arg,
        use_container_width=True,
        hide_index=False,
        column_config=filter_column_config(show_df, table_col_cfg),
        height=min(620, 60 + len(show_df) * 40),
        selection_mode="single-row",
        on_select="rerun",
        key="app1_results_table",
    )

    selected_ticker = None
    try:
        sel_rows = table_event.selection.rows  # type: ignore[union-attr]
        if sel_rows:
            row_idx = int(sel_rows[0])
            if 0 <= row_idx < len(show_df) and "Ticker" in show_df.columns:
                selected_ticker = str(show_df.iloc[row_idx]["Ticker"])
    except Exception:
        selected_ticker = None

    render_historical_detail_panel(
        export_df if want_yahoo else display_df,
        universe_name=universe,
        key_prefix="app1_hist",
        selected_ticker=selected_ticker,
    )
    csv = export_df.to_csv(index=True if export_df.index.name else False)
    st.download_button(
        label="⬇ Download Results as CSV",
        data=csv,
        file_name=f"stocksight_app1_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="app1_dl_csv",
    )
    render_decision_matrix_legend()

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
