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


def _analyze_from_closes(
    raw: str,
    closes: pd.Series,
    flt: MarkovRegimeFilters,
    *,
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
    return _analyze_from_closes(raw, hist["Close"], flt, include_walk_forward=include_walk_forward)


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
