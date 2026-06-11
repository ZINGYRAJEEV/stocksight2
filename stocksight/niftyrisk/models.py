"""Pydantic-style dataclasses for NiftyRisk domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Holding:
    ticker: str
    quantity: float
    avg_price: float = 0.0
    sector: str = ""
    isin: str = ""
    stock_code: str = ""

    @property
    def cost_basis(self) -> float:
        return float(self.quantity) * float(self.avg_price or 0)


@dataclass
class Portfolio:
    name: str = "My Portfolio"
    holdings: list[Holding] = field(default_factory=list)
    currency: str = "INR"

    @property
    def tickers(self) -> list[str]:
        return [h.ticker for h in self.holdings]


@dataclass
class RiskReport:
    portfolio_name: str
    as_of: str
    tier: str
    total_value: float
    total_cost: float
    holdings_count: int
    risk_grade: str
    risk_score: float
    var_1d_pct: float
    var_1d_inr: float
    cvar_1d_pct: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    beta_nifty: Optional[float]
    max_drawdown_pct: Optional[float]
    annual_vol_pct: Optional[float]
    benchmark_return_pct: Optional[float]
    portfolio_return_pct: Optional[float]
    excess_return_pct: Optional[float]
    sector_weights: dict[str, float] = field(default_factory=dict)
    concentration_top3_pct: float = 0.0
    monte_carlo: dict[str, Any] = field(default_factory=dict)
    stress_results: list[dict[str, Any]] = field(default_factory=list)
    tax_estimate: Optional[dict[str, Any]] = None
    holding_risk: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        try:
            from niftyrisk.advice import build_improvement_hints

            hints = build_improvement_hints(self)
        except Exception:
            hints = []
        return {
            "portfolio_name": self.portfolio_name,
            "as_of": self.as_of,
            "tier": self.tier,
            "total_value": round(self.total_value, 2),
            "total_cost": round(self.total_cost, 2),
            "holdings_count": self.holdings_count,
            "risk_grade": self.risk_grade,
            "risk_score": round(self.risk_score, 1),
            "var_1d_pct": round(self.var_1d_pct, 3),
            "var_1d_inr": round(self.var_1d_inr, 2),
            "cvar_1d_pct": round(self.cvar_1d_pct, 3),
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "beta_nifty": self.beta_nifty,
            "max_drawdown_pct": self.max_drawdown_pct,
            "annual_vol_pct": self.annual_vol_pct,
            "benchmark_return_pct": self.benchmark_return_pct,
            "portfolio_return_pct": self.portfolio_return_pct,
            "excess_return_pct": self.excess_return_pct,
            "sector_weights": self.sector_weights,
            "concentration_top3_pct": round(self.concentration_top3_pct, 1),
            "monte_carlo": self.monte_carlo,
            "stress_results": self.stress_results,
            "tax_estimate": self.tax_estimate,
            "holding_risk": self.holding_risk,
            "flags": self.flags,
            "notes": self.notes,
            "improvement_hints": hints,
        }


def upgrade_risk_report(report: Any) -> Optional[RiskReport]:
    """
    Patch RiskReport instances cached before Pro/Elite fields were added.
    Returns None if the object is not a RiskReport.
    """
    if report is None or not isinstance(report, RiskReport):
        return None
    if not hasattr(report, "stress_results"):
        object.__setattr__(report, "stress_results", [])
    if not hasattr(report, "tax_estimate"):
        object.__setattr__(report, "tax_estimate", None)
    if not hasattr(report, "monte_carlo"):
        object.__setattr__(report, "monte_carlo", {})
    return report


def report_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
