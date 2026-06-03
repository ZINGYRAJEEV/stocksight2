"""
Repo-root shim — loads stocksight/stocksight_page_loader.py (avoids self-import loop).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_IMPL = _ROOT / "stocksight" / "stocksight_page_loader.py"

_spec = importlib.util.spec_from_file_location("stocksight_page_loader_impl", _IMPL)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load page loader from {_IMPL}")
_impl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_impl)

exec_stocksight_page = _impl.exec_stocksight_page

# Prefer the real implementation if anything else imports stocksight_page_loader again.
sys.modules["stocksight_page_loader"] = _impl

__all__ = ["exec_stocksight_page"]
