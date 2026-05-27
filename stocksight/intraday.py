"""
Intraday trading screener — momentum, VWAP pullback, ORB, gap-up scans.

All strategies pull Yahoo Finance 5-minute bars for today's session plus a few
days of daily history for context (prev close, 50/200-DMA, avg volume).

Educational only — pair with strict risk management (1-2% per trade, hard stops).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from .screener import (
        NIFTY_50,
        NIFTY_500_EXTRA,
        UNIVERSES,
        compute_rsi,
        get_sector_industry,
        get_stock_links,
        hist_series,
    )
except ImportError:
    from screener import (  # type: ignore[no-redef]
        NIFTY_50,
        NIFTY_500_EXTRA,
        UNIVERSES,
        compute_rsi,
        get_sector_industry,
        get_stock_links,
        hist_series,
    )


# ─────────────────────────────────────────────────────────────
# Markets supported by the intraday module.
# Each market has its own universes, session hours, and time-zone display.
# ─────────────────────────────────────────────────────────────
MARKETS = ("NSE", "US")

MARKET_LABEL = {
    "NSE": "🇮🇳 NSE / India",
    "US":  "🇺🇸 NYSE & NASDAQ",
}

# ── NSE universes (Indian market hours).
NIFTY_500 = NIFTY_50 + NIFTY_500_EXTRA
# Nifty 100 ≈ first 100 unique names from the Nifty 500 composition list.
NIFTY_100: list[str] = list(dict.fromkeys(NIFTY_500))[:100]

NSE_INTRADAY_UNIVERSES: dict[str, list[str]] = {
    "Nifty 50 (fast)": NIFTY_50,
    "Nifty 100 (medium)": NIFTY_100,
    "Nifty 500 (broad, slow)": NIFTY_500,
}

# Common F&O-friendly large/mid caps for the "Liquid F&O shortlist" universe.
LIQUID_INTRADAY_NAMES: list[str] = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "TATAMOTORS.NS", "BAJFINANCE.NS", "AXISBANK.NS", "SBIN.NS", "ITC.NS",
    "LT.NS", "KOTAKBANK.NS", "MARUTI.NS", "BHARTIARTL.NS", "ASIANPAINT.NS",
    "M&M.NS", "TITAN.NS", "WIPRO.NS", "POWERGRID.NS", "NTPC.NS",
    "ADANIENT.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "ULTRACEMCO.NS", "ONGC.NS",
    "HINDUNILVR.NS", "SUNPHARMA.NS", "DRREDDY.NS", "HCLTECH.NS", "TECHM.NS",
]

# ── US universes (NYSE / NASDAQ regular hours).
# S&P 500 is provided by stocksight.screener.UNIVERSES["S&P 500 (NYSE)"].
SP500_LIST: list[str] = list(UNIVERSES.get("S&P 500 (NYSE)", []))

# High-volume, intraday-friendly US mega/large caps (incl. liquid ETFs).
LIQUID_US_NAMES: list[str] = [
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "COST", "WMT", "HD",
    "XOM", "CVX", "OXY", "BA", "DIS", "UBER", "PLTR", "COIN", "SHOP", "BABA",
    "SPY", "QQQ", "IWM", "DIA", "TLT",
]

US_INTRADAY_UNIVERSES: dict[str, list[str]] = {
    "Liquid US shortlist (~35)": LIQUID_US_NAMES,
    "S&P 500 (broad, slow)": SP500_LIST,
}

# Combined (market → {label → tickers}) for routing.
INTRADAY_UNIVERSES_BY_MARKET: dict[str, dict[str, list[str]]] = {
    "NSE": NSE_INTRADAY_UNIVERSES,
    "US":  US_INTRADAY_UNIVERSES,
}

# Back-compat alias used by older code that imports INTRADAY_UNIVERSES directly.
INTRADAY_UNIVERSES: dict[str, list[str]] = dict(NSE_INTRADAY_UNIVERSES)

STRATEGIES = ("BROAD", "MOMENTUM", "VWAP", "ORB", "GAP")

STRATEGY_LABEL = {
    "BROAD":    "🔍 Broad Movers (widest net)",
    "MOMENTUM": "🔥 Momentum Breakout",
    "VWAP":     "📈 VWAP Pullback",
    "ORB":      "🕯️ Opening Range Breakout",
    "GAP":      "📊 Gap-Up with Strength",
}

# Best-time-of-day per strategy, per market. Each entry shows the *market-local*
# trading window AND the equivalent CEST/CET window (Europe/Berlin) for traders
# in Central Europe.
STRATEGY_BEST_TIME_BY_MARKET: dict[str, dict[str, str]] = {
    "NSE": {
        "BROAD":    "Any session window  ·  use when you want the widest list",
        "MOMENTUM": "9:30 – 11:00 AM IST  ·  6:00 – 7:30 AM CEST",
        "VWAP":     "10:30 AM – 1:00 PM IST  ·  7:00 – 9:30 AM CEST",
        "ORB":      "9:45 – 10:15 AM IST only  ·  6:15 – 6:45 AM CEST",
        "GAP":      "Pre-open + 9:15 – 9:30 AM IST  ·  5:45 – 6:00 AM CEST",
    },
    "US": {
        "BROAD":    "Any session window  ·  use when you want the widest list",
        "MOMENTUM": "9:45 – 11:00 AM ET  ·  3:45 – 5:00 PM CEST",
        "VWAP":     "11:00 AM – 1:30 PM ET  ·  5:00 – 7:30 PM CEST",
        "ORB":      "9:45 – 10:00 AM ET only  ·  3:45 – 4:00 PM CEST",
        "GAP":      "Pre-market + 9:30 – 9:45 AM ET  ·  3:30 – 3:45 PM CEST",
    },
}

# Back-compat — old import path.
STRATEGY_BEST_TIME = STRATEGY_BEST_TIME_BY_MARKET["NSE"]


# ─────────────────────────────────────────────────────────────
# Universal filters (applied to every strategy)
# ─────────────────────────────────────────────────────────────
@dataclass
class IntradayFilters:
    min_price: float = 50.0
    max_price: float = 5000.0
    min_avg_volume_20d: float = 500_000.0
    min_market_cap_cr: float = 5000.0          # ₹ crore
    apply_mcap_filter: bool = False            # off by default for speed
    min_volume_ratio: float = 1.0              # current vs 20-bar avg (relaxed default)
    min_rsi: float = 40.0
    max_rsi: float = 80.0
    min_pct_change: float = 0.0                # |% vs prev close|; 0 = off


@dataclass
class IntradayScanStats:
    """Per-scan funnel counts — powers the diagnostic panel in the UI."""
    total_scanned: int = 0
    no_data: int = 0
    failed_price: int = 0
    failed_avg_volume: int = 0
    failed_no_rsi: int = 0
    failed_no_volume_ratio: int = 0
    failed_volume_ratio: int = 0
    failed_rsi: int = 0
    failed_min_change: int = 0
    failed_hard_reject: int = 0
    no_strategy_match: int = 0
    tickers_matched: int = 0
    result_rows: int = 0
    bars_5m: int = 0
    bars_15m: int = 0


# ─────────────────────────────────────────────────────────────
# Result rows
# ─────────────────────────────────────────────────────────────
@dataclass
class IntradayResult:
    ticker: str
    raw_ticker: str
    strategy: str
    price: float
    open_px: float
    prev_close: float
    pct_change: float          # current % vs prev close
    gap_pct: float             # open % vs prev close
    intraday_high: Optional[float] = None
    intraday_low: Optional[float] = None
    rsi: Optional[float] = None
    vol_ratio: Optional[float] = None          # 5-min current vs 20-bar avg
    pct_vs_vwap: Optional[float] = None
    pct_vs_ma50d: Optional[float] = None
    pct_vs_ma200d: Optional[float] = None
    pct_vs_52w_high: Optional[float] = None
    orb_high: Optional[float] = None
    orb_low: Optional[float] = None
    setup_note: str = ""
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    rr_ratio: Optional[float] = None
    sector: str = "—"
    links: dict = field(default_factory=dict)
    session_vol_pct: Optional[int] = None       # typical session volume % at scan time
    prediction: str = ""                        # time-of-day volume quality + stock vol hint
    score_120: int = 0                          # 7-rule score out of 120
    rank_tier: str = ""                         # Elite / Strong / Watchlist / Avoid
    rank_why: str = ""                          # short reason for ranking
    position_size: str = ""                     # suggested position size by tier


@dataclass
class GapResult:
    ticker: str
    raw_ticker: str
    prev_close: float
    open_px: float
    current_price: float
    intraday_high: Optional[float]
    intraday_low: Optional[float]
    gap_pct: float
    open_to_now_pct: float
    direction: str             # "UP" / "DOWN" / "FLAT"
    size_band: str             # "Small" / "Medium" / "Large"
    holding: bool              # current is on the gap side of open
    advice: str
    vol_ratio: Optional[float]
    sector: str = "—"
    links: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def compute_vwap(bars: pd.DataFrame) -> Optional[pd.Series]:
    """Anchored intraday VWAP from 5-minute OHLCV bars."""
    if bars is None or bars.empty:
        return None
    h = hist_series(bars, "High").astype(float)
    l = hist_series(bars, "Low").astype(float)
    c = hist_series(bars, "Close").astype(float)
    v = hist_series(bars, "Volume").astype(float)
    if c.empty or v.empty or v.sum() <= 0:
        return None
    typical = (h + l + c) / 3.0
    cum_v = v.cumsum()
    cum_pv = (typical * v).cumsum()
    return cum_pv / cum_v.replace(0, np.nan)


def _safe_pct(curr: float, base: float) -> Optional[float]:
    if base is None or base <= 0:
        return None
    return round((float(curr) / float(base) - 1.0) * 100.0, 2)


def _gap_category(gap_pct: float) -> tuple[str, str]:
    """Return (size_band, direction) for a gap percentage."""
    ap = abs(gap_pct)
    if gap_pct > 0:
        direction = "UP"
    elif gap_pct < 0:
        direction = "DOWN"
    else:
        direction = "FLAT"
    if ap < 0.5:
        size_band = "Flat"
    elif ap < 1.0:
        size_band = "Small"
    elif ap < 3.0:
        size_band = "Medium"
    else:
        size_band = "Large"
    return size_band, direction


def _gap_advice(gap_pct: float, holding: bool, open_to_now_pct: float, vol_ratio: Optional[float]) -> str:
    """Plain-English suggestion for a gap result row."""
    size_band, direction = _gap_category(gap_pct)
    if size_band == "Flat":
        return "Skip — gap too small to provide an edge."
    if size_band == "Small":
        return "Risky — small gaps often fill back; only trade with confirmation."
    vol_note = ""
    if vol_ratio is not None:
        if vol_ratio >= 2.0:
            vol_note = " Strong volume confirms institutional interest."
        elif vol_ratio >= 1.0:
            vol_note = " Volume is okay."
        else:
            vol_note = " ⚠ Weak volume — gap may not hold."
    if direction == "UP":
        if holding:
            return f"Gap-up holding → look for ORB long / momentum-long setups.{vol_note}"
        return "Gap-up filling → wait, do NOT chase. Consider short if it loses prev close." + vol_note
    if direction == "DOWN":
        if holding:
            return f"Gap-down holding → look for short / VWAP rejection.{vol_note} (Avoid longs.)"
        return "Gap-down filling → bullish recovery; consider long over prev close." + vol_note
    return "Neutral."


def _suggest_setup(strategy: str, price: float, intraday_low: Optional[float],
                    intraday_high: Optional[float], orb_high: Optional[float],
                    orb_low: Optional[float], vwap: Optional[float],
                    prev_close: float, gap_pct: float
                  ) -> tuple[str, Optional[float], Optional[float], Optional[float]]:
    """Return (setup_note, entry, stop, target) for a strategy."""
    if strategy == "BROAD":
        entry = round(price * 1.001, 2)
        stop = round(min(intraday_low or price * 0.992, price * 0.992), 2)
        risk = entry - stop
        if risk <= 0:
            return ("Broad mover: define stop manually.", None, None, None)
        target = round(entry + 1.5 * risk, 2)
        return ("Active mover with volume — confirm direction on 5m chart · 1:1.5 R:R",
                entry, stop, target)

    if strategy == "MOMENTUM":
        entry = round(price * 1.001, 2)
        stop = round(min(price * 0.995, intraday_low or price * 0.985), 2)
        risk = entry - stop
        if risk <= 0:
            return ("Momentum: wait for a clean pullback — no defined risk.", None, None, None)
        target = round(entry + 2.0 * risk, 2)
        return ("Buy on close > entry · 1:2 R:R · trail stop at swing low",
                entry, stop, target)

    if strategy == "VWAP":
        if vwap is None:
            return ("VWAP: no VWAP available.", None, None, None)
        entry = round(max(price, vwap) * 1.001, 2)
        stop = round(vwap * 0.996, 2)
        risk = entry - stop
        if risk <= 0:
            return ("VWAP pullback: wait for clean rebound above VWAP.", None, None, None)
        target = round(entry + 2.0 * risk, 2)
        return ("Buy on 5m close > VWAP · stop just below VWAP",
                entry, stop, target)

    if strategy == "ORB":
        if not orb_high or not orb_low:
            return ("ORB: first 15-min range not yet formed.", None, None, None)
        entry = round(orb_high * 1.001, 2)
        stop = round(orb_low * 0.998, 2)
        risk = entry - stop
        if risk <= 0:
            return ("ORB: invalid range.", None, None, None)
        target = round(entry + 1.5 * risk, 2)
        return ("Buy on 5m close > ORB high · stop < ORB low",
                entry, stop, target)

    if strategy == "GAP":
        entry = round(price * 1.001, 2)
        # Stop at gap-fill (prev close) or intraday low, whichever is higher
        base_stop = max(intraday_low or 0.0, prev_close * 1.001)
        stop = round(base_stop, 2)
        risk = entry - stop
        if risk <= 0:
            return ("Gap-up: gap already filling; skip.", None, None, None)
        target = round(entry + 2.0 * risk, 2)
        return (f"Gap-up {gap_pct:+.2f}% · buy strength continuation · 1:2 R:R",
                entry, stop, target)

    return ("", None, None, None)


# ─────────────────────────────────────────────────────────────
# Data fetch (per ticker) — 5m first, auto-fallback to 15m when market is closed
# ─────────────────────────────────────────────────────────────
def _fetch_intraday_bars(ticker: str) -> tuple[Optional[pd.DataFrame], str]:
    """Fetch intraday OHLCV. Tries 5m then 15m (better when session is closed).

    Returns (dataframe, interval_label) where interval_label is '5m', '15m', or ''.
    """
    attempts = (
        ("5m", "1d"),
        ("5m", "2d"),
        ("5m", "5d"),
        ("15m", "5d"),
        ("15m", "10d"),
    )
    try:
        stk = yf.Ticker(ticker)
        for interval, period in attempts:
            try:
                df = stk.history(period=period, interval=interval, auto_adjust=False)
                if df is not None and not df.empty and len(df) >= 3:
                    return df, interval
            except Exception:
                continue
    except Exception:
        pass
    return None, ""


def _fetch_intraday_5m(ticker: str) -> Optional[pd.DataFrame]:
    """Back-compat wrapper — returns bars only (any interval)."""
    df, _ = _fetch_intraday_bars(ticker)
    return df


def _fetch_daily(ticker: str, period: str = "1y") -> Optional[pd.DataFrame]:
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def _orb_levels(bars: pd.DataFrame, interval: str = "5m") -> tuple[Optional[float], Optional[float]]:
    """First 15-min range high/low for the most recent session."""
    if bars is None or bars.empty:
        return None, None
    # Restrict to the latest session date
    try:
        last_date = bars.index[-1].date()
        session = bars[bars.index.date == last_date]
    except Exception:
        session = bars
    if session.empty:
        return None, None
    # 5m → 3 bars = 15 min; 15m → 1 bar = 15 min
    n_bars = 1 if interval == "15m" else 3
    head = session.head(n_bars)
    if len(head) < 1:
        return None, None
    try:
        orb_h = float(hist_series(head, "High").max())
        orb_l = float(hist_series(head, "Low").min())
        return round(orb_h, 2), round(orb_l, 2)
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────
# Strategy evaluators (one per row).
# Each returns IntradayResult or None.
# ─────────────────────────────────────────────────────────────
def _build_context(raw_ticker: str) -> Optional[dict]:
    """Heavy-lift context block reused by every strategy for a ticker."""
    bars, bar_interval = _fetch_intraday_bars(raw_ticker)
    if bars is None or bars.empty:
        return None
    daily = _fetch_daily(raw_ticker, "1y")
    if daily is None or daily.empty:
        return None

    closes_5m = hist_series(bars, "Close").astype(float).dropna()
    vols_5m = hist_series(bars, "Volume").astype(float).dropna()
    if closes_5m.empty:
        return None

    # Today vs prev close
    daily_close = hist_series(daily, "Close").astype(float).dropna()
    if daily_close.empty:
        return None
    prev_close = float(daily_close.iloc[-2]) if len(daily_close) >= 2 else float(daily_close.iloc[-1])

    # Session-local subset: use the last available session in the bars frame
    try:
        last_date = bars.index[-1].date()
        session = bars[bars.index.date == last_date]
    except Exception:
        session = bars
    if session.empty:
        session = bars

    open_px = float(hist_series(session, "Open").iloc[0])
    price = float(closes_5m.iloc[-1])
    intraday_high = float(hist_series(session, "High").max()) if not session.empty else price
    intraday_low = float(hist_series(session, "Low").min()) if not session.empty else price
    gap_pct = _safe_pct(open_px, prev_close) or 0.0
    pct_change = _safe_pct(price, prev_close) or 0.0

    # Intraday RSI (needs fewer bars early in session — use last 14+ closes)
    rsi_val: Optional[float] = None
    try:
        if len(closes_5m) >= 15:
            r = compute_rsi(closes_5m)
            if r is not None and not np.isnan(r):
                rsi_val = float(r)
    except Exception:
        rsi_val = None

    # Volume ratio: latest bar vs prior-bar average.
    # Off-hours the *last* bar is often stale (vol≈0) — fall back to session mean bar vol.
    vol_ratio: Optional[float] = None
    if len(vols_5m) >= 6:
        lookback = min(20, len(vols_5m) - 1)
        prior = vols_5m.iloc[-(lookback + 1):-1]
        avg = float(prior.mean()) if len(prior) else 0.0
        latest = float(vols_5m.iloc[-1])
        if avg > 0:
            vol_ratio = round(latest / avg, 2)
            if vol_ratio < 1.0:
                recent = vols_5m.iloc[-lookback:]
                bar_avg = float(recent.mean()) if len(recent) else 0.0
                if bar_avg > 0:
                    vol_ratio = max(vol_ratio, round(bar_avg / avg, 2))

    # VWAP for the session
    vwap_series = compute_vwap(session)
    vwap_now = float(vwap_series.iloc[-1]) if vwap_series is not None and not vwap_series.empty else None
    pct_vs_vwap = _safe_pct(price, vwap_now) if vwap_now else None
    ema9 = None
    pct_ema9 = None
    if len(closes_5m) >= 9:
        ema9 = float(closes_5m.ewm(span=9, adjust=False).mean().iloc[-1])
        pct_ema9 = _safe_pct(price, ema9) if ema9 > 0 else None

    # Daily MA context
    pct_ma50 = pct_ma200 = None
    if len(daily_close) >= 50:
        ma50 = float(daily_close.rolling(50).mean().iloc[-1])
        pct_ma50 = _safe_pct(price, ma50) if ma50 > 0 else None
    if len(daily_close) >= 200:
        ma200 = float(daily_close.rolling(200).mean().iloc[-1])
        pct_ma200 = _safe_pct(price, ma200) if ma200 > 0 else None

    # 52-week high context
    wk_high = float(daily_close.tail(252).max()) if len(daily_close) >= 5 else None
    pct_vs_52w = _safe_pct(price, wk_high) if wk_high else None

    # Avg daily volume for liquidity filter
    daily_vol = hist_series(daily, "Volume").astype(float).dropna()
    avg_dvol = float(daily_vol.tail(20).mean()) if len(daily_vol) >= 5 else 0.0

    # Session participation vs typical (works when last intraday bar is stale / market closed).
    if avg_dvol > 0 and not session.empty:
        try:
            sess_vol = float(hist_series(session, "Volume").astype(float).sum())
            bars_per_day = 78.0 if bar_interval == "5m" else 26.0
            expected_per_bar = avg_dvol / bars_per_day
            n_sess = max(len(session), 1)
            if expected_per_bar > 0:
                session_vr = round((sess_vol / n_sess) / expected_per_bar, 2)
                if vol_ratio is None or vol_ratio < session_vr:
                    vol_ratio = session_vr
                # Meaningful session turnover → don't reject on a stale last bar alone.
                if sess_vol >= 0.15 * avg_dvol and n_sess >= 8:
                    vol_ratio = max(vol_ratio or 0.0, 1.0)
        except Exception:
            pass

    orb_h, orb_l = _orb_levels(bars, bar_interval)

    return {
        "bars": bars,
        "bar_interval": bar_interval,
        "session": session,
        "daily": daily,
        "price": price,
        "open_px": open_px,
        "prev_close": prev_close,
        "intraday_high": intraday_high,
        "intraday_low": intraday_low,
        "gap_pct": gap_pct,
        "pct_change": pct_change,
        "rsi": rsi_val,
        "vol_ratio": vol_ratio,
        "vwap": vwap_now,
        "pct_vs_vwap": pct_vs_vwap,
        "pct_vs_ema9": pct_ema9,
        "pct_vs_ma50d": pct_ma50,
        "pct_vs_ma200d": pct_ma200,
        "pct_vs_52w_high": pct_vs_52w,
        "avg_dvol": avg_dvol,
        "orb_high": orb_h,
        "orb_low": orb_l,
    }


def _universal_fail_reason(ctx: dict, flt: IntradayFilters) -> Optional[str]:
    """Return failure reason for price/liquidity filters, or None if passed."""
    p = ctx["price"]
    if p < flt.min_price or p > flt.max_price:
        return "price"
    if ctx["avg_dvol"] and ctx["avg_dvol"] < flt.min_avg_volume_20d:
        return "avg_volume"
    return None


def _passes_universal(ctx: dict, flt: IntradayFilters) -> bool:
    return _universal_fail_reason(ctx, flt) is None


def _signal_fail_reason(ctx: dict, flt: IntradayFilters) -> Optional[str]:
    """RSI / volume-ratio / min-change gates applied before strategy rules."""
    rsi = ctx["rsi"]
    vr = ctx["vol_ratio"]
    if rsi is None:
        return "no_rsi"
    if vr is None:
        return "no_volume_ratio"
    if vr < flt.min_volume_ratio:
        return "volume_ratio"
    if not (flt.min_rsi <= rsi <= flt.max_rsi):
        return "rsi"
    if flt.min_pct_change > 0 and abs(ctx.get("pct_change") or 0.0) < flt.min_pct_change:
        return "min_change"
    return None


def _compose_row_prediction(
    session_pred: "VolumeTimePrediction",
    stock_vol_ratio: Optional[float],
) -> str:
    """Blend session time-of-day volume quality with per-stock volume ratio."""
    base = session_pred.prediction
    if stock_vol_ratio is None:
        return base
    if stock_vol_ratio < 1.0:
        return f"{base} · Stock vol {stock_vol_ratio:.1f}× thin"
    if stock_vol_ratio >= 1.5:
        return f"{base} · Stock vol {stock_vol_ratio:.1f}× confirms"
    return f"{base} · Stock vol {stock_vol_ratio:.1f}×"


def _timing_weight_from_prediction(pred_text: str) -> int:
    s = (pred_text or "").lower()
    if "best time" in s:
        return 3
    if "good" in s and "afternoon" in s:
        return 2
    if "too wild" in s:
        return -1
    if "fake" in s or "avoid" in s:
        return -3
    if "dangerous" in s or "forced" in s:
        return -4
    if "closed" in s:
        return -2
    return 0


def _hard_reject_reasons(ctx: dict) -> list[str]:
    """Immediate long-side disqualifiers from the rulebook."""
    out: list[str] = []
    rsi = ctx.get("rsi")
    pct_vwap = ctx.get("pct_vs_vwap")
    day_chg = float(ctx.get("pct_change") or 0.0)
    gap = float(ctx.get("gap_pct") or 0.0)
    pct_52w = ctx.get("pct_vs_52w_high")
    vr = float(ctx.get("vol_ratio") or 0.0)

    if rsi is not None and float(rsi) > 72.0:
        out.append("RSI>72")
    if pct_vwap is not None and float(pct_vwap) > 2.0:
        out.append("vsVWAP>+2%")
    if day_chg < 0:
        out.append("day<0")
    if gap < -3.0:
        out.append("gap<-3%")
    if pct_52w is not None and float(pct_52w) < -40.0:
        out.append("52W<-40%")
    if vr < 1.0:
        out.append("vol<1.0x")
    return out


def _score_intraday_rules(ctx: dict, *, strategy_hits: int, hard_rejects: list[str]) -> dict:
    """7-rule scoring engine (max 120 points) with penalties and tier mapping."""
    vr = float(ctx.get("vol_ratio") or 0.0)
    gap = float(ctx.get("gap_pct") or 0.0)
    gap_abs = abs(gap)
    day_chg = float(ctx.get("pct_change") or 0.0)
    rsi = ctx.get("rsi")
    pct_52w = ctx.get("pct_vs_52w_high")
    pct_vwap = ctx.get("pct_vs_vwap")
    pct_ma50 = ctx.get("pct_vs_ma50d")
    pct_ma200 = ctx.get("pct_vs_ma200d")

    # 1) Volume ratio (max +30)
    if vr >= 5.0:
        p_vol = 30
    elif vr >= 3.0:
        p_vol = 20
    elif vr >= 1.0:
        p_vol = 10
    else:
        p_vol = 0

    # 2) Gap quality (-25 to +20)
    if gap >= 3.0:
        p_gap = 20
    elif gap >= 1.0:
        p_gap = 12
    elif gap >= 0.0:
        p_gap = 5
    elif gap <= -3.0:
        p_gap = -25
    elif gap <= -1.0:
        p_gap = -15
    else:
        p_gap = 0

    # 3) Day change quality (-20 to +20)
    if day_chg >= 5.0:
        p_day = 20
    elif day_chg >= 2.0:
        p_day = 12
    elif day_chg >= 1.0:
        p_day = 5
    elif day_chg < 0:
        p_day = -20
    else:
        p_day = 0

    # 4) RSI sweet spot (-10 to +15)
    p_rsi = 0
    if rsi is not None:
        r = float(rsi)
        if 50.0 <= r <= 65.0:
            p_rsi = 15
        elif 40.0 <= r <= 49.0:
            p_rsi = 8
        elif 66.0 <= r <= 72.0:
            p_rsi = 5
        elif r > 72.0:
            p_rsi = -10
        elif r < 40.0:
            p_rsi = -5

    # 5) Near 52-week high (-10 to +15)
    p_52w = 0
    if pct_52w is not None:
        d = float(pct_52w)
        if d >= -2.0:
            p_52w = 15
        elif d >= -10.0:
            p_52w = 5
        elif d >= -30.0:
            p_52w = 0
        else:
            p_52w = -10

    # 6) VWAP proximity (-5 to +10)
    p_vwap = 0
    if pct_vwap is not None:
        av = abs(float(pct_vwap))
        if av <= 0.5:
            p_vwap = 10
        elif av <= 1.0:
            p_vwap = 5
        elif av <= 1.5:
            p_vwap = 5
        elif av >= 2.0:
            p_vwap = -5

    # 7) Trend alignment (max +10)
    above50 = pct_ma50 is not None and float(pct_ma50) > 0
    above200 = pct_ma200 is not None and float(pct_ma200) > 0
    p_trend = 10 if (above50 and above200) else (5 if (above50 or above200) else 0)

    score = int(p_vol + p_gap + p_day + p_rsi + p_52w + p_vwap + p_trend)
    if score >= 80:
        tier = "🏆 Best"
        pos_size = "100%"
    elif score >= 50:
        tier = "✅ Good"
        pos_size = "75%"
    elif score >= 25:
        tier = "🟡 OK"
        pos_size = "50%"
    else:
        tier = "⚠️ Avoid"
        pos_size = "Skip"

    # Penalize/flag weak signal overlap or hard reject logic.
    if strategy_hits <= 1:
        pos_size = "50%" if pos_size not in ("Skip",) else pos_size
    if hard_rejects:
        tier = "⚠️ Avoid"
        pos_size = "Skip"

    reason = (
        f"Vol {p_vol}/30 · Gap {p_gap:+d}/20 · Day {p_day:+d}/20 · RSI {p_rsi:+d}/15 · "
        f"52W {p_52w:+d}/15 · VWAP {p_vwap:+d}/10 · Trend {p_trend}/10 · "
        f"Signals {strategy_hits}"
    )
    if hard_rejects:
        reason += " · Reject: " + ", ".join(hard_rejects)
    return {
        "score_120": score,
        "tier": tier,
        "position_size": pos_size,
        "reason": reason,
    }


def _make_result(
    raw: str,
    strategy: str,
    ctx: dict,
    sector: str,
    note: str,
    *,
    session_pred: Optional["VolumeTimePrediction"] = None,
    score_pack: Optional[dict] = None,
) -> IntradayResult:
    note_str, entry, stop, target = _suggest_setup(
        strategy,
        ctx["price"],
        ctx["intraday_low"],
        ctx["intraday_high"],
        ctx["orb_high"],
        ctx["orb_low"],
        ctx["vwap"],
        ctx["prev_close"],
        ctx["gap_pct"],
    )
    rr = None
    if entry is not None and stop is not None and target is not None and (entry - stop) > 0:
        rr = round((target - entry) / (entry - stop), 2)

    pred_text = ""
    sess_pct: Optional[int] = None
    timing_w = 0
    if session_pred is not None:
        sess_pct = session_pred.session_vol_pct
        pred_text = _compose_row_prediction(session_pred, ctx.get("vol_ratio"))
        timing_w = _timing_weight_from_prediction(session_pred.prediction)

    score_pack = score_pack or _score_intraday_rules(ctx, strategy_hits=0, hard_rejects=[])
    score_120 = int(score_pack.get("score_120", 0))
    tier = str(score_pack.get("tier", ""))
    pos_size = str(score_pack.get("position_size", ""))
    base_reason = str(score_pack.get("reason", ""))
    timing_note = f" · Timing {timing_w:+d}" if timing_w else " · Timing 0"
    rank_why = base_reason + timing_note

    return IntradayResult(
        ticker=raw.replace(".NS", "").replace(".BO", ""),
        raw_ticker=raw,
        strategy=strategy,
        price=round(ctx["price"], 2),
        open_px=round(ctx["open_px"], 2),
        prev_close=round(ctx["prev_close"], 2),
        pct_change=ctx["pct_change"],
        gap_pct=ctx["gap_pct"],
        intraday_high=round(ctx["intraday_high"], 2) if ctx["intraday_high"] else None,
        intraday_low=round(ctx["intraday_low"], 2) if ctx["intraday_low"] else None,
        rsi=ctx["rsi"],
        vol_ratio=ctx["vol_ratio"],
        pct_vs_vwap=ctx["pct_vs_vwap"],
        pct_vs_ma50d=ctx["pct_vs_ma50d"],
        pct_vs_ma200d=ctx["pct_vs_ma200d"],
        pct_vs_52w_high=ctx["pct_vs_52w_high"],
        orb_high=ctx["orb_high"],
        orb_low=ctx["orb_low"],
        setup_note=note_str if not note else (note + " · " + note_str),
        entry=entry,
        stop=stop,
        target=target,
        rr_ratio=rr,
        sector=sector or "—",
        links=get_stock_links(raw),
        session_vol_pct=sess_pct,
        prediction=pred_text,
        score_120=score_120,
        rank_tier=tier,
        rank_why=rank_why,
        position_size=pos_size,
    )


def _evaluate(strategy: str, ctx: dict, flt: IntradayFilters) -> Optional[str]:
    """Return matching note string or None if the strategy doesn't match.

    Assumes universal + signal filters (RSI, volume ratio) already passed.
    """
    rsi = ctx["rsi"]
    vr = ctx["vol_ratio"]
    pct_vwap = ctx["pct_vs_vwap"]
    pct_ema9 = ctx.get("pct_vs_ema9")
    pct_52w = ctx["pct_vs_52w_high"]
    pct_ma50 = ctx["pct_vs_ma50d"]
    pct_ma200 = ctx["pct_vs_ma200d"]
    gap = ctx["gap_pct"]
    pct_chg = ctx["pct_change"]
    price = ctx["price"]
    open_px = ctx["open_px"]
    orb_h = ctx["orb_high"]

    if strategy == "BROAD":
        # Widest net: meaningful move + volume (signal filters already applied).
        move_note = f"{pct_chg:+.2f}% vs prev close"
        return f"Broad mover · {move_note} · vol {vr:.1f}× · RSI {rsi:.1f}"

    if strategy == "VWAP":
        if pct_ma200 is None or pct_ma200 <= 0:
            return None
        if not (42.0 <= rsi <= 65.0):
            return None
        if pct_vwap is None or abs(pct_vwap) > 1.0:
            return None
        if vr < 1.0:
            return None
        return f"price>200DMA · RSI {rsi:.1f} · near VWAP ±1% · vol {vr:.1f}×"

    if strategy == "ORB":
        if not orb_h:
            return None
        if price <= orb_h:
            return None
        if vr < 1.5:
            return None
        if gap <= -2.0:
            return None
        return f"break > ORB {orb_h:.2f} · vol≥{vr:.1f}× · gap>{gap:+.2f}%"

    if strategy == "GAP":
        if gap < 0.5:
            return None
        if price <= open_px:
            return None
        if vr < 1.2:
            return None
        if rsi <= 50.0:
            return None
        if pct_ma50 is None or pct_ma50 <= 0:
            return None
        return f"gap {gap:+.2f}% holding open · RSI {rsi:.1f} · vol {vr:.1f}× · price>50DMA"

    if strategy == "MOMENTUM":
        if rsi < 55.0:
            return None
        if pct_ema9 is None or pct_ema9 <= 0:
            return None
        if vr < 1.2:
            return None
        if pct_chg <= 0:
            return None
        if pct_52w is None or pct_52w < -2.0:
            return None
        return f"RSI≥55 · price>9EMA · day>0 · near 52W high · vol {vr:.1f}×"

    return None


# ─────────────────────────────────────────────────────────────
# Public scanners
# ─────────────────────────────────────────────────────────────
def scan_intraday(
    raw_tickers: list[str],
    strategies: tuple[str, ...] = STRATEGIES,
    filters: Optional[IntradayFilters] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    *,
    market: str = "NSE",
    info_delay_sec: float = 0.05,
) -> tuple[list[IntradayResult], IntradayScanStats]:
    """Run all selected strategies across a ticker list.

    Returns (results, stats) where stats powers the diagnostic funnel panel.
    """
    flt = filters or IntradayFilters()
    results: list[IntradayResult] = []
    stats = IntradayScanStats(total_scanned=len(raw_tickers))
    total = len(raw_tickers)
    session_pred = compute_volume_time_prediction(market)

    for i, raw in enumerate(raw_tickers):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        ctx = _build_context(raw)
        if ctx is None:
            stats.no_data += 1
            continue

        interval = ctx.get("bar_interval") or ""
        if interval == "5m":
            stats.bars_5m += 1
        elif interval == "15m":
            stats.bars_15m += 1

        uni_fail = _universal_fail_reason(ctx, flt)
        if uni_fail == "price":
            stats.failed_price += 1
            continue
        if uni_fail == "avg_volume":
            stats.failed_avg_volume += 1
            continue

        sig_fail = _signal_fail_reason(ctx, flt)
        if sig_fail == "no_rsi":
            stats.failed_no_rsi += 1
            continue
        if sig_fail == "no_volume_ratio":
            stats.failed_no_volume_ratio += 1
            continue
        if sig_fail == "volume_ratio":
            stats.failed_volume_ratio += 1
            continue
        if sig_fail == "rsi":
            stats.failed_rsi += 1
            continue
        if sig_fail == "min_change":
            stats.failed_min_change += 1
            continue

        sector = "—"
        try:
            sector, _ = get_sector_industry(yf.Ticker(raw))
        except Exception:
            sector = "—"

        reject_reasons = _hard_reject_reasons(ctx)
        if reject_reasons:
            stats.failed_hard_reject += 1
            continue

        matched_notes: dict[str, str] = {}
        for strategy in strategies:
            note = _evaluate(strategy, ctx, flt)
            if note:
                matched_notes[strategy] = note

        matched_this = bool(matched_notes)
        score_pack = _score_intraday_rules(
            ctx,
            strategy_hits=len(matched_notes),
            hard_rejects=reject_reasons,
        )
        for strategy, note in matched_notes.items():
            results.append(
                _make_result(
                    raw,
                    strategy,
                    ctx,
                    sector,
                    note,
                    session_pred=session_pred,
                    score_pack=score_pack,
                )
            )

        if matched_this:
            stats.tickers_matched += 1
        else:
            stats.no_strategy_match += 1

        if info_delay_sec > 0:
            time.sleep(info_delay_sec)

    stats.result_rows = len(results)
    results.sort(
        key=lambda r: (
            -(r.score_120 + _timing_weight_from_prediction(r.prediction)),
            -r.score_120,
            -(r.vol_ratio or 0.0),
            -(r.rr_ratio or 0.0),
        )
    )
    return results, stats


# ─────────────────────────────────────────────────────────────
# Gap Scanner
# ─────────────────────────────────────────────────────────────
def scan_gaps(
    raw_tickers: list[str],
    *,
    min_gap_abs_pct: float = 0.5,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    info_delay_sec: float = 0.05,
) -> list[GapResult]:
    """Identify stocks with a meaningful gap-up / gap-down vs prev close."""
    out: list[GapResult] = []
    total = len(raw_tickers)
    for i, raw in enumerate(raw_tickers):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        try:
            bars, _interval = _fetch_intraday_bars(raw)
            daily = _fetch_daily(raw, "10d")
            if bars is None or bars.empty or daily is None or daily.empty:
                continue
            daily_close = hist_series(daily, "Close").astype(float).dropna()
            if daily_close.empty or len(daily_close) < 2:
                continue
            prev_close = float(daily_close.iloc[-2])
            # session-local
            try:
                last_date = bars.index[-1].date()
                session = bars[bars.index.date == last_date]
            except Exception:
                session = bars
            if session.empty:
                continue
            open_px = float(hist_series(session, "Open").iloc[0])
            current_price = float(hist_series(session, "Close").iloc[-1])
            intra_h = float(hist_series(session, "High").max())
            intra_l = float(hist_series(session, "Low").min())

            gap_pct = _safe_pct(open_px, prev_close) or 0.0
            if abs(gap_pct) < min_gap_abs_pct:
                continue
            open_to_now_pct = _safe_pct(current_price, open_px) or 0.0

            size_band, direction = _gap_category(gap_pct)
            if direction == "UP":
                holding = current_price >= open_px * 0.999
            elif direction == "DOWN":
                holding = current_price <= open_px * 1.001
            else:
                holding = False

            vols = hist_series(bars, "Volume").astype(float).dropna()
            vol_ratio: Optional[float] = None
            if len(vols) >= 6:
                lookback = min(20, len(vols) - 1)
                avg = float(vols.iloc[-(lookback + 1):-1].mean())
                if avg > 0:
                    vol_ratio = round(float(vols.iloc[-1]) / avg, 2)

            sector = "—"
            try:
                sector, _ = get_sector_industry(yf.Ticker(raw))
            except Exception:
                pass

            out.append(
                GapResult(
                    ticker=raw.replace(".NS", "").replace(".BO", ""),
                    raw_ticker=raw,
                    prev_close=round(prev_close, 2),
                    open_px=round(open_px, 2),
                    current_price=round(current_price, 2),
                    intraday_high=round(intra_h, 2),
                    intraday_low=round(intra_l, 2),
                    gap_pct=round(gap_pct, 2),
                    open_to_now_pct=round(open_to_now_pct, 2),
                    direction=direction,
                    size_band=size_band,
                    holding=holding,
                    advice=_gap_advice(gap_pct, holding, open_to_now_pct, vol_ratio),
                    vol_ratio=vol_ratio,
                    sector=sector or "—",
                    links=get_stock_links(raw),
                )
            )
        except Exception:
            continue
        if info_delay_sec > 0:
            time.sleep(info_delay_sec)
    out.sort(key=lambda g: -abs(g.gap_pct))
    return out


def compute_market_mood(gaps: list[GapResult]) -> tuple[str, str]:
    """Bullish / Bearish / Mixed market mood based on gap distribution."""
    if not gaps:
        return ("Unknown", "No gap data yet — run the scan after 9:15 AM IST.")
    ups = sum(1 for g in gaps if g.direction == "UP" and g.size_band in ("Medium", "Large"))
    downs = sum(1 for g in gaps if g.direction == "DOWN" and g.size_band in ("Medium", "Large"))
    large_ups = sum(1 for g in gaps if g.direction == "UP" and g.size_band == "Large")
    large_downs = sum(1 for g in gaps if g.direction == "DOWN" and g.size_band == "Large")
    if ups >= 2 * max(downs, 1) and (large_ups - large_downs) >= 1:
        return ("Bullish",
                f"{ups} meaningful gap-ups vs {downs} gap-downs · {large_ups} large gap-ups. "
                "Favour long setups (ORB / momentum).")
    if downs >= 2 * max(ups, 1) and (large_downs - large_ups) >= 1:
        return ("Bearish",
                f"{downs} meaningful gap-downs vs {ups} gap-ups · {large_downs} large gap-downs. "
                "Be selective; consider only mean-reversion longs at strong support.")
    return ("Mixed",
            f"{ups} gap-ups vs {downs} gap-downs · no clear directional bias. "
            "Wait for ORB before committing size.")


def resolve_universe(name: str, market: str = "NSE") -> list[str]:
    """Return raw tickers for an intraday-supported universe name.

    `market` lets callers disambiguate when a label exists in both markets;
    falls back to a global search across both market dictionaries.
    """
    mkt = (market or "NSE").upper()
    if mkt in INTRADAY_UNIVERSES_BY_MARKET and name in INTRADAY_UNIVERSES_BY_MARKET[mkt]:
        return list(INTRADAY_UNIVERSES_BY_MARKET[mkt][name])
    # Search other market dictionaries by label.
    for m, dct in INTRADAY_UNIVERSES_BY_MARKET.items():
        if name in dct:
            return list(dct[name])
    # Fall back to global UNIVERSES with light suffix filter.
    if name in UNIVERSES:
        tickers = UNIVERSES[name]
        if mkt == "US":
            return [t for t in tickers if not t.endswith((".NS", ".BO"))]
        return [t for t in tickers if t.endswith((".NS", ".BO"))]
    return []


# ─────────────────────────────────────────────────────────────
# Time-of-day volume prediction (session volume curve)
# Price moves only when volume is there — no volume = fake moves.
# ─────────────────────────────────────────────────────────────
@dataclass
class VolumeTimePrediction:
    """Session volume % and tradeability label at scan time."""
    session_vol_pct: int
    prediction: str
    market_local_time: str
    mins_since_open: int
    is_session_open: bool


# (minutes since regular open, typical session volume %)
_NSE_VOL_CURVE: list[tuple[int, int]] = [
    (0, 100),     # 9:15 AM — real but wild
    (45, 80),     # 10:00 AM — best window
    (165, 20),    # 12:00 PM — lunch fake moves
    (315, 60),    # 2:30 PM — afternoon good
    (370, 90),    # 3:25 PM — forced / dangerous
    (375, 85),    # 3:30 PM close
]

_US_VOL_CURVE: list[tuple[int, int]] = [
    (0, 100),     # 9:30 AM ET
    (30, 80),     # 10:00 AM ET
    (150, 20),    # 12:00 PM ET
    (300, 60),    # 2:30 PM ET
    (355, 90),    # 3:25 PM ET
    (390, 85),    # 4:00 PM ET close
]


def _interp_session_vol_pct(mins_since_open: float, curve: list[tuple[int, int]]) -> int:
    if mins_since_open <= curve[0][0]:
        return curve[0][1]
    if mins_since_open >= curve[-1][0]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        m0, p0 = curve[i]
        m1, p1 = curve[i + 1]
        if m0 <= mins_since_open <= m1:
            t = (mins_since_open - m0) / max(m1 - m0, 1)
            return int(round(p0 + t * (p1 - p0)))
    return curve[-1][1]


def _volume_prediction_label(pct: int, mins: int, *, is_open: bool) -> str:
    """Map interpolated session volume % to the playbook labels."""
    if not is_open and mins < 0:
        return "⏸ Pre-market · session volume building"
    if not is_open:
        return "🔴 Market closed · volume curve resets next session"

    # Anchor windows (minutes since open) — NSE/US share the same playbook shape.
    if mins <= 25 and pct >= 90:
        return f"⚡ Real moves · Too wild ({pct}% vol) — wait for 10:00 window"
    if 25 <= mins <= 75 and pct >= 65:
        return f"✅ Real moves · Best time ({pct}% vol)"
    if 120 <= mins <= 210 and pct <= 35:
        return f"❌ Fake moves · Avoid ({pct}% vol) — lunch lull"
    if 270 <= mins <= 330 and 45 <= pct <= 75:
        return f"✅ Real moves · Good ({pct}% vol) — afternoon session"
    if mins >= 340 and pct >= 82:
        return f"❌ Forced moves · Dangerous ({pct}% vol) — square off soon"

    if pct <= 30:
        return f"❌ Fake moves likely ({pct}% vol) — low participation"
    if pct >= 85:
        return f"⚠ Forced / climax risk ({pct}% vol) — tighten risk"
    if pct >= 55:
        return f"✅ Real moves ({pct}% vol) — price more trustworthy"
    return f"⚠ Mixed quality ({pct}% vol) — use smaller size"


def compute_volume_time_prediction(market: str = "NSE") -> VolumeTimePrediction:
    """Estimate typical session volume % and tradeability at the current clock time."""
    mkt = (market or "NSE").upper()
    if mkt == "US":
        now = _now_tz(US_TZ)
        open_mins = US_OPEN_HOUR * 60 + US_OPEN_MIN
        close_mins = US_CLOSE_HOUR * 60 + US_CLOSE_MIN
        curve = _US_VOL_CURVE
        tz_label = "ET"
    else:
        now = _now_tz(NSE_TZ)
        open_mins = NSE_OPEN_HOUR * 60 + NSE_OPEN_MIN
        close_mins = NSE_CLOSE_HOUR * 60 + NSE_CLOSE_MIN
        curve = _NSE_VOL_CURVE
        tz_label = "IST"

    clock_mins = now.hour * 60 + now.minute
    mins_since_open = clock_mins - open_mins
    is_open = open_mins <= clock_mins < close_mins

    if is_open:
        pct = _interp_session_vol_pct(mins_since_open, curve)
    elif mins_since_open < 0:
        pct = curve[0][1]
    else:
        pct = curve[-1][1]

    label = _volume_prediction_label(pct, max(mins_since_open, 0), is_open=is_open)
    return VolumeTimePrediction(
        session_vol_pct=pct,
        prediction=label,
        market_local_time=now.strftime(f"%H:%M {tz_label}"),
        mins_since_open=mins_since_open,
        is_session_open=is_open,
    )


# ─────────────────────────────────────────────────────────────
# Market-aware time-window helpers
# ─────────────────────────────────────────────────────────────
NSE_OPEN_HOUR = 9
NSE_OPEN_MIN = 15
NSE_CLOSE_HOUR = 15
NSE_CLOSE_MIN = 30

US_OPEN_HOUR = 9
US_OPEN_MIN = 30
US_CLOSE_HOUR = 16
US_CLOSE_MIN = 0

# Time zones (tz-aware via zoneinfo).
NSE_TZ = "Asia/Kolkata"
US_TZ = "America/New_York"
CEST_TZ = "Europe/Berlin"      # auto switches CET ↔ CEST


def _now_tz(tz_name: str):
    """Return tz-aware datetime, falling back to local naive on Python < 3.9."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()


