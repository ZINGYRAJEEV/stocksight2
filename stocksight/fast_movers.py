"""
Intraday Fast Movers — rank tickers by how quickly price is moving right now.

Uses 5m/15m session bars (Breeze or Yahoo) + volume acceleration.
Educational pulse check — not a trade signal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from intraday import (
    DATA_SOURCE_OPTIONS,
    INTRADAY_UNIVERSES_BY_MARKET,
    MARKETS,
    _build_context,
    resolve_universe,
)
from intraday_vol_surge import _bar_direction_ratio, _price_slope_pct, _volume_acceleration
from screener import get_sector_industry, get_stock_links, hist_series

ProgressCb = Callable[[int, int, str], None]

META = {
    "id": "fast_movers",
    "title": "Intraday Fast Movers",
    "emoji": "⚡",
    "nav_title": "Fast Movers",
    "audience": (
        "Intraday traders who need a **live pulse** on which tickers are moving fastest — "
        "session %, short-window velocity, and volume surge."
    ),
    "purpose": (
        "Ranks universe by **speed score** from 5m bars: move vs open, last 5/15/30m %, "
        "volume ratio & acceleration. ICICI Breeze when connected."
    ),
}

DATA_SOURCE_LABELS = {
    "auto": "Auto — ICICI Breeze (NSE) if connected, else Yahoo",
    "breeze": "ICICI Breeze only",
    "yahoo": "Yahoo Finance only",
}

SPEED_TIERS = ("🔥 Blazing", "⚡ Fast", "→ Moving", "— Quiet")
DIRECTIONS = ("🟢 Up burst", "🔴 Down dump", "↔ Choppy")


@dataclass
class FastMoverFilters:
    universe: str = "Nifty 50 (fast)"
    market: str = "NSE"
    data_source: str = "auto"
    min_speed_score: float = 30.0
    min_vol_ratio: float = 1.0
    direction: str = "any"  # any | up | down
    max_tickers: int = 555
    bar_delay_sec: float = 0.08


@dataclass
class FastMoverResult:
    ticker: str
    raw_ticker: str
    sector: str
    price: float
    pct_vs_prev_close: float
    pct_vs_open: float
    move_5m_pct: float
    move_15m_pct: float
    move_30m_pct: float
    velocity_5m: float
    vol_ratio: float
    vol_accel: float
    pct_vs_vwap: Optional[float]
    rsi: Optional[float]
    speed_score: float
    speed_tier: str
    direction: str
    bar_interval: str
    action: str
    links: dict = field(default_factory=dict)


@dataclass
class FastMoverScanStats:
    universe: str
    market: str
    data_source: str
    tickers_scanned: int = 0
    tickers_matched: int = 0
    no_data: int = 0
    scan_elapsed_sec: float = 0.0


def _pct_move(closes, bars_back: int, interval: str) -> float:
    """% change over last N bars (scaled to ~5m equivalent for 15m bars)."""
    if closes is None or len(closes) < 2:
        return 0.0
    n = max(1, bars_back)
    if interval == "15m":
        n = max(1, bars_back // 3)
    return _price_slope_pct(closes, n=n)


def _speed_tier(score: float) -> str:
    if score >= 75:
        return "🔥 Blazing"
    if score >= 55:
        return "⚡ Fast"
    if score >= 35:
        return "→ Moving"
    return "— Quiet"


def _direction_label(move_15m: float, green_ratio: float, red_ratio: float) -> str:
    if move_15m >= 0.2 and green_ratio >= 0.5:
        return "🟢 Up burst"
    if move_15m <= -0.2 and red_ratio >= 0.5:
        return "🔴 Down dump"
    return "↔ Choppy"


def _speed_score(
    *,
    pct_change: float,
    pct_vs_open: float,
    move_15m: float,
    vol_ratio: float,
    vol_accel: float,
) -> float:
    score = 0.0
    score += min(30.0, abs(pct_change) * 4.0)
    score += min(25.0, abs(move_15m) * 8.0)
    score += min(20.0, abs(pct_vs_open) * 3.5)
    score += min(15.0, max(0.0, (vol_ratio or 0) - 1.0) * 10.0)
    score += min(10.0, max(0.0, (vol_accel or 0) - 1.0) * 5.0)
    return round(min(100.0, score), 1)


def _action_hint(tier: str, direction: str, pct_vs_open: float) -> str:
    if "Blazing" in tier and "Up" in direction:
        return "Hot long momentum — confirm VWAP hold"
    if "Blazing" in tier and "Down" in direction:
        return "Fast selloff — avoid catching knife"
    if "Fast" in tier and pct_vs_open > 1:
        return "Strong session trend — watch pullback"
    if "Fast" in tier and pct_vs_open < -1:
        return "Weak session — bounce or fade?"
    return "Monitor — not a top mover yet"


def analyze_fast_mover(raw: str, flt: FastMoverFilters) -> Optional[FastMoverResult]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        ctx = _build_context(raw, data_source=flt.data_source)
        if not ctx:
            return None

        session = ctx.get("session")
        bars = ctx.get("bars")
        interval = str(ctx.get("bar_interval") or "5m")
        if session is None or getattr(session, "empty", True):
            session = bars
        if session is None or getattr(session, "empty", True):
            return None

        closes = hist_series(session, "Close").astype(float).dropna()
        vols = hist_series(session, "Volume").astype(float).dropna()
        if closes.empty:
            return None

        price = float(ctx["price"])
        open_px = float(ctx.get("open_px") or price)
        pct_vs_open = round((price - open_px) / open_px * 100.0, 2) if open_px > 0 else 0.0
        pct_change = float(ctx.get("pct_change") or 0.0)

        bars_5m = 1 if interval == "5m" else 1
        bars_15m = 3 if interval == "5m" else 1
        bars_30m = 6 if interval == "5m" else 2

        move_5m = _pct_move(closes, bars_5m, interval)
        move_15m = _pct_move(closes, bars_15m, interval)
        move_30m = _pct_move(closes, bars_30m, interval)
        velocity_5m = round(abs(move_5m) / max(bars_5m, 1), 3)

        vol_accel = _volume_acceleration(vols, recent=3, prior=3)
        vol_ratio = float(ctx.get("vol_ratio") or 0.0)
        green_r, red_r = _bar_direction_ratio(session, n=4)
        direction = _direction_label(move_15m, green_r, red_r)

        score = _speed_score(
            pct_change=pct_change,
            pct_vs_open=pct_vs_open,
            move_15m=move_15m,
            vol_ratio=vol_ratio,
            vol_accel=vol_accel,
        )
        tier = _speed_tier(score)

        if score < flt.min_speed_score:
            return None
        if vol_ratio < flt.min_vol_ratio:
            return None
        if flt.direction == "up" and "Up" not in direction:
            return None
        if flt.direction == "down" and "Down" not in direction:
            return None

        import yfinance as yf

        sector, _ = get_sector_industry(yf.Ticker(raw))
        disp = raw.replace(".NS", "").replace(".BO", "")

        return FastMoverResult(
            ticker=disp,
            raw_ticker=raw,
            sector=sector or "—",
            price=round(price, 2),
            pct_vs_prev_close=round(pct_change, 2),
            pct_vs_open=pct_vs_open,
            move_5m_pct=move_5m,
            move_15m_pct=move_15m,
            move_30m_pct=move_30m,
            velocity_5m=velocity_5m,
            vol_ratio=round(vol_ratio, 2),
            vol_accel=vol_accel,
            pct_vs_vwap=ctx.get("pct_vs_vwap"),
            rsi=ctx.get("rsi"),
            speed_score=score,
            speed_tier=tier,
            direction=direction,
            bar_interval=interval,
            action=_action_hint(tier, direction, pct_vs_open),
            links=get_stock_links(raw),
        )
    except Exception:
        return None


def scan_fast_movers(
    flt: FastMoverFilters,
    *,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[FastMoverResult], FastMoverScanStats]:
    t0 = time.time()
    tickers = resolve_universe(flt.universe, market=flt.market)[: flt.max_tickers]
    stats = FastMoverScanStats(
        universe=flt.universe,
        market=flt.market,
        data_source=flt.data_source,
    )
    results: list[FastMoverResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        r = analyze_fast_mover(raw, flt)
        if r is None:
            stats.no_data += 1
            continue
        results.append(r)
        stats.tickers_matched += 1
        if flt.bar_delay_sec > 0:
            time.sleep(flt.bar_delay_sec)

    results.sort(key=lambda x: (-x.speed_score, -abs(x.move_15m_pct)))
    stats.scan_elapsed_sec = time.time() - t0
    return results, stats


def universe_options(market: str) -> list[str]:
    mkt = (market or "NSE").upper()
    if mkt in INTRADAY_UNIVERSES_BY_MARKET:
        return list(INTRADAY_UNIVERSES_BY_MARKET[mkt].keys())
    return list(INTRADAY_UNIVERSES_BY_MARKET.get("NSE", {}).keys())
