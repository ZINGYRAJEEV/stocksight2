"""
Generic forward valuation rulebook — Rules 1–6 chain, sector benchmarks (Rule 8), CAGR table (Rule 9).

Educational model (Jupiter / NAM India sheet style). Yahoo Finance proxies for base year —
customise growth, OPM, capex, P/E, and shares before publishing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from multibagger import INR_PER_CRORE, extract_multibagger_fundamentals
from screener import get_pe, get_sector_industry, get_stock_links

META = {
    "id": "valuation_rulebook",
    "title": "Valuation Rulebook",
    "emoji": "🧮",
    "nav_title": "Valuation Rulebook",
    "audience": (
        "Fundamental investors building **forward EPS × P/E** models for any NSE stock — "
        "same Rule 1–6 chain as Jupiter / NAM India sheets, with **sector tabs** and **CAGR sensitivity**."
    ),
    "purpose": (
        "Interactive revenue → OPM → PAT → EPS → target price workbook. "
        "Plug in Screener.in growth, margin guidance, capex/debt, and peer P/E (de-rated for projections)."
    ),
}

SECTOR_KEYS = (
    "amc",
    "bfsi",
    "it_services",
    "consumer",
    "industrials",
    "auto",
    "generic",
)

SECTOR_LABELS: dict[str, str] = {
    "amc": "AMC / Asset Management",
    "bfsi": "BFSI / NBFC (banks)",
    "it_services": "IT & Services",
    "consumer": "Consumer / FMCG",
    "industrials": "Industrials / Capital goods",
    "auto": "Auto & Ancillaries",
    "generic": "Generic / Other",
}

# Rule 8 — sector benchmarks & volume driver hints
SECTOR_RULEBOOK: dict[str, dict[str, Any]] = {
    "amc": {
        "row1_label": "Revenue (fee income on AUM)",
        "volume_driver": "AUM growth × revenue yield (~0.45–0.55% of AUM) + market-share gain",
        "opm_benchmark": "OPM 60–67% (operating leverage) — NAM / HDFC AMC range",
        "opm_default_pct": 63.0,
        "pe_benchmark": "P/E 35–45× AMC premium — de-rate outer year (e.g. 45 → 30)",
        "pe_default": 42.0,
        "pe_is_pb": False,
        "growth_hint": "AMFI industry AUM growth + company concall guidance",
    },
    "bfsi": {
        "row1_label": "Net interest income / fee income (proxy: total revenue)",
        "volume_driver": "Loan book (AUM) growth × NIM expansion + fee income mix",
        "opm_benchmark": "ROA 1.2–2.0% · NIM 3–4% (banks) — use PAT margin proxy 18–28%",
        "opm_default_pct": 22.0,
        "pe_benchmark": "P/B 1.5–2.5× (de-rate vs peak cycle)",
        "pe_default": 2.2,
        "pe_is_pb": True,
        "growth_hint": "Credit growth vs system + deposit franchise",
    },
    "it_services": {
        "row1_label": "Revenue (USD / INR)",
        "volume_driver": "Revenue = headcount × utilisation × billing rate; watch deal wins & attrition",
        "opm_benchmark": "OPM 20–26% (mature) · 15–20% (transition)",
        "opm_default_pct": 22.0,
        "pe_benchmark": "P/E 22–32× (de-rate 10–15% for outer-year projections)",
        "pe_default": 26.0,
        "pe_is_pb": False,
        "growth_hint": "CC growth guidance + large-deal pipeline",
    },
    "consumer": {
        "row1_label": "Revenue",
        "volume_driver": "Revenue ≈ volume growth + ASP/mix + distribution expansion",
        "opm_benchmark": "OPM 12–18% (FMCG) · 8–14% (discretionary retail)",
        "opm_default_pct": 15.0,
        "pe_benchmark": "P/E 40–60× (premium brands) · de-rate if growth <15%",
        "pe_default": 45.0,
        "pe_is_pb": False,
        "growth_hint": "Volume + premiumisation; check SSSG for retail",
    },
    "industrials": {
        "row1_label": "Revenue",
        "volume_driver": "Order book / book-to-bill × execution; capacity utilisation",
        "opm_benchmark": "OPM 12–20% (capital goods) · EBITDA margin 14–22%",
        "opm_default_pct": 16.0,
        "pe_benchmark": "P/E 25–40× (cycle peak → use mid-cycle multiple)",
        "pe_default": 28.0,
        "pe_is_pb": False,
        "growth_hint": "Order inflow vs revenue — 12–18m visibility",
    },
    "auto": {
        "row1_label": "Revenue",
        "volume_driver": "Revenue = units × ASP; watch SIAM monthly volumes vs peers",
        "opm_benchmark": "OPM 8–14% (OEM) · 10–16% (ancillaries)",
        "opm_default_pct": 11.0,
        "pe_benchmark": "P/E 18–28× (de-rate at cycle high margins)",
        "pe_default": 22.0,
        "pe_is_pb": False,
        "growth_hint": "Volume market-share gain + mix (SUV)",
    },
    "generic": {
        "row1_label": "Revenue",
        "volume_driver": "Revenue = volume × price; identify the one KPI management guides on",
        "opm_benchmark": "OPM vs 5y average — avoid projecting peak margin",
        "opm_default_pct": 14.0,
        "pe_benchmark": "Screener.in peers tab — de-rate 10–20% for outer year",
        "pe_default": 25.0,
        "pe_is_pb": False,
        "growth_hint": "5y revenue CAGR + latest concall guidance",
    },
}

# Common mistyped NSE symbols → Yahoo trading symbol (without .NS)
NSE_TICKER_ALIASES: dict[str, str] = {
    "NAMINDIA": "NAM-INDIA",
    "NAMINDIALTD": "NAM-INDIA",
    "NIPPONAMC": "NAM-INDIA",
    "HDFCAMC": "HDFCAMC",
    "360ONE": "360ONE",
}
COMMON_MISTAKES: list[dict[str, str]] = [
    {
        "title": "Peak margin projection",
        "body": "Projecting today's OPM into Year 5 when the company is at a cyclical high "
        "overstates PAT. Use 5y average or sector mid-cycle benchmark from Rule 8.",
    },
    {
        "title": "Static P/E on outer year",
        "body": "Applying peak-cycle P/E to forward EPS double-counts optimism. De-rate peer "
        "multiple by 10–20% when earnings are projected, not trailing.",
    },
    {
        "title": "Ignoring dilution",
        "body": "QIP, ESOP, and convertible instruments inflate share count. Always verify "
        "shares outstanding before publishing — stale data understates EPS dilution.",
    },
    {
        "title": "Capex funded by debt",
        "body": "High growth + rising net debt without ROCE support can destroy equity value. "
        "Cross-check investor presentation for capex and incremental debt.",
    },
]

RULE_CHAIN_LABELS: list[tuple[str, str]] = [
    ("rule1", "Rule 1 — Base revenue (Row 1)"),
    ("rule2", "Rule 2 — Volume driver (sector formula)"),
    ("rule3", "Rule 3 — Revenue projection"),
    ("rule4", "Rule 4 — OPM / margin"),
    ("rule5", "Rule 5 — PAT (after tax & interest drag)"),
    ("rule6", "Rule 6 — EPS × P/E → target price"),
]


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


def classify_valuation_sector(sector: str, industry: str = "") -> str:
    blob = f"{sector or ''} {industry or ''}".lower()
    if any(k in blob for k in ("asset management", "amc", "mutual fund")):
        return "amc"
    if any(k in blob for k in ("bank", "financial", "insurance", "nbfc", "lending")):
        return "bfsi"
    if any(k in blob for k in ("software", "information technology", "it services", "consulting")):
        return "it_services"
    if any(k in blob for k in ("consumer", "fmcg", "staple", "retail", "food", "beverage")):
        return "consumer"
    if any(k in blob for k in ("industrial", "capital goods", "engineering", "infrastructure")):
        return "industrials"
    if any(k in blob for k in ("auto", "automobile", "motor", "tyre", "ancillar")):
        return "auto"
    return "generic"


@dataclass
class ValuationBaseline:
    raw_ticker: str
    display_ticker: str
    company_name: str
    sector: str
    industry: str
    sector_key: str
    price: float
    market_cap_cr: Optional[float]
    revenue_cr: Optional[float]
    revenue_growth_5y_pct: Optional[float]
    opm_pct: Optional[float]
    pat_margin_pct: Optional[float]
    tax_rate_pct: float
    interest_drag_pct: float
    shares_cr: Optional[float]
    trailing_eps: Optional[float]
    trailing_pe: Optional[float]
    book_value_per_share: Optional[float]
    historical_revenue: list[tuple[int, float]] = field(default_factory=list)
    historical_opm_pct: dict[int, float] = field(default_factory=dict)
    historical_revenue_source: str = ""
    links: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    resolved_ticker: str = ""
    user_ticker_input: str = ""
    data_ok: bool = False


def _ticker_has_yahoo_data(ticker: str) -> bool:
    if not ticker:
        return False
    try:
        info = yf.Ticker(ticker).info or {}
        price = _gf(info, ("regularMarketPrice", "currentPrice", "previousClose"))
        return price is not None and float(price) > 0
    except Exception:
        return False


def _compact_symbol(symbol: str) -> str:
    return (symbol or "").upper().replace(".NS", "").replace(".BO", "").replace("-", "").replace(" ", "")


def resolve_valuation_ticker(raw: str) -> tuple[str, list[str]]:
    """Resolve user input to a Yahoo NSE symbol. Returns (ticker.NS, candidates tried)."""
    from niftyrisk.portfolio import normalize_ticker_nse

    text = (raw or "").strip().upper().replace(" ", "")
    tried: list[str] = []
    if not text:
        return "", tried

    candidates: list[str] = []
    bare = text.replace(".NS", "").replace(".BO", "")

    if text.endswith((".NS", ".BO")):
        candidates.append(normalize_ticker_nse(text))
    else:
        candidates.append(normalize_ticker_nse(bare))
        alias = NSE_TICKER_ALIASES.get(_compact_symbol(bare))
        if alias:
            candidates.append(normalize_ticker_nse(alias))

    try:
        from screener import NIFTY_50, NIFTY_500_EXTRA

        want = _compact_symbol(bare)
        for sym in NIFTY_50 + NIFTY_500_EXTRA:
            if _compact_symbol(sym) == want and sym not in candidates:
                candidates.append(sym)
    except ImportError:
        pass

    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)

    for cand in ordered:
        tried.append(cand)
        if _ticker_has_yahoo_data(cand):
            return cand, tried

    return ordered[0] if ordered else normalize_ticker_nse(bare), tried


@dataclass
class ValuationInputs:
    revenue_cr_y0: float
    revenue_growth_pct: float
    projection_years: int
    opm_pct: float
    tax_rate_pct: float
    interest_drag_pct: float
    shares_cr: float
    fair_pe: float
    pe_is_pb: bool = False
    book_value_per_share: float = 0.0
    capex_pct_revenue: float = 0.0  # informational
    new_debt_cr: float = 0.0
    terminal_pe: Optional[float] = None
    terminal_opm_pct: Optional[float] = None
    base_calendar_year: Optional[int] = None
    cagr_holding_years: Optional[int] = None
    revenue_growth_path: Optional[list[float]] = None  # % per step (IndiaMart-style)


def default_estimate_year(baseline: ValuationBaseline) -> int:
    """Latest Mar FY on Screener history, else current calendar year."""
    if baseline.historical_revenue:
        return int(baseline.historical_revenue[-1][0])
    return datetime.now().year


def revenue_for_mar_fy(baseline: ValuationBaseline, mar_year: int) -> Optional[float]:
    for y, r in baseline.historical_revenue:
        if y == mar_year:
            return float(r)
    return None


YearKind = Literal["historical", "estimate", "projection"]


@dataclass
class YearColumn:
    label: str
    calendar_year: int
    kind: YearKind


@dataclass
class ValuationProjection:
    year_columns: list[YearColumn]
    revenue_cr: list[float]
    revenue_growth_pct: list[Optional[float]]
    opm_pct: list[float]
    op_cr: list[float]
    pat_cr: list[float]
    pe_multiple: list[Optional[float]]
    market_cap_cr: list[Optional[float]]
    share_price: list[Optional[float]]
    shares_cr: list[float]
    eps: list[float]
    fair_value_terminal: float
    upside_pct: float
    implied_cagr_pct: float
    chain_rows: list[dict[str, Any]]
    target_holding_years: int


def _revenue_from_financials(stock: yf.Ticker) -> Optional[float]:
    try:
        fin = stock.financials
        if fin is not None and not fin.empty and "Total Revenue" in fin.index:
            rev = float(fin.loc["Total Revenue"].iloc[0])
            if rev > 0:
                return rev
    except Exception:
        pass
    return None


def _parse_mar_fy_year(label: str) -> Optional[int]:
    m = re.search(r"Mar\s+(\d{4})", label, re.I)
    return int(m.group(1)) if m else None


def _parse_screener_number(text: str) -> Optional[float]:
    raw = re.sub(r"<[^>]+>", "", text or "")
    raw = raw.replace("\xa0", " ").replace("&nbsp;", " ").strip()
    if not raw or raw in ("—", "-"):
        return None
    if raw.endswith("%"):
        try:
            return float(raw[:-1].strip())
        except ValueError:
            return None
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_screener_profit_loss(html: str) -> tuple[list[tuple[int, float]], dict[int, float]]:
    """Parse Screener.in consolidated P&L — Sales+ and OPM % by Mar FY."""
    m = re.search(r'id=["\']profit-loss["\'][^>]*>(.*?)</section>', html, re.S | re.I)
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

    sales: list[tuple[int, float]] = []
    opm: dict[int, float] = {}
    for cells in rows[1:]:
        label = (cells[0] or "").lower()
        values = cells[1 : 1 + len(years)]
        if "sales" in label or label.strip() in ("revenue", "revenue +"):
            for y, v in zip(years, values):
                n = _parse_screener_number(v)
                if n is not None and n > 0:
                    sales.append((y, round(n, 0)))
        elif "opm" in label:
            for y, v in zip(years, values):
                n = _parse_screener_number(v)
                if n is not None:
                    opm[y] = round(n, 1)

    sales.sort(key=lambda x: x[0])
    return sales, opm


def fetch_screener_pl_metrics(display_ticker: str) -> tuple[list[tuple[int, float]], dict[int, float], str]:
    """Pull annual Sales+ and OPM % from Screener.in (matches your workbook)."""
    try:
        from screener_buyback import SCREENER_BASE, _http_get, resolve_screener_company_id

        _, _, slug = resolve_screener_company_id(display_ticker)
        slug = slug or display_ticker.replace(".NS", "").replace(".BO", "")
        url = f"{SCREENER_BASE}/company/{slug}/consolidated/"
        html = _http_get(url)
        sales, opm = _parse_screener_profit_loss(html)
        if sales:
            return sales, opm, "Screener.in P&L — Sales+ (consolidated, Mar FY)"
    except Exception:
        pass
    return [], {}, ""


def default_revenue_cr_y0(baseline: ValuationBaseline) -> tuple[float, str]:
    """Row 1 default and where it came from."""
    if baseline.historical_revenue:
        y, r = baseline.historical_revenue[-1]
        src = baseline.historical_revenue_source or "Screener.in / Yahoo"
        return float(r), f"{src} — latest Mar {y}: ₹{r:,.0f} Cr"
    if baseline.revenue_cr is not None and baseline.revenue_cr > 0:
        return float(baseline.revenue_cr), "Yahoo Finance (latest annual revenue / totalRevenue)"
    return 1000.0, "Placeholder only — enter Sales+ from Screener.in P&L"


def apply_baseline_to_session(base: ValuationBaseline, *, book: dict[str, Any]) -> None:
    """Push Yahoo-loaded defaults into Streamlit widget session state."""
    import streamlit as st

    rev, _ = default_revenue_cr_y0(base)
    opm_start = float(base.opm_pct or book["opm_default_pct"])
    opm_end = float(base.opm_pct or book["opm_default_pct"])
    if base.sector_key == "amc" and base.opm_pct:
        opm_end = min(80.0, opm_start + 4.0)
    pe_start = float(
        base.trailing_pe if base.trailing_pe and not book.get("pe_is_pb") else book["pe_default"]
    )
    pe_end = round(pe_start * 0.67, 1)

    st.session_state.val_rev0 = float(rev)
    st.session_state.val_rev_g = float(base.revenue_growth_5y_pct or 12.0)
    st.session_state.val_opm = opm_start
    st.session_state.val_terminal_opm = opm_end
    st.session_state.val_shares = float(base.shares_cr or 1.0)
    st.session_state.val_pe_start = pe_start
    st.session_state.val_pe_terminal = pe_end
    st.session_state.val_entry_px = float(base.price or 1.0)
    st.session_state.val_sector_key = base.sector_key
    st.session_state.val_loaded_ticker = base.display_ticker
    st.session_state.val_est_year = default_estimate_year(base)
    st.session_state.val_use_growth_path = False
    st.session_state.val_growth_path_text = ""


def load_valuation_baseline(raw_ticker: str) -> ValuationBaseline:
    user_in = (raw_ticker or "").strip()
    raw, tried = resolve_valuation_ticker(user_in)
    notes: list[str] = []
    stock = yf.Ticker(raw)
    try:
        info = stock.info or {}
    except Exception:
        info = {}

    sector, industry = get_sector_industry(stock)
    sector_key = classify_valuation_sector(sector, industry)
    book = SECTOR_RULEBOOK[sector_key]

    price = _gf(info, ("regularMarketPrice", "currentPrice", "previousClose")) or 0.0
    fund = extract_multibagger_fundamentals(info)
    mcap_cr = fund.get("market_cap_cr")

    rev_raw = _revenue_from_financials(stock) or _gf(info, ("totalRevenue",))
    revenue_cr = None
    if rev_raw and rev_raw > 0:
        currency = str(info.get("currency") or "INR").upper()
        if currency == "INR":
            revenue_cr = round(float(rev_raw) / INR_PER_CRORE, 2)
        else:
            revenue_cr = round(float(rev_raw) / 1e7, 2)

    rev_growth = _gf(info, ("revenueGrowth", "threeYearRevenueGrowthRate"))
    if rev_growth is not None and abs(rev_growth) <= 1.0:
        rev_growth = round(rev_growth * 100.0, 2)

    opex = _gf(info, ("operatingMargins", "operatingMargin"))
    if opex is not None and abs(opex) <= 1.0:
        opex = round(opex * 100.0, 2)

    profit_margin = _gf(info, ("profitMargins",))
    if profit_margin is not None and abs(profit_margin) <= 1.0:
        profit_margin = round(profit_margin * 100.0, 2)

    shares = _gf(info, ("sharesOutstanding",))
    shares_cr = round(shares / 1e7, 4) if shares and shares > 0 else None

    eps = _gf(info, ("trailingEps", "epsTrailingTwelveMonths"))
    pe = get_pe(stock)
    bv = _gf(info, ("bookValue",))

    if revenue_cr is None:
        notes.append("Revenue missing on Yahoo — enter Row 1 manually from Screener.in.")
    if shares_cr is None:
        notes.append("Share count missing — verify for QIP/ESOP dilution.")
    if opex is None:
        opex = book["opm_default_pct"]
        notes.append(f"OPM defaulted to sector benchmark {opex:.1f}%.")

    disp = raw.replace(".NS", "").replace(".BO", "")
    screener_sales, screener_opm, screener_src = fetch_screener_pl_metrics(disp)
    hist_rev = screener_sales if screener_sales else _revenue_history(stock)
    hist_src = screener_src if screener_sales else "Yahoo Finance annual Total Revenue (may differ from Screener)"

    if screener_sales:
        latest_y, latest_sales = screener_sales[-1]
        revenue_cr = float(latest_sales)
        if screener_src:
            notes.append(f"Revenue history aligned to **Screener.in** (Sales+, Mar FY).")
        # 3Y sales CAGR from Screener when Yahoo growth missing
        if len(screener_sales) >= 4 and (rev_growth is None or rev_growth == 0):
            y0, r0 = screener_sales[-4]
            y1, r1 = screener_sales[-1]
            if r0 > 0 and y1 > y0:
                rev_growth = round(((r1 / r0) ** (1.0 / (y1 - y0)) - 1.0) * 100.0, 1)
    elif hist_rev and not revenue_cr:
        revenue_cr = float(hist_rev[-1][1])

    data_ok = _ticker_has_yahoo_data(raw) and (
        revenue_cr is not None or bool(hist_rev) or (price or 0) > 0
    )
    if not data_ok:
        notes.append(
            f"Yahoo could not resolve **{user_in}**. "
            f"Tried: {', '.join(tried) or raw}. "
            "Use the exact NSE symbol (e.g. **NAM-INDIA**, not NAMINDIA)."
        )
    elif _compact_symbol(user_in) != _compact_symbol(disp) and tried:
        notes.append(f"Resolved **{user_in}** → Yahoo ticker **{disp}**.")

    return ValuationBaseline(
        raw_ticker=raw,
        display_ticker=disp,
        company_name=str(info.get("shortName") or info.get("longName") or disp),
        sector=sector or "—",
        industry=industry or "—",
        sector_key=sector_key,
        price=round(float(price), 2),
        market_cap_cr=mcap_cr,
        revenue_cr=revenue_cr,
        revenue_growth_5y_pct=rev_growth,
        opm_pct=opex,
        pat_margin_pct=profit_margin,
        tax_rate_pct=25.0,
        interest_drag_pct=1.5,
        shares_cr=shares_cr,
        trailing_eps=round(float(eps), 2) if eps is not None else None,
        trailing_pe=round(float(pe), 2) if pe is not None else None,
        book_value_per_share=round(float(bv), 2) if bv is not None else None,
        historical_revenue=hist_rev,
        historical_opm_pct=screener_opm,
        historical_revenue_source=hist_src,
        links=get_stock_links(raw),
        notes=notes,
        resolved_ticker=raw,
        user_ticker_input=user_in,
        data_ok=data_ok,
    )


def cagr_pct(entry: float, target: float, years: int) -> Optional[float]:
    if entry <= 0 or target <= 0 or years <= 0:
        return None
    return round(((target / entry) ** (1.0 / years) - 1.0) * 100.0, 2)


def _revenue_history(stock: yf.Ticker, max_years: int = 8) -> list[tuple[int, float]]:
    """Annual revenue (₹ Cr) from Yahoo — fallback when Screener unavailable."""
    out: list[tuple[int, float]] = []
    try:
        fin = stock.financials
        if fin is None or fin.empty or "Total Revenue" not in fin.index:
            return out
        currency = "INR"
        try:
            currency = str((stock.info or {}).get("currency") or "INR").upper()
        except Exception:
            pass
        for col in fin.columns[:max_years]:
            try:
                rev = float(fin.loc["Total Revenue", col])
            except (TypeError, ValueError, KeyError):
                continue
            if rev <= 0 or np.isnan(rev):
                continue
            if currency == "INR":
                rev_cr = rev / INR_PER_CRORE
            else:
                rev_cr = rev / 1e7
            # Mar FY label from period end (e.g. 2023-03-31 → Mar 2023)
            year = int(getattr(col, "year", 0) or 0)
            if year <= 0:
                continue
            out.append((year, round(rev_cr, 0)))
    except Exception:
        pass
    out.sort(key=lambda x: x[0])
    return out


def _interp(start: float, end: float, steps: int) -> list[float]:
    if steps <= 1:
        return [round(end, 2)]
    return [round(start + (end - start) * i / (steps - 1), 2) for i in range(steps)]


def _pct_growth(prev: Optional[float], curr: Optional[float]) -> Optional[float]:
    if prev is None or curr is None or prev <= 0:
        return None
    return round((curr / prev - 1.0) * 100.0, 1)


def project_valuation(
    baseline: ValuationBaseline,
    inputs: ValuationInputs,
    *,
    current_price: Optional[float] = None,
    historical: Optional[list[tuple[int, float]]] = None,
) -> ValuationProjection:
    """Rules 1–6 forward chain — NAM India / Jupiter sheet layout."""
    proj_n = max(1, int(inputs.projection_years))
    holding_y = max(1, int(inputs.cagr_holding_years or proj_n))
    est_year = int(inputs.base_calendar_year or datetime.now().year)

    g = float(inputs.revenue_growth_pct) / 100.0
    tax = float(inputs.tax_rate_pct) / 100.0
    int_drag = float(inputs.interest_drag_pct) / 100.0
    shares_cr = max(float(inputs.shares_cr), 0.01)
    shares_abs = shares_cr * 1e7

    start_opm = float(inputs.opm_pct)
    end_opm = float(inputs.terminal_opm_pct if inputs.terminal_opm_pct is not None else start_opm)
    start_pe = float(inputs.fair_pe)
    end_pe = float(inputs.terminal_pe if inputs.terminal_pe is not None else start_pe * 0.67)

    hist = list(historical or [])
    hist = [(y, r) for y, r in hist if y < est_year and r and r > 0 and not np.isnan(r)][-8:]
    opm_by_year = baseline.historical_opm_pct or {}

    def _year_label(y: int) -> str:
        return f"Mar {y}"

    # Forward: estimate year (yellow) + outer projections (orange)
    fwd_years = [est_year + i for i in range(proj_n + 1)]
    rev_est = float(inputs.revenue_cr_y0)
    fwd_revenues = [rev_est]
    growth_path = inputs.revenue_growth_path or []
    for i in range(proj_n):
        if i < len(growth_path):
            rate = float(growth_path[i]) / 100.0  # path values are % (e.g. 10, 5, 15)
        else:
            rate = g  # already decimal (e.g. 0.139 for 13.9%)
        fwd_revenues.append(round(fwd_revenues[-1] * (1.0 + rate), 0))

    opm_path = _interp(start_opm, end_opm, len(fwd_revenues))
    pe_path = _interp(start_pe, end_pe, len(fwd_revenues)) if not inputs.pe_is_pb else [start_pe] * len(fwd_revenues)

    year_columns: list[YearColumn] = []
    revenues: list[float] = []
    growths: list[Optional[float]] = []
    opms: list[float] = []
    ops: list[float] = []
    pats: list[float] = []
    pes: list[Optional[float]] = []
    mcaps: list[Optional[float]] = []
    prices: list[Optional[float]] = []
    shares_list: list[float] = []
    eps_list: list[float] = []

    prev_rev: Optional[float] = None
    for y, r in hist:
        year_columns.append(YearColumn(label=_year_label(y), calendar_year=y, kind="historical"))
        revenues.append(float(r))
        growths.append(_pct_growth(prev_rev, float(r)))
        prev_rev = float(r)
        opm_y = opm_by_year.get(y)
        opms.append(float(opm_y if opm_y is not None else (baseline.opm_pct or start_opm)))
        op = round(r * opms[-1] / 100.0, 0)
        ops.append(op)
        pat = round(op * (1.0 - tax) * (1.0 - int_drag / 100.0), 0)
        pats.append(pat)
        pes.append(None)
        mcaps.append(None)
        prices.append(None)
        shares_list.append(shares_cr)
        eps_list.append(round((pat * 1e7) / shares_abs, 2))

    for i, y in enumerate(fwd_years):
        kind: YearKind = "estimate" if i == 0 else "projection"
        year_columns.append(YearColumn(label=_year_label(y), calendar_year=y, kind=kind))
        rev = fwd_revenues[i]
        revenues.append(rev)
        growths.append(_pct_growth(prev_rev, rev))
        prev_rev = rev
        opm_i = opm_path[i]
        opms.append(opm_i)
        op = round(rev * opm_i / 100.0, 0)
        ops.append(op)
        pat = round(op * (1.0 - tax) * (1.0 - int_drag / 100.0), 0)
        pats.append(pat)
        pe_i = pe_path[i]
        pes.append(pe_i)
        eps = round((pat * 1e7) / shares_abs, 2)
        eps_list.append(eps)
        shares_list.append(shares_cr)
        if inputs.pe_is_pb and inputs.book_value_per_share > 0:
            px = round(inputs.book_value_per_share * pe_i, 2)
            mcap = round(px * shares_abs / 1e7, 0)
        else:
            mcap = round(pat * pe_i, 0)
            px = round((mcap * 1e7) / shares_abs, 2) if shares_abs > 0 else None
        mcaps.append(mcap)
        prices.append(px)

    terminal_px = prices[-1] or 0.0
    px = float(current_price or baseline.price or 0.0)
    upside = round((terminal_px / px - 1.0) * 100.0, 2) if px > 0 and terminal_px > 0 else 0.0
    impl_cagr = cagr_pct(px, terminal_px, holding_y) or 0.0

    sector_book = SECTOR_RULEBOOK.get(baseline.sector_key, SECTOR_RULEBOOK["generic"])
    mult_name = "P/B" if inputs.pe_is_pb else "P/E"
    chain = [
        {
            "Rule": "Rule 1",
            "Line": "Base revenue (Row 1)",
            "Value": f"₹{fwd_revenues[0]:,.0f} Cr ({est_year}E)",
            "Note": sector_book["row1_label"],
        },
        {
            "Rule": "Rule 2",
            "Line": "Volume driver",
            "Value": "—",
            "Note": sector_book["volume_driver"],
        },
        {
            "Rule": "Rule 3",
            "Line": f"Revenue {fwd_years[-1]}",
            "Value": f"₹{fwd_revenues[-1]:,.0f} Cr",
            "Note": (
                f"Custom: {', '.join(f'{x:.1f}%' for x in growth_path)}"
                if growth_path
                else f"Growth {inputs.revenue_growth_pct:.1f}% p.a."
            ),
        },
        {
            "Rule": "Rule 4",
            "Line": f"OPM {start_opm:.1f}% → {end_opm:.1f}%",
            "Value": f"₹{ops[-1]:,.0f} Cr OP",
            "Note": sector_book["opm_benchmark"],
        },
        {
            "Rule": "Rule 5",
            "Line": "Net profit (post tax)",
            "Value": f"₹{pats[-1]:,.0f} Cr",
            "Note": f"Tax {inputs.tax_rate_pct:.0f}% · interest drag {inputs.interest_drag_pct:.1f}%",
        },
        {
            "Rule": "Rule 6",
            "Line": f"{mult_name} × earnings → price",
            "Value": f"₹{terminal_px:,.2f}",
            "Note": f"{mult_name} {start_pe:.1f} → {end_pe:.1f} · EPS ₹{eps_list[-1]:.2f}",
        },
    ]

    return ValuationProjection(
        year_columns=year_columns,
        revenue_cr=revenues,
        revenue_growth_pct=growths,
        opm_pct=opms,
        op_cr=ops,
        pat_cr=pats,
        pe_multiple=pes,
        market_cap_cr=mcaps,
        share_price=prices,
        shares_cr=shares_list,
        eps=eps_list,
        fair_value_terminal=terminal_px,
        upside_pct=upside,
        implied_cagr_pct=impl_cagr,
        chain_rows=chain,
        target_holding_years=holding_y,
    )


def projection_sheet_df(proj: ValuationProjection) -> pd.DataFrame:
    """NAM-style grid: line items as rows, calendar years as columns."""
    cols = [yc.label for yc in proj.year_columns]

    def _row(label: str, values: list[Any], fmt: str = "num") -> dict[str, Any]:
        row: dict[str, Any] = {"Line item": label}
        for c, v in zip(cols, values):
            if v is None:
                row[c] = "—"
            elif fmt == "pct":
                row[c] = f"{v:.1f}%"
            elif fmt == "pe":
                row[c] = f"{v:.1f}"
            elif fmt == "price":
                row[c] = f"₹{v:,.0f}" if v >= 1000 else f"₹{v:,.2f}"
            else:
                row[c] = f"{v:,.0f}" if isinstance(v, (int, float)) else v
        return row

    rows = [
        _row("Revenue (₹ Cr)", proj.revenue_cr),
        _row("Revenue growth %", proj.revenue_growth_pct, "pct"),
        _row("OPM %", proj.opm_pct, "pct"),
        _row("Operating profit (₹ Cr)", proj.op_cr),
        _row("Net profit (₹ Cr)", proj.pat_cr),
        _row("P/E multiple", proj.pe_multiple, "pe"),
        _row("Market cap (₹ Cr)", proj.market_cap_cr),
        _row("Share price (₹)", proj.share_price, "price"),
        _row("Num of shares (Cr)", proj.shares_cr),
    ]
    return pd.DataFrame(rows)


def shares_reference_df(proj: ValuationProjection) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Year": [yc.label for yc in proj.year_columns],
            "Num of shares (Cr)": [f"{s:.2f}" for s in proj.shares_cr],
        }
    )


def build_buying_price_cagr_table(
    target_price: float,
    holding_years: int,
    *,
    anchor_price: float,
    steps: int = 8,
    discount_pct: float = 30.0,
) -> pd.DataFrame:
    """Rule 9 — Buying price vs expected CAGR (single horizon, like NAM sheet)."""
    if target_price <= 0 or anchor_price <= 0 or holding_years <= 0:
        return pd.DataFrame(columns=["Buying price ₹", f"Exp. CAGR ({holding_years}Y) %"])

    floor = anchor_price * (1.0 - discount_pct / 100.0)
    prices = sorted(
        {round(anchor_price - i * (anchor_price - floor) / max(steps - 1, 1), 0) for i in range(steps)},
        reverse=True,
    )
    rows = []
    for bp in prices:
        c = cagr_pct(bp, target_price, holding_years)
        rows.append(
            {
                "Buying price ₹": f"₹{bp:,.0f}",
                "Buying price (raw)": bp,
                f"Exp. CAGR ({holding_years}Y) %": c if c is not None else "—",
            }
        )
    return pd.DataFrame(rows)


def max_buying_price_for_cagr(target_price: float, holding_years: int, target_cagr_pct: float) -> Optional[float]:
    """Max entry price to achieve target CAGR — IndiaMart / Financially Free sheet style."""
    if target_price <= 0 or holding_years <= 0:
        return None
    return round(target_price / ((1.0 + target_cagr_pct / 100.0) ** holding_years), 0)


def build_target_cagr_buying_table(
    target_price: float,
    holding_years: int,
    *,
    target_cagrs: Optional[list[float]] = None,
) -> pd.DataFrame:
    """Rule 9 (workbook layout) — Expected CAGR % → max buying price."""
    targets = target_cagrs or [12.0, 15.0, 20.0, 25.0, 30.0, 35.0]
    rows = []
    for tc in targets:
        bp = max_buying_price_for_cagr(target_price, holding_years, tc)
        rows.append(
            {
                "Expected CAGR %": f"{tc:.0f}%",
                "Max buying price ₹": f"₹{bp:,.0f}" if bp is not None else "—",
                "_cagr": tc,
            }
        )
    return pd.DataFrame(rows)


def style_target_cagr_table(df: pd.DataFrame) -> Any:
    def _row_style(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        try:
            tc = float(row.get("_cagr", 0))
        except (TypeError, ValueError):
            return styles
        if tc >= 30:
            bg = "#86efac"
        elif tc >= 20:
            bg = "#bbf7d0"
        else:
            bg = "#d9f99d"
        for i, col in enumerate(df.columns):
            if col != "_cagr":
                styles[i] = f"background-color: {bg}"
        return styles

    show = [c for c in df.columns if c != "_cagr"]
    return df[show].style.apply(_row_style, axis=1)


def build_cagr_sensitivity_table(
    entry_price: float,
    target_prices: list[float],
    holding_years: list[int],
) -> pd.DataFrame:
    """Rule 9 — multi-target × multi-horizon matrix (advanced view)."""
    rows = []
    for tgt in target_prices:
        row: dict[str, Any] = {"Target price ₹": round(float(tgt), 2)}
        for n in holding_years:
            c = cagr_pct(entry_price, tgt, n)
            row[f"{n}Y CAGR %"] = c if c is not None else "—"
        rows.append(row)
    return pd.DataFrame(rows)


def build_key_assumptions(
    baseline: ValuationBaseline,
    inputs: ValuationInputs,
    proj: ValuationProjection,
) -> pd.DataFrame:
    book = SECTOR_RULEBOOK.get(baseline.sector_key, SECTOR_RULEBOOK["generic"])
    end_opm = inputs.terminal_opm_pct if inputs.terminal_opm_pct is not None else inputs.opm_pct
    end_pe = inputs.terminal_pe if inputs.terminal_pe is not None else inputs.fair_pe * 0.67
    mult = "P/B" if inputs.pe_is_pb else "P/E"
    terminal_year = proj.year_columns[-1].label if proj.year_columns else "—"
    return pd.DataFrame(
        [
            {
                "Key assumptions": "Revenue growth",
                "Value / estimate": (
                    ", ".join(f"{x:.1f}%" for x in inputs.revenue_growth_path)
                    if inputs.revenue_growth_path
                    else f"{inputs.revenue_growth_pct:.1f}% p.a."
                ),
                "Source / note": "Screener.in 5yr CAGR + management guidance",
            },
            {
                "Key assumptions": "OPM trajectory",
                "Value / estimate": f"{inputs.opm_pct:.1f}% → {end_opm:.1f}%",
                "Source / note": book["opm_benchmark"],
            },
            {
                "Key assumptions": f"{mult} multiple basis",
                "Value / estimate": f"{inputs.fair_pe:.1f} → {end_pe:.1f} (de-rated)",
                "Source / note": book["pe_benchmark"],
            },
            {
                "Key assumptions": "Shares outstanding",
                "Value / estimate": f"{inputs.shares_cr:.2f} Cr",
                "Source / note": "Verify QIP / ESOP dilution before publishing",
            },
            {
                "Key assumptions": "Capex intensity",
                "Value / estimate": f"{inputs.capex_pct_revenue:.1f}% of revenue",
                "Source / note": "Quarterly investor presentation",
            },
            {
                "Key assumptions": "Incremental net debt",
                "Value / estimate": f"₹{inputs.new_debt_cr:,.0f} Cr",
                "Source / note": "Earnings call / balance sheet",
            },
            {
                "Key assumptions": "Target share price",
                "Value / estimate": f"₹{proj.fair_value_terminal:,.2f} ({terminal_year})",
                "Source / note": f"Net profit × {mult} ÷ shares",
            },
            {
                "Key assumptions": "Volume driver (Rule 2)",
                "Value / estimate": "—",
                "Source / note": book["volume_driver"],
            },
        ]
    )


def style_projection_sheet(df: pd.DataFrame, proj: ValuationProjection) -> Any:
    """Yellow = estimate year, orange = projections, blue header row feel."""
    kind_by_col = {yc.label: yc.kind for yc in proj.year_columns}
    year_cols = [c for c in df.columns if c != "Line item"]

    col_styles: dict[str, str] = {}
    for c in year_cols:
        kind = kind_by_col.get(c, "")
        if kind == "estimate":
            col_styles[c] = "background-color: #fff3cd; color: #1a1a1a"
        elif kind == "projection":
            col_styles[c] = "background-color: #ffd8a8; color: #1a1a1a"
        elif kind == "historical":
            col_styles[c] = "background-color: #f8f9fa; color: #1a1a1a"

    def _highlight(row: pd.Series) -> list[str]:
        styles = []
        for col in df.columns:
            if col == "Line item":
                styles.append("font-weight: 600; background-color: #1e3a5f; color: #ffffff")
            else:
                styles.append(col_styles.get(col, ""))
        return styles

    return df.style.apply(_highlight, axis=1)


def style_cagr_buying_table(df: pd.DataFrame, cagr_col: str) -> Any:
    show_cols = [c for c in df.columns if c != "Buying price (raw)"]
    view = df[show_cols]

    def _color_row(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        try:
            c = float(row[cagr_col])
        except (TypeError, ValueError):
            return styles
        if c >= 20:
            bg = "#86efac"
        elif c >= 15:
            bg = "#bbf7d0"
        elif c >= 12:
            bg = "#fef08a"
        else:
            bg = "#fde68a"
        for i, col in enumerate(view.columns):
            if col == cagr_col:
                styles[i] = f"background-color: {bg}; font-weight: 600"
        return styles

    return view.style.apply(_color_row, axis=1)


# Backward-compatible alias
def projection_detail_df(proj: ValuationProjection) -> pd.DataFrame:
    return projection_sheet_df(proj)


@dataclass
class WealthAssessment:
    verdict: str
    verdict_emoji: str
    verdict_color: str
    wealth_score: int
    implied_cagr_pct: float
    upside_pct: float
    revenue_growth_pct: float
    max_buy_15pct: Optional[float]
    max_buy_20pct: Optional[float]
    holding_years: int
    valuation_stance: str
    valuation_stance_color: str
    valuation_detail: str
    margin_of_safety_pct: float
    model_target: float
    strengths: list[str]
    risks: list[str]
    suggestions: list[str]


def _historical_sales_cagr(hist: list[tuple[int, float]]) -> Optional[float]:
    if len(hist) < 2:
        return None
    use = hist[-4:] if len(hist) >= 4 else hist
    y0, r0 = use[0]
    y1, r1 = use[-1]
    if r0 <= 0 or y1 <= y0:
        return None
    return round(((r1 / r0) ** (1.0 / (y1 - y0)) - 1.0) * 100.0, 1)


def _valuation_stance(
    *,
    entry: float,
    target: float,
    upside_pct: float,
    cagr_pct: float,
) -> tuple[str, str, str, float]:
    """How current price compares to the model target — not a universal 'fair value'."""
    mos = round((target - entry) / target * 100.0, 1) if target > 0 else 0.0
    if upside_pct <= -20:
        return (
            "Overvalued vs model",
            "#dc2626",
            f"LTP **₹{entry:,.0f}** is **{abs(upside_pct):.0f}% above** model target **₹{target:,.0f}**. "
            "Wealth creation unlikely without a materially lower entry.",
            mos,
        )
    if upside_pct < -5:
        return (
            "Above model target",
            "#ea580c",
            f"Price is **{abs(upside_pct):.0f}% above** model target — limited upside if assumptions hold.",
            mos,
        )
    if abs(upside_pct) <= 8:
        return (
            "Priced in — no edge",
            "#64748b",
            f"Model target **₹{target:,.0f}** ≈ LTP (±{abs(upside_pct):.0f}%). "
            "The formula always produces a target; here the market **already prices your assumptions**.",
            mos,
        )
    if upside_pct < 20:
        return (
            "Modestly below model",
            "#ca8a04",
            f"**{upside_pct:+.0f}%** to model target — small margin of safety; verify assumptions before sizing up.",
            mos,
        )
    return (
        "Below model target",
        "#16a34a",
        f"**{upside_pct:+.0f}%** upside to model target · implied CAGR **{cagr_pct:.1f}%** — "
        "only attractive if you trust the growth / margin / P/E inputs.",
        mos,
    )


def assess_wealth_creation(
    baseline: ValuationBaseline,
    inputs: ValuationInputs,
    proj: ValuationProjection,
    *,
    entry_price: float,
) -> WealthAssessment:
    """
    Educational wealth-creation read on the forward model — not investment advice.
    Uses Rule 9 math + growth/margin/valuation quality checks.
    """
    holding = int(inputs.cagr_holding_years or proj.target_holding_years or inputs.projection_years)
    target = float(proj.fair_value_terminal)
    entry = float(entry_price or baseline.price or 0.0)
    cagr = float(proj.implied_cagr_pct)
    upside = float(proj.upside_pct)
    rev_g = float(inputs.revenue_growth_pct)
    if inputs.revenue_growth_path:
        rev_g = sum(inputs.revenue_growth_path) / len(inputs.revenue_growth_path)

    max15 = max_buying_price_for_cagr(target, holding, 15.0)
    max20 = max_buying_price_for_cagr(target, holding, 20.0)
    stance, stance_color, stance_detail, mos = _valuation_stance(
        entry=entry, target=target, upside_pct=upside, cagr_pct=cagr
    )

    strengths: list[str] = []
    risks: list[str] = []
    suggestions: list[str] = []
    score = 40

    risks.append(
        "**Model target ≠ fair value.** It is forward PAT × your P/E — optimistic inputs inflate any stock."
    )

    if abs(upside) <= 8:
        risks.append(
            "Target ≈ LTP — the model is **not** saying this is cheap; it mirrors what you already assumed."
        )
        score -= 18
    elif upside < 0:
        score -= 20
    elif upside >= 25:
        score += 12
    elif upside >= 12:
        score += 6

    hist_cagr = _historical_sales_cagr(baseline.historical_revenue)
    if hist_cagr is not None and rev_g > hist_cagr + 5:
        risks.append(
            f"Projected sales growth **{rev_g:.1f}%** vs historical **{hist_cagr:.1f}%** — "
            "target may be **too high** unless guidance supports it."
        )
        score -= 10
    elif hist_cagr is not None and rev_g <= hist_cagr:
        strengths.append(f"Growth assumption **{rev_g:.1f}%** at/below historical **{hist_cagr:.1f}%** — conservative top line.")
        score += 4

    if rev_g >= 18:
        strengths.append(f"Sales compounding **{rev_g:.1f}%** — in multibagger territory if execution holds.")
        score += 12
    elif rev_g >= 12:
        strengths.append(f"Healthy **{rev_g:.1f}%** revenue growth — can build wealth over 5–7 years.")
        score += 8
    elif rev_g >= 8:
        strengths.append(f"Mid-teens growth (**{rev_g:.1f}%**) — wealth via steady compounding, not a 10-bagger.")
        score += 3
    else:
        risks.append(f"Low revenue growth (**{rev_g:.1f}%**) — hard to create outsized wealth without re-rating.")
        score -= 10

    opm = float(inputs.opm_pct)
    if opm >= 25:
        strengths.append(f"Strong **{opm:.0f}% OPM** — high-quality earnings conversion.")
        score += 8
    elif opm < 12:
        risks.append(f"Thin **{opm:.0f}% OPM** — small margin misses hurt PAT badly.")
        score -= 5

    if inputs.terminal_opm_pct and inputs.opm_pct:
        if inputs.terminal_opm_pct > inputs.opm_pct + 8:
            risks.append(
                f"OPM projected to jump **{inputs.opm_pct:.0f}% → {inputs.terminal_opm_pct:.0f}%** — "
                "verify it's realistic, not peak-cycle."
            )
            score -= 6

    if upside >= 25 and cagr >= 18:
        strengths.append(
            f"**{cagr:.1f}%** CAGR and **{upside:+.0f}%** model upside — only if assumptions are credible."
        )
        score += 12
    elif upside >= 10 and cagr >= 15:
        strengths.append(f"**{cagr:.1f}%** implied CAGR with positive model upside.")
        score += 8
    elif upside < 0:
        risks.append(
            f"**Above model target** ({upside:+.0f}%) — not a wealth-creation entry at ₹{entry:,.0f}."
        )
        score -= 8
    elif cagr < 12:
        risks.append(f"**{cagr:.1f}%** implied CAGR — below 12–15% long-term wealth hurdle.")
        score -= 10

    if max15 and entry <= max15:
        strengths.append(f"Current price **below ₹{max15:,.0f}** max entry for **15% CAGR** (Rule 9).")
        score += 8
    elif max15 and entry > max15:
        suggestions.append(
            f"For **15% CAGR** over **{holding}Y**, consider buying below **₹{max15:,.0f}** "
            f"(current ₹{entry:,.0f} is {(entry / max15 - 1) * 100:.0f}% higher)."
        )
        score -= 5

    if max20 and entry <= max20:
        strengths.append(f"Meets **20% CAGR** entry band (max **₹{max20:,.0f}**).")
        score += 5

    if inputs.capex_pct_revenue > 15:
        risks.append(f"High capex (**{inputs.capex_pct_revenue:.0f}%** of sales) — check ROCE in presentation.")
        score -= 5
    if inputs.new_debt_cr > inputs.revenue_cr_y0 * 0.1:
        risks.append(f"Rising debt (**₹{inputs.new_debt_cr:,.0f} Cr**) — dilutes equity wealth if ROCE < cost of debt.")
        score -= 6

    if inputs.terminal_pe and inputs.fair_pe and inputs.terminal_pe > inputs.fair_pe * 1.1:
        risks.append("Terminal P/E **above** starting P/E — you're betting on re-rating, not just earnings.")
        score -= 4

    if baseline.trailing_pe and inputs.fair_pe and baseline.trailing_pe > inputs.fair_pe * 1.25:
        risks.append("Trailing P/E rich vs your model — little margin of safety.")
        score -= 4

    score = max(0, min(100, score))

    if upside >= 20 and cagr >= 16 and score >= 70 and (max15 is None or entry <= max15):
        verdict, verdict_emoji, color = "Strong wealth candidate", "🟢", "#16a34a"
    elif upside >= 8 and cagr >= 12 and score >= 55:
        verdict, verdict_emoji, color = "Good — if assumptions prove out", "🟡", "#ca8a04"
    elif upside < 0 and max15 and entry > max15:
        verdict, verdict_emoji, color = "Not for wealth at this price", "🔴", "#dc2626"
    elif upside < 0 or abs(upside) <= 8:
        verdict, verdict_emoji, color = "No edge — wait for better price", "🟠", "#ea580c"
    elif cagr < 10:
        verdict, verdict_emoji, color = "Weak compounder at this entry", "🔴", "#dc2626"
    else:
        verdict, verdict_emoji, color = "Moderate — verify before allocating", "⚪", "#64748b"

    terminal_lbl = proj.year_columns[-1].label if proj.year_columns else f"{holding}Y"
    suggestions.append(
        f"Base case target **₹{target:,.0f}** ({terminal_lbl}) — only invest if you agree with sales, OPM, and P/E assumptions."
    )
    suggestions.append(
        "Cross-check: Screener.in P&L, concall guidance, peer P/E, and share count (QIP/ESOP) before acting."
    )
    if cagr < 15 and max15:
        suggestions.append(
            f"**Patience:** stagger entries below **₹{max15:,.0f}** or wait for a correction — improves CAGR materially."
        )
    if rev_g >= 15 and opm >= 20:
        suggestions.append(
            "**SIP / tranches** suit high-growth names — avoids betting one price on a volatile compounder."
        )

    return WealthAssessment(
        verdict=verdict,
        verdict_emoji=verdict_emoji,
        verdict_color=color,
        wealth_score=score,
        implied_cagr_pct=cagr,
        upside_pct=upside,
        revenue_growth_pct=rev_g,
        max_buy_15pct=max15,
        max_buy_20pct=max20,
        holding_years=holding,
        valuation_stance=stance,
        valuation_stance_color=stance_color,
        valuation_detail=stance_detail,
        margin_of_safety_pct=mos,
        model_target=target,
        strengths=strengths,
        risks=risks,
        suggestions=suggestions,
    )
