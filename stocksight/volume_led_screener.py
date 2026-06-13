"""
Volume-Led Market Share Capture — fundamental growth screener.

Translates monthly volume / market-share thesis into Yahoo Finance proxies:
  Sales growth 3Y/1Y · Qtr sales/profit YoY · ROCE · D/E · sector overlays.

Educational only — confirm on Screener.in / filings before investing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from .multibagger import (
        INR_PER_CRORE,
        NSE_UNIVERSES,
        SCAN_SOURCES,
        _gf,
        extract_multibagger_fundamentals,
        normalize_debt_equity,
        normalize_growth_pct,
        normalize_return_pct,
        resolve_scan_tickers,
    )
    from .screener import (
        fetch_monthly_history,
        get_pe,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )
except ImportError:
    from multibagger import (
        INR_PER_CRORE,
        NSE_UNIVERSES,
        SCAN_SOURCES,
        _gf,
        extract_multibagger_fundamentals,
        normalize_debt_equity,
        normalize_growth_pct,
        normalize_return_pct,
        resolve_scan_tickers,
    )
    from screener import (
        fetch_monthly_history,
        get_pe,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )

META = {
    "id": "volume_led_growth",
    "title": "Volume-Led Market Share Capture",
    "emoji": "📈",
    "nav_title": "Volume-Led Growth",
    "audience": (
        "Fundamental investors hunting **market-share gainers** before profits fully compound — "
        "sales acceleration + operating leverage across **sector-specific** rules."
    ),
    "purpose": (
        "Base screen (revenue acceleration, profit leverage, ROCE, balance sheet) plus overlays for "
        "**Auto**, **BFSI**, **Capital Goods**, and **FMCG/Retail**. Results grouped sector-wise. "
        "Includes **Monthly RSI momentum** (70 floor, multi-bagger phases)."
    ),
}

MONTHLY_RSI_ENTRY = 70.0
MONTHLY_RSI_CONFIRMED = 73.0
MONTHLY_RSI_CEILING = 94.0

MONTHLY_RSI_PHASES: list[dict[str, str]] = [
    {"range": "Below 70", "return": "Thesis broken — avoid / exit", "phase": "Below momentum floor"},
    {"range": "70 – 73", "return": "Entry / scale-in zone", "phase": "Crossed 70 threshold"},
    {"range": "70 – 85", "return": "Min ~1x (100%)", "phase": "Initial momentum surge"},
    {"range": "85 – 90", "return": "Min ~3x potential", "phase": "Exponential expansion"},
    {"range": "90 – 94", "return": "Up to ~10x potential", "phase": "Peak multi-bagger territory"},
    {"range": "94+", "return": "Near historical RSI ceiling", "phase": "Monitor exhaustion"},
]

RANK_BY_OPTIONS: dict[str, str] = {
    "momentum": "Volume momentum (fundamental rule)",
    "ma200": "vs 200-DMA % (trend strength)",
    "monthly_rsi": "Monthly RSI (highest first)",
    "composite": "StockSight composite",
    "gate": "Gate score",
}

SECTOR_BUCKETS: dict[str, str] = {
    "generic": "Generic (base screen)",
    "auto": "Auto & Auto Ancillaries",
    "bfsi": "Banking & Financial Services (BFSI)",
    "capital_goods": "Capital Goods & Infrastructure",
    "fmcg_retail": "Consumer Staples / FMCG & Retail",
}

SECTOR_RULES_TEXT: dict[str, list[str]] = {
    "generic": [
        "Sales growth 3Y > 15%",
        "Sales growth 1Y > Sales growth 3Y (acceleration)",
        "Qtr sales var YoY > 15%",
        "Profit growth 3Y > 20%",
        "Qtr profit var YoY > Qtr sales var YoY",
        "ROCE > 20%",
        "Debt/equity < 0.5",
        "Market cap > ₹500 Cr",
    ],
    "auto": [
        "Passes base screen",
        "Sales growth 1Y > 18%",
        "Inventory turnover > 10 (demand-led, not channel stuffing)",
    ],
    "bfsi": [
        "Passes base screen",
        "ROA > 1.5%",
        "Price to book < 2.5",
        "Revenue / loan-book growth YoY > 18% (Yahoo revenueGrowth proxy)",
    ],
    "capital_goods": [
        "Passes base screen",
        "Sales growth 3Y > 20%",
        "CFO > net profit (order book converting to cash)",
    ],
    "fmcg_retail": [
        "Passes base screen",
        "Operating margin > 12%",
        "ROE > 18%",
        "Sales growth 3Y > 12% (5Y proxy on Yahoo)",
    ],
}

_AUTO_KW = (
    "auto", "automobile", "motor", "vehicle", "tyre", "tire", "ancillar",
    "two-wheeler", "tractor", "oem", "automotive",
)
_BFSI_KW = (
    "bank", "financial", "insurance", "nbfc", "lending", "finance",
    "asset management", "amc", "broker", "housing finance",
)
_CAPITAL_KW = (
    "capital goods", "industrial", "infrastructure", "engineering",
    "construction", "defence", "defense", "power equipment", "electrical equipment",
    "machinery", "heavy", "epc", "railway",
)
_FMCG_KW = (
    "consumer", "fmcg", "staple", "retail", "food", "beverage", "personal care",
    "household", "grocery", "apparel", "textile",
)


@dataclass
class BaseScreenThresholds:
    min_sales_growth_3y_pct: float = 15.0
    min_qtr_sales_var_pct: float = 15.0
    min_profit_growth_3y_pct: float = 20.0
    min_roce_pct: float = 20.0
    max_debt_equity: float = 0.5
    min_market_cap_cr: float = 500.0
    require_sales_acceleration: bool = True
    require_profit_beats_sales: bool = True


@dataclass
class SectorOverlayThresholds:
    auto_min_sales_1y_pct: float = 18.0
    auto_min_inventory_turnover: float = 10.0
    bfsi_min_roa_pct: float = 1.5
    bfsi_max_price_to_book: float = 2.5
    bfsi_min_advances_growth_pct: float = 18.0
    capital_min_sales_3y_pct: float = 20.0
    fmcg_min_opm_pct: float = 12.0
    fmcg_min_roe_pct: float = 18.0
    fmcg_min_sales_3y_pct: float = 12.0


@dataclass
class VolumeLedFundamentals:
    sales_growth_1y_pct: Optional[float] = None
    sales_growth_3y_pct: Optional[float] = None
    profit_growth_1y_pct: Optional[float] = None
    profit_growth_3y_pct: Optional[float] = None
    qtr_sales_var_pct: Optional[float] = None
    qtr_profit_var_pct: Optional[float] = None
    roce_pct: Optional[float] = None
    roce_is_roe_proxy: bool = False
    debt_equity: Optional[float] = None
    market_cap_cr: Optional[float] = None
    inventory_turnover: Optional[float] = None
    roa_pct: Optional[float] = None
    price_to_book: Optional[float] = None
    opm_pct: Optional[float] = None
    roe_pct: Optional[float] = None
    cfo: Optional[float] = None
    net_profit: Optional[float] = None
    cfo_gt_profit: Optional[bool] = None


@dataclass
class MonthlyRSIFilters:
    require_above_floor: bool = False
    min_monthly_rsi: float = 70.0


@dataclass
class VolumeLedResult:
    ticker: str
    raw_ticker: str
    label: str
    yahoo_sector: str
    sector_bucket: str
    price: float
    pe: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    fundamentals: VolumeLedFundamentals
    base_pass: bool
    sector_pass: bool
    base_hits: int
    base_total: int
    sector_hits: int
    sector_total: int
    momentum_score: float
    pct_vs_ma200: Optional[float] = None
    ma200: Optional[float] = None
    monthly_rsi: Optional[float] = None
    monthly_rsi_prev: Optional[float] = None
    monthly_rsi_peak_24m: Optional[float] = None
    monthly_rsi_phase: str = "—"
    monthly_rsi_band: str = "—"
    monthly_rsi_signal: str = "—"
    monthly_rsi_above_floor: bool = False
    monthly_rsi_crossed_70: bool = False
    monthly_rsi_score: float = 0.0
    pass_notes: list[str] = field(default_factory=list)
    fail_notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)


def _pct_vs_ma200_from_stock(stock: yf.Ticker, price: float) -> tuple[Optional[float], Optional[float]]:
    """Return (% vs 200-DMA, 200-DMA level) from daily history."""
    try:
        hist = stock.history(period="1y", interval="1d", auto_adjust=True)
        if hist is None or len(hist) < 200:
            hist = stock.history(period="2y", interval="1d", auto_adjust=True)
    except Exception:
        return None, None
    if hist is None or hist.empty:
        return None, None
    closes = hist_series(hist, "Close").dropna()
    if len(closes) < 200:
        return None, None
    ma200 = float(closes.rolling(200).mean().iloc[-1])
    if ma200 <= 0:
        return None, None
    vs = pct_vs_ma(float(price), ma200)
    if vs is None or (isinstance(vs, float) and np.isnan(vs)):
        return None, None
    return float(vs), round(ma200, 2)


def classify_monthly_rsi_phase(rsi: Optional[float]) -> tuple[str, str, str]:
    """Return (phase label, expected return band, hold/exit signal)."""
    if rsi is None or (isinstance(rsi, float) and np.isnan(rsi)):
        return "—", "—", "—"
    r = float(rsi)
    if r < MONTHLY_RSI_ENTRY:
        return "Below 70 floor", "Thesis broken / wait", "❌ Below 70 — avoid or exit"
    if r < MONTHLY_RSI_CONFIRMED:
        return "Entry zone (70–73)", "Scale-in on monthly close", "🟡 Crossed 70 — entry watch"
    if r < 85:
        return "Initial surge (70–85)", "Min ~1x (100%)", "🟢 Hold — above 70 floor"
    if r < 90:
        return "Expansion (85–90)", "Min ~3x potential", "🔥 Hold — exponential phase"
    if r < MONTHLY_RSI_CEILING:
        return "Peak MB zone (90–94)", "Up to ~10x potential", "🚀 Multi-bagger territory"
    return "At RSI ceiling (94+)", "Near historical max", "⚠️ Monitor exhaustion"


def _monthly_rsi_score(rsi: Optional[float]) -> float:
    if rsi is None or (isinstance(rsi, float) and np.isnan(rsi)) or float(rsi) < MONTHLY_RSI_ENTRY:
        return 0.0
    r = float(rsi)
    if r >= 90:
        return round(r * 1.5, 2)
    if r >= 85:
        return round(r * 1.2, 2)
    return round(r, 2)


def _rsi_series(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _monthly_rsi_metrics(stock: yf.Ticker, raw: str = "") -> dict:
    """Monthly-chart RSI(14) — current, prior month, 24m peak, phase."""
    empty = {
        "monthly_rsi": None,
        "monthly_rsi_prev": None,
        "monthly_rsi_peak_24m": None,
        "monthly_rsi_phase": "—",
        "monthly_rsi_band": "—",
        "monthly_rsi_signal": "—",
        "monthly_rsi_above_floor": False,
        "monthly_rsi_crossed_70": False,
        "monthly_rsi_score": 0.0,
    }
    sym = raw or getattr(stock, "ticker", "") or ""
    try:
        hist = fetch_monthly_history(sym) if sym else pd.DataFrame()
        if hist is None or hist.empty:
            hist = stock.history(period="10y", interval="1mo", auto_adjust=True)
    except Exception:
        return empty
    if hist is None or hist.empty:
        return empty

    closes = hist_series(hist, "Close").dropna()
    if len(closes) < 16:
        return empty

    rsi_series = _rsi_series(closes).dropna()
    if rsi_series.empty:
        return empty

    cur = round(float(rsi_series.iloc[-1]), 2)
    prev = round(float(rsi_series.iloc[-2]), 2) if len(rsi_series) >= 2 else None
    peak_tail = rsi_series.tail(24).dropna()
    peak = round(float(peak_tail.max()), 2) if not peak_tail.empty else None

    phase, band, signal = classify_monthly_rsi_phase(cur)
    crossed = prev is not None and prev < MONTHLY_RSI_ENTRY and cur >= MONTHLY_RSI_ENTRY
    return {
        "monthly_rsi": cur,
        "monthly_rsi_prev": prev,
        "monthly_rsi_peak_24m": peak,
        "monthly_rsi_phase": phase,
        "monthly_rsi_band": band,
        "monthly_rsi_signal": signal,
        "monthly_rsi_above_floor": cur >= MONTHLY_RSI_ENTRY,
        "monthly_rsi_crossed_70": crossed,
        "monthly_rsi_score": _monthly_rsi_score(cur),
    }


def classify_sector_bucket(sector: str, industry: str = "") -> str:
    """Map Yahoo sector/industry to one of our sector buckets."""
    blob = f"{sector or ''} {industry or ''}".lower()
    if any(k in blob for k in _AUTO_KW):
        return "auto"
    if any(k in blob for k in _BFSI_KW):
        return "bfsi"
    if any(k in blob for k in _CAPITAL_KW):
        return "capital_goods"
    if any(k in blob for k in _FMCG_KW):
        return "fmcg_retail"
    return "generic"


def extract_volume_led_fundamentals(info: dict) -> VolumeLedFundamentals:
    base = extract_multibagger_fundamentals(info)

    sales_1y = normalize_growth_pct(
        _gf(info, ("revenueGrowth", "revenue_growth"))
    )
    sales_3y = normalize_growth_pct(
        _gf(info, ("threeYearRevenueGrowthRate",))
    )
    profit_1y = normalize_growth_pct(
        _gf(info, ("earningsGrowth", "earnings_growth"))
    )
    profit_3y = normalize_growth_pct(
        _gf(info, ("threeYearEarningsGrowthRate",))
    )

    roa = normalize_return_pct(_gf(info, ("returnOnAssets", "return_on_assets")))
    pb = _gf(info, ("priceToBook", "price_to_book"))
    inv_turn = _gf(info, ("inventoryTurnover",))

    opex = _gf(info, ("operatingMargins", "operatingMargin"))
    if opex is not None and abs(opex) <= 1.0:
        opex = round(opex * 100.0, 2)

    roe = normalize_return_pct(_gf(info, ("returnOnEquity",)))

    cfo = _gf(info, ("operatingCashflow", "totalCashFromOperatingActivities"))
    net_profit = _gf(info, ("netIncomeToCommon", "netIncome"))
    cfo_gt: Optional[bool] = None
    if cfo is not None and net_profit is not None and net_profit > 0:
        cfo_gt = cfo > net_profit

    return VolumeLedFundamentals(
        sales_growth_1y_pct=sales_1y,
        sales_growth_3y_pct=sales_3y,
        profit_growth_1y_pct=profit_1y,
        profit_growth_3y_pct=profit_3y,
        qtr_sales_var_pct=base.get("qtr_sales_var_pct"),
        qtr_profit_var_pct=base.get("qtr_profit_var_pct"),
        roce_pct=base.get("roce_pct"),
        roce_is_roe_proxy=bool(base.get("roce_is_roe_proxy")),
        debt_equity=base.get("debt_equity"),
        market_cap_cr=base.get("market_cap_cr"),
        inventory_turnover=inv_turn,
        roa_pct=roa,
        price_to_book=pb,
        opm_pct=opex,
        roe_pct=roe,
        cfo=cfo,
        net_profit=net_profit,
        cfo_gt_profit=cfo_gt,
    )


def _check(
    ok: bool,
    label: str,
    *,
    hits: list[str],
    fails: list[str],
    optional: bool = False,
) -> bool:
    if ok:
        hits.append(label)
        return True
    if not optional:
        fails.append(label)
    return False


def evaluate_base_screen(
    fund: VolumeLedFundamentals,
    thr: BaseScreenThresholds,
) -> tuple[bool, int, int, list[str], list[str]]:
    hits: list[str] = []
    fails: list[str] = []
    checks: list[bool] = []

    s3 = fund.sales_growth_3y_pct
    s1 = fund.sales_growth_1y_pct
    qs = fund.qtr_sales_var_pct
    p3 = fund.profit_growth_3y_pct
    qp = fund.qtr_profit_var_pct
    roce = fund.roce_pct
    de = fund.debt_equity
    mcap = fund.market_cap_cr

    if s3 is not None:
        checks.append(_check(s3 > thr.min_sales_growth_3y_pct, f"Sales 3Y {s3:.1f}% > {thr.min_sales_growth_3y_pct:.0f}%", hits=hits, fails=fails))
    else:
        fails.append("Sales growth 3Y — missing")

    if thr.require_sales_acceleration and s1 is not None and s3 is not None:
        checks.append(_check(s1 > s3, f"Sales 1Y {s1:.1f}% > 3Y {s3:.1f}%", hits=hits, fails=fails))
    elif thr.require_sales_acceleration:
        fails.append("Sales acceleration — missing")

    if qs is not None:
        checks.append(_check(qs > thr.min_qtr_sales_var_pct, f"Qtr sales {qs:.1f}% > {thr.min_qtr_sales_var_pct:.0f}%", hits=hits, fails=fails))
    else:
        fails.append("Qtr sales var — missing")

    if p3 is not None:
        checks.append(_check(p3 > thr.min_profit_growth_3y_pct, f"Profit 3Y {p3:.1f}% > {thr.min_profit_growth_3y_pct:.0f}%", hits=hits, fails=fails))
    else:
        fails.append("Profit growth 3Y — missing")

    if thr.require_profit_beats_sales and qp is not None and qs is not None:
        checks.append(_check(qp > qs, f"Qtr profit {qp:.1f}% > qtr sales {qs:.1f}%", hits=hits, fails=fails))
    elif thr.require_profit_beats_sales:
        fails.append("Profit beats sales — missing")

    if roce is not None:
        checks.append(_check(roce > thr.min_roce_pct, f"ROCE {roce:.1f}% > {thr.min_roce_pct:.0f}%", hits=hits, fails=fails))
    else:
        fails.append("ROCE — missing")

    if de is not None:
        checks.append(_check(de < thr.max_debt_equity, f"D/E {de:.2f} < {thr.max_debt_equity:.1f}", hits=hits, fails=fails))
    else:
        hits.append("D/E — not reported (skipped)")

    if mcap is not None:
        checks.append(_check(mcap > thr.min_market_cap_cr, f"Mcap ₹{mcap:,.0f} Cr > {thr.min_market_cap_cr:.0f}", hits=hits, fails=fails))
    else:
        fails.append("Market cap — missing")

    total = 8
    passed = all(checks) if checks else False
    return passed, len(hits), total, hits, fails


def evaluate_sector_overlay(
    bucket: str,
    fund: VolumeLedFundamentals,
    thr: SectorOverlayThresholds,
    *,
    base_passed: bool,
) -> tuple[bool, int, int, list[str], list[str]]:
    if bucket == "generic":
        return base_passed, 0, 0, [], []

    hits: list[str] = []
    fails: list[str] = []
    checks: list[bool] = []

    if not base_passed:
        fails.append("Base screen not passed")
        return False, 0, 3, hits, fails

    if bucket == "auto":
        s1 = fund.sales_growth_1y_pct
        if s1 is not None:
            checks.append(_check(s1 > thr.auto_min_sales_1y_pct, f"Sales 1Y {s1:.1f}% > {thr.auto_min_sales_1y_pct:.0f}%", hits=hits, fails=fails))
        else:
            fails.append("Sales 1Y — missing")
        inv = fund.inventory_turnover
        if inv is not None:
            checks.append(_check(inv > thr.auto_min_inventory_turnover, f"Inv turnover {inv:.1f} > {thr.auto_min_inventory_turnover:.0f}", hits=hits, fails=fails))
        else:
            hits.append("Inv turnover — Yahoo omits (skipped)")

    elif bucket == "bfsi":
        roa = fund.roa_pct
        if roa is not None:
            checks.append(_check(roa > thr.bfsi_min_roa_pct, f"ROA {roa:.2f}% > {thr.bfsi_min_roa_pct:.1f}%", hits=hits, fails=fails))
        else:
            fails.append("ROA — missing")
        pb = fund.price_to_book
        if pb is not None:
            checks.append(_check(pb < thr.bfsi_max_price_to_book, f"P/B {pb:.2f} < {thr.bfsi_max_price_to_book:.1f}", hits=hits, fails=fails))
        else:
            fails.append("P/B — missing")
        adv = fund.sales_growth_1y_pct
        if adv is not None:
            checks.append(
                _check(
                    adv > thr.bfsi_min_advances_growth_pct,
                    f"Revenue growth {adv:.1f}% > {thr.bfsi_min_advances_growth_pct:.0f}% (loan-book proxy)",
                    hits=hits,
                    fails=fails,
                )
            )
        else:
            fails.append("Advances/revenue growth — missing")

    elif bucket == "capital_goods":
        s3 = fund.sales_growth_3y_pct
        if s3 is not None:
            checks.append(_check(s3 > thr.capital_min_sales_3y_pct, f"Sales 3Y {s3:.1f}% > {thr.capital_min_sales_3y_pct:.0f}%", hits=hits, fails=fails))
        else:
            fails.append("Sales 3Y — missing")
        if fund.cfo_gt_profit is not None:
            checks.append(_check(fund.cfo_gt_profit, "CFO > net profit", hits=hits, fails=fails))
        else:
            fails.append("CFO vs profit — missing")

    elif bucket == "fmcg_retail":
        opm = fund.opm_pct
        if opm is not None:
            checks.append(_check(opm > thr.fmcg_min_opm_pct, f"OPM {opm:.1f}% > {thr.fmcg_min_opm_pct:.0f}%", hits=hits, fails=fails))
        else:
            fails.append("OPM — missing")
        roe = fund.roe_pct
        if roe is not None:
            checks.append(_check(roe > thr.fmcg_min_roe_pct, f"ROE {roe:.1f}% > {thr.fmcg_min_roe_pct:.0f}%", hits=hits, fails=fails))
        else:
            fails.append("ROE — missing")
        s3 = fund.sales_growth_3y_pct
        if s3 is not None:
            checks.append(_check(s3 > thr.fmcg_min_sales_3y_pct, f"Sales 3Y {s3:.1f}% > {thr.fmcg_min_sales_3y_pct:.0f}%", hits=hits, fails=fails))
        else:
            fails.append("Sales 3Y — missing")

    total = max(len(checks), 1)
    passed = all(checks) if checks else False
    return passed, len(hits), total, hits, fails


def _momentum_score(fund: VolumeLedFundamentals) -> float:
    s1 = float(fund.sales_growth_1y_pct or 0.0)
    s3 = float(fund.sales_growth_3y_pct or 0.0)
    qs = float(fund.qtr_sales_var_pct or 0.0)
    qp = float(fund.qtr_profit_var_pct or 0.0)
    roce = float(fund.roce_pct or 0.0)
    accel = max(0.0, s1 - s3) if s1 and s3 else 0.0
    leverage = max(0.0, qp - qs) if qp and qs else 0.0
    return round((s1 * 0.25 + qs * 0.2 + qp * 0.25 + accel * 0.15 + leverage * 0.1 + roce * 0.05), 1)


def scan_volume_led(
    scan_source: str,
    *,
    base_thr: BaseScreenThresholds | None = None,
    sector_thr: SectorOverlayThresholds | None = None,
    monthly_rsi_thr: MonthlyRSIFilters | None = None,
    sector_filter: str = "all",
    require_sector_overlay: bool = False,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    info_delay_sec: float = 0.10,
) -> list[VolumeLedResult]:
    """Scan universe; return stocks passing base (+ optional sector overlay)."""
    b_thr = base_thr or BaseScreenThresholds()
    s_thr = sector_thr or SectorOverlayThresholds()
    m_thr = monthly_rsi_thr or MonthlyRSIFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[VolumeLedResult] = []
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

            fund = extract_volume_led_fundamentals(info)
            base_pass, base_hits, base_total, pass_notes, fail_notes = evaluate_base_screen(fund, b_thr)

            sector, industry = get_sector_industry(stock)
            bucket = classify_sector_bucket(sector, industry)

            if sector_filter != "all" and bucket != sector_filter:
                continue

            sector_pass, sec_hits, sec_total, sec_pass_notes, sec_fail_notes = evaluate_sector_overlay(
                bucket, fund, s_thr, base_passed=base_pass,
            )

            include = base_pass
            if require_sector_overlay and bucket != "generic":
                include = base_pass and sector_pass
            elif sector_filter != "all" and bucket != "generic":
                include = base_pass and sector_pass

            if not include:
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
            pct_ma200, ma200_px = _pct_vs_ma200_from_stock(stock, float(price))
            m_rsi = _monthly_rsi_metrics(stock, raw)
            if m_thr.require_above_floor:
                rsi_v = m_rsi.get("monthly_rsi")
                if rsi_v is None or float(rsi_v) < float(m_thr.min_monthly_rsi):
                    continue
            disp = raw.replace(".NS", "").replace(".BO", "")
            base_fund = extract_multibagger_fundamentals(info)

            results.append(
                VolumeLedResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    yahoo_sector=sector or "—",
                    sector_bucket=bucket,
                    price=round(float(price), 2),
                    pe=round(float(pe), 2) if pe is not None else None,
                    market_cap_cr=fund.market_cap_cr,
                    market_cap_display=base_fund.get("market_cap_display") or "",
                    fundamentals=fund,
                    base_pass=base_pass,
                    sector_pass=sector_pass,
                    base_hits=base_hits,
                    base_total=base_total,
                    sector_hits=sec_hits,
                    sector_total=sec_total,
                    momentum_score=_momentum_score(fund),
                    pct_vs_ma200=pct_ma200,
                    ma200=ma200_px,
                    monthly_rsi=m_rsi.get("monthly_rsi"),
                    monthly_rsi_prev=m_rsi.get("monthly_rsi_prev"),
                    monthly_rsi_peak_24m=m_rsi.get("monthly_rsi_peak_24m"),
                    monthly_rsi_phase=str(m_rsi.get("monthly_rsi_phase") or "—"),
                    monthly_rsi_band=str(m_rsi.get("monthly_rsi_band") or "—"),
                    monthly_rsi_signal=str(m_rsi.get("monthly_rsi_signal") or "—"),
                    monthly_rsi_above_floor=bool(m_rsi.get("monthly_rsi_above_floor")),
                    monthly_rsi_crossed_70=bool(m_rsi.get("monthly_rsi_crossed_70")),
                    monthly_rsi_score=float(m_rsi.get("monthly_rsi_score") or 0.0),
                    pass_notes=pass_notes + sec_pass_notes,
                    fail_notes=fail_notes + sec_fail_notes,
                    links=get_stock_links(raw),
                )
            )
        except Exception:
            continue

        if info_delay_sec > 0:
            time.sleep(info_delay_sec)

    return sort_volume_led_results(results, rank_by="momentum")


def _rank_sort_key(rank_by: str) -> Callable[[VolumeLedResult], float]:
    if rank_by == "ma200":
        return lambda r: float(r.pct_vs_ma200) if r.pct_vs_ma200 is not None else -9999.0
    if rank_by == "monthly_rsi":
        return lambda r: float(r.monthly_rsi_score or r.monthly_rsi or -9999.0)
    return lambda r: float(r.momentum_score or 0.0)


def sort_volume_led_results(
    results: list[VolumeLedResult],
    *,
    rank_by: str = "momentum",
) -> list[VolumeLedResult]:
    """Sort scan hits — momentum, 200-DMA %, or monthly RSI."""
    if rank_by not in ("momentum", "ma200", "monthly_rsi"):
        return list(results)
    key_fn = _rank_sort_key(rank_by)
    return sorted(results, key=key_fn, reverse=True)


def sort_results_dataframe(df: pd.DataFrame, rank_by: str) -> pd.DataFrame:
    """Sort enriched table by StockSight composite or Gate score."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if rank_by == "composite" and "Composite" in out.columns:
        out = out.sort_values("Composite", ascending=False, kind="stable")
    elif rank_by == "gate" and "Gate score" in out.columns:
        out = out.sort_values("Gate score", ascending=False, kind="stable")
    out["S.No."] = range(1, len(out) + 1)
    return out.reset_index(drop=True)


