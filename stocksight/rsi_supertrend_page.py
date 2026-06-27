"""RSI + Supertrend — live scan (BTST / intraday) and backtest audit."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from btst_screener import btst_timing_schedule
from intraday import MARKET_LABEL, MARKETS, market_session_window, resolve_universe, session_window_now
from rsi_supertrend_backtest import (
    DEFAULT_TICKERS,
    META,
    STEP_MODES,
    UNIVERSE_AUDIT_MODES,
    _build_config,
    prepare_ohlcv,
    results_comparison_df,
    rsi_below_70_pct,
    run_backtest,
    scan_universe_backtest,
    universe_backtest_df,
)
from rsi_supertrend_screener import (
    RsiStScanFilters,
    _intraday_timing_rows,
    btst_scan_recommended,
    intraday_scan_hint,
    scan_rsi_supertrend,
    universe_options,
)
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
    stock_sight_overlay_column_config,
)

IST = ZoneInfo("Asia/Kolkata")
CEST = ZoneInfo("Europe/Berlin")

_GRADE_STYLE = {
    "A": "background-color:#dcfce7;color:#166534;font-weight:700;",
    "B": "background-color:#fef9c3;color:#854d0e;font-weight:600;",
    "C": "background-color:#fee2e2;color:#991b1b;font-weight:600;",
}

_LINK_COLUMNS = ("Yahoo Finance", "Google Finance", "Moneycontrol", "TradingView", "MarketWatch")


def _link_column_config() -> dict:
    return {
        "Yahoo Finance": st.column_config.LinkColumn("Yahoo Finance", display_text="Yahoo ↗"),
        "Google Finance": st.column_config.LinkColumn("Google Finance", display_text="Google ↗"),
        "Moneycontrol": st.column_config.LinkColumn("Moneycontrol", display_text="MC ↗"),
        "TradingView": st.column_config.LinkColumn("TradingView", display_text="TV ↗"),
        "MarketWatch": st.column_config.LinkColumn("MarketWatch", display_text="MW ↗"),
    }


def _results_df(results: list) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        rows.append(
            {
                "Rank": i,
                "Grade": r.grade,
                "Signal": r.signal_label,
                "Ticker": r.ticker,
                "Price": r.price,
                "Day %": r.pct_vs_prev,
                "RSI": r.rsi,
                "ST": r.st_direction,
                "Supertrend": r.supertrend,
                "Vol×": r.vol_ratio,
                "Bars": r.bar_type,
                "Action": r.action[:100] + ("…" if len(r.action) > 100 else ""),
                "Notes": r.notes,
                "Sector": r.sector,
                "Raw": r.raw_ticker,
                **{k: v for k, v in r.links.items()},
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    core = [
        "Rank", "Grade", "Signal", "Ticker", "Price", "Day %", "RSI", "ST",
        "Supertrend", "Vol×", "Bars", "Action", "Notes", "Sector",
    ]
    link_cols = [c for c in _LINK_COLUMNS if c in df.columns]
    return df[[c for c in core if c in df.columns] + link_cols + ["Raw"]]


def _render_when_to_run(scan_mode: str, market: str) -> None:
    """Prominent timing playbook — when users should run each mode."""
    cest_lbl = datetime.now(tz=CEST).strftime("%Z")
    flag = "🇺🇸 NYSE & NASDAQ" if market == "US" else "🇮🇳 NSE"

    with st.container(border=True):
        if scan_mode == "btst":
            timing = btst_timing_schedule(market)
            phase, hint, recommended = btst_scan_recommended(market)
            st.markdown(f"#### 🌙 When to run **BTST** scan · {flag}")
            st.caption(
                f"Times in **Europe/Berlin** ({cest_lbl} in summer · CET in winter). "
                "BTST uses **today's daily bar** — run near the close, not at 10 AM."
            )
            lines = [
                "| Your time (CEST/CET) | Market time | What to do |",
                "|----------------------|-------------|------------|",
            ]
            for cest, mkt, action in timing.schedule_rows:
                action_st = action.replace("BTST scan", "RSI+ST BTST scan")
                lines.append(f"| **{cest}** | {mkt} | {action_st} |")
            lines.append(
                f"| **{timing.exit_deadline_cest}** | {timing.exit_deadline_market} | "
                "☀️ **Tomorrow:** exit on ST bearish / RSI &gt; 70 |"
            )
            st.markdown("\n".join(lines))
        else:
            phase, hint, recommended = intraday_scan_hint(market)
            st.markdown(f"#### ⚡ When to run **Intraday** scan · {flag}")
            st.caption(
                f"Times in **Europe/Berlin** ({cest_lbl}). "
                "Intraday uses **live session bars** — run while the market is open, not after close."
            )
            lines = [
                "| Your time (CEST/CET) | Market time | Guidance |",
                "|----------------------|-------------|----------|",
            ]
            for cest, mkt, action in _intraday_timing_rows(market):
                lines.append(f"| **{cest}** | {mkt} | {action} |")
            st.markdown("\n".join(lines))

        now_line = session_window_now(market)
        st.caption(now_line)

        if phase in ("IDEAL", "BTST_WINDOW", "ENTRY_WINDOW"):
            st.success(f"**Now:** {hint}")
        elif phase in ("OK",):
            st.info(f"**Now:** {hint}")
        elif phase == "SWITCH_BTST":
            st.warning(f"**Now:** {hint}")
        elif phase in ("WAIT", "LATE", "PRE_SCAN"):
            st.warning(f"**Now:** {hint}")
        else:
            st.caption(f"**Now:** {hint}")

        if recommended:
            st.markdown("🟢 **Recommended to run scan now**")
        elif scan_mode == "intraday" and phase == "SWITCH_BTST":
            st.markdown("🟠 **Use BTST mode instead** (select above)")
        else:
            st.markdown("🟠 **Not the ideal window** — you can still run, but signals may be stale or incomplete.")


def _render_playbook(scan_mode: str) -> None:
    with st.expander("📖 Grade legend & execution notes", expanded=False):
        if scan_mode == "btst":
            st.markdown(
                """
| Grade | Meaning |
|-------|---------|
| **A** | Fresh **buy** signal on today's daily bar |
| **B** | **In trend** — hold overnight only if already in |
| **C** | **Exit** signal — no new BTST longs |

Plan entry near **close** (or next open). Exit **next morning** on ST bearish or RSI &gt; 70.

**With backtest audit:** Grade **A** today + positive **fixed** stepwise on that name = stronger confluence (not required).
"""
            )
        else:
            st.markdown(
                """
| Grade | Meaning |
|-------|---------|
| **A** | Fresh **buy** on latest intraday bar |
| **B** | **In trend** — trail Supertrend line |
| **C** | **Exit** — flatten same day |

**Do not hold overnight** from intraday mode — square off before session end.

**With backtest audit:** Prefer names that ranked well on **Universe rank** *and* show Grade **A** here.
"""
            )


def _render_live_scan_tab(key: str) -> None:
    session_results = f"{key}_live_results"
    session_stats = f"{key}_live_stats"

    m1, m2 = st.columns([1.0, 1.2])
    with m1:
        market = st.radio(
            "Market",
            MARKETS,
            format_func=lambda m: MARKET_LABEL.get(m, m),
            horizontal=True,
            key=f"{key}_mkt",
        )
    with m2:
        sess = market_session_window(market)
        cest = datetime.now(tz=CEST).strftime("%H:%M %Z")
        ist = datetime.now(tz=IST).strftime("%H:%M IST")
        st.caption(f"Your time **{cest}** · India **{ist}** · Session: **{sess.get('window', '—')}**")

    if market == "US":
        st.caption("US mode uses **Yahoo Finance** daily / intraday data.")
    else:
        try:
            from breeze_data import breeze_configured, breeze_status_message

            if breeze_configured():
                st.caption(f"OHLCV: **ICICI Breeze** · {breeze_status_message()}")
            else:
                st.caption("OHLCV: **Yahoo Finance** — connect Breeze in sidebar for NSE-aligned bars.")
        except ImportError:
            st.caption("OHLCV: **Yahoo Finance**")

    scan_mode = st.radio(
        "Scan mode",
        ("btst", "intraday"),
        format_func=lambda x: {
            "btst": "🌙 BTST — daily EOD (buy today, manage exit tomorrow)",
            "intraday": "⚡ Intraday — live session bars",
        }[x],
        horizontal=True,
        key=f"{key}_mode",
    )

    _render_when_to_run(scan_mode, market)
    _render_playbook(scan_mode)

    uni_opts = universe_options(market)
    default_uni = next(
        (u for u in ("Nifty 50 (fast)", "Nifty 100 (medium)", "Nifty 500 (broad, slow)") if u in uni_opts),
        uni_opts[0],
    )

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.1, 1.0, 1.0])
        with c1:
            universe = st.selectbox(
                "Universe",
                uni_opts,
                index=uni_opts.index(default_uni) if default_uni in uni_opts else 0,
                key=f"{key}_uni",
            )
            profile = st.selectbox(
                "Strategy profile",
                ("honest_st", "rsi_combo"),
                format_func=lambda p: {
                    "honest_st": "Honest — pure Supertrend flips",
                    "rsi_combo": "RSI + Supertrend (tutorial rules)",
                }[p],
                key=f"{key}_prof",
            )
            show = st.selectbox(
                "Show",
                ("actionable", "buy_only", "all"),
                format_func=lambda s: {
                    "actionable": "Buy + Hold + Exit (A/B/C)",
                    "buy_only": "Fresh buy signals only (A)",
                    "all": "All passes (incl. no setup)",
                }[s],
                key=f"{key}_show",
            )
        with c2:
            max_tickers = st.slider("Max tickers", 25, 600, 200 if scan_mode == "btst" else 120, 25, key=f"{key}_max")
            min_price = st.slider("Min price", 10.0, 500.0, 50.0, 10.0, key=f"{key}_minp")
            max_price = st.slider("Max price", 500.0, 10000.0, 5000.0, 100.0, key=f"{key}_maxp")
        with c3:
            st_period = st.slider("ST ATR period", 7, 14, 10, key=f"{key}_stp")
            st_mult = st.slider("ST multiplier", 2.0, 4.0, 3.0, 0.5, key=f"{key}_stm")
            min_vol = st.slider("Min Vol× (20d)", 0.0, 3.0, 0.0, 0.1, key=f"{key}_vol")
            data_src = "yahoo" if market == "US" else st.selectbox(
                "OHLCV source",
                ("auto", "breeze", "yahoo"),
                format_func=lambda x: {"auto": "Auto", "breeze": "Breeze", "yahoo": "Yahoo"}[x],
                key=f"{key}_ds",
            )

        if scan_mode == "btst":
            c4, c5 = st.columns(2)
            with c4:
                green_only = st.checkbox("Green candle only", value=True, key=f"{key}_green")
            with c5:
                above_prev = st.checkbox("Close above prev close", value=True, key=f"{key}_prev")
        else:
            green_only = False
            above_prev = False

        run = st.button("▶ Run live scan", type="primary", key=f"{key}_scan")

    if run:
        flt = RsiStScanFilters(
            mode=scan_mode,
            market=market,
            universe=universe,
            data_source=data_src,
            profile=profile,
            max_tickers=int(max_tickers),
            min_price=float(min_price),
            max_price=float(max_price),
            show=show,
            st_period=int(st_period),
            st_multiplier=float(st_mult),
            btst_green_only=green_only,
            btst_above_prev=above_prev,
            min_vol_ratio=float(min_vol),
        )
        prog = st.progress(0.0, text="Starting scan…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(i / max(total, 1), text=f"{sym} ({i}/{total})")

        with st.spinner("Scanning latest bars…"):
            results, stats = scan_rsi_supertrend(flt, progress_cb=_cb)
        prog.empty()

        st.session_state[session_results] = results
        st.session_state[session_stats] = stats
        st.session_state[f"{key}_scan_mode"] = scan_mode
        append_scan_record(
            "rsi_supertrend",
            universe,
            [r.raw_ticker for r in results if r.grade == "A"],
            meta={"mode": scan_mode, "grade_a": stats.grade_a, "market": market},
        )

    results = st.session_state.get(session_results) or []
    stats = st.session_state.get(session_stats)

    if not results and not run:
        if scan_mode == "btst":
            timing = btst_timing_schedule(market)
            hint = (
                f"**BTST:** run between **{timing.scan_market}** "
                f"(**{timing.scan_cest}** your time) after today's candle is nearly set."
            )
        else:
            _, ihint, _ = intraday_scan_hint(market)
            hint = f"**Intraday:** {ihint}"
        st.info(f"Choose universe and click **Run live scan**. {hint}")
        return

    if stats:
        st.success(
            f"**{len(results)}** matches · scanned **{stats.tickers_scanned}** · "
            f"Buy **{stats.grade_a}** · Hold **{stats.grade_b}** · Exit **{stats.grade_c}** · "
            f"{stats.scan_elapsed_sec:.0f}s"
        )

    buys = [r for r in results if r.grade == "A"]
    if scan_mode == "btst" and buys:
        st.markdown("#### 🌙 Tonight's BTST candidates")
        st.caption(
            "Grade **A** = fresh buy on latest bar. Cross-check top names on **Backtest audit → Universe rank** "
            "if you want historical confirmation."
        )
        for r in buys[:8]:
            st.markdown(f"- **{r.ticker}** · RSI {r.rsi} · ST {r.st_direction} · Day {r.pct_vs_prev:+.2f}%")

    df = _results_df(results)
    if df.empty:
        st.warning("No names matched filters. Try **Buy + Hold + Exit**, relax Vol×, or widen universe.")
        return

    show_cols = [c for c in df.columns if c != "Raw"]
    styler = df[show_cols].style.apply(
        lambda col: [_GRADE_STYLE.get(str(v), "") for v in col],
        subset=["Grade"],
    )
    sym = "$" if market == "US" else "₹"
    render_clickable_scan_table(
        df[show_cols],
        styler=styler,
        key_prefix=f"{key}_live",
        market=market,
        apply_stock_sight=False,
        column_config={
            **_link_column_config(),
            **stock_sight_overlay_column_config(),
            "Grade": st.column_config.TextColumn(width="small"),
            "Signal": st.column_config.TextColumn(width="medium"),
            "Price": st.column_config.NumberColumn(format=f"{sym}%.2f"),
            "Day %": st.column_config.NumberColumn(format="%+.2f"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "Supertrend": st.column_config.NumberColumn(format=f"{sym}%.2f"),
            "Vol×": st.column_config.NumberColumn(format="%.1f"),
            "Action": st.column_config.TextColumn(width="large"),
        },
        caption=(
            "**Grade A** = fresh buy · **B** = in trend · **C** = exit. "
            "Click row for chart · links open research."
        ),
        show_gate_legend=False,
    )


def _display_from_raw(raw: str) -> str:
    s = str(raw or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def _interpret_sharpe(sharpe: float) -> str:
    if sharpe >= 1.0:
        return "Good risk-adjusted history"
    if sharpe >= 0.3:
        return "Acceptable — not standout"
    if sharpe >= 0:
        return "Flat risk-adjusted edge"
    return "Poor — strategy lost vs risk-free on active days"


def _interpret_return(ret: float) -> str:
    if ret >= 15:
        return "Strong cumulative gain in window"
    if ret >= 5:
        return "Moderate gain"
    if ret >= 0:
        return "Slightly positive"
    return "Net loss in backtest window"


def _interpret_score(score: float) -> tuple[str, str]:
    """Return (short label, detail) for composite score."""
    if score <= -900:
        return "Disqualified", "Fewer trades than your minimum — not ranked."
    if score >= 1.0:
        return "Strong fit", "Top-tier vs peers on Sharpe, return, and drawdown."
    if score >= 0:
        return "Modest fit", "Positive composite — still check live Grade A before acting."
    return "Weak fit", (
        "Negative score = still the **best among ranked names**, not a green light. "
        "Often means the whole universe struggled in this profile."
    )


def _render_audit_workflow() -> None:
    with st.expander("🧭 Recommended workflow (backtest → live)", expanded=False):
        st.markdown(
            """
