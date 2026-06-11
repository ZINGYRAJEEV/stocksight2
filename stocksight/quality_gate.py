"""
Shared Quality Gate (A–D) for scan result tables — row colour + grade columns.
Profiles: daily/swing screeners, gap scanner, intraday (delegates to intraday.py).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]

QUALITY_GATE_BANDS: dict[str, dict[str, str]] = {
    "A": {"label": "🟢 A · Trade ready", "bg": "#d1fae5", "fg": "#064e3b"},
    "B": {"label": "🟡 B · Watch", "bg": "#ecfccb", "fg": "#365314"},
    "C": {"label": "🟠 C · Caution", "bg": "#fef3c7", "fg": "#78350f"},
    "D": {"label": "🔴 D · Skip", "bg": "#fee2e2", "fg": "#991b1b"},
}

GATE_COL = "Quality Gate"
GATE_SCORE_COL = "Gate score"
GATE_WHY_COL = "Gate why"


def detect_quality_gate_profile(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "daily"
    cols = set(df.columns)
    if "Score /120" in cols or "Gate 3 score" in cols:
        return "intraday"
    if "Gap %" in cols and ("Advice" in cols or "Holding?" in cols):
        return "gap"
    return "daily"


def _band_from_points(pts: int, *, allow_a: bool = True) -> str:
    pts = max(0, min(100, int(pts)))
    if pts >= 75 and allow_a:
        return "A"
    if pts >= 58:
        return "B"
    if pts >= 38:
        return "C"
    return "D"


def _pack(band: str, pts: int, why_bits: list[str]) -> dict[str, Any]:
    meta = QUALITY_GATE_BANDS[band]
    return {
        "band": band,
        "label": meta["label"],
        "score": pts,
        "why": " · ".join(why_bits)[:200],
        "bg": meta["bg"],
        "fg": meta["fg"],
    }


def _sentiment_pts(sentiment: str) -> int:
    s = (sentiment or "").lower()
    if "strong bullish" in s:
        return 15
    if "bullish" in s and "bearish" not in s:
        return 10
    if "mixed" in s or "neutral" in s:
        return 2
    if "cautious" in s or "lean bearish" in s:
        return -8
    if "bearish" in s:
        return -15
    if "avoid" in s or "⛔" in (sentiment or ""):
        return -25
    return 0


def _news_pts(row: dict) -> int:
    top = str(row.get("Top tier") or "")
    score = row.get("News score")
    pts = 0
    if "T1" in top:
        pts += 10
    elif "T2" in top:
        pts += 5
    elif "T4" in top:
        pts -= 8
    try:
        if score is not None and float(score) < 40:
            pts -= 8
        elif score is not None and float(score) >= 70:
            pts += 5
    except (TypeError, ValueError):
        pass
    return pts


def compute_stock_sight_daily_gate(row: dict) -> dict[str, Any]:
    """Flag-based A–D gate from StockSight 6-group screener (when scoring columns present)."""
    try:
        from stock_sight_scoring import evaluate_stock_sight, pack_quality_gate
    except ImportError:
        from .stock_sight_scoring import evaluate_stock_sight, pack_quality_gate  # type: ignore[no-redef]
    res = evaluate_stock_sight(
        row,
        news_score=row.get("News score"),
    )
    return pack_quality_gate(res)


def compute_daily_quality_gate(
    row: dict,
    *,
    scenarios_on_ticker: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Swing/daily screener gate — StockSight flag model when G1/G flags exist, else legacy rubric."""
    if row.get("G1 Momentum") is not None or row.get("Flags"):
        return compute_stock_sight_daily_gate(row)

    decision = str(row.get("Decision") or row.get("Action") or "").upper()
    composite = row.get("Composite")
    score = row.get("Score")
    signal = str(row.get("Signal") or "")
    conf = str(row.get("Confidence") or "").upper()
    sentiment = str(row.get("Market sentiment") or "")

    scenarios = list(scenarios_on_ticker or [])
    if not scenarios and row.get("Scenario"):
        scenarios = [str(row["Scenario"])]
    n_conf = len(scenarios)

    pts = 0
    try:
        if composite is not None and float(composite) == float(composite):
            pts += int(min(30, float(composite) * 30 / 100))
    except (TypeError, ValueError):
        pass
    try:
        if score is not None and float(score) == float(score):
            pts += int(min(25, float(score) * 25 / 100))
    except (TypeError, ValueError):
        pass

    if "BUY" in decision and "CAUTIOUS" not in decision:
        pts += 20
    elif "CAUTIOUS" in decision or "CAUTIOUS BUY" in decision:
        pts += 12
    elif decision in ("HOLD", "WAIT", "WATCH"):
        pts += 5
    elif any(x in decision for x in ("AVOID", "SELL", "SKIP", "EXIT")):
        pts -= 18

    if conf.startswith("HIGH") or conf == "A":
        pts += 10
    elif conf.startswith("MED"):
        pts += 5
    elif conf.startswith("LOW"):
        pts -= 6

    pts += _sentiment_pts(sentiment)
    pts += _news_pts(row)

    if n_conf >= 2:
        pts += 10
    elif n_conf == 1:
        pts += 2

    try:
        vr = row.get("Vol×") or row.get("Volume Ratio")
        if vr is not None:
            v = float(vr)
            if v >= 1.3:
                pts += 6
            elif v < 0.85:
                pts -= 6
    except (TypeError, ValueError):
        pass

    try:
        rsi = row.get("RSI")
        if rsi is not None:
            r = float(rsi)
            if "SELL" in signal.upper() or "EXIT" in signal.upper() or "OVERBOUGHT" in signal.upper():
                if r >= 70:
                    pts += 6
                elif r < 55:
                    pts -= 5
            else:
                if 45 <= r <= 68:
                    pts += 5
                elif r > 78:
                    pts -= 6
    except (TypeError, ValueError):
        pass

    if "avoid" in sentiment.lower() or "⛔" in sentiment:
        pts = min(pts, 32)
        band = "D"
    else:
        band = _band_from_points(pts)
        if any(x in decision for x in ("AVOID", "SELL")) and band in ("A", "B"):
            band = "C"

    why: list[str] = []
    if decision:
        why.append(decision[:24])
    try:
        if composite is not None and float(composite) == float(composite):
            why.append(f"Composite {float(composite):.0f}")
    except (TypeError, ValueError):
        pass
    if n_conf >= 2:
        why.append(f"{n_conf} scenarios")
    if sentiment:
        why.append(sentiment.split("·")[0].strip()[:24])
    if signal:
        why.append(signal[:20])

    return _pack(band, max(0, min(100, pts)), why)


