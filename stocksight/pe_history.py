"""
Historical P/E series — Screener.in Mar FY EPS + Yahoo price at FY end.

P/E = adjusted close on (or before) 31 Mar FY / EPS in Rs from Screener P&L.
Educational only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from screener_in_data import fetch_screener_eps_history, fetch_screener_value_profile
except ImportError:
    from stocksight.screener_in_data import fetch_screener_eps_history, fetch_screener_value_profile


@dataclass
class PeHistoryPoint:
    fy_year: int
    label: str
    eps: float
    price: Optional[float]
    pe: Optional[float]
    kind: str = "fy"  # fy | current


def _normalize_hist_index(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    out = hist.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out.index = idx
    return out


def _price_at_fy_end(hist: pd.DataFrame, fy_year: int) -> Optional[float]:
    """Last adjusted close on or before 31 Mar for the given FY end year."""
    h = _normalize_hist_index(hist)
    if h.empty or "Close" not in h.columns:
        return None
    target = pd.Timestamp(fy_year, 3, 31)
    subset = h[h.index <= target]
    if subset.empty:
        subset = h[h.index >= target].head(1)
    if subset.empty:
        return None
    try:
        return round(float(subset["Close"].iloc[-1]), 2)
    except (TypeError, ValueError, IndexError):
        return None


def fetch_long_price_history(raw_ticker: str, *, years: int = 12) -> pd.DataFrame:
    """Daily OHLCV — enough bars for Mar FY P/E backfill."""
    empty = pd.DataFrame()
    if not raw_ticker:
        return empty
    sym = raw_ticker if raw_ticker.endswith((".NS", ".BO")) else f"{raw_ticker}.NS"
    try:
        import yfinance as yf
    except ImportError:
        return empty
    try:
        end = datetime.today()
        start = end - timedelta(days=int(years * 365.25) + 60)
        df = yf.Ticker(sym).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
        return df if df is not None and not df.empty else empty
    except Exception:
        return empty


def build_pe_history(
    display_ticker: str,
    raw_ticker: str = "",
    *,
    html: str = "",
) -> tuple[list[PeHistoryPoint], dict[str, Any]]:
    """
    Build Mar FY P/E points plus a current (LTP / latest EPS) point.

    Returns (points, meta) where meta has median_pe, current_pe, source notes, etc.
    """
    disp = display_ticker.replace(".NS", "").replace(".BO", "").strip().upper()
    raw = raw_ticker or f"{disp}.NS"
    if not raw.endswith((".NS", ".BO")):
        raw = f"{disp}.NS"

    eps_series = fetch_screener_eps_history(disp, html=html)
    profile = fetch_screener_value_profile(disp, html=html) if html else fetch_screener_value_profile(disp)
    hist = fetch_long_price_history(raw)

    points: list[PeHistoryPoint] = []
    for fy, lbl, eps in eps_series:
        if eps <= 0:
            continue
        px = _price_at_fy_end(hist, fy)
        pe = round(px / eps, 2) if px is not None and px > 0 else None
        if pe is not None and pe > 250:
            pe = round(pe, 1)
        points.append(
            PeHistoryPoint(
                fy_year=fy,
                label=lbl,
                eps=eps,
                price=px,
                pe=pe,
                kind="fy",
            )
        )

    cur_price = profile.get("price")
    cur_eps = profile.get("trailing_eps")
    cur_pe = profile.get("pe")
    if cur_price is None and not hist.empty:
        try:
            cur_price = round(float(hist["Close"].iloc[-1]), 2)
        except (TypeError, ValueError, IndexError):
            cur_price = None
    if cur_eps and float(cur_eps) > 0 and cur_price:
        calc_pe = round(float(cur_price) / float(cur_eps), 2)
        if cur_pe is None:
            cur_pe = calc_pe
        fy_cur = profile.get("eps_fy") or (points[-1].fy_year if points else datetime.today().year)
        points.append(
            PeHistoryPoint(
                fy_year=int(fy_cur),
                label="Current (TTM)",
                eps=float(cur_eps),
                price=float(cur_price),
                pe=float(cur_pe) if cur_pe is not None else calc_pe,
                kind="current",
            )
        )

    pe_vals = [p.pe for p in points if p.pe is not None and p.pe > 0]
    meta: dict[str, Any] = {
        "ticker": disp,
        "raw_ticker": raw,
        "screener_url": profile.get("screener_url", ""),
        "n_fy_points": sum(1 for p in points if p.kind == "fy"),
        "current_pe": cur_pe,
        "current_eps": cur_eps,
        "current_price": cur_price,
        "median_pe": round(float(np.median(pe_vals)), 2) if pe_vals else None,
        "min_pe": round(min(pe_vals), 2) if pe_vals else None,
        "max_pe": round(max(pe_vals), 2) if pe_vals else None,
        "eps_source": "Screener.in consolidated P&L (EPS in Rs, Mar FY)",
        "price_source": "Yahoo Finance adjusted close at/near 31 Mar FY",
    }
    if points and meta["current_pe"] and meta["median_pe"]:
        meta["pct_vs_median"] = round(
            (float(meta["current_pe"]) / float(meta["median_pe"]) - 1.0) * 100.0,
            1,
        )
    return points, meta


def pe_history_to_dataframe(points: list[PeHistoryPoint]) -> pd.DataFrame:
    if not points:
        return pd.DataFrame()
    rows = []
    for p in points:
        rows.append(
            {
                "Period": p.label,
                "FY": p.fy_year,
                "EPS ₹": p.eps,
                "Price ₹": p.price,
                "P/E": p.pe,
                "Type": "Current" if p.kind == "current" else "Mar FY",
            }
        )
    return pd.DataFrame(rows)
