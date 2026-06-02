# 📈 StockSight — Real-Time Stock Screener & Signal Generator

A comprehensive stock analysis platform featuring **6 trading strategies**, real-time screening for **NSE (Nifty 50/500)** and **NYSE (S&P 500)** stocks, built with Python, Streamlit, and yfinance. No API key required.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://myapp-stocksight.streamlit.app/)

## ✨ Features

### 🎯 **6 Trading Strategies**
- **Breakout Momentum** 🚀 - High-volume breakouts above resistance
- **Oversold Bounce** 📉 - Panic-sold stocks showing reversal signs
- **Value + Technical** 💎 - Undervalued stocks with technical confirmation
- **Overbought Exit** 🔴 - RSI extreme + volume spike exhaustion
- **Extreme Oversold** ⚡ - Deep distress with green candle catalyst
- **Volume No Confirm** ⏸️ - Volume without RSI direction (noise filter)

### 📊 **Advanced Screening**
- **Real-time data** from NSE API and Yahoo Finance
- **Composite scoring** (PE 30% + Volume 40% + RSI 30%)
- **Multiple view modes**: Cards (trade plans) or Tables (compact)
- **Auto-refresh** capability (60-second intervals)
- **CSV export** for further analysis

### 🎨 **Professional UI**
- **Dark theme** inspired by Bloomberg Terminal
- **Responsive design** for desktop and mobile
- **Interactive charts** and visual indicators
- **Direct links** to Yahoo Finance, Moneycontrol, TradingView

### 🤖 **Intraday Autopilot** (Algo Strategy)
Scheduled **NSE + US** intraday playbook: gap scan → opening → ORB → VWAP → square-off. Supports **dry-run**, **paper**, and **live** (ICICI Breeze) modes, **Yahoo or Breeze** data for NSE scans, live progress in the UI, and continuous ticks (browser or CLI).

**Full user guide:** [docs/INTRADAY_AUTOPILOT.md](../docs/INTRADAY_AUTOPILOT.md)

## 🚀 Quick Start

### Run Locally

```bash
# Clone the repository
git clone https://github.com/ZINGYRAJEEV/stocksight2.git
cd stocksight2

# Install dependencies
pip install -r requirements.txt

# Run the application
streamlit run app.py
```

### Deploy to Streamlit Cloud

