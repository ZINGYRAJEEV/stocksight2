"""Track seen buyback announcement IDs for NEW badges."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_STORE = Path(__file__).resolve().parent / ".buyback_announcements_seen.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_seen() -> dict[str, str]:
    if not _STORE.is_file():
        return {}
    try:
        with _STORE.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_seen(seen: dict[str, str]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    with _STORE.open("w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2)


def mark_seen(ids: list[str]) -> dict[str, str]:
    seen = load_seen()
    now = _now_iso()
    for i in ids:
        if i and i not in seen:
            seen[i] = now
    save_seen(seen)
    return seen
