"""Investment Course Screener — UI aligned to Stock_Analysis_Workflow_1.md."""

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
    render_watchlist_panel,
    safe_set_page_config,
)


VALUATION_RULEBOOK_PAGE = "stocksight/pages/Valuation Rulebook.py"


def _rules_panel() -> None:
    with st.expander("📖 Stock Analysis Workflow 1 — how this screen works", expanded=True):
        st.markdown(
            """
Aligned with [`docs/Stock_Analysis_Workflow_1.md`](docs/Stock_Analysis_Workflow_1.md)
(Basic → Advance course notes). Educational only — not affiliated with any course provider.

### STEP 0 — Categorize first (always)
| Sales + profit growth (Screener compounded) | Category |
|---|---|
| **≥15% and ≥15%** | **Fast Grower** → Workflow A |
| **~10–15%** | **Stalwart** → Workflow B |
| At/below ~GDP (~7%) | **Slow Grower** (usually prefer FD) |
| Demand/supply, no pricing power | **Cyclical** |
| Distressed + recovery signs | **Turnaround** (manual) |

### WORKFLOW A — Fast Growers
1. Confirm compounded sales & profit ≥15% on Screener P&L  
2. Identify growth drivers (AR / presentations) — *manual*  
3. Future growth (concalls / guidance) — *manual*  
4. Valuation: **PE vs historical median** + **PEG** (PEG &lt; 1 buy · =1 fair · &gt; 1 avoid)  
   → use the in-app **Valuation Rulebook** for discounted-PE / forward models  
5. Story building (mgmt / Glassdoor / risks) — *manual via research links*

### SHARED — Quick-Fire Numbers Checklist (final pass)
Sales & profit CAGR · OPM trend · interest reducing YoY · tax caution if falling · net profit YoY  
(+ Google scam check via link — not automated)
"""
        )
        st.page_link(
            VALUATION_RULEBOOK_PAGE,
            label="Open Valuation Rulebook (discounted PE / forward model)",
            icon="🧮",
        )
        st.markdown("**Key websites/tools**")
        for name, use in RESEARCH_TOOLS:
            st.markdown(f"- **{name}** — {use}")
        st.code(
            "\n".join(
                [
                    "-- STEP 0",
                    "sales_3Y >= 15 AND profit_3Y >= 15  => Fast Grower",
                    "sales_3Y, profit_3Y in [10,15)     => Stalwart",
                    "both < ~7%                         => Slow Grower",
                    "",
                    "-- WORKFLOW A valuation",
                    "PEG = PE / profit_3Y_growth",
                    "OR current_PE <= FY_median_PE (PE chart)",
                    "",
                    "-- Quick-Fire (auto)",
                    "OPM stable/up; interest YoY down; net profit YoY > 0",
                ]
            ),
            language="sql",
        )


def _story_panel() -> None:
    with st.expander("📝 Story building checklist (manual — every serious candidate)", expanded=False):
        st.markdown(
            """
Order: **Management → Industry → Risk**

1. Google promoter + scam/fraud · YouTube interviews · promoter salary vs peers (Screener AR)  
2. Glassdoor **≥ 3.0**  
3. Sticky/repeat business? Segment mix?  
4. Market share / industry growth (Trendlyne, presentations, Value Pickr)  
5. Credit ratings + risk factors on Screener  
6. Banks: NPA + ROA  
7. Write a one-paragraph story before you buy
"""
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
                help="Start with Curated or Nifty 50 — Screener + PE history is slow.",
            )
        with c2:
            st.markdown("#### Workflow A valuation")
            st.page_link(
                VALUATION_RULEBOOK_PAGE,
                label="Valuation Rulebook",
                icon="🧮",
                help="Forward EPS x P/E and discounted fair value (My Learning).",
            )
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
            "Portfolio rules from workflow: avoid tiny mcaps (₹100–500 Cr floor); "
            "~15–20 stocks; max ~5% per name. Turnaround = manual research only."
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
        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits), "mode": mode},
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
        st.info("👆 Start with **STEP 0 — Categorize**, then run **WORKFLOW A** on Fast Growers.")
        return

    if not results:
        st.warning(
            "No matches. Try **STEP 0**, lower min mcap / Quick-Fire, or **Curated / Nifty 50**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    default_rank = (
        "vol_ratio"
        if last_mode == "volume_spike"
        else ("checklist" if last_mode == "workflow_a_fast" else "score")
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

    # Category counts for STEP 0
    if last_mode == "step0_categorize":
        cats = {}
        for r in results:
            cats[r.category] = cats.get(r.category, 0) + 1
        st.markdown("#### STEP 0 — category mix")
        cols = st.columns(min(len(cats), 6) or 1)
        for i, (cat, n) in enumerate(sorted(cats.items(), key=lambda x: -x[1])):
            cols[i % len(cols)].metric(cat, n)

    st.success(
        f"**{len(results)}** matches · {SCAN_MODES.get(last_mode, last_mode)} · "
        f"{last_uni} · scanned {scan_at or '—'}"
    )

    rows = []
    for i, r in enumerate(results, start=1):
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

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
    )

    if last_mode != "volume_spike" and results:
        st.markdown("#### P/E history (top match) — Workflow A step 4")
        top = results[0]
        render_pe_history_panel(
            display_ticker=top.ticker,
            raw_ticker=top.raw_ticker,
            max_pe_hint=float(top.fy_median_pe) if top.fy_median_pe else None,
            key_prefix=f"{key}_pehist",
        )

    with st.expander("Quick-Fire + next steps (per stock)", expanded=False):
        for r in results[:25]:
            st.markdown(
                f"**{r.label}** ({r.category}) — {r.verdict}  \n"
                f"QF {r.checklist_score}/{r.checklist_max}: {' · '.join(r.checklist_flags[:5])}  \n"
                f"*{r.next_steps}*"
            )

    st.caption(
        "Source: Stock Analysis Workflow 1. Quant gates from Screener.in; "
        "story / Glassdoor / concalls are manual. Not investment advice."
    )
