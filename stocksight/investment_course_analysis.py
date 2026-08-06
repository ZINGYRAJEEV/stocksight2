"""
Post-scan analysis helpers for Investment Course (Steps 3–6).

Automates the manual checklist: category research prompts, story builder,
Rulebook stress test, and practical stance / sizing / exit guidance.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote_plus

# Category → research questions (Workflow A–E from Stock_Analysis_Workflow_1.md)
CATEGORY_RESEARCH: dict[str, list[dict[str, str]]] = {
    "Fast Grower": [
        {
            "id": "growth_source",
            "q": "Where will the next 3 years of growth come from?",
            "hint": "New products, geography, market share, capacity, efficiency — check presentations & concalls.",
        },
        {
            "id": "reinvestment",
            "q": "Is management reinvesting (capex / R&D / brand) rather than milking cash?",
            "hint": "Annual report + cash-flow: growing fixed assets / expansion notes.",
        },
        {
            "id": "margin_path",
            "q": "Can margins hold as the business scales?",
            "hint": "OPM trail on Screener P&L; peer ASPs if commodity-like.",
        },
        {
            "id": "dilution",
            "q": "Any dilution risk (QIP / ESOP / large equity raise)?",
            "hint": "Share count trend on Screener; recent fundraises in news.",
        },
    ],
    "Stalwart": [
        {
            "id": "growth_steady",
            "q": "Is growth steady (not spiky) over several years?",
            "hint": "Screener P&L — look for consistency, not just the average.",
        },
        {
            "id": "margin_stable",
            "q": "Are margins stable year to year?",
            "hint": "OPM row — wobble is a caution flag for stalwarts.",
        },
        {
            "id": "future_plans",
            "q": "Does management still have clear forward plans?",
            "hint": "Investor presentation + latest concall guidance.",
        },
        {
            "id": "trim_rule",
            "q": "Have you set a trim rule (~30–40% gain or PE stretch)?",
            "hint": "Lynch-style: buy for 30–50%, trim when delivered or multiple peaks.",
        },
    ],
    "Cyclical": [
        {
            "id": "demand_supply",
            "q": "Is demand/supply roughly in balance (not at peak)?",
            "hint": "Industry news, broker reports (Trendlyne), concalls.",
        },
        {
            "id": "opm_rising",
            "q": "Is OPM rising with room left to rise?",
            "hint": "Screener OPM trail — rising with room = better entry window.",
        },
        {
            "id": "promoter_buy",
            "q": "Any promoter / insider buying in shareholding?",
            "hint": "Screener → Shareholding Pattern.",
        },
        {
            "id": "capacity",
            "q": "New capacity — growth or future glut?",
            "hint": "Investor presentations; industry capacity announcements.",
        },
    ],
    "Turnaround": [
        {
            "id": "trigger",
            "q": "Is there a real turnaround trigger (mgmt / strategy / policy)?",
            "hint": "News, AR, concall — not just hope.",
        },
        {
            "id": "debt_cut",
            "q": "Is debt actually falling YoY?",
            "hint": "Screener Balance Sheet → Borrowings.",
        },
        {
            "id": "shareholding",
            "q": "Do shareholding changes show confidence?",
            "hint": "Promoter / institutional buying on Screener.",
        },
        {
            "id": "credibility",
            "q": "Do you trust management credibility on this recovery?",
            "hint": "Highest story-risk category — weight this heavily.",
        },
    ],
    "Slow Grower": [
        {
            "id": "confirm_slow",
            "q": "Is it truly slow — or a temporarily depressed fast grower?",
            "hint": "Multi-year P&L on Screener.",
        },
        {
            "id": "why_slow",
            "q": "Why is growth slow (mgmt / pond size / competition / disruption)?",
            "hint": "MD&A + industry news — decides hold-vs-avoid.",
        },
        {
            "id": "dividend",
            "q": "Is there a specific reason to hold (dividend / deep value)?",
            "hint": "Default: FD may be better use of capital.",
        },
    ],
}

DEFAULT_RESEARCH = [
    {
        "id": "understand",
        "q": "Do you understand the product / customer / how they make money?",
        "hint": "Circle of competence — skip if unclear.",
    },
    {
        "id": "industry",
        "q": "Is the industry in a tailwind or headwind?",
        "hint": "Broker reports, credit notes, presentations.",
    },
]

STORY_CHECKS: list[dict[str, str]] = [
    {
        "id": "scam",
        "label": "Google promoter + scam / fraud check",
        "link_key": "Google scam check",
    },
    {
        "id": "youtube",
        "label": "Watch a management interview (YouTube)",
        "link_key": "YouTube interviews",
    },
    {
        "id": "glassdoor",
        "label": "Glassdoor culture rating ≥ 3.0",
        "link_key": "Glassdoor",
    },
    {
        "id": "concall",
        "label": "Read / listen to latest concall + presentation",
        "link_key": "Screener Concalls",
    },
    {
        "id": "credit",
        "label": "Skim credit rating / risk notes on Screener",
        "link_key": "Screener.in",
    },
    {
        "id": "valuepickr",
        "label": "Skim Value Pickr / peer discussion (optional)",
        "link_key": "Value Pickr",
    },
]


def category_research_items(category: str) -> list[dict[str, str]]:
    items = list(CATEGORY_RESEARCH.get(category) or [])
    # Always prepend circle-of-competence style defaults
    return list(DEFAULT_RESEARCH) + items


def enrich_research_links(links: dict, disp: str, company_name: str = "") -> dict:
    """Add YouTube / Documents links used by the post-scan checklist."""
    out = dict(links or {})
    slug = (disp or "").strip().upper()
    q = quote_plus(company_name or slug)
    out.setdefault("Screener.in", f"https://www.screener.in/company/{slug}/consolidated/")
    out.setdefault(
        "Screener Concalls",
        f"https://www.screener.in/company/{slug}/consolidated/#documents",
    )
    out.setdefault(
        "YouTube interviews",
        f"https://www.youtube.com/results?search_query={q}+CEO+OR+MD+interview",
    )
    out.setdefault("Glassdoor", f"https://www.glassdoor.com/Search/results.htm?keyword={q}")
    out.setdefault(
        "Google scam check",
        f"https://www.google.com/search?q={q}+scam+OR+fraud+OR+SEBI",
    )
    out.setdefault("Value Pickr", f"https://forum.valuepickr.com/search?q={q}")
    out.setdefault("Trendlyne", f"https://trendlyne.com/search/?q={q}")
    return out


def draft_story_paragraph(r: Any) -> str:
    """One-paragraph story starter from scan fields (user edits to finish)."""
    name = getattr(r, "label", None) or getattr(r, "ticker", "This company")
    cat = getattr(r, "category", "—") or "—"
    sales = getattr(r, "sales_growth_3y_pct", None)
    profit = getattr(r, "profit_growth_3y_pct", None)
    opm = getattr(r, "opm_latest_pct", None)
    sector = getattr(r, "sector", None) or "its sector"

    growth_bit = "growth data incomplete"
    if sales is not None and profit is not None:
        growth_bit = f"~{sales:.0f}% sales / ~{profit:.0f}% profit CAGR (3Y)"
    elif sales is not None:
        growth_bit = f"~{sales:.0f}% sales CAGR (3Y)"

    opm_bit = f"OPM around {opm:.0f}%" if opm is not None else "check OPM on Screener"
    peg = getattr(r, "peg", None)
    peg_bit = f"PEG {peg:.2f}" if peg is not None else "PEG n/a"
    dma50 = getattr(r, "pct_vs_50dma", None)
    dma_bit = f"{dma50:+.1f}% vs 50-DMA" if dma50 is not None else "DMA n/a"

    return (
        f"{name} is a **{cat}** in {sector} with {growth_bit}. "
        f"Near-term quality check: {opm_bit}; valuation cue: {peg_bit}; trend: {dma_bit}. "
        f"Future growth should come from: ____ (capacity / products / geography / share). "
        f"Main risk: ____ (competition / margin / dilution / cycle). "
        f"I would only buy if I believe: ____."
    )


def practical_stance(r: Any, stress: Optional[dict] = None) -> dict[str, Any]:
    """
    Step 6 — bull / bear / size / exit guidance from scan + optional stress result.
    Educational heuristics only.
    """
    cat = getattr(r, "category", "") or ""
    is_strong = bool(getattr(r, "is_strong_wealth", False))
    upside = getattr(r, "upside_pct", None)
    cagr = getattr(r, "implied_cagr_pct", None)
    peg = getattr(r, "peg", None)
    dma50 = getattr(r, "pct_vs_50dma", None)
    dma200 = getattr(r, "pct_vs_200dma", None)
    qf = int(getattr(r, "checklist_score", 0) or 0)
    qf_max = int(getattr(r, "checklist_max", 7) or 7)
    price = getattr(r, "price", None)
    max_buy = getattr(r, "max_buy_15pct", None)

    bull: list[str] = []
    bear: list[str] = []

    if cat == "Fast Grower":
        bull.append("Categorized as Fast Grower on sales + profit CAGR gates.")
    elif cat == "Stalwart":
        bull.append("Stalwart profile — suitable as portfolio ballast if valuation is right.")
    elif cat == "Slow Grower":
        bear.append("Slow Grower — default is pass unless dividend / deep-value thesis is clear.")
    elif cat == "Cyclical":
        bear.append("Cyclical — timing and OPM trail matter more than CAGR labels.")
    elif cat == "Turnaround":
        bear.append("Turnaround — highest story risk; size small until debt/mgmt proof shows up.")

    if is_strong:
        bull.append("Default Rulebook flags Strong wealth candidate.")
    if upside is not None and upside >= 20:
        bull.append(f"Model upside ~{upside:+.0f}% under default assumptions.")
    if cagr is not None and cagr >= 16:
        bull.append(f"Implied CAGR ~{cagr:.0f}% under defaults.")
    if peg is not None and peg < 1:
        bull.append(f"PEG {peg:.2f} < 1 (verify base-effect / one-off profit years).")
    if qf_max > 0 and qf >= max(qf_max - 1, 1):
        bull.append(f"Quick-Fire strong ({qf}/{qf_max}).")

    if peg is not None and peg > 1.5:
        bear.append(f"PEG {peg:.2f} stretched — growth may already be priced in.")
    if dma50 is not None and dma50 > 5:
        bear.append(f"Trading {dma50:+.1f}% above 50-DMA — not a deep pullback.")
    if dma50 is not None and dma50 < -15:
        bear.append(f"Deep vs 50-DMA ({dma50:+.1f}%) — confirm not a value trap.")
    if dma200 is not None and dma200 < -10:
        bear.append(f"Below 200-DMA ({dma200:+.1f}%) — long-term trend still weak.")
    if price is not None and max_buy is not None and price > max_buy:
        bear.append(
            f"LTP ₹{price:,.0f} above max buy @15% CAGR (₹{max_buy:,.0f}) on defaults."
        )

    stress = stress or {}
    survives = stress.get("survives_stress")
    if stress:
        if survives:
            bull.append(
                f"Stress case still workable "
                f"(upside {stress.get('upside_pct', '—')}%, "
                f"CAGR {stress.get('implied_cagr_pct', '—')}%)."
            )
        else:
            bear.append(
                "Fails conservative stress (lower growth / OPM / P/E) — treat as watchlist."
            )

    # Sizing heuristic
    if cat == "Slow Grower":
        size = "Skip / tiny only if special situation"
        action = "Pass unless you have a written dividend or deep-value thesis."
    elif cat == "Turnaround":
        size = "Very small starter (≤1–2% of equity book)"
        action = "Watch for debt cut + mgmt proof; add only on confirmed progress."
    elif cat == "Cyclical":
        size = "Small (≤2–3%); scale if OPM trail confirms"
        action = "Buy only with rising OPM + room left; avoid peak-margin complacency."
    elif survives is False:
        size = "Watchlist / paper only until stress improves"
        action = "Do not size up on default model alone — wait for better price or proof."
    elif is_strong and (survives is True or survives is None):
        size = "Starter tranche / SIP (2–4%); add on dips if story holds"
        action = "Prefer phased buys; re-check concall before each add."
    elif cat == "Stalwart" and (getattr(r, "pct_vs_median", 99) or 99) <= 0:
        size = "Core ballast slice (~portfolio ballast, not all-in)"
        action = "Plan trim after ~30–40% or when PE stretches above its mean."
    else:
        size = "Research further before sizing"
        action = "Finish story checklist + stress test, then decide."

    # Exit ideas
    exits: list[str] = []
    if cat == "Stalwart":
        exits.append("Trim after ~30–40% gain or when PE is far above historical mean.")
    if cat == "Fast Grower":
        exits.append("Revisit if growth drivers fade, margins compress, or dilution surprises.")
    if cat == "Cyclical":
        exits.append("Exit / trim when OPM peaks and industry capacity glut appears.")
    if cat == "Turnaround":
        exits.append("Cut if turnaround triggers fail (debt up, mgmt exit, missed launches).")
    exits.append("Cut if your one-paragraph story no longer matches concall reality.")
    if max_buy is not None:
        exits.append(
            f"Be cautious adding above max buy @15% CAGR (₹{max_buy:,.0f} on last model)."
        )

    # Overall label
    if cat == "Slow Grower":
        label = "Likely pass"
    elif survives is False:
        label = "Watchlist — stress failed"
    elif is_strong and (survives is True or not stress):
        label = "Candidate — phased entry if story OK"
    elif cat in ("Turnaround", "Cyclical"):
        label = "High-skill / small size only"
    else:
        label = "Needs story + stress before buy"

    return {
        "label": label,
        "action": action,
        "size": size,
        "bull": bull[:6],
        "bear": bear[:6],
        "exits": exits[:5],
    }
