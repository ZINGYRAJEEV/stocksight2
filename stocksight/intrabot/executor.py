"""Order routing: paper / Breeze (NSE) / Alpaca stub (US)."""

from __future__ import annotations

from typing import Any, Optional

from intrabot.config import BROKER_CONFIG, IntraBotConfig
from intrabot.risk_manager import default_stop_target, suggest_quantity


def execute_buy(
    result: Any,
    *,
    market: str,
    cfg: IntraBotConfig,
    pack: Optional[dict] = None,
) -> tuple[bool, str]:
    pack = pack or {}
    entry = float(getattr(result, "entry", 0) or getattr(result, "price", 0) or 0)
    stop = float(getattr(result, "stop", 0) or 0)
    target = getattr(result, "target", None)
    raw = str(getattr(result, "raw_ticker", ""))
    display = str(getattr(result, "ticker", raw))
    strategy = str(getattr(result, "strategy", ""))
    note = str(getattr(result, "setup_note", "") or "")[:80]

    if entry <= 0:
        return False, "No entry price"
    if stop <= 0 or stop >= entry:
        stop, target = default_stop_target(entry, cfg.risk)
    if target is None:
        _, target = default_stop_target(entry, cfg.risk)

    if cfg.effective_paper():
        return _paper_buy(
            raw, display, entry, stop, float(target), market, strategy, pack, note,
        )

    mkt = market.upper()
    if mkt == "NSE":
        return _breeze_buy(raw, entry, stop, cfg)
    return _alpaca_buy(raw, entry, stop, cfg)


def square_off_market(market: str, cfg: IntraBotConfig) -> list[str]:
    if cfg.effective_paper():
        return _paper_square_off(market)
    mkt = market.upper()
    if mkt == "NSE":
        return _breeze_square_off()
    return _alpaca_square_off()


def _paper_buy(
    raw: str,
    display: str,
    entry: float,
    stop: float,
    target: float,
    market: str,
    strategy: str,
    pack: dict,
    note: str,
) -> tuple[bool, str]:
    from paper_trading import fetch_last_price, paper_buy
    from paper_trading_store import load_paper_account

    from intrabot.config import RISK

    acc = load_paper_account()
    qty = suggest_quantity(float(acc["cash"]), entry, stop, RISK)
    px = fetch_last_price(raw) or entry
    return paper_buy(
        raw_ticker=raw,
        ticker_display=display,
        quantity=qty,
        price=px,
        horizon=market,
        strategy=strategy,
        pattern=pack.get("label", ""),
        stop=stop,
        target=target,
        gate_band=pack.get("label", ""),
        source=f"intrabot_{market}",
        note=note,
    )


def _paper_square_off(market: str) -> list[str]:
    from paper_trading import fetch_last_price, paper_sell
    from paper_trading_store import load_paper_account

    acc = load_paper_account()
    msgs: list[str] = []
    for p in list(acc.get("positions", [])):
        if str(p.get("horizon", "")) != market:
            continue
        if not str(p.get("source", "")).startswith("intrabot"):
            continue
        raw = str(p.get("raw_ticker", ""))
        ok, msg = paper_sell(raw, price=fetch_last_price(raw))
        msgs.append(msg if ok else f"{raw}: {msg}")
    return msgs


def _breeze_buy(raw: str, entry: float, stop: float, cfg: IntraBotConfig) -> tuple[bool, str]:
    try:
        from breeze_data import place_buy_order, place_stoploss_sell
        from intrabot.config import RISK
    except ImportError:
        return False, "Breeze not installed"
    qty = max(1, suggest_quantity(500_000, entry, stop, cfg.risk))
    ok, msg, _ = place_buy_order(raw, qty, order_type="market", product="margin")
    if ok:
        place_stoploss_sell(raw, qty, trigger_price=stop, product="margin")
    return ok, msg


def _breeze_square_off() -> list[str]:
    try:
        from breeze_data import get_positions, place_sell_order
    except ImportError:
        return ["Breeze unavailable"]
    rows, err = get_positions()
    if err:
        return [err]
    msgs = []
    for row in rows or []:
        code = str(row.get("stock_code", ""))
        qty = int(float(row.get("quantity", 0) or 0))
        if qty > 0 and code:
            raw = f"{code}.NS"
            ok, msg, _ = place_sell_order(raw, qty, order_type="market", product="margin")
            msgs.append(msg if ok else f"{raw}: {msg}")
    return msgs


def _alpaca_buy(raw: str, entry: float, stop: float, cfg: IntraBotConfig) -> tuple[bool, str]:
    bc = BROKER_CONFIG.get("nyse", {})
    if not bc.get("api_key"):
        return False, "Alpaca keys not set — use paper mode or add ALPACA_API_KEY"
    return False, "Alpaca live stub — use paper mode (pip install alpaca-trade-api to extend)"


def _alpaca_square_off() -> list[str]:
    return ["Alpaca square-off stub — use paper mode"]
