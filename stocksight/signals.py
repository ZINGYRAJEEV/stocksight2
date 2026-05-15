"""
signals.py — Trading signal detection engine.

Six scenarios derived from the strategy table:
  1. Oversold Bounce       — PE 5–50, Vol ≥2×, RSI 30–40 rising
  2. Breakout Momentum     — PE 5–50, Vol ≥3×, RSI 50–65 rising
  3. Value + Technical     — PE 5–15, Vol 1.5–2×, RSI 40–55
  4. Overbought / Exit     — Any PE, Vol ≥2×, RSI >75
  5. Extreme Oversold      — Any PE, Vol ≥2×, RSI <25
  6. Volume No Confirm     — Vol ≥2×, RSI ambiguous (25–50 or 65–75)

Each scenario returns a list of SignalResult objects with full trade plan.
"""

from __future__ import annotations
import yfinance as yf
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

import warnings
warnings.filterwarnings("ignore")

from screener import (
    UNIVERSES,
    PE_DATA_CAP,
    get_pe,
    compute_rsi,
    compute_volume_ratio,
    get_stock_links,
    fetch_price_history,
    min_bars_for_screen,
    compute_macd,
    compute_atr,
    compute_bollinger_pct_b,
    ma_cross_recent,
    pct_vs_ma,
    get_sector_industry,
    next_earnings_label,
    fetch_quote_news,
)


# ─────────────────────────────────────────────────────────────
# Data Class — one row of output per stock per scenario
# ─────────────────────────────────────────────────────────────

@dataclass
class SignalResult:
    ticker:        str
    raw_ticker:    str
    currency:      str
    price:         float
    pe:            float
    vol_ratio:     float
    rsi:           float
    rsi_prev:      float          # RSI 3 bars ago — to confirm direction
    rsi_rising:    bool

    # Candle flags
    is_green:      bool           # close > open on latest bar
    reversal:      bool           # close > previous close AND low > prev low

    # Trade plan
    entry:         float          # suggested entry (current price as trigger)
    stop_loss:     float          # below recent swing low
    swing_low:     float          # raw swing low used for SL calc
    target1:       float          # 1× risk
    target2:       float          # 1.5× risk
    target3:       float          # 2.5–3× risk
    risk_pct:      float          # (entry - stop) / entry × 100
    rrr:           float          # reward-risk ratio to target2

    # Metadata
    scenario_id:   str
    signal_label:  str            # BUY / SELL / CAUTIOUS BUY / HOLD-WAIT
    timeframe:     str
    note:          str
    confidence:    str            # HIGH / MEDIUM / LOW
    links:         dict = field(default_factory=dict)

    # Bar / context
    data_interval: str = "1d"

    # Fundamentals / classification
    sector: Optional[str] = None
    industry: Optional[str] = None
    next_earnings: Optional[str] = None

    # Indicators (last bar)
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    macd_bullish: bool = False

    ma20: Optional[float] = None
    ma50: Optional[float] = None
    pct_vs_ma20: Optional[float] = None
    golden_cross_recent: bool = False

    bb_pct_b: Optional[float] = None
    bb_touch_lower: bool = False

    atr14: Optional[float] = None

    news_headlines: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _swing_low(lows: pd.Series, lookback: int = 10) -> float:
    """Lowest low in the last `lookback` bars, excluding today."""
    window = lows.iloc[-(lookback + 1):-1]
    return round(float(window.min()), 2)


def _swing_high(highs: pd.Series, lookback: int = 10) -> float:
    """Highest high in the last `lookback` bars, excluding today."""
    window = highs.iloc[-(lookback + 1):-1]
    return round(float(window.max()), 2)


def _resistance(highs: pd.Series, lookback: int = 20) -> float:
    return _swing_high(highs, lookback)


def _confidence(vol_ratio: float, rsi_rising: bool, reversal: bool,
                is_green: bool, scenario_id: str, macd_bullish: bool = False) -> str:
    score = 0
    if vol_ratio >= 3:   score += 2
    elif vol_ratio >= 2: score += 1
    if rsi_rising:       score += 1
    if reversal:         score += 2
    if is_green:         score += 1
    if macd_bullish:      score += 1
    if scenario_id == "breakout" and vol_ratio >= 3 and rsi_rising:
        score += 1
    if score >= 5:   return "HIGH"
    if score >= 3:   return "MEDIUM"
    return "LOW"


