"""NiftyRisk configuration — tier limits and feature flags."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ELITE = "elite"


TIER_LIMITS: dict[SubscriptionTier, dict[str, int | bool]] = {
    SubscriptionTier.FREE: {
        "max_holdings": 10,
        "lookback_days": 252,
        "monte_carlo_runs": 0,
        "stress_scenarios": False,
        "tax_engine": False,
        "pdf_import": False,
    },
    SubscriptionTier.PRO: {
        "max_holdings": 50,
        "lookback_days": 1260,
        "monte_carlo_runs": 10_000,
        "stress_scenarios": False,
        "tax_engine": True,
        "pdf_import": True,
    },
    SubscriptionTier.ELITE: {
        "max_holdings": 200,
        "lookback_days": 2520,
        "monte_carlo_runs": 10_000,
        "stress_scenarios": True,
        "tax_engine": True,
        "pdf_import": True,
    },
}

NIFTY_BENCHMARK = "^NSEI"
DEFAULT_RISK_FREE_RATE = 0.065  # ~6.5% India 10Y proxy


@dataclass
class NiftyRiskConfig:
    tier: SubscriptionTier = SubscriptionTier.FREE
    data_dir: Path = field(default_factory=lambda: Path("stocksight") / ".niftyrisk")
    benchmark: str = NIFTY_BENCHMARK
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE
    var_confidence: float = 0.95
    api_host: str = "0.0.0.0"
    api_port: int = 8090

    def limits(self) -> dict[str, int | bool]:
        return dict(TIER_LIMITS[self.tier])


def _parse_tier(raw: str) -> SubscriptionTier:
    try:
        return SubscriptionTier((raw or "free").strip().lower())
    except ValueError:
        return SubscriptionTier.FREE


def load_config() -> NiftyRiskConfig:
    tier = _parse_tier(os.environ.get("NIFTYRISK_TIER") or "free")
    data = Path(os.environ.get("NIFTYRISK_DATA_DIR", "stocksight/.niftyrisk"))
    return NiftyRiskConfig(
        tier=tier,
        data_dir=data,
        benchmark=os.environ.get("NIFTYRISK_BENCHMARK", NIFTY_BENCHMARK),
        risk_free_rate=float(os.environ.get("NIFTYRISK_RISK_FREE", DEFAULT_RISK_FREE_RATE)),
        api_port=int(os.environ.get("NIFTYRISK_PORT", "8090")),
    )


def config_with_tier(tier: SubscriptionTier | str | None) -> NiftyRiskConfig:
    """Build config with an explicit tier override (UI / API)."""
    base = load_config()
    if tier is None:
        return base
    if isinstance(tier, SubscriptionTier):
        chosen = tier
    else:
        chosen = _parse_tier(str(tier))
    return NiftyRiskConfig(
        tier=chosen,
        data_dir=base.data_dir,
        benchmark=base.benchmark,
        risk_free_rate=base.risk_free_rate,
        var_confidence=base.var_confidence,
        api_host=base.api_host,
        api_port=base.api_port,
    )
