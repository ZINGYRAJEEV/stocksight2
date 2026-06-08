"""Central Brain — AI-mediated trading intermediary (TradingView → validation → exchange)."""

from central_brain.config import CentralBrainConfig, load_config
from central_brain.processor import process_tradingview_signal

__all__ = ["CentralBrainConfig", "load_config", "process_tradingview_signal"]
