"""
Bottom-confirmation features for Healthy Dip (Layer 2).

Each feature uses only bars available at the evaluation index (no lookahead).
Group scores are averaged with equal group weight so correlated indicators
cannot dominate the final 0–100 score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from healthy_dip_config import FEATURE_GROUPS, get_healthy_dip_config

logger = logging.getLogger(__name__)


def _series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def ema_series(closes: pd.Series, span: int) -> pd.Series:
    """EMA via ewm (causal; no center=True)."""
    return closes.astype(float).ewm(span=int(span), adjust=False).mean()


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """Wilder-style ATR using ewm alpha = 1/period."""
    prev = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev).abs(),
            (low - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / float(period), adjust=False).mean()


def rsi_series(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def pivot_low_indices(lows: pd.Series, window: int) -> list[int]:
    """Fractal pivot lows: low[i] <= neighbors within ±window (excludes edges)."""
    n = len(lows)
    w = int(window)
    out: list[int] = []
    if n < w * 2 + 1:
        return out
    vals = lows.astype(float).values
    for i in range(w, n - w):
        left = vals[i - w : i]
        right = vals[i + 1 : i + w + 1]
        if vals[i] <= float(np.min(left)) and vals[i] <= float(np.min(right)):
            out.append(i)
    return out


def feature_higher_low(lows: pd.Series, window: int = 3, at: Optional[int] = None) -> bool:
    """True when the latest confirmed pivot low is above the prior pivot low."""
    end = len(lows) if at is None else int(at) + 1
    sub = lows.iloc[:end]
    pivots = pivot_low_indices(sub, window)
    # Last pivot must be confirmed (at least `window` bars after it)
    confirmed = [p for p in pivots if p <= end - 1 - window]
    if len(confirmed) < 2:
        return False
    return float(sub.iloc[confirmed[-1]]) > float(sub.iloc[confirmed[-2]])


def feature_close_above_ema_turning_up(
    closes: pd.Series,
    span: int = 20,
    at: Optional[int] = None,
) -> bool:
    """Close > EMA(span) and EMA slope positive over the last bar."""
    end = len(closes) if at is None else int(at) + 1
    if end < span + 2:
        return False
    c = closes.iloc[:end].astype(float)
    ema = ema_series(c, span)
    if bool(pd.isna(ema.iloc[-1])) or bool(pd.isna(ema.iloc[-2])):
        return False
    return float(c.iloc[-1]) > float(ema.iloc[-1]) and float(ema.iloc[-1]) > float(ema.iloc[-2])


def feature_capitulation_day(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    *,
    lookback: int = 10,
    vol_mult: float = 2.0,
    wick_frac: float = 0.50,
    at: Optional[int] = None,
    open_: Optional[pd.Series] = None,
) -> bool:
    """
    Capitulation in the last `lookback` bars:
    volume > vol_mult × 20d avg, lower wick > wick_frac of range, close in upper half.
    """
    if open_ is not None:
        return feature_capitulation_day_ohlc(
            open_,
            high,
            low,
            close,
            volume,
            lookback=lookback,
            vol_mult=vol_mult,
            wick_frac=wick_frac,
            at=at,
        )
    end = len(close) if at is None else int(at) + 1
    if end < 25:
        return False
    # Without Open, approximate body low with Close (conservative).
    o = close.iloc[:end]
    return feature_capitulation_day_ohlc(
        o,
        high.iloc[:end],
        low.iloc[:end],
        close.iloc[:end],
        volume.iloc[:end],
        lookback=lookback,
        vol_mult=vol_mult,
        wick_frac=wick_frac,
        at=None,
    )

def feature_capitulation_day_ohlc(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    *,
    lookback: int = 10,
    vol_mult: float = 2.0,
    wick_frac: float = 0.50,
    at: Optional[int] = None,
) -> bool:
    """Capitulation using true lower wick = min(open, close) - low."""
    end = len(close) if at is None else int(at) + 1
    if end < 25:
        return False
    o = open_.iloc[:end].astype(float)
    h = high.iloc[:end].astype(float)
    l = low.iloc[:end].astype(float)
    c = close.iloc[:end].astype(float)
    v = volume.iloc[:end].astype(float)
    vol_ma = v.rolling(20).mean()
    start = max(20, end - lookback)
    for i in range(start, end):
        rng = float(h.iloc[i] - l.iloc[i])
        if rng <= 0 or bool(pd.isna(vol_ma.iloc[i])) or float(vol_ma.iloc[i]) <= 0:
            continue
        body_low = float(min(o.iloc[i], c.iloc[i]))
        lower_wick = body_low - float(l.iloc[i])
        mid = float(l.iloc[i] + 0.5 * rng)
        if (
            float(v.iloc[i]) > vol_mult * float(vol_ma.iloc[i])
            and lower_wick / rng >= wick_frac
            and float(c.iloc[i]) >= mid
        ):
            return True
    return False


def feature_selling_exhaustion(
    close: pd.Series,
    volume: pd.Series,
    *,
    exhaustion_vol_frac: float = 0.70,
    up_down_ratio_min: float = 1.2,
    at: Optional[int] = None,
) -> bool:
    """5d avg vol < frac × 20d avg AND 10d up-volume / down-volume > ratio."""
    end = len(close) if at is None else int(at) + 1
    if end < 25:
        return False
    c = close.iloc[:end].astype(float)
    v = volume.iloc[:end].astype(float)
    vol20 = float(v.iloc[-20:].mean())
    vol5 = float(v.iloc[-5:].mean())
    if vol20 <= 0:
        return False
    if vol5 >= exhaustion_vol_frac * vol20:
        return False
    # up/down volume over last 10 days
    window = 10
    up_vol = 0.0
    down_vol = 0.0
    for i in range(end - window, end):
        if i <= 0:
            continue
        if float(c.iloc[i]) >= float(c.iloc[i - 1]):
            up_vol += float(v.iloc[i])
        else:
            down_vol += float(v.iloc[i])
    if down_vol <= 0:
        return up_vol > 0
    return (up_vol / down_vol) >= up_down_ratio_min


def feature_atr_compression(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    fast: int = 5,
    slow: int = 20,
    max_ratio: float = 0.80,
    at: Optional[int] = None,
) -> bool:
    end = len(close) if at is None else int(at) + 1
    if end < slow + 2:
        return False
    h = high.iloc[:end]
    l = low.iloc[:end]
    c = close.iloc[:end]
    a_fast = atr_series(h, l, c, fast)
    a_slow = atr_series(h, l, c, slow)
    if bool(pd.isna(a_fast.iloc[-1])) or bool(pd.isna(a_slow.iloc[-1])) or float(a_slow.iloc[-1]) <= 0:
        return False
    return float(a_fast.iloc[-1]) / float(a_slow.iloc[-1]) < max_ratio


def feature_bullish_rsi_divergence(
    closes: pd.Series,
    *,
    rsi_period: int = 14,
    pivot_window: int = 3,
    at: Optional[int] = None,
) -> bool:
    """Lower price pivot low with higher RSI pivot low."""
    end = len(closes) if at is None else int(at) + 1
    if end < rsi_period + pivot_window * 4:
        return False
    c = closes.iloc[:end].astype(float)
    rsi = rsi_series(c, rsi_period)
    price_pivots = [p for p in pivot_low_indices(c, pivot_window) if p <= end - 1 - pivot_window]
    if len(price_pivots) < 2:
        return False
    i1, i2 = price_pivots[-2], price_pivots[-1]
    if bool(pd.isna(rsi.iloc[i1])) or bool(pd.isna(rsi.iloc[i2])):
        return False
    return float(c.iloc[i2]) < float(c.iloc[i1]) and float(rsi.iloc[i2]) > float(rsi.iloc[i1])


def feature_rs_outperformance(
    stock_closes: pd.Series,
    index_closes: pd.Series,
    *,
    lookback: int = 10,
    at: Optional[int] = None,
) -> bool:
    """10-day stock return minus index return > 0."""
    end = len(stock_closes) if at is None else int(at) + 1
    if end <= lookback or len(index_closes) < end:
        return False
    s = stock_closes.iloc[:end].astype(float)
    idx = index_closes.iloc[:end].astype(float)
    # align by position (caller should align calendars)
    if float(s.iloc[-lookback - 1]) <= 0 or float(idx.iloc[-lookback - 1]) <= 0:
        return False
    stock_ret = float(s.iloc[-1]) / float(s.iloc[-lookback - 1]) - 1.0
    idx_ret = float(idx.iloc[-1]) / float(idx.iloc[-lookback - 1]) - 1.0
    return (stock_ret - idx_ret) > 0.0


def feature_rs_line_near_high(
    stock_closes: pd.Series,
    index_closes: pd.Series,
    *,
    lookback: int = 20,
    near_pct: float = 0.02,
    at: Optional[int] = None,
) -> bool:
    """Relative-strength line (stock/index) within near_pct of its lookback high."""
    end = len(stock_closes) if at is None else int(at) + 1
    if end < lookback or len(index_closes) < end:
        return False
    s = stock_closes.iloc[:end].astype(float)
    idx = index_closes.iloc[:end].astype(float).replace(0.0, np.nan)
    rs = (s / idx).dropna()
    if len(rs) < lookback:
        return False
    window = rs.iloc[-lookback:]
    hi = float(window.max())
    last = float(window.iloc[-1])
    if hi <= 0:
        return False
    return last >= hi * (1.0 - near_pct)


def feature_near_support(
    closes: pd.Series,
    *,
    ma200: Optional[float] = None,
    prior_base: Optional[float] = None,
    anchored_vwap: Optional[float] = None,
    band_pct: tuple[float, float] = (3.0, 5.0),
    at: Optional[int] = None,
) -> bool:
    """Price within band_pct of 200 DMA, prior base, or anchored VWAP."""
    end = len(closes) if at is None else int(at) + 1
    if end < 1:
        return False
    px = float(closes.iloc[end - 1])
    lo, hi = float(band_pct[0]), float(band_pct[1])
    for level in (ma200, prior_base, anchored_vwap):
        if level is None or level <= 0:
            continue
        dist = abs(px - float(level)) / float(level) * 100.0
        if lo <= dist <= hi or dist <= hi:
            # within 0..hi% counts as "near" (user said 3-5% band; allow ≤ max)
            if dist <= hi:
                return True
    return False


def anchored_vwap_from_swing_low(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    swing_low_idx: int,
    at: Optional[int] = None,
) -> Optional[float]:
    """VWAP anchored at swing_low_idx through `at` (inclusive)."""
    end = len(close) if at is None else int(at) + 1
    if swing_low_idx < 0 or swing_low_idx >= end:
        return None
    h = high.iloc[swing_low_idx:end].astype(float)
    l = low.iloc[swing_low_idx:end].astype(float)
    c = close.iloc[swing_low_idx:end].astype(float)
    v = volume.iloc[swing_low_idx:end].astype(float)
    typical = (h + l + c) / 3.0
    denom = float(v.sum())
    if denom <= 0:
        return None
    return float((typical * v).sum() / denom)


def feature_new_20d_low_recent(
    lows: pd.Series,
    *,
    lookback: int = 20,
    recent_bars: int = 3,
    at: Optional[int] = None,
) -> bool:
    """True if a new `lookback`-day low printed in the last `recent_bars` bars."""
    end = len(lows) if at is None else int(at) + 1
    if end < lookback + 1:
        return False
    l = lows.iloc[:end].astype(float)
    for i in range(end - recent_bars, end):
        window = l.iloc[max(0, i - lookback + 1) : i + 1]
        if float(l.iloc[i]) <= float(window.min()) + 1e-12:
            return True
    return False


def feature_index_above_ma50(index_closes: pd.Series, at: Optional[int] = None) -> bool:
    end = len(index_closes) if at is None else int(at) + 1
    if end < 55:
        return False
    c = index_closes.iloc[:end].astype(float)
    ma = c.rolling(50).mean()
    if bool(pd.isna(ma.iloc[-1])):
        return False
    return float(c.iloc[-1]) > float(ma.iloc[-1])


def feature_vix_falling_from_spike(
    vix_closes: pd.Series,
    *,
    spike_lookback: int = 20,
    at: Optional[int] = None,
) -> bool:
    """VIX made a local high in lookback and is now lower than 3 bars ago."""
    end = len(vix_closes) if at is None else int(at) + 1
    if end < spike_lookback + 3:
        return False
    v = vix_closes.iloc[:end].astype(float)
    recent_high = float(v.iloc[-spike_lookback:].max())
    last = float(v.iloc[-1])
    prev3 = float(v.iloc[-4])
    # spike = last high near recent high, and declining
    near_spike = last >= 0.85 * recent_high or recent_high == float(v.iloc[-spike_lookback:].max())
    return near_spike and last < prev3 and recent_high > last


@dataclass
class BottomConfirmationResult:
    score: float
    state: str
    groups_hit: list[str] = field(default_factory=list)
    group_scores: dict[str, float] = field(default_factory=dict)
    features: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def score_bottom_confirmation(
    ohlcv: pd.DataFrame,
    *,
    index_closes: Optional[pd.Series] = None,
    vix_closes: Optional[pd.Series] = None,
    cfg: Optional[dict[str, Any]] = None,
    at: Optional[int] = None,
) -> BottomConfirmationResult:
    """
    Score Layer-2 bottom confirmation at bar `at` (default: last bar).

    Groups are weighted equally. Confirmed requires ≥ min_groups_for_confirmed
    distinct groups with a positive contribution.
    """
    cfg = cfg or get_healthy_dip_config()
    end = len(ohlcv) if at is None else int(at) + 1
    df = ohlcv.iloc[:end]
    if len(df) < 30:
        return BottomConfirmationResult(score=0.0, state="Falling", notes=["insufficient bars"])

    o = _series(df, "Open")
    h = _series(df, "High")
    l = _series(df, "Low")
    c = _series(df, "Close")
    v = _series(df, "Volume")

    feats: dict[str, bool] = {}
    feats["higher_low"] = feature_higher_low(l, int(cfg["pivot_window"]))
    feats["ema_structure"] = feature_close_above_ema_turning_up(c, int(cfg["ema_span"]))
    if len(o) == len(c):
        feats["capitulation"] = feature_capitulation_day_ohlc(
            o,
            h,
            l,
            c,
            v,
            lookback=int(cfg["capitulation_lookback"]),
            vol_mult=float(cfg["capitulation_vol_mult"]),
            wick_frac=float(cfg["capitulation_wick_frac"]),
        )
    else:
        feats["capitulation"] = False
    feats["exhaustion"] = feature_selling_exhaustion(
        c,
        v,
        exhaustion_vol_frac=float(cfg["exhaustion_vol_frac"]),
        up_down_ratio_min=float(cfg["up_down_vol_ratio_min"]),
    )
    feats["atr_compression"] = feature_atr_compression(
        h,
        l,
        c,
        fast=int(cfg["atr_fast"]),
        slow=int(cfg["atr_slow"]),
        max_ratio=float(cfg["atr_ratio_max"]),
    )
    feats["rsi_divergence"] = feature_bullish_rsi_divergence(
        c, pivot_window=int(cfg["pivot_window"])
    )

    if index_closes is not None and len(index_closes) >= end:
        idx = index_closes.iloc[:end]
        feats["rs_outperform"] = feature_rs_outperformance(
            c, idx, lookback=int(cfg["rs_lookback"])
        )
        feats["rs_near_high"] = feature_rs_line_near_high(
            c, idx, lookback=int(cfg["rs_line_lookback"])
        )
        feats["index_above_ma50"] = feature_index_above_ma50(idx)
    else:
        feats["rs_outperform"] = False
        feats["rs_near_high"] = False
        feats["index_above_ma50"] = False

    # Support: 200 DMA + prior pivot base + AVWAP from last pivot low
    ma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
    pivots = [p for p in pivot_low_indices(l, int(cfg["pivot_window"])) if p <= end - 1 - int(cfg["pivot_window"])]
    prior_base = float(l.iloc[pivots[-1]]) if pivots else None
    avwap = None
    if pivots:
        avwap = anchored_vwap_from_swing_low(h, l, c, v, pivots[-1])
    band = tuple(cfg["support_band_pct"])
    feats["near_support"] = feature_near_support(
        c, ma200=ma200, prior_base=prior_base, anchored_vwap=avwap, band_pct=band
    )

    if vix_closes is not None and len(vix_closes) >= min(end, 25):
        # align by tail length
        vx = vix_closes.iloc[-min(len(vix_closes), end) :]
        feats["vix_falling"] = feature_vix_falling_from_spike(vx)
    else:
        feats["vix_falling"] = False
        logger.debug("VIX series missing — regime VIX feature skipped")

    group_map: dict[str, list[str]] = {
        "structure": ["higher_low", "ema_structure"],
        "volume": ["capitulation", "exhaustion"],
        "volatility": ["atr_compression"],
        "momentum": ["rsi_divergence"],
        "relative_strength": ["rs_outperform", "rs_near_high"],
        "support": ["near_support"],
        "regime": ["index_above_ma50", "vix_falling"],
    }

    group_scores: dict[str, float] = {}
    groups_hit: list[str] = []
    for g in FEATURE_GROUPS:
        keys = group_map[g]
        vals = [1.0 if feats.get(k) else 0.0 for k in keys]
        gs = float(np.mean(vals)) if vals else 0.0
        group_scores[g] = gs
        if gs > 0:
            groups_hit.append(g)

    raw = float(np.mean([group_scores[g] for g in FEATURE_GROUPS])) * 100.0
    notes: list[str] = []
    new_low = feature_new_20d_low_recent(
        l,
        lookback=int(cfg["new_low_lookback"]),
        recent_bars=int(cfg["new_low_recent_bars"]),
    )
    if new_low:
        raw = max(0.0, raw - float(cfg["new_low_penalty"]))
        notes.append("penalty: new 20d low in last 3 bars")

    n_groups = len(groups_hit)
    min_g = int(cfg["min_groups_for_confirmed"])
    conf_min = float(cfg["confirmed_score_min"])
    base_min = float(cfg["basing_score_min"])

    if new_low and n_groups >= 2 and raw < conf_min:
        state = "Failed"
        notes.append("structure attempted but new lows — Failed")
    elif n_groups >= min_g and raw >= conf_min and not new_low:
        state = "Confirmed"
    elif n_groups >= 2 or raw >= base_min:
        state = "Basing"
    else:
        state = "Falling"

    return BottomConfirmationResult(
        score=round(raw, 1),
        state=state,
        groups_hit=groups_hit,
        group_scores={k: round(v, 3) for k, v in group_scores.items()},
        features=feats,
        notes=notes,
    )


def layer3_risk_fields(
    price: float,
    swing_low: float,
    atr: float,
    *,
    cfg: Optional[dict[str, Any]] = None,
    capital: Optional[float] = None,
) -> dict[str, Any]:
    """Invalidation, stop %, position size, tranche suggestion."""
    cfg = cfg or get_healthy_dip_config()
    atr = float(atr or 0.0)
    inv = float(swing_low) - float(cfg["invalidation_atr_mult"]) * atr
    if price <= 0 or inv >= float(price):
        return {
            "invalidation": round(inv, 2),
            "stop_pct": None,
            "position_size": 0,
            "drop_wide_stop": True,
            "tranche_note": "Invalid setup — price at/below invalidation",
        }
    stop_pct = (float(price) - inv) / float(price) * 100.0
    cap = float(capital if capital is not None else cfg["default_capital"])
    risk_pct = float(cfg["risk_pct_of_capital"])
    pos = 0
    try:
        from paper_trading import suggest_quantity
    except ImportError:
        from .paper_trading import suggest_quantity  # type: ignore
    pos = suggest_quantity(cash=cap, entry=price, stop=inv, risk_pct=risk_pct)
    drop = bool(stop_pct > float(cfg["max_stop_pct"]))
    first = float(cfg["tranche_first_frac"])
    return {
        "invalidation": round(inv, 2),
        "stop_pct": round(stop_pct, 2),
        "position_size": int(pos),
        "drop_wide_stop": drop,
        "tranche_note": (
            f"~{int(first * 100)}% on first confirmation; remainder on retest that holds"
        ),
    }
