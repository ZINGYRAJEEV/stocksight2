"""Streamlit page renderers for the Intraday module.

Pages:
    render_intraday_screener_page()  → 4-strategy intraday scanner with tabs
    render_gap_scanner_page()        → pre-market gap-up / gap-down scanner + mood
    render_intraday_guide_page()     → educational playbook (rules, routine, checklist)
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Any, Optional

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
    benchmark_intraday_data_sources,
    resolve_universe,
    scan_gaps,
    scan_intraday,
)
try:
    from scan_progress import (
        ScanLiveState,
        make_streamlit_scan_callback,
        render_live_scan_status,
    )
except ImportError:
    from .scan_progress import (  # type: ignore[no-redef]
        ScanLiveState,
        make_streamlit_scan_callback,
        render_live_scan_status,
    )
from market_sentiment import add_market_sentiment_columns
try:
    from quality_gate import (
        apply_quality_gate_columns,
        quality_gate_row_css,
        render_quality_gate_legend,
    )
except ImportError:
    from .quality_gate import (  # type: ignore[no-redef]
        apply_quality_gate_columns,
        quality_gate_row_css,
        render_quality_gate_legend,
    )
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


def _format_confluence(strategy_codes: list[str]) -> str:
    ordered = [s for s in STRATEGY_TIME_ORDER if s in strategy_codes]
    ordered += [s for s in strategy_codes if s not in ordered]
    if not ordered:
        return "—"
    if len(ordered) == 1:
        return STRATEGY_LABEL.get(ordered[0], ordered[0])
    short = " + ".join(STRATEGY_LABEL.get(s, s).split(" ", 1)[-1][:10] for s in ordered[:4])
    return f"{len(ordered)}× {short}"


def _render_intraday_results_table(
    df: pd.DataFrame,
    *,
    gap_highlight_test=None,
    **kwargs,
) -> Optional[str]:
    """Clickable intraday table with quality-gate row colours."""
    if df is None or df.empty:
        return None

    def _row_style(row: "pd.Series") -> list[str]:
        css = quality_gate_row_css(row)
        if gap_highlight_test is not None and gap_highlight_test(row):
            css = "background-color: #fff7ed; color: #7c2d12; border-left: 4px solid #f0b429;"
        return [css] * len(row)

    styler = df.style.apply(_row_style, axis=1)  # type: ignore[union-attr]
    kwargs.setdefault("show_gate_legend", False)
    return render_clickable_scan_table(df, styler=styler, **kwargs)


def _build_confluence_map(results: list[IntradayResult]) -> dict[str, list[str]]:
    confluence_map: dict[str, list[str]] = {}
    for r in results:
        confluence_map.setdefault(r.raw_ticker, [])
        if r.strategy not in confluence_map[r.raw_ticker]:
            confluence_map[r.raw_ticker].append(r.strategy)
    return confluence_map


def _results_to_df(
    results: list[IntradayResult],
    *,
    market: str = "NSE",
    confluence_map: Optional[dict[str, list[str]]] = None,
    sort_by_gate: bool = True,
    regime: Any = None,
) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    conf = confluence_map if confluence_map is not None else _build_confluence_map(results)
    try:
        from intraday_ranking import unified_intraday_score
    except ImportError:
        from .intraday_ranking import unified_intraday_score  # type: ignore[no-redef]

    rows = []
    for rank, r in enumerate(results, start=1):
        codes = conf.get(r.raw_ticker, [r.strategy])
        u_score, u_band, u_why = unified_intraday_score(r, len(codes), regime)
        row = {
            "S.No.": rank,
            "Rank": f"#{rank}",
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Confluence": _format_confluence(codes),
            "Strategy": STRATEGY_LABEL.get(r.strategy, r.strategy),
            "Unified score": u_score,
            "Unified band": u_band,
            "Rank why (unified)": u_why,
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
            "Exit plan": _exit_hint_for_strategy(r.strategy),
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
        df = apply_quality_gate_columns(df, profile="intraday", confluence_map=conf)
        if sort_by_gate and "Unified score" in df.columns:
            df = df.sort_values("Unified score", ascending=False, kind="stable").reset_index(drop=True)
            if "S.No." in df.columns:
                df["S.No."] = range(1, len(df) + 1)
            if "Rank" in df.columns:
                df["Rank"] = [f"#{i}" for i in range(1, len(df) + 1)]
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
        df = apply_quality_gate_columns(df, profile="gap", sort_by_gate=True)
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
            "Confluence": st.column_config.TextColumn(
                "Confluence",
                width="medium",
                help="Other intraday strategies that also matched this ticker in this scan.",
            ),
            "Quality Gate": st.column_config.TextColumn(
                "Quality Gate",
                width="small",
                help="A–D grade: strategy + sentiment + timing + news. Row colour matches band.",
            ),
            "Unified score": st.column_config.ProgressColumn(
                "Unified score",
                min_value=0,
                max_value=100,
                format="%d",
                help="Same ranking as Algo Strategy Hub: gate + score/120 + timing + confluence + regime.",
            ),
            "Gate score": st.column_config.ProgressColumn(
                "Gate score", min_value=0, max_value=100, format="%d",
            ),
            "Gate why": st.column_config.TextColumn("Gate why", width="large"),
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
            "Exit plan": st.column_config.TextColumn(
                "Exit plan",
                width="medium",
                help="Suggested profit-booking rule for this strategy (see Exit playbook below).",
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
    try:
        from quality_gate import quality_gate_column_config
    except ImportError:
        from .quality_gate import quality_gate_column_config  # type: ignore[no-redef]
    return filter_column_config(
        df,
        {
            **quality_gate_column_config(),
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
    elapsed = getattr(stats, "scan_elapsed_sec", 0.0) or 0.0
    avg_t = getattr(stats, "avg_sec_per_ticker", 0.0) or 0.0
    if elapsed > 0:
        st.caption(
            f"⏱ Scan took **{elapsed:.1f}s** total "
            f"(~**{avg_t:.2f}s** per ticker including filters & sector lookup)."
        )
    data_note = []
    api_label = {"auto": "Auto", "breeze": "Breeze", "yahoo": "Yahoo"}.get(
        getattr(stats, "data_source", "auto") or "auto", "—"
    )
    if stats.bars_from_breeze or stats.bars_from_yahoo:
        data_note.append(f"Breeze {stats.bars_from_breeze} · Yahoo {stats.bars_from_yahoo}")
    if stats.bars_5m:
        data_note.append(f"{stats.bars_5m} on 5m bars")
    if stats.bars_15m:
        data_note.append(f"{stats.bars_15m} on 15m fallback")
    c4.metric("Bars / API", f"{api_label} · " + (" · ".join(data_note) if data_note else "—"))

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
        ("No intraday data", stats.no_data),
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
    "EARLY": {
        "does": "Catches **pre-bust** movers: day up **0.35–8%** (up to **15%** on hot volume), RSI 42–78, "
                "**daily volume surge** (e.g. 2×+ vs 20-day avg) or heavy session participation, ORB coil/break "
                "or **vol-led extension**.",
        "use":  "First 60–75 minutes after open — **before** Momentum/ORB filters fire on a fully extended move.",
        "means": "Designed for names like TEJASNET / ZENTEC-style bursts. Can pass even if the **last bar** "
                 "volume is thin (bypasses vol<1.0 hard-reject when surge is real).",
    },
    "GRIND": {
        "does": "**Sector steady grind** — themed name (e.g. **Defence & Aerospace**), vol **≥1.35×**, "
                "price **+0.35–6% vs open** (smooth, not one spike), **≥68%** of session bars **above VWAP**, "
                "**15m higher highs**, max 5m bar **≤2.8%** (institutional accumulation, not FOMO).",
        "use":  "Mid-morning through early afternoon when sector peers drift up together (ZENTEC / MIDHANI style).",
        "means": "Slow slope + volume = smart money staging in. Different from Early Burst (fast burst) or Gap (open pop).",
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
STRATEGY_TIME_ORDER = ("GAP", "EARLY", "GRIND", "MOMENTUM", "ORB", "ATH", "VWAP", "BROAD")

# One-line exit hint shown on each scan row (matches scanner Target / Stop / R:R logic).
EXIT_HINT_BY_STRATEGY: dict[str, str] = {
    "GAP": "Book 50% at Target (1:2) · exit all if gap fills · flat by close",
    "EARLY": "Book partial at 1× risk · trail under ORB low · exit before lunch fade",
    "GRIND": "Book 50% at Target (1:1.5) · trail under VWAP · exit if 5m closes below VWAP",
    "MOMENTUM": "Book 50% at Target (1:2) · trail stop under 5m swing lows",
    "ORB": "Book 50–100% at Target (1:1.5) · exit if loses ORB high",
    "ATH": "Book 50% at Target (1:2) · trail stop on new highs",
    "VWAP": "Book 50% at Target (1:2) · exit if 5m close < VWAP",
    "BROAD": "Book 50% at 1× risk or Target · strict flat by close",
}

EXIT_PLAYBOOK: dict[str, dict[str, str]] = {
    "GAP": {
        "book": "**50% at Target** (scanner 1:2 R:R) · optional 25% at 1× risk · runner trails above prev close.",
        "exit_now": "Gap filling toward **yesterday’s close** · red 5m after open · **Prediction** = fake/lunch/forced.",
        "hold": "Holding gap + rising Vol× + **Prediction** still “real moves”.",
    },
    "MOMENTUM": {
        "book": "**50% at Target** (1:2) · move stop to **breakeven** · trail rest under each **5m higher low**.",
        "exit_now": "Big reversal candle · RSI > 72 · loses VWAP with volume · afternoon **Prediction** turns dangerous.",
        "hold": "Higher highs + Vol× ≥ 1.5× · stop only trails up, never down.",
    },
    "ORB": {
        "book": "**50–70% at Target** (1:1.5) — ORB moves are fast · many traders exit **full** at Target.",
        "exit_now": "**5m close back below ORB high** · stop hit (below ORB low) · lunch lull with thin volume.",
        "hold": "Stays above ORB high · first 90 min of session · volume not collapsing.",
    },
    "ATH": {
        "book": "**50% at Target** (1:2) · trail stop below **last 5m base** or prior ATH · add only on new highs.",
        "exit_now": "Fails to hold **above breakout / prior ATH** · climax volume + long upper wick.",
        "hold": "Closes above ATH on 5m/15m · trend + Vol× confirm · trail only upward.",
    },
    "VWAP": {
        "book": "**50% at Target** (1:2) · if extended, take **30% at 1× risk** first · rest trails **just under VWAP**.",
        "exit_now": "**5m close below VWAP** after entry · stop hit · lunch fake-move **Prediction**.",
        "hold": "Reclaimed VWAP and holding · RSI 42–65 · price between VWAP and Target.",
    },
    "BROAD": {
        "book": "**50% at 1× risk** OR **Target** (1:1.5) — weaker pattern, take profit earlier.",
        "exit_now": "Only Broad Movers match (no confluence) · **Prediction** bad · near session close.",
        "hold": "Also matches Momentum/GAP/ATH + green **Prediction** — treat like those exits.",
    },
}


def _exit_hint_for_strategy(strategy_code: str) -> str:
    return EXIT_HINT_BY_STRATEGY.get(strategy_code, "Book 50% at Target · flat all positions before close")


def _render_exit_playbook(market: str) -> None:
    """When to sell / book profit after intraday entries — aligned with Entry/Stop/Target columns."""
    mkt = (market or "NSE").upper()
    if mkt == "US":
        close_rule = "**3:45 PM ET** (9:45 PM CEST) — start squaring off · **no overnight** for pure intraday."
        lunch_note = "US lunch lull ~**12:00–1:00 PM ET** — book winners, avoid new adds."
    else:
        close_rule = "**3:15 PM IST** (11:45 AM CEST) — square off **all** intraday positions."
        lunch_note = "NSE lunch lull ~**12:00–2:30 PM IST** — thin volume; book partial profits."

    with st.expander("💰 When to sell / book profit (Exit playbook)", expanded=False):
        st.markdown(
            "Use the **Entry · Stop · Target · R:R** columns from your scan as the default plan. "
            "This section tells you **when to take money off the table** after a good move."
        )
        st.markdown(
            f"""
