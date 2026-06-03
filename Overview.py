"""
StockSight entry — st.navigation with grouped sidebar (pages/ is not used).

Run from repo root: streamlit run Overview.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_STOCKSIGHT_PKG = _REPO / "stocksight"
# Streamlit Cloud may only add stocksight/ to sys.path — put repo root first, then package dir.
for _p in (str(_STOCKSIGHT_PKG), str(_REPO)):
    if _p not in sys.path:
        sys.path.append(_p)
if str(_REPO) in sys.path:
    sys.path.remove(str(_REPO))
sys.path.insert(0, str(_REPO))
if str(_STOCKSIGHT_PKG) not in sys.path:
    sys.path.insert(1, str(_STOCKSIGHT_PKG))

import streamlit as st

try:
    from navigation_pages import (
        page_breakout_momentum,
        page_buy_hold_avoid,
        page_extreme_oversold,
        page_algo_strategy_hub,
        page_paper_trading,
        page_intraday_autopilot,
        page_intrabot,
        page_gap_scanner,
        page_icici_breeze_screener,
        page_icici_positions,
        page_high_profit_category_leader,
        page_high_profit_duopoly,
        page_high_profit_monopoly,
        page_high_profit_platform,
        page_high_profit_regulatory_moat,
        page_intraday_guide,
        page_intraday_screener,
        page_news_scanner,
        page_weekly_swing_ath,
        page_longterm_ath,
        page_ath_playbook,
        page_stage2_momentum,
        page_multibagger,
        page_popular_screens,
        page_proven_multibaggers,
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
except ImportError as _nav_err:
    st.error(
        "Failed to load navigation_pages. "
        f"Repo root on path: `{_REPO}`. Error: {_nav_err}"
    )
    raise

try:
    from stocksight.app import render_overview
except ImportError:
    from app import render_overview  # type: ignore[no-redef]

try:
    from stocksight.ui_components import inject_app_chrome
except ImportError:
    from ui_components import inject_app_chrome  # type: ignore[no-redef]

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
        st.Page(page_proven_multibaggers, title="Proven Multibaggers (500%+)", icon="🏆"),
    ],
    "🤖 Algo Strategy": [
        st.Page(page_algo_strategy_hub, title="Algo Strategy Hub", icon="🤖"),
        st.Page(page_intrabot, title="IntraBot Automation", icon="⚡"),
        st.Page(page_intraday_autopilot, title="Intraday Autopilot", icon="🛰️"),
        st.Page(page_paper_trading, title="Paper Trading", icon="📝"),
    ],
    "⚡ Intraday": [
        st.Page(page_gap_scanner, title="Gap Scanner (pre-market)", icon="🌅"),
        st.Page(page_intraday_screener, title="Intraday Screener (6 strategies)", icon="📡"),
        st.Page(page_icici_breeze_screener, title="ICICI Breeze Screener (live NSE)", icon="🟠"),
        st.Page(page_icici_positions, title="ICICI Positions & Orders", icon="📒"),
        st.Page(page_intraday_guide, title="Intraday Guide", icon="📚"),
    ],
    "🏔️ All-Time High (ATH)": [
        st.Page(page_weekly_swing_ath, title="Weekly Swing ATH", icon="🏔️"),
        st.Page(page_longterm_ath, title="Long-Term ATH", icon="🚀"),
        st.Page(page_ath_playbook, title="ATH Strategy Playbook", icon="📖"),
    ],
    "🎯 Stage 2 Momentum": [
        st.Page(page_stage2_momentum, title="Stage 2 + VCP Screener", icon="🎯"),
    ],
    "📰 News & Sentiment": [
        st.Page(page_news_scanner, title="News Scanner + Rulebook", icon="📰"),
    ],
}

inject_app_chrome()

pg = st.navigation(NAV_PAGES, expanded=True)

with st.sidebar:
    st.markdown("---")
    try:
        from breeze_data import (
            breeze_configured,
            breeze_status_message,
            login_url,
            update_session_token,
        )

        _bz_ok = breeze_configured()
        with st.expander(f"{'🟢' if _bz_ok else '🟠'} ICICI Breeze API", expanded=False):
            st.caption(breeze_status_message())
            if not _bz_ok:
                st.caption(
                    "For NSE/BSE charts via ICICI: register at "
                    "[Breeze API](https://api.icicidirect.com/apiuser/home), "
                    "`pip install breeze-connect`, then add `[breeze]` keys to "
                    "`.streamlit/secrets.toml`. Charts still use **Plotly**; Breeze supplies OHLC data."
                )
            else:
                st.caption(
                    "Session token **expires daily** — refresh it here without editing files "
                    "or restarting."
                )
                st.markdown(f"[**Log in to generate token →**]({login_url()})")
                _tok = st.text_input(
                    "Paste today's apisession token",
                    key="sidebar_breeze_token",
                    placeholder="e.g. 55806325",
                )
                if st.button("💾 Save & reconnect", key="sidebar_breeze_save"):
                    _ok, _msg = update_session_token(_tok)
                    (st.success if _ok else st.error)(_msg)
                    if _ok:
                        st.rerun()
    except Exception:
        pass
    st.caption(
        "📈 **Popular Screens** sits under the main screener for classic named filters. "
        "📰 **News Scanner + Rulebook** classifies headlines (Tier 1–4) and scans your intraday shortlist. "
        "**Buy / Hold / Avoid** is the final decision layer—use it after you have candidates. "
        "Expand the sidebar (**«**) if the menu is truncated."
    )

pg.run()
