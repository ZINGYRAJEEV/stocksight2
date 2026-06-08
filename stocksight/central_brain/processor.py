"""
Central Brain processor — TradingView signal → validation → execution → audit.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from typing import Any, Optional

from central_brain.audit import append_audit
from central_brain.claude_brain import claude_validate_signal
from central_brain.config import CentralBrainConfig, load_config
from central_brain.exchange import execute_order
from central_brain.rules_loader import load_rules, side_rules
from central_brain.validators import validate_risk_limits, validate_signal_indicators

try:
    from central_brain_store import increment_trades_today, load_state, save_state, trades_today
except ImportError:
    from ..central_brain_store import increment_trades_today, load_state, save_state, trades_today  # type: ignore


def parse_tradingview_payload(raw: Any) -> dict[str, Any]:
    """Normalize TradingView alert JSON or plain text."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        return {"message": text}
    return {}


def _float_field(payload: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = payload.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _signal_idempotency_key(payload: dict) -> str:
    blob = json.dumps(
        {
            "action": payload.get("action"),
            "symbol": payload.get("symbol"),
            "price": payload.get("price"),
            "time": payload.get("time") or payload.get("timenow"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def verify_webhook_secret(payload: dict, cfg: CentralBrainConfig) -> tuple[bool, str]:
    secret = cfg.tradingview_secret
    if not secret:
        return True, "No webhook secret configured (set TRADINGVIEW_WEBHOOK_SECRET for production)."
    for key in ("secret", "passphrase", "token"):
        if str(payload.get(key, "")) == secret:
            return True, "Webhook secret verified."
    return False, "Invalid TradingView webhook secret."


def process_tradingview_signal(
    raw_payload: Any,
    *,
    cfg: Optional[CentralBrainConfig] = None,
) -> dict[str, Any]:
    """
    Full pipeline: auth → schema → risk → Claude → execute → audit.
    """
    cfg = cfg or load_config()
    payload = parse_tradingview_payload(raw_payload)
    state = load_state()

    if state.get("kill_switch") or cfg.kill_switch:
        cfg.kill_switch = True

    action = str(
        payload.get("action")
        or payload.get("side")
        or payload.get("order_action")
        or ""
    ).strip().lower()
    symbol = str(payload.get("symbol") or payload.get("ticker") or "").strip()
    price = _float_field(payload, "price", "close", "last")
    vwap = _float_field(payload, "vwap", "VWAP")
    ema = _float_field(payload, "ema8", "ema", "EMA", "ema_8")
    rsi = _float_field(payload, "rsi", "RSI")
    exchange = str(payload.get("exchange") or "bitget").strip().lower()
    notional = _float_field(payload, "notional", "size_usdt") or min(
        cfg.max_trade_size,
        cfg.portfolio_value * 0.05,
    )

    base_record: dict[str, Any] = {
        "exchange_source": exchange,
        "asset": symbol,
        "action": action,
        "payload": payload,
        "execution_mode": cfg.effective_mode(),
        "idempotency_key": _signal_idempotency_key(payload),
    }

    def _finish(status: str, reasoning: str, **extra: Any) -> dict[str, Any]:
        record = {
            **base_record,
            "status": status,
            "reasoning": reasoning,
            **extra,
        }
        sid = append_audit(record)
        state["last_signal_id"] = sid
        save_state(state)
        _emit_alert(cfg, record)
        return {"signal_id": sid, **record}

    if not cfg.enabled:
        return _finish("Blocked", "CENTRAL_BRAIN_ENABLED is false.")

    ok_sec, sec_msg = verify_webhook_secret(payload, cfg)
    if not ok_sec:
        return _finish("Blocked", sec_msg)

    if not symbol or not action:
        return _finish("Blocked", "Missing symbol or action in TradingView payload.")

    if price is None or price <= 0:
        return _finish("Blocked", "Missing or invalid price in signal.")

    try:
        rules = load_rules(cfg.rules_path)
    except Exception as exc:
        return _finish("Blocked", f"rules.json error: {exc}")

    indicator_result = validate_signal_indicators(
        action=action,
        price=price,
        vwap=vwap,
        ema=ema,
        rsi=rsi,
        rules=rules,
    )
    if not indicator_result.approved:
        return _finish(
            "Blocked",
            indicator_result.summary(),
            checks=indicator_result.checks,
            layer="schema",
        )

    risk_result = validate_risk_limits(
        notional=notional,
        trades_today=trades_today(state),
        portfolio_value=cfg.portfolio_value,
        max_trade_size=cfg.max_trade_size,
        max_trades_per_day=cfg.max_trades_per_day,
    )
    if not risk_result.approved:
        return _finish(
            "Blocked",
            risk_result.summary(),
            checks={**indicator_result.checks, **risk_result.checks},
            layer="risk",
        )

    side_rule = side_rules(rules, action)
    claude_ok, claude_reason, claude_raw = claude_validate_signal(
        cfg,
        payload=payload,
        rules_result=indicator_result,
        rules_excerpt=side_rule,
    )
    if not claude_ok:
        return _finish(
            "Blocked",
            claude_reason,
            checks=indicator_result.checks,
            layer="claude",
            claude=claude_raw,
        )

    if cfg.kill_switch:
        return _finish("Blocked", "Kill switch is ON.", layer="kill_switch")

    exec_ok, exec_msg, exec_mode = execute_order(
        cfg,
        symbol=symbol,
        action=action,
        notional=notional,
        price=price,
        exchange=exchange,
    )

    if exec_ok:
        increment_trades_today(state)
        return _finish(
            "Approved",
            f"{claude_reason} | Executed ({exec_mode}): {exec_msg}",
            checks=indicator_result.checks,
            order_message=exec_msg,
            execution_mode=exec_mode,
            notional=notional,
        )

    return _finish(
        "Blocked",
        f"Validation passed but execution failed: {exec_msg}",
        checks=indicator_result.checks,
        execution_mode=exec_mode,
    )


def _emit_alert(cfg: CentralBrainConfig, record: dict[str, Any]) -> None:
    url = cfg.alert_webhook
    if not url:
        return
    try:
        data = json.dumps(
            {
                "event": "central_brain_signal",
                "status": record.get("status"),
                "asset": record.get("asset"),
                "reasoning": record.get("reasoning"),
            },
            default=str,
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass
