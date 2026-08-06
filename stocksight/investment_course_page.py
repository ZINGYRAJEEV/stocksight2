"""Investment Course + Valuation — Workflow 1 scan with Rulebook wealth on each match."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from investment_course_screener import (
    META,
    RANK_BY_OPTIONS,
    RESEARCH_TOOLS,
    SCAN_MODES,
    SCAN_SOURCES,
    InvestmentCourseFilters,
    result_to_row,
    scan_investment_course,
    sort_investment_course,
)
from pe_history_ui import render_pe_history_panel
from scan_history_store import append_scan_record
from screener_session_ui import render_screener_session_panel
from session_utils import deduplicate_scan_results
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_historical_detail_panel,
    render_watchlist_panel,
    safe_set_page_config,
)


VALUATION_RULEBOOK_PAGE = "stocksight/pages/Valuation Rulebook.py"


def _rules_panel() -> None:
    with st.expander("📖 How this screen works", expanded=False):
        st.markdown(
            """
Aligned with [`docs/Stock_Analysis_Workflow_1.md`](docs/Stock_Analysis_Workflow_1.md).
**Scan** applies STEP 0 / Workflow A gates, then runs a **Valuation Rulebook** snapshot
(target price, implied CAGR, Strong wealth flag) on each match.

| Category | Rule |
|---|---|
| **Fast Grower** | Sales & profit 3Y ≥ 15% |
| **Stalwart** | Both 10–15%; buy at/below FY median PE |
| **Strong wealth** | Rulebook: upside ≥20%, CAGR ≥16%, score ≥70, entry ≤ max buy @15% |

Click a result row for **price chart**, **P/E history**, and the full **wealth panel**.
"""
        )
        st.page_link(
            VALUATION_RULEBOOK_PAGE,
            label="Open full Valuation Rulebook (tweak assumptions)",
            icon="🧮",
        )
        st.markdown("**Research tools**")
        for name, use in RESEARCH_TOOLS:
            st.markdown(f"- **{name}** — {use}")


def _story_panel() -> None:
    with st.expander("📝 Story building checklist (manual)", expanded=False):
        st.markdown(
            """
1. Google promoter + scam/fraud · YouTube interviews  
2. Glassdoor ≥ 3.0 · sticky/repeat business?  
3. Market share / industry growth (Trendlyne, presentations)  
4. Credit ratings + risk factors on Screener  
5. Write a one-paragraph story before you buy
"""
        )


def _render_selected_wealth(r) -> None:
    """Wealth / Rulebook panel for the clicked scan row."""
    if not r or not (r.wealth_verdict or r.model_target):
        st.info(
            "No Valuation Rulebook snapshot for this name "
            "(data missing or wealth load was skipped)."
        )
        return

    color = "#16a34a" if r.is_strong_wealth else "#64748b"
    stance = r.wealth_stance or "—"
    st.markdown(
        f"""
