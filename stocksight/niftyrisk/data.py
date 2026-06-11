"""Market data — yfinance OHLCV for NSE holdings and Nifty benchmark."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

_SECTOR_CACHE: dict[str, str] = {}


def fetch_close_matrix(
    tickers: list[str],
    *,
    period: str = "1y",
    benchmark: Optional[str] = None,
) -> pd.DataFrame:
    """Aligned daily close prices — columns = tickers (+ benchmark if set)."""
    if not tickers:
        return pd.DataFrame()
    symbols = list(dict.fromkeys(tickers))
    if benchmark and benchmark not in symbols:
        symbols.append(benchmark)

    if yf is None:
        raise ImportError("yfinance is required: pip install yfinance")

    data = yf.download(
        symbols,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if data is None or data.empty:
        return pd.DataFrame()

    closes: dict[str, pd.Series] = {}
    if len(symbols) == 1:
        sym = symbols[0]
        if "Close" in data.columns:
            closes[sym] = data["Close"].astype(float)
    else:
        for sym in symbols:
            try:
                if sym in data.columns.get_level_values(0):
                    s = data[sym]["Close"].astype(float)
                    if not s.dropna().empty:
                        closes[sym] = s
            except (KeyError, TypeError, AttributeError):
                continue

    if not closes:
        return pd.DataFrame()

    out = pd.DataFrame(closes).dropna(how="all").ffill().dropna(how="any")
    return out


def latest_prices(tickers: list[str]) -> dict[str, float]:
    if yf is None or not tickers:
        return {}
    out: dict[str, float] = {}
    try:
        closes = fetch_close_matrix(tickers, period="1mo")
        if not closes.empty:
            for col in closes.columns:
                s = closes[col].dropna()
                if not s.empty:
                    px = float(s.iloc[-1])
                    if px == px and px > 0:
                        out[str(col)] = px
    except Exception:
        pass
    missing = [t for t in tickers if t not in out]
    for t in missing:
        try:
            hist = yf.Ticker(t).history(period="1mo", interval="1d", auto_adjust=True)
            if hist is not None and not hist.empty:
                s = hist["Close"].dropna()
                if not s.empty:
                    px = float(s.iloc[-1])
                    if px == px and px > 0:
                        out[t] = px
        except Exception:
            continue
    return out


def sector_for_ticker(ticker: str, *, isin: str = "") -> str:
    """Sector/industry from Yahoo; uses screener helper and caches results."""
    key = (ticker or "").strip().upper()
    if not key:
        return "Unknown"
    isin_key = (isin or "").strip().upper()
    if isin_key.startswith("INF"):
        label = "Mutual Fund / ETF"
        _SECTOR_CACHE[key] = label
        return label
    if key in _SECTOR_CACHE:
        return _SECTOR_CACHE[key]

    if yf is None:
        return "Unknown"

    try:
        from screener import get_sector_industry

        sec, ind = get_sector_industry(yf.Ticker(key))
        label = (sec or ind or "").strip()
        if not label:
            label = "Unknown"
    except Exception:
        label = "Unknown"

    _SECTOR_CACHE[key] = label
    return label


def sectors_for_tickers(
    tickers: list[str],
    *,
    isin_by_ticker: dict[str, str] | None = None,
) -> dict[str, str]:
    isin_map = isin_by_ticker or {}
    return {t: sector_for_ticker(t, isin=isin_map.get(t, "")) for t in tickers}
