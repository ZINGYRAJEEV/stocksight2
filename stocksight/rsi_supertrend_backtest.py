"""
RSI + Supertrend strategy backtest — broken vs structurally honest modes.

Educational audit tool: exposes lookahead bias, weak filters, and stepwise fixes.
Not investment advice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

try:
    from screener import (
        benchmark_ticker_for,
        compute_volume_ratio,
        fetch_price_history,
        get_sector_industry,
        hist_series,
    )
except ImportError:
    from .screener import (
        benchmark_ticker_for,
        compute_volume_ratio,
        fetch_price_history,
        get_sector_industry,
        hist_series,
    )

META = {
    "id": "rsi_supertrend_audit",
    "title": "RSI + Supertrend Screener",
    "emoji": "🔬",
    "nav_title": "RSI + Supertrend",
    "audience": (
        "Swing & intraday traders using **Supertrend + RSI** — live **BTST** and **intraday** scans "
        "across Nifty universes, plus honest backtest audit."
    ),
    "purpose": (
        "Scan latest bars for buy/hold/exit signals (Breeze or Yahoo). "
        "BTST = daily EOD setup; Intraday = session 5m/15m bars. Includes stepwise backtest audit."
    ),
}

DEFAULT_TICKERS = [
    "M&M.NS",
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "TATASTEEL.NS",
    "WIPRO.NS",
    "SBIN.NS",
]


@dataclass
class BacktestConfig:
    next_bar_execution: bool = False
    commission_pct: float = 0.0  # per leg (fraction, e.g. 0.001 = 0.1%)
    slippage_pct: float = 0.0  # adverse fill vs quoted price
    position_pct: float = 1.0  # fraction of equity deployed per entry
    cooldown_days: int = 0
    use_rsi: bool = True
    rsi_entry_max: float = 70.0
    rsi_oversold: float = 30.0
    rsi_exit: float = 70.0
    st_period: int = 10
    st_multiplier: float = 3.0
    initial_capital: float = 100_000.0
    sharpe_active_days_only: bool = False
    risk_free_rate_annual: float = 0.06


@dataclass
class TradeRecord:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_inr: float
    bars_held: int


@dataclass
class BacktestResult:
    mode_id: str
    mode_label: str
    config: BacktestConfig
    total_return_pct: float
    win_rate_pct: float
    max_drawdown_pct: float
    sharpe: float
    sharpe_calendar: float
    num_trades: int
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    data_last_date: str = ""
    open_at_end: bool = False
    open_entry_date: str = ""


# Cumulative step presets (each adds fixes on top of the prior step).
STEP_MODES: list[tuple[str, str, dict[str, Any]]] = [
    (
        "broken",
        "Broken (same-bar close, 100% size, RSI rules)",
        {},
    ),
    (
        "step_execution",
        "+ Next-day open execution",
        {"next_bar_execution": True},
    ),
    (
        "step_costs",
        "+ Costs & slippage (0.1% / leg, 0.05% slip)",
        {"commission_pct": 0.001, "slippage_pct": 0.0005},
    ),
    (
        "step_sizing",
        "+ 10% position sizing",
        {"position_pct": 0.10},
    ),
    (
        "step_cooldown",
        "+ 3-day re-entry cooldown",
        {"cooldown_days": 3},
    ),
    (
        "fixed",
        "Fixed (pure Supertrend + honest Sharpe on active days)",
        {"use_rsi": False, "sharpe_active_days_only": True},
    ),
]


def rsi_series(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """Return (supertrend line, direction) where direction 1 = bullish, -1 = bearish."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    hl2 = (high + low) / 2
    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr

    n = len(close)
    final_ub = np.zeros(n, dtype=float)
    final_lb = np.zeros(n, dtype=float)
    direction = np.zeros(n, dtype=int)
    st_line = np.zeros(n, dtype=float)

    direction[0] = 1
    final_ub[0] = basic_ub.iloc[0]
    final_lb[0] = basic_lb.iloc[0]
    st_line[0] = final_lb[0]

    for i in range(1, n):
        if basic_ub.iloc[i] < final_ub[i - 1] or close.iloc[i - 1] > final_ub[i - 1]:
            final_ub[i] = basic_ub.iloc[i]
        else:
            final_ub[i] = final_ub[i - 1]

        if basic_lb.iloc[i] > final_lb[i - 1] or close.iloc[i - 1] < final_lb[i - 1]:
            final_lb[i] = basic_lb.iloc[i]
        else:
            final_lb[i] = final_lb[i - 1]

        if direction[i - 1] == -1 and close.iloc[i] > final_ub[i]:
            direction[i] = 1
        elif direction[i - 1] == 1 and close.iloc[i] < final_lb[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        st_line[i] = final_lb[i] if direction[i] == 1 else final_ub[i]

    idx = close.index
    return (
        pd.Series(st_line, index=idx),
        pd.Series(direction, index=idx),
    )


def _build_config(mode_id: str) -> tuple[str, BacktestConfig]:
    cfg = BacktestConfig()
    label = mode_id
    for mid, lbl, patch in STEP_MODES:
        for k, v in patch.items():
            setattr(cfg, k, v)
        if mid == mode_id:
            label = lbl
            break
    return label, cfg


def prepare_ohlcv(
    raw_ticker: str,
    years: float = 2.0,
    *,
    data_source: str = "auto",
) -> Optional[pd.DataFrame]:
    df = fetch_backtest_ohlcv(raw_ticker, years=years, data_source=data_source)
    if df is None or df.empty:
        return None
    min_bars = int(years * 252)
    if len(df) > min_bars:
        df = df.iloc[-min_bars:]
    return df


def fetch_backtest_ohlcv(
    raw_ticker: str,
    *,
    years: float = 2.0,
    data_source: str = "auto",
) -> Optional[pd.DataFrame]:
    """
    Daily OHLCV for backtests — supports multi-year windows.

    ``data_source``: ``auto`` | ``yahoo`` | ``breeze``
    (Screener.in / TradingView do not expose bulk OHLCV APIs — use Yahoo or Breeze.)
    """
    raw = (raw_ticker or "").strip()
    if not raw:
        return None
    years_f = max(1.0, min(float(years), 10.0))
    lookback_days = int(years_f * 365) + 45
    src = (data_source or "auto").strip().lower()

    def _yahoo_hist() -> pd.DataFrame:
        try:
            import yfinance as yf
            from datetime import datetime, timedelta

            end = datetime.today()
            start = end - timedelta(days=lookback_days)
            stk = yf.Ticker(raw)
            hist = stk.history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=True,
            )
            if hist is None or hist.empty:
                period = f"{min(int(years_f) + 1, 10)}y"
                hist = stk.history(period=period, interval="1d", auto_adjust=True)
            return hist if hist is not None else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    def _breeze_hist() -> pd.DataFrame:
        if not raw.upper().endswith((".NS", ".BO")):
            return pd.DataFrame()
        try:
            from breeze_data import breeze_configured, fetch_breeze_price_history

            if not breeze_configured():
                return pd.DataFrame()
            bdf = fetch_breeze_price_history(raw, "1d", lookback_days=lookback_days)
            return bdf if bdf is not None else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    hist = pd.DataFrame()
    if src == "yahoo":
        hist = _yahoo_hist()
    elif src == "breeze":
        hist = _breeze_hist()
        if hist.empty:
            hist = _yahoo_hist()
    else:
        if raw.upper().endswith((".NS", ".BO")):
            hist = _breeze_hist()
        if hist.empty:
            hist = _yahoo_hist()

    if hist is None or hist.empty:
        return None
    return normalize_ohlcv(hist)