**Universal rules (every strategy)**  
1. **First booking:** sell **~50%** when price reaches **Target** OR profit = **1× risk** (Entry − Stop).  
2. **Protect the rest:** move stop to **breakeven** (entry) after the first booking.  
3. **Time stop:** {close_rule}  
4. **Volume stop:** if the row **Prediction** flips to *fake / lunch / forced / dangerous* — **exit winners**, don’t hope.  
5. {lunch_note}
"""
        )
        st.markdown("---")
        st.markdown("**By strategy** (matches the **Strategy** column in your table)")
        for s in STRATEGY_TIME_ORDER:
            if s not in STRATEGIES:
                continue
            info = EXIT_PLAYBOOK.get(s, {})
            st.markdown(
                f"**{STRATEGY_LABEL.get(s, s)}**  \n"
                f"- 📗 **Book profit:** {info.get('book', '—')}  \n"
                f"- 🔴 **Sell now (thesis broken):** {info.get('exit_now', '—')}  \n"
                f"- 🟢 **Can hold for Target/trail:** {info.get('hold', '—')}",
                unsafe_allow_html=True,
            )
            st.markdown("")
        st.markdown(
            "---\n"
            "**Quick checklist — take profit when any 2 apply:**  \n"
            "✓ At **Target** · ✓ Profit ≥ 1× risk and momentum stalling · ✓ Bad **Prediction** on the row · "
            "✓ Within **45 min of close** · ✓ Strategy-specific stop (VWAP / ORB / gap fill) hit.\n\n"
            "*Educational only — you manage real exits in your broker (ICICI / other).*"
        )


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


def _render_intraday_settings_cheatsheet(market: str) -> None:
    """Gap vs intraday workflow and recommended scanner settings by situation."""
    mkt = (market or "NSE").upper()
    if mkt == "US":
        gap_when = "**Gap Scanner** ~9:00 AM ET (3:00 PM CEST) · **Intraday** from ~9:45 AM ET"
        open_window = "9:45–11:00 AM ET"
        vwap_window = "11:00 AM – 1:30 PM ET"
        lunch_note = "1:30–3:00 PM ET — low conviction"
        square_off = "3:45 PM ET"
    else:
        gap_when = "**Gap Scanner** ~9:15 AM IST (5:45 AM CEST) · **Intraday** from ~9:30 AM IST"
        open_window = "9:30–11:00 AM IST"
        vwap_window = "10:30 AM – 1:00 PM IST"
        lunch_note = "1:00–2:00 PM IST — avoid new entries"
        square_off = "3:15 PM IST"

    with st.expander("📋 Settings cheat sheet — Gap missed or not missed", expanded=False):
        st.markdown(
            f"""
**What each tool does**

| Tool | When | Purpose |
|------|------|---------|
| **Gap Scanner** (sidebar) | {gap_when} | Gaps + **market mood** before you trade |
| **Intraday Screener** (this page) | After open | Live setups, Quality Gate, optional **overlap** with gap list |

Gap = **plan** · Intraday = **confirm** the setup live.

---

### Path A — Gap Scanner **not** missed (ideal)

1. **Gap scan** your universe → read mood, shortlist **3–5** names.
2. **RUN INTRADAY SCAN** at open → enable **Auto-refresh** (**60s**) for the first hour.
3. After results, toggle **Show only Gap Scanner overlap** for the tightest list.
4. Sort by **Unified score** · prefer Quality Gate **A/B**.

---

### Path B — Gap Scanner **missed**

| How late | What to do |
|----------|------------|
| **Few min** (just after open) | Run Gap scan **anyway**, then intraday + overlap filter |
| **30+ min** | **Early Burst + Broad + Momentum**; ORB/GAP will be sparse — expected |
| **Afternoon** | **Broad + Momentum** only; manage exits, few new entries |

Without a gap scan this session: rely on **Early Burst + Broad** + auto-refresh; overlap filter stays off until you run Gap Scanner.

---

### Settings by situation

| Situation | Universe | Strategies | Filters | Auto-refresh | Extra |
|-----------|----------|------------|---------|--------------|-------|
| **Normal morning** | Nifty 50/100 | Early, **Grind**, Broad, GAP, ORB, Momentum | Vol **1.0×**, RSI **40–80**, Min change **0** | **60s** until ~{open_window.split("–")[-1].strip()} | Gap **overlap** on |
| **Sector slow grind** | Nifty 500 / defence peers | **Grind**, Broad, VWAP | Same · RSI **50–72** on chart | **60–90s** 9:45–14:00 | Theme = Defence & Aerospace |
| **Missed gap, still morning** | Nifty 50 | Early, Broad, Momentum, ORB | Same | **60s** | Run gap when you can |
| **Late morning** | Nifty 50 | Early, Broad, Momentum, VWAP | Same | **90–120s** | Overlap optional |
| **Afternoon only** | Watchlist / Nifty 50 | Broad, Momentum | Same | Off or **180s** | Square off by **{square_off}** |

**Base filters (all paths):** Min price per market default · Min 20d avg volume default · Vol ratio **1.0×** · RSI **40–80** · Min |change %| **0**.

---

### Re-scan through the session ({MARKET_LABEL.get(mkt, mkt)})

| Session window | Emphasize |
|----------------|-----------|
| **{open_window}** | Early Burst, Sector Grind, GAP, ORB, Momentum + auto-refresh |
| **{vwap_window}** | VWAP, Momentum, Broad |
| **{lunch_note}** | Manage open trades only |
| **Before close** | No new entries · square off ~**{square_off}** |

---

**Quick rules:** Run **Gap before Intraday** when you can · **One RUN**, then auto-refresh · **Early Burst** for volume-led movers · **Broad** always on as safety net · Stop after **2 losses** · Never rely on a single scan at 10:30 for a 9:35 mover.

*Overlap = stocks in **both** Gap Scanner and this screener — highest-probability setups of the day.*
"""
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


_DATA_API_LABELS: dict[str, str] = {
    "auto": "Auto — ICICI Breeze if connected, else Yahoo Finance",
    "breeze": "ICICI Breeze only (live NSE 5-min + daily)",
    "yahoo": "Yahoo Finance only",
}


def _pick_breeze_data_source(key: str) -> str:
    """Radio to choose intraday/daily data API on the ICICI Breeze screener."""
    try:
        from breeze_data import breeze_configured

        breeze_ok = breeze_configured()
    except Exception:
        breeze_ok = False

    options = ("auto", "breeze", "yahoo")
    default = st.session_state.get(f"{key}_data_source", "auto")
    if default not in options:
        default = "auto"
    pick = st.radio(
        "Market data API for this scan",
        options=options,
        format_func=lambda k: _DATA_API_LABELS[k],
        index=options.index(default),
        key=f"{key}_data_api",
        horizontal=True,
    )
    if pick == "breeze" and not breeze_ok:
        st.warning(
            "Breeze is **not connected** — choose **Auto** or **Yahoo**, or refresh your "
            "daily session token in the sidebar / status banner."
        )
    elif pick == "auto" and breeze_ok:
        st.caption("✓ Breeze connected — **Auto** will use ICICI live data for NSE tickers.")
    return pick


def _render_api_speed_benchmark(key: str, raw_tickers: list[str]) -> None:
    """Compare ICICI Breeze vs Yahoo fetch speed on a small sample."""
    n_avail = len(raw_tickers)
    if n_avail < 1:
        return
    with st.expander("⚡ API speed test (Breeze vs Yahoo)", expanded=False):
        st.caption(
            "Times **one intraday + daily fetch per ticker** (no strategy logic). "
            "Use this to see which API is faster for your session and universe size."
        )
        sample_n = st.slider(
            "Sample size",
            min_value=3,
            max_value=min(25, n_avail),
            value=min(10, n_avail),
            key=f"{key}_bench_n",
        )
        run_bench = st.button("Run speed test", key=f"{key}_bench_run")
        if run_bench:
            bench_prog = st.progress(0, text="Starting benchmark…")
            bench_detail = st.empty()

            def _bench_cb(i: int, t: int, s: str, **kw: object) -> None:
                msg = str(kw.get("message") or s)
                bench_prog.progress(int(i / max(t, 1) * 100), text=f"{msg} ({i}/{t})")
                bench_detail.caption(msg)

            report = benchmark_intraday_data_sources(
                raw_tickers,
                max_tickers=sample_n,
                progress_cb=_bench_cb,
            )
            bench_prog.empty()
            bench_detail.empty()
            st.session_state[f"{key}_bench_report"] = report

        report = st.session_state.get(f"{key}_bench_report")
        if not report:
            return
        tickers = report.get("tickers") or []
        b = report.get("breeze") or {}
        y = report.get("yahoo") or {}
        winner = report.get("winner", "none")
        c1, c2, c3 = st.columns(3)
        c1.metric("Breeze avg / ticker", f"{b.get('avg_sec', 0):.2f}s")
        c2.metric("Yahoo avg / ticker", f"{y.get('avg_sec', 0):.2f}s")
        win_label = {"breeze": "ICICI Breeze", "yahoo": "Yahoo", "tie": "Roughly equal", "none": "—"}.get(
            str(winner), str(winner)
        )
        c3.metric("Faster on sample", win_label)
        rows = []
        b_times = b.get("times_sec") or []
        y_times = b.get("times_sec") or []
        for i, t in enumerate(tickers):
            rows.append(
                {
                    "Ticker": t,
                    "Breeze (s)": round(b_times[i], 3) if i < len(b_times) else None,
                    "Yahoo (s)": round(y_times[i], 3) if i < len(y_times) else None,
                }
            )
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(
            f"OK with data: Breeze **{b.get('ok', 0)}/{b.get('n', 0)}** · "
            f"Yahoo **{y.get('ok', 0)}/{y.get('n', 0)}**. "
            "Full scans also spend time on filters, sector lookup, and a small per-ticker delay."
        )


def _apply_scan_row_to_trade(key: str, row: "pd.Series") -> None:
    """Push a scan-results row into the Live Trade form (session state)."""
    raw = str(row.get("Raw", "") or "").strip()
    if raw:
        if not (raw.endswith(".NS") or raw.endswith(".BO")):
            raw = f"{raw}.NS"
        st.session_state[f"{key}_trade_selected_raw"] = raw
        st.session_state[f"{key}_trade_pick"] = raw
        st.session_state[f"{key}_trade_ticker"] = raw
    display = str(row.get("Ticker", "") or "").strip()
    if display:
        st.session_state[f"{key}_trade_selected_display"] = display
    entry_val = row.get("Entry")
    if entry_val is not None and pd.notna(entry_val):
        try:
            st.session_state[f"{key}_trade_limit"] = float(entry_val)
            st.session_state[f"{key}_trade_buytype"] = "Limit"
        except (TypeError, ValueError):
            pass
    stop_val = row.get("Stop")
    if stop_val is not None and pd.notna(stop_val):
        try:
            st.session_state[f"{key}_trade_sltrig"] = float(stop_val)
            st.session_state[f"{key}_trade_slmode"] = "Exact trigger ₹"
        except (TypeError, ValueError):
            pass
    st.session_state[f"{key}_trade_expand"] = True


def _render_breeze_trade_panel(key: str) -> None:
    """REAL-MONEY trade panel: BUY + stop-loss SELL via Breeze. Heavily guarded."""
    try:
        from breeze_data import (
            breeze_configured,
            get_ltp,
            place_buy_order,
            place_stoploss_sell,
        )
    except Exception:
        return
    if not breeze_configured():
        return

    expand = bool(st.session_state.get(f"{key}_trade_expand"))
    with st.expander(
        "⚠️ Live Trade — places REAL orders (BUY + stop-loss)",
        expanded=expand,
    ):
        st.error(
            "**This places real orders on your live ICICI account and can lose money.** "
            "Orders are sent only after you preview them and type CONFIRM. A stop-loss is a "
            "*trigger* — in fast moves it can fill below your stop (slippage). Educational tool; "
            "you are responsible for every confirmed order."
        )
        armed = st.checkbox(
            "I understand this sends real orders with real money.",
            key=f"{key}_trade_armed",
        )
        if not armed:
            st.caption("Tick the box above to enable the trade form.")
            return

        # Candidate tickers from the last scan (if any).
        results = st.session_state.get(f"{key}_results", [])
        scan_tickers = [getattr(r, "raw_ticker", "") for r in results if getattr(r, "raw_ticker", "")]
        scan_tickers = list(dict.fromkeys(scan_tickers))

        selected_raw = st.session_state.get(f"{key}_trade_selected_raw", "")
        selected_display = st.session_state.get(f"{key}_trade_selected_display", "")
        if selected_raw:
            st.info(
                f"**Loaded from scan row:** {selected_display or selected_raw} "
                f"(`{selected_raw}`) — click another row in the results table to change."
            )

        c1, c2 = st.columns([1.4, 1.0])
        with c1:
            pick_options = scan_tickers + ["Other (type below)"] if scan_tickers else ["Other (type below)"]
            if selected_raw and selected_raw in scan_tickers:
                st.session_state[f"{key}_trade_pick"] = selected_raw
            if scan_tickers:
                choice = st.selectbox(
                    "Ticker (from last scan, or choose ‘Other’)",
                    pick_options,
                    key=f"{key}_trade_pick",
                )
            else:
                choice = "Other (type below)"
                st.caption("Run a scan first, then click a row — or type a ticker below.")
            if choice != "Other (type below)":
                st.session_state[f"{key}_trade_ticker"] = choice
            typed = st.text_input(
                "Ticker (NSE, e.g. ICICIBANK.NS)",
                key=f"{key}_trade_ticker",
            )
            ticker = (typed or "").strip().upper()
            if ticker and not (ticker.endswith(".NS") or ticker.endswith(".BO")):
                ticker = f"{ticker}.NS"
        with c2:
            product_label = st.radio(
                "Hold style",
                ["Delivery (CNC)", "Intraday (MIS)"],
                key=f"{key}_trade_product",
            )
            product = "cash" if product_label.startswith("Delivery") else "margin"

        c3, c4, c5 = st.columns(3)
        with c3:
            buy_type = st.radio("BUY type", ["Market", "Limit"], key=f"{key}_trade_buytype")
        with c4:
            qty = int(st.number_input("Quantity", min_value=1, value=1, step=1, key=f"{key}_trade_qty"))
        with c5:
            limit_price = None
            if buy_type == "Limit":
                limit_price = float(
                    st.number_input(
                        "Limit price ₹", min_value=0.0, value=0.0, step=0.05, key=f"{key}_trade_limit"
                    )
                )

        # Live price for reference / % stop math.
        lp_col, _ = st.columns([1.0, 2.0])
        with lp_col:
            if st.button("🔄 Get live price", key=f"{key}_trade_ltp_btn"):
                st.session_state[f"{key}_trade_ltp"] = get_ltp(ticker) if ticker else None
        ltp = st.session_state.get(f"{key}_trade_ltp")
        if ltp:
            st.caption(f"Live price for **{ticker}**: ₹{ltp:,.2f}")

        scan_entry = st.session_state.get(f"{key}_trade_limit")
        scan_stop = st.session_state.get(f"{key}_trade_sltrig")
        if scan_entry or scan_stop:
            parts = []
            if scan_entry:
                parts.append(f"Entry **₹{float(scan_entry):,.2f}** (BUY → Limit)")
            if scan_stop:
                parts.append(f"Stop **₹{float(scan_stop):,.2f}**")
            st.caption("From scan row — " + " · ".join(parts))

        st.markdown("**Stop-loss (sell if it loses value)**")
        s1, s2 = st.columns(2)
        with s1:
            sl_mode = st.radio(
                "Stop-loss basis",
                ["% below entry", "Exact trigger ₹"],
                key=f"{key}_trade_slmode",
            )
        with s2:
            if sl_mode == "% below entry":
                sl_pct = float(
                    st.number_input(
                        "Stop %", min_value=0.1, max_value=50.0, value=3.0, step=0.1, key=f"{key}_trade_slpct"
                    )
                )
                sl_trigger_input = None
            else:
                sl_pct = None
                sl_trigger_input = float(
                    st.number_input(
                        "Trigger price ₹", min_value=0.0, value=0.0, step=0.05, key=f"{key}_trade_sltrig"
                    )
                )

        # Reference entry: limit price if a limit order, else the live price.
        entry_ref = limit_price if (buy_type == "Limit" and limit_price) else (ltp or 0.0)
        if sl_mode == "% below entry":
            sl_trigger = round(entry_ref * (1 - (sl_pct or 0) / 100.0), 2) if entry_ref else 0.0
        else:
            sl_trigger = sl_trigger_input or 0.0

        # Preview.
        st.markdown("**Order preview**")
        risk_per_share = (entry_ref - sl_trigger) if (entry_ref and sl_trigger) else 0.0
        st.table(
            {
                "Field": ["Ticker", "Side", "Hold", "BUY type", "Qty", "Entry ref ₹", "Stop trigger ₹", "Est. risk ₹"],
                "Value": [
                    ticker or "—",
                    "BUY + Stop-loss SELL",
                    product_label,
                    buy_type + (f" @ ₹{limit_price:,.2f}" if (buy_type == "Limit" and limit_price) else ""),
                    str(qty),
                    f"{entry_ref:,.2f}" if entry_ref else "—",
                    f"{sl_trigger:,.2f}" if sl_trigger else "—",
                    f"{risk_per_share * qty:,.2f}" if risk_per_share > 0 else "—",
                ],
            }
        )

        confirm = st.text_input(
            "Type CONFIRM to enable the order button", key=f"{key}_trade_confirm", placeholder="CONFIRM"
        )
        ready = (
            confirm.strip().upper() == "CONFIRM"
            and bool(ticker)
            and qty >= 1
            and sl_trigger > 0
            and (buy_type == "Market" or (limit_price and limit_price > 0))
        )
        if sl_trigger and entry_ref and sl_trigger >= entry_ref:
            st.warning("Stop trigger is at/above the entry reference — a SELL stop must be **below** entry.")
            ready = False

        if st.button("🚀 Place BUY + Stop-loss", key=f"{key}_trade_send", disabled=not ready, use_container_width=True):
            ok_b, msg_b, _ = place_buy_order(
                ticker, qty, order_type=("limit" if buy_type == "Limit" else "market"),
                price=limit_price, product=product,
            )
            (st.success if ok_b else st.error)(f"BUY: {msg_b}")
            if ok_b:
                ok_s, msg_s, _ = place_stoploss_sell(
                    ticker, qty, trigger_price=sl_trigger, product=product,
                )
                (st.success if ok_s else st.error)(f"Stop-loss SELL: {msg_s}")
                if not ok_s:
                    st.warning(
                        "⚠️ BUY went through but the stop-loss did **not** — your position is "
                        "currently UNPROTECTED. Place a stop-loss manually now."
                    )
            st.caption("Check your ICICI Direct order book to verify status.")


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


def _filters_to_dict(flt: IntradayFilters) -> dict[str, float]:
    return {
        "min_price": flt.min_price,
        "max_price": flt.max_price,
        "min_avg_volume_20d": flt.min_avg_volume_20d,
        "min_volume_ratio": flt.min_volume_ratio,
        "min_rsi": flt.min_rsi,
        "max_rsi": flt.max_rsi,
        "min_pct_change": flt.min_pct_change,
    }


def _filters_from_dict(d: dict[str, float]) -> IntradayFilters:
    return IntradayFilters(
        min_price=float(d.get("min_price", 50.0)),
        max_price=float(d.get("max_price", 5000.0)),
        min_avg_volume_20d=float(d.get("min_avg_volume_20d", 500_000.0)),
        min_volume_ratio=float(d.get("min_volume_ratio", 1.0)),
        min_rsi=float(d.get("min_rsi", 40.0)),
        max_rsi=float(d.get("max_rsi", 80.0)),
        min_pct_change=float(d.get("min_pct_change", 0.0)),
    )


def _run_intraday_scan_core(
    *,
    key: str,
    raw_tickers: list[str],
    strategies: tuple[str, ...],
    flt: IntradayFilters,
    market: str,
    scan_api: str,
    uni_label: str,
    live_detail,
    prog,
    live_state: ScanLiveState,
    cb,
) -> tuple[list[IntradayResult], IntradayScanStats]:
    results, scan_stats = scan_intraday(
        raw_tickers,
        strategies,
        flt,
        progress_cb=cb,
        market=market,
        data_source=scan_api,
    )
    try:
        from algo_selector import detect_market_regime
        from intraday_ranking import sort_intraday_results
    except ImportError:
        from .algo_selector import detect_market_regime  # type: ignore[no-redef]
        from .intraday_ranking import sort_intraday_results  # type: ignore[no-redef]

    regime, regime_note = detect_market_regime(market=market, sample_tickers=raw_tickers[:40])
    st.session_state[f"{key}_regime"] = regime
    st.session_state[f"{key}_regime_note"] = regime_note
    results = sort_intraday_results(results, regime)

    prog.progress(100, text="Scan complete")
    live_state.tick(
        len(raw_tickers),
        len(raw_tickers),
        "",
        stage="done",
        message=f"Finished in {getattr(scan_stats, 'scan_elapsed_sec', 0):.1f}s",
        matched=scan_stats.tickers_matched,
        no_data=scan_stats.no_data,
    )
    render_live_scan_status(live_state, detail_slot=live_detail)
    st.session_state[f"{key}_results"] = results
    st.session_state[f"{key}_stats"] = scan_stats
    st.session_state[f"{key}_at"] = datetime.now().strftime("%d %b %Y %H:%M:%S")
    st.session_state[f"{key}_universe"] = uni_label
    st.session_state[f"{key}_scan_market"] = market
    st.session_state[f"{key}_data_source"] = scan_api
    return results, scan_stats


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
        st.markdown("### 🟠 ICICI Breeze Screener — live NSE intraday")
        _render_breeze_status_banner()
        data_source = _pick_breeze_data_source(key)
        page_audience_note(
            "Active **NSE (India)** intraday traders who want candidates with Entry / Stop / Target "
            "attached, using **ICICI Breeze** or **Yahoo Finance** data (your choice per scan).",
            "Pick the data API above before each scan. **Auto** uses Breeze when your session token "
            "is valid, otherwise Yahoo. Same 8-strategy engine + 7-rule ranking as the Intraday Screener. "
            "**Educational only — confirm risk before trading.**",
        )
    data_source = "auto"
    if not breeze_mode:
        st.markdown("### 📡 Intraday Screener — 8 strategies, NSE or US")
        page_audience_note(
            "Active intraday traders on **NSE (India)** or **US (NYSE & NASDAQ)** who want "
            "pre-screened candidates with Entry / Stop / Target attached.",
            "Scans Yahoo Finance intraday bars (5m, auto-fallback to 15m when closed) + daily history. "
            "Includes **Broad Movers** for the widest net. Diagnostic panel shows why names failed. "
            "**Educational only — confirm risk before trading.**",
        )
    st.info(
        "⚙ **Recommended for results:** Vol ratio **1.0×** · RSI **40–80** · "
        "enable **🔍 Broad Movers** + **⚡ Early Burst** · Min change % = **0** · start with **Nifty 50**."
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

Rows are ranked by **Unified score** (same formula as **Algo Strategy Hub**): Quality Gate + Score/120 + timing + confluence + regime fit + vol/R:R.
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
    _render_intraday_settings_cheatsheet(market)

    with st.container(border=True):
        c1, c2 = st.columns([1.1, 1.0])
        with c1:
            uni_label, raw_tickers = _universe_picker(key, market)
        with c2:
            _default_strats = [
                s for s in ("BROAD", "EARLY", "GRIND", "MOMENTUM", "VWAP", "ORB", "GAP") if s in STRATEGIES
            ]
            strategies_picked: list[str] = st.multiselect(
                "Strategies to scan",
                STRATEGIES,
                default=_default_strats,
                format_func=lambda s: STRATEGY_LABEL.get(s, s),
                key=f"{key}_strats",
                help="Enable **⚡ Early Burst** to catch pre-bust movers (TEJASNET-style volume surge). "
                "**Broad Movers** for the widest net.",
            )
            _render_strategy_playbook(market)

    flt = _filters_panel(key, market)
    _news_confirmation_controls()

    if breeze_mode:
        _render_api_speed_benchmark(key, raw_tickers)
    elif market == "NSE":
        data_source = _pick_breeze_data_source(key)
        _render_api_speed_benchmark(key, raw_tickers)
    else:
        data_source = "yahoo"
        st.caption("US scans use **Yahoo Finance** for intraday bars (ICICI Breeze is NSE/BSE only).")

    r1, r2, r3 = st.columns([1.0, 1.1, 1.0])
    with r1:
        run = st.button("▶  RUN INTRADAY SCAN", use_container_width=True, key=f"{key}_run")
    with r2:
        st.session_state.setdefault(f"{key}_auto_scan", True)
        auto_scan = st.checkbox(
            "Auto-refresh scan (live)",
            key=f"{key}_auto_scan",
            help="Re-runs the same universe + filters on a timer. Keep this tab open.",
        )
    with r3:
        scan_iv = st.slider(
            "Refresh every (sec)",
            30,
            180,
            int(st.session_state.get(f"{key}_scan_iv", 60)),
            5,
            key=f"{key}_scan_iv",
            disabled=not auto_scan,
        )

    if market == "US":
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Best run at **3:45 PM CEST** (9:45 AM ET) for ORB/momentum · "
            "**5:30 PM CEST** (11:30 AM ET) for VWAP pullbacks."
        )
    else:
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Use **⚡ Early Burst** + auto-refresh 9:30–10:45 IST to catch movers **before** they extend."
        )

    with st.expander("📐 Sector Steady Grind — ZENTEC / MIDHANI logic", expanded=False):
        st.markdown(
            """
