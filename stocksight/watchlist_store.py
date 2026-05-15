"""
Persistent watchlist (JSON next to this package). Tickers stored as raw yfinance symbols.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WL_PATH = Path(__file__).resolve().parent / ".watchlist.json"


def _read_raw() -> list[dict[str, Any]]:
    if not WL_PATH.exists():
        return []
    try:
        with open(WL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_raw(rows: list[dict[str, Any]]) -> None:
    WL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WL_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def load_watchlist() -> list[dict[str, Any]]:
    return list(_read_raw())


def save_watchlist(rows: list[dict[str, Any]]) -> None:
    _write_raw(rows)


def add_to_watchlist(raw_ticker: str, note: str = "") -> None:
    raw_ticker = (raw_ticker or "").strip()
    if not raw_ticker:
        return
    rows = _read_raw()
    note = (note or "").strip()
    for r in rows:
        if r.get("raw_ticker") == raw_ticker:
            if note:
                r["note"] = note
            _write_raw(rows)
            return
    rows.append({"raw_ticker": raw_ticker, "note": note})
    _write_raw(rows)


def remove_from_watchlist(raw_ticker: str) -> None:
    raw_ticker = (raw_ticker or "").strip()
    if not raw_ticker:
        return
    rows = [r for r in _read_raw() if r.get("raw_ticker") != raw_ticker]
    _write_raw(rows)
