"""
Value Growth screener — low P/E, high trailing EPS, solid profit growth (Screener.in).

Uses Screener.in consolidated page for P/E, EPS (Mar FY), and Compounded Profit Growth
(3Y / 5Y / TTM) as the forward-earnings proxy. Educational only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    from .multibagger import SCAN_SOURCES, resolve_scan_tickers
    from .screener import get_stock_links
    from .screener_in_data import fetch_screener_value_profile
except ImportError:
    from multibagger import SCAN_SOURCES, resolve_scan_tickers
    from screener import get_stock_links
    from screener_in_data import fetch_screener_value_profile

META = {
    "id": "value_growth",
    "title": "Value Growth (Low P/E · EPS · Growth)",
    "emoji": "📐",
    "nav_title": "Value Growth",
    "audience": (
        "GARP-style hunters: **cheap on P/E**, **high trailing EPS**, and **solid profit compounding** "
        "from Screener.in — not hype multiples."
    ),
    "purpose": (
        "Pulls **Stock P/E**, **EPS in Rs** (latest Mar FY), and **Compounded Profit Growth** "
        "(3Y / TTM) from Screener.in. Ranks by value-growth score (low PE + EPS + growth)."
    ),
}

RANK_OPTIONS: dict[str, str] = {
    "score": "Value-growth score",
    "pe": "P/E (lowest)",
    "eps": "Trailing EPS (highest)",
    "growth_3y": "Profit growth 3Y %",
    "peg": "PEG proxy (lowest)",
}


@dataclass
class ValueGrowthFilters:
    max_pe: float = 22.0
    min_eps: float = 8.0
    min_profit_growth_3y_pct: float = 12.0
    min_profit_growth_ttm_pct: float = 8.0
    require_ttm_growth: bool = True
    min_roce_pct: float = 12.0
    min_market_cap_cr: float = 300.0
    max_market_cap_cr: float = 500_000.0
    screener_delay_sec: float = 0.22


@dataclass
class ValueGrowthResult:
    ticker: str
    raw_ticker: str
    label: str
    price: Optional[float]
    pe: Optional[float]
    trailing_eps: Optional[float]
    eps_fy: Optional[int]
    profit_growth_3y_pct: Optional[float]
    profit_growth_5y_pct: Optional[float]
    profit_growth_ttm_pct: Optional[float]
    sales_growth_3y_pct: Optional[float]
    roce_pct: Optional[float]
    roe_pct: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    peg_proxy: Optional[float]
    value_score: float
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


def _peg_proxy(pe: Optional[float], growth: Optional[float]) -> Optional[float]:
    if pe is None or growth is None or growth <= 0:
        return None
    return round(float(pe) / float(growth), 2)


def _value_score(
    pe: Optional[float],
    eps: Optional[float],
    g3: Optional[float],
    gttm: Optional[float],
    roce: Optional[float],
) -> float:
    pe_pts = max(0.0, 30.0 - float(pe or 30.0)) * 1.2
    eps_pts = min(float(eps or 0.0), 80.0) * 0.35
    g_pts = min(float(g3 or 0.0), 40.0) * 0.9 + min(float(gttm or 0.0), 40.0) * 0.5
    roce_pts = min(float(roce or 0.0), 35.0) * 0.25
    return round(pe_pts + eps_pts + g_pts + roce_pts, 1)


def _verdict(pe: Optional[float], eps: Optional[float], g3: Optional[float], peg: Optional[float]) -> str:
    if pe is not None and pe <= 15 and (g3 or 0) >= 15 and (eps or 0) >= 15:
        return "Deep value + compounding"
    if peg is not None and peg <= 1.0:
        return "GARP — PEG ≤ 1"
    if pe is not None and pe <= 20 and (g3 or 0) >= 12:
        return "Reasonable value + growth"
    if pe is not None and pe > 25:
        return "Growth OK but P/E stretched"
    return "Watch — verify on concall"


def _passes(profile: dict, flt: ValueGrowthFilters) -> tuple[bool, list[str]]:
    notes: list[str] = []
    pe = profile.get("pe")
    eps = profile.get("trailing_eps")
    g3 = profile.get("profit_growth_3y_pct")
    gttm = profile.get("profit_growth_ttm_pct")
    roce = profile.get("roce_pct")
    mcap = profile.get("market_cap_cr")

    if pe is None or pe <= 0 or pe > flt.max_pe:
        return False, notes
    notes.append(f"P/E {pe:.1f}")

    if eps is None or eps < flt.min_eps:
        return False, notes
    notes.append(f"EPS ₹{eps:.2f}")

    if g3 is None or g3 < flt.min_profit_growth_3y_pct:
        return False, notes
    notes.append(f"Profit 3Y {g3:.1f}%")

    if flt.require_ttm_growth:
        if gttm is None or gttm < flt.min_profit_growth_ttm_pct:
            return False, notes
        notes.append(f"Profit TTM {gttm:.1f}%")

    if roce is None or roce < flt.min_roce_pct:
        return False, notes
    notes.append(f"ROCE {roce:.1f}%")

    if mcap is not None:
        if mcap < flt.min_market_cap_cr or mcap > flt.max_market_cap_cr:
            return False, notes
        notes.append(f"Mcap {_mcap_display(mcap)}")

    return True, notes


def scan_value_growth(
    scan_source: str,
    filters: ValueGrowthFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    *,
    max_results: int = 60,
) -> list[ValueGrowthResult]:
    flt = filters or ValueGrowthFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[ValueGrowthResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        if len(results) >= max_results:
            break

        if not raw.endswith((".NS", ".BO")):
            continue

        try:
            disp = raw.replace(".NS", "").replace(".BO", "")
            profile = fetch_screener_value_profile(disp)
            if not profile.get("pe") and not profile.get("trailing_eps"):
                continue

            ok, notes = _passes(profile, flt)
            if not ok:
                continue

            pe = profile.get("pe")
            eps = profile.get("trailing_eps")
            g3 = profile.get("profit_growth_3y_pct")
            gttm = profile.get("profit_growth_ttm_pct")
            roce = profile.get("roce_pct")
            peg = _peg_proxy(pe, g3 or gttm)
            mcap = profile.get("market_cap_cr")
            score = _value_score(pe, eps, g3, gttm, roce)

            links = get_stock_links(raw)
            links["Screener.in"] = profile.get("screener_url") or links.get("Screener.in", "")

            results.append(
                ValueGrowthResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    price=profile.get("price"),
                    pe=pe,
                    trailing_eps=eps,
                    eps_fy=profile.get("eps_fy"),
                    profit_growth_3y_pct=g3,
                    profit_growth_5y_pct=profile.get("profit_growth_5y_pct"),
                    profit_growth_ttm_pct=gttm,
                    sales_growth_3y_pct=profile.get("sales_growth_3y_pct"),
                    roce_pct=roce,
                    roe_pct=profile.get("roe_pct"),
                    market_cap_cr=mcap,
                    market_cap_display=_mcap_display(mcap),
                    peg_proxy=peg,
                    value_score=score,
                    verdict=_verdict(pe, eps, g3, peg),
                    pass_notes=notes,
                    links=links,
                )
            )
        except Exception:
            continue

        if flt.screener_delay_sec > 0:
            time.sleep(flt.screener_delay_sec)

    return sort_value_growth_results(results)


def sort_value_growth_results(
    results: list[ValueGrowthResult],
    *,
    rank_by: str = "score",
) -> list[ValueGrowthResult]:
    if rank_by == "pe":
        key = lambda r: float(r.pe if r.pe is not None else 9999.0)
        return sorted(results, key=key)
    if rank_by == "eps":
        key = lambda r: float(r.trailing_eps or -9999.0)
        return sorted(results, key=key, reverse=True)
    if rank_by == "growth_3y":
        key = lambda r: float(r.profit_growth_3y_pct or -9999.0)
        return sorted(results, key=key, reverse=True)
    if rank_by == "peg":
        key = lambda r: float(r.peg_proxy if r.peg_proxy is not None else 9999.0)
        return sorted(results, key=key)
    key = lambda r: float(r.value_score or 0.0)
    return sorted(results, key=key, reverse=True)


def result_to_row(r: ValueGrowthResult, rank: int) -> dict:
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Score": r.value_score,
        "Verdict": r.verdict,
        "P/E": r.pe,
        "EPS ₹": r.trailing_eps,
        "EPS FY": r.eps_fy,
        "Profit 3Y %": r.profit_growth_3y_pct,
        "Profit TTM %": r.profit_growth_ttm_pct,
        "Profit 5Y %": r.profit_growth_5y_pct,
        "Sales 3Y %": r.sales_growth_3y_pct,
        "PEG proxy": r.peg_proxy,
        "ROCE %": r.roce_pct,
        "ROE %": r.roe_pct,
        "Price ₹": r.price,
        "Mcap": r.market_cap_display,
        "Notes": " · ".join(r.pass_notes[:5]),
    }
