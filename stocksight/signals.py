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

try:
    from .screener import (
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
        fetch_weekly_history,
        weekly_buy_alignment,
        calendar_days_until,
        compute_stochastic,
        stochastic_last_and_crosses,
        compute_vwap,
        relative_strength_vs_benchmark,
        benchmark_ticker_for,
        fetch_nse_fii_dii_equity_snapshot,
    )
except ImportError:
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
        fetch_weekly_history,
        weekly_buy_alignment,
        calendar_days_until,
        compute_stochastic,
        stochastic_last_and_crosses,
        compute_vwap,
        relative_strength_vs_benchmark,
        benchmark_ticker_for,
        fetch_nse_fii_dii_equity_snapshot,
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

    # Signal-quality overlays (daily bars unless weekly fetched explicitly)
    rsi_bullish_div: bool = False
    rsi_bearish_div: bool = False
    weekly_confirm_buy: Optional[bool] = None   # None = weekly MTF not evaluated this fetch
    weekly_macd_bullish: Optional[bool] = None
    days_to_earnings: Optional[int] = None     # negative = past / assumed reported

    # Oscillator / structure
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    stoch_cross_up: bool = False
    stoch_cross_down: bool = False

    rel_strength_20d: Optional[float] = None   # excess % vs Nifty / SPY (aligned bars)
    benchmark_sym: Optional[str] = None

    vwap_last: Optional[float] = None
    price_vs_vwap_pct: Optional[float] = None

    nse_flow_note: Optional[str] = None       # market-wide FII/DII snapshot (NSE names only)
    news_sentiment: Optional[str] = None      # bullish / neutral / bearish (keyword scan)


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


def _pivot_indices(series: pd.Series, order: int, mode: str) -> list[int]:
    """Local highs/lows for RSI divergence (fractal-style pivots)."""
    n = len(series)
    out: list[int] = []
    if n < order * 3:
        return out
    for i in range(order, n - order):
        window = series.iloc[i - order : i + order + 1]
        v = float(series.iloc[i])
        if mode == "high" and v >= float(window.max()):
            out.append(i)
        if mode == "low" and v <= float(window.min()):
            out.append(i)
    return out


def rsi_divergence_flags(highs: pd.Series, lows: pd.Series, rsi: pd.Series, order: int = 3) -> tuple[bool, bool]:
    """
    Classic swing RSI divergence on last two pivots:
      Bearish: higher price high, lower RSI high (warns on aggressive BUY breakouts).
      Bullish: lower price low, higher RSI low (supports dip buys).
    """
    bullish = bearish = False
    if highs is None or lows is None or rsi is None:
        return False, False
    if len(highs) < order * 5:
        return False, False

    ph = _pivot_indices(highs, order, "high")
    pl = _pivot_indices(lows, order, "low")

    if len(ph) >= 2:
        i1, i2 = ph[-2], ph[-1]
        r1, r2 = float(rsi.iloc[i1]), float(rsi.iloc[i2])
        if not (np.isnan(r1) or np.isnan(r2)):
            if float(highs.iloc[i2]) > float(highs.iloc[i1]) and r2 < r1:
                bearish = True

    if len(pl) >= 2:
        j1, j2 = pl[-2], pl[-1]
        r1b, r2b = float(rsi.iloc[j1]), float(rsi.iloc[j2])
        if not (np.isnan(r1b) or np.isnan(r2b)):
            if float(lows.iloc[j2]) < float(lows.iloc[j1]) and r2b > r1b:
                bullish = True

    return bullish, bearish


def _confidence(
    vol_ratio: float,
    rsi_rising: bool,
    reversal: bool,
    is_green: bool,
    scenario_id: str,
    macd_bullish: bool = False,
    *,
    buy_side_screening: bool = False,
    weekly_confirm_buy: Optional[bool] = None,
    rsi_bullish_div: bool = False,
) -> str:
    score = 0
    if vol_ratio >= 3:
        score += 2
    elif vol_ratio >= 2:
        score += 1
    if rsi_rising:
        score += 1
    if reversal:
        score += 2
    if is_green:
        score += 1
    if macd_bullish:
        score += 1
    if buy_side_screening and weekly_confirm_buy is True:
        score += 1
    if buy_side_screening and rsi_bullish_div:
        score += 1
    if scenario_id == "breakout" and vol_ratio >= 3 and rsi_rising:
        score += 1
    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return "LOW"


