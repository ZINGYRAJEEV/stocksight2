"""Six signal scanners — delegates to StockSight intraday engine."""

from __future__ import annotations

from typing import Any, Callable, Optional

try:
    from intraday import (
        IntradayFilters,
        IntradayResult,
        scan_gaps,
        scan_intraday,
    )
except ImportError:
    from ..intraday import IntradayFilters, IntradayResult, scan_gaps, scan_intraday  # type: ignore

STRATEGY_META = {
    "GAP": ("Gap-Up w/ Strength", "09:15–09:30 IST"),
    "MOMENTUM": ("Momentum Breakout", "09:30–11:00 IST"),
    "ORB": ("Opening Range Breakout", "09:45–10:15 IST"),
    "ATH": ("ATH Breakout", "After 10:00 IST"),
    "VWAP": ("VWAP Pullback", "10:30–13:00 IST"),
    "BROAD": ("Broad Movers", "Any window"),
}


def run_gap_scan(
    tickers: list[str],
    *,
    data_source: str = "auto",
    min_gap: float = 0.5,
    progress_cb: Optional[Callable[..., None]] = None,
) -> list:
    return scan_gaps(tickers, min_gap_abs_pct=min_gap, data_source=data_source, progress_cb=progress_cb)


def run_strategy_scan(
    tickers: list[str],
    strategies: tuple[str, ...],
    *,
    market: str = "NSE",
    data_source: str = "auto",
    progress_cb: Optional[Callable[..., None]] = None,
) -> tuple[list[IntradayResult], Any]:
    return scan_intraday(
        tickers,
        strategies,
        IntradayFilters(),
        market=market,
        data_source=data_source,
        progress_cb=progress_cb,
    )


def build_shortlist(gaps: list, n: int = 3) -> list[str]:
    scored: list[tuple[float, str]] = []
    for g in gaps:
        if getattr(g, "direction", "") != "UP":
            continue
        s = abs(float(getattr(g, "gap_pct", 0) or 0)) * 10
        if getattr(g, "holding", False):
            s += 12
        scored.append((s, str(getattr(g, "raw_ticker", ""))))
    scored.sort(reverse=True)
    out: list[str] = []
    for _, raw in scored:
        if raw and raw not in out:
            out.append(raw)
        if len(out) >= n:
            break
    return out
