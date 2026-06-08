"""Finance Hub — portfolio, Google-style news feed, and news chat."""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import streamlit as st
import yfinance as yf

from finance_hub import (
    META,
    build_news_feed,
    news_chat_reply,
    tracked_symbols,
)
from screener import compute_rsi, fetch_price_history, get_stock_links
from ui_components import (
    inject_css,
    notify_watchlist_alerts_from_metrics,
    page_audience_note,
    render_watchlist_panel,
    safe_set_page_config,
)
from watchlist_store import list_open_positions, upsert_watchlist_fields


def _portfolio_alert_helpers():
    def _has_rules(row: dict) -> bool:
        for key in ("alert_rsi_below", "alert_rsi_above", "alert_price_above", "alert_price_below"):
            v = row.get(key)
            try:
                if v is not None and float(v) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _needs_rsi(row: dict) -> bool:
        for key in ("alert_rsi_below", "alert_rsi_above"):
            v = row.get(key)
            try:
                if v is not None and float(v) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    return _has_rules, _needs_rsi


def _render_portfolio_tab() -> None:
    st.markdown("#### 💼 My portfolio")
    st.caption(
        "Like Google Finance **Portfolios** — track quantity, average cost, live P&L. "
        "Data is stored locally in your watchlist file (not synced to Google)."
    )
    render_watchlist_panel("fh_wl")

    with st.expander("Add / update position", expanded=False):
        sym = st.text_input("Raw ticker (e.g. RELIANCE.NS or AAPL)", key="fh_pf_sym")
        qty = st.number_input("Quantity", min_value=0.0, value=0.0, step=1.0, key="fh_pf_qty")
        ep = st.number_input("Average entry price", min_value=0.0, value=0.0, step=0.05, key="fh_pf_ep")
        ed = st.text_input("Entry date (YYYY-MM-DD, optional)", value="", key="fh_pf_ed")
        if st.button("Save position", key="fh_pf_save"):
            sym_clean = (sym or "").strip()
            if not sym_clean:
                st.error("Ticker required.")
            elif qty <= 0 or ep <= 0:
                upsert_watchlist_fields(sym_clean, {"qty": None, "entry_price": None, "entry_date": None})
                st.success("Cleared position fields.")
                st.rerun()
            else:
                upsert_watchlist_fields(
                    sym_clean,
                    {"qty": float(qty), "entry_price": float(ep), "entry_date": (ed or "").strip() or None},
                )
                st.success("Saved.")
                st.rerun()

    rows = list_open_positions()
    if not rows:
        st.info("No open positions — add qty + entry above or use the watchlist panel.")
        return

    has_rules, needs_rsi = _portfolio_alert_helpers()
    out: list[dict] = []
    alert_metrics: list[tuple[str, str, float, float | None]] = []

    for r in rows:
        raw = str(r.get("raw_ticker") or "")
        q = float(r.get("qty") or 0.0)
        ep = float(r.get("entry_price") or 0.0)
        px = None
        try:
            t = yf.Ticker(raw)
            fi = getattr(t, "fast_info", {}) or {}
            lp = fi.get("last_price") or fi.get("regular_market_price")
            if lp is not None:
                px = float(lp)
            else:
                h = t.history(period="5d")
                if not h.empty:
                    px = float(h["Close"].iloc[-1])
        except Exception:
            px = None
        mtm = (float(px) - ep) * q if px is not None else None
        disp = raw.replace(".NS", "").replace(".BO", "")
        links = get_stock_links(raw)
        out.append(
            {
                "Ticker": disp,
                "Qty": q,
                "Entry": ep,
                "Last": round(float(px), 4) if px is not None else None,
                "MTM": round(float(mtm), 2) if mtm is not None else None,
                "%": round((float(px) / ep - 1.0) * 100.0, 2) if px is not None and ep > 0 else None,
                "Google Finance": links.get("Google Finance", ""),
            }
        )
        if px is not None and has_rules(r):
            rsi_val = None
            if needs_rsi(r):
                try:
                    hist = fetch_price_history(raw, "1d")
                    if hist is not None and not hist.empty:
                        rv = compute_rsi(hist["Close"])
                        if rv is not None and not math.isnan(float(rv)):
                            rsi_val = float(rv)
                except Exception:
                    pass
            alert_metrics.append((disp, raw, float(px), rsi_val))

    try:
        notify_watchlist_alerts_from_metrics(
            alert_metrics,
            "Finance Hub portfolio",
            dedupe_session_key="finance_hub_pf",
        )
    except Exception:
        pass

    st.dataframe(
        pd.DataFrame(out),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
            "%": st.column_config.NumberColumn(format="%+.2f"),
        },
    )


