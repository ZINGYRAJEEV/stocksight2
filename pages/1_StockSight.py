"""Proxy page — real script lives in stocksight/pages (see repo root app entry)."""
import runpy
import sys
from pathlib import Path

_STOCKSIGHT = Path(__file__).resolve().parent.parent / "stocksight"
if str(_STOCKSIGHT) not in sys.path:
    sys.path.insert(0, str(_STOCKSIGHT))

runpy.run_path(str(_STOCKSIGHT / "pages" / "StockSight.py"), run_name="__main__")
