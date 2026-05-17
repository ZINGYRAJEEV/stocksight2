"""Page: Portfolio — simple qty / entry tracking with live MTM from Yahoo (best-effort)."""

from __future__ import annotations

import math

import streamlit as st
import pandas as pd
import yfinance as yf

from screener import compute_rsi, fetch_price_history
from watchlist_store import list_open_positions, upsert_watchlist_fields
from ui_components import inject_css, notify_watchlist_alerts_from_metrics, render_watchlist_panel, safe_set_page_config

safe_set_page_config(page_title="Portfolio | StockSight", page_icon="💼", layout="wide")
inject_css()

st.markdown("### 💼 Portfolio tracker")
st.caption(
    "Positions live in the same JSON store as the watchlist (`stocksight/.watchlist.json`). "
    "Set **qty** + **entry price** on a symbol to track MTM; clearing qty removes the position fields."
)

render_watchlist_panel("pf_wl")


def _wl_row_has_alert_rules(row: dict) -> bool:
    for key in ("alert_rsi_below", "alert_rsi_above", "alert_price_above", "alert_price_below"):
        v = row.get(key)
        try:
            if v is not None and float(v) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _wl_row_needs_rsi(row: dict) -> bool:
    for key in ("alert_rsi_below", "alert_rsi_above"):
        v = row.get(key)
        try:
            if v is not None and float(v) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


rows = list_open_positions()

with st.expander("Add / update position", expanded=False):
    sym = st.text_input("Raw ticker (e.g. RELIANCE.NS or AAPL)", key="pf_sym")
    qty = st.number_input("Quantity", min_value=0.0, value=0.0, step=1.0, key="pf_qty")
    ep = st.number_input("Average entry price", min_value=0.0, value=0.0, step=0.05, key="pf_ep")
    ed = st.text_input("Entry date (YYYY-MM-DD, optional)", value="", key="pf_ed")
    if st.button("Save position", key="pf_save"):
        sym_clean = (sym or "").strip()
        if not sym_clean:
            st.error("Ticker required.")
        elif qty <= 0 or ep <= 0:
            upsert_watchlist_fields(sym_clean, {"qty": None, "entry_price": None, "entry_date": None})
            st.success("Cleared position fields for this ticker.")
            st.rerun()
        else:
            upsert_watchlist_fields(
                sym_clean,
                {"qty": float(qty), "entry_price": float(ep), "entry_date": (ed or "").strip() or None},
            )
            st.success("Saved.")
            st.rerun()

if not rows:
    st.info("No open positions yet — add qty + entry above or attach them to any saved watchlist symbol.")
else:
    if st.button("Re-check watchlist alerts", key="pf_alerts_reset", help="Clears de-duplication so hits can notify again."):
        st.session_state.pop("_wl_alert_dedupe_portfolio_mtm", None)

    out: list[dict] = []
    alert_metrics: list[tuple[str, str, float, float | None]] = []
    for r in rows:
        raw = str(r.get("raw_ticker") or "")
        q = float(r.get("qty") or 0.0)
        ep = float(r.get("entry_price") or 0.0)
        px = None
        try:
            t = yf.Ticker(raw)
            fi = getattr(t, "fast_info", {}) or {}
            lp = fi.get("last_price") or fi.get("regular_market_price")
            if lp is not None:
                px = float(lp)
            else:
                h = t.history(period="5d")
                if not h.empty:
                    px = float(h["Close"].iloc[-1])
        except Exception:
            px = None
        mtm = (float(px) - ep) * q if px is not None else None
        disp = raw.replace(".NS", "").replace(".BO", "")
        out.append(
            {
                "Ticker": disp,
                "Qty": q,
                "Entry": ep,
                "Last": round(float(px), 4) if px is not None else None,
                "MTM": round(float(mtm), 2) if mtm is not None else None,
                "%": round((float(px) / ep - 1.0) * 100.0, 2) if px is not None and ep > 0 else None,
            }
        )

        if px is not None and _wl_row_has_alert_rules(r):
            rsi_val: float | None = None
            if _wl_row_needs_rsi(r):
                try:
                    hist = fetch_price_history(raw, "1d")
                    if hist is not None and not hist.empty and "Close" in hist.columns:
                        rv = compute_rsi(hist["Close"])
                        if rv is not None and not math.isnan(float(rv)):
                            rsi_val = float(rv)
                except Exception:
                    rsi_val = None
            alert_metrics.append((disp, raw, float(px), rsi_val))

    try:
        notify_watchlist_alerts_from_metrics(
            alert_metrics,
            "Portfolio (live quotes)",
            dedupe_session_key="portfolio_mtm",
        )
    except Exception:
        pass

    st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)
    st.caption(
        "Saved **alert rules** on each symbol (expand Watchlist above) are checked against **Last** "
        "and daily RSI‑14 when RSI thresholds are set. "
        "Repeated identical hits stay quiet until the hit set changes or you click **Re-check watchlist alerts**."
    )

st.markdown("---")
st.caption("⚠️ Educational only — quotes can lag Yahoo Finance; reconcile with your broker.")