def _entry_signal(
    i: int,
    direction: np.ndarray,
    rsi: np.ndarray,
    cfg: BacktestConfig,
) -> bool:
    if i < 1:
        return False
    st_bull = direction[i] == 1
    st_flip_bull = direction[i] == 1 and direction[i - 1] == -1
    if not cfg.use_rsi:
        return bool(st_flip_bull)
    rsi_ok = rsi[i] < cfg.rsi_entry_max
    rsi_cross_30 = rsi[i - 1] < cfg.rsi_oversold and rsi[i] >= cfg.rsi_oversold
    return bool((st_flip_bull and rsi_ok) or (rsi_cross_30 and st_bull))


def _exit_signal(
    i: int,
    direction: np.ndarray,
    rsi: np.ndarray,
    cfg: BacktestConfig,
) -> bool:
    if i < 1:
        return False
    st_flip_bear = direction[i] == -1 and direction[i - 1] == 1
    if not cfg.use_rsi:
        return bool(st_flip_bear)
    rsi_cross_70 = rsi[i - 1] < cfg.rsi_exit and rsi[i] >= cfg.rsi_exit
    return bool(rsi_cross_70 or st_flip_bear)


def _apply_fill_price(price: float, *, side: str, cfg: BacktestConfig) -> float:
    slip = cfg.slippage_pct
    if side == "buy":
        return price * (1 + slip)
    return price * (1 - slip)


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig, *, mode_id: str = "", mode_label: str = "") -> BacktestResult:
    closes = hist_series(df, "Close").astype(float)
    opens = hist_series(df, "Open").astype(float)
    highs = hist_series(df, "High").astype(float)
    lows = hist_series(df, "Low").astype(float)

    _, direction_s = compute_supertrend(
        highs, lows, closes, period=cfg.st_period, multiplier=cfg.st_multiplier,
    )
    rsi = rsi_series(closes).to_numpy(dtype=float)
    direction = direction_s.to_numpy(dtype=int)
    dates = pd.to_datetime(df.index)

    cash = float(cfg.initial_capital)
    shares = 0.0
    in_position = False
    entry_price = 0.0
    entry_idx = -1
    cooldown_until = -1
    pending_entry = False
    pending_exit = False
    trades: list[TradeRecord] = []
    equity_rows: list[dict[str, Any]] = []

    last_i = len(df) - (2 if cfg.next_bar_execution else 1)

    for i in range(1, last_i + 1):
        # Honest mode: execute yesterday's signals at today's open.
        if cfg.next_bar_execution:
            if pending_exit and in_position:
                raw_px = float(opens.iloc[i])
                fill = _apply_fill_price(raw_px, side="sell", cfg=cfg)
                proceeds = shares * fill * (1 - cfg.commission_pct)
                pnl_inr = proceeds - (shares * entry_price)
                pnl_pct = (fill / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0
                trades.append(
                    TradeRecord(
                        entry_date=str(dates[entry_idx].date()),
                        exit_date=str(dates[i].date()),
                        entry_price=round(entry_price, 2),
                        exit_price=round(fill, 2),
                        pnl_pct=round(pnl_pct, 2),
                        pnl_inr=round(pnl_inr, 2),
                        bars_held=i - entry_idx,
                    )
                )
                cash += proceeds
                shares = 0.0
                in_position = False
                cooldown_until = i + cfg.cooldown_days
                pending_exit = False

            if pending_entry and not in_position and i > cooldown_until:
                equity_now = cash
                max_deploy = cash / (1 + cfg.commission_pct) if cfg.commission_pct > 0 else cash
                deploy = min(equity_now * cfg.position_pct, max_deploy)
                raw_px = float(opens.iloc[i])
                fill = _apply_fill_price(raw_px, side="buy", cfg=cfg)
                cost = deploy * (1 + cfg.commission_pct)
                if deploy > 0 and fill > 0:
                    shares = deploy / fill
                    cash -= cost
                    entry_price = fill
                    entry_idx = i
                    in_position = True
                pending_entry = False

        # Signals known at close of bar i.
        want_exit = in_position and _exit_signal(i, direction, rsi, cfg)
        want_entry = (
            not in_position
            and i > cooldown_until
            and _entry_signal(i, direction, rsi, cfg)
        )

        if cfg.next_bar_execution:
            pending_exit = want_exit
            pending_entry = want_entry and not want_exit
        else:
            if want_exit and in_position:
                fill = float(closes.iloc[i])
                proceeds = shares * fill * (1 - cfg.commission_pct)
                pnl_inr = proceeds - (shares * entry_price)
                pnl_pct = (fill / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0
                trades.append(
                    TradeRecord(
                        entry_date=str(dates[entry_idx].date()),
                        exit_date=str(dates[i].date()),
                        entry_price=round(entry_price, 2),
                        exit_price=round(fill, 2),
                        pnl_pct=round(pnl_pct, 2),
                        pnl_inr=round(pnl_inr, 2),
                        bars_held=i - entry_idx,
                    )
                )
                cash += proceeds
                shares = 0.0
                in_position = False
                cooldown_until = i + cfg.cooldown_days
            elif want_entry and not in_position:
                equity_now = cash
                max_deploy = cash / (1 + cfg.commission_pct) if cfg.commission_pct > 0 else cash
                deploy = min(equity_now * cfg.position_pct, max_deploy)
                fill = float(closes.iloc[i])
                cost = deploy * (1 + cfg.commission_pct)
                if deploy > 0 and fill > 0:
                    shares = deploy / fill
                    cash -= cost
                    entry_price = fill
                    entry_idx = i
                    in_position = True

        mark = float(closes.iloc[i])
        equity = cash + shares * mark
        equity_rows.append(
            {
                "date": dates[i],
                "equity": equity,
                "in_position": in_position,
                "close": mark,
            }
        )

    # Mark open position at last bar (no forced exit).
    if in_position and equity_rows:
        mark = float(closes.iloc[last_i])
        equity_rows[-1]["equity"] = cash + shares * mark

    eq_df = pd.DataFrame(equity_rows)
    if eq_df.empty:
        return BacktestResult(
            mode_id=mode_id,
            mode_label=mode_label,
            config=cfg,
            total_return_pct=0.0,
            win_rate_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe=0.0,
            sharpe_calendar=0.0,
            num_trades=0,
        )

    eq_df["daily_ret"] = eq_df["equity"].pct_change().fillna(0.0)
    total_return = (eq_df["equity"].iloc[-1] / cfg.initial_capital - 1.0) * 100.0

    peak = eq_df["equity"].cummax()
    dd = (eq_df["equity"] - peak) / peak.replace(0, np.nan)
    max_dd = float(dd.min() * 100.0) if len(dd) else 0.0

    rf_daily = cfg.risk_free_rate_annual / 252.0
    cal_excess = eq_df["daily_ret"] - rf_daily
    sharpe_cal = _sharpe_from_returns(cal_excess)

    if cfg.sharpe_active_days_only:
        active = eq_df[eq_df["in_position"]].copy()
        active_excess = active["daily_ret"] - rf_daily
        sharpe_main = _sharpe_from_returns(active_excess)
    else:
        sharpe_main = sharpe_cal

    wins = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = (wins / len(trades) * 100.0) if trades else 0.0

    data_last_date = str(dates[min(last_i, len(dates) - 1)].date())
    open_entry_date = str(dates[entry_idx].date()) if in_position and entry_idx >= 0 else ""

    return BacktestResult(
        mode_id=mode_id,
        mode_label=mode_label,
        config=cfg,
        total_return_pct=round(total_return, 2),
        win_rate_pct=round(win_rate, 1),
        max_drawdown_pct=round(max_dd, 2),
        sharpe=round(sharpe_main, 4),
        sharpe_calendar=round(sharpe_cal, 4),
        num_trades=len(trades),
        trades=trades,
        equity_curve=eq_df,
        data_last_date=data_last_date,
        open_at_end=in_position,
        open_entry_date=open_entry_date,
    )


def _sharpe_from_returns(excess: pd.Series) -> float:
    if excess is None or len(excess) < 2:
        return 0.0
    std = float(excess.std())
    if std <= 1e-12:
        return 0.0
    return float(excess.mean() / std * np.sqrt(252))


def run_mode(df: pd.DataFrame, mode_id: str) -> BacktestResult:
    label, cfg = _build_config(mode_id)
    return run_backtest(df, cfg, mode_id=mode_id, mode_label=label)


def run_all_steps(raw_ticker: str, years: float = 2.0) -> tuple[Optional[pd.DataFrame], list[BacktestResult]]:
    df = prepare_ohlcv(raw_ticker, years=years)
    if df is None:
        return None, []
    results = [run_mode(df, mid) for mid, _, _ in STEP_MODES]
    return df, results


def results_comparison_df(results: list[BacktestResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append(
            {
                "Mode": r.mode_label,
                "Total return %": r.total_return_pct,
                "Win rate %": r.win_rate_pct,
                "Max drawdown %": r.max_drawdown_pct,
                "Sharpe": r.sharpe,
                "Sharpe (calendar)": r.sharpe_calendar,
                "Trades": r.num_trades,
            }
        )
    return pd.DataFrame(rows)


def rsi_below_70_pct(df: pd.DataFrame) -> float:
    """Share of bars with RSI < 70 — illustrates weak filter."""
    closes = hist_series(df, "Close").astype(float)
    rsi = rsi_series(closes)
    valid = rsi.dropna()
    if valid.empty:
        return 0.0
    return round(float((valid < 70).mean() * 100.0), 1)


def normalize_ohlcv(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    out = df.copy()
    out.columns = [str(c).title() for c in out.columns]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return out if not out.empty else None


@dataclass
class BarSignalSnapshot:
    signal: str  # BUY | HOLD | EXIT | NONE
    grade: str  # A | B | C | —
    st_direction: str
    st_bullish: bool
    st_flip_bull: bool
    st_flip_bear: bool
    rsi: float
    rsi_cross_30: bool
    rsi_cross_70: bool
    supertrend: float
    price: float
    pct_vs_prev: float
    notes: list[str] = field(default_factory=list)


def evaluate_latest_bars(df: pd.DataFrame, cfg: BacktestConfig) -> Optional[BarSignalSnapshot]:
    """Classify the latest bar for live BTST / intraday scanning."""
    norm = normalize_ohlcv(df)
    if norm is None or len(norm) < max(cfg.st_period + 5, 20):
        return None

    closes = hist_series(norm, "Close").astype(float)
    highs = hist_series(norm, "High").astype(float)
    lows = hist_series(norm, "Low").astype(float)

    st_line, direction_s = compute_supertrend(
        highs, lows, closes, period=cfg.st_period, multiplier=cfg.st_multiplier,
    )
    rsi = rsi_series(closes).to_numpy(dtype=float)
    direction = direction_s.to_numpy(dtype=int)
    i = len(norm) - 1
    if i < 1 or np.isnan(rsi[i]):
        return None

    price = float(closes.iloc[i])
    prev_close = float(closes.iloc[i - 1])
    pct_vs_prev = round((price / prev_close - 1.0) * 100.0, 2) if prev_close > 0 else 0.0

    st_bull = direction[i] == 1
    flip_bull = direction[i] == 1 and direction[i - 1] == -1
    flip_bear = direction[i] == -1 and direction[i - 1] == 1
    entry = _entry_signal(i, direction, rsi, cfg)
    exit_sig = _exit_signal(i, direction, rsi, cfg)
    cross_30 = rsi[i - 1] < cfg.rsi_oversold and rsi[i] >= cfg.rsi_oversold
    cross_70 = rsi[i - 1] < cfg.rsi_exit and rsi[i] >= cfg.rsi_exit

    notes: list[str] = []
    if flip_bull:
        notes.append("ST flipped bullish")
    if cross_30:
        notes.append("RSI crossed above 30")
    if cross_70:
        notes.append("RSI crossed above 70")
    if flip_bear:
        notes.append("ST flipped bearish")

    signal = "NONE"
    grade = "—"
    if exit_sig:
        signal = "EXIT"
        grade = "C"
    elif entry:
        signal = "BUY"
        grade = "A"
    elif st_bull:
        signal = "HOLD"
        grade = "B"

    return BarSignalSnapshot(
        signal=signal,
        grade=grade,
        st_direction="Bull" if st_bull else "Bear",
        st_bullish=st_bull,
        st_flip_bull=bool(flip_bull),
        st_flip_bear=bool(flip_bear),
        rsi=round(float(rsi[i]), 1),
        rsi_cross_30=bool(cross_30),
        rsi_cross_70=bool(cross_70),
        supertrend=round(float(st_line.iloc[i]), 2),
        price=round(price, 2),
        pct_vs_prev=pct_vs_prev,
        notes=notes,
    )


def config_for_profile(profile: str, **kwargs: Any) -> BacktestConfig:
    """honest_st = pure Supertrend; rsi_combo = tutorial RSI + ST rules."""
    cfg = BacktestConfig()
    if profile == "honest_st":
        cfg.use_rsi = False
    else:
        cfg.use_rsi = True
    for k, v in kwargs.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg


BACKTEST_DATA_SOURCES: list[tuple[str, str]] = [
    ("auto", "Auto — Breeze (NSE) if connected, else Yahoo"),
    ("breeze", "ICICI Breeze — NSE/BSE daily OHLCV (best for India)"),
    ("yahoo", "Yahoo Finance — global fallback"),
]


def backtest_data_source_note(data_source: str, market: str = "NSE") -> str:
    src = (data_source or "auto").lower()
    mkt = (market or "NSE").upper()
    lines = []
    if src in ("auto", "breeze") and mkt == "NSE":
        try:
            from breeze_data import breeze_configured, breeze_status_message

            if breeze_configured():
                lines.append(f"OHLCV: **ICICI Breeze** · {breeze_status_message()}")
            else:
                lines.append(
                    "OHLCV: **Yahoo** (Breeze not configured — add `[breeze]` in `.streamlit/secrets.toml`)"
                )
        except ImportError:
            lines.append("OHLCV: **Yahoo** (`breeze-connect` not installed)")
    else:
        lines.append("OHLCV: **Yahoo Finance**")
    lines.append(
        "**Screener.in** = fundamentals (P&L, ratios) — not price history. "
        "**TradingView** = charts/sentiment links — no bulk OHLCV API in StockSight."
    )
    return " · ".join(lines)

UNIVERSE_AUDIT_MODES: list[tuple[str, str]] = [
    (
        "universe_rank",
        "Universe rank — honest fills + faster ST (7/2.5) · recommended",
    ),
    ("fixed", "Fixed — honest Supertrend (few trades, strict)"),
    ("step_cooldown", "RSI + ST — all honesty fixes (no pure-ST switch)"),
    ("step_execution", "RSI + ST — next-open execution only"),
    ("broken", "Broken tutorial (for contrast only)"),
]


@dataclass
class UniverseBacktestRow:
    raw_ticker: str
    display_ticker: str
    total_return_pct: float
    win_rate_pct: float
    max_drawdown_pct: float
    sharpe: float
    num_trades: int
    score: float
    data_bars: int = 0
    rank: int = 0
    sector: str = ""
    last_entry: str = ""
    last_exit: str = ""
    data_through: str = ""
    position_status: str = ""
    open_entry: str = ""
    trade_summary: str = ""
    vol_ratio: float = float("nan")
    avg_overnight_gap_pct: float = float("nan")
    alpha_pct: float = float("nan")
    benchmark: str = ""
    wf_train_return_pct: float = float("nan")
    wf_test_return_pct: float = float("nan")
    position_pct: float = 1.0
    portfolio_max_dd_pct: float = float("nan")
    confidence: float = 0.0
    score_detail: str = ""


@dataclass
class UniverseBacktestStats:
    universe: str
    market: str
    mode_id: str
    mode_label: str
    tickers_scanned: int
    tickers_ranked: int
    no_data: int
    duplicates_removed: int = 0
    disqualified_low_trades: int = 0
    data_source: str = "auto"
    scan_elapsed_sec: float = 0.0


def _display_ticker(raw: str) -> str:
    s = str(raw or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def dedupe_raw_tickers(tickers: list[str]) -> tuple[list[str], int]:
    """Keep first occurrence per display symbol (fixes Nifty500+SmallMid overlap)."""
    seen: set[str] = set()
    out: list[str] = []
    dupes = 0
    for raw in tickers:
        sym = str(raw or "").strip()
        if not sym:
            continue
        key = _display_ticker(sym)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        out.append(sym)
    return out, dupes


def _trade_summary(trades: list[TradeRecord], *, max_show: int = 3) -> str:
    if not trades:
        return ""
    parts = [f"{t.entry_date}→{t.exit_date}" for t in trades[-max_show:]]
    suffix = f" (+{len(trades) - max_show} more)" if len(trades) > max_show else ""
    return "; ".join(parts) + suffix


def _avg_overnight_gap_pct(df: pd.DataFrame, trades: list[TradeRecord]) -> float:
    """BTST-style overnight gap: next-day open vs entry-day close."""
    if not trades or df is None or df.empty:
        return float("nan")
    closes = hist_series(df, "Close").astype(float)
    opens = hist_series(df, "Open").astype(float)
    dates = pd.to_datetime(df.index)
    date_to_idx = {str(d.date()): i for i, d in enumerate(dates)}
    gaps: list[float] = []
    for t in trades:
        ei = date_to_idx.get(t.entry_date)
        if ei is None or ei + 1 >= len(closes):
            continue
        c = float(closes.iloc[ei])
        o_next = float(opens.iloc[ei + 1])
        if c > 0:
            gaps.append((o_next / c - 1.0) * 100.0)
    if not gaps:
        return float("nan")
    return round(float(np.mean(gaps)), 2)


def _benchmark_alpha_pct(df: pd.DataFrame, raw_ticker: str) -> tuple[float, str]:
    """Excess return vs Nifty/SPY over the same calendar window as ``df``."""
    if df is None or len(df) < 2:
        return float("nan"), ""
    bench_sym = benchmark_ticker_for(raw_ticker)
    try:
        bench_hist = fetch_price_history(bench_sym, "1d")
        if bench_hist is None or bench_hist.empty:
            return float("nan"), bench_sym
        bench = bench_hist.copy()
        bench.columns = [str(c).title() for c in bench.columns]
        left = hist_series(df, "Close").astype(float).to_frame("Close")
        right = hist_series(bench, "Close").astype(float).to_frame("Bench")
        joined = left.join(right, how="inner").dropna()
        if len(joined) < 2:
            return float("nan"), bench_sym
        s0, s1 = float(joined["Close"].iloc[0]), float(joined["Close"].iloc[-1])
        b0, b1 = float(joined["Bench"].iloc[0]), float(joined["Bench"].iloc[-1])
        if s0 <= 0 or b0 <= 0:
            return float("nan"), bench_sym
        stock_ret = (s1 / s0 - 1.0) * 100.0
        bench_ret = (b1 / b0 - 1.0) * 100.0
        return round(stock_ret - bench_ret, 2), bench_sym
    except Exception:
        return float("nan"), bench_sym


def _walk_forward_trade_returns(
    df: pd.DataFrame,
    trades: list[TradeRecord],
    *,
    initial_capital: float,
    train_frac: float = 0.7,
) -> tuple[float, float]:
    """Train/test PnL contribution % from trades split by entry date (no lookahead in ranking)."""
    if df is None or len(df) < 80 or not trades:
        return float("nan"), float("nan")
    split = int(len(df) * train_frac)
    if split < 50 or (len(df) - split) < 20:
        return float("nan"), float("nan")
    split_date = str(pd.to_datetime(df.index[split]).date())
    train_pnl = sum(t.pnl_inr for t in trades if t.entry_date < split_date)
    test_pnl = sum(t.pnl_inr for t in trades if t.entry_date >= split_date)
    cap = float(initial_capital) if initial_capital > 0 else 1.0
    return round(train_pnl / cap * 100.0, 2), round(test_pnl / cap * 100.0, 2)


def _fetch_sector(raw: str) -> str:
    try:
        import yfinance as yf

        sector, _ = get_sector_industry(yf.Ticker(raw))
        return sector or ""
    except Exception:
        return ""


def _latest_vol_ratio(df: pd.DataFrame) -> float:
    if df is None or "Volume" not in df.columns:
        return float("nan")
    vols = hist_series(df, "Volume")
    if vols is None or len(vols) < 22:
        return float("nan")
    try:
        return float(compute_volume_ratio(vols, window=20))
    except Exception:
        return float("nan")


def compute_backtest_score(
    result: BacktestResult,
    *,
    min_trades: int = 5,
) -> tuple[float, float, str]:
    """
    Composite rank score — higher is better; -inf when too few trades.

  Returns (score, confidence 0–1, human-readable breakdown).
    """
    n = int(result.num_trades or 0)
    if n < min_trades:
        return float("-inf"), 0.0, f"Disqualified: {n} trades < min {min_trades}"

    sharpe = float(result.sharpe or 0.0)
    ret = float(result.total_return_pct or 0.0)
    dd = abs(float(result.max_drawdown_pct or 0.0))
    win = float(result.win_rate_pct or 0.0)

    # Confidence ramps from 0 at min_trades to 1 at 10+ trades.
    conf_denom = max(10 - min_trades, 1)
    confidence = min(1.0, max(0.0, (n - min_trades) / conf_denom))
    win_term = (win / 100.0) * 0.2 * confidence  # down-weight win% on small samples
    sharpe_term = sharpe * 3.5
    ret_term = ret / 60.0
    dd_term = dd / 25.0
    raw = sharpe_term + ret_term - dd_term + win_term
    score = raw * (0.45 + 0.55 * confidence)

    detail = (
        f"3.5×Sharpe({sharpe_term:+.2f}) + ret/60({ret_term:+.2f}) "
        f"− |DD|/25({dd_term:.2f}) + win×conf({win_term:+.2f}) "
        f"× sample({0.45 + 0.55 * confidence:.2f})"
    )
    return score, confidence, detail


SCORE_FORMULA_HELP = """
**Score** (higher = better within this universe):
`score = (3.5×Sharpe + return/60 − |max DD|/25 + win%×0.2×confidence) × sample_factor`

- **Sharpe** dominates (risk-adjusted edge).
- **Win %** is scaled by **confidence** — nearly ignored below ~5 trades.
- **sample_factor** = `0.45 + 0.55×confidence`, where confidence ramps from 0 at min trades → 1 at 10+ trades.
- Tickers below **min trades** are excluded from ranking (not shown in table).
"""


def _apply_relaxed_config(cfg: BacktestConfig) -> BacktestConfig:
    """More frequent signals for larger sample sizes (educational)."""
    cfg.cooldown_days = 0
    cfg.rsi_entry_max = 78.0
    cfg.rsi_oversold = 35.0
    return cfg


def build_universe_scan_config(*, relaxed: bool = False) -> tuple[str, BacktestConfig]:
    """
    Ranking preset: honest next-open + costs, RSI+ST, faster Supertrend (more round-trips).
    Pure ST / 10% sizing / 3-day cooldown profiles often yield <3 trades per name on daily bars.
    """
    cfg = BacktestConfig(
        next_bar_execution=True,
        commission_pct=0.001,
        slippage_pct=0.0005,
        position_pct=0.25,
        cooldown_days=0,
        use_rsi=True,
        st_period=7,
        st_multiplier=2.5,
    )
    if relaxed:
        _apply_relaxed_config(cfg)
    label = "Universe rank — honest fills, ST 7/2.5, 25% size"
    if relaxed:
        label += " · relaxed RSI"
    return label, cfg


def _config_for_scan(
    mode_id: str,
    *,
    relaxed_signals: bool,
) -> tuple[str, BacktestConfig]:
    if mode_id == "universe_rank":
        return build_universe_scan_config(relaxed=relaxed_signals)
    mode_label, cfg = _build_config(mode_id)
    if relaxed_signals:
        _apply_relaxed_config(cfg)
        mode_label = f"{mode_label} · relaxed entries"
    return mode_label, cfg


def scan_universe_backtest(
    tickers: list[str],
    *,
    years: float = 2.0,
    capital: float = 100_000.0,
    mode_id: str = "fixed",
    min_trades: int = 2,
    relaxed_signals: bool = True,
    data_source: str = "auto",
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[UniverseBacktestRow], UniverseBacktestStats]:
    """Run one honest backtest mode across a ticker list; return ranked rows."""
    t0 = time.perf_counter()
    tickers, dupes_removed = dedupe_raw_tickers(tickers)
    rows: list[UniverseBacktestRow] = []
    no_data = 0
    disqualified = 0
    total = len(tickers)
    mode_label_base = ""

    for i, raw in enumerate(tickers):
        sym = str(raw or "").strip()
        if not sym:
            continue
        if progress_cb:
            progress_cb(i + 1, total, _display_ticker(sym))

        df = prepare_ohlcv(sym, years=float(years), data_source=data_source)
        if df is None or df.empty:
            no_data += 1
            continue

        mode_label, cfg = _config_for_scan(mode_id, relaxed_signals=relaxed_signals)
        mode_label_base = mode_label
        cfg.initial_capital = float(capital)
        result = run_backtest(df, cfg, mode_id=mode_id, mode_label=mode_label)
        score, confidence, score_detail = compute_backtest_score(result, min_trades=int(min_trades))
        if score <= float("-inf"):
            disqualified += 1
            continue

        alpha, bench = _benchmark_alpha_pct(df, sym)
        wf_train, wf_test = _walk_forward_trade_returns(
            df, result.trades, initial_capital=cfg.initial_capital,
        )
        trades = result.trades
        last = trades[-1] if trades else None
        pos_status = "Flat"
        if result.open_at_end and result.open_entry_date:
            pos_status = f"Open since {result.open_entry_date}"
        pos_pct = float(cfg.position_pct or 1.0)
        port_dd = float(result.max_drawdown_pct or 0.0)  # already on sized equity curve

        rows.append(
            UniverseBacktestRow(
                raw_ticker=sym,
                display_ticker=_display_ticker(sym),
                total_return_pct=result.total_return_pct,
                win_rate_pct=result.win_rate_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                sharpe=result.sharpe,
                num_trades=result.num_trades,
                score=score,
                data_bars=len(df),
                sector=_fetch_sector(sym),
                last_entry=last.entry_date if last else "",
                last_exit=last.exit_date if last else "",
                data_through=result.data_last_date,
                position_status=pos_status,
                open_entry=result.open_entry_date if result.open_at_end else "",
                trade_summary=_trade_summary(trades),
                vol_ratio=_latest_vol_ratio(df),
                avg_overnight_gap_pct=_avg_overnight_gap_pct(df, trades),
                alpha_pct=alpha,
                benchmark=bench,
                wf_train_return_pct=wf_train,
                wf_test_return_pct=wf_test,
                position_pct=pos_pct,
                portfolio_max_dd_pct=port_dd,
                confidence=confidence,
                score_detail=score_detail,
            )
        )

    # Safety dedupe by display ticker — keep higher score.
    by_ticker: dict[str, UniverseBacktestRow] = {}
    for row in rows:
        prev = by_ticker.get(row.display_ticker)
        if prev is None or row.score > prev.score:
            by_ticker[row.display_ticker] = row
    rows = list(by_ticker.values())

    ranked = sorted(rows, key=lambda r: (r.score, r.sharpe, r.total_return_pct), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row.rank = rank

    stats = UniverseBacktestStats(
        universe="",
        market="",
        mode_id=mode_id,
        mode_label=mode_label_base or mode_id,
        tickers_scanned=total,
        tickers_ranked=len(ranked),
        no_data=no_data,
        duplicates_removed=dupes_removed,
        disqualified_low_trades=disqualified,
        data_source=data_source,
        scan_elapsed_sec=time.perf_counter() - t0,
    )
    return ranked, stats


def universe_backtest_df(rows: list[UniverseBacktestRow]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Rank": r.rank,
                "Ticker": r.display_ticker,
                "Score": round(r.score, 3),
                "Conf.": round(r.confidence, 2),
                "Return %": r.total_return_pct,
                "Alpha %": r.alpha_pct,
                "Sharpe": r.sharpe,
                "Win %": r.win_rate_pct,
                "Max DD %": r.max_drawdown_pct,
                "Pos %": round(r.position_pct * 100.0, 0),
                "Trades": r.num_trades,
                "WF train %": r.wf_train_return_pct,
                "WF test %": r.wf_test_return_pct,
                "Avg gap %": r.avg_overnight_gap_pct,
                "Vol×": r.vol_ratio,
                "Sector": r.sector,
                "Data through": r.data_through,
                "Position": r.position_status,
                "Last closed entry": r.last_entry,
                "Last closed exit": r.last_exit,
                "Open entry": r.open_entry or "—",
                "Trade dates": r.trade_summary,
                "Bars": r.data_bars,
                "Raw": r.raw_ticker,
            }
            for r in rows
        ]
    )
