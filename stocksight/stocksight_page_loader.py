"""
Load a Streamlit page module from stocksight/pages on every run.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_STOCKSIGHT = Path(__file__).resolve().parent
_REPO = _STOCKSIGHT.parent


def exec_stocksight_page(filename: str) -> None:
    if str(_STOCKSIGHT) not in sys.path:
        sys.path.insert(0, str(_STOCKSIGHT))
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    for _m in (
        "screener",
        "signals",
        "ui_components",
        "scan_history_store",
        "watchlist_store",
        "email_alerts",
        "high_profit",
        "high_profit_ui",
        "high_profit_page",
        "multibagger",
        "multibagger_page",
        "popular_screens",
        "popular_screens_page",
        "intraday",
        "intraday_ranking",
        "intraday_page",
        "breeze_data",
        "scan_progress",
        "intraday_autopilot",
        "intraday_autopilot_page",
        "intraday_autopilot_store",
        "intrabot",
        "intrabot_page",
        "intrabot.config",
        "intrabot.engine",
        "intrabot.store",
        "paper_trading",
        "paper_trading_page",
        "paper_trading_store",
        "algo_selector",
        "algo_selector_page",
        "stage2_momentum",
        "stage2_momentum_page",
        "stage2_momentum_ui",
        "news_scanner",
        "news_scanner_page",
        "news_sources",
        "volume_gravity",
        "volume_gravity_page",
        "volume_gravity_ui",
    ):
        sys.modules.pop(_m, None)
    path = _STOCKSIGHT / "pages" / filename
    safe = path.stem.replace(" ", "_").replace("-", "_")
    mod_name = f"stocksight__page__{safe}"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load page spec: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
