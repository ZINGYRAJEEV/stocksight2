"""
Bonds & Treasury screener — US yields, US bond ETFs, India gilt / Bharat Bond ETFs.

Educational price/yield proxies via Yahoo Finance (yfinance). India G-Sec path uses
ETF prices (not auction yields). Not investment advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd
import yfinance as yf

try:
    from .screener import drawdown_pct_from_52w_high, get_stock_links, hist_series
except ImportError:
    from screener import drawdown_pct_from_52w_high, get_stock_links, hist_series

META = {
    "id": "bonds_treasury",
    "title": "Bonds & Treasury",
    "emoji": "🏛️",
    "nav_title": "Bonds & Treasury",
    "audience": (
        "Investors watching **interest rates**, **duration**, and **credit** — "
        "US Treasuries, bond ETFs, and India gilt / Bharat Bond ETFs."
    ),
    "purpose": (
        "Screens curated fixed-income instruments: US Treasury **yield levels**, "
        "gov/credit ETFs by duration, and India G-Sec ETF proxies. Suggests sleeves "
        "for rising vs falling rate regimes."
    ),
}

UNIVERSE_OPTIONS = (
    "All (US + India)",
    "US Treasury yields",
    "US Bond ETFs",
    "India Gilt / Bharat Bond ETFs",
)

DURATION_OPTIONS = ("Ultra-short", "Short", "Intermediate", "Long", "Blend")
CREDIT_OPTIONS = ("Sovereign", "IG", "HY")
RATE_MODE_OPTIONS = {
    "neutral": "Neutral — rank by score",
    "rising": "Rising rates — prefer short duration",
    "falling": "Falling rates — prefer long duration",
}

RANK_BY_OPTIONS = {
    "score": "Bond score",
    "ret_1m": "1M return %",
    "ret_3m": "3M return %",
    "yield": "Yield level (US indices)",
    "drawdown": "Below 52w high %",
}

# kind: yield_index | etf
# sleeve: us_yield | us_gov | us_credit | india_gilt | india_corp
UNIVERSE: list[dict] = [
    # US Treasury yields (Close = yield %)
    {"symbol": "^IRX", "name": "US 13-Week T-Bill", "kind": "yield_index", "sleeve": "us_yield",
     "duration": "Ultra-short", "credit": "Sovereign", "maturity": "3M"},
    {"symbol": "^FVX", "name": "US 5-Year Treasury Yield", "kind": "yield_index", "sleeve": "us_yield",
     "duration": "Intermediate", "credit": "Sovereign", "maturity": "5Y"},
    {"symbol": "^TNX", "name": "US 10-Year Treasury Yield", "kind": "yield_index", "sleeve": "us_yield",
     "duration": "Long", "credit": "Sovereign", "maturity": "10Y"},
    {"symbol": "^TYX", "name": "US 30-Year Treasury Yield", "kind": "yield_index", "sleeve": "us_yield",
     "duration": "Long", "credit": "Sovereign", "maturity": "30Y"},
    # US Gov / aggregate ETFs
    {"symbol": "BIL", "name": "SPDR 1-3 Month T-Bill", "kind": "etf", "sleeve": "us_gov",
     "duration": "Ultra-short", "credit": "Sovereign", "maturity": "T-Bill"},
    {"symbol": "SHY", "name": "iShares 1-3 Year Treasury", "kind": "etf", "sleeve": "us_gov",
     "duration": "Short", "credit": "Sovereign", "maturity": "1-3Y"},
    {"symbol": "IEI", "name": "iShares 3-7 Year Treasury", "kind": "etf", "sleeve": "us_gov",
     "duration": "Intermediate", "credit": "Sovereign", "maturity": "3-7Y"},
    {"symbol": "IEF", "name": "iShares 7-10 Year Treasury", "kind": "etf", "sleeve": "us_gov",
     "duration": "Intermediate", "credit": "Sovereign", "maturity": "7-10Y"},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury", "kind": "etf", "sleeve": "us_gov",
     "duration": "Long", "credit": "Sovereign", "maturity": "20+Y"},
    {"symbol": "GOVT", "name": "iShares US Treasury Bond", "kind": "etf", "sleeve": "us_gov",
     "duration": "Blend", "credit": "Sovereign", "maturity": "All"},
    {"symbol": "AGG", "name": "iShares Core US Aggregate Bond", "kind": "etf", "sleeve": "us_gov",
     "duration": "Intermediate", "credit": "IG", "maturity": "Agg"},
    {"symbol": "BND", "name": "Vanguard Total Bond Market", "kind": "etf", "sleeve": "us_gov",
     "duration": "Intermediate", "credit": "IG", "maturity": "Agg"},
    # US Credit
    {"symbol": "VCSH", "name": "Vanguard Short-Term Corp Bond", "kind": "etf", "sleeve": "us_credit",
     "duration": "Short", "credit": "IG", "maturity": "1-5Y"},
    {"symbol": "VCIT", "name": "Vanguard Interm Corp Bond", "kind": "etf", "sleeve": "us_credit",
     "duration": "Intermediate", "credit": "IG", "maturity": "5-10Y"},
    {"symbol": "LQD", "name": "iShares iBoxx IG Corporate", "kind": "etf", "sleeve": "us_credit",
     "duration": "Intermediate", "credit": "IG", "maturity": "Corp IG"},
    {"symbol": "HYG", "name": "iShares iBoxx High Yield", "kind": "etf", "sleeve": "us_credit",
     "duration": "Intermediate", "credit": "HY", "maturity": "HY"},
    {"symbol": "JNK", "name": "SPDR Bloomberg High Yield", "kind": "etf", "sleeve": "us_credit",
     "duration": "Intermediate", "credit": "HY", "maturity": "HY"},
    # India gilt / Bharat Bond (price proxies)
    {"symbol": "GILT5YBEES.NS", "name": "Nippon India ETF 5yr Gilt", "kind": "etf", "sleeve": "india_gilt",
     "duration": "Intermediate", "credit": "Sovereign", "maturity": "5Y"},
    {"symbol": "LTGILTBEES.NS", "name": "Nippon India ETF Long Gilt", "kind": "etf", "sleeve": "india_gilt",
     "duration": "Long", "credit": "Sovereign", "maturity": "Long"},
    {"symbol": "GSEC10YEAR.NS", "name": "Mirae Asset Nifty 10yr G-Sec", "kind": "etf", "sleeve": "india_gilt",
     "duration": "Long", "credit": "Sovereign", "maturity": "10Y"},
    {"symbol": "EBBETF0431.NS", "name": "Edelweiss Bharat Bond 2031", "kind": "etf", "sleeve": "india_corp",
     "duration": "Intermediate", "credit": "IG", "maturity": "2031"},
    {"symbol": "EBBETF0433.NS", "name": "Edelweiss Bharat Bond 2033", "kind": "etf", "sleeve": "india_corp",
     "duration": "Intermediate", "credit": "IG", "maturity": "2033"},
]


@dataclass
class BondsFilters:
    universe: str = "All (US + India)"
    durations: tuple[str, ...] = DURATION_OPTIONS
    credits: tuple[str, ...] = CREDIT_OPTIONS
    rate_mode: str = "neutral"
    min_ret_1m_pct: Optional[float] = None
    max_drawdown_52w_pct: Optional[float] = None
    min_avg_volume: float = 0.0


@dataclass
class BondsResult:
    symbol: str
    name: str
    sleeve: str
    kind: str
    duration: str
    credit: str
    maturity: str
    last: float
    unit: str  # "yield %" | "price"
    ret_1d_pct: Optional[float]
    ret_1w_pct: Optional[float]
    ret_1m_pct: Optional[float]
    ret_3m_pct: Optional[float]
    ytd_pct: Optional[float]
    drawdown_52w_pct: Optional[float]
    avg_volume: Optional[float]
    etf_yield_pct: Optional[float]
    score: float
    verdict: str
    notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)


@dataclass
class YieldCurveSnapshot:
    y_3m: Optional[float]
    y_5y: Optional[float]
    y_10y: Optional[float]
    y_30y: Optional[float]
    spread_10y_3m: Optional[float]
    spread_30y_10y: Optional[float]
    shape: str


def _universe_rows(universe: str) -> list[dict]:
    if universe == "US Treasury yields":
        return [r for r in UNIVERSE if r["sleeve"] == "us_yield"]
    if universe == "US Bond ETFs":
        return [r for r in UNIVERSE if r["sleeve"] in ("us_gov", "us_credit")]
    if universe == "India Gilt / Bharat Bond ETFs":
        return [r for r in UNIVERSE if r["sleeve"] in ("india_gilt", "india_corp")]
    return list(UNIVERSE)


def _period_return(closes: pd.Series, trading_days: int) -> Optional[float]:
    if closes is None or closes.empty or len(closes) < trading_days + 2:
        return None
    end_px = float(closes.iloc[-1])
    start_px = float(closes.iloc[-(trading_days + 1)])
    if start_px == 0:
        return None
    return round((end_px / start_px - 1.0) * 100.0, 2)


def _ytd_return(closes: pd.Series) -> Optional[float]:
    if closes is None or closes.empty:
        return None
    try:
        idx = closes.index
        if not isinstance(idx, pd.DatetimeIndex):
            idx = pd.to_datetime(idx)
            closes = closes.copy()
            closes.index = idx
        year = pd.Timestamp.today().year
        ytd = closes[closes.index.year == year]
        if ytd.empty:
            return None
        start = float(ytd.iloc[0])
        end = float(closes.iloc[-1])
        if start == 0:
            return None
        return round((end / start - 1.0) * 100.0, 2)
    except Exception:
        return None


def _score_and_verdict(
    row_meta: dict,
    *,
    ret_1m: Optional[float],
    ret_3m: Optional[float],
    drawdown: Optional[float],
    yield_level: Optional[float],
    rate_mode: str,
) -> tuple[float, str, list[str]]:
    notes: list[str] = []
    duration = row_meta["duration"]
    credit = row_meta["credit"]
    kind = row_meta["kind"]
    r1 = float(ret_1m or 0.0)
    r3 = float(ret_3m or 0.0)
    dd = float(drawdown or 0.0)

    score = r1 * 0.45 + r3 * 0.25
    if kind == "yield_index" and yield_level is not None:
        # Higher yield can be attractive for income; small bonus.
        score += min(float(yield_level), 8.0) * 0.35
        notes.append(f"Yield {yield_level:.2f}%")

    # Duration tilt by regime
    if rate_mode == "rising":
        if duration in ("Ultra-short", "Short"):
            score += 8.0
            notes.append("Short duration fit (rising rates)")
        elif duration == "Long":
            score -= 10.0
            notes.append("Long duration headwind (rising rates)")
    elif rate_mode == "falling":
        if duration == "Long":
            score += 10.0
            notes.append("Long duration fit (falling rates)")
        elif duration in ("Ultra-short", "Short"):
            score -= 4.0
            notes.append("Short duration less sensitive (falling rates)")

    if credit == "HY" and r1 < -2:
        score -= 6.0
        notes.append("HY weakness")
    if credit == "Sovereign" and dd >= 8:
        score += 3.0
        notes.append("Sovereign dip vs highs")

    score = round(score, 1)

    if kind == "yield_index":
        verdict = "Yield watch — rate level / curve"
    elif rate_mode == "rising" and duration in ("Ultra-short", "Short"):
        verdict = "Rising-rate sleeve — short duration"
    elif rate_mode == "falling" and duration == "Long":
        verdict = "Falling-rate sleeve — long duration"
    elif credit == "HY" and r1 > 1:
        verdict = "Credit risk-on — HY momentum"
    elif credit == "HY" and r1 < -1:
        verdict = "Credit caution — HY soft"
    elif r1 > 1.5:
        verdict = "Positive momentum"
    elif r1 < -1.5:
        verdict = "Weak — wait for stabilisation"
    else:
        verdict = "Hold / watch"

    return score, verdict, notes


def fetch_yield_curve_snapshot() -> YieldCurveSnapshot:
    """Latest US Treasury yield levels and simple curve shape."""
    levels: dict[str, Optional[float]] = {"^IRX": None, "^FVX": None, "^TNX": None, "^TYX": None}
    for sym in levels:
        try:
            hist = yf.Ticker(sym).history(period="10d", interval="1d", auto_adjust=True)
            closes = hist_series(hist, "Close").dropna()
            if not closes.empty:
                levels[sym] = round(float(closes.iloc[-1]), 3)
        except Exception:
            pass

    y3, y5, y10, y30 = levels["^IRX"], levels["^FVX"], levels["^TNX"], levels["^TYX"]
    s10_3 = round(y10 - y3, 3) if y10 is not None and y3 is not None else None
    s30_10 = round(y30 - y10, 3) if y30 is not None and y10 is not None else None

    if s10_3 is None:
        shape = "n/a"
    elif s10_3 < -0.05:
        shape = "Inverted (10Y < 3M) — often late-cycle caution"
    elif s10_3 < 0.35:
        shape = "Flat — little term premium"
    else:
        shape = "Upward sloping — normal term premium"

    return YieldCurveSnapshot(
        y_3m=y3,
        y_5y=y5,
        y_10y=y10,
        y_30y=y30,
        spread_10y_3m=s10_3,
        spread_30y_10y=s30_10,
        shape=shape,
    )


def scan_bonds_treasury(
    filters: BondsFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[BondsResult]:
    flt = filters or BondsFilters()
    rows = _universe_rows(flt.universe)
    rows = [
        r for r in rows
        if r["duration"] in flt.durations and r["credit"] in flt.credits
    ]
    results: list[BondsResult] = []
    total = len(rows)

    for i, meta in enumerate(rows):
        sym = meta["symbol"]
        if progress_cb:
            progress_cb(i + 1, total, sym)
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1y", interval="1d", auto_adjust=True)
            closes = hist_series(hist, "Close").dropna()
            if closes.empty:
                continue
            last = float(closes.iloc[-1])
            vols = hist_series(hist, "Volume").dropna() if "Volume" in getattr(hist, "columns", []) else pd.Series(dtype=float)
            avg_vol = float(vols.tail(20).mean()) if len(vols) >= 5 else None

            ret_1d = _period_return(closes, 1)
            ret_1w = _period_return(closes, 5)
            ret_1m = _period_return(closes, 21)
            ret_3m = _period_return(closes, 63)
            ytd = _ytd_return(closes)

            wk_high = float(closes.max()) if len(closes) else None
            dd = drawdown_pct_from_52w_high(last, wk_high)

            etf_yield = None
            if meta["kind"] == "etf":
                try:
                    info = t.info or {}
                    y = info.get("yield") or info.get("trailingAnnualDividendYield")
                    if y is not None:
                        yf_val = float(y)
                        etf_yield = round(yf_val * 100.0, 2) if yf_val < 1 else round(yf_val, 2)
                except Exception:
                    pass

            yield_level = last if meta["kind"] == "yield_index" else etf_yield

            if flt.min_ret_1m_pct is not None and (ret_1m is None or ret_1m < flt.min_ret_1m_pct):
                continue
            if flt.max_drawdown_52w_pct is not None and (dd is None or dd < flt.max_drawdown_52w_pct):
                continue
            if meta["kind"] == "etf" and flt.min_avg_volume > 0:
                if avg_vol is None or avg_vol < flt.min_avg_volume:
                    continue

            score, verdict, notes = _score_and_verdict(
                meta,
                ret_1m=ret_1m,
                ret_3m=ret_3m,
                drawdown=dd,
                yield_level=yield_level,
                rate_mode=flt.rate_mode,
            )

            links = get_stock_links(sym)
            results.append(
                BondsResult(
                    symbol=sym,
                    name=meta["name"],
                    sleeve=meta["sleeve"],
                    kind=meta["kind"],
                    duration=meta["duration"],
                    credit=meta["credit"],
                    maturity=meta["maturity"],
                    last=round(last, 4 if meta["kind"] == "yield_index" else 2),
                    unit="yield %" if meta["kind"] == "yield_index" else "price",
                    ret_1d_pct=ret_1d,
                    ret_1w_pct=ret_1w,
                    ret_1m_pct=ret_1m,
                    ret_3m_pct=ret_3m,
                    ytd_pct=ytd,
                    drawdown_52w_pct=dd,
                    avg_volume=round(avg_vol, 0) if avg_vol is not None else None,
                    etf_yield_pct=etf_yield,
                    score=score,
                    verdict=verdict,
                    notes=notes,
                    links=links,
                )
            )
        except Exception:
            continue

    return sort_bonds_results(results, rank_by="score")


def sort_bonds_results(results: list[BondsResult], *, rank_by: str = "score") -> list[BondsResult]:
    if rank_by == "ret_1m":
        key = lambda r: float(r.ret_1m_pct or -9999.0)
    elif rank_by == "ret_3m":
        key = lambda r: float(r.ret_3m_pct or -9999.0)
    elif rank_by == "yield":
        key = lambda r: float(
            r.last if r.kind == "yield_index" else (r.etf_yield_pct or -9999.0)
        )
    elif rank_by == "drawdown":
        key = lambda r: float(r.drawdown_52w_pct or -9999.0)
    else:
        key = lambda r: float(r.score or 0.0)
    return sorted(results, key=key, reverse=True)


def result_to_row(r: BondsResult, rank: int) -> dict:
    sleeve_lbl = {
        "us_yield": "US Yield",
        "us_gov": "US Gov ETF",
        "us_credit": "US Credit",
        "india_gilt": "India Gilt",
        "india_corp": "India Bharat Bond",
    }.get(r.sleeve, r.sleeve)
    return {
        "S.No.": rank,
        "Symbol": r.symbol,
        "Name": r.name,
        "Sleeve": sleeve_lbl,
        "Duration": r.duration,
        "Credit": r.credit,
        "Maturity": r.maturity,
        "Last": r.last,
        "Unit": r.unit,
        "1D %": r.ret_1d_pct,
        "1W %": r.ret_1w_pct,
        "1M %": r.ret_1m_pct,
        "3M %": r.ret_3m_pct,
        "YTD %": r.ytd_pct,
        "Below 52w %": r.drawdown_52w_pct,
        "ETF yield %": r.etf_yield_pct,
        "Avg vol": r.avg_volume,
        "Score": r.score,
        "Verdict": r.verdict,
        "Notes": " · ".join(r.notes[:3]),
        "Raw": r.symbol,
    }
