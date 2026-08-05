"""Healthy Below Median PE — Streamlit UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from below_median_pe_screener import (
    META,
    RANK_BY_OPTIONS,
    SCAN_SOURCES,
    BelowMedianPeFilters,
    result_to_row,
    scan_below_median_pe,
    sort_below_median_pe,
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
    with st.expander("📖 How this screen works", expanded=True):
        st.markdown(
            """
**Thesis:** A **healthy** company trading **below its own historical median P/E** may offer
mean-reversion value — the market is pricing it cheaper than its typical past multiple.

| Pillar | Check |
|--------|--------|
| **Discount** | Current P/E **below Mar FY median P/E** (default ≥ 5% cheaper) |
| **History** | At least **5** Mar FY P/E points (Screener EPS × Yahoo FY-end price) |
| **Health** | ROCE, profit growth 3Y, D/E, market cap |

**Data:** Screener.in consolidated EPS + Yahoo adjusted closes near 31 Mar each FY.
"""
        )
        st.code(
            "\n".join(
                [
                    "current_PE < FY_median_PE  (e.g. at least 5% below)",
                    "AND n_FY_PE_points >= 5",
                    "AND ROCE >= 15%",
                    "AND profit_growth_3Y >= 12%",
                    "AND D/E <= 1.0",
                    "AND market_cap >= 300 Cr",
                ]
            ),
            language="sql",
        )


def render_below_median_pe_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    key = "bmpe"
    render_screener_session_panel(key_prefix=f"{key}_screener")
    session_key = f"{key}_results"

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
                help="Start with Curated or Nifty 50 — full Nifty 500 is slow (Screener + Yahoo per name).",
            )
            min_fy = st.slider("Min Mar FY P/E points", 3, 12, 5, 1, key=f"{key}_fy")
        with c2:
            st.markdown("#### Discount vs history")
            max_pct = st.slider(
                "Max vs FY median %",
                -40.0,
                0.0,
                -5.0,
                1.0,
                key=f"{key}_pct",
                help="−5 means current P/E must be at least 5% below FY median.",
            )
            max_pe = st.slider("Soft max current P/E", 15.0, 80.0, 45.0, 1.0, key=f"{key}_maxpe")
        with c3:
            st.markdown("#### Health gates")
            min_roce = st.slider("Min ROCE %", 8.0, 35.0, 15.0, 0.5, key=f"{key}_roce")
            min_g3 = st.slider("Min profit growth 3Y %", 0.0, 40.0, 12.0, 1.0, key=f"{key}_g3")
            max_de = st.slider("Max debt/equity", 0.0, 2.0, 1.0, 0.05, key=f"{key}_de")
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 300.0, 50.0, key=f"{key}_mcap")

    with st.container(border=True):
        q1, q2 = st.columns(2)
        with q1:
            min_roe = st.slider("Min ROE % (if available)", 0.0, 30.0, 12.0, 0.5, key=f"{key}_roe")
            require_ttm = st.checkbox("Require TTM profit growth", value=False, key=f"{key}_ttm")
        with q2:
            min_ttm = st.slider("Min TTM profit growth %", 0.0, 40.0, 8.0, 1.0, key=f"{key}_ttm_v")
            st.caption("Median uses **Mar FY** P/Es only (excludes Current/TTM from the median bar).")

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan", type="primary")

    flt = BelowMedianPeFilters(
        min_fy_points=min_fy,
        max_pct_vs_median=max_pct,
        max_pe=max_pe,
        min_roce_pct=min_roce,
        min_roe_pct=min_roe,
        min_profit_growth_3y_pct=min_g3,
        min_profit_growth_ttm_pct=min_ttm,
        require_ttm_growth=require_ttm,
        max_debt_equity=max_de,
        min_market_cap_cr=min_mcap,
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        hits = scan_below_median_pe(universe, filters=flt, progress_cb=cb)
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe
        try:
            append_scan_record(
                META["id"],
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits)},
            )
        except Exception:
            pass
        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)

    if results is None:
        st.info("👆 Pick universe and thresholds, then click **SCAN NOW**.")
        return

    if not results:
        st.warning(
            "No names passed. Try **Curated** / **Nifty 50**, lower **Min ROCE**, "
            "or set **Max vs FY median %** closer to 0."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    ensure_session_choice(rank_key, rank_choices, "discount")
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_below_median_pe(results, rank_by=rank_by)

    st.success(f"**{len(results)}** matches · {last_uni} · scanned {scan_at or '—'}")

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
            "P/E now": st.column_config.NumberColumn(format="%.1f"),
            "FY median P/E": st.column_config.NumberColumn(format="%.1f"),
            "vs median %": st.column_config.NumberColumn(format="%+.1f"),
            "EPS ₹": st.column_config.NumberColumn(format="%.1f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "ROE %": st.column_config.NumberColumn(format="%.1f"),
            "Profit 3Y %": st.column_config.NumberColumn(format="%.1f"),
            "Profit TTM %": st.column_config.NumberColumn(format="%.1f"),
            "D/E": st.column_config.NumberColumn(format="%.2f"),
            "Price": st.column_config.NumberColumn(format="₹%.2f"),
            "Verdict": st.column_config.TextColumn(width="medium"),
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

    st.markdown("#### P/E history (selected / top match)")
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
                f"**{r.label}** — P/E {r.current_pe} vs median {r.fy_median_pe} "
                f"({r.pct_vs_median:+.1f}%): {' · '.join(r.pass_notes)}"
            )

    st.caption(
        "FY median P/E uses Mar FY points only. Current P/E from Screener Stock P/E / TTM. "
        "Educational only — not investment advice."
    )