def _passes_advanced_filters(
    ex: dict,
    sector_filter: Optional[str],
    require_macd: bool,
    require_bb_lower: bool,
) -> bool:
    if sector_filter and sector_filter.strip():
        needle = sector_filter.strip().lower()
        hay = (ex.get("sector") or "").lower()
        if needle not in hay:
            return False
    if require_macd and not ex.get("macd_bullish"):
        return False
    if require_bb_lower and not ex.get("bb_touch_lower"):
        return False
    return True


def _build_result(
    ticker: str,
    hist: pd.DataFrame,
    pe: float,
    vol_ratio: float,
    rsi: float,
    rsi_prev: float,
    scenario_id: str,
    signal_label: str,
    timeframe: str,
    note: str,
    sl_lookback: int = 10,
    target_ratios: tuple = (1.0, 1.5, 2.5),
    is_sell: bool = False,
    extras: Optional[dict] = None,
    bar_interval: str = "1d",
) -> SignalResult:
    closes  = hist["Close"]
    lows    = hist["Low"]
    highs   = hist["High"]
    opens   = hist["Open"]

    is_nse    = ticker.endswith(".NS") or ticker.endswith(".BO")
    currency  = "₹" if is_nse else "$"
    clean     = ticker.replace(".NS", "").replace(".BO", "")
    price     = round(float(closes.iloc[-1]), 2)

    is_green  = float(closes.iloc[-1]) > float(opens.iloc[-1])
    reversal  = (float(closes.iloc[-1]) > float(closes.iloc[-2]) and
                 float(lows.iloc[-1])   > float(lows.iloc[-2]))
    rsi_rising = rsi > rsi_prev

    sw_low    = _swing_low(lows, sl_lookback)
    # Add a 0.5% buffer below swing low for stop
    stop_loss = round(sw_low * 0.995, 2)
    risk      = price - stop_loss

    if is_sell:
        # For sell signals, targets are downside levels
        entry    = price
        target1  = round(price * 0.97,  2)   # take 3% off table
        target2  = round(price * 0.93,  2)   # 7% correction
        target3  = round(price * 0.88,  2)   # 12% deeper
        risk_pct = 0.0
        rrr      = 0.0
    else:
        entry    = price
        if risk > 0:
            target1 = round(entry + risk * target_ratios[0], 2)
            target2 = round(entry + risk * target_ratios[1], 2)
            target3 = round(entry + risk * target_ratios[2], 2)
            risk_pct = round(risk / entry * 100, 2)
            rrr      = round(target_ratios[1], 1)
        else:
            # Risk = 0 means price is at/below swing low — use fixed %
            target1 = round(entry * 1.03, 2)
            target2 = round(entry * 1.05, 2)
            target3 = round(entry * 1.08, 2)
            risk_pct = 1.5
            rrr      = 1.5

    confidence = _confidence(
        vol_ratio, rsi_rising, reversal, is_green, scenario_id,
        macd_bullish=bool((extras or {}).get("macd_bullish")),
    )

    ex = extras or {}
    macd_line_v = ex.get("macd_line")
    macd_sig_v = ex.get("macd_signal")
    macd_hist_v = ex.get("macd_hist")
    ma20_v = ex.get("ma20")
    ma50_v = ex.get("ma50")
    bb_pb = ex.get("bb_pct_b")
    atr_v = ex.get("atr14")

    def _finite_num(v):
        if v is None:
            return None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        if np.isnan(fv):
            return None
        return fv

    return SignalResult(
        ticker       = clean,
        raw_ticker   = ticker,
        currency     = currency,
        price        = price,
        pe           = round(pe, 2),
        vol_ratio    = round(vol_ratio, 2),
        rsi          = round(rsi, 1),
        rsi_prev     = round(rsi_prev, 1),
        rsi_rising   = rsi_rising,
        is_green     = is_green,
        reversal     = reversal,
        entry        = entry,
        stop_loss    = stop_loss,
        swing_low    = sw_low,
        target1      = target1,
        target2      = target2,
        target3      = target3,
        risk_pct     = risk_pct,
        rrr          = rrr,
        scenario_id  = scenario_id,
        signal_label = signal_label,
        timeframe    = timeframe,
        note         = note,
        confidence   = confidence,
        links        = get_stock_links(ticker),
        data_interval = bar_interval,
        sector       = (ex.get("sector") or None) or None,
        industry     = (ex.get("industry") or None) or None,
        next_earnings = (ex.get("next_earnings") or None) or None,
        macd_line    = _finite_num(macd_line_v),
        macd_signal  = _finite_num(macd_sig_v),
        macd_hist    = _finite_num(macd_hist_v),
        macd_bullish = bool(ex.get("macd_bullish")),
        ma20         = _finite_num(ma20_v),
        ma50         = _finite_num(ma50_v),
        pct_vs_ma20  = _finite_num(ex.get("pct_vs_ma20")),
        golden_cross_recent = bool(ex.get("golden_cross_recent")),
        bb_pct_b     = _finite_num(bb_pb),
        bb_touch_lower = bool(ex.get("bb_touch_lower")),
        atr14        = _finite_num(atr_v),
        news_headlines = list(ex.get("news_headlines") or []),
    )


