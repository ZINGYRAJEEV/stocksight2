"""Healthy Dip — quality fundamentals on a temporary pullback (beginner value + technical)."""
import streamlit as st
from screener import UNIVERSES
from signals import scan_healthy_dip
from ui_components import (
    inject_css,
    scenario_header,
    render_trade_plan_cards,
    results_table,
    no_results_state,
    safe_set_page_config,
    scenario_advanced_panel,
    maybe_enrich_news,
    maybe_enrich_healthy_dip_context,
    render_watchlist_panel,
    signal_results_download,
    log_scenario_scan,
    notify_watchlist_alerts,
    scenario_page_alert_hint,
)

safe_set_page_config(page_title="Healthy Dip | StockSight", page_icon="🩺", layout="wide")
inject_css()

SCENARIO = "healthy_dip"
PRESET_PARAMS: dict[str, dict] = {
    "Balanced (recommended)": {
        "roe": 14.0,
        "de": 1.2,
        "pe": 35.0,
        "dd": (15, 48),
        "rsi": 42.0,
        "pb": False,
        "peg": False,
        "ic": False,
        "ma200": False,
        "ma_tol": 8.0,
    },
    "Classic (educational)": {
        "roe": 15.0,
        "de": 1.0,
        "pe": 30.0,
        "dd": (15, 45),
        "rsi": 40.0,
        "pb": False,
        "peg": False,
        "ic": False,
        "ma200": True,
        "ma_tol": 8.0,
    },
    "NSE · Screener.in style": {
        "roe": 15.0,
        "de": 0.5,
        "pe": 25.0,
        "dd": (18, 45),
        "rsi": 42.0,
        "pb": False,
        "peg": False,
        "ic": True,
        "ma200": False,
        "ma_tol": 8.0,
    },
    "Strict quality": {
        "roe": 18.0,
        "de": 0.5,
        "pe": 25.0,
        "dd": (22, 38),
        "rsi": 38.0,
        "pb": True,
        "peg": False,
        "ic": False,
        "ma200": True,
        "ma_tol": 5.0,
    },
    "Looser dip hunt": {
        "roe": 12.0,
        "de": 1.5,
        "pe": 40.0,
        "dd": (12, 55),
        "rsi": 48.0,
        "pb": False,
        "peg": False,
        "ic": False,
        "ma200": False,
        "ma_tol": 10.0,
    },
}

PRESETS = tuple(PRESET_PARAMS.keys())

scenario_header(SCENARIO)
render_watchlist_panel("hd_wl")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.0, 1.05, 1.2])
    with c1:
        st.markdown("#### Settings")
        preset = st.selectbox(
            "Filter preset",
            PRESETS,
            index=0,
            key="hd_preset",
            help="Start with **Balanced** if you get zero hits. Strict + P/B ≤ 1.5 often returns nothing on Nifty 50.",
        )
        uni_keys = list(UNIVERSES.keys())
        uni_default = 1 if preset == "NSE · Screener.in style" else 0
        universe = st.selectbox(
            "Stock Universe",
            uni_keys,
            index=min(uni_default, len(uni_keys) - 1),
            key="hd_universe",
        )
        if preset == "NSE · Screener.in style":
            st.caption("Pair with **Nifty 500 (NSE)** for a broad India large/mid sweep like Screener.in.")
    with c2:
        st.markdown("#### What we look for")
        st.markdown(
            """
<div style='font-size:0.72rem; color:#4a5568; line-height:1.85;'>
<b>Health</b> ROE · low debt · PE cap<br>
<b>Dip</b> 20–40% below 52-week high · RSI oversold<br>
<b>Entry zone</b> Near 200-day MA (optional)<br>
After scan: <b>Why it fell</b> one-liner from Yahoo headlines
</div>
""",
            unsafe_allow_html=True,
        )
        explain_fall = st.checkbox(
            "Explain why it fell (headlines)",
            value=True,
            key="hd_explain_fall",
            help="Extra Yahoo calls — skipped if more than ~30 matches.",
        )
    with c3:
        st.markdown("#### Fundamentals")
        p = PRESET_PARAMS[preset]
        min_roe = st.slider("Min ROE %", 5.0, 35.0, float(p["roe"]), 0.5, key="hd_roe")
        max_de = st.slider("Max debt/equity", 0.0, 3.0, float(p["de"]), 0.05, key="hd_de")
        max_pe = st.slider("Max P/E", 5.0, 60.0, float(p["pe"]), 0.5, key="hd_pe")

with st.container(border=True):
    st.markdown("#### Dip & technicals")
    t1, t2, t3, t4 = st.columns(4)
    p = PRESET_PARAMS[preset]
    dd_rng_def = tuple(p["dd"])
    rsi_def = float(p["rsi"])
    with t1:
        dd_range = st.slider(
            "Drawdown from 52w high %",
            5,
            60,
            dd_rng_def,
            1,
            key="hd_dd",
            help="Stock price this far below its 52-week high (temporary weakness zone).",
        )
    with t2:
        rsi_max = st.slider("Max RSI (14)", 20, 55, int(rsi_def), 1, key="hd_rsi")
    with t3:
        require_ma200 = st.checkbox("Near 200-day MA", value=bool(p["ma200"]), key="hd_ma200")
        ma_tol = st.slider(
            "Max % above 200-DMA",
            0.0,
            15.0,
            float(p["ma_tol"]),
            0.5,
            key="hd_ma_tol",
            help="Allows price below the 200-DMA. Rejects names extended more than this % above it.",
        )
    with t4:
        apply_pb = st.checkbox(
            "P/B ≤ 1.5 (when available)",
            value=bool(p["pb"]),
            key="hd_pb",
            help="Very strict on NSE — most quality names trade above 1.5× book.",
        )
        apply_peg = st.checkbox("PEG ≤ 1 (when available)", value=bool(p["peg"]), key="hd_peg")
        apply_ic = st.checkbox(
            "Interest coverage ≥ 3× (when reported)",
            value=bool(p["ic"]),
            key="hd_ic",
        )

