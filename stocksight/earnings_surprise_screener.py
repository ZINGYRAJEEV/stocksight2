"""
Earnings Surprise — unpriced quarterly jump screener.

Finds stocks where **revenue and profit jumped sharply QoQ** (latest vs prior quarter)
with **quality / forward growth** signals, but the **share price has not re-rated much**.

NSE/BSE: **Screener.in** quarterly Sales+ / Net Profit+ (QoQ) and top ROCE first;
Yahoo Finance as fallback. Price history still from Yahoo.
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
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        normalize_debt_equity,
        normalize_growth_pct,
        resolve_scan_tickers,
    )
    from .peter_lynch import compute_peg
    from .screener import (
        drawdown_pct_from_52w_high,
        get_pe,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )
except ImportError:
    from multibagger import (
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        normalize_debt_equity,
        normalize_growth_pct,
        resolve_scan_tickers,
    )
    from peter_lynch import compute_peg
    from screener import (
        drawdown_pct_from_52w_high,
        get_pe,
        get_sector_industry,
        get_stock_links,
        hist_series,
        pct_vs_ma,
    )

META = {
    "id": "earnings_surprise",
    "title": "Earnings Surprise — Unpriced Growth",
    "emoji": "💎",
    "nav_title": "Earnings Surprise",
    "audience": (
        "Hunt **earnings acceleration** before the market fully prices it — "
        "sharp **QoQ revenue & profit jumps**, solid fundamentals, but **muted share-price reaction**."
    ),
    "purpose": (
        "Compares the **latest two reported quarters** (Screener.in for NSE, Yahoo fallback) for revenue "
        "and PAT jumps, "
        "layers **ROCE / YoY growth** quality gates, and filters names where price is still **near 200-DMA**, "
        "**below 52-week highs**, and **3M return is capped**. Rank by surprise score."
    ),
}

REVENUE_ROW_CANDIDATES = (
    "Total Revenue",
    "Operating Revenue",
    "Revenue",
)
PROFIT_ROW_CANDIDATES = (
    "Net Income Common Stockholders",
    "Net Income",
    "Net Income Continuous Operations",
    "Net Income From Continuing Operation Net Minority Interest",
)

RANK_BY_OPTIONS: dict[str, str] = {
    "surprise": "Surprise score (QoQ jump − price run-up)",
    "qoq_profit": "QoQ profit jump %",
    "qoq_sales": "QoQ sales jump %",
    "drawdown": "Drawdown from 52w high (most unpriced)",
    "peg": "PEG (lowest first)",
}


@dataclass
class EarningsSurpriseFilters:
    min_qoq_sales_pct: float = 10.0
    min_qoq_profit_pct: float = 15.0
    require_profit_beats_sales_qoq: bool = True
    min_roce_pct: float = 12.0
    min_qtr_sales_yoy_pct: float = 8.0
    min_qtr_profit_yoy_pct: float = 12.0
    require_future_quality: bool = True
    max_pct_vs_ma200: float = 12.0
    min_drawdown_52w_pct: float = 5.0
    max_return_3m_pct: float = 18.0
    max_peg: float = 2.5
    max_debt_equity: float = 1.0
    min_market_cap_cr: float = 300.0
    info_delay_sec: float = 0.12
    screener_delay_sec: float = 0.22


@dataclass
class EarningsSurpriseResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    price: float
    pe: Optional[float]
    peg: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    latest_q: str
    prior_q: str
    qoq_sales_pct: Optional[float]
    qoq_profit_pct: Optional[float]
    qtr_sales_yoy_pct: Optional[float]
    qtr_profit_yoy_pct: Optional[float]
    roce_pct: Optional[float]
    roce_is_roe_proxy: bool
    debt_equity: Optional[float]
    pct_vs_ma200: Optional[float]
    drawdown_52w_pct: Optional[float]
    return_1m_pct: Optional[float]
    return_3m_pct: Optional[float]
    week52_high: Optional[float]
    surprise_score: float
    verdict: str
    pass_notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)
    qoq_source: str = ""
    fundamentals_source: str = ""


def _pick_row(df: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[pd.Series]:
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    lower_map = {str(i).lower(): i for i in df.index}
    for cand in candidates:
        key = cand.lower()
        if key in lower_map:
            return df.loc[lower_map[key]]
    for idx in df.index:
        s = str(idx).lower()
        if "total revenue" in s or s == "revenue":
            return df.loc[idx]
    for idx in df.index:
        s = str(idx).lower()
        if "net income" in s and "noncontrolling" not in s:
            return df.loc[idx]
    return None


def _qoq_pct(current: float, prior: float) -> Optional[float]:
    if prior is None or current is None:
        return None
    try:
        p = float(prior)
        c = float(current)
    except (TypeError, ValueError):
        return None
    if np.isnan(p) or np.isnan(c):
        return None
    if abs(p) < 1.0:
        return None
    return round((c - p) / abs(p) * 100.0, 1)


def extract_quarterly_qoq(stock: yf.Ticker) -> dict:
    """Latest vs prior quarter revenue & profit from Yahoo quarterly statements."""
    qf = getattr(stock, "quarterly_financials", None)
    if qf is None or (hasattr(qf, "empty") and qf.empty):
        qf = getattr(stock, "quarterly_income_stmt", None)
    if qf is None or qf.empty or qf.shape[1] < 2:
        return {}

    cols = list(qf.columns)
    try:
        cols = sorted(cols, reverse=True)
    except Exception:
        pass

    rev = _pick_row(qf, REVENUE_ROW_CANDIDATES)
    profit = _pick_row(qf, PROFIT_ROW_CANDIDATES)
    if rev is None or profit is None:
        return {}

    try:
        r0, r1 = float(rev[cols[0]]), float(rev[cols[1]])
        p0, p1 = float(profit[cols[0]]), float(profit[cols[1]])
    except (TypeError, ValueError, KeyError):
        return {}

    def _fmt_col(c) -> str:
        try:
            return pd.Timestamp(c).strftime("%b %Y")
        except Exception:
            return str(c)[:10]

    return {
        "latest_q": _fmt_col(cols[0]),
        "prior_q": _fmt_col(cols[1]),
        "qoq_sales_pct": _qoq_pct(r0, r1),
        "qoq_profit_pct": _qoq_pct(p0, p1),
        "latest_revenue_cr": round(r0 / 1e7, 1) if abs(r0) > 1e6 else None,
        "latest_profit_cr": round(p0 / 1e7, 1) if abs(p0) > 1e6 else None,
    }


def _period_return_pct(closes: pd.Series, trading_days: int) -> Optional[float]:
    if closes is None or closes.empty or len(closes) < trading_days + 2:
        return None
    end_px = float(closes.iloc[-1])
    start_px = float(closes.iloc[-(trading_days + 1)])
    if start_px <= 0:
        return None
    return round((end_px / start_px - 1.0) * 100.0, 1)


def _surprise_score(
    qoq_sales: Optional[float],
    qoq_profit: Optional[float],
    roce: Optional[float],
    peg: Optional[float],
    pct_ma200: Optional[float],
    ret_3m: Optional[float],
    drawdown: Optional[float],
) -> float:
    qs = float(qoq_sales or 0.0)
    qp = float(qoq_profit or 0.0)
    leverage = max(0.0, qp - qs)
    roce_pts = min(float(roce or 0.0), 40.0) * 0.15
    peg_pen = max(0.0, float(peg or 2.0) - 1.0) * 8.0
    ma_pen = max(0.0, float(pct_ma200 or 0.0)) * 0.35
    ret_pen = max(0.0, float(ret_3m or 0.0)) * 0.45
    dd_bonus = min(float(drawdown or 0.0), 40.0) * 0.25
    raw = qs * 0.22 + qp * 0.38 + leverage * 0.12 + roce_pts - peg_pen - ma_pen - ret_pen + dd_bonus
    return round(max(0.0, raw), 1)


def _verdict(
    qoq_sales: Optional[float],
    qoq_profit: Optional[float],
    pct_ma200: Optional[float],
    ret_3m: Optional[float],
    drawdown: Optional[float],
) -> str:
    qs = float(qoq_sales or 0.0)
    qp = float(qoq_profit or 0.0)
    ma = float(pct_ma200 or 0.0)
    r3 = float(ret_3m or 0.0)
    dd = float(drawdown or 0.0)
    if qs >= 15 and qp >= 25 and ma <= 5 and r3 <= 8:
        return "Hidden gem — big QoQ, price asleep"
    if qp >= 20 and dd >= 10 and r3 <= 12:
        return "Unpriced — still below highs"
    if qs >= 10 and qp >= 15 and r3 <= 15:
        return "Earnings jump — verify sustainability"
    if r3 > 15 or ma > 12:
        return "Price moved — edge may be gone"
    return "Watch — confirm on Screener"


def _passes_filters(
    qoq: dict,
    fund: dict,
    price_metrics: dict,
    flt: EarningsSurpriseFilters,
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    qs = qoq.get("qoq_sales_pct")
    qp = qoq.get("qoq_profit_pct")

    if qs is None or qs < flt.min_qoq_sales_pct:
        return False, notes
    notes.append(f"QoQ sales {qs:.1f}%")

    if qp is None or qp < flt.min_qoq_profit_pct:
        return False, notes
    notes.append(f"QoQ profit {qp:.1f}%")

    if flt.require_profit_beats_sales_qoq and qp <= qs:
        return False, notes
    notes.append("Profit jump > sales jump (QoQ)")

    roce = fund.get("roce_pct")
    if roce is None or roce < flt.min_roce_pct:
        return False, notes
    notes.append(f"ROCE {roce:.1f}%")

    if flt.require_future_quality:
        yoy_s = fund.get("qtr_sales_var_pct")
        yoy_p = fund.get("qtr_profit_var_pct")
        if yoy_s is None or yoy_s < flt.min_qtr_sales_yoy_pct:
            return False, notes
        if yoy_p is None or yoy_p < flt.min_qtr_profit_yoy_pct:
            return False, notes
        notes.append(f"YoY sales {yoy_s:.1f}% · YoY profit {yoy_p:.1f}%")

    mcap = fund.get("market_cap_cr")
    if mcap is None or mcap < flt.min_market_cap_cr:
        return False, notes

    de = fund.get("debt_equity")
    if de is not None and de > flt.max_debt_equity:
        return False, notes

    pct_ma = price_metrics.get("pct_vs_ma200")
    if pct_ma is not None and pct_ma > flt.max_pct_vs_ma200:
        return False, notes
    if pct_ma is not None:
        notes.append(f"vs 200-DMA {pct_ma:+.1f}%")

    dd = price_metrics.get("drawdown_52w_pct")
    if dd is not None and dd < flt.min_drawdown_52w_pct:
        return False, notes
    if dd is not None:
        notes.append(f"{dd:.0f}% below 52w high")

    r3 = price_metrics.get("return_3m_pct")
    if r3 is not None and r3 > flt.max_return_3m_pct:
        return False, notes
    if r3 is not None:
        notes.append(f"3M return {r3:+.1f}%")

    peg = price_metrics.get("peg")
    if peg is not None and peg > flt.max_peg:
        return False, notes
    if peg is not None:
        notes.append(f"PEG {peg:.2f}")

    return True, notes


def _is_indian_ticker(raw: str) -> bool:
    return raw.endswith(".NS") or raw.endswith(".BO")


def _screener_links(disp: str) -> dict:
    slug = disp.replace(".NS", "").replace(".BO", "")
    return {"Screener.in": f"https://www.screener.in/company/{slug}/consolidated/"}


def scan_earnings_surprise(
    scan_source: str,
    filters: EarningsSurpriseFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[EarningsSurpriseResult]:
    flt = filters or EarningsSurpriseFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[EarningsSurpriseResult] = []
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

            qoq: dict = {}
            qoq_source = ""
            fund_source = ""
            disp = raw.replace(".NS", "").replace(".BO", "")
            screener_html = ""

            if _is_indian_ticker(raw):
                try:
                    from screener_in_data import (
                        fetch_screener_company_html,
                        fetch_screener_quarterly_qoq,
                        enrich_fundamentals_from_screener,
                    )

                    screener_html = fetch_screener_company_html(disp)
                    screener_qoq = fetch_screener_quarterly_qoq(disp, html=screener_html)
                    if screener_qoq.get("qoq_sales_pct") is not None and screener_qoq.get("qoq_profit_pct") is not None:
                        qoq = screener_qoq
                        qoq_source = str(screener_qoq.get("source") or "Screener.in")
                    if flt.screener_delay_sec > 0:
                        time.sleep(flt.screener_delay_sec)
                except Exception:
                    pass

            if not qoq:
                qoq = extract_quarterly_qoq(stock)
                if qoq:
                    qoq_source = "Yahoo Finance quarterly P&L"
            if not qoq:
                continue

            fund = extract_multibagger_fundamentals(info)
            if _is_indian_ticker(raw):
                try:
                    from screener_in_data import enrich_fundamentals_from_screener

                    fund = enrich_fundamentals_from_screener(
                        disp,
                        fund,
                        html=screener_html,
                    )
                    fund_source = str(fund.get("screener_fundamentals_source") or "")
                except Exception:
                    pass
            price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0.0)
            if price <= 0:
                continue

            pe = get_pe(stock)
            growth_for_peg = normalize_growth_pct(
                fund.get("qtr_profit_var_pct") or fund.get("qtr_sales_var_pct")
            )
            peg = compute_peg(pe, growth_for_peg)

            wk_high = fund.get("week52_high")
            dd = drawdown_pct_from_52w_high(price, wk_high)

            pct_ma200: Optional[float] = None
            ret_1m: Optional[float] = None
            ret_3m: Optional[float] = None
            try:
                hist = stock.history(period="1y", interval="1d", auto_adjust=True)
                closes = hist_series(hist, "Close").dropna()
                if len(closes) >= 200:
                    ma200 = float(closes.iloc[-200:].mean())
                    pct_ma200 = pct_vs_ma(price, ma200)
                ret_1m = _period_return_pct(closes, 21)
                ret_3m = _period_return_pct(closes, 63)
            except Exception:
                pass

            price_metrics = {
                "pct_vs_ma200": pct_ma200,
                "drawdown_52w_pct": dd,
                "return_3m_pct": ret_3m,
                "peg": peg,
            }
            ok, notes = _passes_filters(qoq, fund, price_metrics, flt)
            if not ok:
                continue

            sector, _ = get_sector_industry(stock)
            disp = raw.replace(".NS", "").replace(".BO", "")
            links = get_stock_links(raw)
            if _is_indian_ticker(raw):
                links = {**links, **_screener_links(disp)}
            score = _surprise_score(
                qoq.get("qoq_sales_pct"),
                qoq.get("qoq_profit_pct"),
                fund.get("roce_pct"),
                peg,
                pct_ma200,
                ret_3m,
                dd,
            )
            verdict = _verdict(
                qoq.get("qoq_sales_pct"),
                qoq.get("qoq_profit_pct"),
                pct_ma200,
                ret_3m,
                dd,
            )

            results.append(
                EarningsSurpriseResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    sector=sector or "—",
                    price=round(price, 2),
                    pe=round(float(pe), 2) if pe is not None else None,
                    peg=peg,
                    market_cap_cr=fund.get("market_cap_cr"),
                    market_cap_display=fund.get("market_cap_display") or "",
                    latest_q=str(qoq.get("latest_q") or "—"),
                    prior_q=str(qoq.get("prior_q") or "—"),
                    qoq_sales_pct=qoq.get("qoq_sales_pct"),
                    qoq_profit_pct=qoq.get("qoq_profit_pct"),
                    qtr_sales_yoy_pct=fund.get("qtr_sales_var_pct"),
                    qtr_profit_yoy_pct=fund.get("qtr_profit_var_pct"),
                    roce_pct=fund.get("roce_pct"),
                    roce_is_roe_proxy=bool(fund.get("roce_is_roe_proxy")),
                    debt_equity=normalize_debt_equity(fund.get("debt_equity")),
                    pct_vs_ma200=pct_ma200,
                    drawdown_52w_pct=dd,
                    return_1m_pct=ret_1m,
                    return_3m_pct=ret_3m,
                    week52_high=wk_high,
                    surprise_score=score,
                    verdict=verdict,
                    pass_notes=notes,
                    links=links,
                    qoq_source=qoq_source,
                    fundamentals_source=fund_source,
                )
            )
        except Exception:
            continue

        if flt.info_delay_sec > 0:
            time.sleep(flt.info_delay_sec)

    return sort_earnings_surprise_results(results, rank_by="surprise")


def sort_earnings_surprise_results(
    results: list[EarningsSurpriseResult],
    *,
    rank_by: str = "surprise",
) -> list[EarningsSurpriseResult]:
    if rank_by == "qoq_profit":
        key = lambda r: float(r.qoq_profit_pct or -9999.0)
    elif rank_by == "qoq_sales":
        key = lambda r: float(r.qoq_sales_pct or -9999.0)
    elif rank_by == "drawdown":
        key = lambda r: float(r.drawdown_52w_pct or -9999.0)
    elif rank_by == "peg":
        key = lambda r: -(float(r.peg) if r.peg is not None else 9999.0)
    else:
        key = lambda r: float(r.surprise_score or 0.0)
    return sorted(results, key=key, reverse=True)


def result_to_row(r: EarningsSurpriseResult, rank: int) -> dict:
    roce_lbl = (
        f"{r.roce_pct:.1f}" + ("*" if r.roce_is_roe_proxy else "")
        if r.roce_pct is not None
        else "—"
    )
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Surprise": r.surprise_score,
        "Verdict": r.verdict,
        "QoQ sales %": r.qoq_sales_pct,
        "QoQ profit %": r.qoq_profit_pct,
        "Latest Q": r.latest_q,
        "Prior Q": r.prior_q,
        "YoY sales %": r.qtr_sales_yoy_pct,
        "YoY profit %": r.qtr_profit_yoy_pct,
        "ROCE %": roce_lbl,
        "PEG": r.peg,
        "vs 200-DMA %": r.pct_vs_ma200,
        "Below 52w high %": r.drawdown_52w_pct,
        "1M return %": r.return_1m_pct,
        "3M return %": r.return_3m_pct,
        "Price": r.price,
        "P/E": r.pe,
        "Mcap": r.market_cap_display,
        "Sector": r.sector,
        "D/E": r.debt_equity,
        "Notes": " · ".join(r.pass_notes[:4]),
        "QoQ src": r.qoq_source or "—",
    }
