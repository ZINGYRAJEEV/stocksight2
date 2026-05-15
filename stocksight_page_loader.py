"""
Load a Streamlit page module from stocksight/pages on every run.
Used by repo-root pages/*.py proxies so the UI executes in-process (avoids blank pages).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_STOCKSIGHT = _REPO / "stocksight"


def exec_stocksight_page(filename: str) -> None:
    if str(_STOCKSIGHT) not in sys.path:
        sys.path.insert(0, str(_STOCKSIGHT))
    # Streamlit keeps the process alive; a previously imported `screener` may be
    # cached without newer symbols. Drop impl modules so the page script always
    # loads fresh code from disk.
    for _m in ("screener", "signals", "ui_components", "high_profit", "high_profit_ui", "high_profit_page"):
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