adv = scenario_advanced_panel("hd_adv")

scan_progress = st.empty()
run = st.button("▶  SCAN NOW", use_container_width=True, key="scan_now_healthy_dip")
st.caption(
    "Scans the full universe with Yahoo Finance data. Nifty 500 runs take several minutes — "
    "start with **Nifty 50** while learning. Not financial advice."
)

if run:
    prog = scan_progress.progress(0, text="Initialising…")

    def cb(i, t, s):
        prog.progress(int(i / t * 100), text=f"Scanning {s}… ({i}/{t})")

    scan_kw = {
        "sector_filter": adv["sector_filter"],
        "interval_key": adv["interval_key"],
        "require_macd_bullish": adv["require_macd_bullish"],
        "require_bb_touch_lower": adv["require_bb_touch_lower"],
        "require_weekly_confirm": adv["require_weekly_confirm"],
        "weekly_macd_confirm": adv["weekly_macd_confirm"],
        "exclude_earnings_within_days": int(adv["exclude_earnings_within_days"]),
        "skip_bearish_divergence_buy": adv["skip_bearish_divergence_buy"],
        "min_rs_vs_bench": adv["min_rs_vs_bench"],
        "require_stoch_cross_up": adv["require_stoch_cross_up"],
        "require_stoch_cross_down": adv["require_stoch_cross_down"],
    }
    results = scan_healthy_dip(
        universe,
        min_roe_pct=min_roe,
        max_debt_equity=max_de,
        max_pe=max_pe,
        drawdown_min_pct=float(dd_range[0]),
        drawdown_max_pct=float(dd_range[1]),
        rsi_max=float(rsi_max),
        require_near_ma200=require_ma200,
        ma200_tolerance_pct=float(ma_tol),
        apply_pb_filter=apply_pb,
        apply_peg_filter=apply_peg,
        apply_interest_coverage=apply_ic,
        progress_cb=cb,
        **scan_kw,
    )
    if explain_fall:
        maybe_enrich_healthy_dip_context(results, True)
    elif adv.get("fetch_news"):
        maybe_enrich_news(results, True)
    log_scenario_scan(SCENARIO, universe, results)
    notify_watchlist_alerts(results, scenario_page_alert_hint(SCENARIO))
    prog.empty()
    scan_progress.empty()
    st.session_state["hd_results"] = results

results = st.session_state.get("hd_results", None)

if results is None:
    st.info(
        "👆 Choose **Nifty 50 (NSE)** or **S&P 500 (NYSE)**, tune filters if you like, then click **SCAN NOW**. "
        "With **Explain why it fell** on, each match gets a headline-based context line."
    )
elif not results:
    no_results_state(SCENARIO)
    st.info(
        "**Why zero matches is common:** all filters must pass at once. In strong markets few large caps are "
        "20–40% below their 52-week high *and* oversold (RSI ≤ 40) *and* high ROE.\n\n"
        "**Try:** preset **Balanced** or **Looser dip hunt**, turn off **P/B ≤ 1.5**, widen drawdown to **12–55%**, "
        "raise **Max RSI** to 45–48, or disable **Near 200-day MA**. Start with **Nifty 50** before Nifty 500."
    )
else:
    st.markdown(f"### 📋 {len(results)} stock(s) matched — review & trade plans")
    pf_sz = float(adv.get("portfolio_for_sizing", 0.0) or 0.0)
    signal_results_download(results, SCENARIO, button_key="hd_dl")
    view = st.radio(
        "View",
        ["Cards", "Table"],
        horizontal=True,
        label_visibility="collapsed",
        key="view_healthy_dip",
    )
    st.markdown("---")

    if view == "Cards":
        render_trade_plan_cards(
            results,
            SCENARIO,
            portfolio_value=pf_sz,
            risk_pct=float(adv.get("risk_pct_per_trade", 1.0) or 1.0),
        )
    else:
        results_table(results, SCENARIO)

    st.markdown("---")
    st.caption("⚠️ Educational screener only. “Why it fell” is keyword-based — always verify on Screener.in or the annual report.")

with st.expander("📘 Beginner checklist (before you buy)", expanded=False):
    st.markdown(
        """
1. **Why did it fall?** Use the blue context line + read full headlines — temporary vs permanent.
2. **Business in 5–10 years?** Can you explain what the company does in one sentence?
3. **Position size** — Could you hold if it drops another 20%?
4. **Diversification** — Aim for 5–8 names across sectors; use 2–3 purchase tranches.
5. **India names** — Cross-check ROE/debt on [Screener.in](https://www.screener.in) when Yahoo omits fields.
"""
    )

st.markdown("---")
st.markdown(
    f"""
<div style='background:#122f25; border:1px solid #1a3b31;
            border-radius:8px; padding:16px; margin-bottom:20px; color:#c8d8e8;'>
    <div style='font-size:1rem; font-weight:600;'>Healthy Dip — active filters</div>
    <div style='margin-top:10px; color:#7ec8e3; font-size:0.92rem;'>
        Preset: <b>{preset}</b> · Universe: <b>{universe}</b> · ROE ≥ {min_roe:.0f}% · D/E ≤ {max_de:.2f} · PE ≤ {max_pe:.0f}
        · Drawdown {dd_range[0]}–{dd_range[1]}% · RSI ≤ {rsi_max}
        · 200-DMA: {"on" if require_ma200 else "off"}
        · Fall context: {"on" if explain_fall else "off"}
    </div>
</div>
""",
    unsafe_allow_html=True,
)
