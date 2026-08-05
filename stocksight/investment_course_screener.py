"""
Investment Course Screener — FF Basic→Advance / Lynch-style categories.

Classifies NSE names using Screener.in compounded sales+profit CAGR, then applies
course buy gates (PEG, PE vs FY median, Chapter 10 volume spike). Educational only;
inspired by publicly shared course notes — not affiliated with Financially Free™.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import yfinance as yf

try:
    from .multibagger import SCAN_SOURCES, resolve_scan_tickers
    from .pe_history import build_pe_history
    from .screener import fetch_price_history, get_sector_industry, get_stock_links, hist_series
    from .screener_in_data import fetch_screener_company_html, fetch_screener_value_profile
except ImportError:
    from multibagger import SCAN_SOURCES, resolve_scan_tickers
    from pe_history import build_pe_history
    from screener import fetch_price_history, get_sector_industry, get_stock_links, hist_series
    from screener_in_data import fetch_screener_company_html, fetch_screener_value_profile

META = {
    "id": "investment_course",
    "title": "Investment Course (Lynch Categories)",
    "emoji": "📘",
    "nav_title": "Investment Course",
    "audience": (
        "Investors learning **Fast Grower · Stalwart · Cyclical · Slow Grower** rules — "
        "sales+profit CAGR from Screener.in, PEG, and PE vs own FY median."
    ),
    "purpose": (
        "Implements Basic→Advance course gates: Fast Grower (≥15% sales & profit), "
        "Stalwart (10–15%, buy ≤ FY median PE), PEG < 1, and Ch.10 volume spike. "
        "Educational approximation — verify on Screener.in / annual reports."
    ),
}

SCAN_MODES: dict[str, str] = {
    "buy_candidates": "Buy candidates (Fast PEG≤1 or Stalwart ≤ median PE)",
    "fast_growers": "Fast Growers (sales & profit ≥15%)",
    "stalwarts_discount": "Stalwarts at discount (10–15% + PE ≤ FY median)",
    "volume_spike": "Volume spike (Ch.10 formula)",
    "classify_all": "Classify all (no buy gate)",
}

RANK_BY_OPTIONS: dict[str, str] = {
    "score": "Course score",
    "peg": "PEG (lowest)",
    "discount": "Discount vs FY median %",
    "growth": "Min(sales, profit) 3Y %",
    "vol_ratio": "Volume ratio (spike mode)",
}

CYCLICAL_KEYWORDS = (
    "cement",
    "paper",
    "steel",
    "iron",
    "cotton",
    "textile",
    "agri",
    "agriculture",
    "sugar",
    "cable",
    "wire",
    "mdf",
    "wood",
    "plywood",
    "chemical",
    "commodity",
    "metal",
    "mining",
    "aluminium",
    "aluminum",
    "copper",
    "shipping",
    "construction",
    "building",
)

INDIA_GDP_PROXY_PCT = 7.0
FAST_GROWTH_PCT = 15.0
STALWART_MIN_PCT = 10.0


@dataclass
class InvestmentCourseFilters:
    mode: str = "buy_candidates"
    max_peg: float = 1.0
    max_pct_vs_fy_median: float = 0.0  # at or below median
    min_fy_points: int = 3
    min_market_cap_cr: float = 500.0
    volume_min_market_cap_cr: float = 50.0
    max_debt_equity: float = 2.0
    min_roce_pct: float = 0.0  # soft; 0 = off
    vol_mult: float = 5.0
    min_week_return_pct: float = 5.0
    screener_delay_sec: float = 0.18
    need_pe_history: bool = True


@dataclass
class InvestmentCourseResult:
    ticker: str
    raw_ticker: str
    label: str
    category: str
    sector: str
    price: Optional[float]
    pe: Optional[float]
    fy_median_pe: Optional[float]
    pct_vs_median: Optional[float]
    n_fy_points: int
    sales_growth_3y_pct: Optional[float]
    profit_growth_3y_pct: Optional[float]
    peg: Optional[float]
    peg_verdict: str
    roce_pct: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    week_return_pct: Optional[float]
    vol_ratio: Optional[float]
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


def _peg(pe: Optional[float], growth: Optional[float]) -> Optional[float]:
    if pe is None or pe <= 0 or growth is None or growth <= 0:
        return None
    return round(float(pe) / float(growth), 2)


def peg_verdict(peg: Optional[float]) -> str:
    if peg is None:
        return "—"
    if peg < 1.0:
        return "Cheap (PEG < 1) - Buy zone"
    if peg <= 1.05:
        return "Fair (PEG ~ 1) - Hold"
    return "Expensive (PEG > 1) - Avoid / Don't buy"


def _is_cyclical(sector: str, industry: str = "") -> bool:
    blob = f"{sector} {industry}".lower()
    return any(k in blob for k in CYCLICAL_KEYWORDS)


def classify_category(
    sales_3y: Optional[float],
    profit_3y: Optional[float],
    *,
    sector: str = "",
    industry: str = "",
) -> tuple[str, str]:
    """Return (category, rationale) from course growth bands."""
    s = float(sales_3y) if sales_3y is not None else None
    p = float(profit_3y) if profit_3y is not None else None

    if s is not None and p is not None:
        if s >= FAST_GROWTH_PCT and p >= FAST_GROWTH_PCT:
            return "Fast Grower", f"Sales {s:.1f}% & profit {p:.1f}% >= 15%"
        if STALWART_MIN_PCT <= s < FAST_GROWTH_PCT and STALWART_MIN_PCT <= p < FAST_GROWTH_PCT:
            return "Stalwart", f"Sales {s:.1f}% & profit {p:.1f}% in 10-15%"
        if s < INDIA_GDP_PROXY_PCT and p < INDIA_GDP_PROXY_PCT:
            return "Slow Grower", f"Both growth < ~{INDIA_GDP_PROXY_PCT:.0f}% GDP - prefer FD"

    if _is_cyclical(sector, industry):
        return "Cyclical", f"Sector/industry matches cyclical keywords ({sector or '—'})"

    if s is None or p is None:
        return "Unclassified", "Missing sales or profit 3Y CAGR"
    return "Other", f"Sales {s:.1f}% / profit {p:.1f}% — not in Fast/Stalwart/Slow bands"


def _course_score(
    category: str,
    peg: Optional[float],
    pct_vs: Optional[float],
    sales: Optional[float],
    profit: Optional[float],
) -> float:
    g = min(float(sales or 0), float(profit or 0))
    pts = min(g, 40.0) * 0.5
    if peg is not None and peg > 0:
        pts += max(0.0, 2.0 - peg) * 20.0
    if pct_vs is not None:
        pts += abs(min(pct_vs, 0.0)) * 0.4
    if category == "Fast Grower":
        pts += 8.0
    elif category == "Stalwart":
        pts += 5.0
    elif category == "Slow Grower":
        pts -= 15.0
    return round(pts, 1)


def _verdict(category: str, peg: Optional[float], pct_vs: Optional[float], mode: str) -> str:
    if category == "Slow Grower":
        return "Avoid — slow grower (FD better)"
    if mode == "volume_spike":
        return "Volume spike — research story"
    if category == "Fast Grower":
        if peg is not None and peg < 1.0:
            return "Fast Grower + cheap PEG"
        if peg is not None and peg <= 1.05:
            return "Fast Grower — fair PEG"
        return "Fast Grower — check valuation"
    if category == "Stalwart":
        if pct_vs is not None and pct_vs <= 0:
            return "Stalwart at/below median PE"
        return "Stalwart — wait for lower PE"
    if category == "Cyclical":
        if pct_vs is not None and pct_vs <= 0:
            return "Cyclical — PE below history"
        return "Cyclical — watch margins / cycle"
    return "Review story / category"


def _volume_spike_metrics(raw: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (week_return_pct, vol_ratio, last_price)."""
    try:
        hist = fetch_price_history(raw, "1d")
    except Exception:
        hist = None
    if hist is None or hist.empty or len(hist) < 30:
        return None, None, None

    close = hist_series(hist, "Close")
    vol = hist_series(hist, "Volume")
    if close is None or close.empty or vol is None or vol.empty:
        return None, None, None

    n = min(5, len(close) - 1)
    if n < 1:
        return None, None, None
    try:
        week_ret = (float(close.iloc[-1]) / float(close.iloc[-1 - n]) - 1.0) * 100.0
    except Exception:
        week_ret = None

    vol_1w = float(vol.tail(5).mean()) if len(vol) >= 5 else float(vol.mean())
    vol_1y = float(vol.tail(252).mean()) if len(vol) >= 20 else float(vol.mean())
    ratio = (vol_1w / vol_1y) if vol_1y > 0 else None
    price = float(close.iloc[-1]) if len(close) else None
    return (
        round(week_ret, 2) if week_ret is not None else None,
        round(ratio, 2) if ratio is not None else None,
        price,
    )


