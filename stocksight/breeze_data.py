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


def _read_secret(key: str) -> str:
    try:
        import streamlit as st

        block = st.secrets.get("breeze", {})
        if isinstance(block, dict) and block.get(key):
            return str(block[key]).strip()
    except Exception:
        pass
    env_key = f"BREEZE_{key.upper()}"
    return (os.environ.get(env_key) or "").strip()


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


def _interval_for_breeze(interval_key: str) -> str:
    return {"1d": "1day", "1h": "30minute", "15m": "5minute"}.get(interval_key, "1day")


def _date_range_ist(interval_key: str) -> tuple[str, str]:
    now = datetime.now(tz=_IST)
    if interval_key == "1d":
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


def fetch_breeze_price_history(raw_ticker: str, interval_key: str = "1d") -> pd.DataFrame:
    """
    Historical OHLCV for NSE/BSE symbols via ICICI Breeze.
    Returns empty DataFrame if unavailable (caller should fall back to yfinance).
    """
    parsed = _parse_breeze_symbol(raw_ticker)
    if parsed is None:
        return pd.DataFrame()
    stock_code, exch_code = parsed
    client = _get_client()
    if client is None:
        return pd.DataFrame()
    from_date, to_date = _date_range_ist(interval_key)
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
        global _LAST_ERROR
        _LAST_ERROR = str(ex)
        return pd.DataFrame()
