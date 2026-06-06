"""
Volume surge screeners — fast accumulation (buy) vs fast distribution (sell).

Uses 5m/15m OHLCV only (no tick-level buy/sell split). Direction is inferred from
price action: green bars + rising price = buying pressure; red bars + falling price = selling.
"""

from __future__ import annotations

from typing import Optional

try:
    from screener import hist_series
except ImportError:
    from .screener import hist_series  # type: ignore[no-redef]


def _bar_direction_ratio(session, n: int = 4) -> tuple[float, float]:
    """Fraction of last ``n`` bars that closed up vs down."""
    if session is None or getattr(session, "empty", True) or len(session) < 2:
        return 0.0, 0.0
    tail = session.tail(n)
    try:
        opens = hist_series(tail, "Open").astype(float)
        closes = hist_series(tail, "Close").astype(float)
    except Exception:
        return 0.0, 0.0
    green = int((closes > opens).sum())
    red = int((closes < opens).sum())
    denom = max(len(tail), 1)
    return round(green / denom, 2), round(red / denom, 2)


def _volume_acceleration(vols, recent: int = 3, prior: int = 3) -> float:
    """Recent-bar mean volume ÷ prior-bar mean volume."""
    if vols is None or len(vols) < recent + prior + 1:
        return 0.0
    try:
        v = vols.astype(float).dropna()
        if len(v) < recent + prior:
            return 0.0
        r_mean = float(v.iloc[-recent:].mean())
        p_mean = float(v.iloc[-(recent + prior):-recent].mean())
        if p_mean <= 0:
            return 0.0
        return round(r_mean / p_mean, 2)
    except Exception:
        return 0.0


def _price_slope_pct(closes, n: int = 3) -> float:
    if closes is None or len(closes) < n + 1:
        return 0.0
    try:
        c = closes.astype(float).dropna()
        if len(c) < n + 1:
            return 0.0
        start = float(c.iloc[-(n + 1)])
        end = float(c.iloc[-1])
        if start <= 0:
            return 0.0
        return round((end - start) / start * 100.0, 2)
    except Exception:
        return 0.0


def enrich_ctx_for_vol_surge(ctx: dict) -> dict:
    """Attach volume-acceleration and buy/sell pressure fields to scan context."""
    session = ctx.get("session")
    bars = ctx.get("bars")
    if session is None or getattr(session, "empty", True):
        session = bars
    if session is None or getattr(session, "empty", True):
        return ctx

    try:
        vols = hist_series(session, "Volume").astype(float).dropna()
        closes = hist_series(session, "Close").astype(float).dropna()
    except Exception:
        return ctx

    accel_3 = _volume_acceleration(vols, recent=3, prior=3)
    accel_6 = _volume_acceleration(vols, recent=3, prior=6)
    vol_accel = max(accel_3, accel_6)
    green_ratio, red_ratio = _bar_direction_ratio(session, n=4)
    slope_3 = _price_slope_pct(closes, n=3)

    sess_vol = float(vols.sum()) if len(vols) else 0.0
    last_bar_vol = float(vols.iloc[-1]) if len(vols) else 0.0
    avg_dvol = float(ctx.get("avg_dvol") or 0.0)
    sess_part = round(sess_vol / avg_dvol, 2) if avg_dvol > 0 else 0.0

    price = float(ctx.get("price") or 0.0)
    vwap = ctx.get("vwap")
    pct_vwap = float(ctx.get("pct_vs_vwap") or 0.0)
    pct_chg = float(ctx.get("pct_change") or 0.0)
    vr = float(ctx.get("vol_ratio") or 0.0)

    above_vwap = price >= float(vwap) if vwap else pct_vwap >= 0
    below_vwap = price <= float(vwap) if vwap else pct_vwap <= 0

    buy_score = 0
    if vol_accel >= 1.5:
        buy_score += 2
    if vol_accel >= 2.0:
        buy_score += 1
    if green_ratio >= 0.5:
        buy_score += 2
    if slope_3 > 0.15:
        buy_score += 1
    if pct_chg >= 0.3:
        buy_score += 1
    if above_vwap:
        buy_score += 1
    if vr >= 1.4:
        buy_score += 1

    sell_score = 0
    if vol_accel >= 1.5:
        sell_score += 2
    if vol_accel >= 2.0:
        sell_score += 1
    if red_ratio >= 0.5:
        sell_score += 2
    if slope_3 < -0.15:
        sell_score += 1
    if pct_chg <= -0.4:
        sell_score += 1
    if below_vwap:
        sell_score += 1
    if vr >= 1.4:
        sell_score += 1

    ctx["vol_accel"] = vol_accel
    ctx["vol_accel_3v3"] = accel_3
    ctx["green_bar_ratio"] = green_ratio
    ctx["red_bar_ratio"] = red_ratio
    ctx["price_slope_3bar"] = slope_3
    ctx["session_volume"] = sess_vol
    ctx["session_vol_part"] = sess_part
    ctx["last_bar_volume"] = last_bar_vol
    ctx["buy_pressure_score"] = buy_score
    ctx["sell_pressure_score"] = sell_score
    return ctx


