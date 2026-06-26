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

def _import_navigation_pages():
    """Load page callables — root shim first, direct file fallback for Cloud."""
    import importlib.util

    _NAV_NAMES = (
        "page_breakout_momentum",
        "page_buy_hold_avoid",
        "page_extreme_oversold",
        "page_algo_strategy_hub",
        "page_paper_trading",
        "page_intraday_autopilot",
        "page_intrabot",
        "page_gap_scanner",
        "page_icici_breeze_screener",
        "page_icici_positions",
        "page_high_profit_category_leader",
        "page_high_profit_duopoly",
        "page_high_profit_monopoly",
        "page_high_profit_platform",
        "page_high_profit_regulatory_moat",
        "page_intraday_guide",
        "page_intraday_screener",
        "page_news_scanner",
        "page_weekly_swing_ath",
        "page_longterm_ath",
        "page_ath_playbook",
        "page_stage2_momentum",
        "page_volume_gravity",
        "page_markov_regime",
        "page_central_brain",
        "page_niftyrisk",
        "page_multibagger",
        "page_popular_screens",
        "page_proven_multibaggers",
        "page_overbought_exit",
        "page_oversold_bounce",
        "page_portfolio",
        "page_finance_hub",
        "page_buyback_screener",
        "page_bulk_order",
        "page_nse_intraday_intel",
        "page_pre_investigation",
        "page_peter_lynch",
        "page_financially_free_swing",
        "page_volume_led_growth",
        "page_crisis_value",
        "page_valuation_rulebook",
        "page_earnings_surprise",
        "page_value_growth",
        "page_multibagger_patterns",
        "page_fast_movers",
        "page_btst_screener",
        "page_rsi_supertrend_audit",
        "page_scan_history",
        "page_stocksight",
        "page_value_technical",
        "page_healthy_dip",
        "page_live_nse_screener",
        "page_volume_no_confirm",
        "page_watchlist_cross_scan",
    )

    def _pick(mod: object) -> dict[str, object]:
        missing = [n for n in _NAV_NAMES if not hasattr(mod, n)]
        if missing:
            raise ImportError(
                f"navigation_pages missing: {', '.join(missing)} "
                f"(module file: {getattr(mod, '__file__', '?')})"
            )
        return {n: getattr(mod, n) for n in _NAV_NAMES}

    try:
        import navigation_pages as nav_mod  # noqa: WPS433

        return _pick(nav_mod)
    except ImportError:
        nav_path = _STOCKSIGHT_PKG / "navigation_pages.py"
        if not nav_path.is_file():
            raise
        spec = importlib.util.spec_from_file_location(
            "stocksight_navigation_pages_direct", nav_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load navigation spec: {nav_path}") from None
        direct = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(direct)
        return _pick(direct)


try:
    _nav = _import_navigation_pages()
    page_breakout_momentum = _nav["page_breakout_momentum"]
    page_buy_hold_avoid = _nav["page_buy_hold_avoid"]
    page_extreme_oversold = _nav["page_extreme_oversold"]
    page_algo_strategy_hub = _nav["page_algo_strategy_hub"]
    page_paper_trading = _nav["page_paper_trading"]
    page_intraday_autopilot = _nav["page_intraday_autopilot"]
    page_intrabot = _nav["page_intrabot"]
    page_gap_scanner = _nav["page_gap_scanner"]
    page_icici_breeze_screener = _nav["page_icici_breeze_screener"]
    page_icici_positions = _nav["page_icici_positions"]
    page_high_profit_category_leader = _nav["page_high_profit_category_leader"]
    page_high_profit_duopoly = _nav["page_high_profit_duopoly"]
    page_high_profit_monopoly = _nav["page_high_profit_monopoly"]
    page_high_profit_platform = _nav["page_high_profit_platform"]
    page_high_profit_regulatory_moat = _nav["page_high_profit_regulatory_moat"]
    page_intraday_guide = _nav["page_intraday_guide"]
    page_intraday_screener = _nav["page_intraday_screener"]
    page_news_scanner = _nav["page_news_scanner"]
    page_weekly_swing_ath = _nav["page_weekly_swing_ath"]
    page_longterm_ath = _nav["page_longterm_ath"]
    page_ath_playbook = _nav["page_ath_playbook"]
    page_stage2_momentum = _nav["page_stage2_momentum"]
    page_volume_gravity = _nav["page_volume_gravity"]
    page_markov_regime = _nav["page_markov_regime"]
    page_central_brain = _nav["page_central_brain"]
    page_niftyrisk = _nav["page_niftyrisk"]
    page_multibagger = _nav["page_multibagger"]
    page_popular_screens = _nav["page_popular_screens"]
    page_proven_multibaggers = _nav["page_proven_multibaggers"]
    page_overbought_exit = _nav["page_overbought_exit"]
    page_oversold_bounce = _nav["page_oversold_bounce"]
    page_portfolio = _nav["page_portfolio"]
    page_finance_hub = _nav["page_finance_hub"]
    page_buyback_screener = _nav["page_buyback_screener"]
    page_bulk_order = _nav["page_bulk_order"]
    page_nse_intraday_intel = _nav["page_nse_intraday_intel"]
    page_pre_investigation = _nav["page_pre_investigation"]
    page_peter_lynch = _nav["page_peter_lynch"]
    page_financially_free_swing = _nav["page_financially_free_swing"]
    page_volume_led_growth = _nav["page_volume_led_growth"]
    page_crisis_value = _nav["page_crisis_value"]
    page_valuation_rulebook = _nav["page_valuation_rulebook"]
    page_earnings_surprise = _nav["page_earnings_surprise"]
    page_value_growth = _nav["page_value_growth"]
    page_multibagger_patterns = _nav["page_multibagger_patterns"]
    page_fast_movers = _nav["page_fast_movers"]
    page_btst_screener = _nav["page_btst_screener"]
    page_rsi_supertrend_audit = _nav["page_rsi_supertrend_audit"]
    page_scan_history = _nav["page_scan_history"]
    page_stocksight = _nav["page_stocksight"]
    page_value_technical = _nav["page_value_technical"]
    page_healthy_dip = _nav["page_healthy_dip"]
    page_live_nse_screener = _nav["page_live_nse_screener"]
    page_volume_no_confirm = _nav["page_volume_no_confirm"]
    page_watchlist_cross_scan = _nav["page_watchlist_cross_scan"]
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
        st.Page(page_finance_hub, title="Finance Hub", icon="📊"),
        st.Page(page_buyback_screener, title="Buyback Screener", icon="💰"),
        st.Page(page_bulk_order, title="Bulk Order", icon="📦"),
        st.Page(page_pre_investigation, title="Pre-Investigation Links", icon="🔎"),
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
    "🛡️ Portfolio Risk": [
        st.Page(page_niftyrisk, title="NiftyRisk (VaR · Monte Carlo)", icon="🛡️"),
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
        st.Page(page_volume_led_growth, title="Volume-Led Growth", icon="📈"),
        st.Page(page_peter_lynch, title="Peter Lynch (PEG / GARP)", icon="🦉"),
        st.Page(page_valuation_rulebook, title="Valuation Rulebook", icon="🧮"),
        st.Page(page_earnings_surprise, title="Earnings Surprise", icon="💎"),
        st.Page(page_crisis_value, title="Crisis Value (Steady Earnings)", icon="🏦"),
    ],
    "📚 My Learning": [
        st.Page(page_multibagger_patterns, title="Multi-Bagger Patterns", icon="🚀"),
        st.Page(page_value_growth, title="Value Growth (P/E · EPS)", icon="📐"),
    ],
    "🤖 Algo Strategy": [
        st.Page(page_algo_strategy_hub, title="Algo Strategy Hub", icon="🤖"),
        st.Page(page_central_brain, title="Central Brain (TV → AI → Exchange)", icon="🧠"),
        st.Page(page_markov_regime, title="Markov Regime Screener", icon="🎲"),
        st.Page(page_intrabot, title="IntraBot Automation", icon="⚡"),
        st.Page(page_intraday_autopilot, title="Intraday Autopilot", icon="🛰️"),
        st.Page(page_paper_trading, title="Paper Trading", icon="📝"),
        st.Page(page_rsi_supertrend_audit, title="RSI + Supertrend", icon="🔬"),
    ],
    "⚡ Intraday": [
        st.Page(page_nse_intraday_intel, title="NSE Intraday Intel", icon="🧠"),
        st.Page(page_btst_screener, title="BTST Screener", icon="🌙"),
        st.Page(page_fast_movers, title="Fast Movers (live speed)", icon="⚡"),
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
        st.Page(page_financially_free_swing, title="Financially Free Swing", icon="💹"),
        st.Page(page_stage2_momentum, title="Stage 2 + VCP Screener", icon="🎯"),
        st.Page(page_volume_gravity, title="Volume Gravity (VWAP / POC)", icon="⚖️"),
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
