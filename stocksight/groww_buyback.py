"""Fetch active buybacks from Groww.in and match to screener rows."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

GROWW_BUYBACK_URL = "https://groww.in/buy-back"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
GROWW_ROW_STYLE = "background-color: #dcfce7; color: #166534; font-weight: 600;"


@dataclass(frozen=True)
class GrowwBuyback:
    company_name: str
    company_short_name: str
    record_date: Optional[date]
    offer_price: float
    status: str
    search_id: str
    symbol: str
    isin: str
    end_date: Optional[date]

    @property
    def detail_url(self) -> str:
        return f"{GROWW_BUYBACK_URL}/{self.search_id}"

    @property
    def record_date_label(self) -> str:
        if not self.record_date:
            return "—"
        return self.record_date.strftime("%d-%b-%Y")

    @property
    def record_still_valid(self) -> bool:
        return is_record_date_valid(self.record_date)


def is_record_date_valid(record_date: Optional[date], *, today: Optional[date] = None) -> bool:
    """True when record date is today or in the future (you can still qualify)."""
    if record_date is None:
        return False
    ref = today or date.today()
    return record_date >= ref


def parse_flexible_date(text: str) -> Optional[date]:
    """Parse common Indian buyback record-date strings."""
    if not text or text.strip() in ("—", "-", ""):
        return None
    s = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s[:10]):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    for fmt in (
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%b-%y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.search(
        r"(\d{1,2}[\s/-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s/-]\d{2,4})",
        s,
        re.I,
    )
    if m:
        return parse_flexible_date(m.group(1).replace("/", "-").replace(" ", "-"))
    return None


def _parse_iso_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _norm_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    for suffix in ("limited", "ltd", "company", "co", "india"):
        s = s.replace(suffix, "")
    return s


def _item_from_raw(raw: dict) -> GrowwBuyback:
    return GrowwBuyback(
        company_name=str(raw.get("companyName") or ""),
        company_short_name=str(raw.get("companyShortName") or ""),
        record_date=_parse_iso_date(raw.get("recordDate")),
        offer_price=float(raw.get("offerPrice") or 0),
        status=str(raw.get("status") or ""),
        search_id=str(raw.get("searchId") or ""),
        symbol=str(raw.get("companySymbol") or raw.get("scripCode") or ""),
        isin=str(raw.get("symbolIsin") or ""),
        end_date=_parse_iso_date(raw.get("endDate")),
    )


def fetch_groww_buybacks(*, include_closed: bool = False) -> list[GrowwBuyback]:
    """Return Groww buybacks (ACTIVE by default)."""
    req = urllib.request.Request(GROWW_BUYBACK_URL, headers={"User-Agent": _USER_AGENT})
    try:
        html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return []

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []

    try:
        data = json.loads(m.group(1))
        listing = data["props"]["pageProps"]["buyBackListingData"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return []

    sections = ["ACTIVE"]
    if include_closed:
        sections.extend(["UPCOMING", "CLOSED"])

    out: list[GrowwBuyback] = []
    seen: set[str] = set()
    for section in sections:
        for raw in listing.get(section) or []:
            key = str(raw.get("buyBackId") or raw.get("searchId") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(_item_from_raw(raw))
    return out


def match_groww_buyback(
    company: str,
    *,
    ticker: str = "",
    isin: str = "",
    items: list[GrowwBuyback],
) -> Optional[GrowwBuyback]:
    """Match a screener row to a Groww active buyback."""
    ticker_u = (ticker or "").upper().replace(".NS", "").replace(".BO", "").strip()
    cn = _norm_name(company)

    for g in items:
        if isin and g.isin and isin.upper() == g.isin.upper():
            return g
        if ticker_u and g.symbol and ticker_u == g.symbol.upper():
            return g
        gn = _norm_name(g.company_name)
        gsn = _norm_name(g.company_short_name)
        if cn and (cn == gn or cn == gsn or cn in gn or gn in cn or gsn in cn):
            return g
    return None


def groww_buybacks_to_rows(items: list[GrowwBuyback]) -> list[dict]:
    rows = []
    for g in items:
        rows.append(
            {
                "Company": g.company_name,
                "Symbol": g.symbol or "—",
                "Offer ₹": g.offer_price,
                "Record date": g.record_date_label,
                "Record valid": "✅" if g.record_still_valid else "—",
                "Status": g.status,
                "Groww": g.detail_url,
            }
        )
    return rows


def groww_highlight_mask(
    df,
    *,
    company_col: str,
    ticker_col: str | None,
    groww_items: list[GrowwBuyback],
) -> list[bool]:
    """Per-row mask: active on Groww with record date still valid."""
    mask: list[bool] = []
    for _, row in df.iterrows():
        company = str(row.get(company_col, "") or "")
        ticker = str(row.get(ticker_col, "") or "") if ticker_col and ticker_col in df.columns else ""
        hit = match_groww_buyback(company, ticker=ticker, items=groww_items)
        mask.append(bool(hit and hit.record_still_valid))
    return mask


def apply_groww_row_style(styler, mask: list[bool]):
    """Apply full-row green highlight for valid Groww buybacks."""

    def _row_style(row) -> list[str]:
        idx = row.name
        if idx < len(mask) and mask[idx]:
            return [GROWW_ROW_STYLE] * len(row)
        return [""] * len(row)

    return styler.apply(_row_style, axis=1)
