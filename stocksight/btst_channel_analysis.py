"""
Kapil Mittal / Telegram BTST channel — reverse-engineered day-1 filters,
0–8 signal scoring, walk-forward backtest, and survivorship-bias reference data.

Educational only — not investment advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from .screener import compute_rsi, fetch_price_history, hist_series
except ImportError:
    from screener import compute_rsi, fetch_price_history, hist_series

# Names seen in public BTST performance screenshots (NSE).
KAPIL_STYLE_TICKERS: list[str] = [
    "ROTO.NS", "BATLIBOI.NS", "GARUDA.NS", "INDOBORAX.NS", "MANCREDIT.NS",
    "JPPOWER.NS", "PENIND.NS", "NDTV.NS", "BALAMINES.NS", "NPST.NS",
    "NEWGEN.NS", "ELECTTHERM.NS", "NIITLTD.NS", "PTCIL.NS", "VIPIND.NS",
    "THOMASCOOK.NS", "OCCLLTD.NS", "BCLIND.NS", "MOTISONS.NS", "EPACK.NS",
    "WENDT.NS", "GOLDIAM.NS", "TBZ.NS", "SENORES.NS", "AGARIND.NS",
    "SCPL.NS", "DEN.NS", "KIRLOSENG.NS", "POWERMECH.NS", "IRCON.NS",
    "HFCL.NS", "CUMMINSIND.NS", "NAZARA.NS", "TANLA.NS", "ROUTE.NS",
    "FINEORG.NS", "JYOTHYLAB.NS", "IDFCFIRSTB.NS", "KARURVYSYA.NS",
]

BIAS_DECODER_SESSIONS: list[dict[str, Any]] = [
    {
        "date": "May 26, 2026",
        "shown": [("MANCREDIT", 8.14), ("JPPOWER", 7.13), ("PENIND", 2.47), ("NDTV", 2.34)],
    },
    {
        "date": "Jun 2, 2026 (A)",
        "shown": [("BALAMINES", 8.38), ("NPST", 5.76), ("NEWGEN", 3.84)],
    },
    {
        "date": "Jun 2, 2026 (B)",
        "shown": [("ELECTTHERM", 16.75), ("NIITLTD", 14.74), ("PTCIL", 5.20), ("VIPIND", -0.48)],
    },
    {
        "date": "Jun 9, 2026 (A)",
        "shown": [("THOMASCOOK", 9.57), ("OCCLLTD", 7.13), ("BCLIND", 5.08)],
    },
    {
        "date": "Jun 9, 2026 (B)",
        "shown": [("MOTISONS", 14.98), ("EPACK", 8.15), ("KWIL", 7.29)],
    },
    {
        "date": "Jun 15, 2026",
        "shown": [("WENDT", 9.29), ("TBZ", 4.49), ("GOLDIAM", 2.76), ("SENORES", 1.63)],
    },
    {
        "date": "Jun 16, 2026",
        "shown": [("AGARIND", 5.11), ("HDBFS", 3.75), ("DEN", 1.53), ("SCPL", 1.46)],
    },
    {
        "date": "Jun 24, 2026",
        "shown": [("ROTO", 11.64), ("BATLIBOI", 5.23), ("GARUDA", 2.80), ("INDOBORAX", 2.40)],
    },
]

BIAS_RED_FLAGS: list[tuple[str, str]] = [
    (
        "Win rate ~97% with only one loser in 32 picks",
        "Real BTST setups typically win 55–65% of the time. Showing almost only winners "
        "strongly suggests cherry-picking after the fact.",
    ),
    (
        "Unknown total calls per day",
        "Only 3–4 names are shown. Were these called before the next session opened, "
        "or selected after seeing which names ran?",
    ),
    (
        "% High vs prev close is best-case",
        "Headline gains use the next day's **high**, not a realistic exit. Achievable "
        "returns are often 30–50% of the printed % high figure.",
    ),
    (
        "Low-float small caps dominate",
        "₹13–₹70 names can move 10–15% on thin liquidity — hard to replicate with size.",
    ),
    (
        "No stop-loss or loser track record",
        "A honest BTST log shows entries, stops, and full distribution of outcomes.",
    ),
]


@dataclass
class KapilDayMetrics:
    price: float
    prev_close: float
    intraday_gain_pct: float
    pct_vs_prev_close: float
    vol_mult: float
    rsi: float
    body_pct: float
    gain_5d_pct: float
    near_52w_high: bool
    kapil_score: int = 0
    kapil_signals: list[str] = field(default_factory=list)


@dataclass
class BtstBacktestTrade:
    signal_date: str
    entry: float
    next_high_pct: float
    next_low_pct: float
    next_close_pct: float
    pct_high_vs_prev: float
    pnl_pct: float
    outcome: str


def compute_kapil_day_metrics(
    hist: pd.DataFrame,
    *,
    min_price: float = 20.0,
    max_price: float = 2000.0,
) -> Optional[KapilDayMetrics]:
    """Day-1 selection metrics from daily OHLCV (latest bar = signal day)."""
    if hist is None or hist.empty or len(hist) < 25:
        return None

    closes = hist_series(hist, "Close").astype(float)
    highs = hist_series(hist, "High").astype(float)
    lows = hist_series(hist, "Low").astype(float)
    opens = hist_series(hist, "Open").astype(float)
    vols = hist_series(hist, "Volume").astype(float)

    price = float(closes.iloc[-1])
    if price < min_price or price > max_price:
        return None

    prev_close = float(closes.iloc[-2])
    day_open = float(opens.iloc[-1])
    day_high = float(highs.iloc[-1])
    day_low = float(lows.iloc[-1])

    if day_open <= 0 or prev_close <= 0:
        return None

    intraday_gain = round((price / day_open - 1.0) * 100.0, 2)
    pct_vs_prev = round((price / prev_close - 1.0) * 100.0, 2)

    avg_vol = float(vols.iloc[-21:-1].mean())
    vol_mult = round(float(vols.iloc[-1]) / avg_vol, 2) if avg_vol > 0 else 0.0

    rsi_val = compute_rsi(closes)
    if rsi_val is None or np.isnan(rsi_val):
        return None
    rsi = float(rsi_val)

    rng = max(day_high - day_low, 1e-9)
    body_pct = round(abs(price - day_open) / rng * 100.0, 1)
    gain_5d = round((price / float(closes.iloc[-6]) - 1.0) * 100.0, 2) if len(closes) >= 6 else 0.0

    high_52w = float(highs.iloc[-252:].max()) if len(highs) >= 20 else day_high
    near_52w = price >= high_52w * 0.98

    score, signals = score_kapil_day1(
        vol_mult=vol_mult,
        intraday_gain_pct=intraday_gain,
        pct_vs_prev_close=pct_vs_prev,
        body_pct=body_pct,
        rsi=rsi,
        gain_5d_pct=gain_5d,
        near_52w_high=near_52w,
    )

    return KapilDayMetrics(
        price=round(price, 2),
        prev_close=round(prev_close, 2),
        intraday_gain_pct=intraday_gain,
        pct_vs_prev_close=pct_vs_prev,
        vol_mult=vol_mult,
        rsi=round(rsi, 1),
        body_pct=body_pct,
        gain_5d_pct=gain_5d,
        near_52w_high=near_52w,
        kapil_score=score,
        kapil_signals=signals,
    )


def score_kapil_day1(
    *,
    vol_mult: float,
    intraday_gain_pct: float,
    pct_vs_prev_close: float,
    body_pct: float,
    rsi: float,
    gain_5d_pct: float,
    near_52w_high: bool,
) -> tuple[int, list[str]]:
    """0–8 Kapil-style momentum score (reverse-engineered from public posts)."""
    score = 0
    signals: list[str] = []

    if vol_mult >= 3.0:
        score += 2
        signals.append("VOL_SURGE_3X")
    elif vol_mult >= 2.0:
        score += 1
        signals.append("VOL_SURGE_2X")

    if intraday_gain_pct >= 3.0:
        score += 2
        signals.append("STRONG_CLOSE")
    elif intraday_gain_pct >= 1.5:
        score += 1
        signals.append("MILD_CLOSE")

    if body_pct >= 60:
        score += 1
        signals.append("BULLISH_BODY")

    if pct_vs_prev_close >= 0.5:
        score += 1
        signals.append("ABOVE_PREV_CLOSE")

    if rsi >= 60:
        score += 1
        signals.append("RSI_MOMENTUM")

    if near_52w_high:
        score += 1
        signals.append("NEAR_52W")

    if gain_5d_pct > 10.0:
        score -= 2
        signals.append("OVEREXTENDED_5D")

    return max(0, min(8, score)), signals


def kapil_grade(kapil_score: int) -> str:
    if kapil_score >= 5:
        return "A"
    if kapil_score >= 3:
        return "B"
    return "C"


def passes_kapil_filters(
    m: KapilDayMetrics,
    *,
    min_vol_mult: float = 2.0,
    min_intraday_gain: float = 1.5,
    max_intraday_gain: float = 8.0,
    min_pct_vs_prev: float = 1.5,
    max_pct_vs_prev: float = 5.0,
    min_rsi: float = 55.0,
    max_rsi: float = 75.0,
    max_gain_5d: float = 10.0,
    min_kapil_score: int = 2,
) -> bool:
    if m.vol_mult < min_vol_mult:
        return False
    if not (min_intraday_gain <= m.intraday_gain_pct <= max_intraday_gain):
        return False
    if not (min_pct_vs_prev <= m.pct_vs_prev_close <= max_pct_vs_prev):
        return False
    if not (min_rsi <= m.rsi <= max_rsi):
        return False
    if m.gain_5d_pct > max_gain_5d:
        return False
    return m.kapil_score >= min_kapil_score


def backtest_btst_symbol(
    raw: str,
    *,
    min_price: float = 20.0,
    max_price: float = 2000.0,
    min_vol_mult: float = 2.0,
    min_intraday_gain: float = 1.5,
    max_intraday_gain: float = 8.0,
    min_pct_vs_prev: float = 1.5,
    max_pct_vs_prev: float = 5.0,
    min_rsi: float = 55.0,
    max_rsi: float = 75.0,
    max_gain_5d: float = 10.0,
    min_kapil_score: int = 2,
    target_pct: float = 2.5,
    sl_pct: float = -2.0,
    window_days: int = 30,
    data_source: str = "yahoo",
) -> list[BtstBacktestTrade]:
    """
    Walk-forward: on each signal day apply Kapil filters, enter at close,
    measure next-day high/low/close vs entry (channel uses % high vs prev close).
    """
    try:
        from btst_screener import BtstFilters, _fetch_daily_hist
    except ImportError:
        from .btst_screener import BtstFilters, _fetch_daily_hist

    flt = BtstFilters(data_source=data_source)
    hist, _ = _fetch_daily_hist(raw, flt)
    if hist is None or hist.empty or len(hist) < window_days + 30:
        return []

    closes = hist_series(hist, "Close").astype(float)
    highs = hist_series(hist, "High").astype(float)
    lows = hist_series(hist, "Low").astype(float)
    opens = hist_series(hist, "Open").astype(float)

    trades: list[BtstBacktestTrade] = []
    start = max(25, len(hist) - window_days - 1)

    for i in range(start, len(hist) - 1):
        slice_df = hist.iloc[: i + 1]
        m = compute_kapil_day_metrics(slice_df, min_price=min_price, max_price=max_price)
        if m is None:
            continue
        if not passes_kapil_filters(
            m,
            min_vol_mult=min_vol_mult,
            min_intraday_gain=min_intraday_gain,
            max_intraday_gain=max_intraday_gain,
            min_pct_vs_prev=min_pct_vs_prev,
            max_pct_vs_prev=max_pct_vs_prev,
            min_rsi=min_rsi,
            max_rsi=max_rsi,
            max_gain_5d=max_gain_5d,
            min_kapil_score=min_kapil_score,
        ):
            continue

        entry = float(closes.iloc[i])
        prev_ref = float(closes.iloc[i])  # channel: prev day close ~3:25 PM
        nxt_high = float(highs.iloc[i + 1])
        nxt_low = float(lows.iloc[i + 1])
        nxt_close = float(closes.iloc[i + 1])
        nxt_open = float(opens.iloc[i + 1])

        pct_high = (nxt_high - entry) / entry * 100.0
        pct_low = (nxt_low - entry) / entry * 100.0
        pct_close = (nxt_close - entry) / entry * 100.0
        pct_high_vs_prev = (nxt_high - prev_ref) / prev_ref * 100.0 if prev_ref > 0 else 0.0

        hit_target = pct_high >= target_pct
        hit_sl = pct_low <= sl_pct
        if hit_target and hit_sl:
            outcome = "TARGET" if nxt_open >= entry * (1 + sl_pct / 100.0) else "SL"
        elif hit_target:
            outcome = "TARGET"
        elif hit_sl:
            outcome = "SL"
        else:
            outcome = "FLAT+" if pct_close >= 0 else "FLAT-"

        if outcome == "TARGET":
            pnl = target_pct
        elif outcome == "SL":
            pnl = sl_pct
        else:
            pnl = pct_close

        dt = hist.index[i]
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]

        trades.append(
            BtstBacktestTrade(
                signal_date=date_str,
                entry=round(entry, 2),
                next_high_pct=round(pct_high, 2),
                next_low_pct=round(pct_low, 2),
                next_close_pct=round(pct_close, 2),
                pct_high_vs_prev=round(pct_high_vs_prev, 2),
                pnl_pct=round(pnl, 2),
                outcome=outcome,
            )
        )

    return trades


def summarize_backtest(trades: list[BtstBacktestTrade]) -> dict[str, Any]:
    if not trades:
        return {}
    df = pd.DataFrame([t.__dict__ for t in trades])
    total = len(df)
    wins = int((df["outcome"] == "TARGET").sum())
    losses = int((df["outcome"] == "SL").sum())
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "hit_rate": round(wins / total * 100.0, 1) if total else 0.0,
        "avg_pnl": round(float(df["pnl_pct"].mean()), 2),
        "cum_pnl": round(float(df["pnl_pct"].sum()), 2),
        "avg_high_vs_prev": round(float(df["pct_high_vs_prev"].mean()), 2),
        "df": df,
    }


def bias_decoder_summary() -> dict[str, Any]:
    all_gains: list[float] = []
    winners = 0
    total = 0
    for sess in BIAS_DECODER_SESSIONS:
        for _, g in sess["shown"]:
            total += 1
            all_gains.append(float(g))
            if g > 0:
                winners += 1
    return {
        "total_picks": total,
        "winners": winners,
        "losers": total - winners,
        "reported_win_rate": round(winners / total * 100.0, 1) if total else 0.0,
        "avg_gain_shown": round(float(np.mean(all_gains)), 2) if all_gains else 0.0,
        "sessions": BIAS_DECODER_SESSIONS,
    }