<div style='border:2px solid {color};border-radius:14px;padding:16px 20px;
            background:#0f172a;margin:8px 0 12px;'>
  <div style='font-size:0.75rem;letter-spacing:0.06em;color:#94a3b8;text-transform:uppercase;'>
    Valuation Rulebook read (defaults — educational)
  </div>
  <div style='font-size:1.25rem;font-weight:700;color:{color};margin-top:4px;'>
    {r.wealth_emoji or ""} {r.wealth_verdict or stance}
  </div>
  <div style='color:#e2e8f0;margin-top:6px;font-size:0.95rem;'>
    Stance: <b>{stance}</b>
    · Target <b>₹{(r.model_target or 0):,.0f}</b>
    · vs LTP ₹{(r.price or 0):,.0f}
    · Upside <b>{(r.upside_pct or 0):+.1f}%</b>
    · Implied CAGR <b>{(r.implied_cagr_pct or 0):.1f}%</b>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if r.wealth_detail:
        st.caption(r.wealth_detail)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Wealth score", f"{r.wealth_score}/100" if r.wealth_score is not None else "—")
    c2.metric("Model target", f"₹{r.model_target:,.0f}" if r.model_target else "—")
    c3.metric("Upside", f"{r.upside_pct:+.1f}%" if r.upside_pct is not None else "—")
    c4.metric(
        "Max buy @15% CAGR",
        f"₹{r.max_buy_15pct:,.0f}" if r.max_buy_15pct else "—",
    )

    if r.is_strong_wealth:
        st.success("🟢 Flagged as **Strong wealth candidate** under default Rulebook assumptions.")

    if r.wealth_strengths or r.wealth_risks or r.wealth_suggestions:
        with st.expander("Strengths · risks · next steps", expanded=True):
            if r.wealth_strengths:
                st.markdown("**Strengths**")
                for s in r.wealth_strengths:
                    st.markdown(f"- {s}")
            if r.wealth_risks:
                st.markdown("**Risks**")
                for s in r.wealth_risks:
                    st.markdown(f"- {s}")
            if r.wealth_suggestions:
                st.markdown("**Suggestions**")
                for s in r.wealth_suggestions:
                    st.markdown(f"- {s}")

    b1, b2 = st.columns(2)
    with b1:
        if st.button(
            f"🧮 Prefill Valuation Rulebook ({r.ticker})",
            key=f"invc_val_prefill_{r.ticker}",
            use_container_width=True,
        ):
            st.session_state.val_prefill_ticker = r.ticker
            st.session_state.val_baseline = None
            st.success(f"**{r.ticker}** queued — open Valuation Rulebook to tweak assumptions.")
    with b2:
        st.page_link(
            VALUATION_RULEBOOK_PAGE,
            label="Open Valuation Rulebook",
            icon="🧮",
        )


