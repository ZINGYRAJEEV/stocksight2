"""Paper trading UI — simulated portfolio (Algo Hub + standalone page)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from paper_trading import (
    account_summary,
    fetch_last_price,
    paper_buy,
    paper_sell,
    pick_to_buy_kwargs,
    square_off_intraday_positions,
    suggest_quantity,
)
from paper_trading_store import (
    DEFAULT_STARTING_CASH_INR,
    DEFAULT_STARTING_CASH_USD,
    load_paper_account,
    reset_paper_account,
)
from ui_components import inject_css, page_audience_note, safe_set_page_config

try:
    from algo_selector import AlgoPick, HORIZON_META
except ImportError:
    AlgoPick = object  # type: ignore
    HORIZON_META = {}


def _fmt_money(val: float, currency: str) -> str:
    sym = "₹" if currency == "INR" else "$"
    return f"{sym}{val:,.2f}"


def render_paper_trading_panel(
    *,
    picks: list | None = None,
    key_prefix: str = "paper",
    expanded: bool = True,
) -> None:
    """Embed paper trading below Algo Hub or on dedicated page."""
    picks = picks or []
    summ = account_summary()

    with st.expander("📝 Paper trading (simulated — no real orders)", expanded=expanded):
        st.caption(
            "Test Algo Hub picks with virtual cash. Uses Yahoo LTP for mark-to-market. "
            "Not SEBI algo execution — practice only."
        )

        m1, m2, m3, m4, m5 = st.columns(5)
        cur = summ["currency"]
        m1.metric("Equity", _fmt_money(summ["equity"], cur))
        m2.metric("Cash", _fmt_money(summ["cash"], cur))
        m3.metric("Unrealized", _fmt_money(summ["unrealized_pnl"], cur))
        m4.metric("Realized", _fmt_money(summ["realized_pnl"], cur))
        m5.metric("Return %", f"{summ['total_return_pct']:+.2f}%")

        r1, r2, r3 = st.columns(3)
        with r1:
            start_cash = st.number_input(
                "Reset starting cash",
                min_value=10_000.0,
                value=float(
                    DEFAULT_STARTING_CASH_INR if cur == "INR" else DEFAULT_STARTING_CASH_USD
                ),
                step=50_000.0,
                key=f"{key_prefix}_reset_cash",
            )
        with r2:
            risk_pct = st.slider(
                "Risk % per paper trade",
                0.25, 3.0, 1.0, 0.25,
                key=f"{key_prefix}_risk_pct",
            )
        with r3:
            if st.button("🔄 Reset paper account", key=f"{key_prefix}_reset"):
                reset_paper_account(starting_cash=start_cash, currency=cur)
                st.success("Paper account reset.")
                st.rerun()

        if summ["positions_mtm"]:
            st.markdown("#### Open paper positions")
            pdf = pd.DataFrame(summ["positions_mtm"])
            st.dataframe(pdf, use_container_width=True, hide_index=True)

            close_col, sq_col = st.columns([2, 1])
            with close_col:
                close_raw = st.selectbox(
                    "Close position",
                    [r["Raw"] for r in summ["positions_mtm"]],
                    format_func=lambda r: next(
                        (x["Ticker"] for x in summ["positions_mtm"] if x["Raw"] == r), r
                    ),
                    key=f"{key_prefix}_close_sel",
                )
            with sq_col:
                st.write("")
                st.write("")
                if st.button("Sell @ LTP", key=f"{key_prefix}_close_btn"):
                    ltp = fetch_last_price(close_raw)
                    ok, msg = paper_sell(close_raw, price=ltp)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()

            if st.button("⏱ Square off all INTRADAY paper positions", key=f"{key_prefix}_sq_intraday"):
                for msg in square_off_intraday_positions():
                    st.caption(msg)
                st.rerun()
        else:
            st.info("No open paper positions.")

        closed = load_paper_account().get("closed_trades", [])
        if closed:
            with st.expander(f"Closed trades ({len(closed)})", expanded=False):
                cdf = pd.DataFrame(reversed(closed[-30:]))
                show = [c for c in ("closed_at", "ticker", "qty", "entry_price", "exit_price", "pnl", "horizon") if c in cdf.columns]
                st.dataframe(cdf[show] if show else cdf, use_container_width=True, hide_index=True)

        if picks:
            st.markdown("#### Paper-buy from latest Algo Hub picks")
            labels = [
                f"#{p.rank} {p.ticker} · {HORIZON_META.get(p.horizon, {}).get('label', p.horizon)} · {p.gate_band}"
                for p in picks
            ]
            idx = st.selectbox(
                "Pick",
                range(len(picks)),
                format_func=lambda i: labels[i],
                key=f"{key_prefix}_pick_idx",
            )
            pick = picks[idx]
            kw = pick_to_buy_kwargs(pick)
            entry = kw["price"] or (fetch_last_price(kw["raw_ticker"]) or 0.0)
            if entry <= 0:
                st.warning("No entry price on pick — refresh LTP or set limit manually.")
                entry = float(
                    st.number_input("Entry price", min_value=0.0, value=0.0, step=0.05, key=f"{key_prefix}_manual_px")
                )
            else:
                ltp = fetch_last_price(kw["raw_ticker"])
                st.caption(
                    f"Entry ref **{entry:,.2f}**"
                    + (f" · LTP **{ltp:,.2f}**" if ltp else "")
                    + (f" · Stop **{kw['stop']:,.2f}**" if kw.get("stop") else "")
                )

            acc = load_paper_account()
            sug = suggest_quantity(
                cash=float(acc["cash"]),
                entry=entry,
                stop=kw.get("stop"),
                risk_pct=risk_pct,
            )
            b1, b2, b3 = st.columns(3)
            with b1:
                qty = int(st.number_input("Quantity", min_value=1, value=max(1, sug), step=1, key=f"{key_prefix}_qty"))
            with b2:
                use_ltp = st.checkbox("Use live LTP as fill", value=True, key=f"{key_prefix}_use_ltp")
            with b3:
                st.write("")
                if st.button("📝 Paper BUY", type="primary", key=f"{key_prefix}_buy"):
                    px = fetch_last_price(kw["raw_ticker"]) if use_ltp else entry
                    px = px or entry
                    ok, msg = paper_buy(**kw, quantity=qty, price=px)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()

        st.markdown("#### Manual paper trade")
        man1, man2, man3, man4 = st.columns(4)
        with man1:
            man_raw = st.text_input("Ticker", placeholder="RELIANCE.NS", key=f"{key_prefix}_man_raw")
        with man2:
            man_qty = st.number_input("Qty", min_value=1, value=1, key=f"{key_prefix}_man_qty")
        with man3:
            man_px = st.number_input("Price", min_value=0.0, value=0.0, step=0.05, key=f"{key_prefix}_man_px")
        with man4:
            man_hz = st.selectbox("Horizon tag", ["intraday", "weekly", "monthly", "long_term", "manual"], key=f"{key_prefix}_man_hz")
        if st.button("Manual paper BUY", key=f"{key_prefix}_man_buy"):
            px = man_px or (fetch_last_price(man_raw) or 0.0)
            ok, msg = paper_buy(
                raw_ticker=man_raw,
                ticker_display=man_raw,
                quantity=int(man_qty),
                price=px,
                horizon=man_hz,
                source="manual",
            )
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()


def render_paper_trading_page() -> None:
    safe_set_page_config(page_title="Paper Trading | StockSight", page_icon="📝", layout="wide")
    inject_css()
    st.markdown("### 📝 Paper Trading")
    page_audience_note(
        "Anyone practicing entries/exits before using real money or ICICI Breeze Live Trade.",
        "Virtual ledger with starting cash, open positions, realized P&L, and optional link to Algo Hub picks. "
        "Data stored locally in stocksight/.paper_trading.json.",
    )
    report = st.session_state.get("algo_report")
    all_picks: list = []
    if report is not None:
        for plist in getattr(report, "picks_by_horizon", {}).values():
            all_picks.extend(plist)
    if all_picks:
        st.caption(f"Linked to last Algo Hub run ({len(all_picks)} picks in session). Run Algo Hub first for fresh picks.")
    render_paper_trading_panel(picks=all_picks, key_prefix="paper_page", expanded=True)
