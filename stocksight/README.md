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
