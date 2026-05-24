"""
StockSight entry — st.navigation with grouped sidebar (pages/ is not used).

Run from repo root: streamlit run Overview.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_STOCKSIGHT_PKG = _REPO / "stocksight"
# Streamlit Cloud may not put the repo root on sys.path — navigation_pages and
# `from stocksight.*` both need it. Page scripts use flat imports from stocksight/.
for _p in (_REPO, _STOCKSIGHT_PKG):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import streamlit as st

from navigation_pages import (
    page_breakout_momentum,
    page_buy_hold_avoid,
    page_extreme_oversold,
    page_high_profit_category_leader,
    page_high_profit_duopoly,
    page_high_profit_monopoly,
    page_high_profit_platform,
    page_high_profit_regulatory_moat,
    page_multibagger,
    page_popular_screens,
    page_overbought_exit,
    page_oversold_bounce,
    page_portfolio,
    page_scan_history,
    page_stocksight,
    page_value_technical,
    page_healthy_dip,
    page_live_nse_screener,
    page_volume_no_confirm,
    page_watchlist_cross_scan,
)
from stocksight.app import render_overview
from stocksight.ui_components import inject_app_chrome

try:
    st.set_page_config(
        page_title="StockSight",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
except st.errors.StreamlitAPIException:
    pass

NAV_PAGES = {
    "": [
        st.Page(render_overview, title="Overview", icon="📊", default=True),
        st.Page(page_stocksight, title="StockSight (Main Screener)", icon="📈"),
        st.Page(page_live_nse_screener, title="Live NSE Screener", icon="📡"),
        st.Page(page_popular_screens, title="Popular Screens", icon="📋"),
        st.Page(page_watchlist_cross_scan, title="Watchlist Cross-Scan", icon="📌"),
        st.Page(page_scan_history, title="Scan History", icon="🗂️"),
        st.Page(page_portfolio, title="Portfolio", icon="💼"),
    ],
    "📈 Strategy Modules": [
        st.Page(page_breakout_momentum, title="Breakout Momentum", icon="🚀"),
        st.Page(page_oversold_bounce, title="Oversold Bounce", icon="📉"),
        st.Page(page_extreme_oversold, title="Extreme Oversold", icon="⚡"),
        st.Page(page_value_technical, title="Value Technical", icon="💎"),
        st.Page(page_healthy_dip, title="Healthy Dip", icon="🩺"),
    ],
    "📉 Risk & Exit Modules": [
        st.Page(page_overbought_exit, title="Overbought Exit", icon="🔴"),
        st.Page(page_volume_no_confirm, title="Volume No Confirm", icon="⏸️"),
    ],
    "🎯 Decision Framework": [
        st.Page(
            page_buy_hold_avoid,
            title="9. Buy / Hold / Avoid",
            icon="🎯",
        ),
    ],
    "⚖️ Risk-Based Scenarios": [
        st.Page(page_high_profit_regulatory_moat, title="Low Risk · Regulatory Moat", icon="🏛️"),
        st.Page(page_high_profit_monopoly, title="Low Risk · Monopoly", icon="👑"),
        st.Page(page_high_profit_duopoly, title="Medium Risk · Duopoly", icon="⚖️"),
        st.Page(page_high_profit_category_leader, title="Medium Risk · Category Leader", icon="🥇"),
        st.Page(page_high_profit_platform, title="High Risk · Platform", icon="🌐"),
    ],
    "🌱 Theme Screens": [
        st.Page(page_multibagger, title="Multibagger Theme", icon="🌱"),
    ],
}

inject_app_chrome()

pg = st.navigation(NAV_PAGES, expanded=True)

with st.sidebar:
    st.markdown("---")
    try:
        from breeze_data import breeze_configured, breeze_status_message

        with st.expander("ICICI Breeze API (optional)", expanded=False):
            st.caption(breeze_status_message())
            if not breeze_configured():
                st.caption(
                    "For NSE/BSE charts via ICICI: register at "
                    "[Breeze API](https://api.icicidirect.com/apiuser/home), "
                    "`pip install breeze-connect`, then add `[breeze]` keys to "
                    "`.streamlit/secrets.toml`. Charts still use **Plotly**; Breeze supplies OHLC data."
                )
    except Exception:
        pass
    st.caption(
        "📈 **Popular Screens** sits under the main screener for classic named filters. "
        "**Buy / Hold / Avoid** is the final decision layer—use it after you have candidates. "
        "Expand the sidebar (**«**) if the menu is truncated."
    )

pg.run()
