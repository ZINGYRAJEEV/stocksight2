"""Fundamental Screener Framework — 3-tier UI (Watchlist / Strict / Momentum)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from fundamental_screener import (
    META,
    RANK_OPTIONS,
    SCAN_SOURCES,
    TIER_IDS,
    TIER_LABELS,
    FundamentalFilters,
    filters_for_tier,
    result_to_row,
    scan_fundamental_framework,
    sort_fundamental_results,
)
from scan_history_store import append_scan_record
from screener_session_ui import render_screener_session_panel
from session_utils import deduplicate_scan_results
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_historical_detail_panel,
    render_watchlist_panel,
    safe_set_page_config,
)


def _rules_panel() -> None:
    with st.expander("📖 How this 3-tier framework works", expanded=True):
        st.markdown(
            """
**Goal:** find **reliable, debt-free, scam-free, fast-growth** names before investing.

| Tier | When | Strictness |
|------|------|------------|
| **1 Watchlist** | Monthly research funnel | Loose |
| **2 Strict** | Before deploying capital | Tight |
| **3 Momentum** | Before swing / BTST entry | Fundamentals + price action |

**Workflow:** Watchlist → research & track repeats → **Strict** for long-term shortlist → **Momentum** for entry timing.

**Scam-free guardrails** (debt / promoter / pledge) should stay tight — if Strict returns 0–2 names, relax **PEG or P/B first**, never governance.

