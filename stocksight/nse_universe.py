"""
Full NSE equity universe from NSE EQUITY_L.csv.

Official list: https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
Cached locally so scans don't re-download every run.
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Optional

NSE_EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

_CACHE_DIR = Path(__file__).resolve().parent / "data"
_CACHE_FILE = _CACHE_DIR / "nse_equity_symbols.txt"
_CACHE_META = _CACHE_DIR / "nse_equity_symbols.meta"

# In-process cache
_SYMBOLS: list[str] | None = None
_LOADED_AT: float = 0.0
_TTL_SEC = 7 * 24 * 3600  # refresh weekly


def _read_meta_mtime() -> float:
    try:
        return float(_CACHE_META.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0.0


def _write_cache(symbols: list[str]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    _CACHE_META.write_text(str(time.time()), encoding="utf-8")


def _parse_equity_csv(text: str) -> list[str]:
    """Return Yahoo-style .NS tickers from EQUITY_L.csv body."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    sym_idx = 0
    series_idx: Optional[int] = None
    if header:
        lower = [h.strip().strip('"').upper() for h in header]
        if "SYMBOL" in lower:
            sym_idx = lower.index("SYMBOL")
        if "SERIES" in lower:
            series_idx = lower.index("SERIES")

    out: list[str] = []
    seen: set[str] = set()
    for row in reader:
        if not row or len(row) <= sym_idx:
            continue
        if series_idx is not None and len(row) > series_idx:
            series = (row[series_idx] or "").strip().strip('"').upper()
            # EQ = normal equity; keep a few liquid alternate series
            if series and series not in ("EQ", "BE", "SM", "ST", "SZ"):
                continue
        sym = (row[sym_idx] or "").strip().strip('"').upper()
        if not sym or any(c.isspace() for c in sym):
            continue
        if sym in seen:
            continue
        seen.add(sym)
        out.append(f"{sym}.NS")
    return out


def _download_equity_csv() -> str:
    import urllib.request

    req = urllib.request.Request(
        NSE_EQUITY_CSV_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/csv,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — curated NSE URL
        return resp.read().decode("utf-8", errors="replace")


def load_nse_equity_tickers(*, force_refresh: bool = False) -> list[str]:
    """
    All NSE equity symbols as Yahoo tickers (e.g. RELIANCE.NS).
    Uses disk cache; refreshes at most weekly unless force_refresh=True.
    """
    global _SYMBOLS, _LOADED_AT

    now = time.time()
    if (
        not force_refresh
        and _SYMBOLS is not None
        and (now - _LOADED_AT) < 3600
    ):
        return list(_SYMBOLS)

    symbols: list[str] = []
    meta_age = now - _read_meta_mtime()
    if not force_refresh and _CACHE_FILE.is_file() and meta_age < _TTL_SEC:
        try:
            symbols = [
                ln.strip()
                for ln in _CACHE_FILE.read_text(encoding="utf-8").splitlines()
                if ln.strip().endswith(".NS")
            ]
        except OSError:
            symbols = []

    if not symbols:
        try:
            text = _download_equity_csv()
            symbols = _parse_equity_csv(text)
            if symbols:
                _write_cache(symbols)
        except Exception:
            # Fall back to stale cache if download fails
            if _CACHE_FILE.is_file():
                try:
                    symbols = [
                        ln.strip()
                        for ln in _CACHE_FILE.read_text(encoding="utf-8").splitlines()
                        if ln.strip().endswith(".NS")
                    ]
                except OSError:
                    symbols = []

    _SYMBOLS = symbols
    _LOADED_AT = now
    return list(symbols)


def nse_equity_count(*, force_refresh: bool = False) -> int:
    return len(load_nse_equity_tickers(force_refresh=force_refresh))


ALL_NSE_EQUITIES_LABEL = "All NSE equities (~2300) - very slow"