def compute_gap_quality_gate(row: dict) -> dict[str, Any]:
    """Pre-market gap scanner gate."""
    gap = row.get("Gap %")
    advice = str(row.get("Advice") or "").lower()
    holding = str(row.get("Holding?") or "")
    direction = str(row.get("Dir") or "")
    vol = row.get("Vol×")
    sentiment = str(row.get("Market sentiment") or "")
    size = str(row.get("Size") or "")

    pts = 40
    try:
        ap = abs(float(gap))
        if 1.0 <= ap < 3.0:
            pts += 18
        elif ap >= 3.0:
            pts += 12
        elif ap < 1.0:
            pts -= 15
    except (TypeError, ValueError):
        pts -= 10

    if "✅" in holding or holding.strip().upper() in ("YES", "Y", "TRUE"):
        pts += 12
    elif "⚠" in holding:
        pts -= 8

    if "UP" in direction:
        pts += 6
    elif "DOWN" in direction:
        pts -= 4

    if "medium" in size.lower():
        pts += 6
    elif "large" in size.lower():
        pts += 4
    elif "small" in size.lower():
        pts -= 10

    if "skip" in advice or "risky" in advice:
        pts -= 18
    elif "orb" in advice or "momentum" in advice or "trade" in advice:
        pts += 8

    pts += _sentiment_pts(sentiment)
    pts += _news_pts(row)

    try:
        if vol is not None and float(vol) >= 1.2:
            pts += 6
        elif vol is not None and float(vol) < 0.9:
            pts -= 5
    except (TypeError, ValueError):
        pass

    pts = max(0, min(100, pts))
    band = _band_from_points(pts)
    if "skip" in advice:
        band = "D"

    why = []
    if gap is not None:
        try:
            why.append(f"Gap {float(gap):+.1f}%")
        except (TypeError, ValueError):
            pass
    if size:
        why.append(size)
    if "✅" in holding:
        why.append("Holding gap side")
    elif "⚠" in holding:
        why.append("Gap filling")
    if sentiment:
        why.append(sentiment.split("·")[0].strip()[:22])

    return _pack(band, pts, why)