def _passes_advanced_filters(
    ex: dict,
    sector_filter: Optional[str],
    require_macd: bool,
    require_bb_lower: bool,
    *,
    require_weekly_confirm: bool = False,
    weekly_macd_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    buy_side_screening: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
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

    if exclude_earnings_within_days > 0:
        d = ex.get("days_to_earnings")
        if d is not None and 0 <= d <= exclude_earnings_within_days:
            return False

    if buy_side_screening and require_weekly_confirm:
        if ex.get("weekly_confirm_buy") is not True:
            return False

    if buy_side_screening and skip_bearish_divergence_buy and ex.get("rsi_bearish_div"):
        return False

    if buy_side_screening and weekly_macd_confirm:
        if ex.get("weekly_macd_bullish") is not True:
            return False

    if min_rs_vs_bench is not None:
        rs = ex.get("rel_strength_20d")
        try:
            thr = float(min_rs_vs_bench)
        except (TypeError, ValueError):
            thr = None
        if thr is not None:
            if rs is None or float(rs) < thr:
                return False

    if buy_side_screening and require_stoch_cross_up:
        if not ex.get("stoch_cross_up"):
            return False

    if require_stoch_cross_down:
        if not ex.get("stoch_cross_down"):
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

    ex = extras or {}
    buy_side = scenario_id in ("oversold_bounce", "breakout", "value_technical", "extreme_oversold")
    confidence = _confidence(
        vol_ratio,
        rsi_rising,
        reversal,
        is_green,
        scenario_id,
        macd_bullish=bool(ex.get("macd_bullish")),
        buy_side_screening=buy_side,
        weekly_confirm_buy=(ex.get("weekly_confirm_buy") if buy_side else None),
        rsi_bullish_div=bool(ex.get("rsi_bullish_div")),
    )

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
        rsi_bullish_div = bool(ex.get("rsi_bullish_div")),
        rsi_bearish_div = bool(ex.get("rsi_bearish_div")),
        weekly_confirm_buy = ex.get("weekly_confirm_buy"),
        weekly_macd_bullish = ex.get("weekly_macd_bullish"),
        days_to_earnings = ex.get("days_to_earnings"),
        stoch_k = _finite_num(ex.get("stoch_k")),
        stoch_d = _finite_num(ex.get("stoch_d")),
        stoch_cross_up = bool(ex.get("stoch_cross_up")),
        stoch_cross_down = bool(ex.get("stoch_cross_down")),
        rel_strength_20d = _finite_num(ex.get("rel_strength_20d")),
        benchmark_sym = (ex.get("benchmark_sym") or None),
        vwap_last = _finite_num(ex.get("vwap_last")),
        price_vs_vwap_pct = _finite_num(ex.get("price_vs_vwap_pct")),
        nse_flow_note = (ex.get("nse_flow_note") or None),
        news_sentiment = (ex.get("news_sentiment") or None),
    )


# ─────────────────────────────────────────────────────────────
# Core fetch — shared across all scenarios
# ─────────────────────────────────────────────────────────────

def _fetch(
    ticker: str,
    interval_key: str = "1d",
    *,
    include_weekly: bool = False,
    weekly_macd_confirm: bool = False,
):
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
        vols = hist["Volume"]
        px = float(closes.iloc[-1])

        div_bull, div_bear = rsi_divergence_flags(highs, lows, rsi_series, order=3)

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

        pct_k_s, pct_d_s = compute_stochastic(highs, lows, closes)
        stoch_pack = stochastic_last_and_crosses(pct_k_s, pct_d_s)

        bench_sym = benchmark_ticker_for(ticker)
        bench_hist = fetch_price_history(bench_sym, interval_key)
        rs_ex = relative_strength_vs_benchmark(hist, bench_hist, bars=20)

        vwap_s = compute_vwap(highs, lows, closes, vols)
        vwap_last = None
        pv_pct = None
        if vwap_s is not None and len(vwap_s) and pd.notna(vwap_s.iloc[-1]):
            vwap_last = round(float(vwap_s.iloc[-1]), 4)
            pv_pct = pct_vs_ma(px, float(vwap_last))

        nse_note = None
        if str(ticker).upper().endswith((".NS", ".BO")):
            nse_note = fetch_nse_fii_dii_equity_snapshot()

        weekly_ok: Optional[bool] = None
        weekly_macd_bull: Optional[bool] = None
        if include_weekly or weekly_macd_confirm:
            wdf = fetch_weekly_history(ticker)
            wc = wdf["Close"] if not wdf.empty else pd.Series(dtype=float)
            if wdf.empty or len(wc) < 15:
                if include_weekly:
                    weekly_ok = False
                if weekly_macd_confirm:
                    weekly_macd_bull = False
            else:
                if include_weekly:
                    weekly_ok = weekly_buy_alignment(wc)
                if weekly_macd_confirm:
                    _w_ml, _w_ms, w_mh = compute_macd(wc)
                    weekly_macd_bull = bool(not np.isnan(w_mh) and w_mh > 0)

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
            "rsi_bullish_div": div_bull,
            "rsi_bearish_div": div_bear,
            "weekly_confirm_buy": weekly_ok,
            "weekly_macd_bullish": weekly_macd_bull,
            "days_to_earnings": calendar_days_until(earn),
            "stoch_k": stoch_pack.get("stoch_k"),
            "stoch_d": stoch_pack.get("stoch_d"),
            "stoch_cross_up": bool(stoch_pack.get("stoch_cross_up")),
            "stoch_cross_down": bool(stoch_pack.get("stoch_cross_down")),
            "rel_strength_20d": rs_ex,
            "benchmark_sym": bench_sym,
            "vwap_last": vwap_last,
            "price_vs_vwap_pct": pv_pct,
            "nse_flow_note": nse_note,
        }

        return hist, pe, vol_ratio, rsi, rsi_prev, extras
    except Exception:
        return None


