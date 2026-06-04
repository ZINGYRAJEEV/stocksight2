"""Streamlit UI helpers — Stage 2 + VCP momentum screener."""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from stage2_momentum import META, Stage2MomentumResult, TREND_TEMPLATE_RULES
from ui_components import render_clickable_scan_table


def stage2_header() -> None:
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #f0b429;
                border-radius:8px; padding:20px 24px; margin-bottom:16px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{html.escape(META["emoji"])}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{html.escape(META["title"])}</div>
                <div style='font-size:0.78rem; color:#f0b429; margin-top:4px; font-weight:600;'>
                    Minervini · Weinstein · Stage 2 + Volatility Contraction (VCP)
                </div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:6px;'>
                    Find stocks in a <b>confirmed uptrend</b> with <b>tightening bases</b> before breakouts.
                    Plain-English guides on this page — always verify on your chart.
                </div>
            </div>
        </div>
    </div>
    """)


def render_education_panels() -> None:
    with st.expander("📘 Executive summary (layman)", expanded=False):
        st.markdown(
            """
**What this strategy tries to do:** ride stocks that institutions are quietly accumulating in a **Stage 2 uptrend**,
then enter when price **breaks out** from a **tight base** (VCP) with strong volume.

**Three ideas to remember:**
1. **Stage 2 only** — buy when the stock is in a healthy advance, not when it is crashing (Stage 4) or topping (Stage 3).
2. **VCP = coiling spring** — each pullback gets smaller and volume dries up; supply is absorbed.
3. **Risk first** — cap losses around **7–8%**; let winners run with trailing stops. **Never average down** on a loser.

*StockSight scores are automated approximations — bases on a chart are partly subjective.*
"""
        )

    with st.expander("🔄 The four stages (Weinstein / Minervini)", expanded=False):
        st.markdown(
            """
| Stage | Plain English | What to do |
|-------|----------------|------------|
| **1 — Consolidation** | Price moves sideways; base is forming. | **Watch** — do not chase yet. |
| **2 — Advance** | Uptrend; institutions accumulating. | **Best buy zone** after VCP breakout. |
| **3 — Distribution** | Churn near highs; big volume, stalling. | **Protect profits** — trim or tighten stops. |
| **4 — Capitulation** | Lower lows, broken trend. | **Never buy or hold** hoping for a bounce. |
"""
        )

    with st.expander("✅ Trend Template — 8 checks (must-pass for elite setups)", expanded=True):
        st.markdown(
            "A stock in **Stage 2** should pass **all eight** filters below. The scanner lets you require **6–8** passes "
            "so you can start broad and tighten later."
        )
        for _key, label in TREND_TEMPLATE_RULES:
            st.markdown(f"- {label}")

    with st.expander("📐 Volatility Contraction Pattern (VCP)", expanded=False):
        st.markdown(
            """
**What you are looking for on the chart:**
- **2–6 pullbacks** inside a base, each **smaller** than the last (e.g. −18% → −12% → −6%).
- **Volume dries up** on pullbacks — sellers are exhausted.
- **Pivot** = the ceiling on the right side of the base; buy when price clears it on a **volume surge** (~40–50% above average).

**Pocket pivot (early clue):** one strong up-day volume inside the base vs recent down-days.

**vs Cup-and-Handle:** VCP focuses on **tightening math**, not a perfect cup shape.
"""
        )

    with st.expander("🏅 Ranking score (how rows are sorted)", expanded=False):
        st.markdown(
            """
Results are sorted by **Rank score** (higher = top of table):

| Component | Points |
|-----------|--------|
| **Composite × 0.45** | Trend Template + VCP + RS blend (0–100 scale) |
| **RS rank × 0.20** | Percentile vs index in this scan |
| **VCP score × 0.15** | Tightening / dry-up / pivot quality |
| **Pivot proximity** | +14 / +10 / +6 / +3 when **% below pivot** is small |
| **Far below pivot** | −2.5 pts per % **above 4%** below pivot (capped) |
| **Vol vs 50d avg** | `min(ratio, 3) × 3` |
| **Stage 2** in label | +8 |
| **High-conviction watch** | +10 |
| **Watchlist** action | +2 |
| **Hold / trim only** | −8 |
| **Pocket pivot** = Yes | +5 |
| **Vol dry-up** = Yes | +4 |

**Composite** (column) is still shown for context; **Rank score** is the primary sort key.
"""
        )

    with st.expander("🎯 Entry, stops & selling (discipline)", expanded=False):
        st.markdown(
            """
| Topic | Rule of thumb |
|-------|----------------|
| **Entry** | Breakout above **pivot** on expanding volume — or skilled early entry in lower third of base. |
| **Initial stop** | **7–8%** below entry — decide *before* you buy. |
| **Add size** | Only when trades work; shrink activity on losing streaks. |
| **Trail** | After 2–3× initial risk, move stop to breakeven+; use **20-day or 50-day MA** on swings. |
| **Sell** | Into late-stage exhaustion or at **2R / 3R** targets. |

