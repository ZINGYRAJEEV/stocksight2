"""
ui_components.py — Shared UI helpers for all signal pages.
"""

import html
import hashlib
from datetime import datetime
from typing import Callable, Optional

import streamlit as st
import pandas as pd
import numpy as np

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

try:
    from plotly.subplots import make_subplots
except ImportError:
    make_subplots = None

try:
    from .screener import (
        DECISION_ZONES,
        compute_score,
        decision_from_metrics,
        fetch_price_history,
        matrix_decision,
        matrix_decision_note,
        rsi_series_wilder,
        compute_vwap,
        enrich_dataframe_recent_news,
        format_recent_news_cell,
    )
    from .signals import SignalResult, SCENARIOS, enrich_results_news, scenario_display_title
    from .scan_history_store import append_scan_record, build_first_seen_map
    from .watchlist_store import (
        add_to_watchlist,
        load_alert_prefs,
        load_watchlist,
        remove_from_watchlist,
        set_email_watchlist_alerts,
        upsert_watchlist_fields,
    )
    from .market_sentiment import add_market_sentiment_columns, market_from_universe
    from .news_scanner import attach_news_scanner_columns
    from .quality_gate import (
        GATE_COL,
        GATE_SCORE_COL,
        GATE_WHY_COL,
        apply_quality_gate_columns,
        build_scenario_confluence_map,
        dataframe_gate_styler,
        detect_quality_gate_profile,
        quality_gate_column_config,
        quality_gate_row_css,
        render_quality_gate_legend,
    )
except ImportError:
    from screener import (
        DECISION_ZONES,
        compute_score,
        decision_from_metrics,
        fetch_price_history,
        matrix_decision,
        matrix_decision_note,
        rsi_series_wilder,
        compute_vwap,
        enrich_dataframe_recent_news,
        format_recent_news_cell,
    )
    from signals import SignalResult, SCENARIOS, enrich_results_news, scenario_display_title
    from scan_history_store import append_scan_record, build_first_seen_map
    from watchlist_store import (
        add_to_watchlist,
        load_alert_prefs,
        load_watchlist,
        remove_from_watchlist,
        set_email_watchlist_alerts,
        upsert_watchlist_fields,
    )
    from market_sentiment import add_market_sentiment_columns, market_from_universe  # type: ignore[no-redef]
    from news_scanner import attach_news_scanner_columns  # type: ignore[no-redef]
    from quality_gate import (  # type: ignore[no-redef]
        GATE_COL,
        GATE_SCORE_COL,
        GATE_WHY_COL,
        apply_quality_gate_columns,
        build_scenario_confluence_map,
        dataframe_gate_styler,
        detect_quality_gate_profile,
        quality_gate_column_config,
        quality_gate_row_css,
        render_quality_gate_legend,
    )


INTERVAL_LABELS = {"1d": "Daily", "1h": "1 Hour", "15m": "15 Minute"}


def scenario_page_alert_hint(nav_registry_key: str) -> str:
    """Human title for emails / banners from `SCENARIOS` sidebar registry key."""
    meta = SCENARIOS.get(nav_registry_key)
    if meta and isinstance(meta, dict) and meta.get("title"):
        return str(meta["title"])
    return str(nav_registry_key)


def first_seen_label(raw_ticker: str) -> str:
    """First calendar date this raw symbol appeared in `.scan_history.jsonl`, else —."""
    s = str(raw_ticker or "").strip()
    if not s:
        return "—"
    return build_first_seen_map().get(s, "—")


def safe_set_page_config(**kwargs) -> None:
    """Call set_page_config once per session; ignore repeats (e.g. under st.navigation)."""
    try:
        st.set_page_config(**kwargs)
    except st.errors.StreamlitAPIException:
        pass


def ensure_session_choice(key: str, choices: list, default: str | None = None) -> str:
    """Reset a widget session value when options were renamed (avoids Streamlit KeyError on Cloud)."""
    if not choices:
        return ""
    fallback = default if default is not None else choices[0]
    if st.session_state.get(key) not in choices:
        st.session_state[key] = fallback
    return str(st.session_state[key])


def filter_column_config(df: pd.DataFrame, column_config: dict) -> dict:
    """Streamlit raises KeyError if column_config references columns missing from df."""
    if df is None or df.empty:
        return {}
    cols = set(df.columns)
    return {k: v for k, v in column_config.items() if k in cols}


def page_audience_note(who_for: str, what_it_does: str) -> None:
    """Short guidance block: intended user and what the page does."""
    st.info(
        f"**Who this is for:** {who_for}\n\n"
        f"**What it does:** {what_it_does}"
    )


def stock_sight_column_config() -> dict:
    """Shared column config for StockSight composite / gate columns."""
    if st is None:
        return {}
    gate_col = "Quality Gate"
    gate_score_col = "Gate score"
    gate_why_col = "Gate why"
    return {
        "Composite": st.column_config.NumberColumn("Composite", format="%.1f"),
        "StockSight score": st.column_config.NumberColumn("StockSight score", format="%.1f"),
        "Screen score": st.column_config.NumberColumn("Screen score", format="%.1f"),
        "HP Score": st.column_config.NumberColumn("HP Score", format="%.1f"),
        "Fit score": st.column_config.NumberColumn("Fit score", format="%.1f"),
        "Decision": st.column_config.TextColumn("Decision", width="medium"),
        "Matrix note": st.column_config.TextColumn("Matrix note", width="large"),
        "Conflict": st.column_config.TextColumn("Conflict", width="large"),
        "Returns": st.column_config.TextColumn("Returns", width="medium"),
        "Flags": st.column_config.TextColumn("Flags", width="medium"),
        "StockSight sentiment": st.column_config.TextColumn("StockSight sentiment", width="small"),
        "G1 Momentum": st.column_config.NumberColumn("G1 Momentum", format="%d"),
        "G2 Fundamentals": st.column_config.NumberColumn("G2 Fundamentals", format="%d"),
        "G3 Volume": st.column_config.NumberColumn("G3 Volume", format="%d"),
        "G4 RS": st.column_config.NumberColumn("G4 RS", format="%d"),
        "G5 Trend": st.column_config.NumberColumn("G5 Trend", format="%d"),
        "G6 News": st.column_config.NumberColumn("G6 News", format="%d"),
        gate_col: st.column_config.TextColumn(gate_col, width="small"),
        gate_score_col: st.column_config.ProgressColumn(
            gate_score_col, min_value=0, max_value=100, format="%d",
        ),
        gate_why_col: st.column_config.TextColumn(gate_why_col, width="large"),
    }


def stock_sight_overlay_column_config() -> dict:
    """Column config for secondary SS_* StockSight overlay on specialized screeners."""
    if st is None:
        return {}
    return {
        "SS Composite": st.column_config.NumberColumn("SS Composite", format="%.1f"),
        "SS Decision": st.column_config.TextColumn("SS Decision", width="small"),
        "SS Gate": st.column_config.TextColumn("SS Gate", width="small"),
        "SS Gate why": st.column_config.TextColumn("SS Gate why", width="medium"),
        "SS Flags": st.column_config.TextColumn("SS Flags", width="medium"),
        "SS Conflict": st.column_config.TextColumn("SS Conflict", width="medium"),
        "SS Returns": st.column_config.TextColumn("SS Returns", width="medium"),
        "SS Sentiment": st.column_config.TextColumn("SS Sentiment", width="small"),
        "SS G1": st.column_config.NumberColumn("SS G1", format="%d"),
        "SS G2": st.column_config.NumberColumn("SS G2", format="%d"),
        "SS G3": st.column_config.NumberColumn("SS G3", format="%d"),
        "SS G4": st.column_config.NumberColumn("SS G4", format="%d"),
        "SS G5": st.column_config.NumberColumn("SS G5", format="%d"),
        "SS G6": st.column_config.NumberColumn("SS G6", format="%d"),
    }


def render_decision_matrix_legend() -> None:
    """Reference key for Decision / Matrix note columns shown after scans."""
    with st.expander("📊 StockSight scoring rules (reference)", expanded=False):
        st.caption(
            "**Composite** (0–100) = Momentum (25) + Fundamentals (20) + Volume (15) + "
            "RS vs index (15) + Trend (15) + News (10). **Quality Gate** A–D can override trust. "
            "**Decision** = Buy / Watch · Neutral · Skip."
        )
        st.markdown(
            "| Gate | Meaning |\n|------|--------|\n"
            "| 🟢 A | Trade ready — no flags, score ≥ 60 |\n"
            "| 🟡 B | Watch — one soft flag |\n"
            "| 🟠 C | Caution — 2+ soft flags |\n"
            "| 🔴 D | Skip — hard flag (RSI>72, earnings ≤5d, MACD falling) |"
        )
        st.markdown(
            "**Decision matrix:** Gate D → always Skip. Gate C downgrades one step. "
            "Score ≥ 65 + gate A/B → Buy / Watch. Conflict banner when score ≥ 60, gate D, RSI exhaustion."
        )
        st.markdown(
            "**Score bands:** 65–100 green (strong) · 45–64 blue (moderate) · 0–44 red (weak)."
        )
        for threshold, label, note in DECISION_ZONES:
            st.markdown(f"- **{label}** (composite ≥ {threshold:.0f}): {note}")


def _decision_for_signal_result(r: SignalResult) -> tuple[str, float, str]:
    dec, comp, note = decision_from_metrics(
        r.pe,
        r.vol_ratio,
        r.rsi,
        signal_label=r.signal_label,
        scenario_id=r.scenario_id,
    )
    return dec, comp, note


# ─────────────────────────────────────────────
# Page-level CSS (call once per page)
# ─────────────────────────────────────────────

APP_CHROME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