def _fmt_session_vol(vol: float) -> str:
    if vol <= 0:
        return "—"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return f"{int(vol)}"


def evaluate_vol_buy(ctx: dict) -> Optional[str]:
    """Fast volume increase with bullish price action — long-bias entry window."""
    vol_accel = float(ctx.get("vol_accel") or 0.0)
    vr = float(ctx.get("vol_ratio") or 0.0)
    green_ratio = float(ctx.get("green_bar_ratio") or 0.0)
    slope_3 = float(ctx.get("price_slope_3bar") or 0.0)
    pct_chg = float(ctx.get("pct_change") or 0.0)
    pct_vwap = ctx.get("pct_vs_vwap")
    rsi = ctx.get("rsi")
    sess_part = float(ctx.get("session_vol_part") or 0.0)
    buy_score = int(ctx.get("buy_pressure_score") or 0)

    if vol_accel < 1.55:
        return None
    if vr < 1.35:
        return None
    if green_ratio < 0.5:
        return None
    if slope_3 < 0.1:
        return None
    if pct_chg < 0.25:
        return None
    if pct_vwap is not None and float(pct_vwap) < -0.35:
        return None
    if rsi is not None and not (38.0 <= float(rsi) <= 78.0):
        return None
    if buy_score < 5:
        return None

    sess_txt = _fmt_session_vol(float(ctx.get("session_volume") or 0.0))
    return (
        f"Fast BUY vol · accel {vol_accel:.1f}× · bar-vol {vr:.1f}× · "
        f"sess {sess_txt} ({sess_part:.0%} day) · green {green_ratio:.0%} · "
        f"3m slope {slope_3:+.2f}% · day {pct_chg:+.2f}% · score {buy_score}/8"
    )


def evaluate_vol_dump(ctx: dict) -> Optional[str]:
    """Fast volume increase with bearish price action — distribution / sell pressure."""
    vol_accel = float(ctx.get("vol_accel") or 0.0)
    vr = float(ctx.get("vol_ratio") or 0.0)
    red_ratio = float(ctx.get("red_bar_ratio") or 0.0)
    slope_3 = float(ctx.get("price_slope_3bar") or 0.0)
    pct_chg = float(ctx.get("pct_change") or 0.0)
    pct_vwap = ctx.get("pct_vs_vwap")
    rsi = ctx.get("rsi")
    sess_part = float(ctx.get("session_vol_part") or 0.0)
    sell_score = int(ctx.get("sell_pressure_score") or 0)

    if vol_accel < 1.55:
        return None
    if vr < 1.35:
        return None
    if red_ratio < 0.5:
        return None
    if slope_3 > -0.1:
        return None
    if pct_chg > -0.35:
        return None
    if pct_vwap is not None and float(pct_vwap) > 0.35:
        return None
    if rsi is not None and float(rsi) > 62.0:
        return None
    if sell_score < 5:
        return None

    sess_txt = _fmt_session_vol(float(ctx.get("session_volume") or 0.0))
    return (
        f"Fast SELL vol · accel {vol_accel:.1f}× · bar-vol {vr:.1f}× · "
        f"sess {sess_txt} ({sess_part:.0%} day) · red {red_ratio:.0%} · "
        f"3m slope {slope_3:+.2f}% · day {pct_chg:+.2f}% · score {sell_score}/8"
    )


def vol_dump_soft_hard_rejects(reasons: list[str], ctx: dict) -> bool:
    """Allow distribution matches through mild long-side hard rejects when sell pressure is hot."""
    if not reasons:
        return True
    vol_accel = float(ctx.get("vol_accel") or 0.0)
    vr = float(ctx.get("vol_ratio") or 0.0)
    sell_score = int(ctx.get("sell_pressure_score") or 0)
    hot = vol_accel >= 1.8 and vr >= 1.5 and sell_score >= 5
    if not hot:
        return False
    soft = {"day<0", "vol<1.0x", "gap<-3%", "RSI>72", "vsVWAP>+2%"}
    return all(r in soft for r in reasons)


def vol_buy_soft_hard_rejects(reasons: list[str], ctx: dict) -> bool:
    """Allow accumulation matches through thin last-bar volume rejects."""
    if not reasons:
        return True
    vol_accel = float(ctx.get("vol_accel") or 0.0)
    vr = float(ctx.get("vol_ratio") or 0.0)
    buy_score = int(ctx.get("buy_pressure_score") or 0)
    hot = vol_accel >= 1.8 and vr >= 1.4 and buy_score >= 5
    if not hot:
        return False
    soft = {"vol<1.0x", "RSI>72", "vsVWAP>+2%"}
    return all(r in soft for r in reasons)
