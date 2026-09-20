"""
Next quarterly results dates — fetch, cache, and calendar-day helpers.

Primary source: Yahoo Finance `Ticker.calendar` (same as existing next_earnings_label).
NSE fallback when Yahoo is blank: Screener.in quarter-end + 45d estimate.

Status:
  - Yahoo dates → "estimated" (Yahoo rarely labels confirmed vs tentative)
  - Screener.in quarter-end+45 → "estimated"
  US coverage is generally better than NSE on Yahoo; treat NSE blanks as expected.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")

_CACHE_LOCK = threading.Lock()
_MEM_CACHE: dict[str, dict[str, Any]] = {}  # raw_ticker -> payload
_CACHE_DAY: Optional[str] = None

_CACHE_FILE = Path(__file__).resolve().parent / "data" / "earnings_date_cache.csv"
_CACHE_TTL_HOURS = 24.0

DAYS_TODAY_COL = "days_to_results_today"
NEXT_DATE_COL = "next_results_date"
STATUS_COL = "results_date_status"
DAYS_AT_SCAN_COL = "days_to_results_at_scan"
SCAN_DATE_COL = "scan_date"
TICKER_COL_CANDIDATES = ("Ticker", "ticker", "Symbol", "symbol")


def is_nse_or_bse(raw_ticker: str) -> bool:
    t = (raw_ticker or "").upper()
    return t.endswith(".NS") or t.endswith(".BO")


def exchange_tz(raw_ticker: str):
    return IST if is_nse_or_bse(raw_ticker) else ET


def local_today(raw_ticker: str = "", *, now: Optional[datetime] = None) -> date:
    """Calendar date in the exchange's local timezone (IST for NSE/BSE, ET for US)."""
    tz = exchange_tz(raw_ticker) if raw_ticker else IST
    clock = now if now is not None else datetime.now(tz)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=tz)
    else:
        clock = clock.astimezone(tz)
    return clock.date()


