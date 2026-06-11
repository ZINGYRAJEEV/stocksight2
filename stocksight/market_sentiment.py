"""
Three-layer market sentiment for scan results (macro → sector → stock).

Rules follow the StockSight intraday sentiment guide: Gift/SGX Nifty, VIX, FII,
US overnight, bank leadership, stock volume/gap/RSI/VWAP/52W, and trap patterns
(failed gap, RSI exhaustion).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
import yfinance as yf

try:
    from .screener import fetch_nse_fii_dii_equity_snapshot
except ImportError:
    from screener import fetch_nse_fii_dii_equity_snapshot  # type: ignore[no-redef]


# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────

@dataclass
class MacroContext:
    market: str = "NSE"
    nifty_pct: Optional[float] = None
    bank_nifty_pct: Optional[float] = None
    vix_level: Optional[float] = None
    spy_pct: Optional[float] = None
    qqq_pct: Optional[float] = None
    fii_note: Optional[str] = None
    macro_tone: str = "Neutral"          # Bullish / Neutral / Bearish
    macro_detail: str = ""


@dataclass
class SentimentVerdict:
    label: str = "🟡 Mixed"
    why: str = ""
    macro: str = "Neutral"
    sector: str = "Neutral"
    stock: str = "Neutral"
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Macro fetch (cached per market)
# ─────────────────────────────────────────────────────────────

_MACRO_CACHE: dict[str, tuple[float, MacroContext]] = {}
_MACRO_TTL = 300  # 5 min


def _day_change_pct(ticker: str) -> Optional[float]:
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
        if hist is None or len(hist) < 2:
            return None
        prev = float(hist["Close"].iloc[-2])
        last = float(hist["Close"].iloc[-1])
        if prev <= 0:
            return None
        return round((last / prev - 1.0) * 100.0, 2)
    except Exception:
        return None


def _last_close(ticker: str) -> Optional[float]:
    try:
        hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _fii_tone(note: Optional[str]) -> str:
    if not note:
        return "Neutral"
    low = note.lower()
    if "net ₹-" in low or "net -" in low or "net ₹−" in low:
        return "Bearish"
    if re.search(r"net\s*₹?\s*[\d,]+\s*cr", low):
        # positive net without minus — treat as buyers
        if "net ₹-" not in low and "net -" not in low:
            m = re.search(r"net\s*₹?\s*(-?[\d,]+)", note, re.I)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    if val > 0:
                        return "Bullish"
                    if val < 0:
                        return "Bearish"
                except ValueError:
                    pass
    if "buy" in low and "sell" not in low:
        return "Bullish"
    if "sell" in low:
        return "Bearish"
    return "Neutral"


def get_macro_context(market: str = "NSE", *, force_refresh: bool = False) -> MacroContext:
    market = (market or "NSE").upper()
    now = time.time()
    cached = _MACRO_CACHE.get(market)
    if cached and not force_refresh and (now - cached[0]) < _MACRO_TTL:
        return cached[1]

    ctx = MacroContext(market=market)
    bits: list[str] = []

    if market == "US":
        ctx.spy_pct = _day_change_pct("SPY")
        ctx.qqq_pct = _day_change_pct("QQQ")
        ctx.vix_level = _last_close("^VIX")
        if ctx.spy_pct is not None:
            if ctx.spy_pct >= 0.5:
                bits.append(f"S&P/SPY +{ctx.spy_pct:.1f}%")
            elif ctx.spy_pct <= -0.5:
                bits.append(f"S&P/SPY {ctx.spy_pct:.1f}%")
            else:
                bits.append(f"S&P/SPY flat ({ctx.spy_pct:+.1f}%)")
        if ctx.qqq_pct is not None and ctx.spy_pct is not None:
            if ctx.qqq_pct > ctx.spy_pct + 0.2:
                bits.append("Nasdaq leading")
        if ctx.vix_level is not None:
            bits.append(f"VIX {ctx.vix_level:.1f}")
    else:
        ctx.nifty_pct = _day_change_pct("^NSEI")
        ctx.bank_nifty_pct = _day_change_pct("^NSEBANK")
        ctx.vix_level = _last_close("^INDIAVIX")
        ctx.fii_note = fetch_nse_fii_dii_equity_snapshot()
        if ctx.nifty_pct is not None:
            if ctx.nifty_pct >= 0.5:
                bits.append(f"Nifty +{ctx.nifty_pct:.1f}%")
            elif ctx.nifty_pct <= -0.5:
                bits.append(f"Nifty {ctx.nifty_pct:.1f}%")
            else:
                bits.append(f"Nifty flat ({ctx.nifty_pct:+.1f}%)")
        if ctx.bank_nifty_pct is not None and ctx.nifty_pct is not None:
            diff = ctx.bank_nifty_pct - ctx.nifty_pct
            if diff >= 0.3:
                bits.append("Bank Nifty leading")
            elif diff <= -0.3:
                bits.append("Bank Nifty lagging")
        if ctx.vix_level is not None:
            bits.append(f"India VIX {ctx.vix_level:.1f}")
        fii = _fii_tone(ctx.fii_note)
        if fii != "Neutral":
            bits.append(f"FII {fii.lower()}")

    # Macro tone from rules
    score = 0
    if market == "US":
        if ctx.spy_pct is not None:
            if ctx.spy_pct >= 0.5:
                score += 1
            elif ctx.spy_pct <= -0.5:
                score -= 1
    else:
        if ctx.nifty_pct is not None:
            if ctx.nifty_pct >= 0.5:
                score += 1
            elif ctx.nifty_pct <= -0.5:
                score -= 1
        if ctx.bank_nifty_pct is not None and ctx.nifty_pct is not None:
            if ctx.bank_nifty_pct - ctx.nifty_pct >= 0.3:
                score += 1
            elif ctx.bank_nifty_pct - ctx.nifty_pct <= -0.3:
                score -= 1
        if _fii_tone(ctx.fii_note) == "Bullish":
            score += 1
        elif _fii_tone(ctx.fii_note) == "Bearish":
            score -= 1

    if ctx.vix_level is not None:
        if ctx.vix_level >= 22:
            score -= 2
        elif ctx.vix_level >= 18:
            score -= 1
        elif ctx.vix_level < 13:
            score += 1

    if score >= 2:
        ctx.macro_tone = "Bullish"
    elif score <= -2:
        ctx.macro_tone = "Bearish"
    else:
        ctx.macro_tone = "Neutral"

    ctx.macro_detail = " · ".join(bits) if bits else "Macro data limited"
    _MACRO_CACHE[market] = (now, ctx)
    return ctx


def market_from_universe(universe_name: str = "") -> str:
    u = (universe_name or "").upper()
    if any(x in u for x in ("S&P", "NYSE", "NASDAQ", "US", "NYSE")):
        return "US"
    return "NSE"


# ─────────────────────────────────────────────────────────────
# Row metric helpers
# ─────────────────────────────────────────────────────────────

def _num(row: dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k not in row:
            continue
        v = row[k]
        if v is None or (isinstance(v, float) and v != v):
            continue
        if isinstance(v, str):
            s = v.strip().replace("%", "").replace("×", "").replace(",", "")
            if not s or s in ("—", "-", "n/a"):
                continue
            try:
                return float(s)
            except ValueError:
                continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _str_val(row: dict[str, Any], *keys: str) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            s = str(row[k]).strip()
            if s and s not in ("—", "nan", "None"):
                return s
    return ""


# ─────────────────────────────────────────────────────────────
# Layer scoring
# ─────────────────────────────────────────────────────────────

def _score_stock_layer(row: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    """Returns (score -5..+5, bullish_bits, warnings)."""
    score = 0
    bull: list[str] = []
    warn: list[str] = []

    vol = _num(row, "Vol×", "Volume Ratio", "vol_ratio", "Vol Ratio")
    rsi = _num(row, "RSI", "RSI(5m)", "rsi")
    gap = _num(row, "Gap %", "gap_pct", "Gap")
    chg = _num(row, "% chg", "pct_change", "% Change", "Change %", "Open→Now %")
    vwap = _num(row, "VWAP %", "vs VWAP %", "price_vs_vwap_pct", "VWAP_pct")
    dd52 = _num(row, "↓ from 52w", "drawdown_52w_pct", "% vs 52w H", "Drawdown %", "↓52w %")
    open_px = _num(row, "Open", "open_px")
    price = _num(row, "Price", "CMP", "CMP Rs.", "LTP", "price")
    score120 = _num(row, "Score /120", "Score", "score_120", "Composite")
    tier = _str_val(row, "Tier", "rank_tier").lower()

    if vol is not None:
        if vol >= 2.0:
            score += 2
            bull.append(f"Vol {vol:.1f}×")
        elif vol < 1.0:
            score -= 2
            warn.append("Low volume")

    if gap is not None:
        if gap >= 1.0:
            score += 1
            bull.append(f"Gap +{gap:.1f}%")
        elif gap <= -1.0:
            score -= 2
            warn.append(f"Gap down {gap:.1f}%")

    if chg is not None:
        if chg >= 2.0:
            score += 1
        elif chg < 0:
            score -= 2

    if gap is not None and chg is not None and gap >= 1.0 and chg < 0:
        score -= 3
        warn.append("Failed gap (sellers overwhelmed)")

    if rsi is not None:
        if 50 <= rsi <= 65:
            score += 1
        elif rsi > 72:
            score -= 2
            warn.append(f"RSI exhaustion ({rsi:.0f})")
        elif rsi < 35:
            score -= 1

    if vwap is not None:
        if vwap >= -0.5:
            score += 1
        elif vwap <= -2.0:
            score -= 2
            warn.append("Below VWAP")

    if dd52 is not None:
        # drawdown is negative % below high
        if dd52 >= -2 or (dd52 <= 0 and dd52 > -2):
            score += 1
        elif dd52 < -35:
            score -= 1

    if open_px is not None and price is not None:
        if price > open_px:
            score += 1
        elif price < open_px:
            score -= 1

    if vol is not None and rsi is not None and vwap is not None:
        if vol >= 2 and rsi > 70 and vwap > 1.5:
            warn.append("High vol + overbought — exhaustion risk")

    if vol is not None and gap is not None and chg is not None:
        if vol >= 3 and gap <= -3 and chg < 0:
            warn.append("Institutional selling (gap down + volume)")

    if score120 is not None and score120 >= 70:
        score += 1
    if tier in ("elite", "strong", "best"):
        score += 1
    elif tier in ("avoid", "skip"):
        score -= 2

    return score, bull, warn


def _score_sector_layer(row: dict[str, Any], macro: MacroContext) -> tuple[str, str]:
    sector = _str_val(row, "Sector", "sector")
    rs = _num(row, "RS vs Idx", "RS20", "rel_strength_20d", "RS20_vs_idx")
    chg = _num(row, "% chg", "pct_change", "Change %")

    if rs is not None:
        if rs >= 1.0:
            return "Bullish", f"Outperforming index ({rs:+.1f}%)"
        if rs <= -1.0:
            return "Bearish", f"Underperforming index ({rs:+.1f}%)"
        return "Neutral", f"Inline vs index ({rs:+.1f}%)"

    if chg is not None and macro.macro_tone == "Bullish" and chg >= 1.5:
        return "Bullish", f"Strong tape in {sector or 'sector'}"

    if macro.macro_tone == "Bearish":
        return "Bearish", "Market headwind for sector"

    return "Neutral", sector or "Sector n/a"


def compute_sentiment(
    row: dict[str, Any],
    *,
    macro: Optional[MacroContext] = None,
    market: str = "NSE",
) -> SentimentVerdict:
    macro = macro or get_macro_context(market)
    stock_score, bull_bits, warnings = _score_stock_layer(row)
    sector_tone, sector_note = _score_sector_layer(row, macro)

    if stock_score >= 3:
        stock_tone = "Bullish"
    elif stock_score <= -2:
        stock_tone = "Bearish"
    else:
        stock_tone = "Neutral"

    layers = [macro.macro_tone, sector_tone, stock_tone]
    bull_n = sum(1 for t in layers if t == "Bullish")
    bear_n = sum(1 for t in layers if t == "Bearish")

    if warnings and any("Failed gap" in w or "exhaustion" in w.lower() for w in warnings):
        label = "⛔ Avoid"
    elif bear_n >= 2:
        label = "🔴 Bearish"
    elif bull_n == 3 and not warnings:
        label = "🟢 Strong Bullish"
    elif bull_n >= 2 and bear_n == 0:
        label = "🟢 Bullish"
    elif bear_n >= 2:
        label = "🟠 Cautious"
    elif bull_n == 1 and bear_n == 1:
        label = "🟡 Mixed"
    elif bull_n >= 1:
        label = "🟡 Lean Bullish"
    elif bear_n >= 1:
        label = "🟠 Lean Bearish"
    else:
        label = "🟡 Neutral"

    why_parts = [f"Macro: {macro.macro_tone}"]
    if sector_note:
        why_parts.append(f"Sector: {sector_note}")
    if bull_bits:
        why_parts.append(", ".join(bull_bits[:3]))
    if warnings:
        why_parts.append("⚠ " + "; ".join(warnings[:2]))

    return SentimentVerdict(
        label=label,
        why=" · ".join(why_parts)[:220],
        macro=macro.macro_tone,
        sector=sector_tone,
        stock=stock_tone,
        warnings=warnings,
    )


def add_market_sentiment_columns(
    df: pd.DataFrame,
    *,
    market: str = "NSE",
    macro: Optional[MacroContext] = None,
    insert_after: str = "Ticker",
) -> pd.DataFrame:
    """Add ``Market sentiment`` and ``Sentiment why`` columns to a results dataframe."""
    if df is None or df.empty:
        return df
    if "Market sentiment" in df.columns:
        return df

    macro = macro or get_macro_context(market)
    labels: list[str] = []
    whys: list[str] = []
    for _, row in df.iterrows():
        v = compute_sentiment(row.to_dict(), macro=macro, market=market)
        labels.append(v.label)
        whys.append(v.why)

    out = df.copy()
    pos = 0
    if insert_after in out.columns:
        pos = out.columns.get_loc(insert_after) + 1
    out.insert(pos, "Market sentiment", labels)
    out.insert(pos + 1, "Sentiment why", whys)
    return out


def enrich_signal_results_sentiment(results: list, *, market: str = "NSE") -> None:
    """Attach sentiment fields to SignalResult-like objects (optional)."""
    macro = get_macro_context(market)
    for r in results:
        row = {
            "Vol×": getattr(r, "vol_ratio", None),
            "RSI": getattr(r, "rsi", None),
            "VWAP %": getattr(r, "price_vs_vwap_pct", None),
            "RS20": getattr(r, "rel_strength_20d", None),
            "Sector": getattr(r, "sector", None),
            "Drawdown %": getattr(r, "drawdown_52w_pct", None),
        }
        v = compute_sentiment(row, macro=macro, market=market)
        if hasattr(r, "__dict__"):
            r.market_sentiment = v.label  # type: ignore[attr-defined]
            r.sentiment_why = v.why  # type: ignore[attr-defined]
