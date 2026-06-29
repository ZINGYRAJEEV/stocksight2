"""
Live RSI + Supertrend scanner — BTST (daily) and intraday modes.

Uses latest OHLCV from Yahoo / ICICI Breeze (same stack as BTST & Intraday screeners).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from intraday import INTRADAY_UNIVERSES_BY_MARKET, _build_context, resolve_universe
from rsi_supertrend_backtest import (
    BacktestConfig,
    BarSignalSnapshot,
    config_for_profile,
    evaluate_latest_bars,
    normalize_ohlcv,
)
from screener import compute_volume_ratio, fetch_price_history, get_sector_industry, get_stock_links, hist_series

ProgressCb = Callable[[int, int, str], None]

SIGNAL_LABELS = {
    "BUY": "🟢 Buy signal",
    "HOLD": "🟡 In trend",
    "EXIT": "🔴 Exit signal",
    "NONE": "— No setup",
}

BTST_ACTION = (
    "BTST: signal at today's close — enter before session end; "
    "exit tomorrow morning if ST bearish or RSI > 70 (honest: use next-open fills in backtest)."
)
INTRADAY_ACTION = (
    "Intraday: signal on latest bar — consider entry on next bar; "
    "trail stop with Supertrend line."
)


def _intraday_timing_rows(market: str) -> list[tuple[str, str, str]]:
    """(CEST range, market range, action) for intraday scan playbook."""
    try:
        from btst_screener import _fmt_time_range
    except ImportError:
        from .btst_screener import _fmt_time_range

    mkt = (market or "NSE").upper()
    if mkt == "US":
        specs = [
            (9, 45, 11, 0, "✅ **Best** — run scan · opening momentum & ST flips"),
            (11, 0, 13, 30, "🟡 **OK** — VWAP pullbacks · fewer signals"),
            (13, 30, 15, 0, "⏸ **Avoid** — mid-day chop · wait"),
            (15, 0, 15, 45, "🟡 **OK** — power hour · **square off before 3:55 PM ET**"),
            (15, 45, 16, 0, "🔴 **Too late** — no new intraday longs · use **BTST** tab after close"),
        ]
    else:
        specs = [
            (9, 30, 11, 0, "✅ **Best** — run scan · ORB breaks & momentum (Supertrend flips)"),
            (11, 0, 13, 0, "🟡 **OK** — trend pullbacks · trail ST line"),
            (13, 0, 14, 0, "⏸ **Avoid** — lunch lull · low-quality signals"),
            (14, 0, 15, 15, "🟡 **OK** — EOD momentum · **must exit before 3:20 PM IST**"),
            (15, 15, 15, 30, "🔴 **Too late** — no new intraday longs"),
            (15, 30, 16, 0, "🌙 **Switch to BTST** — session closed · use daily scan for overnight"),
        ]
    rows = []
    for sh, sm, eh, em, action in specs:
        mkt_range, cest_range = _fmt_time_range(sh, sm, eh, em, mkt)
        rows.append((cest_range, mkt_range, action))
    return rows


def intraday_scan_hint(market: str = "NSE") -> tuple[str, str, bool]:
    """
    Returns (phase, user_hint, run_recommended).
    phase: IDEAL | OK | WAIT | CLOSED | SWITCH_BTST
    """
    from intraday import market_session_window

    mkt = (market or "NSE").upper()
    sess = market_session_window(mkt)
    window = str(sess.get("window") or "")
    tip = str(sess.get("tip") or "")

    if mkt == "US":
        from zoneinfo import ZoneInfo
        from datetime import datetime

        now = datetime.now(tz=ZoneInfo("America/New_York"))
        mins = now.hour * 60 + now.minute
        if mins >= 15 * 60 + 45:
            return (
                "SWITCH_BTST",
                "US cash session ending — use **BTST mode** after 3:45 PM ET for overnight setups.",
                False,
            )
        if not sess.get("is_open"):
            return "CLOSED", f"US session closed. {tip}", False
        if "Opening hour" in window or "9:45" in window:
            return "IDEAL", f"**Best intraday window now** — {tip}", True
        if "Power hour" in window:
            return "OK", f"Power hour — scan OK but **exit before 3:55 PM ET**. {tip}", True
        if "Mid-day chop" in window or "ORB forming" in window or "Pre-market" in window:
            return "WAIT", f"Not ideal for new scans — {tip}", False
        if "Mid-morning" in window:
            return "OK", f"Secondary window — {tip}", True
        return "OK", tip, bool(sess.get("is_open"))

    # NSE
    from zoneinfo import ZoneInfo
    from datetime import datetime

    now = datetime.now(tz=ZoneInfo("Asia/Kolkata"))
    mins = now.hour * 60 + now.minute
    if mins >= 15 * 60 + 30:
        timing = None
        try:
            from btst_screener import btst_timing_schedule
        except ImportError:
            from .btst_screener import btst_timing_schedule
        timing = btst_timing_schedule("NSE")
        return (
            "SWITCH_BTST",
            f"NSE closed — switch to **BTST mode**. Best daily scan **{timing.scan_market}** "
            f"(**{timing.scan_cest}** your time).",
            False,
        )
    if mins >= 15 * 60 + 15:
        return (
            "WAIT",
            "Too late for **new** intraday longs — square existing trades or wait for tomorrow.",
            False,
        )
    if not sess.get("is_open"):
        return "CLOSED", tip, False
    if "Momentum window" in window or "9:30" in window:
        return "IDEAL", f"**Best intraday window** — run scan now. {tip}", True
    if "End-of-day" in window:
        return "OK", f"EOD window — scan OK; **square off before 3:20 PM IST**. {tip}", True
    if "Lunch lull" in window or "ORB forming" in window or "Pre-open" in window:
        return "WAIT", f"Low-quality window — {tip}", False
    if "VWAP pullback" in window:
        return "OK", f"Secondary window — {tip}", True
    return "OK", tip, bool(sess.get("is_open"))


def btst_scan_recommended(market: str = "NSE") -> tuple[str, str, bool]:
    """Wrap btst_session_hint with run_recommended flag."""
    try:
        from btst_screener import btst_session_hint, btst_timing_schedule
    except ImportError:
        from .btst_screener import btst_session_hint, btst_timing_schedule

    phase, hint = btst_session_hint(market)
    timing = btst_timing_schedule(market)
    recommended = phase in ("BTST_WINDOW", "ENTRY_WINDOW")
    if phase == "PRE_SCAN":
        hint = (
            f"Too early for BTST — today's daily bar is still forming. "
            f"Come back **{timing.scan_market}** (**{timing.scan_cest}**)."
        )
    elif phase == "POST_MARKET":
        hint = (
            f"Session closed — you can still review signals, but ideal scan was "
            f"**{timing.scan_market}** (**{timing.scan_cest}**). {hint}"
        )
    return phase, hint, recommended


@dataclass
class RsiStScanFilters:
    mode: str = "btst"  # btst | intraday
    market: str = "NSE"
    universe: str = "Nifty 100 (medium)"
    data_source: str = "auto"
    profile: str = "honest_st"  # honest_st | rsi_combo
    max_tickers: int = 200
    min_price: float = 50.0
    max_price: float = 5000.0
    show: str = "actionable"  # actionable | buy_only | all
    st_period: int = 10
    st_multiplier: float = 3.0
    btst_green_only: bool = True
    btst_above_prev: bool = True
    min_vol_ratio: float = 0.0
    bar_delay_sec: float = 0.06
    ticker_override: Optional[list[str]] = None


@dataclass
class RsiStScanResult:
    ticker: str
    raw_ticker: str
    sector: str
    grade: str
    signal: str
    signal_label: str
    price: float
    pct_vs_prev: float
    rsi: float
    supertrend: float
    st_direction: str
    vol_ratio: float
    bar_type: str
    action: str
    notes: str
    links: dict = field(default_factory=dict)


@dataclass
class RsiStScanStats:
    universe: str
    mode: str
    market: str
    data_source: str
    tickers_scanned: int = 0
    grade_a: int = 0
    grade_b: int = 0
    grade_c: int = 0
    no_data: int = 0
    scan_elapsed_sec: float = 0.0


def universe_options(market: str = "NSE") -> list[str]:
    mkt = (market or "NSE").upper()
    dct = INTRADAY_UNIVERSES_BY_MARKET.get(mkt, {})
    preferred_nse = (
        "Nifty 50 (fast)",
        "Nifty 100 (medium)",
        "Nifty 500 (broad, slow)",
        "Nifty 50 (NSE)",
        "Nifty 500 (NSE)",
    )
    preferred_us = ("S&P 500 (broad, slow)", "Liquid US shortlist (~35)")
    preferred = preferred_us if mkt == "US" else preferred_nse
    opts = list(dct.keys())
    ordered = [u for u in preferred if u in opts]
    ordered += [u for u in opts if u not in ordered]
    return ordered


def _fetch_daily_hist(raw: str, data_source: str) -> Optional[pd.DataFrame]:
    if (data_source or "auto") == "yahoo":
        return fetch_price_history(raw, "1d")
    hist = fetch_price_history(raw, "1d")
    if raw.endswith((".NS", ".BO")):
        try:
            from breeze_data import breeze_configured, fetch_breeze_price_history

            if data_source in ("auto", "breeze") and breeze_configured():
                bdf = fetch_breeze_price_history(raw, "1d")
                if bdf is not None and not bdf.empty:
                    return bdf
        except Exception:
            pass
    return hist


def _cfg_from_filters(flt: RsiStScanFilters) -> BacktestConfig:
    return config_for_profile(
        flt.profile,
        st_period=flt.st_period,
        st_multiplier=flt.st_multiplier,
    )


def _passes_show_filter(grade: str, signal: str, flt: RsiStScanFilters) -> bool:
    if flt.show == "buy_only":
        return signal == "BUY"
    if flt.show == "actionable":
        return grade in ("A", "B", "C")
    return True


def analyze_rsi_st(
    raw: str,
    flt: RsiStScanFilters,
) -> Optional[RsiStScanResult]:
    raw = (raw or "").strip()
    if not raw:
        return None

    cfg = _cfg_from_filters(flt)
    bar_type = "Daily" if flt.mode == "btst" else "Intraday"
    vol_ratio = 0.0

    try:
        if flt.mode == "btst":
            hist = _fetch_daily_hist(raw, flt.data_source)
            norm = normalize_ohlcv(hist) if hist is not None else None
            if norm is None or len(norm) < 25:
                return None

            vols = hist_series(norm, "Volume").astype(float)
            vol_ratio = float(compute_volume_ratio(vols) or 0.0)
            if vol_ratio < flt.min_vol_ratio:
                return None

            price = float(hist_series(norm, "Close").iloc[-1])
            if price < flt.min_price or price > flt.max_price:
                return None

            if flt.btst_green_only:
                o = float(hist_series(norm, "Open").iloc[-1])
                if price <= o:
                    return None

            snap = evaluate_latest_bars(norm, cfg)
            if snap is None:
                return None

            if flt.btst_above_prev and snap.pct_vs_prev <= 0 and snap.signal == "BUY":
                extra = list(snap.notes) + ["Close ≤ prev (BTST filter)"]
                snap = BarSignalSnapshot(
                    signal="HOLD",
                    grade="B",
                    st_direction=snap.st_direction,
                    st_bullish=snap.st_bullish,
                    st_flip_bull=snap.st_flip_bull,
                    st_flip_bear=snap.st_flip_bear,
                    rsi=snap.rsi,
                    rsi_cross_30=snap.rsi_cross_30,
                    rsi_cross_70=snap.rsi_cross_70,
                    supertrend=snap.supertrend,
                    price=snap.price,
                    pct_vs_prev=snap.pct_vs_prev,
                    notes=extra,
                )

            pct_vs_prev = snap.pct_vs_prev
            action = BTST_ACTION if snap.signal == "BUY" else (
                "Hold BTST position — watch ST / RSI for tomorrow's exit."
                if snap.signal == "HOLD" else
                "Exit BTST / avoid new long — bearish trigger fired."
                if snap.signal == "EXIT" else "No BTST setup on latest daily bar."
            )
        else:
            ctx = _build_context(raw, data_source=flt.data_source)
            if not ctx:
                return None

            session = ctx.get("session") or ctx.get("bars")
            if session is None or getattr(session, "empty", True) or len(session) < 25:
                return None

            norm = normalize_ohlcv(session)
            if norm is None:
                return None

            price = float(ctx.get("price") or hist_series(norm, "Close").iloc[-1])
            if price < flt.min_price or price > flt.max_price:
                return None

            vol_ratio = float(ctx.get("vol_ratio") or 0.0)
            if vol_ratio < flt.min_vol_ratio:
                return None

            snap = evaluate_latest_bars(norm, cfg)
            if snap is None:
                return None

            pct_vs_prev = float(ctx.get("pct_change") or snap.pct_vs_prev)
            interval = str(ctx.get("bar_interval") or "5m")
            bar_type = f"Session {interval}"
            action = INTRADAY_ACTION if snap.signal == "BUY" else (
                f"In intraday uptrend ({interval}) — trail Supertrend."
                if snap.signal == "HOLD" else
                "Intraday exit / flatten — ST bearish or RSI > 70."
                if snap.signal == "EXIT" else f"No intraday setup on {interval} bars."
            )

        if not _passes_show_filter(snap.grade, snap.signal, flt):
            return None

        import yfinance as yf

        sector, _ = get_sector_industry(yf.Ticker(raw))
        disp = raw.replace(".NS", "").replace(".BO", "")

        return RsiStScanResult(
            ticker=disp,
            raw_ticker=raw,
            sector=sector or "—",
            grade=snap.grade,
            signal=snap.signal,
            signal_label=SIGNAL_LABELS.get(snap.signal, snap.signal),
            price=round(price, 2),
            pct_vs_prev=round(pct_vs_prev, 2),
            rsi=snap.rsi,
            supertrend=snap.supertrend,
            st_direction=snap.st_direction,
            vol_ratio=round(vol_ratio, 2),
            bar_type=bar_type,
            action=action,
            notes=" · ".join(snap.notes) if snap.notes else "—",
            links=get_stock_links(raw),
        )
    except Exception:
        return None


def scan_rsi_supertrend(
    flt: RsiStScanFilters,
    *,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[RsiStScanResult], RsiStScanStats]:
    tickers = (
        list(flt.ticker_override)[: flt.max_tickers]
        if flt.ticker_override
        else resolve_universe(flt.universe, market=flt.market)[: flt.max_tickers]
    )
    uni_label = (
        f"Historic shortlist ({len(tickers)})"
        if flt.ticker_override
        else flt.universe
    )
    stats = RsiStScanStats(
        universe=uni_label,
        mode=flt.mode,
        market=flt.market,
        data_source=flt.data_source,
    )
    results: list[RsiStScanResult] = []
    t0 = time.time()
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        r = analyze_rsi_st(raw, flt)
        if r is None:
            stats.no_data += 1
            continue
        if r.grade == "A":
            stats.grade_a += 1
        elif r.grade == "B":
            stats.grade_b += 1
        elif r.grade == "C":
            stats.grade_c += 1
        results.append(r)
        if flt.bar_delay_sec > 0:
            time.sleep(flt.bar_delay_sec)

    grade_rank = {"A": 0, "B": 1, "C": 2}
    signal_rank = {"BUY": 0, "EXIT": 1, "HOLD": 2, "NONE": 3}
    results.sort(
        key=lambda x: (
            grade_rank.get(x.grade, 9),
            signal_rank.get(x.signal, 9),
            -abs(x.pct_vs_prev),
            -x.vol_ratio,
        )
    )
    stats.scan_elapsed_sec = round(time.time() - t0, 1)
    return results, stats
