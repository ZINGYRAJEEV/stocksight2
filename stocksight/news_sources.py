"""
Multi-source news fetch for News Scanner — Yahoo Finance API + Google News RSS.

Yahoo ``ticker.news`` is often empty or stale on Streamlit Cloud; Google News RSS
fills gaps with recent India/US headlines.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from screener import NewsHeadline

_USER_AGENT = (
    "Mozilla/5.0 (compatible; StockSight/1.0; +https://github.com/ZINGYRAJEEV/stocksight2)"
)
_FETCH_TIMEOUT = 18

DEFAULT_NEWS_MAX_AGE_DAYS = 7
RELAX_NEWS_MAX_AGE_DAYS = 30


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "en-IN,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
        return resp.read()


def _parse_http_date(raw: str) -> Optional[datetime]:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_title_key(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").lower().strip())
    return t[:80]


def _display_symbol(raw: str) -> str:
    return (raw or "").replace(".NS", "").replace(".BO", "").strip().upper()


def resolve_company_name(raw_ticker: str) -> str:
    """Best-effort company name for search queries."""
    raw = (raw_ticker or "").strip()
    if not raw:
        return ""
    try:
        import yfinance as yf

        info = getattr(yf.Ticker(raw), "info", None) or {}
        for key in ("longName", "shortName", "displayName"):
            name = str(info.get(key) or "").strip()
            if name and len(name) > 2:
                return name
    except Exception:
        pass
    sym = _display_symbol(raw)
    return sym.replace("-", " ").strip()


def _nse_search_symbol(raw_ticker: str) -> str:
    sym = _display_symbol(raw_ticker)
    if raw_ticker.upper().endswith(".BO"):
        return f"BSE:{sym}"
    return f"NSE:{sym}"


def _headline_matches_nse_ticker(title: str, sym: str) -> bool:
    """
    Drop headlines tied to the wrong exchange (e.g. ASX:ACE for NSE:ACE).
    """
    if not title or not sym:
        return True
    t = title.strip()
    other_exchanges = ("ASX", "LSE", "TSE", "HKEX", "TSX", "FWB", "XETRA")
    for ex in other_exchanges:
        if re.search(rf"\b{ex}\s*:\s*{re.escape(sym)}\b", t, re.I):
            return False
        if re.search(rf"\b{ex}\b", t, re.I) and re.search(
            rf"\b{re.escape(sym)}\b", t, re.I
        ) and not re.search(r"\b(NSE|BSE|India|Indian)\b", t, re.I):
            return False
    return True


def _google_news_queries(raw_ticker: str, company: str) -> list[str]:
    sym = _display_symbol(raw_ticker)
    is_india = raw_ticker.upper().endswith((".NS", ".BO"))
    queries: list[str] = []
    if is_india:
        nse_tag = _nse_search_symbol(raw_ticker)
        queries.append(f"{nse_tag} stock news")
        queries.append(f"{sym}.NS NSE stock news")
    if company and company.upper() != sym:
        if is_india:
            queries.append(f"{company} stock India NSE")
            queries.append(f"{company} share price news")
        else:
            queries.append(f"{company} stock news")
            queries.append(f"{sym} stock earnings")
    if is_india:
        queries.append(f"{sym} NSE stock news")
    queries.append(f"{sym} stock news")
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out[:4]


def fetch_google_news_rss(
    query: str,
    *,
    limit: int = 12,
    max_age_days: int = 14,
    hl: str = "en-IN",
    gl: str = "IN",
) -> list["NewsHeadline"]:
    from screener import NewsHeadline

    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:en"
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(max_age_days))
    out: list[NewsHeadline] = []

    try:
        root = ET.fromstring(_http_get(url))
    except Exception:
        return []

    for item in root.findall(".//item")[: max(limit * 2, 20)]:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue
        published = _parse_http_date(pub_el.text if pub_el is not None else "")
        if published is not None and published < cutoff:
            continue
        link = (link_el.text or "").strip() if link_el is not None else ""
        out.append(
            NewsHeadline(
                title=title,
                published=published,
                url=link,
                publisher="Google News",
                source="Google News",
            )
        )
        if len(out) >= limit:
            break
    return out


def fetch_yahoo_finance_news(
    raw_ticker: str,
    *,
    limit: int = 15,
    max_age_days: int = 14,
) -> list["NewsHeadline"]:
    """yfinance ``Ticker.news`` with nested ``content`` shape."""
    from screener import (
        NewsHeadline,
        _news_item_published_dt,
        _news_item_publisher,
        _news_item_title,
        _news_item_url,
    )

    try:
        import yfinance as yf

        news = getattr(yf.Ticker(raw_ticker), "news", None) or []
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=int(max_age_days))
    out: list[NewsHeadline] = []
    for item in news:
        if not isinstance(item, dict):
            continue
        title = _news_item_title(item)
        if not title:
            continue
        published = _news_item_published_dt(item)
        if published is not None and published < cutoff:
            continue
        pub = _news_item_publisher(item) or "Yahoo Finance"
        out.append(
            NewsHeadline(
                title=title,
                published=published,
                url=_news_item_url(item),
                publisher=pub,
                source="Yahoo Finance",
            )
        )
    out.sort(
        key=lambda h: h.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return out[:limit]


def fetch_aggregated_structured_news(
    raw_ticker: str,
    *,
    limit: int = 15,
    max_age_days: int = 7,
    relax_days_if_empty: int = 30,
    skip_company_lookup: bool = False,
) -> list["NewsHeadline"]:
    """
    Merge Yahoo Finance + Google News RSS; dedupe by headline.

    If nothing falls within ``max_age_days``, retries with ``relax_days_if_empty``.
    """
    raw = (raw_ticker or "").strip()
    if not raw:
        return []

    is_india = raw.upper().endswith((".NS", ".BO"))
    hl, gl = ("en-IN", "IN") if is_india else ("en-US", "US")
    company = _display_symbol(raw) if skip_company_lookup else resolve_company_name(raw)

    def _collect(age_days: int) -> list["NewsHeadline"]:
        from screener import NewsHeadline

        seen: set[str] = set()
        merged: list[NewsHeadline] = []

        sym = _display_symbol(raw)

        def _add(batch: list[NewsHeadline]) -> None:
            for h in batch:
                if is_india and not _headline_matches_nse_ticker(h.title, sym):
                    continue
                key = _normalize_title_key(h.title)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(h)

        _add(fetch_yahoo_finance_news(raw, limit=limit, max_age_days=age_days))
        per_q = max(6, limit // 2)
        for query in _google_news_queries(raw, company):
            _add(
                fetch_google_news_rss(
                    query,
                    limit=per_q,
                    max_age_days=age_days,
                    hl=hl,
                    gl=gl,
                )
            )
            if len(merged) >= limit:
                break

        merged.sort(
            key=lambda h: h.published or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return merged[:limit]

    fresh = _collect(max_age_days)
    if fresh:
        return fresh
    return _collect(relax_days_if_empty)


def news_source_summary(headlines: list["NewsHeadline"]) -> str:
    """Comma-separated list of sources present in a headline batch."""
    srcs: list[str] = []
    for h in headlines:
        s = (getattr(h, "source", None) or h.publisher or "").strip()
        if s and s not in srcs:
            srcs.append(s)
    return ", ".join(srcs) if srcs else "—"
