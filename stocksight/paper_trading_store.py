"""Persistent paper-trading ledger (JSON). Separate from live broker / watchlist."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PAPER_PATH = Path(__file__).resolve().parent / ".paper_trading.json"

DEFAULT_STARTING_CASH_INR = 1_000_000.0
DEFAULT_STARTING_CASH_USD = 50_000.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_account(*, currency: str = "INR", starting_cash: float = DEFAULT_STARTING_CASH_INR) -> dict[str, Any]:
    return {
        "version": 1,
        "currency": currency,
        "starting_cash": float(starting_cash),
        "cash": float(starting_cash),
        "positions": [],
        "closed_trades": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def load_paper_account() -> dict[str, Any]:
    if not PAPER_PATH.exists():
        return _empty_account()
    try:
        with open(PAPER_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_account()
        data.setdefault("positions", [])
        data.setdefault("closed_trades", [])
        data.setdefault("cash", data.get("starting_cash", DEFAULT_STARTING_CASH_INR))
        return data
    except Exception:
        return _empty_account()


def save_paper_account(account: dict[str, Any]) -> None:
    account["updated_at"] = _now_iso()
    PAPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPER_PATH, "w", encoding="utf-8") as f:
        json.dump(account, f, indent=2)


def reset_paper_account(
    *,
    starting_cash: float = DEFAULT_STARTING_CASH_INR,
    currency: str = "INR",
) -> dict[str, Any]:
    acc = _empty_account(currency=currency, starting_cash=starting_cash)
    save_paper_account(acc)
    return acc


def _find_open_position(account: dict[str, Any], raw_ticker: str) -> Optional[dict[str, Any]]:
    raw = (raw_ticker or "").strip().upper()
    for p in account.get("positions", []):
        if str(p.get("raw_ticker", "")).strip().upper() == raw:
            return p
    return None
