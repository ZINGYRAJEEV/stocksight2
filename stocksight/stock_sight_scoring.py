"""
StockSight long-term screener — 6-group composite (0–100), flag-based quality gate, final decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

# ── Flags ────────────────────────────────────────────────────────────────────

HARD_FLAGS = frozenset({"RSI_EXHAUSTION", "EARNINGS_IMMINENT", "NEGATIVE_MACD_FALLING"})
SOFT_FLAGS = frozenset({
    "LOW_VOLUME", "NO_NEWS", "BELOW_MA20", "DEATH_CROSS",
    "RS_NEGATIVE", "HIGH_DE", "NEG_REV_GROWTH", "FRESH_CROSS",
})

FLAG_LABELS = {
    "RSI_EXHAUSTION": "RSI > 72",
    "EARNINGS_IMMINENT": "Earnings ≤ 5d",
    "NEGATIVE_MACD_FALLING": "MACD hist falling 3+ bars",
    "LOW_VOLUME": "Vol ratio < 1.5×",
    "NO_NEWS": "No material news (T4)",
    "BELOW_MA20": "Below MA20",
    "DEATH_CROSS": "MA20 < MA50",
    "RS_NEGATIVE": "RS vs index < 0",
    "HIGH_DE": "D/E > 2.0",
    "NEG_REV_GROWTH": "Revenue growth negative",
    "FRESH_CROSS": "Fresh golden cross",
}

GATE_BANDS = {
    "A": {"label": "🟢 A · Trade ready", "bg": "#d1fae5", "fg": "#064e3b"},
    "B": {"label": "🟡 B · Watch", "bg": "#ecfccb", "fg": "#365314"},
    "C": {"label": "🟠 C · Caution", "bg": "#fef3c7", "fg": "#78350f"},
    "D": {"label": "🔴 D · Skip", "bg": "#fee2e2", "fg": "#991b1b"},
}

CONFLICT_BANNER = "Strong setup — wait for RSI to pull back below 70 before entry"


def news_score_to_tier(score: Optional[float]) -> int:
    if score is None:
        return 4
    try:
        s = float(score)
        if np.isnan(s):
            return 4
    except (TypeError, ValueError):
        return 4
    if s >= 80:
        return 1
    if s >= 60:
        return 2
    if s >= 30:
        return 3
    return 4


def news_tier_to_points(tier: int) -> int:
    return {1: 10, 2: 7, 3: 3, 4: 0}.get(int(tier), 0)


def score_band_color(score: Optional[float]) -> str:
    """UI bar colour: green / blue / red."""
    if score is None:
        return "grey"
    try:
        s = float(score)
        if np.isnan(s):
            return "grey"
    except (TypeError, ValueError):
        return "grey"
    if s >= 65:
        return "green"
    if s >= 45:
        return "blue"
    return "red"


# ── Group scorers ───────────────────────────────────────────────────────────

def score_rsi(rsi: Optional[float]) -> tuple[int, list[str]]:
    flags: list[str] = []
    if rsi is None:
        return 0, flags
    try:
        r = float(rsi)
        if np.isnan(r):
            return 0, flags
    except (TypeError, ValueError):
        return 0, flags
    if r > 72:
        flags.append("RSI_EXHAUSTION")
        return 0, flags
    if 45 <= r <= 65:
        return 10, flags
    if 40 <= r < 45 or 65 < r <= 70:
        return 7, flags
    if 35 <= r < 40 or 70 < r <= 72:
        return 4, flags
    if r < 35:
        return 2, flags
    return 0, flags


def score_macd_hist(
    hist_now: Optional[float],
    hist_prev: Optional[float],
) -> int:
    if hist_now is None or hist_prev is None:
        return 0
    try:
        h0 = float(hist_now)
        h1 = float(hist_prev)
        if np.isnan(h0) or np.isnan(h1):
            return 0
    except (TypeError, ValueError):
        return 0
    rising = h0 > h1
    if h0 > 0 and rising:
        return 8
    if h0 > 0:
        return 5
    if h0 < 0 and rising:
        return 3
    return 0


def macd_negative_falling_3bars(hist_tail: list[float]) -> bool:
    """True if last 3 bars are negative and each bar <= previous."""
    if len(hist_tail) < 4:
        return False
    last3 = [float(x) for x in hist_tail[-3:]]
    if any(np.isnan(x) for x in last3):
        return False
    if not all(x < 0 for x in last3):
        return False
    return last3[0] >= last3[1] >= last3[2]


def score_pct_vs_ma20(pct: Optional[float]) -> int:
    if pct is None:
        return 0
    try:
        p = float(pct)
        if np.isnan(p):
            return 0
    except (TypeError, ValueError):
        return 0
    if 2 <= p <= 8:
        return 7
    if 0 <= p < 2:
        return 5
    if 8 < p <= 12:
        return 3
    if p < 0:
        return 0
    if p > 12:
        return 1
    return 0


def score_pe(pe: Optional[float], sector_median_pe: Optional[float] = None) -> int:
    if pe is None:
        return 0
    try:
        p = float(pe)
        if np.isnan(p) or p <= 0:
            return 0
    except (TypeError, ValueError):
        return 0
    ref = sector_median_pe
    if ref is not None:
        try:
            ref = float(ref)
            if ref > 0 and not np.isnan(ref):
                ratio = p / ref
                if ratio < 0.75:
                    return 8
                if ratio < 1.0:
                    return 6
                if ratio < 1.5:
                    return 4
                if ratio < 2.0:
                    return 2
                return 0
        except (TypeError, ValueError):
            pass
    if p < 15:
        return 8
    if p < 25:
        return 5
    if p < 40:
        return 2
    return 0


def score_roe(roe: Optional[float]) -> int:
    if roe is None:
        return 0
    try:
        r = float(roe)
        if np.isnan(r):
            return 0
    except (TypeError, ValueError):
        return 0
    if r >= 20:
        return 7
    if r >= 15:
        return 5
    if r >= 10:
        return 3
    if r >= 5:
        return 1
    return 0


def score_rev_growth(rg: Optional[float]) -> int:
    if rg is None:
        return 0
    try:
        g = float(rg)
        if np.isnan(g):
            return 0
    except (TypeError, ValueError):
        return 0
    if g >= 20:
        return 5
    if g >= 10:
        return 4
    if g >= 5:
        return 3
    if g >= 0:
        return 1
    return 0


def score_volume_ratio(vr: Optional[float]) -> int:
    if vr is None:
        return 0
    try:
        v = float(vr)
        if np.isnan(v):
            return 0
    except (TypeError, ValueError):
        return 0
    if v >= 5:
        return 15
    if v >= 3:
        return 12
    if v >= 2:
        return 8
    if v >= 1.5:
        return 5
    if v >= 1:
        return 2
    return 0


def score_rs_vs_idx(rs: Optional[float]) -> int:
    if rs is None:
        return 0
    try:
        r = float(rs)
        if np.isnan(r):
            return 0
    except (TypeError, ValueError):
        return 0
    if r > 10:
        return 15
    if r > 5:
        return 12
    if r > 0:
        return 8
    if r >= -5:
        return 4
    return 0


def score_ma_cross(
    ma20: Optional[float],
    ma50: Optional[float],
    *,
    fresh_cross: bool = False,
) -> tuple[int, list[str]]:
    flags: list[str] = []
    if ma20 is None or ma50 is None:
        return 0, flags
    try:
        m20 = float(ma20)
        m50 = float(ma50)
        if np.isnan(m20) or np.isnan(m50):
            return 0, flags
    except (TypeError, ValueError):
        return 0, flags
    if m20 > m50:
        if fresh_cross:
            flags.append("FRESH_CROSS")
        return 8, flags
    flags.append("DEATH_CROSS")
    return 0, flags


def score_bollinger_pct_b(pct_b: Optional[float]) -> int:
    if pct_b is None:
        return 0
    try:
        b = float(pct_b)
        if np.isnan(b):
            return 0
    except (TypeError, ValueError):
        return 0
    if 0.4 <= b <= 0.8:
        return 7
    if 0.8 < b <= 1.0:
        return 4
    if 0.2 <= b < 0.4:
        return 3
    if b > 1.0:
        return 1
    if b < 0.2:
        return 1
    return 0


@dataclass
class StockSightResult:
    composite: float = 0.0
    g1_momentum: int = 0
    g2_fundamentals: int = 0
    g3_volume: int = 0
    g4_rs: int = 0
    g5_trend: int = 0
    g6_news: int = 0
    flags: list[str] = field(default_factory=list)
    gate_grade: str = "D"
    gate_label: str = ""
    gate_score: int = 0
    gate_why: str = ""
    final_decision: str = "Skip"
    matrix_note: str = ""
    conflict_banner: str = ""
    news_tier: int = 4
    score_band: str = "red"


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, str):
        s = v.strip().replace("%", "").replace("×", "")
        if not s or s in ("—", "-", "n/a", "Yes"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def evaluate_soft_hard_flags(
    *,
    rsi: Optional[float],
    vol_ratio: Optional[float],
    pct_vs_ma20: Optional[float],
    ma20: Optional[float],
    ma50: Optional[float],
    rs_vs_idx: Optional[float],
    de_ratio: Optional[float],
    rev_growth: Optional[float],
    d_earn: Optional[int],
    news_tier: int,
    macd_hist_tail: Optional[list[float]] = None,
    price: Optional[float] = None,
    existing_flags: Optional[list[str]] = None,
) -> list[str]:
    flags = list(existing_flags or [])

    r = _num(rsi)
    if r is not None and r > 72 and "RSI_EXHAUSTION" not in flags:
        flags.append("RSI_EXHAUSTION")

    if d_earn is not None:
        try:
            d = int(d_earn)
            if 0 <= d <= 5:
                flags.append("EARNINGS_IMMINENT")
        except (TypeError, ValueError):
            pass

    if macd_hist_tail and macd_negative_falling_3bars(macd_hist_tail):
        if "NEGATIVE_MACD_FALLING" not in flags:
            flags.append("NEGATIVE_MACD_FALLING")

    vr = _num(vol_ratio)
    if vr is not None and vr < 1.5:
        flags.append("LOW_VOLUME")

    if int(news_tier) >= 4:
        flags.append("NO_NEWS")

    p_ma = _num(pct_vs_ma20)
    px = _num(price)
    m20 = _num(ma20)
    if p_ma is not None and p_ma < 0:
        flags.append("BELOW_MA20")
    elif px is not None and m20 is not None and px < m20:
        flags.append("BELOW_MA20")

    m50 = _num(ma50)
    if m20 is not None and m50 is not None and m20 < m50:
        if "DEATH_CROSS" not in flags:
            flags.append("DEATH_CROSS")

    rs = _num(rs_vs_idx)
    if rs is not None and rs < 0:
        flags.append("RS_NEGATIVE")

    de = _num(de_ratio)
    if de is not None and de > 2.0:
        flags.append("HIGH_DE")

    rg = _num(rev_growth)
    if rg is not None and rg < 0:
        flags.append("NEG_REV_GROWTH")

    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def gate_from_flags(flags: list[str], composite: float) -> tuple[str, int, str]:
    hard = [f for f in flags if f in HARD_FLAGS]
    soft = [f for f in flags if f in SOFT_FLAGS and f != "FRESH_CROSS"]

    if hard:
        why = " · ".join(FLAG_LABELS.get(f, f) for f in hard[:3])
        return "D", 0, why or "Hard flag"

    if len(soft) >= 2:
        why = " · ".join(FLAG_LABELS.get(f, f) for f in soft[:3])
        return "C", 45, why or "2+ soft flags"

    if len(soft) == 1:
        why = FLAG_LABELS.get(soft[0], soft[0])
        return "B", 58, why

    if composite >= 60:
        return "A", 75, f"Composite {composite:.0f} — no flags"

    return "B", 50, f"Composite {composite:.0f} — watch"


def final_decision_label(composite: float, gate: str) -> str:
    if gate == "D":
        return "Skip"
    if composite >= 65:
        return "Neutral" if gate == "C" else "Buy / Watch"
    if composite >= 45:
        return "Buy / Watch" if gate == "A" else "Neutral"
    if gate == "C":
        return "Skip"
    return "Neutral"


def decision_matrix_note(decision: str, gate: str, composite: float) -> str:
    notes = {
        "Buy / Watch": f"Gate {gate} + composite {composite:.0f} — constructive setup; confirm on chart.",
        "Neutral": f"Gate {gate} + composite {composite:.0f} — mixed; no aggressive new position.",
        "Skip": f"Gate {gate} or weak composite {composite:.0f} — wait for better entry or pass.",
    }
    return notes.get(decision, "Educational matrix only — not financial advice.")


def conflict_banner_text(composite: float, gate: str, flags: list[str]) -> str:
    if composite >= 60 and gate == "D" and "RSI_EXHAUSTION" in flags:
        return CONFLICT_BANNER
    return ""


def compute_stock_sight_sentiment(
    *,
    macro_tone: str = "Neutral",
    sector_tone: str = "Neutral",
    vol_ratio: Optional[float] = None,
    rsi_exhaustion: bool = False,
) -> str:
    macro_bull = (macro_tone or "").lower() == "bullish"
    macro_bear = (macro_tone or "").lower() == "bearish"
    sector_bull = (sector_tone or "").lower() == "bullish"
    sector_neutral = (sector_tone or "").lower() in ("neutral", "")

    vr = _num(vol_ratio) or 0.0

    if macro_bear or rsi_exhaustion:
        return "⛔ Avoid"
    if macro_bull and sector_bull and vr > 2.0:
        return "🟢 Bullish"
    if macro_bull and (sector_neutral or (1.5 <= vr <= 2.0)):
        return "🟡 Lean Bullish"
    return "⬜ Neutral"


def format_return_chips(
    r1m: Optional[float],
    r3m: Optional[float],
    r6m: Optional[float],
    r1y: Optional[float],
) -> str:
    def _chip(label: str, val: Optional[float]) -> str:
        if val is None:
            return f"{label} —"
        try:
            v = float(val)
            if np.isnan(v):
                return f"{label} —"
        except (TypeError, ValueError):
            return f"{label} —"
        if v > 0:
            mark = "+"
            icon = "🟢"
        elif v < 0:
            mark = ""
            icon = "🔴"
        else:
            mark = ""
            icon = "⚪"
        return f"{icon}{label} {mark}{v:.1f}%"

    return " · ".join([
        _chip("1M", r1m),
        _chip("3M", r3m),
        _chip("6M", r6m),
        _chip("1Y", r1y),
    ])


def evaluate_stock_sight(
    row: dict[str, Any],
    *,
    sector_median_pe: Optional[float] = None,
    news_score: Optional[float] = None,
    news_tier: Optional[int] = None,
    macro_tone: str = "Neutral",
    sector_tone: str = "Neutral",
) -> StockSightResult:
    row = normalize_row_metrics(row)
    rsi = _num(row.get("RSI"))
    pe = _num(row.get("PE Ratio") or row.get("PE"))
    vol_ratio = _num(row.get("Volume Ratio") or row.get("Vol×"))
    rs_vs = _num(row.get("RS vs Idx") or row.get("RS20"))
    pct_ma = _num(row.get("% vs MA20"))
    pct_b = _num(row.get("%B Bollinger"))
    roe = _num(row.get("ROE %"))
    rev_g = _num(row.get("Rev growth %"))
    de = _num(row.get("D/E"))
    price = _num(row.get("Price"))
    ma20 = _num(row.get("MA20"))
    ma50 = _num(row.get("MA50"))
    d_earn = row.get("ΔEarn(d)")

    macd_h = _num(row.get("MACD Hist"))
    macd_prev = _num(row.get("MACD Hist prev"))
    macd_tail = row.get("MACD hist tail")
    if isinstance(macd_tail, list):
        tail = macd_tail
    else:
        tail = []
        if macd_prev is not None and macd_h is not None:
            tail = [macd_prev, macd_h]

    fresh = str(row.get("MA20×Golden50") or "").strip().lower() in ("yes", "true", "1")
    if ma20 is None and price is not None and pct_ma is not None:
        ma20 = price / (1.0 + pct_ma / 100.0) if pct_ma != -100 else None

    flags: list[str] = []
    rsi_pts, rsi_flags = score_rsi(rsi)
    flags.extend(rsi_flags)

    mom = rsi_pts
    mom += score_macd_hist(macd_h, macd_prev)
    mom += score_pct_vs_ma20(pct_ma)
    mom = min(25, mom)

    fund = score_pe(pe, sector_median_pe) + score_roe(roe) + score_rev_growth(rev_g)
    fund = min(20, fund)

    vol_pts = score_volume_ratio(vol_ratio)
    rs_pts = score_rs_vs_idx(rs_vs)

    cross_pts, cross_flags = score_ma_cross(ma20, ma50, fresh_cross=fresh)
    flags.extend(cross_flags)
    trend = cross_pts + score_bollinger_pct_b(pct_b)
    trend = min(15, trend)

    tier = news_tier
    if tier is None:
        if "T1" in str(row.get("Top tier", "")):
            tier = 1
        elif "T2" in str(row.get("Top tier", "")):
            tier = 2
        elif "T3" in str(row.get("Top tier", "")):
            tier = 3
        else:
            ns = news_score if news_score is not None else _num(row.get("News score"))
            tier = news_score_to_tier(ns)

    g6 = news_tier_to_points(int(tier))

    composite = min(100.0, float(mom + fund + vol_pts + rs_pts + trend + g6))

    flags = evaluate_soft_hard_flags(
        rsi=rsi,
        vol_ratio=vol_ratio,
        pct_vs_ma20=pct_ma,
        ma20=ma20,
        ma50=ma50,
        rs_vs_idx=rs_vs,
        de_ratio=de,
        rev_growth=rev_g,
        d_earn=d_earn if d_earn is not None else None,
        news_tier=int(tier),
        macd_hist_tail=tail if len(tail) >= 3 else None,
        price=price,
        existing_flags=flags,
    )

    gate, gate_score, gate_why = gate_from_flags(flags, composite)
    decision = final_decision_label(composite, gate)
    banner = conflict_banner_text(composite, gate, flags)
    note = decision_matrix_note(decision, gate, composite)
    if banner:
        note = f"{banner} · {note}"

    meta = GATE_BANDS[gate]
    return StockSightResult(
        composite=round(composite, 1),
        g1_momentum=mom,
        g2_fundamentals=fund,
        g3_volume=vol_pts,
        g4_rs=rs_pts,
        g5_trend=trend,
        g6_news=g6,
        flags=flags,
        gate_grade=gate,
        gate_label=meta["label"],
        gate_score=gate_score,
        gate_why=gate_why,
        final_decision=decision,
        matrix_note=note,
        conflict_banner=banner,
        news_tier=int(tier),
        score_band=score_band_color(composite),
    )


# Column aliases used across scenario / popular / multibagger tables
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "PE Ratio": ("PE", "P/E", "pe"),
    "Volume Ratio": ("Vol×", "Vol Ratio", "vol_ratio", "Vol vs 50d avg", "RVOL"),
    "RS vs Idx": ("RS20", "rel_strength_20d", "RS20_vs_idx", "RS vs index 20d"),
    "%B Bollinger": ("%B", "bb_pct_b"),
    "MACD Hist": ("MACD hist", "macd_hist"),
    "MACD Hist prev": ("MACD hist prev",),
    "MA20×Golden50": ("MA20×50", "Golden cross"),
    "Price": ("CMP", "CMP Rs.", "LTP", "price"),
    "ROE %": ("ROCE %", "roe_pct"),
    "Rev growth %": (
        "Qtr Sales Var %", "revenue_growth_pct", "Qtr Profit Var %",
        "EPS growth %", "Earnings CAGR %",
    ),
    "RSI": ("rsi",),
    "Sector": ("sector",),
    "D/E": ("debt_equity",),
    "return_1m_pct": ("Return 1M %", "1M %"),
    "return_3m_pct": ("Return 3M %", "3M %"),
    "return_6m_pct": ("Return 6M %", "6M %"),
    "return_1y_pct": ("Return 1Y %", "1Y %"),
}


def _truthy_cross(val: Any) -> bool:
    s = str(val or "").strip().lower()
    return s in ("yes", "true", "1", "✓", "y")


def normalize_row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Map heterogeneous screener columns to StockSight metric keys."""
    out = dict(row)
    for canonical, aliases in _METRIC_ALIASES.items():
        if out.get(canonical) is not None:
            continue
        for alias in aliases:
            if alias not in out:
                continue
            val = out[alias]
            if val is None or (isinstance(val, float) and np.isnan(val)):
                continue
            if canonical == "MA20×Golden50":
                out[canonical] = "Yes" if _truthy_cross(val) else "—"
            elif canonical == "ROE %":
                s = str(val).replace("*", "").replace("%", "").strip()
                try:
                    out[canonical] = float(s)
                except ValueError:
                    out[canonical] = val
            else:
                out[canonical] = val
            break
    if out.get("↓52w %") is not None and out.get("Drawdown %") is None:
        try:
            out["Drawdown %"] = abs(float(out["↓52w %"]))
        except (TypeError, ValueError):
            pass
    return out