# ─────────────────────────────────────────────────────────────
# Core fetch — shared across all scenarios
# ─────────────────────────────────────────────────────────────

def _fetch(ticker: str, interval_key: str = "1d"):
    """
    Returns (hist_df, pe, vol_ratio, rsi, rsi_prev, extras_dict) or None on failure.
    """
    try:
        stk = yf.Ticker(ticker)
        hist = fetch_price_history(ticker, interval_key)
        min_bar = min_bars_for_screen(interval_key)
        if hist.empty or len(hist) < min_bar:
            return None

        pe = get_pe(stk)
        if pe is None:
            pe = 9999

        vol_ratio = compute_volume_ratio(hist["Volume"])
        if vol_ratio is None or np.isnan(vol_ratio):
            return None

        rsi_series = _full_rsi(hist["Close"])
        if len(rsi_series) < 4:
            return None
        rsi      = round(float(rsi_series.iloc[-1]),  1)
        rsi_prev = round(float(rsi_series.iloc[-4]),  1)

        closes = hist["Close"]
        highs = hist["High"]
        lows = hist["Low"]
        px = float(closes.iloc[-1])

        ma20_s = closes.rolling(20).mean()
        ma50_s = closes.rolling(50).mean()
        ma20 = float(ma20_s.iloc[-1]) if len(closes) >= 20 else float("nan")
        ma50 = float(ma50_s.iloc[-1]) if len(closes) >= 50 else float("nan")

        macd_l, macd_sig, macd_h = compute_macd(closes)
        bb_pct_b, _bb_m, _bb_u, bb_l = compute_bollinger_pct_b(closes)
        atr_v = compute_atr(highs, lows, closes)
        gc = ma_cross_recent(ma20_s, ma50_s, lookback=5)

        sector, industry = get_sector_industry(stk)
        earn = next_earnings_label(stk)

        touch_lower = False
        if bb_l == bb_l and not np.isnan(bb_l):
            bl = float(bb_l)
            touch_lower = px <= bl * 1.005
            if bb_pct_b == bb_pct_b and not np.isnan(bb_pct_b):
                touch_lower = touch_lower or float(bb_pct_b) <= 0.08

        macd_bull = bool(not np.isnan(macd_h) and macd_h > 0)

        extras = {
            "sector": sector,
            "industry": industry,
            "macd_line": macd_l,
            "macd_signal": macd_sig,
            "macd_hist": macd_h,
            "macd_bullish": macd_bull,
            "ma20": ma20,
            "ma50": ma50,
            "pct_vs_ma20": pct_vs_ma(px, ma20),
            "golden_cross_recent": gc,
            "bb_pct_b": bb_pct_b,
            "bb_touch_lower": touch_lower,
            "atr14": atr_v,
            "next_earnings": earn,
            "news_headlines": [],
        }

        return hist, pe, vol_ratio, rsi, rsi_prev, extras
    except Exception:
        return None


