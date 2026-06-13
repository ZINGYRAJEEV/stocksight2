"""Volume-Led Market Share Capture — sector-wise fundamental screener UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from quality_gate import quality_gate_column_config
from scan_history_store import append_scan_record
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
)
from volume_led_screener import (
    META,
    MONTHLY_RSI_ENTRY,
    MONTHLY_RSI_PHASES,
    RANK_BY_OPTIONS,
    SECTOR_BUCKETS,
    SECTOR_RULES_TEXT,
    BaseScreenThresholds,
    MonthlyRSIFilters,
    SCAN_SOURCES,
    SectorOverlayThresholds,
    group_results_by_sector,
    result_to_row,
    scan_volume_led,
    sort_results_dataframe,
    sort_volume_led_results,
)


def _rules_panel() -> None:
    with st.expander("📖 Strategy & screener rules (sector-wise)", expanded=True):
        st.markdown(
            """
**Volume-Led Market Share Capture** — spot structural share gain *before* the balance sheet fully reflects it.

Operating leverage kicks in when sales volume surges while fixed costs stay flat: profits can compound faster than revenue.

**3-step workflow**
1. **Base screen** — narrow 5,000+ names to ~30–40 high-growth candidates (rules below).
2. **Monthly disclosures** — check NSE/BSE *Monthly Business Update* / SIAM volumes in the 1st week of each month.
3. **Trailing momentum** — track market-share % for two consecutive quarters before the crowd prices it in.
"""
        )
        tab_base, tab_auto, tab_bfsi, tab_cap, tab_fmcg = st.tabs(
            list(SECTOR_BUCKETS.values()),
        )
        panels = [tab_base, tab_auto, tab_bfsi, tab_cap, tab_fmcg]
        keys = list(SECTOR_BUCKETS.keys())
        for tab, key in zip(panels, keys):
            with tab:
                st.markdown(f"**{SECTOR_BUCKETS[key]}**")
                for rule in SECTOR_RULES_TEXT[key]:
                    st.markdown(f"- {rule}")
                if key == "generic":
                    st.code(
                        "\n".join(
                            [
                                "Sales growth 3Years > 15% AND",
                                "Sales growth 1Year > Sales growth 3Years AND",
                                "Quarterly Sales Variant YoY > 15% AND",
                                "Profit growth 3Years > 20% AND",
                                "Quarterly Profit Variant YoY > Quarterly Sales Variant YoY AND",
                                "ROCE > 20% AND",
                                "Debt to equity < 0.5 AND",
                                "Market Capitalization > 500 Cr",
                            ]
                        ),
                        language="sql",
                    )
        st.caption(
            "Yahoo Finance proxies — not identical to Screener.in quarterly fields. "
            "Cross-check growth, ROCE, and sector metrics on filings before investing."
        )

    with st.expander("📊 Monthly RSI momentum — multi-bagger framework", expanded=False):
        st.markdown(
            f"""
**Thesis:** On the **monthly chart**, RSI ≥ **{MONTHLY_RSI_ENTRY:.0f}** marks the start of a major bullish expansion —
not a sell signal. Treat **70 as the floor**: hold while monthly RSI stays above 70.

| RSI range | Expected performance | Growth phase |
|-----------|---------------------|--------------|
| **70 – 85** | Min ~1x (100%) | Initial momentum surge |
| **85 – 90** | Min ~3x | Exponential expansion |
| **90 – 94** | Up to ~10x | Peak multi-bagger territory |

**Entry:** Monthly RSI crossing **70** (~**73** confirmed). **Exit discipline:** only when monthly RSI **breaks below 70** —
avoid exiting on small gains while momentum is intact.

