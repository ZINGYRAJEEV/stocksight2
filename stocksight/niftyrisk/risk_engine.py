"""Risk engine — VaR, CVaR, Monte Carlo, Sharpe, beta, drawdown, risk grade."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from niftyrisk.config import NiftyRiskConfig, SubscriptionTier, load_config
from niftyrisk.data import fetch_close_matrix, latest_prices, sectors_for_tickers
from niftyrisk.models import Portfolio, RiskReport, report_timestamp
from niftyrisk.stress import run_all_stress_scenarios
from niftyrisk.tax import estimate_portfolio_unrealized_tax


def _period_for_lookback(days: int) -> str:
    if days <= 252:
        return "1y"
    if days <= 504:
        return "2y"
    return "5y"


def _portfolio_weights(portfolio: Portfolio, prices: dict[str, float]) -> dict[str, float]:
    values: dict[str, float] = {}
    for h in portfolio.holdings:
        px = prices.get(h.ticker)
        if px and px > 0:
            values[h.ticker] = float(h.quantity) * px
    total = sum(values.values())
    if total <= 0:
        n = len(portfolio.holdings)
        return {h.ticker: 1.0 / n for h in portfolio.holdings} if n else {}
    return {t: v / total for t, v in values.items()}


def _portfolio_returns(closes: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    cols = [c for c in closes.columns if c in weights]
    if not cols:
        return pd.Series(dtype=float)
    w = np.array([weights[c] for c in cols])
    w = w / w.sum()
    rets = closes[cols].pct_change().dropna()
    port_ret = rets.values @ w
    return pd.Series(port_ret, index=rets.index)


def historical_var(returns: pd.Series, confidence: float = 0.95) -> tuple[float, float]:
    """Returns (VaR as positive loss fraction, CVaR as positive loss fraction)."""
    if returns is None or len(returns) < 20:
        return 0.0, 0.0
    r = returns.dropna().astype(float)
    alpha = (1.0 - confidence) * 100
    var_level = np.percentile(r, alpha)
    tail = r[r <= var_level]
    cvar = float(tail.mean()) if len(tail) else float(var_level)
    return abs(float(var_level)), abs(float(cvar))


def monte_carlo_projection(
    returns: pd.Series,
    *,
    runs: int = 5000,
    horizon_days: int = 252,
    initial_value: float = 100_000.0,
) -> dict[str, Any]:
    if returns is None or len(returns) < 30 or runs <= 0:
        return {}
    mu = float(returns.mean())
    sigma = float(returns.std())
    if sigma <= 0 or np.isnan(sigma):
        return {}
    rng = np.random.default_rng(42)
    shocks = rng.normal(mu, sigma, size=(runs, horizon_days))
    paths = initial_value * np.cumprod(1.0 + shocks, axis=1)
    terminal = paths[:, -1]
    return {
        "runs": runs,
        "horizon_days": horizon_days,
        "median_terminal": round(float(np.median(terminal)), 2),
        "p5_terminal": round(float(np.percentile(terminal, 5)), 2),
        "p95_terminal": round(float(np.percentile(terminal, 95)), 2),
        "prob_loss": round(float((terminal < initial_value).mean()) * 100, 1),
        "initial_value": round(initial_value, 2),
    }


def sharpe_ratio(returns: pd.Series, risk_free_annual: float = 0.065) -> Optional[float]:
    if returns is None or len(returns) < 20:
        return None
    r = returns.dropna().astype(float)
    excess = r.mean() * 252 - risk_free_annual
    vol = r.std() * np.sqrt(252)
    if vol <= 0 or np.isnan(vol):
        return None
    return round(float(excess / vol), 3)


def sortino_ratio(returns: pd.Series, risk_free_annual: float = 0.065) -> Optional[float]:
    if returns is None or len(returns) < 20:
        return None
    r = returns.dropna().astype(float)
    excess = r.mean() * 252 - risk_free_annual
    downside = r[r < 0]
    if len(downside) < 5:
        return None
    down_std = downside.std() * np.sqrt(252)
    if down_std <= 0 or np.isnan(down_std):
        return None
    return round(float(excess / down_std), 3)


def beta_vs_benchmark(port_returns: pd.Series, bench_returns: pd.Series) -> Optional[float]:
    if port_returns is None or bench_returns is None:
        return None
    df = pd.concat([port_returns, bench_returns], axis=1, join="inner").dropna()
    if len(df) < 30:
        return None
    cov = np.cov(df.iloc[:, 0], df.iloc[:, 1])
    var_b = cov[1, 1]
    if var_b <= 0:
        return None
    return round(float(cov[0, 1] / var_b), 3)


def max_drawdown(cumulative: pd.Series) -> Optional[float]:
    if cumulative is None or cumulative.empty:
        return None
    peak = cumulative.cummax()
    dd = (cumulative / peak - 1.0).min()
    return round(abs(float(dd)) * 100, 2)


def risk_grade(
    *,
    annual_vol: Optional[float],
    concentration_top3: float,
    var_pct: float,
    beta: Optional[float],
) -> tuple[str, float]:
    """A–F grade and 0–100 risk score (higher = riskier)."""
    score = 35.0
    if annual_vol is not None:
        if annual_vol > 35:
            score += 25
        elif annual_vol > 25:
            score += 15
        elif annual_vol > 18:
            score += 8
        elif annual_vol < 12:
            score -= 8
    if concentration_top3 > 60:
        score += 20
    elif concentration_top3 > 45:
        score += 12
    elif concentration_top3 > 35:
        score += 6
    if var_pct > 3.0:
        score += 15
    elif var_pct > 2.0:
        score += 8
    if beta is not None:
        if beta > 1.3:
            score += 10
        elif beta < 0.8:
            score -= 5
    score = max(0.0, min(100.0, score))
    if score < 25:
        grade = "A"
    elif score < 40:
        grade = "B"
    elif score < 55:
        grade = "C"
    elif score < 70:
        grade = "D"
    elif score < 85:
        grade = "E"
    else:
        grade = "F"
    return grade, round(score, 1)


def analyze_portfolio(
    portfolio: Portfolio,
    *,
    config: Optional[NiftyRiskConfig] = None,
) -> RiskReport:
    cfg = config or load_config()
    limits = cfg.limits()
    max_h = int(limits["max_holdings"])
    holdings = portfolio.holdings[:max_h]

    if len(portfolio.holdings) > max_h:
        notes_pre = [f"Tier {cfg.tier.value}: analyzed first {max_h} holdings only."]
    else:
        notes_pre = []

    tickers = [h.ticker for h in holdings]
    prices = latest_prices(tickers)
    weights = _portfolio_weights(Portfolio(holdings=holdings), prices)

    total_value = sum(
        float(h.quantity) * prices.get(h.ticker, h.avg_price or 0)
        for h in holdings
    )
    total_cost = sum(h.cost_basis for h in holdings)

    lookback = int(limits["lookback_days"])
    period = _period_for_lookback(lookback)
    bench = cfg.benchmark
    closes = fetch_close_matrix(tickers, period=period, benchmark=bench)

    port_rets = _portfolio_returns(closes, weights)
    bench_rets = closes[bench].pct_change().dropna() if bench in closes.columns else pd.Series(dtype=float)

    var_pct, cvar_pct = historical_var(port_rets, cfg.var_confidence)
    var_inr = var_pct * total_value if total_value > 0 else 0.0

    ann_vol = None
    if len(port_rets) >= 20:
        ann_vol = round(float(port_rets.std() * np.sqrt(252) * 100), 2)

    sharpe = sharpe_ratio(port_rets, cfg.risk_free_rate)
    sortino = sortino_ratio(port_rets, cfg.risk_free_rate)
    beta = beta_vs_benchmark(port_rets, bench_rets)

    cum = (1 + port_rets).cumprod()
    mdd = max_drawdown(cum)

    port_total_ret = None
    bench_total_ret = None
    excess = None
    if len(port_rets) >= 2:
        port_total_ret = round((float(cum.iloc[-1]) - 1.0) * 100, 2)
    if bench in closes.columns and len(closes[bench]) >= 2:
        bench_total_ret = round(
            (float(closes[bench].iloc[-1] / closes[bench].iloc[0]) - 1.0) * 100, 2
        )
    if port_total_ret is not None and bench_total_ret is not None:
        excess = round(port_total_ret - bench_total_ret, 2)

    isin_by_ticker = {h.ticker: h.isin for h in holdings if h.isin}
    sector_by_ticker = sectors_for_tickers(tickers, isin_by_ticker=isin_by_ticker)
    sector_weights: dict[str, float] = {}
    for h in holdings:
        px = prices.get(h.ticker, h.avg_price or 0)
        val = float(h.quantity) * px
        sec = h.sector or sector_by_ticker.get(h.ticker) or "Unknown"
        sector_weights[sec] = sector_weights.get(sec, 0.0) + val
    if total_value > 0:
        sector_weights = {k: round(v / total_value * 100, 1) for k, v in sector_weights.items()}

    sorted_vals = sorted(
        [float(h.quantity) * prices.get(h.ticker, 0) for h in holdings],
        reverse=True,
    )
    concentration = sum(sorted_vals[:3]) / total_value * 100 if total_value > 0 else 0.0

    grade, risk_score = risk_grade(
        annual_vol=ann_vol,
        concentration_top3=concentration,
        var_pct=var_pct * 100,
        beta=beta,
    )

    mc_runs = int(limits["monte_carlo_runs"])
    mc = monte_carlo_projection(port_rets, runs=mc_runs, initial_value=total_value) if mc_runs else {}

    holding_risk: list[dict[str, Any]] = []
    for h in holdings:
        px = prices.get(h.ticker)
        val = float(h.quantity) * (px or 0)
        holding_risk.append({
            "ticker": h.ticker.replace(".NS", "").replace(".BO", ""),
            "quantity": h.quantity,
            "price": round(px, 2) if px else None,
            "value": round(val, 2),
            "weight_pct": round(weights.get(h.ticker, 0) * 100, 1),
            "sector": h.sector or sector_by_ticker.get(h.ticker) or "Unknown",
        })

    flags: list[str] = []
    if concentration > 50:
        flags.append("HIGH_CONCENTRATION")
    if beta is not None and beta > 1.25:
        flags.append("HIGH_BETA")
    if ann_vol is not None and ann_vol > 30:
        flags.append("HIGH_VOLATILITY")
    if var_pct * 100 > 2.5:
        flags.append("ELEVATED_VAR")

    stress_results: list[dict[str, Any]] = []
    if limits.get("stress_scenarios"):
        for res in run_all_stress_scenarios(total_value, beta=beta or 1.0):
            stress_results.append({
                "scenario_id": res.scenario_id,
                "label": res.label,
                "portfolio_loss_pct": res.portfolio_loss_pct,
                "portfolio_loss_inr": res.portfolio_loss_inr,
                "recovery_hint": res.recovery_hint,
            })

    tax_estimate: dict[str, Any] | None = None
    if limits.get("tax_engine") and total_value > 0:
        tax_est = estimate_portfolio_unrealized_tax(
            total_value=total_value,
            total_cost=total_cost,
            assume_ltcg=True,
        )
        tax_estimate = {
            "unrealized_gain": round(max(0.0, total_value - total_cost), 2),
            "stcg_gains": tax_est.stcg_gains,
            "ltcg_gains": tax_est.ltcg_gains,
            "stcg_tax": tax_est.stcg_tax,
            "ltcg_tax": tax_est.ltcg_tax,
            "total_tax": tax_est.total_tax,
            "note": tax_est.note,
        }

    notes = list(notes_pre)
    if not mc and cfg.tier == SubscriptionTier.FREE:
        notes.append("Upgrade to Pro for Monte Carlo (10,000 runs) and tax engine.")
    elif not stress_results and cfg.tier != SubscriptionTier.ELITE:
        notes.append("Upgrade to Elite for historical stress scenarios (2008, COVID, IL&FS).")

    return RiskReport(
        portfolio_name=portfolio.name,
        as_of=report_timestamp(),
        tier=cfg.tier.value,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        holdings_count=len(holdings),
        risk_grade=grade,
        risk_score=risk_score,
        var_1d_pct=round(var_pct * 100, 3),
        var_1d_inr=round(var_inr, 2),
        cvar_1d_pct=round(cvar_pct * 100, 3),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        beta_nifty=beta,
        max_drawdown_pct=mdd,
        annual_vol_pct=ann_vol,
        benchmark_return_pct=bench_total_ret,
        portfolio_return_pct=port_total_ret,
        excess_return_pct=excess,
        sector_weights=sector_weights,
        concentration_top3_pct=concentration,
        monte_carlo=mc,
        stress_results=stress_results,
        tax_estimate=tax_estimate,
        holding_risk=holding_risk,
        flags=flags,
        notes=notes,
    )
