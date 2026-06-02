"""Persist intraday autopilot day state (watchlists, trades, kill switch)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent / ".intraday_autopilot_state.json"


def _today() -> str:
    return date.today().isoformat()


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "trading_day": _today(),
        "kill_switch": False,
        "markets": {
            "NSE": {"regime": "", "priority_watchlist": [], "trades_today": 0, "signals_today": []},
            "US": {"regime": "", "priority_watchlist": [], "trades_today": 0, "signals_today": []},
        },
        "daily_realized_pnl": 0.0,
        "log": [],
        "last_tick_at": None,
        "last_phase": {"NSE": "", "US": ""},
    }


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _empty_state()
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("trading_day") != _today():
            fresh = _empty_state()
            fresh["log"].append({"at": datetime.now(timezone.utc).isoformat(), "event": "new_trading_day"})
            return fresh
        return st
    except Exception:
        return _empty_state()


def save_state(state: dict[str, Any]) -> None:
    state["last_tick_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def append_log(state: dict[str, Any], event: str, **fields: Any) -> None:
    row = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    state.setdefault("log", []).append(row)
    state["log"] = state["log"][-500:]
