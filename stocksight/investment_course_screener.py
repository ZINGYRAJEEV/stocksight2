"""
Investment Course Screener — Stock Analysis Workflow (STEP 0 + Workflow A + Quick-Fire).

Aligned with docs/Stock_Analysis_Workflow_1.md / docs/stock_analysis/Stock_Analysis_Workflow_1.md.
Educational only; inspired by course notes — not affiliated with Financially Free™.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote_plus

import yfinance as yf

try:
    from .multibagger import SCAN_SOURCES, resolve_scan_tickers
    from .pe_history import build_pe_history
    from .screener import fetch_price_history, get_sector_industry, get_stock_links, hist_series
    from .screener_in_data import (
        _parse_section_table,
        fetch_screener_company_html,
        fetch_screener_value_profile,
    )
except ImportError:
    from multibagger import SCAN_SOURCES, resolve_scan_tickers
    from pe_history import build_pe_history
    from screener import fetch_price_history, get_sector_industry, get_stock_links, hist_series
    from screener_in_data import (
        _parse_section_table,
        fetch_screener_company_html,
        fetch_screener_value_profile,
    )

# Sector baskets (Nifty sectoral constituents) — scan one sector at a time.
try:
    try:
        from .intraday import NSE_INTRADAY_UNIVERSES
    except ImportError:
        from intraday import NSE_INTRADAY_UNIVERSES
except Exception:
    NSE_INTRADAY_UNIVERSES = {}

SECTOR_SCAN_SOURCES: dict[str, list[str]] = {
    k: list(v)
    for k, v in (NSE_INTRADAY_UNIVERSES or {}).items()
    if str(k).startswith("Sector ·")
}

BROAD_SCAN_SOURCES: list[str] = [
    s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s
]


def resolve_investment_course_tickers(scan_source: str) -> list[tuple[str, str]]:
    """Resolve broad NSE/curated lists or sector baskets into (label, raw) pairs."""
    if scan_source in SECTOR_SCAN_SOURCES:
        out: list[tuple[str, str]] = []
        for t in SECTOR_SCAN_SOURCES[scan_source]:
            raw = t if str(t).endswith((".NS", ".BO")) else f"{t}.NS"
            disp = raw.replace(".NS", "").replace(".BO", "")
            out.append((disp, raw))
        return out
    return resolve_scan_tickers(scan_source)


def universe_ticker_count(scan_source: str) -> int:
    return len(resolve_investment_course_tickers(scan_source))

META = {
    "id": "investment_course",
    "title": "Investment Course + Valuation",
    "emoji": "📘",
    "nav_title": "Investment Course",
    "audience": (
        "Investors following **Stock Analysis Workflow 1**: categorize → Fast Grower gates, "
        "then the **Valuation Rulebook** wealth read on the same scan."
    ),
    "purpose": (
        "STEP 0 buckets by Screener sales+profit CAGR. Workflow A confirms growth, PE vs median, PEG. "
        "Each match also runs a **default Valuation Rulebook** model (target, CAGR, Strong wealth filter). "
        "Click a result for charts, P/E history, and the full wealth panel."
    ),
}

# Modes mapped to Stock_Analysis_Workflow_1.md
SCAN_MODES: dict[str, str] = {
    "step0_categorize": "STEP 0 — Categorize the company",
    "workflow_a_fast": "WORKFLOW A — Fast Growers (growth + valuation)",
    "buy_candidates": "Buy candidates (Fast PEG≤1 or Stalwart ≤ median PE)",
    "stalwarts_discount": "WORKFLOW B — Stalwarts at/below median PE",
    "volume_spike": "Bottom-up — Volume spike (Ch.10)",
}

RANK_BY_OPTIONS: dict[str, str] = {
    "score": "Workflow score",
    "wealth": "Wealth score",
    "checklist": "Quick-Fire checklist score",
    "peg": "PEG (lowest)",
    "discount": "Discount vs FY median %",
    "growth": "Min(sales, profit) 3Y %",
    "vol_ratio": "Volume ratio (spike mode)",
    "dma50": "Most below 50-DMA",
    "dma200": "Most below 200-DMA",
}

RESEARCH_TOOLS = (
    ("Screener.in", "Financials, PE chart, shareholding, concalls, credit ratings"),
    ("Trendlyne", "Broker reports + concall YouTube"),
    ("Tijori Finance", "Investor press releases"),
    ("Value Pickr", "Open investor forum"),
    ("Glassdoor", "Culture rating (target 3.0+)"),
    ("Google / YouTube", "Promoter scam check + interviews"),
)

CYCLICAL_KEYWORDS = (
    "cement", "paper", "steel", "iron", "cotton", "textile", "agri", "agriculture",
    "sugar", "cable", "wire", "mdf", "wood", "plywood", "chemical", "commodity",
    "metal", "mining", "aluminium", "aluminum", "copper", "shipping", "construction",
    "building",
)

INDIA_GDP_PROXY_PCT = 7.0
FAST_GROWTH_PCT = 15.0
STALWART_MIN_PCT = 10.0


@dataclass
class InvestmentCourseFilters:
    mode: str = "step0_categorize"
    max_peg: float = 1.0
    max_pct_vs_fy_median: float = 0.0
    min_fy_points: int = 3
    min_market_cap_cr: float = 500.0
    volume_min_market_cap_cr: float = 50.0
    max_debt_equity: float = 2.0
    min_roce_pct: float = 0.0
    vol_mult: float = 5.0
    min_week_return_pct: float = 5.0
    require_quickfire_pass: bool = False  # Workflow A: optional hard gate
    min_checklist_score: int = 0
    include_wealth: bool = True  # Valuation Rulebook snapshot per match
    strong_wealth_only: bool = False  # keep only "Strong wealth candidate"
    require_growth_cagr: bool = True  # drop if sales or profit 3Y CAGR missing
    drop_unclassified: bool = True  # drop Unclassified / thin-data names
    skip_wealth_without_growth: bool = True  # avoid false Strong wealth on empty CAGR
    require_below_50dma: bool = False
    require_below_200dma: bool = False
    max_pct_vs_50dma: float = 0.0  # keep if % vs 50-DMA <= this (0 = at/below)
    max_pct_vs_200dma: float = 0.0
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
    sales_growth_ttm_pct: Optional[float]
    profit_growth_ttm_pct: Optional[float]
    peg: Optional[float]
    peg_verdict: str
    roce_pct: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    # Quick-Fire Numbers Checklist
    opm_latest_pct: Optional[float]
    opm_delta_pp: Optional[float]
    interest_latest: Optional[float]
    interest_delta: Optional[float]
    interest_reducing: Optional[bool]
    tax_latest: Optional[float]
    tax_falling: Optional[bool]
    net_profit_yoy_pct: Optional[float]
    checklist_score: int
    checklist_max: int
    checklist_flags: list[str] = field(default_factory=list)
    week_return_pct: Optional[float] = None
    vol_ratio: Optional[float] = None
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    pct_vs_50dma: Optional[float] = None
    pct_vs_200dma: Optional[float] = None
    score: float = 0.0
    verdict: str = ""
    next_steps: str = ""
    pass_notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)
    # Valuation Rulebook snapshot
    wealth_verdict: str = ""
    wealth_emoji: str = ""
    wealth_score: Optional[int] = None
    wealth_stance: str = ""
    model_target: Optional[float] = None
    upside_pct: Optional[float] = None
    implied_cagr_pct: Optional[float] = None
    max_buy_15pct: Optional[float] = None
    is_strong_wealth: bool = False
    wealth_detail: str = ""
    wealth_strengths: list[str] = field(default_factory=list)
    wealth_risks: list[str] = field(default_factory=list)
    wealth_suggestions: list[str] = field(default_factory=list)


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
    """STEP 0 — Categorize from Screener compounded sales + profit growth."""
    s = float(sales_3y) if sales_3y is not None else None
    p = float(profit_3y) if profit_3y is not None else None

    if s is not None and p is not None:
        if s >= FAST_GROWTH_PCT and p >= FAST_GROWTH_PCT:
            return "Fast Grower", f"STEP 0: Sales {s:.1f}% & profit {p:.1f}% >= 15%"
        if STALWART_MIN_PCT <= s < FAST_GROWTH_PCT and STALWART_MIN_PCT <= p < FAST_GROWTH_PCT:
            return "Stalwart", f"STEP 0: Sales {s:.1f}% & profit {p:.1f}% in 10-15%"
        if s < INDIA_GDP_PROXY_PCT and p < INDIA_GDP_PROXY_PCT:
            return "Slow Grower", f"STEP 0: Both < ~{INDIA_GDP_PROXY_PCT:.0f}% GDP - prefer FD"

    if _is_cyclical(sector, industry):
        return "Cyclical", f"STEP 0: Cyclical sector keywords ({sector or '-'})"

    if s is None or p is None:
        return "Unclassified", "STEP 0: Missing sales or profit 3Y CAGR"
    return "Other", f"STEP 0: Sales {s:.1f}% / profit {p:.1f}% - check Turnaround manually"


def has_growth_cagr(sales_3y: Optional[float], profit_3y: Optional[float]) -> bool:
    return sales_3y is not None and profit_3y is not None


def passes_data_quality_gates(
    *,
    category: str,
    sales_3y: Optional[float],
    profit_3y: Optional[float],
    flt: InvestmentCourseFilters,
) -> bool:
    """
    Drop thin-data / Unclassified names that produce misleading wealth reads
    (e.g. PSB in PSU Bank with missing Screener CAGRs).
    """
    if flt.require_growth_cagr and not has_growth_cagr(sales_3y, profit_3y):
        return False
    if flt.drop_unclassified and category in ("Unclassified", "Other", ""):
        return False
    return True


def _row_vals(data: dict, *needles: str) -> list[Optional[float]]:
    for key, vals in data.items():
        if any(n in key for n in needles):
            return vals
    return []


def _last_two(vals: list[Optional[float]]) -> tuple[Optional[float], Optional[float]]:
    clean = [float(v) for v in vals if v is not None]
    if len(clean) < 2:
        if len(clean) == 1:
            return clean[0], None
        return None, None
    return clean[-1], clean[-2]


def parse_quickfire_from_html(html: str) -> dict:
    """
    SHARED STEP — Quick-Fire Numbers Checklist (quantifiable fields from Screener P&L).
    """
    out: dict = {
        "opm_latest_pct": None,
        "opm_delta_pp": None,
        "interest_latest": None,
        "interest_delta": None,
        "interest_reducing": None,
        "tax_latest": None,
        "tax_falling": None,
        "net_profit_yoy_pct": None,
    }
    if not html:
        return out

    _headers, data = _parse_section_table(html, "profit-loss")
    if not data:
        return out

    opm_vals = _row_vals(data, "opm")
    opm_now, opm_prev = _last_two(opm_vals)
    if opm_now is not None:
        out["opm_latest_pct"] = round(opm_now, 1)
    if opm_now is not None and opm_prev is not None:
        out["opm_delta_pp"] = round(opm_now - opm_prev, 1)

    int_vals = _row_vals(data, "interest")
    # Prefer financing interest row, avoid "interest coverage" if present as separate
    int_now, int_prev = _last_two(int_vals)
    if int_now is not None:
        out["interest_latest"] = round(int_now, 2)
    if int_now is not None and int_prev is not None:
        out["interest_delta"] = round(int_now - int_prev, 2)
        out["interest_reducing"] = int_now < int_prev

    tax_vals = _row_vals(data, "tax %", "tax%")
    if not tax_vals:
        tax_vals = _row_vals(data, "tax")
    tax_now, tax_prev = _last_two(tax_vals)
    if tax_now is not None:
        out["tax_latest"] = round(tax_now, 1)
    if tax_now is not None and tax_prev is not None and tax_prev > 0:
        # Falling tax YoY can be a caution flag (workflow)
        out["tax_falling"] = tax_now < tax_prev - 1.0

    np_vals = _row_vals(data, "net profit", "profit after tax", "pat")
    np_now, np_prev = _last_two(np_vals)
    if np_now is not None and np_prev is not None and abs(np_prev) > 1e-6:
        out["net_profit_yoy_pct"] = round((np_now / np_prev - 1.0) * 100.0, 1)

    return out


def score_quickfire_checklist(
    *,
    sales_3y: Optional[float],
    profit_3y: Optional[float],
    sales_ttm: Optional[float],
    profit_ttm: Optional[float],
    qf: dict,
    category: str,
) -> tuple[int, int, list[str]]:
    """Return (score, max_score, flag strings) for Quick-Fire checklist."""
    flags: list[str] = []
    score = 0
    max_score = 7

    # 1 Sales growth trend & compounded
    if sales_3y is not None and sales_3y >= (FAST_GROWTH_PCT if category == "Fast Grower" else STALWART_MIN_PCT):
        score += 1
        flags.append(f"Sales 3Y OK ({sales_3y:.1f}%)")
    elif sales_3y is not None:
        flags.append(f"Sales 3Y weak ({sales_3y:.1f}%)")
    else:
        flags.append("Sales 3Y missing")

    # 2 Profit growth trend & compounded
    if profit_3y is not None and profit_3y >= (FAST_GROWTH_PCT if category == "Fast Grower" else STALWART_MIN_PCT):
        score += 1
        flags.append(f"Profit 3Y OK ({profit_3y:.1f}%)")
    elif profit_3y is not None:
        flags.append(f"Profit 3Y weak ({profit_3y:.1f}%)")
    else:
        flags.append("Profit 3Y missing")

    # 3-4 Margin / OPM stable or improving
    opm_d = qf.get("opm_delta_pp")
    if opm_d is not None and opm_d >= -1.0:
        score += 1
        flags.append(f"OPM stable/up ({opm_d:+.1f} pp)")
    elif opm_d is not None:
        flags.append(f"OPM falling ({opm_d:+.1f} pp)")
    else:
        flags.append("OPM trend n/a")

    # 5 Interest reducing YoY
    if qf.get("interest_reducing") is True:
        score += 1
        flags.append("Interest reducing YoY")
    elif qf.get("interest_reducing") is False:
        flags.append("Interest not reducing")
    else:
        flags.append("Interest n/a")

    # 6 Tax falling = caution (do not award point; note it)
    if qf.get("tax_falling"):
        flags.append("CAUTION: tax % falling YoY")
    else:
        score += 1
        flags.append("Tax % not a red flag")

    # 7 Net profit growth
    np_yoy = qf.get("net_profit_yoy_pct")
    if np_yoy is not None and np_yoy > 0:
        score += 1
        flags.append(f"Net profit YoY +{np_yoy:.1f}%")
    elif np_yoy is not None:
        flags.append(f"Net profit YoY {np_yoy:.1f}%")
    elif profit_ttm is not None and profit_ttm > 0:
        score += 1
        flags.append(f"Profit TTM +{profit_ttm:.1f}%")
    else:
        flags.append("Net profit YoY n/a")

    # Bonus consistency: TTM still growing for Fast Growers
    if category == "Fast Grower":
        max_score += 1
        if (sales_ttm is None or sales_ttm >= 0) and (profit_ttm is None or profit_ttm >= 0):
            if sales_ttm is not None or profit_ttm is not None:
                score += 1
                flags.append("TTM growth not collapsing")
            else:
                flags.append("TTM n/a")
        else:
            flags.append("TTM growth soft")

    return score, max_score, flags


def research_links(disp: str, raw: str, company_name: str = "") -> dict:
    """Key websites from Stock_Analysis_Workflow_1.md."""
    links = get_stock_links(raw)
    slug = disp.strip().upper()
    q = quote_plus(company_name or slug)
    links["Screener.in"] = f"https://www.screener.in/company/{slug}/consolidated/"
    links["Screener Concalls"] = f"https://www.screener.in/company/{slug}/consolidated/#documents"
    links["Trendlyne"] = f"https://trendlyne.com/search/?q={q}"
    links["Tijori Finance"] = f"https://www.tijorifinance.com/search/?q={q}"
    links["Value Pickr"] = f"https://forum.valuepickr.com/search?q={q}"
    links["Glassdoor"] = f"https://www.glassdoor.com/Search/results.htm?keyword={q}"
    links["Google scam check"] = f"https://www.google.com/search?q={q}+scam+OR+fraud+OR+SEBI"
    links["YouTube interviews"] = (
        f"https://www.youtube.com/results?search_query={q}+CEO+OR+MD+interview"
    )
    return links


def _course_score(
    category: str,
    peg: Optional[float],
    pct_vs: Optional[float],
    sales: Optional[float],
    profit: Optional[float],
    checklist_score: int = 0,
    checklist_max: int = 7,
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
    if checklist_max > 0:
        pts += (checklist_score / checklist_max) * 12.0
    return round(pts, 1)


def _verdict(
    category: str,
    peg: Optional[float],
    pct_vs: Optional[float],
    mode: str,
    checklist_score: int,
    checklist_max: int,
) -> str:
    if category == "Slow Grower":
        return "Avoid - slow grower (FD better)"
    if mode == "volume_spike":
        return "Volume spike - research story"
    qf = f"QF {checklist_score}/{checklist_max}"
    if category == "Fast Grower":
        if peg is not None and peg < 1.0 and (pct_vs is None or pct_vs <= 5):
            return f"Workflow A: Fast Grower + cheap PEG ({qf})"
        if peg is not None and peg < 1.0:
            return f"Workflow A: Fast Grower PEG OK - check PE chart ({qf})"
        if pct_vs is not None and pct_vs <= 0:
            return f"Workflow A: Fast Grower below median PE ({qf})"
        return f"Workflow A: confirm growth drivers + valuation ({qf})"
    if category == "Stalwart":
        if pct_vs is not None and pct_vs <= 0:
            return f"Stalwart at/below median PE ({qf})"
        return f"Stalwart - wait for lower PE ({qf})"
    if category == "Cyclical":
        return f"Cyclical - track OPM trail ({qf})"
    return f"STEP 0: {category} - build story ({qf})"


def _next_steps(category: str) -> str:
    if category == "Fast Grower":
        return (
            "1) Confirm CAGR on Screener P&L  2) Growth drivers in AR/presentations  "
            "3) Future growth via concalls  4) PE vs median + PEG  5) Story: mgmt/Glassdoor"
        )
    if category == "Stalwart":
        return "Check margin stability (OPM) + PE ≤ historical mean; trim after 30-40% gain"
    if category == "Cyclical":
        return "OPM rising with room to run; shareholding for promoter buying; capacity in presentations"
    if category == "Slow Grower":
        return "Usually pass unless deep value + strong dividend; diagnose why slow"
    if category == "Turnaround":
        return "Mgmt change, debt reduction, shareholding - manual only"
    return "Re-check STEP 0 category; then open matching workflow"


def _empty_dma_fields() -> dict:
    return {
        "ma50": None,
        "ma200": None,
        "pct_vs_50dma": None,
        "pct_vs_200dma": None,
    }


def _volume_spike_metrics(raw: str) -> dict:
    """1w return, volume ratio, price, and 50/200-DMA from one daily history pull."""
    empty = {
        "week_return_pct": None,
        "vol_ratio": None,
        "price": None,
        **_empty_dma_fields(),
    }
    try:
        hist = fetch_price_history(raw, "1d")
    except Exception:
        return empty
    if hist is None or hist.empty or len(hist) < 30:
        return empty

    close = hist_series(hist, "Close")
    vol = hist_series(hist, "Volume")
    if close is None or close.empty or vol is None or vol.empty:
        return empty

    close_f = close.dropna().astype(float)
    if close_f.empty:
        return empty

    n = min(5, len(close_f) - 1)
    week_ret = None
    if n >= 1:
        try:
            week_ret = (float(close_f.iloc[-1]) / float(close_f.iloc[-1 - n]) - 1.0) * 100.0
        except Exception:
            week_ret = None

    vol_1w = float(vol.tail(5).mean()) if len(vol) >= 5 else float(vol.mean())
    vol_1y = float(vol.tail(252).mean()) if len(vol) >= 20 else float(vol.mean())
    ratio = (vol_1w / vol_1y) if vol_1y > 0 else None
    price = float(close_f.iloc[-1])

    out = {
        "week_return_pct": round(week_ret, 2) if week_ret is not None else None,
        "vol_ratio": round(ratio, 2) if ratio is not None else None,
        "price": round(price, 2),
        **_empty_dma_fields(),
    }
    if len(close_f) >= 50:
        ma50 = float(close_f.rolling(50).mean().iloc[-1])
        if ma50 > 0:
            out["ma50"] = round(ma50, 2)
            out["pct_vs_50dma"] = round((price / ma50 - 1.0) * 100.0, 2)
    if len(close_f) >= 200:
        ma200 = float(close_f.rolling(200).mean().iloc[-1])
        if ma200 > 0:
            out["ma200"] = round(ma200, 2)
            out["pct_vs_200dma"] = round((price / ma200 - 1.0) * 100.0, 2)
    return out


def _dma_metrics(raw: str) -> dict:
    """Price vs 50-DMA / 200-DMA from daily Yahoo history."""
    out = _empty_dma_fields()
    try:
        hist = fetch_price_history(raw, "1d")
    except Exception:
        return out
    if hist is None or hist.empty:
        return out
    close = hist_series(hist, "Close")
    if close is None or close.empty:
        return out
    close = close.dropna().astype(float)
    if close.empty:
        return out
    price = float(close.iloc[-1])
    out["price"] = round(price, 2)
    if len(close) >= 50:
        ma50 = float(close.rolling(50).mean().iloc[-1])
        if ma50 > 0:
            out["ma50"] = round(ma50, 2)
            out["pct_vs_50dma"] = round((price / ma50 - 1.0) * 100.0, 2)
    if len(close) >= 200:
        ma200 = float(close.rolling(200).mean().iloc[-1])
        if ma200 > 0:
            out["ma200"] = round(ma200, 2)
            out["pct_vs_200dma"] = round((price / ma200 - 1.0) * 100.0, 2)
    return out


def _need_dma(flt: InvestmentCourseFilters) -> bool:
    return bool(flt.require_below_50dma or flt.require_below_200dma)


def _passes_dma_filter(dma: dict, flt: InvestmentCourseFilters) -> bool:
    if flt.require_below_50dma:
        pct = dma.get("pct_vs_50dma")
        if pct is None or float(pct) > float(flt.max_pct_vs_50dma):
            return False
    if flt.require_below_200dma:
        pct = dma.get("pct_vs_200dma")
        if pct is None or float(pct) > float(flt.max_pct_vs_200dma):
            return False
    return True


def _attach_dma(raw: str, flt: InvestmentCourseFilters, precomputed: dict | None = None) -> dict:
    """Attach 50/200-DMA levels; hard-gate only when require_below_* is on."""
    dma = precomputed if precomputed is not None else _dma_metrics(raw)
    return {
        "ma50": dma.get("ma50"),
        "ma200": dma.get("ma200"),
        "pct_vs_50dma": dma.get("pct_vs_50dma"),
        "pct_vs_200dma": dma.get("pct_vs_200dma"),
        "_dma_ok": _passes_dma_filter(dma, flt) if _need_dma(flt) else True,
        "_dma_price": dma.get("price"),
    }


def _needs_pe_history(mode: str, category: str) -> bool:
    if mode in ("workflow_a_fast", "buy_candidates", "stalwarts_discount"):
        return True
    if mode == "step0_categorize" and category in ("Fast Grower", "Stalwart", "Cyclical"):
        return True
    return False


def _empty_qf_fields() -> dict:
    return {
        "opm_latest_pct": None,
        "opm_delta_pp": None,
        "interest_latest": None,
        "interest_delta": None,
        "interest_reducing": None,
        "tax_latest": None,
        "tax_falling": None,
        "net_profit_yoy_pct": None,
        "checklist_score": 0,
        "checklist_max": 7,
        "checklist_flags": [],
    }


def _empty_wealth_fields() -> dict:
    return {
        "wealth_verdict": "",
        "wealth_emoji": "",
        "wealth_score": None,
        "wealth_stance": "",
        "model_target": None,
        "upside_pct": None,
        "implied_cagr_pct": None,
        "max_buy_15pct": None,
        "is_strong_wealth": False,
        "wealth_detail": "",
        "wealth_strengths": [],
        "wealth_risks": [],
        "wealth_suggestions": [],
    }


def _attach_wealth(raw: str, include: bool) -> dict:
    if not include:
        return _empty_wealth_fields()
    try:
        from valuation_model import quick_wealth_snapshot

        snap = quick_wealth_snapshot(raw) or {}
        if not snap:
            return _empty_wealth_fields()
        return {
            "wealth_verdict": snap.get("wealth_verdict") or "",
            "wealth_emoji": snap.get("wealth_emoji") or "",
            "wealth_score": snap.get("wealth_score"),
            "wealth_stance": snap.get("wealth_stance") or "",
            "model_target": snap.get("model_target"),
            "upside_pct": snap.get("upside_pct"),
            "implied_cagr_pct": snap.get("implied_cagr_pct"),
            "max_buy_15pct": snap.get("max_buy_15pct"),
            "is_strong_wealth": bool(snap.get("is_strong_wealth")),
            "wealth_detail": snap.get("wealth_detail") or "",
            "wealth_strengths": list(snap.get("strengths") or []),
            "wealth_risks": list(snap.get("risks") or []),
            "wealth_suggestions": list(snap.get("suggestions") or []),
        }
    except Exception:
        return _empty_wealth_fields()



def scan_investment_course(
    scan_source: str,
    filters: InvestmentCourseFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[InvestmentCourseResult]:
    flt = filters or InvestmentCourseFilters()
    mode = flt.mode if flt.mode in SCAN_MODES else "step0_categorize"
    universe = resolve_investment_course_tickers(scan_source)
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
                tech = _volume_spike_metrics(raw)
                week_ret = tech.get("week_return_pct")
                vol_ratio = tech.get("vol_ratio")
                price = tech.get("price")
                if week_ret is None or vol_ratio is None:
                    continue
                if vol_ratio < flt.vol_mult or week_ret <= flt.min_week_return_pct:
                    continue

                profile = fetch_screener_value_profile(disp)
                mcap = profile.get("market_cap_cr")
                if mcap is not None and mcap < flt.volume_min_market_cap_cr:
                    continue

                stock = yf.Ticker(raw)
                sector, industry = get_sector_industry(stock)
                sales = profile.get("sales_growth_3y_pct")
                profit = profile.get("profit_growth_3y_pct")
                cat, rationale = classify_category(sales, profit, sector=sector or "", industry=industry or "")
                pe = profile.get("pe")
                peg = _peg(pe, profit)
                qf_fields = _empty_qf_fields()
                notes = [
                    f"1w ret {week_ret:.1f}%",
                    f"Vol ratio {vol_ratio:.1f}x (>={flt.vol_mult:.0f}x)",
                    rationale,
                ]
                links = research_links(disp, raw, label)
                run_wealth = bool(flt.include_wealth)
                if flt.skip_wealth_without_growth and not has_growth_cagr(sales, profit):
                    run_wealth = False
                wealth = _attach_wealth(raw, run_wealth)
                if flt.strong_wealth_only and not wealth.get("is_strong_wealth"):
                    continue
                dma_pack = _attach_dma(raw, flt, precomputed=tech)
                if dma_pack.pop("_dma_ok", True) is False:
                    continue
                dma_price = dma_pack.pop("_dma_price", None)
                if price is None and dma_price is not None:
                    price = dma_price
                if dma_pack.get("pct_vs_50dma") is not None:
                    notes.append(f"vs 50-DMA {dma_pack['pct_vs_50dma']:+.1f}%")
                if dma_pack.get("pct_vs_200dma") is not None:
                    notes.append(f"vs 200-DMA {dma_pack['pct_vs_200dma']:+.1f}%")

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
                        sales_growth_ttm_pct=profile.get("sales_growth_ttm_pct"),
                        profit_growth_ttm_pct=profile.get("profit_growth_ttm_pct"),
                        peg=peg,
                        peg_verdict=peg_verdict(peg),
                        roce_pct=profile.get("roce_pct"),
                        market_cap_cr=mcap,
                        market_cap_display=_mcap_display(mcap),
                        week_return_pct=week_ret,
                        vol_ratio=vol_ratio,
                        score=_course_score(cat, peg, None, sales, profit) + float(vol_ratio or 0) * 2,
                        verdict=_verdict(cat, peg, None, mode, 0, 7),
                        next_steps=_next_steps(cat),
                        pass_notes=notes,
                        links=links,
                        **qf_fields,
                        **wealth,
                        **dma_pack,
                    )
                )
                if flt.screener_delay_sec > 0:
                    time.sleep(flt.screener_delay_sec)
                continue

            html = fetch_screener_company_html(disp)
            if flt.screener_delay_sec > 0:
                time.sleep(flt.screener_delay_sec)
            profile = fetch_screener_value_profile(disp, html=html or "")
            if not profile:
                continue

            sales = profile.get("sales_growth_3y_pct")
            profit = profile.get("profit_growth_3y_pct")
            sales_ttm = profile.get("sales_growth_ttm_pct")
            profit_ttm = profile.get("profit_growth_ttm_pct")
            pe = profile.get("pe")
            mcap = profile.get("market_cap_cr")
            roce = profile.get("roce_pct")
            price = profile.get("price")

            stock = yf.Ticker(raw)
            sector, industry = get_sector_industry(stock)
            cat, rationale = classify_category(sales, profit, sector=sector or "", industry=industry or "")

            qf = parse_quickfire_from_html(html or "")
            ck_score, ck_max, ck_flags = score_quickfire_checklist(
                sales_3y=sales,
                profit_3y=profit,
                sales_ttm=sales_ttm,
                profit_ttm=profit_ttm,
                qf=qf,
                category=cat,
            )

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
            if pct_vs is not None and fy_med is not None and pe is not None:
                notes.append(f"P/E {pe:.1f} vs FY med {fy_med:.1f} ({pct_vs:+.1f}%)")
            notes.append(f"Quick-Fire {ck_score}/{ck_max}")

            if mode != "step0_categorize" and mcap is not None and mcap < flt.min_market_cap_cr:
                continue
            if flt.min_roce_pct > 0 and (roce is None or roce < flt.min_roce_pct):
                if mode != "step0_categorize":
                    continue

            keep = False
            if mode == "step0_categorize":
                keep = passes_data_quality_gates(
                    category=cat,
                    sales_3y=sales,
                    profit_3y=profit,
                    flt=flt,
                )
            elif mode == "workflow_a_fast":
                # Workflow A: confirm Fast Grower; valuation via PEG and/or PE vs median
                if cat != "Fast Grower":
                    keep = False
                else:
                    val_ok = (peg is not None and peg <= flt.max_peg) or (
                        pct_vs is not None
                        and fy_med is not None
                        and n_fy >= flt.min_fy_points
                        and pct_vs <= flt.max_pct_vs_fy_median + 5.0  # soft room
                    )
                    # Still list Fast Growers even if valuation stretched (so user can research)
                    keep = True
                    if not val_ok:
                        notes.append("Valuation stretched - check PE chart / PEG")
                    if flt.require_quickfire_pass and ck_score < max(flt.min_checklist_score, ck_max - 2):
                        keep = False
                    if flt.min_checklist_score > 0 and ck_score < flt.min_checklist_score:
                        keep = False
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
                keep = (fast_ok or stalwart_ok) and cat != "Slow Grower"
            else:
                keep = False

            if not keep:
                continue

            # Also enforce data-quality gates on non-STEP0 modes (skip misleading empties)
            if mode != "step0_categorize" and not passes_data_quality_gates(
                category=cat, sales_3y=sales, profit_3y=profit, flt=flt
            ):
                continue

            links = research_links(disp, raw, label)
            run_wealth = bool(flt.include_wealth)
            if flt.skip_wealth_without_growth and not has_growth_cagr(sales, profit):
                run_wealth = False
            wealth = _attach_wealth(raw, run_wealth)
            if flt.strong_wealth_only and not wealth.get("is_strong_wealth"):
                continue
            dma_pack = _attach_dma(raw, flt)
            if dma_pack.pop("_dma_ok", True) is False:
                continue
            dma_price = dma_pack.pop("_dma_price", None)
            if price is None and dma_price is not None:
                price = dma_price
            if dma_pack.get("pct_vs_50dma") is not None:
                notes.append(f"vs 50-DMA {dma_pack['pct_vs_50dma']:+.1f}%")
            if dma_pack.get("pct_vs_200dma") is not None:
                notes.append(f"vs 200-DMA {dma_pack['pct_vs_200dma']:+.1f}%")

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
                    sales_growth_ttm_pct=sales_ttm,
                    profit_growth_ttm_pct=profit_ttm,
                    peg=peg,
                    peg_verdict=peg_verdict(peg),
                    roce_pct=roce,
                    market_cap_cr=mcap,
                    market_cap_display=_mcap_display(mcap),
                    opm_latest_pct=qf.get("opm_latest_pct"),
                    opm_delta_pp=qf.get("opm_delta_pp"),
                    interest_latest=qf.get("interest_latest"),
                    interest_delta=qf.get("interest_delta"),
                    interest_reducing=qf.get("interest_reducing"),
                    tax_latest=qf.get("tax_latest"),
                    tax_falling=qf.get("tax_falling"),
                    net_profit_yoy_pct=qf.get("net_profit_yoy_pct"),
                    checklist_score=ck_score,
                    checklist_max=ck_max,
                    checklist_flags=ck_flags,
                    week_return_pct=None,
                    vol_ratio=None,
                    score=_course_score(cat, peg, pct_vs, sales, profit, ck_score, ck_max),
                    verdict=_verdict(cat, peg, pct_vs, mode, ck_score, ck_max),
                    next_steps=_next_steps(cat),
                    pass_notes=notes,
                    links=links,
                    **wealth,
                    **dma_pack,
                )
            )
        except Exception:
            continue

    return sort_investment_course(results, rank_by="score", mode=mode)


def sort_investment_course(
    results: list[InvestmentCourseResult],
    *,
    rank_by: str = "score",
    mode: str = "step0_categorize",
) -> list[InvestmentCourseResult]:
    if rank_by == "wealth":
        return sorted(
            results,
            key=lambda r: (
                int(r.wealth_score or -1),
                1 if r.is_strong_wealth else 0,
                float(r.score or 0),
            ),
            reverse=True,
        )
    if rank_by == "checklist":
        return sorted(
            results,
            key=lambda r: (int(r.checklist_score or 0), float(r.score or 0)),
            reverse=True,
        )
    if rank_by == "peg" or (rank_by == "score" and mode == "workflow_a_fast"):
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
    if rank_by == "dma50":
        return sorted(
            results,
            key=lambda r: float(r.pct_vs_50dma) if r.pct_vs_50dma is not None else 9999.0,
        )
    if rank_by == "dma200":
        return sorted(
            results,
            key=lambda r: float(r.pct_vs_200dma) if r.pct_vs_200dma is not None else 9999.0,
        )
    return sorted(results, key=lambda r: float(r.score or 0), reverse=True)


def group_results_by_sector(
    results: list[InvestmentCourseResult],
    *,
    rank_by: str = "score",
    mode: str = "step0_categorize",
) -> dict[str, list[InvestmentCourseResult]]:
    """Group scan hits by Yahoo sector (largest groups first)."""
    grouped: dict[str, list[InvestmentCourseResult]] = {}
    for r in results:
        sec = (r.sector or "").strip() or "—"
        grouped.setdefault(sec, []).append(r)
    for sec in list(grouped.keys()):
        grouped[sec] = sort_investment_course(grouped[sec], rank_by=rank_by, mode=mode)
    return dict(sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())))


def result_to_row(r: InvestmentCourseResult, rank: int) -> dict:
    interest_flag = "—"
    if r.interest_reducing is True:
        interest_flag = "Yes"
    elif r.interest_reducing is False:
        interest_flag = "No"

    wealth_label = r.wealth_verdict or "—"
    if r.wealth_emoji and r.wealth_verdict:
        wealth_label = f"{r.wealth_emoji} {r.wealth_verdict}"

    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Category": r.category,
        "Score": r.score,
        "Wealth": wealth_label,
        "Wealth score": r.wealth_score,
        "Strong wealth": "Yes" if r.is_strong_wealth else "—",
        "Model target ₹": r.model_target,
        "Upside %": r.upside_pct,
        "Implied CAGR %": r.implied_cagr_pct,
        "Max buy @15%": r.max_buy_15pct,
        "Stance": r.wealth_stance or "—",
        "Verdict": r.verdict,
        "QF score": f"{r.checklist_score}/{r.checklist_max}",
        "Sales 3Y %": r.sales_growth_3y_pct,
        "Profit 3Y %": r.profit_growth_3y_pct,
        "Sales TTM %": r.sales_growth_ttm_pct,
        "Profit TTM %": r.profit_growth_ttm_pct,
        "P/E": r.pe,
        "FY median P/E": r.fy_median_pe,
        "vs median %": r.pct_vs_median,
        "PEG": r.peg,
        "PEG verdict": r.peg_verdict,
        "OPM %": r.opm_latest_pct,
        "OPM Δ pp": r.opm_delta_pp,
        "Interest ↓": interest_flag,
        "Tax caution": "Yes" if r.tax_falling else ("No" if r.tax_falling is False else "—"),
        "Net profit YoY %": r.net_profit_yoy_pct,
        "ROCE %": r.roce_pct,
        "1w ret %": r.week_return_pct,
        "Vol ratio": r.vol_ratio,
        "50-DMA": r.ma50,
        "vs 50-DMA %": r.pct_vs_50dma,
        "200-DMA": r.ma200,
        "vs 200-DMA %": r.pct_vs_200dma,
        "Price": r.price,
        "Mcap": r.market_cap_display,
        "Sector": r.sector,
        "Next steps": r.next_steps,
        "Notes": " · ".join(r.pass_notes[:5]),
        "QF flags": " · ".join(r.checklist_flags[:6]),
    }
