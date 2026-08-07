"""
Checkpoint / resume for long Investment Course scans (e.g. full NSE).

Persists next_index + partial hits so Streamlit Cloud timeouts or browser
disconnects do not wipe progress. Mirror of the buyback offset-cursor idea,
but stores match rows so the UI can show partial results between chunks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from investment_course_screener import InvestmentCourseFilters, InvestmentCourseResult

PAGE_ID = "investment_course"
CHECKPOINT_PATH = Path(__file__).resolve().parent / ".invc_scan_checkpoint.json"

# Prefer chunked mode when universe is larger than this
CHUNK_THRESHOLD = 150
DEFAULT_CHUNK_SIZE = 100


def filters_fingerprint(flt: InvestmentCourseFilters) -> str:
    payload = asdict(flt)
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def result_to_dict(r: InvestmentCourseResult) -> dict[str, Any]:
    return asdict(r)


def result_from_dict(data: dict[str, Any]) -> InvestmentCourseResult:
    allowed = {f.name for f in fields(InvestmentCourseResult)}
    clean = {k: v for k, v in (data or {}).items() if k in allowed}
    return InvestmentCourseResult(**clean)


def load_checkpoint(page_id: str = PAGE_ID) -> Optional[dict[str, Any]]:
    if not CHECKPOINT_PATH.is_file():
        return None
    try:
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("page") != page_id:
            return None
        return data
    except Exception:
        return None


def save_checkpoint(
    *,
    universe: str,
    mode: str,
    filters_hash: str,
    next_index: int,
    total: int,
    hits: list[InvestmentCourseResult],
    page_id: str = PAGE_ID,
) -> None:
    payload = {
        "page": page_id,
        "universe": universe,
        "mode": mode,
        "filters_hash": filters_hash,
        "next_index": int(next_index),
        "total": int(total),
        "done": int(next_index) >= int(total),
        "hits": [result_to_dict(r) for r in hits],
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def clear_checkpoint(page_id: str = PAGE_ID) -> None:
    ck = load_checkpoint(page_id)
    if ck is None and not CHECKPOINT_PATH.is_file():
        return
    try:
        if CHECKPOINT_PATH.is_file():
            CHECKPOINT_PATH.unlink()
    except OSError:
        pass


def checkpoint_matches(
    ck: Optional[dict[str, Any]],
    *,
    universe: str,
    mode: str,
    filters_hash: str,
) -> bool:
    if not ck:
        return False
    return (
        ck.get("universe") == universe
        and ck.get("mode") == mode
        and ck.get("filters_hash") == filters_hash
        and not ck.get("done")
        and int(ck.get("next_index") or 0) < int(ck.get("total") or 0)
    )


def hits_from_checkpoint(ck: Optional[dict[str, Any]]) -> list[InvestmentCourseResult]:
    if not ck:
        return []
    out: list[InvestmentCourseResult] = []
    for row in ck.get("hits") or []:
        if isinstance(row, dict):
            try:
                out.append(result_from_dict(row))
            except Exception:
                continue
    return out


def merge_hits(
    prior: list[InvestmentCourseResult],
    new_hits: list[InvestmentCourseResult],
) -> list[InvestmentCourseResult]:
    seen: set[str] = set()
    out: list[InvestmentCourseResult] = []
    for r in list(prior) + list(new_hits):
        key = r.raw_ticker or r.ticker
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
