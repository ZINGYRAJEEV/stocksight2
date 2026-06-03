"""
Repo-root shim — loads navigation_pages from stocksight/ for Streamlit Cloud path quirks.
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

_impl = _PKG / "navigation_pages.py"
_spec = importlib.util.spec_from_file_location("navigation_pages", _impl)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load navigation_pages from {_impl}")
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("navigation_pages", _mod)
_spec.loader.exec_module(_mod)

for _name in dir(_mod):
    if _name.startswith("page_"):
        globals()[_name] = getattr(_mod, _name)
