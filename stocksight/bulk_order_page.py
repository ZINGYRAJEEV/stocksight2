"""Bulk Order — Screener.in order announcements + bulk/block deals."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from buyback_announcements import _nse_quote_url, _screener_company_url
from screener_bulk_order import (
    ORDER_SEARCH_PRESETS,
    SCREENER_BLOCK_DEALS_URL,
    SCREENER_BULK_DEALS_URL,
    SCREENER_ORDER_URL,
    SCREENER_TRADES_URL,
    fetch_bulk_order_intel,
    fetch_company_news_for_symbols,
    screener_login_configured,
)
from ui_components import inject_css, page_audience_note, safe_set_page_config

META = {
    "title": "Bulk Order",
    "emoji": "📦",
    "nav_title": "Bulk Order",
}


def _render_screener_setup() -> None:
    if screener_login_configured():
        st.success(
            "Screener.in session configured — fetching "
            f"[order announcements]({SCREENER_ORDER_URL}), "
            f"[bulk deals]({SCREENER_BULK_DEALS_URL}), and "
            f"[block deals]({SCREENER_BLOCK_DEALS_URL})."
        )
        return
    with st.expander("🔐 Enable Screener.in feeds (free login)", expanded=True):
        st.markdown(
            f"""
[Screener.in](https://www.screener.in/) full-text search and **Trades & Deals** pages require a
**free** account when fetched programmatically.

**Setup** — add to `.streamlit/secrets.toml`:

```toml
[screener]
sessionid = "paste-from-browser"
csrftoken = "paste-from-browser"
```

1. Log in at [screener.in/login](https://www.screener.in/login/).
2. DevTools → Application → Cookies → `www.screener.in` → copy `sessionid` and `csrftoken`.
3. Restart Streamlit.

**Reference links**
- [Order full-text search]({SCREENER_ORDER_URL})
- [Trades hub]({SCREENER_TRADES_URL}) · [Bulk deals]({SCREENER_BULK_DEALS_URL}) · [Block deals]({SCREENER_BLOCK_DEALS_URL})
- [Bulk & block deals feature](https://www.screener.in/docs/changelog/Bulk-Blockdeals-Screener/)
"""
        )


def _ticker_from_slug(slug: str) -> str:
    if not slug:
        return ""
    return slug if slug.endswith((".NS", ".BO")) else f"{slug}.NS"


def _news_by_slug(rows: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        hl = r.get("headlines") or []
        if not hl:
            continue
        text = " | ".join(hl)
        for key in (
            (r.get("slug") or "").strip().upper(),
            (r.get("symbol") or "").strip().upper(),
        ):
            if key and key not in out:
                out[key] = text
    return out


def _announcements_to_df(
    items: list,
    news_by_slug: dict[str, str] | None = None,
) -> pd.DataFrame:
    news_map = news_by_slug or {}
    rows: list[dict] = []
    for it in items:
        slug = (it.company_slug or "").strip()
        slug_key = slug.upper()
        raw = _ticker_from_slug(slug)
        rows.append({
            "Age": it.age_text or "—",
            "Company": it.company or "—",
            "Headline": it.title,
            "Summary": it.summary or "—",
            "Latest news": news_map.get(slug_key) or news_map.get(slug) or "—",
            "Source": it.source,
            "Filing": it.url if it.url.startswith("http") else f"https://www.screener.in{it.url}",
            "Screener": _screener_company_url(it.company, slug),
            "NSE": _nse_quote_url(raw),
        })
    return pd.DataFrame(rows)


def _symbols_from_intel(data: dict) -> list[str]:
    syms: list[str] = []
    seen: set[str] = set()
    for it in data.get("announcements") or []:
        slug = (getattr(it, "company_slug", "") or "").strip()
        if slug and slug.upper() not in seen:
            seen.add(slug.upper())
            syms.append(slug)
    for row in (data.get("bulk_deals") or []) + (data.get("block_deals") or []):
        sym = (getattr(row, "symbol", "") or "").strip()
        if sym and sym.upper() not in seen:
            seen.add(sym.upper())
            syms.append(sym)
    return syms


def _company_news_to_df(rows: list[dict]) -> pd.DataFrame:
    out: list[dict] = []
    for r in rows:
        hl = r.get("headlines") or []
        out.append({
            "Ticker": r.get("symbol") or "—",
            "Company": r.get("company") or "—",
            "Latest news": " | ".join(hl) if hl else "—",
            "Screener": r.get("screener_url") or "—",
        })
    return pd.DataFrame(out)


def _deals_to_df(rows: list) -> pd.DataFrame:
    out: list[dict] = []
    for r in rows:
        slug = (r.symbol or "").strip().lower().replace(" ", "-")
        raw = _ticker_from_slug(slug) if slug else ""
        out.append({
            "Date": r.deal_date,
            "Company": r.company,
            "Person": r.client,
            "Side": r.price,
            "Qty @ Price": r.quantity,
            "Value": r.deal_value,
            "Deal": r.deal_type,
            "Screener": r.url or _screener_company_url(r.company, slug),
            "NSE": _nse_quote_url(raw),
        })
    return pd.DataFrame(out)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_company_news(symbols: tuple[str, ...]) -> list[dict]:
    if not symbols:
        return []
    return fetch_company_news_for_symbols(
        list(symbols),
        limit_per_symbol=1,
        max_age_days=60,
    )


@st.cache_data(ttl=300, show_spinner=False)
def _cached_intel(
    order_query: str,
    strict_filter: bool,
    deal_days: int,
    include_bulk: bool,
    include_block: bool,
) -> dict:
    return fetch_bulk_order_intel(
        order_query=order_query,
        strict_order_filter=strict_filter,
        deal_days=deal_days,
        include_bulk_deals=include_bulk,
        include_block_deals=include_block,
    )


def render_bulk_order_page() -> None:
    safe_set_page_config(
        page_title=f"{META['title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.markdown(f"### {META['emoji']} Bulk Order — orders & institutional deals")
    page_audience_note(
        "Investors tracking **new business orders** (order wins, contracts) and **NSE bulk/block deals** "
        "where institutions move size.",
        "Data from [Screener.in](https://www.screener.in/) full-text search and "
        "[Trades & Deals](https://www.screener.in/trades/). "
        "Educational — verify filings before trading.",
    )

    _render_screener_setup()

    with st.expander("📖 What this page covers", expanded=False):
        st.markdown(
            f"""
| Feed | Screener source | Use case |
|------|-----------------|----------|
| **Order announcements** | [Full-text search `order`]({SCREENER_ORDER_URL}) | Order wins, work orders, LOIs, contract awards |
| **Bulk deals** | [NSE bulk deals]({SCREENER_BULK_DEALS_URL}) | Large off-market trades (often FII/DII activity) |
| **Block deals** | [NSE block deals]({SCREENER_BLOCK_DEALS_URL}) | Pre-market block transactions |

**Tips**
- Use **strict filter** to drop board-meeting / compliance noise from the broad `order` query.
- Bulk/block deals often precede or follow news — cross-check with the **News Scanner** and company chart.
- Not affiliated with Screener.in — respect their terms; session cookie is for personal use only.
"""
        )

    tab_ann, tab_bulk, tab_block, tab_news = st.tabs([
        "📋 Order announcements",
        "📊 Bulk deals",
        "🧱 Block deals",
        "📰 Company latest news",
    ])

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        preset = st.selectbox(
            "Search preset",
            list(ORDER_SEARCH_PRESETS.keys()),
            key="bo_preset",
        )
        order_query = ORDER_SEARCH_PRESETS[preset]
        if preset == "order (broad)":
            order_query = st.text_input("Custom query", value="order", key="bo_query")
    with c2:
        strict = st.checkbox("Strict order filter", value=False, key="bo_strict")
    with c3:
        deal_days = st.selectbox("Deal window (days)", [7, 15, 30, 60], index=2, key="bo_days")
    with c4:
        refresh_sec = st.slider("Auto-refresh (s)", 120, 900, 300, 60, key="bo_refresh")

    extra_tickers = st.text_input(
        "Extra tickers for Company news (comma-separated)",
        value="",
        key="bo_extra_tickers",
        placeholder="MASTER, RELIANCE, TCS",
    )

    @st.fragment(run_every=timedelta(seconds=int(refresh_sec)))
    def _live_panel() -> None:
        if st.button("🔄 Refresh now", key="bo_refresh_btn"):
            _cached_intel.clear()
            _cached_company_news.clear()

        with st.spinner("Fetching from Screener.in…"):
            data = _cached_intel(
                order_query,
                strict,
                int(deal_days),
                True,
                True,
            )

        with tab_ann:
            st.link_button("🔗 Open on Screener.in", SCREENER_ORDER_URL, use_container_width=True)
            status = data["announcement_status"]
            items = data["announcements"]
            if status == "auth_required":
                st.warning("Login required — configure Screener cookies above.")
            elif status == "error":
                st.error("Could not fetch order announcements.")
            elif status == "empty" or not items:
                st.info(
                    "No order announcements matched. Try **order (broad)** preset, "
                    "turn off **strict filter**, or open Screener directly."
                )
            else:
                st.success(f"**{len(items)}** announcement(s) · query: `{order_query[:80]}`")
                news_map: dict[str, str] = {}
                if data.get("login_configured"):
                    slugs = list(dict.fromkeys(
                        (getattr(it, "company_slug", "") or "").strip()
                        for it in items
                        if getattr(it, "company_slug", "")
                    ))[:30]
                    if slugs:
                        news_map = _news_by_slug(_cached_company_news(tuple(slugs)))
                df = _announcements_to_df(items, news_map)
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Latest news": st.column_config.TextColumn("Latest news", width="large"),
                        "Filing": st.column_config.LinkColumn(display_text="Filing ↗"),
                        "Screener": st.column_config.LinkColumn(display_text="Screener ↗"),
                        "NSE": st.column_config.LinkColumn(display_text="NSE ↗"),
                    },
                )

        with tab_bulk:
            st.link_button("🔗 Bulk deals on Screener", SCREENER_BULK_DEALS_URL, use_container_width=True)
            bulk = data["bulk_deals"]
            bstat = data["bulk_status"]
            if bstat == "auth_required":
                st.warning("Login required for bulk deals table.")
            elif bstat == "error":
                st.error("Bulk deals fetch failed.")
            elif not bulk:
                st.info("No bulk deals parsed — open Screener directly or check cookie session.")
            else:
                st.success(f"**{len(bulk)}** bulk deal row(s) · last **{deal_days}** days")
                st.dataframe(
                    _deals_to_df(bulk),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Screener": st.column_config.LinkColumn(display_text="Company ↗"),
                        "NSE": st.column_config.LinkColumn(display_text="NSE ↗"),
                    },
                )

        with tab_block:
            st.link_button("🔗 Block deals on Screener", SCREENER_BLOCK_DEALS_URL, use_container_width=True)
            block = data["block_deals"]
            bstat = data["block_status"]
            if bstat == "auth_required":
                st.warning("Login required for block deals table.")
            elif bstat == "error":
                st.error("Block deals fetch failed.")
            elif not block:
                st.info("No block deals parsed — open Screener directly or check cookie session.")
            else:
                st.success(f"**{len(block)}** block deal row(s) · last **{deal_days}** days")
                st.dataframe(
                    _deals_to_df(block),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Screener": st.column_config.LinkColumn(display_text="Company ↗"),
                        "NSE": st.column_config.LinkColumn(display_text="NSE ↗"),
                    },
                )

        with tab_news:
            st.caption(
                "Pulls the **Announcements** section from each company's Screener page "
                "(e.g. [MASTER](https://www.screener.in/company/MASTER/)) for tickers in the feeds above. "
                "Add more symbols in **Extra tickers** above the refresh panel."
            )
            if not data.get("login_configured"):
                st.warning("Configure Screener cookies above to load company announcements.")
            else:
                symbols = _symbols_from_intel(data)
                if extra_tickers.strip():
                    for part in extra_tickers.replace(";", ",").split(","):
                        sym = part.strip().upper()
                        if sym and sym not in {s.upper() for s in symbols}:
                            symbols.append(sym)
                symbols = symbols[:25]
                if not symbols:
                    st.info("No tickers in current feeds — add symbols above or refresh order/deal tabs.")
                else:
                    with st.spinner(f"Fetching announcements for {len(symbols)} companies…"):
                        news_rows = fetch_company_news_for_symbols(
                            symbols,
                            limit_per_symbol=2,
                            max_age_days=60,
                        )
                    st.success(f"**{len(news_rows)}** companies · latest filings from Screener")
                    st.dataframe(
                        _company_news_to_df(news_rows),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Screener": st.column_config.LinkColumn(display_text="Company page ↗"),
                            "Latest news": st.column_config.TextColumn("Latest news", width="large"),
                        },
                    )

        st.caption(
            f"Last fetch: {data.get('fetched_at', '—')} · "
            f"Screener login: **{'yes' if data.get('login_configured') else 'no'}**"
        )

    _live_panel()
