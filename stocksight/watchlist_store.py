"""
Persistent watchlist (JSON next to this package). Tickers stored as raw yfinance symbols.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WL_PATH = Path(__file__).resolve().parent / ".watchlist.json"
ALERT_PREFS_PATH = Path(__file__).resolve().parent / ".alert_prefs.json"


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.setdefault("raw_ticker", "")
    out.setdefault("note", "")
    out.setdefault("alert_rsi_below", None)
    out.setdefault("alert_rsi_above", None)
    out.setdefault("alert_price_above", None)
    out.setdefault("alert_price_below", None)
    out.setdefault("entry_price", None)
    out.setdefault("qty", None)
    out.setdefault("entry_date", None)
    return out


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
    return [_normalize_row(dict(r)) for r in _read_raw()]


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


def upsert_watchlist_fields(raw_ticker: str, patch: dict[str, Any]) -> None:
    """Merge fields into an existing row or create a lightweight row."""
    raw_ticker = (raw_ticker or "").strip()
    if not raw_ticker:
        return
    rows = _read_raw()
    patch_clean = dict(patch)
    hit = False
    for r in rows:
        if r.get("raw_ticker") == raw_ticker:
            r.update(patch_clean)
            hit = True
            break
    if not hit:
        row = _normalize_row({"raw_ticker": raw_ticker})
        row.update(patch_clean)
        rows.append(row)
    _write_raw(rows)


def list_open_positions() -> list[dict[str, Any]]:
    """Rows that look like an active position (qty + entry price present)."""
    out = []
    for r in load_watchlist():
        q = r.get("qty")
        ep = r.get("entry_price")
        try:
            qv = float(q)
            epv = float(ep)
        except (TypeError, ValueError):
            continue
        if qv > 0 and epv > 0:
            out.append(r)
    return out


def remove_from_watchlist(raw_ticker: str) -> None:
    raw_ticker = (raw_ticker or "").strip()
    if not raw_ticker:
        return
    rows = [r for r in _read_raw() if r.get("raw_ticker") != raw_ticker]
    _write_raw(rows)


def load_alert_prefs() -> dict[str, Any]:
    """Persisted UI prefs for alerting (not per-symbol)."""
    default: dict[str, Any] = {"email_watchlist_alerts": False}
    if not ALERT_PREFS_PATH.exists():
        return dict(default)
    try:
        with open(ALERT_PREFS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "email_watchlist_alerts" in data:
            default["email_watchlist_alerts"] = bool(data["email_watchlist_alerts"])
    except Exception:
        pass
    return default


def set_email_watchlist_alerts(enabled: bool) -> None:
    cur = load_alert_prefs()
    cur["email_watchlist_alerts"] = bool(enabled)
    ALERT_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
