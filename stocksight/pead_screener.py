"""
PEAD (Post-Earnings Announcement Drift) screener.

Computes **Standardized Unexpected Earnings (SUE)** from quarterly PAT using a
seasonal model (actual vs same quarter prior year), measures **post-result price
drift**, and ranks names for long (SUE ≥ +2) or short (SUE ≤ −2) setups.

NSE: Screener.in quarterly Sales+ / Net Profit+; Yahoo price/volume.
US: Yahoo quarterly P&L + price history.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from .earnings_surprise_screener import (
        PROFIT_ROW_CANDIDATES,
        REVENUE_ROW_CANDIDATES,
        _pick_row,
        _qoq_pct,
    )
    from .multibagger import (
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        resolve_scan_tickers,
    )
    from .screener import get_pe, get_sector_industry, get_stock_links, hist_series
except ImportError:
    from earnings_surprise_screener import (
        PROFIT_ROW_CANDIDATES,
        REVENUE_ROW_CANDIDATES,
        _pick_row,
        _qoq_pct,
    )
    from multibagger import (
        SCAN_SOURCES,
        extract_multibagger_fundamentals,
        resolve_scan_tickers,
    )
    from screener import get_pe, get_sector_industry, get_stock_links, hist_series

META = {
    "id": "pead_screener",
    "title": "PEAD — Post-Earnings Drift",
    "emoji": "📈",
    "nav_title": "PEAD Screener",
    "audience": (
        "Screen for **post-earnings announcement drift** — stocks with large "
        "**standardized earnings surprises (SUE)** where price may continue drifting "
        "30–60 trading days after results."
    ),
    "purpose": (
        "Computes **SUE** from quarterly PAT (actual vs same quarter prior year), "
        "filters by **liquidity / market cap**, measures **post-result returns** "
        "(3d / 5d / 20d), and suggests **optimal SUE thresholds** for your universe."
    ),
}

RANK_BY_OPTIONS: dict[str, str] = {
    "pead_score": "PEAD score (SUE + drift alignment)",
    "sue": "SUE (highest magnitude)",
    "post_20d": "Post-result 20d return %",
    "post_5d": "Post-result 5d return %",
    "volume_spike": "Volume spike vs pre-earn",
    "mcap": "Market cap (largest)",
}

DIRECTION_OPTIONS = {
    "long": "Long — positive surprise (SUE ≥ threshold)",
    "short": "Short — negative surprise (SUE ≤ −threshold)",
    "both": "Both — extreme surprises either side",
}


@dataclass
class PEADFilters:
    direction: str = "long"
    min_sue: float = 1.0
    max_days_since_results: int = 120
    min_market_cap_cr: float = 300.0
    min_avg_daily_value_cr: float = 1.0
    min_post_5d_confirm_pct: Optional[float] = None
    require_volume_spike: bool = False
    min_volume_spike_ratio: float = 1.25
    recent_reporters_only: bool = False
    relaxed_scan: bool = False
    info_delay_sec: float = 0.05
    screener_delay_sec: float = 0.12


@dataclass
class PEADResult:
    ticker: str
    raw_ticker: str
    label: str
    sector: str
    price: float
    pe: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    latest_q: str
    result_date_est: Optional[date]
    days_since_results: Optional[int]
    actual_pat_cr: Optional[float]
    expected_pat_cr: Optional[float]
    pat_surprise_cr: Optional[float]
    sue: Optional[float]
    sue_sales: Optional[float]
    qoq_sales_pct: Optional[float]
    qoq_profit_pct: Optional[float]
    avg_daily_value_cr: Optional[float]
    volume_spike_ratio: Optional[float]
    pre_5d_return_pct: Optional[float]
    post_1d_return_pct: Optional[float]
    post_3d_return_pct: Optional[float]
    post_5d_return_pct: Optional[float]
    post_20d_return_pct: Optional[float]
    pead_score: float
    verdict: str
    pass_notes: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)
    data_source: str = ""


@dataclass
class PEADCriteriaRow:
    threshold: float
    direction: str
    count: int
    avg_post_5d_pct: Optional[float]
    avg_post_20d_pct: Optional[float]
    median_sue: Optional[float]
    score: float


def _is_indian_ticker(raw: str) -> bool:
    return raw.endswith(".NS") or raw.endswith(".BO")


def _screener_links(disp: str) -> dict:
    slug = disp.replace(".NS", "").replace(".BO", "")
    return {"Screener.in": f"https://www.screener.in/company/{slug}/consolidated/"}


def compute_sue_from_pat_series(pat_values: list[Optional[float]]) -> tuple[Optional[float], Optional[float], Optional[float], list[float]]:
    """
    SUE from quarterly PAT using YoY % surprise / σ(past YoY % surprises).

    Falls back to absolute PAT surprise when % series is too thin.
  """
    clean = [float(v) if v is not None else np.nan for v in pat_values]
    surprises_pct: list[float] = []
    surprises_abs: list[float] = []
    for i in range(4, len(clean)):
        actual = clean[i]
        expected = clean[i - 4]
        if np.isnan(actual) or np.isnan(expected):
            continue
        surprises_abs.append(actual - expected)
        if abs(expected) >= 0.01:
            surprises_pct.append((actual - expected) / abs(expected) * 100.0)
        elif abs(actual) >= 0.01:
            surprises_pct.append(100.0 if actual > 0 else -100.0)

    if len(surprises_pct) >= 2:
        latest = surprises_pct[-1]
        hist = surprises_pct[:-1]
        std = float(np.std(hist, ddof=1)) if len(hist) > 1 else float(np.std(hist, ddof=0))
        std = max(std, 5.0)
        latest_abs = surprises_abs[-1] if surprises_abs else None
        return round(latest / std, 2), latest_abs, std, surprises_pct

    if len(surprises_abs) < 2:
        return None, None, None, surprises_abs

    latest = surprises_abs[-1]
    hist = surprises_abs[:-1]
    std = float(np.std(hist, ddof=1)) if len(hist) > 1 else float(np.std(hist, ddof=0))
    std = max(std, 0.05)
    return round(latest / std, 2), latest, std, surprises_abs


def extract_yahoo_quarterly_series(stock: yf.Ticker) -> list[dict]:
    """Yahoo quarterly revenue & profit series oldest → newest."""
    qf = getattr(stock, "quarterly_financials", None)
    if qf is None or (hasattr(qf, "empty") and qf.empty):
        qf = getattr(stock, "quarterly_income_stmt", None)
    if qf is None or qf.empty or qf.shape[1] < 2:
        return []

    cols = list(qf.columns)
    try:
        cols = sorted(cols)
    except Exception:
        pass

    rev = _pick_row(qf, REVENUE_ROW_CANDIDATES)
    profit = _pick_row(qf, PROFIT_ROW_CANDIDATES)
    if rev is None or profit is None:
        return []

    out: list[dict] = []
    for col in cols:
        try:
            s = float(rev[col])
            p = float(profit[col])
        except (TypeError, ValueError, KeyError):
            continue
        try:
            lbl = pd.Timestamp(col).strftime("%b %Y")
            q_end = pd.Timestamp(col).date()
        except Exception:
            lbl = str(col)[:10]
            q_end = None
        out.append({
            "label": lbl,
            "sales_cr": round(s / 1e7, 2) if abs(s) > 1e6 else s,
            "profit_cr": round(p / 1e7, 2) if abs(p) > 1e6 else p,
            "quarter_end": q_end,
            "est_announce_date": (q_end + timedelta(days=45)) if q_end else None,
        })
    return out


def _return_pct_between(closes: pd.Series, start_idx: int, end_idx: int) -> Optional[float]:
    if start_idx < 0 or end_idx >= len(closes) or start_idx >= end_idx:
        return None
    s = float(closes.iloc[start_idx])
    e = float(closes.iloc[end_idx])
    if s <= 0:
        return None
    return round((e / s - 1.0) * 100.0, 2)


def post_announcement_metrics(
    hist: pd.DataFrame,
    announce_date: date,
    *,
    currency_inr: bool = True,
) -> dict:
    """Pre/post returns and volume spike around estimated result date."""
    if hist is None or hist.empty:
        return {}

    closes = hist_series(hist, "Close").dropna()
    vols = hist_series(hist, "Volume").dropna()
    if closes.empty:
        return {}

    idx = closes.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            closes.index = idx
            vols.index = idx
        except Exception:
            return {}

    ann_ts = pd.Timestamp(announce_date)
    on_or_after = closes.index.searchsorted(ann_ts, side="left")
    if on_or_after >= len(closes):
        on_or_after = len(closes) - 1
    if on_or_after <= 0:
        return {}

    def _window_ret(days: int) -> Optional[float]:
        end_i = min(on_or_after + days, len(closes) - 1)
        return _return_pct_between(closes, on_or_after, end_i)

    pre_start = max(0, on_or_after - 6)
    pre_end = max(0, on_or_after - 1)
    pre_ret = _return_pct_between(closes, pre_start, pre_end) if pre_end > pre_start else None

    post_1d = _return_pct_between(closes, on_or_after, min(on_or_after + 1, len(closes) - 1))
    post_3d = _window_ret(3)
    post_5d = _window_ret(5)
    post_20d = _window_ret(20)

    vol_spike = None
    if not vols.empty and on_or_after + 5 < len(vols):
        pre_vol = float(vols.iloc[max(0, on_or_after - 20):on_or_after].mean())
        post_vol = float(vols.iloc[on_or_after:min(on_or_after + 5, len(vols))].mean())
        if pre_vol > 0:
            vol_spike = round(post_vol / pre_vol, 2)

    avg_val = None
    if not vols.empty and len(vols) >= 25:
        tail = min(25, len(vols))
        avg_vol = float(vols.iloc[-tail:].mean())
        avg_px = float(closes.iloc[-tail:].mean())
        if currency_inr:
            avg_val = round(avg_vol * avg_px / 1e7, 2)
        else:
            avg_val = round(avg_vol * avg_px / 1e6, 2)

    days_since = (date.today() - announce_date).days

    return {
        "pre_5d_return_pct": pre_ret,
        "post_1d_return_pct": post_1d,
        "post_3d_return_pct": post_3d,
        "post_5d_return_pct": post_5d,
        "post_20d_return_pct": post_20d,
        "volume_spike_ratio": vol_spike,
        "avg_daily_value_cr": avg_val,
        "days_since_results": days_since,
    }


def _pead_score(
    sue: Optional[float],
    direction: str,
    post_5d: Optional[float],
    post_20d: Optional[float],
    vol_spike: Optional[float],
) -> float:
    s = float(sue or 0.0)
    mag = abs(s)
    drift = float(post_20d or post_5d or 0.0)
    if direction == "long":
        align = drift if s >= 0 else -abs(drift)
    elif direction == "short":
        align = -drift if s <= 0 else -abs(drift)
    else:
        align = drift if s >= 0 else -drift
    vol_pts = min(float(vol_spike or 1.0), 3.0) * 4.0
    return round(mag * 12.0 + align * 0.55 + vol_pts, 1)


def _verdict(sue: Optional[float], direction: str, post_5d: Optional[float], post_20d: Optional[float]) -> str:
    s = float(sue or 0.0)
    p5 = float(post_5d or 0.0)
    p20 = float(post_20d or 0.0)
    if direction == "long" or (direction == "both" and s >= 0):
        if s >= 2.5 and p20 >= 3:
            return "Strong long drift — top-decile SUE + follow-through"
        if s >= 2.0 and p5 >= 0:
            return "Long PEAD — positive surprise, early drift"
        if s >= 2.0:
            return "Long setup — surprise in, drift may be starting"
    if direction == "short" or (direction == "both" and s < 0):
        if s <= -2.5 and p20 <= -3:
            return "Strong short drift — worst-decile SUE + follow-through"
        if s <= -2.0 and p5 <= 0:
            return "Short PEAD — negative surprise, early drift"
        if s <= -2.0:
            return "Short setup — miss priced, drift may continue"
    return "Watch — confirm volume + sector trend"


def _passes_filters(
    sue: Optional[float],
    metrics: dict,
    fund: dict,
    flt: PEADFilters,
) -> tuple[bool, list[str]]:
    notes: list[str] = []
    if sue is None:
        return False, notes

    if not flt.relaxed_scan:
        direction = flt.direction
        if direction == "long" and sue < flt.min_sue:
            return False, notes
        if direction == "short" and sue > -flt.min_sue:
            return False, notes
        if direction == "both" and abs(sue) < flt.min_sue:
            return False, notes
    notes.append(f"SUE {sue:+.2f}")

    direction = flt.direction
    days = metrics.get("days_since_results")
    if days is not None and days < 0:
        return False, notes
    if days is None or days > flt.max_days_since_results:
        return False, notes
    if days is not None:
        notes.append(f"~{days}d since est. result")

    mcap = fund.get("market_cap_cr")
    if mcap is None or mcap < flt.min_market_cap_cr:
        return False, notes
    notes.append(f"Mcap ₹{mcap:.0f} Cr" if mcap else "Mcap OK")

    adv = metrics.get("avg_daily_value_cr")
    if adv is not None and adv < flt.min_avg_daily_value_cr:
        return False, notes
    if adv is not None:
        notes.append(f"Avg daily ₹{adv:.1f} Cr traded")

    if flt.min_post_5d_confirm_pct is not None:
        p5 = metrics.get("post_5d_return_pct")
        if p5 is None:
            return False, notes
        if direction == "long" and p5 < flt.min_post_5d_confirm_pct:
            return False, notes
        if direction == "short" and p5 > -flt.min_post_5d_confirm_pct:
            return False, notes
        notes.append(f"Post-5d {p5:+.1f}%")

    if flt.require_volume_spike:
        vs = metrics.get("volume_spike_ratio")
        if vs is None or vs < flt.min_volume_spike_ratio:
            return False, notes
        notes.append(f"Vol spike {vs:.2f}×")

    return True, notes


def _latest_announced_quarter(series: list[dict]) -> Optional[dict]:
    """Most recent quarter whose estimated result date has passed."""
    today = date.today()
    announced = [
        s for s in series
        if s.get("est_announce_date") and s["est_announce_date"] <= today
    ]
    return announced[-1] if announced else None


def _series_from_screener_or_yahoo(
    raw: str,
    stock: yf.Ticker,
    screener_html: str,
    disp: str,
) -> tuple[list[dict], str]:
    if _is_indian_ticker(raw):
        try:
            from screener_in_data import fetch_screener_quarterly_series

            series = fetch_screener_quarterly_series(disp, html=screener_html)
            if series:
                return series, "Screener.in quarterly"
        except Exception:
            pass
    series = extract_yahoo_quarterly_series(stock)
    if series:
        return series, "Yahoo Finance quarterly P&L"
    return [], ""


def _recent_reporter_tickers() -> set[str]:
    try:
        from screener_in_data import fetch_screener_results_latest

        rows = fetch_screener_results_latest(max_rows=250)
        return {r["symbol"].upper() for r in rows}
    except Exception:
        return set()


def scan_pead(
    scan_source: str,
    filters: PEADFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[PEADResult]:
    flt = filters or PEADFilters()
    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    recent_syms = _recent_reporter_tickers() if flt.recent_reporters_only else set()
    results: list[PEADResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)

        try:
            disp = raw.replace(".NS", "").replace(".BO", "")
            if recent_syms and disp.upper() not in recent_syms:
                continue

            stock = yf.Ticker(raw)
            try:
                info = stock.info or {}
            except Exception:
                info = {}
            if not info.get("symbol") and not info.get("shortName"):
                continue

            screener_html = ""
            if _is_indian_ticker(raw):
                try:
                    from screener_in_data import fetch_screener_company_html

                    screener_html = fetch_screener_company_html(disp)
                    if flt.screener_delay_sec > 0:
                        time.sleep(flt.screener_delay_sec)
                except Exception:
                    pass

            series, data_source = _series_from_screener_or_yahoo(raw, stock, screener_html, disp)
            if len(series) < 5:
                continue

            pat_vals = [r.get("profit_cr") for r in series]
            sales_vals = [r.get("sales_cr") for r in series]
            sue, surprise, _std, _ = compute_sue_from_pat_series(pat_vals)
            sue_sales, _, _, _ = compute_sue_from_pat_series(sales_vals)

            latest = _latest_announced_quarter(series)
            if latest is None:
                continue
            try:
                latest_idx = series.index(latest)
            except ValueError:
                latest_idx = len(series) - 1
            prior = series[latest_idx - 1] if latest_idx > 0 else {}
            q_end = latest.get("quarter_end")
            ann_date = latest.get("est_announce_date")
            if ann_date is None and q_end is not None:
                ann_date = q_end + timedelta(days=45)

            fund = extract_multibagger_fundamentals(info)
            if _is_indian_ticker(raw) and screener_html:
                try:
                    from screener_in_data import enrich_fundamentals_from_screener, fetch_screener_value_profile

                    fund = enrich_fundamentals_from_screener(disp, fund, html=screener_html)
                    vp = fetch_screener_value_profile(disp, html=screener_html)
                    if vp.get("market_cap_cr") is not None:
                        fund["market_cap_cr"] = vp["market_cap_cr"]
                except Exception:
                    pass

            price = float(info.get("regularMarketPrice") or info.get("currentPrice") or 0.0)
            if price <= 0:
                continue

            metrics: dict = {}
            try:
                hist = stock.history(period="2y", interval="1d", auto_adjust=True)
                if ann_date:
                    metrics = post_announcement_metrics(
                        hist,
                        ann_date,
                        currency_inr=_is_indian_ticker(raw),
                    )
            except Exception:
                pass
            if ann_date and metrics.get("days_since_results") is None:
                metrics["days_since_results"] = (date.today() - ann_date).days

            ok, notes = _passes_filters(sue, metrics, fund, flt)
            if not ok:
                continue

            sector, _ = get_sector_industry(stock)
            links = get_stock_links(raw)
            if _is_indian_ticker(raw):
                links = {**links, **_screener_links(disp)}

            expected_pat = None
            if len(pat_vals) >= 5 and pat_vals[-5] is not None:
                expected_pat = pat_vals[-5]

            pe = get_pe(stock)
            score = _pead_score(
                sue,
                flt.direction,
                metrics.get("post_5d_return_pct"),
                metrics.get("post_20d_return_pct"),
                metrics.get("volume_spike_ratio"),
            )
            verdict = _verdict(
                sue,
                flt.direction,
                metrics.get("post_5d_return_pct"),
                metrics.get("post_20d_return_pct"),
            )

            results.append(
                PEADResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    sector=sector or "—",
                    price=round(price, 2),
                    pe=round(float(pe), 2) if pe is not None else None,
                    market_cap_cr=fund.get("market_cap_cr"),
                    market_cap_display=fund.get("market_cap_display") or "",
                    latest_q=str(latest.get("label") or "—"),
                    result_date_est=ann_date,
                    days_since_results=metrics.get("days_since_results"),
                    actual_pat_cr=pat_vals[-1] if pat_vals else None,
                    expected_pat_cr=expected_pat,
                    pat_surprise_cr=surprise,
                    sue=sue,
                    sue_sales=sue_sales,
                    qoq_sales_pct=_qoq_pct(latest.get("sales_cr"), prior.get("sales_cr")),
                    qoq_profit_pct=_qoq_pct(latest.get("profit_cr"), prior.get("profit_cr")),
                    avg_daily_value_cr=metrics.get("avg_daily_value_cr"),
                    volume_spike_ratio=metrics.get("volume_spike_ratio"),
                    pre_5d_return_pct=metrics.get("pre_5d_return_pct"),
                    post_1d_return_pct=metrics.get("post_1d_return_pct"),
                    post_3d_return_pct=metrics.get("post_3d_return_pct"),
                    post_5d_return_pct=metrics.get("post_5d_return_pct"),
                    post_20d_return_pct=metrics.get("post_20d_return_pct"),
                    pead_score=score,
                    verdict=verdict,
                    pass_notes=notes,
                    links=links,
                    data_source=data_source,
                )
            )
        except Exception:
            continue

        if flt.info_delay_sec > 0:
            time.sleep(flt.info_delay_sec)

    return sort_pead_results(results, rank_by="pead_score")


def scan_pead_for_criteria(
    scan_source: str,
    *,
    direction: str = "long",
    max_days_since_results: int = 150,
    min_market_cap_cr: float = 100.0,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[PEADResult]:
    """Loose scan to discover optimal SUE thresholds (ignores min_sue)."""
    flt = PEADFilters(
        direction=direction,
        min_sue=0.0,
        max_days_since_results=max_days_since_results,
        min_market_cap_cr=min_market_cap_cr,
        min_avg_daily_value_cr=0.0,
        require_volume_spike=False,
        relaxed_scan=True,
    )
    return scan_pead(scan_source, filters=flt, progress_cb=progress_cb)


def analyze_pead_criteria(
    results: list[PEADResult],
    *,
    direction: str = "long",
) -> list[PEADCriteriaRow]:
    """
    Sweep SUE thresholds and rank by average post-20d drift.

    Helps answer: what SUE cutoff works best in this universe?
    """
    thresholds = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    rows: list[PEADCriteriaRow] = []

    for thr in thresholds:
        if direction == "long":
            subset = [r for r in results if (r.sue or 0) >= thr]
        elif direction == "short":
            subset = [r for r in results if (r.sue or 0) <= -thr]
        else:
            subset = [r for r in results if abs(r.sue or 0) >= thr]

        if not subset:
            continue

        p5 = [r.post_5d_return_pct for r in subset if r.post_5d_return_pct is not None]
        p20 = [r.post_20d_return_pct for r in subset if r.post_20d_return_pct is not None]
        sues = [r.sue for r in subset if r.sue is not None]

        avg5 = round(float(np.mean(p5)), 2) if p5 else None
        avg20 = round(float(np.mean(p20)), 2) if p20 else None
        med_sue = round(float(np.median(sues)), 2) if sues else None

        if direction == "short":
            score = -(avg20 or avg5 or 0.0) * len(subset) ** 0.5
        else:
            score = (avg20 or avg5 or 0.0) * len(subset) ** 0.5

        rows.append(
            PEADCriteriaRow(
                threshold=thr,
                direction=direction,
                count=len(subset),
                avg_post_5d_pct=avg5,
                avg_post_20d_pct=avg20,
                median_sue=med_sue,
                score=round(score, 2),
            )
        )

    return sorted(rows, key=lambda x: x.score, reverse=True)


def best_pead_threshold(criteria_rows: list[PEADCriteriaRow], *, min_count: int = 3) -> Optional[float]:
    eligible = [r for r in criteria_rows if r.count >= min_count]
    if not eligible:
        return None
    return eligible[0].threshold


def sort_pead_results(
    results: list[PEADResult],
    *,
    rank_by: str = "pead_score",
) -> list[PEADResult]:
    if rank_by == "sue":
        key = lambda r: abs(float(r.sue or 0.0))
    elif rank_by == "post_20d":
        key = lambda r: float(r.post_20d_return_pct or -9999.0)
    elif rank_by == "post_5d":
        key = lambda r: float(r.post_5d_return_pct or -9999.0)
    elif rank_by == "volume_spike":
        key = lambda r: float(r.volume_spike_ratio or 0.0)
    elif rank_by == "mcap":
        key = lambda r: float(r.market_cap_cr or 0.0)
    else:
        key = lambda r: float(r.pead_score or 0.0)
    return sorted(results, key=key, reverse=True)


def result_to_row(r: PEADResult, rank: int) -> dict:
    res_dt = r.result_date_est.isoformat() if r.result_date_est else "—"
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "PEAD score": r.pead_score,
        "SUE": r.sue,
        "SUE sales": r.sue_sales,
        "Verdict": r.verdict,
        "Latest Q": r.latest_q,
        "Est result": res_dt,
        "Days since": r.days_since_results,
        "QoQ sales %": r.qoq_sales_pct,
        "QoQ profit %": r.qoq_profit_pct,
        "Post 1d %": r.post_1d_return_pct,
        "Post 5d %": r.post_5d_return_pct,
        "Post 20d %": r.post_20d_return_pct,
        "Pre 5d %": r.pre_5d_return_pct,
        "Vol spike ×": r.volume_spike_ratio,
        "Avg daily ₹Cr": r.avg_daily_value_cr,
        "Price": r.price,
        "P/E": r.pe,
        "Mcap": r.market_cap_display,
        "Sector": r.sector,
        "Notes": " · ".join(r.pass_notes[:4]),
        "Data": r.data_source or "—",
    }
