"""
News Scanner — tier classification, scoring, and watchlist sentiment for StockSight.

Price moves on *expectation*, not the headline itself. Tier 1–2 news with volume
confirms tradable moves; Tier 3 is context; Tier 4 is noise (ignore).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    from .screener import (
        NewsHeadline,
        fetch_structured_news,
        raw_ticker_from_display,
    )
    from .market_sentiment import get_macro_context
except ImportError:
    from screener import NewsHeadline, fetch_structured_news, raw_ticker_from_display
    from market_sentiment import get_macro_context  # type: ignore[no-redef]


TIER_LABELS = {
    1: "Tier 1 · Game-changer",
    2: "Tier 2 · Material",
    3: "Tier 3 · Context",
    4: "Tier 4 · Noise",
}

TIER_EMOJI = {1: "🔥", 2: "✅", 3: "ℹ️", 4: "🚫"}

# ── Tier 4 — always ignore ───────────────────────────────────────────────────
_T4_PATTERNS = (
    r"upper\s*circuit", r"uc\s*coming", r"multibagger", r"10x\s*return",
    r"telegram", r"whatsapp", r"tip\s*group", r"pump", r"operator",
    r"influencer", r"viral\s*tweet", r"going\s*to\s*hit", r"target\s*price\s*\d+",
    r"hot\s*tip", r"penny\s*stock", r"guaranteed", r"don't\s*miss",
    r"blast\s*tomorrow", r"jackpot",
)

# ── Tier 1 — game-changers ───────────────────────────────────────────────────
_T1_BULL = (
    r"beat(s|ing)?\s+(estimates|expectations|street)", r"surprise\s+profit",
    r"record\s+(profit|revenue|sales|earnings)", r"\b\d{2,3}%\s*(jump|surge|rise)\s+in\s+(profit|revenue)",
    r"profit\s+(soars|surges|jumps|doubles)", r"revenue\s+(soars|surges|jumps)",
    r"buyback", r"share\s+repurchase", r"acqui(re|sition|red)", r"merger",
    r"takeover", r"order\s+worth", r"contract\s+worth", r"mega\s+deal",
    r"promoter\s+(buy|purchase|acquir)", r"stake\s+(buy|purchase|hike)",
    r"government\s+(approval|clears|nod)", r"\bpli\b", r"subsidy",
    r"fda\s+approv", r"breakthrough", r"bonus\s+issue", r"stock\s+split",
    r"dividend\s+(hike|surprise)",
)
_T1_BEAR = (
    r"fraud", r"scam", r"sebi\s+penalt", r"raid", r"arrest",
    r"default", r"bankruptcy", r"insolvency", r"resign(s|ation)?\s+(ceo|cfo|auditor)",
    r"profit\s+warning", r"guidance\s+cut", r"miss(es|ed)?\s+(estimates|expectations)",
)

# ── Tier 2 — material ────────────────────────────────────────────────────────
_T2_BULL = (
    r"upgrade", r"outperform", r"raises\s+target", r"new\s+product",
    r"launch(es|ed)?", r"expansion", r"capacity\s+add", r"order\s+win",
    r"contract\s+win", r"partnership", r"joint\s+venture", r"rating\s+upgrade",
    r"strong\s+quarter", r"robust\s+results", r"margin\s+expansion",
    r"sector\s+(tailwind|rally)",
)
_T2_BEAR = (
    r"downgrade", r"underperform", r"cuts\s+target", r"weak\s+results",
    r"disappointing", r"slump", r"plunge", r"probe", r"investigation",
    r"lawsuit", r"ban\b", r"fine\b", r"penalty",
)

# ── Tier 3 — context ─────────────────────────────────────────────────────────
_T3_HINTS = (
    r"analyst", r"conference", r"outlook", r"sector\s+note", r"commentary",
    r"interview", r"speaks\s+at", r"attends", r"market\s+wrap",
)


@dataclass
class ClassifiedNews:
    title: str
    tier: int
    tier_label: str
    score: int
    polarity: str
    action: str
    reason: str
    published: Optional[datetime] = None
    age_label: str = ""
    url: str = ""
    publisher: str = ""
    is_fresh: bool = False


@dataclass
class TickerNewsSummary:
    ticker: str
    raw_ticker: str
    news_score: int
    top_tier: int
    top_headline: str
    action: str
    polarity: str
    tier_counts: dict[int, int] = field(default_factory=dict)
    items: list[ClassifiedNews] = field(default_factory=list)
    macro_tone: str = ""
    vol_ratio: Optional[float] = None
    combo_note: str = ""


def _match_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _polarity_from_text(text: str) -> str:
    bull = (
        "surge", "beat", "upgrade", "growth", "profit", "gain", "buy", "record",
        "strong", "approval", "deal", "wins", "raises", "expands", "bull",
    )
    bear = (
        "miss", "fall", "crash", "probe", "downgrade", "loss", "bear", "warn",
        "cuts", "fraud", "ban", "investigation", "slump", "plunge", "default",
    )
    b = sum(1 for w in bull if w in text)
    s = sum(1 for w in bear if w in text)
    if b > s + 1:
        return "Bullish"
    if s > b + 1:
        return "Bearish"
    return "Neutral"


def classify_headline(title: str, summary: str = "") -> ClassifiedNews:
    """Classify one headline into Tier 1–4 with score and action."""
    text = f"{title} {summary}".lower().strip()

    if _match_any(text, _T4_PATTERNS):
        return ClassifiedNews(
            title=title,
            tier=4,
            tier_label=TIER_LABELS[4],
            score=15,
            polarity="Noise",
            action="IGNORE — social / pump noise",
            reason="Matches Tier-4 noise patterns (tips, hype, circuits)",
        )

    if _match_any(text, _T1_BULL):
        pol = "Bullish"
        return ClassifiedNews(
            title=title,
            tier=1,
            tier_label=TIER_LABELS[1],
            score=92,
            polarity=pol,
            action="REACT — verify volume in 2–15 min window; don't chase late candle",
            reason="Tier-1 bullish catalyst (earnings, M&A, policy, buyback, major order)",
        )
    if _match_any(text, _T1_BEAR):
        return ClassifiedNews(
            title=title,
            tier=1,
            tier_label=TIER_LABELS[1],
            score=88,
            polarity="Bearish",
            action="AVOID longs — structural / earnings shock; wait for clarity",
            reason="Tier-1 bearish risk (fraud, default, major miss, probe)",
        )

    if _match_any(text, _T2_BULL):
        return ClassifiedNews(
            title=title,
            tier=2,
            tier_label=TIER_LABELS[2],
            score=72,
            polarity="Bullish",
            action="TRADE with confirmation — volume + sector + trend aligned",
            reason="Tier-2 positive (upgrade, contract, product, strong quarter)",
        )
    if _match_any(text, _T2_BEAR):
        return ClassifiedNews(
            title=title,
            tier=2,
            tier_label=TIER_LABELS[2],
            score=68,
            polarity="Bearish",
            action="CAUTIOUS — reduce size or skip longs until base forms",
            reason="Tier-2 negative (downgrade, weak results, probe-lite)",
        )

    if _match_any(text, _T3_HINTS):
        pol = _polarity_from_text(text)
        return ClassifiedNews(
            title=title,
            tier=3,
            tier_label=TIER_LABELS[3],
            score=45,
            polarity=pol,
            action="CONTEXT ONLY — do not trade this headline alone",
            reason="Tier-3 commentary / analyst / sector note",
        )

    pol = _polarity_from_text(text)
    return ClassifiedNews(
        title=title,
        tier=3,
        tier_label=TIER_LABELS[3],
        score=40,
        polarity=pol,
        action="CONTEXT ONLY — confirm with volume & tier 1–2 news",
        reason="Unclassified — treated as Tier-3 context",
    )


def _age_label(published: Optional[datetime]) -> tuple[str, bool]:
    if published is None:
        return "—", False
    now = datetime.now(timezone.utc)
    delta = now - published.astimezone(timezone.utc)
    mins = int(delta.total_seconds() // 60)
    if mins < 15:
        return f"{mins}m ago · FRESH", True
    if mins < 60:
        return f"{mins}m ago", mins < 30
    hours = mins // 60
    if hours < 48:
        return f"{hours}h ago", hours < 2
    days = hours // 24
    return f"{days}d ago", False


def classify_headlines(headlines: list[NewsHeadline]) -> list[ClassifiedNews]:
    out: list[ClassifiedNews] = []
    for h in headlines:
        c = classify_headline(h.title)
        c.published = h.published
        c.url = h.url
        c.publisher = h.publisher
        c.age_label, c.is_fresh = _age_label(h.published)
        out.append(c)
    return out


def _aggregate_score(items: list[ClassifiedNews]) -> tuple[int, int, str, str]:
    """Returns (news_score, top_tier, top_headline, action)."""
    if not items:
        return 0, 4, "", "No recent headlines — check broader market / sector"

    tradeable = [i for i in items if i.tier <= 2]
    if tradeable:
        best = max(tradeable, key=lambda x: x.score)
        tier = best.tier
        headline = best.title[:100]
        action = best.action
        # Weighted score: best item + bonus for multiple tier1/2
        bonus = min(8, sum(3 for i in tradeable if i.tier == 1) + sum(1 for i in tradeable if i.tier == 2))
        score = min(100, best.score + bonus)
        return score, tier, headline, action

    best = max(items, key=lambda x: x.score)
    if best.tier == 4:
        return 10, 4, best.title[:100], "IGNORE noise — no tradable tier 1–2 catalyst"
    return best.score, best.tier, best.title[:100], best.action


def analyze_ticker(
    display_ticker: str,
    *,
    universe_name: str = "Nifty 50 (NSE)",
    max_age_days: int = 4,
    vol_ratio: Optional[float] = None,
) -> TickerNewsSummary:
    raw = raw_ticker_from_display(display_ticker, universe_name)
    headlines = fetch_structured_news(raw, max_age_days=max_age_days, limit=15)
    items = classify_headlines(headlines)
    score, top_tier, top_hl, action = _aggregate_score(items)

    tier_counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    for i in items:
        tier_counts[i.tier] = tier_counts.get(i.tier, 0) + 1

    market = "US" if not raw.upper().endswith((".NS", ".BO")) and "NSE" not in universe_name.upper() else "NSE"
    macro = get_macro_context(market)

    polarity = "Neutral"
    if items:
        t12 = [i for i in items if i.tier <= 2]
        if t12:
            polarity = t12[0].polarity
        else:
            polarity = items[0].polarity

    combo = _combo_note(score, top_tier, vol_ratio, macro.macro_tone)

    return TickerNewsSummary(
        ticker=display_ticker.strip().upper(),
        raw_ticker=raw,
        news_score=score,
        top_tier=top_tier,
        top_headline=top_hl,
        action=action,
        polarity=polarity,
        tier_counts=tier_counts,
        items=items,
        macro_tone=macro.macro_tone,
        vol_ratio=vol_ratio,
        combo_note=combo,
    )


def _combo_note(score: int, tier: int, vol_ratio: Optional[float], macro: str) -> str:
    parts: list[str] = []
    if tier <= 2 and score >= 70:
        parts.append("News quality: tradable tier")
    elif tier == 4:
        parts.append("News quality: noise only")
    else:
        parts.append("News quality: weak / context")

    if vol_ratio is not None:
        if vol_ratio >= 2.0:
            parts.append(f"Volume {vol_ratio:.1f}× — strong")
        elif vol_ratio < 1.0:
            parts.append(f"Volume {vol_ratio:.1f}× — weak move")
        else:
            parts.append(f"Volume {vol_ratio:.1f}× — OK")

    if macro == "Bullish":
        parts.append("Market: supportive")
    elif macro == "Bearish":
        parts.append("Market: headwind")
    else:
        parts.append("Market: mixed")

    if tier <= 2 and vol_ratio is not None and vol_ratio >= 2.0 and macro != "Bearish":
        parts.append("★ High-probability combo (news + volume + market)")
    return " · ".join(parts)


def parse_watchlist_lines(text: str) -> list[tuple[str, Optional[float]]]:
    """Parse pasted tickers — optional vol ratio per line (RELIANCE 2.5 or RELIANCE,2.5)."""
    rows: list[tuple[str, Optional[float]]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[\s,;\t|]+", line)
        sym = (parts[0] or "").strip().upper()
        if not sym:
            continue
        vol: Optional[float] = None
        if len(parts) > 1:
            try:
                vol = float(parts[1].replace("×", "").replace("x", ""))
            except ValueError:
                pass
        rows.append((sym, vol))
    return rows


def scan_watchlist_sentiment(
    entries: list[tuple[str, Optional[float]]],
    *,
    universe_name: str = "Nifty 50 (NSE)",
) -> list[TickerNewsSummary]:
    summaries: list[TickerNewsSummary] = []
    for sym, vol in entries:
        summaries.append(
            analyze_ticker(sym, universe_name=universe_name, vol_ratio=vol)
        )
    summaries.sort(key=lambda s: (s.news_score, s.vol_ratio or 0), reverse=True)
    return summaries
