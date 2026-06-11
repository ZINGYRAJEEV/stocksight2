"""
Screener.in — order announcements + bulk/block deals.

Sources (see Screener changelog):
- Full-text search: https://www.screener.in/full-text-search/?q=order&type=announcements
- Bulk deals: https://www.screener.in/trades/bulk/
- Block deals: https://www.screener.in/trades/block/
- Trades hub: https://www.screener.in/trades/
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Optional

from screener_buyback import (
    SCREENER_BASE,
    ScreenerBuybackItem,
    _http_get,
    fetch_company_recent_announcements,
    get_screener_credentials,
    parse_screener_announcement_html,
    resolve_screener_company_id,
    screener_items_to_headlines,
    screener_login_configured,
)

SCREENER_ORDER_URL = f"{SCREENER_BASE}/full-text-search/?q=order&type=announcements"
SCREENER_TRADES_URL = f"{SCREENER_BASE}/trades/"
SCREENER_BULK_DEALS_URL = f"{SCREENER_BASE}/trades/bulk/?trade_type=exclude_intraday"
SCREENER_BLOCK_DEALS_URL = f"{SCREENER_BASE}/trades/block/"

ORDER_SEARCH_PRESETS: dict[str, str] = {
    "order (broad)": "order",
    "order received / win": '"order received" OR "order win" OR "bagged order"',
    "work order / contract": '"work order" OR "contract awarded" OR "letter of intent"',
    "purchase order": '"purchase order" OR "PO received"',
}

_ORDER_POSITIVE = (
    "order received",
    "order win",
    "bagged order",
    "bags order",
    "receives order",
    "received order",
    "work order",
    "purchase order",
    "letter of intent",
    "contract awarded",
    "secures order",
    "order worth",
    "order valued",
    "order from",
    "new order",
    "major order",
)

_ORDER_NEGATIVE = (
    "order of the board",
    "order passed",
    "postal order",
    "standing order",
    "purchase order terms",
    "order book",
    "order management",
    "order confirmation",
    "stop loss order",
    "market order",
    "bulk order facility",
    "order under",
    "registrar",
    "compliance officer",
)


@dataclass
class BulkDealRow:
    company: str
    symbol: str
    client: str
    quantity: str
    price: str
    deal_value: str
    deal_date: str
    deal_type: str
    url: str = ""


def _strip_html(text: str) -> str:
    t = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", t).strip()


def _auth_required(html: str) -> bool:
    return (
        not html
        or "Register - Screener" in html
        or "Get a free account" in html
        or "Login required" in html
    )


def is_order_announcement(text: str) -> bool:
    low = (text or "").lower()
    if any(n in low for n in _ORDER_NEGATIVE):
        return False
    if any(p in low for p in _ORDER_POSITIVE):
        return True
    if " order " in f" {low} " and any(
        w in low for w in ("crore", "cr.", "lakh", "million", "billion", "₹", "rs.", "valued")
    ):
        return True
    return False


def fetch_screener_order_announcements(
    *,
    query: str = "order",
    limit: int = 60,
    strict_filter: bool = True,
) -> tuple[list[ScreenerBuybackItem], str]:
    """
    Full-text announcement search (free Screener login cookies required).
    Returns (items, status) where status is ok | auth_required | error.
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

    if _auth_required(html):
        return [], "auth_required"

    items = parse_screener_announcement_html(html)
    for it in items:
        it.source = "Screener.in order search"

    if strict_filter and items:
        filtered = [
            it for it in items
            if is_order_announcement(f"{it.title} {it.summary}")
        ]
        if filtered:
            items = filtered

    return items[:limit], "ok" if items else "empty"


def _trade_field(tr: str, field: str) -> str:
    m = re.search(
        rf'class="field-{re.escape(field)}"[^>]*>(.*?)</t[dh]>',
        tr,
        flags=re.S | re.I,
    )
    return _strip_html(m.group(1)) if m else ""


