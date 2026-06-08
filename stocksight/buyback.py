"""
Stock buyback screener — acceptance ratio & expected return (General vs Small Shareholder).

Based on tender-offer buyback analysis: SEBI reserves 15% of buyback size for small
shareholders (holdings ≤ ₹2 lakh). Formulas verified against Bajaj Auto case study.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# SEBI: tender buybacks reserve 15% of size for small shareholders
SMALL_QUOTA_PCT_OF_BUYBACK = 15.0
GENERAL_QUOTA_PCT_OF_BUYBACK = 85.0
SMALL_HOLDER_VALUE_LIMIT_INR = 200_000
DEFAULT_PARTICIPATION_PCT = 50.0
WORTH_PLAYING_RETURN_PCT = 8.0

META = {
    "id": "buyback",
    "title": "Buyback Screener",
    "emoji": "💰",
    "nav_title": "Buyback Screener",
    "audience": (
        "Investors participating in **tender offer buybacks** who want to estimate "
        "**acceptance ratio** and **expected return** — especially under the **small shareholder quota**."
    ),
    "purpose": (
        "Spreadsheet-style calculator: compare General vs Small category returns, "
        "sensitivity to post-buyback price, and break-even. Target: small-holder return **> 8%**."
    ),
}


@dataclass
class BuybackInputs:
    stock: str = ""
    raw_ticker: str = ""
    buyback_pct: float = 0.0  # % of total equity
    small_holder_holding_pct: float = 1.0  # % equity held by eligible small holders
    participation_pct: float = DEFAULT_PARTICIPATION_PCT
    offer_type: str = "Tender"
    announcement_price: float = 0.0
    buyback_price: float = 0.0
    record_date: str = ""
    post_buyback_price: float = 0.0
    status: str = "active"  # active | past


@dataclass
class BuybackAnalysis:
    stock: str
    raw_ticker: str
    buyback_pct: float
    small_holder_holding_pct: float
    participation_pct: float
    offer_type: str
    announcement_price: float
    buyback_price: float
    record_date: str
    post_buyback_price: float
    premium_pct: float
    general_acceptance_pct: float
    small_acceptance_pct: float
    general_expected_return_pct: float
    small_expected_return_pct: float
    small_break_even_post_price: float
    worth_playing: bool
    status: str = "active"
    links: dict[str, str] = field(default_factory=dict)
    notes: str = ""


def max_shares_small_category(price: float, limit_inr: float = SMALL_HOLDER_VALUE_LIMIT_INR) -> int:
    if price <= 0:
        return 0
    return max(1, int(limit_inr / price))


def general_holding_pct(small_holder_holding_pct: float) -> float:
    return max(0.0, 100.0 - float(small_holder_holding_pct))


def acceptance_ratio_pct(
    buyback_pct: float,
    category_holding_pct: float,
    participation_pct: float,
    quota_pct_of_buyback: float,
) -> float:
    """
    Estimated % of your shares the company will accept.

    buyback allocated to category = buyback_pct × (quota/100)
    shares tendered (est) = category_holding × (participation/100)
    acceptance = min(100%, allocated / tendered × 100)
    """
    if buyback_pct <= 0 or category_holding_pct <= 0 or participation_pct <= 0:
        return 0.0
    allocated = buyback_pct * (quota_pct_of_buyback / 100.0)
    tendered = category_holding_pct * (participation_pct / 100.0)
    if tendered <= 0:
        return 0.0
    return min(100.0, (allocated / tendered) * 100.0)


def expected_return_pct(
    announcement_price: float,
    buyback_price: float,
    post_buyback_price: float,
    acceptance_pct: float,
) -> float:
    """Weighted return: accepted shares at buyback price, remainder at post-buyback CMP."""
    if announcement_price <= 0:
        return 0.0
    ar = acceptance_pct / 100.0
    weighted = ar * buyback_price + (1.0 - ar) * post_buyback_price
    return round((weighted / announcement_price - 1.0) * 100.0, 2)


def break_even_post_price(
    announcement_price: float,
    buyback_price: float,
    acceptance_pct: float,
) -> float:
    """Post-buyback CMP where expected return hits 0%."""
    if announcement_price <= 0:
        return 0.0
    ar = acceptance_pct / 100.0
    if ar >= 1.0:
        return announcement_price
    if ar <= 0:
        return announcement_price
    return round((announcement_price - ar * buyback_price) / (1.0 - ar), 2)


def sensitivity_table(
    announcement_price: float,
    buyback_price: float,
    acceptance_pct: float,
    post_prices: Optional[list[float]] = None,
) -> list[dict]:
    if post_prices is None:
        step = announcement_price * 0.1
        post_prices = [
            round(announcement_price + step * i, 2)
            for i in range(-5, 8)
        ]
    rows = []
    for px in post_prices:
        ret = expected_return_pct(announcement_price, buyback_price, px, acceptance_pct)
        rows.append({"Post-buyback price": px, "Expected return %": ret})
    return rows


def analyze_buyback(inp: BuybackInputs, *, links: Optional[dict[str, str]] = None) -> BuybackAnalysis:
    ann = float(inp.announcement_price)
    bb = float(inp.buyback_price)
    post = float(inp.post_buyback_price) if inp.post_buyback_price > 0 else ann
    small_h = float(inp.small_holder_holding_pct)
    gen_h = general_holding_pct(small_h)
    part = float(inp.participation_pct)
    bb_pct = float(inp.buyback_pct)

    gen_ar = acceptance_ratio_pct(bb_pct, gen_h, part, GENERAL_QUOTA_PCT_OF_BUYBACK)
    small_ar = acceptance_ratio_pct(bb_pct, small_h, part, SMALL_QUOTA_PCT_OF_BUYBACK)
    gen_ret = expected_return_pct(ann, bb, post, gen_ar)
    small_ret = expected_return_pct(ann, bb, post, small_ar)
    premium = round((bb / ann - 1.0) * 100.0, 2) if ann > 0 else 0.0

    return BuybackAnalysis(
        stock=inp.stock,
        raw_ticker=inp.raw_ticker,
        buyback_pct=bb_pct,
        small_holder_holding_pct=small_h,
        participation_pct=part,
        offer_type=inp.offer_type,
        announcement_price=ann,
        buyback_price=bb,
        record_date=inp.record_date,
        post_buyback_price=post,
        premium_pct=premium,
        general_acceptance_pct=round(gen_ar, 2),
        small_acceptance_pct=round(small_ar, 2),
        general_expected_return_pct=gen_ret,
        small_expected_return_pct=small_ret,
        small_break_even_post_price=break_even_post_price(ann, bb, small_ar),
        worth_playing=small_ret >= WORTH_PLAYING_RETURN_PCT,
        status=inp.status,
        links=links or {},
        notes=inp.offer_type,
    )


def analysis_to_row(a: BuybackAnalysis) -> dict:
    return {
        "Stock": a.stock,
        "Buyback %": a.buyback_pct,
        "Small holder holding %": a.small_holder_holding_pct,
        "Participation %": a.participation_pct,
        "Type": a.offer_type,
        "Ann. price": a.announcement_price,
        "Buyback price": a.buyback_price,
        "Record date": a.record_date,
        "Post-buyback price": a.post_buyback_price,
        "Premium %": a.premium_pct,
        "General acceptance %": a.general_acceptance_pct,
        "Small acceptance %": a.small_acceptance_pct,
        "General return %": a.general_expected_return_pct,
        "Small return %": a.small_expected_return_pct,
        "Break-even post": a.small_break_even_post_price,
        "Worth playing (>8%)": "✅" if a.worth_playing else "—",
        "Status": a.status,
        "Raw": a.raw_ticker,
        **{k: v for k, v in a.links.items()},
    }


# Seed examples (Bajaj Auto verified; others illustrative from common buybacks)
SAMPLE_OPPORTUNITIES: list[BuybackInputs] = [
    BuybackInputs(
        stock="Bajaj Auto",
        raw_ticker="BAJAJ-AUTO.NS",
        buyback_pct=1.41,
        small_holder_holding_pct=1.0,
        participation_pct=50.0,
        offer_type="Tender",
        announcement_price=6900.0,
        buyback_price=10000.0,
        record_date="29-Feb-2024",
        post_buyback_price=6900.0,
        status="past",
    ),
    BuybackInputs(
        stock="TCS",
        raw_ticker="TCS.NS",
        buyback_pct=1.5,
        small_holder_holding_pct=2.5,
        participation_pct=50.0,
        offer_type="Tender",
        announcement_price=3800.0,
        buyback_price=4250.0,
        record_date="",
        post_buyback_price=3800.0,
        status="past",
    ),
    BuybackInputs(
        stock="Wipro",
        raw_ticker="WIPRO.NS",
        buyback_pct=2.0,
        small_holder_holding_pct=3.0,
        participation_pct=50.0,
        offer_type="Tender",
        announcement_price=450.0,
        buyback_price=500.0,
        record_date="",
        post_buyback_price=450.0,
        status="past",
    ),
]
