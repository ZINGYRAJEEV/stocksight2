"""Popular Screens hub — classic named filters for NSE universes (Yahoo data)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from popular_screens import (
    SCAN_SOURCES,
    SCREEN_REGISTRY,
    registry_by_id,
    scan_popular_screen,
)
from scan_history_store import append_scan_record
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_decision_matrix_legend,
    render_watchlist_panel,
    safe_set_page_config,
)


def _category_order() -> list[str]:
    seen: list[str] = []
    for s in SCREEN_REGISTRY:
        if s.category not in seen:
            seen.append(s.category)
    return seen


def _render_run_panel(key: str, reg: dict) -> None:
    screen_ids = [s.screen_id for s in SCREEN_REGISTRY if s.implemented]
    if not screen_ids:
        st.warning("No implemented screens.")
        return

    ensure_session_choice(f"{key}_screen", screen_ids, screen_ids[0])
    sid = st.session_state[f"{key}_screen"]
    idx = screen_ids.index(sid)

    def _screen_title(screen_id: str) -> str:
        meta_row = reg.get(screen_id) or registry_by_id().get(screen_id)
        return meta_row.title if meta_row else screen_id

    picked = st.selectbox(
        "Screen",
        screen_ids,
        index=idx,
        format_func=_screen_title,
    )
    st.session_state[f"{key}_screen"] = picked
    meta = reg.get(picked) or registry_by_id().get(picked)
    if meta is None:
        st.error("Unknown screen — pick another from the list.")
        return

    st.info(f"**{meta.icon} {meta.title}** — {meta.description}\n\n_{meta.fidelity}_")

    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            ensure_session_choice(f"{key}_uni", list(SCAN_SOURCES), SCAN_SOURCES[0])
            universe = st.selectbox("Universe", SCAN_SOURCES, key=f"{key}_uni")
        with c2:
            max_rows = st.slider("Max results", 10, 100, 50, 10, key=f"{key}_max")

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  RUN SCREEN", use_container_width=True, key=f"{key}_run")

    session_key = f"{key}_results_{picked}"

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"{s} ({i}/{t})")

        results, _ = scan_popular_screen(
            picked,
            universe,
            progress_cb=cb,
            max_results=int(max_rows),
        )
        st.session_state[session_key] = results
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        try:
            append_scan_record(
                f"popular_{picked}",
                universe,
                [r.raw_ticker for r in results],
                meta={"count": len(results)},
            )
        except Exception:
            pass
        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")

    if results is None:
        st.info("Click **RUN SCREEN** to scan the universe with this screen's rules.")
    elif not results:
        st.warning(
            "No matches — try **Nifty 500**, relax thresholds on a dedicated page (e.g. Multibagger), "
            "or review quotes on Yahoo Finance."
        )
    else:
        st.caption(f"**{len(results)}** result(s)" + (f" · {scan_at}" if scan_at else ""))
        rows = []
        for i, r in enumerate(results, start=1):
            rows.append(
                {
                    "S.No.": i,
                    "Name": r.ticker,
                    "Screen score": r.score,
                    "Price": r.price,
                    "CMP Rs.": r.price,
                    "PE Ratio": r.pe,
                    "P/E": r.pe,
                    "Mar Cap Rs.Cr.": r.market_cap_cr,
                    "RSI": r.rsi,
                    "Vol×": r.vol_ratio,
                    "ROCE %": r.roce_pct,
                    "Div Yld %": r.div_yield_pct,
                    "% vs 52w H": r.pct_from_52w_high,
                    "Note": r.note,
                    "Score": r.score,
                    "Yahoo Finance": r.links.get("Yahoo Finance", ""),
                    "Google Finance": r.links.get("Google Finance", ""),
                    "Moneycontrol": r.links.get("Moneycontrol", ""),
                    "TradingView": r.links.get("TradingView", ""),
                }
            )
        df = pd.DataFrame(rows)
        from ui_components import stock_sight_column_config

        col_cfg = filter_column_config(
            df,
            {
                **stock_sight_column_config(),
                "Screen score": st.column_config.NumberColumn("Screen score", format="%.1f"),
                "CMP Rs.": st.column_config.NumberColumn(format="%.2f"),
                "P/E": st.column_config.NumberColumn(format="%.1f"),
                "Mar Cap Rs.Cr.": st.column_config.NumberColumn(format="%.1f"),
                "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
                "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
                "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
                "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
            },
        )
        from ui_components import prepare_scan_results_df

        df = prepare_scan_results_df(
            df,
            universe_name="NSE",
            cache_key_prefix=f"{key}_{picked}",
        )
        render_clickable_scan_table(
            df,
            key_prefix=f"{key}_{picked}_results",
            universe_name="NSE",
            column_config=col_cfg,
            height=min(560, 48 + len(df) * 36),
        )
        st.download_button(
            "⬇ Download CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"stocksight_{picked}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key=f"{key}_dl",
        )
        render_decision_matrix_legend()


def render_popular_screens_page() -> None:
    safe_set_page_config(
        page_title="Popular Screens | StockSight",
        page_icon="📋",
        layout="wide",
    )
    inject_css()

    reg = registry_by_id()
    key = "ps"

    implemented_ids = [s.screen_id for s in SCREEN_REGISTRY if s.implemented]
    default_screen = "price_volume_action" if "price_volume_action" in implemented_ids else (implemented_ids[0] if implemented_ids else "")
    ensure_session_choice(f"{key}_screen", implemented_ids, default_screen)
    ensure_session_choice(f"{key}_view", ["catalog", "run"], "catalog")

    st.markdown("### 📋 Popular stock screens")
    page_audience_note(
        "Investors who already know classic screens (Magic Formula, Darvas, RSI oversold, dividend yield, etc.) "
        "and want a quick Yahoo-based pass on NSE universes.",
        "Browse 20+ named screens, open one, pick **Nifty 50** or **Nifty 500**, and run rules ranked by score. "
        "Some screens are proxies only—see fidelity notes in the catalog.",
    )
    st.caption(
        "Pick a screen in **Catalog** → **Open**, or use **Run screen**. Data via **Yahoo Finance**."
    )

    view = st.radio(
        "View",
        ["Catalog", "Run screen"],
        horizontal=True,
        index=1 if st.session_state[f"{key}_view"] == "run" else 0,
        label_visibility="collapsed",
    )
    st.session_state[f"{key}_view"] = "run" if view == "Run screen" else "catalog"

    if st.session_state[f"{key}_view"] == "catalog":
        st.markdown("#### Browse screens")
        cat_filter = st.selectbox(
            "Category",
            ["All"] + _category_order(),
            key=f"{key}_cat",
        )
        for s in SCREEN_REGISTRY:
            if cat_filter != "All" and s.category != cat_filter:
                continue
            status = "✅" if s.implemented else "⏳"
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(f"**{status} {s.icon} {s.title}**")
                    st.caption(s.description)
                    if s.fidelity != "Yahoo Finance proxy — confirm figures on Yahoo":
                        st.caption(f"_{s.fidelity}_")
                with c2:
                    if s.implemented and st.button("Open", key=f"{key}_pick_{s.screen_id}"):
                        st.session_state[f"{key}_screen"] = s.screen_id
                        st.session_state[f"{key}_view"] = "run"
                        st.rerun()
                    elif not s.implemented:
                        st.caption("Soon")

        if st.button("Go to Run screen →", key=f"{key}_goto_run", type="primary"):
            st.session_state[f"{key}_view"] = "run"
            st.rerun()
    else:
        if st.button("← Back to catalog", key=f"{key}_back_cat"):
            st.session_state[f"{key}_view"] = "catalog"
            st.rerun()

        picked_title = reg.get(st.session_state[f"{key}_screen"])
        if picked_title:
            st.caption(f"Selected: **{picked_title.icon} {picked_title.title}**")

        _render_run_panel(key, reg)

    st.markdown("---")
    st.caption(
        "⚠️ Educational only. Several screens are Yahoo proxies or not yet implemented "
        "(FII, quarterly streaks, capacity expansion)."
    )