def enrich_results_news(results: list[SignalResult], limit_per_ticker: int = 3) -> None:
    """Populate news headlines (extra Yahoo calls — use only for small result sets)."""
    for r in results:
        r.news_headlines = fetch_quote_news(r.raw_ticker, limit_per_ticker)
        r.news_sentiment = headline_sentiment_label(r.news_headlines)


def headline_sentiment_label(headlines: list[str]) -> Optional[str]:
    """Crude keyword polarity for Yahoo headlines — educational only."""
    if not headlines:
        return None
    pos_kw = (
        "beat", "surge", "upgrade", "growth", "profit", "gain", "bull", "buy", "record",
        "strong", "expands", "raises", "approval", "deal wins",
    )
    neg_kw = (
        "miss", "falls", "crash", "probe", "downgrade", "loss", "bear", "warn", "cuts",
        "fraud", "ban", "investigation", "lawsuit", "defaults", "bankruptcy",
    )
    score = 0
    for h in headlines:
        low = str(h).lower()
        score += sum(1 for w in pos_kw if w in low)
        score -= sum(1 for w in neg_kw if w in low)
    if score >= 2:
        return "bullish"
    if score <= -2:
        return "bearish"
    return "neutral"


def _full_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta    = closes.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ticker_list(universe_name: str, tickers_override: Optional[list[str]]) -> list[str]:
    if tickers_override is not None:
        return [str(t).strip() for t in tickers_override if str(t).strip()]
    return UNIVERSES.get(universe_name, [])


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
    tickers_override: Optional[list[str]] = None,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = _ticker_list(universe_name, tickers_override)
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(
            ticker,
            interval_key,
            include_weekly=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
        )
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(
            ex, sector_filter, require_macd_bullish, require_bb_touch_lower,
            require_weekly_confirm=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
            exclude_earnings_within_days=exclude_earnings_within_days,
            skip_bearish_divergence_buy=skip_bearish_divergence_buy,
            buy_side_screening=True,
            min_rs_vs_bench=min_rs_vs_bench,
            require_stoch_cross_up=require_stoch_cross_up,
            require_stoch_cross_down=False,
        ):
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
    tickers_override: Optional[list[str]] = None,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = _ticker_list(universe_name, tickers_override)
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(
            ticker,
            interval_key,
            include_weekly=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
        )
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(
            ex, sector_filter, require_macd_bullish, require_bb_touch_lower,
            require_weekly_confirm=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
            exclude_earnings_within_days=exclude_earnings_within_days,
            skip_bearish_divergence_buy=skip_bearish_divergence_buy,
            buy_side_screening=True,
            min_rs_vs_bench=min_rs_vs_bench,
            require_stoch_cross_up=require_stoch_cross_up,
            require_stoch_cross_down=False,
        ):
            continue

        if not (5 <= pe <= pe_max):   continue
        if vol_ratio < vol_min:       continue
        if not (rsi_min <= rsi <= rsi_max): continue
        if rsi <= rsi_prev:           continue   # RSI crossing upward

        ma20 = hist["Close"].rolling(20).mean().iloc[-1]
        if hist["Close"].iloc[-1] < ma20:
            continue

        results.append(_build_result(
            ticker, hist, pe, vol_ratio, rsi, rsi_prev,
            scenario_id  = "breakout",
            signal_label = "BUY",
            timeframe    = "Momentum · 1–8 weeks",
            note         = "Volume confirms breakout. Trail with 10–20% stop or scale out at 20–40% gain.",
            sl_lookback  = 5,
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
    tickers_override: Optional[list[str]] = None,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = _ticker_list(universe_name, tickers_override)
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(
            ticker,
            interval_key,
            include_weekly=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
        )
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(
            ex, sector_filter, require_macd_bullish, require_bb_touch_lower,
            require_weekly_confirm=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
            exclude_earnings_within_days=exclude_earnings_within_days,
            skip_bearish_divergence_buy=skip_bearish_divergence_buy,
            buy_side_screening=True,
            min_rs_vs_bench=min_rs_vs_bench,
            require_stoch_cross_up=require_stoch_cross_up,
            require_stoch_cross_down=False,
        ):
            continue

        if not (5 <= pe <= pe_max):   continue
        if vol_ratio < vol_min:       continue
        if not (rsi_min <= rsi <= rsi_max): continue

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
            sl_lookback  = 20,
            target_ratios= (1.0, 2.0, 4.0),
            extras       = ex,
            bar_interval = interval_key,
        ))

    return sorted(results, key=lambda x: x.pe)


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
    tickers_override: Optional[list[str]] = None,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = _ticker_list(universe_name, tickers_override)
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(
            ticker,
            interval_key,
            include_weekly=require_weekly_confirm,
            weekly_macd_confirm=False,
        )
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(
            ex, sector_filter, require_macd_bullish, require_bb_touch_lower,
            require_weekly_confirm=require_weekly_confirm,
            weekly_macd_confirm=False,
            exclude_earnings_within_days=exclude_earnings_within_days,
            skip_bearish_divergence_buy=skip_bearish_divergence_buy,
            buy_side_screening=False,
            min_rs_vs_bench=min_rs_vs_bench,
            require_stoch_cross_up=False,
            require_stoch_cross_down=require_stoch_cross_down,
        ):
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
    tickers_override: Optional[list[str]] = None,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = _ticker_list(universe_name, tickers_override)
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(
            ticker,
            interval_key,
            include_weekly=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
        )
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(
            ex, sector_filter, require_macd_bullish, require_bb_touch_lower,
            require_weekly_confirm=require_weekly_confirm,
            weekly_macd_confirm=weekly_macd_confirm,
            exclude_earnings_within_days=exclude_earnings_within_days,
            skip_bearish_divergence_buy=skip_bearish_divergence_buy,
            buy_side_screening=True,
            min_rs_vs_bench=min_rs_vs_bench,
            require_stoch_cross_up=require_stoch_cross_up,
            require_stoch_cross_down=False,
        ):
            continue

        if pe > pe_max:           continue
        if vol_ratio < vol_min:   continue
        if rsi > rsi_max:         continue

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

    return sorted(results, key=lambda x: x.rsi)


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
    tickers_override: Optional[list[str]] = None,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
) -> list[SignalResult]:
    results = []
    tickers = _ticker_list(universe_name, tickers_override)
    total   = len(tickers)

    for i, ticker in enumerate(tickers):
        if progress_cb: progress_cb(i + 1, total, ticker)
        data = _fetch(
            ticker,
            interval_key,
            include_weekly=require_weekly_confirm,
            weekly_macd_confirm=False,
        )
        if not data: continue
        hist, pe, vol_ratio, rsi, rsi_prev, ex = data

        if not _passes_advanced_filters(
            ex, sector_filter, require_macd_bullish, require_bb_touch_lower,
            require_weekly_confirm=require_weekly_confirm,
            weekly_macd_confirm=False,
            exclude_earnings_within_days=exclude_earnings_within_days,
            skip_bearish_divergence_buy=skip_bearish_divergence_buy,
            buy_side_screening=False,
            min_rs_vs_bench=min_rs_vs_bench,
            require_stoch_cross_up=False,
            require_stoch_cross_down=require_stoch_cross_down,
        ):
            continue

        if pe > pe_max:       continue
        if vol_ratio < vol_min:  continue
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


