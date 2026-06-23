"""
TradingView news + Screener PeAD (post-earnings drift) enrichment for Intraday Intel.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from nse_intraday_intel import IntradayIntelRecord, StockContext


@dataclass
class MarketContextSnapshot:
    tv_news: str = "—"
    tv_news_items: list[dict[str, str]] | None = None
    tv_headline_sentiment: str = "—"
    tv_rating: str = "—"
    tv_sentiment: str = "—"
    tv_sentiment_note: str = "—"
    pead_summary: str = "—"
    pead_score: Optional[float] = None
    pead_qoq_sales_pct: Optional[float] = None
    pead_qoq_profit_pct: Optional[float] = None
    pead_verdict: str = "—"
    market_sentiment_note: str = "—"


def _format_pead_summary(
    qoq: dict,
    verdict: str,
    score: Optional[float],
) -> str:
    qs = qoq.get("qoq_sales_pct")
    qp = qoq.get("qoq_profit_pct")
    latest_q = qoq.get("latest_q") or ""
    if qs is None and qp is None:
        return "—"

    parts: list[str] = []
    if latest_q:
        parts.append(str(latest_q))
    if qs is not None:
        parts.append(f"Sales {qs:+.0f}% QoQ")
    if qp is not None:
        parts.append(f"PAT {qp:+.0f}% QoQ")
    if score is not None:
        parts.append(f"score {score:.0f}")
    if verdict and verdict != "—":
        parts.append(verdict.split("—")[0].strip())
    return " · ".join(parts) if parts else "—"


def fetch_pead_snapshot(
    display_ticker: str,
    ctx: Optional["StockContext"] = None,
) -> dict[str, Any]:
    """QoQ earnings jump + drift verdict from Screener.in quarterly data."""
    from tradeview_analyst import NSE_TV_SYMBOL_ALIASES

    empty: dict[str, Any] = {
        "pead_summary": "—",
        "pead_score": None,
        "pead_qoq_sales_pct": None,
        "pead_qoq_profit_pct": None,
        "pead_verdict": "—",
    }
    ticker = (display_ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")
    ticker = NSE_TV_SYMBOL_ALIASES.get(ticker, ticker)
    if not ticker:
        return empty

    try:
        from screener_in_data import fetch_screener_company_html, fetch_screener_quarterly_qoq, fetch_screener_top_ratios
        from earnings_surprise_screener import _surprise_score, _verdict
    except ImportError:
        return empty

    try:
        html = fetch_screener_company_html(ticker)
        if not html:
            return empty
        qoq = fetch_screener_quarterly_qoq(ticker, html=html)
        ratios = fetch_screener_top_ratios(ticker, html=html)
        qs = qoq.get("qoq_sales_pct")
        qp = qoq.get("qoq_profit_pct")
        if qs is None and qp is None:
            return empty

        pct_ma = getattr(ctx, "pct_vs_ma20", None) if ctx else None
        ret_proxy = getattr(ctx, "ret_6m_pct", None) if ctx else None
        drawdown = getattr(ctx, "drawdown_pct", None) if ctx else None
        roce = ratios.get("roce_pct")

        score = _surprise_score(qs, qp, roce, None, pct_ma, ret_proxy, drawdown)
        verdict = _verdict(qs, qp, pct_ma, ret_proxy, drawdown)

        return {
            "pead_summary": _format_pead_summary(qoq, verdict, score),
            "pead_score": score,
            "pead_qoq_sales_pct": qs,
            "pead_qoq_profit_pct": qp,
            "pead_verdict": verdict,
        }
    except Exception:
        return empty


def fetch_tv_context(display_ticker: str, *, market: str = "NSE") -> dict[str, Any]:
    """TradingView headlines + technical rating/sentiment."""
    from tradeview_analyst import (
        combine_tv_sentiment,
        fetch_tradeview_analyst_data,
        fetch_tradeview_sentiment,
        fetch_tradingview_news,
        score_headline_sentiment,
    )

    empty: dict[str, Any] = {
        "tv_news": "—",
        "tv_news_items": [],
        "tv_headline_sentiment": "—",
        "tv_rating": "—",
        "tv_sentiment": "—",
        "tv_sentiment_note": "—",
    }
    ticker = (display_ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not ticker:
        return empty

    mkt = (market or "NSE").upper()
    items = fetch_tradingview_news(ticker, market=mkt, limit=3)
    titles = [it.get("title", "") for it in items if it.get("title")]
    hl_label, hl_note = score_headline_sentiment(titles)

    analyst = fetch_tradeview_analyst_data(ticker, market=mkt)
    technical = fetch_tradeview_sentiment(ticker, market=mkt)
    overall, note = combine_tv_sentiment(hl_label, technical)

    news_lines: list[str] = []
    for it in items:
        bit = it.get("title", "")
        pub = it.get("published") or ""
        src = it.get("source") or ""
        if pub or src:
            bit = f"{bit} ({src}, {pub})" if src else f"{bit} ({pub})"
        if bit:
            news_lines.append(bit)

    return {
        "tv_news": " | ".join(news_lines) if news_lines else "—",
        "tv_news_items": items,
        "tv_headline_sentiment": hl_label,
        "tv_rating": analyst.get("summary") or "—",
        "tv_sentiment": overall,
        "tv_sentiment_note": f"{note} · {hl_note}" if note != "—" else hl_note,
    }


def fetch_market_context_snapshot(
    display_ticker: str,
    ctx: Optional["StockContext"] = None,
) -> MarketContextSnapshot:
    pead = fetch_pead_snapshot(display_ticker, ctx=ctx)
    tv = fetch_tv_context(display_ticker, market="NSE")

    filing_sent = "—"
    if ctx and getattr(ctx, "trend", None):
        t = str(ctx.trend).upper()
        if "UP" in t or "BULL" in t:
            filing_sent = "Tape bullish"
        elif "DOWN" in t or "BEAR" in t:
            filing_sent = "Tape bearish"

    notes = [n for n in (tv.get("tv_sentiment_note"), pead.get("pead_verdict"), filing_sent) if n and n != "—"]
    market_note = " · ".join(notes[:3]) if notes else "—"

    return MarketContextSnapshot(
        tv_news=tv.get("tv_news") or "—",
        tv_news_items=tv.get("tv_news_items") or [],
        tv_headline_sentiment=tv.get("tv_headline_sentiment") or "—",
        tv_rating=tv.get("tv_rating") or "—",
        tv_sentiment=tv.get("tv_sentiment") or "—",
        tv_sentiment_note=tv.get("tv_sentiment_note") or "—",
        pead_summary=pead.get("pead_summary") or "—",
        pead_score=pead.get("pead_score"),
        pead_qoq_sales_pct=pead.get("pead_qoq_sales_pct"),
        pead_qoq_profit_pct=pead.get("pead_qoq_profit_pct"),
        pead_verdict=pead.get("pead_verdict") or "—",
        market_sentiment_note=market_note,
    )


def enrich_intel_records(
    records: list["IntradayIntelRecord"],
    *,
    delay_sec: float = 0.12,
    max_workers: int = 4,
) -> list["IntradayIntelRecord"]:
    """Attach TradingView news/sentiment and PeAD fields to intel records in place."""
    if not records:
        return records

    snapshots: dict[str, MarketContextSnapshot] = {}
    workers = min(max_workers, max(1, len(records)))

    def _one(rec: "IntradayIntelRecord") -> tuple[str, MarketContextSnapshot]:
        snap = fetch_market_context_snapshot(rec.ticker, rec.stock_context)
        if delay_sec > 0:
            time.sleep(delay_sec)
        return rec.ticker.upper(), snap

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, r) for r in records]
        for fut in as_completed(futures):
            try:
                key, snap = fut.result()
                snapshots[key] = snap
            except Exception:
                continue

    for rec in records:
        snap = snapshots.get(rec.ticker.upper())
        if not snap:
            continue
        rec.tv_news = snap.tv_news
        rec.tv_headline_sentiment = snap.tv_headline_sentiment
        rec.tv_rating = snap.tv_rating
        rec.tv_sentiment = snap.tv_sentiment
        rec.tv_sentiment_note = snap.tv_sentiment_note
        rec.pead_summary = snap.pead_summary
        rec.pead_score = snap.pead_score
        rec.pead_qoq_sales_pct = snap.pead_qoq_sales_pct
        rec.pead_qoq_profit_pct = snap.pead_qoq_profit_pct
        rec.pead_verdict = snap.pead_verdict
        rec.market_sentiment_note = snap.market_sentiment_note

    return records


def enrich_btst_results(
    results: list[Any],
    *,
    market: str = "NSE",
    delay_sec: float = 0.1,
    max_workers: int = 4,
) -> list[Any]:
    """Attach TradingView news and sentiment to BTST scan results."""
    if not results:
        return results

    mkt = (market or "NSE").upper()
    snapshots: dict[str, dict[str, Any]] = {}
    workers = min(max_workers, max(1, len(results)))

    def _one(result: Any) -> tuple[str, dict[str, Any]]:
        snap = fetch_tv_context(result.ticker, market=mkt)
        if delay_sec > 0:
            time.sleep(delay_sec)
        return result.ticker.upper(), snap

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, r) for r in results]
        for fut in as_completed(futures):
            try:
                key, snap = fut.result()
                snapshots[key] = snap
            except Exception:
                continue

    for result in results:
        snap = snapshots.get(result.ticker.upper())
        if not snap:
            continue
        result.tv_news = snap.get("tv_news") or "—"
        result.tv_sentiment = snap.get("tv_sentiment") or "—"
        result.tv_headline_sentiment = snap.get("tv_headline_sentiment") or "—"
        result.tv_rating = snap.get("tv_rating") or "—"
        result.tv_sentiment_note = snap.get("tv_sentiment_note") or "—"

    return results
