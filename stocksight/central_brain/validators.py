"""
Schema validation — 100% compliance against rules.json before execution.

Validates VWAP proximity, VWAP position, 8 EMA trend, and RSI thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from central_brain.rules_loader import load_rules, side_rules


@dataclass
class ValidationResult:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    side: str = ""

    def summary(self) -> str:
        if self.approved:
            return "Approved: all schema checks passed."
        return "Blocked: " + "; ".join(self.reasons)


def _pct_vs_ref(price: float, ref: float) -> float:
    if ref == 0:
        return 999.0
    return abs((price - ref) / ref) * 100.0


def validate_signal_indicators(
    *,
    action: str,
    price: float,
    vwap: Optional[float],
    ema: Optional[float],
    rsi: Optional[float],
    rules: dict[str, Any],
) -> ValidationResult:
    side = (action or "").strip().lower()
    sr = side_rules(rules, side)
    if not sr:
        return ValidationResult(False, [f"Unknown action '{action}'"], side=side)

    reasons: list[str] = []
    checks: dict[str, Any] = {"action": side, "price": price}

    prox_max = float(sr.get("vwap_proximity_pct_max", rules.get("indicators", {}).get("vwap_proximity_pct", 1.5)))

    if vwap is None or vwap <= 0:
        reasons.append("Missing VWAP in signal payload")
        checks["vwap"] = None
    else:
        prox = _pct_vs_ref(price, vwap)
        checks["vwap"] = vwap
        checks["vwap_proximity_pct"] = round(prox, 4)
        if prox > prox_max:
            reasons.append(f"VWAP proximity {prox:.2f}% exceeds {prox_max}% max")

        if side in ("buy", "long", "entry") and sr.get("price_above_vwap"):
            if price <= vwap:
                reasons.append(f"Price {price} must be above VWAP {vwap}")
            checks["price_above_vwap"] = price > vwap
        if side in ("sell", "short", "exit", "close") and sr.get("price_below_vwap"):
            if price >= vwap:
                reasons.append(f"Price {price} must be below VWAP {vwap}")
            checks["price_below_vwap"] = price < vwap

    if ema is None or ema <= 0:
        reasons.append("Missing EMA in signal payload")
        checks["ema"] = None
    else:
        checks["ema"] = ema
        if side in ("buy", "long", "entry") and sr.get("price_above_ema"):
            if price <= ema:
                reasons.append(f"Price {price} must be above EMA {ema}")
            checks["price_above_ema"] = price > ema
        if side in ("sell", "short", "exit", "close") and sr.get("price_below_ema"):
            if price >= ema:
                reasons.append(f"Price {price} must be below EMA {ema}")
            checks["price_below_ema"] = price < ema

    if rsi is None:
        reasons.append("Missing RSI in signal payload")
        checks["rsi"] = None
    else:
        checks["rsi"] = rsi
        op = str(sr.get("rsi_operator", "lt" if side in ("buy", "long", "entry") else "gt"))
        if side in ("buy", "long", "entry"):
            ceiling = float(sr.get("rsi_max", 30))
            if op == "lt" and rsi >= ceiling:
                reasons.append(f"RSI {rsi} exceeds <{ceiling} threshold (oversold required)")
            checks["rsi_rule"] = f"rsi < {ceiling}"
        else:
            floor = float(sr.get("rsi_min", 70))
            if op == "gt" and rsi <= floor:
                reasons.append(f"RSI {rsi} below >{floor} threshold (overbought required)")
            checks["rsi_rule"] = f"rsi > {floor}"

    return ValidationResult(approved=len(reasons) == 0, reasons=reasons, checks=checks, side=side)


def validate_risk_limits(
    *,
    notional: float,
    trades_today: int,
    portfolio_value: float,
    max_trade_size: float,
    max_trades_per_day: int,
) -> ValidationResult:
    reasons: list[str] = []
    if notional > max_trade_size:
        reasons.append(f"Notional {notional:.2f} exceeds MAX_TRADE_SIZE {max_trade_size}")
    if notional > portfolio_value:
        reasons.append(f"Notional {notional:.2f} exceeds PORTFOLIO_VALUE {portfolio_value}")
    if trades_today >= max_trades_per_day:
        reasons.append(f"MAX_TRADES_PER_DAY {max_trades_per_day} reached ({trades_today} today)")
    return ValidationResult(
        approved=len(reasons) == 0,
        reasons=reasons,
        checks={
            "notional": notional,
            "trades_today": trades_today,
            "portfolio_value": portfolio_value,
            "max_trade_size": max_trade_size,
            "max_trades_per_day": max_trades_per_day,
        },
    )


def validate_from_rules_file(
    rules_path: Any,
    *,
    action: str,
    price: float,
    vwap: Optional[float],
    ema: Optional[float],
    rsi: Optional[float],
) -> ValidationResult:
    rules = load_rules(rules_path)
    return validate_signal_indicators(
        action=action, price=price, vwap=vwap, ema=ema, rsi=rsi, rules=rules,
    )