def build_scenario_confluence_map(df: pd.DataFrame) -> dict[str, list[str]]:
    if df is None or df.empty or "Scenario" not in df.columns:
        return {}
    raw_col = "Raw" if "Raw" in df.columns else "Ticker"
    out: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        raw = str(row.get(raw_col, "")).strip()
        sc = str(row.get("Scenario", "")).strip()
        if not raw or not sc:
            continue
        out.setdefault(raw, [])
        if sc not in out[raw]:
            out[raw].append(sc)
    return out


def compute_row_quality_gate(
    row: dict,
    *,
    profile: str = "daily",
    confluence_map: Optional[dict[str, list[str]]] = None,
    raw_key: str = "",
) -> dict[str, Any]:
    if profile == "intraday":
        try:
            from intraday import compute_intraday_quality_gate
        except ImportError:
            from .intraday import compute_intraday_quality_gate  # type: ignore[no-redef]
        codes = list((confluence_map or {}).get(raw_key, []))
        return compute_intraday_quality_gate(row, strategies_on_ticker=codes)
    if profile == "gap":
        return compute_gap_quality_gate(row)
    codes = list((confluence_map or {}).get(raw_key, []))
    return compute_daily_quality_gate(row, scenarios_on_ticker=codes)


def apply_quality_gate_columns(
    df: pd.DataFrame,
    *,
    profile: Optional[str] = None,
    confluence_map: Optional[dict[str, list[str]]] = None,
    sort_by_gate: bool = False,
) -> pd.DataFrame:
    if df is None or df.empty or GATE_COL in df.columns:
        return df

    prof = profile or detect_quality_gate_profile(df)
    conf = confluence_map if confluence_map is not None else build_scenario_confluence_map(df)
    raw_col = "Raw" if "Raw" in df.columns else None

    gates: list[str] = []
    scores: list[int] = []
    whys: list[str] = []
    for _, row in df.iterrows():
        raw = str(row.get(raw_col, "") if raw_col else row.get("Ticker", ""))
        pack = compute_row_quality_gate(
            row.to_dict(),
            profile=prof,
            confluence_map=conf,
            raw_key=raw,
        )
        gates.append(pack["label"])
        scores.append(int(pack["score"]))
        whys.append(pack["why"])

    out = df.copy()
    if "Tier" in out.columns:
        insert_at = out.columns.get_loc("Tier") + 1
    elif "Decision" in out.columns:
        insert_at = out.columns.get_loc("Decision")
    elif "Market sentiment" in out.columns:
        insert_at = out.columns.get_loc("Market sentiment")
    elif "Ticker" in out.columns:
        insert_at = out.columns.get_loc("Ticker") + 1
    else:
        insert_at = 0
    out.insert(insert_at, GATE_COL, gates)
    out.insert(insert_at + 1, GATE_SCORE_COL, scores)
    out.insert(insert_at + 2, GATE_WHY_COL, whys)

    if sort_by_gate and GATE_SCORE_COL in out.columns:
        out = out.sort_values(GATE_SCORE_COL, ascending=False, kind="stable").reset_index(drop=True)
        for col, fmt in (("S.No.", None), ("Rank", "#{i}")):
            if col in out.columns:
                if col == "Rank":
                    out[col] = [f"#{i}" for i in range(1, len(out) + 1)]
                else:
                    out[col] = range(1, len(out) + 1)

    return out


