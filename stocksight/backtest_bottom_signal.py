"""
Backtest Healthy Dip bottom-confirmation vs baseline (health-gate only).

Measures:
  1) % of Confirmed picks that make a new low within 20 trading days
     + median extra drawdown after the signal
  2) Same metrics for all healthy-dip survivors without requiring Confirmed
  3) Forward returns at 5 / 10 / 20 days for both groups

Uses Yahoo history (survivorship bias: delisted names generally absent).
Point-in-time fundamentals are best-effort (Yahoo `info` is current; we
label that limitation in the report). Coarse thresholds only — no tuning.

Usage (from stocksight/):
  python backtest_bottom_signal.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from bottom_confirmation import score_bottom_confirmation
from healthy_dip_config import get_healthy_dip_config
from screener import (
    drawdown_pct_from_52w_high,
    extract_healthy_dip_fundamentals,
    get_pe,
    normalize_debt_equity,
)


# Coarse sample — Nifty-50 style names that lived through 2020 / 2022 drawdowns.
TICKERS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "LT.NS",
    "AXISBANK.NS",
    "KOTAKBANK.NS",
    "HINDUNILVR.NS",
    "ASIANPAINT.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "BAJFINANCE.NS",
    "WIPRO.NS",
    "ULTRACEMCO.NS",
    "NESTLEIND.NS",
]

INDEX = "^NSEI"
VIX = "^INDIAVIX"

# Bear / stress windows (inclusive) — evaluate monthly sample dates inside.
REGIMES = {
    "covid_2020": ("2020-02-01", "2020-05-31"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "recent_2024_25": ("2024-06-01", "2025-12-31"),
}


@dataclass
class SignalEvent:
    ticker: str
    date: pd.Timestamp
    regime: str
    state: str
    score: float
    price: float
    new_low_20d: bool
    extra_dd_pct: float
    ret_5: Optional[float]
    ret_10: Optional[float]
    ret_20: Optional[float]


def _fwd_return(closes: pd.Series, i: int, horizon: int) -> Optional[float]:
    if i + horizon >= len(closes):
        return None
    a = float(closes.iloc[i])
    b = float(closes.iloc[i + horizon])
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _new_low_and_extra_dd(lows: pd.Series, closes: pd.Series, i: int, horizon: int = 20) -> tuple[bool, float]:
    if i + 1 >= len(lows):
        return False, 0.0
    sig_low = float(lows.iloc[i])
    sig_px = float(closes.iloc[i])
    end = min(len(lows), i + 1 + horizon)
    future_low = float(lows.iloc[i + 1 : end].min()) if end > i + 1 else sig_low
    new_low = future_low < sig_low - 1e-9
    extra = 0.0
    if sig_px > 0 and future_low < sig_px:
        extra = (sig_px - future_low) / sig_px * 100.0
    return new_low, extra


def _passes_health_gate(info: dict, price: float, hist: pd.DataFrame, cfg: dict) -> bool:
    fund = extract_healthy_dip_fundamentals(info)
    roe = fund.get("roe_pct")
    if roe is None or roe < float(cfg["min_roe_pct"]):
        return False
    de = fund.get("debt_equity")
    if de is not None and de > float(cfg["max_debt_equity"]):
        return False
    opm = fund.get("operating_margin_pct")
    if opm is not None and opm < float(cfg["min_operating_margin_pct"]):
        return False
    sales = fund.get("revenue_growth_pct")
    if sales is not None and sales < float(cfg["min_sales_growth_3y_pct"]):
        return False
    wk_high = fund.get("week52_high")
    if wk_high is None or wk_high <= 0:
        # trailing 252 high from hist up to signal (point-in-time price path)
        wk_high = float(hist["High"].iloc[-252:].max()) if len(hist) >= 60 else float(hist["High"].max())
    dd = drawdown_pct_from_52w_high(price, wk_high)
    if dd is None:
        return False
    if dd < float(cfg["drawdown_min_pct"]) or dd > float(cfg["drawdown_max_pct"]):
        return False
    return True


def _month_ends(start: str, end: str) -> list[pd.Timestamp]:
    idx = pd.date_range(start=start, end=end, freq="BM")
    return list(idx)


def evaluate_ticker(
    ticker: str,
    hist: pd.DataFrame,
    index_closes: pd.Series,
    vix_closes: Optional[pd.Series],
    info: dict,
    cfg: dict,
) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    if hist is None or hist.empty or len(hist) < 220:
        return events
    closes = hist["Close"].astype(float)
    lows = hist["Low"].astype(float)
    # Align index/vix by date
    for regime, (start, end) in REGIMES.items():
        for dt in _month_ends(start, end):
            # find last available bar on/before dt
            sub = hist.loc[:dt]
            if len(sub) < 220:
                continue
            i = len(sub) - 1
            price = float(sub["Close"].iloc[-1])
            # Health gate uses CURRENT yahoo info (limitation noted in report)
            if not _passes_health_gate(info, price, sub, cfg):
                continue
            idx_sub = index_closes.loc[:dt] if index_closes is not None else None
            vx_sub = vix_closes.loc[:dt] if vix_closes is not None else None
            bottom = score_bottom_confirmation(
                sub,
                index_closes=idx_sub,
                vix_closes=vx_sub,
                cfg=cfg,
            )
            # Map i to full hist position
            full_i = hist.index.get_loc(sub.index[-1])
            if isinstance(full_i, slice):
                full_i = full_i.stop - 1
            if isinstance(full_i, np.ndarray):
                full_i = int(full_i[-1])
            new_low, extra = _new_low_and_extra_dd(lows, closes, int(full_i), 20)
            events.append(
                SignalEvent(
                    ticker=ticker,
                    date=pd.Timestamp(sub.index[-1]),
                    regime=regime,
                    state=bottom.state,
                    score=bottom.score,
                    price=price,
                    new_low_20d=new_low,
                    extra_dd_pct=extra,
                    ret_5=_fwd_return(closes, int(full_i), 5),
                    ret_10=_fwd_return(closes, int(full_i), 10),
                    ret_20=_fwd_return(closes, int(full_i), 20),
                )
            )
    return events


def _summarize(events: list[SignalEvent], label: str) -> dict[str, Any]:
    if not events:
        return {"group": label, "n": 0}
    n = len(events)
    nl = sum(1 for e in events if e.new_low_20d)
    extras = [e.extra_dd_pct for e in events]
    def med(vals):
        vals = [v for v in vals if v is not None]
        return float(np.median(vals)) if vals else None

    return {
        "group": label,
        "n": n,
        "pct_new_low_20d": round(100.0 * nl / n, 1),
        "median_extra_dd_pct": round(med(extras) or 0.0, 2),
        "median_ret_5d": round(med([e.ret_5 for e in events]) or 0.0, 2),
        "median_ret_10d": round(med([e.ret_10 for e in events]) or 0.0, 2),
        "median_ret_20d": round(med([e.ret_20 for e in events]) or 0.0, 2),
    }


def main() -> None:
    # Coarse Layer-1 — slightly relaxed vs production so bear windows produce events
    cfg = get_healthy_dip_config(
        min_roe_pct=12.0,
        max_debt_equity=1.5,
        min_operating_margin_pct=8.0,
        min_sales_growth_3y_pct=0.0,
        drawdown_min_pct=15.0,
        drawdown_max_pct=45.0,
        apply_promoter_gates=False,
        require_qtr_profit_not_falling=False,
        apply_interest_coverage=False,
    )

    print("Loading index / VIX…")
    idx = yf.Ticker(INDEX).history(start="2019-01-01", auto_adjust=True)["Close"].astype(float)
    try:
        vix = yf.Ticker(VIX).history(start="2019-01-01", auto_adjust=True)["Close"].astype(float)
    except Exception:
        vix = None
        print("WARNING: India VIX unavailable")

    all_events: list[SignalEvent] = []
    for t in TICKERS:
        print(f"  {t}…")
        try:
            hist = yf.Ticker(t).history(start="2019-01-01", auto_adjust=True)
            if hist is None or hist.empty:
                print(f"    skip — no history")
                continue
            info = yf.Ticker(t).info or {}
            ev = evaluate_ticker(t, hist, idx, vix, info, cfg)
            print(f"    events={len(ev)}")
            all_events.extend(ev)
        except Exception as exc:
            print(f"    error: {exc}")

    baseline = all_events  # all health-gate passes
    confirmed = [e for e in all_events if e.state == "Confirmed"]

    rows = [
        _summarize(confirmed, "Confirmed"),
        _summarize(baseline, "All healthy dips (baseline)"),
    ]
    by_regime = []
    for regime in REGIMES:
        by_regime.append(
            _summarize([e for e in confirmed if e.regime == regime], f"Confirmed · {regime}")
        )
        by_regime.append(
            _summarize([e for e in baseline if e.regime == regime], f"Baseline · {regime}")
        )

    df = pd.DataFrame(rows + by_regime)
    print("\n=== RESULTS ===")
    print(df.to_string(index=False))

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "tickers": TICKERS,
        "n_events_baseline": len(baseline),
        "n_events_confirmed": len(confirmed),
        "table": df.to_dict(orient="records"),
        "limitations": [
            "Yahoo history excludes most delisted names → survivorship bias.",
            "Fundamentals use current Yahoo info, not point-in-time filings.",
            "Sample is 20 large-cap NSE names; not the full Nifty 500.",
            "Thresholds are coarse; results are descriptive, not optimized.",
            "Market breadth unavailable — regime uses index>50DMA + India VIX only.",
        ],
        "interpretation": [
            "pct_new_low_20d: how often price undercuts the signal low within 20 sessions.",
            "median_extra_dd_pct: median further drawdown from signal price.",
            "Forward returns are raw (not excess); compare Confirmed vs baseline.",
            "If Confirmed shows lower new-low rate and better forward returns, Layer 2 adds value.",
            "Small N or mixed regimes means do not treat this as proof of edge.",
        ],
    }
    out_path = "backtest_bottom_signal_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote {out_path}")
    print("\nLimitations:")
    for line in report["limitations"]:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
