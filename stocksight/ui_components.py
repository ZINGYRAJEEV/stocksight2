"""
ui_components.py — Shared UI helpers for all signal pages.
"""

import html
import hashlib
from datetime import datetime

import streamlit as st
import pandas as pd

from signals import SignalResult, SCENARIOS, enrich_results_news
from watchlist_store import add_to_watchlist, load_watchlist, remove_from_watchlist


INTERVAL_LABELS = {"1d": "Daily", "1h": "1 Hour", "15m": "15 Minute"}
def safe_set_page_config(**kwargs) -> None:
    """Call set_page_config once per session; ignore repeats (e.g. under st.navigation)."""
    try:
        st.set_page_config(**kwargs)
    except st.errors.StreamlitAPIException:
        pass


# ─────────────────────────────────────────────
# Page-level CSS (call once per page)
# ─────────────────────────────────────────────

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

:root {
    color-scheme: light;
    --app-bg: #f8fafc;
    --app-text: #111827;
    --button-bg: linear-gradient(135deg,#25d366,#1aa34b);
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background-color: var(--app-bg);
    color: var(--app-text);
}
.stButton > button {
    background: var(--button-bg);
    color: #000; font-family:'IBM Plex Mono',monospace;
    font-weight:700; font-size:0.82rem; border:none; border-radius:6px;
    padding:10px 24px; letter-spacing:1px; text-transform:uppercase;
    cursor:pointer; width:100%;
}
.stButton > button:hover { opacity:0.92; }
[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #d4d4d4; color:#111827; }
[data-testid="stSidebar"] label { color:#111827 !important; font-size:0.8rem; }
.stProgress > div > div { background-color:#25d366; }
hr { border-color:#d4d4d4 !important; }
</style>
"""


def inject_css():
    st.markdown(BASE_CSS, unsafe_allow_html=True)


def scenario_advanced_panel(key_prefix: str) -> dict:
    """Shared controls for scenario scans — returns kwargs-compatible dict (+ UI-only keys)."""
    with st.expander("Advanced — bars, sector, MACD / Bollinger, headlines", expanded=False):
        interval_key = st.selectbox(
            "Bar interval",
            options=["1d", "1h", "15m"],
            format_func=lambda x: INTERVAL_LABELS.get(x, x),
            key=f"{key_prefix}_interval",
        )
        sector_filter = st.text_input(
            "Sector filter (substring, optional)",
            "",
            key=f"{key_prefix}_sector",
            placeholder="e.g. Financial Services, Technology",
        )
        require_macd_bullish = st.checkbox(
            "Require MACD histogram > 0",
            value=False,
            key=f"{key_prefix}_macd",
        )
        require_bb_touch_lower = st.checkbox(
            "Require touch / near lower Bollinger band",
            value=False,
            key=f"{key_prefix}_bb",
        )
        fetch_news = st.checkbox(
            "Fetch recent Yahoo headlines for matches (extra calls)",
            value=False,
            key=f"{key_prefix}_news",
        )
        portfolio_for_sizing = st.number_input(
            "Portfolio value for ~1% risk share count (optional, same currency as quote)",
            min_value=0.0,
            value=0.0,
            step=100000.0,
            key=f"{key_prefix}_pf",
        )

    sf = sector_filter.strip() or None
    return {
        "sector_filter": sf,
        "interval_key": interval_key,
        "require_macd_bullish": require_macd_bullish,
        "require_bb_touch_lower": require_bb_touch_lower,
        "fetch_news": fetch_news,
        "portfolio_for_sizing": portfolio_for_sizing,
    }


def maybe_enrich_news(results: list[SignalResult], enabled: bool, max_names: int = 35) -> None:
    if not enabled or not results:
        return
    if len(results) > max_names:
        st.warning(f"Headlines skipped — more than {max_names} matches (too many Yahoo calls). Narrow filters or disable headlines.")
        return
    enrich_results_news(results)


def render_watchlist_panel(key_prefix: str) -> None:
    with st.expander("★ Watchlist (saved on server)", expanded=False):
        rows = load_watchlist()
        if rows:
            st.caption(f"{len(rows)} symbol(s) saved — stored in `stocksight/.watchlist.json`.")
            for r in rows:
                sym = r.get("raw_ticker", "")
                note = r.get("note", "")
                cc = st.columns([4, 1])
                with cc[0]:
                    st.markdown(f"**{sym.replace('.NS','')}** — _{note}_" if note else f"**{sym.replace('.NS','')}**")
                with cc[1]:
                    if st.button("Remove", key=f"{key_prefix}_rm_{hashlib.md5(sym.encode()).hexdigest()[:12]}"):
                        remove_from_watchlist(sym)
                        st.rerun()
        else:
            st.caption("Use ★ Watchlist on a card to pin symbols here.")

        st.divider()
        manual = st.text_input("Add raw ticker (e.g. RELIANCE.NS or AAPL)", "", key=f"{key_prefix}_manual")
        if st.button("Add ticker", key=f"{key_prefix}_manual_add"):
            add_to_watchlist(manual.strip())
            st.rerun()


def signal_results_download(results: list[SignalResult], scenario_id: str, button_key: str = "dl") -> None:
    if not results:
        return
    rows = []
    for r in results:
        rows.append({
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Interval": r.data_interval,
            "Sector": r.sector or "",
            "Signal": r.signal_label,
            "Price": r.price,
            "PE": r.pe,
            "Vol×": r.vol_ratio,
            "RSI": r.rsi,
            "MACD_hist": r.macd_hist,
            "% vs MA20": r.pct_vs_ma20,
            "MA20x50_cross": r.golden_cross_recent,
            "%B_BB": r.bb_pct_b,
            "ATR14": r.atr14,
            "Next_Earnings": r.next_earnings or "",
            "Entry": r.entry,
            "Stop": r.stop_loss,
            "T2": r.target2,
            "Confidence": r.confidence,
        })
    df = pd.DataFrame(rows)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇ Download results CSV",
        csv,
        file_name=f"stocksight_{scenario_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"{button_key}_csv_{scenario_id}",
    )


# ─────────────────────────────────────────────
# Scenario header banner
# ─────────────────────────────────────────────

def scenario_header(scenario_id: str):
    s = SCENARIOS[scenario_id]
    signal_colors = {
        "BUY":           ("#00e5a0", "#0a2e1e"),
        "SELL":          ("#ff4d4d", "#2e0a0a"),
        "CAUTIOUS BUY":  ("#ff9d42", "#2e1a00"),
        "WAIT":          ("#a0a0a0", "#1a1a1a"),
    }
    sig   = s["signal"]
    fc, bc = signal_colors.get(sig, ("#ffffff", "#1a1a1a"))

    # Use st.html so indented markup is not parsed as a Markdown code block.
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {s["color"]};
                border-radius:8px; padding:20px 24px; margin-bottom:20px;'>
        <div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap;'>
            <span style='font-size:2rem;'>{s["emoji"]}</span>
            <div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1.3rem;
                            font-weight:700; color:#e8f7ef;'>{html.escape(s["title"])}</div>
                <div style='font-size:0.82rem; color:#a3d8b8; margin-top:3px;'>
                    {html.escape(s["description"])}
                </div>
            </div>
            <div style='margin-left:auto;
                        background:{bc}; border:1px solid {fc};
                        border-radius:20px; padding:5px 16px;
                        font-family:"IBM Plex Mono",monospace;
                        font-size:0.78rem; font-weight:700; color:{fc};
                        white-space:nowrap;'>
                {html.escape(sig)}
            </div>
        </div>
        <div style='display:flex; gap:24px; margin-top:14px; flex-wrap:wrap;'>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Entry Trigger</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{html.escape(s["entry_note"])}</div>
            </div>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Stop Loss</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{html.escape(s["sl_note"])}</div>
            </div>
            <div style='flex:1; min-width:180px; background:#16352c;
                        border:1px solid #1a3b31; border-radius:6px; padding:10px 14px;'>
                <div style='font-size:9px; color:#a3d8b8; text-transform:uppercase;
                            letter-spacing:1.5px; margin-bottom:5px;'>Targets</div>
                <div style='font-size:0.78rem; color:#e8f7ef;'>{html.escape(s["target_note"])}</div>
            </div>
        </div>
    </div>
    """)


# ─────────────────────────────────────────────
# Trade plan card — one card per stock
# ─────────────────────────────────────────────

def trade_plan_card(r: SignalResult, scenario_id: str, portfolio_value: float = 0.0):
    s       = SCENARIOS[scenario_id]
    color   = s["color"]
    is_sell = r.signal_label in ("SELL / AVOID", "SELL")
    is_wait = r.signal_label in ("HOLD / WAIT", "WAIT")

    conf_color = {"HIGH": "#25d366", "MEDIUM": "#f0b429", "LOW": "#e05252"}.get(r.confidence, "#a0a0a0")

    # Candle flags
    candle_html = ""
    if r.is_green:
        candle_html += '<span style="color:#25d366; font-size:0.72rem;">● Green candle</span> &nbsp;'
    if r.reversal:
        candle_html += '<span style="color:#25d366; font-size:0.72rem;">↑ Reversal</span> &nbsp;'
    if r.rsi_rising:
        candle_html += f'<span style="color:#4db8ff; font-size:0.72rem;">RSI rising ({r.rsi_prev}→{r.rsi})</span>'
    else:
        candle_html += f'<span style="color:#ff9d42; font-size:0.72rem;">RSI flat/falling ({r.rsi_prev}→{r.rsi})</span>'

    macd_part = "—"
    if r.macd_hist is not None:
        macd_part = f"{r.macd_hist:.4f}"
    ma_part = "—"
    if r.pct_vs_ma20 is not None:
        ma_part = f"{r.pct_vs_ma20:+.1f}%"
        if r.golden_cross_recent:
            ma_part += " · MA20×50"
    bb_part = "—"
    if r.bb_pct_b is not None:
        bb_part = f"{r.bb_pct_b:.2f}"
        if r.bb_touch_lower:
            bb_part += " · near lower"
    atr_part = "—"
    if r.atr14 is not None:
        atr_part = f"{r.atr14:.4f}"

    sector_part = html.escape(r.sector) if r.sector else "—"
    earn_part = html.escape(r.next_earnings) if r.next_earnings else "—"
    interval_part = html.escape(r.data_interval or "1d")

    extras_html = f"""
        <div style='margin-top:10px; padding-top:8px; border-top:1px dashed #1a3b31;
                    font-family:"IBM Plex Mono",monospace; font-size:0.72rem; color:#b8e7c7; line-height:1.7;'>
            <span style='color:#a3d8b8;'>Bars</span> {interval_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Sector</span> {sector_part}<br>
            <span style='color:#a3d8b8;'>MACD hist</span> {macd_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>% vs MA20</span> {ma_part}<br>
            <span style='color:#a3d8b8;'>%B</span> {bb_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>ATR14</span> {atr_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Earnings</span> {earn_part}
        </div>
        """

    sizing_html = ""
    if not is_sell and not is_wait and portfolio_value and portfolio_value > 0:
        risk_per_share = abs(float(r.price) - float(r.stop_loss))
        if risk_per_share > 0:
            qty = int((portfolio_value * 0.01) // risk_per_share)
            sizing_html = f"""
            <div style='margin-top:8px; font-size:0.72rem; color:#f0b429;
                        font-family:"IBM Plex Mono",monospace;'>
                ~1% portfolio risk sizing: <b>{qty}</b> shares @ risk/share {html.escape(r.currency)}{risk_per_share:,.2f}
            </div>
            """

    news_html = ""
    if r.news_headlines:
        lis = "".join(f"<li style='margin:3px 0;'>{html.escape(t)}</li>" for t in r.news_headlines[:5])
        news_html = f"<div style='margin-top:10px;font-size:0.72rem;color:#c8d8e8;'><b>Headlines</b><ul style='margin:6px 0 0 18px;'>{lis}</ul></div>"
    if is_sell:
        levels_html = f"""
        <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #2e1414;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Entry (current)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#e8f7ef; font-weight:700;'>{r.currency}{r.entry:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T1 (−3%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff9d42; font-weight:600;'>{r.currency}{r.target1:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T2 (−7%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff4d4d; font-weight:600;'>{r.currency}{r.target2:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1a3b31;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>T3 (−12%)</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff4d4d; font-weight:600;'>{r.currency}{r.target3:,.2f}</div>
            </div>
        </div>
        """
    elif is_wait:
        levels_html = f"""
        <div style='background:#16352c; border:1px dashed #2a2a2a; border-radius:5px;
                    padding:10px 14px; margin-top:10px; font-size:0.78rem; color:#a3d8b8;'>
            ⏸️ Pre-calculated levels (activate only on confirmation)<br>
            <span style='color:#7abeac;'>Entry zone:</span> {r.currency}{r.entry:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>SL:</span> {r.currency}{r.stop_loss:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>T1:</span> {r.currency}{r.target1:,.2f} &nbsp;|&nbsp;
            <span style='color:#7abeac;'>T2:</span> {r.currency}{r.target2:,.2f}
        </div>
        """
    else:
        levels_html = f"""
        <div style='display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;'>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c3020;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Entry</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#e8f7ef; font-weight:700;'>{r.currency}{r.entry:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #2e1414;'>
                <div style='font-size:9px; color:#e05252; letter-spacing:1px;
                            text-transform:uppercase;'>Stop Loss</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#ff6b6b; font-weight:600;'>{r.currency}{r.stop_loss:,.2f}</div>
                <div style='font-size:9px; color:#a3d8b8; margin-top:2px;'>
                    Risk {r.risk_pct:.1f}%</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 1</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#7ed4a0; font-weight:600;'>{r.currency}{r.target1:,.2f}</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 2</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#25d366; font-weight:700;'>{r.currency}{r.target2:,.2f}</div>
                <div style='font-size:9px; color:#a3d8b8; margin-top:2px;'>
                    RRR {r.rrr:.1f}×</div>
            </div>
            <div style='flex:1; min-width:90px; background:#16352c; border-radius:5px;
                        padding:8px 10px; border:1px solid #1c2e1c;'>
                <div style='font-size:9px; color:#a3d8b8; letter-spacing:1px;
                            text-transform:uppercase;'>Target 3</div>
                <div style='font-family:"IBM Plex Mono",monospace; font-size:1rem;
                            color:#1aa34b; font-weight:700;'>{r.currency}{r.target3:,.2f}</div>
            </div>
        </div>
        """

    # Links — escape URLs (e.g. M&M.NS → & in query/path breaks raw HTML href attributes)
    links_html = " &nbsp;".join([
        f'<a href="{html.escape(url, quote=True)}" target="_blank" style="color:{color}; font-size:0.72rem; '
        f'text-decoration:none; border:1px solid {color}33; border-radius:4px; '
        f'padding:2px 8px;">{html.escape(name)} ↗</a>'
        for name, url in r.links.items()
    ])

    safe_ticker = html.escape(r.ticker)
    safe_note = html.escape(r.note, quote=False)

    # st.html: indented lines are not interpreted as Markdown code fences (unlike st.markdown).
    st.html(f"""
    <div style='background:#122f25; border:1px solid #1a3b31;
                border-left:4px solid {color};
                border-radius:8px; padding:16px 18px; margin-bottom:14px;'>

        <div style='display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:8px;'>
            <div>
                <span style='font-family:"IBM Plex Mono",monospace; font-size:1.2rem;
                              font-weight:700; color:#e8f7ef;'>{safe_ticker}</span>
                <span style='font-family:"IBM Plex Mono",monospace; font-size:1.1rem;
                              color:#a3d8b8; margin-left:12px;'>{html.escape(r.currency)}{r.price:,.2f}</span>
            </div>
            <div style='display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                <span style='font-size:9px; background:{conf_color}22; border:1px solid {conf_color}55;
                              color:{conf_color}; border-radius:12px; padding:2px 10px;
                              font-weight:700; letter-spacing:1px;'>
                    {html.escape(r.confidence)} CONFIDENCE
                </span>
                <span style='font-size:9px; color:#a3d8b8; font-family:"IBM Plex Mono",monospace;'>
                    ⏱ {html.escape(r.timeframe)}
                </span>
            </div>
        </div>

        <div style='display:flex; gap:20px; margin-top:10px; flex-wrap:wrap;
                    font-family:"IBM Plex Mono",monospace; font-size:0.78rem;'>
            <span><span style='color:#a3d8b8;'>PE  </span>{r.pe:.1f}×</span>
            <span><span style='color:#a3d8b8;'>VOL </span>{r.vol_ratio:.2f}×&nbsp;avg</span>
            <span><span style='color:#a3d8b8;'>RSI </span>{r.rsi:.1f}</span>
        </div>

        <div style='margin-top:8px;'>{candle_html}</div>

        {extras_html}

        {levels_html}

        {sizing_html}

        {news_html}

        <div style='margin-top:12px; font-size:0.75rem; color:#7abeac;
                    border-top:1px solid #1a3b31; padding-top:8px;'>
            💡 {safe_note}
        </div>

        <div style='margin-top:10px;'>{links_html}</div>
    </div>
    """)

    uid = hashlib.md5(f"{scenario_id}|{r.raw_ticker}".encode("utf-8")).hexdigest()[:16]
    if st.button("★ Watchlist", key=f"wl_add_{uid}"):
        add_to_watchlist(r.raw_ticker)
        try:
            st.toast(f"Saved {r.ticker}", icon="★")
        except Exception:
            st.success(f"Saved {r.ticker}")


# ─────────────────────────────────────────────
# Results table (compact summary)
# ─────────────────────────────────────────────

def results_table(results: list[SignalResult], scenario_id: str):
    if not results:
        return

    rows = []
    for r in results:
        rows.append({
            "Ticker":       r.ticker,
            "Bars":         r.data_interval,
            "Sector":       r.sector or "—",
            "Price":        r.price,
            "PE":           r.pe,
            "Vol×":         r.vol_ratio,
            "RSI":          r.rsi,
            "MACD hist":    r.macd_hist if r.macd_hist is not None else None,
            "% vs MA20":    r.pct_vs_ma20 if r.pct_vs_ma20 is not None else None,
            "MA20×50":      "✓" if r.golden_cross_recent else "—",
            "%B":           r.bb_pct_b if r.bb_pct_b is not None else None,
            "ATR14":        r.atr14 if r.atr14 is not None else None,
            "Earnings":     r.next_earnings or "—",
            "RSI Rising":   "↑" if r.rsi_rising else "→/↓",
            "Green Candle": "✅" if r.is_green else "—",
            "Reversal":     "✅" if r.reversal  else "—",
            "Entry":        r.entry,
            "Stop Loss":    r.stop_loss,
            "Target 2":     r.target2,
            "Risk %":       r.risk_pct,
            "Confidence":   r.confidence,
        })

    df = pd.DataFrame(rows)

    link_cols_nse = ["Yahoo Finance", "Moneycontrol", "TradingView"]
    link_cols_us  = ["Yahoo Finance", "MarketWatch",  "TradingView"]

    # Add first available link set
    if results:
        for name, url in results[0].links.items():
            col_name = name
            df[col_name] = [r.links.get(name, "") for r in results]

    col_cfg = {
        "Price":        st.column_config.NumberColumn("Price", format="%.2f"),
        "PE":           st.column_config.NumberColumn("PE", format="%.1f"),
        "Vol×":         st.column_config.NumberColumn("Vol×", format="%.2f"),
        "RSI":          st.column_config.NumberColumn("RSI", format="%.1f"),
        "MACD hist":    st.column_config.NumberColumn("MACD hist", format="%.4f"),
        "% vs MA20":    st.column_config.NumberColumn("% vs MA20", format="%.2f"),
        "%B":           st.column_config.NumberColumn("%B", format="%.3f"),
        "ATR14":        st.column_config.NumberColumn("ATR14", format="%.4f"),
        "Entry":        st.column_config.NumberColumn("Entry", format="%.2f"),
        "Stop Loss":    st.column_config.NumberColumn("Stop", format="%.2f"),
        "Target 2":     st.column_config.NumberColumn("Target 2", format="%.2f"),
        "Risk %":       st.column_config.NumberColumn("Risk %", format="%.1f%%"),
    }
    # Link columns
    for name in (link_cols_nse + link_cols_us):
        if name in df.columns:
            col_cfg[name] = st.column_config.LinkColumn(name, display_text="Open ↗")

    st.dataframe(
        df, use_container_width=True,
        column_config=col_cfg,
        hide_index=True,
        height=min(500, 50 + len(df) * 38),
    )


# ─────────────────────────────────────────────
# Empty / no-results state
# ─────────────────────────────────────────────

def no_results_state(scenario_id: str):
    s = SCENARIOS[scenario_id]
    st.html(f"""
    <div style='background:#122f25; border:1px dashed #1a3b31;
                border-radius:12px; padding:50px 40px; text-align:center;'>
        <div style='font-size:2.5rem; margin-bottom:14px;'>{html.escape(s["emoji"])}</div>
        <div style='font-family:"IBM Plex Mono",monospace; color:#7abeac; font-size:1rem;'>
            No stocks currently match the <b style='color:{s["color"]};'>{html.escape(s["title"])}</b> criteria.
        </div>
        <div style='color:#6a9d8a; font-size:0.8rem; margin-top:8px;'>
            Markets may not have triggered this pattern today — check again at market open or close.
        </div>
    </div>
    """)
