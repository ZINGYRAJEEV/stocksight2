"""Live NSE healthy-dip screener — shared engine for Flask dashboard and Streamlit page."""

from live_screener.engine import (
    PRESETS,
    ScanConfig,
    ScanState,
    run_healthy_dip_scan,
    signal_result_to_row,
)

__all__ = [
    "PRESETS",
    "ScanConfig",
    "ScanState",
    "run_healthy_dip_scan",
    "signal_result_to_row",
]
