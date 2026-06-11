"""FastAPI — NiftyRisk portfolio risk endpoints."""

from __future__ import annotations

from typing import Any, Optional

from niftyrisk.config import config_with_tier, load_config
from niftyrisk.portfolio import load_portfolio_csv
from niftyrisk.risk_engine import analyze_portfolio

try:
    from fastapi import FastAPI, File, HTTPException, Query, UploadFile
    from fastapi.responses import JSONResponse
except ImportError as exc:
    raise ImportError("Install fastapi and uvicorn: pip install fastapi uvicorn") from exc

app = FastAPI(
    title="NiftyRisk API",
    description="Institutional-grade portfolio risk intelligence for Indian retail investors",
    version="0.2.0",
)


def _cfg(tier: Optional[str] = None):
    return config_with_tier(tier) if tier else load_config()


@app.get("/health")
def health() -> dict[str, str]:
    cfg = load_config()
    return {
        "status": "ok",
        "product": "NiftyRisk",
        "tier": cfg.tier.value,
        "benchmark": cfg.benchmark,
    }


@app.get("/tiers")
def tiers() -> dict[str, Any]:
    from niftyrisk.config import TIER_LIMITS, SubscriptionTier

    return {
        t.value: limits for t, limits in TIER_LIMITS.items()
    }


@app.get("/stress/scenarios")
def stress_scenarios() -> dict[str, Any]:
    from niftyrisk.stress import STRESS_SCENARIOS

    return STRESS_SCENARIOS


@app.post("/stress/apply")
async def stress_apply(body: dict[str, Any]) -> JSONResponse:
    """Body: { portfolio_value, scenario_id, beta? } — Elite tier."""
    from niftyrisk.stress import apply_stress_scenario

    tier = body.get("tier")
    cfg = _cfg(str(tier) if tier else None)
    if not cfg.limits().get("stress_scenarios"):
        raise HTTPException(403, "Stress scenarios require Elite tier (tier=elite)")

    try:
        value = float(body.get("portfolio_value", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "portfolio_value required") from exc
    if value <= 0:
        raise HTTPException(400, "portfolio_value must be positive")

    scenario_id = str(body.get("scenario_id") or "")
    beta = float(body.get("beta") or 1.0)
    try:
        res = apply_stress_scenario(value, scenario_id, beta=beta)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse(content={
        "scenario_id": res.scenario_id,
        "label": res.label,
        "portfolio_loss_pct": res.portfolio_loss_pct,
        "portfolio_loss_inr": res.portfolio_loss_inr,
        "recovery_hint": res.recovery_hint,
    })


@app.post("/tax/estimate")
async def tax_estimate(body: dict[str, Any]) -> JSONResponse:
    """Body: { stcg_gains?, ltcg_gains?, ltcg_exemption_used?, tier? } — Pro+ tier."""
    from niftyrisk.tax import estimate_capital_gains_tax, estimate_portfolio_unrealized_tax

    tier = body.get("tier")
    cfg = _cfg(str(tier) if tier else None)
    if not cfg.limits().get("tax_engine"):
        raise HTTPException(403, "Tax engine requires Pro or Elite tier (tier=pro)")

    if "total_value" in body and "total_cost" in body:
        est = estimate_portfolio_unrealized_tax(
            total_value=float(body["total_value"]),
            total_cost=float(body["total_cost"]),
            assume_ltcg=bool(body.get("assume_ltcg", True)),
        )
    else:
        est = estimate_capital_gains_tax(
            stcg_gains=float(body.get("stcg_gains") or 0),
            ltcg_gains=float(body.get("ltcg_gains") or 0),
            ltcg_exemption_used=float(body.get("ltcg_exemption_used") or 0),
        )
    return JSONResponse(content=est.__dict__)


@app.post("/analyze/csv")
async def analyze_csv(
    file: UploadFile = File(...),
    portfolio_name: str = "Uploaded Portfolio",
    tier: Optional[str] = Query(None, description="free | pro | elite"),
) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload a .csv file with ticker, quantity, avg_price columns")
    raw = await file.read()
    try:
        portfolio = load_portfolio_csv(raw, name=portfolio_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    report = analyze_portfolio(portfolio, config=_cfg(tier))
    return JSONResponse(content=report.to_dict())


@app.post("/analyze/json")
async def analyze_json(
    body: dict[str, Any],
    tier: Optional[str] = Query(None, description="free | pro | elite"),
) -> JSONResponse:
    """Body: { name?, holdings: [{ ticker, quantity, avg_price?, sector? }] }"""
    from niftyrisk.models import Holding, Portfolio
    from niftyrisk.portfolio import normalize_ticker_nse

    holdings_raw = body.get("holdings") or []
    if not holdings_raw:
        raise HTTPException(400, "holdings array required")

    holdings = []
    for row in holdings_raw:
        if not isinstance(row, dict):
            continue
        t = normalize_ticker_nse(str(row.get("ticker", "")))
        if not t:
            continue
        try:
            qty = float(row.get("quantity", 0))
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0:
            continue
        try:
            avg = float(row.get("avg_price", 0) or 0)
        except (TypeError, ValueError):
            avg = 0.0
        holdings.append(
            Holding(
                ticker=t,
                quantity=qty,
                avg_price=avg,
                sector=str(row.get("sector", "") or ""),
            )
        )
    if not holdings:
        raise HTTPException(400, "No valid holdings")
    portfolio = Portfolio(name=str(body.get("name") or "API Portfolio"), holdings=holdings)
    effective_tier = str(body.get("tier") or tier or "")
    report = analyze_portfolio(portfolio, config=_cfg(effective_tier or None))
    return JSONResponse(content=report.to_dict())
