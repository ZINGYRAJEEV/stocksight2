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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "press release / LODR order": (
        'LODR "press release" order OR "media release" order OR "wins order" OR "won order"'
    ),
}

# Extra Screener full-text feeds merged into NSE Intraday Intel (press-release order wins).
INTRADAY_PRESS_RELEASE_QUERIES: tuple[str, ...] = (
    '"wins order" OR "won order" OR wins order OR won order',
    'LODR "press release" order OR "media release" order',
    'MW order OR megawatt order OR hyperscale order',
)

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
    "won order",
    "wins order",
)

_WON_WINS_ORDER_RE = re.compile(r"\bw(?:on|ins)\b", re.I)

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
    if _WON_WINS_ORDER_RE.search(low) and re.search(r"\border\b", low):
        return True
    if re.search(r"\b\d+(?:[.,]\d+)?\s*mw\b", low) and "order" in low:
        return True
    if any(k in low for k in ("press release", "media release", "regulation 30", "lodr")):
        if any(
            w in low
            for w in ("order", "contract", "mw", "wins", "won", "awarded", "bagged", "wins")
        ):
            return True
    if " order " in f" {low} " and any(
        w in low for w in ("crore", "cr.", "lakh", "million", "billion", "₹", "rs.", "valued")
    ):
        return True
    return False


def is_exchange_clarification_filing(text: str) -> bool:
    """
    NSE exchange queries on price/volume spikes — not actionable order catalysts.

    Example: "Exchange has sought clarification from … with reference to significant
    increase in price / volume / news item".
    """
    low = (text or "").lower()
    if "sought clarification" in low or "exchange has sought" in low:
        return True
    if "clarification" in low and any(
        k in low
        for k in (
            "price movement",
            "significant increase",
            "significant rise",
            "unusual price",
            "volume movement",
            "news item",
            "with reference to",
        )
    ):
        return True
    return False


def _dedupe_announcement_items(items: list[ScreenerBuybackItem]) -> list[ScreenerBuybackItem]:
    seen: set[str] = set()
    out: list[ScreenerBuybackItem] = []
    for it in items:
        slug = (it.company_slug or "").strip().upper()
        title_key = re.sub(r"\s+", " ", (it.title or "")[:120].lower())
        keys = [f"{slug}|{title_key}"]
        if it.url:
            keys.append(it.url.strip())
        if any(k in seen for k in keys if k):
            continue
        for k in keys:
            if k:
                seen.add(k)
        out.append(it)
    return out


def fetch_merged_order_announcements(
    primary_query: str,
    *,
    strict_filter: bool = False,
    include_press_release_feeds: bool = True,
    exclude_exchange_clarifications: bool = True,
    limit_per_query: int = 45,
    max_items: int = 80,
) -> tuple[list[ScreenerBuybackItem], str]:
    """
    Merge primary order search with press-release / LODR / MW order feeds
    (captures names like KOEL wins 192 MW HyperNext order).
    """
    queries = [primary_query]
    if include_press_release_feeds:
        for q in INTRADAY_PRESS_RELEASE_QUERIES:
            if q not in queries:
                queries.append(q)

    all_items: list[ScreenerBuybackItem] = []
    statuses: list[str] = []
    workers = min(4, max(1, len(queries)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                fetch_screener_order_announcements,
                query=q,
                limit=limit_per_query,
                strict_filter=False,
            )
            for q in queries
        ]
        for fut in futures:
            try:
                items, status = fut.result()
                statuses.append(status)
                all_items.extend(items)
            except Exception:
                statuses.append("error")

    merged = _dedupe_announcement_items(all_items)
    if exclude_exchange_clarifications and merged:
        merged = [
            it for it in merged
            if not is_exchange_clarification_filing(f"{it.title} {it.summary}")
        ]
    if strict_filter and merged:
        filtered = [
            it for it in merged
            if is_order_announcement(f"{it.title} {it.summary}")
        ]
        if filtered:
            merged = filtered

    if "auth_required" in statuses and not merged:
        return [], "auth_required"
    if not merged:
        return [], "empty" if any(s in ("ok", "empty") for s in statuses) else "error"
    return merged[:max_items], "ok"


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
    max_workers: int = 6,
) -> list[dict]:
    """Latest Screener company announcements for a list of NSE tickers/slugs."""
    clean: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = (raw or "").replace(".NS", "").replace(".BO", "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        clean.append(sym)
    if not clean:
        return []

    def _one(sym: str) -> dict:
        cid, name, slug = resolve_screener_company_id(sym)
        items = fetch_company_recent_announcements(
            sym,
            limit=limit_per_symbol,
            max_age_days=max_age_days,
        )
        headlines = screener_items_to_headlines(items, limit=limit_per_symbol)
        return {
            "symbol": sym,
            "company": name or sym,
            "slug": slug or sym,
            "company_id": cid,
            "headlines": headlines,
            "announcements": items,
            "screener_url": f"{SCREENER_BASE}/company/{slug or sym}/" if slug or sym else "",
        }

    workers = min(max_workers, max(1, len(clean)))
    if workers == 1:
        return [_one(sym) for sym in clean]

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, sym): sym for sym in clean}
        for fut in as_completed(futures):
            try:
                out.append(fut.result())
            except Exception:
                sym = futures[fut]
                out.append({
                    "symbol": sym,
                    "company": sym,
                    "slug": sym,
                    "company_id": None,
                    "headlines": [],
                    "announcements": [],
                    "screener_url": "",
                })
    out.sort(key=lambda r: clean.index(r["symbol"]) if r["symbol"] in clean else 999)
    return out


def fetch_bulk_order_intel(
    *,
    order_query: str = "order",
    strict_order_filter: bool = True,
    include_bulk_deals: bool = True,
    include_block_deals: bool = True,
    deal_days: int = 30,
) -> dict:
    """Aggregate all feeds for the Bulk Order page (parallel Screener fetches)."""
    bulk_rows: list[BulkDealRow] = []
    block_rows: list[BulkDealRow] = []
    bulk_status = "skipped"
    block_status = "skipped"
    announcements: list = []
    ann_status = "error"

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_ann = pool.submit(
            fetch_screener_order_announcements,
            query=order_query,
            strict_filter=strict_order_filter,
        )
        f_bulk = (
            pool.submit(fetch_screener_bulk_deals, days=deal_days)
            if include_bulk_deals
            else None
        )
        f_block = (
            pool.submit(fetch_screener_block_deals, days=deal_days)
            if include_block_deals
            else None
        )
        try:
            announcements, ann_status = f_ann.result()
        except Exception:
            announcements, ann_status = [], "error"
        if f_bulk is not None:
            try:
                bulk_rows, bulk_status = f_bulk.result()
            except Exception:
                bulk_rows, bulk_status = [], "error"
        if f_block is not None:
            try:
                block_rows, block_status = f_block.result()
            except Exception:
                block_rows, block_status = [], "error"

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
