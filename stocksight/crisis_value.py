"""
Crisis Value screener — steady multi-year earnings + fallen stock price (2008-style dislocation).

Finds quality companies where reported earnings stayed consistent while the market marked
the share price down — potential undervaluation when fundamentals held through a panic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from multibagger import extract_multibagger_fundamentals, normalize_debt_equity
from screener import (
    PE_DATA_CAP,
    UNIVERSES,
    drawdown_pct_from_52w_high,
    extract_healthy_dip_fundamentals,
    get_pe,
    get_sector_industry,
    get_stock_links,
    hist_series,
)

ProgressCb = Callable[[int, int, str], None]

META = {
    "id": "crisis_value",
    "title": "Crisis Value Screener",
    "emoji": "🏦",
    "nav_title": "Crisis Value",
    "audience": (
        "Long-term investors hunting **2008-style setups**: share price fell sharply while "
        "**earnings stayed consistent** over multiple years — classic fear vs. fundamentals gap."
    ),
    "purpose": (
        "Screens for multi-year **earnings stability** (positive EPS/net income, limited YoY drops) "
        "combined with **price dislocation** (drawdown + earnings-outpaced-price divergence) and "
        "reasonable valuation (P/E, ROE, debt). Yahoo annual financials — verify on Screener.in."
    ),
}

_EARNINGS_ROW_PRIORITY = (
    "Diluted EPS",
    "Basic EPS",
    "Net Income Common Stockholders",
    "Net Income From Continuing Operation Net Minority Interest",
    "Net Income",
)


@dataclass
class CrisisValueFilters:
    universe: str = "Nifty 50 (NSE)"
    min_earnings_years: int = 3
    min_positive_year_pct: float = 100.0
    max_single_year_drop_pct: float = 25.0
    max_earnings_cv: float = 0.40
    min_earnings_cagr_pct: float = -5.0
    min_drawdown_52w_pct: float = 20.0
    min_drawdown_3y_pct: float = 15.0
    min_eps_price_divergence_pct: float = 15.0
    max_pe: float = 28.0
    min_roe_pct: float = 12.0
    max_debt_equity: float = 1.2
    min_crisis_score: float = 55.0
    require_price_below_3y: bool = True
    max_tickers: int = 80
    info_delay_sec: float = 0.12


@dataclass
class CrisisValueResult:
    ticker: str
    raw_ticker: str
    sector: str
    price: float
    pe: Optional[float]
    roe_pct: Optional[float]
    debt_equity: Optional[float]
    earnings_years: int
    earnings_cagr_pct: Optional[float]
    max_yoy_drop_pct: Optional[float]
    positive_year_pct: float
    earnings_cv: Optional[float]
    stability_score: float
    drawdown_52w_pct: Optional[float]
    drawdown_3y_pct: Optional[float]
    price_return_3y_pct: Optional[float]
    price_return_5y_pct: Optional[float]
    eps_price_divergence_pct: Optional[float]
    crisis_score: float
    verdict: str
    action: str
    thesis: str
    market_cap_display: str
    links: dict = field(default_factory=dict)


@dataclass
class CrisisValueScanStats:
    universe: str
    tickers_scanned: int = 0
    tickers_matched: int = 0
    no_data: int = 0
    scan_elapsed_sec: float = 0.0


def universe_options() -> list[str]:
    return list(UNIVERSES.keys())


def _gf(info: dict, keys: tuple[str, ...]) -> Optional[float]:
    for k in keys:
        v = info.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
            if np.isnan(fv):
                continue
            return fv
        except (TypeError, ValueError):
            continue
    return None


def extract_annual_earnings_series(ticker_obj) -> list[float]:
    """Oldest → newest annual earnings (EPS preferred, else net income)."""
    try:
        inc = ticker_obj.income_stmt
    except Exception:
        return []
    if inc is None or inc.empty:
        return []
    row = None
    for label in _EARNINGS_ROW_PRIORITY:
        if label in inc.index:
            row = inc.loc[label]
            break
    if row is None:
        return []
    vals: list[float] = []
    for v in row.values:
        try:
            fv = float(v)
            if not np.isnan(fv):
                vals.append(fv)
        except (TypeError, ValueError):
            continue
    vals.reverse()
    return vals


def _yoy_changes(values: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        if prev == 0:
            continue
        out.append((cur / prev - 1.0) * 100.0)
    return out


def earnings_stability_metrics(values: list[float]) -> dict:
    if len(values) < 2:
        return {}
    yoy = _yoy_changes(values)
    positive = sum(1 for v in values if v > 0)
    pos_pct = 100.0 * positive / len(values)
    max_drop = 0.0
    for ch in yoy:
        if ch < 0:
            max_drop = max(max_drop, abs(ch))
    mean_v = float(np.mean(values))
    cv = float(np.std(values) / abs(mean_v)) if mean_v != 0 else 99.0
    n = len(values)
    cagr = None
    if values[0] > 0 and values[-1] > 0 and n >= 2:
        cagr = ((values[-1] / values[0]) ** (1.0 / (n - 1)) - 1.0) * 100.0

    score = 0.0
    if pos_pct >= 100:
        score += 35
    elif pos_pct >= 80:
        score += 20
    if max_drop <= 10:
        score += 25
    elif max_drop <= 20:
        score += 15
    elif max_drop <= 30:
        score += 5
    if cv <= 0.15:
        score += 25
    elif cv <= 0.25:
        score += 18
    elif cv <= 0.35:
        score += 10
    if cagr is not None:
        if cagr >= 8:
            score += 15
        elif cagr >= 3:
            score += 10
        elif cagr >= 0:
            score += 5
    return {
        "years": n,
        "positive_year_pct": round(pos_pct, 1),
        "max_yoy_drop_pct": round(max_drop, 1),
        "earnings_cv": round(cv, 3),
        "earnings_cagr_pct": round(cagr, 2) if cagr is not None else None,
        "stability_score": min(100.0, round(score, 1)),
    }


def price_dislocation_metrics(
    hist: pd.DataFrame,
    price: float,
    week52_high: Optional[float],
    earnings_cagr_pct: Optional[float],
) -> dict:
    out: dict = {
        "drawdown_52w_pct": drawdown_pct_from_52w_high(price, week52_high),
        "drawdown_3y_pct": None,
        "price_return_3y_pct": None,
        "price_return_5y_pct": None,
        "eps_price_divergence_pct": None,
    }
    if hist is None or hist.empty:
        return out

    closes = hist_series(hist, "Close")
    if closes is None or len(closes) < 60:
        return out

    last = float(closes.iloc[-1])
    high_3y = float(closes.max())
    if high_3y > 0 and last > 0:
        out["drawdown_3y_pct"] = round((1.0 - last / high_3y) * 100.0, 1)

    def _ret(bars_back: int) -> Optional[float]:
        if len(closes) <= bars_back:
            return None
        old = float(closes.iloc[-bars_back - 1])
        if old <= 0:
            return None
        return round((last / old - 1.0) * 100.0, 1)

    out["price_return_3y_pct"] = _ret(min(756, len(closes) - 1))
    out["price_return_5y_pct"] = _ret(min(1260, len(closes) - 1))

    pr = out["price_return_3y_pct"]
    if earnings_cagr_pct is not None and pr is not None:
        out["eps_price_divergence_pct"] = round(earnings_cagr_pct - pr, 1)
    return out


def crisis_score(
    *,
    stability_score: float,
    divergence_pct: Optional[float],
    drawdown_52w: Optional[float],
    pe: Optional[float],
) -> float:
    div_pts = 0.0
    if divergence_pct is not None:
        div_pts = min(35.0, max(0.0, divergence_pct) * 1.2)
    dd_pts = 0.0
    if drawdown_52w is not None:
        dd_pts = min(20.0, drawdown_52w * 0.45)
    val_pts = 0.0
    if pe is not None and pe > 0:
        if pe <= 12:
            val_pts = 15
        elif pe <= 18:
            val_pts = 12
        elif pe <= 22:
            val_pts = 8
        elif pe <= 28:
            val_pts = 4
    raw = stability_score * 0.45 + div_pts + dd_pts + val_pts
    return min(100.0, round(raw, 1))


def verdict_label(
    crisis_score_val: float,
    divergence: Optional[float],
    drawdown_52w: Optional[float],
) -> tuple[str, str, str]:
    if crisis_score_val >= 75 and (divergence or 0) >= 25:
        return (
            "Strong 2008-style gap",
            "BUY candidate",
            "Earnings held or grew while the market priced in permanent impairment — "
            "verify balance sheet and cycle before sizing in.",
        )
    if crisis_score_val >= 60:
        return (
            "Quality dislocation",
            "Watchlist / scale in",
            "Consistent earnings with meaningful price markdown — "
            "wait for trend confirmation or add in tranches.",
        )
    return (
        "Moderate setup",
        "Research further",
        "Some stability + drawdown present — confirm earnings quality on Screener.in "
        "and that the dip is sentiment, not structural decline.",
    )


def analyze_ticker_crisis_value(raw: str, flt: CrisisValueFilters) -> Optional[CrisisValueResult]:
    try:
        stk = yf.Ticker(raw)
        info = stk.info or {}
        fund = extract_multibagger_fundamentals(info)
        hdip = extract_healthy_dip_fundamentals(info)
        sector, _ = get_sector_industry(stk)

        earnings = extract_annual_earnings_series(stk)
        if len(earnings) < flt.min_earnings_years:
            return None

        stab = earnings_stability_metrics(earnings)
        if stab.get("positive_year_pct", 0) < flt.min_positive_year_pct:
            return None
        if stab.get("max_yoy_drop_pct", 99) > flt.max_single_year_drop_pct:
            return None
        if stab.get("earnings_cv", 99) > flt.max_earnings_cv:
            return None
        cagr = stab.get("earnings_cagr_pct")
        if cagr is not None and cagr < flt.min_earnings_cagr_pct:
            return None

        hist = stk.history(period="5y", interval="1d", auto_adjust=True)
        price = _gf(info, ("currentPrice", "regularMarketPrice", "regularMarketPreviousClose"))
        if not price and hist is not None and not hist.empty:
            price = float(hist_series(hist, "Close").iloc[-1])
        if not price or price <= 0:
            return None

        w52 = _gf(info, ("fiftyTwoWeekHigh", "52WeekHigh"))
        px = price_dislocation_metrics(hist, float(price), w52, cagr)

        dd52 = px.get("drawdown_52w_pct")
        dd3 = px.get("drawdown_3y_pct")
        if dd52 is None or dd52 < flt.min_drawdown_52w_pct:
            return None
        if dd3 is not None and dd3 < flt.min_drawdown_3y_pct:
            return None
        if flt.require_price_below_3y:
            pr3 = px.get("price_return_3y_pct")
            if pr3 is not None and pr3 > 5.0:
                return None

        div = px.get("eps_price_divergence_pct")
        if div is None or div < flt.min_eps_price_divergence_pct:
            return None

        pe_cap = PE_DATA_CAP.get(flt.universe, 400)
        pe = get_pe(stk)
        if pe is not None and (pe <= 0 or pe > min(flt.max_pe, pe_cap)):
            return None

        roe = hdip.get("roe_pct") or fund.get("roe_pct")
        if roe is not None and roe < flt.min_roe_pct:
            return None
        de = normalize_debt_equity(hdip.get("debt_equity") or fund.get("debt_equity"))
        if de is not None and de > flt.max_debt_equity:
            return None

        score = crisis_score(
            stability_score=stab["stability_score"],
            divergence_pct=div,
            drawdown_52w=dd52,
            pe=pe,
        )
        if score < flt.min_crisis_score:
            return None

        verdict, action, thesis = verdict_label(score, div, dd52)
        disp = raw.replace(".NS", "").replace(".BO", "")

        return CrisisValueResult(
            ticker=disp,
            raw_ticker=raw,
            sector=sector or "—",
            price=round(float(price), 2),
            pe=pe,
            roe_pct=roe,
            debt_equity=de,
            earnings_years=stab["years"],
            earnings_cagr_pct=cagr,
            max_yoy_drop_pct=stab.get("max_yoy_drop_pct"),
            positive_year_pct=stab["positive_year_pct"],
            earnings_cv=stab.get("earnings_cv"),
            stability_score=stab["stability_score"],
            drawdown_52w_pct=dd52,
            drawdown_3y_pct=dd3,
            price_return_3y_pct=px.get("price_return_3y_pct"),
            price_return_5y_pct=px.get("price_return_5y_pct"),
            eps_price_divergence_pct=div,
            crisis_score=score,
            verdict=verdict,
            action=action,
            thesis=thesis,
            market_cap_display=fund.get("market_cap_display", "—"),
            links=get_stock_links(raw),
        )
    except Exception:
        return None


def scan_crisis_value(
    flt: CrisisValueFilters,
    *,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[CrisisValueResult], CrisisValueScanStats]:
    t0 = time.time()
    tickers = list(UNIVERSES.get(flt.universe, []))[: flt.max_tickers]
    stats = CrisisValueScanStats(universe=flt.universe)
    results: list[CrisisValueResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        r = analyze_ticker_crisis_value(raw, flt)
        if r is None:
            stats.no_data += 1
            continue
        results.append(r)
        stats.tickers_matched += 1
        if flt.info_delay_sec > 0:
            time.sleep(flt.info_delay_sec)

    results.sort(key=lambda x: (-x.crisis_score, -(x.eps_price_divergence_pct or 0)))
    stats.scan_elapsed_sec = time.time() - t0
    return results, stats
