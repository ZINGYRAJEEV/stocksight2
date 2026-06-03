"""
Unified intraday ranking — combines Intraday Screener + Algo Strategy Hub logic.

- Screener: Score/120, session timing, vol×, R:R
- Hub: Quality Gate, multi-strategy confluence, market regime fit

Both pages should use ``unified_intraday_score`` and ``sort_intraday_results`` for consistent order.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from intraday import (
        STRATEGY_LABEL,
        IntradayResult,
        _timing_weight_from_prediction,
        compute_intraday_quality_gate,
    )
except ImportError:
    from .intraday import (  # type: ignore[no-redef]
        STRATEGY_LABEL,
        IntradayResult,
        _timing_weight_from_prediction,
        compute_intraday_quality_gate,
    )

# Pattern tags aligned with algo_selector.MarketRegime lists
_STRATEGY_PATTERN: dict[str, str] = {
    "VWAP": "vwap_pullback",
    "ORB": "orb_breakout",
    "MOMENTUM": "momentum",
    "GAP": "orb_breakout",
    "ATH": "ath_breakout",
    "BROAD": "grid_range",
}


def build_confluence_map(results: list[IntradayResult]) -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for r in results:
        m.setdefault(r.raw_ticker, [])
        if r.strategy not in m[r.raw_ticker]:
            m[r.raw_ticker].append(r.strategy)
    return m


def _regime_adjustment(strategy: str, regime: Any) -> float:
    if regime is None:
        return 0.0
    pat = _STRATEGY_PATTERN.get(strategy, "momentum")
    adj = 0.0
    favored = getattr(regime, "favored_patterns", None) or []
    avoid = getattr(regime, "avoid_patterns", None) or []
    if pat in favored:
        adj += 8.0
    if pat in avoid:
        adj -= 15.0
    code = getattr(regime, "code", "") or ""
    if code == "range_bound" and strategy == "VWAP":
        adj += 4.0
    if code == "trending_bull" and strategy == "MOMENTUM":
        adj += 4.0
    return adj


def unified_intraday_score(
    r: IntradayResult,
    confluence_n: int,
    regime: Any = None,
) -> tuple[float, str, str]:
    """
    Single 0–100 score + gate band + explanation.

    Built on Quality Gate (includes score/120, timing, confluence) plus optional regime
    nudge and light vol/R:R tie boosts.
    """
    row = {
        "Score /120": r.score_120,
        "Tier": r.rank_tier,
        "Prediction": r.prediction or "",
        "Strategy": STRATEGY_LABEL.get(r.strategy, r.strategy),
        "R:R": r.rr_ratio,
    }
    pack = compute_intraday_quality_gate(
        row,
        strategies_on_ticker=[r.strategy] * max(1, confluence_n),
    )
    score = float(pack["score"])
    score += _regime_adjustment(r.strategy, regime)

    try:
        if r.vol_ratio is not None and float(r.vol_ratio) >= 2.0:
            score += 2.0
        if r.rr_ratio is not None and float(r.rr_ratio) >= 1.5:
            score += 2.0
    except (TypeError, ValueError):
        pass

    if "avoid" in (r.rank_tier or "").lower():
        score = min(score, 35.0)

    score = max(0.0, min(100.0, round(score, 1)))
    why = str(pack.get("why") or "")
    reg_adj = _regime_adjustment(r.strategy, regime)
    if reg_adj > 0:
        why = f"{why} · regime +{int(reg_adj)}"
    elif reg_adj < 0:
        why = f"{why} · regime {int(reg_adj)}"
    if confluence_n >= 2:
        why = f"{why} · {confluence_n} strategies"
    return score, str(pack.get("label", "—")), why


def unified_sort_key(
    r: IntradayResult,
    confluence_map: dict[str, list[str]],
    regime: Any = None,
) -> tuple:
    n_conf = len(confluence_map.get(r.raw_ticker, [r.strategy]))
    u, _, _ = unified_intraday_score(r, n_conf, regime)
    return (
        -u,
        -r.score_120,
        -_timing_weight_from_prediction(r.prediction or "") * 5,
        -(r.vol_ratio or 0.0),
        -(r.rr_ratio or 0.0),
    )


def sort_intraday_results(
    results: list[IntradayResult],
    regime: Any = None,
) -> list[IntradayResult]:
    """Sort all strategy rows by unified score (Screener table order)."""
    if not results:
        return results
    conf = build_confluence_map(results)
    return sorted(results, key=lambda r: unified_sort_key(r, conf, regime))


def best_row_per_ticker(
    results: list[IntradayResult],
    regime: Any = None,
) -> list[tuple[float, IntradayResult, int, str, str]]:
    """One best row per ticker for Hub-style picks: (score, result, confluence_n, band, why)."""
    if not results:
        return []
    conf = build_confluence_map(results)
    by_raw: dict[str, list[IntradayResult]] = {}
    for r in results:
        by_raw.setdefault(r.raw_ticker, []).append(r)
    scored: list[tuple[float, IntradayResult, int, str, str]] = []
    for raw, group in by_raw.items():
        best = max(
            group,
            key=lambda x: unified_sort_key(x, conf, regime),
        )
        n = len(conf.get(raw, [best.strategy]))
        sc, band, why = unified_intraday_score(best, n, regime)
        scored.append((sc, best, n, band, why))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored
