"""Streamlit page renderers for the Intraday module.

Pages:
    render_intraday_screener_page()  → 4-strategy intraday scanner with tabs
    render_gap_scanner_page()        → pre-market gap-up / gap-down scanner + mood
    render_intraday_guide_page()     → educational playbook (rules, routine, checklist)
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from intraday import (
    INTRADAY_UNIVERSES_BY_MARKET,
    LIQUID_INTRADAY_NAMES,
    LIQUID_US_NAMES,
    MARKETS,
    MARKET_LABEL,
    STRATEGIES,
    STRATEGY_BEST_TIME_BY_MARKET,
    STRATEGY_LABEL,
    GapResult,
    IntradayFilters,
    IntradayResult,
    IntradayScanStats,
    compute_market_mood,
    compute_volume_time_prediction,
    is_us_early_session,
    market_session_window,
    resolve_universe,
    scan_gaps,
    scan_intraday,
)
from market_sentiment import add_market_sentiment_columns
try:
    from news_scanner import TIER_EMOJI, TIER_LABELS, analyze_ticker
except ImportError:
    from .news_scanner import TIER_EMOJI, TIER_LABELS, analyze_ticker  # type: ignore[no-redef]
from ui_components import (
    SCAN_RESULTS_NEWS_COL,
    ensure_session_choice,
    filter_column_config,
    inject_css,
    page_audience_note,
    prepare_scan_results_df,
    render_clickable_scan_table,
    safe_set_page_config,
)


# ─────────────────────────────────────────────────────────────
# Trading schedules (CEST · market-local) — educational reference
# ─────────────────────────────────────────────────────────────
NSE_DAY_SCHEDULE: list[tuple[str, str, str]] = [
    ("5:30 AM", "8:00 AM", "☕ Wake up, check SGX Nifty trend, US closing"),
    ("5:45 AM", "9:15 AM", "🌅 **RUN GAP SCANNER** — see who gapped up/down"),
    ("5:50 AM", "9:20 AM", "Read market mood banner, shortlist top 3 stocks"),
    ("6:00 AM", "9:30 AM", "📡 **RUN INTRADAY SCANNER** — find breakout setups"),
    ("6:15 AM", "9:45 AM", "✅ Place your trades (ORB / Momentum setups)"),
    ("7:00 AM", "10:30 AM", "📡 Run scanner again for VWAP pullback setups"),
    ("9:00 AM", "12:30 PM", "⚠️ Lunch zone — low volume, avoid new trades"),
    ("11:00 AM", "2:30 PM", "📡 Run scanner again for afternoon momentum"),
    ("11:45 AM", "3:15 PM", "🔴 Square off **ALL** positions — no open trades at close"),
    ("12:00 PM", "3:30 PM", "NSE closes"),
]

US_DAY_SCHEDULE: list[tuple[str, str, str]] = [
    ("3:00 PM", "9:00 AM", "🌅 **RUN GAP SCANNER** — pre-market gaps forming"),
    ("3:30 PM", "9:30 AM", "US Market opens"),
    ("3:35 PM", "9:35 AM", "⚠️ Wait — first 5 min too volatile, do **NOT** trade"),
    ("3:45 PM", "9:45 AM", "📡 **RUN INTRADAY SCANNER** — ORB setups ready"),
    ("4:00 PM", "10:00 AM", "✅ Place your trades"),
    ("5:30 PM", "11:30 AM", "📡 Run scanner again for VWAP pullbacks"),
    ("7:00 PM", "1:00 PM", "⚠️ Lunch lull — avoid new trades"),
    ("9:00 PM", "3:00 PM", "📡 Power hour — run scanner for afternoon momentum"),
    ("9:45 PM", "3:45 PM", "🔴 Start squaring off all positions"),
    ("10:00 PM", "4:00 PM", "US market closes"),
]

QUICK_TRADING_RULES: list[tuple[str, str]] = [
    ("Never trade first 5 min on US stocks", "Too wild, algos are testing levels"),
    ("Always run **Gap Scanner** BEFORE Intraday Scanner", "Gap tells you market mood first"),
    ("Stop trading after **2 losses** in a day", "Protects your capital"),
    ("Square off **15 min** before close", "Avoid last-minute panic moves"),
]


def _news_universe_for_market(market: str) -> str:
    return "S&P 500 (NYSE)" if str(market).upper() == "US" else "Nifty 500 (NSE)"


def _add_intraday_news_scanner_columns(
    df: pd.DataFrame,
    *,
    market: str = "NSE",
    max_rows: int = 80,
) -> pd.DataFrame:
    """Add News Scanner confirmation columns to intraday/gap tables."""
    if df is None or df.empty:
        return df
    if "News score" in df.columns:
        return df

    enabled = bool(st.session_state.get("intraday_news_confirm_enabled", True))
    if not enabled:
        return df

    max_rows = int(st.session_state.get("intraday_news_confirm_max_rows", max_rows))
    out = df.copy()
    universe_name = _news_universe_for_market(market)
    cache: dict[str, object] = st.session_state.setdefault("_intraday_news_scanner_cache", {})

    news_scores: list[Optional[int]] = []
    top_tiers: list[str] = []
    tier_refs: list[str] = []
    top_headlines: list[str] = []
    confirm_actions: list[str] = []

    for i, (_, row) in enumerate(out.iterrows()):
        if i >= max_rows:
            news_scores.append(None)
            top_tiers.append("—")
            tier_refs.append("—")
            top_headlines.append("—")
            confirm_actions.append("— (narrow list for full news scoring)")
            continue

        raw = str(row.get("Raw") or row.get("Ticker") or "").strip()
        if not raw:
            news_scores.append(None)
            top_tiers.append("—")
            tier_refs.append("—")
            top_headlines.append("—")
            confirm_actions.append("—")
            continue

        ckey = f"{universe_name}|{raw.upper()}"
        summary = cache.get(ckey)
        if summary is None:
            summary = analyze_ticker(raw, universe_name=universe_name)
            cache[ckey] = summary

        score = int(getattr(summary, "news_score", 0) or 0)
        top_tier = int(getattr(summary, "top_tier", 4) or 4)
        headline = str(getattr(summary, "top_headline", "") or "").strip()
        action = str(getattr(summary, "action", "") or "").strip()

        news_scores.append(score)
        top_tiers.append(f"{TIER_EMOJI.get(top_tier, '•')} T{top_tier}")
        tier_refs.append(f"{TIER_EMOJI.get(top_tier, '•')} {TIER_LABELS.get(top_tier, f'Tier {top_tier}')}")
        top_headlines.append(headline[:95] if headline else "—")
        confirm_actions.append(action[:95] if action else "—")

    out["News score"] = news_scores
    out["Top tier"] = top_tiers
    out["Tier reference"] = tier_refs
    out["Top headline"] = top_headlines
    out["Confirm action"] = confirm_actions
    return out


def _news_confirmation_controls() -> None:
    with st.expander("📰 News confirmation settings", expanded=False):
        st.checkbox(
            "Enable News Scanner confirmation columns",
            value=bool(st.session_state.get("intraday_news_confirm_enabled", True)),
            key="intraday_news_confirm_enabled",
            help="Adds News score / Top tier / Tier reference / Top headline / Confirm action.",
        )
        st.slider(
            "Max rows for news scoring",
            min_value=20,
            max_value=300,
            value=int(st.session_state.get("intraday_news_confirm_max_rows", 80)),
            step=10,
            key="intraday_news_confirm_max_rows",
            help="Higher values provide broader scoring but take longer.",
        )


def _schedule_rows_to_md(rows: list[tuple[str, str, str]], local_col: str) -> str:
    lines = [
        f"| Your time (CEST) | {local_col} | Action |",
        "|------------------|-------------|--------|",
    ]
    for cest, local, action in rows:
        lines.append(f"| {cest} | {local} | {action} |")
    return "\n".join(lines)


def _live_market_clocks() -> None:
    """Client-side live clocks for IST, CEST, and US Eastern (ET/EST) — no server rerun."""
    components.html(
        """