def market_session_window(market: str = "NSE") -> dict:
    """Return a rich session-window descriptor for the given market.

    Keys:
      market:           "NSE" / "US"
      market_local_str: e.g. "14:30 IST" / "09:45 ET"
      cest_str:         e.g. "11:00 CEST"
      window:           short label, e.g. "🔥 Momentum window"
      tip:              one-line guidance for the current window
      is_open:          bool — whether the market regular session is currently open
    """
    mkt = (market or "NSE").upper()
    cest_now = _now_tz(CEST_TZ)
    cest_str = cest_now.strftime("%H:%M CEST")

    if mkt == "US":
        market_now = _now_tz(US_TZ)
        mins = market_now.hour * 60 + market_now.minute
        market_local_str = market_now.strftime("%H:%M ET")
        if mins < 7 * 60:
            window, tip = "Too early", "Wait for pre-market (after 7:00 AM ET)."
            is_open = False
        elif mins < 9 * 60 + 30:
            window, tip = "Pre-market", "Scan gaps · plan ORB · don't trade yet."
            is_open = False
        elif mins < 9 * 60 + 45:
            window, tip = "ORB forming (9:30–9:45 AM ET)", "Mark ORB high/low · no entries yet."
            is_open = True
        elif mins < 11 * 60:
            window = "🔥 Opening hour (9:45–11:00 AM ET)"
            tip = "Highest volatility · ORB breaks + momentum work best now."
            is_open = True
        elif mins < 13 * 60 + 30:
            window = "📈 Mid-morning (11:00 AM – 1:30 PM ET)"
            tip = "VWAP-pullback window · take fewer, cleaner trades."
            is_open = True
        elif mins < 15 * 60:
            window = "⏸ Mid-day chop (1:30–3:00 PM ET)"
            tip = "Low conviction window — wait for power hour."
            is_open = True
        elif mins < 16 * 60:
            window = "💥 Power hour (3:00–4:00 PM ET)"
            tip = "End-of-day momentum — close before 3:55 PM ET, no overnight."
            is_open = True
        else:
            window = "Session over"
            tip = "US regular session closed (4:00 PM ET). Plan tomorrow's setups."
            is_open = False
        return {
            "market": "US",
            "market_local_str": market_local_str,
            "cest_str": cest_str,
            "window": window,
            "tip": tip,
            "is_open": is_open,
        }

    # NSE / India
    market_now = _now_tz(NSE_TZ)
    mins = market_now.hour * 60 + market_now.minute
    market_local_str = market_now.strftime("%H:%M IST")
    if mins < 8 * 60 + 30:
        window, tip = "Too early", "Pre-pre-market — wait until 8:30 AM IST."
        is_open = False
    elif mins < 9 * 60 + 15:
        window = "Pre-open"
        tip = "Scan gaps · mark ORB plan — don't trade yet."
        is_open = False
    elif mins < 9 * 60 + 30:
        window = "ORB forming (9:15–9:30 AM IST)"
        tip = "Mark ORB high/low · no entries yet."
        is_open = True
    elif mins < 11 * 60:
        window = "🔥 Momentum window (9:30–11:00 AM IST)"
        tip = "Highest volatility & ORB breaks — best window of the day."
        is_open = True
    elif mins < 13 * 60:
        window = "📈 VWAP pullback (10:30 AM – 1:00 PM IST)"
        tip = "Take fewer, cleaner trades aligned with VWAP."
        is_open = True
    elif mins < 14 * 60:
        window = "⏸ Lunch lull (1:00–2:00 PM IST)"
        tip = "Low conviction — avoid forcing trades."
        is_open = True
    elif mins < 15 * 60 + 15:
        window = "💥 End-of-day (2:00–3:15 PM IST)"
        tip = "Momentum trades only · square off before 3:20 PM IST."
        is_open = True
    else:
        window = "Session over"
        tip = "NSE session closed (3:30 PM IST). Plan tomorrow's setups."
        is_open = False
    return {
        "market": "NSE",
        "market_local_str": market_local_str,
        "cest_str": cest_str,
        "window": window,
        "tip": tip,
        "is_open": is_open,
    }


def session_window_now(market: str = "NSE") -> str:
    """Plain-text session label including both market-local and CEST time."""
    s = market_session_window(market)
    flag = "🇺🇸" if s["market"] == "US" else "🇮🇳"
    return f"{flag} {s['window']} · Now: {s['market_local_str']} / {s['cest_str']} · {s['tip']}"
