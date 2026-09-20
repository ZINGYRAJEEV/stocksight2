"""
Central thresholds for the Healthy Dip 3-layer screener.

All Layer 1–3 knobs live here so UI presets and scans share one source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Layer 1 health gate + dip band (user defaults; UI may override).
HEALTHY_DIP_CONFIG: dict[str, Any] = {
    # Fundamentals
    "min_operating_margin_pct": 12.0,
    "min_roe_pct": 18.0,
    "min_sales_growth_3y_pct": 12.0,
    "require_qtr_profit_not_falling": True,
    "min_interest_coverage": 3.0,
    "apply_interest_coverage": True,
    "max_debt_equity": 0.5,
    "max_pledged_pct": 10.0,
    "min_promoter_change_pct": -2.0,  # recent selling / dilution gate
    "apply_promoter_gates": True,  # NSE/Screener.in only; skip + warn if missing
    "max_pe": 30.0,
    "max_price_to_book": 1.5,
    "apply_pb_filter": False,
    "max_peg": 1.0,
    "apply_peg_filter": False,
    # Drawdown band
    "drawdown_min_pct": 15.0,
    "drawdown_max_pct": 40.0,
    # Stock-specific weakness vs sector / index
    "stock_vs_sector_dd_extra_pct": 10.0,
    "stock_vs_index_dd_extra_pct": 10.0,
    # Soft technical (legacy HD)
    "rsi_max": 40.0,
    "require_near_ma200": False,
    "ma200_tolerance_pct": 5.0,
    # Layer 2 bottom confirmation
    "pivot_window": 3,
    "ema_span": 20,
    "capitulation_lookback": 10,
    "capitulation_vol_mult": 2.0,
    "capitulation_wick_frac": 0.50,
    "exhaustion_vol_frac": 0.70,
    "up_down_vol_ratio_min": 1.2,
    "atr_fast": 5,
    "atr_slow": 20,
    "atr_ratio_max": 0.80,
    "rs_lookback": 10,
    "rs_line_lookback": 20,
    "support_band_pct": (3.0, 5.0),
    "min_groups_for_confirmed": 3,
    "confirmed_score_min": 55.0,
    "basing_score_min": 35.0,
    "new_low_lookback": 20,
    "new_low_recent_bars": 3,
    "new_low_penalty": 20.0,
    # Layer 3 risk
    "max_stop_pct": 8.0,
    "invalidation_atr_mult": 0.5,
    "risk_pct_of_capital": 1.0,
    "default_capital": 100_000.0,
    "tranche_first_frac": 0.33,
}

FEATURE_GROUPS: tuple[str, ...] = (
    "structure",
    "volume",
    "volatility",
    "momentum",
    "relative_strength",
    "support",
    "regime",
)

STATES: tuple[str, ...] = ("Falling", "Basing", "Confirmed", "Failed")


def get_healthy_dip_config(**overrides: Any) -> dict[str, Any]:
    """Return a deep copy of defaults with optional overrides applied."""
    cfg = deepcopy(HEALTHY_DIP_CONFIG)
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    return cfg
