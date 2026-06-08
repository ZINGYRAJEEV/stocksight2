"""
Central Brain configuration — .env / environment variables.

Three-key exchange auth (BitGet): API_KEY, SECRET_KEY, PASSPHRASE.
Withdrawal permissions must be disabled on the exchange key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[2]
_STOCKSIGHT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for path in (_REPO / ".env", _STOCKSIGHT / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


_load_dotenv()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "")
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


@dataclass
class ExchangeCredentials:
    api_key: str = ""
    secret_key: str = ""
    passphrase: str = ""
    provider: str = "bitget"  # bitget | breeze | paper

    def configured(self) -> bool:
        return bool(self.api_key and self.secret_key and self.passphrase)


@dataclass
class CentralBrainConfig:
    """Runtime config — circuit breakers and execution mode."""

    enabled: bool = True
    mode: str = "paper"  # paper | live
    live_confirm: bool = False
    kill_switch: bool = False

    portfolio_value: float = 10_000.0
    max_trade_size: float = 500.0
    max_trades_per_day: int = 10

    tradingview_secret: str = ""
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    use_claude_validation: bool = True

    alert_webhook: str = ""
    rules_path: Path = field(default_factory=lambda: Path(__file__).parent / "rules.json")

    bitget: ExchangeCredentials = field(default_factory=ExchangeCredentials)
    breeze_api_key: str = ""
    breeze_api_secret: str = ""
    breeze_session_token: str = ""

    def effective_mode(self) -> str:
        if self.kill_switch:
            return "blocked"
        if self.mode == "live" and self.live_confirm and self.enabled:
            return "live"
        if self.mode == "live" and not self.live_confirm:
            return "paper"
        return "paper" if self.mode != "live" else "paper"

    def live_allowed(self) -> bool:
        return (
            self.enabled
            and not self.kill_switch
            and self.mode == "live"
            and self.live_confirm
        )


def load_config() -> CentralBrainConfig:
    bitget = ExchangeCredentials(
        api_key=os.environ.get("BITGET_API_KEY", ""),
        secret_key=os.environ.get("BITGET_SECRET_KEY", os.environ.get("BITGET_API_SECRET", "")),
        passphrase=os.environ.get("BITGET_PASSPHRASE", ""),
        provider="bitget",
    )
    rules_override = os.environ.get("CENTRAL_BRAIN_RULES_PATH", "")
    rules_path = Path(rules_override) if rules_override else Path(__file__).parent / "rules.json"

    return CentralBrainConfig(
        enabled=_env_bool("CENTRAL_BRAIN_ENABLED", True),
        mode=os.environ.get("CENTRAL_BRAIN_MODE", "paper").strip().lower() or "paper",
        live_confirm=_env_bool("CENTRAL_BRAIN_LIVE_CONFIRM", False)
        or os.environ.get("CENTRAL_BRAIN_LIVE_CONFIRM", "").strip().upper() == "YES",
        kill_switch=_env_bool("CENTRAL_BRAIN_KILL_SWITCH", False),
        portfolio_value=_env_float("PORTFOLIO_VALUE", 10_000.0),
        max_trade_size=_env_float("MAX_TRADE_SIZE", 500.0),
        max_trades_per_day=_env_int("MAX_TRADES_PER_DAY", 10),
        tradingview_secret=os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        claude_model=os.environ.get("CENTRAL_BRAIN_CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        use_claude_validation=_env_bool("CENTRAL_BRAIN_USE_CLAUDE", True),
        alert_webhook=os.environ.get("CENTRAL_BRAIN_ALERT_WEBHOOK", os.environ.get("INTRABOT_ALERT_WEBHOOK", "")),
        rules_path=rules_path,
        bitget=bitget,
        breeze_api_key=os.environ.get("BREEZE_API_KEY", ""),
        breeze_api_secret=os.environ.get("BREEZE_API_SECRET", ""),
        breeze_session_token=os.environ.get("BREEZE_SESSION_TOKEN", ""),
    )
