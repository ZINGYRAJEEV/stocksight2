"""High-profit archetype pages — curated moat/platform/duopoly watchlists with live technical scores."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from scan_history_store import append_scan_record

from high_profit import (
    ARCHETYPES,
    HighProfitScanFilters,
    SCAN_SOURCES,
    archetype_defaults,
    nav_title,
    scan_high_profit,
)
from screener import fetch_recent_quote_news
from high_profit_ui import (
    high_profit_detail_card,
    high_profit_header,
    high_profit_rank_table,
    no_high_profit_state,
)
from ui_components import (
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    render_decision_matrix_legend,
    render_watchlist_panel,
    safe_set_page_config,
)


def _criteria_html(archetype_id: str, pe_max: float, vol_min: float, rsi_range: tuple[int, int]) -> str:
    a = ARCHETYPES[archetype_id]
    pe_note = a.get("criteria_pe", f"≤ {pe_max:.0f}")
    return f"""
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>PE</b> {pe_note} · <b>Volume</b> ≥ {vol_min:.1f}× avg ·
<b>RSI</b> {rsi_range[0]} – {rsi_range[1]}<br>
<b>Signal</b> {a.get("signal", "BUY")} · <b>Timeframe</b> {a.get("timeframe", "Medium term")}<br>
<b>Risk tier</b> {a.get("risk_label", "—")} · table includes <b>Buy?</b> and <b>Precautions</b> per name
</div>
"""


def render_high_profit_page(archetype_id: str) -> None:
    a = ARCHETYPES[archetype_id]
    defaults = archetype_defaults(archetype_id)
    rsi_default = defaults.get("rsi_range", (50, 100))

    safe_set_page_config(
        page_title=f"{nav_title(archetype_id)} | StockSight",
        page_icon=a["emoji"],
        layout="wide",
    )
    inject_css()
    high_profit_header(archetype_id)
    if a.get("audience") and a.get("purpose"):
        page_audience_note(a["audience"], a["purpose"])

    key = f"hp_{archetype_id}"
    session_key = f"{key}_results"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
        with c1:
            st.markdown("#### Settings")
            scan_source = st.selectbox(
                "Stock Universe",
                SCAN_SOURCES,
                index=0,
                key=f"{key}_source",
                help="Curated watchlist scans all archetype names. Other options limit to names also in that index.",
            )
        with c2:
            st.markdown("#### Criteria")
            # Placeholder updated below after sliders exist
            criteria_slot = st.empty()
        with c3:
            st.markdown("#### Filters")
            pe_max = st.slider(
                "Max PE Ratio",
                5.0,
                300.0,
                float(defaults.get("pe_max", 100.0)),
                0.5,
                key=f"{key}_pe",
            )
            vol_min = st.slider(
                "Min Volume Spike (×avg)",
                0.5,
                10.0,
                float(defaults.get("vol_min", 1.2)),
                0.1,
                key=f"{key}_vol",
            )
            rsi_range = st.slider(
                "RSI Range (14)",
                0,
                100,
                (int(rsi_default[0]), int(rsi_default[1])),
                1,
                key=f"{key}_rsi",
            )

    criteria_slot.markdown(
        _criteria_html(archetype_id, pe_max, vol_min, rsi_range),
        unsafe_allow_html=True,
    )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan")
    st.caption(
        "Pick universe and thresholds, then scan. Progress appears in the bar above while each symbol is processed."
    )

    filters = HighProfitScanFilters(
        pe_max=pe_max,
        vol_min=vol_min,
        rsi_min=float(rsi_range[0]),
        rsi_max=float(rsi_range[1]),
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / t * 100), text=f"Scanning {s}… ({i}/{t})")

        hp_results = scan_high_profit(
            archetype_id,
            scan_source=scan_source,
            filters=filters,
            progress_cb=cb,
        )
        st.session_state[session_key] = hp_results
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y")
        st.session_state[f"{session_key}_source"] = scan_source
        try:
            syms_hp = [r.raw_ticker for r in hp_results]
            append_scan_record(
                f"high_profit_{archetype_id}",
                scan_source or "",
                syms_hp,
                meta={"matches": len(syms_hp)},
            )
        except Exception:
            pass
        try:
            metrics_hp = [
                (r.ticker, r.raw_ticker, float(r.price), float(r.rsi)) for r in hp_results
            ]
            notify_watchlist_alerts_from_metrics(metrics_hp, nav_title(archetype_id))
        except Exception:
            pass
        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_source = st.session_state.get(f"{session_key}_source", scan_source)

    if results is None:
        st.info("👆 Configure the panel above and click **SCAN NOW** to load ranked high-profit names.")
    elif not results:
        no_high_profit_state(archetype_id)
        if scan_source != "Curated watchlist":
            st.caption(
                f"No curated names in **{scan_source}** passed filters — try **Curated watchlist** or relax PE / volume / RSI."
            )
        else:
            st.caption("No names passed filters — lower Min Volume or widen RSI range.")
    else:
        src_note = f" · {last_source}" if last_source else ""
        st.caption(f"Showing {len(results)} match(es){src_note}")
        high_profit_rank_table(results, scan_at, archetype_id=archetype_id)
        render_decision_matrix_legend()
        st.markdown("---")
        st.markdown(f"### 📋 {len(results)} name(s) — Detail cards")
        view = st.radio(
            "View",
            ["Cards", "Table only"],
            horizontal=True,
            label_visibility="collapsed",
            key=f"{key}_view",
        )
        if view == "Cards":
            if len(results) <= 35:
                max_age = int(st.session_state.get("news_scan_max_age", 7))
                with st.spinner("Loading recent headlines (Yahoo + Google News)…"):
                    for r in results:
                        r.news_headlines = fetch_recent_quote_news(
                            r.raw_ticker, limit=3, max_age_days=max_age
                        )
            for rank, r in enumerate(results, start=1):
                high_profit_detail_card(r, rank)

    st.markdown("---")
    st.markdown(
        f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>{nav_title(archetype_id)} — active filters</div>
    <div style='margin-top:10px; color:#a3d8b8; font-size:0.92rem;'>
        Universe: <b>{scan_source}</b> · max PE ≤ {pe_max:.1f} · volume ≥ {vol_min:.1f}× avg ·
        RSI {rsi_range[0]}–{rsi_range[1]}.
    </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption("⚠️ Educational tooling only — not financial advice. Curated metadata is illustrative.")
