"""Load rules.json — single source of truth for strategy validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_rules(path: Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"rules.json not found: {p}")
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("rules.json must be a JSON object")
    return data


def side_rules(rules: dict[str, Any], action: str) -> dict[str, Any]:
    act = (action or "").strip().lower()
    if act in ("buy", "long", "entry"):
        return dict(rules.get("buy") or {})
    if act in ("sell", "short", "exit", "close"):
        return dict(rules.get("sell") or {})
    return {}
