"""UI — Markov Regime screener (Hedge Fund Method)."""

from __future__ import annotations

import html
from typing import Optional

import pandas as pd
import streamlit as st

from markov_regime import (
    META,
    MarkovRegimeResult,
    matrix_forecast_table,
    transition_matrix_df,
)
from ui_components import render_clickable_scan_table


def markov_regime_header() -> None:
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #c084fc;
                border-radius:8px; padding:20px 24px; margin-bottom:16px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{html.escape(META["emoji"])}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{html.escape(META["title"])}</div>
                <div style='font-size:0.78rem; color:#c084fc; margin-top:4px; font-weight:600;'>
                    States · Transition matrix · Bull − Bear signal
                </div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:6px;'>
                    Quant-style regime odds — not subjective trend lines.
                </div>
            </div>
        </div>
    </div>
    """)


def render_education_panels() -> None:
    with st.expander("📘 The 10 elements (Hedge Fund Method)", expanded=False):
        st.markdown(
            """
1. **States** — Bull (20d return ≥ +5%), Bear (≤ −5%), Sideways (between).
2. **Historical labelling** — every day tagged from price history.
3. **Markov property** — tomorrow depends on today's state, not the full path.
4. **3×3 transition matrix** — row = today, column = tomorrow (%).
5. **Persistence** — diagonal = how "sticky" each regime is.
6. **Matrix squaring** — P² = 2-day forecast, P³ = 3-day (signal fades at long horizons).
7. **Stationary distribution** — long-run mix when signal converges.
8. **Signal** = **P(Bull) − P(Bear)** → long if positive, short/avoid if negative; size ∝ |signal|.
9. **Walk-forward** — matrix rebuilt each day using only past data (no look-ahead).
10. **HMM confirmation** — k-means on return + vol assigns states; green light when HMM agrees.
"""
        )

    with st.expander("🎯 How to read the scan table", expanded=True):
        st.markdown(
            """
