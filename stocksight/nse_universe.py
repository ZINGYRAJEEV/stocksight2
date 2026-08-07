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

_MODULE_DIR = Path(__file__).resolve().parent
_CACHE_DIR = _MODULE_DIR / "data"
_CACHE_FILE = _CACHE_DIR / "nse_equity_symbols.txt"
_CACHE_META = _CACHE_DIR / "nse_equity_symbols.meta"

# In-process cache
_SYMBOLS: list[str] | None = None
_LOADED_AT: float = 0.0
_LAST_ERROR: str = ""

ALL_NSE_EQUITIES_LABEL = "All NSE equities (~2300) - very slow"
_ALL_NSE_LABELS = (
    ALL_NSE_EQUITIES_LABEL,
    "All NSE equities (full list — very slow)",  # legacy
)


def is_all_nse_label(name: str) -> bool:
    return bool(name) and (
        name in _ALL_NSE_LABELS or str(name).startswith("All NSE equities")
    )


def _cache_candidates() -> list[Path]:
    """Possible locations for the committed symbol snapshot."""
    cwd = Path.cwd()
    return [
        _CACHE_FILE,
        _MODULE_DIR / "data" / "nse_equity_symbols.txt",
        cwd / "stocksight" / "data" / "nse_equity_symbols.txt",
        cwd / "data" / "nse_equity_symbols.txt",
    ]


def _write_cache(symbols: list[str]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    _CACHE_META.write_text(str(time.time()), encoding="utf-8")


def _read_symbols_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip().endswith(".NS")]


def _read_disk_cache() -> list[str]:
    for path in _cache_candidates():
        try:
            if path.is_file():
                symbols = _read_symbols_file(path)
                if symbols:
                    return symbols
        except OSError:
            continue
    return []


def _parse_equity_csv(text: str) -> list[str]:
    """Return Yahoo-style .NS tickers from EQUITY_L.csv body."""
    if not text or "<html" in text[:200].lower():
        return []
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

    Prefer the committed disk cache always (Streamlit Cloud often cannot
    reach nsearchives). Only hit the network when there is no cache or
    force_refresh=True. Never replace a good cache with an empty download.
    """
    global _SYMBOLS, _LOADED_AT, _LAST_ERROR

    now = time.time()
    if (
        not force_refresh
        and _SYMBOLS is not None
        and (now - _LOADED_AT) < 3600
        and len(_SYMBOLS) > 0
    ):
        return list(_SYMBOLS)

    _LAST_ERROR = ""
    cached = _read_disk_cache()

    # Normal path: use snapshot on disk (do not block on NSE from Cloud).
    if cached and not force_refresh:
        _SYMBOLS = cached
        _LOADED_AT = now
        return list(cached)

    # No cache, or explicit refresh — try NSE, keep cache if download is empty/blocked.
    try:
        text = _download_equity_csv()
        downloaded = _parse_equity_csv(text)
        if downloaded:
            try:
                _write_cache(downloaded)
            except OSError:
                pass
            _SYMBOLS = downloaded
            _LOADED_AT = now
            return list(downloaded)
        _LAST_ERROR = "NSE download returned no symbols (blocked HTML or empty CSV)."
    except Exception as exc:
        _LAST_ERROR = f"NSE download failed: {exc}"

    if cached:
        _SYMBOLS = cached
        _LOADED_AT = now
        return list(cached)

    _SYMBOLS = []
    _LOADED_AT = now
    if not _LAST_ERROR:
        _LAST_ERROR = (
            "NSE equity cache missing (stocksight/data/nse_equity_symbols.txt) "
            "and download failed."
        )
    return []


def nse_equity_count(*, force_refresh: bool = False) -> int:
    return len(load_nse_equity_tickers(force_refresh=force_refresh))


def last_nse_universe_error() -> str:
    return _LAST_ERROR
