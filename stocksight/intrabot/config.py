"""
IntraBot configuration — all parameters in one place.
Edit here or override from the Streamlit UI / env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    capital_per_trade_pct: float = 5.0
    max_open_positions: int = 5
    stop_loss_pct: float = 1.0
    target_rr: float = 2.0
    trail_stop_after_pct: float = 1.5
    trail_stop_distance_pct: float = 0.8
    max_daily_loss_pct: float = 2.0
    min_gate_score: int = 55
    min_rr: float = 1.2


RISK = RiskConfig()

# Paper by default — set PAPER_TRADE=false + broker keys for live
PAPER_TRADE = os.environ.get("INTRABOT_PAPER", "true").lower() not in ("0", "false", "no")

BROKER_CONFIG: dict[str, dict[str, str]] = {
    "nse": {
        "provider": "breeze",  # icici direct (project default); set zerodha + kiteconnect for kite
        "api_key": os.environ.get("BREEZE_API_KEY", ""),
        "api_secret": os.environ.get("BREEZE_API_SECRET", ""),
        "session_token": os.environ.get("BREEZE_SESSION_TOKEN", ""),
        "zerodha_api_key": os.environ.get("KITE_API_KEY", ""),
        "zerodha_access_token": os.environ.get("KITE_ACCESS_TOKEN", ""),
    },
    "nyse": {
        "provider": "alpaca",
        "api_key": os.environ.get("ALPACA_API_KEY", ""),
        "api_secret": os.environ.get("ALPACA_API_SECRET", ""),
        "base_url": os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
    },
}

ALERT_EMAIL = os.environ.get("INTRABOT_ALERT_EMAIL", "")
ALERT_WEBHOOK = os.environ.get("INTRABOT_ALERT_WEBHOOK", "")


@dataclass
class IntraBotConfig:
    paper_trade: bool = True
    markets: tuple[str, ...] = ("NSE", "US")
    universe_nse: str = "Nifty 50 (fast)"
    universe_us: str = "Liquid US shortlist (~35)"
    max_scan_tickers: int = 60
    mood_shortlist_size: int = 3
    data_source_nse: str = "auto"  # auto | breeze | yahoo
    monitor_interval_sec: int = 60
    risk: RiskConfig = field(default_factory=RiskConfig)
    force_phase: str = ""  # empty = auto schedule
    kill_switch: bool = False

    def effective_paper(self) -> bool:
        return self.paper_trade if self.paper_trade is not None else PAPER_TRADE
