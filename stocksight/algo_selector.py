"""
Multi-horizon algo strategy selector — ranks best candidates by timeframe and market regime.

Maps institutional patterns (VWAP/TWAP-style execution, ORB/scalping, grid/range, swing ATH)
to existing StockSight scanners. Educational / research only — not exchange-certified algo deployment.

SEBI note (India): Live algos require broker-hosted infrastructure, exchange approval, and Algo IDs.
This module does not place orders or host strategies on broker systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from intraday import (
    STRATEGIES,
    STRATEGY_LABEL,
    IntradayFilters,
    IntradayResult,
    compute_market_mood,
    compute_volume_time_prediction,
    resolve_universe,
    scan_gaps,
    scan_intraday,
)
from intraday import compute_intraday_quality_gate
from quality_gate import compute_daily_quality_gate

try:
    from signals import (
        SignalResult,
        scan_breakout_momentum,
        scan_monthly_ath_longterm,
        scan_value_technical,
        scan_weekly_ath_swing,
    )
except ImportError:
    from .signals import (  # type: ignore[no-redef]
        SignalResult,
        scan_breakout_momentum,
        scan_monthly_ath_longterm,
        scan_value_technical,
        scan_weekly_ath_swing,
    )

try:
    from screener import decision_from_metrics, UNIVERSES
except ImportError:
    from .screener import decision_from_metrics, UNIVERSES  # type: ignore[no-redef]


# ── Horizons (user-facing) ─────────────────────────────────────
HORIZONS = ("intraday", "weekly", "monthly", "long_term")

HORIZON_META: dict[str, dict[str, str]] = {
    "intraday": {
        "label": "Intraday (MIS)",
        "bars": "5m / 15m",
        "hold": "Same session — square off before close (NSE ~3:15 PM IST)",
        "product": "MIS / margin intraday",
    },
    "weekly": {
        "label": "Weekly swing",
        "bars": "Weekly",
        "hold": "Days to few weeks — weekly chart confirmation",
        "product": "CNC delivery or positional (your risk plan)",
    },
    "monthly": {
        "label": "Monthly trend",
        "bars": "Monthly + daily context",
        "hold": "Weeks to months — trend continuation",
        "product": "CNC — fundamental + technical alignment",
    },
    "long_term": {
        "label": "Long-term / ATH",
        "bars": "Monthly ATH + fundamentals",
        "hold": "Months to years — quality compounders near ATH",
        "product": "CNC delivery — low turnover",
    },
}

# Briefing → pattern tags (white-box labels for UI)
PATTERN_TAGS: dict[str, str] = {
    "vwap_pullback": "VWAP-style pullback (volume-weighted mean reversion)",
    "orb_breakout": "Opening range / breakout scalping",
    "momentum": "Momentum breakout (volume + trend)",
    "grid_range": "Range / grid-friendly (sideways volatility)",
    "twap_slice": "TWAP-style (thin book — scale in over time)",
    "ath_breakout": "ATH / 52w high breakout (trend)",
    "value_quality": "Value + technical quality (long horizon)",
}

# Regimes from gap mood + session timing
REGIMES = ("trending_bull", "trending_bear", "range_bound", "mixed", "high_stress")


@dataclass
class MarketRegime:
    code: str
    label: str
    summary: str
    favored_patterns: list[str] = field(default_factory=list)
    avoid_patterns: list[str] = field(default_factory=list)


@dataclass
class AlgoPick:
    ticker: str
    raw_ticker: str
    horizon: str
    rank: int
    score: float
    gate_band: str
    pattern: str
    algo_style: str
    strategy: str
    regime_fit: str
    signal: str
    confidence: str
    price: Optional[float]
    entry: Optional[float]
    stop: Optional[float]
    target: Optional[float]
    rr: Optional[float]
    rationale: str
    sebi_note: str
    source: str
    score_120: float = 0.0


@dataclass
class AlgoSelectionReport:
    universe: str
    market: str
    regime: MarketRegime
    session_note: str
    picks_by_horizon: dict[str, list[AlgoPick]]
    stats: dict[str, Any] = field(default_factory=dict)


def _default_sebi_note() -> str:
    return (
        "Research signal only — not exchange-approved algo. "
        "India: deploy via broker-owned stack, Algo ID, kill switch, and order limits (SEBI)."
    )


def detect_market_regime(
    *,
    market: str = "NSE",
    sample_tickers: Optional[list[str]] = None,
    min_gap_pct: float = 0.8,
) -> tuple[MarketRegime, str]:
    """Infer regime from gap distribution + session volume curve."""
    tickers = sample_tickers or resolve_universe("Nifty 50 (fast)", market)[:40]
    gaps = scan_gaps(tickers, min_gap_abs_pct=min_gap_pct) if tickers else []
    mood, note = compute_market_mood(gaps)
    vol = compute_volume_time_prediction(market)
    session_note = f"{vol.prediction} · {vol.market_local_time} · session vol ~{vol.session_vol_pct}%"

    m = (mood or "").lower()
    if "bullish" in m:
        regime = MarketRegime(
            "trending_bull",
            "Trending bullish",
            note or mood,
            favored_patterns=["momentum", "orb_breakout", "vwap_pullback", "ath_breakout"],
            avoid_patterns=["grid_range", "twap_slice"],
        )
    elif "bearish" in m:
        regime = MarketRegime(
            "trending_bear",
            "Trending bearish",
            note or mood,
            favored_patterns=["twap_slice"],
            avoid_patterns=["momentum", "orb_breakout", "martingale_warning"],
        )
    elif "mixed" in m:
        regime = MarketRegime(
            "range_bound",
            "Range / mixed (grid-friendly)",
            note or mood,
            favored_patterns=["grid_range", "vwap_pullback", "twap_slice"],
            avoid_patterns=["momentum"],
        )
    else:
        regime = MarketRegime(
            "mixed",
            "Mixed / unclear",
            note or mood,
            favored_patterns=["vwap_pullback", "value_quality"],
            avoid_patterns=[],
        )

    if "fake" in vol.prediction.lower() or "dangerous" in vol.prediction.lower():
        regime = MarketRegime(
            "high_stress",
            "High-stress session window",
            f"{note} · {vol.prediction}",
            favored_patterns=["twap_slice"],
            avoid_patterns=["orb_breakout", "momentum", "martingale_warning"],
        )
        session_note = vol.prediction

    return regime, session_note


def _intraday_pattern(strategy: str, regime: MarketRegime) -> tuple[str, str, str]:
    """Map intraday strategy code → pattern tag, algo style label, regime fit text."""
    mapping = {
        "VWAP": ("vwap_pullback", "VWAP pullback (institutional mean)", "Strong in range or pullback"),
        "ORB": ("orb_breakout", "ORB / scalping breakout", "Best at open; weak in lunch"),
        "MOMENTUM": ("momentum", "Momentum breakout", "Best when regime is trending"),
        "GAP": ("orb_breakout", "Gap + momentum", "Open window only"),
        "ATH": ("ath_breakout", "Intraday ATH extension", "Trending sessions"),
        "BROAD": ("grid_range", "Broad mover / watchlist", "Lower conviction alone"),
    }
    pat, style, fit = mapping.get(strategy, ("momentum", strategy, "—"))
    if regime.code == "range_bound" and strategy == "VWAP":
        fit = "Excellent — grid/VWAP friendly"
    if regime.code == "trending_bull" and strategy == "MOMENTUM":
        fit = "Excellent — trend aligned"
    if regime.code == "high_stress":
        fit = "Caution — reduce size or skip"
    return pat, style, fit


def _picks_from_intraday(
    results: list[IntradayResult],
    regime: MarketRegime,
    *,
    top_n: int,
) -> list[AlgoPick]:
    if not results:
        return []
    try:
        from intraday_ranking import best_row_per_ticker
    except ImportError:
        from .intraday_ranking import best_row_per_ticker  # type: ignore[no-redef]

    scored = best_row_per_ticker(results, regime)

    picks: list[AlgoPick] = []
    for i, (sc, r, n_conf, band, why) in enumerate(scored[:top_n], start=1):
        pat, style, fit = _intraday_pattern(r.strategy, regime)
        picks.append(
            AlgoPick(
                ticker=r.ticker,
                raw_ticker=r.raw_ticker,
                horizon="intraday",
                rank=i,
                score=round(sc, 1),
                score_120=float(r.score_120),
                gate_band=band,
                pattern=PATTERN_TAGS.get(pat, pat),
                algo_style=style,
                strategy=STRATEGY_LABEL.get(r.strategy, r.strategy),
                regime_fit=fit,
                signal="LONG bias" if r.strategy != "BROAD" else "Watch",
                confidence=r.rank_tier or "—",
                price=r.price,
                entry=r.entry,
                stop=r.stop,
                target=r.target,
                rr=r.rr_ratio,
                rationale=f"{why} · confluence {n_conf} strategy(s)",
                sebi_note=_default_sebi_note(),
                source="intraday_scan",
            )
        )
    return picks


def _score_signal(sr: SignalResult, horizon: str) -> tuple[float, str, str]:
    decision, composite, note = decision_from_metrics(
        sr.pe, sr.vol_ratio, sr.rsi, signal_label=sr.signal_label, scenario_id=sr.scenario_id,
    )
    row = {
        "Decision": decision,
        "Composite": composite,
        "Signal": sr.signal_label,
        "Confidence": sr.confidence,
        "RSI": sr.rsi,
        "Vol×": sr.vol_ratio,
    }
    pack = compute_daily_quality_gate(row)
    base = float(pack["score"])
    if sr.confidence == "HIGH":
        base += 5
    if sr.rrr and sr.rrr >= 1.5:
        base += 4
    return base, pack["band"], f"{note[:80]} · {pack['why'][:80]}"


def _pattern_for_signal(sr: SignalResult, horizon: str) -> tuple[str, str]:
    sid = sr.scenario_id or ""
    if "weekly_ath" in sid or horizon == "weekly":
        return "ath_breakout", "Weekly 52w-high / ATH swing"
    if "monthly_ath" in sid or horizon in ("monthly", "long_term"):
        return "ath_breakout", "Monthly ATH + quality trend"
    if "breakout" in sid:
        return "momentum", "Daily breakout momentum"
    if "value" in sid:
        return "value_quality", "Value + technical compounder"
    return "momentum", sr.scenario_id or "scenario"


def _picks_from_signals(
    results: list[SignalResult],
    horizon: str,
    regime: MarketRegime,
    *,
    top_n: int,
) -> list[AlgoPick]:
    if not results:
        return []
    scored: list[tuple[float, SignalResult, str, str]] = []
    for sr in results:
        sc, band, why = _score_signal(sr, horizon)
        pat, _ = _pattern_for_signal(sr, horizon)
        if pat in regime.favored_patterns:
            sc += 6
        scored.append((sc, sr, band, why))
    scored.sort(key=lambda x: x[0], reverse=True)

    picks: list[AlgoPick] = []
    for i, (sc, sr, band, why) in enumerate(scored[:top_n], start=1):
        pat, style = _pattern_for_signal(sr, horizon)
        picks.append(
            AlgoPick(
                ticker=sr.ticker,
                raw_ticker=sr.raw_ticker,
                horizon=horizon,
                rank=i,
                score=round(sc, 1),
                gate_band=band,
                pattern=PATTERN_TAGS.get(pat, pat),
                algo_style=style,
                strategy=sr.scenario_id.replace("_", " ").title(),
                regime_fit="Trend" if regime.code.startswith("trending") else "Swing / position",
                signal=sr.signal_label,
                confidence=sr.confidence,
                price=sr.price,
                entry=sr.entry,
                stop=sr.stop_loss,
                target=sr.target2,
                rr=sr.rrr,
                rationale=why,
                sebi_note=_default_sebi_note(),
                source=sr.scenario_id,
            )
        )
    return picks


def run_algo_selection(
    universe_name: str,
    *,
    market: str = "NSE",
    horizons: tuple[str, ...] = HORIZONS,
    top_n: int = 8,
    max_intraday_tickers: int = 80,
    data_source: str = "auto",
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> AlgoSelectionReport:
    """
    Run multi-horizon scans and return ranked AlgoPick lists per horizon.

    ``universe_name`` must exist in UNIVERSES or intraday universe lists.
    """
    mkt = (market or "NSE").upper()
    tickers = resolve_universe(universe_name, mkt)
    if not tickers and universe_name in UNIVERSES:
        tickers = list(UNIVERSES[universe_name])
    if not tickers:
        empty_regime = MarketRegime("mixed", "Unknown", "Empty universe")
        return AlgoSelectionReport(universe_name, mkt, empty_regime, "—", {})

    regime, session_note = detect_market_regime(market=mkt, sample_tickers=tickers[:35])

    picks_by: dict[str, list[AlgoPick]] = {}
    stats: dict[str, Any] = {"universe_size": len(tickers), "regime": regime.code}

    steps = [h for h in horizons if h in HORIZONS]
    total_steps = len(steps)
    step_i = 0

    def _prog(phase: str, cur: int, tot: int) -> None:
        if progress_cb:
            progress_cb(phase, cur, tot)

    intraday_strats = tuple(s for s in ("MOMENTUM", "VWAP", "ORB", "GAP", "ATH", "BROAD") if s in STRATEGIES)

    for horizon in steps:
        step_i += 1
        _prog(horizon, step_i, total_steps)

        if horizon == "intraday":
            subset = tickers[: max_intraday_tickers]
            results, istats = scan_intraday(
                subset,
                intraday_strats,
                IntradayFilters(),
                progress_cb=None,
                market=mkt,
                data_source=data_source,
            )
            stats["intraday_scanned"] = istats.total_scanned
            stats["intraday_matches"] = len(results)
            picks_by[horizon] = _picks_from_intraday(results, regime, top_n=top_n)

        elif horizon == "weekly":
            wk = scan_weekly_ath_swing(universe_name, progress_cb=None)
            bm = scan_breakout_momentum(
                universe_name, pe_max=55.0, vol_min=2.0, rsi_min=52, rsi_max=72, progress_cb=None,
            )
            combined = wk + [r for r in bm if r.raw_ticker not in {x.raw_ticker for x in wk}]
            stats["weekly_matches"] = len(combined)
            picks_by[horizon] = _picks_from_signals(combined, "weekly", regime, top_n=top_n)

        elif horizon == "monthly":
            wk = scan_weekly_ath_swing(
                universe_name, near_pct=5.0, vol_min=1.2, progress_cb=None,
            )
            picks_by[horizon] = _picks_from_signals(wk, "monthly", regime, top_n=top_n)
            stats["monthly_matches"] = len(wk)

        elif horizon == "long_term":
            lt = scan_monthly_ath_longterm(universe_name, progress_cb=None)
            vt = scan_value_technical(
                universe_name, pe_max=35.0, vol_min=0.8, rsi_min=45, rsi_max=70, progress_cb=None,
            )
            combined = lt + [r for r in vt if r.raw_ticker not in {x.raw_ticker for x in lt}][:20]
            stats["long_term_matches"] = len(combined)
            picks_by[horizon] = _picks_from_signals(combined, "long_term", regime, top_n=top_n)

    return AlgoSelectionReport(
        universe=universe_name,
        market=mkt,
        regime=regime,
        session_note=session_note,
        picks_by_horizon=picks_by,
        stats=stats,
    )


def picks_to_dataframe(picks: list[AlgoPick]):
    """Convert picks to a pandas DataFrame for tables / CSV."""
    import pandas as pd

    if not picks:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Rank": p.rank,
                "Ticker": p.ticker,
                "Horizon": HORIZON_META.get(p.horizon, {}).get("label", p.horizon),
                "Quality Gate": p.gate_band,
                "Unified score": p.score,
                "Score /120": p.score_120,
                "Pattern": p.pattern,
                "Algo style": p.algo_style,
                "Strategy": p.strategy,
                "Signal": p.signal,
                "Confidence": p.confidence,
                "Regime fit": p.regime_fit,
                "Price": p.price,
                "Entry": p.entry,
                "Stop": p.stop,
                "Target": p.target,
                "R:R": p.rr,
                "Rationale": p.rationale,
            }
            for p in picks
        ]
    )


# Strategy catalog for UI (from briefing)
ALGO_STRATEGY_CATALOG: list[dict[str, str]] = [
    {
        "name": "VWAP pullback",
        "type": "Institutional / intraday",
        "regime": "Trend or mild range",
        "risk": "Medium",
        "sebi": "White-box — logic visible in StockSight rules",
    },
    {
        "name": "ORB / scalping",
        "type": "Intraday breakout",
        "regime": "Opening hour, high volume",
        "risk": "Medium–high",
        "sebi": "Throttle orders; use kill switch on broker",
    },
    {
        "name": "Grid-style range",
        "type": "Range-bound",
        "regime": "Mixed / sideways markets",
        "risk": "Medium — trend breaks grid",
        "sebi": "Not auto-grid deployed here — manual levels from scan",
    },
    {
        "name": "TWAP-style slicing",
        "type": "Execution (thin names)",
        "regime": "Low liquidity",
        "risk": "Low slippage focus",
        "sebi": "Split orders yourself; no HFT infra in app",
    },
    {
        "name": "Weekly / monthly ATH",
        "type": "Swing & long-term",
        "regime": "Bullish structural trend",
        "risk": "Lower frequency",
        "sebi": "Positional CNC — no intraday Algo ID required for investing",
    },
    {
        "name": "Martingale averaging",
        "type": "Not recommended",
        "regime": "Sideways (deceptive)",
        "risk": "Very high — trend risk",
        "sebi": "Not implemented — educational warning only",
    },
]