<div id="ss-clocks" style="font-family:'IBM Plex Mono',Consolas,monospace;
     background:linear-gradient(135deg,#0a1f1a 0%,#0f2a22 100%);
     border:1px solid #1a3b31; border-radius:12px; padding:14px 18px; margin:0 0 12px 0;">
  <div style="color:#7abeac; font-size:0.72rem; letter-spacing:0.06em; margin-bottom:10px;">
    🕐 LIVE MARKET CLOCKS · updates every second
  </div>
  <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px;">
    <div style="text-align:center; padding:10px; background:#122f25; border-radius:8px; border:1px solid #1a3b31;">
      <div style="color:#a3d8b8; font-size:0.72rem;">🇮🇳 IST · NSE</div>
      <div id="ss-ist" style="color:#25d366; font-size:1.35rem; font-weight:700; margin-top:4px;">--:--:--</div>
      <div id="ss-nse-status" style="font-size:0.68rem; margin-top:4px; color:#7abeac;">—</div>
    </div>
    <div style="text-align:center; padding:10px; background:#122f25; border-radius:8px; border:1px solid #1a3b31;">
      <div style="color:#a3d8b8; font-size:0.72rem;">🇪🇺 CEST · your time</div>
      <div id="ss-cest" style="color:#f0b429; font-size:1.35rem; font-weight:700; margin-top:4px;">--:--:--</div>
      <div style="font-size:0.68rem; margin-top:4px; color:#7abeac;">Europe/Berlin</div>
    </div>
    <div style="text-align:center; padding:10px; background:#122f25; border-radius:8px; border:1px solid #1a3b31;">
      <div style="color:#a3d8b8; font-size:0.72rem;">🇺🇸 ET · NYSE/NASDAQ</div>
      <div id="ss-et" style="color:#4db8ff; font-size:1.35rem; font-weight:700; margin-top:4px;">--:--:--</div>
      <div id="ss-us-status" style="font-size:0.68rem; margin-top:4px; color:#7abeac;">—</div>
    </div>
  </div>
  <div style="color:#5a8f7a; font-size:0.65rem; margin-top:10px; text-align:center;">
    US clock follows Eastern Time (ET/EST) · auto-adjusts for daylight saving
  </div>
</div>
<script>
(function() {
  const tz = { ist: 'Asia/Kolkata', cest: 'Europe/Berlin', et: 'America/New_York' };
  const fmt = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true };
  function minsInTz(id, h, m) {
    const p = new Intl.DateTimeFormat('en-US', { timeZone: id, hour: 'numeric', minute: 'numeric', hour12: false });
    const parts = p.formatToParts(new Date());
    let hh = 0, mm = 0;
    for (const x of parts) {
      if (x.type === 'hour') hh = parseInt(x.value, 10);
      if (x.type === 'minute') mm = parseInt(x.value, 10);
    }
    return hh * 60 + mm;
  }
  function sessionStatus(tzId, openM, closeM) {
    const m = minsInTz(tzId);
    if (m >= openM && m < closeM) return { t: 'OPEN', c: '#25d366' };
    return { t: 'CLOSED', c: '#7abeac' };
  }
  function tick() {
    const now = new Date();
    document.getElementById('ss-ist').textContent =
      now.toLocaleTimeString('en-IN', { ...fmt, timeZone: tz.ist });
    document.getElementById('ss-cest').textContent =
      now.toLocaleTimeString('de-DE', { ...fmt, timeZone: tz.cest });
    document.getElementById('ss-et').textContent =
      now.toLocaleTimeString('en-US', { ...fmt, timeZone: tz.et });
    const nse = sessionStatus(tz.ist, 9*60+15, 15*60+30);
    const us = sessionStatus(tz.et, 9*60+30, 16*60);
    const ns = document.getElementById('ss-nse-status');
    ns.textContent = 'NSE ' + nse.t;
    ns.style.color = nse.c;
    const usEl = document.getElementById('ss-us-status');
    usEl.textContent = 'US ' + us.t;
    usEl.style.color = us.c;
  }
  tick();
  setInterval(tick, 1000);
})();
</script>
        """,
        height=175,
    )


def _render_market_schedule(market: str, *, expanded: bool = False) -> None:
    """Market-specific day schedule (CEST + IST or ET)."""
    mkt = (market or "NSE").upper()
    if mkt == "US":
        title = "🇺🇸 US Market (NYSE/NASDAQ) schedule · CEST & ET"
        body = _schedule_rows_to_md(US_DAY_SCHEDULE, "US Time (ET)")
        hint = "🌅 Run Gap Scanner at **3:00 PM CEST** (9:00 AM ET) · Intraday Scanner at **3:45 PM CEST** (9:45 AM ET)."
    else:
        title = "🇮🇳 Indian Market (NSE) schedule · CEST & IST"
        body = _schedule_rows_to_md(NSE_DAY_SCHEDULE, "India Time (IST)")
        hint = "🌅 Run Gap Scanner at **5:45 AM CEST** (9:15 AM IST) · Intraday Scanner at **6:00 AM CEST** (9:30 AM IST)."
    with st.expander(title, expanded=expanded):
        st.markdown(body)
        st.caption(hint)


def _render_full_day_glance() -> None:
    st.markdown("#### 📅 Your full day at a glance (CEST)")
    st.code(
        """5:30 AM  ── 🇮🇳 NSE Gap Scanner
6:00 AM  ── 🇮🇳 NSE Intraday Scanner
12:00 PM ── 🇮🇳 NSE closes (Indian trading done)

3:00 PM  ── 🇺🇸 US Gap Scanner
3:45 PM  ── 🇺🇸 US Intraday Scanner
10:00 PM ── 🇺🇸 US closes (US trading done)""",
        language="text",
    )


def _render_quick_rules() -> None:
    st.markdown("#### ⚡ Quick rules to remember")
    lines = ["| Rule | Why |", "|------|-----|"]
    for rule, why in QUICK_TRADING_RULES:
        lines.append(f"| {rule} | {why} |")
    st.markdown("\n".join(lines))


# ─────────────────────────────────────────────────────────────
# Common helpers
# ─────────────────────────────────────────────────────────────
def _render_extended_bars_notice(
    market: str,
    scan_stats: Optional[IntradayScanStats] = None,
) -> None:
    """Explain multi-day intraday fetches used for RSI stability (esp. early US session)."""
    mkt = (market or "NSE").upper()
    early_us = mkt == "US" and is_us_early_session()
    extended_n = int(scan_stats.bars_extended_history) if scan_stats else 0
    if not early_us and extended_n <= 0:
        return

    parts: list[str] = []
    if early_us:
        parts.append(
            "**Early US session:** Yahoo often returns only a handful of 5m bars in the first hour. "
            "The scanner may pull **2–10 days** of 5m/15m history so RSI-14 and volume-ratio gates stay stable."
        )
    if extended_n > 0 and scan_stats and scan_stats.total_scanned:
        pct = round(100 * extended_n / scan_stats.total_scanned)
        parts.append(
            f"**This scan:** **{extended_n}** of **{scan_stats.total_scanned}** tickers "
            f"({pct}%) used extended intraday history (not same-day 5m only)."
        )
    if not parts:
        return

    st.info("📊 " + " ".join(parts))


def _session_banner(market: str = "NSE") -> None:
    """Market-aware session banner with both market-local and CEST clocks."""
    s = market_session_window(market)
    flag = "🇺🇸" if s["market"] == "US" else "🇮🇳"
    is_open_color = "#25d366" if s["is_open"] else "#7abeac"
    is_open_pill = (
        f"<span style='background:#25d36622; color:#25d366; padding:2px 8px; "
        f"border-radius:8px; font-size:0.72rem; margin-left:8px;'>OPEN</span>"
        if s["is_open"] else
        f"<span style='background:#1a3b31; color:#7abeac; padding:2px 8px; "
        f"border-radius:8px; font-size:0.72rem; margin-left:8px;'>CLOSED</span>"
    )
    early_us_note = ""
    if s["market"] == "US" and is_us_early_session():
        early_us_note = (
            "<br><span style='color:#4db8ff;'>ℹ Early US session — extended 5m/15m bars may be used for RSI stability.</span>"
        )
    st.markdown(
        f"""
<div style='background:#0f2a22; border:1px solid #1a3b31; border-left:4px solid {is_open_color};
            border-radius:8px; padding:10px 16px; margin-bottom:12px;
            font-family:"IBM Plex Mono",monospace; color:#a3d8b8; font-size:0.85rem;'>
  {flag} <b>{html.escape(s["window"])}</b> {is_open_pill}<br>
  <span style='color:#7abeac;'>Now:</span>
  <b style='color:#e5f7ed;'>{html.escape(s["market_local_str"])}</b>
  <span style='color:#7abeac;'>·</span>
  <b style='color:#e5f7ed;'>{html.escape(s["cest_str"])}</b>
  <span style='color:#7abeac;'>(your local European time)</span>
  <br>
  <span style='color:#7abeac;'>💡 {html.escape(s["tip"])}</span>
  {early_us_note}
</div>
""",
        unsafe_allow_html=True,
    )


def _market_picker(key_prefix: str) -> str:
    """Market selector — returns 'NSE' or 'US'. Persists in session state."""
    market_key = f"{key_prefix}_market"
    ensure_session_choice(market_key, list(MARKETS), "NSE")
    market = st.radio(
        "Market",
        list(MARKETS),
        format_func=lambda m: MARKET_LABEL.get(m, m),
        horizontal=True,
        key=market_key,
        help=(
            "NSE (India) trades 9:15 AM – 3:30 PM IST (5:45 AM – 12:00 PM CEST in summer). "
            "US (NYSE & NASDAQ) trades 9:30 AM – 4:00 PM ET (3:30 PM – 10:00 PM CEST in summer)."
        ),
    )
    return str(market or "NSE")


def _universe_picker(key_prefix: str, market: str = "NSE") -> tuple[str, list[str]]:
    """Universe picker scoped to the given market."""
    mkt = (market or "NSE").upper()
    market_unis = INTRADAY_UNIVERSES_BY_MARKET.get(mkt, INTRADAY_UNIVERSES_BY_MARKET["NSE"])
    if mkt == "US":
        shortlist_label = "Liquid US shortlist (~35)"
        shortlist_tickers = LIQUID_US_NAMES
        custom_help = "Paste US tickers — no suffix needed (e.g. AAPL, MSFT, NVDA)."
        custom_seed = "\n".join(LIQUID_US_NAMES[:5])
    else:
        shortlist_label = "Liquid F&O shortlist (~30)"
        shortlist_tickers = LIQUID_INTRADAY_NAMES
        custom_help = "Paste NSE tickers — `.NS` is auto-appended if missing (e.g. RELIANCE → RELIANCE.NS)."
        custom_seed = "\n".join(LIQUID_INTRADAY_NAMES[:5])

    options = list(market_unis.keys()) + [shortlist_label, "Custom (paste)"]
    uni_key = f"{key_prefix}_{mkt.lower()}_uni"
    ensure_session_choice(uni_key, options, options[0])
    pick = st.selectbox(
        f"Stock Universe ({MARKET_LABEL.get(mkt, mkt)})",
        options,
        key=uni_key,
        help="Smaller universes scan in 1–3 min. Full S&P 500 / Nifty 500 = 10–20 min.",
    )

    if pick == shortlist_label:
        return pick, list(shortlist_tickers)

    if pick == "Custom (paste)":
        raw = st.text_area(
            "Paste raw tickers (one per line)",
            value=custom_seed,
            key=f"{key_prefix}_{mkt.lower()}_custom",
            height=120,
            help=custom_help,
        )
        out: list[str] = []
        for line in raw.splitlines():
            sym = line.strip().upper()
            if not sym:
                continue
            if mkt == "NSE" and "." not in sym:
                sym = f"{sym}.NS"
            out.append(sym)
        return pick, out

    return pick, resolve_universe(pick, market=mkt)


# Currency-specific defaults & ranges for the universal price filter.
# Volume / RSI defaults are universal (intraday norms don't change much between markets).
_FILTER_DEFAULTS_BY_MARKET: dict[str, dict] = {
    "NSE": {
        "currency_symbol": "₹",
        "min_price_default": 50.0,
        "min_price_max": 10_000.0,
        "min_price_step": 10.0,
        "max_price_default": 5_000.0,
        "max_price_max": 50_000.0,
        "max_price_step": 100.0,
        "avg_vol_default": 500_000.0,
        "avg_vol_help": "Lower = more candidates, but illiquid. Default 5 lakh shares.",
    },
    "US": {
        "currency_symbol": "$",
        "min_price_default": 5.0,
        "min_price_max": 2_000.0,
        "min_price_step": 1.0,
        "max_price_default": 1_000.0,
        "max_price_max": 10_000.0,
        "max_price_step": 10.0,
        "avg_vol_default": 1_000_000.0,
        "avg_vol_help": "US large-caps trade millions of shares daily. Default 1M shares for liquid setups.",
    },
}


def _filters_panel(key_prefix: str, market: str = "NSE") -> IntradayFilters:
    """Universal filters panel — labels, defaults and ranges adapt to the market currency.

    Session-state keys are scoped per-market so switching between NSE and US
    doesn't carry over INR-scale values into a USD-scale field (or vice-versa).
    """
    mkt = (market or "NSE").upper()
    cfg = _FILTER_DEFAULTS_BY_MARKET.get(mkt, _FILTER_DEFAULTS_BY_MARKET["NSE"])
    sym = cfg["currency_symbol"]
    suffix = mkt.lower()  # per-market session key suffix (nse / us)

    with st.expander(
        f"🛑 Universal filters ({MARKET_LABEL.get(mkt, mkt)} · {sym})",
        expanded=False,
    ):
        c1, c2, c3 = st.columns(3)
        with c1:
            min_p = st.number_input(
                f"Min price ({sym})",
                min_value=0.1,
                max_value=float(cfg["min_price_max"]),
                value=float(cfg["min_price_default"]),
                step=float(cfg["min_price_step"]),
                key=f"{key_prefix}_{suffix}_min_p",
                help=(
                    "Filters out penny stocks below this price. "
                    f"Default {sym}{int(cfg['min_price_default'])} is a sensible floor for "
                    f"{'NSE F&O-friendly names' if mkt == 'NSE' else 'liquid US names (avoids sub-$5 chop)'}."
                ),
            )
            max_p = st.number_input(
                f"Max price ({sym})",
                min_value=float(cfg["min_price_step"]),
                max_value=float(cfg["max_price_max"]),
                value=float(cfg["max_price_default"]),
                step=float(cfg["max_price_step"]),
                key=f"{key_prefix}_{suffix}_max_p",
                help=(
                    "Caps very high-priced names where a single tick is large vs. capital. "
                    f"Default {sym}{int(cfg['max_price_default']):,} works for most retail intraday accounts."
                ),
            )
        with c2:
            min_avg_vol = st.number_input(
                "Min 20-day avg volume",
                min_value=10_000.0, max_value=50_000_000.0,
                value=float(cfg["avg_vol_default"]), step=50_000.0,
                key=f"{key_prefix}_{suffix}_min_avg_vol",
                help=cfg["avg_vol_help"],
            )
            min_vr = st.slider(
                "Min volume ratio (× 20-bar avg)",
                0.5, 5.0, 1.0, 0.1,
                key=f"{key_prefix}_{suffix}_min_vr",
                help="Ratio of latest bar volume vs. its 20-bar average. **1.0×** = relaxed default.",
            )
        with c3:
            min_rsi, max_rsi = st.slider(
                "RSI band",
                10.0, 90.0, (40.0, 80.0), 1.0,
                key=f"{key_prefix}_{suffix}_rsi_band",
                help="Relaxed default **40–80**. Tighten for fewer, higher-conviction names.",
            )
            min_chg = st.number_input(
                "Min |change %| vs prev close (0 = off)",
                min_value=0.0, max_value=10.0, value=0.0, step=0.1,
                key=f"{key_prefix}_{suffix}_min_chg",
                help="Optional. Set 0.3–0.5 to skip flat names. **0** = no minimum move filter.",
            )

    return IntradayFilters(
        min_price=float(min_p),
        max_price=float(max_p),
        min_avg_volume_20d=float(min_avg_vol),
        min_volume_ratio=float(min_vr),
        min_rsi=float(min_rsi),
        max_rsi=float(max_rsi),
        min_pct_change=float(min_chg),
    )


def _results_to_df(results: list[IntradayResult], *, market: str = "NSE") -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    rows = []
    for rank, r in enumerate(results, start=1):
        row = {
            "S.No.": rank,
            "Rank": f"#{rank}",
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Strategy": STRATEGY_LABEL.get(r.strategy, r.strategy),
            "Score /120": r.score_120,
            "Tier": r.rank_tier or "—",
            "Size": r.position_size or "—",
            "Rank Why": r.rank_why or "—",
            "Prediction": r.prediction or "—",
            "Sess vol %": r.session_vol_pct,
            "Sector": r.sector,
            "Price": r.price,
            "% chg": r.pct_change,
            "Gap %": r.gap_pct,
            "RSI(5m)": r.rsi,
            "Vol×": r.vol_ratio,
            "vs VWAP %": r.pct_vs_vwap,
            "vs 50DMA %": r.pct_vs_ma50d,
            "vs 200DMA %": r.pct_vs_ma200d,
            "↓ from 52w": r.pct_vs_52w_high,
            "ORB High": r.orb_high,
            "ORB Low": r.orb_low,
            "Entry": r.entry,
            "Stop": r.stop,
            "Target": r.target,
            "R:R": r.rr_ratio,
            "Setup": r.setup_note,
        }
        for name, url in (r.links or {}).items():
            row[name] = url
        rows.append(row)
    df = pd.DataFrame(rows)
    df = df.dropna(axis=1, how="all")
    if not df.empty:
        df = add_market_sentiment_columns(df, market=market, insert_after="Ticker")
        df = _add_intraday_news_scanner_columns(df, market=market)
    return df


def _gap_results_to_df(gaps: list[GapResult], *, market: str = "NSE") -> pd.DataFrame:
    if not gaps:
        return pd.DataFrame()
    rows = []
    for rank, g in enumerate(gaps, start=1):
        row = {
            "S.No.": rank,
            "Ticker": g.ticker,
            "Raw": g.raw_ticker,
            "Sector": g.sector,
            "Dir": ("⬆ UP" if g.direction == "UP" else ("⬇ DOWN" if g.direction == "DOWN" else "▬")),
            "Size": g.size_band,
            "Prev Close": g.prev_close,
            "Open": g.open_px,
            "LTP": g.current_price,
            "Gap %": g.gap_pct,
            "Open→Now %": g.open_to_now_pct,
            "Day High": g.intraday_high,
            "Day Low": g.intraday_low,
            "Vol×": g.vol_ratio,
            "Holding?": "✅" if g.holding else "⚠",
            "Advice": g.advice,
        }
        for name, url in (g.links or {}).items():
            row[name] = url
        rows.append(row)
    df = pd.DataFrame(rows)
    df = df.dropna(axis=1, how="all")
    if not df.empty:
        df = add_market_sentiment_columns(df, market=market, insert_after="Ticker")
        df = _add_intraday_news_scanner_columns(df, market=market)
    return df


def _intraday_col_cfg(df: pd.DataFrame) -> dict:
    return filter_column_config(
        df,
        {
            "Rank": st.column_config.TextColumn("Rank", width="small"),
            "Market sentiment": st.column_config.TextColumn("Market sentiment", width="medium"),
            "Sentiment why": st.column_config.TextColumn("Sentiment why", width="large"),
            SCAN_RESULTS_NEWS_COL: st.column_config.TextColumn(SCAN_RESULTS_NEWS_COL, width="large"),
            "News score": st.column_config.ProgressColumn("News score", min_value=0, max_value=100, format="%d"),
            "Top tier": st.column_config.TextColumn("Top tier", width="small"),
            "Tier reference": st.column_config.TextColumn("Tier reference", width="medium"),
            "Top headline": st.column_config.TextColumn("Top headline", width="large"),
            "Confirm action": st.column_config.TextColumn("Confirm action", width="medium"),
            "Strategy": st.column_config.TextColumn("Strategy", width="medium"),
            "Score /120": st.column_config.NumberColumn(
                "Score /120",
                format="%d",
                help="7-rule intraday quality score. Higher = cleaner setup.",
            ),
            "Tier": st.column_config.TextColumn("Tier", width="small"),
            "Size": st.column_config.TextColumn(
                "Size",
                width="small",
                help="Position size suggestion from score tier (100%, 75%, 50%, Skip).",
            ),
            "Rank Why": st.column_config.TextColumn(
                "Rank Why",
                width="large",
                help="Rule contribution breakdown + timing quality adjustment used for ranking.",
            ),
            "Prediction": st.column_config.TextColumn(
                "Prediction",
                width="large",
                help="Time-of-day volume quality · price moves only when volume is real.",
            ),
            "Sess vol %": st.column_config.NumberColumn(
                "Sess vol %",
                format="%d%%",
                help="Typical session volume participation at scan time (market clock).",
            ),
            "Setup": st.column_config.TextColumn("Setup", width="large"),
            "Price": st.column_config.NumberColumn(format="%.2f"),
            "% chg": st.column_config.NumberColumn(format="%+.2f"),
            "Gap %": st.column_config.NumberColumn(format="%+.2f"),
            "RSI(5m)": st.column_config.NumberColumn(format="%.1f"),
            "Vol×": st.column_config.NumberColumn(format="%.2f"),
            "vs VWAP %": st.column_config.NumberColumn(format="%+.2f"),
            "vs 50DMA %": st.column_config.NumberColumn(format="%+.2f"),
            "vs 200DMA %": st.column_config.NumberColumn(format="%+.2f"),
            "↓ from 52w": st.column_config.NumberColumn(format="%+.2f"),
            "ORB High": st.column_config.NumberColumn(format="%.2f"),
            "ORB Low": st.column_config.NumberColumn(format="%.2f"),
            "Entry": st.column_config.NumberColumn(format="%.2f"),
            "Stop": st.column_config.NumberColumn(format="%.2f"),
            "Target": st.column_config.NumberColumn(format="%.2f"),
            "R:R": st.column_config.NumberColumn(format="%.2f"),
            "Raw": None,
            "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
        },
    )


def _gap_col_cfg(df: pd.DataFrame) -> dict:
    return filter_column_config(
        df,
        {
            "Market sentiment": st.column_config.TextColumn("Market sentiment", width="medium"),
            "Sentiment why": st.column_config.TextColumn("Sentiment why", width="large"),
            SCAN_RESULTS_NEWS_COL: st.column_config.TextColumn(SCAN_RESULTS_NEWS_COL, width="large"),
            "News score": st.column_config.ProgressColumn("News score", min_value=0, max_value=100, format="%d"),
            "Top tier": st.column_config.TextColumn("Top tier", width="small"),
            "Tier reference": st.column_config.TextColumn("Tier reference", width="medium"),
            "Top headline": st.column_config.TextColumn("Top headline", width="large"),
            "Confirm action": st.column_config.TextColumn("Confirm action", width="medium"),
            "Dir": st.column_config.TextColumn("Dir", width="small"),
            "Size": st.column_config.TextColumn("Size", width="small"),
            "Prev Close": st.column_config.NumberColumn(format="%.2f"),
            "Open": st.column_config.NumberColumn(format="%.2f"),
            "LTP": st.column_config.NumberColumn(format="%.2f"),
            "Gap %": st.column_config.NumberColumn(format="%+.2f"),
            "Open→Now %": st.column_config.NumberColumn(format="%+.2f"),
            "Day High": st.column_config.NumberColumn(format="%.2f"),
            "Day Low": st.column_config.NumberColumn(format="%.2f"),
            "Vol×": st.column_config.NumberColumn(format="%.2f"),
            "Advice": st.column_config.TextColumn("Advice", width="large"),
            "Raw": None,
            "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
            "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
            "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
            "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
        },
    )


def _render_diagnostic_panel(stats: IntradayScanStats, *, key_prefix: str) -> None:
    """Funnel breakdown — why stocks passed or failed the scan."""
    if stats.total_scanned <= 0:
        return

    passed = stats.tickers_matched
    st.markdown("#### 🔍 Scan diagnostics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Scanned", stats.total_scanned)
    c2.metric("Matched (tickers)", passed)
    c3.metric("Result rows", stats.result_rows)
    data_note = []
    if stats.bars_5m:
        data_note.append(f"{stats.bars_5m} on 5m bars")
    if stats.bars_15m:
        data_note.append(f"{stats.bars_15m} on 15m fallback")
    c4.metric("Data source", " · ".join(data_note) if data_note else "—")

    if stats.bars_15m and stats.total_scanned:
        st.caption(
            f"ℹ **{stats.bars_15m}** ticker(s) used **15-min fallback** data "
            "(market closed or thin 5m feed). Results are still usable for planning; "
            "re-scan during live hours for best accuracy."
        )
    if stats.bars_extended_history and stats.total_scanned:
        st.caption(
            f"ℹ **{stats.bars_extended_history}** ticker(s) used **multi-day intraday history** "
            "(2d–10d 5m/15m) so RSI and volume-ratio filters have enough bars — common in early US session."
        )

    rows = [
        ("No intraday data (Yahoo)", stats.no_data),
        ("Failed price filter", stats.failed_price),
        ("Failed 20-day avg volume", stats.failed_avg_volume),
        ("No RSI (not enough bars)", stats.failed_no_rsi),
        ("No volume ratio (not enough bars)", stats.failed_no_volume_ratio),
        ("Volume ratio too low", stats.failed_volume_ratio),
        ("RSI outside band", stats.failed_rsi),
        ("|Change %| below minimum", stats.failed_min_change),
        ("Hard reject rules triggered", stats.failed_hard_reject),
        ("Passed filters but no strategy match", stats.no_strategy_match),
    ]
    fail_rows = [(label, n) for label, n in rows if n > 0]
    if fail_rows:
        diag_df = pd.DataFrame(fail_rows, columns=["Reason", "Count"])
        diag_df["% of universe"] = (diag_df["Count"] / stats.total_scanned * 100).round(1).astype(str) + "%"
        st.dataframe(diag_df, use_container_width=True, hide_index=True, key=f"{key_prefix}_diag_tbl")
    else:
        st.success("All scanned tickers either matched or had no recorded failure bucket.")

    if passed == 0 and stats.total_scanned > 0:
        st.warning(
            "**Tips to get results:** Vol ratio **1.0×** · RSI **40–80** · enable **🔍 Broad Movers** · "
            "lower min price / avg volume · run during market hours · try **Nifty 50** first."
        )


def _csv_download(
    df: pd.DataFrame,
    *,
    label: str,
    file_prefix: str,
    key: str,
    universe_name: str = "",
    market: str = "NSE",
) -> None:
    if df is None or df.empty:
        return
    df = prepare_scan_results_df(
        df,
        market=market,
        universe_name=universe_name,
        cache_key_prefix=f"csv_{key}",
        raw_ticker_col="Raw" if "Raw" in df.columns else None,
    )
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label,
        csv,
        file_name=f"{file_prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=key,
    )


# ─────────────────────────────────────────────────────────────
# Page 1: Intraday Screener (4-strategy)
# ─────────────────────────────────────────────────────────────
# What each strategy does, when to use it, and what a match tells the trader.
STRATEGY_PLAYBOOK: dict[str, dict[str, str]] = {
    "BROAD": {
        "does": "Loosest filter — flags any stock making a meaningful move on above-average "
                "volume (RSI 40–80). No chart pattern required.",
        "use":  "Any session window, especially when the stricter pattern strategies return too "
                "few names, or when you just want a broad list of what is moving today.",
        "means": "Low specificity — a *starting point*, not a setup. Confirm direction on the 5m chart "
                 "before acting.",
    },
    "MOMENTUM": {
        "does": "Strong stocks pushing higher — RSI ≥ 55, price above the 9-EMA, up on the day, "
                "near the 52-week high, with volume.",
        "use":  "The opening 60–90 minutes, when fresh trends establish and volume is real.",
        "means": "Trend-continuation long. Best when volume confirms; avoid chasing if already extended.",
    },
    "VWAP": {
        "does": "Up-trend stocks (above the 200-DMA) pulling back to within ±1% of VWAP on a calm "
                "RSI (42–65).",
        "use":  "Mid-morning to early afternoon, when the opening trend consolidates around VWAP.",
        "means": "Lower-risk continuation entry — buy the dip to VWAP with a tight stop just below it.",
    },
    "ORB": {
        "does": "Price breaking above the high of the first 15-minute range on volume.",
        "use":  "Strictly the post-open window (9:45–10:15 AM IST / 9:45–10:00 AM ET) — the opening "
                "range must have formed first.",
        "means": "Opening-range breakout long. Outside its window it returns little/nothing — that is "
                 "expected, not a bug.",
    },
    "GAP": {
        "does": "Stock gapping up ≥ 0.5%, holding above the open, RSI > 50, above the 50-DMA.",
        "use":  "Pre-open and the first 15 minutes, to catch a gap-and-go continuation.",
        "means": "Gap continuation long. Skip if the gap is already filling back toward prev close.",
    },
    "ATH": {
        "does": "Price at / within 2% of (or breaking) its true all-time high, volume ≥ 1.5×, "
                "RSI 55–78, above the 50-DMA.",
        "use":  "After ~10:00 AM (post-ORB) so you don't chase the first spike. Needs an extra "
                "all-time-high history fetch, so it is OFF by default — select it explicitly.",
        "means": "Highest-conviction breakout (zero overhead resistance). See the **ATH Strategy "
                 "Playbook** page for the full rulebook.",
    },
}


# Strategies ordered by where they fire in the trading session (earliest → latest).
# BROAD is time-agnostic so it sits last.
STRATEGY_TIME_ORDER = ("GAP", "MOMENTUM", "ORB", "ATH", "VWAP", "BROAD")


def _render_strategy_playbook(market: str) -> None:
    """Explain when to use each strategy, what it does, and what confluence means."""
    times = STRATEGY_BEST_TIME_BY_MARKET.get(market, STRATEGY_BEST_TIME_BY_MARKET["NSE"])
    ordered = [s for s in STRATEGY_TIME_ORDER if s in STRATEGIES]
    ordered += [s for s in STRATEGIES if s not in ordered]  # any new strategy falls through
    with st.expander(f"ℹ When to use each strategy — by session time ({MARKET_LABEL.get(market, market)})", expanded=False):
        st.caption("Ordered chronologically through the session: pre-open → opening → mid-day. "
                   "Broad Movers is time-agnostic, so it sits last.")
        for s in ordered:
            info = STRATEGY_PLAYBOOK.get(s, {})
            st.markdown(
                f"**{STRATEGY_LABEL.get(s, s)}**  \n"
                f"<span style='color:#7abeac;'>🕐 Best time:</span> {times.get(s, '—')}  \n"
                f"<span style='color:#7abeac;'>⚙ What it does:</span> {info.get('does', '')}  \n"
                f"<span style='color:#7abeac;'>✅ When to use:</span> {info.get('use', '')}  \n"
                f"<span style='color:#7abeac;'>📌 What a match means:</span> {info.get('means', '')}",
                unsafe_allow_html=True,
            )
            st.markdown("")
        st.markdown(
            "---\n"
            "**Do they matter together? — Yes, this is *signal confluence*:**\n"
            "- Each result is scored **0–120**; the score counts how many strategies a stock matched "
            "(shown as *Signals N* in the rank reason). **More strategies firing on the same stock = "
            "higher conviction.**\n"
            "- A stock under **several** strategies (e.g. *Gap + Momentum + ATH*) is a far stronger "
            "setup than one that only shows under **Broad Movers**.\n"
            "- If a name matches **only Broad Movers**, it is moving but has **no clean pattern** — "
            "treat it as a watchlist item, not a trade.\n"
            "- If a name **doesn't appear at all**, it failed the filters — open **🔍 Scan diagnostics** "
            "to see exactly which rule rejected it.\n"
            "- **Time-gating matters:** ORB/Gap are valid only in their narrow windows, so running them "
            "off-window yields few/no matches by design.\n\n"
            "**Tip:** select **more** strategies for the widest net + confluence detection; select "
            "**fewer** for a faster, more focused scan."
        )


def _render_breeze_token_refresh() -> None:
    """Daily session-token refresh widget — paste the apisession value, save, reconnect."""
    try:
        from breeze_data import login_url, update_session_token
    except Exception:
        return
    with st.expander("🔑 Refresh daily session token", expanded=False):
        st.caption(
            "The Breeze **session token expires every day**. Click the login link, sign in, then "
            "copy the `apisession=…` value from the redirected URL and paste it below."
        )
        st.markdown(f"1. Open the Breeze login: [**Log in to generate token →**]({login_url()})")
        st.markdown(
            "2. After login your browser goes to `http://localhost:8501/?apisession=XXXXXX` "
            "(the page may not load — that's fine). Copy the **XXXXXX**."
        )
        new_token = st.text_input(
            "3. Paste today's apisession token",
            key="breeze_token_input",
            placeholder="e.g. 55806325",
        )
        if st.button("💾 Save token & reconnect", key="breeze_token_save"):
            ok, msg = update_session_token(new_token)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)


def _render_breeze_status_banner() -> None:
    """Show ICICI Breeze connection status + setup hint on the Breeze screener."""
    try:
        from breeze_data import breeze_configured, breeze_status_message
    except Exception:
        st.warning("Breeze module unavailable — this screener will use Yahoo Finance data.")
        return
    configured = breeze_configured()
    msg = breeze_status_message()
    if configured:
        st.success(f"🟢 {msg}")
        _render_breeze_token_refresh()
    else:
        st.warning(f"🟠 {msg}")
        with st.expander("🔌 How to connect ICICI Breeze", expanded=False):
            st.markdown(
                "1. Register your app at "
                "[ICICI Direct API portal](https://api.icicidirect.com/apiuser/home).\n"
                "2. Install the SDK: `pip install breeze-connect`\n"
                "3. Add credentials to `.streamlit/secrets.toml` (repo root or `stocksight/.streamlit/`):\n"
                "```toml\n[breeze]\napi_key = \"your_api_key\"\napi_secret = \"your_api_secret\"\n"
                "session_token = \"your_session_token\"\n```\n"
                "   …or set env vars `BREEZE_API_KEY`, `BREEZE_API_SECRET`, `BREEZE_SESSION_TOKEN`.\n"
                "4. The **session token expires daily** — regenerate it from the Breeze login URL each day.\n\n"
                "Until then, this screener still runs on **Yahoo Finance** data automatically."
            )
        _render_breeze_token_refresh()


def render_intraday_screener_page(
    *,
    key: str = "id",
    breeze_mode: bool = False,
    force_market: Optional[str] = None,
) -> None:
    title = "ICICI Breeze Screener" if breeze_mode else "Intraday Screener"
    icon = "🟠" if breeze_mode else "📡"
    safe_set_page_config(page_title=f"{title} | StockSight", page_icon=icon, layout="wide")
    inject_css()

    if breeze_mode:
        st.markdown("### 🟠 ICICI Breeze Screener — live NSE intraday (Breeze data)")
        _render_breeze_status_banner()
        page_audience_note(
            "Active **NSE (India)** intraday traders who want candidates powered by **ICICI Direct "
            "Breeze** market data, with Entry / Stop / Target attached.",
            "Fetches 5-minute bars from **ICICI Breeze** when configured (auto-fallback to Yahoo "
            "Finance otherwise). Same 6-strategy engine + 7-rule ranking as the Intraday Screener, "
            "scoped to NSE. **Educational only — confirm risk before trading.**",
        )
    else:
        st.markdown("### 📡 Intraday Screener — 6 strategies, NSE or US")
        page_audience_note(
            "Active intraday traders on **NSE (India)** or **US (NYSE & NASDAQ)** who want "
            "pre-screened candidates with Entry / Stop / Target attached.",
            "Scans Yahoo Finance intraday bars (5m, auto-fallback to 15m when closed) + daily history. "
            "Includes **Broad Movers** for the widest net. Diagnostic panel shows why names failed. "
            "**Educational only — confirm risk before trading.**",
        )
    st.info(
        "⚙ **Recommended for results:** Vol ratio **1.0×** · RSI **40–80** · "
        "enable **🔍 Broad Movers** · Min change % = **0** · start with **Nifty 50**."
    )
    with st.expander("🏅 Ranking scorebook (7 rules · max 120)", expanded=False):
        st.markdown(
            """
| Rule | Max points | Best condition |
|------|------------|----------------|
| Volume ratio | +30 | Vol ≥ 5× |
| Gap quality | +20 | Gap ≥ 3% |
| Day change | +20 | Change ≥ 5% |
| RSI sweet spot | +15 | RSI 50–65 |
| Near 52-week high | +15 | Within -2% of 52w high |
| VWAP proximity | +10 | Within ±0.5% of VWAP |
| Trend alignment | +10 | Above both 50-DMA and 200-DMA |

Negative scoring is applied for weak/contra signals (e.g. gap-down, negative day, RSI>72, far below 52w high, too far from VWAP).

Tier + action:
- **≥ 80** → 🏆 Best (100% planned size)
- **50–79** → ✅ Good (75%)
- **25–49** → 🟡 OK (50%)
- **< 25** → ⚠️ Avoid (Skip)

Rows are ranked by **Score/120**, then adjusted by **scan timing quality** (best/good/mixed/avoid/dangerous).
"""
        )

    if force_market:
        market = force_market
        st.session_state[f"{key}_market"] = market
    else:
        market = _market_picker(key)
    _live_market_clocks()
    _session_banner(market)
    _render_market_schedule(market)

    with st.container(border=True):
        c1, c2 = st.columns([1.1, 1.0])
        with c1:
            uni_label, raw_tickers = _universe_picker(key, market)
        with c2:
            _default_strats = [s for s in ("BROAD", "MOMENTUM", "VWAP", "ORB", "GAP") if s in STRATEGIES]
            strategies_picked: list[str] = st.multiselect(
                "Strategies to scan",
                STRATEGIES,
                default=_default_strats,
                format_func=lambda s: STRATEGY_LABEL.get(s, s),
                key=f"{key}_strats",
                help="Enable **Broad Movers** for the widest net. Pattern strategies are stricter.",
            )
            _render_strategy_playbook(market)

    flt = _filters_panel(key, market)
    _news_confirmation_controls()

    run = st.button("▶  RUN INTRADAY SCAN", use_container_width=True, key=f"{key}_run")
    if market == "US":
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Best run at **3:45 PM CEST** (9:45 AM ET) for ORB/momentum · "
            "**5:30 PM CEST** (11:30 AM ET) for VWAP pullbacks."
        )
    else:
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Best run at **6:00 AM CEST** (9:30 AM IST) for breakouts · "
            "**7:00 AM CEST** (10:30 AM IST) for VWAP pullbacks."
        )

    if run:
        if not raw_tickers:
            st.warning("Universe is empty. Pick a list or paste tickers.")
            return
        if not strategies_picked:
            st.warning("Pick at least one strategy.")
            return
        prog = st.progress(0, text="Initialising…")

        def cb(i: int, t: int, s: str) -> None:
            prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {s}… ({i}/{t})")

        results, scan_stats = scan_intraday(
            raw_tickers,
            tuple(strategies_picked),
            flt,
            progress_cb=cb,
            market=market,
        )
        prog.empty()
        st.session_state[f"{key}_results"] = results
        st.session_state[f"{key}_stats"] = scan_stats
        st.session_state[f"{key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{key}_universe"] = uni_label
        st.session_state[f"{key}_scan_market"] = market

    results: list[IntradayResult] = st.session_state.get(f"{key}_results", [])
    scan_stats: Optional[IntradayScanStats] = st.session_state.get(f"{key}_stats")
    scan_at = st.session_state.get(f"{key}_at")
    last_uni = st.session_state.get(f"{key}_universe", "")

    if scan_stats is not None:
        _render_diagnostic_panel(scan_stats, key_prefix=key)

    scan_market = st.session_state.get(f"{key}_scan_market", market)
    _render_extended_bars_notice(scan_market, scan_stats)
    vol_pred = compute_volume_time_prediction(scan_market)
    st.markdown(
        f"""
