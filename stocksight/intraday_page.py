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
    compute_market_mood,
    market_session_window,
    resolve_universe,
    scan_gaps,
    scan_intraday,
)
from ui_components import (
    ensure_session_choice,
    filter_column_config,
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    safe_set_page_config,
)


# ─────────────────────────────────────────────────────────────
# Common helpers
# ─────────────────────────────────────────────────────────────
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
                "Min 5-min volume ratio (× 20-bar avg)",
                0.5, 5.0, 1.5, 0.1,
                key=f"{key_prefix}_{suffix}_min_vr",
                help="Ratio of last 5-min bar volume vs. its 20-bar average. ≥ 1.5 = above-average participation.",
            )
        with c3:
            min_rsi, max_rsi = st.slider(
                "RSI band",
                10.0, 90.0, (30.0, 80.0), 1.0,
                key=f"{key_prefix}_{suffix}_rsi_band",
                help="Skip too-oversold (<30) and too-overbought (>80) names by default.",
            )

    return IntradayFilters(
        min_price=float(min_p),
        max_price=float(max_p),
        min_avg_volume_20d=float(min_avg_vol),
        min_volume_ratio=float(min_vr),
        min_rsi=float(min_rsi),
        max_rsi=float(max_rsi),
    )


def _results_to_df(results: list[IntradayResult]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    rows = []
    for rank, r in enumerate(results, start=1):
        row = {
            "S.No.": rank,
            "Ticker": r.ticker,
            "Raw": r.raw_ticker,
            "Strategy": STRATEGY_LABEL.get(r.strategy, r.strategy),
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
    return df.dropna(axis=1, how="all")


def _gap_results_to_df(gaps: list[GapResult]) -> pd.DataFrame:
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
    return df.dropna(axis=1, how="all")


def _intraday_col_cfg(df: pd.DataFrame) -> dict:
    return filter_column_config(
        df,
        {
            "Strategy": st.column_config.TextColumn("Strategy", width="medium"),
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


def _csv_download(df: pd.DataFrame, *, label: str, file_prefix: str, key: str) -> None:
    if df is None or df.empty:
        return
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
def render_intraday_screener_page() -> None:
    safe_set_page_config(page_title="Intraday Screener | StockSight", page_icon="📡", layout="wide")
    inject_css()

    st.markdown("### 📡 Intraday Screener — 4 strategies, NSE or US")
    page_audience_note(
        "Active intraday traders on **NSE (India)** or **US (NYSE & NASDAQ)** who want "
        "pre-screened candidates with Entry / Stop / Target attached.",
        "Scans Yahoo Finance 5-minute bars + 1-year daily history. Tags each match with its strategy "
        "(Momentum / VWAP Pullback / ORB / Gap-Up) and outputs a clickable table with R:R suggestions. "
        "**Educational only — confirm risk before trading.**",
    )

    key = "id"
    market = _market_picker(key)
    _session_banner(market)

    with st.container(border=True):
        c1, c2 = st.columns([1.1, 1.0])
        with c1:
            uni_label, raw_tickers = _universe_picker(key, market)
        with c2:
            strategies_picked: list[str] = st.multiselect(
                "Strategies to scan",
                STRATEGIES,
                default=list(STRATEGIES),
                format_func=lambda s: STRATEGY_LABEL.get(s, s),
                key=f"{key}_strats",
                help="Each strategy has a best time-of-day. Hover the legend below.",
            )
            with st.expander(f"ℹ Best time-of-day per strategy ({MARKET_LABEL.get(market, market)})", expanded=False):
                times = STRATEGY_BEST_TIME_BY_MARKET.get(market, STRATEGY_BEST_TIME_BY_MARKET["NSE"])
                for s in STRATEGIES:
                    st.markdown(f"- **{STRATEGY_LABEL[s]}** — {times.get(s, '')}")

    flt = _filters_panel(key, market)

    run = st.button("▶  RUN INTRADAY SCAN", use_container_width=True, key=f"{key}_run")
    st.caption(
        f"Universe: **{uni_label}** ({len(raw_tickers)} tickers) · "
        "Yahoo 5-min data — runs slow during off-hours."
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

        results = scan_intraday(raw_tickers, tuple(strategies_picked), flt, progress_cb=cb)
        prog.empty()
        st.session_state[f"{key}_results"] = results
        st.session_state[f"{key}_at"] = datetime.now().strftime("%d %b %Y %H:%M")
        st.session_state[f"{key}_universe"] = uni_label
        st.session_state[f"{key}_scan_market"] = market

    results: list[IntradayResult] = st.session_state.get(f"{key}_results", [])
    scan_at = st.session_state.get(f"{key}_at")
    last_uni = st.session_state.get(f"{key}_universe", "")

    if not results:
        if scan_at:
            st.warning(
                "No matches with current filters. Loosen volume ratio (try 1.0×), "
                "widen RSI band, or pick a larger universe."
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

    df_all = _results_to_df(results)
    tab_labels = ["📋 All matches"] + [STRATEGY_LABEL[s] for s in STRATEGIES if counts.get(s, 0)]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        render_clickable_scan_table(
            df_all,
            key_prefix=f"{key}_all",
            universe_name=last_uni,
            column_config=_intraday_col_cfg(df_all),
            height=min(620, 48 + len(df_all) * 36),
        )
        _csv_download(df_all, label="⬇ Download All matches CSV",
                       file_prefix="stocksight_intraday_all", key=f"{key}_dl_all")

    tab_idx = 1
    scan_market = st.session_state.get(f"{key}_scan_market", market)
    best_times = STRATEGY_BEST_TIME_BY_MARKET.get(scan_market, STRATEGY_BEST_TIME_BY_MARKET["NSE"])
    for s in STRATEGIES:
        if not counts.get(s, 0):
            continue
        with tabs[tab_idx]:
            sub_results = [r for r in results if r.strategy == s]
            sub_df = _results_to_df(sub_results)
            st.caption(f"Best time-of-day: **{best_times.get(s, '')}**")
            render_clickable_scan_table(
                sub_df,
                key_prefix=f"{key}_{s.lower()}",
                universe_name=last_uni,
                column_config=_intraday_col_cfg(sub_df),
                height=min(560, 48 + len(sub_df) * 36),
            )
            _csv_download(sub_df, label=f"⬇ Download {STRATEGY_LABEL[s]} CSV",
                           file_prefix=f"stocksight_intraday_{s.lower()}",
                           key=f"{key}_dl_{s.lower()}")
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
    _session_banner(market)

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

    run = st.button("▶  SCAN GAPS NOW", use_container_width=True, key=f"{key}_run")
    if market == "US":
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Run at 9:00–9:45 AM ET (3:00–3:45 PM CEST) for maximum signal."
        )
    else:
        st.caption(
            f"Universe: **{uni_label}** ({len(raw_tickers)} tickers). "
            "Run at 8:30–9:30 AM IST (5:00–6:00 AM CEST) for maximum signal."
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

    df = _gap_results_to_df(gaps)
    render_clickable_scan_table(
        df,
        key_prefix=f"{key}_results",
        universe_name=last_uni,
        column_config=_gap_col_cfg(df),
        height=min(600, 48 + len(df) * 36),
    )
    _csv_download(df, label="⬇ Download Gap Scanner CSV",
                   file_prefix="stocksight_gaps", key=f"{key}_dl")

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
    st.markdown("## ⏰ Time-based scan schedule")

    tab_nse, tab_us = st.tabs(["🇮🇳 NSE (India)", "🇺🇸 US (NYSE / NASDAQ)"])

    with tab_nse:
        st.caption("NSE regular session: **9:15 AM – 3:30 PM IST** · **5:45 AM – 12:00 PM CEST** (summer)")
        st.markdown(
            """
| IST | CEST | What to scan |
|-----|------|--------------|
| 8:30–9:10 AM | 5:00–5:40 AM | Gap-up / Gap-down candidates |
| 9:15–9:30 AM | 5:45–6:00 AM | ORB setup stocks |
| 9:30–10:30 AM | 6:00–7:00 AM | Momentum breakouts |
| 10:30 AM–1:00 PM | 7:00–9:30 AM | VWAP pullbacks |
| 1:00–2:00 PM | 9:30–10:30 AM | **Avoid** (lunch lull) |
| 2:00–3:15 PM | 10:30 AM–11:45 AM | End-of-day momentum plays |
| 3:30 PM | 12:00 PM | Session close — square off all positions |
"""
        )

    with tab_us:
        st.caption("US regular session: **9:30 AM – 4:00 PM ET** · **3:30 PM – 10:00 PM CEST** (summer)")
        st.markdown(
            """
| ET | CEST | What to scan |
|----|------|--------------|
| 7:00–9:30 AM | 1:00–3:30 PM | Pre-market gap scan + watchlist build |
| 9:30–9:45 AM | 3:30–3:45 PM | ORB high/low forming · no entries yet |
| 9:45–11:00 AM | 3:45–5:00 PM | Opening hour: ORB breaks + momentum |
| 11:00 AM–1:30 PM | 5:00–7:30 PM | VWAP pullbacks · fewer, cleaner trades |
| 1:30–3:00 PM | 7:30–9:00 PM | Mid-day chop · **avoid noise** |
| 3:00–4:00 PM | 9:00–10:00 PM | 💥 Power hour — strong moves, close before 3:55 PM ET |
| 4:00 PM | 10:00 PM | Session close — square off, no overnight |
"""
        )
        st.info(
            "🇪🇺 **Tip for European day traders:** The US session aligns nicely with European afternoons/evenings. "
            "Pre-market scan ~3:00 PM CEST, opening volatility 3:30–5:00 PM CEST, power hour 9:00–10:00 PM CEST. "
            "DST shifts move CEST↔CET by 1 hour twice a year — the app's clocks auto-adjust."
        )

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

    st.markdown("---")
    st.markdown("## 📅 Your daily routine")
    rc1, rc2 = st.columns(2)
    with rc1:
        st.markdown("**🇮🇳 NSE day (IST · CEST in parens)**")
        st.code(
            """8:30 AM IST  (5:00 AM CEST) → Check gaps, note market mood
9:00 AM IST  (5:30 AM CEST) → Run Intraday Screener, shortlist 3–5
9:15 AM IST  (5:45 AM CEST) → Mark ORB high/low, do NOT trade yet
9:30 AM IST  (6:00 AM CEST) → Start trading (ORB / VWAP)
11:00 AM IST (7:30 AM CEST) → Stop if 2 losses hit
2:00 PM IST  (10:30 AM CEST)→ One more session if trending
3:00 PM IST  (11:30 AM CEST)→ Square off ALL positions""",
            language="text",
        )
    with rc2:
        st.markdown("**🇺🇸 US day (ET · CEST in parens)**")
        st.code(
            """9:00 AM ET   (3:00 PM CEST) → Check gaps, note market mood
9:15 AM ET   (3:15 PM CEST) → Run Intraday Screener, shortlist 3–5
9:30 AM ET   (3:30 PM CEST) → Mark ORB high/low, do NOT trade yet
9:45 AM ET   (3:45 PM CEST) → Start trading (ORB / momentum)
11:00 AM ET  (5:00 PM CEST) → Stop if 2 losses hit
3:00 PM ET   (9:00 PM CEST) → Power hour — last session
3:55 PM ET   (9:55 PM CEST) → Square off ALL positions""",
            language="text",
        )

    st.info(
        "📈 The **most reliable signals** appear when a stock shows up in **both** the Gap Scanner "
        "(pre-open) and the Intraday Screener (after 9:30 AM)."
    )
