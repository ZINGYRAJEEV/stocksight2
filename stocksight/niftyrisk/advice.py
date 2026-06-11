"""Actionable portfolio improvement hints from a NiftyRisk report."""

from __future__ import annotations

from typing import Any

from niftyrisk.models import RiskReport

_PRIORITY = {"high": 0, "medium": 1, "low": 2}


def _add(
    hints: list[dict[str, str]],
    *,
    priority: str,
    title: str,
    action: str,
    why: str,
) -> None:
    hints.append({
        "priority": priority,
        "title": title,
        "action": action,
        "why": why,
    })


def build_improvement_hints(report: RiskReport) -> list[dict[str, str]]:
    """Return sorted hints (high → low priority) based on report metrics."""
    hints: list[dict[str, str]] = []
    grade = (report.risk_grade or "").upper()
    flags = set(report.flags or [])
    holdings = list(report.holding_risk or [])
    sectors = dict(report.sector_weights or {})

    # --- Concentration & single-name risk ---
    if report.concentration_top3_pct > 55:
        _add(
            hints,
            priority="high",
            title="Top-3 names dominate the book",
            action="Trim the largest 1–2 positions toward ~15% each and redeploy into 3–5 uncorrelated names.",
            why=f"Top-3 concentration is **{report.concentration_top3_pct:.1f}%** — a single bad week can move the whole portfolio.",
        )
    elif report.concentration_top3_pct > 40:
        _add(
            hints,
            priority="medium",
            title="Moderate concentration",
            action="Avoid adding more to existing heavyweights; size new buys smaller than your top holding.",
            why=f"Top-3 weight is **{report.concentration_top3_pct:.1f}%** — still above a typical 35% comfort zone.",
        )

    if holdings:
        top = max(holdings, key=lambda h: float(h.get("weight_pct") or 0))
        top_w = float(top.get("weight_pct") or 0)
        top_t = str(top.get("ticker") or "")
        if top_w >= 25:
            _add(
                hints,
                priority="high",
                title=f"{top_t} is oversized",
                action=f"Consider partial profit-booking or a hard cap (e.g. max 15–20% per stock) on **{top_t}**.",
                why=f"Single-name weight is **{top_w:.1f}%** of portfolio value.",
            )
        elif top_w >= 18:
            _add(
                hints,
                priority="medium",
                title=f"Watch weight in {top_t}",
                action=f"Pause fresh buys in **{top_t}** until other holdings catch up in size.",
                why=f"Largest holding is **{top_w:.1f}%** of the book.",
            )

    # --- Market / beta / volatility ---
    if "HIGH_BETA" in flags or (report.beta_nifty is not None and report.beta_nifty > 1.25):
        beta_txt = f"{report.beta_nifty:.2f}" if report.beta_nifty is not None else ">1.25"
        _add(
            hints,
            priority="high",
            title="Portfolio moves harder than Nifty",
            action="Add lower-beta names (large-cap FMCG, pharma, utilities) or keep 10–15% cash for drawdowns.",
            why=f"Beta vs Nifty is **{beta_txt}** — in a −10% index week you may see a larger drop.",
        )
    elif report.beta_nifty is not None and report.beta_nifty < 0.75:
        _add(
            hints,
            priority="low",
            title="Defensive tilt",
            action="If you want more upside in rallies, selectively add quality mid-caps or index ETFs.",
            why=f"Beta **{report.beta_nifty:.2f}** is below Nifty — you may lag strong bull phases.",
        )

    if "HIGH_VOLATILITY" in flags or (report.annual_vol_pct is not None and report.annual_vol_pct > 28):
        vol = report.annual_vol_pct or 0
        _add(
            hints,
            priority="high",
            title="Swingy portfolio",
            action="Reduce speculative / small-cap weights; use staggered exits instead of all-or-nothing sells.",
            why=f"Annualised vol is **{vol:.1f}%** — daily P/L swings are likely large.",
        )

    if "ELEVATED_VAR" in flags or report.var_1d_pct > 2.5:
        _add(
            hints,
            priority="high",
            title="Elevated 1-day loss risk",
            action=f"Keep a liquidity buffer ≥ **₹{report.var_1d_inr:,.0f}** (your 1-day VaR) before deploying fresh capital.",
            why=f"95% 1-day VaR is **{report.var_1d_pct:.2f}%** (~₹{report.var_1d_inr:,.0f}).",
        )

    if report.max_drawdown_pct is not None and report.max_drawdown_pct > 25:
        _add(
            hints,
            priority="medium",
            title="Deep historical drawdown",
            action="Define max portfolio drawdown rules (e.g. −15%) and trim weakest laggards when breached.",
            why=f"Max drawdown over the lookback window was **{report.max_drawdown_pct:.1f}%**.",
        )

    # --- Returns vs benchmark ---
    if report.excess_return_pct is not None and report.excess_return_pct < -5:
        _add(
            hints,
            priority="medium",
            title="Trailing Nifty",
            action="Review holdings with poor risk-adjusted returns; replace chronic laggards with index leaders or ETFs.",
            why=f"Portfolio returned **{report.portfolio_return_pct}%** vs Nifty **{report.benchmark_return_pct}%**.",
        )
    elif report.excess_return_pct is not None and report.excess_return_pct > 8:
        _add(
            hints,
            priority="low",
            title="Strong vs Nifty",
            action="Book partial profits on big winners and rebalance so gains don't become new concentration risk.",
            why=f"Excess return vs Nifty is **+{report.excess_return_pct:.1f}%** — winners may now be overweight.",
        )

    if report.sharpe_ratio is not None and report.sharpe_ratio < 0.3:
        _add(
            hints,
            priority="medium",
            title="Weak risk-adjusted returns",
            action="Prefer fewer, higher-conviction names with defined stops instead of many small speculative bets.",
            why=f"Sharpe ratio is **{report.sharpe_ratio:.2f}** — return per unit of risk is low.",
        )

    # --- Sector diversification ---
    if sectors:
        top_sec = max(sectors.items(), key=lambda kv: kv[1])
        if top_sec[1] > 45:
            _add(
                hints,
                priority="high",
                title=f"Sector skew: {top_sec[0]}",
                action=f"Add exposure outside **{top_sec[0]}** (e.g. financials, healthcare, consumer) to balance cycles.",
                why=f"One sector is **{top_sec[1]:.1f}%** of portfolio value.",
            )
        elif top_sec[1] > 35:
            _add(
                hints,
                priority="medium",
                title=f"Heavy {top_sec[0]} exposure",
                action="Next 2–3 buys should be in under-represented sectors rather than the same theme.",
                why=f"**{top_sec[0]}** at **{top_sec[1]:.1f}%** — sector risk is building.",
            )
        if len(sectors) < 4 and report.holdings_count >= 8:
            _add(
                hints,
                priority="medium",
                title="Few sectors for many stocks",
                action="Spread across at least 4–5 sectors so earnings shocks don't hit the whole book.",
                why=f"Only **{len(sectors)}** sectors across **{report.holdings_count}** holdings.",
            )

    # --- Monte Carlo (Pro+) ---
    mc: dict[str, Any] = getattr(report, "monte_carlo", None) or {}
    if mc:
        prob_loss = float(mc.get("prob_loss") or 0)
        if prob_loss >= 45:
            _add(
                hints,
                priority="high",
                title="High chance of a losing year",
                action="Lower equity allocation or add stabilisers (gold ETF, short-duration debt) for the next 12 months.",
                why=f"Monte Carlo shows **{prob_loss:.0f}%** probability of ending below today's value.",
            )
        elif prob_loss >= 30:
            _add(
                hints,
                priority="medium",
                title="Meaningful downside in simulations",
                action="Keep SIPs in staggered tranches; avoid lump-sum adds until volatility cools.",
                why=f"Simulated 1-year loss probability is **{prob_loss:.0f}%**.",
            )
        p5 = float(mc.get("p5_terminal") or 0)
        init = float(mc.get("initial_value") or report.total_value or 0)
        if init > 0 and p5 < init * 0.85:
            _add(
                hints,
                priority="medium",
                title="Fat left tail in projections",
                action="Stress-test your largest positions on ICICI Positions exit hints; tighten stops on high-beta names.",
                why=f"5th percentile 1-year outcome is **₹{p5:,.0f}** vs **₹{init:,.0f}** today.",
            )

    # --- Stress (Elite) ---
    stress = getattr(report, "stress_results", None) or []
    if stress:
        worst = max(stress, key=lambda s: float(s.get("portfolio_loss_inr") or 0))
        loss_inr = float(worst.get("portfolio_loss_inr") or 0)
        if loss_inr > 0:
            _add(
                hints,
                priority="high",
                title="Stress-test buffer",
                action="Maintain emergency cash or liquid funds equal to the worst-case stress loss before adding risk.",
                why=f"**{worst.get('label')}** scenario implies ~**₹{loss_inr:,.0f}** loss ({worst.get('portfolio_loss_pct')}% ).",
            )

    # --- Tax / cost basis (Pro+) ---
    tax = getattr(report, "tax_estimate", None) or {}
    if report.total_cost <= 0 and report.total_value > 0:
        _add(
            hints,
            priority="medium",
            title="Missing average purchase prices",
            action="Fill **average_price** in holdings (ICICI export or manual) for accurate tax and gain estimates.",
            why="Cost basis is zero — unrealised gain and tax hints cannot be precise.",
        )
    elif tax.get("unrealized_gain", 0) > 100_000:
        _add(
            hints,
            priority="low",
            title="Large unrealised gains",
            action="Plan LTCG exemption (₹1.25L/yr) and harvest losers to offset gains before year-end.",
            why=f"Unrealised gain ~**₹{tax['unrealized_gain']:,.0f}** — tax timing can improve net returns.",
        )

    # --- Holdings count ---
    if report.holdings_count < 5 and report.total_value > 50_000:
        _add(
            hints,
            priority="medium",
            title="Very few holdings",
            action="Build toward 8–15 quality names (or 1–2 index ETFs + satellites) to reduce single-stock risk.",
            why=f"Only **{report.holdings_count}** positions — idiosyncratic risk is high.",
        )
    elif report.holdings_count > 35:
        _add(
            hints,
            priority="low",
            title="Many small positions",
            action="Consolidate tail holdings (<1% weight) into top convictions or an index ETF.",
            why=f"**{report.holdings_count}** holdings — monitoring and rebalancing cost is high.",
        )

    # --- Grade-based summary ---
    if grade in ("D", "E", "F"):
        _add(
            hints,
            priority="high",
            title=f"Risk grade {grade} — de-risk first",
            action="Pause new high-beta buys; rebalance toward large-cap quality and cap any single stock at 15%.",
            why=f"Risk score **{report.risk_score}/100** — address concentration, beta, and vol before chasing returns.",
        )
    elif grade in ("A", "B"):
        _add(
            hints,
            priority="low",
            title=f"Risk grade {grade} — stay disciplined",
            action="Rebalance quarterly; don't let winners grow past 20% without trimming.",
            why="Portfolio risk metrics are healthy — main risk is complacency and drift.",
        )
    else:
        _add(
            hints,
            priority="low",
            title="Balanced risk profile",
            action="Fix the highest-priority flags above first, then revisit after the next earnings season.",
            why=f"Grade **{grade}** — selective tweaks beat a full portfolio overhaul.",
        )

    # --- ICICI workflow hook ---
    _add(
        hints,
        priority="low",
        title="Use StockSight workflow",
        action="On **ICICI Positions**, link today's scan for Target/Stop; use **Sell now?** hints before stress events.",
        why="NiftyRisk measures book risk; intraday exit plans help you act on it.",
    )

    hints.sort(key=lambda h: _PRIORITY.get(h["priority"], 9))
    # De-duplicate similar titles, keep highest-priority first
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for h in hints:
        if h["title"] in seen:
            continue
        seen.add(h["title"])
        unique.append(h)
    return unique[:8]