def cross_scan_watchlist(
    symbols: list[str],
    *,
    interval_key: str = "1d",
    sector_filter: Optional[str] = None,
    require_macd_bullish: bool = False,
    require_bb_touch_lower: bool = False,
    require_weekly_confirm: bool = False,
    exclude_earnings_within_days: int = 0,
    skip_bearish_divergence_buy: bool = False,
    min_rs_vs_bench: Optional[float] = None,
    require_stoch_cross_up: bool = False,
    require_stoch_cross_down: bool = False,
    weekly_macd_confirm: bool = False,
    progress_cb=None,
) -> list[SignalResult]:
    """
    Run all six scenario scanners against an explicit symbol list (e.g. saved watchlist).
    Uses each scanner's default PE/volume/RSI thresholds — tune filters on individual scenario pages.
    """
    syms = [str(s).strip() for s in symbols if str(s).strip()]
    if not syms:
        return []

    dummy_universe = "Nifty 50 (NSE)"
    scanners = (
        scan_oversold_bounce,
        scan_breakout_momentum,
        scan_value_technical,
        scan_overbought_exit,
        scan_extreme_oversold,
        scan_volume_no_confirm,
    )

    merged: list[SignalResult] = []
    for fn in scanners:
        merged.extend(
            fn(
                dummy_universe,
                progress_cb=progress_cb,
                sector_filter=sector_filter,
                interval_key=interval_key,
                require_macd_bullish=require_macd_bullish,
                require_bb_touch_lower=require_bb_touch_lower,
                tickers_override=syms,
                require_weekly_confirm=require_weekly_confirm,
                exclude_earnings_within_days=exclude_earnings_within_days,
                skip_bearish_divergence_buy=skip_bearish_divergence_buy,
                min_rs_vs_bench=min_rs_vs_bench,
                require_stoch_cross_up=require_stoch_cross_up,
                require_stoch_cross_down=require_stoch_cross_down,
                weekly_macd_confirm=weekly_macd_confirm,
            )
        )
    return merged


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
        "audience": "Swing traders hunting mean-reversion entries after sharp sell-offs (Nifty 50 / 500 or S&P 500).",
        "purpose": "Finds oversold names with volume spike and RSI turning up; outputs trade plan cards with entry, stop, and targets.",
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
        "audience": "Momentum traders who want early-stage breakouts with confirming volume and trend.",
        "purpose": "Screens for price above the 20-day MA, heavy volume, and RSI in a bullish band; ranks matches with full trade plans.",
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
        "audience": "Value-oriented investors blending fundamentals (low PE) with technical timing on pullbacks.",
        "purpose": "Combines modest valuation, controlled volume, and mid-range RSI to flag quality names near support.",
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
        "audience": "Investors managing winners or trimming risk when momentum looks stretched.",
        "purpose": "Flags overbought, high-volume names that may be due for profit-taking or tighter stops.",
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
        "audience": "Contrarian traders comfortable with higher risk and smaller position sizes.",
        "purpose": "Surfaces deep oversold extremes; use for watchlists and catalyst checks—not blind bottom-fishing.",
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
        "audience": "Traders who want an early heads-up before direction is clear—prep levels, wait for confirmation.",
        "purpose": "Lists unusual volume with ambiguous RSI; ideal for a watchlist until a scenario module confirms BUY or SELL.",
        "entry_note":  "Do NOT enter yet. Watch for 1–3 bars of price/RSI confirmation.",
        "sl_note":     "Mark levels now so you are ready when confirmation arrives.",
        "target_note": "Pre-calculate trade plan. Act only on confirmed directional move.",
    },
}


# Map SignalResult.scenario_id (internal) → sidebar SCENARIOS registry keys / UI cards
SCENARIO_RESULT_TO_PAGE: dict[str, str] = {
    "oversold_bounce": "oversold_bounce",
    "breakout": "breakout_momentum",
    "value_technical": "value_technical",
    "overbought": "overbought_exit",
    "extreme_oversold": "extreme_oversold",
    "volume_no_confirm": "volume_no_confirm",
}


def scenario_nav_key(scenario_id: str) -> str:
    """Registry key used by `SCENARIOS` / `trade_plan_card` / `scenario_header`."""
    return SCENARIO_RESULT_TO_PAGE.get(scenario_id, "oversold_bounce")


def scenario_display_title(scenario_id: str) -> str:
    nav = scenario_nav_key(scenario_id)
    meta = SCENARIOS.get(nav)
    return str(meta["title"]) if meta else scenario_id
