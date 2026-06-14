"""Financially Free™ swing screener — Streamlit UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from financially_free_screener import (
    META,
    NIFTY_MONTHLY_ROC_LEN,
    NIFTY_ROC_SELL_ZONE,
    RANK_OPTIONS,
    SCAN_MODES,
    SECTOR_FOCUS_PRESETS,
    SMALLCAP_MONTHLY_ROC_LEN,
    SMALLCAP_ROC_SELL_ZONE,
    FinanciallyFreeFilters,
    fetch_market_cycle_snapshot,
    result_to_row,
    scan_financially_free,
    sort_ff_results,
)
from multibagger import SCAN_SOURCES
from quality_gate import quality_gate_column_config
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


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_market_cycle():
    return fetch_market_cycle_snapshot()


def _methodology_panels() -> None:
    with st.expander("📖 Financially Free™ methodology (summary)", expanded=True):
        st.markdown(
            """
**Core philosophy:** Equity **cash** over F&O · **Price = EPS × PE** (research EPS tailwinds; PE is sentiment).

**Momentum over value:** Buy **sector leaders** making new highs while the index is flat — not falling knives.

**Portfolio:** Concentrate in **5–10 stocks** · cap losses at **~10%** · rotate quickly when stops hit.

**Monthly ritual (1st weekend):** Review **ROC** on Nifty/Smallcap + **Nifty/Gold** ratio before adding risk.
"""
        )
        tab1, tab2, tab3, tab4 = st.tabs(
            ["VCP", "Sector leaders", "IPO / ESM", "Risk rules"],
        )
        with tab1:
            st.markdown(
                """
**Volatility Contraction Pattern (Minervini):** Each pullback in a base is **shallower** than the last;
volume **dries up** before a pivot breakout. This screener scores VCP algorithmically — confirm on chart.
"""
            )
        with tab2:
            st.markdown(
                """
**Sector leaders:** Stocks within ~8% of **52w high** with **RS vs Nifty**, **ROCE > 20%**, **ROE > 20%**
(Screener.in style). Examples from the framework: solar/power leaders in prior bull runs; **metal & mining**
(Rare Earth angle) flagged as an emerging theme.
"""
            )
        with tab3:
            st.markdown(
                """