def should_skip_stock_sight_profile(df) -> bool:
    """Specialized screeners keep their own primary scoring."""
    if df is None or df.empty:
        return True
    cols = set(df.columns)
    if cols & {"Score /120", "Gate 3 score", "Gate 1", "Gate 2", "Unified score"}:
        return True
    if "Gap %" in cols and cols & {"Advice", "Holding?"}:
        return True
    if "Crisis score" in cols:
        return True
    if "Lynch score" in cols:
        return True
    if "VCP score" in cols or "Rank score" in cols:
        return True
    if "Speed" in cols and "vs Open %" in cols:
        return True
    if "Gravity" in cols and "RVOL" in cols:
        return True
    return False


def _has_stock_sight_metrics(df) -> bool:
    if df is None or df.empty:
        return False
    cols = set(df.columns)
    has_ticker = bool(cols & {"Ticker", "ticker", "Name"})
    metric_hits = cols & {
        "RSI", "rsi", "PE Ratio", "PE", "P/E", "Vol×", "Volume Ratio",
        "Vol vs 50d avg", "RVOL", "MACD Hist", "MACD hist", "% vs MA20",
        "RS vs Idx", "RS20", "RS vs index 20d",
        "ROE %", "ROCE %", "Rev growth %", "Qtr Sales Var %",
        "EPS growth %", "Earnings CAGR %",
    }
    return has_ticker and bool(metric_hits)


