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
    from screener import fetch_price_history, hist_series
except ImportError:
    from .screener import fetch_price_history, hist_series

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


def prepare_ohlcv(raw_ticker: str, years: float = 2.0) -> Optional[pd.DataFrame]:
    hist = fetch_price_history(raw_ticker, "1d")
    if hist is None or hist.empty:
        return None
    df = hist.copy()
    df.columns = [str(c).title() for c in df.columns]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        return None
    min_bars = int(years * 252)
    if len(df) > min_bars:
        df = df.iloc[-min_bars:]
    return df


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


ProgressCb = Callable[[int, int, str], None]

UNIVERSE_AUDIT_MODES: list[tuple[str, str]] = [
    ("fixed", "Fixed — honest Supertrend (recommended)"),
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


@dataclass
class UniverseBacktestStats:
    universe: str
    market: str
    mode_id: str
    mode_label: str
    tickers_scanned: int
    tickers_ranked: int
    no_data: int
    scan_elapsed_sec: float = 0.0


def _display_ticker(raw: str) -> str:
    s = str(raw or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def compute_backtest_score(result: BacktestResult, *, min_trades: int = 3) -> float:
    """Composite rank score — higher is better; -inf when too few trades."""
    if result.num_trades < min_trades:
        return float("-inf")
    sharpe = float(result.sharpe or 0.0)
    ret = float(result.total_return_pct or 0.0)
    dd = abs(float(result.max_drawdown_pct or 0.0))
    win = float(result.win_rate_pct or 0.0)
    return sharpe * 2.0 + ret / 40.0 - dd / 30.0 + (win / 200.0)


def scan_universe_backtest(
    tickers: list[str],
    *,
    years: float = 2.0,
    capital: float = 100_000.0,
    mode_id: str = "fixed",
    min_trades: int = 3,
    progress_cb: Optional[ProgressCb] = None,
) -> tuple[list[UniverseBacktestRow], UniverseBacktestStats]:
    """Run one honest backtest mode across a ticker list; return ranked rows."""
    t0 = time.perf_counter()
    mode_label, _ = _build_config(mode_id)
    rows: list[UniverseBacktestRow] = []
    no_data = 0
    total = len(tickers)

    for i, raw in enumerate(tickers):
        sym = str(raw or "").strip()
        if not sym:
            continue
        if progress_cb:
            progress_cb(i + 1, total, _display_ticker(sym))

        df = prepare_ohlcv(sym, years=float(years))
        if df is None or df.empty:
            no_data += 1
            continue

        _, cfg = _build_config(mode_id)
        cfg.initial_capital = float(capital)
        result = run_backtest(df, cfg, mode_id=mode_id, mode_label=mode_label)
        score = compute_backtest_score(result, min_trades=int(min_trades))
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
            )
        )

    ranked = [r for r in rows if r.score > float("-inf")]
    ranked.sort(key=lambda r: (r.score, r.sharpe, r.total_return_pct), reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row.rank = rank

    stats = UniverseBacktestStats(
        universe="",
        market="",
        mode_id=mode_id,
        mode_label=mode_label,
        tickers_scanned=total,
        tickers_ranked=len(ranked),
        no_data=no_data,
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
                "Score": round(r.score, 3) if r.score > float("-inf") else None,
                "Return %": r.total_return_pct,
                "Sharpe": r.sharpe,
                "Win %": r.win_rate_pct,
                "Max DD %": r.max_drawdown_pct,
                "Trades": r.num_trades,
                "Bars": r.data_bars,
                "Raw": r.raw_ticker,
            }
            for r in rows
        ]
    )