**Common pattern:** peers in the same **theme** (e.g. **Defence & Aerospace**) rise **slowly since open** — no single news spike, 
**volume ≥1.35×**, price **holds above VWAP** most of the session, **15m higher highs**, and **no violent 5m candles** (max bar ≤ ~2.8%).

| Check | Rule in screener |
|-------|------------------|
| Specialization | Yahoo sector/industry keywords **or** known theme tickers (HAL, BEL, ZENTEC, MIDHANI, …) |
| Volume | Bar or daily vol **≥1.35×** average |
| vs open | **+0.35% to +6%** (wider if daily vol very hot) |
| VWAP | **≥68%** of session bars close above VWAP |
| Structure | **15m higher-high score ≥50%** · smooth 5m bodies |
| RSI | **52–72** (or **40–72** when VWAP-hold + smooth grind) |

Enable **📐 Sector Steady Grind** in strategies. Use **Nifty 500** or a defence watchlist + **auto-refresh** mid-morning.

*Early Burst* = fast burst · *Grind* = slow institutional slope in a themed sector.
"""
        )

    with st.expander("⚡ Why TEJASNET / ZENTEC-style moves were easy to miss", expanded=False):
        st.markdown(
            """
**What happened (Yahoo daily data):**
- **TEJASNET** — ~**5×** daily volume vs prior weeks; multi-day trend (+25% / 5d) with a sharp **Jun 3–4** burst.
- **ZENTEC** — quiet name until **today’s volume explosion** (~10× typical) and a **+7–8%** session.

**Why the old screener lagged:**
1. **Momentum** wants RSI≥55 + extension — often fires **after** the first leg.
2. **Hard reject `vol<1.0×`** on the **last 5m bar** — fails when volume already printed earlier in the session.
3. No rule for **daily volume surge** independent of the latest bar.

**What we added:**
- **⚡ Early Burst** — ORB coil/break **or** vol-led extension when **daily vol ≥2×**; up to **+15%** day move on hot volume; recovery names up to **~28%** below 52W high.
- Scoring / Quality Gate boost for volume surge; thin **last-bar** volume no longer hard-rejects Early hits.
- **Auto-refresh** so the table updates without clicking RUN again.

*Tip: Nifty 50 + Early Burst + 60s refresh during the first hour.*
"""
        )

    scan_cfg_ready = bool(raw_tickers and strategies_picked)
    scan_api = data_source if market == "NSE" or breeze_mode else "yahoo"

    if run and scan_cfg_ready:
        st.session_state[f"{key}_scan_cfg"] = {
            "tickers": list(raw_tickers),
            "strategies": tuple(strategies_picked),
            "filters": _filters_to_dict(flt),
            "market": market,
            "scan_api": scan_api,
            "uni_label": uni_label,
        }
        # When auto-refresh is on, only the fragment runs the scan (avoids duplicate UI).
        if not auto_scan:
            st.markdown("#### Live scan status")
            live_detail = st.empty()
            prog = st.progress(0, text="Initialising…")
            live_state = ScanLiveState(total=len(raw_tickers), data_source=scan_api)
            cb = make_streamlit_scan_callback(prog, live_detail, state=live_state)
            results, scan_stats = _run_intraday_scan_core(
                key=key,
                raw_tickers=raw_tickers,
                strategies=tuple(strategies_picked),
                flt=flt,
                market=market,
                scan_api=scan_api,
                uni_label=uni_label,
                live_detail=live_detail,
                prog=prog,
                live_state=live_state,
                cb=cb,
            )
            if breeze_mode and results:
                _apply_scan_row_to_trade(
                    key, pd.Series(_results_to_df([results[0]], market=market).iloc[0])
                )
        elif auto_scan:
            st.caption("Auto-refresh will run the scan below — one live status panel.")
    elif run:
        if not raw_tickers:
            st.warning("Universe is empty. Pick a list or paste tickers.")
            return
        if not strategies_picked:
            st.warning("Pick at least one strategy.")
            return

    cfg = st.session_state.get(f"{key}_scan_cfg")
    if auto_scan and cfg and scan_cfg_ready:
        if len(raw_tickers) > 120:
            st.warning("Auto-refresh works best on **≤120** tickers — use Nifty 50 / 100 for speed.")
        st.info(f"**Live scan** — refreshing every **{scan_iv}s** (same universe & filters). Keep this tab open.")

        @st.fragment(run_every=timedelta(seconds=max(30, int(scan_iv))))
        def _intraday_auto_scan() -> None:
            if not st.session_state.get(f"{key}_auto_scan", False):
                return
            c = st.session_state.get(f"{key}_scan_cfg") or cfg
            tickers = c.get("tickers") or raw_tickers
            strats = tuple(c.get("strategies") or strategies_picked)
            flt_c = _filters_from_dict(c.get("filters") or _filters_to_dict(flt))
            mkt = c.get("market") or market
            api = c.get("scan_api") or scan_api
            uni = c.get("uni_label") or uni_label
            st.markdown("#### Live scan status")
            live_detail = st.empty()
            prog = st.progress(0, text="Refreshing…")
            live_state = ScanLiveState(total=len(tickers), data_source=api)
            cb = make_streamlit_scan_callback(prog, live_detail, state=live_state)
            _run_intraday_scan_core(
                key=key,
                raw_tickers=tickers,
                strategies=strats,
                flt=flt_c,
                market=mkt,
                scan_api=api,
                uni_label=uni,
                live_detail=live_detail,
                prog=prog,
                live_state=live_state,
                cb=cb,
            )

        _intraday_auto_scan()

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
    ds_note = ""
    ds_key = st.session_state.get(
        f"{key}_data_source", getattr(scan_stats, "data_source", "auto") if scan_stats else "auto"
    )
    if scan_market == "NSE" or breeze_mode:
        ds_note = f" · Data API: **{_DATA_API_LABELS.get(ds_key, ds_key)}**"
    st.success(
        f"**{len(results)}** match(es) across {last_uni}{overlap_note}{ds_note}"
        + (f" · {scan_at}" if scan_at else "")
    )
    regime_note = st.session_state.get(f"{key}_regime_note", "")
    if regime_note:
        st.info(f"**Market regime (Hub-aligned):** {regime_note}")
    st.caption(
        "Sorted by **Unified score** (Screener + Hub). Rows are **colour-coded** by **Quality Gate** (A–D). "
        "See **Confluence** for multi-strategy matches. **Exit plan** + **💰 When to sell** below."
    )
    render_quality_gate_legend(profile="intraday")

    conf_map = _build_confluence_map(results)
    scan_regime = st.session_state.get(f"{key}_regime")
    df_all = _results_to_df(
        results,
        market=scan_market,
        confluence_map=conf_map,
        sort_by_gate=True,
        regime=scan_regime,
    )
    gap_raw_set = {getattr(g, "raw_ticker", "") for g in (st.session_state.get("gap_results") or []) if getattr(g, "raw_ticker", "")}
    tab_labels = ["📋 All matches"] + [STRATEGY_LABEL[s] for s in STRATEGIES if counts.get(s, 0)]
    tabs = st.tabs(tab_labels)

    trade_row_cb = (lambda row: _apply_scan_row_to_trade(key, row)) if breeze_mode else None
    table_caption = (
        "💡 **Click any row** — loads chart below and fills **⚠️ Live Trade** with that ticker’s Entry/Stop."
        if breeze_mode
        else "💡 Click any row to load its interactive chart + pre-buy research below."
    )

    with tabs[0]:
        _render_intraday_results_table(
            df_all,
            key_prefix=f"{key}_all",
            universe_name=last_uni,
            market=scan_market,
            column_config=_intraday_col_cfg(df_all),
            height=min(620, 48 + len(df_all) * 36),
            caption=table_caption + " · 🟢/🟡/🟠/🔴 = Quality Gate band.",
            on_row_select=trade_row_cb,
            gap_highlight_test=(
                (lambda row, g=gap_raw_set: str(row.get("Raw", "")) in g) if gap_raw_set else None
            ),
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
            sub_df = _results_to_df(
                sub_results,
                market=scan_market,
                confluence_map=conf_map,
                sort_by_gate=True,
                regime=scan_regime,
            )
            st.caption(f"Best time-of-day: **{best_times.get(s, '')}**")
            _render_intraday_results_table(
                sub_df,
                key_prefix=f"{key}_{s.lower()}",
                universe_name=last_uni,
                market=scan_market,
                column_config=_intraday_col_cfg(sub_df),
                height=min(560, 48 + len(sub_df) * 36),
                caption=table_caption,
                on_row_select=trade_row_cb,
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

    st.markdown("---")
    _render_exit_playbook(scan_market)

    if breeze_mode:
        st.markdown("---")
        _render_breeze_trade_panel(key)


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


def _breeze_rows_to_df(rows: list, prefer: tuple[str, ...]) -> "pd.DataFrame":
    """Build a tidy DataFrame from Breeze list-of-dicts, surfacing key columns first."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    ordered = [c for c in prefer if c in df.columns]
    rest = [c for c in df.columns if c not in ordered]
    return df[ordered + rest]


def _scan_plans_lookup() -> dict[str, dict]:
    """Last intraday scan rows keyed by Raw ticker and bare NSE symbol."""
    plans: dict[str, dict] = {}
    for sess_key in ("icici", "id"):
        for r in st.session_state.get(f"{sess_key}_results", []) or []:
            raw = (getattr(r, "raw_ticker", "") or "").strip().upper()
            if not raw:
                continue
            plan = {
                "entry": getattr(r, "entry", None),
                "stop": getattr(r, "stop", None),
                "target": getattr(r, "target", None),
                "strategy": getattr(r, "strategy", ""),
                "prediction": getattr(r, "prediction", "") or "",
                "exit_hint": _exit_hint_for_strategy(getattr(r, "strategy", "")),
            }
            plans[raw] = plan
            bare = raw.replace(".NS", "").replace(".BO", "")
            plans[bare] = plan
    return plans


def _breeze_code_to_ticker(stock_code: str) -> str:
    """Map Breeze stock_code (ISEC or NSE symbol) to yfinance-style ticker."""
    code = (stock_code or "").strip().upper()
    if not code:
        return ""
    if code.endswith(".NS") or code.endswith(".BO"):
        return code
    try:
        from breeze_data import lookup_nse_symbol

        sym = lookup_nse_symbol("NSE", code)
        if sym:
            return sym if "." in sym else f"{sym}.NS"
    except Exception:
        pass
    return f"{code}.NS"


def _position_sell_candidates(pos_rows: list) -> list[dict]:
    """Open long positions that can be sold via Breeze."""
    out: list[dict] = []
    for row in pos_rows or []:
        if not isinstance(row, dict):
            continue
        try:
            qty = int(float(row.get("quantity") or 0))
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        if str(row.get("action", "")).lower() == "sell":
            continue
        code = str(row.get("stock_code", ""))
        ticker = _breeze_code_to_ticker(code)
        prod = str(row.get("product_type", "") or "cash").lower()
        product = "margin" if "margin" in prod or "mis" in prod else "cash"
        out.append(
            {
                "label": f"{code} · qty {qty} · {ticker}",
                "stock_code": code,
                "sell_ticker": ticker,
                "sell_qty": qty,
                "ltp": row.get("ltp"),
                "product": product,
                "average_price": row.get("average_price"),
            }
        )
    return out


