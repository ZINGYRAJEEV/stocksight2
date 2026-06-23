"""
BTST (Buy Today, Sell Tomorrow) — close-strength + volume continuation screener.

Runs on the **latest daily bar** (ideal window 3:00–3:20 PM IST). Targets names that
close in the top quartile of the day's range on above-average volume.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from .intraday import resolve_universe
    from .screener import (
        compute_rsi,
        compute_volume_ratio,
        fetch_price_history,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )
except ImportError:
    from intraday import resolve_universe
    from screener import (
        compute_rsi,
        compute_volume_ratio,
        fetch_price_history,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )

IST = ZoneInfo("Asia/Kolkata")

META = {
    "id": "btst",
    "title": "BTST Screener — Buy Today, Sell Tomorrow",
    "emoji": "🌙",
    "nav_title": "BTST Screener",
    "audience": (
        "End-of-day **momentum continuation** — strong close in the top of the day's range "
        "with volume confirmation, sold the **next morning** (9:15–10:00 AM IST)."
    ),
    "purpose": (
        "Scores **close position (CPR)**, volume surge, trend (MA20/50), and RSI. "
        "Grade **A/B** names get entry (3:25 PM) and morning exit rules. "
        "Data: **Breeze** when connected, else Yahoo."
    ),
}


@dataclass
class BtstFilters:
    min_price: float = 50.0
    max_price: float = 5000.0
    min_avg_volume_20d: float = 500_000.0
    min_pct_change: float = 1.5
    max_pct_change: float = 8.0
    min_cpr_grade_a: float = 75.0
    min_cpr_grade_b: float = 60.0
    min_vol_ratio_a: float = 1.8
    min_vol_ratio_b: float = 1.4
    min_score_a: float = 70.0
    min_score_b: float = 55.0
    max_upper_wick_pct: float = 25.0
    min_rsi: float = 50.0
    max_rsi: float = 78.0
    require_green_candle: bool = True
    grade_a_only: bool = False
    max_tickers: int = 600
    bar_delay_sec: float = 0.08
    data_source: str = "auto"  # auto | breeze | yahoo


@dataclass
class BtstScanStats:
    universe: str = ""
    tickers_scanned: int = 0
    no_data: int = 0
    failed_hard: int = 0
    grade_a: int = 0
    grade_b: int = 0
    grade_c: int = 0
    scan_elapsed_sec: float = 0.0
    data_source: str = "auto"
    bars_from_breeze: int = 0


@dataclass
class BtstResult:
    ticker: str
    raw_ticker: str
    sector: str
    grade: str
    btst_score: float
    cpr_pct: float
    vol_ratio: float
    pct_vs_prev_close: float
    rsi: float
    pct_vs_ma20: Optional[float]
    pct_vs_ma50: Optional[float]
    price: float
    prev_close: float
    day_low: float
    day_high: float
    stop_price: float
    target_t1_pct: float = 2.0
    target_t2_pct: float = 3.5
    entry_window: str = "3:25–3:28 PM IST"
    morning_rule: str = ""
    pass_notes: list[str] = field(default_factory=list)
    reject_reason: str = ""
    links: dict = field(default_factory=dict)


def ist_session_hint() -> tuple[str, str]:
    """Return (phase_label, user_hint) for BTST timing."""
    now = datetime.now(tz=IST)
    t = now.hour * 60 + now.minute
    if t < 14 * 60 + 45:
        return "PRE_SCAN", "Best run **2:45–3:20 PM IST** — today's bar may still be forming."
    if t < 15 * 60 + 20:
        return "BTST_WINDOW", "Ideal BTST scan window — close strength reflects today's tape."
    if t < 15 * 60 + 30:
        return "ENTRY_WINDOW", "Entry window **3:25–3:28 PM** — confirm Grade A/B before buying."
    if t < 16 * 60:
        return "LATE", "Late session — only enter if CPR/volume still qualify; prefer CNC delivery."
    return "POST_MARKET", "Market closed — review list for **tomorrow morning** exit plan (9:15–10:00 AM)."


def _compute_cpr(high: float, low: float, close: float) -> float:
    rng = high - low
    if rng <= 0:
        return 50.0
    return round((close - low) / rng * 100.0, 1)


def _upper_wick_pct(high: float, low: float, close: float) -> float:
    rng = high - low
    if rng <= 0:
        return 0.0
    return round((high - close) / rng * 100.0, 1)


def _btst_score(
    *,
    cpr: float,
    vol_ratio: float,
    pct_change: float,
    above_ma20: bool,
    above_ma50: bool,
    rsi: float,
) -> float:
    score = 0.0
    if cpr >= 75:
        score += 25
    elif cpr >= 60:
        score += 15
    if vol_ratio >= 2.0:
        score += 20
    elif vol_ratio >= 1.5:
        score += 12
    elif vol_ratio >= 1.4:
        score += 8
    if 2.0 <= pct_change <= 6.0:
        score += 15
    elif 1.5 <= pct_change < 2.0:
        score += 8
    elif 6.0 < pct_change <= 8.0:
        score += 10
    if above_ma20:
        score += 10
    if above_ma50:
        score += 10
    if 55 <= rsi <= 72:
        score += 10
    elif 50 <= rsi < 55 or 72 < rsi <= 78:
        score += 5
    return round(min(100.0, score), 1)


def _assign_grade(score: float, cpr: float, vol_ratio: float, flt: BtstFilters) -> str:
    if score >= flt.min_score_a and cpr >= flt.min_cpr_grade_a and vol_ratio >= flt.min_vol_ratio_a:
        return "A"
    if score >= flt.min_score_b and cpr >= flt.min_cpr_grade_b and vol_ratio >= flt.min_vol_ratio_b:
        return "B"
    return "C"


def _morning_rule(pct_change: float, cpr: float) -> str:
    base = (
        "Gap-up ≥1.5%: book **50%** at open · +0.5–1.5% gap: book **30–50%** in first 5 min · "
        "Flat: hold only if breaks **9:15 high** by 9:30 else exit · "
        "Gap-down: exit by **9:20** unless reclaims prev close · "
        "**100% flat by 10:00 AM IST**"
    )
    if pct_change >= 4 and cpr >= 80:
        return f"Strong momentum day — {base}"
    return base


def _fetch_daily_hist(raw: str, flt: BtstFilters) -> tuple[pd.DataFrame, str]:
    if flt.data_source == "yahoo":
        return fetch_price_history(raw, "1d"), "yahoo"

    hist = fetch_price_history(raw, "1d")
    source = "yahoo"
    if raw.endswith((".NS", ".BO")):
        try:
            from breeze_data import fetch_breeze_price_history, breeze_configured

            if flt.data_source in ("auto", "breeze") and breeze_configured():
                bdf = fetch_breeze_price_history(raw, "1d")
                if bdf is not None and not bdf.empty:
                    hist = bdf
                    source = "breeze"
        except Exception:
            pass
    return hist, source


def analyze_btst(raw: str, flt: BtstFilters) -> Optional[BtstResult]:
    disp = raw.replace(".NS", "").replace(".BO", "")
    try:
        hist, _src = _fetch_daily_hist(raw, flt)
        if hist is None or hist.empty or len(hist) < 22:
            return None

        closes = hist_series(hist, "Close").astype(float)
        highs = hist_series(hist, "High").astype(float)
        lows = hist_series(hist, "Low").astype(float)
        opens = hist_series(hist, "Open").astype(float)
        vols = hist_series(hist, "Volume").astype(float)

        price = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2])
        day_open = float(opens.iloc[-1])
        day_high = float(highs.iloc[-1])
        day_low = float(lows.iloc[-1])

        if price < flt.min_price or price > flt.max_price:
            return None

        avg_vol = float(vols.iloc[-21:-1].mean())
        if avg_vol < flt.min_avg_volume_20d:
            return None

        vol_ratio = compute_volume_ratio(vols)
        if vol_ratio is None or np.isnan(vol_ratio):
            return None
        vol_ratio = float(vol_ratio)

        pct_change = round((price / prev_close - 1.0) * 100.0, 2) if prev_close > 0 else 0.0
        if pct_change < flt.min_pct_change or pct_change > flt.max_pct_change:
            return None

        cpr = _compute_cpr(day_high, day_low, price)
        wick = _upper_wick_pct(day_high, day_low, price)

        rsi = compute_rsi(closes)
        if rsi is None or np.isnan(rsi):
            return None
        rsi = float(rsi)

        notes: list[str] = []
        reject = ""

        if flt.require_green_candle and price <= day_open:
            reject = "Not a green candle (close ≤ open)"
        elif price <= prev_close:
            reject = "Close below prior day close"
        elif cpr < flt.min_cpr_grade_b:
            reject = f"Weak close (CPR {cpr:.0f}% < {flt.min_cpr_grade_b:.0f}%)"
        elif vol_ratio < flt.min_vol_ratio_b:
            reject = f"Volume too low ({vol_ratio:.1f}× < {flt.min_vol_ratio_b:.1f}×)"
        elif wick > flt.max_upper_wick_pct:
            reject = f"Large upper wick ({wick:.0f}% of range)"
        elif rsi < flt.min_rsi:
            reject = f"RSI too weak ({rsi:.1f})"
        elif rsi > flt.max_rsi:
            reject = f"RSI exhausted ({rsi:.1f})"

        ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else price
        ma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else ma20
        above_ma20 = price >= ma20
        above_ma50 = price >= ma50
        vs_ma20 = pct_vs_ma(price, ma20) if ma20 > 0 else None
        vs_ma50 = pct_vs_ma(price, ma50) if ma50 > 0 else None

        score = _btst_score(
            cpr=cpr,
            vol_ratio=vol_ratio,
            pct_change=pct_change,
            above_ma20=above_ma20,
            above_ma50=above_ma50,
            rsi=rsi,
        )
        grade = _assign_grade(score, cpr, vol_ratio, flt)

        if not reject:
            if grade == "A":
                notes.append("Grade A — full size (within risk cap)")
            elif grade == "B":
                notes.append("Grade B — half size recommended")
            else:
                notes.append("Grade C — observe only")
            if cpr >= 75:
                notes.append(f"CPR {cpr:.0f}% (top-quartile close)")
            notes.append(f"Vol {vol_ratio:.1f}× 20D avg")

        stop = round(min(day_low, price * 0.985), 2)
        sector, _ = get_sector_industry(yf.Ticker(raw))

        return BtstResult(
            ticker=disp,
            raw_ticker=raw,
            sector=sector or "—",
            grade=grade if not reject else "C",
            btst_score=score,
            cpr_pct=cpr,
            vol_ratio=vol_ratio,
            pct_vs_prev_close=pct_change,
            rsi=rsi,
            pct_vs_ma20=vs_ma20,
            pct_vs_ma50=vs_ma50,
            price=round(price, 2),
            prev_close=round(prev_close, 2),
            day_low=round(day_low, 2),
            day_high=round(day_high, 2),
            stop_price=stop,
            morning_rule=_morning_rule(pct_change, cpr),
            pass_notes=notes,
            reject_reason=reject,
            links=get_stock_links(raw),
        )
    except Exception:
        return None


def scan_btst(
    universe: str,
    flt: Optional[BtstFilters] = None,
    *,
    market: str = "NSE",
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[list[BtstResult], BtstScanStats]:
    flt = flt or BtstFilters()
    t0 = time.time()
    tickers = resolve_universe(universe, market=market)[: flt.max_tickers]
    stats = BtstScanStats(universe=universe, data_source=flt.data_source)
    results: list[BtstResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        r = analyze_btst(raw, flt)
        if r is None:
            stats.no_data += 1
        elif r.reject_reason:
            stats.failed_hard += 1
        elif r.grade == "A":
            stats.grade_a += 1
        elif r.grade == "B":
            stats.grade_b += 1
        else:
            stats.grade_c += 1

        if r is not None and not r.reject_reason and r.grade in ("A", "B"):
            if not flt.grade_a_only or r.grade == "A":
                results.append(r)

        if flt.bar_delay_sec > 0:
            time.sleep(flt.bar_delay_sec)

    grade_rank = {"A": 0, "B": 1, "C": 2}
    results.sort(
        key=lambda x: (grade_rank.get(x.grade, 9), -x.btst_score, -x.cpr_pct, -x.vol_ratio),
    )
    stats.scan_elapsed_sec = round(time.time() - t0, 1)
    return results, stats


def universe_options(market: str = "NSE") -> list[str]:
    from intraday import INTRADAY_UNIVERSES_BY_MARKET

    mkt = (market or "NSE").upper()
    dct = INTRADAY_UNIVERSES_BY_MARKET.get(mkt, {})
    preferred = (
        "Nifty 100 (medium)",
        "Nifty 500 (broad, slow)",
        "Nifty 50 (fast)",
        "Nifty Midcap 150",
    )
    opts = list(dct.keys())
    ordered = [u for u in preferred if u in opts]
    ordered += [u for u in opts if u not in ordered]
    return ordered
