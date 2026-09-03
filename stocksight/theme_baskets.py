"""
Named NSE theme baskets (curated idea lists) for screeners.

Emerging Market Growth Club — validated from the “50% Growth Club /
India’s Emerging Market Leaders” idea sheet (directional niche growth),
plus similar-health peers in each niche.
"""

from __future__ import annotations

from typing import Iterable

# Yahoo-style .NS symbols. Labels are display names used in UI / notes.
EMERGING_MARKET_GROWTH_CLUB: list[dict[str, str]] = [
    {
        "label": "E2E Networks",
        "ticker": "E2E.NS",
        "theme": "AI / GPU cloud rentals",
        "note": "Infographic name matched. NSE: E2E.",
    },
    {
        "label": "Netweb Technologies",
        "ticker": "NETWEB.NS",
        "theme": "AI / GPU cloud rentals",
        "note": "Peer — GPU / server infra adjacency to E2E.",
    },
    {
        "label": "Sudeep Pharma",
        "ticker": "SUDEEPPHRM.NS",
        "theme": "Pharma → LFP iron phosphate (EV batteries)",
        "note": "Infographic said “Sudip Pharma”; listed name is Sudeep Pharma (SUDEEPPHRM).",
    },
    {
        "label": "Neogen Chemicals",
        "ticker": "NEOGEN.NS",
        "theme": "Pharma → LFP iron phosphate (EV batteries)",
        "note": "Peer — specialty chemicals / battery materials.",
    },
    {
        "label": "PCBL Chemical",
        "ticker": "PCBL.NS",
        "theme": "Pharma → LFP iron phosphate (EV batteries)",
        "note": "Peer — carbon black / battery-adjacent materials.",
    },
    {
        "label": "Himadri Speciality",
        "ticker": "HSCL.NS",
        "theme": "Pharma → LFP iron phosphate (EV batteries)",
        "note": "Peer — speciality chemicals (listed as HSCL).",
    },
    {
        "label": "Aeroflex Industries",
        "ticker": "AEROFLEX.NS",
        "theme": "AI data-center cooling / skid assemblies",
        "note": "Infographic name matched. NSE: AEROFLEX.",
    },
    {
        "label": "EPack Prefab Technologies",
        "ticker": "EPACK.NS",
        "theme": "AI data-center cooling / skid assemblies",
        "note": "Peer — prefab / modular data-center builds.",
    },
    {
        "label": "Blue Star",
        "ticker": "BLUESTARCO.NS",
        "theme": "AI data-center cooling / skid assemblies",
        "note": "Peer — commercial HVAC / cooling systems.",
    },
    {
        "label": "Amanta Healthcare",
        "ticker": "AMANTA.NS",
        "theme": "Sterile IV / dual-port bottles",
        "note": "Infographic said “Aamanta”; listed name is Amanta Healthcare (AMANTA).",
    },
    {
        "label": "Gland Pharma",
        "ticker": "GLAND.NS",
        "theme": "Sterile IV / dual-port bottles",
        "note": "Peer — injectables CDMO.",
    },
    {
        "label": "Caplin Point Labs",
        "ticker": "CAPLIPOINT.NS",
        "theme": "Sterile IV / dual-port bottles",
        "note": "Peer — sterile injectables focus.",
    },
    {
        "label": "Sai Life Sciences",
        "ticker": "SAILIFE.NS",
        "theme": "Sterile IV / dual-port bottles",
        "note": "Peer — CRAMS / injectables.",
    },
    {
        "label": "Bluestone Jewellery",
        "ticker": "BLUESTONE.NS",
        "theme": "Online-first jewellery retail",
        "note": "Infographic said “Blue Stone”; listed name is Bluestone (BLUESTONE).",
    },
    {
        "label": "Kalyan Jewellers",
        "ticker": "KALYANKJIL.NS",
        "theme": "Online-first jewellery retail",
        "note": "Peer — organised jewellery retail.",
    },
    {
        "label": "Senco Gold",
        "ticker": "SENCO.NS",
        "theme": "Online-first jewellery retail",
        "note": "Peer — branded gold retail.",
    },
    {
        "label": "Thangamayil Jewellery",
        "ticker": "THANGAMAYL.NS",
        "theme": "Online-first jewellery retail",
        "note": "Peer — regional jewellery chain.",
    },
    {
        "label": "Sky Gold",
        "ticker": "SKYGOLD.NS",
        "theme": "Online-first jewellery retail",
        "note": "Peer — gold jewellery manufacturer / retail.",
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


def theme_scan_source_labels() -> list[str]:
    """Universe labels for all theme baskets."""
    return list(theme_universe_map().keys())


def is_theme_scan_source(label: str) -> bool:
    return bool(label) and str(label).startswith("Theme ·")


def is_nse_scan_source(label: str) -> bool:
    """True for NSE index universes, curated NSE lists, and theme baskets."""
    if not label:
        return False
    s = str(label)
    if is_theme_scan_source(s):
        return True
    if "Curated" in s and "US" not in s:
        return True
    return "NSE" in s


def nse_scan_sources(sources: Iterable[str]) -> list[str]:
    """
    NSE-facing universe labels from a SCAN_SOURCES list.

    Order: curated NSE → theme baskets → other NSE universes (deduped).
    """
    src = list(sources)
    themes = [t for t in theme_scan_source_labels() if t in src]
    curated = [s for s in src if "Curated" in s and "US" not in s]
    nse_rest = [
        s
        for s in src
        if is_nse_scan_source(s) and s not in themes and s not in curated
    ]
    out: list[str] = []
    seen: set[str] = set()
    for group in (curated, themes, nse_rest):
        for s in group:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out