def _render_breeze_sell_panel(
    candidates: list[dict],
    *,
    key_prefix: str = "bpos",
    hint_row: Optional[dict] = None,
) -> None:
    """Place a real SELL order for an open ICICI position."""
    try:
        from breeze_data import breeze_configured, place_sell_order
    except Exception:
        return
    if not breeze_configured():
        return

    with st.expander("⚠️ Sell from screen — places REAL SELL orders", expanded=False):
        st.error(
            "**This sends a real SELL order on your ICICI account.** "
            "Use only after you read **Sell now?** and **Why sell?**. "
            "Requires typed CONFIRM below."
        )
        if not candidates:
            st.info("No open long positions to sell. Check **📈 Open Positions** after you buy.")
            return

        armed = st.checkbox(
            "I understand this sells real shares from my account.",
            key=f"{key_prefix}_sell_armed",
        )
        if not armed:
            return

        labels = [c["label"] for c in candidates]
        default_idx = 0
        if hint_row and hint_row.get("stock_code"):
            for i, c in enumerate(candidates):
                if c["stock_code"] == hint_row["stock_code"]:
                    default_idx = i
                    break
        pick_label = st.selectbox(
            "Position to sell",
            labels,
            index=default_idx,
            key=f"{key_prefix}_sell_pick",
        )
        sel = next(c for c in candidates if c["label"] == pick_label)
        ticker = sel["sell_ticker"]
        max_qty = int(sel["sell_qty"])

        if hint_row:
            why = hint_row.get("Why sell?") or ""
            sell_sig = hint_row.get("Sell now?") or ""
            if why or sell_sig:
                st.markdown(f"**Signal:** {sell_sig}  \n**Why:** {why}")

        c1, c2, c3 = st.columns(3)
        with c1:
            sell_type = st.radio("SELL type", ["Market", "Limit"], key=f"{key_prefix}_sell_type", horizontal=True)
        with c2:
            pct = st.slider("Quantity % of position", 25, 100, 100, 25, key=f"{key_prefix}_sell_pct")
            qty = max(1, int(max_qty * pct / 100))
            st.caption(f"Selling **{qty}** of **{max_qty}** shares")
        with c3:
            product = sel.get("product", "cash")
            st.caption(f"Product: **{product}** (from ICICI position)")

        limit_price = None
        ltp = sel.get("ltp")
        try:
            ltp_f = float(ltp) if ltp is not None else None
        except (TypeError, ValueError):
            ltp_f = None
        if sell_type == "Limit":
            limit_price = float(
                st.number_input(
                    "Limit price ₹",
                    min_value=0.0,
                    value=ltp_f or 0.0,
                    step=0.05,
                    key=f"{key_prefix}_sell_limit",
                )
            )

        st.table(
            {
                "Field": ["Ticker", "Side", "Type", "Qty", "Product", "Limit ₹" if sell_type == "Limit" else "Price"],
                "Value": [
                    ticker,
                    "SELL",
                    sell_type,
                    str(qty),
                    product,
                    f"{limit_price:,.2f}" if limit_price else "Market",
                ],
            }
        )

        confirm = st.text_input("Type CONFIRM to enable SELL", key=f"{key_prefix}_sell_confirm")
        ready = (
            confirm.strip().upper() == "CONFIRM"
            and bool(ticker)
            and qty >= 1
            and (sell_type == "Market" or (limit_price and limit_price > 0))
        )

        if st.button(
            f"🔻 Place SELL ({qty} @ {sell_type})",
            key=f"{key_prefix}_sell_send",
            disabled=not ready,
            use_container_width=True,
        ):
            ok, msg, _ = place_sell_order(
                ticker,
                qty,
                order_type="limit" if sell_type == "Limit" else "market",
                price=limit_price,
                product=product,
            )
            if ok:
                st.success(msg)
                _bpos_clear_cache()
                st.rerun()
            else:
                st.error(msg)
        st.caption("Verify fill in **Today's Orders** / **Today's Trades** tabs after sending.")


def _plan_for_breeze_code(stock_code: str, plans: dict[str, dict]) -> Optional[dict]:
    code = (stock_code or "").strip().upper()
    if not code:
        return None
    if code in plans:
        return plans[code]
    try:
        from breeze_data import lookup_nse_symbol

        sym = lookup_nse_symbol("NSE", code)
        if sym:
            return plans.get(sym) or plans.get(f"{sym}.NS")
    except Exception:
        pass
    return None


def _row_float(row: Any, *keys: str) -> Optional[float]:
    """Read a numeric field from a DataFrame row (Series) or Breeze API dict."""
    for k in keys:
        if isinstance(row, dict):
            if k not in row:
                continue
            v = row.get(k)
        else:
            if k not in row.index:
                continue
            v = row[k]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _prediction_is_exit(pred: str) -> bool:
    p = (pred or "").lower()
    return any(w in p for w in ("fake", "forced", "dangerous", "avoid", "lunch")) or "❌" in (pred or "")


def _compute_exit_advice(
    entry: Optional[float],
    ltp: Optional[float],
    stop: Optional[float],
    target: Optional[float],
    prediction: str,
    session_pred: str,
    strategy: str = "",
) -> tuple[str, str, str, str]:
    """Returns (max_profit_done, sell_now, why_sell, exit_note)."""
    if entry is None or ltp is None or entry <= 0:
        return "—", "—", "—", "No entry/LTP — refresh or run scan"

    profit = ltp - entry
    profit_pct = round(profit / entry * 100, 2)
    risk = (entry - stop) if stop and entry > stop else None
    at_target = bool(target and ltp >= target)
    one_r = bool(risk and risk > 0 and profit >= risk)
    one_five_r = bool(risk and risk > 0 and profit >= 1.5 * risk)
    below_stop = bool(stop and ltp <= stop)

    sess_exit = _prediction_is_exit(session_pred)
    pred_exit = _prediction_is_exit(prediction)

    if at_target:
        max_done = "✅ Yes — at Target"
    elif one_five_r:
        max_done = "✅ Yes — ≥1.5× risk"
    elif one_r:
        max_done = "🟡 Partial — 1× risk hit"
    elif profit > 0:
        max_done = "No — profit, below plan"
    else:
        max_done = "No — loss / wait"

    why = ""
    if below_stop:
        sell = "🔴 Sell now — stop zone"
        why = (
            f"LTP ₹{ltp:,.2f} is at/below scan Stop ₹{stop:,.2f} — "
            "the intraday thesis is broken; exit to limit loss."
        )
    elif at_target and sess_exit:
        sell = "🔴 Book all — Target + bad session"
        why = (
            f"LTP ₹{ltp:,.2f} reached scan Target ₹{target:,.2f} (planned profit). "
            f"Session timing is unfavourable ({session_pred}) — "
            "late/lunch/forced volume often reverses winners."
        )
    elif at_target:
        sell = "🟡 Book ~50–70% — at Target"
        why = (
            f"LTP ₹{ltp:,.2f} is at/above scan Target ₹{target:,.2f} — "
            "that is the planned reward from the screener; book most of the position "
            "and trail a small runner if momentum continues."
        )
    elif one_r and (pred_exit or sess_exit):
        sell = "🔴 Book profit — time/volume risk"
        parts = [
            f"Profit ₹{profit:,.2f} ≥ 1× risk (Entry ₹{entry:,.2f} − Stop ₹{stop:,.2f}) — "
            "minimum planned reward is in hand."
        ]
        if pred_exit:
            parts.append(f"Scan Prediction warns: {prediction[:80]}{'…' if len(prediction) > 80 else ''}.")
        if sess_exit:
            parts.append(f"NSE session: {session_pred}.")
        why = " ".join(parts)
    elif one_r:
        sell = "🟡 Book ~50% · trail rest"
        why = (
            f"Profit ₹{profit:,.2f} hit **1× risk** (risk was ₹{risk:,.2f}) — "
            f"Target ₹{target:,.2f} may still be ahead; lock ~50% and move stop to breakeven."
        )
    elif one_five_r:
        sell = "🟡 Scale out — extended move"
        why = (
            f"Profit ≥ **1.5× risk** (₹{profit:,.2f} vs risk ₹{risk:,.2f}) — "
            "move is extended; scale out to avoid giving back gains on a pullback."
        )
    elif profit > 0 and sess_exit:
        sell = "🔴 Book profit — session exit"
        why = (
            f"In profit ({profit_pct:+.2f}%) but NSE session quality is poor ({session_pred}) — "
            "thin/forced volume near lunch or close often erodes intraday gains."
        )
    elif profit > 0 and pred_exit:
        sell = "🟡 Tighten — weak Prediction"
        why = (
            f"In profit ({profit_pct:+.2f}%) but this stock's scan Prediction is weak "
            f"({prediction[:100]}{'…' if len(prediction) > 100 else ''}) — "
            "volume/quality no longer supports holding for Target."
        )
    elif profit > 0:
        sell = "🟢 Hold — not at Target yet"
        tgt_txt = f"₹{target:,.2f}" if target else "—"
        why = (
            f"In profit ({profit_pct:+.2f}%) but LTP ₹{ltp:,.2f} is still below Target {tgt_txt} — "
            "session timing OK; wait for Target or trail stop up, don't chase new size."
        )
    else:
        sell = "🟢 Hold / wait"
        if target and stop:
            why = (
                f"LTP ₹{ltp:,.2f} below entry ₹{entry:,.2f} or still building — "
                f"hold while above Stop ₹{stop:,.2f}; exit if Stop breaks. Target ₹{target:,.2f}."
            )
        else:
            why = "No scan Target/Stop linked — run ICICI Breeze screener, then refresh this page."

    note = f"P/L {profit_pct:+.2f}%"
    if target and target > 0:
        note += f" · vs Target {(ltp / target - 1) * 100:+.1f}%"
    if strategy:
        note += f" · {STRATEGY_LABEL.get(strategy, strategy)}"
    return max_done, sell, why, note


def _enrich_breeze_portfolio_df(df: "pd.DataFrame", *, session_pred: str) -> "pd.DataFrame":
    """Add Max profit done? / Sell now? using last scan Entry/Stop/Target + session volume."""
    if df.empty or "stock_code" not in df.columns:
        return df
    plans = _scan_plans_lookup()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        r = dict(row)
        plan = _plan_for_breeze_code(str(r.get("stock_code", "")), plans)
        entry = _row_float(row, "average_price", "average_cost", "price")
        ltp = _row_float(row, "ltp", "current_market_price")
        if plan:
            r["Scan Entry"] = plan.get("entry")
            r["Scan Stop"] = plan.get("stop")
            r["Scan Target"] = plan.get("target")
            r["Exit plan"] = plan.get("exit_hint", "")
            pred = plan.get("prediction", "")
            strat = plan.get("strategy", "")
        else:
            r["Scan Entry"] = None
            r["Scan Stop"] = None
            r["Scan Target"] = None
            r["Exit plan"] = "Run ICICI Breeze scan to link Target/Stop"
            pred, strat = "", ""
        scan_entry = plan.get("entry") if plan else None
        scan_stop = plan.get("stop") if plan else None
        scan_target = plan.get("target") if plan else None
        max_done, sell, why, note = _compute_exit_advice(
            entry or scan_entry,
            ltp,
            scan_stop,
            scan_target,
            pred,
            session_pred,
            strat,
        )
        r["Max profit done?"] = max_done
        r["Sell now?"] = sell
        r["Why sell?"] = why
        r["Exit note"] = note
        r["Session timing"] = session_pred
        r["Ticker (.NS)"] = _breeze_code_to_ticker(str(r.get("stock_code", "")))
        out_rows.append(r)
    out = pd.DataFrame(out_rows)
    prefer = (
        "stock_code",
        "Ticker (.NS)",
        "action",
        "quantity",
        "average_price",
        "average_cost",
        "ltp",
        "pnl",
        "Max profit done?",
        "Sell now?",
        "Profit health",
        "Why sell?",
        "Scan Target",
        "Scan Stop",
        "Scan Entry",
        "Exit plan",
        "Exit note",
        "Session timing",
        "product_type",
        "order_type",
        "status",
        "order_datetime",
        "order_id",
        "trade_date",
        "current_market_price",
    )
    ordered = [c for c in prefer if c in out.columns]
    rest = [c for c in out.columns if c not in ordered]
    out = out[ordered + rest]
    if "Sell now?" in out.columns and "Profit health" not in out.columns:
        loc = int(out.columns.get_loc("Sell now?")) + 1
        out.insert(loc, "Profit health", out.apply(_profit_health_label, axis=1))
    return out


