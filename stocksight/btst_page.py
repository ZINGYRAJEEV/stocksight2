"""BTST Screener — Buy Today, Sell Tomorrow (close-strength EOD scan)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from btst_screener import (
    META,
    BtstFilters,
    BtstTiming,
    btst_session_hint,
    btst_timing_schedule,
    scan_btst,
    universe_options,
)
from intraday import MARKET_LABEL, MARKETS, market_session_window
from intel_market_enrichment import enrich_btst_results
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
    stock_sight_overlay_column_config,
)

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")
CEST = ZoneInfo("Europe/Berlin")

_GRADE_STYLE = {
    "A": "background-color:#dcfce7;color:#166534;font-weight:700;",
    "B": "background-color:#fef9c3;color:#854d0e;font-weight:600;",
}

_LINK_COLUMNS = ("Yahoo Finance", "Google Finance", "Moneycontrol", "TradingView", "MarketWatch")

_TV_SENTIMENT_EMOJI = {
    "Bullish": "🟢",
    "Mildly bullish": "🟢",
    "Bearish": "🔴",
    "Mildly bearish": "🔴",
    "Neutral": "⚪",
    "Mixed": "🟡",
    "—": "⚪",
}


def _link_column_config() -> dict:
    return {
        "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
        "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
        "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
        "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
        "MarketWatch": st.column_config.LinkColumn("MarketWatch", display_text="MW ↗"),
    }


def _rules_panel(market: str = "NSE", timing: BtstTiming | None = None) -> None:
    timing = timing or btst_timing_schedule(market)
    is_us = (market or "NSE").upper() == "US"
    mkt_label = "NYSE / NASDAQ" if is_us else "NSE"
    with st.expander("📖 BTST methodology & rules", expanded=True):
        st.markdown(
            f"""
**Edge:** Stocks that **close in the top quartile** of the day's range on **≥1.8× volume**
tend to continue into the **next morning**. Expectancy is small (~1%/trade) but repeatable with discipline.

| Phase | Your time (CEST/CET) | Market time | Rule |
|-------|----------------------|-------------|------|
| **Scan** | **{timing.scan_cest}** | {timing.scan_market} | Today's daily bar ({mkt_label}) |
| **Entry** | **{timing.entry_cest}** | {timing.entry_market} | Grade **A** (full) or **B** (half) |
| **Exit** | **{timing.exit_cest}** | {timing.exit_market} | Flat by **{timing.exit_deadline_cest}** |

**Grade A:** Score ≥ 70 · CPR ≥ 75% · Vol ≥ 1.8× · Green day · RSI 50–78

**Grade B:** Score ≥ 55 · CPR ≥ 60% · Vol ≥ 1.4×