/* Sidebar nav — dark panel, light text (do not use html/body/[class*="css"] globals). */
section[data-testid="stSidebar"],
[data-testid="stSidebar"] {
    background-color: #0d1f18 !important;
    border-right: 1px solid #1a3b31 !important;
    color: #e8f7ef !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    background-color: #0d1f18 !important;
    color: #e8f7ef !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] a,
[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNavLink"],
[data-testid="stSidebarNavLink"] span {
    color: #e8f7ef !important;
}
[data-testid="stSidebarNavLink"][aria-current="page"],
[data-testid="stSidebarNavLink"][aria-current="page"] span {
    color: #25d366 !important;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
    color: #a3d8b8 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #1a3b31 !important;
}
[data-testid="stSidebar"] button[kind="header"] {
    color: #e8f7ef !important;
}
</style>
"""

BASE_CSS = """
<style>
:root {
    color-scheme: light;
    --app-bg: #f8fafc;
    --app-text: #111827;
    --button-bg: linear-gradient(135deg,#25d366,#1aa34b);
}

section.main,
section.main .block-container {
    font-family: 'IBM Plex Sans', sans-serif;
    background-color: var(--app-bg);
    color: var(--app-text);
}
.stButton > button {
    background: var(--button-bg);
    color: #000; font-family:'IBM Plex Mono',monospace;
    font-weight:700; font-size:0.82rem; border:none; border-radius:6px;
    padding:10px 24px; letter-spacing:1px; text-transform:uppercase;
    cursor:pointer; width:100%;
}
.stButton > button:hover { opacity:0.92; }
section.main label { color: #111827 !important; font-size: 0.8rem; }
.stProgress > div > div { background-color:#25d366; }
section.main hr { border-color:#d4d4d4 !important; }

/* Universe / filters — light controls on light main (Popular Screens, Multibagger, scenarios, etc.) */
section.main [data-testid="stSelectbox"] label,
section.main [data-testid="stMultiSelect"] label,
section.main [data-testid="stTextInput"] label,
section.main [data-testid="stNumberInput"] label,
section.main [data-testid="stSlider"] label,
section.main [data-testid="stRadio"] label,
section.main [data-testid="stCheckbox"] label {
    color: #111827 !important;
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
section.main [data-testid="stTextInput"] input,
section.main [data-testid="stTextInput"] textarea,
section.main [data-testid="stNumberInput"] input {
    background-color: #ffffff !important;
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
    border-color: #cbd5e1 !important;
}
section.main [data-testid="stSlider"] [data-testid="stThumbValue"],
section.main [data-testid="stSlider"] [data-baseweb="slider"] {
    color: #111827 !important;
}
/* Dropdown menu (portaled) */
motion.div[data-baseweb="popover"] [role="listbox"] li,
motion.div[data-baseweb="popover"] [role="option"] {
    color: #111827 !important;
    background-color: #ffffff !important;
}
motion.div[data-baseweb="popover"] [role="option"][aria-selected="true"],
motion.div[data-baseweb="popover"] [role="option"]:hover {
    background-color: #ecfdf5 !important;
    color: #111827 !important;
}
</style>
"""


def inject_app_chrome():
    """Sidebar + nav styling — call once from Overview.py so every page has a readable menu."""
    st.markdown(APP_CHROME_CSS, unsafe_allow_html=True)


def inject_css():
    inject_app_chrome()
    st.markdown(BASE_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=180)
def _cached_chart_df(raw_ticker: str, interval_key: str, bars: int = 130):
    df = fetch_price_history(raw_ticker, interval_key)
    if df is None or df.empty:
        return None
    return df.tail(int(bars))


def render_chart_expander(raw_ticker: str, interval_key: str, uid: str) -> None:
    """Multi-pane chart: candlesticks + MA20/50 (+ VWAP intraday), volume, RSI(14)."""
    if not raw_ticker:
        return
    with st.expander("📉 Inline chart — OHLC · MA · Volume · RSI", expanded=False):
        try:
            from breeze_data import breeze_status_message

            st.caption(breeze_status_message())
        except Exception:
            pass
        df = _cached_chart_df(raw_ticker, interval_key)
        if df is None or df.empty:
            st.caption("No chart data for this symbol / interval.")
            return
        if go is None or make_subplots is None:
            st.caption("Install **plotly** for layered charts (`pip install plotly`). Showing close line.")
            st.line_chart(df["Close"])
            return
        closes = df["Close"].astype(float)
        highs = df["High"].astype(float)
        lows = df["Low"].astype(float)
        opens = df["Open"].astype(float)
        vols = df["Volume"].astype(float)
        ma20 = closes.rolling(20).mean()
        ma50 = closes.rolling(50).mean()
        rsi_line = rsi_series_wilder(closes, 14)
        vwap_line = compute_vwap(highs, lows, closes, vols)

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.58, 0.18, 0.24],
        )
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=opens,
                high=highs,
                low=lows,
                close=closes,
                name="OHLC",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(go.Scatter(x=df.index, y=ma20, name="MA20", line=dict(color="#4db8ff", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=ma50, name="MA50", line=dict(color="#f0b429", width=1)), row=1, col=1)
        if interval_key in ("1h", "15m") and vwap_line is not None and len(vwap_line):
            vv = vwap_line.replace([np.inf, -np.inf], np.nan).dropna()
            if not vv.empty:
                fig.add_trace(
                    go.Scatter(
                        x=vv.index,
                        y=vv,
                        name="VWAP",
                        line=dict(color="#c084fc", width=1, dash="dot"),
                    ),
                    row=1,
                    col=1,
                )

        colors = np.where(
            closes.values >= opens.values,
            "rgba(37,211,102,0.4)",
            "rgba(255,107,107,0.4)",
        )
        fig.add_trace(go.Bar(x=df.index, y=vols, name="Volume", marker_color=list(colors)), row=2, col=1)

        fig.add_trace(
            go.Scatter(x=df.index, y=rsi_line, name="RSI(14)", line=dict(color="#7abeac", width=1)),
            row=3,
            col=1,
        )
        fig.add_hline(y=70, line_width=1, line_dash="dash", line_color="rgba(255,107,107,0.27)", row=3, col=1)
        fig.add_hline(y=30, line_width=1, line_dash="dash", line_color="rgba(37,211,102,0.27)", row=3, col=1)

        fig.update_layout(
            height=520,
            margin=dict(l=8, r=8, t=10, b=8),
            template="plotly_dark",
            paper_bgcolor="#0d1f18",
            plot_bgcolor="#122f25",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend_orientation="h",
        )
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Vol", row=2, col=1)
        fig.update_yaxes(title_text="RSI", row=3, col=1)

        st.plotly_chart(fig, use_container_width=True, key=f"ch_{uid}")


def scenario_advanced_panel(key_prefix: str) -> dict:
    """Shared controls for scenario scans — returns kwargs-compatible dict (+ UI-only keys)."""
    with st.expander("Advanced — bars, sector, MACD / Bollinger, MTF, earnings, RSI divergence", expanded=False):
        interval_key = st.selectbox(
            "Bar interval",
            options=["1d", "1h", "15m"],
            format_func=lambda x: INTERVAL_LABELS.get(x, x),
            key=f"{key_prefix}_interval",
        )
        sector_filter = st.text_input(
            "Sector filter (substring, optional)",
            "",
            key=f"{key_prefix}_sector",
            placeholder="e.g. Financial Services, Technology",
        )
        require_macd_bullish = st.checkbox(
            "Require MACD histogram > 0",
            value=False,
            key=f"{key_prefix}_macd",
        )
        require_bb_touch_lower = st.checkbox(
            "Require touch / near lower Bollinger band",
            value=False,
            key=f"{key_prefix}_bb",
        )
        require_weekly_confirm = st.checkbox(
            "Require weekly uptrend filter (close vs 10-w MA + weekly RSI ≥ 45)",
            value=False,
            key=f"{key_prefix}_wk",
        )
        exclude_earnings_within_days = st.slider(
            "Exclude if earnings within N days (0 = off)",
            min_value=0,
            max_value=21,
            value=0,
            step=1,
            key=f"{key_prefix}_earn",
        )
        skip_bearish_divergence_buy = st.checkbox(
            "Skip BUY-side setups with bearish RSI divergence (HH price vs LH RSI)",
            value=False,
            key=f"{key_prefix}_nodivbear",
        )
        fetch_news = st.checkbox(
            "Fetch recent headlines for matches (Yahoo + Google News, 7d window, extra calls)",
            value=True,
            key=f"{key_prefix}_news",
        )
        portfolio_for_sizing = st.number_input(
            "Portfolio value for position sizing (optional, same currency as quote)",
            min_value=0.0,
            value=0.0,
            step=100000.0,
            key=f"{key_prefix}_pf",
        )
        risk_pct_per_trade = st.slider(
            "Risk % of portfolio per trade (used in share count)",
            min_value=0.25,
            max_value=5.0,
            value=1.0,
            step=0.25,
            key=f"{key_prefix}_riskpct",
        )
        use_rs_filter = st.checkbox(
            "Require minimum relative strength vs index (20-bar excess return)",
            value=False,
            key=f"{key_prefix}_users",
        )
        min_rs_vs_bench = st.slider(
            "Min RS vs index (percentage points)",
            min_value=-30.0,
            max_value=30.0,
            value=0.0,
            step=0.5,
            key=f"{key_prefix}_minrs",
        )
        weekly_macd_confirm = st.checkbox(
            "Weekly MACD histogram > 0 (extra MTF confirmation on BUY-side scans)",
            value=False,
            key=f"{key_prefix}_wkmacd",
        )
        require_stoch_cross_up = st.checkbox(
            "Require Stochastic %K cross above %D (BUY-side confirmation)",
            value=False,
            key=f"{key_prefix}_stup",
        )
        require_stoch_cross_down = st.checkbox(
            "Require Stochastic %K cross below %D (overbought / exit confirmation)",
            value=False,
            key=f"{key_prefix}_stdn",
        )

    sf = sector_filter.strip() or None
    return {
        "sector_filter": sf,
        "interval_key": interval_key,
        "require_macd_bullish": require_macd_bullish,
        "require_bb_touch_lower": require_bb_touch_lower,
        "require_weekly_confirm": require_weekly_confirm,
        "weekly_macd_confirm": weekly_macd_confirm,
        "exclude_earnings_within_days": int(exclude_earnings_within_days),
        "skip_bearish_divergence_buy": skip_bearish_divergence_buy,
        "fetch_news": fetch_news,
        "portfolio_for_sizing": portfolio_for_sizing,
        "risk_pct_per_trade": float(risk_pct_per_trade),
        "min_rs_vs_bench": float(min_rs_vs_bench) if use_rs_filter else None,
        "require_stoch_cross_up": require_stoch_cross_up,
        "require_stoch_cross_down": require_stoch_cross_down,
    }


try:
    from screener import RECENT_NEWS_COL_LABEL as SCAN_RESULTS_NEWS_COL
except ImportError:
    from .screener import RECENT_NEWS_COL_LABEL as SCAN_RESULTS_NEWS_COL  # type: ignore[no-redef]
SCAN_NEWS_SCORE_COL = "News score"
SCAN_TOP_TIER_COL = "Top tier"
SCAN_TIER_REF_COL = "Tier reference"
SCAN_TOP_HEADLINE_COL = "Top headline"
SCAN_CONFIRM_ACTION_COL = "Confirm action"


def maybe_enrich_news(
    results: list[SignalResult],
    enabled: bool = True,
    max_names: int = 35,
) -> None:
    """Fetch dated headlines (Yahoo + Google News) for cards and fall-context helpers."""
    if not enabled or not results:
        return
    if len(results) > max_names:
        st.warning(
            f"Headlines skipped — more than {max_names} matches (too many news API calls). "
            "Narrow filters or disable headlines in Advanced."
        )
        return
    enrich_results_news(results)


def ensure_scan_results_news(results: list[SignalResult], max_names: int = 35) -> None:
    """Always enrich scan matches with recent headlines when the list is small enough."""
    maybe_enrich_news(results, enabled=True, max_names=max_names)


def render_trade_plan_cards(
    results: list[SignalResult],
    scenario_id: str,
    *,
    portfolio_value: float = 0.0,
    risk_pct: float = 1.0,
) -> None:
    """Render trade-plan cards with recent news prefetched for sentiment context."""
    ensure_scan_results_news(results)
    for r in results:
        trade_plan_card(
            r,
            scenario_id,
            portfolio_value=portfolio_value,
            risk_pct=risk_pct,
        )


def _scan_table_news_column_config() -> dict:
    return {
        "Market sentiment": st.column_config.TextColumn("Market sentiment", width="medium"),
        "Sentiment why": st.column_config.TextColumn("Sentiment why", width="large"),
        SCAN_RESULTS_NEWS_COL: st.column_config.TextColumn(SCAN_RESULTS_NEWS_COL, width="large"),
        SCAN_NEWS_SCORE_COL: st.column_config.ProgressColumn(SCAN_NEWS_SCORE_COL, min_value=0, max_value=100, format="%d"),
        SCAN_TOP_TIER_COL: st.column_config.TextColumn(SCAN_TOP_TIER_COL, width="small"),
        SCAN_TIER_REF_COL: st.column_config.TextColumn(SCAN_TIER_REF_COL, width="medium"),
        SCAN_TOP_HEADLINE_COL: st.column_config.TextColumn(SCAN_TOP_HEADLINE_COL, width="large"),
        SCAN_CONFIRM_ACTION_COL: st.column_config.TextColumn(SCAN_CONFIRM_ACTION_COL, width="medium"),
        "News sources": st.column_config.TextColumn("News sources", width="small"),
        **quality_gate_column_config(),
    }


def prepare_scan_results_df(
    df: pd.DataFrame,
    *,
    market: Optional[str] = None,
    universe_name: str = "",
    cache_key_prefix: str = "",
    max_news_rows: int = 50,
    raw_ticker_col: Optional[str] = None,
    apply_quality_gate: bool = True,
    apply_stock_sight: Optional[bool] = None,
    stock_sight_overlay: bool = True,
    confluence_map: Optional[dict[str, list[str]]] = None,
    sort_by_gate: bool = False,
) -> pd.DataFrame:
    """Add market sentiment, recent news, StockSight scoring, and optional Quality Gate columns."""
    if df is None or df.empty:
        return df

    def _finish(out_df: pd.DataFrame) -> pd.DataFrame:
        try:
            from stock_sight_scoring import (
                apply_stock_sight_columns,
                apply_stock_sight_overlay_columns,
                should_apply_stock_sight_overlay,
                should_apply_stock_sight_scoring,
            )
        except ImportError:
            from .stock_sight_scoring import (  # type: ignore[no-redef]
                apply_stock_sight_columns,
                apply_stock_sight_overlay_columns,
                should_apply_stock_sight_overlay,
                should_apply_stock_sight_scoring,
            )

        def _macro_tone() -> str:
            try:
                from market_sentiment import get_macro_context
            except ImportError:
                from .market_sentiment import get_macro_context  # type: ignore[no-redef]
            try:
                return get_macro_context(mkt).macro_tone
            except Exception:
                return "Neutral"

        use_stock_sight = (
            should_apply_stock_sight_scoring(out_df)
            if apply_stock_sight is None
            else bool(apply_stock_sight)
        )
        if use_stock_sight:
            out_df = apply_stock_sight_columns(out_df, macro_tone=_macro_tone())
        elif stock_sight_overlay and should_apply_stock_sight_overlay(out_df):
            out_df = apply_stock_sight_overlay_columns(out_df, macro_tone=_macro_tone())
        elif apply_quality_gate and GATE_COL not in out_df.columns:
            prof = detect_quality_gate_profile(out_df)
            out_df = apply_quality_gate_columns(
                out_df,
                profile=prof,
                confluence_map=confluence_map,
                sort_by_gate=sort_by_gate,
            )
        if sort_by_gate and GATE_COL in out_df.columns:
            band_order = {"🟢": 0, "🟡": 1, "🟠": 2, "🔴": 3}
            out_df = out_df.copy()
            out_df["_gate_sort"] = out_df[GATE_COL].astype(str).map(
                lambda s: band_order.get(s[:2] if len(s) >= 2 else s, 9)
            )
            sort_cols = ["_gate_sort"]
            if "Composite" in out_df.columns:
                sort_cols.append("Composite")
            elif "Score" in out_df.columns:
                sort_cols.append("Score")
            out_df = out_df.sort_values(sort_cols, ascending=[True, False]).drop(
                columns=["_gate_sort"], errors="ignore"
            )
            out_df = out_df.reset_index(drop=True)
            if out_df.index.name != "Rank":
                out_df.index += 1
                out_df.index.name = "Rank"
        return out_df

    mkt = market or market_from_universe(universe_name)
    insert_after = next((c for c in ("Ticker", "Name", "ticker") if c in df.columns), "Ticker")

    if "Market sentiment" not in df.columns:
        df = add_market_sentiment_columns(df, market=mkt, insert_after=insert_after)

    if SCAN_RESULTS_NEWS_COL in df.columns or "Recent news (<4d)" in df.columns:
        return _finish(df)

    raw_col = raw_ticker_col
    if raw_col is None and "Raw" in df.columns:
        raw_col = "Raw"

    ticker_key = "Ticker" if "Ticker" in df.columns else ("ticker" if "ticker" in df.columns else df.columns[0])
    news_cache_key = (
        f"scan_news_{cache_key_prefix}_{universe_name}_{mkt}_"
        f"{hash(tuple(df[ticker_key].astype(str).tolist()))}"
    )

    if len(df) <= max_news_rows:
        if news_cache_key not in st.session_state:
            max_age = int(st.session_state.get("news_scan_max_age", 7))
            with st.spinner("Loading Screener company announcements…"):
                enriched = enrich_dataframe_recent_news(
                    df,
                    universe_name=universe_name,
                    raw_ticker_col=raw_col,
                    max_age_days=max_age,
                    insert_after="Sentiment why" if "Sentiment why" in df.columns else insert_after,
                    skip_company_lookup=True,
                )
                mkt_for_news = "S&P 500 (NYSE)" if str(mkt).upper() == "US" else "Nifty 500 (NSE)"
                enriched = attach_news_scanner_columns(
                    enriched,
                    universe_name=mkt_for_news,
                    max_rows=len(enriched),
                    max_age_days=max_age,
                    fast_universe=True,
                    cache_key=f"{news_cache_key}_confirm",
                )
                st.session_state[news_cache_key] = enriched
        return _finish(st.session_state[news_cache_key])

    out = df.copy()
    out[SCAN_RESULTS_NEWS_COL] = f"— (narrow to ≤{max_news_rows} rows for headlines)"
    out[SCAN_NEWS_SCORE_COL] = None
    out[SCAN_TOP_TIER_COL] = "—"
    out[SCAN_TIER_REF_COL] = "—"
    out[SCAN_TOP_HEADLINE_COL] = "—"
    out[SCAN_CONFIRM_ACTION_COL] = f"— (narrow to ≤{max_news_rows} rows for confirmation)"
    return _finish(out)


def maybe_enrich_healthy_dip_context(results: list[SignalResult], enabled: bool, max_names: int = 30) -> None:
    """Headlines + one-line fall context for Healthy Dip (on by default after scan)."""
    if not enabled or not results:
        return
    try:
        from signals import enrich_healthy_dip_fall_context
    except ImportError:
        from .signals import enrich_healthy_dip_fall_context  # type: ignore[attr-defined]
    if len(results) > max_names:
        st.warning(
            f"“Why it fell” context skipped — {len(results)} matches (cap {max_names}). "
            "Tighten filters or turn off context in the panel above."
        )
        return
    enrich_healthy_dip_fall_context(results)


def log_scenario_scan(page_key: str, universe_label: str, results: list[SignalResult]) -> None:
    """Persist a lightweight snapshot for audit / 'first seen' style workflows."""
    try:
        syms = [r.raw_ticker for r in results]
        append_scan_record(page_key, universe_label or "", syms, meta={"matches": len(syms)})
    except Exception:
        return


def raw_symbol_from_screen_display(display_ticker: str, universe_name: str) -> str:
    """Map stripped screen-table ticker back to yfinance raw symbol (e.g. `RELIANCE` → `RELIANCE.NS`)."""
    s = str(display_ticker or "").strip()
    if not s:
        return ""
    if "NSE" in str(universe_name):
        return f"{s}.NS"
    return s


def notify_watchlist_alerts_from_metrics(
    metrics: list[tuple[str, str, float, float | None]],
    page_hint: str = "",
    *,
    dedupe_session_key: str | None = None,
) -> None:
    """
    Banner + optional email when rows match saved watchlist RSI / price thresholds.

    Each item is ``(display_ticker, raw_ticker, price, rsi)``. Use ``rsi=None`` to evaluate
    price alerts only (RSI thresholds are skipped).

    ``dedupe_session_key``: identical hit lists are not shown/emailed again until the hit set clears or changes.
    """
    if not metrics:
        return
    wl_by = {str(r.get("raw_ticker")): r for r in load_watchlist()}
    msgs: list[str] = []
    for disp, raw, price, rsi in metrics:
        row = wl_by.get(raw)
        if not row:
            continue
        try:
            rb = row.get("alert_rsi_below")
            ra = row.get("alert_rsi_above")
            pa = row.get("alert_price_above")
            pb = row.get("alert_price_below")
            if rsi is not None and not (isinstance(rsi, float) and np.isnan(rsi)):
                rsi_f = float(rsi)
                if rb is not None and float(rb) > 0 and rsi_f <= float(rb):
                    msgs.append(f"{disp}: RSI {rsi_f:.1f} ≤ {float(rb):.1f}")
                if ra is not None and float(ra) > 0 and rsi_f >= float(ra):
                    msgs.append(f"{disp}: RSI {rsi_f:.1f} ≥ {float(ra):.1f}")
            if pa is not None and float(pa) > 0 and price >= float(pa):
                msgs.append(f"{disp}: price {price:.2f} ≥ {float(pa):.2f}")
            if pb is not None and float(pb) > 0 and price <= float(pb):
                msgs.append(f"{disp}: price {price:.2f} ≤ {float(pb):.2f}")
        except (TypeError, ValueError):
            continue
    if not msgs:
        if dedupe_session_key:
            st.session_state.pop(f"_wl_alert_dedupe_{dedupe_session_key}", None)
        return

    if dedupe_session_key:
        slot = f"_wl_alert_dedupe_{dedupe_session_key}"
        sig = tuple(sorted(msgs))
        if st.session_state.get(slot) == sig:
            return
        st.session_state[slot] = sig

    st.info("🔔 Watchlist alert hits:\n" + "\n".join(f"- {m}" for m in msgs[:15]))

    if load_alert_prefs().get("email_watchlist_alerts"):
        try:
            from email_alerts import resolve_smtp_settings, send_watchlist_alert_email

            if not resolve_smtp_settings():
                st.warning("Email alerts are enabled, but SMTP is not configured — add `.streamlit/secrets.toml` `[smtp]` or env vars.")
            else:
                ok, err = send_watchlist_alert_email(page_hint, msgs[:50])
                if ok:
                    st.caption("📧 Sent alert summary by email.")
                else:
                    st.warning(f"Could not send email: {err}")
        except Exception as e:
            st.warning(f"Email alert error: {e}")


def notify_watchlist_alerts_screen_df(df: pd.DataFrame, universe_name: str, page_hint: str = "") -> None:
    """Watchlist alerts from a ``screen_stocks`` dataframe (expects ``Ticker``, ``Price``, ``RSI`` columns)."""
    if df is None or df.empty:
        return
    metrics: list[tuple[str, str, float, float | None]] = []
    for _, row in df.iterrows():
        try:
            disp = str(row["Ticker"]).strip()
            price = float(row["Price"])
            rsi = float(row["RSI"])
        except (KeyError, TypeError, ValueError):
            continue
        raw = raw_symbol_from_screen_display(disp, universe_name)
        if raw:
            metrics.append((disp, raw, price, rsi))
    notify_watchlist_alerts_from_metrics(metrics, page_hint)


def notify_watchlist_alerts(results: list[SignalResult], page_hint: str = "") -> None:
    """Banner when a scanned symbol matches saved RSI / price alert thresholds."""
    if not results:
        return
    metrics = [(r.ticker, r.raw_ticker, float(r.price), float(r.rsi)) for r in results]
    notify_watchlist_alerts_from_metrics(metrics, page_hint)


def render_watchlist_panel(key_prefix: str) -> None:
    with st.expander("★ Watchlist (saved on server)", expanded=False):
        rows = load_watchlist()
        if rows:
            st.caption(f"{len(rows)} symbol(s) saved — stored in `stocksight/.watchlist.json`.")
            for r in rows:
                sym = r.get("raw_ticker", "")
                note = r.get("note", "")
                cc = st.columns([4, 1])
                with cc[0]:
                    st.markdown(f"**{sym.replace('.NS','')}** — _{note}_" if note else f"**{sym.replace('.NS','')}**")
                with cc[1]:
                    if st.button("Remove", key=f"{key_prefix}_rm_{hashlib.md5(sym.encode()).hexdigest()[:12]}"):
                        remove_from_watchlist(sym)
                        st.rerun()
        else:
            st.caption("Use ★ Watchlist on a card to pin symbols here.")

        st.divider()
        manual = st.text_input("Add raw ticker (e.g. RELIANCE.NS or AAPL)", "", key=f"{key_prefix}_manual")
        if st.button("Add ticker", key=f"{key_prefix}_manual_add"):
            add_to_watchlist(manual.strip())
            st.rerun()

        st.divider()
        with st.expander("🔔 Watchlist alerts (evaluated after each scenario scan)", expanded=False):
            rows_a = load_watchlist()
            symbols = [str(r.get("raw_ticker")) for r in rows_a if r.get("raw_ticker")]
            if not symbols:
                st.caption("Save symbols first.")
            else:
                pick = st.selectbox("Pick symbol", symbols, key=f"{key_prefix}_alert_sym")
                row = next((x for x in rows_a if x.get("raw_ticker") == pick), {})

                def _num(v, default: float = 0.0) -> float:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return default

                c1, c2 = st.columns(2)
                with c1:
                    rb = st.number_input("Alert if RSI ≤ (0 = off)", 0.0, 100.0, _num(row.get("alert_rsi_below")), 1.0, key=f"{key_prefix}_arb")
                    ra = st.number_input("Alert if RSI ≥ (0 = off)", 0.0, 100.0, _num(row.get("alert_rsi_above")), 1.0, key=f"{key_prefix}_ara")
                with c2:
                    pa = st.number_input("Alert if price ≥ (0 = off)", 0.0, value=_num(row.get("alert_price_above")), step=0.05, key=f"{key_prefix}_apa")
                    pb = st.number_input("Alert if price ≤ (0 = off)", 0.0, value=_num(row.get("alert_price_below")), step=0.05, key=f"{key_prefix}_apb")
                if st.button("Save alerts", key=f"{key_prefix}_asave"):
                    upsert_watchlist_fields(pick, {
                        "alert_rsi_below": rb if rb > 0 else None,
                        "alert_rsi_above": ra if ra > 0 else None,
                        "alert_price_above": pa if pa > 0 else None,
                        "alert_price_below": pb if pb > 0 else None,
                    })
                    st.success("Saved.")
                    st.rerun()

            st.divider()
            st.markdown("**Email alerts**")
            st.caption(
                "Configure SMTP in `.streamlit/secrets.toml` under `[smtp]` or use env vars "
                "`STOCKSIGHT_SMTP_HOST`, `STOCKSIGHT_SMTP_USER`, `STOCKSIGHT_SMTP_PASSWORD`, "
                "`STOCKSIGHT_SMTP_FROM`, `STOCKSIGHT_SMTP_TO`. See `email_alerts.py` for the full schema."
            )
            prefs = load_alert_prefs()
            email_on = st.checkbox(
                "Email me when watchlist alerts fire (after a scenario scan)",
                value=bool(prefs.get("email_watchlist_alerts")),
                key=f"{key_prefix}_email_on",
            )
            ec1, ec2 = st.columns(2)
            with ec1:
                if st.button("Save email preference", key=f"{key_prefix}_email_pref_save"):
                    set_email_watchlist_alerts(email_on)
                    st.success("Saved.")
                    st.rerun()
            with ec2:
                if st.button("Send test email", key=f"{key_prefix}_email_test"):
                    try:
                        from email_alerts import resolve_smtp_settings, send_test_email

                        if not resolve_smtp_settings():
                            st.error("SMTP not configured.")
                        else:
                            ok, err = send_test_email()
                            if ok:
                                st.success("Test email sent.")
                            else:
                                st.error(err)
                    except Exception as ex:
                        st.error(str(ex))

            try:
                from email_alerts import resolve_smtp_settings

                st.caption("SMTP status: **ready** ✓" if resolve_smtp_settings() else "SMTP status: **not configured**")
            except Exception:
                st.caption("SMTP status: unknown")


def render_historical_detail_panel(
    df: pd.DataFrame,
    *,
    universe_name: str = "",
    key_prefix: str = "hist",
    selected_ticker: Optional[str] = None,
) -> None:
    """Yahoo ~1y historical fields **and** an interactive Yahoo-Finance-style chart.

    Click a ticker in the picker below the table to load 1M/3M/6M/1Y/2Y/5Y/MAX price chart
    with 50-DMA / 200-DMA overlays, range slider, and a period-return summary.
    """
    if df is None or df.empty:
        return
    has_history = "Historical detail" in df.columns
    hist_cols = [
        c
        for c in (
            "Ticker",
            "Hist start",
            "Hist end",
            "52w high",
            "52w low",
            "% below 52w high",
            "Return 1M %",
            "Return 3M %",
            "Return 6M %",
            "Return 1Y %",
            "Avg volume 20d",
            "Historical snapshot",
            "Historical detail",
        )
        if c in df.columns
    ]
    label = "📊 Historical detail & interactive chart" if has_history else "📈 Interactive price chart"
    # Auto-expand when the user has clicked a row so they immediately see the chart for that ticker.
    with st.expander(label, expanded=bool(selected_ticker)):
        if has_history and len(hist_cols) >= 2:
            st.caption("Daily OHLCV-derived stats from Yahoo Finance. Trading-day approximations for return windows.")
            st.dataframe(
                df[hist_cols],
                use_container_width=True,
                hide_index=False,
                column_config={
                    "Historical snapshot": st.column_config.TextColumn(width="large"),
                    "Historical detail": st.column_config.TextColumn(width="large"),
                },
            )

        # Ticker picker → progressive chart (Yahoo Finance style).
        if "Ticker" not in df.columns:
            return
        tickers = [str(t) for t in df["Ticker"].astype(str).tolist() if str(t).strip()]
        if not tickers:
            return

        st.markdown("---")
        st.markdown("#### 🔍 Click a ticker for an interactive price chart")
        if selected_ticker:
            st.caption(
                f"📍 Showing chart for **{html.escape(str(selected_ticker))}** — "
                "selected from the results table above. Click another row to switch, "
                "or use the dropdown below."
            )

        selectbox_key = f"{key_prefix}_chart_ticker"
        # If the user clicked a different row in the results table, sync the dropdown to it.
        if selected_ticker and selected_ticker in tickers:
            if st.session_state.get(selectbox_key) != selected_ticker:
                st.session_state[selectbox_key] = selected_ticker

        default_choice = st.session_state.get(selectbox_key) or selected_ticker or tickers[0]
        try:
            default_idx = tickers.index(str(default_choice))
        except ValueError:
            default_idx = 0

        pick = st.selectbox(
            "Ticker",
            options=tickers,
            index=default_idx,
            key=selectbox_key,
            help="Click a row in the results table above, or pick a ticker here.",
        )
        raw = ""
        if "Raw" in df.columns:
            try:
                raw = str(df.loc[df["Ticker"].astype(str) == pick, "Raw"].iloc[0])
            except Exception:
                raw = ""
        if not raw:
            raw = raw_symbol_from_screen_display(pick, universe_name)

        # Pre-buy research summary (decision, fundamentals, analyst, research links).
        try:
            picked_row = df.loc[df["Ticker"].astype(str) == pick].iloc[0]
        except Exception:
            picked_row = None
        if picked_row is not None:
            _render_pre_buy_research_card(picked_row, raw_ticker=raw)

        render_progressive_history_chart(raw, display_ticker=pick, key=f"{key_prefix}_progchart")


def render_clickable_scan_table(
    df: pd.DataFrame,
    *,
    key_prefix: str,
    universe_name: str = "",
    column_config=None,
    height: Optional[int] = None,
    hide_index: bool = True,
    caption: Optional[str] = "💡 Click any row to load its interactive chart + pre-buy research below.",
    show_panel: bool = True,
    styler=None,
    market: Optional[str] = None,
    highlight_row_test=None,
    highlight_row_style: str = "background-color: #d1fae5; color: #064e3b",
    on_row_select: Optional[Callable[[pd.Series], None]] = None,
    show_gate_legend: bool = True,
    sort_by_gate: bool = False,
    apply_stock_sight: Optional[bool] = None,
    stock_sight_overlay: bool = True,
) -> Optional[str]:
    """Render a results dataframe with row selection wired to the chart/research panel.

    Replaces an `st.dataframe(...)` call. Captures the row click and renders
    `render_historical_detail_panel(...)` (chart + pre-buy research card) below.

    If ``on_row_select`` is provided, it is called with the selected row (Series)
    whenever the user picks a row (e.g. to sync a live-trade form).

    Returns the selected display ticker (or None).
    """
    if df is None or df.empty:
        return None

    mkt = market or market_from_universe(universe_name)
    raw_col = "Raw" if "Raw" in df.columns else None
    df = prepare_scan_results_df(
        df,
        market=mkt,
        universe_name=universe_name,
        cache_key_prefix=key_prefix,
        raw_ticker_col=raw_col,
        sort_by_gate=sort_by_gate,
        apply_stock_sight=apply_stock_sight,
        stock_sight_overlay=stock_sight_overlay,
    )
    if column_config is not None:
        column_config = dict(column_config)
        for k, v in _scan_table_news_column_config().items():
            column_config.setdefault(k, v)
        for k, v in stock_sight_column_config().items():
            column_config.setdefault(k, v)
        for k, v in stock_sight_overlay_column_config().items():
            column_config.setdefault(k, v)

    if "SS Composite" in df.columns:
        st.caption(
            "**SS columns** = long-term StockSight context (6-group composite + gate). "
            "Primary score on this page stays the screen-specific model."
        )

    if show_gate_legend and GATE_COL in df.columns:
        render_quality_gate_legend(profile=detect_quality_gate_profile(df))

    gate_caption = " · 🟢/🟡/🟠/🔴 = Quality Gate band" if GATE_COL in df.columns else ""
    if caption:
        st.caption(caption + gate_caption)
    elif gate_caption:
        st.caption(gate_caption.strip(" · "))

    if highlight_row_test is not None:
        def _highlight_style(row: pd.Series) -> list[str]:
            if highlight_row_test(row):
                css = "background-color: #fff7ed; color: #7c2d12; border-left: 4px solid #f0b429;"
            elif GATE_COL in df.columns:
                css = quality_gate_row_css(row)
            else:
                css = ""
            return [css] * len(row)

        table_arg = df.style.apply(_highlight_style, axis=1)  # type: ignore[union-attr]
    elif styler is not None:
        table_arg = styler
    elif GATE_COL in df.columns:
        table_arg = dataframe_gate_styler(df)
    else:
        table_arg = df
    kwargs = {
        "use_container_width": True,
        "hide_index": hide_index,
        "selection_mode": "single-row",
        "on_select": "rerun",
        "key": f"{key_prefix}_table",
    }
    if column_config is not None:
        kwargs["column_config"] = column_config
    if height is not None:
        kwargs["height"] = height

    event = st.dataframe(table_arg, **kwargs)

    selected_ticker: Optional[str] = None
    try:
        sel_rows = event.selection.rows  # type: ignore[union-attr]
        if sel_rows:
            row_idx = int(sel_rows[0])
            if 0 <= row_idx < len(df):
                row = df.iloc[row_idx]
                if "Ticker" in df.columns:
                    selected_ticker = str(row["Ticker"])
                if on_row_select is not None:
                    on_row_select(row)
    except Exception:
        selected_ticker = None

    if show_panel:
        render_historical_detail_panel(
            df,
            universe_name=universe_name,
            key_prefix=f"{key_prefix}_hist",
            selected_ticker=selected_ticker,
        )

    return selected_ticker


def _fmt_number(val, *, decimals: int = 2, suffix: str = "") -> str:
    """Format a numeric cell for display, with em-dash fallback."""
    try:
        if val is None:
            return "—"
        if isinstance(val, str):
            s = val.strip()
            if not s or s in ("—", "-", "n/a", "NaN", "nan"):
                return "—"
            try:
                val = float(s.replace(",", "").rstrip("%"))
            except ValueError:
                return html.escape(s)
        if isinstance(val, float) and (val != val):  # NaN check
            return "—"
        return f"{float(val):,.{decimals}f}{suffix}"
    except Exception:
        return "—"


def _fmt_int(val) -> str:
    try:
        if val is None or (isinstance(val, float) and val != val):
            return "—"
        return f"{int(float(val)):,}"
    except (TypeError, ValueError):
        s = str(val).strip()
        return s if s else "—"


def _decision_color(decision: str) -> str:
    d = str(decision or "").upper()
    if "STRONG BUY" in d or "BUY" in d:
        return "#25d366"
    if "HOLD" in d or "WATCH" in d:
        return "#f0b429"
    if "AVOID" in d or "SELL" in d:
        return "#e05252"
    return "#7abeac"


def _render_pre_buy_research_card(row: pd.Series, *, raw_ticker: str) -> None:
    """Render a research summary card for the selected ticker — pre-buy checklist data.

    Shows decision/score block, growth, research links and the analyst section.
    Resilient to missing columns: skips fields that aren't in the row.
    """
    if row is None:
        return

    def _g(col: str, default=None):
        try:
            v = row.get(col, default)
        except Exception:
            v = default
        if isinstance(v, float) and (v != v):
            return default
        return v

    ticker_label = str(_g("Ticker", raw_ticker) or raw_ticker or "—")
    decision = str(_g("Decision", "—") or "—")
    matrix_note = str(_g("Matrix note", "") or "")
    composite = _g("Composite")
    score = _g("Score")
    rev_growth = _g("Rev growth %")
    sector = str(_g("Sector", "") or "")
    price = _g("Price")
    pe = _g("PE Ratio") if _g("PE Ratio") is not None else _g("PE")

    decision_color = _decision_color(decision)

    st.markdown(
        f"""
<div style="background:linear-gradient(135deg,#0f2a22 0%,#122f25 100%);
            border:1px solid #1a3b31; border-left:4px solid {decision_color};
            border-radius:14px; padding:18px 22px; margin:14px 0 10px 0;
            font-family:'IBM Plex Mono', monospace;">
  <div style="display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;">
    <div style="font-size:1.25rem; color:#e5f7ed; letter-spacing:0.5px;">
      🎯 Pre-buy research — <b>{html.escape(ticker_label)}</b>
    </div>
    {f"<div style='color:#7abeac; font-size:0.82rem;'>{html.escape(sector)}</div>" if sector else ""}
  </div>
  <div style="display:flex; gap:18px; margin-top:10px; flex-wrap:wrap; font-size:0.82rem;">
    <div><span style="color:#7abeac;">DECISION&nbsp;</span>
         <b style="color:{decision_color};">{html.escape(decision)}</b></div>
    <div><span style="color:#7abeac;">COMPOSITE&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(composite, decimals=1)}</b></div>
    <div><span style="color:#7abeac;">SCORE&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(score, decimals=1)}</b></div>
    <div><span style="color:#7abeac;">REV GROWTH&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(rev_growth, decimals=2, suffix='%')}</b></div>
    <div><span style="color:#7abeac;">PRICE&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(price, decimals=2)}</b></div>
    <div><span style="color:#7abeac;">PE&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(pe, decimals=1)}</b></div>
  </div>
  {("<div style='margin-top:10px; color:#a3d8b8; font-size:0.82rem; line-height:1.45;'>"
    "<span style='color:#7abeac;'>📋 Matrix note&nbsp;</span>" + html.escape(matrix_note) + "</div>") if matrix_note else ""}
</div>
""",
        unsafe_allow_html=True,
    )

    # Research links — clickable chips
    link_pairs = [
        ("📊 Yahoo Finance", _g("Yahoo Finance", "")),
        ("🔎 Google Finance", _g("Google Finance", "")),
        ("📈 Moneycontrol", _g("Moneycontrol", "")),
        ("📈 MarketWatch", _g("MarketWatch", "")),
        ("📉 TradingView", _g("TradingView", "")),
    ]
    chips = "".join(
        (
            f"<a href='{html.escape(str(url))}' target='_blank' rel='noopener' "
            "style='display:inline-block; margin:4px 8px 4px 0; padding:6px 12px; "
            "background:#1a3b31; color:#25d366; text-decoration:none; "
            "border-radius:8px; font-family:\"IBM Plex Mono\", monospace; "
            "font-size:0.78rem; border:1px solid #25d36644;'>"
            f"{html.escape(label)} ↗</a>"
        )
        for label, url in link_pairs
        if url and str(url).strip()
    )
    if chips:
        st.markdown(
            f"<div style='margin:2px 0 14px 0;'>"
            f"<span style='color:#7abeac; font-family:\"IBM Plex Mono\",monospace; "
            f"font-size:0.78rem; margin-right:8px;'>🔗 RESEARCH&nbsp;</span>{chips}</div>",
            unsafe_allow_html=True,
        )

    # Analyst section — only show if any analyst column is populated
    analyst_consensus = _g("Analyst consensus")
    analyst_mean = _g("Analyst mean (1-5)")
    analyst_count = _g("Analyst count")
    target_mean = _g("Analyst target mean")
    upside_pct = _g("Upside to target %")
    ratings_mix = str(_g("Analyst ratings mix", "") or "")
    recommendation = str(_g("Analyst recommendation", "") or "")

    has_analyst = any(
        v not in (None, "", "—") for v in (analyst_consensus, analyst_mean, analyst_count, target_mean, upside_pct)
    ) or bool(ratings_mix) or (recommendation and recommendation != "—")

    if not has_analyst:
        return

    upside_color = "#25d366"
    try:
        if upside_pct is not None and float(upside_pct) < 0:
            upside_color = "#e05252"
    except (TypeError, ValueError):
        pass

    st.markdown(
        f"""
<div style="background:#0f2a22; border:1px solid #1a3b31; border-radius:12px;
            padding:14px 18px; margin:4px 0 10px 0;
            font-family:'IBM Plex Mono', monospace;">
  <div style="color:#e5f7ed; font-size:0.95rem; margin-bottom:8px;">
    👥 Analyst consensus
  </div>
  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));
              gap:10px 18px; font-size:0.8rem;">
    <div><span style="color:#7abeac;">Consensus&nbsp;</span>
         <b style="color:#e5f7ed;">{html.escape(str(analyst_consensus) if analyst_consensus is not None else "—")}</b></div>
    <div><span style="color:#7abeac;">Mean (1-5)&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(analyst_mean, decimals=2)}</b></div>
    <div><span style="color:#7abeac;">Analysts&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_int(analyst_count)}</b></div>
    <div><span style="color:#7abeac;">Target mean&nbsp;</span>
         <b style="color:#e5f7ed;">{_fmt_number(target_mean, decimals=2)}</b></div>
    <div><span style="color:#7abeac;">Upside&nbsp;</span>
         <b style="color:{upside_color};">{_fmt_number(upside_pct, decimals=2, suffix='%')}</b></div>
  </div>
  {("<div style='margin-top:10px; color:#a3d8b8; font-size:0.78rem; line-height:1.45;'>"
    "<span style='color:#7abeac;'>📊 Ratings mix&nbsp;</span>" + html.escape(ratings_mix) + "</div>") if ratings_mix else ""}
  {("<div style='margin-top:6px; color:#a3d8b8; font-size:0.78rem; line-height:1.45;'>"
    "<span style='color:#7abeac;'>📝 Recommendation&nbsp;</span>" + html.escape(recommendation) + "</div>") if recommendation and recommendation != "—" else ""}