<div style='background:#122f25; border:1px solid #1a3b31; border-left:4px solid #4db8ff;
            border-radius:8px; padding:12px 16px; margin:8px 0 12px 0;
            font-family:"IBM Plex Mono",monospace; font-size:0.82rem; color:#a3d8b8;'>
  <b style='color:#e8f7ef;'>📊 Volume is everything</b> · Now <b>{html.escape(vol_pred.market_local_time)}</b>
  · Session vol ~<b>{vol_pred.session_vol_pct}%</b><br>
  <span style='color:#e5f7ed;'>{html.escape(vol_pred.prediction)}</span>
</div>
""",
        unsafe_allow_html=True,
    )
    with st.expander("ℹ Session volume playbook (why Prediction matters)", expanded=False):
        st.markdown(
            """
| Clock (NSE) | Session vol | Moves |
|-------------|-------------|--------|
| 9:15 AM | ~100% | Real — but **too wild** |
| 10:00 AM | ~80% | Real — **best time** |
| 12:00 PM | ~20% | **Fake** — avoid new trades |
| 2:30 PM | ~60% | Real — **good** afternoon window |
| 3:25 PM | ~90% | **Forced** — dangerous, square off |

*US session uses the same shape on ET (9:30 open). Each result row also notes if **that stock's** volume (Vol×) confirms or looks thin.*
"""
        )

    if not results:
        if scan_at:
            st.warning(
                "No matches with current filters — see **Scan diagnostics** above for why. "
                "Try Vol ratio **1.0×**, RSI **40–80**, enable **Broad Movers**, or **Nifty 50**."
            )
        else:
            st.info("👆 Pick universe + strategies and click **RUN INTRADAY SCAN**.")
        return

    # ── Gap-Scanner cross-match (highest-probability filter) ─────────────
    gap_results = st.session_state.get("gap_results", [])
    gap_at = st.session_state.get("gap_at")
    gap_uni = st.session_state.get("gap_universe", "")
    gap_raw_set = {getattr(g, "raw_ticker", "") for g in (gap_results or []) if getattr(g, "raw_ticker", "")}
    overlap_count = sum(1 for r in results if r.raw_ticker in gap_raw_set)

    st.markdown(
        f"""
