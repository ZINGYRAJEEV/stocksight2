"""Portfolio import — CSV, manual rows, NSE ticker normalization."""

from __future__ import annotations

import csv
import io
import re
from typing import BinaryIO, Optional, TextIO, Union

from niftyrisk.models import Holding, Portfolio

_TICKER_ALIASES = {
    "ticker": "ticker",
    "symbol": "ticker",
    "stock": "ticker",
    "scrip": "ticker",
    "qty": "quantity",
    "quantity": "quantity",
    "shares": "quantity",
    "units": "quantity",
    "avg_price": "avg_price",
    "average_price": "avg_price",
    "price": "avg_price",
    "cost": "avg_price",
    "buy_price": "avg_price",
    "sector": "sector",
}


def normalize_ticker_nse(raw: str) -> str:
    """Ensure Yahoo-compatible NSE symbol (e.g. RELIANCE → RELIANCE.NS)."""
    s = (raw or "").strip().upper()
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    if s.endswith((".NS", ".BO")):
        return s
    if "." in s and not s.endswith(".NS"):
        return s
    return f"{s}.NS"


def _norm_header(h: str) -> str:
    key = (h or "").strip().lower().replace(" ", "_")
    return _TICKER_ALIASES.get(key, key)


def load_portfolio_csv(
    source: Union[str, TextIO, BinaryIO],
    *,
    name: str = "Imported Portfolio",
    max_rows: int = 200,
) -> Portfolio:
    """
    Parse NiftyRisk or ICICI holdings CSV.

    NiftyRisk:
        ticker,quantity,avg_price

    ICICI Positions export (Holdings tab):
        stock_code,Ticker (.NS),quantity,...,demat_avail_quantity,...
    """
    if isinstance(source, bytes):
        text = source
    elif hasattr(source, "read"):
        raw = source.read()
        text = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    else:
        text = str(source).encode("utf-8")

    from niftyrisk.icici_bridge import load_portfolio_csv_universal

    return load_portfolio_csv_universal(text, name=name, max_rows=max_rows)
