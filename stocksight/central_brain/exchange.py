"""Execution layer — paper, BitGet, ICICI Breeze."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

from central_brain.config import CentralBrainConfig


def _bitget_sign(secret: str, timestamp: str, method: str, path: str, body: str) -> str:
    msg = timestamp + method.upper() + path + body
    mac = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def _bitget_request(
    cfg: CentralBrainConfig,
    method: str,
    path: str,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
) -> tuple[bool, str, dict]:
    creds = cfg.bitget
    if not creds.configured():
        return False, "BitGet credentials not configured (API_KEY, SECRET_KEY, PASSPHRASE)", {}

    base = "https://api.bitget.com"
    qs = ""
    if params:
        qs = "?" + urllib.parse.urlencode(params)
    full_path = path + qs
    body_str = json.dumps(body) if body else ""
    ts = str(int(time.time() * 1000))
    sign = _bitget_sign(creds.secret_key, ts, method, full_path, body_str)

    headers = {
        "ACCESS-KEY": creds.api_key,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": creds.passphrase,
        "Content-Type": "application/json",
        "locale": "en-US",
    }
    url = base + full_path
    data = body_str.encode("utf-8") if body_str else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            code = str(parsed.get("code", "00000"))
            if code in ("00000", "0"):
                return True, "OK", parsed
            return False, str(parsed.get("msg", raw))[:200], parsed
    except Exception as exc:
        return False, str(exc)[:200], {}


def bitget_place_market_order(
    cfg: CentralBrainConfig,
    *,
    symbol: str,
    side: str,
    size_usdt: float,
    price_hint: float,
) -> tuple[bool, str, dict]:
    """
    Spot market order sized by USDT notional.
    symbol e.g. XRPUSDT → BitGet symbol XRPUSDT.
    """
    sym = symbol.upper().replace("/", "").replace("-", "")
    if not sym.endswith("USDT"):
        sym = f"{sym}USDT"
    qty = max(size_usdt / max(price_hint, 1e-9), 0.0001)
    body = {
        "symbol": sym,
        "side": side.lower(),
        "orderType": "market",
        "force": "gtc",
        "size": f"{qty:.8f}".rstrip("0").rstrip("."),
    }
    return _bitget_request(cfg, "POST", "/api/v2/spot/trade/place-order", body=body)


def execute_order(
    cfg: CentralBrainConfig,
    *,
    symbol: str,
    action: str,
    notional: float,
    price: float,
    exchange: str = "bitget",
) -> tuple[bool, str, str]:
    """
    Route order to paper / BitGet / Breeze.
    Returns (ok, message, execution_mode).
    """
    mode = cfg.effective_mode()
    if mode != "live":
        return _execute_paper(symbol, action, notional, price, mode)

    ex = (exchange or "bitget").lower()
    side = "buy" if action.lower() in ("buy", "long", "entry") else "sell"

    if ex == "bitget":
        if not cfg.bitget.configured():
            return False, "BitGet live keys missing — blocked", "live"
        ok, msg, _ = bitget_place_market_order(
            cfg, symbol=symbol, side=side, size_usdt=notional, price_hint=price,
        )
        return ok, msg, "live"

    if ex == "breeze":
        return _execute_breeze(symbol, side, notional, price, cfg)

    return False, f"Unknown exchange '{exchange}'", mode


def _execute_paper(
    symbol: str,
    action: str,
    notional: float,
    price: float,
    mode: str,
) -> tuple[bool, str, str]:
    try:
        from paper_trading import fetch_last_price, paper_buy, paper_sell
    except ImportError:
        from ..paper_trading import fetch_last_price, paper_buy, paper_sell  # type: ignore

    raw = _symbol_to_yahoo(symbol)
    px = fetch_last_price(raw) or price
    qty = max(1, int(notional / max(px, 1e-9)))
    disp = raw.replace(".NS", "").replace(".BO", "")

    if action.lower() in ("buy", "long", "entry"):
        stop = px * 0.985
        target = px * 1.03
        return paper_buy(
            raw_ticker=raw,
            ticker_display=disp,
            quantity=qty,
            price=px,
            horizon="CRYPTO" if "USDT" in symbol.upper() else "NSE",
            strategy="central_brain",
            pattern="tv_webhook",
            stop=stop,
            target=target,
            gate_band="Central Brain",
            source="central_brain",
            note=f"Paper {action} {symbol} notional≈{notional:.2f}",
        ) + (mode,)

    return paper_sell(raw, price=px) + (mode,)


def _execute_breeze(
    symbol: str,
    side: str,
    notional: float,
    price: float,
    cfg: CentralBrainConfig,
) -> tuple[bool, str, str]:
    try:
        from breeze_data import place_buy_order, place_sell_order
    except ImportError:
        return False, "breeze_data not available", "live"

    raw = symbol if "." in symbol else f"{symbol}.NS"
    qty = max(1, int(notional / max(price, 1e-9)))
    if side == "buy":
        ok, msg, _ = place_buy_order(raw, qty, order_type="market", product="margin")
    else:
        ok, msg, _ = place_sell_order(raw, qty, order_type="market", product="margin")
    return ok, msg, "live"


def _symbol_to_yahoo(symbol: str) -> str:
    s = symbol.upper().replace("/", "").replace("-", "")
    if s.endswith("USDT"):
        # Crypto — yfinance uses e.g. XRP-USD
        base = s[:-4]
        return f"{base}-USD"
    if "." not in s:
        return f"{s}.NS"
    return s
