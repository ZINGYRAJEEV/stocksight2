"""Persist IntraBot day state, positions meta, and event log."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent.parent / ".intrabot_state.json"


def _today() -> str:
    return date.today().isoformat()


def _empty() -> dict[str, Any]:
    return {
        "version": 1,
        "trading_day": _today(),
        "kill_switch": False,
        "paper_trade": True,
        "daily_pnl_pct": 0.0,
        "halted": False,
        "markets": {
            "NSE": {"watchlist": [], "trades_today": 0, "regime": ""},
            "US": {"watchlist": [], "trades_today": 0, "regime": ""},
        },
        "trail_stops": {},
        "log": [],
        "runtime": {},
        "last_tick_at": None,
    }


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _empty()
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("trading_day") != _today():
            fresh = _empty()
            fresh["log"].append(
                {"at": _now(), "level": "info", "event": "new_trading_day", "message": "State reset"}
            )
            return fresh
        return st
    except Exception:
        return _empty()


def save_state(state: dict[str, Any]) -> None:
    state["last_tick_at"] = _now()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(
    state: dict[str, Any],
    event: str,
    message: str = "",
    *,
    level: str = "info",
    market: str = "",
    **extra: Any,
) -> None:
    row = {
        "at": _now(),
        "level": level,
        "event": event,
        "message": message,
        "market": market,
        **extra,
    }
    state.setdefault("log", []).append(row)
    state["log"] = state["log"][-1000:]


def set_runtime(state: dict[str, Any], **fields: Any) -> None:
    rt = dict(state.get("runtime") or {})
    rt.update(fields)
    rt["updated_at"] = _now()
    state["runtime"] = rt