</div>
""",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=600)
def _cached_period_history(raw_ticker: str, period: str) -> Optional[pd.DataFrame]:
    """Yahoo Finance daily history for a given period code. Cached 10 min."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        stk = yf.Ticker(raw_ticker)
        df = stk.history(period=period, interval="1d", auto_adjust=True)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def render_progressive_history_chart(
    raw_ticker: str,
    *,
    display_ticker: str = "",
    key: str = "progchart",
    default_period_label: str = "1Y",
) -> None:
    """Yahoo-Finance-like progressive chart: range pills, area line, 50/200-DMA, range slider."""
    if not raw_ticker:
        return
    label = display_ticker or raw_ticker

    periods = [
        ("1mo", "1M"),
        ("3mo", "3M"),
        ("6mo", "6M"),
        ("1y", "1Y"),
        ("2y", "2Y"),
        ("5y", "5Y"),
        ("max", "MAX"),
    ]
    period_labels = [lbl for _, lbl in periods]
    try:
        default_idx = period_labels.index(default_period_label)
    except ValueError:
        default_idx = 3

    st.markdown(
        f"<div style='font-family:IBM Plex Mono, monospace; font-size:1.05rem; "
        f"color:#25d366; margin: 6px 0;'>📈 {html.escape(label)} — interactive chart "
        f"<span style='color:#7abeac; font-size:0.78rem;'>({html.escape(raw_ticker)})</span></div>",
        unsafe_allow_html=True,
    )
    selected = st.radio(
        "Range",
        period_labels,
        index=default_idx,
        horizontal=True,
        key=f"{key}_period",
        label_visibility="collapsed",
    )
    period_value = next(p for p, lbl in periods if lbl == selected)

    hist = _cached_period_history(raw_ticker, period_value)
    if hist is None or hist.empty:
        st.warning(f"No Yahoo Finance history available for **{raw_ticker}** at range **{selected}**.")
        return

    closes = hist["Close"].astype(float)
    start_px = float(closes.iloc[0])
    end_px = float(closes.iloc[-1])
    ret_pct = (end_px / start_px - 1.0) * 100.0 if start_px > 0 else 0.0
    period_high = float(closes.max())
    period_low = float(closes.min())
    drawdown_from_high = (1.0 - end_px / period_high) * 100.0 if period_high > 0 else 0.0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Price", f"{end_px:,.2f}")
    m2.metric(f"{selected} return", f"{ret_pct:+.2f}%")
    m3.metric(f"{selected} high", f"{period_high:,.2f}")
    m4.metric(f"{selected} low", f"{period_low:,.2f}")
    m5.metric("↓ from high", f"-{drawdown_from_high:.1f}%")

    if go is None:
        st.line_chart(closes)
        return

    color = "#25d366" if ret_pct >= 0 else "#e05252"
    fill = "rgba(37, 211, 102, 0.18)" if ret_pct >= 0 else "rgba(224, 82, 82, 0.18)"

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hist.index,
            y=closes,
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=fill,
            name="Close",
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:,.2f}</b><extra></extra>",
        )
    )

    if len(closes) >= 50:
        ma50 = closes.rolling(50).mean()
        fig.add_trace(
            go.Scatter(
                x=hist.index,
                y=ma50,
                mode="lines",
                line=dict(color="#f0b429", width=1.2, dash="dot"),
                name="50-DMA",
                hovertemplate="50-DMA: %{y:,.2f}<extra></extra>",
            )
        )
    if len(closes) >= 200:
        ma200 = closes.rolling(200).mean()
        fig.add_trace(
            go.Scatter(
                x=hist.index,
                y=ma200,
                mode="lines",
                line=dict(color="#4db8ff", width=1.2, dash="dash"),
                name="200-DMA",
                hovertemplate="200-DMA: %{y:,.2f}<extra></extra>",
            )
        )

    # Anchor a y-axis range that doesn't drop to 0 (area fills stay readable).
    y_pad = max((period_high - period_low) * 0.10, 0.01)
    y_min = max(0.0, period_low - y_pad)
    y_max = period_high + y_pad

    fig.update_layout(
        template="plotly_white",
        height=420,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        xaxis=dict(
            rangeslider=dict(visible=True, thickness=0.06),
            type="date",
            showgrid=True,
            gridcolor="#eef2f7",
        ),
        yaxis=dict(
            title="Price",
            range=[y_min, y_max],
            showgrid=True,
            gridcolor="#eef2f7",
        ),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{key}_plot")

    # Volume sub-chart (cleaner separately so the price area stays prominent).
    if "Volume" in hist.columns and hist["Volume"].notna().any():
        vol_fig = go.Figure(
            go.Bar(
                x=hist.index,
                y=hist["Volume"].astype(float),
                marker_color="#7abeac",
                name="Volume",
                hovertemplate="%{x|%d %b %Y}<br>Volume: %{y:,.0f}<extra></extra>",
            )
        )
        vol_fig.update_layout(
            template="plotly_white",
            height=150,
            margin=dict(l=10, r=10, t=10, b=10),
            showlegend=False,
            xaxis=dict(type="date", showgrid=False),
            yaxis=dict(title="Volume", gridcolor="#eef2f7"),
        )
        st.plotly_chart(vol_fig, use_container_width=True, key=f"{key}_vol")

    summary = pd.DataFrame(
        {
            "Start date": [hist.index[0].strftime("%d %b %Y")],
            "End date": [hist.index[-1].strftime("%d %b %Y")],
            "Bars": [int(len(hist))],
            "Start price": [round(start_px, 2)],
            "End price": [round(end_px, 2)],
            "Return %": [round(ret_pct, 2)],
            f"{selected} high": [round(period_high, 2)],
            f"{selected} low": [round(period_low, 2)],
            "Avg volume": [
                int(hist["Volume"].mean()) if "Volume" in hist.columns and hist["Volume"].notna().any() else None
            ],
        }
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)
    st.caption(
        f"Source: Yahoo Finance ({raw_ticker}) · adjusted daily closes · "
        f"50/200-DMA overlays are computed on the visible range."
    )


def signal_results_download(
    results: list[SignalResult],
    scenario_id: str,
    button_key: str = "dl",
    *,
    include_scenario: bool = False,
    include_analyst: bool = True,
    include_history: bool = True,
) -> None:
    if not results:
        return
    ensure_scan_results_news(results)
    if (include_analyst or include_history) and len(results) > 50:
        st.warning(
            "Yahoo analyst/history columns skipped — more than 50 matches (rate limits). "
            "Narrow the scan or disable extras."
        )
        include_analyst = False
        include_history = False
    rows = []
    for r in results:
        decision, composite, matrix_note = _decision_for_signal_result(r)
        links = r.links or {}
        row = {
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "First_seen": first_seen_label(r.raw_ticker),
            "Interval": r.data_interval,
            "Sector": r.sector or "",
            "Signal": r.signal_label,
            "Decision": decision,
            "Composite": composite if composite == composite else None,
            "Matrix note": matrix_note,
            "Price": r.price,
            "PE": r.pe,
            "Vol×": r.vol_ratio,
            "RSI": r.rsi,
            "MACD_hist": r.macd_hist,
            "% vs MA20": r.pct_vs_ma20,
            "MA20x50_cross": r.golden_cross_recent,
            "%B_BB": r.bb_pct_b,
            "ATR14": r.atr14,
            "Next_Earnings": r.next_earnings or "",
            "Days_to_earn": r.days_to_earnings if r.days_to_earnings is not None else "",
            "Weekly_OK": r.weekly_confirm_buy,
            "Weekly_MACD_OK": r.weekly_macd_bullish,
            "RSI_bull_div": r.rsi_bullish_div,
            "RSI_bear_div": r.rsi_bearish_div,
            "Stoch_K": r.stoch_k,
            "Stoch_D": r.stoch_d,
            "RS20_vs_idx": r.rel_strength_20d,
            "VWAP_pct": r.price_vs_vwap_pct,
            "News_tone": r.news_sentiment or "",
            SCAN_RESULTS_NEWS_COL: format_recent_news_cell(r.news_headlines)
            if r.news_headlines
            else "—",
            "NSE_flow_note": r.nse_flow_note or "",
            "Entry": r.entry,
            "Stop": r.stop_loss,
            "T2": r.target2,
            "Confidence": r.confidence,
            # Research / chart deep links — clickable in Excel/Sheets and the in-app table.
            "Yahoo Finance": links.get("Yahoo Finance", ""),
            "Google Finance": links.get("Google Finance", ""),
            "Moneycontrol": links.get("Moneycontrol", ""),
            "MarketWatch": links.get("MarketWatch", ""),
            "TradingView": links.get("TradingView", ""),
        }
        if include_scenario:
            row = {
                "Ticker": row["Ticker"],
                "Scenario": scenario_display_title(r.scenario_id),
                **{k: v for k, v in row.items() if k != "Ticker"},
            }
        rows.append(row)
    df = pd.DataFrame(rows)
    if "First_seen" in df.columns:
        df = df.rename(columns={"First_seen": "First seen"})
    mkt = "NSE"
    if results and not any(
        str(getattr(r, "raw_ticker", "")).upper().endswith((".NS", ".BO")) for r in results
    ):
        mkt = "US"
    if not df.empty:
        df = prepare_scan_results_df(
            df,
            market=mkt,
            cache_key_prefix=f"csv_{scenario_id}_{button_key}",
            raw_ticker_col="Raw",
        )
    if (include_analyst or include_history) and not df.empty:
        try:
            from screener import enrich_dataframe_yahoo_context
        except ImportError:
            from .screener import enrich_dataframe_yahoo_context  # type: ignore[attr-defined]
        cache_key = (
            f"csv_yahoo_{scenario_id}_{button_key}_{include_analyst}_{include_history}_"
            f"{hash(tuple(df['Raw'].astype(str).tolist()))}"
        )
        if cache_key not in st.session_state:
            with st.spinner("Fetching Yahoo analyst + historical data for CSV…"):
                st.session_state[cache_key] = enrich_dataframe_yahoo_context(
                    df,
                    ticker_col="Ticker",
                    raw_ticker_col="Raw",
                    include_analyst=include_analyst,
                    include_history=include_history,
                )
        df = st.session_state[cache_key]
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇ Download results CSV",
        csv,
        file_name=f"stocksight_{scenario_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"{button_key}_csv_{scenario_id}",
    )


