"""Pre-Investigation Links — Screener.in research shortcuts."""

from __future__ import annotations

import html

import streamlit as st

from pre_investigation import CATEGORIES, LINKS, META
from ui_components import inject_css, page_audience_note, safe_set_page_config


def _link_card(link) -> None:
    st.markdown(
        f"""
        <div style='background:#0f172a; border:1px solid #1e293b; border-radius:10px;
                    padding:16px 18px; margin-bottom:8px; min-height:140px;'>
            <div style='font-size:1.1rem; font-weight:700; color:#f1f5f9;'>
                {html.escape(link.emoji)} {html.escape(link.title)}
            </div>
            <div style='font-size:0.72rem; color:#94a3b8; margin-top:4px; text-transform:uppercase;'>
                {html.escape(link.category)}
            </div>
            <div style='font-size:0.85rem; color:#cbd5e1; margin-top:10px; line-height:1.45;'>
                {html.escape(link.summary)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.link_button(
        f"Open on Screener.in ↗",
        link.url,
        key=f"preinv_{link.id}",
        use_container_width=True,
    )
    if link.tips:
        st.caption(f"💡 {link.tips}")


def _render_workflow() -> None:
    with st.expander("📖 How to use these links", expanded=True):
        st.markdown(
            """
1. **Pick a theme** below (big orders, buyback, open offer, etc.).
2. **Open Screener.in** — review latest matching announcements (free account may be required).
3. **Shortlist tickers** — open each company on Screener for financials.
4. **Cross-check in StockSight** — run relevant screener (e.g. **Buyback Screener** for buybacks).
5. **Watchlist** — add names; set alerts before placing orders.

**Note:** Open Offers, Delisting, and Demergers use the same Screener.in corporate-action search —
filter results by keyword once the page loads.
"""
        )


def render_pre_investigation_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.html(f"""
    <div style='background:#0c4a6e; border:1px solid #075985; border-left:4px solid #38bdf8;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#f0f9ff;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#bae6fd; margin-top:6px;'>
            Screener.in bookmarks for pre-trade corporate & order research
        </div>
    </div>
    """)

    page_audience_note(META["audience"], META["purpose"])
    _render_workflow()

    filter_cat = st.selectbox(
        "Filter by category",
        ["All"] + list(CATEGORIES),
        key="preinv_cat",
    )

    shown = [lk for lk in LINKS if filter_cat == "All" or lk.category == filter_cat]

    st.markdown("#### Quick links")
    cols = st.columns(2)
    for i, link in enumerate(shown):
        with cols[i % 2]:
            _link_card(link)

    with st.expander("🔗 Copy URLs (all links)", expanded=False):
        for link in LINKS:
            st.markdown(f"**{link.title}**")
            st.code(link.url, language=None)

    st.caption(
        "Links point to [Screener.in](https://www.screener.in) — not affiliated with StockSight. "
        "Verify announcements on NSE/BSE before trading."
    )
