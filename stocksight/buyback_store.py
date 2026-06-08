"""Persist buyback opportunities (active + past)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from buyback import SAMPLE_OPPORTUNITIES, BuybackInputs, analyze_buyback

_STORE = Path(__file__).resolve().parent / ".buyback_opportunities.json"


def _inp_to_dict(inp: BuybackInputs) -> dict[str, Any]:
    return {
        "stock": inp.stock,
        "raw_ticker": inp.raw_ticker,
        "buyback_pct": inp.buyback_pct,
        "small_holder_holding_pct": inp.small_holder_holding_pct,
        "participation_pct": inp.participation_pct,
        "offer_type": inp.offer_type,
        "announcement_price": inp.announcement_price,
        "buyback_price": inp.buyback_price,
        "record_date": inp.record_date,
        "post_buyback_price": inp.post_buyback_price,
        "status": inp.status,
    }


def _dict_to_inp(d: dict[str, Any]) -> BuybackInputs:
    return BuybackInputs(
        stock=str(d.get("stock", "")),
        raw_ticker=str(d.get("raw_ticker", "")),
        buyback_pct=float(d.get("buyback_pct", 0)),
        small_holder_holding_pct=float(d.get("small_holder_holding_pct", 1)),
        participation_pct=float(d.get("participation_pct", 50)),
        offer_type=str(d.get("offer_type", "Tender")),
        announcement_price=float(d.get("announcement_price", 0)),
        buyback_price=float(d.get("buyback_price", 0)),
        record_date=str(d.get("record_date", "")),
        post_buyback_price=float(d.get("post_buyback_price", 0)),
        status=str(d.get("status", "active")),
    )


def load_opportunities() -> list[BuybackInputs]:
    if not _STORE.is_file():
        return list(SAMPLE_OPPORTUNITIES)
    try:
        with _STORE.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return [_dict_to_inp(x) for x in data]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    return list(SAMPLE_OPPORTUNITIES)


def save_opportunities(items: list[BuybackInputs]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    with _STORE.open("w", encoding="utf-8") as f:
        json.dump([_inp_to_dict(x) for x in items], f, indent=2)


def load_analyses() -> list:
    try:
        from screener import get_stock_links
    except ImportError:
        get_stock_links = lambda _: {}  # type: ignore

    out = []
    for inp in load_opportunities():
        links = get_stock_links(inp.raw_ticker) if inp.raw_ticker else {}
        out.append(analyze_buyback(inp, links=links))
    return out
