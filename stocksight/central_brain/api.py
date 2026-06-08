"""FastAPI webhook receiver for TradingView → Central Brain."""

from __future__ import annotations

from typing import Any

from central_brain.config import load_config
from central_brain.processor import process_tradingview_signal

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError as exc:
    raise ImportError("Install fastapi and uvicorn: pip install fastapi uvicorn") from exc

app = FastAPI(
    title="StockSight Central Brain",
    description="AI-mediated trading intermediary webhook (TradingView → validation → exchange)",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    cfg = load_config()
    return {
        "status": "ok",
        "mode": cfg.effective_mode(),
        "enabled": str(cfg.enabled),
        "claude": "on" if cfg.anthropic_api_key and cfg.use_claude_validation else "off",
    }


@app.get("/checklist")
def live_checklist() -> dict[str, Any]:
    """Pre-flight checklist for live trading."""
    cfg = load_config()
    return {
        "signal_link": "Configure TradingView alert → POST this /webhook/tradingview URL",
        "ai_status": "configured" if cfg.anthropic_api_key else "rule_engine_only",
        "api_security": "Verify exchange key is Read/Write only; Withdrawal DISABLED",
        "cloud_persistence": "Mirror .env to Railway; schedule health cron",
        "execution_mode": cfg.effective_mode(),
        "live_confirm": cfg.live_confirm,
        "kill_switch": cfg.kill_switch,
        "bitget_keys": cfg.bitget.configured(),
        "webhook_secret_set": bool(cfg.tradingview_secret),
    }


@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raw = (await request.body()).decode("utf-8", errors="replace")
        body = {"message": raw}

    result = process_tradingview_signal(body)
    status_code = 200 if result.get("status") == "Approved" else 422
    return JSONResponse(content=result, status_code=status_code)


@app.post("/webhook/test")
async def test_signal(request: Request) -> JSONResponse:
    """Dry-run style test — same pipeline, respects paper mode."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body.setdefault("action", "buy")
    body.setdefault("symbol", "XRPUSDT")
    body.setdefault("price", 0.5)
    body.setdefault("vwap", 0.49)
    body.setdefault("ema8", 0.48)
    body.setdefault("rsi", 28)
    result = process_tradingview_signal(body)
    return JSONResponse(content=result)
