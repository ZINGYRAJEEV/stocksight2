"""
ui_components.py — Shared UI helpers for all signal pages.
"""

import html
import hashlib
from datetime import datetime

import streamlit as st
import pandas as pd
import numpy as np

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

try:
    from plotly.subplots import make_subplots
except ImportError:
    make_subplots = None

try:
    from .screener import (
        DECISION_ZONES,
        compute_score,
        decision_from_metrics,
        fetch_price_history,
        matrix_decision,
        matrix_decision_note,
        rsi_series_wilder,
        compute_vwap,
    )
    from .signals import SignalResult, SCENARIOS, enrich_results_news, scenario_display_title
    from .scan_history_store import append_scan_record, build_first_seen_map
    from .watchlist_store import (
        add_to_watchlist,
        load_alert_prefs,
        load_watchlist,
        remove_from_watchlist,
        set_email_watchlist_alerts,
        upsert_watchlist_fields,
    )
except ImportError:
    from screener import (
        DECISION_ZONES,
        compute_score,
        decision_from_metrics,
        fetch_price_history,
        matrix_decision,
        matrix_decision_note,
        rsi_series_wilder,
        compute_vwap,
    )
    from signals import SignalResult, SCENARIOS, enrich_results_news, scenario_display_title
    from scan_history_store import append_scan_record, build_first_seen_map
    from watchlist_store import (
        add_to_watchlist,
        load_alert_prefs,
        load_watchlist,
        remove_from_watchlist,
        set_email_watchlist_alerts,
        upsert_watchlist_fields,
    )


INTERVAL_LABELS = {"1d": "Daily", "1h": "1 Hour", "15m": "15 Minute"}


def scenario_page_alert_hint(nav_registry_key: str) -> str:
    """Human title for emails / banners from `SCENARIOS` sidebar registry key."""
    meta = SCENARIOS.get(nav_registry_key)
    if meta and isinstance(meta, dict) and meta.get("title"):
        return str(meta["title"])
    return str(nav_registry_key)


def first_seen_label(raw_ticker: str) -> str:
    """First calendar date this raw symbol appeared in `.scan_history.jsonl`, else —."""
    s = str(raw_ticker or "").strip()
    if not s:
        return "—"
    return build_first_seen_map().get(s, "—")


def safe_set_page_config(**kwargs) -> None:
    """Call set_page_config once per session; ignore repeats (e.g. under st.navigation)."""
    try:
        st.set_page_config(**kwargs)
    except st.errors.StreamlitAPIException:
        pass


def ensure_session_choice(key: str, choices: list, default: str | None = None) -> str:
    """Reset a widget session value when options were renamed (avoids Streamlit KeyError on Cloud)."""
    if not choices:
        return ""
    fallback = default if default is not None else choices[0]
    if st.session_state.get(key) not in choices:
        st.session_state[key] = fallback
    return str(st.session_state[key])


def filter_column_config(df: pd.DataFrame, column_config: dict) -> dict:
    """Streamlit raises KeyError if column_config references columns missing from df."""
    if df is None or df.empty:
        return {}
    cols = set(df.columns)
    return {k: v for k, v in column_config.items() if k in cols}


def page_audience_note(who_for: str, what_it_does: str) -> None:
    """Short guidance block: intended user and what the page does."""
    st.info(
        f"**Who this is for:** {who_for}\n\n"
        f"**What it does:** {what_it_does}"
    )


def render_decision_matrix_legend() -> None:
    """Reference key for Decision / Matrix note columns shown after scans."""
    with st.expander("📊 Buy / Sell decision matrix (reference)", expanded=False):
        st.caption(
            "After each scan, **Decision** blends the scenario signal (when applicable) with the "
            "**Composite** score (PE + volume + RSI, 0–100). Same zones as **Buy / Hold / Avoid**."
        )
        for threshold, label, note in DECISION_ZONES:
            st.markdown(f"- **{label}** (composite ≥ {threshold:.0f}): {note}")
        st.markdown(
            "- **Sell / Trim** — Overbought / exit scenario or SELL signal.\n"
            "- **Cautious Buy** — Extreme oversold / cautious entry only.\n"
            "- **Neutral / Wait** — Volume spike without RSI confirmation or WAIT signal."
        )


def _decision_for_signal_result(r: SignalResult) -> tuple[str, float, str]:
    dec, comp, note = decision_from_metrics(
        r.pe,
        r.vol_ratio,
        r.rsi,
        signal_label=r.signal_label,
        scenario_id=r.scenario_id,
    )
    return dec, comp, note


# ─────────────────────────────────────────────
# Page-level CSS (call once per page)
# ─────────────────────────────────────────────

APP_CHROME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

