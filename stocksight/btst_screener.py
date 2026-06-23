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
ET = ZoneInfo("America/New_York")
CEST = ZoneInfo("Europe/Berlin")

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
        "Grade **A/B** names get entry and morning exit rules with **CEST** times for European traders. "
        "Data: **Breeze** when connected (NSE), else Yahoo."
    ),
}


@dataclass
class BtstTiming:
    """BTST scan / entry / exit windows in market-local and Europe/Berlin time."""
    market: str
    scan_market: str
    scan_cest: str
    entry_market: str
    entry_cest: str
    exit_market: str
    exit_cest: str
    exit_deadline_market: str
    exit_deadline_cest: str
    schedule_rows: list[tuple[str, str, str]] = field(default_factory=list)


def _market_tz(market: str) -> ZoneInfo:
    return ET if (market or "NSE").upper() == "US" else IST


def _market_tz_label(market: str) -> str:
    return "ET" if (market or "NSE").upper() == "US" else "IST"


def _dt_market_local(hour: int, minute: int, market: str) -> datetime:
    return datetime.now(tz=_market_tz(market)).replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )


def _fmt_hm(dt: datetime, tz_label: str | None = None) -> str:
    label = tz_label or dt.strftime("%Z")
    h12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{h12}:{dt.minute:02d} {ampm} {label}"


def _fmt_time_range(sh: int, sm: int, eh: int, em: int, market: str) -> tuple[str, str]:
    mkt_lbl = _market_tz_label(market)
    start = _dt_market_local(sh, sm, market)
    end = _dt_market_local(eh, em, market)
    market_range = f"{_fmt_hm(start, mkt_lbl)} – {_fmt_hm(end, mkt_lbl)}"
    cs = start.astimezone(CEST)
    ce = end.astimezone(CEST)
    cest_lbl = cs.strftime("%Z")
    cest_range = f"{_fmt_hm(cs, cest_lbl)} – {_fmt_hm(ce, cest_lbl)}"
    return market_range, cest_range


def _fmt_single_time(hour: int, minute: int, market: str) -> tuple[str, str]:
    dt = _dt_market_local(hour, minute, market)
    cest = dt.astimezone(CEST)
    return _fmt_hm(dt, _market_tz_label(market)), _fmt_hm(cest, cest.strftime("%Z"))


def btst_timing_schedule(market: str = "NSE") -> BtstTiming:
    """Return BTST windows for the selected market with CEST/CET equivalents."""
    mkt = (market or "NSE").upper()
    if mkt == "US":
        scan_m, scan_c = _fmt_time_range(14, 45, 15, 30, mkt)
        entry_m, entry_c = _fmt_time_range(15, 50, 15, 58, mkt)
        exit_m, exit_c = _fmt_time_range(9, 30, 10, 0, mkt)
        exit_dead_m, exit_dead_c = _fmt_single_time(10, 0, mkt)
        rows = [
            (scan_c, scan_m, "🌙 **Run BTST scan** — close strength into the NYSE/NASDAQ bell"),
            (entry_c, entry_m, "✅ **Entry** — Grade A/B before the close"),
            (exit_c, exit_m, "☀️ **Next-morning exit** — book gap-up opens · flat by deadline"),
        ]
    else:
        scan_m, scan_c = _fmt_time_range(14, 45, 15, 20, mkt)
        entry_m, entry_c = _fmt_time_range(15, 25, 15, 28, mkt)
        exit_m, exit_c = _fmt_time_range(9, 15, 10, 0, mkt)
        exit_dead_m, exit_dead_c = _fmt_single_time(10, 0, mkt)
        rows = [
            (scan_c, scan_m, "🌙 **Run BTST scan** — close strength on today's NSE bar"),
            (entry_c, entry_m, "✅ **Entry** — Grade A/B (CNC delivery)"),
            (exit_c, exit_m, "☀️ **Next-morning exit** — book gap-up at open · flat by deadline"),
        ]
    return BtstTiming(
        market=mkt,
        scan_market=scan_m,
        scan_cest=scan_c,
        entry_market=entry_m,
        entry_cest=entry_c,
        exit_market=exit_m,
        exit_cest=exit_c,
        exit_deadline_market=exit_dead_m,
        exit_deadline_cest=exit_dead_c,
        schedule_rows=rows,
    )


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
    market: str = "NSE"
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
    tv_news: str = "—"
    tv_sentiment: str = "—"
    tv_headline_sentiment: str = "—"
    tv_rating: str = "—"
    tv_sentiment_note: str = "—"
    pass_notes: list[str] = field(default_factory=list)
    reject_reason: str = ""
    links: dict = field(default_factory=dict)