| Step | Tab | What you learn |
|------|-----|----------------|
| **1** | **Backtest audit** → Universe rank | Which names *historically* suited RSI+ST / Supertrend in your window |
| **2** | **Backtest audit** → Deep-dive stepwise | Whether edge survives **honest** fixes (next-open, costs, sizing) — not just tutorial math |
| **3** | **Live scan** | Whether the winner has a **Grade A** setup **today** (BTST or intraday) |

**Rule of thumb:** Only consider a trade when **step 1 + step 3** agree. Step 2 tells you if the backtest is trustworthy.

Past performance ≠ future results. Educational tool only.
"""
        )


def _render_universe_reading_guide() -> None:
    with st.expander("📖 How to read universe rank & best pick", expanded=False):
        st.markdown(
            """
### What you are looking at
Each row is one stock run through the **same** backtest rules you picked (profile, years, capital).
The table sorts by **Score** — a blend of Sharpe, return, drawdown, and win rate — not by tonight's chart.

### Column guide
| Column | How to read it |
|--------|----------------|
| **Rank** | 1 = highest composite score in this run (your **best pick**) |
| **Score** | Higher is better *within this universe*. Can still be **negative** if every name lost money |
| **Return %** | Total P&amp;L on starting capital over the history window (after profile rules) |
| **Sharpe** | Risk-adjusted quality while in trades; **&gt; 1** is solid, **&lt; 0** is poor |
| **Win %** | Share of closed trades that made money — low win % can still work if winners are large |
| **Max DD %** | Worst peak-to-trough equity drop — closer to **0** is smoother |
| **Trades** | Must be **≥ min trades** to qualify; too few = noisy / disqualified |

