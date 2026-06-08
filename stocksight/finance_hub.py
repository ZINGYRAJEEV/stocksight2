"""
Finance Hub — Google Finance-style portfolio news, tracking, and chat Q&A.

Uses existing watchlist/positions, Yahoo quotes, and Yahoo + Google News RSS
(no official Google Finance API — links open google.com/finance in browser).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    from news_scanner import TickerNewsSummary, analyze_ticker
    from screener import get_stock_links
    from watchlist_store import list_open_positions, load_watchlist
except ImportError:
    from .news_scanner import TickerNewsSummary, analyze_ticker  # type: ignore[no-redef]
    from .screener import get_stock_links  # type: ignore[no-redef]
    from .watchlist_store import list_open_positions, load_watchlist  # type: ignore[no-redef]

META = {
    "id": "finance_hub",
    "title": "Finance Hub",
    "emoji": "📊",
    "nav_title": "Finance Hub",
}


@dataclass
class NewsFeedRow:
    ticker: str
    raw_ticker: str
    in_portfolio: bool
    news_score: int
    top_tier: int
    top_headline: str
    action: str
    news_sources: str
    polarity: str
    google_finance: str
    items_count: int = 0


@dataclass
class ChatNewsReply:
    text: str
    summaries: list[TickerNewsSummary] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)


def tracked_symbols(*, include_watchlist: bool = True, include_positions: bool = True) -> list[dict]:
    """Unique symbols from open positions and/or full watchlist."""
    seen: set[str] = set()
    out: list[dict] = []

    def _add(row: dict, in_pf: bool) -> None:
        raw = str(row.get("raw_ticker") or "").strip()
        if not raw or raw in seen:
            return
        seen.add(raw)
        out.append(
            {
                "raw_ticker": raw,
                "ticker": raw.replace(".NS", "").replace(".BO", ""),
                "in_portfolio": in_pf,
                "note": str(row.get("note") or ""),
            }
        )

    if include_positions:
        for r in list_open_positions():
            _add(r, True)
    if include_watchlist:
        for r in load_watchlist():
            _add(r, bool(r.get("qty") and r.get("entry_price")))
    return out


def _known_symbol_map() -> dict[str, str]:
    """Upper display symbol / raw → raw ticker."""
    m: dict[str, str] = {}
    for row in tracked_symbols():
        raw = row["raw_ticker"]
        disp = row["ticker"].upper()
        m[disp] = raw
        m[raw.upper()] = raw
    return m


def resolve_tickers_from_text(text: str) -> list[str]:
    """
    Pull ticker symbols from chat text (watchlist + common NSE/US patterns).
    """
    text = (text or "").strip()
    if not text:
        return []

    sym_map = _known_symbol_map()
    found: list[str] = []
    seen: set[str] = set()

    for token in re.findall(r"[A-Za-z][A-Za-z0-9.\-]{0,14}", text):
        t = token.strip().upper().replace(".NS", "").replace(".BO", "")
        if t in seen:
            continue
        if t in sym_map:
            seen.add(t)
            found.append(sym_map[t])
            continue
        if token.upper().endswith((".NS", ".BO")):
            raw = token.upper() if "." in token else f"{t}.NS"
            seen.add(t)
            found.append(raw)
            continue
        # Bare symbol mention (3+ letters)
        if len(t) >= 3 and t.isalpha() and t in sym_map:
            seen.add(t)
            found.append(sym_map[t])

    # Explicit "news on X" / "about X"
    for m in re.finditer(
        r"(?:news|headlines|update|happening|status)\s+(?:on|for|about)\s+([A-Za-z][\w.\-]+)",
        text,
        re.I,
    ):
        sub = m.group(1).upper().replace(".NS", "").replace(".BO", "")
        raw = sym_map.get(sub) or (f"{sub}.NS" if len(sub) <= 12 else sub)
        if raw not in seen:
            seen.add(sub)
            found.append(raw)

    return found[:8]


def build_news_feed(
    symbols: list[dict],
    *,
    max_age_days: int = 7,
    max_symbols: int = 30,
    delay_sec: float = 0.12,
) -> list[NewsFeedRow]:
    rows: list[NewsFeedRow] = []
    for row in symbols[:max_symbols]:
        raw = row["raw_ticker"]
        try:
            s = analyze_ticker(
                raw,
                universe_name="Nifty 500 (NSE)",
                max_age_days=max_age_days,
                fast_universe=True,
            )
        except Exception:
            continue
        links = get_stock_links(raw)
        rows.append(
            NewsFeedRow(
                ticker=row["ticker"],
                raw_ticker=raw,
                in_portfolio=bool(row.get("in_portfolio")),
                news_score=s.news_score,
                top_tier=s.top_tier,
                top_headline=(s.top_headline or "—")[:120],
                action=(s.action or "—")[:100],
                news_sources=s.news_sources or "—",
                polarity=s.polarity or "—",
                google_finance=links.get("Google Finance", ""),
                items_count=len(s.items),
            )
        )
        if delay_sec > 0:
            time.sleep(delay_sec)
    rows.sort(key=lambda r: (-r.news_score, r.top_tier))
    return rows


def _format_summary_block(s: TickerNewsSummary) -> str:
    links = get_stock_links(s.raw_ticker)
    gf = links.get("Google Finance", "")
    lines = [
        f"**{s.ticker}** · News score **{s.news_score}**/100 · Tier **{s.top_tier}** · {s.polarity}",
        f"Top headline: {s.top_headline or '—'}",
        f"Action: {s.action or '—'}",
        f"Sources: {s.news_sources or 'Yahoo + Google News'}",
    ]
    if s.combo_note:
        lines.append(f"Context: {s.combo_note}")
    if s.items:
        extra = [f"• {i.title[:90]}" for i in s.items[:4] if i.title]
        if extra:
            lines.append("Recent headlines:\n" + "\n".join(extra))
    if gf:
        lines.append(f"[Open on Google Finance]({gf})")
    return "\n".join(lines)


def news_chat_reply(
    query: str,
    *,
    max_age_days: int = 7,
    explicit_tickers: Optional[list[str]] = None,
) -> ChatNewsReply:
    """Rule-based news assistant (no LLM) — fetches live headlines for named tickers."""
    q = (query or "").strip()
    if not q:
        return ChatNewsReply(
            "Ask something like: *What's the news on RELIANCE?* or *Headlines for my portfolio*.",
        )

    tickers: list[str] = list(explicit_tickers or [])
    if not tickers:
        low = q.lower()
        if any(k in low for k in ("portfolio", "my holdings", "my positions", "watchlist")):
            tickers = [s["raw_ticker"] for s in tracked_symbols()][:12]
        else:
            tickers = resolve_tickers_from_text(q)

    if not tickers:
        syms = ", ".join(sorted(_known_symbol_map().keys())[:12])
        return ChatNewsReply(
            f"I couldn't match a ticker in your message. "
            f"Try a symbol from your watchlist (e.g. {syms}…) or add holdings on the **Portfolio** tab.\n\n"
            "Examples:\n"
            "- `News on TCS`\n"
            "- `What's happening with RELIANCE?`\n"
            "- `Headlines for my portfolio`",
        )

    summaries: list[TickerNewsSummary] = []
    blocks: list[str] = []
    for raw in tickers:
        try:
            s = analyze_ticker(
                raw,
                universe_name="Nifty 500 (NSE)",
                max_age_days=max_age_days,
                fast_universe=True,
            )
            summaries.append(s)
            blocks.append(_format_summary_block(s))
        except Exception as exc:
            blocks.append(f"**{raw}** — could not load news ({exc}).")

    intro = f"Here's what I found for **{len(summaries)}** symbol(s) (Yahoo + Google News, last {max_age_days}d):\n\n"
    return ChatNewsReply(intro + "\n\n---\n\n".join(blocks), summaries=summaries, tickers=tickers)