**Data:** Screener.in consolidated company pages (+ Yahoo for D/E / P/B / returns when needed).
"""
        )
        st.markdown("**Tier 1 query (reference)**")
        st.code(
            "Market Cap > 500 AND D/E < 0.5 AND Promoter > 40 AND Pledge < 10 AND "
            "ROE > 12 AND Sales 3Y > 8 AND Profit 3Y > 8 AND PE < Industry PE + 5",
            language="sql",
        )
        st.markdown("**Tier 2 adds** ICR, current ratio, avg ROE, ROCE, ROA, OPM, YoY qtr growth, PEG, P/B.")
        st.markdown(
            "**Tier 3** keeps Watchlist fundamentals and requires 3M > 0, 6M > 10%, "
            "and 3M return > 1Y/4 (acceleration proxy)."
        )


def render_fundamental_screener_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    key = "fund3"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"

    with st.container(border=True):
        c1, c2 = st.columns([1.1, 1.4])
        with c1:
            st.markdown("#### Universe")
            uni_key = f"{key}_universe"
            nse_sources = [s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s]
            # Prefer Nifty 50 / curated first for sane runtimes
            default_uni = next(
                (s for s in nse_sources if "Curated" in s or "Nifty 50" in s),
                nse_sources[0] if nse_sources else "",
            )
            ensure_session_choice(uni_key, nse_sources, default_uni)
            universe = st.selectbox(
                "Stock universe (NSE)",
                nse_sources,
                key=uni_key,
                help="Start with Curated or Nifty 50. Full NSE is very slow — use Investment Course chunks for that.",
            )
        with c2:
            st.markdown("#### Tier")
            tier_key = f"{key}_tier"
            ensure_session_choice(tier_key, list(TIER_IDS), "watchlist")
            tier = st.radio(
                "Framework tier",
                list(TIER_IDS),
                format_func=lambda t: TIER_LABELS[t],
                key=tier_key,
                horizontal=False,
            )

    preset = filters_for_tier(tier)
    with st.expander("⚙️ Fine-tune thresholds (optional)", expanded=False):
        st.caption(
            "Defaults match `docs/fundamental_screener_framework.md`. "
            "Do **not** loosen debt / promoter / pledge casually."
        )
        a1, a2, a3 = st.columns(3)
        with a1:
            min_mcap = st.number_input(
                "Min market cap ₹ Cr",
                min_value=0.0,
                value=float(preset.min_market_cap_cr),
                step=50.0,
                key=f"{key}_mcap",
            )
            max_de = st.number_input(
                "Max debt / equity",
                min_value=0.0,
                max_value=2.0,
                value=float(preset.max_debt_equity),
                step=0.05,
                key=f"{key}_de",
            )
            min_prom = st.number_input(
                "Min promoter holding %",
                min_value=0.0,
                max_value=100.0,
                value=float(preset.min_promoter_holding_pct),
                step=1.0,
                key=f"{key}_prom",
            )
            max_pledge = st.number_input(
                "Max pledged %",
                min_value=0.0,
                max_value=50.0,
                value=float(preset.max_pledged_pct),
                step=1.0,
                key=f"{key}_pledge",
            )
        with a2:
            min_roe = st.number_input(
                "Min ROE %",
                min_value=0.0,
                value=float(preset.min_roe_pct),
                step=1.0,
                key=f"{key}_roe",
            )
            min_sg = st.number_input(
                "Min sales growth 3Y %",
                min_value=0.0,
                value=float(preset.min_sales_growth_3y_pct),
                step=1.0,
                key=f"{key}_sg",
            )
            min_pg = st.number_input(
                "Min profit growth 3Y %",
                min_value=0.0,
                value=float(preset.min_profit_growth_3y_pct),
                step=1.0,
                key=f"{key}_pg",
            )
            max_peg = st.number_input(
                "Max PEG (0 = off)",
                min_value=0.0,
                max_value=5.0,
                value=float(preset.max_peg),
                step=0.1,
                key=f"{key}_peg",
            )
        with a3:
            soft_val = st.checkbox(
                "Soft-skip missing PE/PEG/P/B",
                value=bool(preset.soft_skip_missing_valuation),
                key=f"{key}_soft",
                help="If Industry PE / PEG / P/B missing, don't fail the name.",
            )
            req_gov = st.checkbox(
                "Require debt / promoter / pledge data",
                value=bool(preset.require_governance_data),
                key=f"{key}_gov",
            )
            max_hits = st.number_input(
                "Max results",
                min_value=10,
                max_value=200,
                value=int(preset.max_results),
                step=10,
                key=f"{key}_max",
            )
            if tier == "momentum":
                st.caption("Momentum uses 3M / 6M / acceleration from Yahoo history.")

    flt = FundamentalFilters(
        tier=tier,
        min_market_cap_cr=float(min_mcap),
        max_debt_equity=float(max_de),
        min_interest_coverage=preset.min_interest_coverage,
        min_current_ratio=preset.min_current_ratio,
        min_promoter_holding_pct=float(min_prom),
        min_promoter_change_pct=preset.min_promoter_change_pct,
        max_pledged_pct=float(max_pledge),
        min_roe_pct=float(min_roe),
        min_avg_roe_3y_pct=preset.min_avg_roe_3y_pct,
        min_roce_pct=preset.min_roce_pct,
        min_roa_pct=preset.min_roa_pct,
        min_opm_pct=preset.min_opm_pct,
        min_sales_growth_3y_pct=float(min_sg),
        min_profit_growth_3y_pct=float(min_pg),
        min_yoy_sales_pct=preset.min_yoy_sales_pct,
        min_yoy_profit_pct=preset.min_yoy_profit_pct,
        pe_vs_industry_max_gap=preset.pe_vs_industry_max_gap,
        require_pe_vs_industry=preset.require_pe_vs_industry,
        max_peg=float(max_peg),
        max_price_to_book=preset.max_price_to_book,
        min_ret_3m_pct=preset.min_ret_3m_pct,
        min_ret_6m_pct=preset.min_ret_6m_pct,
        require_acceleration=preset.require_acceleration,
        soft_skip_missing_valuation=bool(soft_val),
        require_governance_data=bool(req_gov),
        max_results=int(max_hits),
    )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan", type="primary")
    st.caption(
        f"Running **{TIER_LABELS[tier]}** on **{universe}**. "
        "Log into Screener.in (session panel) if fetches look empty on Cloud."
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Checking {s}… ({i}/{t})")

        hits = scan_fundamental_framework(universe, filters=flt, progress_cb=cb)
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe
        st.session_state[f"{session_key}_tier"] = tier
        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits), "tier": tier},
            )
        except Exception:
            pass
        try:
            metrics = [(r.ticker, r.raw_ticker, float(r.price or 0), None) for r in hits if r.price]
            notify_watchlist_alerts_from_metrics(metrics, META["title"])
        except Exception:
            pass
        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)
    last_tier = st.session_state.get(f"{session_key}_tier", tier)

    if results is None:
        st.info("👆 Pick a universe + tier, then **SCAN NOW**.")
        return

    if not results:
        st.warning(
            "No matches. Try **Tier 1 Watchlist**, a larger universe, turn on "
            "**Soft-skip missing PE/PEG/P/B**, or slightly relax PEG / P/B — "
            "not debt or promoter/pledge."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_OPTIONS.keys())
    default_rank = "ret_3m" if last_tier == "momentum" else "score"
    ensure_session_choice(rank_key, rank_choices, default_rank)
    rank_by = st.radio(
        "Rank by",
        rank_choices,
        format_func=lambda x: RANK_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_fundamental_results(results, rank_by=rank_by)

    st.success(
        f"**{len(results)}** matches · {TIER_LABELS.get(last_tier, last_tier)} · "
        f"{last_uni} · {scan_at or '—'}"
    )

    rows = [result_to_row(r, i + 1) for i, r in enumerate(results)]
    df = pd.DataFrame(rows)
    df = deduplicate_scan_results(df, ticker_col="Ticker")
    df = prepare_scan_results_df(df)

    col_cfg = {
        **filter_column_config(df),
        "Score": st.column_config.NumberColumn(format="%.1f"),
        "D/E": st.column_config.NumberColumn(format="%.2f"),
        "PEG": st.column_config.NumberColumn(format="%.2f"),
        "ROE %": st.column_config.NumberColumn(format="%.1f"),
    }
    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_tbl",
        column_config=col_cfg,
        height=min(520, 48 + 28 * min(len(df), 18)),
    )

    by_ticker = {r.ticker: r for r in results}
    sel = st.session_state.get(f"{key}_tbl_selected")
    if sel and str(sel) in by_ticker:
        picked = by_ticker[str(sel)]
        st.markdown(f"#### {picked.label} — detail")
        st.write(picked.verdict)
        st.caption(" · ".join(picked.pass_notes))
        if picked.fail_soft:
            st.caption("Soft skips: " + " · ".join(picked.fail_soft))
        render_historical_detail_panel(picked.raw_ticker, key_prefix=f"{key}_hist")
        if picked.links:
            link_bits = " · ".join(f"[{k}]({v})" for k, v in picked.links.items() if v)
            if link_bits:
                st.markdown(link_bits)

    st.caption(
        "Educational framework only — not investment advice. "
        "Cross-check survivors on Screener.in + annual report before sizing."
    )
