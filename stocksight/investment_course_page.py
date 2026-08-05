"""Investment Course Screener — Streamlit UI (FF Basic→Advance notes)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from investment_course_screener import (
    META,
    RANK_BY_OPTIONS,
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


def _rules_panel() -> None:
    with st.expander("📖 How this screen works (course rules)", expanded=True):
        st.markdown(
            """
Inspired by **Basic → Advance** investment course notes (Lynch-style categories).
Educational only — not affiliated with any course provider.

| Category | Rule |
|----------|------|
| **Fast Grower** | Sales 3Y **and** profit 3Y CAGR **≥ 15%** (Screener compounded) |
| **Stalwart** | Both growth in **10–15%**; buy when P/E **≤ FY median** |
| **Slow Grower** | Both &lt; ~7% (GDP proxy) — prefer fixed deposit |
| **Cyclical** | Sector keywords (cement, paper, steel, agri, cables, MDF…) |
| **PEG** | PE ÷ profit growth 3Y — **&lt; 1 buy**, ≈1 fair, **&gt; 1 expensive** |
| **Volume spike** | 1w vol &gt; 5× 1y avg **and** 1w return &gt; 5% **and** mcap &gt; 50 Cr |

**Data:** Screener.in compounded sales/profit + Stock P/E; FY median from PE history;
Yahoo for volume/returns. Build a **story** (mgmt, industry, risks) before buying.
"""
        )
        st.code(
            "\n".join(
                [
                    "-- Fast Grower buy",
                    "sales_3Y >= 15 AND profit_3Y >= 15 AND PEG <= 1 AND mcap >= 500",
                    "",
                    "-- Stalwart buy",
                    "sales_3Y in [10,15) AND profit_3Y in [10,15)",
                    "AND current_PE <= FY_median_PE",
                    "",
                    "-- Volume spike (Ch.10)",
                    "avg_vol_1w > avg_vol_1y * 5 AND return_1w > 5 AND mcap > 50",
                ]
            ),
            language="sql",
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

    key = "invc"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"

    mode_key = f"{key}_mode"
    mode_ids = list(SCAN_MODES.keys())
    ensure_session_choice(mode_key, mode_ids, "buy_candidates")
    mode = st.radio(
        "Scan mode",
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
            st.markdown("#### Valuation gates")
            max_peg = st.slider("Max PEG (Fast Grower)", 0.5, 2.0, 1.0, 0.05, key=f"{key}_peg")
            max_pct = st.slider(
                "Max vs FY median % (Stalwart)",
                -30.0,
                5.0,
                0.0,
                1.0,
                key=f"{key}_pct",
                help="0 = at or below FY median PE.",
            )
            min_fy = st.slider("Min FY PE points (Stalwart)", 2, 10, 3, 1, key=f"{key}_fy")
        with c3:
            st.markdown("#### Size & volume")
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 500.0, 50.0, key=f"{key}_mcap")
            vol_mcap = st.slider("Volume mode min mcap (₹ Cr)", 50.0, 1000.0, 50.0, 25.0, key=f"{key}_vmcap")
            vol_mult = st.slider("Volume multiple (1w vs 1y)", 2.0, 10.0, 5.0, 0.5, key=f"{key}_vmult")
            min_wret = st.slider("Min 1-week return %", 1.0, 20.0, 5.0, 0.5, key=f"{key}_wret")

    with st.container(border=True):
        min_roce = st.slider("Min ROCE % (0 = off)", 0.0, 30.0, 0.0, 1.0, key=f"{key}_roce")
        st.caption(
            "Turnaround / story building is qualitative (management change, con-calls) — "
            "use Screener links after the scan. Portfolio tip from notes: ~15–20 names; "
            "avoid tiny mcaps; max ~5% per name."
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
        need_pe_history=mode in ("buy_candidates", "stalwarts_discount", "classify_all"),
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
        st.info("👆 Pick mode and universe, then click **SCAN NOW**.")
        return

    if not results:
        st.warning(
            "No matches. Try **Classify all**, lower min mcap, raise max PEG, "
            "or use **Curated / Nifty 50**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    default_rank = "vol_ratio" if last_mode == "volume_spike" else "score"
    ensure_session_choice(rank_key, rank_choices, default_rank)
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_investment_course(results, rank_by=rank_by, mode=last_mode)

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
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "FY median P/E": st.column_config.NumberColumn(format="%.1f"),
            "vs median %": st.column_config.NumberColumn(format="%+.1f"),
            "PEG": st.column_config.NumberColumn(format="%.2f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "1w ret %": st.column_config.NumberColumn(format="%+.1f"),
            "Vol ratio": st.column_config.NumberColumn(format="%.1f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "PEG verdict": st.column_config.TextColumn(width="medium"),
            "Raw": None,
            "Notes": None,
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
            "Screener.in": st.column_config.LinkColumn(display_text="Screener ↗"),
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
        st.markdown("#### P/E history (top match)")
        top = results[0]
        render_pe_history_panel(
            display_ticker=top.ticker,
            raw_ticker=top.raw_ticker,
            max_pe_hint=float(top.fy_median_pe) if top.fy_median_pe else None,
            key_prefix=f"{key}_pehist",
        )

    with st.expander("Pass notes (per stock)", expanded=False):
        for r in results[:25]:
            st.markdown(
                f"**{r.label}** ({r.category}) — {r.verdict}: "
                f"{' · '.join(r.pass_notes)}"
            )

    st.caption(
        "Course-inspired rules using Screener.in CAGR and FY median P/E. "
        "Not investment advice. Cross-check annual reports, concalls, and Glassdoor."
    )
