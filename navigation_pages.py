"""Callables for st.Page — each loads a real page from stocksight/pages via stocksight_page_loader."""

from __future__ import annotations


def page_stocksight() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("StockSight.py")


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


def page_overbought_exit() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Overbought Exit.py")


def page_volume_no_confirm() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Volume No Confirm.py")


def page_buy_hold_avoid() -> None:
    from stocksight_page_loader import exec_stocksight_page

    exec_stocksight_page("Buy Hold Avoid.py")
