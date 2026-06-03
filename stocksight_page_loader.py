"""Repo-root shim — delegates to stocksight/stocksight_page_loader.py."""
from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent / "stocksight"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from stocksight_page_loader import exec_stocksight_page  # noqa: F401

__all__ = ["exec_stocksight_page"]
