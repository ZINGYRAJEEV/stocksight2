# NiftyRisk — Portfolio Risk Intelligence

Institutional-grade risk analytics for Indian retail investors: VaR, Monte Carlo, sector concentration, Nifty benchmark, and A–F risk grading.

## Architecture

```
React (Vite) — future frontend
        ↕
FastAPI (niftyrisk/api.py)
        ↕
Risk Engine (niftyrisk/risk_engine.py) — NumPy / Pandas
        ↕
Data (yfinance NSE/BSE + ^NSEI benchmark)
```

## Quick start

### Streamlit (Phase 1 MVP)

```bash
streamlit run Overview.py
# Sidebar → NiftyRisk
```

### API

```bash
python scripts/run_niftyrisk.py
# http://localhost:8090/health
```

### CSV format

```csv
ticker,quantity,avg_price
RELIANCE,10,2450
HDFCBANK,25,1650
```

### Analyze via API

```bash
curl -X POST http://localhost:8090/analyze/csv -F "file=@stocksight/niftyrisk/sample_portfolio.csv"
```

### JSON body

```json
{
  "name": "Test",
  "holdings": [
    {"ticker": "RELIANCE", "quantity": 10, "avg_price": 2450}
  ]
}
```

## Tiers

| Tier | Holdings | Monte Carlo | Stress | Tax |
|------|----------|-------------|--------|-----|
| Free | 10 | — | — | — |
| Pro | 50 | 10,000 runs | — | STCG/LTCG |
| Elite | 200 | 10,000 runs | 2008/COVID/IL&FS | STCG/LTCG |

Set tier: `NIFTYRISK_TIER=free|pro|elite`

## Package layout

```
stocksight/niftyrisk/
  __init__.py
  config.py          # tier limits
  models.py          # Portfolio, RiskReport
  portfolio.py       # CSV import
  data.py            # yfinance prices
  risk_engine.py     # VaR, MC, Sharpe, beta, grade
  tax.py             # Phase 2 STCG/LTCG
  stress.py          # Phase 3 scenarios
  api.py             # FastAPI
  blueprint.html     # product blueprint UI
  sample_portfolio.csv
```

## Roadmap

- **Phase 1 (current):** CSV upload, VaR, risk grade, sector chart, Nifty compare
- **Phase 2:** Zerodha PDF parser, Razorpay, SIP projector
- **Phase 3:** Stress tests, WhatsApp alerts, multi-portfolio
- **Phase 4:** React frontend, RIA B2B, API product

Educational only — not financial or tax advice.
