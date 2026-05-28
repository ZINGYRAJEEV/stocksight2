"""
high_profit.py — Curated high-profit archetype screeners (monopoly, platform, etc.).

Each archetype has a watchlist with static sector / market-share metadata; live
PE, volume, RSI, valuation, fundamentals, and composite scores come from yfinance.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from screener import UNIVERSES, compute_rsi, compute_volume_ratio, get_pe, get_stock_links

SCAN_SOURCES = ["Curated watchlist"] + list(UNIVERSES.keys())

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────
# Archetype registry + curated watchlists
# ─────────────────────────────────────────────────────────────

ARCHETYPES: dict[str, dict] = {
    "monopoly": {
        "title": "Monopoly / Dominant Share",
        "nav_title": "Low Risk · Monopoly",
        "risk_tier": "low",
        "risk_label": "Low Risk",
        "emoji": "👑",
        "color": "#f0b429",
        "tier_precautions": (
            "Near-monopoly names can trade at very high PE; regulation or new entrants are the main tail risks."
        ),
        "description": (
            "Near-monopoly businesses with pricing power and high barriers. "
            "PE can be rich; momentum and business quality matter more than value alone."
        ),
        "audience": "Long-term investors seeking durable franchises with pricing power and lower business risk.",
        "purpose": "Scores curated monopoly-style names on live PE, volume, RSI, and a composite quality/momentum score.",
        "filter_note": "Curated watchlist · live PE / vol / RSI · ranked by composite /100",
        "defaults": {"pe_max": 120.0, "vol_min": 1.2, "rsi_range": (50, 100)},
        "criteria_pe": "Any (rich OK)",
        "signal": "BUY / Quality compounder",
        "timeframe": "Medium · 6–24 months",
    },
    "platform": {
        "title": "Platform / Network Effect",
        "nav_title": "High Risk · Platform",
        "risk_tier": "high",
        "risk_label": "High Risk",
        "emoji": "🌐",
        "color": "#4db8ff",
        "tier_precautions": (
            "Platforms face competition, regulation, and profitability swings — expect higher drawdowns."
        ),
        "description": (
            "Two-sided or aggregator platforms where scale reinforces growth. "
            "Favour rising volume with intact trend."
        ),
        "audience": "Growth investors comfortable with volatility and platform business models.",
        "purpose": "Screens platform archetype watchlist names for trend, liquidity, and composite score—not a full startup screener.",
        "filter_note": "Curated platform names · ranked by composite /100",
        "defaults": {"pe_max": 100.0, "vol_min": 1.0, "rsi_range": (45, 100)},
        "criteria_pe": "5 – 100",
        "signal": "BUY / Growth platform",
        "timeframe": "Medium · 3–18 months",
    },
    "regulatory_moat": {
        "title": "Regulatory Moat",
        "nav_title": "Low Risk · Regulatory Moat",
        "risk_tier": "low",
        "risk_label": "Low Risk",
        "emoji": "🏛️",
        "color": "#00e5a0",
        "tier_precautions": (
            "Policy or SEBI rule changes can alter economics; rich valuations still need disciplined entry."
        ),
        "description": (
            "Licence- or regulation-protected franchises (exchanges, depositories, clearing). "
            "Typically asset-light with very high margins."
        ),
        "audience": "Conservative investors who like regulated, licence-backed cash generators.",
        "purpose": "Ranks exchange/clearing-style names on technicals plus static moat metadata and Buy? / Precautions columns.",
        "filter_note": "Licence-backed franchises · ranked by composite /100",
        "defaults": {"pe_max": 120.0, "vol_min": 1.0, "rsi_range": (48, 100)},
        "criteria_pe": "Any",
        "signal": "BUY / Hold moat",
        "timeframe": "Long · 12–36 months",
    },
    "duopoly": {
        "title": "Duopoly",
        "nav_title": "Medium Risk · Duopoly",
        "risk_tier": "medium",
        "risk_label": "Medium Risk",
        "emoji": "⚖️",
        "color": "#c77dff",
        "tier_precautions": (
            "Duopolies are stable but not immune to price wars, share shifts, or disruption from a third player."
        ),
        "description": (
            "Markets split between two dominant players — stable economics, less disruption risk than fragmented sectors."
        ),
        "audience": "Investors wanting oligopoly stability without paying for a pure monopoly premium.",
        "purpose": "Applies PE/volume/RSI filters to duopoly watchlist names and surfaces leadership / precaution notes.",
        "filter_note": "Two-player markets · ranked by composite /100",
        "defaults": {"pe_max": 80.0, "vol_min": 1.2, "rsi_range": (48, 100)},
        "criteria_pe": "5 – 80",
        "signal": "BUY / Watch leader",
        "timeframe": "Medium · 6–18 months",
    },
    "category_leader": {
        "title": "Category Leader",
        "nav_title": "Medium Risk · Category Leader",
        "risk_tier": "medium",
        "risk_label": "Medium Risk",
        "emoji": "🥇",
        "color": "#ff9d42",
        "tier_precautions": (
            "Leaders can lose share in slowdowns; premium multiples compress if growth disappoints."
        ),
        "description": (
            "#1 or #2 share in a growing category — brand + distribution moat, not always legal monopoly."
        ),
        "audience": "Investors targeting category winners in consumer, pharma, or industrial niches.",
        "purpose": "Filters category-leader watchlist for momentum and valuation; compare Buy? flags across peers.",
        "filter_note": "#1/#2 category share · ranked by composite /100",
        "defaults": {"pe_max": 90.0, "vol_min": 1.3, "rsi_range": (50, 100)},
        "criteria_pe": "5 – 90",
        "signal": "BUY / Category winner",
        "timeframe": "Medium · 6–24 months",
    },
}

# Static metadata: exchange_line, badge, optional catalyst flags (display only)
_WATCHLIST: dict[str, list[dict]] = {
    "monopoly": [
        {
            "ticker": "MCX.NS",
            "exchange_line": "SE · BSE 534091 · Financial Svcs-Specialty",
            "badge": "MONOPOLY · 95.9% MARKET SHARE",
            "market_share_pct": 95.9,
            "catalysts": ["ATH breakout", "MSCI inclusion"],
        },
        {
            "ticker": "CDSL.NS",
            "exchange_line": "EQ · BSE 542669 · Financial Services",
            "badge": "MONOPOLY · ~89% DEPOSITORY SHARE",
            "market_share_pct": 89.0,
            "catalysts": [],
        },
        {
            "ticker": "CAMS.NS",
            "exchange_line": "EQ · BSE 543232 · Financial Services",
            "badge": "MONOPOLY · ~70% RTA SHARE",
            "market_share_pct": 70.0,
            "catalysts": [],
        },
        {
            "ticker": "IEX.NS",
            "exchange_line": "EQ · BSE 540750 · Power Exchange",
            "badge": "MONOPOLY · ~94% SHORT-TERM POWER",
            "market_share_pct": 94.0,
            "catalysts": [],
        },
        {
            "ticker": "IRCTC.NS",
            "exchange_line": "EQ · BSE 542830 · Travel & Leisure",
            "badge": "MONOPOLY · RAIL CATERING & TICKETING",
            "market_share_pct": 100.0,
            "catalysts": [],
        },
        {
            "ticker": "PAGEIND.NS",
            "exchange_line": "EQ · BSE 532827 · Consumer Durables",
            "badge": "MONOPOLY · DOMINANT ZIPPER NICHE",
            "market_share_pct": 80.0,
            "catalysts": [],
        },
    ],
    "platform": [
        {
            "ticker": "NAUKRI.NS",
            "exchange_line": "EQ · BSE 532777 · Internet & Software",
            "badge": "PLATFORM · #1 JOB PORTAL (INDIA)",
            "market_share_pct": 60.0,
            "catalysts": [],
        },
        {
            "ticker": "POLICYBZR.NS",
            "exchange_line": "EQ · BSE 543390 · Insurance Aggregator",
            "badge": "PLATFORM · LEADING INSURTECH",
            "market_share_pct": 55.0,
            "catalysts": [],
        },
        {
            "ticker": "INDIAMART.NS",
            "exchange_line": "EQ · BSE 542726 · B2B Marketplace",
            "badge": "PLATFORM · B2B LISTINGS LEADER",
            "market_share_pct": 50.0,
            "catalysts": [],
        },
        {
            "ticker": "NYKAA.NS",
            "exchange_line": "EQ · BSE 543384 · E-Commerce / Beauty",
            "badge": "PLATFORM · BEAUTY E-COMM LEADER",
            "market_share_pct": 35.0,
            "catalysts": [],
        },
        {
            "ticker": "PAYTM.NS",
            "exchange_line": "EQ · BSE 543396 · Fintech / Payments",
            "badge": "PLATFORM · UPI + WALLET ECOSYSTEM",
            "market_share_pct": 20.0,
            "catalysts": [],
        },
        {
            "ticker": "ZOMATO.NS",
            "exchange_line": "EQ · BSE 543320 · Food Delivery",
            "badge": "PLATFORM · FOOD DELIVERY DUOPOLY",
            "market_share_pct": 55.0,
            "catalysts": [],
        },
    ],
    "regulatory_moat": [
        {
            "ticker": "MCX.NS",
            "exchange_line": "SE · BSE 534091 · Commodity Exchange",
            "badge": "REGULATED · SEBI-LICENSED EXCHANGE",
            "market_share_pct": 95.9,
            "catalysts": ["ATH breakout", "MSCI inclusion"],
        },
        {
            "ticker": "BSE.NS",
            "exchange_line": "EQ · BSE 533278 · Stock Exchange",
            "badge": "REGULATED · LISTED EXCHANGE",
            "market_share_pct": 18.0,
            "catalysts": [],
        },
        {
            "ticker": "CDSL.NS",
            "exchange_line": "EQ · BSE 542669 · Depository",
            "badge": "REGULATED · SEBI DEPOSITORY",
            "market_share_pct": 89.0,
            "catalysts": [],
        },
        {
            "ticker": "CAMS.NS",
            "exchange_line": "EQ · BSE 543232 · RTA / Reg Tech",
            "badge": "REGULATED · AMFI RTA FRAMEWORK",
            "market_share_pct": 70.0,
            "catalysts": [],
        },
        {
            "ticker": "IEX.NS",
            "exchange_line": "EQ · BSE 540750 · Power Exchange",
            "badge": "REGULATED · CERC / POWER MARKET",
            "market_share_pct": 94.0,
            "catalysts": [],
        },
        {
            "ticker": "IRCTC.NS",
            "exchange_line": "EQ · BSE 542830 · PSU Concession",
            "badge": "REGULATED · RAIL MINISTRY CONCESSION",
            "market_share_pct": 100.0,
            "catalysts": [],
        },
    ],
    "duopoly": [
        {
            "ticker": "BSE.NS",
            "exchange_line": "EQ · BSE 533278 · Exchanges",
            "badge": "DUOPOLY · NSE / BSE MARKET STRUCTURE",
            "market_share_pct": 18.0,
            "catalysts": [],
        },
        {
            "ticker": "ZOMATO.NS",
            "exchange_line": "EQ · BSE 543320 · Food Delivery",
            "badge": "DUOPOLY · WITH SWIGGY",
            "market_share_pct": 55.0,
            "catalysts": [],
        },
        {
            "ticker": "SWIGGY.NS",
            "exchange_line": "EQ · BSE · Food Delivery",
            "badge": "DUOPOLY · WITH ZOMATO",
            "market_share_pct": 45.0,
            "catalysts": [],
        },
        {
            "ticker": "ASIANPAINT.NS",
            "exchange_line": "EQ · BSE 500820 · Paints",
            "badge": "DUOPOLY · WITH BERGER (DECORATIVE)",
            "market_share_pct": 52.0,
            "catalysts": [],
        },
        {
            "ticker": "BERGEPAINT.NS",
            "exchange_line": "EQ · BSE 509480 · Paints",
            "badge": "DUOPOLY · #2 DECORATIVE PAINTS",
            "market_share_pct": 28.0,
            "catalysts": [],
        },
        {
            "ticker": "HDFCBANK.NS",
            "exchange_line": "EQ · BSE 500180 · Private Banks",
            "badge": "DUOPOLY · WITH ICICI (PRIVATE BANK)",
            "market_share_pct": 28.0,
            "catalysts": [],
        },
    ],
    "category_leader": [
        {
            "ticker": "TITAN.NS",
            "exchange_line": "EQ · BSE 500114 · Consumer / Jewellery",
            "badge": "CATEGORY LEADER · ORGANISED JEWELLERY",
            "market_share_pct": 35.0,
            "catalysts": [],
        },
        {
            "ticker": "ASIANPAINT.NS",
            "exchange_line": "EQ · BSE 500820 · Paints",
            "badge": "CATEGORY LEADER · DECORATIVE PAINTS",
            "market_share_pct": 52.0,
            "catalysts": [],
        },
        {
            "ticker": "DMART.NS",
            "exchange_line": "EQ · BSE 540376 · Retail",
            "badge": "CATEGORY LEADER · VALUE RETAIL",
            "market_share_pct": 12.0,
            "catalysts": [],
        },
        {
            "ticker": "HDFCAMC.NS",
            "exchange_line": "EQ · BSE 541729 · Asset Management",
            "badge": "CATEGORY LEADER · LARGEST AMC (AUM)",
            "market_share_pct": 12.0,
            "catalysts": [],
        },
        {
            "ticker": "NESTLEIND.NS",
            "exchange_line": "EQ · BSE 500790 · FMCG",
            "badge": "CATEGORY LEADER · PREMIUM FMCG",
            "market_share_pct": 40.0,
            "catalysts": [],
        },
        {
            "ticker": "TRENT.NS",
            "exchange_line": "EQ · BSE 500251 · Retail / Fashion",
            "badge": "CATEGORY LEADER · WESTSIDE / ZUDIO",
            "market_share_pct": 8.0,
            "catalysts": [],
        },
    ],
}

@dataclass
class HighProfitScanFilters:
    pe_max: float = 300.0
    vol_min: float = 1.0
    rsi_min: float = 0.0
    rsi_max: float = 100.0


@dataclass
class HighProfitResult:
    ticker: str
    raw_ticker: str
    currency: str
    archetype_id: str
    exchange_line: str
    badge: str
    market_share_pct: float
    catalysts: list[str] = field(default_factory=list)

    price: float = 0.0
    pe: float = 0.0
    vol_ratio: float = 0.0
    rsi: float = 0.0
    score: float = 0.0
    links: dict = field(default_factory=dict)
    news_headlines: list[str] = field(default_factory=list)

    today_low: float = 0.0
    today_high: float = 0.0
    week52_low: float = 0.0
    week52_high: float = 0.0
    dma50: float = 0.0
    dma50_pct: float = 0.0
    dma200: float = 0.0
    dma200_pct: float = 0.0
    return_1y_pct: float = 0.0

    pe_label: str = ""
    pb: Optional[float] = None
    eps: Optional[float] = None
    mkt_cap_cr: Optional[float] = None
    div_yield: Optional[float] = None

    rev_growth_pct: Optional[float] = None
    profit_margin: Optional[float] = None
    ebitda_margin: Optional[float] = None
    roe: Optional[float] = None
    debt_equity: Optional[str] = None

    score_growth: int = 0
    score_business: int = 0
    score_technicals: int = 0
    score_momentum: int = 0
    score_valuation: int = 0

    signal_daily: str = "—"
    signal_weekly: str = "—"
    signal_monthly: str = "—"
    tech_flags: list[str] = field(default_factory=list)
    buy_action: str = "—"
    precautions: str = ""


def nav_title(archetype_id: str) -> str:
    a = ARCHETYPES.get(archetype_id, {})
    return a.get("nav_title") or a.get("title", archetype_id)


def derive_buy_guidance(row: HighProfitResult) -> tuple[str, str]:
    """Return (buy_action, precautions) from scores, technicals, and risk tier."""
    meta = ARCHETYPES.get(row.archetype_id, {})
    risk = meta.get("risk_tier", "medium")
    notes: list[str] = []

    strong_tech = row.signal_daily == "STRONG BUY" and row.signal_weekly in ("STRONG BUY", "BUY")
    bullish = row.signal_daily in ("STRONG BUY", "BUY") and row.rsi < 78
    extended = row.rsi >= 75 or row.pe_label == "rich"
    weak_val = row.score_valuation < 8
    above_dma = row.dma50_pct >= 0 and row.dma200_pct >= 0

    if row.score >= 72 and bullish and not extended:
        action = "Buy"
    elif row.score >= 62 and bullish:
        action = "Buy on dips"
    elif row.score >= 55 and above_dma and row.rsi < 72:
        action = "Hold / Add small"
    elif extended and row.score >= 60:
        action = "Hold only — don't chase"
    elif row.rsi >= 78 or (extended and weak_val):
        action = "Avoid new buys"
    elif row.score < 45 or row.signal_daily == "SELL":
        action = "Avoid / Wait"
    else:
        action = "Watchlist"

    if extended:
        notes.append("Rich/extended valuation or RSI — stagger entries; avoid lump-sum at highs")
    if row.return_1y_pct > 80:
        notes.append(f"1Y return +{row.return_1y_pct:.0f}% — profit-taking and mean-reversion risk")
    if row.vol_ratio < 1.3:
        notes.append("Volume below 1.3× avg — wait for confirmation before sizing up")
    if not above_dma:
        notes.append("Below key moving averages — trend not fully confirmed")
    if weak_val and row.pe < 9000:
        notes.append("Valuation pillar weak — margin of safety is limited")
    if risk == "high":
        notes.append("High-risk tier — use smaller position size and wider risk limits")
    elif risk == "medium":
        notes.append("Medium-risk tier — diversify; don't overweight a single name")
    if row.score_technicals < 10:
        notes.append("Technicals weak — align with weekly/monthly signals before buying")

    tier_note = meta.get("tier_precautions", "")
    if tier_note and tier_note not in " ".join(notes):
        notes.append(tier_note)

    if not notes:
        notes.append("Use stop below 50 DMA or recent swing low; not financial advice")

    return action, " · ".join(notes)


def get_watchlist(archetype_id: str) -> list[dict]:
    return _WATCHLIST.get(archetype_id, [])


def resolve_watchlist(archetype_id: str, scan_source: str) -> list[dict]:
    """Curated list, or intersection with a Nifty / S&P universe."""
    wl = get_watchlist(archetype_id)
    if scan_source == "Curated watchlist":
        return wl
    universe = set(UNIVERSES.get(scan_source, []))
    if not universe:
        return wl
    return [e for e in wl if e["ticker"] in universe]


def passes_scan_filters(row: HighProfitResult, filters: HighProfitScanFilters) -> bool:
    pe = row.pe if row.pe < 9000 else None
    if pe is not None and pe > filters.pe_max:
        return False
    if row.vol_ratio < filters.vol_min:
        return False
    if not (filters.rsi_min <= row.rsi <= filters.rsi_max):
        return False
    return True


def archetype_defaults(archetype_id: str) -> dict:
    return ARCHETYPES.get(archetype_id, {}).get(
        "defaults",
        {"pe_max": 100.0, "vol_min": 1.2, "rsi_range": (50, 100)},
    )


def _pct_vs(price: float, ref: float) -> float:
    if not ref or ref <= 0:
        return 0.0
    return round((price / ref - 1) * 100, 1)


def _signal_label(closes: pd.Series, period_ma: int = 50) -> str:
    if len(closes) < period_ma + 5:
        return "NEUTRAL"
    ma = closes.rolling(period_ma).mean().iloc[-1]
    price = closes.iloc[-1]
    rsi = compute_rsi(closes)
    if np.isnan(rsi):
        rsi = 50.0
    slope = closes.iloc[-1] - closes.iloc[-5]
    if price > ma and rsi >= 60 and slope > 0:
        return "STRONG BUY"
    if price > ma and rsi >= 50:
        return "BUY"
    if price < ma and rsi < 45:
        return "SELL"
    return "NEUTRAL"


def _resample_closes(hist: pd.DataFrame, rule: str) -> pd.Series:
    s = hist["Close"].resample(rule).last().dropna()
    return s


def _score_pillar_growth(rev_growth: Optional[float]) -> int:
    if rev_growth is None:
        return 8
    g = rev_growth * 100 if abs(rev_growth) <= 2 else rev_growth
    if g >= 40:
        return 20
    if g >= 25:
        return 16
    if g >= 15:
        return 12
    if g >= 5:
        return 8
    return 4


def _score_pillar_business(roe: Optional[float], pm: Optional[float], de: Optional[float]) -> int:
    score = 0
    if roe is not None:
        r = roe * 100 if abs(roe) <= 2 else roe
        score += 8 if r >= 25 else (6 if r >= 18 else (4 if r >= 12 else 2))
    else:
        score += 4
    if pm is not None:
        m = pm * 100 if abs(pm) <= 1 else pm
        score += 8 if m >= 20 else (6 if m >= 12 else (4 if m >= 8 else 2))
    else:
        score += 4
    if de is not None:
        score += 4 if de < 0.3 else (3 if de < 0.8 else (2 if de < 1.5 else 0))
    else:
        score += 3
    return min(20, score)


def _score_pillar_technicals(
    above_50: bool, above_200: bool, rsi: float, ath_breakout: bool
) -> int:
    score = 0
    if above_50:
        score += 7
    if above_200:
        score += 7
    if rsi >= 60:
        score += 4
    elif rsi >= 50:
        score += 2
    if ath_breakout:
        score += 2
    return min(20, score)


def _score_pillar_momentum(ret_1y: float, vol_ratio: float) -> int:
    score = 0
    if ret_1y >= 80:
        score += 12
    elif ret_1y >= 40:
        score += 9
    elif ret_1y >= 15:
        score += 6
    elif ret_1y >= 0:
        score += 3
    if vol_ratio >= 2.0:
        score += 8
    elif vol_ratio >= 1.5:
        score += 5
    elif vol_ratio >= 1.2:
        score += 3
    return min(20, score)


def _score_pillar_valuation(pe: float, pb: Optional[float]) -> int:
    if pe <= 0 or pe >= 9000:
        return 6
    score = 0
    if pe <= 20:
        score += 12
    elif pe <= 35:
        score += 8
    elif pe <= 50:
        score += 5
    else:
        score += 2
    if pb is not None:
        if pb <= 5:
            score += 8
        elif pb <= 15:
            score += 5
        elif pb <= 30:
            score += 3
    else:
        score += 3
    return min(20, score)


def _pe_label(pe: float) -> str:
    if pe <= 0 or pe >= 9000:
        return "n/a"
    if pe > 40:
        return "rich"
    if pe > 25:
        return "fair"
    return "attractive"


def _enrich_entry(
    entry: dict,
    archetype_id: str,
    _thresholds: dict | None = None,
) -> Optional[HighProfitResult]:
    ticker = entry["ticker"]
    try:
        stk = yf.Ticker(ticker)
        end = datetime.today()
        start = end - timedelta(days=400)
        hist = stk.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
        if hist.empty or len(hist) < 60:
            return None

        closes = hist["Close"]
        volumes = hist["Volume"]
        price = round(float(closes.iloc[-1]), 2)

        pe = get_pe(stk)
        if pe is None:
            pe = 9999.0
        pe = round(float(pe), 2)

        vol_ratio = compute_volume_ratio(volumes)
        if vol_ratio is None or np.isnan(vol_ratio):
            return None

        rsi = compute_rsi(closes)
        if rsi is None or np.isnan(rsi):
            return None

        dma50 = round(float(closes.rolling(50).mean().iloc[-1]), 2)
        dma200 = (
            round(float(closes.rolling(200).mean().iloc[-1]), 2)
            if len(closes) >= 200
            else dma50
        )
        above_50 = price >= dma50
        above_200 = price >= dma200

        week52 = hist.tail(252) if len(hist) >= 252 else hist
        wlow = round(float(week52["Low"].min()), 2)
        whigh = round(float(week52["High"].max()), 2)
        today = hist.tail(1)
        tlow = round(float(today["Low"].iloc[-1]), 2)
        thigh = round(float(today["High"].iloc[-1]), 2)

        ret_1y = 0.0
        if len(closes) >= 252:
            ret_1y = round((price / float(closes.iloc[-252]) - 1) * 100, 1)

        ath_breakout = price >= whigh * 0.995

        daily_sig = _signal_label(closes, 50)
        weekly = _resample_closes(hist, "W-FRI")
        monthly = _resample_closes(hist, "M")
        weekly_sig = _signal_label(weekly, 20) if len(weekly) >= 25 else "NEUTRAL"
        monthly_sig = _signal_label(monthly, 10) if len(monthly) >= 12 else "NEUTRAL"

        info = {}
        try:
            info = stk.info or {}
        except Exception:
            pass

        rev_growth = info.get("revenueGrowth")
        profit_margin = info.get("profitMargins")
        ebitda_margin = info.get("ebitdaMargins")
        roe = info.get("returnOnEquity")
        de_raw = info.get("debtToEquity")
        pb = info.get("priceToBook")
        eps = info.get("trailingEps")
        mcap = info.get("marketCap")
        div_y = info.get("dividendYield")

        if de_raw is not None:
            de_val = float(de_raw)
            debt_label = "~0 (debt-free)" if de_val < 5 else f"{de_val:.1f}"
        else:
            de_val = None
            debt_label = "—"

        mkt_cap_cr = round(mcap / 1e7, 0) if mcap else None
        if div_y and div_y < 1:
            div_pct = round(div_y * 100, 2)
        elif div_y:
            div_pct = round(div_y, 2)
        else:
            div_pct = None

        sg = _score_pillar_growth(rev_growth)
        sb = _score_pillar_business(roe, profit_margin, de_val)
        st_score = _score_pillar_technicals(above_50, above_200, rsi, ath_breakout)
        sm = _score_pillar_momentum(ret_1y, vol_ratio)
        sv = _score_pillar_valuation(pe, float(pb) if pb else None)
        total = round(sg + sb + st_score + sm + sv, 1)

        tech_flags = []
        if above_50:
            tech_flags.append(f"Above 50 DMA\n✓ {_pct_vs(price, dma50):+.0f}%")
        if above_200:
            tech_flags.append(f"Above 200 DMA\n✓ {_pct_vs(price, dma200):+.0f}%")
        if ath_breakout:
            tech_flags.append(f"ATH breakout\n✓ {end.strftime('%b %Y')}")
        for cat in entry.get("catalysts", []):
            tech_flags.append(f"{cat}\n✓ {end.strftime('%b %Y')}")

        is_nse = ticker.endswith(".NS") or ticker.endswith(".BO")
        currency = "₹" if is_nse else "$"
        clean = ticker.replace(".NS", "").replace(".BO", "")

        def _fmt_pct(v: Optional[float]) -> Optional[float]:
            if v is None:
                return None
            return round(v * 100, 1) if abs(v) <= 2 else round(v, 1)

        row = HighProfitResult(
            ticker=clean,
            raw_ticker=ticker,
            currency=currency,
            archetype_id=archetype_id,
            exchange_line=entry.get("exchange_line", ""),
            badge=entry.get("badge", ""),
            market_share_pct=entry.get("market_share_pct", 0.0),
            catalysts=list(entry.get("catalysts", [])),
            price=price,
            pe=pe,
            vol_ratio=round(vol_ratio, 2),
            rsi=round(rsi, 1),
            score=total,
            links=get_stock_links(ticker),
            today_low=tlow,
            today_high=thigh,
            week52_low=wlow,
            week52_high=whigh,
            dma50=dma50,
            dma50_pct=_pct_vs(price, dma50),
            dma200=dma200,
            dma200_pct=_pct_vs(price, dma200),
            return_1y_pct=ret_1y,
            pe_label=_pe_label(pe),
            pb=round(float(pb), 1) if pb else None,
            eps=round(float(eps), 2) if eps else None,
            mkt_cap_cr=mkt_cap_cr,
            div_yield=div_pct,
            rev_growth_pct=_fmt_pct(rev_growth),
            profit_margin=_fmt_pct(profit_margin),
            ebitda_margin=_fmt_pct(ebitda_margin),
            roe=_fmt_pct(roe),
            debt_equity=debt_label,
            score_growth=sg,
            score_business=sb,
            score_technicals=st_score,
            score_momentum=sm,
            score_valuation=sv,
            signal_daily=daily_sig,
            signal_weekly=weekly_sig,
            signal_monthly=monthly_sig,
            tech_flags=tech_flags,
        )
        row.buy_action, row.precautions = derive_buy_guidance(row)
        return row
    except Exception:
        return None


def scan_high_profit(
    archetype_id: str,
    scan_source: str = "Curated watchlist",
    filters: HighProfitScanFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[HighProfitResult]:
    """Scan watchlist for an archetype; returns ranked HighProfitResult list."""
    if filters is None:
        d = archetype_defaults(archetype_id)
        rr = d.get("rsi_range", (50, 100))
        filters = HighProfitScanFilters(
            pe_max=d.get("pe_max", 100.0),
            vol_min=d.get("vol_min", 1.2),
            rsi_min=rr[0],
            rsi_max=rr[1],
        )

    watchlist = resolve_watchlist(archetype_id, scan_source)
    results: list[HighProfitResult] = []
    total = len(watchlist)

    for i, entry in enumerate(watchlist):
        if progress_cb:
            progress_cb(i + 1, total, entry["ticker"])
        row = _enrich_entry(entry, archetype_id)
        if row and passes_scan_filters(row, filters):
            results.append(row)

    return sorted(results, key=lambda x: x.score, reverse=True)