def _profit_health_label(row: "pd.Series") -> str:
    sell = str(row.get("Sell now?") or "")
    if "🔴" in sell:
        return "🔴 Act — exit / protect"
    if "🟡" in sell:
        return "🟡 Caution — scale or trail"
    pnl = _row_float(row, "pnl")
    if pnl is not None:
        if pnl > 0:
            return "🟢 Healthy — in profit"
        if pnl < 0:
            return "🔴 Underwater"
    max_done = str(row.get("Max profit done?") or "")
    if "✅" in max_done:
        return "🟢 Target / plan hit"
    return "🟢 Hold — plan intact"


_BPOS_CACHE_KEYS = ("bpos_positions", "bpos_orders", "bpos_trades", "bpos_holdings", "bpos_fetched_at")


def _count_trade_tickers(trd_rows: list) -> int:
    codes: set[str] = set()
    for row in trd_rows or []:
        t = _parse_breeze_trade_row(row)
        if t:
            codes.add(t["stock_code"])
    return len(codes)


def _parse_breeze_trade_row(row: dict) -> Optional[dict]:
    """Normalize one Breeze trade-book row."""
    if not isinstance(row, dict):
        return None
    code = str(row.get("stock_code") or "").strip().upper()
    if not code:
        return None
    action = str(row.get("action") or "").strip().lower()
    try:
        qty = int(float(row.get("quantity") or 0))
    except (TypeError, ValueError):
        qty = 0
    if qty <= 0:
        return None
    price = _row_float(row, "average_cost", "price", "average_price")
    if price is None or price <= 0:
        return None
    return {
        "stock_code": code,
        "action": action,
        "quantity": qty,
        "price": price,
        "trade_date": str(row.get("trade_date") or row.get("order_datetime") or ""),
        "order_id": str(row.get("order_id") or ""),
        "product_type": str(row.get("product_type") or ""),
    }


def _latest_order_status_by_code(ord_rows: list) -> dict[str, str]:
    """Most recent order status string per stock_code."""
    latest: dict[str, tuple[str, str]] = {}
    for row in ord_rows or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("stock_code") or "").strip().upper()
        if not code:
            continue
        ts = str(row.get("order_datetime") or row.get("trade_date") or "")
        status = str(row.get("status") or "—")
        action = str(row.get("action") or "")
        label = f"{action} · {status}".strip(" · ")
        if code not in latest or ts >= latest[code][0]:
            latest[code] = (ts, label)
    return {k: v[1] for k, v in latest.items()}


def _build_todays_trades_summary(
    trd_rows: list,
    pos_rows: list,
    ord_rows: list,
) -> pd.DataFrame:
    """
    One row per ticker: buys + sells today, open vs closed, LTP, realized/unrealized P/L.
    """
    agg: dict[str, dict] = {}

    for row in trd_rows or []:
        t = _parse_breeze_trade_row(row)
        if not t:
            continue
        code = t["stock_code"]
        bucket = agg.setdefault(
            code,
            {
                "stock_code": code,
                "buy_qty": 0,
                "sell_qty": 0,
                "buy_value": 0.0,
                "sell_value": 0.0,
                "trade_count": 0,
                "last_trade": "",
            },
        )
        bucket["trade_count"] += 1
        if t["trade_date"] >= bucket["last_trade"]:
            bucket["last_trade"] = t["trade_date"]
        if t["action"] == "sell":
            bucket["sell_qty"] += t["quantity"]
            bucket["sell_value"] += t["quantity"] * t["price"]
        else:
            bucket["buy_qty"] += t["quantity"]
            bucket["buy_value"] += t["quantity"] * t["price"]

    pos_by_code: dict[str, dict] = {}
    for row in pos_rows or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("stock_code") or "").strip().upper()
        if code:
            pos_by_code[code] = row

    order_status = _latest_order_status_by_code(ord_rows)

    try:
        from breeze_data import get_ltp
    except Exception:
        get_ltp = None  # type: ignore[assignment,misc]

    summary_rows: list[dict] = []
    for code, b in agg.items():
        buy_qty = int(b["buy_qty"])
        sell_qty = int(b["sell_qty"])
        net_qty = buy_qty - sell_qty
        avg_buy = round(b["buy_value"] / buy_qty, 2) if buy_qty > 0 else None
        avg_sell = round(b["sell_value"] / sell_qty, 2) if sell_qty > 0 else None

        pos = pos_by_code.get(code)
        ltp = None
        if pos:
            ltp = _row_float(pos, "ltp", "current_market_price")
        if ltp is None and get_ltp:
            try:
                ltp = get_ltp(_breeze_code_to_ticker(code))
            except Exception:
                ltp = None
        if ltp is not None:
            ltp = round(float(ltp), 2)

        if net_qty > 0 and sell_qty > 0:
            position_status = "🟡 Partially sold — still open"
        elif net_qty > 0:
            position_status = "🟢 Open"
        elif sell_qty > 0 and buy_qty > 0:
            position_status = "✅ Closed — sold today"
        elif sell_qty > 0:
            position_status = "🔴 Sell only"
        elif buy_qty > 0:
            position_status = "🟢 Bought — check positions"
        else:
            position_status = "—"

        matched = min(buy_qty, sell_qty)
        realized_pnl = None
        if matched > 0 and avg_buy is not None and avg_sell is not None:
            realized_pnl = round(matched * (avg_sell - avg_buy), 2)

        unrealized_pnl = None
        ref_avg = avg_buy
        if pos and pos.get("average_price") is not None:
            try:
                ref_avg = float(pos["average_price"])
            except (TypeError, ValueError):
                pass
        if net_qty > 0 and ltp is not None and ref_avg is not None:
            unrealized_pnl = round(net_qty * (ltp - ref_avg), 2)

        total_pnl = None
        if realized_pnl is not None or unrealized_pnl is not None:
            total_pnl = round((realized_pnl or 0.0) + (unrealized_pnl or 0.0), 2)

        summary_rows.append(
            {
                "stock_code": code,
                "Ticker (.NS)": _breeze_code_to_ticker(code),
                "Position status": position_status,
                "Latest order": order_status.get(code, "—"),
                "Buy qty": buy_qty,
                "Sell qty": sell_qty,
                "Net qty": net_qty,
                "Avg buy ₹": avg_buy,
                "Avg sell ₹": avg_sell,
                "ltp": ltp,
                "Realized P/L ₹": realized_pnl,
                "Unrealized P/L ₹": unrealized_pnl,
                "Total P/L ₹": total_pnl,
                "Trades today": b["trade_count"],
                "Last trade": b["last_trade"] or "—",
                "average_price": ref_avg if net_qty > 0 else avg_buy,
                "action": "buy" if net_qty >= 0 else "sell",
                "quantity": net_qty if net_qty > 0 else sell_qty,
                "pnl": total_pnl,
            }
        )

    if not summary_rows:
        return pd.DataFrame()

    out = pd.DataFrame(summary_rows)
    prefer = (
        "stock_code",
        "Ticker (.NS)",
        "Position status",
        "Latest order",
        "ltp",
        "Total P/L ₹",
        "Realized P/L ₹",
        "Unrealized P/L ₹",
        "Buy qty",
        "Sell qty",
        "Net qty",
        "Avg buy ₹",
        "Avg sell ₹",
        "Trades today",
        "Last trade",
    )
    ordered = [c for c in prefer if c in out.columns]
    rest = [c for c in out.columns if c not in ordered]
    return out[ordered + rest]