*Case refs from the framework: entry ~RSI 73 → ~2x by RSI 85 → ~6–7x by RSI 93 (e.g. Zen Technologies-style 10x journeys).*
"""
        )
        st.dataframe(
            pd.DataFrame(MONTHLY_RSI_PHASES),
            use_container_width=True,
            hide_index=True,
        )


def render_volume_led_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _rules_panel()

    key = "vlm"
    session_key = f"{key}_results"

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
        with c1:
            st.markdown("#### Universe")
            uni_key = f"{key}_universe"
            nse_sources = [s for s in SCAN_SOURCES if "NSE" in s or "Curated" in s]
            ensure_session_choice(uni_key, nse_sources, nse_sources[0])
            universe = st.selectbox(
                "Stock universe (NSE)",
                nse_sources,
                key=uni_key,
                help="Start with Curated or Nifty 200; Nifty 500 takes several minutes.",
            )
            sector_key = f"{key}_sector"
            sector_options = ["all"] + list(SECTOR_BUCKETS.keys())
            sector_labels = ["All sectors (grouped)"] + list(SECTOR_BUCKETS.values())
            ensure_session_choice(sector_key, sector_options, "all")
            sector_pick = st.selectbox(
                "Sector focus",
                sector_options,
                format_func=lambda x: sector_labels[sector_options.index(x)],
                key=sector_key,
            )
            require_overlay = st.checkbox(
                "Require sector overlay pass",
                value=False,
                key=f"{key}_overlay",
                help="When on, non-generic sectors must also pass their extra rules.",
            )
        with c2:
            st.markdown("#### Base screen thresholds")
            min_s3 = st.slider("Min sales growth 3Y %", 5.0, 40.0, 15.0, 1.0, key=f"{key}_s3")
            min_qs = st.slider("Min qtr sales var %", 5.0, 50.0, 15.0, 1.0, key=f"{key}_qs")
            min_p3 = st.slider("Min profit growth 3Y %", 5.0, 60.0, 20.0, 1.0, key=f"{key}_p3")
            min_roce = st.slider("Min ROCE %", 10.0, 40.0, 20.0, 0.5, key=f"{key}_roce")
            max_de = st.slider("Max debt/equity", 0.0, 1.5, 0.5, 0.05, key=f"{key}_de")
            min_mcap = st.slider("Min market cap (₹ Cr)", 100.0, 5000.0, 500.0, 50.0, key=f"{key}_mcap")
        with c3:
            st.markdown("#### Sector overlay thresholds")
            auto_s1 = st.slider("Auto — min sales 1Y %", 10.0, 35.0, 18.0, 1.0, key=f"{key}_auto_s1")
            auto_inv = st.slider("Auto — min inventory turnover", 4.0, 20.0, 10.0, 0.5, key=f"{key}_auto_inv")
            bfsi_roa = st.slider("BFSI — min ROA %", 0.5, 3.0, 1.5, 0.1, key=f"{key}_bfsi_roa")
            bfsi_pb = st.slider("BFSI — max P/B", 0.5, 5.0, 2.5, 0.1, key=f"{key}_bfsi_pb")
            cap_s3 = st.slider("Capital goods — min sales 3Y %", 10.0, 40.0, 20.0, 1.0, key=f"{key}_cap_s3")
            fmcg_opm = st.slider("FMCG — min OPM %", 5.0, 25.0, 12.0, 0.5, key=f"{key}_fmcg_opm")

    with st.container(border=True):
        st.markdown("#### Monthly RSI momentum (monthly chart)")
        m1, m2, m3 = st.columns([1.2, 1, 1.8])
        with m1:
            require_rsi70 = st.checkbox(
                f"Require monthly RSI ≥ {MONTHLY_RSI_ENTRY:.0f}",
                value=False,
                key=f"{key}_rsi70",
                help="Filter to high-momentum names only — monthly RSI(14) on Yahoo monthly bars.",
            )
        with m2:
            min_rsi = st.slider(
                "Min monthly RSI",
                50.0,
                94.0,
                MONTHLY_RSI_ENTRY,
                1.0,
                key=f"{key}_min_rsi",
                disabled=not require_rsi70,
            )
        with m3:
            st.caption(
                f"**70 floor rule:** hold while monthly RSI stays ≥ {MONTHLY_RSI_ENTRY:.0f}. "
                "Rank results by **Monthly RSI** to surface peak multi-bagger zone names first."
            )

    render_watchlist_panel(f"{key}_wl")

    scan_progress = st.empty()
    run = st.button("▶  SCAN NOW", use_container_width=True, key=f"{key}_scan")
    st.caption(
        "Use **Nifty 200** or **Curated** first. Results are grouped by sector bucket after the scan."
    )

    base_thr = BaseScreenThresholds(
        min_sales_growth_3y_pct=min_s3,
        min_qtr_sales_var_pct=min_qs,
        min_profit_growth_3y_pct=min_p3,
        min_roce_pct=min_roce,
        max_debt_equity=max_de,
        min_market_cap_cr=min_mcap,
    )
    sector_thr = SectorOverlayThresholds(
        auto_min_sales_1y_pct=auto_s1,
        auto_min_inventory_turnover=auto_inv,
        bfsi_min_roa_pct=bfsi_roa,
        bfsi_max_price_to_book=bfsi_pb,
        capital_min_sales_3y_pct=cap_s3,
        fmcg_min_opm_pct=fmcg_opm,
    )
    monthly_rsi_thr = MonthlyRSIFilters(
        require_above_floor=require_rsi70,
        min_monthly_rsi=min_rsi,
    )

    if run:
        prog = scan_progress.progress(0, text="Initialising…")

        def cb(i, t, s):
            prog.progress(int(i / max(t, 1) * 100), text=f"Fetching {s}… ({i}/{t})")

        hits = scan_volume_led(
            universe,
            base_thr=base_thr,
            sector_thr=sector_thr,
            monthly_rsi_thr=monthly_rsi_thr,
            sector_filter=sector_pick,
            require_sector_overlay=require_overlay,
            progress_cb=cb,
        )
        st.session_state[session_key] = hits
        st.session_state[f"{session_key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{session_key}_universe"] = universe
        st.session_state[f"{session_key}_sector"] = sector_pick

        try:
            append_scan_record(
                "volume_led_growth",
                universe,
                [r.raw_ticker for r in hits],
                meta={"matches": len(hits), "sector": sector_pick},
            )
        except Exception:
            pass
        try:
            metrics = [(r.ticker, r.raw_ticker, float(r.price), None) for r in hits]
            notify_watchlist_alerts_from_metrics(metrics, META["title"])
        except Exception:
            pass

        prog.empty()
        scan_progress.empty()

    results = st.session_state.get(session_key)
    scan_at = st.session_state.get(f"{session_key}_at")
    last_uni = st.session_state.get(f"{session_key}_universe", universe)
    last_sector = st.session_state.get(f"{session_key}_sector", sector_pick)

    if results is None:
        st.info("👆 Pick universe and thresholds, then click **SCAN NOW**.")
        return

    if not results:
        st.warning(
            "No names passed with current Yahoo data and filters. "
            "Try **Nifty 200**, relax base thresholds, or turn off **Require sector overlay pass**."
        )
        return

    rank_key = f"{key}_rank"
    rank_choices = list(RANK_BY_OPTIONS.keys())
    ensure_session_choice(rank_key, rank_choices, "momentum")
    rank_by = st.radio(
        "Rank results by",
        rank_choices,
        format_func=lambda x: RANK_BY_OPTIONS[x],
        horizontal=True,
        key=rank_key,
        help=(
            "**Volume momentum** = sales/profit acceleration score (default screener rule). "
            "**vs 200-DMA %** = price extension above 200-day average (trend strength). "
            "**Monthly RSI** = monthly-chart RSI(14) — highest multi-bagger phase first. "
            "**StockSight composite** / **Gate score** = standard StockSight quality ranking after enrich."
        ),
    )
    results = sort_volume_led_results(results, rank_by=rank_by)

    grouped = group_results_by_sector(results, rank_by=rank_by)
    non_empty = {k: v for k, v in grouped.items() if v}
    rank_label = RANK_BY_OPTIONS.get(rank_by, rank_by)
    st.success(
        f"**{len(results)}** match(es) · {last_uni}"
        + (f" · {scan_at}" if scan_at else "")
        + (f" · focus: {SECTOR_BUCKETS.get(last_sector, last_sector)}" if last_sector != "all" else "")
        + f" · ranked by **{rank_label}**"
    )

    col_cfg_base = {
        "Momentum": st.column_config.NumberColumn(format="%.1f"),
        "Monthly RSI": st.column_config.NumberColumn(format="%.1f"),
        "RSI prev": st.column_config.NumberColumn(format="%.1f"),
        "RSI 24m peak": st.column_config.NumberColumn(format="%.1f"),
        "RSI phase": st.column_config.TextColumn("RSI phase", width="medium"),
        "RSI target band": st.column_config.TextColumn("RSI target band", width="medium"),
        "RSI signal": st.column_config.TextColumn("RSI signal", width="medium"),
        "Above 70 floor": st.column_config.TextColumn(width="small"),
        "Crossed 70": st.column_config.TextColumn(width="small"),
        "vs 200-DMA %": st.column_config.NumberColumn(format="%+.2f"),
        "200 DMA": st.column_config.NumberColumn(format="%.2f"),
        "Composite": st.column_config.NumberColumn(format="%.1f"),
        "Gate score": st.column_config.ProgressColumn("Gate score", min_value=0, max_value=100, format="%d"),
        "Sales 1Y %": st.column_config.NumberColumn(format="%.1f"),
        "Sales 3Y %": st.column_config.NumberColumn(format="%.1f"),
        "Qtr sales %": st.column_config.NumberColumn(format="%.1f"),
        "Profit 3Y %": st.column_config.NumberColumn(format="%.1f"),
        "Qtr profit %": st.column_config.NumberColumn(format="%.1f"),
        "ROCE %": st.column_config.TextColumn("ROCE %"),
        "D/E": st.column_config.NumberColumn(format="%.3f"),
        "ROA %": st.column_config.NumberColumn(format="%.2f"),
        "P/B": st.column_config.NumberColumn(format="%.2f"),
        "OPM %": st.column_config.NumberColumn(format="%.1f"),
        "ROE %": st.column_config.NumberColumn(format="%.1f"),
        "Inv turnover": st.column_config.NumberColumn(format="%.1f"),
        "Raw": None,
        "Yahoo Finance": st.column_config.LinkColumn(display_text="Yahoo ↗"),
        "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
        "Moneycontrol": st.column_config.LinkColumn(display_text="MC ↗"),
        "TradingView": st.column_config.LinkColumn(display_text="TV ↗"),
        **quality_gate_column_config(),
    }

    def _render_sector_table(bucket_key: str, rows: list) -> None:
        if not rows:
            st.caption("No matches in this sector bucket for current filters.")
            return
        st.caption(" · ".join(SECTOR_RULES_TEXT.get(bucket_key, [])[:3]) + " …")
        ordered = (
            sort_volume_led_results(rows, rank_by=rank_by)
            if rank_by in ("momentum", "ma200", "monthly_rsi")
            else rows
        )
        data = [result_to_row(r, i) for i, r in enumerate(ordered, start=1)]
        df = pd.DataFrame(data)
        df = prepare_scan_results_df(
            df,
            universe_name=last_uni,
            cache_key_prefix=f"{key}_{bucket_key}",
            raw_ticker_col="Raw",
            apply_stock_sight=True,
            sort_by_gate=(rank_by == "gate"),
        )
        if rank_by in ("composite", "gate"):
            df = sort_results_dataframe(df, rank_by)
        col_cfg = filter_column_config(df, col_cfg_base)
        render_clickable_scan_table(
            df,
            key_prefix=f"{key}_{bucket_key}",
            universe_name=last_uni,
            column_config=col_cfg,
            height=min(480, 48 + len(df) * 36),
        )

    if last_sector != "all":
        _render_sector_table(last_sector, results)
    else:
        tab_all, *sector_tabs = st.tabs(
            ["All matches"] + [SECTOR_BUCKETS[k] for k in SECTOR_BUCKETS if k != "generic"]
        )
        with tab_all:
            ordered = (
                sort_volume_led_results(results, rank_by=rank_by)
                if rank_by in ("momentum", "ma200", "monthly_rsi")
                else results
            )
            all_rows = [result_to_row(r, i) for i, r in enumerate(ordered, start=1)]
            df_all = pd.DataFrame(all_rows)
            df_all = prepare_scan_results_df(
                df_all,
                universe_name=last_uni,
                cache_key_prefix=f"{key}_all",
                raw_ticker_col="Raw",
                apply_stock_sight=True,
                sort_by_gate=(rank_by == "gate"),
            )
            if rank_by in ("composite", "gate"):
                df_all = sort_results_dataframe(df_all, rank_by)
            col_cfg = filter_column_config(df_all, col_cfg_base)
            render_clickable_scan_table(
                df_all,
                key_prefix=f"{key}_all",
                universe_name=last_uni,
                column_config=col_cfg,
                height=min(520, 48 + len(df_all) * 36),
            )

        bucket_keys = [k for k in SECTOR_BUCKETS if k != "generic"]
        for tab, bkey in zip(sector_tabs, bucket_keys):
            with tab:
                st.markdown(f"**{len(non_empty.get(bkey, []))}** names · {SECTOR_BUCKETS[bkey]}")
                _render_sector_table(bkey, grouped.get(bkey, []))

        with st.expander("Generic bucket (base screen only — unclassified sector)", expanded=False):
            _render_sector_table("generic", grouped.get("generic", []))

    csv_ordered = (
        sort_volume_led_results(results, rank_by=rank_by)
        if rank_by in ("momentum", "ma200", "monthly_rsi")
        else results
    )
    csv_rows = [result_to_row(r, i) for i, r in enumerate(csv_ordered, start=1)]
    st.download_button(
        "⬇ Download results CSV",
        pd.DataFrame(csv_rows).to_csv(index=False).encode("utf-8"),
        file_name=f"stocksight_volume_led_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"{key}_dl",
    )

    st.markdown("---")
    st.markdown(
        """
**Next steps (manual)**
- **Monthly RSI:** confirm on TradingView monthly chart — hold above **70 floor**; do not exit on overbought alone.
- **Auto:** SIAM monthly volumes + exchange disclosures on the 1st of the month.
- **BFSI:** RBI credit growth + provisional loan-book updates (~15 days before results).
- **Capital goods:** order-book / book-to-bill in investor presentations.
- **FMCG/Retail:** same-store sales (SSSG) in quarterly updates.
"""
    )
    st.caption("⚠️ Educational only — Yahoo proxies ≠ Screener.in. Verify before investing.")