# ─────────────────────────────────────────────
# Scenario header banner
# ─────────────────────────────────────────────

def scenario_header(scenario_id: str):
    s = SCENARIOS[scenario_id]
    signal_colors = {
        "BUY":           ("#00e5a0", "#0a2e1e"),
        "SELL":          ("#ff4d4d", "#2e0a0a"),
        "CAUTIOUS BUY":  ("#ff9d42", "#2e1a00"),
        "WAIT":          ("#a0a0a0", "#1a1a1a"),
    }
    sig   = s["signal"]
    fc, bc = signal_colors.get(sig, ("#ffffff", "#1a1a1a"))

    # Use st.html so indented markup is not parsed as a Markdown code block.
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {s["color"]};
                border-radius:8px; padding:20px 24px; margin-bottom:20px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{s["emoji"]}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{html.escape(s["title"])}</div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:3px;'>
                    {html.escape(s["description"])}
                </div>
            </div>
            <div style='margin-left:auto;
                        background:{bc}; border:1px solid {fc};
                        border-radius:20px; padding:5px 16px;
                        font-family:"IBM Plex Mono",monospace;
                        font-size:0.78rem; font-weight:700; color:{fc};
                        white-space:nowrap;'>
                {html.escape(sig)}
            </div>
        </div>
        <div style='display:flex; gap:24px; margin-top:14px; flex-wrap:wrap;'>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Entry Trigger</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{html.escape(s["entry_note"])}</div>
            </div>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Stop Loss</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{html.escape(s["sl_note"])}</div>
            </div>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Targets</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{html.escape(s["target_note"])}</div>
            </div>
        </div>
    </div>
    """)
    audience = s.get("audience")
    purpose = s.get("purpose")
    if audience and purpose:
        page_audience_note(audience, purpose)


# ─────────────────────────────────────────────
# Trade plan card — one card per stock
# ─────────────────────────────────────────────

def trade_plan_card(
    r: SignalResult,
    scenario_id: str,
    portfolio_value: float = 0.0,
    risk_pct: float = 1.0,
):
    s       = SCENARIOS[scenario_id]
    color   = s["color"]
    is_sell = r.signal_label in ("SELL / AVOID", "SELL")
    is_wait = r.signal_label in ("HOLD / WAIT", "WAIT")

    conf_color = {"HIGH": "#25d366", "MEDIUM": "#f0b429", "LOW": "#e05252"}.get(r.confidence, "#a0a0a0")

    # Candle flags
    candle_html = ""
    if r.is_green:
        candle_html += '<span style="color:#25d366; font-size:0.72rem;">● Green candle</span> &nbsp;'
    if r.reversal:
        candle_html += '<span style="color:#25d366; font-size:0.72rem;">↑ Reversal</span> &nbsp;'
    if r.rsi_rising:
        candle_html += f'<span style="color:#4db8ff; font-size:0.72rem;">RSI rising ({r.rsi_prev}→{r.rsi})</span>'
    else:
        candle_html += f'<span style="color:#ff9d42; font-size:0.72rem;">RSI flat/falling ({r.rsi_prev}→{r.rsi})</span>'

    macd_part = "—"
    if r.macd_hist is not None:
        macd_part = f"{r.macd_hist:.4f}"
    ma_part = "—"
    if r.pct_vs_ma20 is not None:
        ma_part = f"{r.pct_vs_ma20:+.1f}%"
        if r.golden_cross_recent:
            ma_part += " · MA20×50"
    bb_part = "—"
    if r.bb_pct_b is not None:
        bb_part = f"{r.bb_pct_b:.2f}"
        if r.bb_touch_lower:
            bb_part += " · near lower"
    atr_part = "—"
    if r.atr14 is not None:
        atr_part = f"{r.atr14:.4f}"

    sector_part = html.escape(r.sector) if r.sector else "—"
    earn_part = html.escape(r.next_earnings) if r.next_earnings else "—"
    interval_part = html.escape(r.data_interval or "1d")

    if r.weekly_confirm_buy is True:
        wk_txt = "✓ Weekly aligned"
    elif r.weekly_confirm_buy is False:
        wk_txt = "✗ Weekly weak"
    else:
        wk_txt = "Weekly n/a"

    if r.weekly_macd_bullish is True:
        wkm = "✓ W MACD+"
    elif r.weekly_macd_bullish is False:
        wkm = "✗ W MACD−"
    else:
        wkm = "W MACD n/a"

    stoch_txt = "—"
    if r.stoch_k is not None and r.stoch_d is not None:
        stoch_txt = f"{r.stoch_k:.1f}/{r.stoch_d:.1f}"
        if r.stoch_cross_up:
            stoch_txt += " · X↑"
        if r.stoch_cross_down:
            stoch_txt += " · X↓"

    rs_txt = "—"
    if r.rel_strength_20d is not None:
        bench_lbl = (r.benchmark_sym or "").replace("^", "")
        rs_txt = f"{r.rel_strength_20d:+.1f} pp vs {bench_lbl or 'idx'}"

    vwap_txt = "—"
    if r.vwap_last is not None and r.price_vs_vwap_pct is not None:
        vwap_txt = f"{r.price_vs_vwap_pct:+.1f}% vs VWAP"

    nse_txt = html.escape(r.nse_flow_note) if r.nse_flow_note else "—"

    fs_txt = html.escape(first_seen_label(r.raw_ticker))

    sent_html = ""
    if r.news_sentiment:
        pal = {"bullish": "#25d366", "bearish": "#ff6b6b", "neutral": "#a0a0a0"}.get(r.news_sentiment, "#a0a0a0")
        sent_html = (
            "<div style='margin-top:8px;font-size:0.72rem;color:#b8e7c7;'>"
            f"<span style='color:{pal};font-weight:700;'>News sentiment:</span> "
            f"{html.escape(str(r.news_sentiment).upper())}"
            "</div>"
        )
    div_bits = []
    if r.rsi_bullish_div:
        div_bits.append("Bull div")
    if r.rsi_bearish_div:
        div_bits.append("Bear div")
    div_txt = html.escape(" · ".join(div_bits) if div_bits else "—")

    dte = r.days_to_earnings
    dte_txt = html.escape(f"{dte}d" if dte is not None else "—")

    earn_warn_html = ""
    if dte is not None and 0 <= dte <= 14:
        earn_warn_html = (
            "<div style='margin-top:8px;color:#ffb020;font-size:0.72rem;font-weight:600;'>"
            f"⚠ Event risk: earnings in <b>{html.escape(str(dte))}</b> day(s)."
            "</div>"
        )

    extras_html = f"""
        <div style='margin-top:10px; padding-top:8px; border-top:1px dashed #1a3b31;
                    font-family:"IBM Plex Mono",monospace; font-size:0.72rem; color:#b8e7c7; line-height:1.7;'>
            <span style='color:#a3d8b8;'>Bars</span> {interval_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Sector</span> {sector_part}<br>
            <span style='color:#a3d8b8;'>First seen</span> {fs_txt}<br>
            <span style='color:#a3d8b8;'>MACD hist</span> {macd_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>% vs MA20</span> {ma_part}<br>
            <span style='color:#a3d8b8;'>%B</span> {bb_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>ATR14</span> {atr_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Earnings</span> {earn_part}<br>
            <span style='color:#a3d8b8;'>Weekly MTF</span> {html.escape(wk_txt)}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>W MACD</span> {html.escape(wkm)}<br>
            <span style='color:#a3d8b8;'>RSI div</span> {div_txt}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Δ earnings</span> {dte_txt}<br>
            <span style='color:#a3d8b8;'>Stoch %K/%D</span> {html.escape(stoch_txt)}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>RS vs idx</span> {html.escape(rs_txt)}<br>
            <span style='color:#a3d8b8;'>VWAP</span> {html.escape(vwap_txt)}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>NSE flows</span> {nse_txt}
        </div>
        {earn_warn_html}
        {sent_html}
        """

    sizing_html = ""
    rp = float(risk_pct) if risk_pct and risk_pct > 0 else 1.0
    if not is_sell and not is_wait and portfolio_value and portfolio_value > 0:
        risk_per_share = abs(float(r.price) - float(r.stop_loss))
        if risk_per_share > 0:
            budget = float(portfolio_value) * (rp / 100.0)
            qty = int(budget // risk_per_share)
            sizing_html = f"""
            <div style='margin-top:8px; font-size:0.72rem; color:#f0b429;
                        font-family:'IBM Plex Mono',monospace;'>
                Position sizing (~{rp:.2f}% portfolio risk): <b>{qty}</b> shares @ risk/share {html.escape(r.currency)}{risk_per_share:,.2f}
            </div>
            """

    fall_html = ""
    if r.fall_context:
        fall_html = f"""
        <div style='margin-top:10px; padding:10px 12px; background:#0a1e28;
                    border-left:3px solid #7ec8e3; border-radius:4px;
                    font-size:0.78rem; color:#c8d8e8; line-height:1.5;'>
            <span style='color:#7ec8e3; font-weight:700;'>Why it might have fallen</span><br>
            {html.escape(r.fall_context, quote=False)}
        </div>
        """

    news_html = ""
    if r.news_headlines:
        lis = "".join(f"<li style='margin:3px 0;'>{html.escape(t)}</li>" for t in r.news_headlines[:5])
        news_html = f"<div style='margin-top:10px;font-size:0.72rem;color:#c8d8e8;'><b>Headlines</b><ul style='margin:6px 0 0 18px;'>{lis}</ul></div>"
    if is_sell:
        levels_html = f"""
        <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #2e1414;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Entry (current)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#e8f7ef; font-weight:700;'>{r.currency}{r.entry:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T1 (−3%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff9d42; font-weight:600;'>{r.currency}{r.target1:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T2 (−7%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff4d4d; font-weight:600;'>{r.currency}{r.target2:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T3 (−12%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff4d4d; font-weight:600;'>{r.currency}{r.target3:,.2f}</div>
            </div>
        </div>
        """
    elif is_wait:
        levels_html = f"""
        <div style='background:#16352c; border:1px dashed #2a2a2a; border-radius:5px;
                    padding:10px 14px; margin-top:10px; font-size:0.78rem; color:#a3d8b8;'>
            ⏸️ Pre-calculated levels (activate only on confirmation)<br>
            <span style='color:#7abeac;'>Entry zone:</span> {r.currency}{r.entry:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>SL:</span> {r.currency}{r.stop_loss:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>T1:</span> {r.currency}{r.target1:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>T2:</span> {r.currency}{r.target2:,.2f}
        </div>
        """
    else:
        levels_html = f"""
        <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c3020;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Entry</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#e8f7ef; font-weight:700;'>{r.currency}{r.entry:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #2e1414;'>
                <div style='font-size:9px; color:#e05252; letter-spacing:1px;
                            text-transform:uppercase;'>Stop Loss</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff6b6b; font-weight:600;'>{r.currency}{r.stop_loss:,.2f}</div>
                <div style='font-size:9px; color:#a3d8b8; margin-top:2px;'>
                    Risk {r.risk_pct:.1f}%</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 1</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#7ed4a0; font-weight:600;'>{r.currency}{r.target1:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 2</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#25d366; font-weight:700;'>{r.currency}{r.target2:,.2f}</div>
                <div style='font-size:9px; color:#a3d8b8; margin-top:2px;'>
                    RRR {r.rrr:.1f}×</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 3</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#1aa34b; font-weight:700;'>{r.currency}{r.target3:,.2f}</div>
            </div>
        </div>
        """

    # Links — escape URLs (e.g. M&M.NS → & in query/path breaks raw HTML href attributes)
    links_html = " &nbsp;".join([
        f'<a href="{html.escape(url, quote=True)}" target="_blank" style="color:{color}; font-size:0.72rem; '
        f'text-decoration:none; border:1px solid {color}33; border-radius:4px; '
        f'padding:2px 8px;">{html.escape(name)} ↗</a>'
        for name, url in r.links.items()
    ])

    safe_ticker = html.escape(r.ticker)
    safe_note = html.escape(r.note, quote=False)

    # st.html: indented lines are not interpreted as Markdown code fences (unlike st.markdown).
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {color};
                border-radius:8px; padding:16px 18px; margin-bottom:14px;'>

        <div style='display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:8px;'>
            <div>
                <span style='font-family:"IBM Plex Mono",monospace; font-size:1.2rem;
                              font-weight:700; color:#e8f7ef;'>{safe_ticker}</span>
                <span style='font-family:"IBM Plex Mono",monospace; font-size:1.1rem;
                              color:#a3d8b8; margin-left:12px;'>{html.escape(r.currency)}{r.price:,.2f}</span>
            </div>
            <div style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                <span style='font-size:9px; background:{conf_color}22; border:1px solid {conf_color}55;
                              color:{conf_color}; border-radius:12px; padding:2px 10px;
                              font-weight:700; letter-spacing:1px;'>
                    {html.escape(r.confidence)} CONFIDENCE
                </span>
                <span style='font-size:9px; color:#a3d8b8; font-family:"IBM Plex Mono",monospace;'>
                    ⏱ {html.escape(r.timeframe)}
                </span>
            </div>
        </div>

        <div style='display:flex; gap:20px; margin-top:10px; flex-wrap:wrap;
                    font-family:"IBM Plex Mono",monospace; font-size:0.78rem;'>
            <span><span style='color:#a3d8b8;'>PE  </span>{r.pe:.1f}×</span>
            <span><span style='color:#a3d8b8;'>VOL </span>{r.vol_ratio:.2f}×&nbsp;avg</span>
            <span><span style='color:#a3d8b8;'>RSI </span>{r.rsi:.1f}</span>
        </div>

        <div style='margin-top:8px;'>{candle_html}</div>

        {extras_html}

        {levels_html}

        {sizing_html}

        {fall_html}

        {news_html}

        <div style='margin-top:12px; font-size:0.75rem; color:#7abeac;
                    border-top:1px solid #1a3b31; padding-top:8px;'>
            💡 {safe_note}
        </div>

        <div style='margin-top:10px;'>{links_html}</div>
    </div>
    """)

    uid = hashlib.md5(f"{scenario_id}|{r.raw_ticker}".encode("utf-8")).hexdigest()[:16]
    if st.button("★ Watchlist", key=f"wl_add_{uid}"):
        add_to_watchlist(r.raw_ticker)
        try:
            st.toast(f"Saved {r.ticker}", icon="★")
        except Exception:
            st.success(f"Saved {r.ticker}")

    render_chart_expander(r.raw_ticker, r.data_interval or "1d", uid)
# ─────────────────────────────────────────────
# Results table (compact summary)
# ─────────────────────────────────────────────

def results_table(
    results: list[SignalResult],
    scenario_id: str,
    *,
    include_scenario: bool = False,
    include_yahoo_context: bool = True,
) -> None:
    if not results:
        return

    ensure_scan_results_news(results)

    rows = []
    for r in results:
        row = {
            "Ticker":       r.ticker,
            "First seen":   first_seen_label(r.raw_ticker),
            "Signal":       r.signal_label,
            "Bars":         r.data_interval,
            "Sector":       r.sector or "—",
            "Price":        r.price,
            "PE":           r.pe,
            "Vol×":         r.vol_ratio,
            "RSI":          r.rsi,
            "MACD hist":    r.macd_hist if r.macd_hist is not None else None,
            "% vs MA20":    r.pct_vs_ma20 if r.pct_vs_ma20 is not None else None,
            "MA20×50":      "✓" if r.golden_cross_recent else "—",
            "%B":           r.bb_pct_b if r.bb_pct_b is not None else None,
            "ATR14":        r.atr14 if r.atr14 is not None else None,
            "Earnings":     r.next_earnings or "—",
            "ΔEarn(d)":    r.days_to_earnings if r.days_to_earnings is not None else None,
            "Weekly":      {True: "✓", False: "✗", None: "—"}[r.weekly_confirm_buy],
            "W MACD":      {True: "✓", False: "✗", None: "—"}[r.weekly_macd_bullish],
            "%K":          r.stoch_k,
            "%D":          r.stoch_d,
            "RS20":        r.rel_strength_20d,
            "VWAP %":      r.price_vs_vwap_pct,
            "News tone":   r.news_sentiment or "—",
            SCAN_RESULTS_NEWS_COL: format_recent_news_cell(r.news_headlines)
            if r.news_headlines
            else "—",
            "Bull div":    "✓" if r.rsi_bullish_div else "—",
            "Bear div":    "⚠" if r.rsi_bearish_div else "—",
            "RSI Rising":   "↑" if r.rsi_rising else "→/↓",
            "Green Candle": "✅" if r.is_green else "—",
            "Reversal":     "✅" if r.reversal  else "—",
            "Entry":        r.entry,
            "Stop Loss":    r.stop_loss,
            "Target 2":     r.target2,
            "Risk %":       r.risk_pct,
            "Confidence":   r.confidence,
        }
        if scenario_id == "healthy_dip":
            row["Drawdown %"] = r.drawdown_52w_pct
            row["Why it fell"] = (r.fall_context or "—")[:120]
        if include_scenario:
            row = {
                "Ticker": row["Ticker"],
                "Scenario": scenario_display_title(r.scenario_id),
                **{k: v for k, v in row.items() if k != "Ticker"},
            }
        rows.append(row)

    df = pd.DataFrame(rows)
    df["Raw"] = [r.raw_ticker for r in results]

    mkt = "NSE"
    if results and not any(
        str(getattr(r, "raw_ticker", "")).upper().endswith((".NS", ".BO")) for r in results
    ):
        mkt = "US"
    conf_map = build_scenario_confluence_map(df) if include_scenario else None
    df = prepare_scan_results_df(
        df,
        market=mkt,
        cache_key_prefix=f"scenario_{scenario_id}",
        raw_ticker_col="Raw",
        confluence_map=conf_map,
        sort_by_gate=True,
    )

    if include_yahoo_context and len(df) <= 50:
        try:
            from screener import enrich_dataframe_yahoo_context
        except ImportError:
            from .screener import enrich_dataframe_yahoo_context  # type: ignore[attr-defined]
        cache_key = f"table_yahoo_{scenario_id}_{hash(tuple(df['Raw'].astype(str).tolist()))}"
        if cache_key not in st.session_state:
            with st.spinner("Loading Yahoo historical + analyst columns…"):
                st.session_state[cache_key] = enrich_dataframe_yahoo_context(
                    df,
                    ticker_col="Ticker",
                    raw_ticker_col="Raw",
                    include_analyst=True,
                    include_history=True,
                )
        df = st.session_state[cache_key]

    link_cols_nse = ["Yahoo Finance", "Google Finance", "Moneycontrol", "TradingView"]
    link_cols_us  = ["Yahoo Finance", "Google Finance", "MarketWatch",  "TradingView"]

    # Add first available link set
    if results:
        for name, url in results[0].links.items():
            col_name = name
            df[col_name] = [r.links.get(name, "") for r in results]

    if GATE_COL in df.columns:
        render_quality_gate_legend(profile=detect_quality_gate_profile(df))

    col_cfg = {
        **_scan_table_news_column_config(),
        **stock_sight_column_config(),
        "Price":        st.column_config.NumberColumn("Price", format="%.2f"),
        "PE":           st.column_config.NumberColumn("PE", format="%.1f"),
        "Vol×":         st.column_config.NumberColumn("Vol×", format="%.2f"),
        "RSI":          st.column_config.NumberColumn("RSI", format="%.1f"),
        "MACD hist":    st.column_config.NumberColumn("MACD hist", format="%.4f"),
        "% vs MA20":    st.column_config.NumberColumn("% vs MA20", format="%.2f"),
        "%B":           st.column_config.NumberColumn("%B", format="%.3f"),
        "ATR14":        st.column_config.NumberColumn("ATR14", format="%.4f"),
        "ΔEarn(d)":     st.column_config.NumberColumn("ΔEarn(d)", format="%d"),
        "%K":           st.column_config.NumberColumn("%K", format="%.1f"),
        "%D":           st.column_config.NumberColumn("%D", format="%.1f"),
        "RS20":         st.column_config.NumberColumn("RS20", format="%.2f"),
        "VWAP %":       st.column_config.NumberColumn("VWAP %", format="%.2f"),
        "Entry":        st.column_config.NumberColumn("Entry", format="%.2f"),
        "Stop Loss":    st.column_config.NumberColumn("Stop", format="%.2f"),
        "Target 2":     st.column_config.NumberColumn("Target 2", format="%.2f"),
        "Risk %":       st.column_config.NumberColumn("Risk %", format="%.1f%%"),
    }
    # Link columns
    for name in (link_cols_nse + link_cols_us):
        if name in df.columns:
            col_cfg[name] = st.column_config.LinkColumn(name, display_text="Open ↗")

    for text_col in ("Analyst recommendation", "Historical snapshot", "Historical detail"):
        if text_col in df.columns:
            col_cfg[text_col] = st.column_config.TextColumn(text_col, width="large")

    gate_note = " · 🟢/🟡/🟠/🔴 = Quality Gate" if GATE_COL in df.columns else ""
    st.caption(f"💡 Click any row to load its interactive chart in the panel below.{gate_note}")
    table_arg = dataframe_gate_styler(df) if GATE_COL in df.columns else df
    table_event = st.dataframe(
        table_arg, use_container_width=True,
        column_config=filter_column_config(df, col_cfg),
        hide_index=True,
        height=min(500, 50 + len(df) * 38),
        selection_mode="single-row",
        on_select="rerun",
        key=f"{scenario_id}_results_table",
    )
    selected_ticker = None
    try:
        sel_rows = table_event.selection.rows  # type: ignore[union-attr]
        if sel_rows:
            row_idx = int(sel_rows[0])
            if 0 <= row_idx < len(df) and "Ticker" in df.columns:
                selected_ticker = str(df.iloc[row_idx]["Ticker"])
    except Exception:
        selected_ticker = None
    render_historical_detail_panel(
        df,
        key_prefix=f"{scenario_id}_tbl_hist",
        selected_ticker=selected_ticker,
    )
    render_decision_matrix_legend()


# ─────────────────────────────────────────────
# Empty / no-results state
# ─────────────────────────────────────────────

def no_results_state(scenario_id: str):
    s = SCENARIOS[scenario_id]
    st.html(f"""
    <div style='background:#122f25; border:1px dashed #1a3b31;
                border-radius:12px; padding:50px 40px; text-align:center;'>
        <div style='font-size:2.5rem; margin-bottom:14px;'>{html.escape(s["emoji"])}</div>
        <div style='font-family:"IBM Plex Mono",monospace; color:#7abeac; font-size:1rem;'>
            No stocks currently match the <b style='color:{s["color"]};'>{html.escape(s["title"])}</b> criteria.
        </div>
        <div style='color:#6a9d8a; font-size:0.8rem; margin-top:8px;'>
            Markets may not have triggered this pattern today — check again at market open or close.
        </div>
    </div>
    """)
