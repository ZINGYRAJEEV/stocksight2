"""Insider Trading Tracker — SEC Form 4 + universe scan."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from insider_trading import (
    ALERT_VALUE_USD,
    HIGH_VALUE_USD,
    META,
    market_intelligence_summary,
    scan_sec_form4,
    scan_yahoo_insider_universe,
    trades_to_dataframe,
)
from intraday import INTRADAY_UNIVERSES_BY_MARKET, MARKET_LABEL, MARKETS, resolve_universe
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
)

_LINK_COLUMNS = ("Yahoo Finance", "Google Finance", "Moneycontrol", "TradingView", "MarketWatch")


def _link_config() -> dict:
    return {
        "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
        "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
        "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
        "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
        "SEC ↗": st.column_config.LinkColumn("SEC filing", display_text="SEC ↗"),
    }


def _side_style(series: pd.Series) -> list[str]:
    styles = []
    for v in series:
        s = str(v)
        if s == "Buy":
            styles.append("background-color:#dcfce7;color:#166534;font-weight:600;")
        elif s == "Sell":
            styles.append("background-color:#fee2e2;color:#991b1b;font-weight:600;")
        else:
            styles.append("")
    return styles


def _value_style(series: pd.Series) -> list[str]:
    styles = []
    for v in series:
        try:
            x = float(v)
        except (TypeError, ValueError):
            styles.append("")
            continue
        if x >= HIGH_VALUE_USD:
            styles.append("background-color:#bbf7d0;color:#14532d;font-weight:700;")
        elif x >= ALERT_VALUE_USD:
            styles.append("background-color:#ecfdf5;color:#047857;")
        else:
            styles.append("")
    return styles


def _render_methodology() -> None:
    with st.expander("📖 What this tracker is (and is not)", expanded=False):
        st.markdown(
            """
**Validated from the briefing — what's accurate:**

| Claim | Verdict |
|-------|---------|
| Form 4 = legal insider disclosure within ~2 business days | ✅ Correct (US SEC) |
| SEC Edgar API is free, no API key | ✅ Correct — requires a proper `User-Agent` string |
| Rank by dollar value, CEO/CFO filter, cluster buying | ✅ Sound and implemented here |
| Cherry-picked $600k CMO buy as “edge” | ⚠️ Anecdote — one trade ≠ strategy |
| “Real-time” | ⚠️ Near real-time after filing; not tick-by-tick |
| Telegram/WhatsApp alerts | ⚠️ Optional — add `[sec]` / email in secrets later; not required |
| React + FastAPI stack | N/A — StockSight uses **Streamlit** + same public data |

**India (NSE):** There is no SEC Form 4. Use **Universe scan** (Yahoo insider history) or
Screener.in shareholding — NSE PIT API is often blocked without session cookies.