1. **Push to GitHub**: Ensure your code is in a GitHub repository
2. **Connect Streamlit Cloud**: Go to [share.streamlit.io](https://share.streamlit.io)
3. **Deploy**: Select your repo → Set main file to `app.py` → Deploy
4. **Access**: Your app will be live at `https://your-app-name.streamlit.app`

## 📋 How to Use

### 1. **Choose Your Universe**
Select from three stock universes in the sidebar:
- **Nifty 50 (NSE)**: 50 largest Indian stocks
- **Nifty 500 (NSE)**: 503 comprehensive Indian stocks
- **S&P 500 (NYSE)**: 247 major US stocks

### 2. **Configure Filters**
Adjust screening parameters:
- **PE Ratio**: Valuation filter (lower = more undervalued)
- **Volume Spike**: Activity multiplier (higher = more volatile)
- **RSI**: Momentum indicator (50+ = bullish, 70+ = overbought)

### 3. **Run Scan**
Click **"SCAN NOW"** to analyze stocks against your criteria. Results show:
- **Cards View**: Detailed trade plans with entry/exit levels
- **Table View**: Compact overview with key metrics

### 4. **Analyze Results**
Each result includes:
- **Confidence Score**: HIGH/MEDIUM/LOW based on composite scoring
- **Trade Levels**: Entry, Stop Loss, Target 1/2/3 with RRR
- **Research Links**: Direct access to Yahoo Finance, Moneycontrol, TradingView

## 📊 Strategy Details

| Strategy | Signal | PE Range | Volume | RSI | Timeframe | Best For |
|----------|--------|----------|--------|-----|-----------|----------|
| Breakout Momentum | BUY | 5–50 | ≥3× | 50–65↑ | 1–8 weeks | Strong trends |
| Oversold Bounce | BUY | 5–50 | ≥2× | 30–40↑ | 3–21 days | Panic selling |
| Value + Technical | BUY | 5–15 | 1.5–2× | 40–55 | 1–6 months | Long-term holds |
| Overbought Exit | SELL | Any | ≥2× | >75 | Days | Profit taking |
| Extreme Oversold | CAUTIOUS BUY | Any | ≥2× | <25 | Speculative | High-risk entries |
| Volume No Confirm | WAIT | Any | ≥2× | Ambiguous | Intraday | Noise filtering |

## 🛠️ Technical Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Frontend** | Streamlit | Web interface & interactivity |
| **Backend** | Python 3.10+ | Core logic & data processing |
| **Data Source** | yfinance | Real-time stock data (Yahoo Finance) |
| **NSE Data** | Official NSE API | Live Indian market constituents |
| **Analysis** | pandas, numpy | Data manipulation & calculations |
| **Indicators** | TA-Lib compatible | RSI, volume analysis |

## 📁 Project Structure

```
stocksight/
├── app.py                      # Main Streamlit application
├── screener.py                 # Core screening logic & stock universes
├── signals.py                  # Trading strategy implementations
├── ui_components.py            # Shared UI components & styling
├── requirements.txt            # Python dependencies
├── pages/                      # Individual strategy pages
│   ├── StockSight.py          # Main screener page
│   ├── Breakout Momentum.py   # Momentum strategy
│   ├── Buy Hold Avoid.py      # Decision guidance
│   ├── Oversold Bounce.py     # Reversal strategy
│   ├── Overbought Exit.py     # Exit signals
│   ├── Extreme Oversold.py    # High-risk entries
│   └── Volume No Confirm.py   # Noise filter
├── .streamlit/
│   └── config.toml            # Streamlit configuration
└── README.md                  # This file
```

## 🔧 Configuration

### Environment Setup
```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Streamlit Configuration
Edit `.streamlit/config.toml`:
```toml
[theme]
base = "dark"
primaryColor = "#25d366"
backgroundColor = "#0f1724"
secondaryBackgroundColor = "#122f25"
textColor = "#e8f7ef"
```

## 📈 Understanding the Metrics

### Composite Score Calculation
```
Score = (PE Score × 30%) + (Volume Score × 40%) + (RSI Score × 30%)
```

### Score Ranges
- **80–100**: Strong Buy (ideal setup)
- **60–79**: Buy / Watch (constructive)
- **40–59**: Neutral / Wait (unclear)
- **0–39**: Avoid (poor setup)

### Risk-Reward Ratio (RRR)
- **Entry** → **Stop Loss** = Risk amount
- **Entry** → **Target** = Reward amount
- **RRR** = Reward ÷ Risk (aim for 1.5× or higher)

## 🚨 Important Notes

### Data Sources
- **NSE stocks**: Official NSE API for live constituents
- **US stocks**: Yahoo Finance via yfinance library
- **Real-time**: Data refreshes with each scan (not streaming)

### Limitations
- **Market hours**: Best results during active trading sessions
- **Data accuracy**: Dependent on Yahoo Finance data quality
- **No streaming**: Manual refresh required for updates

### Performance
- **Scan time**: 30–120 seconds depending on universe size
- **Memory usage**: ~100–500MB during scans
- **Network**: Requires stable internet for data fetching

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-strategy`)
3. Commit changes (`git commit -am 'Add new strategy'`)
4. Push to branch (`git push origin feature/new-strategy`)
5. Create a Pull Request

## 📄 License

This project is for educational purposes only. Not financial advice. Use at your own risk.

## 🙏 Acknowledgments

- **NSE India** for providing official market data APIs
- **Yahoo Finance** for comprehensive stock data
- **Streamlit** for the amazing web app framework
- **yfinance** library for simplified financial data access

---

**Built with ❤️ for traders and investors**

*Last updated: May 2026*