def should_skip_stock_sight_overlay(df) -> bool:
    """Intraday/gap tables — skip long-term overlay (wrong timeframe)."""
    if df is None or df.empty:
        return True
    cols = set(df.columns)
    if cols & {"Score /120", "Gate 3 score", "Gate 1", "Gate 2", "Unified score"}:
        return True
    if "Gap %" in cols and cols & {"Advice", "Holding?"}:
        return True
    return False


def should_apply_stock_sight_scoring(df) -> bool:
    """True for daily/swing tables with enough metrics; false for intraday/gap/etc."""
    if df is None or df.empty:
        return False
    if should_skip_stock_sight_profile(df):
        return False
    cols = set(df.columns)
    if "G1 Momentum" in cols:
        return True
    return _has_stock_sight_metrics(df)


def should_apply_stock_sight_overlay(df) -> bool:
    """Secondary StockSight columns on specialized screeners (crisis, Lynch, stage2, etc.)."""
    if df is None or df.empty:
        return False
    if should_skip_stock_sight_overlay(df):
        return False
    if "SS Composite" in df.columns:
        return False
    if not should_skip_stock_sight_profile(df):
        return False
    return _has_stock_sight_metrics(df)


def preserve_domain_scores(df) -> "pd.DataFrame":
    """Keep screen-specific scores before StockSight overwrites Score/Composite."""
    import pandas as pd

    if df is None or df.empty:
        return df
    out = df.copy()
    if "Fit score" not in out.columns and "fit_score" in out.columns:
        out["Fit score"] = out["fit_score"]
    for src, dst in (
        ("Score", "Screen score"),
        ("Fit score", "Screen score"),
    ):
        if src in out.columns and dst not in out.columns and "G1 Momentum" not in out.columns:
            out[dst] = out[src]
    if "Score" in out.columns and "HP Score" not in out.columns and "Buy?" in out.columns:
        out["HP Score"] = out["Score"]
    return out


