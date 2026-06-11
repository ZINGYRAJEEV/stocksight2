"""UI — Volume Gravity screener (VWAP, RVOL, POC, ORB)."""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from volume_gravity import META, VolumeGravityResult
from ui_components import render_clickable_scan_table, stock_sight_overlay_column_config


def volume_gravity_header() -> None:
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #4db8ff;
                border-radius:8px; padding:20px 24px; margin-bottom:16px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{html.escape(META["emoji"])}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{html.escape(META["title"])}</div>
                <div style='font-size:0.78rem; color:#4db8ff; margin-top:4px; font-weight:600;'>
                    Price advertises · Volume proves conviction
                </div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:6px;'>
                    VWAP = institutional fair value · RVOL = participation · POC = market gravity.
                </div>
            </div>
        </div>
    </div>
    """)


def render_education_panels() -> None:
    with st.expander("📘 Core idea (plain English)", expanded=False):
        st.markdown(
            """
**Price** tells you what the market *wants* you to see. **Volume** tells you whether *real money* agrees.

- **RVOL ≥ 3×** at the open = institutions likely involved (Gap & Go filter).
- **VWAP** = average price paid today, weighted by size — funds benchmark execution here.
- **Volume Profile POC** = price level with most agreement; price tends to rotate toward it until a **breakout with volume**.
"""
        )

    with st.expander("📊 VWAP vs moving average", expanded=False):
        st.markdown(
            """
| | SMA (moving average) | VWAP |
|--|---------------------|------|
| **Built from** | Time only | Price × volume |
| **Who uses it** | Retail trend tools | Institutions, algos |
| **Best for** | General trend | Intraday fair value & execution quality |

**VWAP hold entry:** after the opening move, wait for a **pullback to VWAP**, see a **bounce + volume spike**, enter with stop **just below VWAP**.
"""
        )

    with st.expander("🗺️ Volume Profile — POC & Value Area", expanded=False):
        st.markdown(
            """
| Level | Meaning |
|-------|---------|
| **POC** | Most-traded price — “market gravity” |
| **Value Area (70%)** | Range where most volume traded — balance zone |
| **Single prints / thin zones** | Fast moves — often support/resistance later |

**Rule:** Do not blindly buy the POC touch. Trade **breakouts away from POC** with **3×+ RVOL**.
"""
        )

    with st.expander("⚡ ORB + gap checklist (intraday)", expanded=True):
        st.markdown(
            """
**Trade execution checklist (from handbook):**
- [ ] Gap **≥ 2%** with a real catalyst (earnings/news)
- [ ] Mark **ORB** high/low (first 15–30 min)
- [ ] Price **above VWAP** for longs (below for shorts)
- [ ] **RVOL ≥ 3×** for follow-through
- [ ] Target **1.5–2× ORB range** or next thin profile node
- [ ] **Time exit:** if target not hit by ~90 min into session, reduce risk (lunch mean reversion)

**Gap types:** Breakaway · Continuation · **Exhaustion (trap)** · Common (small, often fills).
"""
        )

    with st.expander("🛡️ Risk rules", expanded=False):
        st.markdown(
            """
1. Size from **stop distance** — fixed ₹/$ risk per trade.
2. **Daily loss limit ~3%** — stop trading for the day.
3. **Max 2–3 trades/day** — overtrading = chasing, not data.
4. **False breakouts** — inside bar + failed pierce (Hikkake-style trap); wait for volume confirmation.
"""
        )


def results_to_dataframe(results: list[VolumeGravityResult]) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        row = {
            "Rank": i,
            "Mode": r.mode,
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Setup": r.setup_label,
            "Gravity": r.gravity_score,
            "Band": r.gravity_band,
            "Gap %": r.gap_pct,
            "Gap type": r.gap_type,
            "RVOL": r.rvol,
            "vs VWAP %": r.pct_vs_vwap,
            "Price": r.price,
            "VWAP": r.vwap,
            "POC": r.poc,
            "VA high": r.va_high,
            "VA low": r.va_low,
            "Day type": r.day_type,
            "ORB high": r.orb_high,
            "ORB low": r.orb_low,
            "Checklist": f"{r.checklist_pass}/{r.checklist_total}",
            "Action": r.action_hint,
            "Entry": r.entry_hint,
            "Stop": r.stop_hint,
            "Target": r.target_hint,
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


def volume_gravity_table(
    results: list[VolumeGravityResult],
    *,
    scan_at: str | None = None,
    key_prefix: str = "vg",
    market: str = "NSE",
) -> None:
    if not results:
        return
    df = results_to_dataframe(results)
    if scan_at:
        st.caption(scan_at)

    col_cfg: dict = {
        **stock_sight_overlay_column_config(),
        "Gravity": st.column_config.ProgressColumn("Gravity", min_value=0, max_value=100, format="%d"),
        "RVOL": st.column_config.NumberColumn("RVOL", format="%.2f"),
        "Gap %": st.column_config.NumberColumn("Gap %", format="%+.2f"),
        "vs VWAP %": st.column_config.NumberColumn("vs VWAP %", format="%+.2f"),
        "Setup": st.column_config.TextColumn("Setup", width="medium"),
        "Day type": st.column_config.TextColumn("Day type", width="large"),
        "Entry": st.column_config.TextColumn("Entry", width="large"),
        "Stop": st.column_config.TextColumn("Stop", width="medium"),
        "Target": st.column_config.TextColumn("Target", width="medium"),
    }
    for col in df.columns:
        if col.startswith(("📊", "📈", "📉", "🔎")):
            col_cfg[col] = st.column_config.LinkColumn(col, display_text="Open ↗")
    for canonical in ("Yahoo Finance", "Google Finance", "Moneycontrol", "MarketWatch", "TradingView"):
        if canonical in df.columns:
            col_cfg[canonical] = None  # type: ignore[assignment]

    render_clickable_scan_table(
        df,
        key_prefix=key_prefix,
        apply_stock_sight=False,
        universe_name=market,
        market=market,
        column_config=col_cfg,
        hide_index=True,
        height=min(600, 52 + len(df) * 40),
        caption="💡 Click a row for chart research. Gravity score blends setup quality + handbook checklist.",
    )


def no_results_state(mode: str) -> None:
    st.warning(
        f"No **{mode}** matches. Try lowering **Min gravity score** or **Min RVOL**, "
        "or run during / after the session for intraday data. "
        "Gap & Go needs **≥2% gap** and strong relative volume."
    )
