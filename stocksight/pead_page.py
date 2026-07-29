"""PEAD — Post-Earnings Announcement Drift screener UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from pead_screener import (
    DIRECTION_OPTIONS,
    META,
    PEADFilters,
    RANK_BY_OPTIONS,
    SCAN_SOURCES,
    analyze_pead_criteria,
    best_pead_threshold,
    result_to_row,
    scan_pead,
    scan_pead_for_criteria,
    sort_pead_results,
)
from quality_gate import quality_gate_column_config
from scan_history_store import append_scan_record
from screener_session_ui import render_screener_session_panel
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
)
from session_utils import deduplicate_scan_results
from stock_analysis_framework import StockAnalysisFramework


def _rules_panel() -> None:
    with st.expander("📖 PEAD & SUE explained", expanded=True):
        st.markdown(
            """
**PEAD (Post-Earnings Announcement Drift)** — after results, prices often keep drifting in the
direction of the earnings surprise for **30–60 trading days**.

**SUE (Standardized Unexpected Earnings)** — surprise scaled by historical volatility:

| Component | How we compute it |
|-----------|-------------------|
| **Actual** | Latest quarter PAT (Net Profit) |
| **Expected** | Same quarter **prior year** (seasonal model) |
| **SUE** | (Actual − Expected) ÷ σ(past surprises) |

**Favourable values (literature):**
- **Long:** SUE **≥ +2.0** (top decile positive surprise)
- **Short:** SUE **≤ −2.0** (bottom decile miss)

**Filters we apply:** liquidity (avg daily traded value), market cap, days since estimated result date,
optional volume spike & post-5d confirmation.

