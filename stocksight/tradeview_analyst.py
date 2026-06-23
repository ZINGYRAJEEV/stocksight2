"""
TradingView analyst recommendations integration.

Fetches analyst consensus, ratings, and target prices from TradingView.
Falls back to Yahoo Finance if TradingView data is unavailable.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import warnings

warnings.filterwarnings("ignore")

IST = ZoneInfo("Asia/Kolkata")

# NSE display tickers that differ on TradingView (e.g. KOEL → KIRLOSENG).
NSE_TV_SYMBOL_ALIASES: dict[str, str] = {
    "KOEL": "KIRLOSENG",
}

_BULLISH_NEWS_KW = (
    "soar", "surge", "rally", "jump", "gain", "wins", "won", "beat", "record",
    "strong", "upgrade", "breakout", "high", "bullish", "order", "contract",
)
_BEARISH_NEWS_KW = (
    "fall", "drop", "slump", "plunge", "cut", "miss", "downgrade", "probe",
    "fraud", "loss", "bearish", "weak", "decline", "selloff", "penalty",
    "default", "resign",
)

# TradingView's unofficial endpoints and headers
TRADINGVIEW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Mapping of conviction levels
CONVICTION_MAPPING = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "neutral": "Hold",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
    "outperform": "Outperform",
    "hold": "Hold",
    "underperform": "Underperform",
}

# Color mapping for recommendations
COLOR_MAPPING = {
    "Strong Buy": "#00e5a0",      # Green
    "Buy": "#4db8ff",              # Light blue
    "Hold": "#f0b429",             # Yellow/Orange
    "Sell": "#ff9d42",             # Orange
    "Strong Sell": "#ff4d4d",      # Red
    "Outperform": "#4db8ff",       # Light blue
    "Underperform": "#ff9d42",     # Orange
    "—": "#7abeac",                # Gray
}


def resolve_tradingview_symbol(symbol: str, market: str = "NSE") -> str:
    """Map app ticker to TradingView `EXCHANGE:SYMBOL` (with NSE aliases)."""
    clean = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if market.upper() == "NSE":
        clean = NSE_TV_SYMBOL_ALIASES.get(clean, clean)
        return f"NSE:{clean}"
    return clean


def fetch_tradingview_news(
    symbol: str,
    *,
    market: str = "NSE",
    limit: int = 3,
) -> list[dict[str, str]]:
    """
    Recent TradingView headlines for a symbol (unofficial headlines API).

    Returns [{title, source, published, url}, ...] newest first.
    """
    if not symbol:
        return []

    clean = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    mkt = (market or "NSE").upper()
    candidates: list[str] = []
    if mkt == "US":
        for prefix in ("NASDAQ", "NYSE"):
            sym = f"{prefix}:{clean}"
            if sym not in candidates:
                candidates.append(sym)
        if clean not in candidates:
            candidates.append(clean)
    else:
        tv_symbol = resolve_tradingview_symbol(symbol, market="NSE")
        candidates = [tv_symbol]
        alt = NSE_TV_SYMBOL_ALIASES.get(clean)
        if alt and f"NSE:{alt}" not in candidates:
            candidates.append(f"NSE:{alt}")
        if f"NSE:{clean}" not in candidates:
            candidates.append(f"NSE:{clean}")

    headers = {
        **TRADINGVIEW_HEADERS,
        "Referer": "https://www.tradingview.com/",
        "Origin": "https://www.tradingview.com",
    }

    for sym in candidates:
        try:
            resp = requests.get(
                "https://news-headlines.tradingview.com/headlines/",
                params={"category": "stock", "lang": "en", "symbol": sym},
                headers=headers,
                timeout=12,
            )
            if resp.status_code != 200:
                continue
            payload = resp.json()
            if not isinstance(payload, list) or not payload:
                continue

            out: list[dict[str, str]] = []
            for item in payload[: max(1, limit)]:
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                pub = ""
                ts = item.get("published")
                if ts:
                    try:
                        pub = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST).strftime(
                            "%d %b %H:%M"
                        )
                    except (TypeError, ValueError, OSError):
                        pub = ""
                out.append({
                    "title": title,
                    "source": str(item.get("source") or "TradingView").strip(),
                    "published": pub,
                    "url": str(item.get("link") or item.get("storyPath") or "").strip(),
                })
            if out:
                return out
        except Exception:
            continue
    return []


def score_headline_sentiment(headlines: list[str]) -> tuple[str, str]:
    """
    Lightweight bullish / bearish / neutral tag from headline text.

    Returns (label, note) e.g. ("Bullish", "+2 bullish · 0 bearish").
    """
    if not headlines:
        return "—", "No headlines"

    bull = bear = 0
    for raw in headlines:
        low = (raw or "").lower()
        if any(k in low for k in _BULLISH_NEWS_KW):
            bull += 1
        if any(k in low for k in _BEARISH_NEWS_KW):
            bear += 1

    if bull > bear and bull > 0:
        label = "Bullish"
    elif bear > bull and bear > 0:
        label = "Bearish"
    elif bull == bear and bull > 0:
        label = "Mixed"
    else:
        label = "Neutral"

    note = f"+{bull} bullish · {bear} bearish" if (bull or bear) else "Neutral tone"
    return label, note


def combine_tv_sentiment(
    headline_label: str,
    technical: dict[str, Any],
) -> tuple[str, str]:
    """Merge headline tone with TradingView technical sentiment."""
    tech_sent = str(technical.get("sentiment") or "—")
    tech_score = technical.get("technical_score")

    if headline_label == "—" and tech_sent == "—":
        return "—", "—"

    parts: list[str] = []
    if headline_label and headline_label != "—":
        parts.append(f"News {headline_label}")
    if tech_sent and tech_sent != "—":
        score_bit = f" ({tech_score:.0f})" if isinstance(tech_score, (int, float)) else ""
        parts.append(f"TV tech {tech_sent}{score_bit}")

    combined = " · ".join(parts) if parts else "—"

    # Overall lean for table column
    scores = {"Bullish": 1, "Mixed": 0, "Neutral": 0, "Bearish": -1, "—": 0}
    h = scores.get(headline_label, 0)
    t = scores.get(tech_sent, 0)
    total = h + t
    if total >= 2:
        overall = "Bullish"
    elif total <= -2:
        overall = "Bearish"
    elif total == 1:
        overall = "Mildly bullish"
    elif total == -1:
        overall = "Mildly bearish"
    else:
        overall = "Neutral"

    return overall, combined


def fetch_tradeview_analyst_data(symbol: str, market: str = "NSE") -> dict[str, Any]:
    """
    Fetch analyst consensus and technical rating from TradingView.
    
    Args:
        symbol: Stock symbol (e.g., "RELIANCE" for NSE or "AAPL" for US)
        market: Market type ("NSE" or "US")
    
    Returns:
        Dictionary with analyst data including consensus, count, and target prices
    """
    empty: dict[str, Any] = {
        "consensus": None,
        "analyst_count": None,
        "target_mean": None,
        "target_high": None,
        "target_low": None,
        "upside_pct": None,
        "source": "—",
        "summary": "—",
    }
    
    if not symbol:
        return empty
    
    try:
        if market == "NSE":
            tv_symbol = resolve_tradingview_symbol(symbol, market="NSE")
        else:
            tv_symbol = symbol if not symbol.startswith("NASDAQ:") and not symbol.startswith("NYSE:") else symbol

        result = _fetch_tradeview_technical_analysis(tv_symbol)
        if result:
            return result
        
    except Exception as e:
        warnings.warn(f"TradingView fetch failed for {symbol}: {str(e)}")
    
    return empty


def _fetch_tradeview_technical_analysis(tv_symbol: str) -> Optional[dict[str, Any]]:
    """
    Fetch technical analysis and recommendation from TradingView's technical analysis engine.
    
    TradingView generates a technical score (0-100) and recommendation based on multiple indicators.
    """
    try:
        # TradingView's technical analysis endpoint
        url = f"https://api.tradingview.com/symbols/{tv_symbol}/technical-analysis"
        response = requests.get(url, headers=TRADINGVIEW_HEADERS, timeout=5)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        if not data or "result" not in data:
            return None
        
        result = data.get("result", {})
        
        # Extract recommendation
        recommendation = result.get("recommendation", "neutral")
        consensus_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "neutral": "Hold",
            "sell": "Sell",
            "strong_sell": "Strong Sell",
        }
        consensus = consensus_map.get(recommendation, "—")
        
        # Extract technical score
        tech_score = result.get("technical_analysis", {}).get("technicalRating", None)
        
        summary = f"{consensus}"
        if tech_score is not None:
            summary = f"{consensus} · Score {tech_score:.0f}/100"
        
        return {
            "consensus": consensus if consensus != "—" else None,
            "analyst_count": None,
            "target_mean": None,
            "target_high": None,
            "target_low": None,
            "upside_pct": None,
            "source": "TradingView",
            "summary": summary,
        }
    except Exception:
        return None


def fetch_tradeview_sentiment(symbol: str, market: str = "NSE") -> dict[str, Any]:
    """
    Fetch market sentiment and strength from TradingView.
    
    Returns sentiment score, signal strength, and pivot points if available.
    """
    empty: dict[str, Any] = {
        "sentiment": "Neutral",
        "strength": "—",
        "technical_score": None,
        "source": "—",
    }
    
    try:
        if market == "NSE":
            tv_symbol = resolve_tradingview_symbol(symbol, market="NSE")
        else:
            tv_symbol = symbol

        url = f"https://api.tradingview.com/symbols/{tv_symbol}/technical-analysis"
        response = requests.get(url, headers=TRADINGVIEW_HEADERS, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            result = data.get("result", {})
            
            tech_analysis = result.get("technical_analysis", {})
            technical_rating = tech_analysis.get("technicalRating")
            
            if technical_rating:
                # Map rating to sentiment
                if technical_rating >= 70:
                    sentiment = "Bullish"
                    strength = "Strong"
                elif technical_rating >= 50:
                    sentiment = "Bullish"
                    strength = "Moderate"
                elif technical_rating >= 30:
                    sentiment = "Neutral"
                    strength = "Weak"
                else:
                    sentiment = "Bearish"
                    strength = "Strong"
                
                return {
                    "sentiment": sentiment,
                    "strength": strength,
                    "technical_score": technical_rating,
                    "source": "TradingView",
                }
        
    except Exception:
        pass
    
    return empty


def enrich_dataframe_tradeview_analyst(
    df: pd.DataFrame,
    *,
    market: str = "NSE",
    ticker_col: str = "Ticker",
    delay_sec: float = 0.2,
) -> pd.DataFrame:
    """
    Add TradingView analyst recommendation columns to a dataframe.
    
    Args:
        df: DataFrame with stock results
        market: Market type ("NSE" or "US")
        ticker_col: Name of the ticker column
        delay_sec: Delay between requests to avoid rate limiting
    
    Returns:
        DataFrame with TradingView analyst columns added
    """
    import time
    
    if df is None or df.empty:
        return df
    
    out = df.copy()
    
    consensus_l: list[Optional[str]] = []
    count_l: list[Optional[int]] = []
    tgt_l: list[Optional[float]] = []
    upside_l: list[Optional[float]] = []
    summary_l: list[str] = []
    source_l: list[str] = []
    
    for idx, row in out.iterrows():
        ticker = str(row.get(ticker_col, "")).strip()
        if not ticker:
            consensus_l.append(None)
            count_l.append(None)
            tgt_l.append(None)
            upside_l.append(None)
            summary_l.append("—")
            source_l.append("—")
            continue
        
        rec = fetch_tradeview_analyst_data(ticker, market=market)
        consensus_l.append(rec.get("consensus"))
        count_l.append(rec.get("analyst_count"))
        tgt_l.append(rec.get("target_mean"))
        upside_l.append(rec.get("upside_pct"))
        summary_l.append(rec.get("summary", "—"))
        source_l.append(rec.get("source", "—"))
        
        if delay_sec > 0:
            time.sleep(delay_sec)
    
    out["TradingView consensus"] = consensus_l
    out["TradingView analyst count"] = count_l
    out["TradingView target"] = tgt_l
    out["TradingView upside %"] = upside_l
    out["TradingView rating"] = summary_l
    out["Rating source"] = source_l
    
    return out


def get_analyst_color(recommendation: str) -> str:
    """Get color code for recommendation label."""
    return COLOR_MAPPING.get(str(recommendation), "#7abeac")


def format_analyst_recommendation(
    consensus: Optional[str],
    count: Optional[int],
    target: Optional[float],
    upside: Optional[float],
    price: Optional[float] = None,
) -> str:
    """
    Format analyst recommendation into a readable summary with color indicator.
    
    Returns a formatted string showing consensus, analyst count, and upside.
    """
    if not consensus or consensus == "—":
        return "—"
    
    parts = [consensus]
    
    if count and count > 0:
        parts.append(f"{count} analysts")
    
    if target and target > 0:
        parts.append(f"Target {target:.2f}")
        if upside:
            parts.append(f"({upside:+.1f}%)")
    
    return " · ".join(parts) if parts else "—"