def render_investment_course_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()
    _story_panel()

    key = "invc"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"

    mode_key = f"{key}_mode"
    mode_ids = list(SCAN_MODES.keys())
    ensure_session_choice(mode_key, mode_ids, "step0_categorize")
    mode = st.radio(
        "Workflow mode",
        mode_ids,
        format_func=lambda x: SCAN_MODES[x],
        horizontal=False,
        key=mode_key,
    )

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
                help="Start with Curated or Nifty 50 — Screener + wealth model is slower.",
            )
            include_wealth = st.checkbox(
                "Load Valuation Rulebook on each match",
                value=True,
                key=f"{key}_wealth",
                help="Runs default Rulebook model (target, CAGR, Strong wealth flag) per pass.",
            )
            strong_only = st.checkbox(
                "Only Strong wealth candidates",
                value=False,
                key=f"{key}_strong",
                help="Keep names where wealth verdict = Strong wealth candidate.",
            )
        with c2:
            st.markdown("#### Workflow A valuation")
            max_peg = st.slider("Max PEG (buy zone)", 0.5, 2.0, 1.0, 0.05, key=f"{key}_peg")
            max_pct = st.slider(
                "Max vs FY median % (Stalwart / PE check)",
                -30.0,
                5.0,
                0.0,
                1.0,
                key=f"{key}_pct",
            )
            min_fy = st.slider("Min FY PE points", 2, 10, 3, 1, key=f"{key}_fy")
        with c3:
            st.markdown("#### Size, Quick-Fire & volume")
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 500.0, 50.0, key=f"{key}_mcap")
            min_qf = st.slider("Min Quick-Fire score (0 = off)", 0, 8, 0, 1, key=f"{key}_qf")
            require_qf = st.checkbox(
                "Workflow A: require strong Quick-Fire",
                value=False,
                key=f"{key}_req_qf",
            )
            vol_mcap = st.slider("Volume mode min mcap (₹ Cr)", 50.0, 1000.0, 50.0, 25.0, key=f"{key}_vmcap")
            vol_mult = st.slider("Volume multiple (1w vs 1y)", 2.0, 10.0, 5.0, 0.5, key=f"{key}_vmult")
            min_wret = st.slider("Min 1-week return %", 1.0, 20.0, 5.0, 0.5, key=f"{key}_wret")

    with st.container(border=True):
        min_roce = st.slider("Min ROCE % (0 = off)", 0.0, 30.0, 0.0, 1.0, key=f"{key}_roce")
        st.caption(
            "Scan = Workflow gates + optional Rulebook wealth. "
            "Click a row for charts / P/E / full wealth panel. "
            "Use Valuation Rulebook to change assumptions."
        )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan", type="primary")

    flt = InvestmentCourseFilters(
        mode=mode,
        max_peg=max_peg,
        max_pct_vs_fy_median=max_pct,
        min_fy_points=min_fy,
        min_market_cap_cr=min_mcap,
        volume_min_market_cap_cr=vol_mcap,
        min_roce_pct=min_roce,
        vol_mult=vol_mult,
        min_week_return_pct=min_wret,
        require_quickfire_pass=require_qf,
        min_checklist_score=min_qf,
        include_wealth=include_wealth,
        strong_wealth_only=strong_only,
        need_pe_history=mode
        in ("step0_categorize", "workflow_a_fast", "buy_candidates", "stalwarts_discount"),
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        hits = scan_investment_course(universe, filters=flt, progress_cb=cb)
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe
        st.session_state[f"{session_key}_mode"] = mode
        st.session_state[f"{key}_chart_selected"] = None
        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in hits],
                meta={
                    "matches": len(hits),
                    "mode": mode,
                    "strong_wealth": sum(1 for r in hits if r.is_strong_wealth),
                },
            )
        except Exception:
            pass
        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)
    last_mode = st.session_state.get(f"{session_key}_mode", mode)

    if results is None:
        st.info(
            "👆 Pick a mode and universe, then **SCAN NOW**. "
            "Results include Valuation Rulebook wealth when enabled."
        )
        return

    if not results:
        st.warning(
            "No matches. Try **STEP 0**, turn off **Only Strong wealth**, "
            "lower min mcap, or use **Curated / Nifty 50**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    default_rank = (
        "vol_ratio"
        if last_mode == "volume_spike"
        else ("wealth" if include_wealth else "score")
    )
    ensure_session_choice(rank_key, rank_choices, default_rank)
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_investment_course(results, rank_by=rank_by, mode=last_mode)

    if last_mode == "step0_categorize":
        cats = {}
        for r in results:
            cats[r.category] = cats.get(r.category, 0) + 1
        st.markdown("#### STEP 0 — category mix")
        cols = st.columns(min(len(cats), 6) or 1)
        for i, (cat, n) in enumerate(sorted(cats.items(), key=lambda x: -x[1])):
            cols[i % len(cols)].metric(cat, n)

    n_strong = sum(1 for r in results if r.is_strong_wealth)
    st.success(
        f"**{len(results)}** matches · **{n_strong}** Strong wealth · "
        f"{SCAN_MODES.get(last_mode, last_mode)} · {last_uni} · scanned {scan_at or '—'}"
    )

    rows = []
    by_ticker = {}
    for i, r in enumerate(results, start=1):
        by_ticker[r.ticker] = r
        row = result_to_row(r, i)
        for link_name, link_url in (r.links or {}).items():
            row[link_name] = link_url
        rows.append(row)

    df = pd.DataFrame(rows)
    df = deduplicate_scan_results(df)
    df = prepare_scan_results_df(
        df,
        universe_name=last_uni,
        cache_key_prefix=f"{key}_results",
        raw_ticker_col="Raw",
    )

    col_cfg = filter_column_config(
        df,
        {
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "Wealth score": st.column_config.NumberColumn(format="%d"),
            "Model target ₹": st.column_config.NumberColumn(format="₹%.0f"),
            "Upside %": st.column_config.NumberColumn(format="%+.1f"),
            "Implied CAGR %": st.column_config.NumberColumn(format="%.1f"),
            "Max buy @15%": st.column_config.NumberColumn(format="₹%.0f"),
            "Sales 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "Profit 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "Sales TTM %": st.column_config.NumberColumn(format="%.1f"),
            "Profit TTM %": st.column_config.NumberColumn(format="%.1f"),
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "FY median P/E": st.column_config.NumberColumn(format="%.1f"),
            "vs median %": st.column_config.NumberColumn(format="%+.1f"),
            "PEG": st.column_config.NumberColumn(format="%.2f"),
            "OPM %": st.column_config.NumberColumn(format="%.1f"),
            "OPM Δ pp": st.column_config.NumberColumn(format="%+.1f"),
            "Net profit YoY %": st.column_config.NumberColumn(format="%+.1f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "1w ret %": st.column_config.NumberColumn(format="%+.1f"),
            "Vol ratio": st.column_config.NumberColumn(format="%.1f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "Wealth": st.column_config.TextColumn(width="medium"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "Next steps": st.column_config.TextColumn(width="large"),
            "QF flags": st.column_config.TextColumn(width="large"),
            "Raw": None,
            "Notes": None,
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
            "Screener.in": st.column_config.LinkColumn(display_text="Screener ↗"),
            "Screener Concalls": st.column_config.LinkColumn(display_text="Concalls ↗"),
            "Trendlyne": st.column_config.LinkColumn(display_text="Trendlyne ↗"),
            "Tijori Finance": st.column_config.LinkColumn(display_text="Tijori ↗"),
            "Value Pickr": st.column_config.LinkColumn(display_text="ValuePickr ↗"),
            "Glassdoor": st.column_config.LinkColumn(display_text="Glassdoor ↗"),
            "Google scam check": st.column_config.LinkColumn(display_text="Scam check ↗"),
        },
    )

    chart_sel_key = f"{key}_chart_selected"

    def _on_row_select(row: pd.Series) -> None:
        try:
            st.session_state[chart_sel_key] = str(row["Ticker"])
        except Exception:
            pass

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
        show_panel=False,
        on_row_select=_on_row_select,
    )

    sel = st.session_state.get(chart_sel_key)
    if not sel and results:
        sel = results[0].ticker
        st.caption("💡 Click a row to switch charts / wealth panel (showing top match for now).")

    if sel and not df.empty:
        st.markdown("---")
        st.markdown(f"#### Selected: **{sel}**")
        render_historical_detail_panel(
            df,
            universe_name=last_uni,
            key_prefix=f"{key}_detail",
            selected_ticker=sel,
        )

        hit = df[df["Ticker"].astype(str) == str(sel)]
        raw_sym = None
        fy_med_hint = None
        if not hit.empty:
            if "Raw" in hit.columns:
                raw_sym = str(hit.iloc[0]["Raw"])
            if "FY median P/E" in hit.columns:
                try:
                    v = hit.iloc[0]["FY median P/E"]
                    if pd.notna(v):
                        fy_med_hint = float(v)
                except Exception:
                    pass

        if last_mode != "volume_spike":
            render_pe_history_panel(
                display_ticker=str(sel),
                raw_ticker=raw_sym,
                max_pe_hint=fy_med_hint,
                key_prefix=f"{key}_pehist",
            )

        picked = by_ticker.get(str(sel))
        if picked:
            st.markdown("#### Valuation Rulebook (from scan)")
            _render_selected_wealth(picked)

    with st.expander("Quick-Fire + next steps (per stock)", expanded=False):
        for r in results[:25]:
            wealth_bit = f" · {r.wealth_emoji} {r.wealth_verdict}" if r.wealth_verdict else ""
            st.markdown(
                f"**{r.label}** ({r.category}) — {r.verdict}{wealth_bit}  \n"
                f"QF {r.checklist_score}/{r.checklist_max}: {' · '.join(r.checklist_flags[:5])}  \n"
                f"*{r.next_steps}*"
            )

    st.caption(
        "Workflow 1 gates + Valuation Rulebook defaults. "
        "Not investment advice — tweak assumptions on Valuation Rulebook before acting."
    )
