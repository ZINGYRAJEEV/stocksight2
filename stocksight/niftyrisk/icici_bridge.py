"""Bridge ICICI Breeze holdings / export CSV ↔ NiftyRisk portfolio format."""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Optional, Union

import pandas as pd

from niftyrisk.models import Holding, Portfolio
from niftyrisk.portfolio import normalize_ticker_nse
from niftyrisk.symbols import resolve_yahoo_ticker

# NiftyRisk minimal export columns
NIFTYRISK_CSV_COLUMNS = ("ticker", "quantity", "avg_price")

# ICICI enriched export may include these (holdings tab)
ICICI_EXTRA_COLUMNS = (
    "stock_code",
    "Ticker (.NS)",
    "quantity",
    "average_price",
    "ltp",
    "Scan Entry",
    "demat_avail_quantity",
    "demat_total_bulk_quantity",
)


def _clean_num(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, float) and val != val:
        return None
    s = str(val).strip().replace(",", "").replace("₹", "")
    if not s or s in ("—", "-", "n/a", "nan", "None"):
        return None
    try:
        f = float(s)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _norm_header(h: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")
    mapping = {
        "ticker": "ticker",
        "ticker_ns": "ticker",
        "symbol": "ticker",
        "stock_code": "stock_code",
        "quantity": "quantity",
        "qty": "quantity",
        "shares": "quantity",
        "units": "quantity",
        "demat_avail_quantity": "qty_avail",
        "demat_total_bulk_quantity": "qty_demat",
        "avg_price": "avg_price",
        "average_price": "avg_price",
        "average_cost": "avg_price",
        "price": "avg_price",
        "scan_entry": "avg_price",
        "ltp": "ltp",
        "current_market_price": "ltp",
        "sector": "sector",
        "stock_isin": "isin",
    }
    return mapping.get(compact, compact)


def _row_isin(row: dict[str, Any], col_map: dict[str, str]) -> str:
    for key in ("isin", "stock_isin"):
        col = col_map.get(key)
        if col:
            val = str(row.get(col) or "").strip()
            if val:
                return val
    for raw_key in row.keys():
        if _norm_header(raw_key) == "isin":
            val = str(row.get(raw_key) or "").strip()
            if val:
                return val
    return ""


def _breeze_code_to_ticker(stock_code: str, isin: str = "") -> str:
    """Map Breeze stock_code (ISEC or NSE symbol) to yfinance-style ticker."""
    return resolve_yahoo_ticker(stock_code, isin)


def _ticker_from_row(row: dict[str, Any], col_map: dict[str, str]) -> str:
    """Resolve Yahoo ticker using ISIN + ISEC (ICICI demat export)."""
    isin = _row_isin(row, col_map)
    col = col_map.get("stock_code")
    code = str(row.get(col) or "").strip() if col else ""
    if code or isin:
        resolved = resolve_yahoo_ticker(code, isin)
        if resolved:
            return resolved
    col = col_map.get("ticker")
    if col:
        raw = str(row.get(col) or "").strip()
        if raw:
            return resolve_yahoo_ticker(raw, isin)
    return ""


def _quantity_from_row(row: dict[str, Any], col_map: dict[str, str]) -> float:
    for key in ("quantity", "qty_avail", "qty_demat"):
        col = col_map.get(key)
        if not col:
            continue
        v = _clean_num(row.get(col))
        if v is not None and v > 0:
            return float(v)
    return 0.0


def _avg_price_from_row(row: dict[str, Any], col_map: dict[str, str]) -> float:
    for key in ("avg_price", "ltp"):
        col = col_map.get(key)
        if not col:
            continue
        v = _clean_num(row.get(col))
        if v is not None and v > 0:
            return float(v)
    return 0.0


def portfolio_from_rows(
    rows: list[dict[str, Any]],
    *,
    name: str = "ICICI Holdings",
    skip_zero_qty: bool = True,
) -> Portfolio:
    """Build NiftyRisk portfolio from Breeze holdings rows or ICICI export dicts."""
    holdings: list[Holding] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        col_map = {_norm_header(k): k for k in row.keys()}
        ticker = _ticker_from_row(row, col_map)
        if not ticker:
            continue
        qty = _quantity_from_row(row, col_map)
        if skip_zero_qty and qty <= 0:
            continue
        avg = _avg_price_from_row(row, col_map)
        isin = _row_isin(row, col_map)
        stock_code = str(row.get(col_map.get("stock_code", ""), "") or "").strip()
        sector = str(row.get(col_map.get("sector", ""), "") or "").strip()
        holdings.append(
            Holding(
                ticker=ticker,
                quantity=qty,
                avg_price=avg,
                sector=sector,
                isin=isin,
                stock_code=stock_code,
            )
        )
    if not holdings:
        raise ValueError("No holdings with quantity > 0")
    return Portfolio(name=name, holdings=holdings)


def portfolio_from_dataframe(df: pd.DataFrame, *, name: str = "ICICI Holdings") -> Portfolio:
    if df is None or df.empty:
        raise ValueError("Empty holdings table")
    return portfolio_from_rows(df.to_dict(orient="records"), name=name)


def detect_csv_format(fieldnames: list[str]) -> str:
    """Return 'icici' | 'niftyrisk' | 'unknown'."""
    norms = {_norm_header(h) for h in fieldnames}
    if "stock_code" in norms or "qty_avail" in norms or "qty_demat" in norms:
        return "icici"
    if "ticker" in norms and "quantity" in norms:
        return "niftyrisk"
    if "ticker" in norms or "stock_code" in norms:
        return "icici" if "stock_code" in norms else "niftyrisk"
    return "unknown"


def load_portfolio_csv_universal(
    source: Union[str, bytes],
    *,
    name: str = "Imported Portfolio",
    max_rows: int = 200,
) -> Portfolio:
    """
    Accept NiftyRisk CSV (ticker, quantity, avg_price) or ICICI holdings export
    (stock_code, Ticker (.NS), quantity, demat_* columns, optional average_price / Scan Entry).
    """
    if isinstance(source, bytes):
        text = source.decode("utf-8-sig", errors="replace")
    else:
        text = str(source)

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    fmt = detect_csv_format(list(reader.fieldnames))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no data rows")

    col_map = {_norm_header(h): h for h in reader.fieldnames}
    if "ticker" not in col_map and "stock_code" not in col_map:
        raise ValueError("CSV must include ticker, Ticker (.NS), or stock_code column")

    holdings: list[Holding] = []
    for i, row in enumerate(rows):
        if i >= max_rows:
            break
        ticker = _ticker_from_row(row, col_map)
        if not ticker:
            continue
        qty = _quantity_from_row(row, col_map)
        if qty <= 0:
            continue
        avg = _avg_price_from_row(row, col_map)
        sector = ""
        if "sector" in col_map:
            sector = str(row.get(col_map["sector"], "") or "").strip()
        isin = _row_isin(row, col_map)
        stock_code = str(row.get(col_map.get("stock_code", ""), "") or "").strip()
        holdings.append(
            Holding(
                ticker=ticker,
                quantity=qty,
                avg_price=avg,
                sector=sector,
                isin=isin,
                stock_code=stock_code,
            )
        )

    if not holdings:
        raise ValueError(
            "No valid holdings (need quantity > 0). "
            "ICICI export: use Holdings tab CSV or demat_avail_quantity column."
        )

    default_name = "ICICI Holdings" if fmt == "icici" else name
    return Portfolio(name=default_name if fmt == "icici" else name, holdings=holdings)


def portfolio_to_niftyrisk_csv(portfolio: Portfolio) -> str:
    """Minimal CSV for NiftyRisk re-import or external tools."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(NIFTYRISK_CSV_COLUMNS)
    for h in portfolio.holdings:
        w.writerow([
            h.ticker.replace(".NS", "").replace(".BO", ""),
            int(h.quantity) if h.quantity == int(h.quantity) else h.quantity,
            round(h.avg_price, 2) if h.avg_price else "",
        ])
    return buf.getvalue()


def portfolio_to_icici_enriched_csv(portfolio: Portfolio, *, source_rows: Optional[list[dict]] = None) -> str:
    """
    Export compatible with ICICI holdings shape + NiftyRisk core columns.
    Merges NiftyRisk fields into existing ICICI rows when source_rows provided.
    """
    buf = io.StringIO()
    fieldnames = [
        "stock_code",
        "Ticker (.NS)",
        "ticker",
        "quantity",
        "avg_price",
        "average_price",
        "ltp",
    ]
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()

    src_by_ticker: dict[str, dict] = {}
    if source_rows:
        for row in source_rows:
            try:
                p = portfolio_from_rows([row], skip_zero_qty=False)
                if p.holdings:
                    src_by_ticker[p.holdings[0].ticker] = row
            except ValueError:
                continue

    for h in portfolio.holdings:
        base = src_by_ticker.get(h.ticker, {})
        code = str(base.get("stock_code") or h.ticker.replace(".NS", ""))
        w.writerow({
            "stock_code": code,
            "Ticker (.NS)": h.ticker,
            "ticker": h.ticker.replace(".NS", ""),
            "quantity": h.quantity,
            "avg_price": h.avg_price or "",
            "average_price": h.avg_price or base.get("average_price", ""),
            "ltp": base.get("ltp") or base.get("current_market_price", ""),
        })
    return buf.getvalue()
