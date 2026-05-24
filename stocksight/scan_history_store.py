"""Append-only scan history (JSONL) — lightweight signal audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HISTORY_PATH = Path(__file__).resolve().parent / ".scan_history.jsonl"

_first_seen_cache_mtime: float = -1.0
_first_seen_cache_map: dict[str, str] = {}


def append_scan_record(
    page_id: str,
    universe: str,
    symbols: list[str],
    *,
    meta: dict[str, Any] | None = None,
) -> None:
    """Persist one scan snapshot (deduped raw symbols)."""
    global _first_seen_cache_mtime
    syms = sorted({str(s).strip() for s in symbols if str(s).strip()})
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "page": page_id,
        "universe": universe,
        "count": len(syms),
        "symbols": syms,
        "meta": meta or {},
    }
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    _first_seen_cache_mtime = -1.0


def read_recent_lines(limit: int = 200) -> list[dict[str, Any]]:
    """Tail-most JSON objects from the log (best-effort)."""
    if not _HISTORY_PATH.exists():
        return []
    try:
        lines = _HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
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


def build_first_seen_map() -> dict[str, str]:
    """
    Earliest calendar date (UTC prefix YYYY-MM-DD from record ts) each **raw** symbol
    appeared in history. File is processed top-to-bottom (append order ≈ chronological).
    Cached while `.scan_history.jsonl` mtime is unchanged.
    """
    global _first_seen_cache_mtime, _first_seen_cache_map
    if not _HISTORY_PATH.exists():
        _first_seen_cache_mtime = -1.0
        _first_seen_cache_map = {}
        return {}

    try:
        mt = float(_HISTORY_PATH.stat().st_mtime)
    except OSError:
        return dict(_first_seen_cache_map)

    if mt == _first_seen_cache_mtime and _first_seen_cache_map:
        return dict(_first_seen_cache_map)

    first: dict[str, str] = {}
    try:
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = str(rec.get("ts") or "")
                day = ts[:10] if len(ts) >= 10 else ""
                if not day:
                    continue
                syms = rec.get("symbols")
                if not isinstance(syms, list):
                    continue
                for sym in syms:
                    s = str(sym).strip()
                    if not s:
                        continue
                    if s not in first:
                        first[s] = day
    except Exception:
        first = {}

    _first_seen_cache_mtime = mt
    _first_seen_cache_map = first
    return dict(first)
