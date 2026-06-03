"""
Stage 2 momentum + VCP screener — Minervini Trend Template & volatility contraction.

Educational screening only; pattern detection is algorithmic approximation of
Mark Minervini / Stan Weinstein principles (not a substitute for chart review).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from screener import (
    UNIVERSES,
    benchmark_ticker_for,
    get_stock_links,
    hist_series,
    relative_strength_vs_benchmark,
)

warnings.filterwarnings("ignore")

ProgressCb = Callable[[int, int, str], None]

META = {
    "id": "stage2_vcp",
    "title": "Stage 2 + VCP Momentum",
    "emoji": "🎯",
    "nav_title": "Stage 2 + VCP",
    "audience": (
        "Swing and position traders who want **Stage 2 uptrends** with **tightening bases (VCP)** "
        "before breakouts — explained in plain language on the page."
    ),
    "purpose": (
        "Scores each stock on Mark Minervini’s **8-point Trend Template**, optional **VCP-style** "
        "tightening + volume dry-up, and **relative strength vs the index**. Results are ranked for review — "
        "**not buy signals**."
    ),
}

TREND_TEMPLATE_RULES: list[tuple[str, str]] = [
    ("tt_price_ma", "Price above 150-day & 200-day moving averages"),
    ("tt_ma_align", "150-day MA is above 200-day MA"),
    ("tt_ma200_slope", "200-day MA is rising (at least ~1 month)"),
    ("tt_ma50_stack", "50-day MA is above 150-day & 200-day MAs"),
    ("tt_price_ma50", "Price is above the 50-day MA"),
    ("tt_above_low", "Price is at least 25% above its 52-week low"),
    ("tt_near_high", "Price is within 25% of its 52-week high"),
    ("tt_rs_rank", "Relative strength rank ≥ 70 in this scan (vs index)"),
]


@dataclass
class Stage2ScanFilters:
    min_trend_pass: int = 6
    min_vcp_score: float = 35.0
    min_rs_rank: float = 70.0
    min_pct_above_52w_low: float = 25.0
    max_pct_below_52w_high: float = 25.0
    require_vcp_tightening: bool = False
    require_volume_dryup: bool = False
    min_breakout_vol_ratio: float = 0.0
    stage2_only: bool = False


@dataclass
class Stage2MomentumResult:
    ticker: str
    raw_ticker: str
    price: float
    stage_label: str
    trend_pass: int
    trend_max: int = 8
    trend_checks: list[str] = field(default_factory=list)
    trend_failed: list[str] = field(default_factory=list)
    vcp_score: float = 0.0
    vcp_grade: str = "—"
    vcp_contractions: int = 0
    vcp_depths_pct: str = "—"
    volume_dryup: bool = False
    pivot_price: Optional[float] = None
    pct_from_pivot: Optional[float] = None
    pocket_pivot: bool = False
    rs_rank: float = 0.0
    rs_20d: Optional[float] = None
    pct_above_52w_low: Optional[float] = None
    pct_below_52w_high: Optional[float] = None
    ma50: Optional[float] = None
    ma150: Optional[float] = None
    ma200: Optional[float] = None
    vol_ratio_50d: Optional[float] = None
    composite_score: float = 0.0
    action_hint: str = "Watchlist"
    entry_hint: str = ""
    stop_hint: str = "Plan 7–8% max loss below entry before you buy."
    sell_hint: str = ""
    warnings: list[str] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)
    badge: str = ""


@dataclass
class Stage2ScanStats:
    universe: str
    tickers_scanned: int = 0
    tickers_matched: int = 0
    no_data: int = 0
    scan_elapsed_sec: float = 0.0


def _display_ticker(raw: str) -> str:
    return raw.replace(".NS", "").replace(".BO", "")


def _ma_series(closes: pd.Series, period: int) -> pd.Series:
    return closes.rolling(period, min_periods=period).mean()


def _eval_trend_template(
    hist: pd.DataFrame,
    *,
    min_pct_above_low: float,
    max_pct_below_high: float,
) -> tuple[int, list[str], list[str], dict[str, Any]]:
    closes = hist_series(hist, "Close")
    highs = hist_series(hist, "High")
    lows = hist_series(hist, "Low")
    if len(closes) < 200:
        return 0, [], ["Need ~200 trading days of history"], {}

    price = float(closes.iloc[-1])
    ma50 = _ma_series(closes, 50)
    ma150 = _ma_series(closes, 150)
    ma200 = _ma_series(closes, 200)
    m50 = float(ma50.iloc[-1])
    m150 = float(ma150.iloc[-1])
    m200 = float(ma200.iloc[-1])
    m200_1m = float(ma200.iloc[-22]) if len(ma200) >= 22 and pd.notna(ma200.iloc[-22]) else m200
    m200_4m = float(ma200.iloc[-105]) if len(ma200) >= 105 and pd.notna(ma200.iloc[-105]) else m200_1m

    win = closes.tail(252)
    win_h = highs.tail(252)
    win_l = lows.tail(252)
    low_52 = float(win_l.min()) if not win_l.empty else float(lows.min())
    high_52 = float(win_h.max()) if not win_h.empty else float(highs.max())
    pct_above_low = round((price / low_52 - 1.0) * 100.0, 1) if low_52 > 0 else None
    pct_below_high = round((1.0 - price / high_52) * 100.0, 1) if high_52 > 0 else None

    checks: list[tuple[str, bool]] = [
        ("Price above 150 & 200 DMA", price > m150 and price > m200),
        ("150 DMA above 200 DMA", m150 > m200),
        ("200 DMA rising (~1 month)", m200 > m200_1m),
        ("50 DMA above 150 & 200 DMA", m50 > m150 and m50 > m200),
        ("Price above 50 DMA", price > m50),
        (
            f"≥{min_pct_above_low:.0f}% above 52w low",
            pct_above_low is not None and pct_above_low >= min_pct_above_low,
        ),
        (
            f"Within {max_pct_below_high:.0f}% of 52w high",
            pct_below_high is not None and pct_below_high <= max_pct_below_high,
        ),
    ]

    passed = [label for label, ok in checks if ok]
    failed = [label for label, ok in checks if not ok]
    pass_n = len(passed)

    extra = {
        "price": price,
        "ma50": m50,
        "ma150": m150,
        "ma200": m200,
        "ma200_slope_4m": m200 > m200_4m,
        "pct_above_52w_low": pct_above_low,
        "pct_below_52w_high": pct_below_high,
        "low_52": low_52,
        "high_52": high_52,
    }
    return pass_n, passed, failed, extra


def _analyze_vcp(hist: pd.DataFrame, price: float) -> dict[str, Any]:
    """Approximate VCP: tightening pullbacks + volume dry-up near pivot."""
    out: dict[str, Any] = {
        "vcp_score": 0.0,
        "vcp_grade": "Weak / none",
        "vcp_contractions": 0,
        "vcp_depths_pct": "—",
        "volume_dryup": False,
        "pivot_price": None,
        "pct_from_pivot": None,
        "pocket_pivot": False,
        "tightening": False,
    }
    lookback = 90
    h = hist.tail(lookback)
    if len(h) < 45:
        return out

    highs = hist_series(h, "High")
    lows = hist_series(h, "Low")
    closes = hist_series(h, "Close")
    vols = hist_series(h, "Volume")

    peaks: list[int] = []
    for i in range(2, len(highs) - 2):
        if float(highs.iloc[i]) >= float(highs.iloc[i - 1]) and float(highs.iloc[i]) >= float(highs.iloc[i + 1]):
            peaks.append(i)

    depths: list[float] = []
    for pk in peaks[-8:]:
        seg_low = lows.iloc[pk : min(pk + 22, len(lows))]
        if len(seg_low) < 2:
            continue
        peak_px = float(highs.iloc[pk])
        trough = float(seg_low.min())
        if peak_px <= 0:
            continue
        depths.append(round((peak_px - trough) / peak_px * 100.0, 1))

    contractions = 0
    tightening = False
    if len(depths) >= 2:
        for j in range(1, len(depths)):
            if depths[j] < depths[j - 1] * 0.92:
                contractions += 1
        tightening = depths[-1] < depths[0] * 0.85

    vol_recent = float(vols.tail(15).mean()) if len(vols) >= 15 else float(vols.mean())
    vol_base = float(vols.iloc[: max(30, len(vols) // 2)].mean())
    volume_dryup = vol_recent < vol_base * 0.82 if vol_base > 0 else False

    pivot = float(highs.tail(25).max())
    pct_from_pivot = round((1.0 - price / pivot) * 100.0, 1) if pivot > 0 else None
    near_pivot = pct_from_pivot is not None and pct_from_pivot <= 8.0

    pocket = False
    if len(h) >= 12:
        last = h.iloc[-1]
        prev10 = h.iloc[-11:-1]
        if float(last["Close"]) >= float(last["Open"]):
            up_vol = float(last["Volume"])
            down_vols = [
                float(r["Volume"])
                for _, r in prev10.iterrows()
                if float(r["Close"]) < float(r["Open"])
            ]
            if down_vols and up_vol > max(down_vols) * 1.05:
                pocket = True

    score = 0.0
    score += min(30.0, contractions * 12.0)
    if tightening:
        score += 18.0
    if volume_dryup:
        score += 20.0
    if near_pivot:
        score += 17.0
    if pocket:
        score += 15.0
    if len(depths) >= 3 and all(depths[i] <= depths[i - 1] for i in range(1, len(depths))):
        score += 10.0
    score = min(100.0, round(score, 1))

    if score >= 70:
        grade = "Strong VCP setup"
    elif score >= 50:
        grade = "Developing VCP"
    elif score >= 35:
        grade = "Early base / loose"
    else:
        grade = "Weak / none"

    depths_str = " → ".join(f"{d:.0f}%" for d in depths[-4:]) if depths else "—"

    out.update(
        vcp_score=score,
        vcp_grade=grade,
        vcp_contractions=contractions,
        vcp_depths_pct=depths_str,
        volume_dryup=volume_dryup,
        pivot_price=round(pivot, 2),
        pct_from_pivot=pct_from_pivot,
        pocket_pivot=pocket,
        tightening=tightening,
    )
    return out


def _infer_stage(
    trend_pass: int,
    extra: dict[str, Any],
    *,
    rs_rank: float,
) -> str:
    price = extra.get("price") or 0.0
    m200 = extra.get("ma200") or 0.0
    m200_up = extra.get("ma200_slope_4m", False)
    pct_below = extra.get("pct_below_52w_high")

    if m200 and price < m200 and not m200_up:
        return "Stage 4 — Capitulation (do not buy)"
    if trend_pass >= 7 and m200_up:
        return "Stage 2 — Advancing (primary buy zone)"
    if trend_pass >= 5 and m200_up:
        return "Stage 1 → 2 — Base / early advance (watch)"
    if pct_below is not None and pct_below < 8 and trend_pass >= 5:
        return "Stage 3 risk — Near highs (protect profits)"
    if trend_pass >= 4:
        return "Stage 1 — Consolidation (watch for breakout)"
    return "Unclear — review chart manually"


def _action_hints(
    stage: str,
    vcp: dict[str, Any],
    extra: dict[str, Any],
    trend_pass: int,
) -> tuple[str, str, str, str, list[str]]:
    warnings: list[str] = []
    pct_pivot = vcp.get("pct_from_pivot")
    near_breakout = pct_pivot is not None and pct_pivot <= 5.0

    if "Stage 4" in stage:
        return (
            "Avoid",
            "Do not enter — wait for Stage 2 template to rebuild.",
            "If stuck in a loser: exit; never average down in Stage 4.",
            "N/A until trend repairs.",
            ["Cardinal sin: averaging down in a downtrend."],
        )

    entry = (
        "Buy only on a **breakout above the pivot** with volume ≥ ~40–50% above the 50-day average — "
        "or a validated **pocket pivot** inside the base."
    )
    if near_breakout and vcp.get("pocket_pivot"):
        entry = "Near pivot with pocket-pivot volume — **early entry zone** (higher skill; smaller size)."
    elif near_breakout:
        entry = "Price near pivot — **set alert** for breakout + volume surge before full size."
    elif vcp.get("vcp_score", 0) < 40:
        entry = "VCP not tight yet — **watch only**; forcing trades without contraction is a common mistake."
        warnings.append("No strong volatility contraction detected.")

    stop = "Before buying: plan a **7–8% stop** below your entry (non-negotiable risk cap)."
    sell = (
        "After +2R to +3R: consider partial profit; trail with **20-day or 50-day MA**. "
        "Sell into late-stage exhaustion (many up-days, parabolic extension)."
    )

    if trend_pass < 6:
        warnings.append("Trend Template incomplete — higher false-breakout risk.")

    if "Stage 3" in stage:
        action = "Hold / trim only"
        warnings.append("Distribution risk near highs — avoid new full-size entries.")
    elif trend_pass >= 7 and vcp.get("vcp_score", 0) >= 55:
        action = "High-conviction watch"
    elif trend_pass >= 6:
        action = "Watchlist — wait for pivot break"
    else:
        action = "Watchlist"

    return action, entry, stop, sell, warnings


def _vol_ratio_vs_50d(hist: pd.DataFrame) -> Optional[float]:
    vols = hist_series(hist, "Volume")
    if len(vols) < 55:
        return None
    avg50 = float(vols.tail(50).mean())
    last = float(vols.iloc[-1])
    if avg50 <= 0:
        return None
    return round(last / avg50, 2)


def _composite_score(trend_pass: int, vcp_score: float, rs_rank: float) -> float:
    tt = (trend_pass / 8.0) * 42.0
    vcp = vcp_score * 0.33
    rs = rs_rank * 0.25
    return round(min(100.0, tt + vcp + rs), 1)


def _fetch_hist(raw: str) -> Optional[pd.DataFrame]:
    try:
        hist = yf.Ticker(raw).history(period="2y", interval="1d", auto_adjust=True)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    hist = hist.dropna(subset=["Close", "High", "Low"], how="any")
    if len(hist) < 120:
        return None
    return hist


def scan_stage2_momentum(
    universe_name: str,
    filters: Optional[Stage2ScanFilters] = None,
    *,
    progress_cb: Optional[ProgressCb] = None,
    tickers_override: Optional[list[str]] = None,
) -> tuple[list[Stage2MomentumResult], Stage2ScanStats]:
    import time

    flt = filters or Stage2ScanFilters()
    tickers = list(tickers_override or UNIVERSES.get(universe_name, []))
    stats = Stage2ScanStats(universe=universe_name, tickers_scanned=len(tickers))
    t0 = time.time()

    bench_sym = benchmark_ticker_for(tickers[0] if tickers else "^NSEI")
    bench_hist: Optional[pd.DataFrame] = None
    try:
        bench_hist = yf.Ticker(bench_sym).history(period="1y", interval="1d", auto_adjust=True)
    except Exception:
        bench_hist = None

    raw_rows: list[dict[str, Any]] = []

    for i, raw in enumerate(tickers):
        if progress_cb:
            progress_cb(i + 1, len(tickers), _display_ticker(raw))

        hist = _fetch_hist(raw)
        if hist is None:
            stats.no_data += 1
            continue

        trend_pass, passed, failed, extra = _eval_trend_template(
            hist,
            min_pct_above_low=flt.min_pct_above_52w_low,
            max_pct_below_high=flt.max_pct_below_52w_high,
        )
        if trend_pass < flt.min_trend_pass:
            continue

        price = float(extra.get("price") or 0.0)
        vcp = _analyze_vcp(hist, price)
        if flt.min_vcp_score and vcp["vcp_score"] < flt.min_vcp_score:
            continue
        if flt.require_vcp_tightening and not vcp.get("tightening"):
            continue
        if flt.require_volume_dryup and not vcp.get("volume_dryup"):
            continue

        vol_ratio = _vol_ratio_vs_50d(hist)
        if flt.min_breakout_vol_ratio > 0 and (vol_ratio is None or vol_ratio < flt.min_breakout_vol_ratio):
            continue

        rs_20d = relative_strength_vs_benchmark(hist, bench_hist, bars=20) if bench_hist is not None else None

        raw_rows.append(
            {
                "raw": raw,
                "hist": hist,
                "trend_pass": trend_pass,
                "passed": passed,
                "failed": failed,
                "extra": extra,
                "vcp": vcp,
                "rs_20d": rs_20d,
                "vol_ratio": vol_ratio,
            }
        )

    if not raw_rows:
        stats.scan_elapsed_sec = time.time() - t0
        return [], stats

    rs_vals = [r["rs_20d"] for r in raw_rows if r["rs_20d"] is not None]
    rs_sorted = sorted(rs_vals)
    n_rs = len(rs_sorted)

    def _rs_percentile(val: Optional[float]) -> float:
        if val is None or n_rs == 0:
            return 50.0
        below = sum(1 for x in rs_sorted if x <= val)
        return round(100.0 * below / n_rs, 1)

    results: list[Stage2MomentumResult] = []
    for row in raw_rows:
        raw = row["raw"]
        extra = row["extra"]
        vcp = row["vcp"]
        rs_20d = row["rs_20d"]
        rs_rank = _rs_percentile(rs_20d)

        trend_pass = row["trend_pass"]
        if rs_rank < flt.min_rs_rank:
            continue

        trend_pass_full = trend_pass + (1 if rs_rank >= flt.min_rs_rank else 0)
        passed = list(row["passed"])
        failed = list(row["failed"])
        if rs_rank >= flt.min_rs_rank:
            passed.append(f"RS rank {rs_rank:.0f} (this scan)")
        else:
            failed.append(f"RS rank {rs_rank:.0f} (need ≥{flt.min_rs_rank:.0f})")

        stage = _infer_stage(trend_pass_full, extra, rs_rank=rs_rank)
        if flt.stage2_only and "Stage 2" not in stage:
            continue

        action, entry, stop, sell, warnings = _action_hints(stage, vcp, extra, trend_pass_full)
        comp = _composite_score(trend_pass_full, float(vcp["vcp_score"]), rs_rank)
        price = float(extra.get("price") or 0.0)

        badge = "🏆 Stage 2" if "Stage 2" in stage else ("⚠️ Stage 3/4 risk" if "Stage 3" in stage or "Stage 4" in stage else "👀 Watch")

        results.append(
            Stage2MomentumResult(
                ticker=_display_ticker(raw),
                raw_ticker=raw,
                price=round(price, 2),
                stage_label=stage,
                trend_pass=trend_pass_full,
                trend_checks=passed,
                trend_failed=failed,
                vcp_score=float(vcp["vcp_score"]),
                vcp_grade=str(vcp["vcp_grade"]),
                vcp_contractions=int(vcp["vcp_contractions"]),
                vcp_depths_pct=str(vcp["vcp_depths_pct"]),
                volume_dryup=bool(vcp["volume_dryup"]),
                pivot_price=vcp.get("pivot_price"),
                pct_from_pivot=vcp.get("pct_from_pivot"),
                pocket_pivot=bool(vcp.get("pocket_pivot")),
                rs_rank=rs_rank,
                rs_20d=rs_20d,
                pct_above_52w_low=extra.get("pct_above_52w_low"),
                pct_below_52w_high=extra.get("pct_below_52w_high"),
                ma50=round(float(extra["ma50"]), 2) if extra.get("ma50") else None,
                ma150=round(float(extra["ma150"]), 2) if extra.get("ma150") else None,
                ma200=round(float(extra["ma200"]), 2) if extra.get("ma200") else None,
                vol_ratio_50d=row.get("vol_ratio"),
                composite_score=comp,
                action_hint=action,
                entry_hint=entry,
                stop_hint=stop,
                sell_hint=sell,
                warnings=warnings,
                links=get_stock_links(raw),
                badge=badge,
            )
        )

    results.sort(key=lambda r: (-r.composite_score, -r.trend_pass, -r.vcp_score, -r.rs_rank))
    stats.tickers_matched = len(results)
    stats.tickers_scanned = len(tickers)
    stats.scan_elapsed_sec = round(time.time() - t0, 2)
    return results, stats
