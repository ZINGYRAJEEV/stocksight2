"""Accountant-ready audit trail — append-only JSONL."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_STOCKSIGHT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_PATH = _STOCKSIGHT / ".central_brain_audit.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_audit(
    record: dict[str, Any],
    *,
    path: Optional[Path] = None,
) -> str:
    """Append one audit row; returns signal_id."""
    p = path or DEFAULT_AUDIT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = dict(record)
    row.setdefault("signal_id", str(uuid.uuid4()))
    row.setdefault("ts", _now_iso())
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return str(row["signal_id"])


def read_audit_tail(
    *,
    path: Optional[Path] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    p = path or DEFAULT_AUDIT_PATH
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))