<div style='background:linear-gradient(135deg,#0f2a22 0%,#122f25 100%);
            border:1px solid #1a3b31; border-left:5px solid #f0b429;
            border-radius:12px; padding:14px 18px; margin:8px 0 12px 0;
            font-family:"IBM Plex Mono", monospace;'>
  <div style='font-size:0.95rem; color:#e8f7ef;'>
    🎯 <b>Cross-match with Gap Scanner</b> ·
    <span style='color:#f0b429;'>{overlap_count} stock(s) appear in BOTH</span> ·
    out of {len(results)} intraday matches and {len(gap_raw_set)} gapped names
  </div>
  <div style='color:#a3d8b8; font-size:0.78rem; margin-top:6px; line-height:1.55;'>
    💡 Stocks appearing in <b>both</b> the Gap Scanner (pre-market) and the Intraday Screener (after 9:30 AM)
    are the <b>highest-probability setups of the day</b> — the gap shows where the energy is,
    and the intraday strategy confirms a tradable setup is forming live.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    bc1, bc2 = st.columns([1.0, 2.0])
    with bc1:
        if not gap_raw_set:
            st.button(
                "🎯 Show only Gap Scanner overlap",
                key=f"{key}_overlap_btn",
                disabled=True,
                help="Run the Gap Scanner first (sidebar → ⚡ Intraday → Gap Scanner) to enable this filter.",
                use_container_width=True,
            )
            st.session_state[f"{key}_overlap_on"] = False
        else:
            st.session_state.setdefault(f"{key}_overlap_on", False)
            st.toggle(
                "🎯 Show only Gap Scanner overlap",
                key=f"{key}_overlap_on",
                help=(
                    "Filter the results to ONLY stocks that also appeared in the most recent Gap Scanner run "
                    "= highest-probability intraday setups."
                ),
            )
    with bc2:
        if gap_raw_set:
            st.caption(
                f"📅 Latest Gap Scanner: **{gap_uni or '—'}**" + (f" · {gap_at}" if gap_at else "")
                + f" · {len(gap_raw_set)} gapped name(s)"
            )
        else:
            st.caption(
                "⚠ No Gap Scanner results in this session yet. Open the **🌅 Gap Scanner** page "
                "(sidebar → ⚡ Intraday), click **SCAN GAPS NOW**, then return here to enable the overlap filter."
            )

    overlap_on = bool(gap_raw_set) and bool(st.session_state.get(f"{key}_overlap_on", False))
    if overlap_on:
        results = [r for r in results if r.raw_ticker in gap_raw_set]
        if not results:
            st.warning(
                "No overlap with current Gap Scanner results. "
                "Disable the overlap toggle to see all intraday matches, or rerun the Gap Scanner."
            )
            return

    # Headline strip — counts per strategy (post-overlap filter if active)
    counts = {s: 0 for s in STRATEGIES}
    for r in results:
        counts[r.strategy] = counts.get(r.strategy, 0) + 1
    c_cols = st.columns(len(STRATEGIES))
    for col, s in zip(c_cols, STRATEGIES):
        col.metric(STRATEGY_LABEL[s], counts.get(s, 0))

    overlap_note = " · 🎯 Gap-Scanner overlap only" if overlap_on else ""
    st.success(
        f"**{len(results)}** match(es) across {last_uni}{overlap_note}"
        + (f" · {scan_at}" if scan_at else "")
    )

    df_all = _results_to_df(results, market=scan_market)
    tab_labels = ["📋 All matches"] + [STRATEGY_LABEL[s] for s in STRATEGIES if counts.get(s, 0)]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        render_clickable_scan_table(
            df_all,
            key_prefix=f"{key}_all",
            universe_name=last_uni,
            market=scan_market,
            column_config=_intraday_col_cfg(df_all),
            height=min(620, 48 + len(df_all) * 36),
        )
        _csv_download(
            df_all,
            label="⬇ Download All matches CSV",
            file_prefix="stocksight_intraday_all",
            key=f"{key}_dl_all",
            universe_name=last_uni,
            market=scan_market,
        )

    tab_idx = 1
    scan_market = st.session_state.get(f"{key}_scan_market", market)
    best_times = STRATEGY_BEST_TIME_BY_MARKET.get(scan_market, STRATEGY_BEST_TIME_BY_MARKET["NSE"])
    for s in STRATEGIES:
        if not counts.get(s, 0):
            continue
        with tabs[tab_idx]:
            sub_results = [r for r in results if r.strategy == s]
            sub_df = _results_to_df(sub_results, market=scan_market)
            st.caption(f"Best time-of-day: **{best_times.get(s, '')}**")
            render_clickable_scan_table(
                sub_df,
                key_prefix=f"{key}_{s.lower()}",
                universe_name=last_uni,
                market=scan_market,
                column_config=_intraday_col_cfg(sub_df),
                height=min(560, 48 + len(sub_df) * 36),
            )
            _csv_download(
                sub_df,
                label=f"⬇ Download {STRATEGY_LABEL[s]} CSV",
                file_prefix=f"stocksight_intraday_{s.lower()}",
                key=f"{key}_dl_{s.lower()}",
                universe_name=last_uni,
                market=scan_market,
            )
        tab_idx += 1