def _render_news_tab() -> None:
    st.markdown("#### 📰 News tracker")
    st.caption(
        "Aggregates **Yahoo Finance + Google News RSS** for your holdings and watchlist — "
        "similar to the news tab on Google Finance."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        scope = st.radio(
            "Symbols",
            ("Portfolio + watchlist", "Portfolio only", "Watchlist only"),
            key="fh_news_scope",
        )
    with c2:
        max_age = st.slider("News window (days)", 3, 30, 7, key="fh_news_age")
    with c3:
        max_sym = st.slider("Max symbols to scan", 5, 40, 20, key="fh_news_max")

    inc_pf = scope != "Watchlist only"
    inc_wl = scope != "Portfolio only"
    symbols = tracked_symbols(include_watchlist=inc_wl, include_positions=inc_pf)

    if not symbols:
        st.info("Add symbols to your watchlist or portfolio first.")
        return

    if st.button("🔄 Refresh news feed", type="primary", key="fh_news_run"):
        with st.spinner("Fetching headlines (Yahoo + Google News)…"):
            feed = build_news_feed(symbols, max_age_days=max_age, max_symbols=max_sym)
            st.session_state["fh_news_feed"] = feed
            st.session_state["fh_news_at"] = datetime.now().strftime("%H:%M:%S")

    feed = st.session_state.get("fh_news_feed", [])
    if not feed:
        st.info("Click **Refresh news feed** to load headlines.")
        return

    at = st.session_state.get("fh_news_at", "")
    st.caption(f"Showing **{len(feed)}** symbols with news · last refresh {at}")

    df = pd.DataFrame(
        [
            {
                "Ticker": r.ticker,
                "Portfolio": "✅" if r.in_portfolio else "—",
                "News score": r.news_score,
                "Tier": f"T{r.top_tier}",
                "Headline": r.top_headline,
                "Sources": r.news_sources,
                "Polarity": r.polarity,
                "Action": r.action,
                "Google Finance": r.google_finance,
            }
            for r in feed
        ]
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "News score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
            "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="News ↗"),
            "Headline": st.column_config.TextColumn(width="large"),
        },
    )


def _render_chat_tab() -> None:
    st.markdown("#### 💬 News assistant")
    st.caption(
        "Ask about headlines for any watchlist symbol or your whole portfolio. "
        "Uses live **Yahoo + Google News** data (not a generative AI — factual headlines only)."
    )

    if "fh_chat_messages" not in st.session_state:
        st.session_state["fh_chat_messages"] = [
            {
                "role": "assistant",
                "content": (
                    "Hi — I can pull **recent news** for your stocks.\n\n"
                    "Try:\n"
                    "- `News on RELIANCE`\n"
                    "- `What's happening with TCS and INFY?`\n"
                    "- `Headlines for my portfolio`"
                ),
            }
        ]

    max_age = int(st.session_state.get("news_scan_max_age", 7))

    for msg in st.session_state["fh_chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Ask about news for a ticker or your portfolio…")
    if prompt:
        st.session_state["fh_chat_messages"].append({"role": "user", "content": prompt})
        with st.spinner("Searching Yahoo + Google News…"):
            reply = news_chat_reply(prompt, max_age_days=max_age)
        st.session_state["fh_chat_messages"].append({"role": "assistant", "content": reply.text})
        st.rerun()

    if st.button("Clear chat", key="fh_chat_clear"):
        st.session_state["fh_chat_messages"] = []
        st.rerun()


def render_finance_hub_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #4285f4;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#e8f7ef;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#a3d8b8; margin-top:6px;'>
            Portfolio · tracked news · chat-style headline lookup (Google Finance + Yahoo)
        </div>
    </div>
    """)

    page_audience_note(
        "Investors who want one place to track holdings, follow news, and ask what's in the headlines — "
        "like Google Finance portfolios + news, inside StockSight.",
        "Portfolio data stays in your local watchlist file. News from Yahoo API and Google News RSS. "
        "Chat answers use fetched headlines (not generative AI).",
    )

    tab_pf, tab_news, tab_chat = st.tabs(["💼 Portfolio", "📰 News tracker", "💬 News chat"])

    with tab_pf:
        _render_portfolio_tab()
    with tab_news:
        _render_news_tab()
    with tab_chat:
        _render_chat_tab()

    st.caption(
        "⚠️ Educational only — not financial advice. No official Google Finance API; "
        "Google Finance links open in your browser. For full News Scanner tiers see **News Scanner** page."
    )
