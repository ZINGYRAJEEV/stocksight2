"""
Peter Lynch framework screener — six categories, PEG / PEGY (GARP), fundamentals.

Educational implementation using Yahoo Finance proxies. Classification is heuristic —
verify on Screener.in / annual reports before investing.
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
    UNIVERSES,
    drawdown_pct_from_52w_high,
    get_pe,
    get_sector_industry,
    get_stock_links,
    hist_series,
)

ProgressCb = Callable[[int, int, str], None]

META = {
    "id": "peter_lynch",
    "title": "Peter Lynch Screener",
    "emoji": "🦉",
    "nav_title": "Peter Lynch",
    "audience": (
        "Fundamental investors using **Lynch's six stock categories**, **PEG / PEGY (GARP)**, "
        "and balance-sheet checks before the **two-minute drill**."
    ),
    "purpose": (
        "Classifies names into Slow Grower · Stalwart · Fast Grower · Cyclical · Turnaround · Asset Play; "
        "flags PEG ≤ 1 and PEGY. **Auto / Breeze** uses ICICI for NSE/BSE prices when connected; "
        "fundamentals still from Yahoo — cross-check on Screener.in."
    ),
}

DATA_SOURCE_OPTIONS = ("auto", "breeze", "yahoo")
DATA_SOURCE_LABELS = {
    "auto": "Auto — ICICI Breeze (NSE/BSE) if connected, else Yahoo",
    "breeze": "ICICI Breeze only — NSE/BSE prices (fundamentals: Yahoo)",
    "yahoo": "Yahoo Finance only",
}

LYNCH_CATEGORIES = (
    "Slow Grower",
    "Stalwart",
    "Fast Grower",
    "Cyclical",
    "Turnaround",
    "Asset Play",
)

CATEGORY_META = {
    "Slow Grower": {"growth": "2–6%", "note": "Large mature; dividends; low risk unless business fails."},
    "Stalwart": {"growth": "8–12%", "note": "Blue-chips; 30–50% upside target; portfolio ballast."},
    "Fast Grower": {"growth": "15–25%+", "note": "Tenbagger hunting; watch PEG to avoid overpaying."},
    "Cyclical": {"growth": "Variable", "note": "Buy downturns; avoid peak-earnings traps."},
    "Turnaround": {"growth": "Variable", "note": "High risk/reward; needs restructuring proof."},
    "Asset Play": {"growth": "N/A", "note": "Hidden assets (cash, RE, patents) below market price."},
}

CYCLICAL_KEYWORDS = (
    "steel", "aluminum", "airline", "auto", "automobile", "chemical", "mining",
    "oil", "gas", "petroleum", "shipping", "marine", "construction", "lumber",
    "paper", "hotel", "lodging", "bank", "insurance", "reit", "real estate",
    "semiconductor equipment", "homebuilding", "railroad", "copper", "cement",
)

PEG_FAIR = 1.0
PEG_EXPENSIVE = 2.0


@dataclass
class LynchFilters:
    universe: str = "Nifty 50 (NSE)"
    categories: tuple[str, ...] = LYNCH_CATEGORIES
    max_peg: float = 2.0
    max_pegy: float = 1.5
    max_debt_equity: float = 1.5
    min_lynch_score: float = 45.0
    require_garp: bool = False  # PEG or PEGY <= 1
    max_tickers: int = 80
    info_delay_sec: float = 0.15
    data_source: str = "auto"  # auto | breeze | yahoo


@dataclass
class LynchResult:
    ticker: str
    raw_ticker: str
    sector: str
    price: float
    lynch_category: str
    category_rationale: str
    pe: Optional[float]
    eps_growth_pct: Optional[float]
    div_yield_pct: Optional[float]
    peg: Optional[float]
    pegy: Optional[float]
    peg_verdict: str
    debt_equity: Optional[float]
    inventory_note: str
    market_cap_display: str
    lynch_score: float
    garp_fit: str
    two_minute_prompt: str
    action: str
    price_source: str = "yahoo"
    fundamentals_source: str = "yahoo"
    links: dict = field(default_factory=dict)


@dataclass
class LynchScanStats:
    universe: str
    data_source: str = "auto"
    tickers_scanned: int = 0
    tickers_matched: int = 0
    no_data: int = 0
    breeze_price_count: int = 0
    yahoo_price_count: int = 0
    scan_elapsed_sec: float = 0.0


def _is_nse_bse(raw: str) -> bool:
    u = (raw or "").upper()
    return u.endswith(".NS") or u.endswith(".BO")


def _breeze_available() -> bool:
    try:
        from breeze_data import breeze_configured

        return bool(breeze_configured())
    except Exception:
        return False


def _fetch_yahoo_history(raw: str, period: str = "1y") -> pd.DataFrame:
    try:
        hist = yf.Ticker(raw).history(period=period, interval="1d", auto_adjust=True)
        if hist is not None and not hist.empty:
            return hist
    except Exception:
        pass
    return pd.DataFrame()


def _fetch_breeze_history(raw: str) -> pd.DataFrame:
    try:
        from breeze_data import fetch_breeze_price_history

        bdf = fetch_breeze_price_history(raw, "1d")
        if bdf is not None and not bdf.empty:
            return bdf
    except Exception:
        pass
    return pd.DataFrame()


def _fetch_lynch_price_data(
    raw: str,
    data_source: str,
) -> tuple[Optional[pd.DataFrame], Optional[float], str]:
    """
    OHLCV + optional live LTP for Lynch scoring.

    Returns (history_df, ltp_override, price_source_tag).
    """
    ds = (data_source or "auto").lower()
    if ds not in DATA_SOURCE_OPTIONS:
        ds = "auto"

    if ds != "yahoo" and _is_nse_bse(raw) and _breeze_available():
        bdf = _fetch_breeze_history(raw)
        if not bdf.empty:
            ltp = None
            try:
                from breeze_data import get_ltp

                ltp = get_ltp(raw)
            except Exception:
                pass
            return bdf, ltp, "breeze"
        if ds == "breeze":
            return None, None, "breeze"

    if ds == "breeze":
        return None, None, "breeze"

    ydf = _fetch_yahoo_history(raw)
    if ydf.empty:
        return None, None, "yahoo"
    return ydf, None, "yahoo"


def _week52_high(hist: pd.DataFrame, raw: str, data_source: str) -> Optional[float]:
    """52-week high — supplement with Yahoo when Breeze history is short."""
    highs: list[float] = []
    if hist is not None and not hist.empty and "High" in hist.columns:
        highs.append(float(hist["High"].max()))
    ds = (data_source or "auto").lower()
    if ds in ("auto", "breeze") and _is_nse_bse(raw) and (hist is None or len(hist) < 200):
        ydf = _fetch_yahoo_history(raw, "1y")
        if not ydf.empty and "High" in ydf.columns:
            highs.append(float(ydf["High"].max()))
    return max(highs) if highs else None


def _hybrid_pe(price: float, stock, info: dict) -> Optional[float]:
    """P/E from live Breeze price ÷ Yahoo EPS when possible."""
    eps = _gf(info, ("trailingEps", "epsTrailingTwelveMonths", "trailingEPS"))
    if eps is not None and eps > 0 and price > 0:
        return round(price / eps, 2)
    pe = get_pe(stock)
    return round(float(pe), 2) if pe is not None else None


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


def _growth_pct(info: dict, fund: dict) -> Optional[float]:
    g = fund.get("profit_growth_pct") or fund.get("qtr_profit_var_pct")
    if g is not None:
        return float(g)
    g = fund.get("revenue_growth_pct") or fund.get("qtr_sales_var_pct")
    if g is not None:
        return float(g)
    raw = _gf(
        info,
        (
            "earningsGrowth",
            "earningsQuarterlyGrowth",
            "revenueGrowth",
            "revenueQuarterlyGrowth",
        ),
    )
    if raw is not None and abs(raw) <= 1.0:
        raw *= 100.0
    return round(raw, 1) if raw is not None else None


def compute_peg(pe: Optional[float], growth_pct: Optional[float]) -> Optional[float]:
    if pe is None or pe <= 0 or growth_pct is None or growth_pct <= 0:
        return None
    return round(pe / growth_pct, 2)


def compute_pegy(
    pe: Optional[float],
    growth_pct: Optional[float],
    div_yield_pct: Optional[float],
) -> Optional[float]:
    if pe is None or pe <= 0 or growth_pct is None:
        return None
    dy = float(div_yield_pct or 0)
    denom = growth_pct + dy
    if denom <= 0:
        return None
    return round(pe / denom, 2)


def peg_verdict(peg: Optional[float]) -> str:
    if peg is None:
        return "—"
    if peg < PEG_FAIR:
        return "Undervalued (<1)"
    if peg <= PEG_EXPENSIVE:
        return "Fair (1–2)"
    return "Expensive (>2)"


def _is_large_cap(fund: dict, currency: str) -> bool:
    if currency == "INR":
        mcap = fund.get("market_cap_cr")
        return mcap is not None and mcap >= 20_000
    mcap = fund.get("market_cap_usd_bn")
    return mcap is not None and mcap >= 50


def _is_cyclical(sector: str, industry: str) -> bool:
    blob = f"{sector} {industry}".lower()
    return any(k in blob for k in CYCLICAL_KEYWORDS)


def classify_lynch_category(
    *,
    growth_pct: Optional[float],
    div_yield_pct: Optional[float],
    pb: Optional[float],
    pe: Optional[float],
    sector: str,
    industry: str,
    fund: dict,
    drawdown_52w: Optional[float],
    profit_margin_pct: Optional[float],
    debt_equity: Optional[float],
) -> tuple[str, str]:
    g = growth_pct if growth_pct is not None else 0.0
    dy = div_yield_pct or 0.0
    currency = fund.get("currency") or "USD"
    large = _is_large_cap(fund, currency)

    if pb is not None and pb > 0 and pb < 1.2 and g < 12:
        return "Asset Play", f"P/B {pb:.2f} — possible hidden book value / assets"

    if drawdown_52w is not None and drawdown_52w >= 35 and g > 10:
        return "Turnaround", f"Deep drawdown ({drawdown_52w:.0f}%) with improving growth narrative"

    if (profit_margin_pct is not None and profit_margin_pct < 0) or (pe is not None and pe < 0):
        if g > 15:
            return "Turnaround", "Loss-making or negative P/E with strong growth rebound signal"
        return "Turnaround", "Distressed fundamentals — verify restructuring plan"

    if _is_cyclical(sector, industry):
        return "Cyclical", f"Cyclical sector ({sector or industry}) — time the cycle"

    if g >= 15:
        return "Fast Grower", f"EPS/revenue growth ~{g:.0f}% — tenbagger candidate; monitor PEG"

    if large and 8 <= g < 15:
        return "Stalwart", f"Large cap, ~{g:.0f}% growth — 30–50% upside potential"

    if dy >= 2.0 and g <= 8:
        return "Slow Grower", f"Dividend {dy:.1f}%, modest growth — income compounder"

    if large and g < 8:
        return "Stalwart", f"Mature large cap (~{g:.0f}% growth) — stability"

    if g >= 8:
        return "Stalwart", f"Moderate growth ~{g:.0f}%"

    if dy >= 1.5:
        return "Slow Grower", f"Yield-led ({dy:.1f}%) with low growth"

    return "Slow Grower", "Low growth profile — dividend / stability focus"


def inventory_trend_note(raw_ticker: str) -> str:
    try:
        bs = yf.Ticker(raw_ticker).balance_sheet
        if bs is None or bs.empty:
            return "—"
        inv_key = next((k for k in bs.index if str(k).lower() == "inventory"), None)
        if not inv_key:
            return "—"
        inv = bs.loc[inv_key].dropna()
        if len(inv) < 2:
            return "—"
        latest, prior = float(inv.iloc[0]), float(inv.iloc[1])
        if prior <= 0:
            return "—"
        chg = (latest / prior - 1.0) * 100.0
        if chg > 25:
            return f"Inventory +{chg:.0f}% ⚠"
        if chg < -10:
            return f"Inventory {chg:.0f}% ✓"
        return "Inventory stable"
    except Exception:
        return "—"


def lynch_score(
    *,
    peg: Optional[float],
    pegy: Optional[float],
    category: str,
    debt_equity: Optional[float],
    inventory_note: str,
    growth_pct: Optional[float],
) -> float:
    score = 0.0
    peg_use = pegy if category == "Slow Grower" and pegy is not None else peg
    if peg_use is not None:
        if peg_use < 1.0:
            score += 40
        elif peg_use < 1.5:
            score += 28
        elif peg_use < 2.0:
            score += 15
        else:
            score += 5
    else:
        score += 10

    if debt_equity is not None:
        if debt_equity < 0.5:
            score += 20
        elif debt_equity < 1.0:
            score += 12
        elif debt_equity < 1.5:
            score += 5

    if category == "Fast Grower" and growth_pct and growth_pct >= 20:
        score += 15
    elif category in ("Stalwart", "Slow Grower"):
        score += 12
    elif category == "Asset Play":
        score += 10
    else:
        score += 8

    if "✓" in inventory_note:
        score += 10
    elif "⚠" in inventory_note:
        score -= 5

    return round(min(100.0, max(0.0, score)), 1)


def garp_fit_label(peg: Optional[float], pegy: Optional[float], category: str) -> str:
    if category == "Slow Grower" and pegy is not None:
        if pegy < 1.0:
            return "GARP ✓ (PEGY<1)"
        if pegy < 1.5:
            return "PEGY fair"
        return "PEGY rich"
    if peg is not None:
        if peg < 1.0:
            return "GARP ✓ (PEG<1)"
        if peg < 2.0:
            return "PEG fair"
        return "PEG expensive"
    return "—"


def two_minute_prompt(stock: str, category: str, growth: Optional[float], peg: Optional[float]) -> str:
    g = f"{growth:.0f}%" if growth is not None else "?"
    p = f"{peg:.2f}" if peg is not None else "?"
    return (
        f"Why will {stock} succeed as a {category}? "
        f"Growth ~{g}, PEG {p}. What must happen for the stock to rise? Key risks?"
    )


def action_hint(category: str, peg: Optional[float], peg_verdict_str: str) -> str:
    if category == "Fast Grower" and peg is not None and peg < 1.0:
        return "Research tenbagger thesis — GARP entry"
    if category == "Cyclical":
        return "Map cycle phase — buy trough, not peak earnings"
    if category == "Turnaround":
        return "Verify debt fix + insider confidence before sizing"
    if category == "Asset Play":
        return "Identify catalyst unlocking hidden NAV"
    if peg_verdict_str.startswith("Undervalued"):
        return "GARP candidate — run two-minute drill"
    if category == "Slow Grower":
        return "Income + PEGY check — patience compounder"
    return "Watchlist — confirm category & fundamentals"


def analyze_ticker_lynch(raw: str, flt: LynchFilters) -> Optional[LynchResult]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        stock = yf.Ticker(raw)
        info = stock.info or {}
        if not info.get("symbol") and not info.get("shortName"):
            return None
        fund = extract_multibagger_fundamentals(info)

        hist, ltp, price_src = _fetch_lynch_price_data(raw, flt.data_source)
        if hist is None or hist.empty:
            return None
        closes = hist_series(hist, "Close").dropna()
        if closes.empty:
            return None
        price = float(ltp) if ltp is not None and ltp > 0 else float(closes.iloc[-1])

        pe = _hybrid_pe(price, stock, info) if price_src == "breeze" else get_pe(stock)
        if pe is not None:
            pe = round(float(pe), 2)

        growth = _growth_pct(info, fund)
        div_y = fund.get("div_yield_pct")
        peg = compute_peg(pe, growth)
        pegy = compute_pegy(pe, growth, div_y)
        pb = _gf(info, ("priceToBook", "price_to_book"))
        pm = _gf(info, ("profitMargins", "profit_margin"))
        if pm is not None and abs(pm) <= 1.0:
            pm *= 100.0
        de = normalize_debt_equity(fund.get("debt_equity"))
        wk_high = _week52_high(hist, raw, flt.data_source) or fund.get("week52_high")
        dd = drawdown_pct_from_52w_high(price, wk_high)
        sector, industry = get_sector_industry(stock)

        cat, rationale = classify_lynch_category(
            growth_pct=growth,
            div_yield_pct=div_y,
            pb=pb,
            pe=pe,
            sector=sector or "",
            industry=industry or "",
            fund=fund,
            drawdown_52w=dd,
            profit_margin_pct=pm,
            debt_equity=de,
        )

        if cat not in flt.categories:
            return None

        if flt.require_garp:
            ok = (peg is not None and peg <= 1.0) or (pegy is not None and pegy <= 1.0)
            if not ok:
                return None

        if peg is not None and peg > flt.max_peg and cat != "Slow Grower":
            return None
        if pegy is not None and pegy > flt.max_pegy and cat == "Slow Grower":
            return None
        if de is not None and de > flt.max_debt_equity:
            return None

        inv_note = inventory_trend_note(raw)
        pv = peg_verdict(peg)
        score = lynch_score(
            peg=peg,
            pegy=pegy,
            category=cat,
            debt_equity=de,
            inventory_note=inv_note,
            growth_pct=growth,
        )
        if score < flt.min_lynch_score:
            return None

        disp = raw.replace(".NS", "").replace(".BO", "")
        return LynchResult(
            ticker=disp,
            raw_ticker=raw,
            sector=sector or "—",
            price=round(price, 2),
            lynch_category=cat,
            category_rationale=rationale,
            pe=pe,
            eps_growth_pct=growth,
            div_yield_pct=div_y,
            peg=peg,
            pegy=pegy,
            peg_verdict=pv,
            debt_equity=de,
            inventory_note=inv_note,
            market_cap_display=fund.get("market_cap_display", "—"),
            lynch_score=score,
            garp_fit=garp_fit_label(peg, pegy, cat),
            two_minute_prompt=two_minute_prompt(disp, cat, growth, peg),
            action=action_hint(cat, peg, pv),
            price_source=price_src,
            fundamentals_source="yahoo",
            links=get_stock_links(raw),
        )
    except Exception:
        return None


def scan_peter_lynch(
    flt: LynchFilters,
    *,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[LynchResult], LynchScanStats]:
    t0 = time.time()
    tickers = list(UNIVERSES.get(flt.universe, []))[: flt.max_tickers]
    stats = LynchScanStats(universe=flt.universe, data_source=flt.data_source)
    results: list[LynchResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        r = analyze_ticker_lynch(raw, flt)
        if r is None:
            stats.no_data += 1
            continue
        results.append(r)
        stats.tickers_matched += 1
        if r.price_source == "breeze":
            stats.breeze_price_count += 1
        else:
            stats.yahoo_price_count += 1
        if flt.info_delay_sec > 0:
            time.sleep(flt.info_delay_sec)

    results.sort(key=lambda x: (-x.lynch_score, x.peg or 99))
    stats.scan_elapsed_sec = time.time() - t0
    return results, stats


def universe_options() -> list[str]:
    return list(UNIVERSES.keys())