def enrich_results_news(results: list[SignalResult], limit_per_ticker: int = 3) -> None:
    """Populate news headlines (extra Yahoo calls — use only for small result sets)."""
    for r in results:
        r.news_headlines = fetch_quote_news(r.raw_ticker, limit_per_ticker)


def _full_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta    = closes.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─────────────────────────────────────────────────────────────
# Scenario 1 — Oversold Bounce
# PE 5–50 · Vol ≥2× · RSI 30–40 · RSI rising
# ─────────────────────────────────────────────────────────────

def scan_oversold_bounce(
    universe_name: str,
    pe_max: float = 50.0,
    vol_min: float = 2.0,
    rsi_min: float = 30.0,
    rsi_max: float = 40.0,
    progress_cb=None,
    sector_filter: Optional[str] = None,
    interval_key: str = "1d",
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = UNIVERSES.get(universe_name, [])
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(ticker, interval_key)
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(ex, sector_filter, require_macd_bullish, require_bb_touch_lower):
            continue

        if not (5 <= pe <= pe_max):   continue
        if vol_ratio < vol_min:       continue
        if not (rsi_min <= rsi <= rsi_max): continue
        if rsi <= rsi_prev:           continue   # must be rising

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "oversold_bounce",
            signal_label = "BUY",
            timeframe    = "Swing · 3–21 days",
            note         = "Oversold bounce after panic. Confirm no negative news. Enter only on green reversal candle.",
            sl_lookback  = 10,
            target_ratios= (1.0, 2.0, 3.0),
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.vol_ratio, reverse=True)


# ─────────────────────────────────────────────────────────────
# Scenario 2 — Breakout Momentum
# PE 5–50 · Vol ≥3× · RSI 50–65 rising
# ─────────────────────────────────────────────────────────────

def scan_breakout_momentum(
    universe_name: str,
    pe_max: float = 50.0,
    vol_min: float = 3.0,
    rsi_min: float = 50.0,
    rsi_max: float = 65.0,
    progress_cb=None,
    sector_filter: Optional[str] = None,
    interval_key: str = "1d",
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = UNIVERSES.get(universe_name, [])
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(ticker, interval_key)
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(ex, sector_filter, require_macd_bullish, require_bb_touch_lower):
            continue

        if not (5 <= pe <= pe_max):   continue
        if vol_ratio < vol_min:       continue
        if not (rsi_min <= rsi <= rsi_max): continue
        if rsi <= rsi_prev:           continue   # RSI crossing upward

        # Extra: price must be above 20-period MA (momentum confirmation)
        ma20 = hist["Close"].rolling(20).mean().iloc[-1]
        if hist["Close"].iloc[-1] < ma20:
            continue

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "breakout",
            signal_label = "BUY",
            timeframe    = "Momentum · 1–8 weeks",
            note         = "Volume confirms breakout. Trail with 10–20% stop or scale out at 20–40% gain.",
            sl_lookback  = 5,   # stop below breakout candle low
            target_ratios= (1.0, 1.5, 2.5),
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.vol_ratio, reverse=True)


# ─────────────────────────────────────────────────────────────
# Scenario 3 — Value + Technical
# PE 5–15 · Vol 1.5–2× · RSI 40–55
# ─────────────────────────────────────────────────────────────

def scan_value_technical(
    universe_name: str,
    pe_max: float = 15.0,
    vol_min: float = 1.5,
    rsi_min: float = 40.0,
    rsi_max: float = 55.0,
    progress_cb=None,
    sector_filter: Optional[str] = None,
    interval_key: str = "1d",
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = UNIVERSES.get(universe_name, [])
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(ticker, interval_key)
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(ex, sector_filter, require_macd_bullish, require_bb_touch_lower):
            continue

        if not (5 <= pe <= pe_max):   continue
        if vol_ratio < vol_min:       continue
        if not (rsi_min <= rsi <= rsi_max): continue

        # Pullback to MA: price near 20-day MA (within 4%)
        ma20 = hist["Close"].rolling(20).mean().iloc[-1]
        price = hist["Close"].iloc[-1]
        if abs(price - ma20) / ma20 > 0.04:
            continue

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "value_technical",
            signal_label = "BUY",
            timeframe    = "Long · 1–6 months",
            note         = "Undervalued with improving technicals. Slower entry — add on confirmation. Target 30–60% gain.",
            sl_lookback  = 20,  # wider stop for long-term
            target_ratios= (1.0, 2.0, 4.0),
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.pe)   # lowest PE first