def _parse_trades_table(html: str, *, deal_type: str) -> list[BulkDealRow]:
    if _auth_required(html):
        return []

    rows: list[BulkDealRow] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        if 'scope="col"' in tr:
            continue
        company = _trade_field(tr, "company_display")
        if not company:
            continue

        href = ""
        m = re.search(r'href="(/company/[^"]+)"', tr, re.I)
        if m:
            href = SCREENER_BASE + m.group(1)

        symbol = ""
        sm = re.search(r"/company/([^/]+)/", href or tr, re.I)
        if sm:
            symbol = sm.group(1).replace("-", " ").upper()

        person = _trade_field(tr, "_get_person")
        deal_date = _trade_field(tr, "_get_deal_date")
        txn_type = _trade_field(tr, "_get_transaction_type")
        deal_value = _trade_field(tr, "_get_deal_value")

        qty_price = ""
        qp_m = re.search(r"<small>([^<]+)</small>", tr, re.I)
        if qp_m:
            qty_price = _strip_html(qp_m.group(1))

        rows.append(
            BulkDealRow(
                company=company,
                symbol=symbol,
                client=person,
                quantity=qty_price,
                price=txn_type,
                deal_value=deal_value,
                deal_date=deal_date,
                deal_type=deal_type,
                url=href,
            )
        )
    return rows


def fetch_screener_bulk_deals(*, days: int = 30) -> tuple[list[BulkDealRow], str]:
    creds = get_screener_credentials()
    if not creds.get("sessionid"):
        return [], "auth_required"

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    url = (
        f"{SCREENER_BULK_DEALS_URL}&deal_date__gt={since}&o=-4"
    )
    try:
        html = _http_get(url, cookies=creds)
    except Exception:
        return [], "error"

    if _auth_required(html):
        return [], "auth_required"

    rows = _parse_trades_table(html, deal_type="Bulk")
    return rows, "ok" if rows else "empty"


def fetch_screener_block_deals(*, days: int = 30) -> tuple[list[BulkDealRow], str]:
    creds = get_screener_credentials()
    if not creds.get("sessionid"):
        return [], "auth_required"

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    url = f"{SCREENER_BLOCK_DEALS_URL}?deal_date__gt={since}&o=-4"
    try:
        html = _http_get(url, cookies=creds)
    except Exception:
        return [], "error"

    if _auth_required(html):
        return [], "auth_required"

    rows = _parse_trades_table(html, deal_type="Block")
    return rows, "ok" if rows else "empty"


def fetch_company_news_for_symbols(
    symbols: list[str],
    *,
    limit_per_symbol: int = 2,
    max_age_days: int = 30,
) -> list[dict]:
    """Latest Screener company announcements for a list of NSE tickers/slugs."""
    out: list[dict] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = (raw or "").replace(".NS", "").replace(".BO", "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        cid, name, slug = resolve_screener_company_id(sym)
        items = fetch_company_recent_announcements(
            sym,
            limit=limit_per_symbol,
            max_age_days=max_age_days,
        )
        headlines = screener_items_to_headlines(items, limit=limit_per_symbol)
        out.append({
            "symbol": sym,
            "company": name or sym,
            "slug": slug or sym,
            "company_id": cid,
            "headlines": headlines,
            "announcements": items,
            "screener_url": f"{SCREENER_BASE}/company/{slug or sym}/" if slug or sym else "",
        })
    return out


def fetch_bulk_order_intel(
    *,
    order_query: str = "order",
    strict_order_filter: bool = True,
    include_bulk_deals: bool = True,
    include_block_deals: bool = True,
    deal_days: int = 30,
) -> dict:
    """Aggregate all feeds for the Bulk Order page."""
    announcements, ann_status = fetch_screener_order_announcements(
        query=order_query,
        strict_filter=strict_order_filter,
    )
    bulk_rows: list[BulkDealRow] = []
    block_rows: list[BulkDealRow] = []
    bulk_status = "skipped"
    block_status = "skipped"

    if include_bulk_deals:
        bulk_rows, bulk_status = fetch_screener_bulk_deals(days=deal_days)
    if include_block_deals:
        block_rows, block_status = fetch_screener_block_deals(days=deal_days)

    return {
        "announcements": announcements,
        "bulk_deals": bulk_rows,
        "block_deals": block_rows,
        "announcement_status": ann_status,
        "bulk_status": bulk_status,
        "block_status": block_status,
        "login_configured": screener_login_configured(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
