"""NSE Intraday Intel — Bulk Order dataset + rule-based intraday setups."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from bulk_order_page import _news_by_slug
from screener_session_ui import render_screener_session_panel
from nse_intraday_intel import (
    IntradayIntelRecord,
    build_intel_batch,
    build_market_themes,
    ist_clock_label,
    market_session_phase,
    _fmt_inr,
)
from screener_bulk_order import (
    ORDER_SEARCH_PRESETS,
    SCREENER_ORDER_URL,
    fetch_bulk_order_intel,
    fetch_company_news_for_symbols,
    screener_login_configured,
)
from ui_components import inject_css, page_audience_note, safe_set_page_config

META = {
    "title": "NSE Intraday Intel",
    "emoji": "⚡",
    "nav_title": "NSE Intraday Intel",
}

_NEWS_TYPE_LABEL = {
    "ORDER_WIN": "ORDER WIN",
    "VOLUME_ALERT": "VOL ALERT",
    "LEGAL_NEGATIVE": "LEGAL -VE",
    "CLARIFICATION_NEUTRAL": "QUERY RESOLVED",
    "CLARIFICATION_PENDING": "QUERY PENDING",
    "OTHER": "OTHER",
}

_SENTIMENT_EMOJI = {
    "BULLISH": "🟢",
    "MILDLY_BULLISH": "🟡",
    "CAUTIOUSLY_BULLISH": "🟡",
    "NEUTRAL": "⚪",
    "NEUTRAL_TO_CAUTIOUS": "🟠",
    "MILDLY_BEARISH": "🟠",
    "BEARISH_BIAS": "🔴",
    "SHORT_BIAS_OR_AVOID": "🔴",
    "BINARY": "🟣",
    "WAIT": "⏸️",
}


def _intel_summary_df(records: list[IntradayIntelRecord]) -> pd.DataFrame:
    rows: list[dict] = []
    for r in records:
        em = _SENTIMENT_EMOJI.get(r.intraday.sentiment, "⚪")
        ctx = r.stock_context
        rows.append({
            "Ticker": r.ticker,
            "Company": r.name,
            "LTP ₹": ctx.price,
            "Prev close ₹": ctx.prev_close,
            "Gap %": ctx.gap_pct,
            "Type": _NEWS_TYPE_LABEL.get(r.news_type, r.news_type),
            "Sentiment": f"{em} {r.intraday.sentiment.replace('_', ' ')}",
            "Strength": "★" * r.intraday.strength + "☆" * (3 - r.intraday.strength),
            "Bias": r.intraday.bias.replace("_", " "),
            "Risk": r.intraday.risk.replace("_", " "),
            "React by": r.intraday.react_by or "—",
            "Exit by": r.intraday.exit_by or "—",
            "Indicator": r.intraday.indicator,
            "Suggestion": r.intraday.suggestion,
            "News": r.news[:120] + ("…" if len(r.news) > 120 else ""),
            "Latest news": r.latest_news[:100] + ("…" if len(r.latest_news) > 100 else ""),
            "Screener": r.screener_url,
            "NSE": r.nse_url,
        })
    return pd.DataFrame(rows)


def _render_company_detail(r: IntradayIntelRecord) -> None:
    ctx = r.stock_context
    intra = r.intraday
    em = _SENTIMENT_EMOJI.get(intra.sentiment, "⚪")

    st.markdown(f"#### {r.name} · `{r.ticker}`")
    st.caption(f"{r.sector} · {r.news_date} · {_NEWS_TYPE_LABEL.get(r.news_type, r.news_type)}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("LTP", ctx.approx_price)
    gap_lbl = f"{ctx.gap_pct:+.2f}%" if ctx.gap_pct is not None else "—"
    m2.metric("Gap vs prev close", gap_lbl)
    prev_lbl = _fmt_inr(ctx.prev_close) if ctx.prev_close else "—"
    m3.metric("Prev close", prev_lbl)
    m4.metric("Now (IST)", ist_clock_label())

    m1, m2, m3, m4 = st.columns(4)
    em = _SENTIMENT_EMOJI.get(intra.sentiment, "⚪")
    m1.metric("Sentiment", f"{em} {intra.sentiment.replace('_', ' ')}")
    m2.metric("Strength", "★" * intra.strength + "☆" * (3 - intra.strength))
    m3.metric("Bias", intra.bias.replace("_", " "))
    m4.metric("Risk", intra.risk.replace("_", " "))

    t1, t2, t3 = st.columns(3)
    t1.metric("React by", intra.react_by or "—")
    t2.metric("Exit by", intra.exit_by or "—")
    t3.metric("52W range", f"{ctx.week_low52} – {ctx.week_high52}")

    st.info(f"**Indicator:** {intra.indicator}")
    st.success(f"**Suggestion:** {intra.suggestion}")

    if intra.react_windows:
        st.markdown("**When to react (IST timeline)**")
        for line in intra.react_windows:
            st.markdown(f"- {line}")

    st.markdown("**Catalyst (Bulk Order feed)**")
    st.write(r.news)
    if r.latest_news and r.latest_news != "—":
        st.markdown("**Latest company filing (Screener)**")
        st.write(r.latest_news)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Stock context**")
        st.write(
            f"Price: **{ctx.approx_price}** · Gap: **{ctx.gap_pct:+.2f}%** vs prev close "
            f"({ _fmt_inr(ctx.prev_close) if ctx.prev_close else '—'}) · "
            f"52W H: **{ctx.week_high52}** · 52W L: **{ctx.week_low52}** · "
            f"Trend: **{ctx.trend.replace('_', ' ')}**"
        )
        st.caption(ctx.note)
    with c2:
        st.markdown("**Trade setup**")
        st.write(f"**Entry:** {intra.entry}")
        st.write(f"**Target:** {intra.target}")
        st.write(f"**Stop:** {intra.stop}")

    st.markdown("**Intraday rules**")
    for i, rule in enumerate(intra.rules, 1):
        st.markdown(f"{i:02d}. {rule}")

    st.warning(f"**Risk note ({intra.risk.replace('_', ' ')}):** {intra.risk_note}")

    l1, l2 = st.columns(2)
    with l1:
        if r.screener_url:
            st.link_button("Screener company page", r.screener_url, use_container_width=True)
    with l2:
        if r.nse_url:
            st.link_button("NSE quote", r.nse_url, use_container_width=True)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_intel(order_query: str, strict_filter: bool) -> dict:
    return fetch_bulk_order_intel(
        order_query=order_query,
        strict_order_filter=strict_filter,
        include_bulk_deals=False,
        include_block_deals=False,
        deal_days=7,
    )


@st.cache_data(ttl=300, show_spinner=False)
def _cached_company_news(symbols: tuple[str, ...]) -> list[dict]:
    if not symbols:
        return []
    return fetch_company_news_for_symbols(
        list(symbols),
        limit_per_symbol=2,
        max_age_days=60,
    )


@st.cache_data(ttl=300, show_spinner=False)
def _cached_analysis(
    order_query: str,
    strict_filter: bool,
    max_companies: int,
    sort_by: str,
) -> tuple[list[dict], list[dict], dict]:
    data = _cached_intel(order_query, strict_filter)
    items = data.get("announcements") or []
    slugs = list(dict.fromkeys(
        (getattr(it, "company_slug", "") or "").strip().upper()
        for it in items
        if getattr(it, "company_slug", "")
    ))[:max_companies]

    news_map: dict[str, str] = {}
    if data.get("login_configured") and slugs:
        news_map = _news_by_slug(_cached_company_news(tuple(slugs)))

    unique_slugs = list(dict.fromkeys(
        (getattr(it, "company_slug", "") or "").strip().upper()
        for it in items
        if getattr(it, "company_slug", "")
    ))
    records = build_intel_batch(
        items,
        news_by_slug=news_map,
        max_companies=max_companies,
        enrich_prices=True,
        sort_by=sort_by,
    )
    themes = build_market_themes(records)
    feed_meta = {
        "announcement_count": len(items),
        "unique_companies": len(unique_slugs),
        "shown_companies": len(records),
        "fetched_at": data.get("fetched_at", ""),
    }

    def _rec_dict(r: IntradayIntelRecord) -> dict:
        return {
            "ticker": r.ticker,
            "name": r.name,
            "sector": r.sector,
            "news": r.news,
            "news_type": r.news_type,
            "news_date": r.news_date,
            "latest_news": r.latest_news,
            "screener_url": r.screener_url,
            "nse_url": r.nse_url,
            "stock_context": {
                "approx_price": r.stock_context.approx_price,
                "trend": r.stock_context.trend,
                "note": r.stock_context.note,
                "week_high52": r.stock_context.week_high52,
                "week_low52": r.stock_context.week_low52,
                "price": r.stock_context.price,
                "prev_close": r.stock_context.prev_close,
                "gap_pct": r.stock_context.gap_pct,
            },
            "intraday": {
                "sentiment": r.intraday.sentiment,
                "strength": r.intraday.strength,
                "bias": r.intraday.bias,
                "entry": r.intraday.entry,
                "target": r.intraday.target,
                "stop": r.intraday.stop,
                "rules": r.intraday.rules,
                "risk": r.intraday.risk,
                "risk_note": r.intraday.risk_note,
                "indicator": r.intraday.indicator,
                "suggestion": r.intraday.suggestion,
                "react_by": r.intraday.react_by,
                "exit_by": r.intraday.exit_by,
                "react_windows": r.intraday.react_windows,
            },
        }

    return [_rec_dict(r) for r in records], [
        {"title": t.title, "icon": t.icon, "summary": t.summary, "rule": t.rule}
        for t in themes
    ], feed_meta


def _records_from_cache(raw: list[dict]) -> list[IntradayIntelRecord]:
    from nse_intraday_intel import IntradaySetup, StockContext

    out: list[IntradayIntelRecord] = []
    for d in raw:
        sc = d["stock_context"]
        ia = d["intraday"]
        out.append(
            IntradayIntelRecord(
                ticker=d["ticker"],
                name=d["name"],
                sector=d["sector"],
                news=d["news"],
                news_type=d["news_type"],
                news_date=d["news_date"],
                latest_news=d["latest_news"],
                screener_url=d.get("screener_url", ""),
                nse_url=d.get("nse_url", ""),
                stock_context=StockContext(
                    approx_price=sc["approx_price"],
                    trend=sc["trend"],
                    note=sc["note"],
                    week_high52=sc["week_high52"],
                    week_low52=sc["week_low52"],
                    price=sc.get("price"),
                    prev_close=sc.get("prev_close"),
                    gap_pct=sc.get("gap_pct"),
                ),
                intraday=IntradaySetup(
                    sentiment=ia["sentiment"],
                    strength=ia["strength"],
                    bias=ia["bias"],
                    entry=ia["entry"],
                    target=ia["target"],
                    stop=ia["stop"],
                    rules=ia["rules"],
                    risk=ia["risk"],
                    risk_note=ia["risk_note"],
                    indicator=ia["indicator"],
                    suggestion=ia["suggestion"],
                    react_by=ia.get("react_by", ""),
                    exit_by=ia.get("exit_by", ""),
                    react_windows=ia.get("react_windows", []),
                ),
            )
        )
    return out


_PHASE_HINT = {
    "PRE_OPEN": "Pre-open — review filings and set alerts before 9:15.",
    "PRE_MARKET": "Pre-market window — final prep; entries start at 9:15.",
    "OPENING_15M": "Opening 15 min — highest urgency; many setups react by 9:30–9:45.",
    "MORNING_SETUP": "Morning setup — confirm volume before 10:00 deadlines.",
    "MID_MORNING": "Mid-morning — narrative trades fading; respect 11:00 exits.",
    "MIDDAY": "Midday — avoid new illiquid small-cap entries.",
    "AFTERNOON": "Afternoon — manage exits; event trades should be flat by 1:30.",
    "CLOSING": "Closing auction window — no new intraday entries.",
    "POST_MARKET": "Market closed — prep for next session.",
    "WEEKEND": "Weekend — review watchlist for Monday open.",
}


def render_nse_intraday_intel_page() -> None:
    safe_set_page_config(
        page_title=f"{META['title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} NSE Intraday Intel")
    page_audience_note(
        "Turns **Bulk Order** Screener filings into intraday bias, entry/stop/target, and rule cards "
        "— similar to a morning intel brief before the open.",
        "Educational only — not SEBI-registered advice. Verify filings and tape before trading.",
    )

    render_screener_session_panel(
        key_prefix="nii_screener",
        success_message=(
            "Screener.in session active — Bulk Order feed + company announcements enabled."
        ),
        extra_setup_links=f"- [Order search on Screener]({SCREENER_ORDER_URL})",
    )

    with st.expander("📖 How this screen works", expanded=False):
        st.markdown(
            f"""
