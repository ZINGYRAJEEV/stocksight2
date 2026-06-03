"""Position sizing, trailing stops, daily loss halt."""

from __future__ import annotations

from typing import Any, Optional

from intrabot.config import RiskConfig


def suggest_quantity(
    cash: float,
    entry: float,
    stop: Optional[float],
    risk: RiskConfig,
) -> int:
    if entry <= 0 or cash <= 0:
        return 0
    deploy_cap = int((cash * risk.capital_per_trade_pct / 100.0) / entry)
    if stop and 0 < stop < entry:
        risk_budget = cash * (risk.stop_loss_pct / 100.0)
        per_share = entry - stop
        qty_risk = int(risk_budget / per_share) if per_share > 0 else 0
        qty = min(qty_risk, deploy_cap) if deploy_cap > 0 else qty_risk
    else:
        stop_dist = entry * (risk.stop_loss_pct / 100.0)
        qty = int((cash * risk.capital_per_trade_pct / 100.0) / stop_dist) if stop_dist > 0 else deploy_cap
    return max(1, qty) if qty > 0 else 0


def default_stop_target(entry: float, risk: RiskConfig) -> tuple[float, float]:
    stop = round(entry * (1 - risk.stop_loss_pct / 100.0), 2)
    risk_amt = entry - stop
    target = round(entry + risk_amt * risk.target_rr, 2)
    return stop, target


def daily_loss_halted(state: dict[str, Any], risk: RiskConfig) -> bool:
    if state.get("halted"):
        return True
    pnl = float(state.get("daily_pnl_pct") or 0.0)
    return pnl <= -abs(risk.max_daily_loss_pct)


def count_open(state: dict[str, Any], market: str, source_prefix: str = "intrabot") -> int:
    try:
        from paper_trading_store import load_paper_account
    except ImportError:
        return 0
    acc = load_paper_account()
    return sum(
        1
        for p in acc.get("positions", [])
        if str(p.get("source", "")).startswith(source_prefix)
        and str(p.get("horizon", "")) == market
    )


def update_trailing_stops(state: dict[str, Any], market: str, risk: RiskConfig) -> list[str]:
    """Adjust trail stop levels for open intrabot positions."""
    msgs: list[str] = []
    try:
        from paper_trading import fetch_last_price
        from paper_trading_store import load_paper_account
    except ImportError:
        return msgs

    acc = load_paper_account()
    trails: dict[str, Any] = state.setdefault("trail_stops", {})
    for p in acc.get("positions", []):
        if not str(p.get("source", "")).startswith("intrabot"):
            continue
        if str(p.get("horizon", "")) != market:
            continue
        raw = str(p.get("raw_ticker", ""))
        entry = float(p.get("entry_price", 0) or 0)
        if entry <= 0:
            continue
        px = fetch_last_price(raw) or entry
        pnl_pct = (px - entry) / entry * 100.0
        key = f"{market}:{raw}"
        if pnl_pct >= risk.trail_stop_after_pct:
            new_stop = round(px * (1 - risk.trail_stop_distance_pct / 100.0), 2)
            old = float(trails.get(key, 0) or 0)
            if new_stop > old:
                trails[key] = new_stop
                p["stop"] = new_stop
                msgs.append(f"Trail {raw} stop → {new_stop} (PnL {pnl_pct:+.2f}%)")
    return msgs