def parse_results_date(value: Any) -> Optional[date]:
    """Parse YYYY-MM-DD (or datetime-like) to a date; None if missing/invalid."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return None
    s = s[:10]
    try:
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        try:
            return pd.to_datetime(s).date()
        except Exception:
            return None


def days_to_results(
    next_results: Any,
    *,
    raw_ticker: str = "",
    as_of: Optional[date] = None,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """
    Calendar days from as_of (default: exchange-local today) to next_results.
    Negative if the date is already past. None if next_results missing.
    """
    tgt = parse_results_date(next_results)
    if tgt is None:
        return None
    base = as_of if as_of is not None else local_today(raw_ticker, now=now)
    return (tgt - base).days


def _normalize_yahoo_earnings_value(ed: Any) -> Optional[date]:
    if ed is None:
        return None
    if isinstance(ed, (list, tuple)) and ed:
        # Yahoo sometimes returns [start, end]; take the earliest upcoming, else first
        parsed = [parse_results_date(x) for x in ed]
        parsed = [d for d in parsed if d is not None]
        if not parsed:
            return None
        today = date.today()
        future = sorted(d for d in parsed if d >= today)
        return future[0] if future else min(parsed)
    return parse_results_date(ed)


def fetch_yahoo_next_results(raw_ticker: str) -> dict[str, Any]:
    """
    Fetch next earnings date from Yahoo calendar.
    Returns {next_results_date, results_date_status, source, error}.
    Yahoo does not reliably expose confirmed vs estimated → status='estimated'.
    """
    out: dict[str, Any] = {
        "next_results_date": None,
        "results_date_status": None,
        "source": "yahoo",
        "error": None,
    }
    try:
        import yfinance as yf

        cal = yf.Ticker(raw_ticker).calendar
        if cal is None:
            return out
        ed = None
        if isinstance(cal, pd.DataFrame) and not cal.empty:
            for key in ("Earnings Date", "earningsDate"):
                if key in cal.columns:
                    ed = cal.iloc[0][key]
                    break
        elif isinstance(cal, dict):
            ed = cal.get("Earnings Date") or cal.get("earningsDate")
        d = _normalize_yahoo_earnings_value(ed)
        if d is not None:
            out["next_results_date"] = d.isoformat()
            out["results_date_status"] = "estimated"
    except Exception as exc:
        out["error"] = str(exc)
        logger.debug("Yahoo earnings fetch failed for %s: %s", raw_ticker, exc)
    return out


def fetch_nse_estimated_results(raw_ticker: str) -> dict[str, Any]:
    """NSE/BSE fallback: latest Screener.in quarter end + 45 calendar days."""
    out: dict[str, Any] = {
        "next_results_date": None,
        "results_date_status": "estimated",
        "source": "screener_in_estimate",
        "error": None,
    }
    disp = raw_ticker.replace(".NS", "").replace(".BO", "")
    try:
        try:
            from screener_in_data import (
                estimate_results_announcement_date,
                fetch_screener_quarterly_series,
            )
        except ImportError:
            from .screener_in_data import (  # type: ignore
                estimate_results_announcement_date,
                fetch_screener_quarterly_series,
            )
        series = fetch_screener_quarterly_series(disp) or []
        today = local_today(raw_ticker)
        candidates: list[date] = []
        for item in series:
            q_end = item.get("quarter_end") or item.get("period_end")
            q_end_d = parse_results_date(q_end)
            if q_end_d is None:
                continue
            est = item.get("est_announce_date")
            est_d = parse_results_date(est) if est else estimate_results_announcement_date(q_end_d)
            if est_d is not None:
                candidates.append(est_d)
        future = sorted(d for d in candidates if d >= today)
        pick = future[0] if future else (max(candidates) if candidates else None)
        if pick is not None:
            out["next_results_date"] = pick.isoformat()
    except Exception as exc:
        out["error"] = str(exc)
        logger.debug("NSE estimate earnings failed for %s: %s", raw_ticker, exc)
    return out


def _load_disk_cache() -> dict[str, dict[str, Any]]:
    if not _CACHE_FILE.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        with _CACHE_FILE.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("raw_ticker") or "").strip().upper()
                if not key:
                    continue
                out[key] = {
                    "next_results_date": row.get("next_results_date") or None,
                    "results_date_status": row.get("results_date_status") or None,
                    "source": row.get("source") or "",
                    "fetched_at": row.get("fetched_at") or "",
                }
    except Exception as exc:
        logger.warning("Could not read earnings cache: %s", exc)
    return out


def _save_disk_cache(cache: dict[str, dict[str, Any]]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_FILE.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "raw_ticker",
                    "next_results_date",
                    "results_date_status",
                    "source",
                    "fetched_at",
                ],
            )
            writer.writeheader()
            for key, payload in sorted(cache.items()):
                writer.writerow(
                    {
                        "raw_ticker": key,
                        "next_results_date": payload.get("next_results_date") or "",
                        "results_date_status": payload.get("results_date_status") or "",
                        "source": payload.get("source") or "",
                        "fetched_at": payload.get("fetched_at") or "",
                    }
                )
    except Exception as exc:
        logger.warning("Could not write earnings cache: %s", exc)


def _cache_fresh(payload: dict[str, Any]) -> bool:
    fetched = payload.get("fetched_at") or ""
    if not fetched:
        return False
    try:
        ts = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            age = datetime.utcnow() - ts
        else:
            age = datetime.now(ts.tzinfo) - ts
        return age <= timedelta(hours=_CACHE_TTL_HOURS)
    except Exception:
        return False


def get_next_results_info(
    raw_ticker: str,
    *,
    force_refresh: bool = False,
    allow_nse_fallback: bool = True,
) -> dict[str, Any]:
    """
    Cached next results date for a Yahoo-style ticker.
    One fetch per ticker per day (memory + CSV). Failures return blanks, never raise.
    """
    global _CACHE_DAY, _MEM_CACHE
    key = (raw_ticker or "").strip().upper()
    empty = {
        "next_results_date": None,
        "results_date_status": None,
        "source": None,
        "error": None,
    }
    if not key:
        return empty

    today_key = date.today().isoformat()
    with _CACHE_LOCK:
        if _CACHE_DAY != today_key:
            _MEM_CACHE = _load_disk_cache()
            _CACHE_DAY = today_key
        if not force_refresh and key in _MEM_CACHE and _cache_fresh(_MEM_CACHE[key]):
            hit = dict(_MEM_CACHE[key])
            hit.setdefault("error", None)
            return hit

    # Network fetch outside lock
    payload = fetch_yahoo_next_results(key)
    if (
        not payload.get("next_results_date")
        and allow_nse_fallback
        and is_nse_or_bse(key)
    ):
        fb = fetch_nse_estimated_results(key)
        if fb.get("next_results_date"):
            payload = fb

    payload["fetched_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with _CACHE_LOCK:
        disk = _load_disk_cache()
        disk[key] = {
            "next_results_date": payload.get("next_results_date"),
            "results_date_status": payload.get("results_date_status"),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
        }
        _MEM_CACHE[key] = dict(disk[key])
        _save_disk_cache(disk)
    return payload


def enrich_scan_row_results_dates(
    *,
    raw_ticker: str,
    scan_date: Optional[date] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build stored scan fields for one ticker (does not include days_to_results_today)."""
    info = get_next_results_info(raw_ticker)
    nxt = info.get("next_results_date")
    status = info.get("results_date_status")
    sd = scan_date or local_today(raw_ticker, now=now)
    at_scan = days_to_results(nxt, raw_ticker=raw_ticker, as_of=sd, now=now)
    return {
        NEXT_DATE_COL: nxt,
        STATUS_COL: status,
        DAYS_AT_SCAN_COL: at_scan,
        SCAN_DATE_COL: sd.isoformat(),
        "next_earnings": nxt or "",  # backward-compat alias
        "days_to_earnings": at_scan,
    }