def _render_bpos_trades_tab(
    trd_rows: list,
    pos_rows: list,
    ord_rows: list,
    *,
    trd_err: Optional[str],
    session_pred: str,
) -> None:
    """Today's trades: per-ticker summary including sold/closed + all executions."""
    st.caption(
        "Every ticker you **bought or sold today** — including **already sold** names — "
        "with **latest LTP**, order status, and realized / unrealized P/L."
    )
    if trd_err:
        st.error(f"Could not load trades: {trd_err}")
        return

    summary = _build_todays_trades_summary(trd_rows, pos_rows, ord_rows)
    if summary.empty:
        st.info("No executed trades for today.")
        return

    n_closed = int(summary["Position status"].astype(str).str.contains("Closed", na=False).sum())
    n_open = int(summary["Position status"].astype(str).str.contains("Open", na=False).sum())
    n_partial = int(summary["Position status"].astype(str).str.contains("Partially", na=False).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tickers traded", len(summary))
    c2.metric("Still open", n_open + n_partial)
    c3.metric("Sold / closed today", n_closed)
    if "Total P/L ₹" in summary.columns:
        pnl_vals = []
        for v in summary["Total P/L ₹"]:
            try:
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    pnl_vals.append(float(v))
            except (TypeError, ValueError):
                pass
        if pnl_vals:
            c4.metric("Combined P/L ₹", f"{sum(pnl_vals):,.0f}")

    enriched = _enrich_breeze_portfolio_df(summary, session_pred=session_pred)
    st.markdown("#### By ticker (open + sold)")
    st.dataframe(enriched, use_container_width=True, hide_index=True)

    raw_df = _breeze_rows_to_df(
        trd_rows,
        ("stock_code", "action", "quantity", "average_cost", "price", "product_type",
         "trade_date", "order_id"),
    )
    with st.expander(f"📋 All executions today ({len(raw_df)} fills)", expanded=False):
        if raw_df.empty:
            st.caption("No raw fills.")
        else:
            st.dataframe(
                _enrich_breeze_portfolio_df(raw_df, session_pred=session_pred),
                use_container_width=True,
                hide_index=True,
            )


def _bpos_clear_cache() -> None:
    for k in _BPOS_CACHE_KEYS:
        st.session_state.pop(k, None)


def _bpos_fetch_snapshot(*, force: bool = False) -> None:
    """Load positions, orders, trades, holdings from ICICI Breeze into session state."""
    if not force and "bpos_positions" in st.session_state:
        return
    from breeze_data import get_holdings, get_order_book, get_positions, get_trade_book

    st.session_state["bpos_positions"] = get_positions()
    st.session_state["bpos_orders"] = get_order_book(days=1)
    st.session_state["bpos_trades"] = get_trade_book(days=1)
    st.session_state["bpos_holdings"] = get_holdings()
    st.session_state["bpos_fetched_at"] = datetime.now().strftime("%H:%M:%S")


def _render_bpos_live_summary(pos_enriched: "pd.DataFrame") -> None:
    """Headline P/L and sell-signal counts for open positions."""
    fetched = st.session_state.get("bpos_fetched_at", "—")
    auto = st.session_state.get("bpos_auto_refresh", False)
    iv = st.session_state.get("bpos_refresh_sec", 60)
    mode = f"Auto every **{iv}s**" if auto else "Manual"
    st.caption(f"Last ICICI fetch: **{fetched}** · {mode}")

    if pos_enriched.empty:
        return

    total_pnl = 0.0
    has_pnl = False
    if "pnl" in pos_enriched.columns:
        for v in pos_enriched["pnl"]:
            try:
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    total_pnl += float(v)
                    has_pnl = True
            except (TypeError, ValueError):
                pass

    sell_col = pos_enriched.get("Sell now?", pd.Series(dtype=str)).astype(str)
    n_exit = int(sell_col.str.contains("🔴", na=False).sum())
    n_caution = int(sell_col.str.contains("🟡", na=False).sum())
    n_hold = int(sell_col.str.contains("🟢", na=False).sum())
    n_at_target = int(
        pos_enriched.get("Max profit done?", pd.Series(dtype=str))
        .astype(str)
        .str.contains("✅", na=False)
        .sum()
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Open positions", len(pos_enriched))
    if has_pnl:
        m2.metric("Total P/L (₹)", f"{total_pnl:,.0f}")
    else:
        m2.metric("Total P/L (₹)", "—")
    m3.metric("🔴 Sell now", n_exit)
    m4.metric("🟡 Scale / trail", n_caution)
    m5.metric("✅ Plan complete", n_at_target)
    if n_hold:
        st.caption(f"**{n_hold}** position(s) marked **🟢 Hold** — refresh updates LTP and profit health.")


def _render_breeze_positions_content() -> None:
    """Tabs + tables — expects ``_bpos_fetch_snapshot`` to have run."""
    pos_rows, pos_err = st.session_state["bpos_positions"]
    ord_rows, ord_err = st.session_state["bpos_orders"]
    trd_rows, trd_err = st.session_state["bpos_trades"]
    hld_rows, hld_err = st.session_state["bpos_holdings"]

    session_pred = compute_volume_time_prediction("NSE").prediction
    has_scan = bool(_scan_plans_lookup())
    st.info(
        f"**Session timing (NSE):** {session_pred}  \n"
        + (
            "Linked to your last **ICICI Breeze / Intraday** scan (Entry/Stop/Target)."
            if has_scan
            else "Run **ICICI Breeze Screener** today so **Scan Target/Stop** and sell hints can populate."
        )
    )

    trd_summary_n = _count_trade_tickers(trd_rows)
    tab_pos, tab_ord, tab_trd, tab_hld = st.tabs(
        [
            f"📈 Open Positions ({len(pos_rows)})",
            f"🧾 Today's Orders ({len(ord_rows)})",
            f"✅ Today's Trades ({trd_summary_n or len(trd_rows)} tickers)",
            f"🏦 Holdings ({len(hld_rows)})",
        ]
    )

    sell_candidates = _position_sell_candidates(pos_rows)

    with tab_pos:
        st.caption(
            "Live intraday positions · **Profit health**, **Max profit done?**, **Sell now?** "
            "refresh with LTP when auto-refresh is on."
        )
        if pos_err:
            st.error(f"Could not load positions: {pos_err}")
        df = _breeze_rows_to_df(
            pos_rows,
            ("stock_code", "action", "quantity", "average_price", "ltp", "product_type", "pnl"),
        )
        pos_enriched = pd.DataFrame()
        hint: Optional[dict] = None
        if df.empty:
            st.info("No open positions right now.")
        else:
            pos_enriched = _enrich_breeze_portfolio_df(df, session_pred=session_pred)
            _render_bpos_live_summary(pos_enriched)
            st.caption("💡 Click a row to pre-fill **Sell from screen** with that position's signals.")
            tbl = st.dataframe(
                pos_enriched,
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="bpos_pos_table",
            )
            try:
                sel_rows = tbl.selection.rows  # type: ignore[union-attr]
                if sel_rows:
                    hint = pos_enriched.iloc[int(sel_rows[0])].to_dict()
            except Exception:
                hint = None
        _render_breeze_sell_panel(sell_candidates, key_prefix="bpos", hint_row=hint)

    with tab_ord:
        st.caption("Today's orders — sell hints on filled BUY rows with a linked scan plan.")
        if ord_err:
            st.error(f"Could not load orders: {ord_err}")
        df = _breeze_rows_to_df(
            ord_rows,
            ("stock_code", "action", "quantity", "price", "average_price", "order_type",
             "status", "product_type", "order_datetime", "order_id"),
        )
        if df.empty:
            st.info("No orders found for today.")
        else:
            st.dataframe(_enrich_breeze_portfolio_df(df, session_pred=session_pred), use_container_width=True, hide_index=True)

    with tab_trd:
        _render_bpos_trades_tab(
            trd_rows, pos_rows, ord_rows, trd_err=trd_err, session_pred=session_pred,
        )

    with tab_hld:
        st.caption("Delivery holdings — exit hints apply if the symbol was in today's scan.")
        if hld_err:
            st.error(f"Could not load holdings: {hld_err}")
        df = _breeze_rows_to_df(
            hld_rows,
            ("stock_code", "quantity", "average_price", "current_market_price", "ltp"),
        )
        if df.empty:
            st.info("No holdings found.")
        else:
            st.dataframe(_enrich_breeze_portfolio_df(df, session_pred=session_pred), use_container_width=True, hide_index=True)


def render_breeze_positions_page() -> None:
    """Show ICICI live positions, today's orders, and executed trades (purchased tickers)."""
    safe_set_page_config(page_title="ICICI Positions & Orders | StockSight", page_icon="📒", layout="wide")
    inject_css()

    st.markdown("### 📒 ICICI Positions & Orders — your purchased tickers")
    _render_breeze_status_banner()
    page_audience_note(
        "Traders who placed orders via the **ICICI Breeze Screener** and want to see open "
        "positions, today's orders, and executed trades in one place.",
        "Reads live data from your ICICI account via Breeze (positions, order book, trade book). "
        "You can also place **SELL** orders from the **Sell from screen** panel (with CONFIRM).",
    )

    try:
        from breeze_data import (
            breeze_configured,
            get_holdings,
            get_order_book,
            get_positions,
            get_trade_book,
        )
    except Exception:
        st.error("Breeze module unavailable.")
        return

    if not breeze_configured():
        st.warning("🟠 Breeze isn't connected — add credentials / refresh the daily token above.")
        return

    st.session_state.setdefault("bpos_auto_refresh", True)
    st.session_state.setdefault("bpos_refresh_sec", 45)

    t1, t2, t3 = st.columns([1.0, 1.1, 1.0])
    with t1:
        if st.button("🔄 Refresh now", key="bpos_refresh", use_container_width=True):
            _bpos_clear_cache()
            st.rerun()
    with t2:
        auto_refresh = st.checkbox(
            "Auto-refresh positions (live P/L & sell signals)",
            key="bpos_auto_refresh",
            help="Keeps this tab open and re-fetches from ICICI on a timer.",
        )
    with t3:
        refresh_sec = st.slider(
            "Refresh every (seconds)",
            15,
            120,
            int(st.session_state.get("bpos_refresh_sec", 45)),
            5,
            key="bpos_refresh_sec",
            disabled=not auto_refresh,
        )

    if auto_refresh:
        st.info(
            f"**Live mode** — open positions, P/L, and **Profit health** update every "
            f"**{refresh_sec}** seconds. Keep this page open during the session."
        )

        @st.fragment(run_every=timedelta(seconds=max(15, int(refresh_sec))))
        def _bpos_live_refresh() -> None:
            if not st.session_state.get("bpos_auto_refresh", False):
                return
            with st.spinner("Updating from ICICI…"):
                _bpos_fetch_snapshot(force=True)
            _render_breeze_positions_content()

        _bpos_live_refresh()
    else:
        if "bpos_positions" not in st.session_state:
            with st.spinner("Fetching positions, orders and trades from ICICI…"):
                _bpos_fetch_snapshot(force=True)
        else:
            _bpos_fetch_snapshot(force=False)
        _render_breeze_positions_content()

    with st.expander("ℹ How Max profit done? / Sell now? are calculated", expanded=False):
        st.markdown(
            """
| Column | Meaning |
|--------|---------|
| **Max profit done?** | **✅ Yes** if LTP ≥ scan **Target**, or profit ≥ **1.5× risk** (Entry−Stop), or **🟡 Partial** at 1× risk. |
| **Sell now?** | Combines Target/risk, scan **Prediction**, and **session timing** (lunch/close/forced volume). |
| **Why sell?** | Plain-language reason for the **Sell now?** signal (prices, Target, Stop, session). |
| **Scan Target / Stop / Entry** | From your last **ICICI Breeze** or **Intraday** scan (same session). |
| **Exit plan** | Same one-line rule as the screener results table. |

**🔴 Sell now** ≈ book profit or exit · **🟡** ≈ scale out (often 50% at Target) · **🟢 Hold** ≈ plan not complete yet.

*Educational signals only — confirm on your broker before placing sells.*

Use **⚠️ Sell from screen** below the positions table to send a Market or Limit **SELL** (after CONFIRM).
"""
        )

    st.caption(
        "Data from ICICI Breeze. Use **Auto-refresh** for continuous open-position P/L and sell signals, "
        "or **Refresh now** for a one-off update. Always verify against ICICI Direct."
    )


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
        sort_by_gate=False,
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
