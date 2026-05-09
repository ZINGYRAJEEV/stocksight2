# 📈 StockSight — Smart Stock Screener

A real-time stock screener for **NSE (Nifty 50 / 500)** and **NYSE (S&P 500)** built with Python, Streamlit, and yfinance. No API key required.

## Features
- 🔍 Filter by **PE Ratio**, **Volume Spike**, and **RSI**
- 📊 Composite scoring (PE 40pts + Volume 30pts + RSI 30pts)
- ⏱ 60-second auto-refresh for near real-time monitoring
- 📥 Download results as CSV
- 🌙 Bloomberg Terminal-inspired dark UI

## Tech Stack
| Layer | Tool |
|-------|------|
| Language | Python 3.10+ |
| UI | Streamlit |
| Data | yfinance (Yahoo Finance) |
| Indicators | RSI-14, 20-day avg volume, trailing PE |

## Run Locally

```bash
git clone https://github.com/YOUR_USERNAME/stocksight.git
cd stocksight
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Push your code to GitHub (already done for this repo).
2. Open https://share.streamlit.io and sign in with your GitHub account.
3. Click **New app** and choose this repository and the `main` branch.
4. Set the **main file** to `app.py` and click **Deploy**.
5. Optionally, change the app name and enable private sharing if needed.

Your app will launch automatically once Streamlit builds the environment.

## Project Structure

```
stocksight/
├── app.py                  # Streamlit UI
├── screener.py             # Screening logic & indicators
├── requirements.txt
└── .streamlit/
    └── config.toml         # Theme & server config
```

## Filters Explained

| Filter | Default | Logic |
|--------|---------|-------|
| Max PE Ratio | ≤ 20 | Value bias — undervalued stocks |
| Min Volume Spike | ≥ 2× | Unusual buying/selling interest |
| Min RSI (14) | ≥ 50 | Bullish momentum confirmation |

## Disclaimer
For educational purposes only. Not financial advice.
