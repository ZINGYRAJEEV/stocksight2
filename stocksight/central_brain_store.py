"""Central Brain persistent state — daily trade counters, kill switch."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent / ".central_brain_state.json"


def _today() -> str:
    return date.today().isoformat()


def load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"trades_by_day": {}, "kill_switch": False, "last_signal_id": ""}
    try:
        with _STATE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("trades_by_day", {})
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"trades_by_day": {}, "kill_switch": False, "last_signal_id": ""}


def save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def trades_today(state: dict[str, Any]) -> int:
    return int((state.get("trades_by_day") or {}).get(_today(), 0))


def increment_trades_today(state: dict[str, Any]) -> int:
    day = _today()
    by_day = dict(state.get("trades_by_day") or {})
    by_day[day] = int(by_day.get(day, 0)) + 1
    state["trades_by_day"] = by_day
    save_state(state)
    return int(by_day[day])


def set_kill_switch(on: bool) -> None:
    st = load_state()
    st["kill_switch"] = bool(on)
    save_state(st)
