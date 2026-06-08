"""
Pre-investigation links — Screener.in shortcuts for corporate announcements & orders.

Curated URLs for research before trading on order wins, open offers, delisting, etc.
"""

from __future__ import annotations

from dataclasses import dataclass

META = {
    "id": "pre_investigation",
    "title": "Pre-Investigation Links",
    "emoji": "🔎",
    "nav_title": "Pre-Investigation Links",
    "audience": (
        "Investors who scan **corporate announcements** on Screener.in before acting on "
        "order wins, buybacks, open offers, delisting, demergers, or warrant issues."
    ),
    "purpose": (
        "One-click bookmarks to Screener.in full-text search and results — "
        "use alongside StockSight screeners and the **Buyback Screener**."
    ),
}

# Shared corporate-action search (open offer, delisting, demerger, buyback, NCLT)
_CORPORATE_ACTIONS_URL = (
    "https://www.screener.in/full-text-search/?q=%22open+offer%22+or+%22delisting%22+"
    "or+%22demerger%22+or+%22buyback%22+or+%22+buy+back%22+or+%22scheme+of+arrangement%22+"
    "or+%22NCLT%22"
)

BIG_ORDERS_URL = (
    "https://www.screener.in/full-text-search/?q=-%22Commissioner%22+-%22tax%22+-%22gst%22+"
    "%22order+received%22+or+%22award+of+order%22+or+%22Notification+of+Award%22+or+"
    "%22letter+of+intent%22+or+%22large+order%22+or++%22Order+for+Procurement%22+or+"
    "%22Awarding+of+order%22+or+%22bagged+an+order+%22+or+%22Letter+of+Award%22+or+"
    "%22repeat+order%22+or+%22additional+order%22+or+%22Contract+Award%22%29"
)

WARRANT_ISSUE_URL = (
    "https://www.screener.in/full-text-search/?q=%22Preferential+Issue%22+or+"
    "%22Issue+Of+Warrants%22+or+%22Preferential+Allotment"
)

PEAD_URL = "https://www.screener.in/results/latest/"

BUYBACK_URL = "https://www.screener.in/full-text-search/?q=buyback&type=announcements"


@dataclass(frozen=True)
class InvestigationLink:
    id: str
    title: str
    emoji: str
    url: str
    summary: str
    tips: str = ""
    category: str = "Announcements"


LINKS: tuple[InvestigationLink, ...] = (
    InvestigationLink(
        id="big_orders",
        title="Big Orders",
        emoji="📦",
        url=BIG_ORDERS_URL,
        category="Order flow",
        summary=(
            "Large contract wins — order received, letter of award, LOI, repeat/additional orders. "
            "Excludes tax/GST noise."
        ),
        tips="Read order value vs market cap. Check execution timeline and margin impact.",
    ),
    InvestigationLink(
        id="open_offers",
        title="Open Offers",
        emoji="📨",
        url=_CORPORATE_ACTIONS_URL,
        category="Corporate actions",
        summary="Open offer announcements — acquirer buying public shareholders (Takeover Code).",
        tips="Compare offer price to CMP; note minimum acceptance and closing date.",
    ),
    InvestigationLink(
        id="delisting",
        title="Delisting",
        emoji="🚪",
        url=_CORPORATE_ACTIONS_URL,
        category="Corporate actions",
        summary="Voluntary delisting and related open offers — exit liquidity events.",
        tips="Check floor price, reverse book building, and dissenting shareholder rights.",
    ),
    InvestigationLink(
        id="demergers",
        title="Demergers",
        emoji="✂️",
        url=_CORPORATE_ACTIONS_URL,
        category="Corporate actions",
        summary="Demerger / scheme of arrangement / NCLT filings — value unlock spin-offs.",
        tips="Track record date, swap ratio, and listed entity post demerger.",
    ),
    InvestigationLink(
        id="warrant_issue",
        title="Warrant Issue",
        emoji="🎫",
        url=WARRANT_ISSUE_URL,
        category="Capital raising",
        summary="Preferential issue, warrant allotment — dilution and conversion price matter.",
        tips="Note warrant strike, tenure, and promoter participation.",
    ),
    InvestigationLink(
        id="pead",
        title="PeAD (Post-Earnings Announcement Drift)",
        emoji="📊",
        url=PEAD_URL,
        category="Earnings",
        summary="Latest quarterly results on Screener — screen for earnings surprises and drift setups.",
        tips="Cross-check result date vs price reaction; use with StockSight quality gate.",
    ),
    InvestigationLink(
        id="buybacks",
        title="Buybacks",
        emoji="💰",
        url=BUYBACK_URL,
        category="Corporate actions",
        summary="Tender and open-market buyback announcements.",
        tips="Use StockSight **Buyback Screener** for acceptance ratio & small-holder return.",
    ),
)

CATEGORIES = tuple(dict.fromkeys(lk.category for lk in LINKS))
