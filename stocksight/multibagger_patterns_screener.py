"""
Multi-Bagger Patterns screener — Screener.in primary, Yahoo Finance secondary.

Implements the playbook: hyper revenue/profit acceleration, operating leverage,
cash-flow validation (anti channel-dumping), margin expansion, asset-light proxies,
and sector tailwind / ancillary tagging. Educational only.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from .multibagger import (
        INR_PER_CRORE,
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        is_nse_source,
        resolve_scan_tickers,
    )
    from .screener import drawdown_pct_from_52w_high, get_pe, get_sector_industry, get_stock_links
    from .valuation_model import _parse_mar_fy_year, _parse_screener_number
except ImportError:
    from multibagger import (
        INR_PER_CRORE,
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        is_nse_source,
        resolve_scan_tickers,
    )
    from screener import drawdown_pct_from_52w_high, get_pe, get_sector_industry, get_stock_links
    from valuation_model import _parse_mar_fy_year, _parse_screener_number

META = {
    "id": "multibagger_patterns",
    "title": "Multi-Bagger Patterns (Screener + Yahoo)",
    "emoji": "🚀",
    "nav_title": "Multi-Bagger Patterns",
    "audience": (
        "Hunt **undiscovered mid/small-caps** with NPST-style acceleration — "
        "**Screener.in** annual P&L & cash flow first, **Yahoo** for price/PE/sector."
    ),
    "purpose": (
        "Scores **revenue & profit explosions**, **profit > sales growth** (operating leverage), "
        "**CFO vs PAT** (channel-dumping filter), **OPM expansion**, and **asset-light** proxies. "
        "Tags sector tailwinds & ancillary plays — **Buy and Track**, not buy-and-forget."
    ),
}

TAILWIND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Fintech / UPI": ("fintech", "payment", "upi", "wallet", "api", "switch", "npci"),
    "Defense / IDDM": ("defence", "defense", "drone", "simulator", "ammunition", "aerospace"),
    "Railways ancillary": ("railway", "rail", "wagon", "spring", "coach", "locomotive"),
    "Smart meter / power": ("meter", "smart grid", "electrical", "switchgear", "transmission"),
    "Spirits / premiumisation": ("distill", "spirit", "liquor", "whisky", "brewery", "alcohol"),
    "Contract manufacturing": ("contract", "electronic", "oem", "ems", "manufacturing"),
    "AMC / asset-light": ("asset management", "amc", "wealth", "mutual fund"),
    "IT / software": ("software", "it services", "saas", "technology", "digital"),
}

ANCILLARY_KEYWORDS = (
    "ancillar", "component", "spring", "switchgear", "plastic", "packaging",
    "forging", "casting", "electrode", "connector", "harness", "precision",
)

RANK_OPTIONS: dict[str, str] = {
    "mb_score": "Multi-bagger score",
    "profit_yoy": "Latest profit YoY %",
    "sales_yoy": "Latest sales YoY %",
    "cfo_ratio": "CFO / PAT ratio",
    "opm_delta": "OPM expansion (pp)",
}


@dataclass
class MultibaggerPatternFilters:
    min_sales_yoy_pct: float = 40.0
    min_profit_yoy_pct: float = 80.0
    require_profit_beats_sales: bool = True
    min_cfo_to_pat: float = 0.65
    require_cash_backed: bool = True
    min_opm_expansion_pp: float = 0.0
    max_market_cap_cr: float = 25_000.0
    min_market_cap_cr: float = 200.0
    min_roce_pct: float = 12.0
    max_pe: float = 80.0
    prefer_asset_light: bool = False
    tailwind_only: bool = False
    ancillary_only: bool = False
    screener_delay_sec: float = 0.22


@dataclass
class ScreenerAnnualSeries:
    sales: list[tuple[int, float]] = field(default_factory=list)
    net_profit: list[tuple[int, float]] = field(default_factory=list)
    opm_pct: dict[int, float] = field(default_factory=dict)
    cfo: list[tuple[int, float]] = field(default_factory=list)
    source: str = ""


@dataclass
class MultibaggerPatternResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    industry: str
    price: float
    pe: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    sales_yoy_pct: Optional[float]
    profit_yoy_pct: Optional[float]
    sales_cagr_3y_pct: Optional[float]
    profit_cagr_3y_pct: Optional[float]
    opm_latest_pct: Optional[float]
    opm_delta_3y_pp: Optional[float]
    cfo_to_pat: Optional[float]
    roce_pct: Optional[float]
    drawdown_52w_pct: Optional[float]
    return_1y_pct: Optional[float]
    mb_score: float
    patterns: str
    tailwinds: str
    verdict: str
    data_source: str
    screener_years: str
    pass_notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)


def _parse_screener_section_table(html: str, section_id: str) -> tuple[list[int], dict[str, list[Optional[float]]]]:
    """Parse first table in a Screener.in section — row label → values by Mar FY."""
    m = re.search(rf'id=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</section>', html, re.S | re.I)
    if not m:
        return [], {}
    tables = re.findall(r"<table[^>]*>(.*?)</table>", m.group(1), re.S | re.I)
    if not tables:
        return [], {}

    rows: list[list[str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tables[0], re.S | re.I):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S | re.I)
        ]
        if cells:
            rows.append(cells)
    if len(rows) < 2:
        return [], {}

    years: list[int] = []
    for label in rows[0][1:]:
        fy = _parse_mar_fy_year(label)
        if fy:
            years.append(fy)
    if not years:
        return [], {}

    data: dict[str, list[Optional[float]]] = {}
    for cells in rows[1:]:
        label = (cells[0] or "").strip()
        if not label:
            continue
        vals: list[Optional[float]] = []
        for v in cells[1 : 1 + len(years)]:
            n = _parse_screener_number(v)
            vals.append(n)
        data[label.lower()] = vals

    return years, data


def _row_values(data: dict[str, list[Optional[float]]], *needles: str) -> list[Optional[float]]:
    for key, vals in data.items():
        if any(n in key for n in needles):
            return vals
    return []


def fetch_screener_annuals(display_ticker: str) -> ScreenerAnnualSeries:
    """Pull Sales+, Net Profit, OPM, CFO from Screener.in consolidated statements."""
    out = ScreenerAnnualSeries()
    try:
        from screener_buyback import SCREENER_BASE, _http_get, resolve_screener_company_id

        _, _, slug = resolve_screener_company_id(display_ticker)
        slug = slug or display_ticker.replace(".NS", "").replace(".BO", "")
        base = f"{SCREENER_BASE}/company/{slug}/consolidated/"
        html = _http_get(base)

        pl_years, pl_data = _parse_screener_section_table(html, "profit-loss")
        if pl_years:
            sales_vals = _row_values(pl_data, "sales+", "sales +", "revenue")
            profit_vals = _row_values(pl_data, "net profit", "pat", "profit after tax")
            opm_vals = _row_values(pl_data, "opm")

            for y, v in zip(pl_years, sales_vals):
                if v is not None and v > 0:
                    out.sales.append((y, float(v)))
            for y, v in zip(pl_years, profit_vals):
                if v is not None:
                    out.net_profit.append((y, float(v)))
            for y, v in zip(pl_years, opm_vals):
                if v is not None:
                    out.opm_pct[y] = float(v)
            out.sales.sort(key=lambda x: x[0])
            out.net_profit.sort(key=lambda x: x[0])

        cf_years, cf_data = _parse_screener_section_table(html, "cash-flow")
        if cf_years:
            cfo_vals = _row_values(
                cf_data,
                "cash from operating",
                "operating activity",
                "cash flows from operating",
            )
            for y, v in zip(cf_years, cfo_vals):
                if v is not None:
                    out.cfo.append((y, float(v)))
            out.cfo.sort(key=lambda x: x[0])

        if out.sales:
            out.source = "Screener.in consolidated (Mar FY)"
        elif out.net_profit or out.cfo:
            out.source = "Screener.in (partial — sales from Yahoo if needed)"

        if not out.sales:
            try:
                from valuation_model import fetch_screener_pl_metrics

                sales_pl, opm_pl, src = fetch_screener_pl_metrics(display_ticker)
                if sales_pl:
                    out.sales = [(y, float(v)) for y, v in sales_pl]
                for y, v in (opm_pl or {}).items():
                    out.opm_pct.setdefault(y, float(v))
                if sales_pl and not out.source.startswith("Screener"):
                    out.source = src or out.source
            except Exception:
                pass
    except Exception:
        pass
    return out


def _yoy_pct(series: list[tuple[int, float]]) -> Optional[float]:
    if len(series) < 2:
        return None
    cur_y, cur_v = series[-1]
    prev_y, prev_v = series[-2]
    if prev_v == 0 or abs(prev_v) < 1e-6:
        return None
    return round((cur_v / prev_v - 1.0) * 100.0, 1)


def _cagr_pct(series: list[tuple[int, float]], years: int = 3) -> Optional[float]:
    if len(series) < years:
        return None
    end_y, end_v = series[-1]
    start_y, start_v = series[-1 - (years - 1)]
    if start_v <= 0 or end_v <= 0:
        return None
    span = max(end_y - start_y, 1)
    if span <= 0:
        return None
    n = span
    return round(((end_v / start_v) ** (1.0 / n) - 1.0) * 100.0, 1)


def _latest_pair_value(series: list[tuple[int, float]]) -> Optional[float]:
    return float(series[-1][1]) if series else None


def _opm_delta_3y(opm: dict[int, float], sales: list[tuple[int, float]]) -> Optional[float]:
    if not opm or len(sales) < 2:
        return None
    latest_y = sales[-1][0]
    prior_y = None
    for y in sorted(opm.keys(), reverse=True):
        if y < latest_y - 1:
            prior_y = y
            break
    if prior_y is None:
        keys = sorted(opm.keys())
        if len(keys) < 2:
            return None
        prior_y = keys[-2]
    if latest_y not in opm or prior_y not in opm:
        return None
    return round(opm[latest_y] - opm[prior_y], 1)


def _cfo_to_pat(cfo: list[tuple[int, float]], profit: list[tuple[int, float]]) -> Optional[float]:
    if not cfo or not profit:
        return None
    cfo_v = cfo[-1][1]
    pat = profit[-1][1]
    if pat is None or pat <= 0:
        return None
    return round(cfo_v / pat, 2)


def _detect_tailwinds(sector: str, industry: str, name: str) -> list[str]:
    blob = f"{sector} {industry} {name}".lower()
    hits: list[str] = []
    for label, kws in TAILWIND_KEYWORDS.items():
        if any(k in blob for k in kws):
            hits.append(label)
    return hits


def _is_ancillary(sector: str, industry: str, name: str) -> bool:
    blob = f"{sector} {industry} {name}".lower()
    return any(k in blob for k in ANCILLARY_KEYWORDS)


def _asset_light_proxy(info: dict, sector: str, industry: str) -> bool:
    blob = f"{sector} {industry}".lower()
    if any(k in blob for k in ("software", "it ", "amc", "asset management", "financial services", "fintech")):
        return True
    ta = info.get("totalAssets")
    rev = info.get("totalRevenue") or info.get("revenue")
    try:
        if ta and rev and float(rev) > 0:
            return float(ta) / float(rev) < 3.0
    except (TypeError, ValueError):
        pass
    return False


def _mb_score(
    sales_yoy: Optional[float],
    profit_yoy: Optional[float],
    cfo_ratio: Optional[float],
    opm_delta: Optional[float],
    tailwind_count: int,
    ancillary: bool,
    asset_light: bool,
) -> float:
    s = float(sales_yoy or 0)
    p = float(profit_yoy or 0)
    leverage = max(0.0, p - s)
    cash_pts = min(float(cfo_ratio or 0), 2.0) * 12.0 if cfo_ratio is not None else 0.0
    opm_pts = max(0.0, float(opm_delta or 0)) * 0.8
    tw_pts = min(tailwind_count, 3) * 5.0
    raw = s * 0.22 + p * 0.28 + leverage * 0.15 + cash_pts + opm_pts + tw_pts
    if ancillary:
        raw += 8.0
    if asset_light:
        raw += 6.0
    return round(min(100.0, max(0.0, raw)), 1)


def _verdict(
    sales_yoy: Optional[float],
    profit_yoy: Optional[float],
    cfo_ratio: Optional[float],
    pass_cash: bool,
    tailwinds: list[str],
) -> str:
    s = float(sales_yoy or 0)
    p = float(profit_yoy or 0)
    if p >= 150 and s >= 60 and pass_cash:
        return "NPST-style hyper growth — track quarterly"
    if p >= 80 and s >= 40 and pass_cash:
        return "Acceleration candidate — verify concall"
    if p >= 50 and not pass_cash:
        return "Growth but weak cash — channel-dumping risk"
    if tailwinds:
        return f"Tailwind ({tailwinds[0]}) — confirm orders"
    return "Watch — needs more data"


def _yahoo_fallback_growth(info: dict) -> tuple[Optional[float], Optional[float]]:
    from multibagger import normalize_growth_pct

    sales = normalize_growth_pct(
        info.get("revenueGrowth") or info.get("revenueQuarterlyGrowth")
    )
    profit = normalize_growth_pct(
        info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    )
    return sales, profit


def _passes(
    metrics: dict,
    flt: MultibaggerPatternFilters,
    tailwinds: list[str],
    ancillary: bool,
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    sy = metrics.get("sales_yoy_pct")
    py = metrics.get("profit_yoy_pct")
    cfo_r = metrics.get("cfo_to_pat")
    opm_d = metrics.get("opm_delta_3y_pp")
    mcap = metrics.get("market_cap_cr")
    roce = metrics.get("roce_pct")
    pe = metrics.get("pe")

    if sy is None or sy < flt.min_sales_yoy_pct:
        return False, notes
    notes.append(f"Sales YoY {sy:.1f}%")

    if py is None or py < flt.min_profit_yoy_pct:
        return False, notes
    notes.append(f"Profit YoY {py:.1f}%")

    if flt.require_profit_beats_sales and py <= sy:
        return False, notes
    notes.append("Profit growth > sales growth")

    if flt.require_cash_backed:
        if cfo_r is None or cfo_r < flt.min_cfo_to_pat:
            return False, notes
        notes.append(f"CFO/PAT {cfo_r:.2f}")

    if flt.min_opm_expansion_pp > 0:
        if opm_d is None or opm_d < flt.min_opm_expansion_pp:
            return False, notes
        if opm_d is not None:
            notes.append(f"OPM +{opm_d:.1f} pp")

    if mcap is not None:
        if mcap < flt.min_market_cap_cr or mcap > flt.max_market_cap_cr:
            return False, notes
        notes.append(f"Mcap ₹{mcap:,.0f} Cr")

    if roce is None or roce < flt.min_roce_pct:
        return False, notes
    notes.append(f"ROCE {roce:.1f}%")

    if pe is not None and pe > flt.max_pe:
        return False, notes

    if flt.tailwind_only and not tailwinds:
        return False, notes

    if flt.ancillary_only and not ancillary:
        return False, notes

    if flt.prefer_asset_light and not metrics.get("asset_light"):
        return False, notes

    return True, notes


def scan_multibagger_patterns(
    scan_source: str,
    filters: MultibaggerPatternFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    *,
    max_results: int = 80,
) -> list[MultibaggerPatternResult]:
    flt = filters or MultibaggerPatternFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[MultibaggerPatternResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        if len(results) >= max_results:
            break

        try:
            disp = raw.replace(".NS", "").replace(".BO", "")
            screener = fetch_screener_annuals(disp)

            stock = yf.Ticker(raw)
            try:
                info = stock.info or {}
            except Exception:
                info = {}
            if not info.get("symbol") and not info.get("shortName"):
                continue

            fund = extract_multibagger_fundamentals(info)
            sector, industry = get_sector_industry(stock)
            price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0.0)
            if price <= 0:
                continue

            pe = get_pe(stock)
            sales_yoy = _yoy_pct(screener.sales)
            profit_yoy = _yoy_pct(screener.net_profit)
            data_src = screener.source or "Yahoo Finance proxies"

            if sales_yoy is None or profit_yoy is None:
                y_sales, y_profit = _yahoo_fallback_growth(info)
                if sales_yoy is None:
                    sales_yoy = y_sales
                if profit_yoy is None:
                    profit_yoy = y_profit
                if not screener.sales:
                    data_src = "Yahoo Finance (Screener P&L unavailable)"

            sales_cagr = _cagr_pct(screener.sales, 3)
            profit_cagr = _cagr_pct(screener.net_profit, 3)
            opm_latest = screener.opm_pct.get(screener.sales[-1][0]) if screener.sales else None
            opm_delta = _opm_delta_3y(screener.opm_pct, screener.sales)
            cfo_ratio = _cfo_to_pat(screener.cfo, screener.net_profit)

            tailwinds = _detect_tailwinds(sector or "", industry or "", label)
            ancillary = _is_ancillary(sector or "", industry or "", label)
            asset_light = _asset_light_proxy(info, sector or "", industry or "")

            wk_high = fund.get("week52_high")
            dd = drawdown_pct_from_52w_high(price, wk_high)

            ret_1y: Optional[float] = None
            try:
                hist = stock.history(period="1y", interval="1d", auto_adjust=True)
                if hist is not None and len(hist) >= 30:
                    c0 = float(hist["Close"].iloc[0])
                    c1 = float(hist["Close"].iloc[-1])
                    if c0 > 0:
                        ret_1y = round((c1 / c0 - 1.0) * 100.0, 1)
            except Exception:
                pass

            patterns: list[str] = []
            if sales_yoy and sales_yoy >= 80:
                patterns.append("Hyper sales")
            if profit_yoy and profit_yoy >= 120:
                patterns.append("Profit explosion")
            if profit_yoy and sales_yoy and profit_yoy > sales_yoy + 20:
                patterns.append("Operating leverage")
            if cfo_ratio is not None and cfo_ratio >= flt.min_cfo_to_pat:
                patterns.append("Cash-backed")
            elif cfo_ratio is not None and cfo_ratio < 0.5:
                patterns.append("⚠ Weak CFO")
            if opm_delta and opm_delta >= 2:
                patterns.append("Margin expansion")
            if asset_light:
                patterns.append("Asset-light")
            if ancillary:
                patterns.append("Ancillary play")

            metrics = {
                "sales_yoy_pct": sales_yoy,
                "profit_yoy_pct": profit_yoy,
                "cfo_to_pat": cfo_ratio,
                "opm_delta_3y_pp": opm_delta,
                "market_cap_cr": fund.get("market_cap_cr"),
                "roce_pct": fund.get("roce_pct"),
                "pe": pe,
                "asset_light": asset_light,
            }
            ok, notes = _passes(metrics, flt, tailwinds, ancillary)
            if not ok:
                continue

            score = _mb_score(
                sales_yoy, profit_yoy, cfo_ratio, opm_delta,
                len(tailwinds), ancillary, asset_light,
            )
            years_lbl = ""
            if screener.sales:
                years_lbl = f"{screener.sales[0][0]}–{screener.sales[-1][0]}"

            links = get_stock_links(raw)
            slug = disp
            try:
                from screener_buyback import resolve_screener_company_id

                _, _, slug = resolve_screener_company_id(disp)
            except Exception:
                pass
            links["Screener.in"] = f"https://www.screener.in/company/{slug}/consolidated/"

            results.append(
                MultibaggerPatternResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    sector=sector or "—",
                    industry=industry or "—",
                    price=round(price, 2),
                    pe=round(float(pe), 2) if pe is not None else None,
                    market_cap_cr=fund.get("market_cap_cr"),
                    market_cap_display=fund.get("market_cap_display") or "",
                    sales_yoy_pct=sales_yoy,
                    profit_yoy_pct=profit_yoy,
                    sales_cagr_3y_pct=sales_cagr,
                    profit_cagr_3y_pct=profit_cagr,
                    opm_latest_pct=opm_latest,
                    opm_delta_3y_pp=opm_delta,
                    cfo_to_pat=cfo_ratio,
                    roce_pct=fund.get("roce_pct"),
                    drawdown_52w_pct=dd,
                    return_1y_pct=ret_1y,
                    mb_score=score,
                    patterns=" · ".join(patterns) if patterns else "—",
                    tailwinds=" · ".join(tailwinds) if tailwinds else "—",
                    verdict=_verdict(sales_yoy, profit_yoy, cfo_ratio, cfo_ratio is not None and cfo_ratio >= flt.min_cfo_to_pat, tailwinds),
                    data_source=data_src,
                    screener_years=years_lbl,
                    pass_notes=notes,
                    links=links,
                )
            )
        except Exception:
            continue

        if flt.screener_delay_sec > 0:
            time.sleep(flt.screener_delay_sec)

    return sort_mb_pattern_results(results)


def sort_mb_pattern_results(
    results: list[MultibaggerPatternResult],
    *,
    rank_by: str = "mb_score",
) -> list[MultibaggerPatternResult]:
    if rank_by == "profit_yoy":
        key = lambda r: float(r.profit_yoy_pct or -9999)
    elif rank_by == "sales_yoy":
        key = lambda r: float(r.sales_yoy_pct or -9999)
    elif rank_by == "cfo_ratio":
        key = lambda r: float(r.cfo_to_pat or -9999)
    elif rank_by == "opm_delta":
        key = lambda r: float(r.opm_delta_3y_pp or -9999)
    else:
        key = lambda r: float(r.mb_score or 0)
    return sorted(results, key=key, reverse=True)


def result_to_row(r: MultibaggerPatternResult, rank: int) -> dict:
    roce_lbl = (
        f"{r.roce_pct:.1f}" if r.roce_pct is not None else "—"
    )
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "MB score": r.mb_score,
        "Verdict": r.verdict,
        "Patterns": r.patterns,
        "Tailwinds": r.tailwinds,
        "Sales YoY %": r.sales_yoy_pct,
        "Profit YoY %": r.profit_yoy_pct,
        "Sales CAGR 3Y %": r.sales_cagr_3y_pct,
        "Profit CAGR 3Y %": r.profit_cagr_3y_pct,
        "OPM %": r.opm_latest_pct,
        "OPM Δ 3Y pp": r.opm_delta_3y_pp,
        "CFO/PAT": r.cfo_to_pat,
        "ROCE %": roce_lbl,
        "1Y return %": r.return_1y_pct,
        "Below 52w %": r.drawdown_52w_pct,
        "Price": r.price,
        "P/E": r.pe,
        "Mcap": r.market_cap_display,
        "Sector": r.sector,
        "Industry": r.industry,
        "Data": r.data_source,
        "Screener yrs": r.screener_years,
        "Notes": " · ".join(r.pass_notes[:4]),
    }
