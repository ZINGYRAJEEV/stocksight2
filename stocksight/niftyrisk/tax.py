"""STCG / LTCG tax estimator — Phase 2 (Pro tier)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TaxEstimate:
    stcg_gains: float = 0.0
    ltcg_gains: float = 0.0
    stcg_tax: float = 0.0
    ltcg_tax: float = 0.0
    total_tax: float = 0.0
    note: str = "Phase 2 — enable with NIFTYRISK_TIER=pro"


def estimate_portfolio_unrealized_tax(
    *,
    total_value: float,
    total_cost: float,
    assume_ltcg: bool = True,
) -> TaxEstimate:
    """
    Estimate tax on unrealized book gains (educational).
    Defaults to LTCG treatment when assume_ltcg=True.
    """
    gain = max(0.0, float(total_value) - float(total_cost))
    if gain <= 0:
        return TaxEstimate(
            note="No unrealized gain vs recorded cost basis.",
        )
    if assume_ltcg:
        return estimate_capital_gains_tax(ltcg_gains=gain)
    return estimate_capital_gains_tax(stcg_gains=gain)


def estimate_capital_gains_tax(
    *,
    stcg_gains: float = 0.0,
    ltcg_gains: float = 0.0,
    ltcg_exemption_used: float = 0.0,
) -> TaxEstimate:
    """
    Simplified FY2024+ rules: STCG equity 20%, LTCG 12.5% above ₹1.25L exemption.
    Educational only — not tax advice.
    """
    stcg_tax = max(0.0, stcg_gains) * 0.20
    exempt_remaining = max(0.0, 125_000.0 - ltcg_exemption_used)
    taxable_ltcg = max(0.0, ltcg_gains - exempt_remaining)
    ltcg_tax = taxable_ltcg * 0.125
    return TaxEstimate(
        stcg_gains=stcg_gains,
        ltcg_gains=ltcg_gains,
        stcg_tax=round(stcg_tax, 2),
        ltcg_tax=round(ltcg_tax, 2),
        total_tax=round(stcg_tax + ltcg_tax, 2),
        note="Simplified slab — consult a CA for filing.",
    )
