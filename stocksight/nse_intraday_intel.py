"""
NSE Intraday Intel — rule-based intraday setup from Bulk Order / Screener filings.

Educational analysis only — not investment advice.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

from buyback_announcements import _nse_quote_url, _screener_company_url
from screener_buyback import ScreenerBuybackItem, _parse_age_minutes
from screener_bulk_order import is_order_announcement, is_exchange_clarification_filing

NEWS_TYPES = (
    "ORDER_WIN",
    "VOLUME_ALERT",
    "LEGAL_NEGATIVE",
    "CLARIFICATION_NEUTRAL",
    "CLARIFICATION_PENDING",
    "OTHER",
)

GOVT_KW = (
    "government", "govt", "psu", "rbi", "hpcl", "ntpc", "state discom",
    "irrigation", "municipal", "ministry", "nhai", "railway", "defence",
    "domestic purchase order", "loi", "letter of intent",
)

AI_NARRATIVE_KW = ("ai ", "artificial intelligence", "healthcare tech", "saas", "fintech")

_RUPEE_CR = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d,.]+)\s*(crore|cr\.?|lakh|lakhs|million|mn)",
    re.I,
)
_ORDER_VALUE_PATTERNS = (
    _RUPEE_CR,
    re.compile(
        r"(?:worth|valued|value|order)\s+(?:of\s+)?(?:₹|rs\.?|inr)?\s*([\d,.]+)\s*"
        r"(crore|cr\.?|lakh|lakhs|million|mn)\b",
        re.I,
    ),
    re.compile(
        r"([\d,.]+)\s*(crore|cr\.?|lakh|lakhs|million|mn)\b",
        re.I,
    ),
)
_UNDISCLOSED_ORDER_KW = (
    "undisclosed",
    "not disclosed",
    "no value",
    "value not",
    "amount not disclosed",
    "value of the order is not",
)
_REL_AGE_RE = re.compile(r"^\d+\s*(?:m|min|h|hr|d|day)\b", re.I)
_MW_ORDER_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*mw\b", re.I)


@dataclass
class StockContext:
    approx_price: str = "—"
    trend: str = "NEUTRAL"
    note: str = ""
    week_high52: str = "—"
    week_low52: str = "—"
    price: Optional[float] = None
    prev_close: Optional[float] = None
    gap_pct: Optional[float] = None
    drawdown_pct: Optional[float] = None
    ret_6m_pct: Optional[float] = None
    vol_ratio: Optional[float] = None
    pct_vs_ma20: Optional[float] = None
    market_cap_cr: Optional[float] = None
    near_52w_low: bool = False
    sector: str = "—"
    industry: str = "—"


@dataclass
class IntradaySetup:
    sentiment: str = "NEUTRAL"
    strength: int = 1
    bias: str = "WAIT_AND_WATCH"
    entry: str = ""
    target: str = ""
    stop: str = ""
    rules: list[str] = field(default_factory=list)
    risk: str = "MEDIUM"
    risk_note: str = ""
    indicator: str = ""
    suggestion: str = ""
    react_by: str = ""
    exit_by: str = ""
    react_windows: list[str] = field(default_factory=list)


@dataclass
class IntradayIntelRecord:
    ticker: str
    name: str
    sector: str
    news: str
    news_type: str
    news_date: str
    latest_news: str
    stock_context: StockContext
    intraday: IntradaySetup
    screener_url: str = ""
    nse_url: str = ""
    order_value_cr: Optional[float] = None
    order_value_label: str = "—"
    published_at: str = "—"
    tv_news: str = "—"
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


@dataclass
class MarketTheme:
    title: str
    icon: str
    summary: str
    rule: str


def _yahoo_ticker(slug: str) -> str:
    s = (slug or "").strip()
    if not s:
        return ""
    if s.endswith((".NS", ".BO")):
        return s
    if s.isdigit():
        return f"{s}.BO"
    return f"{s.upper()}.NS"


def _amount_unit_to_cr(val: float, unit: str) -> float:
    u = (unit or "").lower()
    if u.startswith("lakh"):
        return val / 100.0
    if u.startswith("million") or u == "mn":
        return val * 0.1
    return val


def _parse_rupees_to_cr(text: str) -> Optional[float]:
    blob = text or ""
    for pattern in _ORDER_VALUE_PATTERNS:
        m = pattern.search(blob)
        if not m:
            continue
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        return round(_amount_unit_to_cr(val, m.group(2)), 2)
    return None


def extract_order_win_value(
    text: str,
    news_type: str,
) -> tuple[Optional[float], str]:
    """Parse order-win rupee value for table display (amount in ₹ Cr)."""
    if news_type != "ORDER_WIN":
        return None, "—"
    low = (text or "").lower()
    if any(k in low for k in _UNDISCLOSED_ORDER_KW):
        return None, "Undisclosed"
    amount_cr = _parse_rupees_to_cr(text)
    if amount_cr is not None:
        if amount_cr >= 100:
            return amount_cr, f"₹{amount_cr:,.0f} Cr"
        if amount_cr >= 1:
            return amount_cr, f"₹{amount_cr:,.1f} Cr"
        return amount_cr, f"₹{amount_cr * 100:,.0f} L"
    mw_m = _MW_ORDER_RE.search(text or "")
    if mw_m:
        return None, f"{mw_m.group(1).replace(',', '')} MW"
    return None, "—"


def format_screener_published(item: ScreenerBuybackItem) -> str:
    """
    Screener.in publish time for the table:
    - relative age (15m, 2h) → estimated IST timestamp
    - calendar date (10 June 2026) → date only
    - else raw age_text
    """
    age_raw = (item.age_text or "").strip()
    if item.published:
        pub_ist = item.published.astimezone(IST)
        if age_raw and _REL_AGE_RE.match(age_raw):
            return pub_ist.strftime("%d %b %Y %H:%M IST")
        if age_raw and not _REL_AGE_RE.match(age_raw):
            return pub_ist.strftime("%d %b %Y")
        return pub_ist.strftime("%d %b %Y %H:%M IST")
    if age_raw:
        return age_raw
    return "—"


def classify_news_type(text: str) -> str:
    low = (text or "").lower()
    if any(
        k in low
        for k in (
            "spurt in volume",
            "volume spurt",
            "unusual volume",
            "volume alert",
            "significant increase in volume",
        )
    ):
        return "VOLUME_ALERT"
    if "sought clarification" in low or (
        "clarification" in low and "price movement" in low
    ):
        if any(
            k in low
            for k in (
                "no undisclosed",
                "no material",
                "no information",
                "denied",
                "not aware",
            )
        ):
            return "CLARIFICATION_NEUTRAL"
        return "CLARIFICATION_PENDING"
    if any(
        k in low
        for k in (
            "gst",
            "penalty",
            "demand confirmed",
            "litigation",
            "lawsuit",
            "appeal against",
            "sebi penalty",
            "regulatory action",
            "appellate order",
        )
    ):
        return "LEGAL_NEGATIVE"
    if is_order_announcement(text):
        return "ORDER_WIN"
    if any(k in low for k in ("order", "contract", "loa", "work order", "purchase order")):
        return "ORDER_WIN"
    return "OTHER"


def _fmt_inr(price: float) -> str:
    return f"₹{price:,.2f}"


def _info_float(info: dict, keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        val = info.get(key)
        if val is None:
            continue
        try:
            fv = float(val)
            if fv > 0:
                return fv
        except (TypeError, ValueError):
            continue
    return None


def _gap_vs_prev_close(ltp: float, prev_close: float) -> Optional[float]:
    if prev_close <= 0:
        return None
    return round((ltp - prev_close) / prev_close * 100.0, 2)


def fetch_stock_context(raw_ticker: str) -> StockContext:
    ctx = StockContext()
    if not raw_ticker:
        ctx.note = "Ticker unresolved — check NSE symbol."
        return ctx

    try:
        import yfinance as yf

        from screener import (
            compute_volume_ratio,
            fetch_price_history,
            get_sector_industry,
        )
    except ImportError:
        from .screener import (  # type: ignore[no-redef]
            compute_volume_ratio,
            fetch_price_history,
            get_sector_industry,
        )

    hist = fetch_price_history(raw_ticker, "1d")
    if hist is None or hist.empty or len(hist) < 20:
        ctx.note = "Insufficient price history for context."
        return ctx

    info: dict = {}
    try:
        info = yf.Ticker(raw_ticker).info or {}
    except Exception:
        info = {}

    prev_close = _info_float(info, ("previousClose", "regularMarketPreviousClose"))
    if prev_close is None and len(hist) >= 2:
        prev_close = float(hist["Close"].iloc[-2])
    elif prev_close is None:
        prev_close = float(hist["Close"].iloc[-1])

    ltp = _info_float(info, ("regularMarketPrice", "currentPrice"))
    if ltp is None:
        ltp = float(hist["Close"].iloc[-1])

    ctx.price = round(ltp, 2)
    ctx.prev_close = round(prev_close, 2) if prev_close else None
    ctx.gap_pct = _gap_vs_prev_close(ltp, prev_close) if prev_close else None
    ctx.approx_price = _fmt_inr(ltp)

    window = hist.tail(252) if len(hist) >= 252 else hist
    whigh = float(window["High"].max())
    wlow = float(window["Low"].min())
    ctx.week_high52 = _fmt_inr(whigh)
    ctx.week_low52 = _fmt_inr(wlow)
    ctx.drawdown_pct = round((whigh - ltp) / whigh * 100, 1) if whigh else None
    ctx.near_52w_low = bool(wlow and ltp <= wlow * 1.08)

    bars_6m = min(126, len(hist) - 1)
    if bars_6m > 0:
        ctx.ret_6m_pct = round((ltp / float(hist["Close"].iloc[-bars_6m]) - 1) * 100, 1)

    vr = compute_volume_ratio(hist["Volume"])
    ctx.vol_ratio = round(float(vr), 2) if vr is not None else None

    ma20_s = hist["Close"].rolling(20).mean()
    if len(ma20_s) and ma20_s.iloc[-1] == ma20_s.iloc[-1]:
        ma20 = float(ma20_s.iloc[-1])
        ctx.pct_vs_ma20 = round((ltp - ma20) / ma20 * 100, 1)

    ret6 = ctx.ret_6m_pct or 0.0
    dd = ctx.drawdown_pct or 0.0
    if ret6 < -15:
        ctx.trend = "DOWN_TREND"
    elif ctx.near_52w_low and ret6 < 5:
        ctx.trend = "RECOVERY"
    elif dd < 8 and ret6 > 20:
        ctx.trend = "SPECULATIVE_RUN"
    elif abs(ret6) < 8 and dd < 20:
        ctx.trend = "NEUTRAL"
    elif ret6 > 0:
        ctx.trend = "WEAK_RECOVERY"
    else:
        ctx.trend = "HIGH_VOLATILITY"

    notes: list[str] = []
    if ctx.gap_pct is not None:
        notes.append(f"Gap {ctx.gap_pct:+.2f}% vs prev close")
    if ctx.drawdown_pct is not None:
        notes.append(f"{ctx.drawdown_pct:.0f}% below 52-week high")
    if ctx.ret_6m_pct is not None:
        notes.append(f"6M return {ctx.ret_6m_pct:+.1f}%")
    if ctx.vol_ratio is not None:
        notes.append(f"Vol ratio {ctx.vol_ratio:.1f}x")
    if ctx.near_52w_low:
        notes.append("Trading near 52-week lows")

    try:
        sec, ind = get_sector_industry(yf.Ticker(raw_ticker))
        ctx.sector = sec or "—"
        ctx.industry = ind or "—"
        mcap = info.get("marketCap")
        if mcap:
            ctx.market_cap_cr = round(float(mcap) / 1e7, 1)
            notes.append(f"Mcap ~₹{ctx.market_cap_cr:.0f} Cr")
    except Exception:
        pass

    ctx.note = ". ".join(notes) if notes else "Limited tape context available."
    return ctx


def _order_strength(
    news_text: str,
    ctx: StockContext,
) -> tuple[int, bool, Optional[float]]:
    order_cr = _parse_rupees_to_cr(news_text)
    govt = any(k in news_text.lower() for k in GOVT_KW)
    undisclosed = any(
        k in news_text.lower()
        for k in ("undisclosed", "not disclosed", "value not", "no value")
    )
    mcap = ctx.market_cap_cr
    material = False
    if order_cr and mcap and mcap > 0:
        material = order_cr / mcap >= 0.08
    elif order_cr and order_cr >= 50:
        material = True

    strength = 1
    if undisclosed:
        strength = 1
    elif material and govt:
        strength = 3
    elif material or govt:
        strength = 2
    elif order_cr and order_cr >= 10:
        strength = 2
    return strength, govt, order_cr


def ist_now() -> datetime:
    return datetime.now(IST)


def ist_clock_label() -> str:
    return ist_now().strftime("%H:%M IST")


def market_session_phase() -> str:
    """NSE cash session phase for UI urgency hints."""
    now = ist_now()
    if now.weekday() >= 5:
        return "WEEKEND"
    t = now.time()
    if t < time(9, 0):
        return "PRE_OPEN"
    if t < time(9, 15):
        return "PRE_MARKET"
    if t < time(9, 30):
        return "OPENING_15M"
    if t < time(10, 0):
        return "MORNING_SETUP"
    if t < time(11, 30):
        return "MID_MORNING"
    if t < time(13, 30):
        return "MIDDAY"
    if t < time(15, 15):
        return "AFTERNOON"
    if t < time(15, 30):
        return "CLOSING"
    return "POST_MARKET"


def _build_reaction_schedule(
    *,
    news_type: str,
    bias: str,
    strength: int,
    ctx: StockContext,
) -> tuple[str, str, list[str]]:
    """Return (react_by, exit_by, react_windows) in IST."""
    windows: list[str] = [
        "08:45–09:10 IST — Pre-market: read filing, note prev day high/low, set price alerts.",
        "09:15 IST — Market open: watch gap % vs prev close (do not chase blind gap-ups).",
    ]

    if news_type == "ORDER_WIN":
        if bias == "WAIT_AND_WATCH":
            react_by = "10:00 AM IST"
            exit_by = "1:30 PM IST (if entered)"
            windows += [
                "09:15–09:30 IST — If flat open (<0.5% gap), wait for 9:30–10:00 consolidation break.",
                "09:30–10:00 IST — React only if gap-up >3% with volume >1.5x 30-min average.",
                "10:00 AM IST — Decision deadline: enter, pass, or wait for value disclosure.",
            ]
        elif strength >= 3:
            react_by = "9:45 AM IST"
            exit_by = "1:30 PM IST"
            windows += [
                "09:15–09:30 IST — First 15-min candle must close above open for momentum long.",
                "09:30–09:45 IST — Volume must exceed 1.5x average; confirm ORB breakout.",
                "09:45 AM IST — Enter on confirmed breakout or VWAP hold; skip if volume fails.",
                "1:30 PM IST — Hard exit if target not hit (event names give back afternoon gains).",
            ]
        elif strength == 2:
            react_by = "10:00 AM IST"
            exit_by = "1:30 PM IST"
            windows += [
                "09:30 IST — Watch 5-min volume surge; avoid entries before first 15 min close.",
                "09:30–10:00 IST — Confirm delivery % and sector peers before adding size.",
                "10:00 AM IST — Final entry window for moderate-catalyst longs.",
                "1:30 PM IST — Trim or exit — do not hold event trades into close.",
            ]
        else:
            react_by = "9:45 AM IST"
            exit_by = "11:00 AM IST"
            windows += [
                "09:15–09:30 IST — Narrative trade only: buy early momentum above open.",
                "09:45 AM IST — Last chance to enter; skip if volume already fading.",
                "11:00 AM IST — Mandatory exit — small-order names lose steam after lunch.",
            ]
        if ctx.near_52w_low:
            windows.append("09:30 IST — Near 52W low: size down 50%; bounce trades only.")

    elif news_type == "VOLUME_ALERT":
        react_by = "9:30 AM IST"
        exit_by = "12:00 PM IST (longs) · 3:00 PM IST (shorts)"
        windows += [
            "09:15–09:30 IST — Watch opening spike; short only on rejection below prev close.",
            "09:30 AM IST — React: failed gap-up = short trigger; do not buy second gap-up.",
            "12:00 PM IST — Cover long attempts; volume-alert longs rarely work afternoon.",
        ]

    elif news_type == "LEGAL_NEGATIVE":
        react_by = "9:20 AM IST"
        exit_by = "12:00 PM IST"
        windows += [
            "09:15–09:20 IST — Read open vs prev close; skip short if already down >4%.",
            "09:20 AM IST — Short on failure to hold prev close (flat/weak open).",
            "10:00 AM IST — Watch for company clarification that could reverse tone.",
            "12:00 PM IST — Close tactical shorts before lunch chop.",
        ]

    elif news_type == "CLARIFICATION_NEUTRAL":
        react_by = "9:30 AM IST"
        exit_by = "1:00 PM IST"
        windows += [
            "09:15 IST — Expect flat/down bias after 'no material info' filing.",
            "09:15–09:30 IST — Short on rejection candle if pop fails at open.",
            "09:30 AM IST — React on first 15-min breakdown; do not buy dips.",
            "1:00 PM IST — Exit shorts — illiquid small caps chop in afternoon.",
        ]

    elif news_type == "CLARIFICATION_PENDING":
        react_by = "10:00 AM IST"
        exit_by = "Depends on 10 AM filing"
        windows += [
            "09:00 IST — Check NSE/BSE filings before open for overnight response.",
            "09:15 IST — Do NOT trade until response is read — binary outcome.",
            "10:00 AM IST — If no company response by now, avoid (chop risk).",
            "Post-response — Positive: buy first 15-min ORB. Negative: short fade.",
        ]

    elif bias.startswith("SHORT"):
        react_by = "9:30 AM IST"
        exit_by = "1:00 PM IST"
        windows += [
            "09:15–09:30 IST — Confirm tape weakness before shorting.",
            "09:30 AM IST — Entry on rejection / breakdown.",
            "1:00 PM IST — Cover shorts on small caps.",
        ]

    else:
        react_by = "10:00 AM IST"
        exit_by = "1:30 PM IST (if setup confirms)"
        windows += [
            "09:30–10:00 IST — Wait for tape confirmation; no filing-only entries.",
            "10:00 AM IST — Decide: trade only if volume + direction align.",
        ]

    return react_by, exit_by, windows


def _risk_level(
    news_type: str,
    ctx: StockContext,
    strength: int,
) -> str:
    if news_type in ("CLARIFICATION_PENDING",):
        return "VERY_HIGH"
    if news_type == "VOLUME_ALERT":
        return "HIGH"
    if ctx.near_52w_low and (ctx.ret_6m_pct or 0) < -10:
        return "HIGH"
    if news_type == "LEGAL_NEGATIVE":
        return "MEDIUM"
    if strength >= 3 and (ctx.drawdown_pct or 0) > 35:
        return "HIGH"
    if strength <= 1:
        return "LOW_TO_MEDIUM"
    if (ctx.vol_ratio or 0) < 0.8:
        return "MEDIUM_HIGH"
    return "MEDIUM"


def analyze_intraday_setup(
    *,
    news_type: str,
    news_text: str,
    ctx: StockContext,
    latest_news: str = "",
) -> IntradaySetup:
    text = f"{news_text} {latest_news}".strip()
    low = text.lower()
    setup = IntradaySetup()

    if news_type == "ORDER_WIN":
        strength, govt, order_cr = _order_strength(text, ctx)
        setup.strength = strength
        undisclosed = "undisclosed" in low or "not disclosed" in low

        if undisclosed:
            setup.sentiment = "NEUTRAL"
            setup.bias = "WAIT_AND_WATCH"
            setup.entry = "Wait for order value disclosure or >3% gap-up with volume"
            setup.target = "N/A until value known"
            setup.stop = "Below prev close"
            setup.rules = [
                "No order size = weak catalyst — market often ignores undisclosed orders.",
                "If stock opens up >3% with volume >1.5x avg, treat as confirmation.",
                "Check Screener company page for updated filing before sizing up.",
                "Sector tailwind can matter more than headline on slow movers.",
            ]
            setup.risk_note = "Low catalyst strength until order value is known."
        elif strength >= 3:
            setup.sentiment = "BULLISH"
            setup.bias = "LONG"
            setup.entry = "Buy on ORB breakout above prev day high or VWAP hold in first 30 min"
            setup.target = "+5–8% intraday (high-beta)" if (ctx.drawdown_pct or 0) > 25 else "+3–5% intraday"
            setup.stop = "Below ORB low or VWAP loss"
            setup.rules = [
                "Hard catalyst — validate with volume >1.5x avg in first 30 min.",
                "Wait for first 15-min candle close above open to confirm momentum.",
                "Government-linked orders carry lower execution-risk perception.",
                "Size down if stock already up >2 days before the news.",
                "Exit by 1:30 PM if target not hit — thin names give back gains.",
            ]
            if govt:
                setup.rules.insert(2, "Government / PSU buyer — treat as durable revenue signal.")
            if order_cr:
                setup.rules.insert(0, f"Order ~₹{order_cr:.1f} Cr — check vs mcap before sizing.")
        elif strength == 2:
            setup.sentiment = "MILDLY_BULLISH" if not ctx.near_52w_low else "CAUTIOUSLY_BULLISH"
            setup.bias = "LONG"
            setup.entry = "Buy on 5-min volume surge after 9:30 AM; ORB breakout preferred"
            setup.target = "+2–4% intraday"
            setup.stop = "Below ORB low or prev day low"
            setup.rules = [
                "Moderate catalyst — confirm delivery % and volume before adding.",
                "Avoid chasing >3% gap without volume confirmation.",
                "Narrative + sector momentum can amplify small order wins.",
                "Use trailing stop after +2% — reversal risk on extended names.",
            ]
            if ctx.near_52w_low:
                setup.rules.append("Near 52-week lows — bounce trade only; size down.")
        else:
            setup.sentiment = "MILDLY_BULLISH"
            setup.bias = "LONG_SMALL_SIZE"
            setup.entry = "Early session momentum only; buy above open with tight stop"
            setup.target = "+2–3%"
            setup.stop = "Below opening range low"
            setup.rules = [
                "Small order relative to company — narrative trade, not fundamental repricing.",
                "Exit by 11 AM if volume fades.",
                "Do not pyramid — micro-caps punish averaging on fakeouts.",
            ]

    elif news_type == "VOLUME_ALERT":
        setup.sentiment = "NEUTRAL_TO_CAUTIOUS"
        setup.strength = 2
        setup.bias = "SHORT_BIAS_OR_AVOID"
        setup.entry = (
            "Short if gap-up fails below prev close; long ONLY with market green + vol >2x"
        )
        setup.target = "Short: -3 to -5% | Long: +2%"
        setup.stop = "Short: above day high | Long: below ORB low"
        setup.rules = [
            "NSE volume spurt without fresh fundamental news = operator / FOMO risk.",
            "Do not buy blind gap-ups on volume-alert names.",
            "Short on rejection candle after first 15 min if opening spike fades.",
            "If already down >4% at open, avoid new shorts — news may be priced in.",
            "Follow Nifty direction — speculative names amplify index moves.",
        ]
        setup.risk_note = "Classic pump pattern risk — prefer short side on failure."

    elif news_type == "LEGAL_NEGATIVE":
        setup.sentiment = "MILDLY_BEARISH"
        setup.strength = 2
        order_cr = _parse_rupees_to_cr(text) or 0
        mcap = ctx.market_cap_cr or 0
        material = mcap > 0 and order_cr / mcap > 0.03
        setup.bias = "SHORT_BIAS" if material or (ctx.ret_6m_pct or 0) < 0 else "AVOID_OR_SHORT_SMALL"
        setup.entry = "Short on gap-down or failure to hold prev close on flat open"
        setup.target = "-2 to -3%"
        setup.stop = "Above prev close + 0.5%"
        setup.rules = [
            "Legal / GST events create cash-flow uncertainty until resolved.",
            "Short bias only if amount is material vs mcap OR stock is in downtrend.",
            "On strong market days, legal overhang is often ignored — step aside.",
            "If stock opens down >4%, downside may be priced in — no fresh shorts.",
            "Watch for company clarification by 10 AM that could reverse tone.",
        ]
        setup.risk_note = "Tactical short only when tape confirms weakness."

    elif news_type == "CLARIFICATION_NEUTRAL":
        setup.sentiment = "BEARISH_BIAS"
        setup.strength = 2
        setup.bias = "SHORT_ON_REJECTION"
        setup.entry = "Short if flat/down open after 'no material info' style response"
        setup.target = "-3 to -5%"
        setup.stop = "Above prev 2-day high"
        setup.rules = [
            "'No material information' = pump may lack fundamental support.",
            "Exchange query + denial often triggers retail exit.",
            "Do not buy into clarity events without a new positive catalyst.",
            "Cover fast if stock continues up despite denial.",
            "Avoid illiquid afternoon sessions on small caps.",
        ]
        setup.risk_note = "Post-exchange-query fade setup — confirm with price action."

    elif news_type == "CLARIFICATION_PENDING":
        setup.sentiment = "BINARY"
        setup.strength = 1
        setup.bias = "WAIT"
        setup.entry = "Do not trade until company responds — then ORB breakout or short fade"
        setup.target = "Depends on response"
        setup.stop = "Depends on response"
        setup.rules = [
            "Pending clarification = binary outcome — not an intraday setup yet.",
            "Check NSE filings at open for company response.",
            "If no response by 10 AM, expect chop — avoid.",
            "Positive catalyst → buy first 15-min breakout with tight stop.",
            "'No info' response → apply short-on-rejection logic.",
        ]
        setup.risk_note = "Avoid until clarity — outcome unpredictable."

    else:
        setup.sentiment = "NEUTRAL"
        setup.strength = 1
        setup.bias = "WAIT_AND_WATCH"
        setup.entry = "No clear intraday edge from filing alone — wait for tape"
        setup.target = "—"
        setup.stop = "—"
        setup.rules = [
            "Filing does not match order / legal / volume templates — verify manually.",
            "Cross-check latest news on Screener company page.",
            "Trade only if price action confirms a directional move with volume.",
        ]
        setup.risk_note = "Unclassified filing — low conviction."

    setup.risk = _risk_level(news_type, ctx, setup.strength)
    react_by, exit_by, react_windows = _build_reaction_schedule(
        news_type=news_type,
        bias=setup.bias,
        strength=setup.strength,
        ctx=ctx,
    )
    setup.react_by = react_by
    setup.exit_by = exit_by
    setup.react_windows = react_windows
    setup.indicator = _build_indicator(setup)
    setup.suggestion = _build_suggestion(news_type, setup, ctx)
    return setup


def _build_indicator(setup: IntradaySetup) -> str:
    bias = setup.bias.replace("_", " ")
    stars = "★" * setup.strength + "☆" * (3 - setup.strength)
    sent = setup.sentiment.replace("_", " ")
    timing = f"React by {setup.react_by}" if setup.react_by else ""
    parts = [f"{sent} {stars}", bias, timing, f"Risk {setup.risk.replace('_', ' ')}"]
    return " · ".join(p for p in parts if p)


def _build_suggestion(
    news_type: str,
    setup: IntradaySetup,
    ctx: StockContext,
) -> str:
    if setup.bias in ("WAIT", "WAIT_AND_WATCH"):
        return f"Wait for confirmation — no aggressive entry before {setup.react_by or 'tape clarity'}."
    if setup.bias.startswith("SHORT"):
        return f"Fade strength / short rejection — act by {setup.react_by or '9:30 AM IST'}."
    if news_type == "ORDER_WIN" and setup.strength >= 3:
        return f"Primary long — ORB breakout + volume by 9:45 AM; exit by 1:30 PM if flat."
    if news_type == "ORDER_WIN":
        return f"Conditional long — confirm volume in first 30 min; decide by {setup.react_by}."
    if news_type == "VOLUME_ALERT":
        return f"Avoid chasing — watch failed gap-up; short trigger by {setup.react_by}."
    if news_type == "CLARIFICATION_NEUTRAL":
        return f"Fade bias — short on rejection in first 15 min ({setup.react_by})."
    if news_type == "CLARIFICATION_PENDING":
        return f"Do not trade until filing clarity — deadline {setup.react_by}."
    exit_bit = f" Exit by {setup.exit_by}." if setup.exit_by else ""
    return f"Monitor tape — decide by {setup.react_by}.{exit_bit}"


def _news_line(item: ScreenerBuybackItem) -> str:
    parts = [item.title.replace("_", " ")]
    if item.summary:
        parts.append(item.summary)
    elif item.age_text:
        parts.append(item.age_text)
    return " — ".join(parts) if len(parts) > 1 else parts[0]


def _news_date(item: ScreenerBuybackItem) -> str:
    if item.age_text and not re.match(r"\d+\s*[mhd]", item.age_text.strip(), re.I):
        return item.age_text.strip()
    if item.published:
        return item.published.astimezone(timezone.utc).strftime("%d %b %Y")
    return item.age_text or datetime.now(timezone.utc).strftime("%d %b %Y")


def build_intel_record(
    item: ScreenerBuybackItem,
    *,
    latest_news: str = "",
    stock_ctx: Optional[StockContext] = None,
) -> IntradayIntelRecord:
    slug = (item.company_slug or "").strip()
    yahoo = _yahoo_ticker(slug)
    display_ticker = slug.upper() if slug else "—"
    news_text = _news_line(item)
    if latest_news and latest_news not in news_text:
        news_text = f"{news_text} | {latest_news}"

    news_type = classify_news_type(news_text)
    ctx = stock_ctx or fetch_stock_context(yahoo)
    sector = ctx.sector
    if ctx.industry and ctx.industry != "—":
        sector = f"{sector} / {ctx.industry}" if sector != "—" else ctx.industry

    intraday = analyze_intraday_setup(
        news_type=news_type,
        news_text=news_text,
        ctx=ctx,
        latest_news=latest_news,
    )
    order_value_cr, order_value_label = extract_order_win_value(news_text, news_type)
    published_at = format_screener_published(item)

    return IntradayIntelRecord(
        ticker=display_ticker,
        name=item.company or display_ticker,
        sector=sector,
        news=_news_line(item),
        news_type=news_type,
        news_date=_news_date(item),
        latest_news=latest_news or "—",
        stock_context=ctx,
        intraday=intraday,
        screener_url=_screener_company_url(item.company, slug),
        nse_url=_nse_quote_url(yahoo),
        order_value_cr=order_value_cr,
        order_value_label=order_value_label,
        published_at=published_at,
    )


def _announcement_recency_key(
    item: ScreenerBuybackItem,
    feed_index: int,
) -> tuple:
    """Higher = more recent. Uses published time, relative age, then feed position."""
    if item.published:
        return (0, item.published.timestamp(), -feed_index)
    mins = _parse_age_minutes(item.age_text or "")
    if mins is not None:
        return (1, -mins, -feed_index)
    return (2, -feed_index)


def _newer_announcement(
    left: ScreenerBuybackItem,
    left_idx: int,
    right: ScreenerBuybackItem,
    right_idx: int,
) -> ScreenerBuybackItem:
    lk = _announcement_recency_key(left, left_idx)
    rk = _announcement_recency_key(right, right_idx)
    return left if lk >= rk else right


def build_intel_batch(
    announcements: list[ScreenerBuybackItem],
    *,
    news_by_slug: Optional[dict[str, str]] = None,
    max_companies: int = 30,
    enrich_prices: bool = True,
    sort_by: str = "newest",
) -> list[IntradayIntelRecord]:
    """One intel card per company (newest actionable filing — skips exchange queries)."""
    news_map = news_by_slug or {}
    grouped: dict[str, list[tuple[int, ScreenerBuybackItem]]] = defaultdict(list)
    for idx, item in enumerate(announcements):
        slug = (item.company_slug or "").strip().upper()
        if not slug:
            continue
        grouped[slug].append((idx, item))

    by_slug: dict[str, ScreenerBuybackItem] = {}
    slug_index: dict[str, int] = {}
    for slug, pairs in grouped.items():
        actionable = [
            (idx, it)
            for idx, it in pairs
            if not is_exchange_clarification_filing(f"{it.title} {it.summary}")
        ]
        if not actionable:
            continue
        best_idx, best_item = max(
            actionable,
            key=lambda p: _announcement_recency_key(p[1], p[0]),
        )
        by_slug[slug] = best_item
        slug_index[slug] = best_idx

    ranked_slugs = sorted(
        by_slug.keys(),
        key=lambda s: _announcement_recency_key(by_slug[s], slug_index[s]),
        reverse=True,
    )
    slugs = ranked_slugs[:max_companies]
    ctx_cache: dict[str, StockContext] = {}
    if enrich_prices:
        for slug in slugs:
            yahoo = _yahoo_ticker(slug)
            if yahoo:
                ctx_cache[slug] = fetch_stock_context(yahoo)

    out: list[IntradayIntelRecord] = []
    for slug in slugs:
        item = by_slug[slug]
        latest = news_map.get(slug) or news_map.get(slug.lower()) or ""
        out.append(
            build_intel_record(
                item,
                latest_news=latest,
                stock_ctx=ctx_cache.get(slug),
            )
        )

    if sort_by == "strength":
        out.sort(
            key=lambda r: (r.intraday.strength, r.news_type == "ORDER_WIN"),
            reverse=True,
        )
    else:
        slug_order = {s: i for i, s in enumerate(slugs)}
        out.sort(key=lambda r: slug_order.get(r.ticker.upper(), 999))
    return out


def build_market_themes(records: list[IntradayIntelRecord]) -> list[MarketTheme]:
    if not records:
        return []

    themes: list[MarketTheme] = []
    type_counts: dict[str, int] = {}
    order_wins = 0
    govt_orders = 0
    vol_alerts = 0
    legal = 0
    clarifications = 0
    ai_narrative = 0

    for r in records:
        type_counts[r.news_type] = type_counts.get(r.news_type, 0) + 1
        blob = f"{r.news} {r.latest_news}".lower()
        if r.news_type == "ORDER_WIN":
            order_wins += 1
            if any(k in blob for k in GOVT_KW):
                govt_orders += 1
        if r.news_type == "VOLUME_ALERT":
            vol_alerts += 1
        if r.news_type == "LEGAL_NEGATIVE":
            legal += 1
        if r.news_type.startswith("CLARIFICATION"):
            clarifications += 1
        if any(k in blob for k in AI_NARRATIVE_KW):
            ai_narrative += 1

    n = len(records)
    if order_wins:
        pct = int(order_wins / n * 100)
        themes.append(
            MarketTheme(
                title="Order-Win Momentum",
                icon="📦",
                summary=(
                    f"{order_wins} of {n} names ({pct}%) show order / contract wins. "
                    "Infrastructure, EPC, and manufacturing orders dominate when capex themes are active."
                ),
                rule=(
                    "On order-win days: wait for gap-up confirmation, watch the first 15-min candle, "
                    "and validate volume >1.5x average before entry. Don't chase >3% gaps without volume."
                ),
            )
        )

    if govt_orders and order_wins:
        gpct = int(govt_orders / max(order_wins, 1) * 100)
        themes.append(
            MarketTheme(
                title="PSU / Government Infra Capex",
                icon="🏛️",
                summary=(
                    f"{govt_orders} order-win names ({gpct}% of wins) have government-linked buyers. "
                    "Sector bid can outweigh single-name noise."
                ),
                rule=(
                    "When most order wins are govt-linked, scale up on intraday dips in the theme. "
                    "Government contracts = lower perceived execution risk."
                ),
            )
        )

    if clarifications:
        themes.append(
            MarketTheme(
                title="Exchange Clarification Pattern",
                icon="⚠️",
                summary=(
                    f"{clarifications} names have exchange clarification filings. "
                    "'No material info' responses often fade; pending = binary — avoid until resolved."
                ),
                rule=(
                    "No material info → short on rejection. Pending → avoid until clarity. "
                    "Never buy exchange-query stocks without knowing the catalyst."
                ),
            )
        )

    if legal:
        themes.append(
            MarketTheme(
                title="GST / Legal Overhang",
                icon="⚖️",
                summary=(
                    f"{legal} names carry GST / legal headlines. "
                    "Impact depends on amount vs market cap and broader market tone."
                ),
                rule=(
                    "Legal shorts work when amount >3% of mcap OR stock is in downtrend. "
                    "On strong market days, legal news is often noise."
                ),
            )
        )

    if vol_alerts:
        themes.append(
            MarketTheme(
                title="Volume Spurt Alerts",
                icon="🔊",
                summary=(
                    f"{vol_alerts} names flagged for unusual volume. "
                    "Back-to-back alerts without earnings = distribution / FOMO risk."
                ),
                rule=(
                    "Volume alerts without news → short on failure. "
                    "Never buy a second consecutive gap-up without an earnings catalyst."
                ),
            )
        )

    if ai_narrative:
        themes.append(
            MarketTheme(
                title="AI / Tech Narrative Plays",
                icon="🤖",
                summary=(
                    f"{ai_narrative} names mention AI / SaaS / fintech narratives. "
                    "Retail magnet themes — shelf life ~60–90 minutes intraday."
                ),
                rule=(
                    "Narrative trades: buy early, exit before lunch. "
                    "Skip if 5-min RSI already stretched at entry."
                ),
            )
        )

    bullish = sum(1 for r in records if r.intraday.bias.startswith("LONG"))
    if bullish >= 3:
        themes.append(
            MarketTheme(
                title="Batch Intraday Bias",
                icon="📊",
                summary=(
                    f"{bullish} of {n} setups lean LONG today. "
                    "Prioritize ORB + volume confirmation; fade weak gaps on volume-alert names."
                ),
                rule=(
                    "Rank by strength ★★★ first, then filter by risk. "
                    "Exit winners by 1:30 PM on event-driven small caps."
                ),
            )
        )

    return themes
