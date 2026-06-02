"""
Paper trading engine — simulated buys/sells with local ledger and Yahoo MTM.

Educational only; not connected to NSE/broker. Pair with Algo Strategy Hub picks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import yfinance as yf

from paper_trading_store import (
    DEFAULT_STARTING_CASH_INR,
    DEFAULT_STARTING_CASH_USD,
    load_paper_account,
    reset_paper_account,
    save_paper_account,
)

try:
    from algo_selector import AlgoPick
except ImportError:
    AlgoPick = Any  # type: ignore[misc, assignment]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_last_price(raw_ticker: str) -> Optional[float]:
    raw = (raw_ticker or "").strip()
    if not raw:
        return None
    try:
        hist = yf.Ticker(raw).history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    try:
        info = yf.Ticker(raw).fast_info
        for key in ("last_price", "lastPrice", "regularMarketPrice"):
            v = getattr(info, key, None) if hasattr(info, key) else None
            if v is None and isinstance(info, dict):
                v = info.get(key)
            if v is not None and float(v) > 0:
                return float(v)
    except Exception:
        pass
    return None


def suggest_quantity(
    *,
    cash: float,
    entry: float,
    stop: Optional[float],
    risk_pct: float = 1.0,
    max_deploy_pct: float = 25.0,
) -> int:
    """Shares sized so risk ≈ risk_pct of cash (if stop provided)."""
    if entry <= 0 or cash <= 0:
        return 0
    qty_cap = int((cash * max_deploy_pct / 100.0) / entry)
    if stop is not None and stop > 0 and stop < entry:
        risk_per_share = entry - stop
        risk_budget = cash * (risk_pct / 100.0)
        qty_risk = int(risk_budget / risk_per_share)
        qty = min(qty_risk, qty_cap) if qty_cap > 0 else qty_risk
    else:
        qty = qty_cap
    return max(1, qty) if qty > 0 else 0


def paper_buy(
    *,
    raw_ticker: str,
    ticker_display: str,
    quantity: int,
    price: float,
    horizon: str = "",
    strategy: str = "",
    pattern: str = "",
    stop: Optional[float] = None,
    target: Optional[float] = None,
    gate_band: str = "",
    source: str = "manual",
    note: str = "",
) -> tuple[bool, str]:
    raw = (raw_ticker or "").strip().upper()
    if not raw.endswith((".NS", ".BO")) and "." not in raw:
        raw = f"{raw}.NS"
    qty = int(quantity)
    px = float(price)
    if qty <= 0 or px <= 0:
        return False, "Quantity and price must be positive."

    acc = load_paper_account()
    cost = qty * px
    if cost > float(acc.get("cash", 0)):
        return False, f"Insufficient paper cash (need {cost:,.2f}, have {acc['cash']:,.2f})."

    existing = None
    for p in acc["positions"]:
        if str(p.get("raw_ticker", "")).upper() == raw:
            existing = p
            break

    if existing:
        old_q = int(existing.get("qty", 0))
        old_ep = float(existing.get("entry_price", 0))
        new_q = old_q + qty
        new_ep = (old_ep * old_q + px * qty) / new_q if new_q else px
        existing["qty"] = new_q
        existing["entry_price"] = round(new_ep, 4)
        existing["last_add_at"] = _now_iso()
        if stop is not None:
            existing["stop"] = stop
        if target is not None:
            existing["target"] = target
    else:
        acc["positions"].append(
            {
                "id": str(uuid.uuid4())[:12],
                "raw_ticker": raw,
                "ticker": ticker_display or raw,
                "qty": qty,
                "entry_price": round(px, 4),
                "entry_at": _now_iso(),
                "horizon": horizon,
                "strategy": strategy,
                "pattern": pattern,
                "stop": stop,
                "target": target,
                "gate_band": gate_band,
                "source": source,
                "note": note,
            }
        )

    acc["cash"] = round(float(acc["cash"]) - cost, 2)
    save_paper_account(acc)
    return True, f"Paper BUY {qty} × {raw} @ {px:,.2f} (cost {cost:,.2f})"


def paper_sell(
    raw_ticker: str,
    quantity: Optional[int] = None,
    price: Optional[float] = None,
) -> tuple[bool, str]:
    raw = (raw_ticker or "").strip().upper()
    acc = load_paper_account()
    pos = None
    for p in acc["positions"]:
        if str(p.get("raw_ticker", "")).upper() == raw:
            pos = p
            break
    if not pos:
        return False, "No open paper position for this ticker."

    held = int(pos.get("qty", 0))
    sell_q = int(quantity) if quantity is not None else held
    if sell_q <= 0 or sell_q > held:
        return False, f"Invalid sell quantity (held {held})."

    px = float(price) if price is not None else (fetch_last_price(raw) or 0.0)
    if px <= 0:
        return False, "Could not fetch price for paper sell."

    proceeds = sell_q * px
    entry = float(pos.get("entry_price", 0))
    pnl = (px - entry) * sell_q

    acc["cash"] = round(float(acc["cash"]) + proceeds, 2)
    acc["closed_trades"].append(
        {
            "id": str(uuid.uuid4())[:12],
            "raw_ticker": raw,
            "ticker": pos.get("ticker", raw),
            "qty": sell_q,
            "entry_price": entry,
            "exit_price": round(px, 4),
            "pnl": round(pnl, 2),
            "closed_at": _now_iso(),
            "horizon": pos.get("horizon", ""),
            "strategy": pos.get("strategy", ""),
        }
    )

    if sell_q >= held:
        acc["positions"] = [p for p in acc["positions"] if str(p.get("raw_ticker", "")).upper() != raw]
    else:
        pos["qty"] = held - sell_q

    save_paper_account(acc)
    return True, f"Paper SELL {sell_q} × {raw} @ {px:,.2f} · P&L {pnl:+,.2f}"


def square_off_intraday_positions() -> list[str]:
    """Close all paper positions tagged horizon=intraday."""
    acc = load_paper_account()
    msgs: list[str] = []
    for p in list(acc.get("positions", [])):
        if str(p.get("horizon", "")).lower() != "intraday":
            continue
        raw = str(p.get("raw_ticker", ""))
        ok, msg = paper_sell(raw)
        msgs.append(msg if ok else f"{raw}: {msg}")
    return msgs


def account_summary(account: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    acc = account or load_paper_account()
    positions = acc.get("positions", [])
    mtm_rows: list[dict[str, Any]] = []
    invested = 0.0
    market_value = 0.0
    unrealized = 0.0

    for p in positions:
        raw = str(p.get("raw_ticker", ""))
        qty = int(p.get("qty", 0))
        entry = float(p.get("entry_price", 0))
        ltp = fetch_last_price(raw) or entry
        cost_basis = entry * qty
        mv = ltp * qty
        upnl = mv - cost_basis
        invested += cost_basis
        market_value += mv
        unrealized += upnl
        stop = p.get("stop")
        target = p.get("target")
        dist_stop = ((ltp - stop) / entry * 100) if stop and entry else None
        mtm_rows.append(
            {
                "Ticker": p.get("ticker", raw),
                "Raw": raw,
                "Horizon": p.get("horizon", "—"),
                "Qty": qty,
                "Entry": entry,
                "LTP": round(ltp, 2),
                "MTM value": round(mv, 2),
                "Unrealized P&L": round(upnl, 2),
                "P&L %": round((ltp / entry - 1) * 100, 2) if entry else None,
                "Stop": stop,
                "Target": target,
                "Gate": p.get("gate_band", "—"),
                "Strategy": p.get("strategy", "—"),
            }
        )

    cash = float(acc.get("cash", 0))
    starting = float(acc.get("starting_cash", cash))
    equity = cash + market_value
    realized = sum(float(t.get("pnl", 0) or 0) for t in acc.get("closed_trades", []))

    return {
        "currency": acc.get("currency", "INR"),
        "starting_cash": starting,
        "cash": cash,
        "invested": round(invested, 2),
        "market_value": round(market_value, 2),
        "equity": round(equity, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "total_pnl": round(equity - starting, 2),
        "total_return_pct": round((equity / starting - 1) * 100, 2) if starting else 0.0,
        "open_positions": len(positions),
        "closed_trades": len(acc.get("closed_trades", [])),
        "positions_mtm": mtm_rows,
    }


def pick_to_buy_kwargs(pick: Any) -> dict[str, Any]:
    """Build paper_buy kwargs from an AlgoPick."""
    return {
        "raw_ticker": getattr(pick, "raw_ticker", ""),
        "ticker_display": getattr(pick, "ticker", ""),
        "price": float(getattr(pick, "entry", None) or getattr(pick, "price", 0) or 0),
        "horizon": getattr(pick, "horizon", ""),
        "strategy": getattr(pick, "strategy", ""),
        "pattern": getattr(pick, "pattern", ""),
        "stop": getattr(pick, "stop", None),
        "target": getattr(pick, "target", None),
        "gate_band": getattr(pick, "gate_band", ""),
        "source": "algo_hub",
        "note": (getattr(pick, "rationale", "") or "")[:120],
    }
