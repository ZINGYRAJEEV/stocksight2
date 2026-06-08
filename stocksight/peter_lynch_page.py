"""Peter Lynch Screener — Streamlit UI."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from peter_lynch import (
    DATA_SOURCE_LABELS,
    DATA_SOURCE_OPTIONS,
    LYNCH_CATEGORIES,
    META,
    LynchFilters,
    scan_peter_lynch,
    universe_options,
)
from scan_history_store import append_scan_record
from ui_components import (
    inject_css,
    page_audience_note,
    render_clickable_scan_table,
    render_watchlist_panel,
    safe_set_page_config,
)


def _category_style(series: pd.Series) -> list[str]:
    colors = {
        "Fast Grower": "background-color:#dcfce7;color:#166534;font-weight:600;",
        "Stalwart": "background-color:#dbeafe;color:#1e40af;",
        "Slow Grower": "background-color:#fef9c3;color:#854d0e;",
        "Cyclical": "background-color:#ffedd5;color:#9a3412;",
        "Turnaround": "background-color:#fce7f3;color:#9d174d;",
        "Asset Play": "background-color:#e0e7ff;color:#3730a3;",
    }
    return [colors.get(str(v), "") for v in series]


def _peg_style(series: pd.Series) -> list[str]:
    styles = []
    for v in series:
        try:
            x = float(v)
        except (TypeError, ValueError):
            styles.append("")
            continue
        if x < 1.0:
            styles.append("background-color:#dcfce7;color:#166534;font-weight:600;")
        elif x <= 2.0:
            styles.append("background-color:#fef9c3;color:#854d0e;")
        else:
            styles.append("background-color:#fee2e2;color:#991b1b;")
    return styles


def _results_df(results: list) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(results, start=1):
        rows.append(
            {
                "S.No.": i,
                "Ticker": r.ticker,
                "Category": r.lynch_category,
                "Lynch score": r.lynch_score,
                "PEG": r.peg,
                "PEGY": r.pegy,
                "PEG verdict": r.peg_verdict,
                "GARP": r.garp_fit,
                "P/E": r.pe,
                "EPS growth %": r.eps_growth_pct,
                "Div yield %": r.div_yield_pct,
                "D/E": r.debt_equity,
                "Inventory": r.inventory_note,
                "Mar Cap": r.market_cap_display,
                "Sector": r.sector,
                "Action": r.action,
                "Price data": r.price_source,
                "Fundamentals": r.fundamentals_source,
                "Two-minute drill": r.two_minute_prompt,
                "Rationale": r.category_rationale,
                "Raw": r.raw_ticker,
                **{k: v for k, v in r.links.items()},
            }
        )
    return pd.DataFrame(rows)


def _render_framework() -> None:
    with st.expander("📘 Lynch's six categories", expanded=False):
        st.markdown(
            """
| Category | Growth | Lynch case |
|----------|--------|--------------|
| **Slow Grower** | 2–6% | Dividends, mature utilities & consumer staples |
| **Stalwart** | 8–12% | Large blue-chips; 30–50% gains realistic |
| **Fast Grower** | 15–25%+ | Tenbaggers — **PEG** avoids overpaying |
| **Cyclical** | Variable | Steel, autos, airlines — buy downturns |
| **Turnaround** | Variable | Restructuring — high risk, high reward |
| **Asset Play** | N/A | Hidden NAV (cash, real estate, patents) |

**Category confusion** = applying tech multiples to a stalwart. This screener assigns one primary bucket per stock.
"""
        )

    with st.expander("📡 ICICI Breeze vs Yahoo", expanded=False):
        st.markdown(
            """
| Data | Auto / Breeze | Yahoo |
|------|---------------|-------|
| NSE/BSE **price** (LTP) | ICICI Breeze when connected | Yahoo quote |
| **OHLC / 52w high** | Breeze daily bars (+ Yahoo supplement for 52w) | Yahoo history |
| **P/E, PEG, growth, dividend, D/E** | Yahoo `info` (EPS applied to Breeze price for P/E) | Yahoo |

Configure Breeze in `.streamlit/secrets.toml` or sidebar — session token refreshes daily.
"""
        )

    with st.expander("📐 GARP — PEG & PEGY", expanded=False):
        st.markdown(
            """
**PEG** = P/E ÷ projected EPS growth rate
- **< 1.0** — undervalued vs growth (GARP sweet spot)
- **1.0–2.0** — fair
- **> 2.0** — expensive

