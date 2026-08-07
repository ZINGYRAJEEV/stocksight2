"""Investment Course + Valuation — Workflow 1 scan with Rulebook wealth on each match."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from investment_course_analysis import (
    STORY_CHECKS,
    category_research_items,
    draft_story_paragraph,
    enrich_research_links,
    practical_stance,
)
from investment_course_screener import (
    BROAD_SCAN_SOURCES,
    META,
    RANK_BY_OPTIONS,
    RESEARCH_TOOLS,
    SCAN_MODES,
    SCAN_SOURCES,
    SECTOR_SCAN_SOURCES,
    InvestmentCourseFilters,
    group_results_by_sector,
    resolve_investment_course_tickers,
    result_to_row,
    scan_investment_course,
    sort_investment_course,
    universe_ticker_count,
)
from pe_history_ui import render_pe_history_panel
from scan_checkpoint_store import (
    CHUNK_THRESHOLD,
    DEFAULT_CHUNK_SIZE,
    PAGE_ID as CKPT_PAGE,
    checkpoint_matches,
    clear_checkpoint,
    filters_fingerprint,
    hits_from_checkpoint,
    load_checkpoint,
    merge_hits,
    result_from_dict,
    result_to_dict,
    save_checkpoint,
)
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
| **Below DMA** | Optional: price ≤ 50-DMA and/or ≤ 200-DMA (set how far below) |
| **PEG &lt; 1** | Optional hard filter: PE / profit 3Y growth ≤ Max PEG (default 1.0) |

After you click a result: **Steps 3–6** (category research · story checks · stress Rulebook · stance/sizing).
Results can be **grouped by sector** after the scan. For faster scans, pick a
**sector basket** (Bank / IT / Pharma / …) under Universe → Scan scope.
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


def _render_post_scan_workflow(r) -> None:
    """Steps 3–6: research checklist, story builder, stress test, practical stance."""
    if not r:
        return

    ticker = str(r.ticker)
    links = enrich_research_links(r.links or {}, r.ticker, r.label or r.ticker)
    prefix = f"invc_ps_{ticker}"

    st.markdown("#### After the scan — Steps 3 to 6")
    st.caption(
        "Guided workflow from Stock Analysis Workflow 1. "
        "Tick what you’ve done; stress the Rulebook; then read the stance."
    )

    tab3, tab4, tab5, tab6 = st.tabs(
        [
            "3 · Category research",
            "4 · Story checks",
            "5 · Stress Rulebook",
            "6 · Stance & sizing",
        ]
    )

    # ----- Step 3 -----
    with tab3:
        st.markdown(f"**{r.category}** research prompts")
        items = category_research_items(r.category)
        done = 0
        for it in items:
            ck = st.checkbox(
                it["q"],
                key=f"{prefix}_r_{it['id']}",
                help=it.get("hint") or "",
            )
            if ck:
                done += 1
            st.caption(it.get("hint") or "")
        st.progress(done / max(len(items), 1), text=f"{done}/{len(items)} answered")

        st.markdown("**Open research links**")
        link_cols = st.columns(3)
        for i, (name, url) in enumerate(
            [
                ("Screener Concalls", links.get("Screener Concalls")),
                ("Trendlyne", links.get("Trendlyne")),
                ("Screener.in", links.get("Screener.in")),
                ("Tijori Finance", links.get("Tijori Finance")),
                ("YouTube interviews", links.get("YouTube interviews")),
                ("Value Pickr", links.get("Value Pickr")),
            ]
        ):
            if not url:
                continue
            with link_cols[i % 3]:
                st.markdown(f"[{name} ↗]({url})")

    # ----- Step 4 -----
    with tab4:
        st.markdown("**Story building checklist** (do before any buy)")
        story_done = 0
        for chk in STORY_CHECKS:
            url = links.get(chk["link_key"])
            label = chk["label"]
            if url:
                c_a, c_b = st.columns([3.2, 1.0])
                with c_a:
                    ok = st.checkbox(label, key=f"{prefix}_s_{chk['id']}")
                with c_b:
                    st.markdown(f"[Open ↗]({url})")
            else:
                ok = st.checkbox(label, key=f"{prefix}_s_{chk['id']}")
            if ok:
                story_done += 1
        st.progress(
            story_done / max(len(STORY_CHECKS), 1),
            text=f"{story_done}/{len(STORY_CHECKS)} story checks done",
        )

        draft_key = f"{prefix}_story"
        if draft_key not in st.session_state:
            st.session_state[draft_key] = draft_story_paragraph(r)
        st.text_area(
            "One-paragraph story (edit until clear — if you can’t finish blanks, don’t buy)",
            key=draft_key,
            height=140,
        )
        if st.button("Reset story draft from scan", key=f"{prefix}_story_reset"):
            st.session_state[draft_key] = draft_story_paragraph(r)
            st.rerun()

    # ----- Step 5 -----
    with tab5:
        st.markdown(
            "Run a **conservative Rulebook** pass: cut growth, OPM, and P/E vs defaults. "
            "If the thesis dies under mild stress, keep it on the watchlist."
        )
        s1, s2, s3 = st.columns(3)
        with s1:
            g_cut = st.slider("Growth haircut (pp)", 5.0, 25.0, 10.0, 1.0, key=f"{prefix}_gcut")
        with s2:
            o_cut = st.slider("OPM haircut (pp)", 1.0, 10.0, 3.0, 0.5, key=f"{prefix}_ocut")
        with s3:
            p_cut = st.slider("P/E haircut (%)", 5.0, 40.0, 15.0, 1.0, key=f"{prefix}_pcut")

        run_stress = st.button(
            f"▶ Stress-test {ticker}",
            key=f"{prefix}_stress_btn",
            type="primary",
            use_container_width=True,
        )
        stress_key = f"{prefix}_stress_result"
        if run_stress:
            with st.spinner("Running conservative Rulebook…"):
                try:
                    from valuation_model import stress_wealth_snapshot

                    st.session_state[stress_key] = stress_wealth_snapshot(
                        r.raw_ticker,
                        growth_haircut_pp=g_cut,
                        opm_haircut_pp=o_cut,
                        pe_haircut_pct=p_cut,
                    )
                except Exception as exc:
                    st.session_state[stress_key] = {"error": str(exc)}

        stress = st.session_state.get(stress_key) or {}
        if stress.get("error"):
            st.error(f"Stress test failed: {stress['error']}")
        elif stress:
            ass = stress.get("assumptions") or {}
            survives = bool(stress.get("survives_stress"))
            if survives:
                st.success(
                    f"Survives stress · {stress.get('wealth_emoji', '')} "
                    f"{stress.get('wealth_verdict', '—')}"
                )
            else:
                st.warning(
                    f"Weak under stress · {stress.get('wealth_verdict', '—')} — "
                    "prefer watchlist / better entry."
                )

            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                "Stress target",
                f"₹{stress['model_target']:,.0f}" if stress.get("model_target") else "—",
            )
            m2.metric(
                "Stress upside",
                f"{stress['upside_pct']:+.1f}%" if stress.get("upside_pct") is not None else "—",
            )
            m3.metric(
                "Stress CAGR",
                f"{stress['implied_cagr_pct']:.1f}%"
                if stress.get("implied_cagr_pct") is not None
                else "—",
            )
            m4.metric(
                "Max buy @15%",
                f"₹{stress['max_buy_15pct']:,.0f}" if stress.get("max_buy_15pct") else "—",
            )

            st.caption(
                f"Assumptions: growth {ass.get('base_growth_pct', '—')}% → "
                f"**{ass.get('growth_pct', '—')}%** · "
                f"OPM {ass.get('base_opm_pct', '—')}% → **{ass.get('opm_pct', '—')}%** · "
                f"P/E {ass.get('base_fair_pe', '—')} → **{ass.get('fair_pe', '—')}** · "
                f"entry ₹{ass.get('entry_price', '—')} · "
                f"below max-buy@15%: {'Yes' if ass.get('still_below_max_buy_15') else 'No'}"
            )

            c_base, c_stress = st.columns(2)
            with c_base:
                st.markdown("**Scan (defaults)**")
                st.write(
                    f"Target ₹{(r.model_target or 0):,.0f} · "
                    f"upside {(r.upside_pct or 0):+.1f}% · "
                    f"CAGR {(r.implied_cagr_pct or 0):.1f}% · "
                    f"{'Strong wealth' if r.is_strong_wealth else (r.wealth_verdict or '—')}"
                )
            with c_stress:
                st.markdown("**Stress case**")
                st.write(
                    f"Target ₹{(stress.get('model_target') or 0):,.0f} · "
                    f"upside {(stress.get('upside_pct') or 0):+.1f}% · "
                    f"CAGR {(stress.get('implied_cagr_pct') or 0):.1f}% · "
                    f"{stress.get('wealth_verdict') or '—'}"
                )
        else:
            st.info("Set haircuts and run the stress test.")

        st.page_link(
            VALUATION_RULEBOOK_PAGE,
            label="Open full Valuation Rulebook to edit every assumption",
            icon="🧮",
        )

    # ----- Step 6 -----
    with tab6:
        stress = st.session_state.get(f"{prefix}_stress_result") or {}
        if stress.get("error"):
            stress = {}
        stance = practical_stance(r, stress if stress else None)

        color = (
            "#16a34a"
            if "Candidate" in stance["label"]
            else ("#b45309" if "Watchlist" in stance["label"] or "pass" in stance["label"].lower() else "#64748b")
        )
        st.markdown(
            f"""
