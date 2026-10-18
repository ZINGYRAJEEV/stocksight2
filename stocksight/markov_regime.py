"""
Markov Regime screener — Hedge Fund Method (states, transition matrix, Bull − Bear signal).

Educational quant framework: 3-state Markov chain, matrix powers, walk-forward accuracy,
simple k-means HMM confirmation.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from screener import fetch_price_history, get_stock_links

warnings.filterwarnings("ignore")

try:
    from intraday import INTRADAY_UNIVERSES_BY_MARKET, MARKETS, resolve_universe
except ImportError:
    from .intraday import INTRADAY_UNIVERSES_BY_MARKET, MARKETS, resolve_universe  # type: ignore

ProgressCb = Callable[[int, int, str], None]

STATE_NAMES = ("Bull", "Sideways", "Bear")
STATE_INDEX = {s: i for i, s in enumerate(STATE_NAMES)}

META = {
    "id": "markov_regime",
    "title": "Markov Regime Screener",
    "emoji": "🎲",
    "nav_title": "Markov Regime",
    "audience": (
        "Quant-minded traders who want **regime probabilities** (Bull / Sideways / Bear) "
        "from a Markov transition matrix — not subjective trend lines."
    ),
    "purpose": (
        "Labels history into three states, builds a 3×3 transition matrix, and scores "
        "**Signal = P(Bull) − P(Bear)** with optional HMM confirmation and walk-forward accuracy."
    ),
}


@dataclass
class MarkovRegimeFilters:
    lookback_days: int = 20
    bull_threshold_pct: float = 5.0
    bear_threshold_pct: float = -5.0
    forecast_days: int = 1
    min_signal: float = 0.05
    require_hmm_agree: bool = False
    signal_side: str = "any"  # long | short | any
    account_value: float = 5000.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    atr_stop_multiple: float = 2.5


@dataclass
class MarkovRegimeResult:
    ticker: str
    raw_ticker: str
    current_state: str
    cum_return_20d_pct: float
    signal_1d: float
    signal_nd: float
    forecast_days: int
    p_bull_1d: float
    p_side_1d: float
    p_bear_1d: float
    persistence_bull: float
    persistence_side: float
    persistence_bear: float
    stationary_bull: float
    stationary_bear: float
    hmm_state: str
    hmm_agrees: bool
    walk_forward_acc: float
    position_hint: str
    action: str
    last_price: float = 0.0
    atr_14: float = 0.0
    atr_pct: float = 0.0
    rsi_14: float = 0.0
    ma20: float = 0.0
    ma50: float = 0.0
    extension_ma20_pct: float = 0.0
    extension_ma50_pct: float = 0.0
    stop_price: float = 0.0
    target_1r: float = 0.0
    target_2r: float = 0.0
    suggested_shares: int = 0
    suggested_position_value: float = 0.0
    planned_risk_amount: float = 0.0
    risk_status: str = ""
    risk_flags: list[str] = field(default_factory=list)
    matrix_flat: list[float] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)


@dataclass
class MarkovRegimeScanStats:
    universe: str
    market: str
    tickers_scanned: int = 0
    tickers_matched: int = 0
    no_data: int = 0
    scan_elapsed_sec: float = 0.0


def universe_options(market: str) -> list[str]:
    mkt = (market or "NSE").upper()
    if mkt in INTRADAY_UNIVERSES_BY_MARKET:
        return list(INTRADAY_UNIVERSES_BY_MARKET[mkt].keys())
    try:
        from screener import UNIVERSES

        return list(UNIVERSES.keys())
    except Exception:
        return ["Nifty 50 (fast)"]


def _label_state(ret_pct: float, flt: MarkovRegimeFilters) -> str:
    if ret_pct >= flt.bull_threshold_pct:
        return "Bull"
    if ret_pct <= flt.bear_threshold_pct:
        return "Bear"
    return "Sideways"


def _rolling_return_pct(closes: pd.Series, window: int) -> pd.Series:
    if len(closes) < window + 1:
        return pd.Series(dtype=float)
    past = closes.shift(window)
    return ((closes / past) - 1.0) * 100.0


def _state_series(closes: pd.Series, flt: MarkovRegimeFilters) -> pd.Series:
    rets = _rolling_return_pct(closes, flt.lookback_days)
    return rets.apply(lambda x: _label_state(float(x), flt) if pd.notna(x) else np.nan)


def _build_transition_matrix(states: pd.Series) -> np.ndarray:
    """Row-stochastic 3×3 matrix (Bull, Sideways, Bear)."""
    counts = np.zeros((3, 3), dtype=float)
    vals = states.dropna().tolist()
    for i in range(len(vals) - 1):
        a = STATE_INDEX.get(str(vals[i]), 1)
        b = STATE_INDEX.get(str(vals[i + 1]), 1)
        counts[a, b] += 1.0
    # Laplace smoothing
    counts += 0.5
    row_sums = counts.sum(axis=1, keepdims=True)
    return counts / np.maximum(row_sums, 1e-9)


def _matrix_power(mat: np.ndarray, n: int) -> np.ndarray:
    if n <= 1:
        return mat.copy()
    out = mat.copy()
    for _ in range(n - 1):
        out = out @ mat
    return out


def _stationary_distribution(mat: np.ndarray, iters: int = 200) -> np.ndarray:
    pi = np.array([1 / 3, 1 / 3, 1 / 3], dtype=float)
    for _ in range(iters):
        pi = pi @ mat
    s = pi.sum()
    return pi / s if s > 0 else pi


def _simple_kmeans_hmm(
    closes: pd.Series,
    flt: MarkovRegimeFilters,
    *,
    k: int = 3,
    iters: int = 25,
) -> str:
    """k-means on (20d return, 20d vol) → map cluster to Bull/Sideways/Bear."""
    rets = _rolling_return_pct(closes, flt.lookback_days)
    vol = closes.pct_change().rolling(flt.lookback_days).std() * 100.0
    df = pd.DataFrame({"ret": rets, "vol": vol}).dropna()
    if len(df) < k + 5:
        return "Sideways"
    x = df[["ret", "vol"]].values.astype(float)
    # z-score
    mu = x.mean(axis=0)
    sd = x.std(axis=0)
    sd[sd == 0] = 1.0
    x = (x - mu) / sd
    rng = np.random.default_rng(42)
    centroids = x[rng.choice(len(x), size=k, replace=False)]
    labels = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        dists = np.linalg.norm(x[:, None, :] - centroids[None, :, :], axis=2)
        labels = dists.argmin(axis=1)
        for j in range(k):
            mask = labels == j
            if mask.any():
                centroids[j] = x[mask].mean(axis=0)
    last_label = int(labels[-1])
    cluster_ret = df["ret"].groupby(labels).mean()
    ordered = cluster_ret.sort_values(ascending=False)
    rank = list(ordered.index).index(last_label) if last_label in ordered.index else 1
    if rank == 0:
        return "Bull"
    if rank == k - 1:
        return "Bear"
    return "Sideways"


def _walk_forward_accuracy(
    closes: pd.Series,
    flt: MarkovRegimeFilters,
    *,
    min_train: int = 60,
) -> float:
    states = _state_series(closes, flt)
    valid_idx = states.dropna().index
    if len(valid_idx) < min_train + 10:
        return 0.0
    hits = 0
    total = 0
    for i in range(min_train, len(valid_idx) - 1):
        train_end = valid_idx[i]
        hist_states = states.loc[:train_end].dropna()
        if len(hist_states) < 30:
            continue
        mat = _build_transition_matrix(hist_states)
        cur = str(states.loc[train_end])
        row = STATE_INDEX.get(cur, 1)
        probs = mat[row]
        signal = float(probs[0] - probs[2])
        actual_next = str(states.loc[valid_idx[i + 1]])
        if signal > 0.02:
            pred = "Bull"
        elif signal < -0.02:
            pred = "Bear"
        else:
            pred = "Sideways"
        if pred == actual_next or (pred == "Bull" and actual_next == "Bull"):
            hits += 1
        elif pred == "Bear" and actual_next == "Bear":
            hits += 1
        elif pred == "Sideways" and actual_next == "Sideways":
            hits += 1
        total += 1
    return hits / total if total > 0 else 0.0


def _position_hint(signal: float) -> str:
    mag = abs(signal)
    if signal >= 0.15:
        return "Strong long bias — size up cautiously"
    if signal >= 0.05:
        return "Moderate long — partial size"
    if signal <= -0.15:
        return "Strong short / avoid — defensive"
    if signal <= -0.05:
        return "Moderate bearish — reduce exposure"
    return "Neutral — wait for clearer regime shift"


def _action_text(signal: float, state: str) -> str:
    if signal >= 0.10:
        return f"Long bias: P(Bull)−P(Bear) positive in {state} regime"
    if signal <= -0.10:
        return f"Short/avoid: P(Bull)−P(Bear) negative in {state} regime"
    return f"Watch: weak signal in {state} — matrix near stationary mix"


def _risk_plan(hist: pd.DataFrame, signal: float, flt: MarkovRegimeFilters) -> dict[str, object]:
    """Turn daily OHLC data into a bounded, educational trade-risk plan."""
    close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if close.empty:
        return {}
    high = pd.to_numeric(hist.get("High", close), errors="coerce").reindex(close.index).fillna(close)
    low = pd.to_numeric(hist.get("Low", close), errors="coerce").reindex(close.index).fillna(close)
    previous = close.shift(1)
    true_range = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1]) if len(true_range) >= 14 else 0.0
    price = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else price
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else price
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if len(close) >= 14 and pd.notna(rs.iloc[-1]) else 50.0
    extension20 = ((price / ma20) - 1) * 100 if ma20 else 0.0
    extension50 = ((price / ma50) - 1) * 100 if ma50 else 0.0
    atr_pct = (atr / price) * 100 if price else 0.0

    stop = price - (flt.atr_stop_multiple * atr) if atr > 0 else 0.0
    per_share_risk = price - stop
    base_risk = max(0.0, flt.account_value * flt.risk_per_trade_pct / 100)
    signal_scale = min(1.0, abs(signal) / 0.35) if signal > 0 else 0.0
    planned_risk = base_risk * signal_scale
    shares_by_risk = int(planned_risk / per_share_risk) if per_share_risk > 0 else 0
    shares_by_cap = int((flt.account_value * flt.max_position_pct / 100) / price) if price > 0 else 0
    shares = max(0, min(shares_by_risk, shares_by_cap))

    flags: list[str] = []
    if signal < 0.20:
        flags.append("Signal below +0.20 entry threshold")
    if extension20 > 12:
        flags.append(f"Extended {extension20:.1f}% above 20-day MA")
    if extension50 > 25:
        flags.append(f"Extended {extension50:.1f}% above 50-day MA")
    if rsi > 75:
        flags.append(f"RSI {rsi:.0f}: overbought / avoid chasing")
    if atr_pct > 6:
        flags.append(f"ATR {atr_pct:.1f}%: high daily volatility")
    if ma20 and price < ma20:
        flags.append("Price below 20-day MA")
    if not flags and signal >= 0.20:
        status = "Eligible - risk plan passes price and volatility checks"
    elif signal > 0:
        status = "Caution - bullish model, but reversal-risk guardrails are active"
    else:
        status = "Avoid long - model signal is not bullish"
    return {
        "last_price": round(price, 2), "atr_14": round(atr, 2), "atr_pct": round(atr_pct, 2),
        "rsi_14": round(rsi, 1), "ma20": round(ma20, 2), "ma50": round(ma50, 2),
        "extension_ma20_pct": round(extension20, 1), "extension_ma50_pct": round(extension50, 1),
        "stop_price": round(stop, 2), "target_1r": round(price + per_share_risk, 2),
        "target_2r": round(price + 2 * per_share_risk, 2), "suggested_shares": shares,
        "suggested_position_value": round(shares * price, 2), "planned_risk_amount": round(planned_risk, 2),
        "risk_status": status, "risk_flags": flags,
    }


def _analyze_from_closes(
    raw: str,
    closes: pd.Series,
    flt: MarkovRegimeFilters,
    *,
    hist: Optional[pd.DataFrame] = None,
    include_walk_forward: bool = False,
) -> Optional[MarkovRegimeResult]:
    if closes is None or len(closes) < flt.lookback_days + 40:
        return None

    states = _state_series(closes, flt)
    if states.dropna().empty:
        return None

    mat = _build_transition_matrix(states.dropna())
    cur_state = str(states.dropna().iloc[-1])
    row = STATE_INDEX.get(cur_state, 1)
    probs_1d = mat[row]
    mat_n = _matrix_power(mat, max(1, flt.forecast_days))
    probs_nd = mat_n[row]

    signal_1d = float(probs_1d[0] - probs_1d[2])
    signal_nd = float(probs_nd[0] - probs_nd[2])
    sig_use = signal_nd if flt.forecast_days > 1 else signal_1d

    if flt.signal_side == "long" and sig_use < flt.min_signal:
        return None
    if flt.signal_side == "short" and sig_use > -flt.min_signal:
        return None
    if flt.signal_side == "any" and abs(sig_use) < flt.min_signal:
        return None

    hmm = _simple_kmeans_hmm(closes, flt)
    hmm_agrees = hmm == cur_state
    if flt.require_hmm_agree and not hmm_agrees:
        return None

    rets = _rolling_return_pct(closes, flt.lookback_days)
    cum_ret = float(rets.dropna().iloc[-1]) if not rets.dropna().empty else 0.0
    stat = _stationary_distribution(mat)
    wf = _walk_forward_accuracy(closes, flt) if include_walk_forward else 0.0

    disp = raw.replace(".NS", "").replace(".BO", "")
    risk = _risk_plan(hist if hist is not None else pd.DataFrame({"Close": closes}), sig_use, flt)
    return MarkovRegimeResult(
        ticker=disp,
        raw_ticker=raw,
        current_state=cur_state,
        cum_return_20d_pct=round(cum_ret, 2),
        signal_1d=round(signal_1d, 4),
        signal_nd=round(signal_nd, 4),
        forecast_days=flt.forecast_days,
        p_bull_1d=round(float(probs_1d[0]) * 100, 1),
        p_side_1d=round(float(probs_1d[1]) * 100, 1),
        p_bear_1d=round(float(probs_1d[2]) * 100, 1),
        persistence_bull=round(float(mat[0, 0]) * 100, 1),
        persistence_side=round(float(mat[1, 1]) * 100, 1),
        persistence_bear=round(float(mat[2, 2]) * 100, 1),
        stationary_bull=round(float(stat[0]) * 100, 1),
        stationary_bear=round(float(stat[2]) * 100, 1),
        hmm_state=hmm,
        hmm_agrees=hmm_agrees,
        walk_forward_acc=round(wf, 3),
        position_hint=_position_hint(sig_use),
        action=_action_text(sig_use, cur_state),
        **risk,
        matrix_flat=[round(float(x) * 100, 2) for x in mat.flatten()],
        links=get_stock_links(raw),
    )


def analyze_ticker_markov(
    raw_ticker: str,
    flt: MarkovRegimeFilters,
    *,
    include_walk_forward: bool = False,
) -> Optional[MarkovRegimeResult]:
    raw = (raw_ticker or "").strip()
    if not raw:
        return None
    hist = fetch_price_history(raw, "1d")
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    return _analyze_from_closes(
        raw, hist["Close"], flt, hist=hist, include_walk_forward=include_walk_forward
    )


def scan_markov_regime(
    universe_name: str,
    *,
    market: str = "NSE",
    filters: Optional[MarkovRegimeFilters] = None,
    progress_cb: Optional[ProgressCb] = None,
    max_tickers: int = 120,
) -> tuple[list[MarkovRegimeResult], MarkovRegimeScanStats]:
    flt = filters or MarkovRegimeFilters()
    t0 = time.time()
    tickers = resolve_universe(universe_name, market=market)[:max_tickers]
    stats = MarkovRegimeScanStats(universe=universe_name, market=market)
    results: list[MarkovRegimeResult] = []
    total = len(tickers)

    for i, raw in enumerate(tickers, start=1):
        if progress_cb:
            progress_cb(i, total, raw.replace(".NS", "").replace(".BO", ""))
        stats.tickers_scanned += 1
        try:
            r = analyze_ticker_markov(raw, flt, include_walk_forward=True)
        except Exception:
            stats.no_data += 1
            continue
        if r is None:
            stats.no_data += 1
            continue
        results.append(r)
        stats.tickers_matched += 1

    sig_key = lambda r: abs(r.signal_nd if flt.forecast_days > 1 else r.signal_1d)
    results.sort(key=sig_key, reverse=True)
    stats.scan_elapsed_sec = time.time() - t0
    return results, stats


def transition_matrix_df(matrix_flat: list[float]) -> pd.DataFrame:
    if not matrix_flat or len(matrix_flat) != 9:
        return pd.DataFrame()
    arr = np.array(matrix_flat, dtype=float).reshape(3, 3)
    return pd.DataFrame(arr, index=list(STATE_NAMES), columns=list(STATE_NAMES))


def matrix_forecast_table(matrix_flat: list[float], *, days: tuple[int, ...] = (1, 2, 3, 5, 10)) -> pd.DataFrame:
    if not matrix_flat or len(matrix_flat) != 9:
        return pd.DataFrame()
    mat = np.array(matrix_flat, dtype=float).reshape(3, 3) / 100.0
    rows = []
    for d in days:
        p = _matrix_power(mat, d)
        for state_idx, state_name in enumerate(STATE_NAMES):
            rows.append(
                {
                    "Horizon (days)": d,
                    "From state": state_name,
                    "P(Bull) %": round(float(p[state_idx, 0]) * 100, 1),
                    "P(Sideways) %": round(float(p[state_idx, 1]) * 100, 1),
                    "P(Bear) %": round(float(p[state_idx, 2]) * 100, 1),
                    "Signal": round(float(p[state_idx, 0] - p[state_idx, 2]), 4),
                }
            )
    return pd.DataFrame(rows)