/* Sidebar nav — dark panel, light text (do not use html/body/[class*="css"] globals). */
section[data-testid="stSidebar"],
[data-testid="stSidebar"] {
    background-color: #0d1f18 !important;
    border-right: 1px solid #1a3b31 !important;
    color: #e8f7ef !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    background-color: #0d1f18 !important;
    color: #e8f7ef !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] a,
[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNavLink"],
[data-testid="stSidebarNavLink"] span {
    color: #e8f7ef !important;
}
[data-testid="stSidebarNavLink"][aria-current="page"],
[data-testid="stSidebarNavLink"][aria-current="page"] span {
    color: #25d366 !important;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
    color: #a3d8b8 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #1a3b31 !important;
}
[data-testid="stSidebar"] button[kind="header"] {
    color: #e8f7ef !important;
}
</style>
"""

BASE_CSS = """
<style>
:root {
    color-scheme: light;
    --app-bg: #f8fafc;
    --app-text: #111827;
    --button-bg: linear-gradient(135deg,#25d366,#1aa34b);
}

section.main,
section.main .block-container {
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
section.main label { color: #111827 !important; font-size: 0.8rem; }
.stProgress > div > div { background-color:#25d366; }
section.main hr { border-color:#d4d4d4 !important; }

/* Universe / filters — light controls on light main (Popular Screens, Multibagger, scenarios, etc.) */
section.main [data-testid="stSelectbox"] label,
section.main [data-testid="stMultiSelect"] label,
section.main [data-testid="stTextInput"] label,
section.main [data-testid="stNumberInput"] label,
section.main [data-testid="stSlider"] label,
section.main [data-testid="stRadio"] label,
section.main [data-testid="stCheckbox"] label {
    color: #111827 !important;
}
section.main div[data-baseweb="select"] > div,
section.main div[data-baseweb="select"] > div > div {
    background-color: #ffffff !important;
    color: #111827 !important;
    border-color: #cbd5e1 !important;
}
section.main div[data-baseweb="select"] input,
section.main div[data-baseweb="select"] span,
section.main div[data-baseweb="select"] [role="combobox"] {
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
}
section.main [data-testid="stTextInput"] input,
section.main [data-testid="stTextInput"] textarea,
section.main [data-testid="stNumberInput"] input {
    background-color: #ffffff !important;
    color: #111827 !important;
    -webkit-text-fill-color: #111827 !important;
    border-color: #cbd5e1 !important;
}
section.main [data-testid="stSlider"] [data-testid="stThumbValue"],
section.main [data-testid="stSlider"] [data-baseweb="slider"] {
    color: #111827 !important;
}
/* Dropdown menu (portaled) */
motion.div[data-baseweb="popover"] [role="listbox"] li,
motion.div[data-baseweb="popover"] [role="option"] {
    color: #111827 !important;
    background-color: #ffffff !important;
}
motion.div[data-baseweb="popover"] [role="option"][aria-selected="true"],
motion.div[data-baseweb="popover"] [role="option"]:hover {
    background-color: #ecfdf5 !important;
    color: #111827 !important;
}
</style>
"""


def inject_app_chrome():
    """Sidebar + nav styling — call once from Overview.py so every page has a readable menu."""
    st.markdown(APP_CHROME_CSS, unsafe_allow_html=True)


def inject_css():
    inject_app_chrome()
    st.markdown(BASE_CSS, unsafe_allow_html=True)


@st.cache_data(ttl=180)
def _cached_chart_df(raw_ticker: str, interval_key: str, bars: int = 130):
    df = fetch_price_history(raw_ticker, interval_key)
    if df is None or df.empty:
        return None
    return df.tail(int(bars))


def render_chart_expander(raw_ticker: str, interval_key: str, uid: str) -> None:
    """Multi-pane chart: candlesticks + MA20/50 (+ VWAP intraday), volume, RSI(14)."""
    if not raw_ticker:
        return
    with st.expander("📉 Inline chart — OHLC · MA · Volume · RSI", expanded=False):
        try:
            from breeze_data import breeze_status_message

            st.caption(breeze_status_message())
        except Exception:
            pass
        df = _cached_chart_df(raw_ticker, interval_key)
        if df is None or df.empty:
            st.caption("No chart data for this symbol / interval.")
            return
        if go is None or make_subplots is None:
            st.caption("Install **plotly** for layered charts (`pip install plotly`). Showing close line.")
            st.line_chart(df["Close"])
            return
        closes = df["Close"].astype(float)
        highs = df["High"].astype(float)
        lows = df["Low"].astype(float)
        opens = df["Open"].astype(float)
        vols = df["Volume"].astype(float)
        ma20 = closes.rolling(20).mean()
        ma50 = closes.rolling(50).mean()
        rsi_line = rsi_series_wilder(closes, 14)
        vwap_line = compute_vwap(highs, lows, closes, vols)

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.58, 0.18, 0.24],
        )
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=opens,
                high=highs,
                low=lows,
                close=closes,
                name="OHLC",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(go.Scatter(x=df.index, y=ma20, name="MA20", line=dict(color="#4db8ff", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=ma50, name="MA50", line=dict(color="#f0b429", width=1)), row=1, col=1)
        if interval_key in ("1h", "15m") and vwap_line is not None and len(vwap_line):
            vv = vwap_line.replace([np.inf, -np.inf], np.nan).dropna()
            if not vv.empty:
                fig.add_trace(
                    go.Scatter(
                        x=vv.index,
                        y=vv,
                        name="VWAP",
                        line=dict(color="#c084fc", width=1, dash="dot"),
                    ),
                    row=1,
                    col=1,
                )

        colors = np.where(closes.values >= opens.values, "#25d36666", "#ff6b6b66")
        fig.add_trace(go.Bar(x=df.index, y=vols, name="Volume", marker_color=list(colors)), row=2, col=1)

        fig.add_trace(
            go.Scatter(x=df.index, y=rsi_line, name="RSI(14)", line=dict(color="#7abeac", width=1)),
            row=3,
            col=1,
        )
        fig.add_hline(y=70, line_width=1, line_dash="dash", line_color="#ff6b6b44", row=3, col=1)
        fig.add_hline(y=30, line_width=1, line_dash="dash", line_color="#25d36644", row=3, col=1)

        fig.update_layout(
            height=520,
            margin=dict(l=8, r=8, t=10, b=8),
            template="plotly_dark",
            paper_bgcolor="#0d1f18",
            plot_bgcolor="#122f25",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend_orientation="h",
        )
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Vol", row=2, col=1)
        fig.update_yaxes(title_text="RSI", row=3, col=1)

        st.plotly_chart(fig, use_container_width=True, key=f"ch_{uid}")


def scenario_advanced_panel(key_prefix: str) -> dict:
    """Shared controls for scenario scans — returns kwargs-compatible dict (+ UI-only keys)."""
    with st.expander("Advanced — bars, sector, MACD / Bollinger, MTF, earnings, RSI divergence", expanded=False):
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
        require_weekly_confirm = st.checkbox(
            "Require weekly uptrend filter (close vs 10-w MA + weekly RSI ≥ 45)",
            value=False,
            key=f"{key_prefix}_wk",
        )
        exclude_earnings_within_days = st.slider(
            "Exclude if earnings within N days (0 = off)",
            min_value=0,
            max_value=21,
            value=0,
            step=1,
            key=f"{key_prefix}_earn",
        )
        skip_bearish_divergence_buy = st.checkbox(
            "Skip BUY-side setups with bearish RSI divergence (HH price vs LH RSI)",
            value=False,
            key=f"{key_prefix}_nodivbear",
        )
        fetch_news = st.checkbox(
            "Fetch recent Yahoo headlines for matches (extra calls)",
            value=False,
            key=f"{key_prefix}_news",
        )
        portfolio_for_sizing = st.number_input(
            "Portfolio value for position sizing (optional, same currency as quote)",
            min_value=0.0,
            value=0.0,
            step=100000.0,
            key=f"{key_prefix}_pf",
        )
        risk_pct_per_trade = st.slider(
            "Risk % of portfolio per trade (used in share count)",
            min_value=0.25,
            max_value=5.0,
            value=1.0,
            step=0.25,
            key=f"{key_prefix}_riskpct",
        )
        use_rs_filter = st.checkbox(
            "Require minimum relative strength vs index (20-bar excess return)",
            value=False,
            key=f"{key_prefix}_users",
        )
        min_rs_vs_bench = st.slider(
            "Min RS vs index (percentage points)",
            min_value=-30.0,
            max_value=30.0,
            value=0.0,
            step=0.5,
            key=f"{key_prefix}_minrs",
        )
        weekly_macd_confirm = st.checkbox(
            "Weekly MACD histogram > 0 (extra MTF confirmation on BUY-side scans)",
            value=False,
            key=f"{key_prefix}_wkmacd",
        )
        require_stoch_cross_up = st.checkbox(
            "Require Stochastic %K cross above %D (BUY-side confirmation)",
            value=False,
            key=f"{key_prefix}_stup",
        )
        require_stoch_cross_down = st.checkbox(
            "Require Stochastic %K cross below %D (overbought / exit confirmation)",
            value=False,
            key=f"{key_prefix}_stdn",
        )

    sf = sector_filter.strip() or None
    return {
        "sector_filter": sf,
        "interval_key": interval_key,
        "require_macd_bullish": require_macd_bullish,
        "require_bb_touch_lower": require_bb_touch_lower,
        "require_weekly_confirm": require_weekly_confirm,
        "weekly_macd_confirm": weekly_macd_confirm,
        "exclude_earnings_within_days": int(exclude_earnings_within_days),
        "skip_bearish_divergence_buy": skip_bearish_divergence_buy,
        "fetch_news": fetch_news,
        "portfolio_for_sizing": portfolio_for_sizing,
        "risk_pct_per_trade": float(risk_pct_per_trade),
        "min_rs_vs_bench": float(min_rs_vs_bench) if use_rs_filter else None,
        "require_stoch_cross_up": require_stoch_cross_up,
        "require_stoch_cross_down": require_stoch_cross_down,
    }


def maybe_enrich_news(results: list[SignalResult], enabled: bool, max_names: int = 35) -> None:
    if not enabled or not results:
        return
    if len(results) > max_names:
        st.warning(f"Headlines skipped — more than {max_names} matches (too many Yahoo calls). Narrow filters or disable headlines.")
        return
    enrich_results_news(results)


def maybe_enrich_healthy_dip_context(results: list[SignalResult], enabled: bool, max_names: int = 30) -> None:
    """Headlines + one-line fall context for Healthy Dip (on by default after scan)."""
    if not enabled or not results:
        return
    try:
        from signals import enrich_healthy_dip_fall_context
    except ImportError:
        from .signals import enrich_healthy_dip_fall_context  # type: ignore[attr-defined]
    if len(results) > max_names:
        st.warning(
            f"“Why it fell” context skipped — {len(results)} matches (cap {max_names}). "
            "Tighten filters or turn off context in the panel above."
        )
        return
    enrich_healthy_dip_fall_context(results)


def log_scenario_scan(page_key: str, universe_label: str, results: list[SignalResult]) -> None:
    """Persist a lightweight snapshot for audit / 'first seen' style workflows."""
    try:
        syms = [r.raw_ticker for r in results]
        append_scan_record(page_key, universe_label or "", syms, meta={"matches": len(syms)})
    except Exception:
        return


def raw_symbol_from_screen_display(display_ticker: str, universe_name: str) -> str:
    """Map stripped screen-table ticker back to yfinance raw symbol (e.g. `RELIANCE` → `RELIANCE.NS`)."""
    s = str(display_ticker or "").strip()
    if not s:
        return ""
    if "NSE" in str(universe_name):
        return f"{s}.NS"
    return s


def notify_watchlist_alerts_from_metrics(
    metrics: list[tuple[str, str, float, float | None]],
    page_hint: str = "",
    *,
    dedupe_session_key: str | None = None,
) -> None:
    """
    Banner + optional email when rows match saved watchlist RSI / price thresholds.

    Each item is ``(display_ticker, raw_ticker, price, rsi)``. Use ``rsi=None`` to evaluate
    price alerts only (RSI thresholds are skipped).

    ``dedupe_session_key``: identical hit lists are not shown/emailed again until the hit set clears or changes.
    """
    if not metrics:
        return
    wl_by = {str(r.get("raw_ticker")): r for r in load_watchlist()}
    msgs: list[str] = []
    for disp, raw, price, rsi in metrics:
        row = wl_by.get(raw)
        if not row:
            continue
        try:
            rb = row.get("alert_rsi_below")
            ra = row.get("alert_rsi_above")
            pa = row.get("alert_price_above")
            pb = row.get("alert_price_below")
            if rsi is not None and not (isinstance(rsi, float) and np.isnan(rsi)):
                rsi_f = float(rsi)
                if rb is not None and float(rb) > 0 and rsi_f <= float(rb):
                    msgs.append(f"{disp}: RSI {rsi_f:.1f} ≤ {float(rb):.1f}")
                if ra is not None and float(ra) > 0 and rsi_f >= float(ra):
                    msgs.append(f"{disp}: RSI {rsi_f:.1f} ≥ {float(ra):.1f}")
            if pa is not None and float(pa) > 0 and price >= float(pa):
                msgs.append(f"{disp}: price {price:.2f} ≥ {float(pa):.2f}")
            if pb is not None and float(pb) > 0 and price <= float(pb):
                msgs.append(f"{disp}: price {price:.2f} ≤ {float(pb):.2f}")
        except (TypeError, ValueError):
            continue
    if not msgs:
        if dedupe_session_key:
            st.session_state.pop(f"_wl_alert_dedupe_{dedupe_session_key}", None)
        return

    if dedupe_session_key:
        slot = f"_wl_alert_dedupe_{dedupe_session_key}"
        sig = tuple(sorted(msgs))
        if st.session_state.get(slot) == sig:
            return
        st.session_state[slot] = sig

    st.info("🔔 Watchlist alert hits:\n" + "\n".join(f"- {m}" for m in msgs[:15]))

    if load_alert_prefs().get("email_watchlist_alerts"):
        try:
            from email_alerts import resolve_smtp_settings, send_watchlist_alert_email

            if not resolve_smtp_settings():
                st.warning("Email alerts are enabled, but SMTP is not configured — add `.streamlit/secrets.toml` `[smtp]` or env vars.")
            else:
                ok, err = send_watchlist_alert_email(page_hint, msgs[:50])
                if ok:
                    st.caption("📧 Sent alert summary by email.")
                else:
                    st.warning(f"Could not send email: {err}")
        except Exception as e:
            st.warning(f"Email alert error: {e}")


def notify_watchlist_alerts_screen_df(df: pd.DataFrame, universe_name: str, page_hint: str = "") -> None:
    """Watchlist alerts from a ``screen_stocks`` dataframe (expects ``Ticker``, ``Price``, ``RSI`` columns)."""
    if df is None or df.empty:
        return
    metrics: list[tuple[str, str, float, float | None]] = []
    for _, row in df.iterrows():
        try:
            disp = str(row["Ticker"]).strip()
            price = float(row["Price"])
            rsi = float(row["RSI"])
        except (KeyError, TypeError, ValueError):
            continue
        raw = raw_symbol_from_screen_display(disp, universe_name)
        if raw:
            metrics.append((disp, raw, price, rsi))
    notify_watchlist_alerts_from_metrics(metrics, page_hint)


def notify_watchlist_alerts(results: list[SignalResult], page_hint: str = "") -> None:
    """Banner when a scanned symbol matches saved RSI / price alert thresholds."""
    if not results:
        return
    metrics = [(r.ticker, r.raw_ticker, float(r.price), float(r.rsi)) for r in results]
    notify_watchlist_alerts_from_metrics(metrics, page_hint)


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

        st.divider()
        with st.expander("🔔 Watchlist alerts (evaluated after each scenario scan)", expanded=False):
            rows_a = load_watchlist()
            symbols = [str(r.get("raw_ticker")) for r in rows_a if r.get("raw_ticker")]
            if not symbols:
                st.caption("Save symbols first.")
            else:
                pick = st.selectbox("Pick symbol", symbols, key=f"{key_prefix}_alert_sym")
                row = next((x for x in rows_a if x.get("raw_ticker") == pick), {})

                def _num(v, default: float = 0.0) -> float:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return default

                c1, c2 = st.columns(2)
                with c1:
                    rb = st.number_input("Alert if RSI ≤ (0 = off)", 0.0, 100.0, _num(row.get("alert_rsi_below")), 1.0, key=f"{key_prefix}_arb")
                    ra = st.number_input("Alert if RSI ≥ (0 = off)", 0.0, 100.0, _num(row.get("alert_rsi_above")), 1.0, key=f"{key_prefix}_ara")
                with c2:
                    pa = st.number_input("Alert if price ≥ (0 = off)", 0.0, value=_num(row.get("alert_price_above")), step=0.05, key=f"{key_prefix}_apa")
                    pb = st.number_input("Alert if price ≤ (0 = off)", 0.0, value=_num(row.get("alert_price_below")), step=0.05, key=f"{key_prefix}_apb")
                if st.button("Save alerts", key=f"{key_prefix}_asave"):
                    upsert_watchlist_fields(pick, {
                        "alert_rsi_below": rb if rb > 0 else None,
                        "alert_rsi_above": ra if ra > 0 else None,
                        "alert_price_above": pa if pa > 0 else None,
                        "alert_price_below": pb if pb > 0 else None,
                    })
                    st.success("Saved.")
                    st.rerun()

            st.divider()
            st.markdown("**Email alerts**")
            st.caption(
                "Configure SMTP in `.streamlit/secrets.toml` under `[smtp]` or use env vars "
                "`STOCKSIGHT_SMTP_HOST`, `STOCKSIGHT_SMTP_USER`, `STOCKSIGHT_SMTP_PASSWORD`, "
                "`STOCKSIGHT_SMTP_FROM`, `STOCKSIGHT_SMTP_TO`. See `email_alerts.py` for the full schema."
            )
            prefs = load_alert_prefs()
            email_on = st.checkbox(
                "Email me when watchlist alerts fire (after a scenario scan)",
                value=bool(prefs.get("email_watchlist_alerts")),
                key=f"{key_prefix}_email_on",
            )
            ec1, ec2 = st.columns(2)
            with ec1:
                if st.button("Save email preference", key=f"{key_prefix}_email_pref_save"):
                    set_email_watchlist_alerts(email_on)
                    st.success("Saved.")
                    st.rerun()
            with ec2:
                if st.button("Send test email", key=f"{key_prefix}_email_test"):
                    try:
                        from email_alerts import resolve_smtp_settings, send_test_email

                        if not resolve_smtp_settings():
                            st.error("SMTP not configured.")
                        else:
                            ok, err = send_test_email()
                            if ok:
                                st.success("Test email sent.")
                            else:
                                st.error(err)
                    except Exception as ex:
                        st.error(str(ex))

            try:
                from email_alerts import resolve_smtp_settings

                st.caption("SMTP status: **ready** ✓" if resolve_smtp_settings() else "SMTP status: **not configured**")
            except Exception:
                st.caption("SMTP status: unknown")


def render_historical_detail_panel(df: pd.DataFrame) -> None:
    """Expandable table of Yahoo ~1y historical fields for result rows."""
    if df is None or df.empty or "Historical detail" not in df.columns:
        return
    hist_cols = [
        c
        for c in (
            "Ticker",
            "Hist start",
            "Hist end",
            "52w high",
            "52w low",
            "% below 52w high",
            "Return 1M %",
            "Return 3M %",
            "Return 6M %",
            "Return 1Y %",
            "Avg volume 20d",
            "Historical snapshot",
            "Historical detail",
        )
        if c in df.columns
    ]
    if len(hist_cols) < 2:
        return
    with st.expander("📊 Historical detail (Yahoo ~1y daily)", expanded=False):
        st.caption("Daily OHLCV-derived stats from Yahoo Finance. Trading-day approximations for return windows.")
        st.dataframe(
            df[hist_cols],
            use_container_width=True,
            hide_index=False,
            column_config={
                "Historical snapshot": st.column_config.TextColumn(width="large"),
                "Historical detail": st.column_config.TextColumn(width="large"),
            },
        )


def signal_results_download(
    results: list[SignalResult],
    scenario_id: str,
    button_key: str = "dl",
    *,
    include_scenario: bool = False,
    include_analyst: bool = True,
    include_history: bool = True,
) -> None:
    if not results:
        return
    if (include_analyst or include_history) and len(results) > 50:
        st.warning(
            "Yahoo analyst/history columns skipped — more than 50 matches (rate limits). "
            "Narrow the scan or disable extras."
        )
        include_analyst = False
        include_history = False
    rows = []
    for r in results:
        decision, composite, matrix_note = _decision_for_signal_result(r)
        row = {
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "First_seen": first_seen_label(r.raw_ticker),
            "Interval": r.data_interval,
            "Sector": r.sector or "",
            "Signal": r.signal_label,
            "Decision": decision,
            "Composite": composite if composite == composite else None,
            "Matrix note": matrix_note,
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
            "Days_to_earn": r.days_to_earnings if r.days_to_earnings is not None else "",
            "Weekly_OK": r.weekly_confirm_buy,
            "Weekly_MACD_OK": r.weekly_macd_bullish,
            "RSI_bull_div": r.rsi_bullish_div,
            "RSI_bear_div": r.rsi_bearish_div,
            "Stoch_K": r.stoch_k,
            "Stoch_D": r.stoch_d,
            "RS20_vs_idx": r.rel_strength_20d,
            "VWAP_pct": r.price_vs_vwap_pct,
            "News_sentiment": r.news_sentiment or "",
            "NSE_flow_note": r.nse_flow_note or "",
            "Entry": r.entry,
            "Stop": r.stop_loss,
            "T2": r.target2,
            "Confidence": r.confidence,
        }
        if include_scenario:
            row = {
                "Ticker": row["Ticker"],
                "Scenario": scenario_display_title(r.scenario_id),
                **{k: v for k, v in row.items() if k != "Ticker"},
            }
        rows.append(row)
    df = pd.DataFrame(rows)
    if "First_seen" in df.columns:
        df = df.rename(columns={"First_seen": "First seen"})
    if (include_analyst or include_history) and not df.empty:
        try:
            from screener import enrich_dataframe_yahoo_context
        except ImportError:
            from .screener import enrich_dataframe_yahoo_context  # type: ignore[attr-defined]
        cache_key = (
            f"csv_yahoo_{scenario_id}_{button_key}_{include_analyst}_{include_history}_"
            f"{hash(tuple(df['Raw'].astype(str).tolist()))}"
        )
        if cache_key not in st.session_state:
            with st.spinner("Fetching Yahoo analyst + historical data for CSV…"):
                st.session_state[cache_key] = enrich_dataframe_yahoo_context(
                    df,
                    ticker_col="Ticker",
                    raw_ticker_col="Raw",
                    include_analyst=include_analyst,
                    include_history=include_history,
                )
        df = st.session_state[cache_key]
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
    audience = s.get("audience")
    purpose = s.get("purpose")
    if audience and purpose:
        page_audience_note(audience, purpose)


# ─────────────────────────────────────────────
# Trade plan card — one card per stock
# ─────────────────────────────────────────────

def trade_plan_card(
    r: SignalResult,
    scenario_id: str,
    portfolio_value: float = 0.0,
    risk_pct: float = 1.0,
):
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

    if r.weekly_confirm_buy is True:
        wk_txt = "✓ Weekly aligned"
    elif r.weekly_confirm_buy is False:
        wk_txt = "✗ Weekly weak"
    else:
        wk_txt = "Weekly n/a"

    if r.weekly_macd_bullish is True:
        wkm = "✓ W MACD+"
    elif r.weekly_macd_bullish is False:
        wkm = "✗ W MACD−"
    else:
        wkm = "W MACD n/a"

    stoch_txt = "—"
    if r.stoch_k is not None and r.stoch_d is not None:
        stoch_txt = f"{r.stoch_k:.1f}/{r.stoch_d:.1f}"
        if r.stoch_cross_up:
            stoch_txt += " · X↑"
        if r.stoch_cross_down:
            stoch_txt += " · X↓"

    rs_txt = "—"
    if r.rel_strength_20d is not None:
        bench_lbl = (r.benchmark_sym or "").replace("^", "")
        rs_txt = f"{r.rel_strength_20d:+.1f} pp vs {bench_lbl or 'idx'}"

    vwap_txt = "—"
    if r.vwap_last is not None and r.price_vs_vwap_pct is not None:
        vwap_txt = f"{r.price_vs_vwap_pct:+.1f}% vs VWAP"

    nse_txt = html.escape(r.nse_flow_note) if r.nse_flow_note else "—"

    fs_txt = html.escape(first_seen_label(r.raw_ticker))

    sent_html = ""
    if r.news_sentiment:
        pal = {"bullish": "#25d366", "bearish": "#ff6b6b", "neutral": "#a0a0a0"}.get(r.news_sentiment, "#a0a0a0")
        sent_html = (
            "<div style='margin-top:8px;font-size:0.72rem;color:#b8e7c7;'>"
            f"<span style='color:{pal};font-weight:700;'>News sentiment:</span> "
            f"{html.escape(str(r.news_sentiment).upper())}"
            "</div>"
        )
    div_bits = []
    if r.rsi_bullish_div:
        div_bits.append("Bull div")
    if r.rsi_bearish_div:
        div_bits.append("Bear div")
    div_txt = html.escape(" · ".join(div_bits) if div_bits else "—")

    dte = r.days_to_earnings
    dte_txt = html.escape(f"{dte}d" if dte is not None else "—")

    earn_warn_html = ""
    if dte is not None and 0 <= dte <= 14:
        earn_warn_html = (
            "<div style='margin-top:8px;color:#ffb020;font-size:0.72rem;font-weight:600;'>"
            f"⚠ Event risk: earnings in <b>{html.escape(str(dte))}</b> day(s)."
            "</div>"
        )

    extras_html = f"""
        <div style='margin-top:10px; padding-top:8px; border-top:1px dashed #1a3b31;
                    font-family:"IBM Plex Mono",monospace; font-size:0.72rem; color:#b8e7c7; line-height:1.7;'>
            <span style='color:#a3d8b8;'>Bars</span> {interval_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Sector</span> {sector_part}<br>
            <span style='color:#a3d8b8;'>First seen</span> {fs_txt}<br>
            <span style='color:#a3d8b8;'>MACD hist</span> {macd_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>% vs MA20</span> {ma_part}<br>
            <span style='color:#a3d8b8;'>%B</span> {bb_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>ATR14</span> {atr_part}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Earnings</span> {earn_part}<br>
            <span style='color:#a3d8b8;'>Weekly MTF</span> {html.escape(wk_txt)}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>W MACD</span> {html.escape(wkm)}<br>
            <span style='color:#a3d8b8;'>RSI div</span> {div_txt}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>Δ earnings</span> {dte_txt}<br>
            <span style='color:#a3d8b8;'>Stoch %K/%D</span> {html.escape(stoch_txt)}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>RS vs idx</span> {html.escape(rs_txt)}<br>
            <span style='color:#a3d8b8;'>VWAP</span> {html.escape(vwap_txt)}
            &nbsp;·&nbsp; <span style='color:#a3d8b8;'>NSE flows</span> {nse_txt}
        </div>
        {earn_warn_html}
        {sent_html}
        """

    sizing_html = ""
    rp = float(risk_pct) if risk_pct and risk_pct > 0 else 1.0
    if not is_sell and not is_wait and portfolio_value and portfolio_value > 0:
        risk_per_share = abs(float(r.price) - float(r.stop_loss))
        if risk_per_share > 0:
            budget = float(portfolio_value) * (rp / 100.0)
            qty = int(budget // risk_per_share)
            sizing_html = f"""
            <div style='margin-top:8px; font-size:0.72rem; color:#f0b429;
                        font-family:'IBM Plex Mono',monospace;'>
                Position sizing (~{rp:.2f}% portfolio risk): <b>{qty}</b> shares @ risk/share {html.escape(r.currency)}{risk_per_share:,.2f}
            </div>
            """

    fall_html = ""
    if r.fall_context:
        fall_html = f"""
        <div style='margin-top:10px; padding:10px 12px; background:#0a1e28;
                    border-left:3px solid #7ec8e3; border-radius:4px;
                    font-size:0.78rem; color:#c8d8e8; line-height:1.5;'>
            <span style='color:#7ec8e3; font-weight:700;'>Why it might have fallen</span><br>
            {html.escape(r.fall_context, quote=False)}
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

        {fall_html}

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

    render_chart_expander(r.raw_ticker, r.data_interval or "1d", uid)
# ─────────────────────────────────────────────
# Results table (compact summary)
# ─────────────────────────────────────────────

def results_table(
    results: list[SignalResult],
    scenario_id: str,
    *,
    include_scenario: bool = False,
    include_yahoo_context: bool = True,
) -> None:
    if not results:
        return

    rows = []
    for r in results:
        decision, composite, matrix_note = _decision_for_signal_result(r)
        row = {
            "Ticker":       r.ticker,
            "First seen":   first_seen_label(r.raw_ticker),
            "Decision":     decision,
            "Composite":    composite if composite == composite else None,
            "Matrix note":  matrix_note,
            "Signal":       r.signal_label,
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
            "ΔEarn(d)":    r.days_to_earnings if r.days_to_earnings is not None else None,
            "Weekly":      {True: "✓", False: "✗", None: "—"}[r.weekly_confirm_buy],
            "W MACD":      {True: "✓", False: "✗", None: "—"}[r.weekly_macd_bullish],
            "%K":          r.stoch_k,
            "%D":          r.stoch_d,
            "RS20":        r.rel_strength_20d,
            "VWAP %":      r.price_vs_vwap_pct,
            "Sentiment":   r.news_sentiment or "—",
            "Bull div":    "✓" if r.rsi_bullish_div else "—",
            "Bear div":    "⚠" if r.rsi_bearish_div else "—",
            "RSI Rising":   "↑" if r.rsi_rising else "→/↓",
            "Green Candle": "✅" if r.is_green else "—",
            "Reversal":     "✅" if r.reversal  else "—",
            "Entry":        r.entry,
            "Stop Loss":    r.stop_loss,
            "Target 2":     r.target2,
            "Risk %":       r.risk_pct,
            "Confidence":   r.confidence,
        }
        if scenario_id == "healthy_dip":
            row["Drawdown %"] = r.drawdown_52w_pct
            row["Why it fell"] = (r.fall_context or "—")[:120]
        if include_scenario:
            row = {
                "Ticker": row["Ticker"],
                "Scenario": scenario_display_title(r.scenario_id),
                **{k: v for k, v in row.items() if k != "Ticker"},
            }
        rows.append(row)

    df = pd.DataFrame(rows)
    df["Raw"] = [r.raw_ticker for r in results]

    if include_yahoo_context and len(df) <= 50:
        try:
            from screener import enrich_dataframe_yahoo_context
        except ImportError:
            from .screener import enrich_dataframe_yahoo_context  # type: ignore[attr-defined]
        cache_key = f"table_yahoo_{scenario_id}_{hash(tuple(df['Raw'].astype(str).tolist()))}"
        if cache_key not in st.session_state:
            with st.spinner("Loading Yahoo historical + analyst columns…"):
                st.session_state[cache_key] = enrich_dataframe_yahoo_context(
                    df,
                    ticker_col="Ticker",
                    raw_ticker_col="Raw",
                    include_analyst=True,
                    include_history=True,
                )
        df = st.session_state[cache_key]

    link_cols_nse = ["Yahoo Finance", "Google Finance", "Moneycontrol", "TradingView"]
    link_cols_us  = ["Yahoo Finance", "Google Finance", "MarketWatch",  "TradingView"]

    # Add first available link set
    if results:
        for name, url in results[0].links.items():
            col_name = name
            df[col_name] = [r.links.get(name, "") for r in results]

    col_cfg = {
        "Decision":     st.column_config.TextColumn("Decision", width="medium"),
        "Matrix note":  st.column_config.TextColumn("Matrix note", width="large"),
        "Composite":    st.column_config.NumberColumn("Composite", format="%.1f"),
        "Price":        st.column_config.NumberColumn("Price", format="%.2f"),
        "PE":           st.column_config.NumberColumn("PE", format="%.1f"),
        "Vol×":         st.column_config.NumberColumn("Vol×", format="%.2f"),
        "RSI":          st.column_config.NumberColumn("RSI", format="%.1f"),
        "MACD hist":    st.column_config.NumberColumn("MACD hist", format="%.4f"),
        "% vs MA20":    st.column_config.NumberColumn("% vs MA20", format="%.2f"),
        "%B":           st.column_config.NumberColumn("%B", format="%.3f"),
        "ATR14":        st.column_config.NumberColumn("ATR14", format="%.4f"),
        "ΔEarn(d)":     st.column_config.NumberColumn("ΔEarn(d)", format="%d"),
        "%K":           st.column_config.NumberColumn("%K", format="%.1f"),
        "%D":           st.column_config.NumberColumn("%D", format="%.1f"),
        "RS20":         st.column_config.NumberColumn("RS20", format="%.2f"),
        "VWAP %":       st.column_config.NumberColumn("VWAP %", format="%.2f"),
        "Entry":        st.column_config.NumberColumn("Entry", format="%.2f"),
        "Stop Loss":    st.column_config.NumberColumn("Stop", format="%.2f"),
        "Target 2":     st.column_config.NumberColumn("Target 2", format="%.2f"),
        "Risk %":       st.column_config.NumberColumn("Risk %", format="%.1f%%"),
    }
    # Link columns
    for name in (link_cols_nse + link_cols_us):
        if name in df.columns:
            col_cfg[name] = st.column_config.LinkColumn(name, display_text="Open ↗")

    for text_col in ("Analyst recommendation", "Historical snapshot", "Historical detail"):
        if text_col in df.columns:
            col_cfg[text_col] = st.column_config.TextColumn(text_col, width="large")

    render_historical_detail_panel(df)
    st.dataframe(
        df, use_container_width=True,
        column_config=filter_column_config(df, col_cfg),
        hide_index=True,
        height=min(500, 50 + len(df) * 38),
    )
    render_decision_matrix_legend()


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
