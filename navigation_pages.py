"""
Repo-root shim — re-exports page callables from stocksight/navigation_pages.py.

Streamlit Cloud imports this file as ``navigation_pages``; we must not replace
``sys.modules['navigation_pages']`` with a different module object (that breaks
``from navigation_pages import page_*``).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_PKG = _ROOT / "stocksight"
for _p in (str(_ROOT), str(_PKG)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_IMPL = _PKG / "navigation_pages.py"
_spec = importlib.util.spec_from_file_location("stocksight_navigation_pages_impl", _IMPL)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load navigation_pages from {_IMPL}")
_impl_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_impl_mod)

_this = sys.modules[__name__]
_exported: list[str] = []
for _name in dir(_impl_mod):
    if _name.startswith("page_"):
        setattr(_this, _name, getattr(_impl_mod, _name))
        _exported.append(_name)

__all__ = sorted(_exported)
