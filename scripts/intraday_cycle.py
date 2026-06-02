#!/usr/bin/env python3
"""
Headless intraday trading cycle for StockSight (no Streamlit UI).

Steps (default --phase full):
  1. Gap scan (pre-market / open battle map)
  2. Intraday strategy scan (BROAD, MOMENTUM, VWAP, ORB, GAP, ATH)
  3. Overlap filter (intraday names that also gapped)
  4. Export CSV + JSON summary under output/intraday/

Run from repo root:
  python scripts/intraday_cycle.py
  python scripts/intraday_cycle.py --universe "Nifty 50 (fast)" --data-source yahoo

GitHub Actions: see .github/workflows/intraday-cycle.yml
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# stocksight package on path
_ROOT = Path(__file__).resolve().parents[1]
_STOCKSIGHT = _ROOT / "stocksight"
if str(_STOCKSIGHT) not in sys.path:
    sys.path.insert(0, str(_STOCKSIGHT))

from intraday import (  # noqa: E402
    STRATEGIES,
    STRATEGY_LABEL,
    GapResult,
    IntradayFilters,
    IntradayResult,
    IntradayScanStats,
    compute_market_mood,
    compute_volume_time_prediction,
    resolve_universe,
    scan_gaps,
    scan_intraday,
)
from market_sentiment import add_market_sentiment_columns  # noqa: E402
from quality_gate import apply_quality_gate_columns  # noqa: E402

try:
    from scan_history_store import append_scan_record  # noqa: E402
except ImportError:
    append_scan_record = None  # type: ignore[misc, assignment]

EXIT_HINT_BY_STRATEGY: dict[str, str] = {
    "GAP": "Book 50% at Target (1:2) · exit all if gap fills · flat by close",
    "MOMENTUM": "Book 50% at Target (1:2) · trail stop under 5m swing lows",
    "ORB": "Book 50–100% at Target (1:1.5) · exit if loses ORB high",
    "ATH": "Book 50% at Target (1:2) · trail stop on new highs",
    "VWAP": "Book 50% at Target (1:2) · exit if 5m close < VWAP",
    "BROAD": "Book 50% at 1× risk or Target · strict flat by close",
}

STRATEGY_TIME_ORDER = ("GAP", "MOMENTUM", "ORB", "ATH", "VWAP", "BROAD")
DEFAULT_STRATEGIES = ("BROAD", "MOMENTUM", "VWAP", "ORB", "GAP")
DEFAULT_UNIVERSE_NSE = "Nifty 50 (fast)"
DEFAULT_UNIVERSE_US = "Liquid US shortlist (~35)"


def _format_confluence(strategy_codes: list[str]) -> str:
    ordered = [s for s in STRATEGY_TIME_ORDER if s in strategy_codes]
    ordered += [s for s in strategy_codes if s not in ordered]
    if not ordered:
        return "—"
    if len(ordered) == 1:
        return STRATEGY_LABEL.get(ordered[0], ordered[0])
    short = " + ".join(STRATEGY_LABEL.get(s, s).split(" ", 1)[-1][:10] for s in ordered[:4])
    return f"{len(ordered)}× {short}"


def _build_confluence_map(results: list[IntradayResult]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in results:
        out.setdefault(r.raw_ticker, [])
        if r.strategy not in out[r.raw_ticker]:
            out[r.raw_ticker].append(r.strategy)
    return out


def intraday_results_to_df(
    results: list[IntradayResult],
    *,
    market: str = "NSE",
    confluence_map: Optional[dict[str, list[str]]] = None,
    sort_by_gate: bool = True,
    with_sentiment: bool = True,
) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    conf = confluence_map if confluence_map is not None else _build_confluence_map(results)
    rows: list[dict[str, Any]] = []
    for rank, r in enumerate(results, start=1):
        codes = conf.get(r.raw_ticker, [r.strategy])
        row: dict[str, Any] = {
            "S.No.": rank,
            "Rank": f"#{rank}",
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Confluence": _format_confluence(codes),
            "Strategy": STRATEGY_LABEL.get(r.strategy, r.strategy),
            "Score /120": r.score_120,
            "Tier": r.rank_tier or "—",
            "Size": r.position_size or "—",
            "Rank Why": r.rank_why or "—",
            "Prediction": r.prediction or "—",
            "Sess vol %": r.session_vol_pct,
            "Sector": r.sector,
            "Price": r.price,
            "% chg": r.pct_change,
            "Gap %": r.gap_pct,
            "RSI(5m)": r.rsi,
            "Vol×": r.vol_ratio,
            "vs VWAP %": r.pct_vs_vwap,
            "vs 50DMA %": r.pct_vs_ma50d,
            "vs 200DMA %": r.pct_vs_ma200d,
            "↓ from 52w": r.pct_vs_52w_high,
            "ORB High": r.orb_high,
            "ORB Low": r.orb_low,
            "Entry": r.entry,
            "Stop": r.stop,
            "Target": r.target,
            "R:R": r.rr_ratio,
            "Exit plan": EXIT_HINT_BY_STRATEGY.get(r.strategy, "Book 50% at Target · flat by close"),
            "Setup": r.setup_note,
        }
        for name, url in (r.links or {}).items():
            row[name] = url
        rows.append(row)
    df = pd.DataFrame(rows).dropna(axis=1, how="all")
    if with_sentiment and not df.empty:
        df = add_market_sentiment_columns(df, market=market, insert_after="Ticker")
    if not df.empty:
        df = apply_quality_gate_columns(df, profile="intraday", confluence_map=conf)
        if sort_by_gate and "Gate score" in df.columns:
            df = df.sort_values("Gate score", ascending=False, kind="stable").reset_index(drop=True)
            if "S.No." in df.columns:
                df["S.No."] = range(1, len(df) + 1)
            if "Rank" in df.columns:
                df["Rank"] = [f"#{i}" for i in range(1, len(df) + 1)]
    return df


def gap_results_to_df(gaps: list[GapResult], *, market: str = "NSE") -> pd.DataFrame:
    if not gaps:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for rank, g in enumerate(gaps, start=1):
        row = {
            "S.No.": rank,
            "Ticker": g.ticker,
            "Raw": g.raw_ticker,
            "Sector": g.sector,
            "Dir": ("⬆ UP" if g.direction == "UP" else ("⬇ DOWN" if g.direction == "DOWN" else "▬")),
            "Size": g.size_band,
            "Prev Close": g.prev_close,
            "Open": g.open_px,
            "LTP": g.current_price,
            "Gap %": g.gap_pct,
            "Open→Now %": g.open_to_now_pct,
            "Day High": g.intraday_high,
            "Day Low": g.intraday_low,
            "Vol×": g.vol_ratio,
            "Holding?": "✅" if g.holding else "⚠",
            "Advice": g.advice,
        }
        for name, url in (g.links or {}).items():
            row[name] = url
        rows.append(row)
    df = pd.DataFrame(rows).dropna(axis=1, how="all")
    if not df.empty:
        df = add_market_sentiment_columns(df, market=market, insert_after="Ticker")
        df = apply_quality_gate_columns(df, profile="gap", sort_by_gate=True)
    return df


def _stats_dict(stats: IntradayScanStats) -> dict[str, Any]:
    return asdict(stats)


def _progress(i: int, total: int, symbol: str) -> None:
    pct = int(100 * i / max(total, 1))
    print(f"\r  [{pct:3d}%] {i}/{total} {symbol[:24]:<24}", end="", flush=True)
    if i >= total:
        print()


def run_gap_scan(
    tickers: list[str],
    *,
    min_gap_pct: float,
    market: str,
) -> tuple[list[GapResult], tuple[str, str]]:
    print(f"\n=== Gap scan ({len(tickers)} tickers, min |gap| {min_gap_pct}%) ===")
    gaps = scan_gaps(tickers, min_gap_abs_pct=min_gap_pct, progress_cb=_progress)
    mood, note = compute_market_mood(gaps)
    print(f"  Gaps found: {len(gaps)} · mood: {mood}")
    return gaps, (mood, note)


def run_intraday_scan(
    tickers: list[str],
    *,
    strategies: tuple[str, ...],
    filters: IntradayFilters,
    market: str,
    data_source: str,
) -> tuple[list[IntradayResult], IntradayScanStats]:
    print(f"\n=== Intraday scan ({len(tickers)} tickers, strategies={','.join(strategies)}) ===")
    print(f"  Data source: {data_source}")
    results, stats = scan_intraday(
        tickers,
        strategies,
        filters,
        progress_cb=_progress,
        market=market,
        data_source=data_source,
    )
    print(
        f"  Matches: {len(results)} rows · scanned={stats.total_scanned} "
        f"· no_data={stats.no_data} · breeze_bars={stats.bars_from_breeze} "
        f"· yahoo_bars={stats.bars_from_yahoo}"
    )
    return results, stats


def filter_overlap(
    intraday: list[IntradayResult],
    gaps: list[GapResult],
) -> list[IntradayResult]:
    gap_set = {g.raw_ticker for g in gaps if g.raw_ticker}
    return [r for r in intraday if r.raw_ticker in gap_set]


def write_outputs(
    out_dir: Path,
    stamp: str,
    *,
    gaps: list[GapResult],
    intraday: list[IntradayResult],
    overlap: list[IntradayResult],
    market: str,
    universe: str,
    mood: str,
    mood_note: str,
    stats: Optional[IntradayScanStats],
    data_source: str,
    strategies: tuple[str, ...],
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    conf = _build_confluence_map(intraday)
    paths: dict[str, str] = {}

    if gaps:
        gdf = gap_results_to_df(gaps, market=market)
        p = out_dir / f"gaps_{stamp}.csv"
        gdf.to_csv(p, index=False)
        paths["gaps_csv"] = str(p)

    if intraday:
        idf = intraday_results_to_df(intraday, market=market, confluence_map=conf)
        p = out_dir / f"intraday_all_{stamp}.csv"
        idf.to_csv(p, index=False)
        paths["intraday_csv"] = str(p)

    if overlap:
        odf = intraday_results_to_df(overlap, market=market, confluence_map=conf)
        p = out_dir / f"intraday_gap_overlap_{stamp}.csv"
        odf.to_csv(p, index=False)
        paths["overlap_csv"] = str(p)

    vol_pred = compute_volume_time_prediction(market)
    summary: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "universe": universe,
        "data_source": data_source,
        "strategies": list(strategies),
        "gap_mood": mood,
        "gap_mood_note": mood_note,
        "gap_count": len(gaps),
        "intraday_match_rows": len(intraday),
        "overlap_rows": len(overlap),
        "session_prediction": vol_pred.prediction,
        "session_vol_pct": vol_pred.session_vol_pct,
        "market_local_time": vol_pred.market_local_time,
        "outputs": paths,
    }
    if stats is not None:
        summary["scan_stats"] = _stats_dict(stats)

    if intraday:
        top = intraday_results_to_df(intraday[:15], market=market, confluence_map=conf)
        cols = [c for c in ("Ticker", "Strategy", "Quality Gate", "Gate score", "Entry", "Stop", "Target") if c in top.columns]
        summary["top_rows"] = top[cols].head(10).to_dict(orient="records") if cols else []

    sp = out_dir / f"summary_{stamp}.json"
    sp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["summary_json"] = str(sp)
    summary["outputs"] = paths
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="StockSight headless intraday cycle")
    p.add_argument(
        "--phase",
        choices=("full", "gap", "intraday", "overlap"),
        default="full",
        help="full = gap + intraday + overlap export (choices: full, gap, intraday, overlap)",
    )
    p.add_argument("--market", choices=("NSE", "US"), default="NSE")
    p.add_argument("--universe", default="", help=f"Universe label (NSE default: {DEFAULT_UNIVERSE_NSE})")
    p.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help="Comma-separated strategy codes",
    )
    p.add_argument("--gap-min-pct", type=float, default=1.0, help="Minimum absolute gap percent for gap scan")
    p.add_argument(
        "--data-source",
        choices=("auto", "breeze", "yahoo"),
        default="yahoo",
        help="yahoo recommended for GitHub Actions; breeze needs daily session token",
    )
    p.add_argument("--out-dir", default="", help="Output folder (default: output/intraday)")
    p.add_argument("--max-tickers", type=int, default=0, help="Cap universe size (0 = no cap)")
    p.add_argument("--skip-sentiment", action="store_true", help="Skip market sentiment columns (faster)")
    p.add_argument("--history", action="store_true", help="Append to stocksight/.scan_history.jsonl")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    market = args.market.upper()
    universe = args.universe or (DEFAULT_UNIVERSE_NSE if market == "NSE" else DEFAULT_UNIVERSE_US)
    tickers = resolve_universe(universe, market)
    if not tickers:
        print(f"ERROR: Unknown or empty universe '{universe}' for market {market}", file=sys.stderr)
        print("  List keys in intraday.INTRADAY_UNIVERSES_BY_MARKET", file=sys.stderr)
        return 1
    if args.max_tickers > 0:
        tickers = tickers[: args.max_tickers]

    strat_raw = [s.strip().upper() for s in args.strategies.split(",") if s.strip()]
    strategies = tuple(s for s in strat_raw if s in STRATEGIES)
    if not strategies and args.phase in ("full", "intraday", "overlap"):
        print(f"ERROR: No valid strategies in {args.strategies}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else _ROOT / "output" / "intraday"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    flt = IntradayFilters()

    print(f"StockSight intraday cycle · phase={args.phase} · {universe} ({len(tickers)} tickers)")

    gaps: list[GapResult] = []
    intraday: list[IntradayResult] = []
    overlap: list[IntradayResult] = []
    stats: Optional[IntradayScanStats] = None
    mood, mood_note = "—", ""

    if args.phase in ("full", "gap"):
        gaps, (mood, mood_note) = run_gap_scan(tickers, min_gap_pct=args.gap_min_pct, market=market)
        if append_scan_record and args.history:
            append_scan_record(
                "gap_cycle",
                universe,
                [g.raw_ticker for g in gaps],
                meta={"matches": len(gaps), "mood": mood},
            )

    if args.phase in ("full", "intraday"):
        intraday, stats = run_intraday_scan(
            tickers,
            strategies=strategies,
            filters=flt,
            market=market,
            data_source=args.data_source,
        )
        if append_scan_record and args.history:
            append_scan_record(
                "intraday_cycle",
                universe,
                list({r.raw_ticker for r in intraday}),
                meta={"rows": len(intraday), "data_source": args.data_source},
            )

    if args.phase in ("full", "overlap"):
        if not gaps and args.phase == "overlap":
            print("WARN: overlap phase needs gaps from a prior gap run; running gap scan first.")
            gaps, (mood, mood_note) = run_gap_scan(tickers, min_gap_pct=args.gap_min_pct, market=market)
        if not intraday:
            intraday, stats = run_intraday_scan(
                tickers,
                strategies=strategies,
                filters=flt,
                market=market,
                data_source=args.data_source,
            )
        overlap = filter_overlap(intraday, gaps)
        print(f"\n=== Gap overlap: {len(overlap)} intraday row(s) on gapped names ===")

    summary = write_outputs(
        out_dir,
        stamp,
        gaps=gaps,
        intraday=intraday,
        overlap=overlap,
        market=market,
        universe=universe,
        mood=mood,
        mood_note=mood_note,
        stats=stats,
        data_source=args.data_source,
        strategies=strategies,
    )

    print("\n=== Done ===")
    for label, path in summary.get("outputs", {}).items():
        print(f"  {label}: {path}")
    print("\nEducational scan only — review CSVs before placing orders in ICICI Breeze / your broker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