**Skip BTST on:** expiry day, major macro events, exchange clarification names, weak closes.
"""
        )
        st.code(
            "\n".join(
                [
                    "CPR = (Close - Low) / (High - Low) × 100",
                    "Vol× = Today volume / 20-day average",
                    f"Target T1: +2% (book 40%) · T2: +3.5% (book 40%) · Runner: exit {timing.exit_deadline_cest}",
                    "Morning: Gap-up ≥1.5% → sell 50% at open",
                ]
            ),
            language="text",
        )


def _render_cest_schedule(timing: BtstTiming) -> None:
    flag = "🇺🇸 NYSE & NASDAQ" if timing.market == "US" else "🇮🇳 NSE"
    cest_lbl = datetime.now(tz=CEST).strftime("%Z")
    with st.container(border=True):
        st.markdown(f"#### 📅 Your BTST playbook · {flag}")
        st.caption(
            f"Times in **Europe/Berlin** ({cest_lbl} in summer · CET in winter) — "
            "updates when you change market."
        )
        lines = [
            "| Your time (CEST/CET) | Market time | Action |",
            "|----------------------|-------------|--------|",
        ]
        for cest, mkt, action in timing.schedule_rows:
            lines.append(f"| **{cest}** | {mkt} | {action} |")
        st.markdown("\n".join(lines))


def _results_df(results: list) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        tv_em = _TV_SENTIMENT_EMOJI.get(r.tv_sentiment, "⚪")
        tv_news = r.tv_news or "—"
        if len(tv_news) > 140:
            tv_news = tv_news[:140] + "…"
        rows.append(
            {
                "Rank": i,
                "Grade": r.grade,
                "Ticker": r.ticker,
                "Score": r.btst_score,
                "CPR %": r.cpr_pct,
                "Vol×": r.vol_ratio,
                "Day %": r.pct_vs_prev_close,
                "RSI": r.rsi,
                "vs MA20 %": r.pct_vs_ma20,
                "Price": r.price,
                "Stop": r.stop_price,
                "T1 %": r.target_t1_pct,
                "T2 %": r.target_t2_pct,
                "Entry": r.entry_window,
                "Sector": r.sector,
                "TV sentiment": f"{tv_em} {r.tv_sentiment}",
                "TV news": tv_news,
                "Morning exit": r.morning_rule[:90] + ("…" if len(r.morning_rule) > 90 else ""),
                "Notes": " · ".join(r.pass_notes[:3]),
                "Raw": r.raw_ticker,
                **{k: v for k, v in r.links.items()},
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    core = [
        "Rank", "Grade", "Ticker", "Score", "CPR %", "Vol×", "Day %", "RSI", "vs MA20 %",
        "Price", "Stop", "T1 %", "T2 %", "Entry", "Sector", "TV sentiment", "TV news",
        "Morning exit", "Notes",
    ]
    link_cols = [c for c in _LINK_COLUMNS if c in df.columns]
    tail = [c for c in df.columns if c not in core + link_cols + ["Raw"]]
    return df[core + link_cols + tail + ["Raw"]]


def _render_pick_card(r) -> None:
    st.markdown(f"#### {r.ticker} · Grade **{r.grade}** · Score **{r.btst_score:.0f}**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CPR (close strength)", f"{r.cpr_pct:.0f}%")
    c2.metric("Vol × 20D", f"{r.vol_ratio:.1f}")
    c3.metric("Day %", f"{r.pct_vs_prev_close:+.2f}%")
    c4.metric("RSI", f"{r.rsi:.1f}")

    sym = "$" if not r.raw_ticker.endswith((".NS", ".BO")) else "₹"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"{sym}{r.price:,.2f}")
    c2.metric("Stop", f"{sym}{r.stop_price:,.2f}")
    c3.metric("Day range", f"{sym}{r.day_low:,.2f} – {sym}{r.day_high:,.2f}")
    c4.metric("Prev close", f"{sym}{r.prev_close:,.2f}")

    st.success(f"**Entry:** {r.entry_window} · **T1** +{r.target_t1_pct}% · **T2** +{r.target_t2_pct}%")
    st.info(f"**Tomorrow morning:** {r.morning_rule}")
    if r.tv_news and r.tv_news != "—":
        tv_em = _TV_SENTIMENT_EMOJI.get(r.tv_sentiment, "⚪")
        st.markdown("**TradingView news**")
        st.caption(
            f"{tv_em} **Sentiment:** {r.tv_sentiment} · "
            f"Headlines: {r.tv_headline_sentiment} · **Rating:** {r.tv_rating}"
        )
        if r.tv_sentiment_note and r.tv_sentiment_note != "—":
            st.caption(r.tv_sentiment_note)
        for line in r.tv_news.split(" | "):
            if line.strip():
                st.markdown(f"- {line}")
    if r.pass_notes:
        st.caption(" · ".join(r.pass_notes))
    if r.links:
        lcols = st.columns(min(len(r.links), 4))
        for i, (name, url) in enumerate(r.links.items()):
            if url and i < len(lcols):
                with lcols[i]:
                    st.link_button(name, url, use_container_width=True)


def render_btst_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    key = "btst"
    session_results = f"{key}_results"
    session_stats = f"{key}_stats"

    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])

    m1, m2, m3 = st.columns([1.0, 1.0, 1.2])
    with m1:
        market = st.radio(
            "Market",
            MARKETS,
            format_func=lambda m: MARKET_LABEL.get(m, m),
            horizontal=True,
            key=f"{key}_market",
        )
    timing = btst_timing_schedule(market)
    with m2:
        cest_now = datetime.now(tz=CEST)
        cest_lbl = cest_now.strftime("%Z")
        st.metric("Your time", cest_now.strftime(f"%H:%M {cest_lbl}"))
        st.caption(f"BTST scan: **{timing.scan_cest}**")
    with m3:
        sess = market_session_window(market)
        st.metric("Market session", sess.get("window", "—"))
        st.caption(f"{sess.get('market_local_str', '')} · {sess.get('tip', '')}")

    _render_cest_schedule(timing)
    _rules_panel(market, timing)

    phase, hint = btst_session_hint(market)
    cest_lbl = datetime.now(tz=CEST).strftime("%Z")
    cest_now_str = datetime.now(tz=CEST).strftime(f"%d %b %Y %H:%M {cest_lbl}")
    if market == "US":
        mkt_now = datetime.now(tz=ET).strftime("%d %b %Y %H:%M ET")
    else:
        mkt_now = datetime.now(tz=IST).strftime("%d %b %Y %H:%M IST")
    now_lbl = f"{cest_now_str} · {mkt_now}"

    if phase == "BTST_WINDOW":
        st.success(f"**{now_lbl}** — {hint}")
    elif phase == "ENTRY_WINDOW":
        st.warning(f"**{now_lbl}** — {hint}")
    else:
        st.caption(f"**{now_lbl}** — {hint}")

    if market == "US":
        st.caption("US BTST uses **Yahoo Finance** (NYSE & NASDAQ via S&P 500 or liquid shortlist).")
    else:
        try:
            from breeze_data import breeze_configured, breeze_status_message

            if breeze_configured():
                st.caption(f"Data: **ICICI Breeze** · {breeze_status_message()}")
            else:
                st.caption("Data: **Yahoo Finance** (connect Breeze in sidebar for NSE-aligned OHLCV).")
        except ImportError:
            st.caption("Data: **Yahoo Finance**")

    render_watchlist_panel("btst_wl")

    uni_opts = universe_options(market)
    if market == "US":
        default_uni = next(
            (u for u in ("S&P 500 (broad, slow)", "Liquid US shortlist (~35)") if u in uni_opts),
            uni_opts[0],
        )
    else:
        default_uni = next(
            (u for u in ("Nifty 100 (medium)", "Nifty 500 (broad, slow)") if u in uni_opts),
            uni_opts[0],
        )

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.1, 1.0, 1.0])
        with c1:
            universe = st.selectbox("Universe", uni_opts, index=uni_opts.index(default_uni), key=f"{key}_uni")
            max_tickers = st.slider("Max tickers to scan", 50, 600, 600, 25, key=f"{key}_max")
            grade_a_only = st.checkbox("Grade A only", value=False, key=f"{key}_ga")
            include_tv_news = st.checkbox(
                "TradingView news after scan",
                value=True,
                key=f"{key}_tv",
                help="Fetches latest TradingView headlines for each Grade A/B pick.",
            )
        with c2:
            min_cpr_a = st.slider("Min CPR % (Grade A)", 65.0, 90.0, 75.0, 1.0, key=f"{key}_cpra")
            min_vol_a = st.slider("Min Vol× (Grade A)", 1.2, 3.0, 1.8, 0.1, key=f"{key}_vola")
            min_score_a = st.slider("Min score (Grade A)", 60.0, 85.0, 70.0, 1.0, key=f"{key}_sca")
        with c3:
            min_day_pct = st.slider("Min day % vs prev close", 0.5, 4.0, 1.5, 0.1, key=f"{key}_dpct")
            max_day_pct = st.slider("Max day % (avoid exhaustion)", 4.0, 12.0, 8.0, 0.5, key=f"{key}_xpct")
            if market == "US":
                data_src = "yahoo"
                st.caption("OHLCV: **Yahoo Finance** (NYSE / NASDAQ)")
            else:
                data_src = st.selectbox(
                    "OHLCV source",
                    ("auto", "breeze", "yahoo"),
                    format_func=lambda x: {
                        "auto": "Auto (Breeze if connected)",
                        "breeze": "Breeze only",
                        "yahoo": "Yahoo only",
                    }[x],
                    key=f"{key}_ds",
                )

        run = st.button("🌙 Run BTST scan", type="primary", key=f"{key}_run")

    if run:
        flt = BtstFilters(
            min_pct_change=float(min_day_pct),
            max_pct_change=float(max_day_pct),
            min_cpr_grade_a=float(min_cpr_a),
            min_vol_ratio_a=float(min_vol_a),
            min_score_a=float(min_score_a),
            max_tickers=int(max_tickers),
            grade_a_only=grade_a_only,
            data_source=data_src,
        )
        prog = st.progress(0.0, text="Starting BTST scan…")
        status = st.empty()

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(i / max(total, 1), text=f"Scanning {sym} ({i}/{total})…")

        with st.spinner("Scanning close strength + volume…"):
            results, stats = scan_btst(universe, flt, market=market, progress_cb=_cb)

        if include_tv_news and results:
            tv_prog = st.progress(0.0, text="Fetching TradingView news…")
            enrich_btst_results(results, market=market)
            tv_prog.progress(1.0, text=f"TradingView news loaded for {len(results)} picks")
            tv_prog.empty()

        prog.empty()
        status.empty()
        st.session_state[session_results] = results
        st.session_state[session_stats] = stats
        st.session_state[f"{key}_market_last"] = market
        append_scan_record(
            "btst",
            universe,
            [r.raw_ticker for r in results],
            meta={"grade_a": stats.grade_a, "market": market},
        )

    results = st.session_state.get(session_results) or []
    stats = st.session_state.get(session_stats)

    if not results and not run:
        st.info(
            f"Run a scan between **{timing.scan_cest}** "
            f"({timing.scan_market}) for best results. Uses today's daily bar."
        )
        return

    if stats:
        st.success(
            f"**{len(results)}** actionable (Grade A/B) · scanned **{stats.tickers_scanned}** · "
            f"A={stats.grade_a} B={stats.grade_b} · hard-reject **{stats.failed_hard}** · "
            f"{stats.scan_elapsed_sec:.0f}s"
        )

    if not results:
        st.warning("No Grade A/B names passed all rules. Loosen CPR/volume sliders or widen universe.")
        return

    df = _results_df(results)
    show = [c for c in df.columns if c != "Raw"]
    styler = df[show].style.apply(
        lambda col: [_GRADE_STYLE.get(str(v), "") for v in col],
        subset=["Grade"],
    )
    price_fmt = "$%.2f" if market == "US" else "₹%.2f"

    render_clickable_scan_table(
        df[show],
        styler=styler,
        key_prefix=key,
        market=market,
        apply_stock_sight=False,
        column_config={
            **_link_column_config(),
            **stock_sight_overlay_column_config(),
            "Grade": st.column_config.TextColumn("Grade", width="small"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "CPR %": st.column_config.NumberColumn(format="%.0f"),
            "Vol×": st.column_config.NumberColumn(format="%.1f"),
            "Day %": st.column_config.NumberColumn(format="%+.2f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "vs MA20 %": st.column_config.NumberColumn(format="%+.1f"),
            "Price": st.column_config.NumberColumn(format=price_fmt),
            "Stop": st.column_config.NumberColumn(format=price_fmt),
            "TV sentiment": st.column_config.TextColumn("TV sentiment", width="small"),
            "TV news": st.column_config.TextColumn("TV news", width="large"),
            "Morning exit": st.column_config.TextColumn(width="large"),
        },
        caption=(
            "Grade **A/B** only — sorted by grade then score. "
            "**TV news** = TradingView headlines · Click a row for chart · **Yahoo / TV ↗** open research links."
        ),
        show_gate_legend=False,
    )

    st.markdown("---")
    st.markdown("#### Morning exit card")
    labels = [f"{r.grade} · {r.ticker} (score {r.btst_score:.0f})" for r in results]
    pick = st.selectbox("Select pick", labels, key=f"{key}_pick")
    idx = labels.index(pick) if pick in labels else 0
    _render_pick_card(results[idx])
