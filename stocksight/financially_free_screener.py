"""
Financially Free™ swing methodology screener — equity cash, momentum, VCP, cycle timing.

Educational approximation of earnings-driven swing trading (sector leaders at highs,
VCP breakouts, ROCE/ROE quality, 21-EMA exit discipline). Not financial advice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from multibagger import extract_multibagger_fundamentals, normalize_return_pct, resolve_scan_tickers
from screener import (
    benchmark_ticker_for,
    compute_rsi,
    fetch_monthly_history,
    get_pe,
    get_sector_industry,
    get_stock_links,
    hist_series,
    relative_strength_vs_benchmark,
)
from stage2_momentum import (
    _analyze_vcp,
    _eval_trend_template,
    _fetch_hist,
    _infer_stage,
)

ProgressCb = Callable[[int, int, str], None]

META = {
    "id": "financially_free_swing",
    "title": "Financially Free™ Swing Screener",
    "emoji": "💹",
    "nav_title": "Financially Free Swing",
    "audience": (
        "Swing traders in **equity cash** — momentum over value, **sector leaders** near highs, "
        "VCP bases, ROCE/ROE quality, and **21-EMA** risk discipline."
    ),
    "purpose": (
        "Monthly **ROC** + **Nifty/Gold** cycle panel, stock scan for leaders/VCP/quality, "
        "concentrated-portfolio rules (5–10 names, ~10% stop). Yahoo proxies — verify on charts."
    ),
}

SCAN_MODES: dict[str, str] = {
    "sector_leader": "Sector leader (ATH momentum + quality)",
    "vcp_swing": "VCP swing (contraction + breakout)",
    "combined": "Combined (leader + VCP + quality)",
}

NIFTY_MONTHLY_ROC_LEN = 18
SMALLCAP_MONTHLY_ROC_LEN = 20
NIFTY_ROC_SELL_ZONE = 45.0
SMALLCAP_ROC_SELL_ZONE = 100.0

RANK_OPTIONS: dict[str, str] = {
    "ff_score": "FF score (default)",
    "rs": "Relative strength vs Nifty",
    "near_high": "Nearest to 52w high",
    "vcp": "VCP score",
    "roce": "ROCE %",
}

SECTOR_FOCUS_PRESETS: dict[str, str] = {
    "": "Any sector",
    "metal": "Metal & mining",
    "power": "Power / transmission",
    "solar": "Solar / renewable",
    "chemical": "Chemicals",
}


@dataclass
class FinanciallyFreeFilters:
    scan_mode: str = "combined"
    min_roce_pct: float = 20.0
    min_roe_pct: float = 20.0
    require_roce_roe: bool = True
    max_pct_below_52w_high: float = 8.0
    min_pct_above_52w_low: float = 25.0
    min_rs_vs_nifty_pp: float = 0.0
    min_vcp_score: float = 25.0
    min_trend_pass: int = 5
    require_above_21ema: bool = False
    sector_keyword: str = ""
    stop_loss_pct: float = 10.0


@dataclass
class MarketCycleSnapshot:
    nifty_roc: Optional[float] = None
    nifty_zone: str = "—"
    smallcap_roc: Optional[float] = None
    smallcap_zone: str = "—"
    nifty_gold_ratio: Optional[float] = None
    nifty_gold_pctile: Optional[float] = None
    nifty_gold_signal: str = "—"
    cycle_summary: str = ""


@dataclass
class FinanciallyFreeResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    price: float
    pe: Optional[float]
    eps: Optional[float]
    eps_growth_pct: Optional[float]
    roce_pct: Optional[float]
    roe_pct: Optional[float]
    pct_below_52w_high: Optional[float]
    pct_above_52w_low: Optional[float]
    rs_vs_nifty_pp: Optional[float]
    rsi_14: Optional[float]
    monthly_rsi_14: Optional[float]
    vcp_score: float
    vcp_grade: str
    trend_pass: int
    stage_label: str
    ema21: Optional[float]
    pct_vs_21ema: Optional[float]
    above_21ema: bool
    two_red_below_21ema: bool
    exit_21ema: str
    stop_price_10pct: Optional[float]
    ff_score: float
    scan_mode: str
    action_hint: str
    links: dict = field(default_factory=dict)


def _display_ticker(raw: str) -> str:
    return raw.replace(".NS", "").replace(".BO", "")


def _monthly_rsi_14(raw: str, stock: yf.Ticker) -> Optional[float]:
    try:
        mhist = fetch_monthly_history(raw)
        if mhist is None or mhist.empty:
            mhist = stock.history(period="10y", interval="1mo", auto_adjust=True)
    except Exception:
        return None
    if mhist is None or mhist.empty:
        return None
    closes = hist_series(mhist, "Close").dropna()
    if len(closes) < 16:
        return None
    val = compute_rsi(closes)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), 2)


def _daily_rsi_14(hist: pd.DataFrame) -> Optional[float]:
    closes = hist_series(hist, "Close").dropna()
    if len(closes) < 16:
        return None
    val = compute_rsi(closes)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), 2)


def _monthly_roc(closes: pd.Series, length: int) -> Optional[float]:
    if closes is None or len(closes) < length + 1:
        return None
    s = closes.dropna()
    if len(s) < length + 1:
        return None
    cur = float(s.iloc[-1])
    past = float(s.iloc[-1 - length])
    if past <= 0:
        return None
    return round((cur / past - 1.0) * 100.0, 2)


def _roc_zone(roc: Optional[float], sell_threshold: float) -> str:
    if roc is None:
        return "—"
    r = float(roc)
    if r <= 5:
        return "🟢 Buy zone (near 0)"
    if r >= sell_threshold * 0.85:
        return "🔴 Sell / caution zone"
    if r >= sell_threshold * 0.6:
        return "🟠 Extended — tighten stops"
    return "🟡 Neutral / hold"


def _fetch_monthly_closes(symbol: str) -> pd.Series:
    hist = fetch_monthly_history(symbol, period="max")
    if hist is None or hist.empty:
        try:
            hist = yf.Ticker(symbol).history(period="10y", interval="1mo", auto_adjust=True)
        except Exception:
            return pd.Series(dtype=float)
    if hist is None or hist.empty:
        return pd.Series(dtype=float)
    return hist_series(hist, "Close").dropna()


def fetch_market_cycle_snapshot() -> MarketCycleSnapshot:
    """Monthly ROC (Nifty / Smallcap) + Nifty/Gold ratio context."""
    snap = MarketCycleSnapshot()
    nifty_c = _fetch_monthly_closes("^NSEI")
    snap.nifty_roc = _monthly_roc(nifty_c, NIFTY_MONTHLY_ROC_LEN)
    snap.nifty_zone = _roc_zone(snap.nifty_roc, NIFTY_ROC_SELL_ZONE)

    small_c = pd.Series(dtype=float)
    for sym in ("^CNXSC", "NIFTYSMLCAP.NS", "^NSEMDCP50", "^CNXSMALLCAP"):
        small_c = _fetch_monthly_closes(sym)
        if not small_c.empty:
            break
    snap.smallcap_roc = _monthly_roc(small_c, SMALLCAP_MONTHLY_ROC_LEN)
    snap.smallcap_zone = _roc_zone(snap.smallcap_roc, SMALLCAP_ROC_SELL_ZONE)

    try:
        n_daily = yf.Ticker("^NSEI").history(period="5y", interval="1d", auto_adjust=True)
        g_daily = yf.Ticker("GOLDBEES.NS").history(period="5y", interval="1d", auto_adjust=True)
        if n_daily is not None and g_daily is not None and not n_daily.empty and not g_daily.empty:
            nc = hist_series(n_daily, "Close").dropna()
            gc = hist_series(g_daily, "Close").dropna()
            aligned = pd.concat([nc.rename("n"), gc.rename("g")], axis=1).dropna()
            if len(aligned) >= 60:
                ratio = (aligned["n"] / aligned["g"].replace(0, np.nan)).dropna()
                cur_r = float(ratio.iloc[-1])
                snap.nifty_gold_ratio = round(cur_r, 4)
                pctile = float((ratio <= cur_r).mean() * 100.0)
                snap.nifty_gold_pctile = round(pctile, 1)
                if pctile <= 25:
                    snap.nifty_gold_signal = "🟢 Equity favored (ratio low in channel)"
                elif pctile >= 75:
                    snap.nifty_gold_signal = "🔴 Gold favored (ratio high in channel)"
                else:
                    snap.nifty_gold_signal = "🟡 Mid-channel — balanced"
    except Exception:
        pass

    parts = []
    if snap.nifty_roc is not None:
        parts.append(f"Nifty ROC({NIFTY_MONTHLY_ROC_LEN}m)={snap.nifty_roc:+.1f}%")
    if snap.smallcap_roc is not None:
        parts.append(f"Smallcap ROC({SMALLCAP_MONTHLY_ROC_LEN}m)={snap.smallcap_roc:+.1f}%")
    snap.cycle_summary = " · ".join(parts) if parts else "Cycle data unavailable"
    return snap


def _ema21_status(hist: pd.DataFrame) -> dict:
    closes = hist_series(hist, "Close").dropna()
    if len(closes) < 25:
        return {
            "ema21": None,
            "pct_vs_21ema": None,
            "above_21ema": False,
            "two_red_below_21ema": False,
            "exit_signal": "—",
        }
    ema21 = closes.ewm(span=21, adjust=False).mean()
    price = float(closes.iloc[-1])
    e21 = float(ema21.iloc[-1])
    pct = round((price / e21 - 1.0) * 100.0, 2) if e21 > 0 else None
    two_red = (
        float(closes.iloc[-1]) < float(ema21.iloc[-1])
        and float(closes.iloc[-2]) < float(ema21.iloc[-2])
    )
    above = price > e21
    if two_red:
        exit_sig = "🔴 Exit — 2 closes below 21-EMA"
    elif above:
        exit_sig = "🟢 Hold / re-entry OK above 21-EMA"
    else:
        exit_sig = "🟡 Below 21-EMA — watch"
    return {
        "ema21": round(e21, 2),
        "pct_vs_21ema": pct,
        "above_21ema": above,
        "two_red_below_21ema": two_red,
        "exit_signal": exit_sig,
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


def _ff_score(
    *,
    pct_below_high: Optional[float],
    rs_pp: Optional[float],
    vcp_score: float,
    roce: Optional[float],
    roe: Optional[float],
    above_21ema: bool,
    trend_pass: int,
) -> float:
    score = 0.0
    if pct_below_high is not None:
        score += max(0.0, (12.0 - float(pct_below_high)) * 3.0)
    if rs_pp is not None:
        score += min(30.0, max(0.0, float(rs_pp) * 1.5))
    score += min(25.0, float(vcp_score) * 0.35)
    if roce is not None:
        score += min(15.0, float(roce) * 0.4)
    if roe is not None:
        score += min(10.0, float(roe) * 0.25)
    score += trend_pass * 2.5
    if above_21ema:
        score += 8.0
    return round(score, 1)


def _passes_mode(
    mode: str,
    *,
    pct_below_high: Optional[float],
    vcp_score: float,
    trend_pass: int,
    roce: Optional[float],
    roe: Optional[float],
    rs_pp: Optional[float],
    flt: FinanciallyFreeFilters,
) -> bool:
    near_high = pct_below_high is not None and pct_below_high <= flt.max_pct_below_52w_high
    quality = True
    if flt.require_roce_roe:
        quality = (
            roce is not None
            and roe is not None
            and roce >= flt.min_roce_pct
            and roe >= flt.min_roe_pct
        )
    rs_ok = rs_pp is None or float(rs_pp) >= flt.min_rs_vs_nifty_pp
    vcp_ok = vcp_score >= flt.min_vcp_score
    trend_ok = trend_pass >= flt.min_trend_pass

    if mode == "sector_leader":
        return near_high and quality and rs_ok and trend_ok
    if mode == "vcp_swing":
        return vcp_ok and trend_ok and near_high
    return near_high and quality and rs_ok and (vcp_ok or trend_ok >= 6)


def _action_hint(mode: str, stage: str, vcp_grade: str, exit_sig: str) -> str:
    if "Exit" in exit_sig:
        return "Trim / exit per 21-EMA rule"
    if "Stage 2" in stage and "Strong" in vcp_grade:
        return "High-conviction swing — plan 10% stop"
    if mode == "sector_leader":
        return "Sector leader — buy strength, not dips"
    if vcp_grade != "Weak / none":
        return "VCP watch — buy pivot breakout"
    return "Watchlist — confirm on monthly chart"


def scan_financially_free(
    scan_source: str,
    filters: FinanciallyFreeFilters | None = None,
    progress_cb: Optional[ProgressCb] = None,
    *,
    info_delay_sec: float = 0.08,
) -> list[FinanciallyFreeResult]:
    flt = filters or FinanciallyFreeFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    tickers = [raw for _, raw in universe]
    bench_sym = benchmark_ticker_for(tickers[0] if tickers else "^NSEI")
    bench_hist: Optional[pd.DataFrame] = None
    try:
        bench_hist = yf.Ticker(bench_sym).history(period="1y", interval="1d", auto_adjust=True)
    except Exception:
        bench_hist = None

    results: list[FinanciallyFreeResult] = []
    total = len(universe)
    kw = (flt.sector_keyword or "").strip().lower()

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)

        hist = _fetch_hist(raw)
        if hist is None:
            continue

        try:
            stock = yf.Ticker(raw)
            info = stock.info or {}
        except Exception:
            info = {}

        sector, industry = get_sector_industry(stock)
        if kw and kw not in f"{sector} {industry}".lower():
            continue

        trend_pass, _passed, _failed, extra = _eval_trend_template(
            hist,
            min_pct_above_low=flt.min_pct_above_52w_low,
            max_pct_below_high=flt.max_pct_below_52w_high,
        )
        price = float(extra.get("price") or 0.0)
        vcp = _analyze_vcp(hist, price)
        rs_pp = (
            relative_strength_vs_benchmark(hist, bench_hist, bars=20)
            if bench_hist is not None
            else None
        )
        ema = _ema21_status(hist)
        if flt.require_above_21ema and not ema["above_21ema"]:
            continue

        fund = extract_multibagger_fundamentals(info)
        roce = fund.get("roce_pct")
        roe = normalize_return_pct(_gf(info, ("returnOnEquity",)))
        pct_below = extra.get("pct_below_52w_high")
        vcp_score = float(vcp.get("vcp_score") or 0.0)

        if not _passes_mode(
            flt.scan_mode,
            pct_below_high=pct_below,
            vcp_score=vcp_score,
            trend_pass=trend_pass,
            roce=roce,
            roe=roe,
            rs_pp=rs_pp,
            flt=flt,
        ):
            continue

        eps = _gf(info, ("trailingEps", "epsTrailingTwelveMonths"))
        eps_g = normalize_return_pct(
            _gf(info, ("earningsGrowth", "earningsQuarterlyGrowth"))
        )
        pe = get_pe(stock)
        stage = _infer_stage(trend_pass, extra, rs_rank=min(100.0, max(50.0, (rs_pp or 0) + 50)))
        disp = _display_ticker(raw)
        stop_px = round(price * (1.0 - flt.stop_loss_pct / 100.0), 2)
        rsi_14 = _daily_rsi_14(hist)
        monthly_rsi = _monthly_rsi_14(raw, stock)

        results.append(
            FinanciallyFreeResult(
                ticker=disp,
                raw_ticker=raw,
                label=label if label != disp else disp,
                sector=sector or "—",
                price=round(price, 2),
                pe=round(float(pe), 2) if pe is not None else None,
                eps=round(float(eps), 2) if eps is not None else None,
                eps_growth_pct=eps_g,
                roce_pct=roce,
                roe_pct=roe,
                pct_below_52w_high=pct_below,
                pct_above_52w_low=extra.get("pct_above_52w_low"),
                rs_vs_nifty_pp=round(float(rs_pp), 2) if rs_pp is not None else None,
                rsi_14=rsi_14,
                monthly_rsi_14=monthly_rsi,
                vcp_score=vcp_score,
                vcp_grade=str(vcp.get("vcp_grade") or "—"),
                trend_pass=trend_pass,
                stage_label=stage,
                ema21=ema.get("ema21"),
                pct_vs_21ema=ema.get("pct_vs_21ema"),
                above_21ema=bool(ema.get("above_21ema")),
                two_red_below_21ema=bool(ema.get("two_red_below_21ema")),
                exit_21ema=str(ema.get("exit_signal") or "—"),
                stop_price_10pct=stop_px,
                ff_score=_ff_score(
                    pct_below_high=pct_below,
                    rs_pp=rs_pp,
                    vcp_score=vcp_score,
                    roce=roce,
                    roe=roe,
                    above_21ema=bool(ema.get("above_21ema")),
                    trend_pass=trend_pass,
                ),
                scan_mode=flt.scan_mode,
                action_hint=_action_hint(
                    flt.scan_mode,
                    stage,
                    str(vcp.get("vcp_grade") or ""),
                    str(ema.get("exit_signal") or ""),
                ),
                links=get_stock_links(raw),
            )
        )

        if info_delay_sec > 0:
            time.sleep(info_delay_sec)

    return results


def sort_ff_results(
    results: list[FinanciallyFreeResult],
    *,
    rank_by: str = "ff_score",
) -> list[FinanciallyFreeResult]:
    if not results:
        return results

    def _key(r: FinanciallyFreeResult) -> float:
        if rank_by == "rs":
            return float(r.rs_vs_nifty_pp or -999.0)
        if rank_by == "near_high":
            return -float(r.pct_below_52w_high or 999.0)
        if rank_by == "vcp":
            return float(r.vcp_score or 0.0)
        if rank_by == "roce":
            return float(r.roce_pct or 0.0)
        return float(r.ff_score or 0.0)

    return sorted(results, key=_key, reverse=True)


def result_to_row(r: FinanciallyFreeResult, rank: int, stop_pct: float = 10.0) -> dict:
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Sector": r.sector,
        "FF score": r.ff_score,
        "Action": r.action_hint,
        "Stage": r.stage_label,
        "Price": r.price,
        "PE": r.pe,
        "EPS": r.eps,
        "EPS growth %": r.eps_growth_pct,
        "ROCE %": r.roce_pct,
        "ROE %": r.roe_pct,
        "% below 52w high": r.pct_below_52w_high,
        "RSI (14)": r.rsi_14,
        "Monthly RSI": r.monthly_rsi_14,
        "RS vs Nifty (pp)": r.rs_vs_nifty_pp,
        "VCP score": r.vcp_score,
        "VCP grade": r.vcp_grade,
        "Trend passes": r.trend_pass,
        "21-EMA": r.ema21,
        "vs 21-EMA %": r.pct_vs_21ema,
        "21-EMA rule": r.exit_21ema,
        f"Stop @ {int(stop_pct)}%": r.stop_price_10pct,
        **(r.links or {}),
    }
