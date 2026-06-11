"""Indian market stress scenarios — Phase 3 (Elite tier)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Historical Nifty drawdown proxies (educational shock factors)
STRESS_SCENARIOS: dict[str, dict[str, Any]] = {
    "gfc_2008": {
        "label": "2008 Global Financial Crisis",
        "nifty_shock_pct": -52.0,
        "duration_days": 180,
    },
    "covid_2020": {
        "label": "COVID March 2020",
        "nifty_shock_pct": -38.0,
        "duration_days": 45,
    },
    "ilfs_2018": {
        "label": "2018 IL&FS / NBFC stress",
        "nifty_shock_pct": -12.0,
        "duration_days": 90,
    },
    "demonetisation_2016": {
        "label": "2016 Demonetisation",
        "nifty_shock_pct": -8.0,
        "duration_days": 60,
    },
}


@dataclass
class StressResult:
    scenario_id: str
    label: str
    portfolio_loss_pct: float
    portfolio_loss_inr: float
    recovery_hint: str


def run_all_stress_scenarios(
    portfolio_value: float,
    *,
    beta: float = 1.0,
) -> list[StressResult]:
    return [
        apply_stress_scenario(portfolio_value, sid, beta=beta)
        for sid in STRESS_SCENARIOS
    ]


def apply_stress_scenario(
    portfolio_value: float,
    scenario_id: str,
    *,
    beta: float = 1.0,
) -> StressResult:
    sc = STRESS_SCENARIOS.get(scenario_id)
    if not sc:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    shock = float(sc["nifty_shock_pct"]) / 100.0
    port_shock = shock * beta
    loss_inr = portfolio_value * abs(port_shock)
    return StressResult(
        scenario_id=scenario_id,
        label=str(sc["label"]),
        portfolio_loss_pct=round(abs(port_shock) * 100, 1),
        portfolio_loss_inr=round(loss_inr, 2),
        recovery_hint=f"Historical duration ~{sc['duration_days']} trading days (illustrative).",
    )