**IPO base breakout:** Track recent listings on [Chittorgarh](https://www.chittorgarh.com/) —
enter when price breaks **listing-day high** after the base forms. **ESM-2** exits can unblock value
(manual check on exchange surveillance lists).
"""
            )
        with tab4:
            st.markdown(
                """
| Loss | Gain needed to recover |
|------|------------------------|
| 10% | ~11% |
| 20% | 25% |
| 50% | 100% |

**21-EMA rule:** Exit if **two consecutive closes** below 21-EMA; re-enter when price **reclaims** 21-EMA
(even 3–5% higher). Trailing stop uses the same line.
"""
            )


def _render_market_cycle() -> None:
    st.markdown("#### 📅 Market cycle (monthly)")
    if st.button("🔄 Refresh cycle data", key="ff_cycle_refresh"):
        _cached_market_cycle.clear()

    snap = _cached_market_cycle()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            f"Nifty ROC ({NIFTY_MONTHLY_ROC_LEN}m)",
            f"{snap.nifty_roc:+.1f}%" if snap.nifty_roc is not None else "—",
        )
        st.caption(snap.nifty_zone)
        st.caption(f"Sell caution near **{NIFTY_ROC_SELL_ZONE:.0f}**")
    with c2:
        st.metric(
            f"Smallcap ROC ({SMALLCAP_MONTHLY_ROC_LEN}m)",
            f"{snap.smallcap_roc:+.1f}%" if snap.smallcap_roc is not None else "—",
        )
        st.caption(snap.smallcap_zone)
        st.caption(f"Sell caution near **{SMALLCAP_ROC_SELL_ZONE:.0f}**")
    with c3:
        st.metric(
            "Nifty / Gold (GOLDBEES)",
            f"{snap.nifty_gold_ratio:.2f}" if snap.nifty_gold_ratio is not None else "—",
        )
        st.caption(snap.nifty_gold_signal)
    with c4:
        st.metric(
            "Ratio percentile (5y)",
            f"{snap.nifty_gold_pctile:.0f}%" if snap.nifty_gold_pctile is not None else "—",
        )
        st.caption("Low = equity favored · High = gold favored")
    st.caption(snap.cycle_summary)


def render_financially_free_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _methodology_panels()
    _render_market_cycle()

    key = "ff"
    session_key = f"{key}_results"
    nse_sources = [s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s]

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
        with c1:
            st.markdown("#### Universe & mode")
            ensure_session_choice(f"{key}_uni", nse_sources, nse_sources[0])
            universe = st.selectbox("Stock universe", nse_sources, key=f"{key}_uni")
            mode_keys = list(SCAN_MODES.keys())
            ensure_session_choice(f"{key}_mode", mode_keys, "combined")
            scan_mode = st.selectbox(
                "Scan mode",
                mode_keys,
                format_func=lambda x: SCAN_MODES[x],
                key=f"{key}_mode",
            )
            sector_keys = list(SECTOR_FOCUS_PRESETS.keys())
            sector_pick = st.selectbox(
                "Sector focus",
                sector_keys,
                format_func=lambda x: SECTOR_FOCUS_PRESETS[x],
                key=f"{key}_sector",
            )
        with c2:
            st.markdown("#### Quality (EPS × PE)")
            require_q = st.checkbox("Require ROCE & ROE", value=True, key=f"{key}_req_q")
            min_roce = st.slider("Min ROCE %", 10.0, 40.0, 20.0, 0.5, key=f"{key}_roce")
            min_roe = st.slider("Min ROE %", 10.0, 40.0, 20.0, 0.5, key=f"{key}_roe")
            max_below_hi = st.slider(
                "Max % below 52w high",
                2.0,
                25.0,
                8.0,
                0.5,
                key=f"{key}_below_hi",
                help="Sector leaders near highs — lower = closer to high.",
            )
            min_rs = st.slider("Min RS vs Nifty (pp)", -10.0, 20.0, 0.0, 0.5, key=f"{key}_rs")
        with c3:
            st.markdown("#### Technical & risk")
            min_vcp = st.slider("Min VCP score", 0, 70, 25, 5, key=f"{key}_vcp")
            min_trend = st.slider("Min trend passes", 3, 7, 5, 1, key=f"{key}_trend")
            require_21 = st.checkbox("Require above 21-EMA", value=False, key=f"{key}_21ema")
            stop_pct = st.slider("Planned stop-loss %", 5.0, 15.0, 10.0, 0.5, key=f"{key}_stop")

    render_watchlist_panel(f"{key}_wl")

    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan")
    st.caption(
        "Target **5–10 concentrated names** from results. Cross-check VCP bases and monthly ROC on TradingView."
    )

    flt = FinanciallyFreeFilters(
        scan_mode=scan_mode,
        min_roce_pct=min_roce,
        min_roe_pct=min_roe,
        require_roce_roe=require_q,
        max_pct_below_52w_high=max_below_hi,
        min_rs_vs_nifty_pp=min_rs,
        min_vcp_score=float(min_vcp),
        min_trend_pass=int(min_trend),
        require_above_21ema=require_21,
        sector_keyword=sector_pick,
        stop_loss_pct=stop_pct,
    )

    if run:
        prog = st.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {s}… ({i}/{t})")

        hits = scan_financially_free(universe, flt, progress_cb=cb)
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_uni"] = universe
        st.session_state[f"{session_key}_stop"] = stop_pct

        try:
            append_scan_record(
                "financially_free_swing",
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits), "mode": scan_mode},
            )
        except Exception:
            pass
        prog.empty()

    results = st.session_state.get(session_key)
    if results is None:
        st.info("👆 Configure filters and click **SCAN NOW**.")
        return

    rank_keys = list(RANK_OPTIONS.keys())
    ensure_session_choice(f"{key}_rank", rank_keys, "ff_score")
    rank_by = st.radio(
        "Rank by",
        rank_keys,
        format_func=lambda x: RANK_OPTIONS[x],
        horizontal=True,
        key=f"{key}_rank",
    )
    results = sort_ff_results(results, rank_by=rank_by)
    scan_at = st.session_state.get(f"{session_key}_at", "")
    last_uni = st.session_state.get(f"{session_key}_uni", universe)
    last_stop = st.session_state.get(f"{session_key}_stop", stop_pct)

    if not results:
        st.warning(
            "No matches — try **Nifty 200**, relax ROCE/ROE, widen distance from 52w high, "
            "or switch scan mode to **VCP swing**."
        )
        return

    st.success(
        f"**{len(results)}** match(es) · {last_uni} · {SCAN_MODES.get(scan_mode, scan_mode)}"
        + (f" · {scan_at}" if scan_at else "")
        + f" · top **5–10** for a concentrated book"
    )

    rows = [result_to_row(r, i, stop_pct=last_stop) for i, r in enumerate(results, start=1)]
    df = pd.DataFrame(rows)
    df = prepare_scan_results_df(
        df,
        universe_name=last_uni,
        cache_key_prefix=f"{key}_results",
        raw_ticker_col="Raw",
        apply_stock_sight=True,
    )

    col_cfg = filter_column_config(
        df,
        {
            "FF score": st.column_config.NumberColumn(format="%.1f"),
            "Price": st.column_config.NumberColumn(format="%.2f"),
            "PE": st.column_config.NumberColumn(format="%.2f"),
            "EPS": st.column_config.NumberColumn(format="%.2f"),
            "EPS growth %": st.column_config.NumberColumn(format="%.1f"),
            "ROCE %": st.column_config.NumberColumn(format="%.1f"),
            "ROE %": st.column_config.NumberColumn(format="%.1f"),
            "% below 52w high": st.column_config.NumberColumn(format="%.1f"),
            "RSI (14)": st.column_config.NumberColumn(format="%.1f"),
            "Monthly RSI": st.column_config.NumberColumn(format="%.1f"),
            "RS vs Nifty (pp)": st.column_config.NumberColumn(format="%+.2f"),
            "VCP score": st.column_config.NumberColumn(format="%.1f"),
            "Trend passes": st.column_config.NumberColumn(format="%d"),
            "21-EMA": st.column_config.NumberColumn(format="%.2f"),
            "vs 21-EMA %": st.column_config.NumberColumn(format="%+.2f"),
            f"Stop @ {int(last_stop)}%": st.column_config.NumberColumn(format="%.2f"),
            "Raw": None,
            "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
            **quality_gate_column_config(),
        },
    )

    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=col_cfg,
        height=min(560, 48 + len(df) * 38),
    )

    st.download_button(
        "⬇ Download CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"stocksight_ff_swing_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"{key}_dl",
    )

    st.markdown("---")
    st.markdown(
        """
**Research ritual:** RHP / investor deck / concall for EPS tailwinds · "
        "[Screener.in](https://www.screener.in/) for ROCE/ROE · "
        "[Chittorgarh](https://www.chittorgarh.com/) for IPO bases · TradingView for monthly ROC.
"""
    )
    st.caption("⚠️ Educational only — not SEBI-registered advice. Verify every setup on your chart.")
