"""
Growth & innovation qualitative research checklist.

Maps the manual research steps (Screener.in / Tijori / Trendlyne) used after
quantitative filters pass — credit ratings, annual reports, concalls, MD&A,
board pay, and broker research.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

try:
    from .screener import get_stock_links
except ImportError:
    from screener import get_stock_links

# Ordered checklist from the growth/opportunity + risk research notes.
GROWTH_INNOVATION_CHECKLIST: tuple[dict[str, str], ...] = (
    {
        "id": "credit_rating",
        "source": "Screener.in",
        "title": "Credit rating",
        "why": "Solvency / refinancing risk for growth companies that still use debt.",
        "how": "Open Screener → Documents / Ratings section; prefer stable or improving ratings.",
    },
    {
        "id": "annual_report",
        "source": "Screener.in",
        "title": "Annual report",
        "why": "Confirms the growth story, segment mix, related-party deals, and auditor notes.",
        "how": "Download the latest AR from Screener Documents; skim MD&A + notes to accounts.",
    },
    {
        "id": "concalls",
        "source": "Screener.in",
        "title": "Conference calls",
        "why": "Forward guidance, capacity, order book, and management tone on innovation bets.",
        "how": "Screener Documents → latest transcripts / audio; note guidance vs last quarter.",
    },
    {
        "id": "mda_letters_pay",
        "source": "Screener.in / AR",
        "title": "Management discussion, investor letters, board pay",
        "why": "Alignment and culture: inflated board salary vs profits is a red flag.",
        "how": "AR → MD&A + letter to shareholders; check remuneration of directors vs PAT.",
    },
    {
        "id": "tijori",
        "source": "Tijori Finance",
        "title": "Tijori Finance company data",
        "why": "Second source for filings, segment mix, and structural risk flags.",
        "how": "Search company on Tijori → Overview / Financials / Reports.",
    },
    {
        "id": "trendlyne",
        "source": "Trendlyne",
        "title": "Broker / research reports",
        "why": "Independent view on growth runway, valuation, and risks.",
        "how": "Trendlyne search → Research reports + concall videos.",
    },
)


def growth_innovation_research_links(
    disp: str,
    raw: str,
    company_name: str = "",
) -> dict[str, str]:
    """Deep links for the growth/innovation qualitative checklist."""
    links = dict(get_stock_links(raw) or {})
    slug = (disp or "").strip().upper()
    q = quote_plus(company_name or slug)
    if slug:
        base = f"https://www.screener.in/company/{slug}/consolidated/"
        links["Screener.in"] = base
        links["Screener Documents"] = f"{base}#documents"
        links["Screener Concalls"] = f"{base}#documents"
    links["Trendlyne"] = f"https://trendlyne.com/search/?q={q}"
    links["Trendlyne Reports"] = f"https://trendlyne.com/search/?q={q}"
    links["Tijori Finance"] = f"https://www.tijorifinance.com/search/?q={q}"
    links["Google AR / MD&A"] = (
        f"https://www.google.com/search?q={q}+annual+report+OR+MD%26A+OR+%22letter+to+shareholders%22"
    )
    links["Google board remuneration"] = (
        f"https://www.google.com/search?q={q}+%22remuneration%22+OR+%22managerial+remuneration%22"
    )
    return links


def checklist_rows_for_ticker(
    disp: str,
    raw: str,
    company_name: str = "",
) -> list[dict[str, Optional[str]]]:
    """UI-ready rows: title, source, why, how, primary_url."""
    links = growth_innovation_research_links(disp, raw, company_name)
    primary = {
        "credit_rating": links.get("Screener Documents") or links.get("Screener.in"),
        "annual_report": links.get("Screener Documents") or links.get("Screener.in"),
        "concalls": links.get("Screener Concalls") or links.get("Screener.in"),
        "mda_letters_pay": links.get("Google AR / MD&A"),
        "tijori": links.get("Tijori Finance"),
        "trendlyne": links.get("Trendlyne Reports") or links.get("Trendlyne"),
    }
    rows: list[dict[str, Optional[str]]] = []
    for item in GROWTH_INNOVATION_CHECKLIST:
        rows.append(
            {
                "id": item["id"],
                "title": item["title"],
                "source": item["source"],
                "why": item["why"],
                "how": item["how"],
                "url": primary.get(item["id"]),
            }
        )
    return rows
