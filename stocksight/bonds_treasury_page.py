"""Bonds & Treasury — Streamlit UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from bonds_treasury import (
    CREDIT_OPTIONS,
    DURATION_OPTIONS,
    META,
    RANK_BY_OPTIONS,
    RATE_MODE_OPTIONS,
    UNIVERSE_OPTIONS,
    BondsFilters,
    fetch_yield_curve_snapshot,
    result_to_row,
    scan_bonds_treasury,
    sort_bonds_results,
)
from scan_history_store import append_scan_record
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
from session_utils import deduplicate_scan_results


def _rules_panel() -> None:
    with st.expander("📖 How this screen works", expanded=True):
        st.markdown(
            """
**What you get**

| Sleeve | Data | Use |
|--------|------|-----|
| **US Treasury yields** | `^IRX` / `^FVX` / `^TNX` / `^TYX` | Rate levels & curve shape |
| **US Bond ETFs** | SHY, IEF, TLT, LQD, HYG… | Duration & credit proxies |
| **India Gilt / Bharat Bond** | GILT5YBEES, LTGILTBEES, EBBETF… | G-Sec / PSU bond **price** proxies |

**Rate regime**
- **Rising rates** → prefer ultra-short / short duration (less price risk).
- **Falling rates** → prefer long duration (price upside as yields fall).

**India note:** Yahoo does not publish auction G-Sec yields here — India names are **ETF prices**, not YTM.
Educational only — not investment advice.
"""
        )


def _render_curve_panel() -> None:
    with st.spinner("Loading US yield curve…"):
        try:
            snap = fetch_yield_curve_snapshot()
        except Exception as exc:
            st.warning(f"Could not load yield curve: {exc}")
            return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("3M (^IRX)", f"{snap.y_3m:.2f}%" if snap.y_3m is not None else "—")
    c2.metric("5Y (^FVX)", f"{snap.y_5y:.2f}%" if snap.y_5y is not None else "—")
    c3.metric("10Y (^TNX)", f"{snap.y_10y:.2f}%" if snap.y_10y is not None else "—")
    c4.metric("30Y (^TYX)", f"{snap.y_30y:.2f}%" if snap.y_30y is not None else "—")
    c5.metric(
        "10Y − 3M",
        f"{snap.spread_10y_3m:+.2f}%" if snap.spread_10y_3m is not None else "—",
    )
    st.caption(f"**Curve:** {snap.shape}")
    if snap.spread_30y_10y is not None:
        st.caption(f"30Y − 10Y spread: **{snap.spread_30y_10y:+.2f}%**")


def render_bonds_treasury_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    key = "bonds"
    session_key = f"{key}_results"

    st.markdown("#### US Treasury yield curve")
    _render_curve_panel()

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.1, 1.1, 1.0])
        with c1:
            st.markdown("#### Universe")
            uni_key = f"{key}_universe"
            ensure_session_choice(uni_key, list(UNIVERSE_OPTIONS), UNIVERSE_OPTIONS[0])
            universe = st.selectbox("Instrument set", list(UNIVERSE_OPTIONS), key=uni_key)
            rate_key = f"{key}_rate"
            rate_choices = list(RATE_MODE_OPTIONS.keys())
            ensure_session_choice(rate_key, rate_choices, "neutral")
            rate_mode = st.radio(
                "Rate regime",
                rate_choices,
                format_func=lambda x: RATE_MODE_OPTIONS[x],
                key=rate_key,
            )
        with c2:
            st.markdown("#### Duration & credit")
            durations = st.multiselect(
                "Duration buckets",
                list(DURATION_OPTIONS),
                default=list(DURATION_OPTIONS),
                key=f"{key}_dur",
            )
            credits = st.multiselect(
                "Credit",
                list(CREDIT_OPTIONS),
                default=list(CREDIT_OPTIONS),
                key=f"{key}_cred",
            )
        with c3:
            st.markdown("#### Filters")
            use_ret = st.checkbox("Min 1M return filter", value=False, key=f"{key}_use_ret")
            min_ret = st.slider("Min 1M return %", -10.0, 10.0, 0.0, 0.5, key=f"{key}_ret") if use_ret else None
            use_dd = st.checkbox("Min below 52w high", value=False, key=f"{key}_use_dd")
            min_dd = st.slider("Min below 52w %", 0.0, 25.0, 5.0, 1.0, key=f"{key}_dd") if use_dd else None
            min_vol = st.number_input(
                "Min avg volume (ETFs)",
                min_value=0,
                value=0,
                step=10000,
                key=f"{key}_vol",
                help="0 = no volume filter",
            )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN BONDS", use_container_width=True, key=f"{key}_scan", type="primary")

    flt = BondsFilters(
        universe=universe,
        durations=tuple(durations) if durations else DURATION_OPTIONS,
        credits=tuple(credits) if credits else CREDIT_OPTIONS,
        rate_mode=rate_mode,
        min_ret_1m_pct=min_ret,
        max_drawdown_52w_pct=min_dd,
        min_avg_volume=float(min_vol or 0),
    )

    if run:
        prog = scan_progress.progress(0, text="Scanning fixed income…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        hits = scan_bonds_treasury(filters=flt, progress_cb=cb)
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe
        try:
            append_scan_record(
                META["id"],
                universe,
                [r.symbol for r in hits],
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
        st.info("👆 Pick universe / rate regime, then click **SCAN BONDS**.")
        return

    if not results:
        st.warning("No instruments passed filters — widen duration/credit or clear return filters.")
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    ensure_session_choice(rank_key, rank_choices, "score")
    rank_by = st.radio(
        "Rank by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
    )
    results = sort_bonds_results(results, rank_by=rank_by)

    st.success(f"**{len(results)}** instruments · {last_uni} · scanned {scan_at or '—'}")

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
            "Last": st.column_config.NumberColumn(format="%.4f"),
            "1D %": st.column_config.NumberColumn(format="%+.2f"),
            "1W %": st.column_config.NumberColumn(format="%+.2f"),
            "1M %": st.column_config.NumberColumn(format="%+.2f"),
            "3M %": st.column_config.NumberColumn(format="%+.2f"),
            "YTD %": st.column_config.NumberColumn(format="%+.2f"),
            "Below 52w %": st.column_config.NumberColumn(format="%.1f"),
            "ETF yield %": st.column_config.NumberColumn(format="%.2f"),
            "Verdict": st.column_config.TextColumn(width="medium"),
            "Raw": None,
            "Notes": None,
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
        },
    )

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
    )

    with st.expander("Notes (per instrument)", expanded=False):
        for r in results[:25]:
            st.markdown(f"**{r.name}** ({r.symbol}): {' · '.join(r.notes) or r.verdict}")

    st.caption(
        "US yield indices show **yield %** in Last. ETF Last is **price**. "
        "India gilt ETFs are price proxies — not auction YTM. Educational only."
    )