**PEGY** = P/E ÷ (earnings growth % + dividend yield %)
- Use for **Slow Growers** so yield isn't penalized.

*Growth rates are Yahoo proxies (earnings or revenue growth). Cross-check on [Screener.in](https://www.screener.in).*
"""
        )

    with st.expander("⏱️ Two-minute drill (before you buy)", expanded=False):
        st.markdown(
            """
Can you explain the thesis in **under two minutes**?

1. **Why** will this company succeed?
2. **What** must happen for the stock to rise?
3. **Risks** — debt, inventory, cycle, competition?

Also check: balance sheet strength · debt/equity · inventory trend · insider buying (manual on Screener/BSE).
"""
        )

    with st.expander("🏆 Golden rules (Lynch)", expanded=False):
        st.markdown(
            """
- **Ignore macro** — focus on the company (Rule 19)
- **Avoid hot industries** — great companies in cold industries win (Rule 11)
- **Stomach for declines** — or avoid stocks (Rules 16–17)
- **Sell on fundamentals**, not panic (Rule 18)
- **Do the homework** — or your odds are like poker without looking at cards (Rule 21)
- **Tenbaggers** — one huge winner offsets several modest losers; don't sell winners too early
"""
        )


def render_peter_lynch_page() -> None:
    safe_set_page_config(
        page_title=f"{META['nav_title']} | StockSight",
        page_icon=META["emoji"],
        layout="wide",
    )
    inject_css()

    st.html(f"""
    <div style='background:#1e3a2f; border:1px solid #2d5a47; border-left:4px solid #fbbf24;
                border-radius:8px; padding:18px 22px; margin-bottom:14px;'>
        <div style='font-size:1.35rem; font-weight:700; color:#ecfdf5;'>{META['emoji']} {META['title']}</div>
        <div style='font-size:0.85rem; color:#a7f3d0; margin-top:6px;'>
            Six categories · PEG / PEGY (GARP) · debt & inventory · tenbagger hunting
        </div>
    </div>
    """)

    page_audience_note(META["audience"], META["purpose"])
    _render_framework()
    render_watchlist_panel("lynch_wl")

    try:
        from breeze_data import breeze_configured, breeze_status_message

        breeze_ok = breeze_configured()
        breeze_msg = breeze_status_message()
    except Exception:
        breeze_ok = False
        breeze_msg = "Breeze module not available"

    key = "lynch"
    session_results = f"{key}_results"
    session_at = f"{key}_at"

    uni_opts = universe_options()
    default_uni = next((u for u in ("Nifty 50 (NSE)", "Nifty 50 (fast)") if u in uni_opts), uni_opts[0])
    uni_idx = uni_opts.index(default_uni) if default_uni in uni_opts else 0

    with st.container(border=True):
        ds_default = st.session_state.get(f"{key}_data_source", "auto")
        if ds_default not in DATA_SOURCE_OPTIONS:
            ds_default = "auto"
        data_source = st.radio(
            "Market data API (NSE/BSE prices)",
            DATA_SOURCE_OPTIONS,
            format_func=lambda k: DATA_SOURCE_LABELS[k],
            index=list(DATA_SOURCE_OPTIONS).index(ds_default),
            key=f"{key}_data_api",
            horizontal=True,
        )
        st.session_state[f"{key}_data_source"] = data_source
        if data_source == "breeze" and not breeze_ok:
            st.warning(
                "Breeze is **not connected** — use **Auto** or **Yahoo**, or refresh your daily "
                "session token in the sidebar **ICICI Breeze API** expander."
            )
        elif data_source in ("auto", "breeze") and breeze_ok:
            st.caption(f"✓ {breeze_msg}")
        elif data_source == "auto":
            st.caption("Breeze not configured — **Auto** falls back to Yahoo for all tickers.")
        st.caption(
            "ICICI Breeze supplies **live NSE/BSE prices & OHLC** when connected. "
            "**PEG, growth, debt, dividend** still use Yahoo `info` (Breeze has no fundamentals API here)."
        )

        c1, c2, c3 = st.columns([1.1, 1.0, 1.0])
        with c1:
            universe = st.selectbox("Universe", uni_opts, index=uni_idx, key=f"{key}_uni")
            cats = st.multiselect(
                "Categories",
                LYNCH_CATEGORIES,
                default=list(LYNCH_CATEGORIES),
                key=f"{key}_cats",
            )
        with c2:
            max_peg = st.slider("Max PEG", 0.5, 4.0, 2.0, 0.1, key=f"{key}_maxpeg")
            max_pegy = st.slider("Max PEGY (slow growers)", 0.5, 3.0, 1.5, 0.1, key=f"{key}_maxpegy")
            max_de = st.slider("Max debt/equity", 0.0, 3.0, 1.5, 0.05, key=f"{key}_maxde")
        with c3:
            min_score = st.slider("Min Lynch score", 20, 80, 45, key=f"{key}_minsc")
            require_garp = st.checkbox("GARP only (PEG or PEGY ≤ 1)", value=False, key=f"{key}_garp")
            max_n = st.slider("Max tickers to scan", 20, 150, 60, key=f"{key}_maxn")

    flt = LynchFilters(
        universe=universe,
        categories=tuple(cats) if cats else LYNCH_CATEGORIES,
        max_peg=float(max_peg),
        max_pegy=float(max_pegy),
        max_debt_equity=float(max_de),
        min_lynch_score=float(min_score),
        require_garp=bool(require_garp),
        max_tickers=int(max_n),
        data_source=data_source,
    )

    if st.button(f"🦉 RUN {META['nav_title'].upper()} SCAN", type="primary", key=f"{key}_run"):
        prog = st.progress(0, text="Starting Lynch scan…")

        def _cb(i: int, total: int, sym: str) -> None:
            prog.progress(min(99, int(100 * i / max(total, 1))), text=f"Lynch: {sym} ({i}/{total})")

        results, stats = scan_peter_lynch(flt, progress_cb=_cb)
        prog.progress(100, text="Done")
        st.session_state[session_results] = results
        st.session_state[f"{key}_stats"] = stats
        st.session_state[session_at] = datetime.now().strftime("%d %b %Y %H:%M:%S")
        append_scan_record(
            "peter_lynch",
            universe,
            [r.raw_ticker for r in results],
            meta={"categories": list(cats)},
        )

    results = st.session_state.get(session_results, [])
    stats = st.session_state.get(f"{key}_stats")
    scan_at = st.session_state.get(session_at)

    if stats:
        ds_label = DATA_SOURCE_LABELS.get(stats.data_source, stats.data_source)
        st.caption(
            f"Scanned **{stats.tickers_scanned}** · matched **{stats.tickers_matched}** · "
            f"skipped **{stats.no_data}** · {stats.scan_elapsed_sec:.1f}s · "
            f"API: **{ds_label}** · Breeze prices **{stats.breeze_price_count}** · "
            f"Yahoo prices **{stats.yahoo_price_count}**"
            + (f" · {scan_at}" if scan_at else "")
        )

    if not results:
        st.info("Run a scan to classify stocks into Lynch categories with PEG / PEGY.")
        return

    df = _results_df(results)
    show_cols = [c for c in df.columns if c not in ("Raw", "Two-minute drill", "Rationale")]
    styler = df[show_cols].style.apply(_category_style, subset=["Category"])
    if "PEG" in show_cols:
        styler = styler.apply(_peg_style, subset=["PEG"])

    render_clickable_scan_table(
        df[show_cols],
        styler=styler,
        key_prefix=key,
        column_config={
            "Lynch score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "PEG": st.column_config.NumberColumn(format="%.2f"),
            "PEGY": st.column_config.NumberColumn(format="%.2f"),
            "P/E": st.column_config.NumberColumn(format="%.1f"),
            "EPS growth %": st.column_config.NumberColumn(format="%+.1f"),
            "Div yield %": st.column_config.NumberColumn(format="%.2f"),
            "D/E": st.column_config.NumberColumn(format="%.2f"),
            "Google Finance": st.column_config.LinkColumn(display_text="Google ↗"),
        },
        caption="Sorted by **Lynch score** then **PEG**. Click a row for chart. Use **Two-minute drill** expander below.",
        show_gate_legend=False,
    )

    with st.expander("⏱️ Two-minute drill prompts (matched stocks)", expanded=False):
        for r in results[:15]:
            st.markdown(f"**{r.ticker}** ({r.lynch_category}) — {r.two_minute_prompt}")

    st.caption(
        "⚠️ Category labels are heuristic (Yahoo data). Verify growth, debt, and insider activity on "
        "[Screener.in](https://www.screener.in) before investing. Not financial advice."
    )
