"""
StockSight entry — st.navigation with grouped sidebar (pages/ is not used).

Run from repo root: streamlit run Overview.py
"""
from __future__ import annotations

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
    page_overbought_exit,
    page_oversold_bounce,
    page_stocksight,
    page_value_technical,
    page_volume_no_confirm,
)
from stocksight.app import render_overview

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
    ],
    "📈 Strategy Modules": [
        st.Page(page_breakout_momentum, title="Breakout Momentum", icon="🚀"),
        st.Page(page_oversold_bounce, title="Oversold Bounce", icon="📉"),
        st.Page(page_extreme_oversold, title="Extreme Oversold", icon="⚡"),
        st.Page(page_value_technical, title="Value Technical", icon="💎"),
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
}

pg = st.navigation(NAV_PAGES, expanded=True)

with st.sidebar:
    st.markdown("---")
    st.caption(
        "📈 StockSight — pick a page above to run scans. "
        "Under **🎯 Decision Framework**, **9. Buy / Hold / Avoid** is the final decision layer "
        "(composite score, zones, and action rules) — use it last before acting. "
        "If the menu is truncated, use **View more** or expand the sidebar (**«**)."
    )

pg.run()
