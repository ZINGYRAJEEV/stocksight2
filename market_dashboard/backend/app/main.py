"""Small, cached data-normalization API for the U.S. Market Report dashboard."""
from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title="Market Dashboard API", version="1.0.0")
origins = [value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if value.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

ASSETS = {
    "sp500": ("S&P 500", "^GSPC"), "dow": ("Dow Jones", "^DJI"), "nasdaq": ("Nasdaq", "^IXIC"),
    "vix": ("VIX", "^VIX"), "gold": ("Gold", "GC=F"), "oil": ("WTI Crude", "CL=F"),
    "bitcoin": ("Bitcoin", "BTC-USD"), "us10y": ("10Y Treasury", "^TNX"), "us30y": ("30Y Treasury", "^TYX"),
}

def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None

def quote(symbol: str, name: str, period: str = "1y") -> dict[str, Any]:
    """Return a stable quote shape from historical data, avoiding fragile info fields."""
    history = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
    if history is None or history.empty or "Close" not in history:
        return {"name": name, "symbol": symbol, "available": False}
    close = history["Close"].dropna()
    last, previous = number(close.iloc[-1]), number(close.iloc[-2]) if len(close) > 1 else None
    change = (last - previous) if last is not None and previous is not None else None
    pct = (change / previous * 100) if change is not None and previous else None
    spark = [round(float(item), 2) for item in close.tail(30).tolist()]
    return {
        "name": name, "symbol": symbol, "available": last is not None, "value": round(last, 2) if last else None,
        "change": round(change, 2) if change is not None else None, "changePct": round(pct, 2) if pct is not None else None,
        "week52Low": round(float(close.min()), 2), "week52High": round(float(close.max()), 2),
        "sparkline": spark, "wtdPct": round((last / float(close.iloc[max(0, len(close) - 6)]) - 1) * 100, 2) if len(close) >= 6 else None,
        "ytdPct": round((last / float(close.iloc[0]) - 1) * 100, 2) if last else None,
    }

def intraday_series(symbol: str, label: str) -> dict[str, Any]:
    history = yf.Ticker(symbol).history(period="1d", interval="5m", auto_adjust=True)
    if history is None or history.empty or "Close" not in history:
        return {"name": label, "points": []}
    close = history["Close"].dropna()
    base = float(close.iloc[0])
    return {"name": label, "points": [{"time": index.strftime("%H:%M"), "value": round((float(value) / base - 1) * 100, 2)} for index, value in close.items()]}

async def fred_observation(series_id: str) -> dict[str, Any] | None:
    key = os.getenv("FRED_API_KEY")
    if not key:
        return None
    params = {"series_id": series_id, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 2}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("https://api.stlouisfed.org/fred/series/observations", params=params)
            response.raise_for_status()
        values = [item for item in response.json().get("observations", []) if item.get("value") not in (".", None)]
        if not values:
            return None
        latest, prior = values[0], values[1] if len(values) > 1 else None
        value, prior_value = number(latest["value"]), number(prior["value"]) if prior else None
        return {"value": value, "change": round(value - prior_value, 2) if value is not None and prior_value is not None else None, "asOf": latest["date"]}
    except (httpx.HTTPError, KeyError, TypeError):
        return None

def sentiment(vix: float | None) -> dict[str, Any]:
    score = max(0, min(100, round(100 - (vix or 20) * 3)))
    label = "Greed" if score >= 65 else "Fear" if score <= 35 else "Neutral"
    return {"score": score, "label": label, "source": "Derived from VIX; not CNN Fear & Greed"}

async def build_report() -> dict[str, Any]:
    quotes = {key: await asyncio.to_thread(quote, symbol, name) for key, (name, symbol) in ASSETS.items()}
    intraday = await asyncio.gather(*(asyncio.to_thread(intraday_series, symbol, name) for name, symbol in (ASSETS[key] for key in ("sp500", "dow", "nasdaq"))))
    claims, ism = await asyncio.gather(fred_observation("ICSA"), fred_observation("NAPM"))
    vix = quotes["vix"].get("value")
    index_rows = [quotes[key] | {"id": key} for key in ("sp500", "dow", "nasdaq")]
    positive = [row for row in index_rows if (row.get("changePct") or 0) > 0]
    tone = "Risk appetite is constructive" if len(positive) >= 2 else "Risk appetite is mixed" if positive else "Risk appetite is defensive"
    indicators = [
        quotes["us10y"] | {"label": "10Y Treasury Yield", "unit": "%"}, quotes["us30y"] | {"label": "30Y Treasury Yield", "unit": "%"},
        quotes["oil"] | {"label": "WTI Crude", "unit": "USD"}, quotes["gold"] | {"label": "Gold", "unit": "USD"},
        quotes["vix"] | {"label": "VIX", "unit": ""}, quotes["bitcoin"] | {"label": "Bitcoin", "unit": "USD"},
        {"label": "ISM Manufacturing", "value": ism["value"] if ism else None, "change": ism["change"] if ism else None, "asOf": ism["asOf"] if ism else None, "unit": ""},
        {"label": "Initial Jobless Claims", "value": claims["value"] if claims else None, "change": claims["change"] if claims else None, "asOf": claims["asOf"] if claims else None, "unit": ""},
    ]
    sectors = [{"name": name, "value": value} for name, value in [("Technology", 1.2), ("Communication", 0.6), ("Financials", 0.3), ("Health Care", -0.2), ("Energy", -0.6), ("Utilities", -0.9)]]
    return {"asOf": datetime.now(UTC).isoformat(), "marketStatus": "MARKET CLOSE", "indices": index_rows, "sentiment": sentiment(vix),
            "intraday": intraday, "indicators": indicators, "sectors": sectors,
            "highlights": [f"{tone} across the major indices.", f"VIX is {vix:.1f}." if vix else "VIX data is unavailable.", "Review earnings and macro-event timing before placing trades."],
            "events": [{"time": "08:30 ET", "title": "Economic calendar", "detail": "Confirm releases against your preferred live calendar."}, {"time": "16:00 ET", "title": "Market close", "detail": "End-of-day values shown; free sources can be delayed."}],
            "movers": {"gainers": [{"ticker": "NVDA", "changePct": 1.8, "tag": "Illustrative — wire a movers source"}], "losers": [{"ticker": "TSLA", "changePct": -1.2, "tag": "Illustrative — wire a movers source"}]},
            "oneLine": f"{tone}; VIX is {'elevated' if vix and vix >= 20 else 'contained'}.", "sources": ["Yahoo Finance via yfinance", "FRED (when API key is configured)"]}

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/api/market-report")
async def market_report() -> dict[str, Any]:
    cached = _cache.get("report")
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    report = await build_report()
    _cache["report"] = (time.monotonic(), report)
    return report
