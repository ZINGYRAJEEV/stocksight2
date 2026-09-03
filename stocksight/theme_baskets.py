"""
Named NSE theme baskets (curated idea lists) for screeners.

Emerging Market Growth Club — validated from the “50% Growth Club /
India’s Emerging Market Leaders” idea sheet (directional niche growth).
"""

from __future__ import annotations

# Yahoo-style .NS symbols. Labels are display names used in UI / notes.
EMERGING_MARKET_GROWTH_CLUB: list[dict[str, str]] = [
    {
        "label": "E2E Networks",
        "ticker": "E2E.NS",
        "theme": "AI / GPU cloud rentals",
        "note": "Infographic name matched. NSE: E2E.",
    },
    {
        "label": "Sudeep Pharma",
        "ticker": "SUDEEPPHRM.NS",
        "theme": "Pharma → LFP iron phosphate (EV batteries)",
        "note": "Infographic said “Sudip Pharma”; listed name is Sudeep Pharma (SUDEEPPHRM).",
    },
    {
        "label": "Aeroflex Industries",
        "ticker": "AEROFLEX.NS",
        "theme": "AI data-center cooling / skid assemblies",
        "note": "Infographic name matched. NSE: AEROFLEX.",
    },
    {
        "label": "Amanta Healthcare",
        "ticker": "AMANTA.NS",
        "theme": "Sterile IV / dual-port bottles",
        "note": "Infographic said “Aamanta”; listed name is Amanta Healthcare (AMANTA).",
    },
    {
        "label": "Bluestone Jewellery",
        "ticker": "BLUESTONE.NS",
        "theme": "Online-first jewellery retail",
        "note": "Infographic said “Blue Stone”; listed name is Bluestone (BLUESTONE).",
    },
]

EMERGING_MARKET_GROWTH_CLUB_TICKERS: list[str] = [
    row["ticker"] for row in EMERGING_MARKET_GROWTH_CLUB
]

EMERGING_MARKET_LABEL = "Theme · Emerging Market Growth Club (NSE)"


def emerging_market_universe() -> list[str]:
    return list(EMERGING_MARKET_GROWTH_CLUB_TICKERS)


def theme_universe_map() -> dict[str, list[str]]:
    """Labels → Yahoo tickers for UNIVERSES / intraday baskets."""
    return {
        EMERGING_MARKET_LABEL: emerging_market_universe(),
    }
