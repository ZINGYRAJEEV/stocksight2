"""
Volume Gravity screener — VWAP, RVOL, Volume Profile (POC/VA), ORB synthesis.

Modes:
  - intraday: session VWAP, opening range, gap-and-go (Minervini-style volume conviction)
  - swing: daily POC/VA, multi-day VWAP proxy, gap structure on daily bars

Educational only — algorithmic approximation of institutional volume concepts.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from screener import UNIVERSES, get_stock_links, hist_series

warnings.filterwarnings("ignore")

try:
    from intraday import (
        INTRADAY_UNIVERSES_BY_MARKET,
        MARKETS,
        _build_context,
        _fetch_daily,
        _orb_levels,
        _safe_pct,
        compute_vwap,
        resolve_universe,
    )
except ImportError:
    from .intraday import (  # type: ignore[no-redef]
        INTRADAY_UNIVERSES_BY_MARKET,
        MARKETS,
        _build_context,
        _fetch_daily,
        _orb_levels,
        _safe_pct,
        compute_vwap,
        resolve_universe,
    )

ProgressCb = Callable[[int, int, str], None]

META = {
    "id": "volume_gravity",
    "title": "Volume Gravity",
    "emoji": "⚖️",
    "nav_title": "Volume Gravity",
    "audience": (
        "Intraday and swing traders who trade **where institutions showed conviction** — "
        "VWAP, relative volume (RVOL), Volume Profile POC/Value Area, and ORB alignment."
    ),
    "purpose": (
        "Scores **Gap & Go**, **VWAP hold**, **ORB + VWAP**, and **POC breakout** setups. "
        "Switch **Intraday** (today’s session) or **Swing** (daily POC/VA). Not auto-trading."
    ),
}

MODES = ("intraday", "swing")


@dataclass
class VolumeGravityFilters:
    min_gap_pct: float = 2.0
    min_rvol: float = 2.0
    min_gravity_score: float = 45.0
    require_above_vwap_long: bool = False
    min_orb_vwap_score: float = 0.0
    setups: tuple[str, ...] = ("GAP_GO", "VWAP_HOLD", "ORB_VWAP", "POC_BREAKOUT", "WATCH")


@dataclass
class VolumeGravityResult:
    ticker: str
    raw_ticker: str
    mode: str
    setup: str
    setup_label: str
    gravity_score: float
    gravity_band: str
    gap_pct: float
    gap_type: str
    rvol: float
    pct_vs_vwap: Optional[float]
    price: float
    vwap: Optional[float]
    poc: Optional[float]
    va_high: Optional[float]
    va_low: Optional[float]
    day_type: str
    orb_high: Optional[float] = None
    orb_low: Optional[float] = None
    pct_in_va: Optional[float] = None
    checklist_pass: int = 0
    checklist_total: int = 6
    action_hint: str = "Watchlist"
    entry_hint: str = ""
    stop_hint: str = "Plan stop below VWAP or ORB low before entry."
    target_hint: str = ""
    warnings: list[str] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)


@dataclass
class VolumeGravityScanStats:
    universe: str
    mode: str
    market: str
    tickers_scanned: int = 0
    tickers_matched: int = 0
    no_data: int = 0
    scan_elapsed_sec: float = 0.0


def _display_ticker(raw: str) -> str:
    return raw.replace(".NS", "").replace(".BO", "")


def compute_volume_profile(
    bars: pd.DataFrame,
    *,
    n_bins: int = 24,
) -> dict[str, Any]:
    """POC, Value Area (70% volume), thin-zone flag from OHLCV bars."""
    empty: dict[str, Any] = {
        "poc": None,
        "va_high": None,
        "va_low": None,
        "thin_zone": False,
        "total_vol": 0.0,
    }
    if bars is None or bars.empty or len(bars) < 5:
        return empty

    highs = hist_series(bars, "High").astype(float)
    lows = hist_series(bars, "Low").astype(float)
    closes = hist_series(bars, "Close").astype(float)
    vols = hist_series(bars, "Volume").astype(float).fillna(0)
    typical = (highs + lows + closes) / 3.0
    valid = typical.notna() & (vols > 0)
    if valid.sum() < 5:
        return empty

    t = typical[valid].values
    v = vols[valid].values
    pmin, pmax = float(np.min(t)), float(np.max(t))
    if pmax <= pmin:
        pmax = pmin * 1.001

    n_bins = max(12, min(n_bins, 40))
    edges = np.linspace(pmin, pmax, n_bins + 1)
    vol_by = np.zeros(n_bins, dtype=float)
    for px, vol in zip(t, v):
        idx = min(n_bins - 1, int((px - pmin) / (pmax - pmin) * n_bins))
        vol_by[idx] += float(vol)

    total = float(vol_by.sum())
    if total <= 0:
        return empty

    poc_idx = int(np.argmax(vol_by))
    poc = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)

    target_vol = total * 0.70
    acc = float(vol_by[poc_idx])
    lo_i = hi_i = poc_idx
    while acc < target_vol and (lo_i > 0 or hi_i < n_bins - 1):
        expand_lo = vol_by[lo_i - 1] if lo_i > 0 else -1.0
        expand_hi = vol_by[hi_i + 1] if hi_i < n_bins - 1 else -1.0
        if expand_hi >= expand_lo:
            hi_i += 1
            acc += float(vol_by[hi_i])
        else:
            lo_i -= 1
            acc += float(vol_by[lo_i])

    va_low = float(edges[lo_i])
    va_high = float(edges[hi_i + 1])
    thin_zone = float(vol_by.max()) > 0 and (vol_by < vol_by.max() * 0.08).sum() > n_bins * 0.4

    return {
        "poc": round(poc, 2),
        "va_high": round(va_high, 2),
        "va_low": round(va_low, 2),
        "thin_zone": thin_zone,
        "total_vol": total,
    }


def _rolling_vwap_daily(daily: pd.DataFrame, window: int = 20) -> Optional[float]:
    if daily is None or len(daily) < window:
        return None
    h = hist_series(daily, "High").astype(float)
    l = hist_series(daily, "Low").astype(float)
    c = hist_series(daily, "Close").astype(float)
    v = hist_series(daily, "Volume").astype(float)
    typical = (h + l + c) / 3.0
    tail = typical.tail(window)
    tv = v.tail(window)
    if tv.sum() <= 0:
        return None
    return float((tail * tv).sum() / tv.sum())


def _classify_gap(
    gap_pct: float,
    *,
    rsi: Optional[float] = None,
    pct_vs_ma50: Optional[float] = None,
    exhaustion_run: bool = False,
) -> str:
    ag = abs(gap_pct)
    if ag < 1.0:
        return "Common (likely fill)"
    if ag < 2.0:
        return "Small — needs confirmation"
    if exhaustion_run or (rsi is not None and rsi > 72 and gap_pct > 0):
        return "Exhaustion risk"
    if pct_vs_ma50 is not None and pct_vs_ma50 > 0 and gap_pct > 0:
        return "Continuation"
    if ag >= 2.0:
        return "Breakaway candidate"
    return "Unclassified"


def _day_type(
    price: float,
    open_px: float,
    va_low: Optional[float],
    va_high: Optional[float],
) -> str:
    if va_low is None or va_high is None:
        return "Unknown"
    if open_px < va_low or open_px > va_high:
        if price < va_low or price > va_high:
            return "Trend day — outside prior value"
        return "Trend attempt — watch reclaim"
    if va_low <= open_px <= va_high and va_low <= price <= va_high:
        return "Consolidation — mean revert around POC"
    return "Mixed — rotating in value"


def _checklist_score(
    *,
    gap_ok: bool,
    rvol_ok: bool,
    vwap_ok: bool,
    orb_ok: bool,
    poc_ok: bool,
    day_ok: bool,
) -> tuple[int, list[str]]:
    items = [
        ("2%+ gap with catalyst mindset", gap_ok),
        (f"RVOL conviction", rvol_ok),
        ("VWAP side aligned", vwap_ok),
        ("ORB range defined", orb_ok),
        ("POC / VA mapped", poc_ok),
        ("Trend vs consolidation read", day_ok),
    ]
    passed = [label for label, ok in items if ok]
    return len(passed), passed


def _gravity_band(score: float) -> str:
    if score >= 75:
        return "High conviction"
    if score >= 55:
        return "Actionable watch"
    if score >= 40:
        return "Developing"
    return "Low — skip chase"


def _detect_setups_intraday(
    ctx: dict,
    vp: dict,
    flt: VolumeGravityFilters,
) -> list[tuple[str, str, float, str, str, str, list[str]]]:
    """Return list of (setup_id, label, score, action, entry, stop, target, warnings)."""
    out: list[tuple[str, str, float, str, str, str, list[str]]] = []
    price = float(ctx["price"])
    gap = float(ctx.get("gap_pct") or 0.0)
    rvol = float(ctx.get("vol_ratio") or 0.0)
    pct_vwap = ctx.get("pct_vs_vwap")
    vwap = ctx.get("vwap")
    orb_h, orb_l = ctx.get("orb_high"), ctx.get("orb_low")
    poc, va_h, va_l = vp.get("poc"), vp.get("va_high"), vp.get("va_low")
    warnings: list[str] = []

    above_vwap = pct_vwap is not None and float(pct_vwap) > 0
    near_vwap = pct_vwap is not None and abs(float(pct_vwap)) <= 1.2
    gap_ok = abs(gap) >= flt.min_gap_pct
    rvol_ok = rvol >= flt.min_rvol

    # Gap and Go
    if gap_ok and rvol_ok and above_vwap and gap > 0:
        sc = min(100.0, 40.0 + min(30.0, abs(gap) * 4) + min(30.0, (rvol - 1) * 10))
        out.append((
            "GAP_GO",
            "Gap & Go (long)",
            sc,
            "Watch for ORB break + hold above VWAP",
            "Enter on break above ORB high with RVOL ≥ 3×; do not chase without volume.",
            "Stop below VWAP or ORB low (5–10 ticks / ~0.5–1%).",
            "Target 1.5–2× ORB range or next thin profile zone.",
            warnings,
        ))
    elif gap_ok and rvol < flt.min_rvol:
        warnings.append("Gap without RVOL — likely noise per handbook.")

    # VWAP Hold
    if near_vwap and above_vwap and rvol >= 1.5:
        sc = min(100.0, 35.0 + (10 if near_vwap else 0) + min(25.0, rvol * 8))
        out.append((
            "VWAP_HOLD",
            "VWAP hold (pullback)",
            sc,
            "Pullback entry zone",
            "Wait for bounce off VWAP with volume spike away from the line.",
            "Stop just below VWAP or session low.",
            "Target prior intraday high or 1.5× risk.",
            warnings,
        ))

    # ORB + VWAP
    if orb_h and orb_l and above_vwap and price >= float(orb_h) * 0.998 and rvol >= max(2.0, flt.min_rvol * 0.7):
        rng = float(orb_h) - float(orb_l)
        sc = min(100.0, 50.0 + min(25.0, rvol * 6))
        out.append((
            "ORB_VWAP",
            "ORB + VWAP aligned",
            sc,
            "ORB long with institutional floor",
            "Long above ORB high while price holds above VWAP.",
            f"Stop below ORB low ({orb_l:.2f}).",
            f"Target ~{price + 1.5 * rng:.2f} (1.5× range)." if rng > 0 else "Target 1.5× ORB range.",
            warnings,
        ))

    # POC breakout (no blind touch — need RVOL)
    if poc and va_h and va_l and rvol_ok and (price > va_h or price < va_l):
        sc = min(100.0, 45.0 + min(35.0, rvol * 8))
        side = "above value" if price > va_h else "below value"
        out.append((
            "POC_BREAKOUT",
            f"POC gravity break ({side})",
            sc,
            "Breakout from value — confirm volume",
            "Do not fade POC chop; trade only with 3×+ RVOL expansion.",
            f"Stop back inside value area ({va_l:.2f}–{va_h:.2f}).",
            "Target next single-print / thin node on profile.",
            warnings,
        ))

    if not out and rvol >= 1.0:
        out.append((
            "WATCH",
            "Volume watch",
            max(25.0, min(50.0, rvol * 12)),
            "Map levels — no trigger yet",
            "Build plan: gap filter, mark ORB, watch VWAP reaction.",
            "No trade until checklist confirms.",
            "—",
            warnings,
        ))
    return out


def _detect_setups_swing(
    daily: pd.DataFrame,
    *,
    price: float,
    open_px: float,
    gap_pct: float,
    rvol: float,
    pct_vwap: Optional[float],
    vwap: Optional[float],
    vp: dict,
    flt: VolumeGravityFilters,
) -> list[tuple[str, str, float, str, str, str, list[str]]]:
    out: list[tuple[str, str, float, str, str, str, list[str]]] = []
    warnings: list[str] = []
    poc, va_h, va_l = vp.get("poc"), vp.get("va_high"), vp.get("va_low")
    above_vwap = pct_vwap is not None and float(pct_vwap) > 0
    gap_ok = abs(gap_pct) >= flt.min_gap_pct
    rvol_ok = rvol >= flt.min_rvol

    if gap_ok and rvol_ok and above_vwap and gap_pct > 0:
        sc = min(100.0, 38.0 + min(32.0, abs(gap_pct) * 5) + min(30.0, rvol * 7))
        out.append((
            "GAP_GO",
            "Swing gap & go",
            sc,
            "Multi-day momentum candidate",
            "Buy strength above 20-day VWAP after gap; confirm next-day hold.",
            "Stop 7–8% or below VWAP — whichever is tighter.",
            "Trail with 20/50 DMA; partial at 2R.",
            warnings,
        ))

    if poc and va_h and va_l and above_vwap and price > va_h and rvol_ok:
        out.append((
            "POC_BREAKOUT",
            "Swing POC / VA break",
            min(100.0, 42.0 + rvol * 8),
            "Value migration up",
            "Weekly close above value area with rising volume.",
            f"Stop below VA high ({va_h:.2f}).",
            "Target measured move = VA width added to break.",
            warnings,
        ))

    if pct_vwap is not None and abs(float(pct_vwap)) <= 2.0 and above_vwap:
        out.append((
            "VWAP_HOLD",
            "Swing VWAP pullback",
            min(100.0, 40.0 + min(20.0, rvol * 5)),
            "Buy institutional floor",
            "Add on pullback to 20-day VWAP in uptrend.",
            "Stop below VWAP cluster.",
            "Target prior swing high.",
            warnings,
        ))

    if not out:
        out.append((
            "WATCH",
            "Swing volume map",
            max(20.0, min(45.0, rvol * 10)),
            "Study profile",
            "Mark POC/VA on daily chart before sizing.",
            "—",
            "—",
            warnings,
        ))
    return out


def _build_swing_context(raw: str) -> Optional[dict]:
    daily = _fetch_daily(raw, "1y")
    if daily is None or daily.empty:
        return None
    daily = daily.dropna(subset=["Close", "High", "Low", "Open"], how="any")
    if len(daily) < 30:
        return None

    closes = hist_series(daily, "Close").astype(float)
    opens = hist_series(daily, "Open").astype(float)
    vols = hist_series(daily, "Volume").astype(float)

    price = float(closes.iloc[-1])
    open_px = float(opens.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else price
    gap_pct = _safe_pct(open_px, prev_close) or 0.0

    avg_vol = float(vols.tail(20).mean()) if len(vols) >= 20 else float(vols.mean())
    rvol = round(float(vols.iloc[-1]) / avg_vol, 2) if avg_vol > 0 else 0.0

    vwap = _rolling_vwap_daily(daily, 20)
    pct_vs_vwap = _safe_pct(price, vwap) if vwap else None

    profile_bars = daily.tail(40)
    vp = compute_volume_profile(profile_bars, n_bins=20)

    return {
        "daily": daily,
        "price": price,
        "open_px": open_px,
        "prev_close": prev_close,
        "gap_pct": gap_pct,
        "vol_ratio": rvol,
        "vwap": vwap,
        "pct_vs_vwap": pct_vs_vwap,
        "vp": vp,
    }


def _result_from_candidate(
    raw: str,
    mode: str,
    best: tuple[str, str, float, str, str, str, list[str]],
    ctx: dict,
    vp: dict,
    flt: VolumeGravityFilters,
) -> VolumeGravityResult:
    setup_id, label, setup_score, action, entry, stop, target, warns = best
    price = float(ctx["price"])
    gap = float(ctx.get("gap_pct") or 0.0)
    rvol = float(ctx.get("vol_ratio") or 0.0)
    pct_vwap = ctx.get("pct_vs_vwap")
    vwap = ctx.get("vwap")
    open_px = float(ctx.get("open_px") or price)
    poc, va_h, va_l = vp.get("poc"), vp.get("va_high"), vp.get("va_low")

    gap_type = _classify_gap(gap, pct_vs_ma50=ctx.get("pct_vs_ma50d"))
    day_type = _day_type(price, open_px, va_l, va_h)

    gap_ok = abs(gap) >= flt.min_gap_pct
    rvol_ok = rvol >= flt.min_rvol
    vwap_ok = pct_vwap is not None and (float(pct_vwap) > 0 if flt.require_above_vwap_long else True)
    orb_ok = ctx.get("orb_high") is not None
    poc_ok = poc is not None
    day_ok = "Trend" in day_type or "Consolidation" in day_type
    chk, _passed = _checklist_score(
        gap_ok=gap_ok, rvol_ok=rvol_ok, vwap_ok=vwap_ok, orb_ok=orb_ok, poc_ok=poc_ok, day_ok=day_ok,
    )

    gravity = min(100.0, round(setup_score * 0.65 + chk * 5 + (10 if rvol_ok else 0), 1))

    pct_in_va = None
    if va_l and va_h and va_h > va_l:
        if va_l <= price <= va_h:
            pct_in_va = 0.0
        elif price > va_h:
            pct_in_va = round((price - va_h) / (va_h - va_l) * 100, 1)
        else:
            pct_in_va = round((va_l - price) / (va_h - va_l) * 100, 1)

    return VolumeGravityResult(
        ticker=_display_ticker(raw),
        raw_ticker=raw,
        mode=mode,
        setup=setup_id,
        setup_label=label,
        gravity_score=gravity,
        gravity_band=_gravity_band(gravity),
        gap_pct=round(gap, 2),
        gap_type=gap_type,
        rvol=rvol,
        pct_vs_vwap=pct_vwap,
        price=round(price, 2),
        vwap=round(vwap, 2) if vwap else None,
        poc=poc,
        va_high=va_h,
        va_low=va_l,
        day_type=day_type,
        orb_high=ctx.get("orb_high"),
        orb_low=ctx.get("orb_low"),
        pct_in_va=pct_in_va,
        checklist_pass=chk,
        checklist_total=6,
        action_hint=action,
        entry_hint=entry,
        stop_hint=stop,
        target_hint=target,
        warnings=warns,
        links=get_stock_links(raw),
    )


def scan_volume_gravity(
    universe_name: str,
    mode: str = "intraday",
    *,
    market: str = "NSE",
    filters: Optional[VolumeGravityFilters] = None,
    progress_cb: Optional[ProgressCb] = None,
    tickers_override: Optional[list[str]] = None,
    data_source: str = "auto",
) -> tuple[list[VolumeGravityResult], VolumeGravityScanStats]:
    flt = filters or VolumeGravityFilters()
    mode = mode if mode in MODES else "intraday"
    mkt = market if market in MARKETS else "NSE"

    if tickers_override is not None:
        tickers = list(tickers_override)
    elif mode == "intraday":
        tickers = resolve_universe(universe_name, mkt)
    else:
        tickers = list(UNIVERSES.get(universe_name, []))

    stats = VolumeGravityScanStats(
        universe=universe_name, mode=mode, market=mkt, tickers_scanned=len(tickers),
    )
    t0 = time.time()
    results: list[VolumeGravityResult] = []

    for i, raw in enumerate(tickers):
        if progress_cb:
            progress_cb(i + 1, len(tickers), _display_ticker(raw))

        if mode == "intraday":
            ctx = _build_context(raw, data_source=data_source)
            if not ctx:
                stats.no_data += 1
                continue
            session = ctx.get("session")
            if session is None or (hasattr(session, "empty") and session.empty):
                session = ctx.get("bars")
            vp = compute_volume_profile(session)
            candidates = _detect_setups_intraday(ctx, vp, flt)
        else:
            ctx = _build_swing_context(raw)
            if not ctx:
                stats.no_data += 1
                continue
            vp = ctx["vp"]
            candidates = _detect_setups_swing(
                ctx["daily"],
                price=ctx["price"],
                open_px=ctx["open_px"],
                gap_pct=ctx["gap_pct"],
                rvol=ctx["vol_ratio"],
                pct_vwap=ctx["pct_vs_vwap"],
                vwap=ctx["vwap"],
                vp=vp,
                flt=flt,
            )
            ctx["orb_high"] = None
            ctx["orb_low"] = None
            ctx["pct_vs_ma50d"] = None

        if not candidates:
            continue

        allowed = set(flt.setups)
        candidates = [c for c in candidates if c[0] in allowed]
        if not candidates:
            continue

        best = max(candidates, key=lambda x: x[2])
        if best[2] < flt.min_gravity_score and best[0] != "WATCH":
            continue
        if flt.require_above_vwap_long:
            pv = ctx.get("pct_vs_vwap")
            if pv is None or float(pv) <= 0:
                continue

        res = _result_from_candidate(raw, mode, best, ctx, vp, flt)
        if res.gravity_score >= flt.min_gravity_score or res.setup == "WATCH":
            results.append(res)

    results.sort(key=lambda r: (-r.gravity_score, -r.rvol, -abs(r.gap_pct)))
    stats.tickers_matched = len(results)
    stats.scan_elapsed_sec = round(time.time() - t0, 2)
    return results, stats


def universe_options(mode: str, market: str) -> list[str]:
    if mode == "intraday" and market in INTRADAY_UNIVERSES_BY_MARKET:
        return list(INTRADAY_UNIVERSES_BY_MARKET[market].keys())
    return list(UNIVERSES.keys())
