"""
Multibagger theme screener — fundamental growth + quality gates (NSE via Yahoo Finance).

Yahoo `info` fields used where available:
  Qtr Sales Var %  → revenueQuarterlyGrowth / revenueGrowth
  Qtr Profit Var % → earningsQuarterlyGrowth / earningsGrowth
  ROCE %           → returnOnCapitalEmployed or ROE proxy
  Mar Cap Rs.Cr.   → marketCap
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

NSE_UNIVERSES = [k for k in UNIVERSES if "NSE" in k]

SCAN_SOURCES = ["Curated (ROCE export names)"] + NSE_UNIVERSES

# Curated high-ROCE names (verify symbols on NSE).
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

# Default: ROCE-led screen (like export); growth uses Yahoo quarterly YoY proxies.
DEFAULT_FILTERS = {
    "min_qtr_sales_var_pct": 0.0,
    "min_qtr_profit_var_pct": 0.0,
    "max_debt_equity": 0.5,
    "max_market_cap_cr": 5000.0,
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


def extract_multibagger_fundamentals(info: dict) -> dict[str, Optional[float]]:
    """Fundamental fields for multibagger filters (best-effort from Yahoo `info`)."""
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
    mcap_cr = market_cap_inr_to_cr(_gf(info, ("marketCap", "market_cap")))

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
        "market_cap_cr": mcap_cr,
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


def resolve_scan_tickers(scan_source: str) -> list[tuple[str, str]]:
    """Return list of (display_label, raw_ticker)."""
    if scan_source == "Curated (ROCE export names)":
        out: list[tuple[str, str]] = []
        for row in CURATED_MULTIBAGGER:
            t = str(row.get("ticker") or "").strip()
            if t:
                out.append((str(row.get("label") or t), t))
        return out

    tickers = UNIVERSES.get(scan_source, [])
    return [(t.replace(".NS", ""), t) for t in tickers]


def _passes_filters(fund: dict[str, Optional[float]], flt: MultibaggerFilters) -> bool:
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
        mcap = fund.get("market_cap_cr")
        if mcap is None or mcap >= flt.max_market_cap_cr:
            return False

    return True


def _fit_score(fund: dict[str, Optional[float]], flt: MultibaggerFilters) -> float:
    sales = float(fund.get("qtr_sales_var_pct") or 0.0)
    profit = float(fund.get("qtr_profit_var_pct") or 0.0)
    roce = float(fund.get("roce_pct") or 0.0)
    de = float(fund.get("debt_equity") or flt.max_debt_equity)
    mcap = float(fund.get("market_cap_cr") or flt.max_market_cap_cr)

    sales_s = min(sales / max(flt.min_qtr_sales_var_pct, 1.0), 3.0)
    prof_s = min(profit / max(flt.min_qtr_profit_var_pct, 1.0), 3.0)
    roce_s = min(roce / max(flt.min_roce_pct, 1.0), 3.0)
    de_s = max(0.0, (flt.max_debt_equity - de) / max(flt.max_debt_equity, 0.01)) if flt.apply_de_filter else 0.5
    cap_s = max(0.0, (flt.max_market_cap_cr - mcap) / max(flt.max_market_cap_cr, 1.0)) if flt.apply_mcap_filter else 0.5

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
            mcap_cr = fund.get("market_cap_cr")
            if mcap_cr is not None and mcap_cr < flt.min_market_cap_cr:
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
                )
            )
        except Exception:
            continue

        if info_delay_sec > 0 and scan_source != "Curated (ROCE export names)":
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
            )
            results.append(row)
        except Exception:
            continue

        if info_delay_sec > 0 and scan_source != "Curated (ROCE export names)":
            time.sleep(info_delay_sec)

    return sorted(results, key=lambda x: (x.roce_pct or 0.0), reverse=True)
