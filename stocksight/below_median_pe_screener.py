"""
Healthy Below Median PE — quality stocks trading below historical Mar FY median P/E.

Uses Screener.in EPS + Yahoo FY-end prices (pe_history) and quality gates
(ROCE, growth, D/E, mcap). Educational only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import yfinance as yf

try:
    from .multibagger import (
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        normalize_debt_equity,
        resolve_scan_tickers,
    )
    from .pe_history import build_pe_history
    from .screener import get_pe, get_sector_industry, get_stock_links
    from .screener_in_data import fetch_screener_company_html
except ImportError:
    from multibagger import (
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        normalize_debt_equity,
        resolve_scan_tickers,
    )
    from pe_history import build_pe_history
    from screener import get_pe, get_sector_industry, get_stock_links
    from screener_in_data import fetch_screener_company_html

META = {
    "id": "below_median_pe",
    "title": "Healthy Below Median PE",
    "emoji": "📉",
    "nav_title": "Below Median PE",
    "audience": (
        "Investors hunting **quality businesses** trading **below their own historical "
        "median P/E** — mean-reversion value with health filters."
    ),
    "purpose": (
        "Builds Mar FY P/E history (Screener EPS + Yahoo prices), computes **FY median P/E**, "
        "and keeps names where **current P/E < median** with ROCE, profit growth, and D/E gates."
    ),
}

RANK_BY_OPTIONS: dict[str, str] = {
    "discount": "Discount vs median % (most undervalued)",
    "score": "Health + discount score",
    "pe": "Current P/E (lowest)",
    "roce": "ROCE %",
    "growth": "Profit growth 3Y %",
}


@dataclass
class BelowMedianPeFilters:
    min_fy_points: int = 5
    max_pct_vs_median: float = -5.0  # current at least 5% below median
    min_roce_pct: float = 15.0
    min_roe_pct: float = 12.0
    min_profit_growth_3y_pct: float = 12.0
    min_profit_growth_ttm_pct: float = 0.0
    require_ttm_growth: bool = False
    max_debt_equity: float = 1.0
    min_market_cap_cr: float = 300.0
    max_pe: float = 45.0  # soft cap — exclude broken/outlier PE
    min_eps: float = 1.0
    screener_delay_sec: float = 0.18
    info_delay_sec: float = 0.05


@dataclass
class BelowMedianPeResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    price: Optional[float]
    current_pe: Optional[float]
    fy_median_pe: Optional[float]
    median_pe: Optional[float]
    pct_vs_median: Optional[float]
    n_fy_points: int
    trailing_eps: Optional[float]
    roce_pct: Optional[float]
    roe_pct: Optional[float]
    profit_growth_3y_pct: Optional[float]
    profit_growth_ttm_pct: Optional[float]
    debt_equity: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    score: float
    verdict: str
    pass_notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)


def _mcap_display(cr: Optional[float]) -> str:
    if cr is None:
        return "—"
    if cr >= 100_000:
        return f"₹{cr / 100_000:.2f} L Cr"
    if cr >= 1_000:
        return f"₹{cr:,.0f} Cr"
    return f"₹{cr:.0f} Cr"


def _score(
    pct_vs_median: Optional[float],
    roce: Optional[float],
    g3: Optional[float],
    pe: Optional[float],
) -> float:
    # More negative pct_vs_median = larger discount = higher score
    disc = abs(min(float(pct_vs_median or 0.0), 0.0)) * 0.55
    roce_pts = min(float(roce or 0.0), 40.0) * 0.35
    g_pts = min(float(g3 or 0.0), 40.0) * 0.4
    pe_pts = max(0.0, 25.0 - float(pe or 25.0)) * 0.4
    return round(disc + roce_pts + g_pts + pe_pts, 1)


def _verdict(pct: Optional[float], roce: Optional[float], g3: Optional[float]) -> str:
    p = float(pct or 0.0)
    if p <= -25 and (roce or 0) >= 18 and (g3 or 0) >= 15:
        return "Deep discount + healthy compounder"
    if p <= -15 and (roce or 0) >= 15:
        return "Clear discount to own history"
    if p <= -5:
        return "Below median — confirm quality"
    return "Near median — thin edge"


def _passes(
    meta: dict,
    fund: dict,
    flt: BelowMedianPeFilters,
) -> tuple[bool, list[str], Optional[float], Optional[float]]:
    notes: list[str] = []
    cur = meta.get("current_pe")
    fy_med = meta.get("fy_median_pe") or meta.get("median_pe")
    n_fy = int(meta.get("n_fy_points") or 0)

    if n_fy < flt.min_fy_points:
        return False, notes, cur, fy_med
    if cur is None or fy_med is None or fy_med <= 0:
        return False, notes, cur, fy_med
    if cur > flt.max_pe:
        return False, notes, cur, fy_med
    if cur < 0:
        return False, notes, cur, fy_med

    pct = round((float(cur) / float(fy_med) - 1.0) * 100.0, 1)
    if pct > flt.max_pct_vs_median:
        return False, notes, cur, fy_med
    notes.append(f"P/E {cur:.1f} vs FY median {fy_med:.1f} ({pct:+.1f}%)")
    notes.append(f"{n_fy} Mar FY P/E points")

    eps = meta.get("current_eps")
    if eps is None or float(eps) < flt.min_eps:
        return False, notes, cur, fy_med

    roce = meta.get("roce_pct")
    if roce is None:
        roce = fund.get("roce_pct")
    if roce is None or roce < flt.min_roce_pct:
        return False, notes, cur, fy_med
    notes.append(f"ROCE {roce:.1f}%")

    roe = meta.get("roe_pct") or fund.get("roe_pct")
    if roe is not None and roe < flt.min_roe_pct:
        return False, notes, cur, fy_med
    if roe is not None:
        notes.append(f"ROE {roe:.1f}%")

    g3 = meta.get("profit_growth_3y_pct")
    if g3 is None or g3 < flt.min_profit_growth_3y_pct:
        return False, notes, cur, fy_med
    notes.append(f"Profit 3Y {g3:.1f}%")

    gttm = meta.get("profit_growth_ttm_pct")
    if flt.require_ttm_growth:
        if gttm is None or gttm < flt.min_profit_growth_ttm_pct:
            return False, notes, cur, fy_med
        notes.append(f"TTM profit {gttm:.1f}%")

    mcap = meta.get("market_cap_cr") or fund.get("market_cap_cr")
    if mcap is None or mcap < flt.min_market_cap_cr:
        return False, notes, cur, fy_med

    de = normalize_debt_equity(fund.get("debt_equity"))
    if de is not None and de > flt.max_debt_equity:
        return False, notes, cur, fy_med
    if de is not None:
        notes.append(f"D/E {de:.2f}")

    return True, notes, cur, fy_med


def scan_below_median_pe(
    scan_source: str,
    filters: BelowMedianPeFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[BelowMedianPeResult]:
    flt = filters or BelowMedianPeFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[BelowMedianPeResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        try:
            if not (raw.endswith(".NS") or raw.endswith(".BO")):
                continue
            disp = raw.replace(".NS", "").replace(".BO", "")
            html = fetch_screener_company_html(disp)
            if flt.screener_delay_sec > 0:
                time.sleep(flt.screener_delay_sec)

            _points, meta = build_pe_history(disp, raw, html=html)
            stock = yf.Ticker(raw)
            try:
                info = stock.info or {}
            except Exception:
                info = {}
            fund = extract_multibagger_fundamentals(info)

            ok, notes, cur, fy_med = _passes(meta, fund, flt)
            if not ok:
                continue

            pct = meta.get("pct_vs_fy_median")
            if pct is None and cur and fy_med:
                pct = round((float(cur) / float(fy_med) - 1.0) * 100.0, 1)

            price = meta.get("current_price")
            if not price:
                try:
                    price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0) or None
                except Exception:
                    price = None

            pe_yahoo = get_pe(stock)
            if cur is None and pe_yahoo is not None:
                cur = pe_yahoo

            roce = meta.get("roce_pct") or fund.get("roce_pct")
            g3 = meta.get("profit_growth_3y_pct")
            score = _score(pct, roce, g3, cur)
            verdict = _verdict(pct, roce, g3)
            sector, _ = get_sector_industry(stock)
            mcap = meta.get("market_cap_cr") or fund.get("market_cap_cr")
            links = {**get_stock_links(raw), "Screener.in": f"https://www.screener.in/company/{disp}/consolidated/"}

            results.append(
                BelowMedianPeResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    sector=sector or "—",
                    price=round(float(price), 2) if price else None,
                    current_pe=round(float(cur), 2) if cur is not None else None,
                    fy_median_pe=round(float(fy_med), 2) if fy_med is not None else None,
                    median_pe=meta.get("median_pe"),
                    pct_vs_median=pct,
                    n_fy_points=int(meta.get("n_fy_points") or 0),
                    trailing_eps=meta.get("current_eps"),
                    roce_pct=roce,
                    roe_pct=meta.get("roe_pct") or fund.get("roe_pct"),
                    profit_growth_3y_pct=g3,
                    profit_growth_ttm_pct=meta.get("profit_growth_ttm_pct"),
                    debt_equity=normalize_debt_equity(fund.get("debt_equity")),
                    market_cap_cr=mcap,
                    market_cap_display=_mcap_display(mcap) if mcap else (fund.get("market_cap_display") or ""),
                    score=score,
                    verdict=verdict,
                    pass_notes=notes,
                    links=links,
                )
            )
        except Exception:
            continue

        if flt.info_delay_sec > 0:
            time.sleep(flt.info_delay_sec)

    return sort_below_median_pe(results, rank_by="discount")


def sort_below_median_pe(
    results: list[BelowMedianPeResult],
    *,
    rank_by: str = "discount",
) -> list[BelowMedianPeResult]:
    if rank_by == "pe":
        return sorted(
            results,
            key=lambda r: float(r.current_pe) if r.current_pe is not None else 9999.0,
        )
    if rank_by == "roce":
        return sorted(results, key=lambda r: float(r.roce_pct or -9999.0), reverse=True)
    if rank_by == "growth":
        return sorted(results, key=lambda r: float(r.profit_growth_3y_pct or -9999.0), reverse=True)
    if rank_by == "score":
        return sorted(results, key=lambda r: float(r.score or 0.0), reverse=True)
    # Most discounted first (most negative pct_vs_median)
    return sorted(
        results,
        key=lambda r: float(r.pct_vs_median) if r.pct_vs_median is not None else 9999.0,
    )


def result_to_row(r: BelowMedianPeResult, rank: int) -> dict:
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Score": r.score,
        "Verdict": r.verdict,
        "P/E now": r.current_pe,
        "FY median P/E": r.fy_median_pe,
        "vs median %": r.pct_vs_median,
        "FY points": r.n_fy_points,
        "EPS ₹": r.trailing_eps,
        "ROCE %": r.roce_pct,
        "ROE %": r.roe_pct,
        "Profit 3Y %": r.profit_growth_3y_pct,
        "Profit TTM %": r.profit_growth_ttm_pct,
        "D/E": r.debt_equity,
        "Price": r.price,
        "Mcap": r.market_cap_display,
        "Sector": r.sector,
        "Notes": " · ".join(r.pass_notes[:4]),
    }