def quality_gate_row_css(row: "pd.Series") -> str:
    gate = str(row.get(GATE_COL, ""))
    for meta in QUALITY_GATE_BANDS.values():
        tag = meta["label"].split("·")[0].strip()
        if tag in gate or gate.startswith(meta["label"][:2]):
            return f"background-color: {meta['bg']}; color: {meta['fg']};"
    if gate.startswith("🟢"):
        m = QUALITY_GATE_BANDS["A"]
    elif gate.startswith("🟡"):
        m = QUALITY_GATE_BANDS["B"]
    elif gate.startswith("🟠"):
        m = QUALITY_GATE_BANDS["C"]
    else:
        m = QUALITY_GATE_BANDS["D"]
    return f"background-color: {m['bg']}; color: {m['fg']};"


def dataframe_gate_styler(
    df: pd.DataFrame,
    *,
    extra_row_style: Optional[callable] = None,
) -> Any:
    """Pandas Styler with quality-gate row backgrounds."""

    def _row_style(row: "pd.Series") -> list[str]:
        css = quality_gate_row_css(row)
        if extra_row_style is not None:
            override = extra_row_style(row)
            if override:
                css = override
        return [css] * len(row)

    return df.style.apply(_row_style, axis=1)  # type: ignore[union-attr]


def quality_gate_column_config() -> dict:
    if st is None:
        return {}
    return {
        GATE_COL: st.column_config.TextColumn(
            GATE_COL,
            width="small",
            help="A–D grade from decision/signal, sentiment, news, and confluence. Row colour matches.",
        ),
        GATE_SCORE_COL: st.column_config.ProgressColumn(
            GATE_SCORE_COL, min_value=0, max_value=100, format="%d",
        ),
        GATE_WHY_COL: st.column_config.TextColumn(GATE_WHY_COL, width="large"),
    }


def composite_score_bar_css(score: Any) -> str:
    """Score band colours: 65+ green, 45–64 blue, <45 red."""
    try:
        s = float(score)
        if s != s:
            return ""
    except (TypeError, ValueError):
        return ""
    if s >= 65:
        return "background-color: #d1fae5; color: #064e3b;"
    if s >= 45:
        return "background-color: #dbeafe; color: #1e3a8a;"
    return "background-color: #fee2e2; color: #991b1b;"


def render_quality_gate_legend(*, profile: Optional[str] = None, expanded: bool = False) -> None:
    if st is None:
        return
    prof = profile or "daily"
    titles = {
        "intraday": "strategy confluence + 7-rule score + session timing",
        "gap": "gap size, hold/fill, direction, sentiment, news",
        "daily": "flag-based gate: RSI exhaustion, earnings, MACD, volume, news, MA cross",
    }
    with st.expander(f"🚦 Quality Gate — colour code ({titles.get(prof, titles['daily'])})", expanded=expanded):
        for band in ("A", "B", "C", "D"):
            m = QUALITY_GATE_BANDS[band]
            hints = {
                "A": "Highest conviction — full size if your rules allow",
                "B": "Solid — normal size",
                "C": "Mixed — reduce size or wait",
                "D": "Skip — do not trade this row",
            }
            st.markdown(
                f"<span style='background:{m['bg']};color:{m['fg']};padding:4px 10px;"
                f"border-radius:6px;font-weight:600;'>{m['label']}</span> — {hints[band]}",
                unsafe_allow_html=True,
            )