### Best pick card
- **Best pick** = top score in *this* scan — **not** automatic buy advice.
- If **Return** or **Score** is negative, you are picking the **least weak** name, not a confirmed winner.
- Always cross-check on **Live scan**: look for **Grade A** (fresh buy) on the same profile you trust from stepwise audit.

### Backtest profile (dropdown)
| Profile | Use when |
|---------|----------|
| **Fixed — honest Supertrend** | You want the strictest reference (pure ST, realistic fills) |
| **RSI + ST — all honesty fixes** | You trade the tutorial RSI+ST rules but with costs &amp; next-open fills |
| **RSI + ST — next-open only** | Quick check if execution timing alone kills the edge |
| **Broken tutorial** | Contrast only — usually **overstates** returns |

### If the table is empty
Lower **Min trades**, widen **History**, or switch profile to **RSI + ST — all honesty fixes** (often more trades than pure ST).
"""
        )


def _render_stepwise_reading_guide() -> None:
    with st.expander("📖 How to read stepwise audit", expanded=False):
        st.markdown(
            """
### What the 6 rows mean
Each row adds **one more realism layer** on top of the previous. Read **top → bottom**:

| Mode | What changed | What to watch |
|------|--------------|---------------|
| **broken** | Same-bar close, 100% size, RSI rules | Usually **inflated** — tutorial/backtest scam territory |
| **+ Next-day open** | Signals execute at **next bar open** | Return often **drops** — proves lookahead bias |
| **+ Costs & slippage** | 0.1% commission + 0.05% slip per leg | Another step down — closer to real brokerage |
| **+ 10% sizing** | Only 10% of equity per trade | Return scales down; drawdown usually improves |
| **+ 3-day cooldown** | No re-entry for 3 days after exit | Fewer trades; tests overtrading |
| **fixed** | Pure Supertrend, Sharpe on **in-market days only** | Honest ST reference — compare to **broken** gap |

