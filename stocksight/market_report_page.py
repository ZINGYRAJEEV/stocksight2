"""Native Streamlit U.S. market dashboard backed by the app's cached Yahoo history."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

try:
    from screener import fetch_price_history
    from ui_components import inject_css, safe_set_page_config
except ImportError:
    from .screener import fetch_price_history  # type: ignore
    from .ui_components import inject_css, safe_set_page_config  # type: ignore


ASSETS = {
    "S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
    "10Y Treasury": "^TNX", "30Y Treasury": "^TYX", "WTI Crude": "CL=F",
    "Gold": "GC=F", "Bitcoin": "BTC-USD",
}


@st.cache_data(ttl=60, show_spinner=False)
def _quotes() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, symbol in ASSETS.items():
        try:
            hist = fetch_price_history(symbol, "1d")
            close = pd.to_numeric(hist.get("Close"), errors="coerce").dropna() if hist is not None else pd.Series(dtype=float)
            if len(close) < 2:
                result[name] = {"available": False}
                continue
            last, previous = float(close.iloc[-1]), float(close.iloc[-2])
            result[name] = {
                "available": True, "value": last, "change": last - previous,
                "pct": (last / previous - 1) * 100, "low": float(close.min()),
                "high": float(close.max()), "series": close.tail(30),
                "wtd": (last / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else None,
                "ytd": (last / float(close.iloc[0]) - 1) * 100,
            }
        except Exception:
            result[name] = {"available": False}
    return result


def _fmt(value: object, digits: int = 2) -> str:
    return f"{float(value):,.{digits}f}" if isinstance(value, (float, int)) else "—"


def _delta(value: object) -> str:
    return f"{float(value):+.2f}%" if isinstance(value, (float, int)) else "—"


def _sentiment(vix: object) -> tuple[str, int]:
    level = float(vix) if isinstance(vix, (float, int)) else 20.0
    score = max(0, min(100, round(100 - level * 3)))
    return ("Greed" if score >= 65 else "Fear" if score <= 35 else "Neutral", score)


def _metric_card(name: str, quote: dict[str, object]) -> None:
    if not quote.get("available"):
        st.metric(name, "Unavailable")
        return
    pct = float(quote["pct"])
    st.metric(name, _fmt(quote["value"]), f"{pct:+.2f}% ({float(quote['change']):+.2f})")
    series = quote.get("series")
    if isinstance(series, pd.Series):
        st.line_chart(series, height=70, use_container_width=True)
    st.caption(f"52W  {_fmt(quote['low'])} — {_fmt(quote['high'])}")


def render_market_report_page() -> None:
    safe_set_page_config(page_title="U.S. Market Report | StockSight", page_icon="🇺🇸", layout="wide")
    inject_css()
    quotes = _quotes()
    now = datetime.now(ZoneInfo("America/New_York"))
    market_status = "MARKET OPEN" if now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0) else "MARKET CLOSE"
    st.html("""
    <div style='background:#121824;border:1px solid #1E2638;border-radius:14px;padding:20px 24px;margin-bottom:16px;'>
      <div style='font-size:.72rem;font-weight:700;letter-spacing:.13em;color:#91a4c4;'>🇺🇸 UNITED STATES</div>
      <div style='display:flex;gap:16px;align-items:end;justify-content:space-between;flex-wrap:wrap;'>
        <div style='font-size:1.7rem;font-weight:800;color:#edf3ff;'>U.S. MARKET REPORT</div>
        <div style='border:1px solid #34d39955;color:#34d399;background:#34d39912;padding:5px 10px;border-radius:99px;font-size:.75rem;font-weight:700;'>LIVE / DELAYED FREE DATA</div>
      </div>
    </div>""")
    st.caption(f"As of {now.strftime('%d %b %Y, %H:%M %Z')} · {market_status} · Refreshes on page reload; quotes are cached for 60 seconds.")

    index_names = ("S&P 500", "Dow Jones", "Nasdaq")
    cols = st.columns([1, 1, 1, 1.15, .9])
    for col, name in zip(cols[:3], index_names):
        with col:
            _metric_card(name, quotes[name])
    vix_value = quotes["VIX"].get("value")
    label, score = _sentiment(vix_value)
    with cols[3]:
        st.markdown("#### Today at a glance")
        positive = sum(1 for name in index_names if isinstance(quotes[name].get("pct"), float) and quotes[name]["pct"] > 0)
        st.markdown(f"- **{positive}/3** major indices are higher today.")
        st.markdown(f"- VIX: **{_fmt(vix_value, 1)}** — {label.lower()} risk backdrop.")
        st.markdown("- Check earnings and macro releases before acting on momentum.")
    with cols[4]:
        st.markdown("#### Market sentiment")
        st.progress(score, text=f"{label} · {score}/100")
        st.caption("VIX-derived gauge; not CNN Fear & Greed.")

    st.markdown("### Market indicators")
    indicators = ("10Y Treasury", "30Y Treasury", "WTI Crude", "Gold", "VIX", "Bitcoin")
    for row in (indicators[:3], indicators[3:]):
        columns = st.columns(3)
        for column, name in zip(columns, row):
            with column:
                _metric_card(name, quotes[name])

    st.markdown("### Major indices")
    rows = []
    for name in index_names:
        q = quotes[name]
        rows.append({"Index": name, "Last": q.get("value"), "Today %": q.get("pct"), "Points": q.get("change"), "WTD %": q.get("wtd"), "YTD %": q.get("ytd")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 column_config={"Last": st.column_config.NumberColumn(format="%.2f"), "Today %": st.column_config.NumberColumn(format="%+.2f%%"), "Points": st.column_config.NumberColumn(format="%+.2f"), "WTD %": st.column_config.NumberColumn(format="%+.2f%%"), "YTD %": st.column_config.NumberColumn(format="%+.2f%%")})
    index_pct = [float(quotes[name].get("pct") or 0) for name in index_names]
    one_line = "Risk appetite is constructive" if sum(value > 0 for value in index_pct) >= 2 else "Market leadership is mixed" if any(value > 0 for value in index_pct) else "The major-index tape is defensive"
    st.info(f"**TODAY IN ONE LINE:** {one_line}; VIX is {label.lower()} at {_fmt(vix_value, 1)}.")
    st.caption("Sources: Yahoo Finance via yfinance. Free data can be delayed, incomplete, or revised. Educational information only—not investment advice.")
