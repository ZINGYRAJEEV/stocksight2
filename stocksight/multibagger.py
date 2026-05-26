"""
Multibagger theme screener — fundamental growth + quality gates.

Supports both NSE (.NS / .BO) and US (NYSE / NASDAQ) tickers via Yahoo Finance.
Market-cap thresholds are interpreted in the right unit for each universe:
  * NSE → ₹ Crore
  * US  → USD Billion

Yahoo `info` fields used where available:
  Qtr Sales Var %  → revenueQuarterlyGrowth / revenueGrowth
  Qtr Profit Var % → earningsQuarterlyGrowth / earningsGrowth
  ROCE %           → returnOnCapitalEmployed or ROE proxy
  Mar Cap          → marketCap (in native currency)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import yfinance as yf

try:
    from .screener import (
        UNIVERSES,
        compute_rsi,
        get_pe,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )
except ImportError:
    from screener import (
        UNIVERSES,
        compute_rsi,
        get_pe,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )

INR_PER_CRORE = 10_000_000.0
USD_PER_BILLION = 1_000_000_000.0

NSE_UNIVERSES = [k for k in UNIVERSES if "NSE" in k]
US_UNIVERSES = [k for k in UNIVERSES if any(x in k for x in ("NYSE", "NASDAQ", "S&P", "Dow"))]

CURATED_NSE_LABEL = "Curated NSE (ROCE export names)"
CURATED_US_LABEL = "Curated US (mega/large-cap)"

# Curated high-ROCE NSE names (verify symbols on NSE).
CURATED_MULTIBAGGER: list[dict[str, str]] = [
    {"label": "Tips Music", "ticker": "TIPSMUSIC.NS"},
    {"label": "Gravity India", "ticker": "GRAVITA.NS"},
    {"label": "ICICI AMC", "ticker": "ICICIAMC.NS"},
    {"label": "Nestle India", "ticker": "NESTLEIND.NS"},
    {"label": "MCX", "ticker": "MCX.NS"},
    {"label": "Esab India", "ticker": "ESABINDIA.NS"},
    {"label": "Hindustan Zinc", "ticker": "HINDZINC.NS"},
    {"label": "Ingersoll-Rand", "ticker": "INGERRAND.NS"},
    {"label": "BSE", "ticker": "BSE.NS"},
    {"label": "Anand Rathi Wealth", "ticker": "ANANDRATHI.NS"},
    {"label": "Tenneco Clean", "ticker": "TENNIND.NS"},
    {"label": "Vivid Electromech", "ticker": "VIVIDHA.NS"},
    {"label": "NINtec Systems", "ticker": "NINSYS.NS"},
    {"label": "Influx Health", "ticker": "INFLUX.NS"},
    {"label": "Mobilise App", "ticker": "MOBILISE.NS"},
    {"label": "Hitachi Energy India", "ticker": "POWERINDIA.NS"},
    {"label": "Siemens", "ticker": "SIEMENS.NS"},
]

# Curated US mega/large-cap names with strong long-run compounding (verify symbols).
CURATED_MULTIBAGGER_US: list[dict[str, str]] = [
    {"label": "Nvidia",               "ticker": "NVDA"},
    {"label": "Apple",                "ticker": "AAPL"},
    {"label": "Microsoft",            "ticker": "MSFT"},
    {"label": "Amazon",               "ticker": "AMZN"},
    {"label": "Alphabet (Google)",    "ticker": "GOOGL"},
    {"label": "Meta Platforms",       "ticker": "META"},
    {"label": "Tesla",                "ticker": "TSLA"},
    {"label": "Broadcom",             "ticker": "AVGO"},
    {"label": "AMD",                  "ticker": "AMD"},
    {"label": "Netflix",              "ticker": "NFLX"},
    {"label": "Costco",               "ticker": "COST"},
    {"label": "ASML",                 "ticker": "ASML"},
    {"label": "Adobe",                "ticker": "ADBE"},
    {"label": "Visa",                 "ticker": "V"},
    {"label": "Mastercard",           "ticker": "MA"},
    {"label": "Eli Lilly",            "ticker": "LLY"},
    {"label": "JPMorgan Chase",       "ticker": "JPM"},
    {"label": "ServiceNow",           "ticker": "NOW"},
    {"label": "Palantir",             "ticker": "PLTR"},
    {"label": "Berkshire Hathaway B", "ticker": "BRK-B"},
]

SCAN_SOURCES = (
    [CURATED_NSE_LABEL]
    + NSE_UNIVERSES
    + [CURATED_US_LABEL]
    + US_UNIVERSES
)

# Back-compat alias for any older session_state that stored the old curated key.
LEGACY_CURATED_KEY = "Curated (ROCE export names)"


def is_us_source(scan_source: str) -> bool:
    """True when scan_source represents a US universe / curated US list."""
    if not scan_source:
        return False
    if scan_source == CURATED_US_LABEL:
        return True
    return scan_source in US_UNIVERSES


def is_nse_source(scan_source: str) -> bool:
    """True when scan_source represents an NSE/BSE universe / curated NSE list."""
    if not scan_source:
        return True
    if scan_source in (CURATED_NSE_LABEL, LEGACY_CURATED_KEY):
        return True
    return scan_source in NSE_UNIVERSES


# Default: ROCE-led screen (like export); growth uses Yahoo quarterly YoY proxies.
DEFAULT_FILTERS = {
    "min_qtr_sales_var_pct": 0.0,
    "min_qtr_profit_var_pct": 0.0,
    "max_debt_equity": 0.5,
    "max_market_cap_cr": 5000.0,
    "max_market_cap_usd_bn": 100.0,
    "min_roce_pct": 15.0,
    "apply_mcap_filter": False,
    "apply_de_filter": False,
}


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


def normalize_growth_pct(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    if abs(v) <= 1.0:
        return round(v * 100.0, 2)
    return round(v, 2)


def normalize_debt_equity(v: Optional[float]) -> Optional[float]:
    """
    Debt/equity is often a ratio (e.g. 0.39). Yahoo NSE often reports D/E as percent (39 → 0.39).
    Values already < 1.5 are kept as ratio.
    """
    if v is None:
        return None
    if v > 1.0:
        v = v / 100.0
    return round(v, 3)


def normalize_return_pct(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    if abs(v) <= 1.0:
        return round(v * 100.0, 2)
    return round(v, 2)


def market_cap_inr_to_cr(mcap_inr: Optional[float]) -> Optional[float]:
    if mcap_inr is None or mcap_inr <= 0:
        return None
    return round(float(mcap_inr) / INR_PER_CRORE, 2)


def market_cap_usd_to_bn(mcap_usd: Optional[float]) -> Optional[float]:
    if mcap_usd is None or mcap_usd <= 0:
        return None
    return round(float(mcap_usd) / USD_PER_BILLION, 3)


def _norm_currency(raw: Optional[str]) -> str:
    """Normalise Yahoo currency string (e.g. 'INR', 'USD', 'usd', 'GBp')."""
    s = str(raw or "").strip().upper()
    if not s:
        return ""
    # Yahoo sometimes returns "GBp" (pence) or "ZAc" → strip lowercase 'p'/'c'
    if s.endswith(("P", "C")) and len(s) == 3 and s[:2].isalpha():
        return s[:2]
    return s


def format_market_cap(mcap_native: Optional[float], currency: str) -> str:
    """Human-friendly Mar Cap string for display (e.g. '₹5,200 Cr', '$1.2 T')."""
    if mcap_native is None or mcap_native <= 0:
        return ""
    cur = _norm_currency(currency)
    if cur == "INR":
        cr = float(mcap_native) / INR_PER_CRORE
        if cr >= 100_000:
            return f"₹{cr / 100_000:.2f} L Cr"
        if cr >= 1_000:
            return f"₹{cr:,.0f} Cr"
        return f"₹{cr:,.1f} Cr"
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "HKD": "HK$", "JPY": "¥"}.get(cur, cur + " ")
    v = float(mcap_native)
    av = abs(v)
    if av >= 1e12:
        return f"{sym}{v/1e12:.2f} T"
    if av >= 1e9:
        return f"{sym}{v/1e9:.2f} B"
    if av >= 1e6:
        return f"{sym}{v/1e6:.2f} M"
    return f"{sym}{v:,.0f}"


def extract_multibagger_fundamentals(info: dict) -> dict:
    """Fundamental fields for multibagger filters (best-effort from Yahoo `info`).

    Currency-aware: returns market cap in both INR-crore and USD-bn so callers can
    apply the right threshold for NSE vs US universes.
    """
    qtr_sales = normalize_growth_pct(
        _gf(
            info,
            (
                "revenueQuarterlyGrowth",
                "quarterlyRevenueGrowth",
                "revenueGrowth",
                "threeYearRevenueGrowthRate",
            ),
        )
    )
    qtr_profit = normalize_growth_pct(
        _gf(
            info,
            (
                "earningsQuarterlyGrowth",
                "quarterlyEarningsGrowth",
                "earningsGrowth",
                "threeYearEarningsGrowthRate",
            ),
        )
    )

    de = normalize_debt_equity(_gf(info, ("debtToEquity", "totalDebtToEquity")))

    currency = _norm_currency(info.get("currency") or info.get("financialCurrency"))
    mcap_raw = _gf(info, ("marketCap", "market_cap"))
    mcap_cr: Optional[float] = None
    mcap_usd_bn: Optional[float] = None
    if mcap_raw is not None and mcap_raw > 0:
        if currency == "INR":
            mcap_cr = market_cap_inr_to_cr(mcap_raw)
        else:
            # Default to USD when currency isn't given (most US tickers report).
            mcap_usd_bn = market_cap_usd_to_bn(mcap_raw)

    roce = normalize_return_pct(
        _gf(
            info,
            (
                "returnOnCapitalEmployed",
                "returnOnCapital",
                "return_on_capital_employed",
            ),
        )
    )
    roe = normalize_return_pct(_gf(info, ("returnOnEquity", "return_on_equity")))
    roce_used = roce if roce is not None else roe

    div_yld = _gf(info, ("dividendYield", "trailingAnnualDividendYield"))
    if div_yld is not None:
        if abs(div_yld) <= 1.0:
            div_yld = round(div_yld * 100.0, 2)
        elif div_yld > 20.0:
            div_yld = None

    wk_high = _gf(info, ("fiftyTwoWeekHigh", "52WeekHigh"))

    return {
        "qtr_sales_var_pct": qtr_sales,
        "qtr_profit_var_pct": qtr_profit,
        "revenue_growth_pct": qtr_sales,
        "profit_growth_pct": qtr_profit,
        "debt_equity": de,
        "currency": currency or "USD",
        "market_cap_native": mcap_raw,
        "market_cap_cr": mcap_cr,
        "market_cap_usd_bn": mcap_usd_bn,
        "market_cap_display": format_market_cap(mcap_raw, currency or "USD"),
        "roce_pct": roce_used,
        "roce_is_roe_proxy": roce is None and roe is not None,
        "div_yield_pct": div_yld,
        "week52_high": wk_high,
    }


@dataclass
class MultibaggerFilters:
    min_qtr_sales_var_pct: float = 0.0
    min_qtr_profit_var_pct: float = 0.0
    max_debt_equity: float = 0.5
    max_market_cap_cr: float = 5000.0
    max_market_cap_usd_bn: float = 100.0
    min_roce_pct: float = 15.0
    apply_mcap_filter: bool = False
    apply_de_filter: bool = False


@dataclass
class MultibaggerResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    price: float
    pe: Optional[float]
    market_cap_cr: Optional[float]
    div_yield_pct: Optional[float]
    qtr_sales_var_pct: Optional[float]
    qtr_profit_var_pct: Optional[float]
    debt_equity: Optional[float]
    roce_pct: Optional[float]
    week52_high: Optional[float]
    roce_is_roe_proxy: bool = False
    fit_score: float = 0.0
    links: dict = field(default_factory=dict)
    currency: str = "INR"
    market_cap_native: Optional[float] = None
    market_cap_usd_bn: Optional[float] = None
    market_cap_display: str = ""


def resolve_scan_tickers(scan_source: str) -> list[tuple[str, str]]:
    """Return list of (display_label, raw_ticker)."""
    if scan_source in (CURATED_NSE_LABEL, LEGACY_CURATED_KEY):
        out: list[tuple[str, str]] = []
        for row in CURATED_MULTIBAGGER:
            t = str(row.get("ticker") or "").strip()
            if t:
                out.append((str(row.get("label") or t), t))
        return out
    if scan_source == CURATED_US_LABEL:
        out_us: list[tuple[str, str]] = []
        for row in CURATED_MULTIBAGGER_US:
            t = str(row.get("ticker") or "").strip()
            if t:
                out_us.append((str(row.get("label") or t), t))
        return out_us

    tickers = UNIVERSES.get(scan_source, [])
    out_uni: list[tuple[str, str]] = []
    for t in tickers:
        disp = t.replace(".NS", "").replace(".BO", "")
        out_uni.append((disp, t))
    return out_uni


def _passes_filters(fund: dict, flt: MultibaggerFilters) -> bool:
    if flt.min_qtr_sales_var_pct > 0:
        sales = fund.get("qtr_sales_var_pct")
        if sales is None or sales < flt.min_qtr_sales_var_pct:
            return False

    if flt.min_qtr_profit_var_pct > 0:
        profit = fund.get("qtr_profit_var_pct")
        if profit is None or profit < flt.min_qtr_profit_var_pct:
            return False

    roce = fund.get("roce_pct")
    if roce is None or roce < flt.min_roce_pct:
        return False

    if flt.apply_de_filter:
        de = fund.get("debt_equity")
        if de is not None and de >= flt.max_debt_equity:
            return False

    if flt.apply_mcap_filter:
        currency = _norm_currency(fund.get("currency"))
        if currency == "INR":
            mcap = fund.get("market_cap_cr")
            if mcap is None or mcap >= flt.max_market_cap_cr:
                return False
        else:
            mcap_bn = fund.get("market_cap_usd_bn")
            if mcap_bn is None or mcap_bn >= flt.max_market_cap_usd_bn:
                return False

    return True


def _fit_score(fund: dict, flt: MultibaggerFilters) -> float:
    sales = float(fund.get("qtr_sales_var_pct") or 0.0)
    profit = float(fund.get("qtr_profit_var_pct") or 0.0)
    roce = float(fund.get("roce_pct") or 0.0)
    de = float(fund.get("debt_equity") or flt.max_debt_equity)

    currency = _norm_currency(fund.get("currency"))
    if currency == "INR":
        mcap = float(fund.get("market_cap_cr") or flt.max_market_cap_cr)
        cap_threshold = flt.max_market_cap_cr
    else:
        mcap = float(fund.get("market_cap_usd_bn") or flt.max_market_cap_usd_bn)
        cap_threshold = flt.max_market_cap_usd_bn

    sales_s = min(sales / max(flt.min_qtr_sales_var_pct, 1.0), 3.0)
    prof_s = min(profit / max(flt.min_qtr_profit_var_pct, 1.0), 3.0)
    roce_s = min(roce / max(flt.min_roce_pct, 1.0), 3.0)
    de_s = max(0.0, (flt.max_debt_equity - de) / max(flt.max_debt_equity, 0.01)) if flt.apply_de_filter else 0.5
    cap_s = max(0.0, (cap_threshold - mcap) / max(cap_threshold, 1.0)) if flt.apply_mcap_filter else 0.5

    return round((sales_s + prof_s + roce_s * 1.2 + de_s + cap_s) * 16.0, 1)


@dataclass
class ProvenMultibaggerFilters:
    """Filters for stocks that already became multibaggers and are still healthy."""

    min_past_return_pct: float = 500.0
    lookback_years: int = 5
    max_drawdown_from_52w_high_pct: float = 25.0
    rsi_min: float = 45.0
    rsi_max: float = 75.0
    require_above_ma200: bool = True
    min_market_cap_cr: float = 500.0
    min_market_cap_usd_bn: float = 1.0


@dataclass
class ProvenMultibaggerResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    price: float
    pe: Optional[float]
    market_cap_cr: Optional[float]
    past_return_pct: float
    lookback_years: int
    drawdown_from_52w_high_pct: Optional[float]
    pct_vs_ma200: Optional[float]
    rsi: Optional[float]
    roce_pct: Optional[float]
    qtr_profit_var_pct: Optional[float]
    week52_high: Optional[float]
    fit_score: float = 0.0
    links: dict = field(default_factory=dict)
    currency: str = "INR"
    market_cap_native: Optional[float] = None
    market_cap_usd_bn: Optional[float] = None
    market_cap_display: str = ""


def _long_term_return_pct(stock: "yf.Ticker", years: int = 5) -> tuple[Optional[float], int]:
    """Total return % over `years` using Yahoo daily history.

    Returns (return_pct, actual_years_used). Falls back to max history if shorter.
    """
    try:
        period = f"{max(int(years), 1)}y"
        hist = stock.history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            hist = stock.history(period="max", interval="1d", auto_adjust=True)
    except Exception:
        return None, 0
    if hist is None or hist.empty:
        return None, 0

    closes = hist_series(hist, "Close").dropna()
    if closes.empty or len(closes) < 30:
        return None, 0

    start_px = float(closes.iloc[0])
    end_px = float(closes.iloc[-1])
    if start_px <= 0:
        return None, 0
    span_days = (closes.index[-1] - closes.index[0]).days
    actual_years = max(1, round(span_days / 365.0))
    return round((end_px / start_px - 1.0) * 100.0, 1), actual_years


def _proven_fit_score(
    past_return: float,
    pct_vs_ma200: Optional[float],
    rsi: Optional[float],
    drawdown: Optional[float],
    roce: Optional[float],
) -> float:
    """0–100 score: rewards big past return + healthy current trend."""
    ret_s = min(past_return / 1000.0, 1.5)
    ma_s = 0.5
    if pct_vs_ma200 is not None:
        ma_s = max(0.0, min(1.5, (pct_vs_ma200 + 10.0) / 40.0))
    rsi_s = 0.5
    if rsi is not None:
        ideal = 60.0
        rsi_s = max(0.0, 1.0 - abs(rsi - ideal) / 25.0)
    dd_s = 0.5
    if drawdown is not None:
        dd_s = max(0.0, 1.0 - drawdown / 30.0)
    roce_s = min((roce or 0.0) / 25.0, 1.0)
    return round((ret_s * 1.4 + ma_s + rsi_s + dd_s + roce_s) * 18.0, 1)


def scan_proven_multibaggers(
    scan_source: str,
    filters: ProvenMultibaggerFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    *,
    info_delay_sec: float = 0.10,
) -> list[ProvenMultibaggerResult]:
    """Find stocks that already returned ≥ `min_past_return_pct`% and are still healthy.

    "Healthy" today = above 200-DMA, RSI in band, not deeply off 52-week high.
    Educational only — past returns ≠ future returns.
    """
    flt = filters or ProvenMultibaggerFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[ProvenMultibaggerResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)

        try:
            stock = yf.Ticker(raw)
            try:
                info = stock.info or {}
            except Exception:
                info = {}
            if not info.get("symbol") and not info.get("shortName"):
                continue

            past_return, years_used = _long_term_return_pct(stock, flt.lookback_years)
            if past_return is None or past_return < flt.min_past_return_pct:
                continue

            try:
                hist = stock.history(period="1y", interval="1d", auto_adjust=True)
            except Exception:
                hist = None
            if hist is None or hist.empty:
                continue
            closes = hist_series(hist, "Close").dropna()
            if closes.empty:
                continue
            price = float(closes.iloc[-1])

            wk_high = float(closes.tail(252).max()) if len(closes) >= 5 else None
            drawdown = None
            if wk_high and wk_high > 0:
                drawdown = round((1.0 - price / wk_high) * 100.0, 1)
                if drawdown > flt.max_drawdown_from_52w_high_pct:
                    continue

            pct_ma200: Optional[float] = None
            if len(closes) >= 200:
                ma200 = float(closes.rolling(200).mean().iloc[-1])
                if ma200 > 0:
                    pct_ma200 = pct_vs_ma(price, ma200)
            if flt.require_above_ma200:
                if pct_ma200 is None or pct_ma200 < 0:
                    continue

            rsi_val: Optional[float] = None
            try:
                r = compute_rsi(closes)
                if r is not None and not np.isnan(r):
                    rsi_val = float(r)
            except Exception:
                rsi_val = None
            if rsi_val is not None and (rsi_val < flt.rsi_min or rsi_val > flt.rsi_max):
                continue

            fund = extract_multibagger_fundamentals(info)
            currency = _norm_currency(fund.get("currency"))
            mcap_cr = fund.get("market_cap_cr")
            mcap_usd_bn = fund.get("market_cap_usd_bn")
            if currency == "INR":
                if mcap_cr is not None and mcap_cr < flt.min_market_cap_cr:
                    continue
            else:
                if mcap_usd_bn is not None and mcap_usd_bn < flt.min_market_cap_usd_bn:
                    continue

            pe = get_pe(stock)
            sector, _ = get_sector_industry(stock)
            disp = raw.replace(".NS", "").replace(".BO", "")

            results.append(
                ProvenMultibaggerResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    sector=sector or "—",
                    price=round(price, 2),
                    pe=round(float(pe), 2) if pe is not None else None,
                    market_cap_cr=mcap_cr,
                    past_return_pct=past_return,
                    lookback_years=years_used,
                    drawdown_from_52w_high_pct=drawdown,
                    pct_vs_ma200=pct_ma200,
                    rsi=round(rsi_val, 1) if rsi_val is not None else None,
                    roce_pct=fund.get("roce_pct"),
                    qtr_profit_var_pct=fund.get("qtr_profit_var_pct"),
                    week52_high=fund.get("week52_high") or wk_high,
                    fit_score=_proven_fit_score(past_return, pct_ma200, rsi_val, drawdown, fund.get("roce_pct")),
                    links=get_stock_links(raw),
                    currency=currency or "INR",
                    market_cap_native=fund.get("market_cap_native"),
                    market_cap_usd_bn=mcap_usd_bn,
                    market_cap_display=fund.get("market_cap_display", ""),
                )
            )
        except Exception:
            continue

        if info_delay_sec > 0 and scan_source not in (CURATED_NSE_LABEL, CURATED_US_LABEL, LEGACY_CURATED_KEY):
            time.sleep(info_delay_sec)

    return sorted(results, key=lambda x: x.past_return_pct, reverse=True)


def scan_multibagger(
    scan_source: str,
    filters: MultibaggerFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    *,
    info_delay_sec: float = 0.12,
) -> list[MultibaggerResult]:
    """Scan universe with multibagger fundamental gates."""
    if filters is None:
        filters = MultibaggerFilters(
            min_qtr_sales_var_pct=DEFAULT_FILTERS["min_qtr_sales_var_pct"],
            min_qtr_profit_var_pct=DEFAULT_FILTERS["min_qtr_profit_var_pct"],
            max_debt_equity=DEFAULT_FILTERS["max_debt_equity"],
            max_market_cap_cr=DEFAULT_FILTERS["max_market_cap_cr"],
            min_roce_pct=DEFAULT_FILTERS["min_roce_pct"],
            apply_mcap_filter=DEFAULT_FILTERS["apply_mcap_filter"],
            apply_de_filter=DEFAULT_FILTERS["apply_de_filter"],
        )

    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[MultibaggerResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)

        try:
            stock = yf.Ticker(raw)
            try:
                info = stock.info or {}
            except Exception:
                info = {}

            if not info.get("symbol") and not info.get("shortName"):
                continue

            fund = extract_multibagger_fundamentals(info)
            if not _passes_filters(fund, filters):
                continue

            price = _gf(info, ("regularMarketPrice", "currentPrice", "previousClose"))
            if price is None:
                try:
                    h = stock.history(period="5d")
                    closes = hist_series(h, "Close")
                    if not closes.empty:
                        price = float(closes.iloc[-1])
                except Exception:
                    price = None
            if price is None:
                continue

            pe = get_pe(stock)
            sector, _ = get_sector_industry(stock)
            disp = raw.replace(".NS", "").replace(".BO", "")

            row = MultibaggerResult(
                ticker=disp,
                raw_ticker=raw,
                label=label if label != disp else disp,
                sector=sector or "—",
                price=round(float(price), 2),
                pe=round(float(pe), 2) if pe is not None else None,
                market_cap_cr=fund.get("market_cap_cr"),
                div_yield_pct=fund.get("div_yield_pct"),
                qtr_sales_var_pct=fund.get("qtr_sales_var_pct"),
                qtr_profit_var_pct=fund.get("qtr_profit_var_pct"),
                debt_equity=fund.get("debt_equity"),
                roce_pct=fund.get("roce_pct"),
                week52_high=fund.get("week52_high"),
                roce_is_roe_proxy=bool(fund.get("roce_is_roe_proxy")),
                fit_score=_fit_score(fund, filters),
                links=get_stock_links(raw),
                currency=_norm_currency(fund.get("currency")) or "INR",
                market_cap_native=fund.get("market_cap_native"),
                market_cap_usd_bn=fund.get("market_cap_usd_bn"),
                market_cap_display=fund.get("market_cap_display", ""),
            )
            results.append(row)
        except Exception:
            continue

        if info_delay_sec > 0 and scan_source not in (CURATED_NSE_LABEL, CURATED_US_LABEL, LEGACY_CURATED_KEY):
            time.sleep(info_delay_sec)

    return sorted(results, key=lambda x: (x.roce_pct or 0.0), reverse=True)
