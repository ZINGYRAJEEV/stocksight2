"""
Popular stock screens — catalog of classic filters with Yahoo Finance implementations.

Not every filter can be replicated exactly on Yahoo (FII flows, 10Y avg earnings,
Piotroski full score, quarterly streaks need filings). Each screen notes data fidelity.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from .multibagger import (
        INR_PER_CRORE,
        extract_multibagger_fundamentals,
        market_cap_inr_to_cr,
        normalize_debt_equity,
        normalize_growth_pct,
        normalize_return_pct,
    )
    from .screener import (
        UNIVERSES,
        compute_rsi,
        compute_volume_ratio,
        fetch_price_history,
        get_pe,
        get_stock_links,
        get_sector_industry,
        hist_series,
        ma_cross_recent,
    )
except ImportError:
    from multibagger import (
        INR_PER_CRORE,
        extract_multibagger_fundamentals,
        market_cap_inr_to_cr,
        normalize_debt_equity,
        normalize_growth_pct,
        normalize_return_pct,
    )
    from screener import (
        UNIVERSES,
        compute_rsi,
        compute_volume_ratio,
        fetch_price_history,
        get_pe,
        get_stock_links,
        get_sector_industry,
        hist_series,
        ma_cross_recent,
    )

NSE_UNIVERSES = [k for k in UNIVERSES if "NSE" in k]
SCAN_SOURCES = NSE_UNIVERSES


@dataclass
class ScreenMeta:
    screen_id: str
    title: str
    description: str
    category: str
    icon: str = "📋"
    implemented: bool = True
    fidelity: str = "Yahoo Finance proxy — confirm figures on Yahoo"


@dataclass
class PopularScreenResult:
    ticker: str
    raw_ticker: str
    price: float
    pe: Optional[float] = None
    market_cap_cr: Optional[float] = None
    rsi: Optional[float] = None
    vol_ratio: Optional[float] = None
    roce_pct: Optional[float] = None
    div_yield_pct: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    score: float = 0.0
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    links: dict = field(default_factory=dict)


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


def _fundamentals(info: dict) -> dict[str, Optional[float]]:
    f = extract_multibagger_fundamentals(info)
    roe = normalize_return_pct(_gf(info, ("returnOnEquity",)))
    opex = _gf(info, ("operatingMargins", "operatingMargin"))
    if opex is not None and abs(opex) <= 1.0:
        opex = round(opex * 100.0, 2)
    rev = _gf(info, ("totalRevenue",))
    rev_cr = market_cap_inr_to_cr(rev) if rev and rev > 1e7 else None
    div = _gf(info, ("dividendYield",))
    if div is not None and abs(div) <= 1.0:
        div = round(div * 100.0, 2)
    return {
        **f,
        "roe_pct": roe,
        "opm_pct": opex,
        "revenue_cr": rev_cr,
        "div_yield_pct": div,
        "trailing_pe": _gf(info, ("trailingPE", "forwardPE")),
    }


def _result_from_ticker(
    raw: str,
    info: dict,
    hist: pd.DataFrame,
    *,
    note: str = "",
    score: float = 0.0,
    extra: Optional[dict] = None,
) -> Optional[PopularScreenResult]:
    if hist is None or hist.empty:
        return None
    closes = hist_series(hist, "Close")
    vols = hist_series(hist, "Volume")
    if closes.empty:
        return None
    price = float(closes.iloc[-1])
    if price < 1:
        return None

    rsi_v = compute_rsi(closes)
    vol_r = compute_volume_ratio(vols)
    highs = hist_series(hist, "High")
    wk_high = _gf(info, ("fiftyTwoWeekHigh",)) or (float(highs.max()) if not highs.empty else None)
    pct_hi = round((price / wk_high - 1.0) * 100.0, 2) if wk_high and wk_high > 0 else None

    fund = _fundamentals(info)
    pe = get_pe(yf.Ticker(raw)) if info else fund.get("trailing_pe")

    disp = raw.replace(".NS", "").replace(".BO", "")
    return PopularScreenResult(
        ticker=disp,
        raw_ticker=raw,
        price=round(price, 2),
        pe=round(float(pe), 2) if pe is not None else None,
        market_cap_cr=fund.get("market_cap_cr"),
        rsi=rsi_v if not np.isnan(rsi_v) else None,
        vol_ratio=vol_r if not np.isnan(vol_r) else None,
        roce_pct=fund.get("roce_pct"),
        div_yield_pct=fund.get("div_yield_pct"),
        pct_from_52w_high=pct_hi,
        score=score,
        note=note,
        extra=extra or {},
        links=get_stock_links(raw),
    )


# Fix div_yield - use fund key div_yield_pct
def _mk_result(raw: str, info: dict, hist: pd.DataFrame, **kw) -> Optional[PopularScreenResult]:
    r = _result_from_ticker(raw, info, hist, **kw)
    if r is None:
        return None
    fund = _fundamentals(info)
    r.div_yield_pct = fund.get("div_yield_pct")
    r.market_cap_cr = fund.get("market_cap_cr")
    r.roce_pct = fund.get("roce_pct")
    return r


def _evaluate_screen(
    screen_id: str,
    raw: str,
    info: dict,
    hist: pd.DataFrame,
) -> Optional[PopularScreenResult]:
    if hist is None or len(hist) < 30:
        return None
    closes = hist_series(hist, "Close")
    vols = hist_series(hist, "Volume")
    if closes.empty:
        return None
    price = float(closes.iloc[-1])
    highs = hist_series(hist, "High")
    lows = hist_series(hist, "Low")
    fund = _fundamentals(info)

    if screen_id == "rsi_oversold":
        rsi_v = compute_rsi(closes)
        if np.isnan(rsi_v) or rsi_v >= 30:
            return None
        return _mk_result(raw, info, hist, note=f"RSI {rsi_v:.1f}", score=30 - rsi_v)

    if screen_id in ("darvas", "breakout_stocks"):
        wk_high = _gf(info, ("fiftyTwoWeekHigh",)) or (float(highs.max()) if not highs.empty else 0.0)
        wk_low = _gf(info, ("fiftyTwoWeekLow",)) or (float(lows.min()) if not lows.empty else 0.0)
        if price < 10 or wk_high <= 0:
            return None
        if price < wk_low:
            return None
        pct = (price / wk_high - 1.0) * 100.0
        if pct < -10.0:
            return None
        avg_vol = float(vols.tail(20).mean())
        if avg_vol < 100_000:
            return None
        return _mk_result(
            raw, info, hist,
            note=f"{pct:+.1f}% from 52w high",
            score=100 + pct,
            extra={"52w_high": wk_high, "avg_volume": avg_vol},
        )

    if screen_id == "new_52w_high":
        wk_high = _gf(info, ("fiftyTwoWeekHigh",)) or (float(highs.max()) if not highs.empty else 0.0)
        if wk_high <= 0 or price < 0.98 * wk_high:
            return None
        return _mk_result(raw, info, hist, note="Near / at 52-week high", score=price / wk_high * 100)

    if screen_id == "golden_crossover":
        ma50 = closes.rolling(50).mean()
        ma200 = closes.rolling(200).mean()
        if len(closes) < 205:
            return None
        if not ma_cross_recent(ma50, ma200, lookback=8):
            return None
        return _mk_result(raw, info, hist, note="50 DMA crossed above 200 DMA", score=50.0)

    if screen_id == "price_volume_action":
        if len(closes) < 15:
            return None
        wk = (
            pd.DataFrame({"Close": closes, "Volume": vols})
            .resample("W")
            .agg({"Close": "last", "Volume": "sum"})
            .dropna()
        )
        if len(wk) < 3:
            return None
        vol_chg = float(wk["Volume"].iloc[-1]) / max(float(wk["Volume"].iloc[-2]), 1.0)
        price_chg = float(wk["Close"].iloc[-1]) / max(float(wk["Close"].iloc[-2]), 1.0) - 1.0
        if vol_chg < 5.0 or price_chg <= 0:
            return None
        return _mk_result(
            raw, info, hist,
            note=f"Weekly vol {vol_chg:.1f}×, price {price_chg*100:+.1f}%",
            score=vol_chg * 10 + price_chg * 100,
        )

    if screen_id == "highest_dividend_yield":
        dy = fund.get("div_yield_pct")
        if dy is None:
            dy = _gf(info, ("dividendYield",))
        if dy is not None and abs(dy) <= 1.0:
            dy = dy * 100.0
        if dy is None or dy < 1.0:
            return None
        return _mk_result(raw, info, hist, note=f"Div yield {dy:.2f}%", score=dy)

    if screen_id == "magic_formula":
        pe = fund.get("trailing_pe") or get_pe(yf.Ticker(raw))
        roce = fund.get("roce_pct")
        if pe is None or pe <= 0 or roce is None:
            return None
        ey = 100.0 / pe
        score = ey + roce
        if score < 25:
            return None
        return _mk_result(raw, info, hist, note=f"EY {ey:.1f}% + ROCE {roce:.1f}", score=score)

    if screen_id == "high_growth_roe_pe":
        rg = fund.get("qtr_sales_var_pct") or 0
        roe = fund.get("roe_pct") or fund.get("roce_pct")
        pe = fund.get("trailing_pe")
        if rg < 15 or roe is None or roe < 15 or pe is None or pe > 40:
            return None
        g_factor = min(10.0, (rg / 10.0 + roe / 15.0 + max(0, 40 - pe) / 10.0))
        return _mk_result(raw, info, hist, note=f"G-factor ~{g_factor:.1f}/10", score=g_factor * 10)

    if screen_id == "value_stocks":
        opm = fund.get("opm_pct")
        roce = fund.get("roce_pct")
        de = fund.get("debt_equity")
        if opm is None or opm < 15 or roce is None or roce < 18:
            return None
        if de is not None and de >= 0.5:
            return None
        return _mk_result(raw, info, hist, note=f"OPM {opm:.0f}% ROCE {roce:.0f}%", score=opm + roce)

    if screen_id == "bluest_chips":
        mcap = fund.get("market_cap_cr")
        roe = fund.get("roe_pct")
        rg = fund.get("qtr_sales_var_pct")
        pe = fund.get("trailing_pe")
        if mcap is None or mcap < 3000 or roe is None or roe < 12:
            return None
        if rg is not None and rg < 5:
            return None
        if pe is not None and pe > 60:
            return None
        return _mk_result(raw, info, hist, note=f"Mcap {mcap:.0f} cr ROE {roe:.0f}%", score=roe + mcap / 1000)

    if screen_id == "bull_cartel":
        sg = fund.get("qtr_sales_var_pct")
        pg = fund.get("qtr_profit_var_pct")
        if sg is None or pg is None or sg < 10 or pg < 10:
            return None
        return _mk_result(raw, info, hist, note=f"Sales {sg:.0f}% Profit {pg:.0f}%", score=sg + pg)

    if screen_id == "growth_stocks":
        sg = fund.get("qtr_sales_var_pct") or 0
        pg = fund.get("qtr_profit_var_pct") or 0
        pe = fund.get("trailing_pe")
        if sg < 12 or pg < 8:
            return None
        if pe is not None and pe > 55:
            return None
        g = min(10.0, sg / 8.0 + pg / 10.0)
        return _mk_result(raw, info, hist, note=f"Growth score ~{g:.1f}", score=g * 10)

    if screen_id == "multibagger":
        try:
            from .multibagger import MultibaggerFilters, _passes_filters
        except ImportError:
            from multibagger import MultibaggerFilters, _passes_filters

        flt = MultibaggerFilters(
            min_qtr_sales_var_pct=0.0,
            min_qtr_profit_var_pct=0.0,
            min_roce_pct=15.0,
            apply_mcap_filter=False,
            apply_de_filter=False,
        )
        if not _passes_filters(fund, flt):
            return None
        return _mk_result(raw, info, hist, note="Multibagger gates (Yahoo)", score=fund.get("roce_pct") or 0)

    if screen_id == "benjamin_graham":
        rev = _gf(info, ("totalRevenue",))
        rev_cr = (rev or 0) / INR_PER_CRORE
        pe = fund.get("trailing_pe")
        if rev_cr < 250 or pe is None or pe > 25 or pe <= 0:
            return None
        return _mk_result(raw, info, hist, note=f"Sales ~{rev_cr:.0f} cr PE {pe:.1f}", score=250 / pe)

    if screen_id == "coffee_can":
        roe = fund.get("roe_pct")
        de = fund.get("debt_equity")
        sg = fund.get("qtr_sales_var_pct")
        if roe is None or roe < 18 or sg is None or sg < 8:
            return None
        if de is not None and de > 0.4:
            return None
        return _mk_result(raw, info, hist, note=f"ROE {roe:.0f}% steady growth", score=roe + sg)

    if screen_id == "loss_to_profit":
        pg = fund.get("qtr_profit_var_pct")
        if pg is None or pg < 50:
            return None
        pm = _gf(info, ("profitMargins",))
        if pm is not None and pm < 0:
            return None
        return _mk_result(raw, info, hist, note=f"Profit growth {pg:.0f}%", score=pg)

    if screen_id == "high_growth_high_roe_low_pe":
        roe = fund.get("roe_pct")
        pe = fund.get("trailing_pe")
        sg = fund.get("qtr_sales_var_pct")
        if roe is None or roe < 20 or pe is None or pe > 25 or sg is None or sg < 15:
            return None
        return _mk_result(raw, info, hist, note=f"ROE {roe:.0f}% PE {pe:.1f}", score=roe / max(pe, 1) * 10)

    if screen_id == "piotroski_lite":
        roa = normalize_return_pct(_gf(info, ("returnOnAssets",)))
        roe = fund.get("roe_pct")
        de = fund.get("debt_equity")
        om = fund.get("opm_pct")
        score = 0
        if roe and roe > 10:
            score += 3
        if roa and roa > 5:
            score += 2
        if om and om > 10:
            score += 2
        if de is not None and de < 0.6:
            score += 2
        if fund.get("qtr_profit_var_pct") and fund.get("qtr_profit_var_pct", 0) > 0:
            score += 1
        if score < 7:
            return None
        return _mk_result(raw, info, hist, note=f"Piotroski-lite {score}/10", score=float(score))

    if screen_id == "low_pe_vs_earnings":
        pe = fund.get("trailing_pe")
        eg = fund.get("qtr_profit_var_pct")
        if pe is None or pe > 18 or pe <= 0:
            return None
        return _mk_result(raw, info, hist, note=f"Trailing PE {pe:.1f}", score=100 / pe)

    if screen_id == "top_100":
        mcap = fund.get("market_cap_cr") or 0
        return _mk_result(raw, info, hist, note=f"Mcap {mcap:.0f} cr", score=mcap)

    if screen_id == "fii_buying":
        return None

    if screen_id in ("quarterly_growers", "capacity_expansion", "debt_reduction"):
        return None

    return None


SCREEN_REGISTRY: list[ScreenMeta] = [
    ScreenMeta(
        "price_volume_action",
        "Price Volume Action",
        "Weekly volume >5× prior week with positive price change.",
        "Technical",
        "📊",
    ),
    ScreenMeta("fii_buying", "FII Buying", "Foreign institutional flow bias — requires exchange flow data.", "Flows", "🌏", False, "Not available on Yahoo"),
    ScreenMeta("bull_cartel", "The Bull Cartel", "Strong quarterly sales & profit growth (Yahoo YoY proxies).", "Growth", "🐂"),
    ScreenMeta("low_pe_vs_earnings", "Low on 10Y Average Earnings", "Proxy: low trailing PE vs earnings (not true 10Y Graham average).", "Value", "📉", True, "Proxy only — not true 10Y average on Yahoo"),
    ScreenMeta("magic_formula", "Magic Formula", "High earnings yield (1/PE) + ROCE rank (Greenblatt-style proxy).", "Value", "✨"),
    ScreenMeta("growth_stocks", "Growth Stocks", "Revenue & profit growth with reasonable PE; G-factor style score.", "Growth", "📈"),
    ScreenMeta("highest_dividend_yield", "Highest Dividend Yield", "Consistent dividend payers sorted by yield.", "Income", "💰"),
    ScreenMeta("new_52w_high", "Companies Creating New High", "Price within ~2% of 52-week high.", "Technical", "⬆️"),
    ScreenMeta("golden_crossover", "Golden Crossover", "50 DMA crossed above 200 DMA recently.", "Technical", "✝️"),
    ScreenMeta("capacity_expansion", "Capacity Expansion", "Fixed assets doubled — needs balance-sheet history.", "Fundamental", "🏭", False, "Requires multi-year filings"),
    ScreenMeta("piotroski_lite", "Piotroski Scan", "Simplified 0–10 score from ROE, ROA, margins, leverage.", "Quality", "🔬", True, "Lite version — not full 9-point Piotroski"),
    ScreenMeta("high_growth_high_roe_low_pe", "High Growth · High RoE · Low PE", "Growth + ROE + PE below 25.", "Blend", "⚡"),
    ScreenMeta("loss_to_profit", "Loss to Profit", "Large profit growth % after turnaround (proxy).", "Growth", "🔄", True, "Proxy via earnings growth %"),
    ScreenMeta("debt_reduction", "Debt Reduction", "Companies reducing debt — needs multi-year balance sheet.", "Quality", "📉", False),
    ScreenMeta("benjamin_graham", "Benjamin Graham Filter", "Sales > ₹250 cr & PE < 25 (ET/Vikas Gupta style proxy).", "Value", "🎩"),
    ScreenMeta("coffee_can", "Coffee Can Portfolio", "High ROE, moderate leverage, steady sales growth.", "Quality", "☕"),
    ScreenMeta("darvas", "Darvas Scan", "Within 10% of 52w high, above 52w low, vol & price filters.", "Technical", "📦"),
    ScreenMeta("bluest_chips", "Bluest of Blue Chips", "Mcap > ₹3,000 cr, ROE & growth, PE cap.", "Large cap", "💎"),
    ScreenMeta("value_stocks", "Value Stocks", "High OPM, ROCE, debt/equity < 0.5.", "Value", "💎"),
    ScreenMeta("rsi_oversold", "RSI — Oversold", "RSI(14) below 30.", "Technical", "📉"),
    ScreenMeta("quarterly_growers", "Quarterly Growers", "Q0>Q1>Q2>Q3 consecutive — needs quarterly series.", "Growth", "📅", False),
    ScreenMeta("multibagger", "Multibagger Stocks", "Growth + ROCE + optional cap gates.", "Theme", "🌱"),
    ScreenMeta("top_100", "Top 100 Stocks", "Largest NSE names in universe by market cap.", "Index", "🏆"),
    ScreenMeta("breakout_stocks", "Breakout Stocks", "Same as Darvas: near 52w high with liquidity.", "Technical", "🚀"),
]


def registry_by_id() -> dict[str, ScreenMeta]:
    return {s.screen_id: s for s in SCREEN_REGISTRY}


def scan_popular_screen(
    screen_id: str,
    universe_name: str,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    *,
    info_delay_sec: float = 0.08,
    max_results: int = 100,
) -> tuple[list[PopularScreenResult], ScreenMeta]:
    meta = registry_by_id().get(screen_id)
    if meta is None:
        raise ValueError(f"Unknown screen: {screen_id}")

    if not meta.implemented:
        return [], meta

    tickers = UNIVERSES.get(universe_name, [])
    results: list[PopularScreenResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        try:
            stock = yf.Ticker(raw)
            try:
                info = stock.info or {}
            except Exception:
                info = {}
            hist = fetch_price_history(raw, "1d")
            row = _evaluate_screen(screen_id, raw, info, hist)
            if row:
                results.append(row)
        except Exception:
            continue
        if info_delay_sec > 0 and universe_name != "Nifty 50 (NSE)":
            time.sleep(info_delay_sec)

    if screen_id == "top_100":
        results.sort(key=lambda x: x.market_cap_cr or 0, reverse=True)
        results = results[:100]
    else:
        results.sort(key=lambda x: x.score, reverse=True)

    return results[:max_results], meta
