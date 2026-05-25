"""
Live NSE screener engine — wraps `scan_healthy_dip` with progress callbacks and JSON rows.
Data: Yahoo Finance via yfinance (.NS symbols). Educational only.
"""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
_STOCKSIGHT = _ROOT / "stocksight"
if str(_STOCKSIGHT) not in sys.path:
    sys.path.insert(0, str(_STOCKSIGHT))

from screener import NIFTY_BENCHMARK, UNIVERSES, index_regime  # noqa: E402
from signals import (  # noqa: E402
    SignalResult,
    enrich_healthy_dip_fall_context,
    scan_healthy_dip,
)

ProgressCallback = Callable[[int, int, str], None]

PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {
        "label": "Balanced (recommended)",
        "universe": "Nifty 50 (NSE)",
        "min_roe_pct": 14.0,
        "max_debt_equity": 1.2,
        "max_pe": 35.0,
        "drawdown_min_pct": 15.0,
        "drawdown_max_pct": 48.0,
        "rsi_max": 42.0,
        "require_near_ma200": False,
        "ma200_tolerance_pct": 8.0,
        "apply_pb_filter": False,
        "apply_peg_filter": False,
        "apply_interest_coverage": False,
        "explain_fall": True,
    },
    "nse_screener": {
        "label": "NSE · Screener.in style",
        "universe": "Nifty 500 (NSE)",
        "min_roe_pct": 15.0,
        "max_debt_equity": 0.5,
        "max_pe": 25.0,
        "drawdown_min_pct": 18.0,
        "drawdown_max_pct": 45.0,
        "rsi_max": 42.0,
        "require_near_ma200": False,
        "ma200_tolerance_pct": 8.0,
        "apply_pb_filter": False,
        "apply_peg_filter": False,
        "apply_interest_coverage": True,
        "explain_fall": True,
    },
    "nifty50": {
        "label": "Nifty 50 · faster",
        "universe": "Nifty 50 (NSE)",
        "min_roe_pct": 14.0,
        "max_debt_equity": 1.2,
        "max_pe": 35.0,
        "drawdown_min_pct": 15.0,
        "drawdown_max_pct": 48.0,
        "rsi_max": 42.0,
        "require_near_ma200": False,
        "ma200_tolerance_pct": 8.0,
        "apply_pb_filter": False,
        "apply_peg_filter": False,
        "apply_interest_coverage": False,
        "explain_fall": True,
    },
}


@dataclass
class ScanConfig:
    preset: str = "nse_screener"
    universe: str = ""
    explain_fall: bool = True
    fall_context_max: int = 30

    def resolved(self) -> dict[str, Any]:
        base = dict(PRESETS.get(self.preset, PRESETS["nse_screener"]))
        if self.universe:
            base["universe"] = self.universe
        base["explain_fall"] = self.explain_fall
        return base


@dataclass
class ScanState:
    running: bool = False
    progress_pct: int = 0
    progress_label: str = ""
    universe: str = ""
    preset: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    total_scanned: int = 0
    match_count: int = 0
    index_regime: Optional[dict[str, Any]] = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "progress_pct": self.progress_pct,
            "progress_label": self.progress_label,
            "universe": self.universe,
            "preset": self.preset,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "total_scanned": self.total_scanned,
            "match_count": self.match_count,
            "index_regime": self.index_regime,
        }


_STATE = ScanState()
_STATE_LOCK = threading.Lock()


def get_scan_state() -> ScanState:
    with _STATE_LOCK:
        return ScanState(
            running=_STATE.running,
            progress_pct=_STATE.progress_pct,
            progress_label=_STATE.progress_label,
            universe=_STATE.universe,
            preset=_STATE.preset,
            started_at=_STATE.started_at,
            finished_at=_STATE.finished_at,
            error=_STATE.error,
            rows=list(_STATE.rows),
            total_scanned=_STATE.total_scanned,
            match_count=_STATE.match_count,
            index_regime=_STATE.index_regime,
        )


def _criteria_pass_flags(row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, bool]:
    """Per-filter pass flags for UI highlighting — aligned with `scan_healthy_dip` gates."""
    roe = row.get("roe_pct")
    de = row.get("debt_equity")
    pe = row.get("pe")
    dd = row.get("drawdown_52w_pct")
    rsi = row.get("rsi")
    ma200 = row.get("pct_vs_ma200")
    max_de = float(cfg.get("max_debt_equity", 1))

    return {
        "roe": roe is not None and roe >= float(cfg.get("min_roe_pct", 15)),
        # Banks often omit D/E on Yahoo — same as scan: skip gate when missing.
        "debt": de is None or de <= max_de,
        "pe": pe is not None and pe <= float(cfg.get("max_pe", 30)),
        "drawdown": dd is not None
        and float(cfg.get("drawdown_min_pct", 20)) <= dd <= float(cfg.get("drawdown_max_pct", 40)),
        "rsi": rsi is not None and rsi <= float(cfg.get("rsi_max", 40)),
        "ma200": (not cfg.get("require_near_ma200"))
        or (ma200 is not None and ma200 <= float(cfg.get("ma200_tolerance_pct", 5))),
    }


