"""Market Mood — India (NSE) and US tape on one screen."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from market_sentiment import (
    MacroContext,
    cross_market_read,
    get_global_gauges,
    get_macro_context,
    mood_emoji,
    vix_bucket,
)
from ui_components import inject_css, page_audience_note, safe_set_page_config

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")

_TONE_COLOR = {
    "Bullish": "#25d366",
    "Neutral": "#f0b429",
    "Bearish": "#ff6b6b",
}


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _fmt_num(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def _tone_card(title: str, ctx: MacroContext, *, india: bool) -> None:
    tone = ctx.macro_tone or "Neutral"
    color = _TONE_COLOR.get(tone, "#f0b429")
    emoji = mood_emoji(tone)
    vix_name = "India VIX" if india else "VIX"
    vix_reg = vix_bucket(ctx.vix_level, india=india)
    clock = datetime.now(IST if india else ET).strftime("%H:%M")
    tz = "IST" if india else "ET"

    rows: list[str] = []
    if india:
        rows.append(f"<b>Nifty</b> {_fmt_pct(ctx.nifty_pct)}")
        rows.append(f"<b>Bank Nifty</b> {_fmt_pct(ctx.bank_nifty_pct)}")
    else:
        rows.append(f"<b>S&amp;P (SPY)</b> {_fmt_pct(ctx.spy_pct)}")
        rows.append(f"<b>Nasdaq (QQQ)</b> {_fmt_pct(ctx.qqq_pct)}")
    rows.append(f"<b>{vix_name}</b> {_fmt_num(ctx.vix_level)} · {html.escape(vix_reg)}")

    fii_html = ""
    if india and ctx.fii_note:
        fii_html = (
            f"<div style='margin-top:10px;font-size:0.78rem;color:#a3d8b8;'>"
            f"<b>FII/DII</b> {html.escape(str(ctx.fii_note)[:180])}</div>"
        )

    st.markdown(
        f"""
<div style='background:#122f25;border:1px solid {color}55;border-radius:10px;
            padding:18px 18px 14px;min-height:240px;'>
  <div style='font-family:"IBM Plex Mono",monospace;font-size:0.72rem;letter-spacing:1.4px;
              text-transform:uppercase;color:#7abeac;'>{html.escape(title)} · {tz} {clock}</div>
  <div style='margin-top:8px;font-size:1.85rem;font-weight:700;color:{color};'>
    {emoji} {html.escape(tone)}
  </div>
  <div style='margin-top:12px;font-size:0.88rem;color:#e8f7ef;line-height:1.75;'>
    {" &nbsp;·&nbsp; ".join(rows)}
  </div>
  <div style='margin-top:10px;font-size:0.8rem;color:#c8d8e8;line-height:1.5;'>
    {html.escape(ctx.macro_detail or "—")}
  </div>
  {fii_html}
</div>
""",
        unsafe_allow_html=True,
    )


def render_market_mood_page() -> None:
    safe_set_page_config(page_title="Market Mood | StockSight", page_icon="🌡️", layout="wide")
    inject_css()
    st.markdown("### 🌡️ Market mood — India & US")
    page_audience_note(
        "Traders who want a single glance at **NSE vs US** risk appetite before scanning stocks.",
        "Macro tone from Nifty / Bank Nifty / India VIX / FII (India) and SPY / QQQ / VIX (US), "
        "plus USD-INR, dollar index, US 10Y, crude, and gold. Educational snapshot — not a trade signal.",
    )

    c_btn, _ = st.columns([1, 4])
    with c_btn:
        refresh = st.button("Refresh tape", type="primary", use_container_width=True, key="mood_refresh")

    with st.spinner("Loading India + US macro…"):
        india = get_macro_context("NSE", force_refresh=refresh)
        us = get_macro_context("US", force_refresh=refresh)
        gauges = get_global_gauges(force_refresh=refresh)

    read = cross_market_read(india.macro_tone, us.macro_tone)
    st.info(f"**Cross-read:** {read}")

    left, right = st.columns(2, gap="large")
    with left:
        _tone_card("India · NSE", india, india=True)
    with right:
        _tone_card("United States", us, india=False)

    st.markdown("#### Global gauges")
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("USD / INR", _fmt_num(gauges.usd_inr_last, 2), _fmt_pct(gauges.usd_inr_pct))
    g2.metric("DXY", _fmt_num(gauges.dxy_last, 1), _fmt_pct(gauges.dxy_pct))
    g3.metric("US 10Y", _fmt_num(gauges.us10y_last, 2) + ("%" if gauges.us10y_last else ""), _fmt_pct(gauges.us10y_pct))
    g4.metric("Crude", _fmt_pct(gauges.crude_pct), None)
    g5.metric("Gold", _fmt_pct(gauges.gold_pct), None)
    st.caption(gauges.detail)

    with st.expander("How this score is built", expanded=False):
        st.markdown(
            """
**India:** Nifty day change (±0.5%), Bank Nifty vs Nifty (±0.3% leadership), FII net (when NSE publishes it), India VIX bands.

**US:** SPY day change (±0.5%), Nasdaq leadership vs SPY (shown in the detail line), CBOE VIX bands.

**VIX:** high VIX pulls the tone toward Bearish; very low VIX can nudge Bullish. Same engine as scan-result **Macro** columns.

**Reliability:** Yahoo daily bars (often last close if the session is closed). FII is India-only and can lag. USD-INR / DXY / 10Y / crude / gold are **context**, not part of the Bullish/Neutral/Bearish score.

Not financial advice — confirm on the exchange tape before acting.
"""
        )


if __name__ == "__main__":
    render_market_mood_page()
