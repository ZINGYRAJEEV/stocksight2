"""
Optional ICICI Direct Breeze API data (package: breeze-connect).

Breeze provides NSE/BSE historical OHLCV — StockSight still draws charts with Plotly.
Configure credentials (see below); without them everything falls back to Yahoo (yfinance).

Setup:
  1. Register at https://api.icicidirect.com/apiuser/home
  2. pip install breeze-connect
  3. Add to .streamlit/secrets.toml (repo root or stocksight/.streamlit/):

     [breeze]
     api_key = "your_api_key"
     api_secret = "your_api_secret"
     session_token = "your_session_token"

     Or env: BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN

  Session token: log in via Breeze login URL from the API portal after app registration.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

_IST = ZoneInfo("Asia/Kolkata")
_CLIENT: Any = None
_CLIENT_READY = False
_LAST_ERROR: Optional[str] = None
# In-memory overrides (e.g. a freshly pasted daily session token) take priority
# over secrets.toml so a UI refresh applies immediately without a server restart.
_OVERRIDES: dict[str, str] = {}


def _read_secret(key: str) -> str:
    override = _OVERRIDES.get(key)
    if override:
        return override.strip()
    try:
        import streamlit as st

        # st.secrets returns an AttrDict (not a dict subclass), so use .get directly.
        block = st.secrets.get("breeze", {})
        getter = getattr(block, "get", None)
        if callable(getter):
            val = getter(key)
            if val:
                return str(val).strip()
    except Exception:
        pass
    env_key = f"BREEZE_{key.upper()}"
    return (os.environ.get(env_key) or "").strip()


def reset_client() -> None:
    """Drop the cached Breeze client so the next call re-authenticates."""
    global _CLIENT, _CLIENT_READY, _LAST_ERROR
    _CLIENT = None
    _CLIENT_READY = False
    _LAST_ERROR = None


def _secrets_path() -> str:
    return os.path.join(".streamlit", "secrets.toml")


def login_url() -> str:
    """ICICI Breeze daily-login URL, pre-filled with the configured api_key.

    The api_key often contains characters like '#', '%', '!', '*' which MUST be
    percent-encoded — otherwise the browser truncates the key (e.g. at '#') and
    ICICI returns "Public Key does not exist".
    """
    from urllib.parse import quote

    api_key = _read_secret("api_key")
    base = "https://api.icicidirect.com/apiuser/login"
    return f"{base}?api_key={quote(api_key, safe='')}" if api_key else base


def update_session_token(token: str) -> tuple[bool, str]:
    """
    Apply a new daily session token: take effect immediately (in-memory override),
    persist to .streamlit/secrets.toml, and verify the connection.
    Returns (ok, message).
    """
    import re

    token = (token or "").strip()
    if not token:
        return False, "Token is empty — paste the apisession value first."
    _OVERRIDES["session_token"] = token
    reset_client()

    path = _secrets_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            new, n = re.subn(
                r"(?m)^\s*session_token\s*=.*$",
                lambda _m: f'session_token = "{token}"',
                content,
            )
            if n == 0:
                if "[breeze]" not in new:
                    new = new.rstrip() + "\n\n[breeze]\n"
                new = new.rstrip() + f'\nsession_token = "{token}"\n'
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
    except Exception as ex:
        return False, f"Token applied in-memory but could not save to file: {ex}"

    client = _get_client()
    if client is not None:
        return True, "Token saved — Breeze connected ✅"
    return False, _LAST_ERROR or "Token saved, but connection could not be verified."


def breeze_configured() -> bool:
    return bool(_read_secret("api_key") and _read_secret("api_secret") and _read_secret("session_token"))


def breeze_status_message() -> str:
    if not breeze_configured():
        return "Breeze API not configured — charts use Yahoo Finance (yfinance)."
    if _CLIENT_READY:
        return "Breeze API connected — NSE/BSE charts can use ICICI historical data."
    if _LAST_ERROR:
        return f"Breeze configured but session failed: {_LAST_ERROR}"
    return "Breeze credentials present — connect on first NSE chart load."


def _parse_breeze_symbol(raw_ticker: str) -> tuple[str, str] | None:
    """Map yfinance-style ticker to Breeze stock_code + exchange_code."""
    t = (raw_ticker or "").strip().upper()
    if t.endswith(".NS"):
        return t[:-3], "NSE"
    if t.endswith(".BO"):
        return t[:-3], "BSE"
    return None


_CODE_CACHE: dict[tuple[str, str], str] = {}
# Reverse map: (exchange, ISEC code) -> NSE/BSE symbol (e.g. ICIBAN -> ICICIBANK).
_REVERSE_ISEC_CACHE: dict[tuple[str, str], str] = {}


def lookup_nse_symbol(exchange_code: str, isec_or_symbol: str) -> Optional[str]:
    """Resolve a Breeze ``stock_code`` (ISEC or NSE symbol) to the NSE trading symbol."""
    return resolve_nse_trading_symbol(isec_or_symbol, exchange_code=exchange_code)


def resolve_nse_trading_symbol(
    isec_or_symbol: str,
    *,
    exchange_code: str = "NSE",
) -> Optional[str]:
    """ISEC code (e.g. HINCOP) or NSE symbol → NSE trading symbol (e.g. HINDCOPPER)."""
    code = (isec_or_symbol or "").strip().upper()
    if not code:
        return None
    hit = _REVERSE_ISEC_CACHE.get((exchange_code, code))
    if hit:
        return hit
    if (exchange_code, code) in _CODE_CACHE:
        return code

    client = _get_client()
    if client is not None:
        try:
            info = client.get_names(exchange_code=exchange_code, stock_code=code)
            if isinstance(info, dict):
                nse_sym = (
                    info.get("exchange_stock_code")
                    or info.get("nse_symbol")
                    or info.get("stock_code")
                )
                isec = (info.get("isec_stock_code") or "").strip().upper()
                if nse_sym:
                    nse_sym = str(nse_sym).strip().upper()
                    if isec:
                        _REVERSE_ISEC_CACHE[(exchange_code, isec)] = nse_sym
                    if nse_sym != code:
                        _REVERSE_ISEC_CACHE[(exchange_code, code)] = nse_sym
                    _CODE_CACHE[(exchange_code, nse_sym)] = isec or code
                    return nse_sym
        except Exception:
            pass
    return None


def _resolve_stock_code(client: Any, exch_code: str, symbol: str) -> str:
    """
    Breeze identifies instruments by its own ISEC code (e.g. ICICI Bank -> 'ICIBAN'),
    NOT the NSE/BSE symbol. Translate via get_names() and cache the result.
    Falls back to the original symbol if the lookup fails.
    """
    key = (exch_code, symbol)
    if key in _CODE_CACHE:
        return _CODE_CACHE[key]
    code = symbol
    try:
        info = client.get_names(exchange_code=exch_code, stock_code=symbol)
        if isinstance(info, dict):
            isec = info.get("isec_stock_code") or info.get("isec_stock_code".upper())
            if isec:
                code = str(isec).strip()
    except Exception:
        pass
    _CODE_CACHE[key] = code
    if code != symbol:
        _REVERSE_ISEC_CACHE[(exch_code, code.upper())] = symbol.upper()
    return code


def _interval_for_breeze(interval_key: str) -> str:
    return {"1d": "1day", "1h": "30minute", "15m": "5minute"}.get(interval_key, "1day")


def _date_range_ist(interval_key: str, *, lookback_days: Optional[int] = None) -> tuple[str, str]:
    now = datetime.now(tz=_IST)
    if lookback_days is not None and lookback_days > 0:
        start = now - timedelta(days=int(lookback_days))
    elif interval_key == "1d":
        start = now - timedelta(days=180)
    elif interval_key == "1h":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=10)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    return start.strftime(fmt), now.strftime(fmt)


def _get_client() -> Any:
    global _CLIENT, _CLIENT_READY, _LAST_ERROR
    if _CLIENT_READY and _CLIENT is not None:
        return _CLIENT
    if not breeze_configured():
        return None
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        _LAST_ERROR = "breeze-connect not installed (pip install breeze-connect)"
        return None
    try:
        api_key = _read_secret("api_key")
        api_secret = _read_secret("api_secret")
        session_token = _read_secret("session_token")
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        _CLIENT = breeze
        _CLIENT_READY = True
        _LAST_ERROR = None
        return _CLIENT
    except Exception as ex:
        _CLIENT = None
        _CLIENT_READY = False
        _LAST_ERROR = str(ex)
        return None


def _response_to_ohlc_df(payload: Any) -> pd.DataFrame:
    if not isinstance(payload, dict):
        return pd.DataFrame()
    if payload.get("Error"):
        return pd.DataFrame()
    rows = payload.get("Success") or payload.get("success") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame()
    rename = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "datetime": "Datetime",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "Datetime" not in df.columns:
        return pd.DataFrame()
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    df = df.set_index("Datetime").sort_index()
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")


def fetch_breeze_price_history(
    raw_ticker: str,
    interval_key: str = "1d",
    *,
    lookback_days: Optional[int] = None,
) -> pd.DataFrame:
    """
    Historical OHLCV for NSE/BSE symbols via ICICI Breeze.
    Returns empty DataFrame if unavailable (caller should fall back to yfinance).

    ``lookback_days`` overrides the default 180-day daily window (e.g. 1095 for ~3y backtests).
    """
    parsed = _parse_breeze_symbol(raw_ticker)
    if parsed is None:
        return pd.DataFrame()
    stock_code, exch_code = parsed
    client = _get_client()
    if client is None:
        return pd.DataFrame()
    stock_code = _resolve_stock_code(client, exch_code, stock_code)
    from_date, to_date = _date_range_ist(interval_key, lookback_days=lookback_days)
    try:
        payload = client.get_historical_data_v2(
            interval=_interval_for_breeze(interval_key),
            from_date=from_date,
            to_date=to_date,
            stock_code=stock_code,
            exchange_code=exch_code,
            product_type="cash",
        )
        return _response_to_ohlc_df(payload)
    except Exception as ex:
        global _LAST_ERROR  # noqa: PLW0603
        _LAST_ERROR = str(ex)
        return pd.DataFrame()


def fetch_breeze_intraday_bars(raw_ticker: str, days: int = 5) -> pd.DataFrame:
    """
    5-minute intraday OHLCV for an NSE/BSE symbol via ICICI Breeze.

    Used by the intraday engine when Breeze is configured. Returns an empty
    DataFrame when Breeze is unavailable so the caller can fall back to Yahoo.
    """
    parsed = _parse_breeze_symbol(raw_ticker)
    if parsed is None:
        return pd.DataFrame()
    stock_code, exch_code = parsed
    client = _get_client()
    if client is None:
        return pd.DataFrame()
    stock_code = _resolve_stock_code(client, exch_code, stock_code)
    now = datetime.now(tz=_IST)
    start = now - timedelta(days=max(1, int(days)))
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    try:
        payload = client.get_historical_data_v2(
            interval="5minute",
            from_date=start.strftime(fmt),
            to_date=now.strftime(fmt),
            stock_code=stock_code,
            exchange_code=exch_code,
            product_type="cash",
        )
        return _response_to_ohlc_df(payload)
    except Exception as ex:
        global _LAST_ERROR  # noqa: PLW0603
        _LAST_ERROR = str(ex)
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────
# Live quotes + order placement (REAL MONEY — use with care).
# product: "cash" = delivery/CNC, "margin" = intraday/MIS.
# ─────────────────────────────────────────────────────────────
def get_ltp(raw_ticker: str) -> Optional[float]:
    """Last traded price for an NSE/BSE symbol via Breeze. None if unavailable."""
    parsed = _parse_breeze_symbol(raw_ticker)
    if parsed is None:
        return None
    stock_code, exch_code = parsed
    client = _get_client()
    if client is None:
        return None
    code = _resolve_stock_code(client, exch_code, stock_code)
    try:
        resp = client.get_quotes(
            stock_code=code,
            exchange_code=exch_code,
            expiry_date="",
            product_type="cash",
            right="",
            strike_price="",
        )
        rows = (resp or {}).get("Success") or []
        if rows:
            row = rows[0]
            for key in ("ltp", "last_traded_price", "close", "best_bid_price"):
                val = row.get(key)
                if val not in (None, "", 0, "0"):
                    return float(val)
    except Exception as ex:
        global _LAST_ERROR  # noqa: PLW0603
        _LAST_ERROR = str(ex)
    return None


def _place_order(
    raw_ticker: str,
    action: str,
    quantity: int,
    order_type: str,
    price: Optional[float],
    stoploss: Optional[float],
    product: str,
) -> tuple[bool, str, Any]:
    """Low-level Breeze order call. Returns (ok, message, raw_response)."""
    parsed = _parse_breeze_symbol(raw_ticker)
    if parsed is None:
        return False, "Not an NSE/BSE symbol.", None
    stock_code, exch_code = parsed
    client = _get_client()
    if client is None:
        return False, _LAST_ERROR or "Breeze not connected.", None
    code = _resolve_stock_code(client, exch_code, stock_code)
    try:
        resp = client.place_order(
            stock_code=code,
            exchange_code=exch_code,
            product=product,
            action=action,
            order_type=order_type,
            stoploss=str(stoploss) if stoploss else "",
            quantity=str(int(quantity)),
            price=str(price) if price else "",
            validity="day",
            validity_date="",
            disclosed_quantity="0",
            expiry_date="",
            right="",
            strike_price="",
        )
        if isinstance(resp, dict):
            if resp.get("Error"):
                return False, str(resp.get("Error")), resp
            success = resp.get("Success") or {}
            order_id = success.get("order_id") if isinstance(success, dict) else None
            return True, f"Order accepted (id: {order_id or 'n/a'}).", resp
        return False, f"Unexpected response: {resp!r}", resp
    except Exception as ex:
        return False, str(ex), None


def place_buy_order(
    raw_ticker: str,
    quantity: int,
    order_type: str = "market",
    price: Optional[float] = None,
    product: str = "cash",
) -> tuple[bool, str, Any]:
    """Place a BUY order (market or limit)."""
    return _place_order(
        raw_ticker,
        action="buy",
        quantity=quantity,
        order_type=order_type,
        price=price if order_type == "limit" else None,
        stoploss=None,
        product=product,
    )


def place_stoploss_sell(
    raw_ticker: str,
    quantity: int,
    trigger_price: float,
    limit_price: Optional[float] = None,
    product: str = "cash",
) -> tuple[bool, str, Any]:
    """Place a stop-loss SELL order — sells if price falls to trigger_price."""
    return _place_order(
        raw_ticker,
        action="sell",
        quantity=quantity,
        order_type="stoploss",
        price=limit_price if limit_price else trigger_price,
        stoploss=trigger_price,
        product=product,
    )


def place_sell_order(
    raw_ticker: str,
    quantity: int,
    order_type: str = "market",
    price: Optional[float] = None,
    product: str = "cash",
) -> tuple[bool, str, Any]:
    """Place a SELL order (market or limit) to exit a long position."""
    return _place_order(
        raw_ticker,
        action="sell",
        quantity=quantity,
        order_type=order_type,
        price=price if order_type == "limit" else None,
        stoploss=None,
        product=product,
    )


def _unwrap(resp: Any) -> tuple[list, Optional[str]]:
    """Normalise a Breeze response into (rows, error).

    Breeze reports an empty result via the Error field with messages like
    'No Data Found' / 'No Positions available' — treat those as empty, not errors.
    """
    if not isinstance(resp, dict):
        return [], f"Unexpected response: {resp!r}"
    err = resp.get("Error")
    if err:
        low = str(err).lower()
        if any(s in low for s in ("no data", "no position", "no order", "no record", "not available", "no trade")):
            return [], None
        return [], str(err)
    rows = resp.get("Success")
    if rows is None:
        return [], None
    if isinstance(rows, dict):
        rows = [rows]
    return list(rows), None


def get_positions() -> tuple[list, Optional[str]]:
    """Current portfolio positions (open intraday / derivative positions)."""
    client = _get_client()
    if client is None:
        return [], _LAST_ERROR or "Breeze not connected."
    try:
        return _unwrap(client.get_portfolio_positions())
    except Exception as ex:
        return [], str(ex)


def _coerce_breeze_price(val: Any) -> Optional[float]:
    if val in (None, "", "0", 0, "0.0"):
        return None
    try:
        f = float(str(val).replace(",", ""))
        return f if f == f and f > 0 else None
    except (TypeError, ValueError):
        return None


def _is_nse_equity_holding(row: dict) -> bool:
    if str(row.get("exchange_code", "NSE")).upper() != "NSE":
        return False
    prod = str(row.get("product_type", "") or "").lower()
    if prod in ("options", "option", "futures", "future", "fno"):
        return False
    if row.get("expiry_date") or row.get("strike_price"):
        return False
    return True


def _merge_demat_with_portfolio_prices(demat_rows: list, portfolio_rows: list) -> list[dict]:
    """Demat API has qty only; NSE portfolio holdings carry average_price / CMP."""
    price_by_code: dict[str, dict] = {}
    for row in portfolio_rows or []:
        if not isinstance(row, dict) or not _is_nse_equity_holding(row):
            continue
        code = str(row.get("stock_code", "")).strip().upper()
        if code:
            price_by_code[code] = row

    merged: list[dict] = []
    for row in demat_rows or []:
        if not isinstance(row, dict):
            continue
        out = dict(row)
        pr = price_by_code.get(str(row.get("stock_code", "")).strip().upper(), {})
        avg = _coerce_breeze_price(pr.get("average_price"))
        cmp_ = _coerce_breeze_price(pr.get("current_market_price"))
        if avg is not None:
            out["average_price"] = avg
        if cmp_ is not None:
            out["current_market_price"] = cmp_
            out.setdefault("ltp", cmp_)
        for extra in ("unrealized_profit", "realized_profit", "change_percentage"):
            if pr.get(extra) not in (None, ""):
                out[extra] = pr.get(extra)
        merged.append(out)
    return merged


def get_holdings() -> tuple[list, Optional[str]]:
    """Demat / delivery holdings with cost and LTP merged from NSE portfolio holdings."""
    client = _get_client()
    if client is None:
        return [], _LAST_ERROR or "Breeze not connected."
    try:
        if not hasattr(client, "get_demat_holdings"):
            return _unwrap(
                client.get_portfolio_holdings(
                    exchange_code="NSE", from_date="", to_date="", stock_code="", portfolio_type=""
                )
            )

        demat_rows, demat_err = _unwrap(client.get_demat_holdings())
        if demat_err:
            return [], demat_err
        if not demat_rows:
            return [], None

        portfolio_rows: list = []
        if hasattr(client, "get_portfolio_holdings"):
            now = datetime.now(tz=_IST)
            fmt = "%Y-%m-%dT%H:%M:%S.000Z"
            start = (now - timedelta(days=365)).replace(hour=0, minute=0, second=0, microsecond=0)
            portfolio_rows, _ = _unwrap(
                client.get_portfolio_holdings(
                    exchange_code="NSE",
                    from_date=start.strftime(fmt),
                    to_date=now.strftime(fmt),
                    stock_code="",
                    portfolio_type="",
                )
            )

        return _merge_demat_with_portfolio_prices(demat_rows, portfolio_rows), None
    except Exception as ex:
        return [], str(ex)


def get_order_book(days: int = 1) -> tuple[list, Optional[str]]:
    """Order book for the last `days` calendar days (default = today)."""
    client = _get_client()
    if client is None:
        return [], _LAST_ERROR or "Breeze not connected."
    now = datetime.now(tz=_IST)
    start = (now - timedelta(days=max(0, days - 1))).replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    try:
        return _unwrap(
            client.get_order_list(
                exchange_code="NSE", from_date=start.strftime(fmt), to_date=now.strftime(fmt)
            )
        )
    except Exception as ex:
        return [], str(ex)


def get_trade_book(days: int = 1) -> tuple[list, Optional[str]]:
    """Executed trades for the last `days` calendar days (default = today)."""
    client = _get_client()
    if client is None:
        return [], _LAST_ERROR or "Breeze not connected."
    now = datetime.now(tz=_IST)
    start = (now - timedelta(days=max(0, days - 1))).replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    try:
        return _unwrap(
            client.get_trade_list(
                from_date=start.strftime(fmt), to_date=now.strftime(fmt), exchange_code="NSE",
                product_type="", action="", stock_code="",
            )
        )
    except Exception as ex:
        return [], str(ex)
