# U.S. Market Report Dashboard

Standalone React + FastAPI dashboard. It is intentionally separate from the existing Streamlit screener.

## Structure

```
market_dashboard/
  backend/app/main.py       # cache, Yahoo/FRED/CoinGecko adapters, /api/market-report
  backend/requirements.txt
  backend/.env.example
  frontend/src/App.tsx      # dashboard composition
  frontend/src/api.ts       # typed API client
  frontend/src/index.css    # Tailwind dark theme
  frontend/package.json
```

## Run

```powershell
cd market_dashboard/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env  # Add FRED_API_KEY to enable macro observations
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev
```

The browser refreshes the report every 60 seconds. Yahoo Finance data is delayed/informal and must not be used for order execution. FRED indicators require a free `FRED_API_KEY`; missing keys leave those cards explicitly marked unavailable.