**Cardinal sins:** forcing trades without VCP · averaging down · trusting breakouts on **light volume** · selling because of taxes/PE instead of chart damage.
"""
        )


def results_to_dataframe(results: list[Stage2MomentumResult]) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        row = {
            "Rank": i,
            "Badge": r.badge,
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Stage": r.stage_label,
            "Rank score": r.rank_score,
            "Rank why": r.rank_why,
            "Composite": r.composite_score,
            "Trend pass": f"{r.trend_pass}/{r.trend_max}",
            "VCP score": r.vcp_score,
            "VCP grade": r.vcp_grade,
            "Contractions": r.vcp_contractions,
            "Pullback depths": r.vcp_depths_pct,
            "Vol dry-up": "Yes" if r.volume_dryup else "No",
            "Pivot": r.pivot_price,
            "% below pivot": r.pct_from_pivot,
            "Pocket pivot": "Yes" if r.pocket_pivot else "No",
            "RS rank (scan)": r.rs_rank,
            "RS vs index 20d": r.rs_20d,
            "% above 52w low": r.pct_above_52w_low,
            "% below 52w high": r.pct_below_52w_high,
            "Vol vs 50d avg": r.vol_ratio_50d,
            "Action": r.action_hint,
            "Price": r.price,
            "50 DMA": r.ma50,
            "150 DMA": r.ma150,
            "200 DMA": r.ma200,
            "Entry plan": r.entry_hint,
            "Stop plan": r.stop_hint,
            "Sell plan": r.sell_hint,
            "Passed checks": " · ".join(r.trend_checks[:6]),
            "Failed checks": " · ".join(r.trend_failed[:4]) if r.trend_failed else "—",
            "Warnings": " · ".join(r.warnings) if r.warnings else "—",
        }
        for name, url in r.links.items():
            short = {
                "Yahoo Finance": "📊 Yahoo",
                "Google Finance": "🔎 Google",
                "Moneycontrol": "📈 MC",
                "MarketWatch": "📈 MW",
                "TradingView": "📉 TV",
            }.get(name, name)
            row[short] = url
            row[name] = url
        rows.append(row)
    return pd.DataFrame(rows)


def stage2_results_table(
    results: list[Stage2MomentumResult],
    *,
    scan_at: str | None = None,
    key_prefix: str = "s2",
) -> None:
    if not results:
        return
    df = results_to_dataframe(results)
    if scan_at:
        st.caption(f"Scan completed · {scan_at}")

    col_cfg: dict = {
        "Rank score": st.column_config.NumberColumn("Rank score", format="%.1f"),
        "Rank why": st.column_config.TextColumn("Rank why", width="large"),
        "Composite": st.column_config.ProgressColumn("Composite", min_value=0, max_value=100, format="%d"),
        "VCP score": st.column_config.ProgressColumn("VCP score", min_value=0, max_value=100, format="%d"),
        "RS rank (scan)": st.column_config.ProgressColumn("RS rank", min_value=0, max_value=100, format="%d"),
        "Trend pass": st.column_config.TextColumn("Trend pass", width="small"),
        "Stage": st.column_config.TextColumn("Stage", width="large"),
        "Action": st.column_config.TextColumn("Action", width="medium"),
        "Entry plan": st.column_config.TextColumn("Entry plan", width="large"),
        "Stop plan": st.column_config.TextColumn("Stop plan", width="medium"),
        "Sell plan": st.column_config.TextColumn("Sell plan", width="large"),
        "Warnings": st.column_config.TextColumn("Warnings", width="large"),
    }
    for col in df.columns:
        if col.startswith(("📊", "📈", "📉", "🔎")):
            col_cfg[col] = st.column_config.LinkColumn(col, display_text="Open ↗")
    for canonical in ("Yahoo Finance", "Google Finance", "Moneycontrol", "MarketWatch", "TradingView"):
        if canonical in df.columns:
            col_cfg[canonical] = None  # type: ignore[assignment]

    render_clickable_scan_table(
        df,
        key_prefix=f"{key_prefix}_rank",
        universe_name="Stage 2 scan",
        column_config=col_cfg,
        hide_index=True,
        height=min(580, 52 + len(df) * 40),
        caption="💡 Sorted by **Rank score**. Click a row for chart + research; see **Rank why** for the breakdown.",
    )


def stage2_detail_card(r: Stage2MomentumResult) -> None:
    st.markdown(f"#### {r.ticker} — {r.stage_label}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rank score", f"{r.rank_score:.1f}")
    c2.metric("Composite", f"{r.composite_score:.0f}")
    c3.metric("VCP score", f"{r.vcp_score:.0f}")
    c4.metric("RS rank", f"{r.rs_rank:.0f}")
    st.caption(r.rank_why or "—")
    st.markdown(f"**Trend Template:** {r.trend_pass}/{r.trend_max}")
    st.info(f"**Action:** {r.action_hint}")
    st.markdown(f"**Entry:** {r.entry_hint}")
    st.markdown(f"**Stop:** {r.stop_hint}")
    st.markdown(f"**Sell:** {r.sell_hint}")
    if r.trend_checks:
        st.markdown("**Passed:** " + " · ".join(r.trend_checks))
    if r.trend_failed:
        st.markdown("**Not yet:** " + " · ".join(r.trend_failed))
    if r.warnings:
        st.warning(" · ".join(r.warnings))


def no_results_state() -> None:
    st.warning(
        "No matches with current filters. Try **Trend pass ≥ 5**, lower **Min VCP score**, "
        "or a broader universe (**Nifty 500**). Stage 2 setups are rare by design."
    )
