"""
Persist Tier 1 / Tier 2 shortlists so later tiers can scan the funnel.

Each successful Watchlist (Tier 1) scan overwrites the saved list.
Zero matches clears it so Strict does not use stale names.
Same pattern for Strict → Momentum.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FUNNEL_PATH = Path(__file__).resolve().parent / ".fundamental_funnel.json"

TIER_WATCHLIST = "watchlist"
TIER_STRICT = "strict"


def _empty() -> dict[str, Any]:
    return {TIER_WATCHLIST: None, TIER_STRICT: None}


def _read() -> dict[str, Any]:
    if not FUNNEL_PATH.is_file():
        return _empty()
    try:
        with open(FUNNEL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        out = _empty()
        for key in (TIER_WATCHLIST, TIER_STRICT):
            block = data.get(key)
            if isinstance(block, dict) and isinstance(block.get("tickers"), list):
                out[key] = block
        return out
    except Exception:
        return _empty()


def _write(data: dict[str, Any]) -> None:
    FUNNEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FUNNEL_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _rows_from_hits(hits: list[Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for r in hits or []:
        raw = str(getattr(r, "raw_ticker", "") or "").strip()
        if not raw:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        ticker = str(getattr(r, "ticker", "") or raw.replace(".NS", "").replace(".BO", ""))
        label = str(getattr(r, "label", "") or ticker)
        rows.append({"label": label, "ticker": ticker, "raw": raw})
    return rows


def save_tier_shortlist(
    tier: str,
    hits: list[Any],
    *,
    source_universe: str,
) -> None:
    """
    Refresh the saved shortlist for watchlist/strict.

    - Non-empty hits → overwrite with this scan
    - Empty hits → clear that tier's shortlist (avoid stale funnel)
    """
    if tier not in (TIER_WATCHLIST, TIER_STRICT):
        return
    data = _read()
    rows = _rows_from_hits(hits)
    if not rows:
        data[tier] = None
        _write(data)
        return
    data[tier] = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source_universe": source_universe,
        "count": len(rows),
        "tickers": rows,
    }
    _write(data)


def clear_tier_shortlist(tier: str) -> None:
    if tier not in (TIER_WATCHLIST, TIER_STRICT):
        return
    data = _read()
    data[tier] = None
    _write(data)


def clear_all_shortlists() -> None:
    _write(_empty())


def load_tier_shortlist(tier: str) -> Optional[dict[str, Any]]:
    if tier not in (TIER_WATCHLIST, TIER_STRICT):
        return None
    block = _read().get(tier)
    if not block or not block.get("tickers"):
        return None
    return block


def shortlist_as_universe(tier: str) -> list[tuple[str, str]]:
    """Return (label, raw_ticker) pairs for scan_fundamental_framework."""
    block = load_tier_shortlist(tier)
    if not block:
        return []
    out: list[tuple[str, str]] = []
    for row in block.get("tickers") or []:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("raw") or "").strip()
        if not raw:
            continue
        if not (raw.endswith(".NS") or raw.endswith(".BO")):
            raw = f"{raw}.NS"
        label = str(row.get("label") or row.get("ticker") or raw)
        out.append((label, raw))
    return out


def shortlist_summary(tier: str) -> str:
    block = load_tier_shortlist(tier)
    if not block:
        return "none saved"
    n = int(block.get("count") or len(block.get("tickers") or []))
    src = block.get("source_universe") or "—"
    updated = str(block.get("updated") or "")[:16].replace("T", " ")
    return f"{n} names · from {src} · {updated} UTC"