def signal_result_to_row(r: SignalResult, cfg: dict[str, Any]) -> dict[str, Any]:
    flags = {
        "roe": r.roe_pct is not None,
        "debt": r.debt_equity is not None,
        "pe": True,
        "drawdown": r.drawdown_52w_pct is not None,
        "rsi": True,
        "ma200": r.pct_vs_ma200 is not None or not cfg.get("require_near_ma200"),
    }
    criteria = _criteria_pass_flags(
        {
            "roe_pct": r.roe_pct,
            "debt_equity": r.debt_equity,
            "pe": r.pe,
            "drawdown_52w_pct": r.drawdown_52w_pct,
            "rsi": r.rsi,
            "pct_vs_ma200": r.pct_vs_ma200,
        },
        cfg,
    )
    all_pass = all(criteria.values())

    links = r.links or {}
    return {
        "ticker": r.ticker,
        "raw_ticker": r.raw_ticker,
        "currency": r.currency,
        "price": r.price,
        "pe": r.pe,
        "vol_ratio": r.vol_ratio,
        "rsi": r.rsi,
        "roe_pct": r.roe_pct,
        "debt_equity": r.debt_equity,
        "drawdown_52w_pct": r.drawdown_52w_pct,
        "pct_vs_ma200": r.pct_vs_ma200,
        "sector": r.sector,
        "confidence": r.confidence,
        "fall_context": r.fall_context,
        "news_sentiment": r.news_sentiment,
        "signal": r.signal_label,
        "all_conditions_met": all_pass,
        "criteria": criteria,
        "data_flags": flags,
        "links": links,
        "yahoo": links.get("Yahoo Finance"),
        "google": links.get("Google Finance"),
        "research": links.get("Moneycontrol") or links.get("MarketWatch"),
        "chart": links.get("TradingView"),
    }


def run_healthy_dip_scan(
    config: ScanConfig,
    *,
    progress_cb: Optional[ProgressCallback] = None,
    on_event: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """Run scan synchronously; updates global `_STATE`."""
    cfg = config.resolved()
    universe = str(cfg.get("universe") or "Nifty 500 (NSE)")
    tickers = UNIVERSES.get(universe, [])
    total = len(tickers)

    def _emit(evt: dict[str, Any]) -> None:
        if on_event:
            on_event(evt)

    with _STATE_LOCK:
        _STATE.running = True
        _STATE.progress_pct = 0
        _STATE.progress_label = "Starting…"
        _STATE.universe = universe
        _STATE.preset = config.preset
        _STATE.started_at = datetime.now(timezone.utc).isoformat()
        _STATE.finished_at = None
        _STATE.error = None
        _STATE.rows = []
        _STATE.total_scanned = total
        _STATE.match_count = 0
        try:
            _STATE.index_regime = index_regime(NIFTY_BENCHMARK)
        except Exception:
            _STATE.index_regime = None

    _emit({"type": "start", "total": total, "universe": universe})

    def inner_progress(i: int, t: int, sym: str) -> None:
        pct = int(i / max(t, 1) * 100)
        with _STATE_LOCK:
            _STATE.progress_pct = pct
            _STATE.progress_label = sym
        if progress_cb:
            progress_cb(i, t, sym)
        _emit({"type": "progress", "i": i, "total": t, "symbol": sym, "pct": pct})

    scan_kw = {
        k: cfg[k]
        for k in (
            "min_roe_pct",
            "max_debt_equity",
            "max_pe",
            "drawdown_min_pct",
            "drawdown_max_pct",
            "rsi_max",
            "require_near_ma200",
            "ma200_tolerance_pct",
            "apply_pb_filter",
            "apply_peg_filter",
            "apply_interest_coverage",
        )
        if k in cfg
    }

    try:
        results: list[SignalResult] = scan_healthy_dip(
            universe,
            progress_cb=inner_progress,
            **scan_kw,
        )
        if cfg.get("explain_fall") and results:
            cap = int(config.fall_context_max)
            if len(results) > cap:
                _emit({"type": "warn", "message": f"Fall context skipped for {len(results)} hits (cap {cap})."})
            else:
                enrich_healthy_dip_fall_context(results)
        rows = [signal_result_to_row(r, cfg) for r in results]
    except Exception as e:
        with _STATE_LOCK:
            _STATE.running = False
            _STATE.error = str(e)
            _STATE.finished_at = datetime.now(timezone.utc).isoformat()
        _emit({"type": "error", "message": str(e)})
        raise

    with _STATE_LOCK:
        _STATE.running = False
        _STATE.progress_pct = 100
        _STATE.progress_label = "Done"
        _STATE.rows = rows
        _STATE.match_count = len(rows)
        _STATE.finished_at = datetime.now(timezone.utc).isoformat()

    _emit({"type": "done", "matches": len(rows), "rows": rows})
    return rows


def start_scan_async(
    config: ScanConfig,
    on_event: Optional[Callable[[dict[str, Any]], None]] = None,
) -> threading.Thread:
    """Background thread for Flask SSE."""

    def _run() -> None:
        try:
            run_healthy_dip_scan(config, on_event=on_event)
        except Exception as e:
            on_event and on_event({"type": "error", "message": str(e)})

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    return th