def ist_session_hint() -> tuple[str, str]:
    """Return (phase_label, user_hint) for NSE BTST timing."""
    timing = btst_timing_schedule("NSE")
    now = datetime.now(tz=IST)
    t = now.hour * 60 + now.minute
    if t < 14 * 60 + 45:
        return (
            "PRE_SCAN",
            f"Best run **{timing.scan_market}** (**{timing.scan_cest}**) — today's bar may still be forming.",
        )
    if t < 15 * 60 + 20:
        return "BTST_WINDOW", f"Ideal BTST scan window — **{timing.scan_cest}** your time."
    if t < 15 * 60 + 30:
        return (
            "ENTRY_WINDOW",
            f"Entry **{timing.entry_market}** (**{timing.entry_cest}**) — confirm Grade A/B before buying.",
        )
    if t < 16 * 60:
        return "LATE", "Late session — only enter if CPR/volume still qualify; prefer CNC delivery."
    return (
        "POST_MARKET",
        f"Market closed — morning exit **{timing.exit_market}** (**{timing.exit_cest}**).",
    )


def us_session_hint() -> tuple[str, str]:
    """Return (phase_label, user_hint) for US (NYSE / NASDAQ) BTST timing."""
    timing = btst_timing_schedule("US")
    now = datetime.now(tz=ET)
    t = now.hour * 60 + now.minute
    if t < 14 * 60 + 45:
        return (
            "PRE_SCAN",
            f"Best run **{timing.scan_market}** (**{timing.scan_cest}**) — today's bar may still be forming.",
        )
    if t < 15 * 60 + 30:
        return "BTST_WINDOW", f"Ideal US BTST scan — **{timing.scan_cest}** your time."
    if t < 15 * 60 + 55:
        return (
            "ENTRY_WINDOW",
            f"Entry **{timing.entry_market}** (**{timing.entry_cest}**) — confirm Grade A/B before the close.",
        )
    if t < 16 * 60:
        return "LATE", "Near the bell — only enter if CPR/volume still qualify."
    return (
        "POST_MARKET",
        f"US session closed — exit plan **{timing.exit_market}** (**{timing.exit_cest}**).",
    )


def btst_session_hint(market: str = "NSE") -> tuple[str, str]:
    if (market or "NSE").upper() == "US":
        return us_session_hint()
    return ist_session_hint()


def _is_us_ticker(raw: str) -> bool:
    return not (raw or "").endswith((".NS", ".BO"))


def _entry_window_for_ticker(raw: str) -> str:
    mkt = "US" if _is_us_ticker(raw) else "NSE"
    timing = btst_timing_schedule(mkt)
    return f"{timing.entry_market} · {timing.entry_cest}"


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


def _morning_rule(pct_change: float, cpr: float, *, market: str = "NSE") -> str:
    timing = btst_timing_schedule(market)
    if (market or "NSE").upper() == "US":
        exit_note = f"**100% flat by {timing.exit_deadline_market}** ({timing.exit_deadline_cest})"
        open_note = f"Gap-up ≥1.5%: book **50%** at the open ({timing.exit_market.split(' – ')[0]})"
    else:
        exit_note = f"**100% flat by {timing.exit_deadline_market}** ({timing.exit_deadline_cest})"
        open_note = f"Gap-up ≥1.5%: book **50%** at open ({timing.exit_market.split(' – ')[0]})"
    base = (
        f"{open_note} · +0.5–1.5% gap: book **30–50%** in first 5 min · "
        "Flat: hold only if breaks **session open high** by 30 min else exit · "
        "Gap-down: exit early unless reclaims prev close · "
        f"{exit_note}"
    )
    if pct_change >= 4 and cpr >= 80:
        return f"Strong momentum day — {base}"
    return base


def _fetch_daily_hist(raw: str, flt: BtstFilters) -> tuple[pd.DataFrame, str]:
    if _is_us_ticker(raw) or flt.data_source == "yahoo":
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


def analyze_btst(raw: str, flt: BtstFilters, *, market: str = "NSE") -> Optional[BtstResult]:
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
        mkt = "US" if _is_us_ticker(raw) else (market or "NSE").upper()

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
            entry_window=_entry_window_for_ticker(raw),
            morning_rule=_morning_rule(pct_change, cpr, market=mkt),
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
    mkt = (market or "NSE").upper()
    t0 = time.time()
    tickers = resolve_universe(universe, market=mkt)[: flt.max_tickers]
    stats = BtstScanStats(universe=universe, data_source=flt.data_source)
    stats.market = mkt
    results: list[BtstResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        r = analyze_btst(raw, flt, market=mkt)
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
    if mkt == "US":
        preferred = (
            "S&P 500 (broad, slow)",
            "Liquid US shortlist (~35)",
        )
    else:
        preferred = (
            "Nifty 100 (medium)",
            "Nifty 500 (broad, slow)",
            "Nifty 50 (fast)",
            "Nifty Midcap 150",
        )
        all_key = next((k for k in dct if str(k).startswith("🌐 ALL")), None)
        if all_key:
            preferred = preferred + (all_key,)
    opts = list(dct.keys())
    ordered = [u for u in preferred if u in opts]
    ordered += [u for u in opts if u not in ordered]
    return ordered
