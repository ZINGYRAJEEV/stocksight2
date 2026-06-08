# Central Brain — Cloud AI Trading Intermediary

TradingView alerts → **schema + risk validation** → optional **Claude** review → **BitGet / paper** execution, with accountant-ready JSONL audit logs.

## Architecture

```
TradingView (webhook)
        ↓
FastAPI /webhook/tradingview
        ↓
rules.json validation (VWAP, EMA8, RSI)
        ↓
Risk circuit breakers (PORTFOLIO_VALUE, MAX_TRADE_SIZE, MAX_TRADES_PER_DAY)
        ↓
Claude (optional, ANTHROPIC_API_KEY)
        ↓
Paper | BitGet | Breeze
        ↓
.central_brain_audit.jsonl
```

## Quick start (local)

1. Copy `.env.example` → `.env` and fill secrets.
2. Install deps: `pip install -r stocksight/requirements.txt`
3. Run API: `python scripts/run_central_brain.py`
4. Open Streamlit: `streamlit run Overview.py` → **Central Brain** page.
5. Test: `POST http://localhost:8080/webhook/test`

## TradingView alert JSON

```json
{
  "secret": "YOUR_TRADINGVIEW_WEBHOOK_SECRET",
  "action": "buy",
  "symbol": "XRPUSDT",
  "price": {{close}},
  "vwap": {{plot("VWAP")}},
  "ema8": {{plot("EMA8")}},
  "rsi": {{plot("RSI")}}
}
```

Webhook URL: `https://<your-host>/webhook/tradingview`

## rules.json

Located at `stocksight/central_brain/rules.json`. Edit thresholds without changing Python code.

| Check | Buy | Sell |
|-------|-----|------|
| VWAP proximity | ≤ 1.5% | ≤ 1.5% |
| VWAP position | Above | Below |
| 8 EMA | Above | Below |
| RSI | < 30 | > 70 |

Example block: price above VWAP and EMA but RSI 38.26 → **Blocked**.

## Three-key auth (BitGet)

- `BITGET_API_KEY`
- `BITGET_SECRET_KEY`
- `BITGET_PASSPHRASE`

**Disable withdrawal** on the API key.

## Live trading gates

All must be true:

- `CENTRAL_BRAIN_MODE=live`
- `CENTRAL_BRAIN_LIVE_CONFIRM=YES`
- Kill switch OFF
- BitGet keys configured (for crypto live)
- Mandatory **paper trading** validation period first

## Railway deployment

1. `railway link` (CLI) or connect GitHub repo in Railway dashboard.
2. Set **start command**: `python scripts/run_central_brain.py`
3. Mirror every `.env` variable in Railway **Variables**.
4. Health check: `GET /health`
5. Optional cron: ping `/health` every 5 minutes.

`Procfile` and `railway.toml` are included at repo root.

## Audit log

Append-only: `stocksight/.central_brain_audit.jsonl`

Each row: exchange, asset, status (Approved/Blocked), reasoning, checks, execution mode.

View in Streamlit **Central Brain → Audit log** tab.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET | `/checklist` | Pre-flight live checklist |
| POST | `/webhook/tradingview` | Production TradingView alerts |
| POST | `/webhook/test` | Sample buy signal |

## Security notes

- Set `TRADINGVIEW_WEBHOOK_SECRET` in production.
- Never commit `.env` or API keys.
- NSE live via Breeze is optional; SEBI algo-ID rules apply separately.
- Claude validation is optional; deterministic rules always run first.