def group_results_by_sector(
    results: list[VolumeLedResult],
    *,
    rank_by: str = "momentum",
) -> dict[str, list[VolumeLedResult]]:
    grouped: dict[str, list[VolumeLedResult]] = {k: [] for k in SECTOR_BUCKETS}
    for r in results:
        grouped.setdefault(r.sector_bucket, []).append(r)
    for bucket in grouped:
        grouped[bucket] = sort_volume_led_results(grouped[bucket], rank_by=rank_by)
    return grouped


def result_to_row(r: VolumeLedResult, rank: int) -> dict:
    f = r.fundamentals
    roce_lbl = f"{f.roce_pct:.1f}" + ("*" if f.roce_is_roe_proxy else "") if f.roce_pct is not None else "—"
    sector_lbl = SECTOR_BUCKETS.get(r.sector_bucket, r.sector_bucket)
    overlay = "✅" if r.sector_pass or r.sector_bucket == "generic" else "—"
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Sector bucket": sector_lbl,
        "Yahoo sector": r.yahoo_sector,
        "Momentum": r.momentum_score,
        "Monthly RSI": r.monthly_rsi,
        "RSI prev": r.monthly_rsi_prev,
        "RSI 24m peak": r.monthly_rsi_peak_24m,
        "RSI phase": r.monthly_rsi_phase,
        "RSI target band": r.monthly_rsi_band,
        "RSI signal": r.monthly_rsi_signal,
        "Above 70 floor": "✅" if r.monthly_rsi_above_floor else "—",
        "Crossed 70": "🆕" if r.monthly_rsi_crossed_70 else "—",
        "vs 200-DMA %": r.pct_vs_ma200,
        "200 DMA": r.ma200,
        "Base pass": "✅" if r.base_pass else "—",
        "Sector pass": overlay,
        "Price": r.price,
        "PE": r.pe,
        "Mar Cap": r.market_cap_display or (f"₹{r.market_cap_cr:,.0f} Cr" if r.market_cap_cr else "—"),
        "Sales 1Y %": f.sales_growth_1y_pct,
        "Sales 3Y %": f.sales_growth_3y_pct,
        "Qtr sales %": f.qtr_sales_var_pct,
        "Profit 3Y %": f.profit_growth_3y_pct,
        "Qtr profit %": f.qtr_profit_var_pct,
        "ROCE %": roce_lbl,
        "D/E": f.debt_equity,
        "ROA %": f.roa_pct,
        "P/B": f.price_to_book,
        "OPM %": f.opm_pct,
        "ROE %": f.roe_pct,
        "Inv turnover": f.inventory_turnover,
        "CFO > profit": "✅" if f.cfo_gt_profit else ("—" if f.cfo_gt_profit is None else "❌"),
        "Pass notes": "; ".join(r.pass_notes[:4]),
        **(r.links or {}),
    }