def recompute_days_to_results_today(
    next_results_date: Any,
    *,
    raw_ticker: str = "",
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Display-time recompute — never persist this value."""
    return days_to_results(next_results_date, raw_ticker=raw_ticker, now=now)


def _ticker_col(df: pd.DataFrame) -> Optional[str]:
    for c in TICKER_COL_CANDIDATES:
        if c in df.columns:
            return c
    return None


def place_days_before_ticker(df: pd.DataFrame, days_col: str = DAYS_TODAY_COL) -> pd.DataFrame:
    """Ensure days_col sits immediately before the ticker/symbol column."""
    if df is None or df.empty or days_col not in df.columns:
        return df
    tcol = _ticker_col(df)
    if not tcol:
        return df
    cols = [c for c in df.columns if c != days_col]
    idx = cols.index(tcol)
    cols.insert(idx, days_col)
    return df.loc[:, cols]


def apply_results_date_display_columns(
    df: pd.DataFrame,
    *,
    raw_ticker_col: str = "Raw",
    now: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Ensure display columns exist; recompute days_to_results_today; place it before Ticker.
    Missing historical columns fill as NaN (old CSVs).
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in (NEXT_DATE_COL, STATUS_COL, DAYS_AT_SCAN_COL, SCAN_DATE_COL, DAYS_TODAY_COL):
        if col not in out.columns:
            out[col] = pd.NA

    raws = (
        out[raw_ticker_col].astype(str)
        if raw_ticker_col in out.columns
        else pd.Series([""] * len(out), index=out.index)
    )
    # Prefer stored next_results_date; fall back to legacy Earnings / next_earnings
    legacy = None
    for c in ("Earnings", "Next_Earnings", "next_earnings"):
        if c in out.columns:
            legacy = out[c]
            break

    days_list: list[Optional[int]] = []
    for i, (_, row) in enumerate(out.iterrows()):
        nxt = row.get(NEXT_DATE_COL)
        if nxt is None or (isinstance(nxt, float) and pd.isna(nxt)) or str(nxt).strip() in ("", "—"):
            if legacy is not None:
                nxt = legacy.iloc[i] if hasattr(legacy, "iloc") else legacy
        raw = str(raws.iloc[i]) if i < len(raws) else ""
        days_list.append(recompute_days_to_results_today(nxt, raw_ticker=raw, now=now))
    out[DAYS_TODAY_COL] = days_list

    # Trail stored meta cols; days_today stays in body for place_ helper
    end_cols = [c for c in (NEXT_DATE_COL, STATUS_COL, DAYS_AT_SCAN_COL, SCAN_DATE_COL) if c in out.columns]
    body = [c for c in out.columns if c not in end_cols]
    # Preserve computed end-col values from `out` (not the pre-fill `df`)
    trailing = {c: out[c] for c in end_cols}
    out = out.loc[:, body]
    for c, series in trailing.items():
        out[c] = series
    return place_days_before_ticker(out, DAYS_TODAY_COL)


def style_days_to_results(val: Any) -> str:
    """CSS for Streamlit Styler — red ≤7, amber 8–21, neutral otherwise."""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        n = int(val)
    except (TypeError, ValueError):
        return ""
    if n <= 7:
        return "background-color: #5c1a1a; color: #ff8a8a; font-weight: 600"
    if n <= 21:
        return "background-color: #4a3a12; color: #ffd666; font-weight: 600"
    return "color: #a0aec0"


def filter_hide_near_results(
    df: pd.DataFrame,
    *,
    within_days: int,
    days_col: str = DAYS_TODAY_COL,
) -> pd.DataFrame:
    """Drop rows where 0 <= days_to_results_today <= within_days."""
    if df is None or df.empty or days_col not in df.columns or within_days < 0:
        return df
    s = pd.to_numeric(df[days_col], errors="coerce")
    mask = ~(s.notna() & (s >= 0) & (s <= within_days))
    return df.loc[mask].copy()


def load_scan_csv_compatible(path: str | Path) -> pd.DataFrame:
    """Load a scan CSV; older files without new columns get NaN fills."""
    df = pd.read_csv(path)
    for col in (DAYS_TODAY_COL, NEXT_DATE_COL, STATUS_COL, DAYS_AT_SCAN_COL, SCAN_DATE_COL):
        if col not in df.columns:
            df[col] = pd.NA
    return df
