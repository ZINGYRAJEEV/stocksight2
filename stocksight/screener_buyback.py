"""
Screener.in buyback announcements — full-text search (login) + recent filings fallback.

Full-text search (the page users bookmark) requires a free Screener.in session:
https://www.screener.in/full-text-search/?q=buyback&type=announcements

Without login we still scan per-company /announcements/recent/{id}/ for Nifty names.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from screener import UNIVERSES

SCREENER_BASE = "https://www.screener.in"
SCREENER_FULLTEXT_URL = (
    f"{SCREENER_BASE}/full-text-search/?q=buyback&type=announcements"
)
_USER_AGENT = (
    "Mozilla/5.0 (compatible; StockSight/1.0; +https://github.com/ZINGYRAJEEV/stocksight2)"
)
_TIMEOUT = 18
_BUYBACK_KW = ("buyback", "buy back", "buy-back", "repurchase", "tender offer")

_ID_CACHE = Path(__file__).resolve().parent / ".screener_company_ids.json"
_SCAN_CURSOR = Path(__file__).resolve().parent / ".screener_buyback_scan_cursor.json"


@dataclass
class ScreenerBuybackItem:
    title: str
    url: str
    summary: str
    age_text: str
    company: str
    company_slug: str
    published: Optional[datetime]
    source: str = "Screener.in"


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_screener_credentials() -> dict[str, str]:
    """sessionid + csrftoken from env or Streamlit secrets (optional)."""
    out: dict[str, str] = {}
    for key in ("sessionid", "csrftoken"):
        env_key = f"SCREENER_{key.upper()}"
        val = os.environ.get(env_key, "").strip()
        if val:
            out[key] = val
    try:
        import streamlit as st

        sec = getattr(st, "secrets", None)
        block = None
        if sec is not None:
            try:
                block = sec.get("screener", {})
            except Exception:
                block = None
        if block:
            for key in ("sessionid", "csrftoken"):
                val = str(block.get(key, "") or "").strip()
                if val:
                    out[key] = val
    except Exception:
        pass
    return out


def screener_login_configured() -> bool:
    creds = get_screener_credentials()
    return bool(creds.get("sessionid"))


def _http_get(url: str, *, cookies: Optional[dict[str, str]] = None) -> str:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": SCREENER_BASE + "/",
    }
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _slug_from_company_url(url: str) -> str:
    m = re.search(r"/company/([^/]+)/", url or "")
    return m.group(1) if m else ""


def _parse_age_minutes(age_text: str) -> Optional[int]:
    if not age_text:
        return None
    low = age_text.strip().lower()
    m = re.match(r"(\d+)\s*(m|min|h|hr|d|day)", low)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("m"):
        return n
    if unit.startswith("h"):
        return n * 60
    return n * 24 * 60


def _published_from_age(age_text: str) -> Optional[datetime]:
    mins = _parse_age_minutes(age_text)
    if mins is None:
        return None
    return datetime.now(timezone.utc) - timedelta(minutes=mins)


def parse_screener_announcement_html(
    html: str,
    *,
    default_company: str = "",
    default_slug: str = "",
) -> list[ScreenerBuybackItem]:
    """Parse Screener list-links announcement blocks."""
    if not html or "Login required" in html or "Get a free account" in html:
        return []
    items: list[ScreenerBuybackItem] = []
    for block in re.findall(
        r'<li[^>]*class="[^"]*overflow-wrap-anywhere[^"]*"[^>]*>(.*?)</li>',
        html,
        flags=re.S | re.I,
    ):
        href_m = re.search(r'<a\s+href="([^"]+)"', block, re.I)
        title_m = re.search(r"<a[^>]*>\s*([^<]+?)\s*</a>", block, re.S | re.I)
        desc_m = re.search(r'class="ink-600 smaller">([^<]*)</div>', block, re.I)
        if not title_m:
            continue
        title = re.sub(r"\s+", " ", title_m.group(1)).strip()
        if not title:
            continue
        url = (href_m.group(1) if href_m else "").strip()
        summary = (desc_m.group(1) if desc_m else "").strip()
        age_text = ""
        if summary and " - " in summary:
            age_text, _, rest = summary.partition(" - ")
            age_text = age_text.strip()
            summary = rest.strip()
        company = default_company
        slug = default_slug
        co_m = re.search(r'/company/([^/]+)/[^"]*"[^>]*>([^<]+)</a>', block, re.I)
        if co_m:
            slug = co_m.group(1)
            company = re.sub(r"\s+", " ", co_m.group(2)).strip()
        items.append(
            ScreenerBuybackItem(
                title=title,
                url=url,
                summary=summary,
                age_text=age_text,
                company=company or slug.replace("-", " ").title(),
                company_slug=slug,
                published=_published_from_age(age_text),
                source="Screener.in",
            )
        )
    return items


def _is_buyback_text(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in _BUYBACK_KW)


def resolve_screener_company_id(ticker: str) -> tuple[Optional[int], str, str]:
    """Resolve NSE ticker → (screener_id, company_name, slug)."""
    sym = (ticker or "").replace(".NS", "").replace(".BO", "").strip()
    if not sym:
        return None, "", ""
    cache = _load_json(_ID_CACHE)
    hit = cache.get(sym.upper())
    if hit and hit.get("id"):
        return int(hit["id"]), str(hit.get("name", "")), str(hit.get("slug", sym))

    q = urllib.parse.quote(sym.replace("-", " "))
    url = f"{SCREENER_BASE}/api/company/search/?q={q}&limit=8"
    try:
        raw = _http_get(url)
        data = json.loads(raw)
    except Exception:
        return None, "", sym

    best = None
    sym_u = sym.upper().replace("-", "")
    for row in data if isinstance(data, list) else []:
        slug = _slug_from_company_url(str(row.get("url", "")))
        if slug.upper().replace("-", "") == sym_u:
            best = row
            break
    if best is None and data:
        best = data[0]

    if not best:
        return None, "", sym

    cid = int(best["id"])
    name = str(best.get("name", sym))
    slug = _slug_from_company_url(str(best.get("url", ""))) or sym
    cache[sym.upper()] = {"id": cid, "name": name, "slug": slug}
    _save_json(_ID_CACHE, cache)
    return cid, name, slug


def fetch_screener_fulltext_buybacks(
    *,
    query: str = "buyback",
    limit: int = 40,
) -> tuple[list[ScreenerBuybackItem], str]:
    """
    Fetch Screener.in full-text search announcements (requires free login cookies).

    Returns (items, status) where status is 'ok' | 'auth_required' | 'error'.
    """
    creds = get_screener_credentials()
    if not creds.get("sessionid"):
        return [], "auth_required"

    q = urllib.parse.quote(query)
    url = f"{SCREENER_BASE}/full-text-search/?q={q}&type=announcements"
    try:
        html = _http_get(url, cookies=creds)
    except Exception:
        return [], "error"

    if "Register - Screener" in html or "Get a free account" in html:
        return [], "auth_required"

    items = parse_screener_announcement_html(html)
    if not items:
        # Full-text page may use a different layout — parse generic result rows.
        for block in re.findall(
            r'<div[^>]*class="[^"]*flex[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html,
            flags=re.S,
        ):
            if "buyback" not in block.lower() and "buy back" not in block.lower():
                continue
            title_m = re.search(r"<a[^>]*href=\"([^\"]+)\"[^>]*>([^<]+)</a>", block, re.I)
            if not title_m:
                continue
            url_ = title_m.group(1).strip()
            title = re.sub(r"\s+", " ", title_m.group(2)).strip()
            co_m = re.search(r'/company/([^/]+)/[^"]*"[^>]*>([^<]+)</a>', block, re.I)
            slug = co_m.group(1) if co_m else ""
            company = co_m.group(2).strip() if co_m else slug.replace("-", " ").title()
            items.append(
                ScreenerBuybackItem(
                    title=title,
                    url=url_,
                    summary="",
                    age_text="",
                    company=company,
                    company_slug=slug,
                    published=None,
                    source="Screener.in full-text",
                )
            )

    out = [i for i in items if _is_buyback_text(f"{i.title} {i.summary}")]
    if not out:
        out = items
    return out[:limit], "ok"


def _universe_tickers() -> list[str]:
    syms = UNIVERSES.get("Nifty 500 (NSE)", []) or UNIVERSES.get("Nifty 50 (NSE)", [])
    out: list[str] = []
    seen: set[str] = set()
    for raw in syms:
        sym = raw.replace(".NS", "").replace(".BO", "").upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _announcements_from_paths(
    cid: int,
    name: str,
    slug: str,
    paths: tuple[str, ...],
) -> list[ScreenerBuybackItem]:
    out: list[ScreenerBuybackItem] = []
    seen: set[str] = set()
    for path in paths:
        try:
            html = _http_get(f"{SCREENER_BASE}{path}")
        except Exception:
            continue
        for item in parse_screener_announcement_html(
            html, default_company=name, default_slug=slug
        ):
            if not _is_buyback_text(f"{item.title} {item.summary}"):
                continue
            key = f"{item.title}|{item.url}"
            if key in seen:
                continue
            seen.add(key)
            item.source = "Screener.in recent"
            out.append(item)
    return out


def _recent_buybacks_for_symbol(sym: str) -> list[ScreenerBuybackItem]:
    cid, name, slug = resolve_screener_company_id(sym)
    if not cid:
        return []
    return _announcements_from_paths(
        cid,
        name,
        slug,
        (
            f"/announcements/recent/{cid}/",
            f"/announcements/important/{cid}/",
        ),
    )


def fetch_screener_recent_buybacks(
    *,
    batch_size: int = 24,
    max_items: int = 25,
    workers: int = 6,
) -> list[ScreenerBuybackItem]:
    """
    Fallback without login: rotate through Nifty 500 and pull /announcements/recent/{id}/.
    """
    tickers = _universe_tickers()
    if not tickers:
        return []

    cursor = _load_json(_SCAN_CURSOR)
    offset = int(cursor.get("offset", 0)) % len(tickers)
    batch = [tickers[(offset + i) % len(tickers)] for i in range(batch_size)]
    found: list[ScreenerBuybackItem] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_recent_buybacks_for_symbol, sym): sym for sym in batch}
        for fut in as_completed(futures):
            try:
                found.extend(fut.result())
            except Exception:
                continue
            if len(found) >= max_items:
                break

    cursor["offset"] = (offset + batch_size) % len(tickers)
    cursor["updated"] = datetime.now(timezone.utc).isoformat()
    _save_json(_SCAN_CURSOR, cursor)
    found.sort(key=lambda x: _parse_age_minutes(x.age_text) or 99999)
    return found[:max_items]


def fetch_all_screener_buybacks(
    *,
    use_fulltext: bool = True,
    use_recent_scan: bool = True,
    recent_batch: int = 40,
) -> tuple[list[ScreenerBuybackItem], dict]:
    """
    Merge Screener.in sources. Metadata reports auth status and counts.
    """
    meta: dict = {
        "fulltext_status": "skipped",
        "fulltext_count": 0,
        "recent_count": 0,
        "login_configured": screener_login_configured(),
    }
    merged: dict[str, ScreenerBuybackItem] = {}

    if use_fulltext:
        items, status = fetch_screener_fulltext_buybacks()
        meta["fulltext_status"] = status
        meta["fulltext_count"] = len(items)
        for it in items:
            key = f"{it.company}|{it.title}|{it.url}"
            merged[key] = it

    if use_recent_scan and meta["fulltext_status"] != "ok":
        recent = fetch_screener_recent_buybacks(batch_size=min(recent_batch, 24))
        meta["recent_count"] = len(recent)
        for it in recent:
            key = f"{it.company}|{it.title}|{it.url}"
            if key not in merged:
                merged[key] = it

    return list(merged.values()), meta