1. Pulls the same **order announcement** feed as [Bulk Order]({SCREENER_ORDER_URL}).
2. Classifies each filing (order win, volume alert, legal, exchange query).
3. Enriches with **price context** (52-week range, trend, volume ratio) via Yahoo Finance.
4. Applies **intraday rules** (ORB, VWAP, volume confirmation, risk tier).
5. Surfaces **indicators** and **suggestions** per ticker plus batch **market themes**.

Use with the **Intraday Screener** and **Gap Scanner** for tape confirmation.
"""
        )

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        preset = st.selectbox(
            "Search preset",
            list(ORDER_SEARCH_PRESETS.keys()),
            key="nii_preset",
        )
        order_query = ORDER_SEARCH_PRESETS[preset]
        if preset == "order (broad)":
            order_query = st.text_input("Custom query", value="order", key="nii_query")
    with c2:
        strict = st.checkbox("Strict order filter", value=False, key="nii_strict")
    with c3:
        max_co = st.slider("Max companies", 5, 60, 40, key="nii_max")
    sort_by = st.radio(
        "Sort results by",
        ("newest", "strength"),
        format_func=lambda x: "Newest filing first" if x == "newest" else "Setup strength (★)",
        horizontal=True,
        key="nii_sort",
    )
    with c4:
        auto_refresh = st.checkbox(
            "Enable auto-refresh",
            value=False,
            key="nii_auto_refresh",
            help="Off by default — click **Refresh analysis** to reload. "
            "Turn on to poll Screener on an interval while this tab stays open.",
        )

    refresh_sec = 300
    if auto_refresh:
        refresh_sec = st.slider(
            "Auto-refresh interval (seconds)",
            120,
            900,
            300,
            60,
            key="nii_refresh",
        )

    def _live_intel_body() -> None:
        if st.button("🔄 Refresh analysis", key="nii_refresh_btn", type="primary"):
            _cached_intel.clear()
            _cached_company_news.clear()
            _cached_analysis.clear()

        if auto_refresh:
            st.caption(f"Auto-refresh **on** · every **{int(refresh_sec)}s** (manual refresh still clears cache)")

        if not screener_login_configured():
            st.warning("Configure Screener cookies to load the Bulk Order announcement feed.")
            return

        with st.spinner("Building intraday intel from Bulk Order feed…"):
            raw_records, themes, feed_meta = _cached_analysis(
                order_query, strict, int(max_co), sort_by
            )

        records = _records_from_cache(raw_records)

        phase = market_session_phase()
        st.caption(
            f"**{ist_clock_label()}** · Session: **{phase.replace('_', ' ')}** — "
            f"{_PHASE_HINT.get(phase, '')}"
        )

        tab_companies, tab_themes = st.tabs([
            "📊 Company analysis",
            "🧭 Market themes & rules",
        ])

        with tab_companies:
            if not records:
                st.info(
                    "No announcements to analyse. Try **order (broad)** preset or "
                    "turn off **strict filter** on the Bulk Order query."
                )
                return

            ann_n = feed_meta.get("announcement_count", len(records))
            uniq_n = feed_meta.get("unique_companies", len(records))
            st.success(
                f"**{len(records)}** companies analysed · "
                f"**{ann_n}** announcements in feed ({uniq_n} unique) · "
                f"query: `{order_query[:60]}`"
            )
            if uniq_n > len(records):
                st.warning(
                    f"Bulk Order lists all **{ann_n}** rows; this screen shows **one newest filing "
                    f"per company** (capped at **{int(max_co)}**). Raise **Max companies** to include more."
                )
            st.caption(
                "**LTP** = live / latest Yahoo price · **Gap %** = change vs **previous close**. "
                "Data is cached ~5 min — click **Refresh analysis** after refreshing Bulk Order. "
                "Bulk Order and this page use separate caches until you refresh here."
            )
            st.link_button("🔗 Bulk Order feed on Screener", SCREENER_ORDER_URL)

            df = _intel_summary_df(records)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "LTP ₹": st.column_config.NumberColumn(format="₹%.2f"),
                    "Prev close ₹": st.column_config.NumberColumn(format="₹%.2f"),
                    "Gap %": st.column_config.NumberColumn(format="%+.2f"),
                    "React by": st.column_config.TextColumn("React by", width="small"),
                    "Exit by": st.column_config.TextColumn("Exit by", width="small"),
                    "Indicator": st.column_config.TextColumn("Indicator", width="medium"),
                    "Suggestion": st.column_config.TextColumn("Suggestion", width="medium"),
                    "News": st.column_config.TextColumn("News", width="large"),
                    "Latest news": st.column_config.TextColumn("Latest news", width="large"),
                    "Screener": st.column_config.LinkColumn("Screener ↗"),
                    "NSE": st.column_config.LinkColumn("NSE ↗"),
                },
            )

            st.markdown("---")
            st.markdown("#### Detail view")
            labels = [f"{r.ticker} — {r.name}" for r in records]
            pick = st.selectbox("Select company", labels, key="nii_pick")
            idx = labels.index(pick) if pick in labels else 0
            _render_company_detail(records[idx])

        with tab_themes:
            if not themes:
                st.info("Run a scan first to generate batch themes.")
                return
            for t in themes:
                with st.container(border=True):
                    st.markdown(f"### {t['icon']} {t['title']}")
                    st.write(t["summary"])
                    st.markdown(f"**Rule:** {t['rule']}")

        st.caption(f"Screener login: **{'yes' if screener_login_configured() else 'no'}**")

    if auto_refresh:
        @st.fragment(run_every=timedelta(seconds=int(refresh_sec)))
        def _live_intel() -> None:
            if not st.session_state.get("nii_auto_refresh"):
                return
            _live_intel_body()
    else:
        @st.fragment
        def _live_intel() -> None:
            _live_intel_body()

    _live_intel()
