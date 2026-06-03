"""Market data + indicators via yfinance / Breeze."""

from __future__ import annotations

from typing import Optional

import pandas as pd

try:
    from intraday import _fetch_daily, _fetch_intraday_bars
    from screener import compute_rsi, compute_vwap, hist_series
except ImportError:
    from ..intraday import _fetch_daily, _fetch_intraday_bars  # type: ignore
    from ..screener import compute_rsi, compute_vwap, hist_series  # type: ignore


def fetch_bars(raw_ticker: str, *, data_source: str = "auto") -> tuple[Optional[pd.DataFrame], str]:
    df, interval, period = _fetch_intraday_bars(raw_ticker, data_source=data_source)
    return df, interval or ""


def fetch_daily(raw_ticker: str, *, data_source: str = "auto") -> Optional[pd.DataFrame]:
    return _fetch_daily(raw_ticker, "1y", data_source=data_source)


def snapshot_indicators(bars: pd.DataFrame, daily: pd.DataFrame) -> dict:
    out: dict = {}
    if bars is None or bars.empty:
        return out
    closes = hist_series(bars, "Close").astype(float).dropna()
    if len(closes) >= 14:
        r = compute_rsi(closes)
        if r is not None and not pd.isna(r):
            out["rsi"] = round(float(r), 2)
    if len(closes) >= 9:
        out["ema9"] = round(float(closes.ewm(span=9, adjust=False).mean().iloc[-1]), 2)
    vwap_s = compute_vwap(bars)
    if vwap_s is not None and not vwap_s.empty:
        out["vwap"] = round(float(vwap_s.iloc[-1]), 2)
    try:
        from screener import compute_atr
    except ImportError:
        from ..screener import compute_atr  # type: ignore
    if len(bars) >= 15:
        h, l, c = hist_series(bars, "High"), hist_series(bars, "Low"), hist_series(bars, "Close")
        atr = compute_atr(h, l, c)
        if atr is not None and not pd.isna(atr):
            out["atr"] = round(float(atr.iloc[-1] if hasattr(atr, "iloc") else atr), 2)
    if daily is not None and not daily.empty:
        dc = hist_series(daily, "Close").astype(float).dropna()
        if len(dc) >= 50:
            out["ma50"] = round(float(dc.rolling(50).mean().iloc[-1]), 2)
        if len(dc) >= 200:
            out["ma200"] = round(float(dc.rolling(200).mean().iloc[-1]), 2)
    out["ltp"] = round(float(closes.iloc[-1]), 2) if not closes.empty else None
    return out
