"""
screener.py — Core screening logic for NSE (Nifty 50/500) and NYSE (S&P 500) stocks.
Uses yfinance for free market data. No API key required.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────
# Stock Universes
# ─────────────────────────────────────────────

NIFTY_50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
    "INFOSYS.NS", "SBIN.NS", "HINDUNILVR.NS", "INFY.NS", "ITC.NS",
    "KOTAKBANK.NS", "LT.NS", "HCLTECH.NS", "AXISBANK.NS", "BAJFINANCE.NS",
    "WIPRO.NS", "ASIANPAINT.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS",
    "NTPC.NS", "POWERGRID.NS", "ULTRACEMCO.NS", "NESTLEIND.NS", "BAJAJFINSV.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "TATACONSUM.NS",
    "HINDALCO.NS", "DIVISLAB.NS", "CIPLA.NS", "DRREDDY.NS", "APOLLOHOSP.NS",
    "EICHERMOT.NS", "HEROMOTOCO.NS", "M&M.NS", "BAJAJ-AUTO.NS", "TATAMOTORS.NS",
    "COALINDIA.NS", "ONGC.NS", "INDUSINDBK.NS", "BPCL.NS", "BRITANNIA.NS",
    "GRASIM.NS", "TECHM.NS", "SBILIFE.NS", "HDFCLIFE.NS", "LTIM.NS",
]

NIFTY_500_EXTRA = [
    "PIDILITIND.NS", "SIEMENS.NS", "ABB.NS", "HAL.NS", "BEL.NS",
    "IRFC.NS", "PFC.NS", "RECLTD.NS", "TRENT.NS", "NAUKRI.NS",
    "ZOMATO.NS", "PAYTM.NS", "DMART.NS", "MARICO.NS", "GODREJCP.NS",
    "COLPAL.NS", "DABUR.NS", "BERGEPAINT.NS", "MUTHOOTFIN.NS", "CHOLAFIN.NS",
    "BANKBARODA.NS", "CANBK.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS", "AUBANK.NS",
    "HAVELLS.NS", "POLYCAB.NS", "DIXON.NS", "VOLTAS.NS", "IRCTC.NS",
    "TATAPOWER.NS", "TORNTPOWER.NS", "GODREJPROP.NS", "DLF.NS", "PRESTIGE.NS",
]

SP500_SAMPLE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "JNJ", "COST",
    "HD", "PG", "ABBV", "CVX", "MRK", "KO", "WMT", "BAC", "NFLX",
    "CRM", "AMD", "ORCL", "ACN", "TMO", "CSCO", "LIN", "ABT", "TXN",
    "PM", "PEP", "DHR", "INTC", "VZ", "ADBE", "DIS", "CMCSA", "MCD",
    "IBM", "GE", "CAT", "RTX", "HON", "UPS", "GS", "MS", "SPGI",
    "BLK", "AXP", "LOW", "AMGN", "ISRG", "AMAT", "BKNG", "TJX",
]

UNIVERSES = {
    "Nifty 50 (NSE)": NIFTY_50,
    "Nifty 500 (NSE)": NIFTY_50 + NIFTY_500_EXTRA,
    "S&P 500 Sample (NYSE)": SP500_SAMPLE,
}

PE_DATA_CAP = {
    "Nifty 50 (NSE)":        300,
    "Nifty 500 (NSE)":       300,
    "S&P 500 Sample (NYSE)": 500,
}


# ─────────────────────────────────────────────
# Stock Link Builder
# ─────────────────────────────────────────────

def get_stock_links(raw_ticker: str) -> dict:
    """
    Returns a dict of deep-link URLs for a given raw yfinance ticker.

    NSE tickers (end with .NS):
      Yahoo Finance  → finance.yahoo.com/quote/RELIANCE.NS
      Moneycontrol   → moneycontrol.com search for the symbol
      TradingView    → tradingview.com/symbols/NSE-RELIANCE

    NYSE / NASDAQ tickers (no suffix):
      Yahoo Finance  → finance.yahoo.com/quote/AAPL
      MarketWatch    → marketwatch.com/investing/stock/aapl
      TradingView    → tradingview.com/symbols/AAPL
    """
    is_nse = raw_ticker.endswith(".NS") or raw_ticker.endswith(".BO")
    clean  = raw_ticker.replace(".NS", "").replace(".BO", "")

    if is_nse:
        return {
            "Yahoo Finance":  f"https://finance.yahoo.com/quote/{raw_ticker}",
            "Moneycontrol":   f"https://www.moneycontrol.com/india/stockpricequote/search?q={clean}",
            "TradingView":    f"https://www.tradingview.com/symbols/NSE-{clean}/",
        }
    else:
        return {
            "Yahoo Finance":  f"https://finance.yahoo.com/quote/{clean}",
            "MarketWatch":    f"https://www.marketwatch.com/investing/stock/{clean.lower()}",
            "TradingView":    f"https://www.tradingview.com/symbols/{clean}/",
        }


# ─────────────────────────────────────────────
# PE Fetching — robust multi-fallback
# ─────────────────────────────────────────────

def get_pe(ticker_obj):
    """
    Try multiple yfinance attributes to get trailing PE.
    Returns None if genuinely unavailable.
    """
    # Attempt 1: fast_info
    try:
        pe = getattr(ticker_obj.fast_info, "trailing_pe", None)
        if pe and float(pe) > 0:
            return float(pe)
    except Exception:
        pass

    # Attempt 2: full info dict
    try:
        info = ticker_obj.info
        for key in ("trailingPE", "forwardPE"):
            val = info.get(key)
            if val and float(val) > 0:
                return float(val)
    except Exception:
        pass

    # Attempt 3: derive from EPS + price
    try:
        info  = ticker_obj.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        eps   = info.get("trailingEps")
        if price and eps and float(eps) > 0:
            return round(float(price) / float(eps), 2)
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────
# Technical Indicators
# ─────────────────────────────────────────────

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return np.nan
    delta    = closes.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def compute_volume_ratio(volumes, window=20):
    if len(volumes) < window + 1:
        return np.nan
    avg = volumes.iloc[-window - 1:-1].mean()
    if avg == 0:
        return np.nan
    return round(float(volumes.iloc[-1] / avg), 2)


def compute_score(pe, vol_ratio, rsi):
    pe_score  = max(0.0, min(40.0, (50 - pe)  / 45 * 40)) if pe  and pe  > 0  else 0.0
    vol_score = max(0.0, min(30.0, (vol_ratio - 1) / 4 * 30)) if vol_ratio     else 0.0
    rsi_score = max(0.0, min(30.0, (rsi - 50) / 30 * 30)) if rsi and rsi > 50 else 0.0
    return round(pe_score + vol_score + rsi_score, 1)


# ─────────────────────────────────────────────
# Main Screening Function
# ─────────────────────────────────────────────

def screen_stocks(
    universe_name="Nifty 50 (NSE)",
    pe_threshold=30.0,
    vol_multiplier=1.5,
    rsi_min=50.0,
    progress_callback=None,
):
    tickers = UNIVERSES.get(universe_name, NIFTY_50)
    pe_cap  = PE_DATA_CAP.get(universe_name, 400)
    results = []
    total   = len(tickers)
    end     = datetime.today()
    start   = end - timedelta(days=60)

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i + 1, total, ticker)

        try:
            stock = yf.Ticker(ticker)

            hist = stock.history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
            )
            if hist.empty or len(hist) < 22:
                continue

            closes  = hist["Close"]
            volumes = hist["Volume"]
            current_price = round(float(closes.iloc[-1]), 2)

            pe = get_pe(stock)
            if pe is None or pe <= 0 or pe > pe_cap:
                continue
            pe = round(pe, 2)

            vol_ratio = compute_volume_ratio(volumes)
            if vol_ratio is None or np.isnan(vol_ratio):
                continue

            rsi = compute_rsi(closes)
            if rsi is None or np.isnan(rsi):
                continue

            if pe        > pe_threshold:   continue
            if vol_ratio < vol_multiplier: continue
            if rsi       < rsi_min:        continue

            score    = compute_score(pe, vol_ratio, rsi)
            is_nse   = ticker.endswith(".NS") or ticker.endswith(".BO")
            currency = "₹" if is_nse else "$"
            links    = get_stock_links(ticker)
            lk       = list(links.keys())   # e.g. ["Yahoo Finance","Moneycontrol","TradingView"]

            results.append({
                "Ticker":        ticker.replace(".NS", "").replace(".BO", ""),
                "Currency":      currency,
                "Price":         current_price,
                "PE Ratio":      pe,
                "Volume Ratio":  vol_ratio,
                "RSI":           rsi,
                "Score":         score,
                lk[0]:           links[lk[0]],
                lk[1]:           links[lk[1]],
                lk[2]:           links[lk[2]],
            })

        except Exception:
            continue

    if not results:
        return pd.DataFrame(
            columns=["Ticker", "Currency", "Price", "PE Ratio", "Volume Ratio", "RSI", "Score", "Yahoo Finance", "Moneycontrol", "TradingView"]
        )

    df            = pd.DataFrame(results)
    df            = df.sort_values("Score", ascending=False).reset_index(drop=True)
    df.index     += 1
    df.index.name = "Rank"
    return df


# CLI diagnostic
if __name__ == "__main__":
    print("Diagnostic — first 5 Nifty 50 tickers:\n")
    for t in NIFTY_50[:5]:
        stk = yf.Ticker(t)
        pe  = get_pe(stk)
        try:
            hist      = stk.history(period="25d", auto_adjust=True)
            vol_ratio = compute_volume_ratio(hist["Volume"]) if not hist.empty else None
            rsi       = compute_rsi(hist["Close"])           if not hist.empty else None
            price     = round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else None
        except Exception:
            vol_ratio = rsi = price = None
        print(f"  {t:<20}  price={price}  pe={pe}  vol_ratio={vol_ratio}  rsi={rsi}")

    print("\nFull screen (PE<=30, Vol>=1.5x, RSI>=50)…")
    df = screen_stocks(
        "Nifty 50 (NSE)",
        pe_threshold=30.0,
        vol_multiplier=1.5,
        rsi_min=50.0,
        progress_callback=lambda i, t, s: print(f"  [{i:02d}/{t}] {s}"),
    )
    print(f"\n✅ {len(df)} stocks passed\n")
    if not df.empty:
        print(df.to_string())