# ─────────────────────────────────────────────────────────────
# Page 2: Gap Scanner (pre-market)
# ─────────────────────────────────────────────────────────────
def _mood_banner(mood: str, note: str) -> None:
    color = {"Bullish": "#25d366", "Bearish": "#e05252", "Mixed": "#f0b429"}.get(mood, "#7abeac")
    emoji = {"Bullish": "📈", "Bearish": "📉", "Mixed": "⚖", "Unknown": "❓"}.get(mood, "🕒")
    st.markdown(
        f"""
<div style='background:linear-gradient(135deg,#0f2a22 0%,#122f25 100%);
            border:1px solid #1a3b31; border-left:6px solid {color};
            border-radius:14px; padding:18px 22px; margin:6px 0 14px 0;
            font-family:"IBM Plex Mono",monospace;'>
  <div style='font-size:1.3rem; color:#e5f7ed; letter-spacing:0.5px;'>
    {emoji} Market Mood: <b style='color:{color};'>{html.escape(mood)}</b>
  </div>
  <div style='color:#a3d8b8; font-size:0.86rem; margin-top:6px; line-height:1.6;'>
    {html.escape(note)}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _mood_counters(gaps: list[GapResult]) -> None:
    large_up = sum(1 for g in gaps if g.direction == "UP" and g.size_band == "Large")
    med_up = sum(1 for g in gaps if g.direction == "UP" and g.size_band == "Medium")
    sm_up = sum(1 for g in gaps if g.direction == "UP" and g.size_band == "Small")
    large_dn = sum(1 for g in gaps if g.direction == "DOWN" and g.size_band == "Large")
    med_dn = sum(1 for g in gaps if g.direction == "DOWN" and g.size_band == "Medium")
    sm_dn = sum(1 for g in gaps if g.direction == "DOWN" and g.size_band == "Small")
    c = st.columns(6)
    c[0].metric("🚀 Large gap-ups", large_up)
    c[1].metric("📈 Medium gap-ups", med_up)
    c[2].metric("↗ Small gap-ups", sm_up)
    c[3].metric("💥 Large gap-downs", large_dn)
    c[4].metric("📉 Medium gap-downs", med_dn)
    c[5].metric("↘ Small gap-downs", sm_dn)


def render_icici_breeze_screener_page() -> None:
    """ICICI Breeze-powered live NSE intraday screener (reuses the intraday engine)."""
    render_intraday_screener_page(key="icici", breeze_mode=True, force_market="NSE")


def render_gap_scanner_page() -> None:
    safe_set_page_config(page_title="Gap Scanner | StockSight", page_icon="🌅", layout="wide")
    inject_css()

    st.markdown("### 🌅 Gap Scanner — pre-market battle map")
    page_audience_note(
        "Intraday traders who want to know where the energy is **before the bell** — NSE or US.",
        "Scans Yahoo Finance for stocks that **opened far from yesterday's close** and shows whether the "
        "gap is **holding or filling**. Includes a market-mood banner and plain-English advice per row. "
        "Best run during pre-market in your chosen market.",
    )

    key = "gap"
    market = _market_picker(key)
    _live_market_clocks()
    _session_banner(market)
    _render_market_schedule(market)

    with st.container(border=True):
        c1, c2 = st.columns([1.2, 1.0])
        with c1:
            uni_label, raw_tickers = _universe_picker(key, market)
        with c2:
            min_gap = st.slider(
                "Minimum |gap %|",
                0.3, 5.0, 1.0, 0.1,
                key=f"{key}_min_gap",
                help="Filter out micro-gaps. Default 1% catches most actionable setups.",
            )
    _news_confirmation_controls()

    run = st.button("▶  SCAN GAPS NOW", use_container_width=True, key=f"{key}_run")
    if market == "US":
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Run at **3:00 PM CEST** (9:00 AM ET) — pre-market gaps forming."
        )
    else:
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Run at **5:45 AM CEST** (9:15 AM IST) — see who gapped up/down before the open."
        )

    if run:
        if not raw_tickers:
            st.warning("Universe is empty.")
            return
        prog = st.progress(0, text="Initialising…")

        def cb(i: int, t: int, s: str) -> None:
            prog.progress(int(i / max(t, 1) * 100), text=f"Scanning {s}… ({i}/{t})")

        gaps = scan_gaps(raw_tickers, min_gap_abs_pct=float(min_gap), progress_cb=cb)
        prog.empty()
        st.session_state[f"{key}_results"] = gaps
        st.session_state[f"{key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{key}_universe"] = uni_label
        st.session_state[f"{key}_scan_market"] = market

    gaps: list[GapResult] = st.session_state.get(f"{key}_results", [])
    scan_at = st.session_state.get(f"{key}_at")
    last_uni = st.session_state.get(f"{key}_universe", "")

    if not gaps:
        if scan_at:
            st.warning("No gaps at this threshold. Lower the minimum |gap %| or wait for the open.")
        else:
            st.info("👆 Click **SCAN GAPS NOW** to populate the morning battle map.")
        return

    mood, note = compute_market_mood(gaps)
    _mood_banner(mood, note)
    _mood_counters(gaps)

    st.success(f"**{len(gaps)}** gaps ≥ {min_gap}% · {last_uni}" + (f" · {scan_at}" if scan_at else ""))

    gap_market = st.session_state.get(f"{key}_scan_market", "NSE")
    df = _gap_results_to_df(gaps, market=gap_market)
    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        market=gap_market,
        column_config=_gap_col_cfg(df),
        height=min(600, 48 + len(df) * 36),
    )
    _csv_download(
        df,
        label="⬇ Download Gap Scanner CSV",
        file_prefix="stocksight_gaps",
        key=f"{key}_dl",
        universe_name=last_uni,
        market=gap_market,
    )

    st.markdown("---")
    st.markdown(
        """
**Gap-trading cheat sheet:**

| Gap Size | What usually happens | Trade idea |
|---------|---------------------|------------|
| 0.5–1%  | Often fills back | Risky, avoid |
| 1–3%    | May hold or fill | ORB setup works well |
| 3%+     | Usually holds direction | Trade *with* the gap |

> **Gap-up + holds above gap = BUY momentum.**
> **Gap-down + stays below gap = SHORT / avoid longs.**
"""
    )


# ─────────────────────────────────────────────────────────────
# Page 3: Intraday Guide
# ─────────────────────────────────────────────────────────────
def render_intraday_guide_page() -> None:
    safe_set_page_config(page_title="Intraday Guide | StockSight", page_icon="📚", layout="wide")
    inject_css()

    st.markdown("### 📚 Intraday Trading Playbook")
    page_audience_note(
        "Anyone starting or refining their intraday journey — covers both **NSE (India)** and **US (NYSE/NASDAQ)** sessions.",
        "Pure educational reference — strategy choice, risk management, psychology, daily routine, "
        "screener rules and pre-trade checklist. Not financial advice.",
    )

    _live_market_clocks()

    # Show both market banners side-by-side so European traders see local time for each session.
    bnr_col1, bnr_col2 = st.columns(2)
    with bnr_col1:
        _session_banner("NSE")
    with bnr_col2:
        _session_banner("US")

    st.markdown(
        """
## 1️⃣ Build a strong foundation
- **Market structure** — how price moves, liquidity, bid-ask spreads.
- **Technical analysis** — candlestick patterns, support/resistance, trend lines.
- **Key indicators** — RSI, MACD, VWAP, Bollinger Bands, moving averages.
- **Order flow** — Level 2 data, volume profile, how institutional orders move price.

## 2️⃣ Pick ONE strategy & master it
| Strategy | Best for |
|---------|----------|
| **Momentum** | Stocks breaking out on volume |
| **Mean reversion** | Fade extreme moves back to VWAP / mean |
| **Gap trading** | Trade opening gaps at key levels |
| **Scalping** | Dozens of trades, 0.1–0.5 % each |

## 3️⃣ Risk management — most critical
- Never risk more than **1–2 % of capital per trade**.
- Set a **hard stop-loss before entering**.
- Maintain **R:R ≥ 1:2**.
- Know your **max daily loss limit** — stop trading when hit.
- *Position sizing matters more than entry accuracy.*

## 4️⃣ Psychological discipline
- **Revenge trading** kills accounts. Walk away after losses.
- Follow rules even when emotions scream otherwise.
- Losing trades are **normal** — pros win 50–60 %.
- Journal every trade: emotion, reason, outcome.

## 5️⃣ Tools you need
| Tool | Purpose |
|------|---------|
| Screener (this app, Chartink) | Find setups pre-market |
| Level-2 / Depth of Market | Read order flow |
| Charting (TradingView) | Technical analysis |
| Trade journal (Excel / Edgewonk) | Track & improve |

## 6️⃣ Realistic learning path
```
Paper trade (3–6 months)
  → Small capital (₹10k–50k)
    → Scale up ONLY after 3 consistent profitable months
```

## 7️⃣ What pros know that beginners don't
- **First 30 min** and **last 30 min** = highest volatility/opportunity.
- **Volume confirms everything** — no volume = fake-out.
- Fewer, **high-quality trades** beat frequent low-quality ones.
- Edge comes from **cutting losers fast**, not picking winners.
- They study **losing trades** more than winning ones.
"""
    )

    st.markdown("---")
    st.markdown("## 🔥 Screener rules (battle-tested)")
    st.markdown(
        """
### Strategy 0 — Broad Movers · *any session*
```
Vol ratio ≥ 1.0× (adjustable)
RSI between 40–80 (adjustable)
Any meaningful % move vs prev close (min change % = 0 by default)
```
*Widest net — use when pattern strategies return too few names.*

### Strategy 1 — Momentum Breakout · *9:30–11:00 AM*
```
RSI(14) > 60
Volume > 2 × 20-period avg
Close > 52w high one week ago
Close > Open  (green candle)
Delivery volume > 40 %
```

### Strategy 2 — VWAP Pullback · *10:30 AM – 1:00 PM*
```
Close > SMA(close, 200)
Close >= SMA(close, 9)
RSI(14) between 45 and 60
Volume > 1.5 × 20-period avg
|Close − Open| / Open < 0.5 %   (small body near VWAP)
```

### Strategy 3 — Opening Range Breakout (ORB) · *9:45–10:15 AM only*
```
Close > 52w high 1 day ago
Open > Close 1 day ago
Volume > 3 × 20-period avg
Market cap > 5000 cr

Manual: mark High/Low of first 15-min candle.
Enter ONLY on close above that high.
Stop = below the 15-min low.
```

### Strategy 4 — Gap-Up with Strength · *Pre-market + 9:15–9:30 AM*
```
Open > Yesterday Close × 1.01
Close > Open                  (holding the gap, green candle)
Volume > 2 × 20-period avg
RSI(14) > 55
Close > SMA(close, 50)
```

### Strategy 5 — 🏔️ All-Time High Breakout · *after 10:00 AM (post-ORB)*
```
Price at / within 2% of the prior ALL-TIME high
Volume ≥ 1.5 × 20-period avg   (institutional confirmation)
RSI(14) between 55 and 78       (strong, not parabolic)
Close > SMA(close, 50)          (trend intact)
Day change ≥ 0                  (holding, not fading)

Enter on a 5m/15m CLOSE above the prior ATH (not just a touch).
Stop = below the intraday base / breakout level.
Target = 1:2 R:R · trail the stop as new highs print.
```
*ATH breakouts have **zero overhead resistance** — see the **ATH Strategy Playbook**
page for the full rulebook, structure diagram, and Go / No-Go checklist. For the
**weekly** and **monthly/long-term** versions, use the dedicated ATH screener pages.*

### Universal filters (apply to every strategy)
```
Market cap > 5000 cr        ← Avoid illiquid small caps
Avg 20-day volume > 500 000  ← Minimum liquidity
50 ≤ Close ≤ 5000            ← Avoid penny + ultra-high price
Beta > 0.8                   ← Must move with market
```
"""
    )

    st.markdown("---")
    st.markdown("## ⏰ Time-based trading schedule")

    tab_nse, tab_us = st.tabs(["🇮🇳 Indian Market (NSE)", "🇺🇸 US Market (NYSE/NASDAQ)"])

    with tab_nse:
        st.caption("NSE regular session: **9:15 AM – 3:30 PM IST** · **5:45 AM – 12:00 PM CEST** (summer)")
        st.markdown(_schedule_rows_to_md(NSE_DAY_SCHEDULE, "India Time (IST)"))

    with tab_us:
        st.caption("US regular session: **9:30 AM – 4:00 PM ET** · **3:30 PM – 10:00 PM CEST** (summer)")
        st.markdown(_schedule_rows_to_md(US_DAY_SCHEDULE, "US Time (ET)"))
        st.info(
            "🇪🇺 **Tip for European day traders:** Run the US Gap Scanner at **3:00 PM CEST**, "
            "Intraday Scanner at **3:45 PM CEST**, square off by **9:45 PM CEST**. "
            "Never trade the first 5 minutes after the US open (9:30–9:35 AM ET)."
        )

    st.markdown("---")
    _render_full_day_glance()
    _render_quick_rules()

    st.markdown("---")
    st.markdown("## ✅ Pre-trade checklist")
    st.markdown(
        """
- [ ] Stock in F&O segment? (better liquidity)
- [ ] No results / news today that can cause wild swings?
- [ ] Volume ≥ 50 % of daily average by 10 AM?
- [ ] Sector also moving in same direction?
- [ ] R:R ≥ 1:2 from entry?
- [ ] Stop-loss level clearly defined?
"""
    )

    st.info(
        "📈 The **most reliable signals** appear when a stock shows up in **both** the Gap Scanner "
        "(pre-open) and the Intraday Screener (after 9:30 AM)."
    )