# ─────────────────────────────────────────────────────────────
# Scenario 4 — Overbought / Exit
# Any PE · Vol ≥2× · RSI >75
# ─────────────────────────────────────────────────────────────

def scan_overbought_exit(
    universe_name: str,
    pe_max: float = 300.0,
    vol_min: float = 2.0,
    rsi_min: float = 75.0,
    rsi_max: float = 100.0,
    progress_cb=None,
    sector_filter: Optional[str] = None,
    interval_key: str = "1d",
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = UNIVERSES.get(universe_name, [])
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(ticker, interval_key)
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(ex, sector_filter, require_macd_bullish, require_bb_touch_lower):
            continue

        if pe > pe_max:               continue
        if vol_ratio < vol_min:       continue
        if rsi <= rsi_min:            continue
        if rsi > rsi_max:             continue

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "overbought",
            signal_label = "SELL / AVOID",
            timeframe    = "Short term · Days",
            note         = "RSI extreme with volume often signals exhaustion. Tighten stop to breakeven. Take profits in tranches.",
            sl_lookback  = 5,
            target_ratios= (1.0, 1.5, 2.5),
            is_sell      = True,
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.rsi, reverse=True)


# ─────────────────────────────────────────────────────────────
# Scenario 5 — Extreme Oversold
# Any PE · Vol ≥2× · RSI <25
# ─────────────────────────────────────────────────────────────

def scan_extreme_oversold(
    universe_name: str,
    pe_max: float = 300.0,
    vol_min: float = 2.0,
    rsi_max: float = 25.0,
    progress_cb=None,
    sector_filter: Optional[str] = None,
    interval_key: str = "1d",
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = UNIVERSES.get(universe_name, [])
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(ticker, interval_key)
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(ex, sector_filter, require_macd_bullish, require_bb_touch_lower):
            continue

        if pe > pe_max:           continue
        if vol_ratio < vol_min:   continue
        if rsi > rsi_max:         continue

        # Require a reversal candle OR RSI starting to tick up
        closes = hist["Close"]
        opens  = hist["Open"]
        lows   = hist["Low"]
        is_green  = float(closes.iloc[-1]) > float(opens.iloc[-1])
        rsi_ticking_up = rsi > rsi_prev

        if not (is_green or rsi_ticking_up):
            continue

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "extreme_oversold",
            signal_label = "CAUTIOUS BUY",
            timeframe    = "Speculative Swing",
            note         = "Very oversold — could be value trap or distress. Require positive news catalyst. Small position only, scale if confirmed.",
            sl_lookback  = 7,
            target_ratios= (0.5, 1.0, 1.5),
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.rsi)   # lowest RSI first (most extreme)


# ─────────────────────────────────────────────────────────────
# Scenario 6 — Volume Spike, No RSI Confirmation
# Vol ≥2× · RSI in ambiguous zone (25–50 or 65–75)
# ─────────────────────────────────────────────────────────────

def scan_volume_no_confirm(
    universe_name: str,
    pe_max: float = 300.0,
    vol_min: float = 2.0,
    rsi_min: float = 25.0,
    rsi_max: float = 75.0,
    progress_cb=None,
    sector_filter: Optional[str] = None,
    interval_key: str = "1d",
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = UNIVERSES.get(universe_name, [])
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(ticker, interval_key)
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(ex, sector_filter, require_macd_bullish, require_bb_touch_lower):
            continue

        if pe > pe_max:       continue
        if vol_ratio < vol_min:  continue
        # Ambiguous RSI: not oversold, not overbought, not clearly in breakout zone
        in_ambiguous = (rsi_min < rsi < 50) or (65 < rsi < rsi_max)
        if not in_ambiguous:
            continue

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "volume_no_confirm",
            signal_label = "HOLD / WAIT",
            timeframe    = "Intraday to Swing",
            note         = "Volume alone is ambiguous — direction unconfirmed. Wait 1–3 bars for RSI or price confirmation before acting.",
            sl_lookback  = 10,
            target_ratios= (1.0, 1.5, 2.0),
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.vol_ratio, reverse=True)