<div style='border:2px solid {color};border-radius:14px;padding:16px 20px;
            background:#0f172a;margin:4px 0 12px;'>
  <div style='font-size:0.75rem;letter-spacing:0.06em;color:#94a3b8;text-transform:uppercase;'>
    Practical stance (educational — not advice)
  </div>
  <div style='font-size:1.2rem;font-weight:700;color:{color};margin-top:4px;'>
    {stance["label"]}
  </div>
  <div style='color:#e2e8f0;margin-top:8px;font-size:0.95rem;'>
    {stance["action"]}
  </div>
  <div style='color:#94a3b8;margin-top:6px;font-size:0.9rem;'>
    Suggested size: <b style='color:#e2e8f0'>{stance["size"]}</b>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

        bcol, rcol = st.columns(2)
        with bcol:
            st.markdown("**Bull case (from scan)**")
            for x in stance["bull"] or ["—"]:
                st.markdown(f"- {x}")
        with rcol:
            st.markdown("**Bear / caution**")
            for x in stance["bear"] or ["—"]:
                st.markdown(f"- {x}")

        st.markdown("**Exit ideas (set before you buy)**")
        for x in stance["exits"]:
            st.markdown(f"- {x}")

        if not stress:
            st.caption("Tip: run **Step 5 · Stress Rulebook** first — stance gets sharper with stress results.")

        notes_key = f"{prefix}_notes"
        st.text_area(
            "Your decision notes",
            key=notes_key,
            height=90,
            placeholder="e.g. Wait for next concall · Buy 1% on dip below 50-DMA · Trim plan…",
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
            scope_key = f"{key}_uni_scope"
            ensure_session_choice(scope_key, ["By sector", "Broad market"], "By sector")
            uni_scope = st.radio(
                "Scan scope",
                ["By sector", "Broad market"],
                horizontal=True,
                key=scope_key,
                help="Prefer **By sector** — smaller lists scan faster and are easier to research.",
            )

            if uni_scope == "By sector" and SECTOR_SCAN_SOURCES:
                sector_keys = list(SECTOR_SCAN_SOURCES.keys())
                sec_key = f"{key}_sector_uni"
                ensure_session_choice(sec_key, sector_keys, sector_keys[0])
                universe = st.selectbox(
                    "Sector basket",
                    sector_keys,
                    key=sec_key,
                    format_func=lambda s: f"{s.replace('Sector · ', '')} ({universe_ticker_count(s)})",
                    help="Nifty sectoral constituents — pick one sector per scan.",
                )
                preview = resolve_investment_course_tickers(universe)
                st.caption(
                    f"**{len(preview)}** tickers · "
                    + ", ".join(t for t, _ in preview[:12])
                    + ("…" if len(preview) > 12 else "")
                )
            else:
                uni_key = f"{key}_universe"
                nse_sources = BROAD_SCAN_SOURCES or [
                    s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s
                ]
                # Always surface full NSE at the top of Broad market.
                all_nse = "All NSE equities (~2300) - very slow"
                if all_nse not in nse_sources:
                    nse_sources = [all_nse] + list(nse_sources)
                else:
                    nse_sources = [all_nse] + [s for s in nse_sources if s != all_nse]
                ensure_session_choice(uni_key, nse_sources, nse_sources[1] if len(nse_sources) > 1 else nse_sources[0])
                universe = st.selectbox(
                    "Stock universe (NSE)",
                    nse_sources,
                    key=uni_key,
                    format_func=lambda s: f"{s} ({universe_ticker_count(s)})",
                    help=(
                        "First option = full NSE (~2300). "
                        "Prefer Curated / Nifty 50 / sector baskets for normal scans."
                    ),
                )
                st.caption(
                    "💡 Full list = **All NSE equities (~2300) - very slow** (first row in this dropdown)."
                )
                n_uni = universe_ticker_count(universe)
                if "All NSE" in universe:
                    if n_uni <= 0:
                        st.error(
                            "Full NSE list failed to load (0 tickers). "
                            "Cloud may be blocking NSE download — use **Nifty 500** or a **sector basket**. "
                            "If this persists after redeploy, the committed `stocksight/data/nse_equity_symbols.txt` cache is missing."
                        )
                    else:
                        st.warning(
                            f"**{n_uni}** tickers — full NSE scan can take hours. "
                            "Use sector baskets or Nifty 500 for normal research."
                        )
                else:
                    st.caption(f"**{n_uni}** tickers in this broad list.")

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
            require_cagr = st.checkbox(
                "Require 3Y sales + profit CAGR",
                value=True,
                key=f"{key}_req_cagr",
                help="Drops names like PSB where Screener CAGR is missing (avoids fake Strong wealth).",
            )
            drop_unclass = st.checkbox(
                "Drop Unclassified / thin-data names",
                value=True,
                key=f"{key}_drop_unclass",
                help="STEP 0 only keeps categorized names with usable growth data.",
            )
        with c2:
            st.markdown("#### Workflow A valuation")
            max_peg = st.slider(
                "Max PEG (buy zone)",
                0.5,
                2.0,
                1.0,
                0.05,
                key=f"{key}_peg",
                help="Course rule: PEG = PE / profit growth. PEG < 1 ≈ cheap.",
            )
            require_peg = st.checkbox(
                "Only PEG ≤ max (hard filter)",
                value=False,
                key=f"{key}_req_peg",
                help="Keep names where PEG is known and ≤ Max PEG (set 1.0 for classic PEG < 1).",
            )
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
        st.markdown("#### Price vs moving averages")
        d1, d2, d3 = st.columns([1.0, 1.0, 1.1])
        with d1:
            below_50 = st.checkbox(
                "Only below 50-DMA",
                value=False,
                key=f"{key}_below50",
                help="Keep names where LTP is at or below the 50-day moving average.",
            )
            max_vs_50 = st.slider(
                "Max % vs 50-DMA",
                -40.0,
                0.0,
                0.0,
                1.0,
                key=f"{key}_pct50",
                disabled=not below_50,
                help="0 = at/below DMA. −10 = at least 10% below the 50-DMA.",
            )
        with d2:
            below_200 = st.checkbox(
                "Only below 200-DMA",
                value=False,
                key=f"{key}_below200",
                help="Keep names where LTP is at or below the 200-day moving average.",
            )
            max_vs_200 = st.slider(
                "Max % vs 200-DMA",
                -40.0,
                0.0,
                0.0,
                1.0,
                key=f"{key}_pct200",
                disabled=not below_200,
                help="0 = at/below DMA. −10 = at least 10% below the 200-DMA.",
            )
        with d3:
            min_roce = st.slider("Min ROCE % (0 = off)", 0.0, 30.0, 0.0, 1.0, key=f"{key}_roce")
            st.caption(
                "Every match shows **vs 50-DMA %** and **vs 200-DMA %**. "
                "Tick the boxes to hard-filter for names trading low vs those averages. "
                "Rank by “Most below 50/200-DMA” after the scan."
            )

    render_watchlist_panel(f"{key}_wl")

    flt = InvestmentCourseFilters(
        mode=mode,
        max_peg=max_peg,
        require_peg_max=require_peg,
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
        require_growth_cagr=require_cagr,
        drop_unclassified=drop_unclass,
        skip_wealth_without_growth=True,
        require_below_50dma=below_50,
        require_below_200dma=below_200,
        max_pct_vs_50dma=max_vs_50,
        max_pct_vs_200dma=max_vs_200,
        need_pe_history=mode
        in ("step0_categorize", "workflow_a_fast", "buy_candidates", "stalwarts_discount"),
    )
    flt_hash = filters_fingerprint(flt)
    n_uni = universe_ticker_count(universe)
    use_chunks = n_uni > CHUNK_THRESHOLD

    ckpt = load_checkpoint(CKPT_PAGE)
    can_resume = checkpoint_matches(
        ckpt, universe=universe, mode=mode, filters_hash=flt_hash
    )

    st.markdown("#### Scan control")
    if use_chunks:
        st.caption(
            f"Large universe (**{n_uni}** tickers) → scans run in **chunks** with a checkpoint, "
            "so Cloud timeouts / disconnects do not wipe progress. Keep the tab open for auto-continue."
        )
        chunk_size = int(
            st.number_input(
                "Tickers per chunk",
                min_value=25,
                max_value=300,
                value=DEFAULT_CHUNK_SIZE,
                step=25,
                key=f"{key}_chunk_size",
                help="Smaller chunks = safer on Streamlit Cloud; larger = fewer reruns.",
            )
        )
        auto_continue = st.checkbox(
            "Auto-continue chunks until done",
            value=True,
            key=f"{key}_auto_continue",
            help="After each chunk, automatically start the next until the universe is finished.",
        )
    else:
        chunk_size = n_uni or DEFAULT_CHUNK_SIZE
        auto_continue = False

    if can_resume and ckpt:
        st.info(
            f"Checkpoint: **{int(ckpt.get('next_index') or 0)} / {int(ckpt.get('total') or n_uni)}** "
            f"scanned · **{len(ckpt.get('hits') or [])}** matches so far. "
            "Use **Continue** or **Reset**."
        )

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        run_fresh = st.button(
            "▶  SCAN NOW",
            use_container_width=True,
            key=f"{key}_scan",
            type="primary",
        )
    with b2:
        run_continue = st.button(
            "⏯ Continue",
            use_container_width=True,
            key=f"{key}_continue",
            disabled=not can_resume,
        )
    with b3:
        stop_scan = st.button(
            "⏹ Stop",
            use_container_width=True,
            key=f"{key}_stop",
        )
    with b4:
        reset_ckpt = st.button(
            "🗑 Reset checkpoint",
            use_container_width=True,
            key=f"{key}_reset_ckpt",
        )

    if reset_ckpt:
        clear_checkpoint(CKPT_PAGE)
        st.session_state.pop(f"{key}_scan_job", None)
        st.session_state[f"{key}_cancel"] = False
        st.success("Checkpoint cleared.")
        st.rerun()

    if stop_scan:
        st.session_state[f"{key}_cancel"] = True
        st.session_state.pop(f"{key}_scan_job", None)
        st.warning("Stop requested — current chunk will finish, then pause.")

    scan_progress = st.empty()

    if run_fresh:
        clear_checkpoint(CKPT_PAGE)
        st.session_state[f"{key}_cancel"] = False
        st.session_state[f"{key}_scan_job"] = {
            "universe": universe,
            "mode": mode,
            "filters_hash": flt_hash,
            "next_index": 0,
            "hits": [],
            "auto": bool(auto_continue) if use_chunks else False,
            "chunk_size": int(chunk_size) if use_chunks else max(n_uni, 1),
            "fresh": True,
        }
        st.rerun()

    if run_continue and can_resume and ckpt:
        st.session_state[f"{key}_cancel"] = False
        st.session_state[f"{key}_scan_job"] = {
            "universe": universe,
            "mode": mode,
            "filters_hash": flt_hash,
            "next_index": int(ckpt.get("next_index") or 0),
            "hits": [result_to_dict(r) for r in hits_from_checkpoint(ckpt)],
            "auto": bool(auto_continue) if use_chunks else False,
            "chunk_size": int(chunk_size) if use_chunks else max(n_uni, 1),
            "fresh": False,
        }
        st.rerun()

    job = st.session_state.get(f"{key}_scan_job")
    if (
        job
        and job.get("universe") == universe
        and job.get("mode") == mode
        and job.get("filters_hash") == flt_hash
    ):
        start_idx = int(job.get("next_index") or 0)
        csize = int(job.get("chunk_size") or DEFAULT_CHUNK_SIZE)
        prior_hits = []
        for row in job.get("hits") or []:
            try:
                prior_hits.append(result_from_dict(row))
            except Exception:
                pass

        prog = scan_progress.progress(
            int(start_idx / max(n_uni, 1) * 100),
            text=f"Resuming at {start_idx}/{n_uni}…",
        )

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        def cancel_cb() -> bool:
            return bool(st.session_state.get(f"{key}_cancel"))

        chunk = scan_investment_course(
            universe,
            filters=flt,
            progress_cb=cb,
            start_index=start_idx,
            max_tickers=csize if use_chunks else None,
            cancel_cb=cancel_cb,
        )
        merged = merge_hits(prior_hits, chunk.hits)
        merged = sort_investment_course(merged, rank_by="score", mode=mode)

        st.session_state[session_key] = merged
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe
        st.session_state[f"{session_key}_mode"] = mode
        if job.get("fresh"):
            st.session_state[f"{key}_chart_selected"] = None

        if chunk.cancelled or st.session_state.get(f"{key}_cancel"):
            save_checkpoint(
                universe=universe,
                mode=mode,
                filters_hash=flt_hash,
                next_index=chunk.next_index,
                total=chunk.total,
                hits=merged,
            )
            st.session_state.pop(f"{key}_scan_job", None)
            st.session_state[f"{key}_cancel"] = False
            prog.empty()
            scan_progress.empty()
            st.warning(
                f"Paused at **{chunk.next_index}/{chunk.total}**. "
                f"**{len(merged)}** matches saved — click **Continue** to resume."
            )
        elif chunk.done:
            clear_checkpoint(CKPT_PAGE)
            st.session_state.pop(f"{key}_scan_job", None)
            try:
                append_scan_record(
                    META["id"],
                    universe,
                    [r.raw_ticker for r in merged],
                    meta={
                        "matches": len(merged),
                        "mode": mode,
                        "strong_wealth": sum(1 for r in merged if r.is_strong_wealth),
                        "scanned": chunk.total,
                    },
                )
            except Exception:
                pass
            prog.empty()
            scan_progress.empty()
            st.success(f"Scan complete — **{chunk.total}** tickers · **{len(merged)}** matches.")
        else:
            save_checkpoint(
                universe=universe,
                mode=mode,
                filters_hash=flt_hash,
                next_index=chunk.next_index,
                total=chunk.total,
                hits=merged,
            )
            st.session_state[f"{key}_scan_job"] = {
                "universe": universe,
                "mode": mode,
                "filters_hash": flt_hash,
                "next_index": chunk.next_index,
                "hits": [result_to_dict(r) for r in merged],
                "auto": bool(job.get("auto")),
                "chunk_size": csize,
                "fresh": False,
            }
            prog.empty()
            scan_progress.empty()
            st.info(
                f"Chunk done — **{chunk.next_index}/{chunk.total}** · "
                f"**{len(merged)}** matches so far."
            )
            if job.get("auto") and not st.session_state.get(f"{key}_cancel"):
                st.rerun()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)
    last_mode = st.session_state.get(f"{session_key}_mode", mode)

    # Restore partial hits from checkpoint when session was lost but disk remains
    if results is None and can_resume and ckpt:
        restored = hits_from_checkpoint(ckpt)
        if restored:
            st.session_state[session_key] = restored
            st.session_state[f"{session_key}_at"] = "checkpoint"
            st.session_state[f"{session_key}_universe"] = universe
            st.session_state[f"{session_key}_mode"] = mode
            results = restored
            scan_at = "checkpoint"
            last_uni = universe
            last_mode = mode

    if results is None:
        st.info(
            "👆 Pick a **sector basket** (or broad universe), then **SCAN NOW**. "
            "Large universes run in **chunks** with resume support."
        )
        return

    if not results:
        if "All NSE" in str(last_uni) and (not results):
            # Distinguish empty universe vs filters wiping matches
            try:
                from nse_universe import last_nse_universe_error, nse_equity_count

                n_all = nse_equity_count()
                err = last_nse_universe_error()
            except Exception:
                n_all, err = 0, ""
            if n_all <= 0:
                st.warning(
                    "No matches because the **full NSE ticker list is empty** "
                    f"(load error: {err or 'cache missing'}). "
                    "Pick **Nifty 500** or a **sector basket** instead."
                )
                return
        # Incomplete scan with zero hits yet — don't show "no matches" as final
        if can_resume and ckpt and int(ckpt.get("next_index") or 0) > 0:
            st.info(
                "No matches yet in the scanned portion. Click **Continue** to keep going, "
                "or loosen filters and **SCAN NOW** again."
            )
            return
        st.warning(
            "No matches. Try **STEP 0**, turn off **Only Strong wealth** / DMA / "
            "**Require CAGR** / **PEG** filters, lower min mcap, or use **Curated / Nifty 50**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    default_rank = (
        "vol_ratio"
        if last_mode == "volume_spike"
        else (
            "dma200"
            if below_200
            else ("dma50" if below_50 else ("wealth" if include_wealth else "score"))
        )
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

    grouped_all = group_results_by_sector(results, rank_by=rank_by, mode=last_mode)
    sector_names = list(grouped_all.keys())

    st.markdown("#### Sector mix")
    if sector_names:
        scols = st.columns(min(len(sector_names), 6) or 1)
        for i, sec in enumerate(sector_names):
            scols[i % len(scols)].metric(sec, len(grouped_all[sec]))
    else:
        st.caption("No sector data on matches.")

    v1, v2 = st.columns([1.2, 1.4])
    with v1:
        view_mode = st.radio(
            "Results layout",
            ["Grouped by sector", "Flat table"],
            horizontal=True,
            key=f"{key}_view",
        )
    with v2:
        sector_choices = ["All sectors"] + sector_names
        ensure_session_choice(f"{key}_sector_filter", sector_choices, "All sectors")
        sector_filter = st.selectbox(
            "Filter sector",
            sector_choices,
            key=f"{key}_sector_filter",
            help="Show one sector only, or all.",
        )

    if sector_filter != "All sectors":
        results = [r for r in results if ((r.sector or "").strip() or "—") == sector_filter]
        grouped_all = group_results_by_sector(results, rank_by=rank_by, mode=last_mode)

    n_strong = sum(1 for r in results if r.is_strong_wealth)
    n_sectors = len(grouped_all)
    st.success(
        f"**{len(results)}** matches · **{n_sectors}** sector(s) · **{n_strong}** Strong wealth · "
        f"{SCAN_MODES.get(last_mode, last_mode)} · {last_uni} · scanned {scan_at or '—'}"
    )

    by_ticker = {r.ticker: r for r in results}

    def _rows_for(slice_results: list) -> list[dict]:
        out = []
        for i, r in enumerate(slice_results, start=1):
            row = result_to_row(r, i)
            for link_name, link_url in (r.links or {}).items():
                row[link_name] = link_url
            out.append(row)
        return out

    def _df_for(slice_results: list, cache_suffix: str) -> pd.DataFrame:
        df_local = pd.DataFrame(_rows_for(slice_results))
        if df_local.empty:
            return df_local
        df_local = deduplicate_scan_results(df_local)
        return prepare_scan_results_df(
            df_local,
            universe_name=last_uni,
            cache_key_prefix=f"{key}_results_{cache_suffix}",
            raw_ticker_col="Raw",
        )

    # Build a master df (all filtered results) for detail / PE panels
    df = _df_for(results, "all")

    col_cfg = filter_column_config(
        df if not df.empty else pd.DataFrame([{"Ticker": ""}]),
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
            "50-DMA": st.column_config.NumberColumn(format="₹%.2f"),
            "vs 50-DMA %": st.column_config.NumberColumn(format="%+.1f"),
            "200-DMA": st.column_config.NumberColumn(format="₹%.2f"),
            "vs 200-DMA %": st.column_config.NumberColumn(format="%+.1f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "Sector": st.column_config.TextColumn(width="medium"),
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
            "YouTube interviews": st.column_config.LinkColumn(display_text="YouTube ↗"),
        },
    )

    chart_sel_key = f"{key}_chart_selected"

    def _on_row_select(row: pd.Series) -> None:
        try:
            st.session_state[chart_sel_key] = str(row["Ticker"])
        except Exception:
            pass

    if df.empty:
        st.warning("No matches in the selected sector filter.")
        return

    if view_mode == "Grouped by sector":
        for sec, sec_hits in grouped_all.items():
            n_sw = sum(1 for r in sec_hits if r.is_strong_wealth)
            with st.expander(
                f"**{sec}** — {len(sec_hits)} ticker(s)"
                + (f" · {n_sw} Strong wealth" if n_sw else ""),
                expanded=len(grouped_all) <= 4 or sec == sector_names[0],
            ):
                tickers_line = ", ".join(r.ticker for r in sec_hits[:40])
                if len(sec_hits) > 40:
                    tickers_line += f" … +{len(sec_hits) - 40} more"
                st.caption(tickers_line)
                sec_df = _df_for(sec_hits, f"sec_{sec}")
                if sec_df.empty:
                    st.caption("No rows.")
                    continue
                render_clickable_scan_table(
                    sec_df,
                    key_prefix=f"{key}_sec_{sec}",
                    universe_name=last_uni,
                    column_config=filter_column_config(sec_df, col_cfg),
                    height=min(420, 48 + len(sec_df) * 38),
                    show_panel=False,
                    on_row_select=_on_row_select,
                )
    else:
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
            _render_post_scan_workflow(picked)

    with st.expander("Quick-Fire + next steps (by sector)", expanded=False):
        for sec, sec_hits in grouped_all.items():
            st.markdown(f"**{sec}**")
            for r in sec_hits[:15]:
                wealth_bit = f" · {r.wealth_emoji} {r.wealth_verdict}" if r.wealth_verdict else ""
                st.markdown(
                    f"- **{r.label}** ({r.category}) — {r.verdict}{wealth_bit}  \n"
                    f"  QF {r.checklist_score}/{r.checklist_max}: "
                    f"{' · '.join(r.checklist_flags[:5])}  \n"
                    f"  *{r.next_steps}*"
                )
            if len(sec_hits) > 15:
                st.caption(f"…and {len(sec_hits) - 15} more in {sec}")

    st.caption(
        "Workflow 1 gates + Valuation Rulebook defaults. "
        "Not investment advice — tweak assumptions on Valuation Rulebook before acting."
    )