| Column | Meaning |
|--------|---------|
| **Current state** | Bull / Sideways / Bear from 20-day cumulative return |
| **Signal (1d)** | P(Bull tomorrow) − P(Bear tomorrow) from today's row |
| **Signal (Nd)** | Same after matrix power for multi-day forecast |
| **Persistence %** | Diagonal stickiness for the active regime |
| **HMM agrees** | Simple HMM state matches threshold-based state |
| **Walk-fwd acc** | Historical hit rate of signal direction (walk-forward) |
| **Position hint** | Educational sizing from signal magnitude |
"""
        )


def _signal_cell_style(series: pd.Series) -> list[str]:
    styles: list[str] = []
    for v in series:
        try:
            x = float(v)
        except (TypeError, ValueError):
            styles.append("")
            continue
        if x >= 0.10:
            styles.append("background-color: #dcfce7; color: #166534; font-weight: 600;")
        elif x > 0.05:
            styles.append("background-color: #ecfdf5; color: #047857;")
        elif x <= -0.10:
            styles.append("background-color: #fee2e2; color: #991b1b; font-weight: 600;")
        elif x < -0.05:
            styles.append("background-color: #fef2f2; color: #b91c1c;")
        else:
            styles.append("")
    return styles


def _state_cell_style(series: pd.Series) -> list[str]:
    styles: list[str] = []
    for v in series:
        t = str(v).strip()
        if t == "Bull":
            styles.append("background-color: #dcfce7; color: #166534; font-weight: 600;")
        elif t == "Bear":
            styles.append("background-color: #fee2e2; color: #991b1b; font-weight: 600;")
        elif t == "Sideways":
            styles.append("background-color: #fef9c3; color: #854d0e;")
        else:
            styles.append("")
    return styles


def results_to_dataframe(results: list[MarkovRegimeResult]) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        sig = r.signal_nd if r.forecast_days > 1 else r.signal_1d
        persist = {
            "Bull": r.persistence_bull,
            "Sideways": r.persistence_side,
            "Bear": r.persistence_bear,
        }.get(r.current_state, 0.0)
        rows.append(
            {
                "S.No.": i,
                "Ticker": r.ticker,
                "Raw": r.raw_ticker,
                "Current state": r.current_state,
                "20d return %": r.cum_return_20d_pct,
                "Signal (1d)": r.signal_1d,
                "Signal (Nd)": r.signal_nd,
                "Signal": sig,
                "P(Bull) %": r.p_bull_1d,
                "P(Sideways) %": r.p_side_1d,
                "P(Bear) %": r.p_bear_1d,
                "Persistence %": persist,
                "HMM state": r.hmm_state,
                "HMM agrees": "✅" if r.hmm_agrees else "—",
                "Walk-fwd acc": r.walk_forward_acc,
                "Position hint": r.position_hint,
                "Action": r.action,
                "Stationary Bull %": r.stationary_bull,
                "Stationary Bear %": r.stationary_bear,
                **{f"link_{k}": v for k, v in (r.links or {}).items()},
            }
        )
        for k, v in (r.links or {}).items():
            rows[-1][k] = v
    df = pd.DataFrame(rows)
    return df.dropna(axis=1, how="all")


def markov_regime_table(
    df: pd.DataFrame,
    *,
    key_prefix: str = "markov",
    caption: Optional[str] = None,
) -> Optional[str]:
    if df is None or df.empty:
        st.info("No matches — loosen **Min signal** or disable **Require HMM agree**.")
        return None

    col_cfg = {
        "Current state": st.column_config.TextColumn(width="small"),
        "20d return %": st.column_config.NumberColumn(format="%+.2f"),
        "Signal (1d)": st.column_config.NumberColumn(format="%+.3f"),
        "Signal (Nd)": st.column_config.NumberColumn(format="%+.3f"),
        "Signal": st.column_config.NumberColumn(format="%+.3f"),
        "P(Bull) %": st.column_config.NumberColumn(format="%.1f"),
        "P(Sideways) %": st.column_config.NumberColumn(format="%.1f"),
        "P(Bear) %": st.column_config.NumberColumn(format="%.1f"),
        "Persistence %": st.column_config.NumberColumn(format="%.1f"),
        "Walk-fwd acc": st.column_config.NumberColumn(format="%.2f"),
        "HMM agrees": st.column_config.TextColumn(width="small"),
        "Position hint": st.column_config.TextColumn(width="medium"),
        "Action": st.column_config.TextColumn(width="medium"),
        "Raw": None,
    }

    styler = df.style.apply(_state_cell_style, subset=["Current state"])  # type: ignore[union-attr]
    for col in ("Signal (1d)", "Signal (Nd)", "Signal"):
        if col in df.columns:
            styler = styler.apply(_signal_cell_style, subset=[col])  # type: ignore[union-attr]

    return render_clickable_scan_table(
        df,
        styler=styler,
        key_prefix=key_prefix,
        column_config=col_cfg,
        caption=caption or "💡 Sorted by **Signal** (Bull − Bear). Click a row for chart below.",
        show_gate_legend=False,
    )


def render_matrix_detail(result: MarkovRegimeResult) -> None:
    st.markdown(f"### {result.ticker} — transition matrix & forecasts")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Current state", result.current_state)
        st.metric("20d return", f"{result.cum_return_20d_pct:+.2f}%")
    with c2:
        st.metric("Signal (1d)", f"{result.signal_1d:+.3f}")
        st.metric("HMM", f"{result.hmm_state} {'✅' if result.hmm_agrees else '—'}")
    with c3:
        st.metric("Walk-forward acc", f"{result.walk_forward_acc:.0%}" if result.walk_forward_acc else "—")
        st.metric("Position", result.position_hint)

    st.markdown("**3×3 transition matrix (% — rows sum to 100)**")
    st.dataframe(transition_matrix_df(result.matrix_flat), use_container_width=True)

    st.markdown("**Multi-day forecasts (matrix powers)**")
    st.dataframe(
        matrix_forecast_table(result.matrix_flat, days=(1, 2, 3, 5, 10)),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        f"Stationary mix (long-run): Bull {result.stationary_bull:.1f}% · "
        f"Bear {result.stationary_bear:.1f}% · "
        "Signal weakens as forecast horizon grows (stationary convergence)."
    )