# ─────────────────────────────────────────────────────────────
# Scenario Registry
# ─────────────────────────────────────────────────────────────

SCENARIOS = {
    "oversold_bounce":   {
        "fn":          scan_oversold_bounce,
        "title":       "Oversold Bounce",
        "emoji":       "📉",
        "signal":      "BUY",
        "color":       "#00e5a0",
        "badge_bg":    "#0a2e1e",
        "description": "Panic-sold stocks showing first signs of recovery. PE 5–50 · Vol ≥2× · RSI 30–40 rising.",
        "entry_note":  "Enter on green reversal candle with RSI rising above 35.",
        "sl_note":     "Stop below recent swing low (1–2% portfolio risk).",
        "target_note": "Target 1 = 1× risk · Target 2 = 2× risk · Target 3 = 3× risk.",
    },
    "breakout_momentum": {
        "fn":          scan_breakout_momentum,
        "title":       "Breakout Momentum",
        "emoji":       "🚀",
        "signal":      "BUY",
        "color":       "#4db8ff",
        "badge_bg":    "#0a1e2e",
        "description": "High-volume breakouts above resistance with rising RSI. PE 5–50 · Vol ≥3× · RSI 50–65 rising.",
        "entry_note":  "Enter on break above resistance candle close, above 20-day MA.",
        "sl_note":     "Stop below breakout candle low. Trail with 10–20% once in profit.",
        "target_note": "Scale out at 20–40% gain. Target 2 = 1.5× risk.",
    },
    "value_technical":   {
        "fn":          scan_value_technical,
        "title":       "Value + Technical",
        "emoji":       "💎",
        "signal":      "BUY",
        "color":       "#f0b429",
        "badge_bg":    "#2a1e00",
        "description": "Undervalued stocks pulling back to MA with modest volume uptick. PE 5–15 · Vol 1.5–2× · RSI 40–55.",
        "entry_note":  "Enter on pullback to 20-day MA with RSI stabilizing.",
        "sl_note":     "Stop below fundamental support or 20% from entry.",
        "target_note": "Hold until fundamentals improve or 30–60% gain reached.",
    },
    "overbought_exit":   {
        "fn":          scan_overbought_exit,
        "title":       "Overbought / Exit Signal",
        "emoji":       "🔴",
        "signal":      "SELL",
        "color":       "#ff4d4d",
        "badge_bg":    "#2e0a0a",
        "description": "Extended stocks showing exhaustion signals. Any PE · Vol ≥2× · RSI >75.",
        "entry_note":  "If holding: tighten stop to breakeven + small buffer.",
        "sl_note":     "Do NOT open new longs. Exit in tranches on further weakness.",
        "target_note": "Profit target: T1 −3% · T2 −7% · T3 −12% from current price.",
    },
    "extreme_oversold":  {
        "fn":          scan_extreme_oversold,
        "title":       "Extreme Oversold",
        "emoji":       "⚡",
        "signal":      "CAUTIOUS BUY",
        "color":       "#ff9d42",
        "badge_bg":    "#2e1a00",
        "description": "Severely oversold on heavy volume — may be distress or capitulation. Any PE · Vol ≥2× · RSI <25.",
        "entry_note":  "Require positive news catalyst + reversal candle before entry.",
        "sl_note":     "Tight stop below reversal low. Small position only.",
        "target_note": "Scale in if confirmed. T1 = 0.5× risk · T2 = 1× risk.",
    },
    "volume_no_confirm": {
        "fn":          scan_volume_no_confirm,
        "title":       "Volume Spike — Awaiting Confirmation",
        "emoji":       "⏸️",
        "signal":      "WAIT",
        "color":       "#a0a0a0",
        "badge_bg":    "#1a1a1a",
        "description": "High volume without RSI direction clarity — ambiguous signal. Vol ≥2× · RSI in 25–50 or 65–75 zone.",
        "entry_note":  "Do NOT enter yet. Watch for 1–3 bars of price/RSI confirmation.",
        "sl_note":     "Mark levels now so you are ready when confirmation arrives.",
        "target_note": "Pre-calculate trade plan. Act only on confirmed directional move.",
    },
}