def pack_quality_gate(result: StockSightResult) -> dict[str, Any]:
    meta = GATE_BANDS[result.gate_grade]
    return {
        "band": result.gate_grade,
        "label": result.gate_label,
        "score": result.gate_score,
        "why": result.gate_why,
        "bg": meta["bg"],
        "fg": meta["fg"],
    }


def apply_stock_sight_columns(df, *, macro_tone: str = "Neutral") -> "pd.DataFrame":
    """Re-score rows with 6-group composite + gate + decision (e.g. after news enrichment)."""
    import pandas as pd

    if df is None or df.empty:
        return df
    out = preserve_domain_scores(df)

    composites: list[float] = []
    scores: list[float] = []
    decisions: list[str] = []
    notes: list[str] = []
    gates: list[str] = []
    gate_scores: list[int] = []
    gate_whys: list[str] = []
    g1s: list[int] = []
    g2s: list[int] = []
    g3s: list[int] = []
    g4s: list[int] = []
    g5s: list[int] = []
    g6s: list[int] = []
    flags_col: list[str] = []
    banners: list[str] = []
    bands: list[str] = []
    returns_col: list[str] = []
    sentiments: list[str] = []

    for _, row in out.iterrows():
        r = normalize_row_metrics(row.to_dict())
        ns = _num(r.get("News score"))
        res = evaluate_stock_sight(r, news_score=ns, macro_tone=macro_tone)
        composites.append(res.composite)
        scores.append(res.composite)
        decisions.append(res.final_decision)
        notes.append(res.matrix_note)
        gates.append(res.gate_label)
        gate_scores.append(res.gate_score)
        gate_whys.append(res.gate_why)
        g1s.append(res.g1_momentum)
        g2s.append(res.g2_fundamentals)
        g3s.append(res.g3_volume)
        g4s.append(res.g4_rs)
        g5s.append(res.g5_trend)
        g6s.append(res.g6_news)
        flags_col.append(", ".join(res.flags) if res.flags else "—")
        banners.append(res.conflict_banner or "—")
        bands.append(res.score_band)
        returns_col.append(format_return_chips(
            _num(r.get("return_1m_pct")),
            _num(r.get("return_3m_pct")),
            _num(r.get("return_6m_pct")),
            _num(r.get("return_1y_pct")),
        ))
        sector_tone = "Neutral"
        rs = _num(r.get("RS vs Idx"))
        if rs is not None:
            sector_tone = "Bullish" if rs > 0 else ("Bearish" if rs < -1 else "Neutral")
        sentiments.append(compute_stock_sight_sentiment(
            macro_tone=macro_tone,
            sector_tone=str(r.get("Sector tone") or sector_tone),
            vol_ratio=_num(r.get("Volume Ratio")),
            rsi_exhaustion="RSI_EXHAUSTION" in res.flags,
        ))

    out["Composite"] = composites
    if "Screen score" not in out.columns and "HP Score" not in out.columns:
        out["Score"] = scores
    else:
        out["StockSight score"] = scores
    out["Decision"] = decisions
    out["Matrix note"] = notes
    out["Quality Gate"] = gates
    out["Gate score"] = gate_scores
    out["Gate why"] = gate_whys
    out["G1 Momentum"] = g1s
    out["G2 Fundamentals"] = g2s
    out["G3 Volume"] = g3s
    out["G4 RS"] = g4s
    out["G5 Trend"] = g5s
    out["G6 News"] = g6s
    out["Flags"] = flags_col
    out["Conflict"] = banners
    out["Score band"] = bands
    out["Returns"] = returns_col
    if "StockSight sentiment" not in out.columns:
        out["StockSight sentiment"] = sentiments
    return out


