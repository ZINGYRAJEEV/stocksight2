"""Callables for st.Page — each loads a real page from stocksight/pages via stocksight_page_loader."""

from __future__ import annotations


def page_stocksight() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("StockSight.py")


def page_watchlist_cross_scan() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Watchlist Cross-Scan.py")


def page_scan_history() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Scan History.py")


def page_portfolio() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Portfolio.py")


def page_breakout_momentum() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Breakout Momentum.py")


def page_oversold_bounce() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Oversold Bounce.py")


def page_extreme_oversold() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Extreme Oversold.py")


def page_value_technical() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Value Technical.py")


def page_healthy_dip() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Healthy Dip.py")


def page_live_nse_screener() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Live NSE Screener.py")


def page_overbought_exit() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Overbought Exit.py")


def page_volume_no_confirm() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Volume No Confirm.py")


def page_buy_hold_avoid() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Buy Hold Avoid.py")


def page_high_profit_monopoly() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("High Profit Monopoly.py")


def page_high_profit_platform() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("High Profit Platform.py")


def page_high_profit_regulatory_moat() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("High Profit Regulatory Moat.py")


def page_high_profit_duopoly() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("High Profit Duopoly.py")


def page_high_profit_category_leader() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("High Profit Category Leader.py")


def page_multibagger() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Multibagger.py")


def page_proven_multibaggers() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Proven Multibaggers.py")


def page_popular_screens() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Popular Screens.py")