**Not financial advice.** Cluster buying and CEO buys are *signals to research*, not buy orders.
"""
        )


def _render_sec_tab(key: str) -> None:
    session_key = f"{key}_sec_trades"
    stats_key = f"{key}_sec_stats"

    st.markdown(
        "Live **SEC Form 4** feed — parses each filing's XML for shares, price, and buy/sell. "
        f"Highlights trades ≥ **${HIGH_VALUE_USD:,}**."
    )
    st.caption(
        "SEC requires a contact User-Agent. Optional: add `user_agent = \"YourName you@email.com\"` "
        "under `[sec]` in `.streamlit/secrets.toml`."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        days = st.slider("Filing window (days)", 1, 14, 7, key=f"{key}_sec_days")
        max_f = st.slider("Max filings to parse", 20, 120, 60, 10, key=f"{key}_sec_max")
    with c2:
        min_val = st.number_input("Min trade value ($)", 0, 2_000_000, 25_000, 5_000, key=f"{key}_sec_min")
        ceo_only = st.checkbox("CEO / CFO / Chair only", value=False, key=f"{key}_sec_ceo")
    with c3:
        buys_only = st.checkbox("Buys only", value=False, key=f"{key}_sec_buy")
        ticker_q = st.text_input("Filter ticker", placeholder="AAPL", key=f"{key}_sec_q").strip().upper()

    run = st.button("▶ Load SEC Form 4 feed", type="primary", key=f"{key}_sec_run")

    if run:
        prog = st.progress(0.0, text="Fetching Edgar index…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(i / max(total, 1), text=f"Parsing {sym} ({i}/{total})…")

        with st.spinner("Pulling Form 4 filings from SEC Edgar…"):
            trades, stats = scan_sec_form4(
                days=int(days),
                max_filings=int(max_f),
                min_value_usd=float(min_val),
                ceo_cfo_only=ceo_only,
                buys_only=buys_only,
                progress_cb=_cb,
            )
        prog.empty()
        st.session_state[session_key] = trades
        st.session_state[stats_key] = stats
        append_scan_record(
            "insider_sec",
            "SEC Form 4",
            [t.ticker for t in trades[:20]],
            meta={"trades": stats.trades_parsed, "clusters": stats.cluster_count},
        )

    trades = st.session_state.get(session_key) or []
    stats = st.session_state.get(stats_key)

    if ticker_q and trades:
        trades = [t for t in trades if ticker_q in t.ticker.upper() or ticker_q in t.company.upper()]

    if not trades and not run:
        st.info(
            "Click **Load SEC Form 4 feed** — best on **US market days** after insiders file "
            "(typically within 2 business days of the trade)."
        )
        return

    intel = market_intelligence_summary(trades)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Trades", intel["total_trades"])
    m2.metric("Buy flow ($)", f"{intel['buy_value']:,.0f}")
    m3.metric("Sell flow ($)", f"{intel['sell_value']:,.0f}")
    m4.metric("Clusters", intel["clusters"])
    m5.metric("≥$100k alerts", intel["alert_count"])
    st.caption(f"**Insider sentiment:** {intel['net_sentiment']}")

    if stats:
        st.success(
            f"Parsed **{stats.trades_parsed}** trades from **{stats.filings_fetched}** filings · "
            f"buys **{stats.buy_count}** · sells **{stats.sell_count}** · "
            f"{stats.scan_elapsed_sec:.0f}s"
        )

    clusters = [t for t in trades if t.is_cluster]
    if clusters:
        st.markdown("#### 🔥 Cluster buying (3+ insiders · 48h)")
        for cik in {t.cluster_id for t in clusters}:
            grp = [t for t in clusters if t.cluster_id == cik]
            if not grp:
                continue
            st.markdown(
                f"- **{grp[0].company}** ({grp[0].ticker}) — "
                f"{len({g.insider_name for g in grp})} insiders · "
                f"total buys **${sum(g.value_usd for g in grp):,.0f}**"
            )

    df = trades_to_dataframe(trades)
    if df.empty:
        st.warning("No trades matched filters. Lower min value or widen the filing window.")
        return

    link_cols = [c for c in _LINK_COLUMNS if c in df.columns]
    core = [c for c in df.columns if c not in link_cols]
    display = df[core + link_cols]

    styler = display.style
    if "Side" in display.columns:
        styler = styler.apply(_side_style, subset=["Side"])
    if "Value ($)" in display.columns:
        styler = styler.apply(_value_style, subset=["Value ($)"])

    render_clickable_scan_table(
        display,
        styler=styler,
        key_prefix=f"{key}_sec",
        market="US",
        apply_stock_sight=False,
        column_config={
            **_link_config(),
            "Value ($)": st.column_config.NumberColumn(format="$%.0f"),
            "Shares": st.column_config.NumberColumn(format="%.0f"),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
        },
        caption="Green rows ≥ $500k · Buys highlighted · **Cluster** = 3+ insiders bought within 48h.",
        show_gate_legend=False,
    )


def _universe_options(market: str) -> list[str]:
    mkt = (market or "NSE").upper()
    dct = INTRADAY_UNIVERSES_BY_MARKET.get(mkt, {})
    preferred = (
        ("Nifty 50 (fast)", "Nifty 100 (medium)", "Liquid US shortlist (~35)")
        if mkt == "US"
        else ("Nifty 50 (fast)", "Nifty 100 (medium)", "Nifty 500 (broad, slow)")
    )
    opts = list(dct.keys())
    ordered = [u for u in preferred if u in opts]
    ordered += [u for u in opts if u not in ordered]
    return ordered


def _render_universe_tab(key: str) -> None:
    session_key = f"{key}_uni_trades"

    st.markdown(
        "Scan your **NSE / US universe** via Yahoo `insider_transactions` — useful when SEC Form 4 "
        "does not apply (India) or for historical context on watchlist names."
    )
    st.warning(
        "Yahoo insider data is **sparse for many NSE tickers** and may lag. "
        "Treat as a starting point — verify on Screener.in / exchange filings."
    )

    market = st.radio(
        "Market",
        MARKETS,
        format_func=lambda m: MARKET_LABEL.get(m, m),
        horizontal=True,
        key=f"{key}_uni_mkt",
    )
    uni_opts = _universe_options(market)
    c1, c2, c3 = st.columns(3)
    with c1:
        universe = st.selectbox("Universe", uni_opts, key=f"{key}_uni")
        max_n = st.slider("Max tickers", 10, 200, 50 if market == "NSE" else 35, 5, key=f"{key}_uni_max")
    with c2:
        days = st.slider("Lookback (days)", 30, 365, 120, key=f"{key}_uni_days")
        min_val = st.number_input("Min value ($)", 0, 5_000_000, 100_000, 25_000, key=f"{key}_uni_min")
    with c3:
        ceo_only = st.checkbox("CEO / CFO filter", key=f"{key}_uni_ceo")
        buys_only = st.checkbox("Buys only", value=True, key=f"{key}_uni_buy")

    run = st.button("▶ Scan universe", type="primary", key=f"{key}_uni_run")

    if run:
        tickers = resolve_universe(universe, market=market)[: int(max_n)]
        prog = st.progress(0.0, text="Scanning…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(i / max(total, 1), text=f"{sym} ({i}/{total})")

        with st.spinner("Fetching Yahoo insider history…"):
            from insider_trading import is_ceo_cfo_role

            trades, stats = scan_yahoo_insider_universe(
                tickers,
                days=int(days),
                min_value_usd=float(min_val),
                progress_cb=_cb,
            )
        prog.empty()
        if ceo_only:
            trades = [t for t in trades if is_ceo_cfo_role(t.role)]
        if buys_only:
            trades = [t for t in trades if t.side == "Buy"]
        st.session_state[session_key] = trades
        st.session_state[f"{key}_uni_stats"] = stats
        append_scan_record("insider_universe", universe, [t.ticker for t in trades[:15]])

    trades = st.session_state.get(session_key) or []
    if not trades and not run:
        st.info("Pick a universe and click **Scan universe**.")
        return

    intel = market_intelligence_summary(trades)
    c1, c2, c3 = st.columns(3)
    c1.metric("Trades", intel["total_trades"])
    c2.metric("Sentiment", intel["net_sentiment"])
    c3.metric("CEO/CFO buys", intel["ceo_cfo_buys"])

    df = trades_to_dataframe(trades)
    if df.empty:
        st.warning("No insider rows found — try a shorter lookback or lower min value.")
        return

    render_clickable_scan_table(
        df[[c for c in df.columns if c in df.columns]],
        key_prefix=f"{key}_uni",
        market=market,
        apply_stock_sight=False,
        column_config=_link_config(),
        caption="Yahoo-sourced insider history · verify material trades on primary exchange filings.",
        show_gate_legend=False,
    )


def render_insider_trading_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    key = "insider"
    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])
    _render_methodology()
    render_watchlist_panel("insider_wl")

    tab_sec, tab_uni = st.tabs(["🇺🇸 SEC Form 4 (live)", "🌐 Universe scan (NSE / US)"])

    with tab_sec:
        _render_sec_tab(key)

    with tab_uni:
        _render_universe_tab(key)
