"""Resolve ICICI ISEC / ISIN codes to Yahoo Finance NSE tickers."""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Optional

from niftyrisk.portfolio import normalize_ticker_nse

_NSE_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_CACHE_DIR = Path("stocksight") / ".niftyrisk"
_ISIN_MAP: dict[str, str] | None = None
_ISIN_LOADED_AT: float = 0.0
_RESOLVE_CACHE: dict[str, str] = {}
_VALID_YAHOO_CACHE: dict[str, bool] = {}

# Common ICICI ISEC → NSE trading symbol (fallback when ISIN/Breeze unavailable)
_ISEC_TO_NSE: dict[str, str] = {
    "HINCOP": "HINDCOPPER",
    "RAIVIK": "RVNL",
    "ASHLEY": "ASHOKLEY",
    "BHAELE": "BHEL",
    "FEDBAN": "FEDERALBNK",
    "BOMBUR": "BOMDYEING",
    "IDFBAN": "IDFCFIRSTB",
    "JSWENE": "JSWENERGY",
    "NAGCON": "NCC",
    "SAGCEM": "SAGCEM",
    "SEQSCI": "SEQUENT",
    "SONSOF": "SONACOMS",
    "BHAFOR": "BHARATFORG",
    "HUHPPL": "HUHTAMAKI",
    "KECIN": "KEC",
    "LTFINA": "LTF",
    "LICHF": "LICHSGFIN",
    "PNCINF": "PNCINFRA",
    "TORPOW": "TORNTPOWER",
    "UNIP": "UNIPARTS",
    "MINCOR": "MOIL",
    "CAPPOI": "CAPACITE",
    "EMMPHO": "EMAMIPAP",
    "GUJPPL": "GPPL",
    "HERHON": "HEROMOTOCO",
    "ICIBAN": "ICICIBANK",
    "HDFBAN": "HDFCBANK",
    "RELBAN": "RELIANCE",
}


def _cache_path() -> Path:
    return _CACHE_DIR / "nse_isin_map.csv"


def _load_isin_map(*, force: bool = False) -> dict[str, str]:
    global _ISIN_MAP, _ISIN_LOADED_AT
    if _ISIN_MAP is not None and not force and (time.time() - _ISIN_LOADED_AT) < 86400:
        return _ISIN_MAP

    mapping: dict[str, str] = {}
    cache_file = _cache_path()
    text = ""
    if cache_file.is_file() and not force:
        try:
            text = cache_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""

    if not text.strip():
        try:
            import urllib.request

            req = urllib.request.Request(
                _NSE_CSV_URL,
                headers={"User-Agent": "Mozilla/5.0 (StockSight NiftyRisk)"},
            )
            text = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="replace")
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
        except Exception:
            text = ""

    if text.strip():
        reader = csv.reader(io.StringIO(text))
        next(reader, None)
        for row in reader:
            if len(row) < 7:
                continue
            symbol = (row[0] or "").strip().strip('"').upper()
            isin = (row[6] or "").strip().strip('"').upper()
            if symbol and isin:
                mapping[isin] = symbol

    _ISIN_MAP = mapping
    _ISIN_LOADED_AT = time.time()
    return mapping


def _yahoo_ticker_valid(ticker: str) -> bool:
    key = ticker.upper()
    if key in _VALID_YAHOO_CACHE:
        return _VALID_YAHOO_CACHE[key]
    ok = False
    try:
        import yfinance as yf

        hist = yf.Ticker(key).history(period="5d", interval="1d", auto_adjust=True)
        ok = hist is not None and not hist.empty
    except Exception:
        ok = False
    _VALID_YAHOO_CACHE[key] = ok
    return ok


def resolve_yahoo_ticker(stock_code: str, isin: str = "") -> str:
    """
    Map Breeze stock_code (ISEC or NSE) + optional ISIN to a Yahoo symbol (e.g. HINDCOPPER.NS).
    """
    code = (stock_code or "").strip().upper()
    isin_key = (isin or "").strip().upper()
    cache_key = f"{code}|{isin_key}"
    if cache_key in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[cache_key]

    if not code and not isin_key:
        return ""

    if code.endswith(".NS") or code.endswith(".BO"):
        result = normalize_ticker_nse(code)
        _RESOLVE_CACHE[cache_key] = result
        return result

    # 1) ISIN → NSE symbol (most reliable for ICICI demat holdings)
    if isin_key:
        sym = _load_isin_map().get(isin_key)
        if sym:
            candidate = normalize_ticker_nse(f"{sym}.NS")
            if _yahoo_ticker_valid(candidate):
                _RESOLVE_CACHE[cache_key] = candidate
                return candidate

    # 2) Breeze reverse cache / get_names when connected
    try:
        from breeze_data import resolve_nse_trading_symbol

        sym = resolve_nse_trading_symbol(code)
        if sym:
            candidate = normalize_ticker_nse(f"{sym}.NS")
            if _yahoo_ticker_valid(candidate):
                _RESOLVE_CACHE[cache_key] = candidate
                return candidate
    except Exception:
        pass

    # 3) Already a valid NSE symbol on Yahoo
    direct = normalize_ticker_nse(f"{code}.NS")
    if _yahoo_ticker_valid(direct):
        _RESOLVE_CACHE[cache_key] = direct
        return direct

    # 4) Known ISEC shorthand table
    mapped = _ISEC_TO_NSE.get(code)
    if mapped:
        candidate = normalize_ticker_nse(f"{mapped}.NS")
        if _yahoo_ticker_valid(candidate):
            _RESOLVE_CACHE[cache_key] = candidate
            return candidate

    _RESOLVE_CACHE[cache_key] = direct
    return direct


def clear_symbol_cache() -> None:
    _RESOLVE_CACHE.clear()
    _VALID_YAHOO_CACHE.clear()
