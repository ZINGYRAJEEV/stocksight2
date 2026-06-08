"""
Live buyback announcement feed — aggregate India buyback news early via Google News RSS.

Supplements manual Screener.in / NSE checks. Parses headlines for price, size %, record date.
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from buyback import (
    DEFAULT_PARTICIPATION_PCT,
    BuybackInputs,
    analyze_buyback,
)
from buyback_announcements_store import load_seen, mark_seen
from news_sources import fetch_google_news_rss
from screener import UNIVERSES, get_stock_links
from screener_buyback import ScreenerBuybackItem, fetch_all_screener_buybacks

SCREENER_BUYBACK_URL = "https://www.screener.in/full-text-search/?q=buyback&type=announcements"

BUYBACK_RSS_QUERIES = (
    "buyback tender offer India NSE BSE",
    "share buyback record date India listed",
    "company announces buyback India stock",
    "open market buyback tender price India",
)

# Common headline names → NSE tickers (extend as needed)
_COMPANY_ALIASES: dict[str, str] = {
    "INFOSYS": "INFY.NS",
    "TATA CONSULTANCY": "TCS.NS",
    "TCS": "TCS.NS",
    "WIPRO": "WIPRO.NS",
    "BAJAJ AUTO": "BAJAJ-AUTO.NS",
    "RELIANCE": "RELIANCE.NS",
    "HDFC BANK": "HDFCBANK.NS",
    "ICICI BANK": "ICICIBANK.NS",
    "ITC": "ITC.NS",
    "HCL TECH": "HCLTECH.NS",
    "HCLTECH": "HCLTECH.NS",
    "LARSEN": "LT.NS",
    "L&T": "LT.NS",
    "GARWARE": "GRWRTECH.NS",
    "GRWRTECH": "GRWRTECH.NS",
}

_TICKER_INDEX: list[tuple[str, str]] = []


def _build_ticker_index() -> list[tuple[str, str]]:
    global _TICKER_INDEX
    if _TICKER_INDEX:
        return _TICKER_INDEX
    seen: set[str] = set()
    for name, syms in UNIVERSES.items():
        if "NSE" not in name and "Nifty" not in name:
            continue
        for raw in syms:
            if not raw.endswith((".NS", ".BO")):
                continue
            sym = raw.replace(".NS", "").replace(".BO", "")
            if sym not in seen:
                seen.add(sym)
                _TICKER_INDEX.append((sym, raw))
    _TICKER_INDEX.sort(key=lambda x: -len(x[0]))
    return _TICKER_INDEX


def _announcement_id(title: str, published: Optional[datetime]) -> str:
    blob = f"{title}|{published.isoformat() if published else ''}"
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _parse_price(text: str) -> Optional[float]:
    for pat in (
        r"₹\s*([\d,]+(?:\.\d+)?)",
        r"Rs\.?\s*([\d,]+(?:\.\d+)?)",
        r"INR\s*([\d,]+(?:\.\d+)?)",
        r"at\s+([\d,]+(?:\.\d+)?)\s*(?:per share|/share|a share)",
        r"price\s+of\s+₹?\s*([\d,]+(?:\.\d+)?)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _parse_pct(text: str) -> Optional[float]:
    m = re.search(r"([\d.]+)\s*%\s*(?:of\s+)?(?:equity|shares|stake|capital)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"buyback\s+of\s+([\d.]+)\s*%", text, re.I)
    if m:
        return float(m.group(1))
    return None


def _parse_record_date(text: str) -> str:
    m = re.search(
        r"record\s+date\s*[:\-]?\s*(\d{1,2}[\s/-]\w+[\s/-]\d{2,4}|\d{1,2}-\w+-\d{4})",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})", text, re.I)
    if m:
        return m.group(1).strip()
    return ""


def _parse_offer_type(text: str) -> str:
    low = text.lower()
    if "tender" in low:
        return "Tender"
    if "open market" in low or "open-market" in low:
        return "Open market"
    if "buyback" in low or "buy back" in low or "buy-back" in low:
        return "Buyback"
    return "Unknown"


def resolve_company_ticker(text: str) -> tuple[str, str]:
    """Return (display company, raw_ticker)."""
    text_u = (text or "").upper()
    for alias, raw in sorted(_COMPANY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in text_u:
            return alias.title(), raw
    for sym, raw in _build_ticker_index():
        if sym in text_u.replace(" ", ""):
            return sym.replace("-", " "), raw
        if sym.replace("-", "") in text_u.replace(" ", "").replace("-", ""):
            return sym.replace("-", " "), raw
    # First capitalized phrase before buyback
    m = re.search(r"^([A-Za-z][\w\s&.-]{2,40}?)\s+(?:announces|to buy|buyback|buy back)", text, re.I)
    if m:
        return m.group(1).strip().title(), ""
    return "—", ""


def _age_minutes(published: Optional[datetime]) -> int:
    if not published:
        return 9999
    delta = datetime.now(timezone.utc) - published.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() / 60))


def _screener_company_url(company: str, slug: str = "") -> str:
    if slug:
        return f"https://www.screener.in/company/{slug}/"
    if not company or company == "—":
        return SCREENER_BUYBACK_URL
    q = urllib.parse.quote(company)
    return f"https://www.screener.in/company/{q}/"


def _nse_quote_url(raw_ticker: str) -> str:
    if not raw_ticker or not raw_ticker.endswith(".NS"):
        return "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    sym = raw_ticker.replace(".NS", "")
    return f"https://www.nseindia.com/get-quotes/equity?symbol={urllib.parse.quote(sym)}"


@dataclass
class BuybackAnnouncement:
    id: str
    title: str
    published_at: Optional[datetime]
    age_minutes: int
    age_label: str
    source: str
    url: str
    company: str
    raw_ticker: str
    offer_type: str
    buyback_price: Optional[float]
    buyback_pct: Optional[float]
    record_date: str
    last_price: Optional[float]
    premium_pct: Optional[float]
    small_return_est: Optional[float]
    worth_watching: bool
    is_new: bool
    screener_url: str
    nse_url: str
    links: dict = field(default_factory=dict)
    parse_note: str = ""


def _age_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 24 * 60:
        return f"{minutes // 60}h ago"
    return f"{minutes // (24 * 60)}d ago"


def _fetch_last_price(raw: str) -> Optional[float]:
    if not raw:
        return None
    try:
        import yfinance as yf

        t = yf.Ticker(raw)
        fi = getattr(t, "fast_info", {}) or {}
        for k in ("last_price", "regularMarketPrice", "lastPrice"):
            v = fi.get(k) if isinstance(fi, dict) else getattr(fi, k, None)
            if v and float(v) > 0:
                return round(float(v), 2)
        h = t.history(period="5d")
        if h is not None and not h.empty:
            return round(float(h["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return None


def _enrich_announcement(
    *,
    title: str,
    url: str,
    source: str,
    published: Optional[datetime],
    seen: dict[str, str],
    fetch_price: bool,
    company_hint: str = "",
    raw_ticker_hint: str = "",
    screener_slug: str = "",
    parse_text: str = "",
) -> BuybackAnnouncement:
    blob = parse_text or title
    company, raw = resolve_company_ticker(blob)
    if company_hint and company_hint != "—":
        company = company_hint
    if raw_ticker_hint:
        raw = raw_ticker_hint
    elif company != "—" and not raw:
        _, raw = resolve_company_ticker(company)
    offer_type = _parse_offer_type(blob)
    bb_price = _parse_price(blob)
    bb_pct = _parse_pct(blob)
    rec = _parse_record_date(blob)
    aid = _announcement_id(title, published)
    is_new = aid not in seen

    last_px = _fetch_last_price(raw) if fetch_price and raw else None
    premium = None
    small_ret = None
    worth = False
    note_parts: list[str] = []

    if bb_price and last_px and last_px > 0:
        premium = round((bb_price / last_px - 1) * 100, 2)
    elif bb_price:
        note_parts.append("CMP not loaded — set in calculator")
    if not bb_pct:
        note_parts.append("Size % not in headline — check PDF")
    if not rec:
        note_parts.append("Record date — check filing")

    if bb_price and last_px and last_px > 0:
        try:
            est = analyze_buyback(
                BuybackInputs(
                    stock=company,
                    raw_ticker=raw,
                    buyback_pct=bb_pct or 1.0,
                    small_holder_holding_pct=1.0,
                    participation_pct=DEFAULT_PARTICIPATION_PCT,
                    offer_type=offer_type,
                    announcement_price=last_px,
                    buyback_price=bb_price,
                    record_date=rec,
                    post_buyback_price=last_px,
                    status="active",
                ),
                links=get_stock_links(raw) if raw else {},
            )
            small_ret = est.small_expected_return_pct
            worth = est.worth_playing
        except Exception:
            pass

    age_m = _age_minutes(published)
    links = get_stock_links(raw) if raw else {}
    screener_url = _screener_company_url(company, screener_slug)
    links["Screener.in"] = screener_url

    return BuybackAnnouncement(
        id=aid,
        title=title,
        published_at=published,
        age_minutes=age_m,
        age_label=_age_label(age_m),
        source=source,
        url=url or SCREENER_BUYBACK_URL,
        company=company,
        raw_ticker=raw,
        offer_type=offer_type,
        buyback_price=bb_price,
        buyback_pct=bb_pct,
        record_date=rec,
        last_price=last_px,
        premium_pct=premium,
        small_return_est=small_ret,
        worth_watching=worth or (premium is not None and premium >= 5),
        is_new=is_new,
        screener_url=screener_url,
        nse_url=_nse_quote_url(raw),
        links=links,
        parse_note=" · ".join(note_parts),
    )


def _screener_item_to_announcement(
    item: ScreenerBuybackItem,
    *,
    seen: dict[str, str],
    fetch_price: bool,
) -> BuybackAnnouncement:
    slug = item.company_slug or ""
    raw = f"{slug}.NS" if slug else ""
    title = item.title
    blob = f"{title} {item.summary}"
    company = item.company or resolve_company_ticker(title)[0]
    if company == "—" and slug:
        company = slug.replace("-", " ").title()
    if not raw and company != "—":
        _, raw = resolve_company_ticker(company)
    screener_url = (
        f"https://www.screener.in/company/{slug}/" if slug else SCREENER_BUYBACK_URL
    )
    return _enrich_announcement(
        title=title,
        url=item.url or screener_url,
        source=item.source,
        published=item.published,
        seen=seen,
        fetch_price=fetch_price,
        company_hint=company,
        raw_ticker_hint=raw,
        screener_slug=slug,
        parse_text=f"{title} {item.summary}".strip(),
    )


def fetch_buyback_announcements(
    *,
    max_per_query: int = 15,
    max_age_days: int = 45,
    enrich_prices: bool = True,
    max_enrich: int = 30,
    mark_as_seen: bool = True,
    include_screener: bool = True,
) -> list[BuybackAnnouncement]:
    """Aggregate buyback headlines from Screener.in + Google News RSS."""
    seen = load_seen()
    merged: dict[str, BuybackAnnouncement] = {}
    enrich_count = 0

    if include_screener:
        screener_items, _meta = fetch_all_screener_buybacks()
        for item in screener_items:
            do_price = enrich_prices and enrich_count < max_enrich
            ann = _screener_item_to_announcement(item, seen=seen, fetch_price=do_price)
            if do_price and ann.raw_ticker:
                enrich_count += 1
                time.sleep(0.08)
            merged[ann.id] = ann

    for query in BUYBACK_RSS_QUERIES:
        headlines = fetch_google_news_rss(
            query,
            limit=max_per_query,
            max_age_days=max_age_days,
        )
        for h in headlines:
            title = (h.title or "").strip()
            if not title:
                continue
            low = title.lower()
            if not any(k in low for k in ("buyback", "buy back", "buy-back", "repurchase", "tender offer")):
                continue
            aid = _announcement_id(title, h.published)
            if aid in merged:
                continue
            do_price = enrich_prices and enrich_count < max_enrich
            ann = _enrich_announcement(
                title=title,
                url=h.url or "",
                source=h.source or "Google News",
                published=h.published,
                seen=seen,
                fetch_price=do_price,
            )
            if do_price and ann.raw_ticker:
                enrich_count += 1
                time.sleep(0.08)
            merged[aid] = ann

    out = sorted(
        merged.values(),
        key=lambda a: (0 if a.is_new else 1, a.age_minutes, -(a.premium_pct or 0)),
    )
    if mark_as_seen and out:
        mark_seen([a.id for a in out])
    return out


def get_screener_feed_status() -> dict:
    """Lightweight Screener.in config status for the UI (no network)."""
    from screener_buyback import screener_login_configured

    return {
        "login_configured": screener_login_configured(),
        "fulltext_url": SCREENER_BUYBACK_URL,
    }


def announcements_to_rows(announcements: list[BuybackAnnouncement]) -> list[dict]:
    rows = []
    for i, a in enumerate(announcements, start=1):
        rows.append(
            {
                "": "🆕" if a.is_new else "",
                "Age": a.age_label,
                "Company": a.company,
                "Headline": a.title[:100],
                "Type": a.offer_type,
                "Offer ₹": a.buyback_price,
                "Size %": a.buyback_pct,
                "Record date": a.record_date or "—",
                "CMP ₹": a.last_price,
                "Premium %": a.premium_pct,
                "Est. small ret %": a.small_return_est,
                "Worth watch": "✅" if a.worth_watching else "—",
                "Source": a.source,
                "Ticker": a.raw_ticker.replace(".NS", "") if a.raw_ticker else "—",
                "Announcement": a.url,
                "Screener": a.screener_url,
                "NSE": a.nse_url,
                "Parse notes": a.parse_note,
                "id": a.id,
            }
        )
    return rows
