"""UI helpers for high-profit archetype Streamlit pages."""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from high_profit import ARCHETYPES, nav_title
from screener import composite_action_zone, matrix_decision_note
from ui_components import render_clickable_scan_table


def high_profit_header(archetype_id: str) -> None:
    a = ARCHETYPES[archetype_id]
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {a["color"]};
                border-radius:8px; padding:20px 24px; margin-bottom:20px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{html.escape(a["emoji"])}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{html.escape(nav_title(archetype_id))}</div>
                <div style='font-size:0.78rem; color:{a["color"]}; margin-top:4px; font-weight:600;'>
                    {html.escape(a.get("risk_label", ""))} · {html.escape(a["title"])}
                </div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:6px;'>
                    {html.escape(a["description"])}
                </div>
                <div style='font-size:0.75rem; color:#7abeac; margin-top:8px; line-height:1.5;'>
                    ⚠️ {html.escape(a.get("tier_precautions", ""))}
                </div>
            </div>
            <div style='margin-left:auto; font-family:"IBM Plex Mono",monospace;
                        font-size:0.72rem; color:#7abeac;'>
                {html.escape(a["filter_note"])}
            </div>
        </div>
    </div>
    """)


def high_profit_rank_table(
    results: list,
    scan_date: str | None = None,
    *,
    archetype_id: str = "hp",
) -> None:
    if not results:
        return
    if scan_date is None:
        scan_date = datetime.now().strftime("%d %b %Y")

    rows = []
    for rank, r in enumerate(results, start=1):
        decision = composite_action_zone(r.score)
        row = {
            "Rank": rank,
            "Ticker": r.ticker,
            "Decision": decision,
            "Composite": r.score,
            "Matrix note": matrix_decision_note(decision),
            "Price": r.price,
            "PE": r.pe if r.pe < 9000 else None,
            "Vol×": r.vol_ratio,
            "RSI": r.rsi,
            "Score": r.score,
            "Buy?": r.buy_action,
            "Precautions": r.precautions,
        }
        for name, url in r.links.items():
            short = {
                "Yahoo Finance": "📊 Yahoo",
                "Google Finance": "🔎 Google",
                "Moneycontrol": "📈 MC",
                "MarketWatch": "📈 MW",
                "TradingView": "📉 TV",
            }.get(name, name)
            row[short] = url
            # Plain canonical link name (hidden in table) — used by pre-buy research card.
            row[name] = url
        rows.append(row)

    df = pd.DataFrame(rows)
    col_cfg = {
        "Decision": st.column_config.TextColumn("Decision", width="medium"),
        "Matrix note": st.column_config.TextColumn("Matrix note", width="large"),
        "Composite": st.column_config.NumberColumn("Composite", format="%.1f"),
        "Price": st.column_config.NumberColumn("Price ₹", format="%.0f"),
        "PE": st.column_config.NumberColumn("PE", format="%.1f"),
        "Vol×": st.column_config.NumberColumn("Vol×", format="%.2f"),
        "RSI": st.column_config.NumberColumn("RSI", format="%.1f"),
        "Score": st.column_config.NumberColumn("Score", format="%.1f"),
        "Buy?": st.column_config.TextColumn("Buy?", width="medium"),
        "Precautions": st.column_config.TextColumn("Precautions", width="large"),
    }
    for col in df.columns:
        if col.startswith(("📊", "📈", "📉", "🔎")):
            col_cfg[col] = st.column_config.LinkColumn(col, display_text="Open ↗")

    # Hide the canonical link columns (kept in the df for the pre-buy research card).
    for canonical in ("Yahoo Finance", "Google Finance", "Moneycontrol", "MarketWatch", "TradingView"):
        if canonical in df.columns:
            col_cfg[canonical] = None  # type: ignore[assignment]

    st.caption(scan_date)
    render_clickable_scan_table(
        df,
        key_prefix=f"hp_{archetype_id}_rank",
        universe_name="NSE",
        column_config=col_cfg,
        hide_index=True,
        height=min(520, 48 + len(df) * 42),
    )


def _buy_action_color(action: str) -> str:
    a = action.lower()
    if a.startswith("buy") and "avoid" not in a and "chase" not in a:
        return "#25d366"
    if "hold" in a or "watch" in a:
        return "#f0b429"
    if "avoid" in a or "wait" in a:
        return "#ff6b6b"
    return "#a3d8b8"


def _signal_color(label: str) -> str:
    if "STRONG BUY" in label:
        return "#25d366"
    if label == "BUY":
        return "#7ed4a0"
    if label == "SELL":
        return "#ff4d4d"
    return "#a3d8b8"


def high_profit_detail_card(r, rank: int) -> None:
    a = ARCHETYPES[r.archetype_id]
    color = a["color"]

    def _fmt(v, suffix="", na="—"):
        if v is None:
            return na
        return f"{v}{suffix}"

    def _pct(v):
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v}%"

    bars_html = ""
    for label, val in [
        ("Growth", r.score_growth),
        ("Business quality", r.score_business),
        ("Technicals", r.score_technicals),
        ("Momentum", r.score_momentum),
        ("Valuation", r.score_valuation),
    ]:
        pct = val / 20 * 100
        bars_html += f"""
        <div style='margin-bottom:8px;'>
            <div style='display:flex; justify-content:space-between; font-size:0.75rem; color:#a3d8b8;'>
                <span>{html.escape(label)}</span>
                <span style='color:#e8f7ef;'>{val} / 20</span>
            </div>
            <div style='background:#0d1f18; border-radius:4px; height:6px; margin-top:4px;'>
                <div style='width:{pct}%; background:{color}; height:6px; border-radius:4px;'></div>
            </div>
        </div>
        """

    flags_html = ""
    for flag in r.tech_flags:
        parts = flag.split("\n")
        title = html.escape(parts[0])
        sub = html.escape(parts[1]) if len(parts) > 1 else ""
        flags_html += f"""
        <div style='background:#16352c; border:1px solid #1a3b31; border-radius:6px;
                    padding:8px 12px; font-size:0.75rem; min-width:140px;'>
            <div style='color:#a3d8b8;'>{title}</div>
            <div style='color:#25d366; font-weight:600;'>{sub}</div>
        </div>
        """

    links_html = " &nbsp;".join([
        f'<a href="{html.escape(url, quote=True)}" target="_blank" style="color:{color}; '
        f'font-size:0.72rem; text-decoration:none; border:1px solid {color}33; '
        f'border-radius:4px; padding:2px 8px;">{html.escape(name)} ↗</a>'
        for name, url in r.links.items()
    ])

    pe_display = f"{r.pe:.1f}" if r.pe < 9000 else "—"
    pe_note = f" ({html.escape(r.pe_label)})" if r.pe_label and r.pe < 9000 else ""
    mcap = _fmt(int(r.mkt_cap_cr) if r.mkt_cap_cr else None, " Cr")

    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {color};
                border-radius:8px; padding:18px 20px; margin-bottom:18px;'>
        <div style='font-size:0.72rem; color:#7abeac;'>{html.escape(r.exchange_line)}</div>
        <div style='font-family:"IBM Plex Mono",monospace; font-size:0.78rem; color:{color};
                    font-weight:700; margin-top:4px;'>{html.escape(r.badge)}</div>
        <div style='display:flex; align-items:baseline; gap:12px; margin-top:14px; flex-wrap:wrap;'>
            <span style='font-family:"IBM Plex Mono",monospace; font-size:0.85rem; color:#a3d8b8;'>#{rank}</span>
            <span style='font-family:"IBM Plex Mono",monospace; font-size:1.35rem; font-weight:700; color:#e8f7ef;'>
                {html.escape(r.ticker)}</span>
            <span style='font-family:"IBM Plex Mono",monospace; font-size:1.2rem; color:#e8f7ef;'>
                {html.escape(r.currency)}{r.price:,.0f}</span>
            <span style='font-size:0.78rem; color:#a3d8b8;'>PE {pe_display} · Vol {r.vol_ratio:.2f}× ·
                RSI {r.rsi:.1f} · <span style='color:{color}; font-weight:700;'>Score {r.score:.1f}</span></span>
        </div>
        <div style='display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:14px;'>
            <div style='background:#16352c; border:1px solid #1a3b31; border-radius:8px; padding:12px 14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>Should you buy?</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem; font-weight:700;
                            color:{_buy_action_color(r.buy_action)}; margin-top:6px;'>
                    {html.escape(r.buy_action)}</div>
            </div>
            <div style='background:#16352c; border:1px solid #2e2a14; border-radius:8px; padding:12px 14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>Precautions</div>
                <div style='font-size:0.76rem; color:#e8f7ef; margin-top:6px; line-height:1.55;'>
                    {html.escape(r.precautions)}</div>
            </div>
        </div>
        <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap:14px; margin-top:18px;'>
            <div style='background:#16352c; border:1px solid #1a3b31; border-radius:8px; padding:14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>PRICE SNAPSHOT</div>
                <div style='font-size:0.78rem; color:#e8f7ef; margin-top:10px; line-height:1.7;'>
                    <b style='color:#a3d8b8;'>Today range</b><br>
                    {html.escape(r.currency)}{r.today_low:,.0f} – {html.escape(r.currency)}{r.today_high:,.0f}<br>
                    <b style='color:#a3d8b8;'>52-week range</b><br>
                    {html.escape(r.currency)}{r.week52_low:,.0f} – {html.escape(r.currency)}{r.week52_high:,.0f}<br>
                    <b style='color:#a3d8b8;'>50 DMA</b><br>
                    {html.escape(r.currency)}{r.dma50:,.0f} ({_pct(r.dma50_pct)})<br>
                    <b style='color:#a3d8b8;'>200 DMA</b><br>
                    {html.escape(r.currency)}{r.dma200:,.0f} ({_pct(r.dma200_pct)})<br>
                    <b style='color:#a3d8b8;'>1-year return</b><br>{_pct(r.return_1y_pct)}
                </div>
            </div>
            <div style='background:#16352c; border:1px solid #1a3b31; border-radius:8px; padding:14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>VALUATION</div>
                <div style='font-size:0.78rem; color:#e8f7ef; margin-top:10px; line-height:1.7;'>
                    <b style='color:#a3d8b8;'>PE (TTM)</b><br>{pe_display}{pe_note}<br>
                    <b style='color:#a3d8b8;'>PB</b><br>{_fmt(r.pb, "×")}<br>
                    <b style='color:#a3d8b8;'>EPS</b><br>
                    {html.escape(r.currency) if r.eps else ""}{_fmt(r.eps)}<br>
                    <b style='color:#a3d8b8;'>Mkt cap</b><br>{mcap}<br>
                    <b style='color:#a3d8b8;'>Div yield</b><br>{_fmt(r.div_yield, "%")}
                </div>
            </div>
            <div style='background:#16352c; border:1px solid #1a3b31; border-radius:8px; padding:14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>FUNDAMENTALS</div>
                <div style='font-size:0.78rem; color:#e8f7ef; margin-top:10px; line-height:1.7;'>
                    <b style='color:#a3d8b8;'>Revenue growth</b><br>{_pct(r.rev_growth_pct)} YoY<br>
                    <b style='color:#a3d8b8;'>Profit margin</b><br>{_fmt(r.profit_margin, "%")}<br>
                    <b style='color:#a3d8b8;'>EBITDA margin</b><br>{_fmt(r.ebitda_margin, "%")}<br>
                    <b style='color:#a3d8b8;'>ROE</b><br>{_fmt(r.roe, "%")}<br>
                    <b style='color:#a3d8b8;'>Debt/equity</b><br>{html.escape(r.debt_equity or "—")}
                </div>
            </div>
            <div style='background:#16352c; border:1px solid #1a3b31; border-radius:8px; padding:14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>SCORE BREAKDOWN /100</div>
                <div style='margin-top:10px;'>{bars_html}</div>
            </div>
            <div style='background:#16352c; border:1px solid #1a3b31; border-radius:8px; padding:14px;'>
                <div style='font-size:0.68rem; color:#a3d8b8; text-transform:uppercase;'>TECHNICAL SIGNALS</div>
                <div style='display:flex; gap:16px; margin-top:10px; flex-wrap:wrap; font-size:0.78rem;'>
                    <div><span style='color:#a3d8b8;'>Daily</span><br>
                        <span style='color:{_signal_color(r.signal_daily)}; font-weight:700;'>
                        {html.escape(r.signal_daily)}</span></div>
                    <div><span style='color:#a3d8b8;'>Weekly</span><br>
                        <span style='color:{_signal_color(r.signal_weekly)}; font-weight:700;'>
                        {html.escape(r.signal_weekly)}</span></div>
                    <div><span style='color:#a3d8b8;'>Monthly</span><br>
                        <span style='color:{_signal_color(r.signal_monthly)}; font-weight:700;'>
                        {html.escape(r.signal_monthly)}</span></div>
                </div>
                <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:12px;'>{flags_html}</div>
            </div>
        </div>
        <div style='margin-top:14px;'>{links_html}</div>
    </div>
    """)


def no_high_profit_state(archetype_id: str) -> None:
    a = ARCHETYPES[archetype_id]
    st.html(f"""
    <div style='background:#122f25; border:1px dashed #1a3b31;
                border-radius:12px; padding:50px 40px; text-align:center;'>
        <div style='font-size:2.5rem; margin-bottom:14px;'>{html.escape(a["emoji"])}</div>
        <div style='font-family:"IBM Plex Mono",monospace; color:#7abeac; font-size:1rem;'>
            No names in <b style='color:{a["color"]};'>{html.escape(nav_title(archetype_id))}</b> passed live filters right now.
        </div>
        <div style='color:#6a9d8a; font-size:0.8rem; margin-top:8px;'>
            Try again after market hours, or review the curated watchlist for this archetype.
        </div>
    </div>
    """)