### Column guide
| Column | How to read it |
|--------|----------------|
| **Total return %** | End equity vs start capital for that mode |
| **Win rate %** | % of trades closed in profit |
| **Max drawdown %** | Worst equity dip — **more negative = bumpier ride** |
| **Sharpe** | Risk-adjusted return (mode-specific: calendar vs active days on **fixed**) |
| **Trades** | Sample size — **&lt; 5** is anecdotal; prefer **10+** for trust |

### Healthy vs unhealthy audit
| Pattern | Verdict |
|---------|---------|
| **broken** high, **fixed** near zero or negative | Strategy was mostly **curve-fit / lookahead** — do not trade live |
| Returns step down gradually, **fixed** still positive with **10+ trades** | Edge may be **real but small** — size small, use Live scan for timing |
| **Win rate** under 40% but positive **fixed** return | Trend-following style — normal; rely on ST trail, not win rate |
| Equity curve (chart) smooth until **broken**, then choppy after fixes | Visual confirmation that honesty matters |

### RSI &lt; 70 % (header metric)
Shows how often RSI &lt; 70 on daily bars — illustrates why **"RSI &lt; 70"** alone is a weak filter (often 80%+ of bars).
"""
        )


def _render_best_pick_reading(best, stats, years: float, capital: float, sym: str) -> None:
    label, detail = _interpret_score(best.score)
    sharpe_note = _interpret_sharpe(best.sharpe)
    ret_note = _interpret_return(best.total_return_pct)

    if best.score >= 0:
        st.success(f"**{label}** — {detail}")
    elif best.score > float("-inf"):
        st.warning(f"**{label}** — {detail}")
    else:
        st.error(detail)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"- **Return ({best.total_return_pct:+.1f}%):** {ret_note}\n"
            f"- **Sharpe ({best.sharpe:.2f}):** {sharpe_note}"
        )
    with c2:
        st.markdown(
            f"- **Win rate ({best.win_rate_pct:.0f}%):** "
            f"{'Majority of trades won' if best.win_rate_pct >= 50 else 'Losers may be larger than winners (trend style)'}\n"
            f"- **Max DD ({best.max_drawdown_pct:.1f}%):** "
            f"{'Mild drawdown' if best.max_drawdown_pct > -10 else 'Deep drawdown — size carefully'}"
        )

    st.markdown(
        f"**Next:** Open **Live scan** → same market → filter **{best.display_ticker}** "
        f"or run **Deep-dive stepwise** below to see if **broken → fixed** still holds for this name."
    )


def _render_stepwise_results(key: str, raw: str, years: float, capital: float) -> None:
    with st.spinner(f"Backtesting {raw}…"):
        df = prepare_ohlcv(raw, years=float(years))
        if df is None or df.empty:
            st.error(f"No data for **{raw}**.")
            return
        results = []
        for mode_id, mode_label, _ in STEP_MODES:
            lbl, cfg = _build_config(mode_id)
            cfg.initial_capital = float(capital)
            results.append(run_backtest(df, cfg, mode_id=mode_id, mode_label=lbl))

    m1, m2, m3 = st.columns(3)
    m1.metric("Bars", len(df))
    m2.metric("RSI < 70 %", f"{rsi_below_70_pct(df)}%")
    m3.metric("Range", f"{df.index[0].date()} → {df.index[-1].date()}")

    _render_stepwise_reading_guide()

    broken = next((r for r in results if r.mode_id == "broken"), None)
    fixed = next((r for r in results if r.mode_id == "fixed"), None)
    if broken and fixed:
        gap = broken.total_return_pct - fixed.total_return_pct
        if gap > 20:
            st.warning(
                f"**Honesty gap {gap:.1f} pp** — broken return **{broken.total_return_pct:+.1f}%** vs "
                f"fixed **{fixed.total_return_pct:+.1f}%**. Large gap = tutorial math overstated the edge."
            )
        elif fixed.total_return_pct > 0 and fixed.num_trades >= 5:
            st.info(
                f"**Fixed mode still positive** ({fixed.total_return_pct:+.1f}%, {fixed.num_trades} trades) — "
                "worth checking **Live scan** for a Grade A entry; not a standalone buy signal."
            )
        elif fixed.total_return_pct <= 0:
            st.error(
                f"**Fixed mode negative** ({fixed.total_return_pct:+.1f}%) — this name did not reward "
                "honest Supertrend rules in the selected window."
            )

    st.dataframe(
        results_comparison_df(results),
        use_container_width=True,
        hide_index=True,
    )

    try:
        import plotly.graph_objects as go

        fig = go.Figure()
        for r in results:
            if r.equity_curve.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=r.equity_curve["date"],
                    y=r.equity_curve["equity"],
                    name=r.mode_id,
                )
            )
        fig.update_layout(title=f"Equity curves — {_display_from_raw(raw)}", height=360, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Chart: each line = one audit mode. **broken** often looks best but is misleading — "
            "compare **broken** vs **fixed** separation."
        )
    except ImportError:
        pass


def _render_universe_audit(key: str) -> None:
    session_rows = f"{key}_uni_bt_rows"
    session_stats = f"{key}_uni_bt_stats"

    st.markdown(
        "Rank every name in a universe on the **honest backtest** profile, then surface the "
        "**best pick** by composite score (Sharpe, return, drawdown, win rate)."
    )
    st.caption(
        "Educational ranking only — past backtest ≠ future performance. "
        "Requires ≥ min trades to qualify."
    )
    _render_universe_reading_guide()

    market = st.radio(
        "Market",
        MARKETS,
        format_func=lambda m: MARKET_LABEL.get(m, m),
        horizontal=True,
        key=f"{key}_bt_mkt",
    )

    uni_opts = universe_options(market)
    default_uni = next(
        (u for u in ("Nifty 50 (fast)", "Nifty 100 (medium)", "Nifty 500 (broad, slow)") if u in uni_opts),
        uni_opts[0] if uni_opts else "",
    )

    mode_ids = [m[0] for m in UNIVERSE_AUDIT_MODES]
    mode_labels = {m[0]: m[1] for m in UNIVERSE_AUDIT_MODES}

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.2, 1.0, 1.0])
        with c1:
            universe = st.selectbox(
                "Universe",
                uni_opts,
                index=uni_opts.index(default_uni) if default_uni in uni_opts else 0,
                key=f"{key}_bt_uni",
            )
            audit_mode = st.selectbox(
                "Backtest profile",
                mode_ids,
                format_func=lambda m: mode_labels.get(m, m),
                index=0,
                key=f"{key}_bt_mode",
            )
        with c2:
            max_tickers = st.slider("Max tickers", 10, 200, 50, 5, key=f"{key}_bt_max")
            min_trades = st.slider("Min trades to qualify", 1, 15, 2, key=f"{key}_bt_mintr")
        with c3:
            years = st.slider("History (years)", 1.0, 5.0, 2.0, 0.5, key=f"{key}_bt_yrs")
            cap_lbl = "Capital ($)" if market == "US" else "Capital (₹)"
            capital = st.number_input(cap_lbl, 10_000, 5_000_000, 100_000, 10_000, key=f"{key}_bt_cap")

        run = st.button("▶ Rank universe", type="primary", key=f"{key}_bt_run")

    if run:
        tickers = resolve_universe(universe, market=market)[: int(max_tickers)]
        prog = st.progress(0.0, text="Starting universe backtest…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(i / max(total, 1), text=f"{sym} ({i}/{total})")

        with st.spinner("Running walk-forward backtests…"):
            rows, stats = scan_universe_backtest(
                tickers,
                years=float(years),
                capital=float(capital),
                mode_id=audit_mode,
                min_trades=int(min_trades),
                progress_cb=_cb,
            )
        prog.empty()
        stats.universe = universe
        stats.market = market
        st.session_state[session_rows] = rows
        st.session_state[session_stats] = stats
        append_scan_record(
            "rsi_st_universe_audit",
            universe,
            [r.raw_ticker for r in rows[:5]],
            meta={"mode": audit_mode, "best": rows[0].display_ticker if rows else ""},
        )

    rows = st.session_state.get(session_rows) or []
    stats = st.session_state.get(session_stats)

    if not rows and not run:
        st.info("Pick a universe and click **Rank universe** to see the best historical fit.")
        return

    if stats:
        st.success(
            f"Ranked **{stats.tickers_ranked}** / **{stats.tickers_scanned}** tickers · "
            f"no data **{stats.no_data}** · profile **{stats.mode_label}** · "
            f"{stats.scan_elapsed_sec:.0f}s"
        )

    best = rows[0]
    sym = "₹" if (stats and stats.market != "US") else "$"
    with st.container(border=True):
        st.markdown(f"#### 🏆 Best pick — **{best.display_ticker}**")
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        b1.metric("Score", f"{best.score:.2f}")
        b2.metric("Return", f"{best.total_return_pct:+.1f}%")
        b3.metric("Sharpe", f"{best.sharpe:.2f}")
        b4.metric("Win rate", f"{best.win_rate_pct:.0f}%")
        b5.metric("Max DD", f"{best.max_drawdown_pct:.1f}%")
        b6.metric("Trades", best.num_trades)
        st.caption(
            f"Highest composite score in **{stats.universe if stats else universe}** "
            f"over ~{years:.0f}y daily bars · capital {sym}{capital:,.0f}."
        )
        _render_best_pick_reading(best, stats, years, capital, sym)

    df = universe_backtest_df(rows)
    if df.empty:
        st.warning(
            f"No names met **≥ {min_trades} trades**. Lower min trades or widen history / universe."
        )
        return

    show_cols = [c for c in df.columns if c != "Raw"]
    st.markdown("#### Ranked table")
    st.caption(
        "Sorted by **Score** (desc). **Rank 1** = best pick above. "
        "Negative scores are common — compare peers, not absolute levels."
    )
    st.dataframe(
        df[show_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Return %": st.column_config.NumberColumn(format="%+.1f"),
            "Sharpe": st.column_config.NumberColumn(format="%.2f"),
            "Win %": st.column_config.NumberColumn(format="%.0f"),
            "Max DD %": st.column_config.NumberColumn(format="%.1f"),
            "Score": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    pick_opts = [r.raw_ticker for r in rows[:15]]
    drill = st.selectbox(
        "Deep-dive stepwise audit",
        pick_opts,
        format_func=_display_from_raw,
        key=f"{key}_bt_drill",
    )
    if st.button("▶ Run stepwise audit on selection", key=f"{key}_bt_drill_run"):
        _render_stepwise_results(key, drill, years, capital)


def _render_single_audit(key: str) -> None:
    c1, c2, c3 = st.columns([1.2, 1.0, 1.0])
    with c1:
        ticker = st.selectbox(
            "Ticker",
            DEFAULT_TICKERS,
            format_func=lambda t: t.replace(".NS", ""),
            key=f"{key}_bt_ticker",
        )
        custom = st.text_input("Custom symbol", placeholder="M&M.NS", key=f"{key}_bt_custom")
        raw = (custom.strip() or ticker).upper()
        if raw and not raw.endswith((".NS", ".BO")) and "." not in raw:
            raw = f"{raw}.NS"
    with c2:
        years = st.slider("History (years)", 1.0, 5.0, 2.0, 0.5, key=f"{key}_yrs")
    with c3:
        capital = st.number_input("Capital (₹)", 10_000, 5_000_000, 100_000, 10_000, key=f"{key}_cap")

    run = st.button("▶ Run stepwise audit", key=f"{key}_audit")

    if not run:
        st.caption("Single-stock walk-forward audit with 6 cumulative fix layers.")
        _render_stepwise_reading_guide()
        return

    _render_stepwise_results(key, raw, years, capital)


def _render_audit_tab(key: str) -> None:
    _render_audit_workflow()

    audit_view = st.radio(
        "Audit view",
        ("universe", "single"),
        format_func=lambda x: {
            "universe": "🌐 Universe rank & best pick",
            "single": "🔬 Single-stock stepwise audit",
        }[x],
        horizontal=True,
        key=f"{key}_audit_view",
    )

    if audit_view == "universe":
        _render_universe_audit(key)
    else:
        _render_single_audit(key)


def render_rsi_supertrend_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    key = "rsi_st"
    st.markdown(f"### {META['emoji']} {META['title']}")
    page_audience_note(META["audience"], META["purpose"])

    render_watchlist_panel("rsi_st_wl")

    tab_live, tab_audit = st.tabs(["📡 Live scan (BTST / Intraday)", "📊 Backtest audit"])

    with tab_live:
        _render_live_scan_tab(key)

    with tab_audit:
        _render_audit_tab(key)