def apply_stock_sight_overlay_columns(df, *, macro_tone: str = "Neutral") -> "pd.DataFrame":
    """
    Add prefixed StockSight columns without overwriting the screen's primary scores.
    Used on Crisis Value, Peter Lynch, Stage 2, Fast Movers, Volume Gravity, etc.
    """
    import pandas as pd

    if df is None or df.empty:
        return df
    out = df.copy()

    ss_composite: list[float] = []
    ss_decision: list[str] = []
    ss_gate: list[str] = []
    ss_gate_why: list[str] = []
    ss_flags: list[str] = []
    ss_conflict: list[str] = []
    ss_returns: list[str] = []
    ss_sentiment: list[str] = []
    ss_g1: list[int] = []
    ss_g2: list[int] = []
    ss_g3: list[int] = []
    ss_g4: list[int] = []
    ss_g5: list[int] = []
    ss_g6: list[int] = []

    for _, row in out.iterrows():
        r = normalize_row_metrics(row.to_dict())
        ns = _num(r.get("News score"))
        res = evaluate_stock_sight(r, news_score=ns, macro_tone=macro_tone)
        ss_composite.append(res.composite)
        ss_decision.append(res.final_decision)
        ss_gate.append(res.gate_label)
        ss_gate_why.append(res.gate_why)
        ss_flags.append(", ".join(res.flags) if res.flags else "—")
        ss_conflict.append(res.conflict_banner or "—")
        ss_returns.append(format_return_chips(
            _num(r.get("return_1m_pct")),
            _num(r.get("return_3m_pct")),
            _num(r.get("return_6m_pct")),
            _num(r.get("return_1y_pct")),
        ))
        sector_tone = "Neutral"
        rs = _num(r.get("RS vs Idx"))
        if rs is not None:
            sector_tone = "Bullish" if rs > 0 else ("Bearish" if rs < -1 else "Neutral")
        ss_sentiment.append(compute_stock_sight_sentiment(
            macro_tone=macro_tone,
            sector_tone=str(r.get("Sector tone") or sector_tone),
            vol_ratio=_num(r.get("Volume Ratio")),
            rsi_exhaustion="RSI_EXHAUSTION" in res.flags,
        ))
        ss_g1.append(res.g1_momentum)
        ss_g2.append(res.g2_fundamentals)
        ss_g3.append(res.g3_volume)
        ss_g4.append(res.g4_rs)
        ss_g5.append(res.g5_trend)
        ss_g6.append(res.g6_news)

    out["SS Composite"] = ss_composite
    out["SS Decision"] = ss_decision
    out["SS Gate"] = ss_gate
    out["SS Gate why"] = ss_gate_why
    out["SS Flags"] = ss_flags
    out["SS Conflict"] = ss_conflict
    out["SS Returns"] = ss_returns
    out["SS Sentiment"] = ss_sentiment
    out["SS G1"] = ss_g1
    out["SS G2"] = ss_g2
    out["SS G3"] = ss_g3
    out["SS G4"] = ss_g4
    out["SS G5"] = ss_g5
    out["SS G6"] = ss_g6
    return out