def _needs_pe_history(mode: str, category: str) -> bool:
    if mode in ("stalwarts_discount", "buy_candidates") and category in ("Stalwart", "Cyclical", "Fast Grower"):
        return True
    if mode == "classify_all" and category in ("Stalwart", "Cyclical"):
        return True
    return mode == "stalwarts_discount"


def scan_investment_course(
    scan_source: str,
    filters: InvestmentCourseFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[InvestmentCourseResult]:
    flt = filters or InvestmentCourseFilters()
    mode = flt.mode if flt.mode in SCAN_MODES else "buy_candidates"
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[InvestmentCourseResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        if not (raw.endswith(".NS") or raw.endswith(".BO")):
            continue

        disp = raw.replace(".NS", "").replace(".BO", "")
        try:
            if mode == "volume_spike":
                week_ret, vol_ratio, price = _volume_spike_metrics(raw)
                if week_ret is None or vol_ratio is None:
                    continue
                if vol_ratio < flt.vol_mult or week_ret <= flt.min_week_return_pct:
                    continue

                profile = fetch_screener_value_profile(disp)
                mcap = profile.get("market_cap_cr")
                if mcap is not None and mcap < flt.volume_min_market_cap_cr:
                    continue
                if mcap is None:
                    # Soft allow if Screener missing mcap
                    pass

                stock = yf.Ticker(raw)
                sector, industry = get_sector_industry(stock)
                sales = profile.get("sales_growth_3y_pct")
                profit = profile.get("profit_growth_3y_pct")
                cat, rationale = classify_category(sales, profit, sector=sector or "", industry=industry or "")
                pe = profile.get("pe")
                peg = _peg(pe, profit)
                notes = [
                    f"1w ret {week_ret:.1f}%",
                    f"Vol ratio {vol_ratio:.1f}× (≥{flt.vol_mult:.0f}×)",
                    rationale,
                ]
                links = get_stock_links(raw)
                if profile.get("screener_url"):
                    links["Screener.in"] = profile["screener_url"]

                results.append(
                    InvestmentCourseResult(
                        ticker=disp,
                        raw_ticker=raw,
                        label=label if label != disp else disp,
                        category=cat,
                        sector=sector or "—",
                        price=price or profile.get("price"),
                        pe=pe,
                        fy_median_pe=None,
                        pct_vs_median=None,
                        n_fy_points=0,
                        sales_growth_3y_pct=sales,
                        profit_growth_3y_pct=profit,
                        peg=peg,
                        peg_verdict=peg_verdict(peg),
                        roce_pct=profile.get("roce_pct"),
                        market_cap_cr=mcap,
                        market_cap_display=_mcap_display(mcap),
                        week_return_pct=week_ret,
                        vol_ratio=vol_ratio,
                        score=_course_score(cat, peg, None, sales, profit) + float(vol_ratio or 0) * 2,
                        verdict=_verdict(cat, peg, None, mode),
                        pass_notes=notes,
                        links=links,
                    )
                )
                if flt.screener_delay_sec > 0:
                    time.sleep(flt.screener_delay_sec)
                continue

            # Fundamental modes
            html = fetch_screener_company_html(disp)
            if flt.screener_delay_sec > 0:
                time.sleep(flt.screener_delay_sec)
            profile = fetch_screener_value_profile(disp, html=html or "")
            if not profile:
                continue

            sales = profile.get("sales_growth_3y_pct")
            profit = profile.get("profit_growth_3y_pct")
            pe = profile.get("pe")
            mcap = profile.get("market_cap_cr")
            roce = profile.get("roce_pct")
            price = profile.get("price")

            stock = yf.Ticker(raw)
            sector, industry = get_sector_industry(stock)
            cat, rationale = classify_category(sales, profit, sector=sector or "", industry=industry or "")

            fy_med = None
            pct_vs = None
            n_fy = 0
            if flt.need_pe_history and _needs_pe_history(mode, cat):
                try:
                    _pts, meta = build_pe_history(disp, raw, html=html or "")
                    fy_med = meta.get("fy_median_pe") or meta.get("median_pe")
                    pct_vs = meta.get("pct_vs_fy_median")
                    if pct_vs is None and pe and fy_med:
                        pct_vs = round((float(pe) / float(fy_med) - 1.0) * 100.0, 1)
                    n_fy = int(meta.get("n_fy_points") or 0)
                    if pe is None:
                        pe = meta.get("current_pe")
                    if price is None:
                        price = meta.get("current_price")
                except Exception:
                    pass

            peg = _peg(pe, profit)
            notes = [rationale]
            if peg is not None:
                notes.append(f"PEG {peg:.2f}")
            if pct_vs is not None and fy_med is not None:
                notes.append(f"P/E {pe:.1f} vs FY med {fy_med:.1f} ({pct_vs:+.1f}%)")

            # Soft filters
            min_mcap = flt.min_market_cap_cr
            if mode != "classify_all" and mcap is not None and mcap < min_mcap:
                continue
            if flt.min_roce_pct > 0 and (roce is None or roce < flt.min_roce_pct):
                if mode != "classify_all":
                    continue

            # Mode gates
            keep = False
            if mode == "classify_all":
                keep = True
            elif mode == "fast_growers":
                keep = cat == "Fast Grower"
            elif mode == "stalwarts_discount":
                keep = (
                    cat == "Stalwart"
                    and pe is not None
                    and fy_med is not None
                    and n_fy >= flt.min_fy_points
                    and pct_vs is not None
                    and pct_vs <= flt.max_pct_vs_fy_median
                )
            elif mode == "buy_candidates":
                fast_ok = cat == "Fast Grower" and peg is not None and peg <= flt.max_peg
                stalwart_ok = (
                    cat == "Stalwart"
                    and pe is not None
                    and fy_med is not None
                    and n_fy >= flt.min_fy_points
                    and pct_vs is not None
                    and pct_vs <= flt.max_pct_vs_fy_median
                )
                keep = fast_ok or stalwart_ok
                if cat == "Slow Grower":
                    keep = False
            else:
                keep = False

            if not keep:
                continue

            if cat == "Fast Grower" and mode == "fast_growers" and peg is not None and peg > flt.max_peg * 2:
                # Still show fast growers in that mode; soft note only
                notes.append("PEG stretched vs course <1 rule")

            links = get_stock_links(raw)
            if profile.get("screener_url"):
                links["Screener.in"] = profile["screener_url"]

            results.append(
                InvestmentCourseResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    category=cat,
                    sector=sector or "—",
                    price=round(float(price), 2) if price else None,
                    pe=round(float(pe), 2) if pe is not None else None,
                    fy_median_pe=round(float(fy_med), 2) if fy_med is not None else None,
                    pct_vs_median=pct_vs,
                    n_fy_points=n_fy,
                    sales_growth_3y_pct=sales,
                    profit_growth_3y_pct=profit,
                    peg=peg,
                    peg_verdict=peg_verdict(peg),
                    roce_pct=roce,
                    market_cap_cr=mcap,
                    market_cap_display=_mcap_display(mcap),
                    week_return_pct=None,
                    vol_ratio=None,
                    score=_course_score(cat, peg, pct_vs, sales, profit),
                    verdict=_verdict(cat, peg, pct_vs, mode),
                    pass_notes=notes,
                    links=links,
                )
            )
        except Exception:
            continue

    return sort_investment_course(results, rank_by="score", mode=mode)


def sort_investment_course(
    results: list[InvestmentCourseResult],
    *,
    rank_by: str = "score",
    mode: str = "buy_candidates",
) -> list[InvestmentCourseResult]:
    if rank_by == "peg" or (rank_by == "score" and mode == "fast_growers"):
        return sorted(
            results,
            key=lambda r: (
                float(r.peg) if r.peg is not None else 9999.0,
                -min(float(r.sales_growth_3y_pct or 0), float(r.profit_growth_3y_pct or 0)),
            ),
        )
    if rank_by == "discount":
        return sorted(
            results,
            key=lambda r: float(r.pct_vs_median) if r.pct_vs_median is not None else 9999.0,
        )
    if rank_by == "growth":
        return sorted(
            results,
            key=lambda r: min(float(r.sales_growth_3y_pct or -999), float(r.profit_growth_3y_pct or -999)),
            reverse=True,
        )
    if rank_by == "vol_ratio" or mode == "volume_spike":
        return sorted(results, key=lambda r: float(r.vol_ratio or 0), reverse=True)
    return sorted(results, key=lambda r: float(r.score or 0), reverse=True)


def result_to_row(r: InvestmentCourseResult, rank: int) -> dict:
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Category": r.category,
        "Score": r.score,
        "Verdict": r.verdict,
        "Sales 3Y %": r.sales_growth_3y_pct,
        "Profit 3Y %": r.profit_growth_3y_pct,
        "P/E": r.pe,
        "FY median P/E": r.fy_median_pe,
        "vs median %": r.pct_vs_median,
        "PEG": r.peg,
        "PEG verdict": r.peg_verdict,
        "ROCE %": r.roce_pct,
        "1w ret %": r.week_return_pct,
        "Vol ratio": r.vol_ratio,
        "Price": r.price,
        "Mcap": r.market_cap_display,
        "Sector": r.sector,
        "Notes": " · ".join(r.pass_notes[:5]),
    }