**Data:** Screener.in quarterly P&L for NSE; Yahoo price/volume for drift windows.
Result date ≈ quarter-end + 45 days when exact filing date is unavailable.
"""
        )
        st.code(
            "\n".join(
                [
                    "-- Classic long PEAD screen",
                    "SUE >= +2.0",
                    "AND days_since_results <= 60",
                    "AND avg_daily_value >= 3 Cr (INR)",
                    "AND market_cap >= 300 Cr",
                    "ORDER BY post_20d_return DESC",
                ]
            ),
            language="sql",
        )


def render_pead_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    enable_analysis = st.sidebar.checkbox(
        "Enable 7-Category Analysis (Beta)",
        value=False,
        help="Adds Valuation, Profitability, Growth, Financial Health scores. Off by default (faster).",
    )

    key = "pead"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"
    criteria_key = f"{key}_criteria"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.05])
        with c1:
            st.markdown("#### Universe")
            uni_key = f"{key}_universe"
            nse_sources = [s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s]
            ensure_session_choice(uni_key, nse_sources, nse_sources[0])
            universe = st.selectbox(
                "Stock universe (NSE)",
                nse_sources,
                key=uni_key,
                help="Start with Curated or Nifty 50. Use **Find best SUE threshold** below to tune filters.",
            )
            recent_only = st.checkbox(
                "Recent reporters only (Screener.in /results/latest/)",
                value=False,
                key=f"{key}_recent",
                help="Restricts to names on Screener's latest results feed (needs login).",
            )
        with c2:
            st.markdown("#### SUE & direction")
            dir_key = f"{key}_dir"
            dir_choices = list(DIRECTION_OPTIONS.keys())
            ensure_session_choice(dir_key, dir_choices, "long")
            direction = st.radio(
                "Trade direction",
                dir_choices,
                format_func=lambda x: DIRECTION_OPTIONS[x],
                horizontal=True,
                key=dir_key,
            )
            min_sue = st.slider(
                "Min |SUE| threshold",
                0.5,
                4.0,
                1.0,
                0.25,
                key=f"{key}_sue",
                help="Academic top/bottom decile ≈ ±2.0. Start at 1.0 if you get zero hits.",
            )
            max_days = st.slider(
                "Max days since est. result",
                30,
                180,
                120,
                5,
                key=f"{key}_days",
                help="Raise to 150+ if latest results are a few months old.",
            )
        with c3:
            st.markdown("#### Liquidity & confirmation")
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 300.0, 50.0, key=f"{key}_mcap")
            min_adv = st.slider(
                "Min avg daily traded (₹ Cr)",
                0.0,
                20.0,
                1.0,
                0.5,
                key=f"{key}_adv",
            )
            vol_spike = st.checkbox("Require volume spike post-result", value=False, key=f"{key}_vol")
            confirm = st.checkbox("Require 5d drift confirms direction", value=False, key=f"{key}_conf")
            min_conf = st.slider("Min post-5d return %", -5.0, 15.0, 0.0, 0.5, key=f"{key}_p5") if confirm else 0.0

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    b_scan, b_criteria = st.columns(2)
    with b_scan:
        run = st.button("▶  SCAN PEAD", use_container_width=True, key=f"{key}_scan", type="primary")
    with b_criteria:
        run_criteria = st.button(
            "🔬 Find best SUE threshold",
            use_container_width=True,
            key=f"{key}_criteria_scan",
            help="Loose scan on this universe, then ranks SUE cutoffs by avg post-20d drift.",
        )

    flt = PEADFilters(
        direction=direction,
        min_sue=min_sue,
        max_days_since_results=max_days,
        min_market_cap_cr=min_mcap,
        min_avg_daily_value_cr=min_adv,
        min_post_5d_confirm_pct=min_conf if confirm else None,
        require_volume_spike=vol_spike,
        recent_reporters_only=recent_only,
    )

    if run or run_criteria:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        if run_criteria:
            loose = scan_pead_for_criteria(universe, direction=direction, progress_cb=cb)
            crit_rows = analyze_pead_criteria(loose, direction=direction)
            st.session_state[criteria_key] = crit_rows
            st.session_state[f"{criteria_key}_loose_n"] = len(loose)
            best = best_pead_threshold(crit_rows)
            if best is not None:
                st.session_state[f"{key}_sue"] = float(best)
            hits = [r for r in loose if (
                (direction == "long" and (r.sue or 0) >= (best or min_sue))
                or (direction == "short" and (r.sue or 0) <= -(best or min_sue))
                or (direction == "both" and abs(r.sue or 0) >= (best or min_sue))
            )]
            st.session_state[session_key] = sort_pead_results(hits, rank_by="pead_score")
        else:
            hits = scan_pead(universe, filters=flt, progress_cb=cb)
            st.session_state[session_key] = hits

        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe

        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in st.session_state[session_key]],
                meta={"matches": len(st.session_state[session_key])},
            )
        except Exception:
            pass
        try:
            metrics = [(r.ticker, r.raw_ticker, float(r.price), None) for r in st.session_state[session_key]]
            notify_watchlist_alerts_from_metrics(metrics, META["title"])
        except Exception:
            pass

        prog.empty()
        scan_progress.empty()

    crit_rows = st.session_state.get(criteria_key)
    if crit_rows:
        with st.container(border=True):
            st.markdown("#### 🔬 Best SUE thresholds for this universe")
            loose_n = st.session_state.get(f"{criteria_key}_loose_n", 0)
            st.caption(
                f"Based on **{loose_n}** names with valid SUE & price history in the last ~90 days. "
                "Ranked by avg post-20d drift × √(sample size)."
            )
            crit_df = pd.DataFrame([
                {
                    "SUE cutoff": (
                        f"≤ −{r.threshold:.1f}" if direction == "short"
                        else f"|SUE| ≥ {r.threshold:.1f}" if direction == "both"
                        else f"≥ +{r.threshold:.1f}"
                    ),
                    "Matches": r.count,
                    "Median SUE": r.median_sue,
                    "Avg post-5d %": r.avg_post_5d_pct,
                    "Avg post-20d %": r.avg_post_20d_pct,
                    "Score": r.score,
                }
                for r in crit_rows
            ])
            st.dataframe(crit_df, use_container_width=True, hide_index=True)
            best = best_pead_threshold(crit_rows)
            if best is not None:
                st.success(
                    f"**Suggested threshold for {DIRECTION_OPTIONS.get(direction, direction)}:** "
                    f"**|SUE| ≥ {best:.1f}** — highest drift score with ≥3 names."
                )

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)

    if results is None:
        st.info("👆 Pick universe and SUE filters, then click **SCAN PEAD** or **Find best SUE threshold**.")
        return

    if not results:
        st.warning(
            "No names passed with current filters. Try:\n"
            "- **Find best SUE threshold** first (looser scan)\n"
            "- **Max days since est. result** → **150**\n"
            "- **Min |SUE|** → **0.5** or **1.0**\n"
            "- **Min avg daily traded** → **0**\n"
            "- Turn off **Recent reporters only** unless Screener login is active"
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    ensure_session_choice(rank_key, rank_choices, "pead_score")
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_pead_results(results, rank_by=rank_by)

    top_sue = max((abs(r.sue or 0) for r in results), default=0)
    st.success(
        f"**{len(results)}** matches · {last_uni} · scanned {scan_at or '—'} · "
        f"highest |SUE| **{top_sue:.2f}**"
    )

    rows = []
    for i, r in enumerate(results, start=1):
        row = result_to_row(r, i)
        for link_name, link_url in (r.links or {}).items():
            row[link_name] = link_url
        rows.append(row)

    df = pd.DataFrame(rows)
    df = deduplicate_scan_results(df)

    if enable_analysis and not df.empty:
        try:
            framework = StockAnalysisFramework()
            df = framework.enrich_dataframe(df)
        except Exception as exc:
            st.warning(f"Stock analysis framework error: {exc}")

    df = prepare_scan_results_df(
        df,
        universe_name=last_uni,
        cache_key_prefix=f"{key}_results",
        raw_ticker_col="Raw",
    )

    col_cfg = filter_column_config(
        df,
        {
            **quality_gate_column_config(),
            "PEAD score": st.column_config.NumberColumn(format="%.1f"),
            "SUE": st.column_config.NumberColumn(format="%+.2f"),
            "SUE sales": st.column_config.NumberColumn(format="%+.2f"),
            "QoQ sales %": st.column_config.NumberColumn(format="%.1f"),
            "QoQ profit %": st.column_config.NumberColumn(format="%.1f"),
            "Post 1d %": st.column_config.NumberColumn(format="%+.2f"),
            "Post 5d %": st.column_config.NumberColumn(format="%+.2f"),
            "Post 20d %": st.column_config.NumberColumn(format="%+.2f"),
            "Pre 5d %": st.column_config.NumberColumn(format="%+.2f"),
            "Vol spike ×": st.column_config.NumberColumn(format="%.2f"),
            "Avg daily ₹Cr": st.column_config.NumberColumn(format="%.2f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "P/E": st.column_config.NumberColumn(format="%.2f"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "Raw": None,
            "Notes": None,
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
            "Screener.in": st.column_config.LinkColumn(display_text="Screener ↗"),
            "Data": st.column_config.TextColumn(width="medium"),
        },
    )

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
    )

    with st.expander("Pass criteria notes (per stock)", expanded=False):
        for r in results[:25]:
            st.markdown(
                f"**{r.label}** ({r.latest_q}, SUE {r.sue:+.2f}): "
                f"{' · '.join(r.pass_notes)}"
            )

    st.caption(
        "SUE uses quarterly PAT vs same quarter prior year. Result date is estimated (quarter-end + 45d). "
        "Educational only — not investment advice."
    )
