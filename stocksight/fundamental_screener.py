"""
Fundamental Screener Framework — 3-tier debt-free / scam-free / fast-growth filter.

Implements docs/fundamental_screener_framework.md using Screener.in company pages
(+ Yahoo price history for Tier-3 momentum returns). Educational only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

try:
    from .multibagger import SCAN_SOURCES, extract_multibagger_fundamentals, resolve_scan_tickers
    from .screener import get_stock_links
    from .screener_in_data import fetch_screener_company_html, fetch_screener_fundamental_profile
except ImportError:
    from multibagger import SCAN_SOURCES, extract_multibagger_fundamentals, resolve_scan_tickers
    from screener import get_stock_links
    from screener_in_data import fetch_screener_company_html, fetch_screener_fundamental_profile

META = {
    "id": "fundamental_framework",
    "title": "Fundamental Screener (3-Tier)",
    "emoji": "🛡️",
    "nav_title": "Fundamental 3-Tier",
    "audience": (
        "Investors who want a **reliable, debt-free, scam-free, fast-growth** funnel "
        "before deploying capital — Watchlist → Strict → Momentum timing."
    ),
    "purpose": (
        "Applies the Fundamental Screener Framework: Tier 1 wide monthly watchlist, "
        "Tier 2 high-conviction buy candidates, Tier 3 momentum overlay for swing/BTST entry. "
        "Governance gates (debt / promoter / pledge) stay tight."
    ),
}

TIER_IDS = ("watchlist", "strict", "momentum")

TIER_LABELS: dict[str, str] = {
    "watchlist": "Tier 1 — Watchlist (monthly funnel)",
    "strict": "Tier 2 — Strict Fundamental (before capital)",
    "momentum": "Tier 3 — Momentum Overlay (entry timing)",
}

RANK_OPTIONS: dict[str, str] = {
    "score": "Framework score",
    "roe": "ROE (highest)",
    "growth": "Min(sales, profit) 3Y %",
    "peg": "PEG (lowest)",
    "mcap": "Market cap",
    "ret_3m": "3M return (Tier 3)",
}


@dataclass
class FundamentalFilters:
    tier: str = "watchlist"
    # Size
    min_market_cap_cr: float = 500.0
    # Debt-free / liquidity
    max_debt_equity: float = 0.5
    min_interest_coverage: float = 0.0  # 0 = off (Tier 1)
    min_current_ratio: float = 0.0  # 0 = off
    # Governance (scam-free guardrails — do not loosen casually)
    min_promoter_holding_pct: float = 40.0
    min_promoter_change_pct: float = -999.0  # -999 = off
    max_pledged_pct: float = 10.0
    # Quality
    min_roe_pct: float = 12.0
    min_avg_roe_3y_pct: float = 0.0  # 0 = off
    min_roce_pct: float = 0.0
    min_roa_pct: float = 0.0
    min_opm_pct: float = 0.0
    # Growth
    min_sales_growth_3y_pct: float = 8.0
    min_profit_growth_3y_pct: float = 8.0
    min_yoy_sales_pct: float = 0.0  # 0 = off
    min_yoy_profit_pct: float = 0.0
    # Valuation
    pe_vs_industry_max_gap: float = 5.0  # PE < Industry PE + gap; Tier2 uses 0
    require_pe_vs_industry: bool = True
    max_peg: float = 0.0  # 0 = off
    max_price_to_book: float = 0.0  # 0 = off
    # Momentum (Tier 3)
    min_ret_3m_pct: float = 0.0
    min_ret_6m_pct: float = 0.0
    require_acceleration: bool = False  # ret_3m > ret_1y / 4
    # Behaviour
    soft_skip_missing_valuation: bool = True  # skip PE-vs-industry / PEG / PB if data missing
    require_governance_data: bool = True  # fail if debt/promoter/pledge missing
    screener_delay_sec: float = 0.20
    max_results: int = 80


def filters_for_tier(tier: str) -> FundamentalFilters:
    """Preset thresholds from fundamental_screener_framework.md."""
    t = tier if tier in TIER_IDS else "watchlist"
    if t == "watchlist":
        return FundamentalFilters(
            tier="watchlist",
            min_market_cap_cr=500.0,
            max_debt_equity=0.5,
            min_promoter_holding_pct=40.0,
            max_pledged_pct=10.0,
            min_roe_pct=12.0,
            min_sales_growth_3y_pct=8.0,
            min_profit_growth_3y_pct=8.0,
            pe_vs_industry_max_gap=5.0,
            require_pe_vs_industry=True,
        )
    if t == "strict":
        return FundamentalFilters(
            tier="strict",
            min_market_cap_cr=1000.0,
            max_debt_equity=0.3,
            min_interest_coverage=8.0,
            min_current_ratio=1.5,
            min_promoter_holding_pct=50.0,
            min_promoter_change_pct=-2.0,
            max_pledged_pct=5.0,
            min_roe_pct=15.0,
            min_avg_roe_3y_pct=15.0,
            min_roce_pct=18.0,
            min_roa_pct=8.0,
            min_opm_pct=12.0,
            min_sales_growth_3y_pct=12.0,
            min_profit_growth_3y_pct=12.0,
            min_yoy_sales_pct=10.0,
            min_yoy_profit_pct=10.0,
            pe_vs_industry_max_gap=0.0,
            require_pe_vs_industry=True,
            max_peg=1.5,
            max_price_to_book=8.0,
        )
    # momentum
    return FundamentalFilters(
        tier="momentum",
        min_market_cap_cr=500.0,
        max_debt_equity=0.5,
        min_promoter_holding_pct=40.0,
        max_pledged_pct=10.0,
        min_roe_pct=12.0,
        min_sales_growth_3y_pct=8.0,
        min_profit_growth_3y_pct=8.0,
        require_pe_vs_industry=False,
        min_ret_3m_pct=0.0,
        min_ret_6m_pct=10.0,
        require_acceleration=True,
    )


@dataclass
class FundamentalResult:
    ticker: str
    raw_ticker: str
    label: str
    tier: str
    price: Optional[float]
    market_cap_cr: Optional[float]
    market_cap_display: str
    debt_equity: Optional[float]
    interest_coverage: Optional[float]
    current_ratio: Optional[float]
    promoter_holding_pct: Optional[float]
    promoter_change_pct: Optional[float]
    pledged_pct: Optional[float]
    roe_pct: Optional[float]
    avg_roe_3y_pct: Optional[float]
    roce_pct: Optional[float]
    roa_pct: Optional[float]
    opm_pct: Optional[float]
    sales_growth_3y_pct: Optional[float]
    profit_growth_3y_pct: Optional[float]
    yoy_sales_pct: Optional[float]
    yoy_profit_pct: Optional[float]
    pe: Optional[float]
    industry_pe: Optional[float]
    peg: Optional[float]
    price_to_book: Optional[float]
    ret_3m_pct: Optional[float]
    ret_6m_pct: Optional[float]
    ret_1y_pct: Optional[float]
    score: float
    verdict: str
    pass_notes: list[str] = field(default_factory=list)
    fail_soft: list[str] = field(default_factory=list)
    links: dict = field(default_factory=dict)


def _mcap_display(cr: Optional[float]) -> str:
    if cr is None:
        return "—"
    if cr >= 100_000:
        return f"₹{cr / 100_000:.2f} L Cr"
    if cr >= 1_000:
        return f"₹{cr:,.0f} Cr"
    return f"₹{cr:.0f} Cr"


def _score(profile: dict, flt: FundamentalFilters) -> float:
    pts = 0.0
    pts += min(float(profile.get("roe_pct") or 0), 40.0) * 0.5
    pts += min(float(profile.get("roce_pct") or 0), 40.0) * 0.35
    g = min(
        float(profile.get("sales_growth_3y_pct") or 0),
        float(profile.get("profit_growth_3y_pct") or 0),
        40.0,
    )
    pts += max(g, 0.0) * 0.6
    de = profile.get("debt_equity")
    if de is not None:
        pts += max(0.0, (flt.max_debt_equity - float(de)) * 20.0)
    peg = profile.get("peg")
    if peg is not None and peg > 0:
        pts += max(0.0, 15.0 - float(peg) * 8.0)
    if flt.tier == "momentum":
        pts += min(float(profile.get("ret_6m_pct") or 0), 40.0) * 0.4
    return round(pts, 1)


def _verdict(tier: str, score: float, notes: list[str]) -> str:
    if tier == "strict":
        if score >= 45:
            return "High-conviction candidate — verify story & size 1/15–1/20"
        return "Cleared Strict gates — dig into concall / annual report"
    if tier == "momentum":
        return "Momentum + fundamentals OK — identify catalyst before BTST/swing"
    if score >= 35:
        return "Strong watchlist name — track monthly repeats"
    return "Watchlist pass — research before Strict"


def _require(
    val: Optional[float],
    *,
    ok: bool,
    notes: list[str],
    label: str,
    missing_fail: bool,
) -> bool:
    if val is None:
        if missing_fail:
            return False
        notes.append(f"{label} n/a")
        return True
    if not ok:
        return False
    notes.append(label)
    return True


def _passes(profile: dict, flt: FundamentalFilters) -> tuple[bool, list[str], list[str]]:
    notes: list[str] = []
    soft: list[str] = []
    gov = bool(flt.require_governance_data)

    mcap = profile.get("market_cap_cr")
    if mcap is None or float(mcap) < flt.min_market_cap_cr:
        return False, notes, soft
    notes.append(f"Mcap {_mcap_display(mcap)}")

    de = profile.get("debt_equity")
    if not _require(
        de,
        ok=de is not None and float(de) < flt.max_debt_equity,
        notes=notes,
        label=f"D/E {de:.2f}" if de is not None else "D/E",
        missing_fail=gov,
    ):
        return False, notes, soft

    if flt.min_interest_coverage > 0:
        ic = profile.get("interest_coverage")
        if ic is None:
            if gov:
                return False, notes, soft
            soft.append("Interest coverage n/a")
        elif float(ic) < flt.min_interest_coverage:
            return False, notes, soft
        else:
            notes.append(f"ICR {ic:.1f}")

    if flt.min_current_ratio > 0:
        cr = profile.get("current_ratio")
        if cr is None:
            if not flt.soft_skip_missing_valuation:
                return False, notes, soft
            soft.append("Current ratio n/a")
        elif float(cr) < flt.min_current_ratio:
            return False, notes, soft
        else:
            notes.append(f"CR {cr:.2f}")

    prom = profile.get("promoter_holding_pct")
    if not _require(
        prom,
        ok=prom is not None and float(prom) > flt.min_promoter_holding_pct,
        notes=notes,
        label=f"Promoter {prom:.1f}%" if prom is not None else "Promoter",
        missing_fail=gov,
    ):
        return False, notes, soft

    if flt.min_promoter_change_pct > -900:
        chg = profile.get("promoter_change_pct")
        if chg is None:
            soft.append("Promoter Δ n/a")
        elif float(chg) <= flt.min_promoter_change_pct:
            return False, notes, soft
        else:
            notes.append(f"Promoter Δ {chg:+.1f}%")

    pledged = profile.get("pledged_pct")
    # Missing pledge often means 0 on Screener — treat None as 0 when promoter known
    if pledged is None and prom is not None:
        pledged = 0.0
        profile = dict(profile)
        profile["pledged_pct"] = 0.0
    if not _require(
        pledged,
        ok=pledged is not None and float(pledged) < flt.max_pledged_pct,
        notes=notes,
        label=f"Pledge {pledged:.1f}%" if pledged is not None else "Pledge",
        missing_fail=gov,
    ):
        return False, notes, soft

    roe = profile.get("roe_pct")
    if roe is None or float(roe) <= flt.min_roe_pct:
        return False, notes, soft
    notes.append(f"ROE {roe:.1f}%")

    if flt.min_avg_roe_3y_pct > 0:
        ar = profile.get("avg_roe_3y_pct")
        if ar is None:
            soft.append("Avg ROE 3Y n/a")
        elif float(ar) <= flt.min_avg_roe_3y_pct:
            return False, notes, soft
        else:
            notes.append(f"Avg ROE 3Y {ar:.1f}%")

    if flt.min_roce_pct > 0:
        roce = profile.get("roce_pct")
        if roce is None or float(roce) <= flt.min_roce_pct:
            return False, notes, soft
        notes.append(f"ROCE {roce:.1f}%")

    if flt.min_roa_pct > 0:
        roa = profile.get("roa_pct")
        if roa is None:
            soft.append("ROA n/a")
        elif float(roa) <= flt.min_roa_pct:
            return False, notes, soft
        else:
            notes.append(f"ROA {roa:.1f}%")

    if flt.min_opm_pct > 0:
        opm = profile.get("opm_pct")
        if opm is None or float(opm) <= flt.min_opm_pct:
            return False, notes, soft
        notes.append(f"OPM {opm:.1f}%")

    sg = profile.get("sales_growth_3y_pct")
    pg = profile.get("profit_growth_3y_pct")
    if sg is None or float(sg) <= flt.min_sales_growth_3y_pct:
        return False, notes, soft
    if pg is None or float(pg) <= flt.min_profit_growth_3y_pct:
        return False, notes, soft
    notes.append(f"Sales 3Y {sg:.1f}% · Profit 3Y {pg:.1f}%")

    if flt.min_yoy_sales_pct > 0:
        ys = profile.get("yoy_sales_pct")
        if ys is None or float(ys) <= flt.min_yoy_sales_pct:
            return False, notes, soft
        notes.append(f"YoY sales {ys:.1f}%")
    if flt.min_yoy_profit_pct > 0:
        yp = profile.get("yoy_profit_pct")
        if yp is None or float(yp) <= flt.min_yoy_profit_pct:
            return False, notes, soft
        notes.append(f"YoY profit {yp:.1f}%")

    if flt.require_pe_vs_industry:
        pe = profile.get("pe")
        ipe = profile.get("industry_pe")
        if pe is None or ipe is None:
            if not flt.soft_skip_missing_valuation:
                return False, notes, soft
            soft.append("PE vs Industry n/a")
        elif float(pe) >= float(ipe) + float(flt.pe_vs_industry_max_gap):
            return False, notes, soft
        else:
            notes.append(f"PE {pe:.1f} < Ind {ipe:.1f}+{flt.pe_vs_industry_max_gap:g}")

    if flt.max_peg > 0:
        peg = profile.get("peg")
        if peg is None:
            if not flt.soft_skip_missing_valuation:
                return False, notes, soft
            soft.append("PEG n/a")
        elif float(peg) >= flt.max_peg:
            return False, notes, soft
        else:
            notes.append(f"PEG {peg:.2f}")

    if flt.max_price_to_book > 0:
        pb = profile.get("price_to_book")
        if pb is None:
            if not flt.soft_skip_missing_valuation:
                return False, notes, soft
            soft.append("P/B n/a")
        elif float(pb) >= flt.max_price_to_book:
            return False, notes, soft
        else:
            notes.append(f"P/B {pb:.2f}")

    if flt.tier == "momentum" or flt.min_ret_6m_pct > 0 or flt.require_acceleration:
        r3 = profile.get("ret_3m_pct")
        r6 = profile.get("ret_6m_pct")
        r1 = profile.get("ret_1y_pct")
        if r3 is None or float(r3) <= flt.min_ret_3m_pct:
            return False, notes, soft
        if r6 is None or float(r6) <= flt.min_ret_6m_pct:
            return False, notes, soft
        notes.append(f"3M {r3:.1f}% · 6M {r6:.1f}%")
        if flt.require_acceleration:
            if r1 is None:
                return False, notes, soft
            if float(r3) <= float(r1) / 4.0:
                return False, notes, soft
            notes.append(f"Accel 3M>{r1:.1f}%/4")

    return True, notes, soft


def _yahoo_overlays(raw: str, profile: dict) -> dict:
    """Fill debt / P/B / returns from Yahoo when Screener gaps exist."""
    out = dict(profile)
    try:
        import yfinance as yf

        stock = yf.Ticker(raw)
        info = stock.info or {}
        fund = extract_multibagger_fundamentals(info)
        if out.get("debt_equity") is None and fund.get("debt_equity") is not None:
            out["debt_equity"] = fund.get("debt_equity")
        if out.get("price_to_book") is None:
            pb = info.get("priceToBook")
            if pb is not None:
                try:
                    out["price_to_book"] = round(float(pb), 2)
                except (TypeError, ValueError):
                    pass
        if out.get("roa_pct") is None:
            roa = info.get("returnOnAssets")
            if roa is not None:
                try:
                    v = float(roa)
                    out["roa_pct"] = round(v * 100.0 if abs(v) <= 1.5 else v, 2)
                except (TypeError, ValueError):
                    pass

        hist = stock.history(period="1y", auto_adjust=True)
        if hist is not None and len(hist) >= 30 and "Close" in hist.columns:
            close = hist["Close"]
            last = float(close.iloc[-1])

            def _ret(bars: int) -> Optional[float]:
                if len(close) <= bars:
                    return None
                prev = float(close.iloc[-(bars + 1)])
                if prev <= 0:
                    return None
                return round((last / prev - 1.0) * 100.0, 2)

            out.setdefault("ret_3m_pct", _ret(63))
            out.setdefault("ret_6m_pct", _ret(126))
            out.setdefault("ret_1y_pct", _ret(min(252, len(close) - 2)))
            if out.get("price") is None:
                out["price"] = round(last, 2)
    except Exception:
        pass
    return out


def scan_fundamental_framework(
    scan_source: str,
    filters: FundamentalFilters | None = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> list[FundamentalResult]:
    flt = filters or filters_for_tier("watchlist")
    if flt.tier not in TIER_IDS:
        flt = replace(flt, tier="watchlist")

    universe = resolve_scan_tickers(scan_source)
    if not universe:
        return []

    results: list[FundamentalResult] = []
    total = len(universe)

    for i, (label, raw) in enumerate(universe):
        if progress_cb:
            progress_cb(i + 1, total, raw)
        if len(results) >= int(flt.max_results):
            break
        if not (raw.endswith(".NS") or raw.endswith(".BO")):
            continue

        disp = raw.replace(".NS", "").replace(".BO", "")
        try:
            html = fetch_screener_company_html(disp)
            profile = fetch_screener_fundamental_profile(disp, html=html)
            if not profile:
                continue
            if flt.tier == "momentum" or profile.get("debt_equity") is None or profile.get(
                "price_to_book"
            ) is None:
                profile = _yahoo_overlays(raw, profile)

            ok, notes, soft = _passes(profile, flt)
            if not ok:
                continue

            score = _score(profile, flt)
            links = get_stock_links(raw)
            if profile.get("screener_url"):
                links = dict(links or {})
                links["Screener"] = profile["screener_url"]

            results.append(
                FundamentalResult(
                    ticker=disp,
                    raw_ticker=raw,
                    label=label if label != disp else disp,
                    tier=flt.tier,
                    price=profile.get("price"),
                    market_cap_cr=profile.get("market_cap_cr"),
                    market_cap_display=_mcap_display(profile.get("market_cap_cr")),
                    debt_equity=profile.get("debt_equity"),
                    interest_coverage=profile.get("interest_coverage"),
                    current_ratio=profile.get("current_ratio"),
                    promoter_holding_pct=profile.get("promoter_holding_pct"),
                    promoter_change_pct=profile.get("promoter_change_pct"),
                    pledged_pct=profile.get("pledged_pct"),
                    roe_pct=profile.get("roe_pct"),
                    avg_roe_3y_pct=profile.get("avg_roe_3y_pct"),
                    roce_pct=profile.get("roce_pct"),
                    roa_pct=profile.get("roa_pct"),
                    opm_pct=profile.get("opm_pct"),
                    sales_growth_3y_pct=profile.get("sales_growth_3y_pct"),
                    profit_growth_3y_pct=profile.get("profit_growth_3y_pct"),
                    yoy_sales_pct=profile.get("yoy_sales_pct"),
                    yoy_profit_pct=profile.get("yoy_profit_pct"),
                    pe=profile.get("pe"),
                    industry_pe=profile.get("industry_pe"),
                    peg=profile.get("peg"),
                    price_to_book=profile.get("price_to_book"),
                    ret_3m_pct=profile.get("ret_3m_pct"),
                    ret_6m_pct=profile.get("ret_6m_pct"),
                    ret_1y_pct=profile.get("ret_1y_pct"),
                    score=score,
                    verdict=_verdict(flt.tier, score, notes),
                    pass_notes=notes,
                    fail_soft=soft,
                    links=links or {},
                )
            )
            if flt.screener_delay_sec > 0:
                time.sleep(flt.screener_delay_sec)
        except Exception:
            continue

    return sort_fundamental_results(results, rank_by="score")


def sort_fundamental_results(
    results: list[FundamentalResult],
    *,
    rank_by: str = "score",
) -> list[FundamentalResult]:
    if rank_by == "roe":
        return sorted(results, key=lambda r: float(r.roe_pct or -999), reverse=True)
    if rank_by == "growth":
        return sorted(
            results,
            key=lambda r: min(
                float(r.sales_growth_3y_pct or -999),
                float(r.profit_growth_3y_pct or -999),
            ),
            reverse=True,
        )
    if rank_by == "peg":
        return sorted(
            results,
            key=lambda r: float(r.peg) if r.peg is not None else 9999.0,
        )
    if rank_by == "mcap":
        return sorted(results, key=lambda r: float(r.market_cap_cr or 0), reverse=True)
    if rank_by == "ret_3m":
        return sorted(results, key=lambda r: float(r.ret_3m_pct or -999), reverse=True)
    return sorted(results, key=lambda r: float(r.score or 0), reverse=True)


def result_to_row(r: FundamentalResult, rank: int) -> dict:
    return {
        "S.No.": rank,
        "Name": r.label,
        "Ticker": r.ticker,
        "Raw": r.raw_ticker,
        "Tier": r.tier,
        "Score": r.score,
        "Verdict": r.verdict,
        "Price": r.price,
        "Mcap": r.market_cap_display,
        "D/E": r.debt_equity,
        "ICR": r.interest_coverage,
        "Current ratio": r.current_ratio,
        "Promoter %": r.promoter_holding_pct,
        "Promoter Δ %": r.promoter_change_pct,
        "Pledge %": r.pledged_pct,
        "ROE %": r.roe_pct,
        "Avg ROE 3Y %": r.avg_roe_3y_pct,
        "ROCE %": r.roce_pct,
        "ROA %": r.roa_pct,
        "OPM %": r.opm_pct,
        "Sales 3Y %": r.sales_growth_3y_pct,
        "Profit 3Y %": r.profit_growth_3y_pct,
        "YoY sales %": r.yoy_sales_pct,
        "YoY profit %": r.yoy_profit_pct,
        "P/E": r.pe,
        "Industry PE": r.industry_pe,
        "PEG": r.peg,
        "P/B": r.price_to_book,
        "3M %": r.ret_3m_pct,
        "6M %": r.ret_6m_pct,
        "1Y %": r.ret_1y_pct,
        "Notes": " · ".join(r.pass_notes[:6]),
        "Soft skips": " · ".join(r.fail_soft[:4]) if r.fail_soft else "—",
    }
