"""
screener.py — Core screening logic for NSE (Nifty 50/500) and NYSE (S&P 500) stocks.
Uses yfinance for free market data. No API key required.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo
import json
import time
import urllib.error
import urllib.request
import warnings
warnings.filterwarnings("ignore")


_NSE_FII_CACHE: tuple[float, Optional[str]] = (0.0, None)


NIFTY_BENCHMARK = "^NSEI"
SPY_BENCHMARK = "SPY"


# ─────────────────────────────────────────────
# Stock Universes
# ─────────────────────────────────────────────

NIFTY_50 = [
    "SBIN.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "TITAN.NS", "ICICIBANK.NS",
    "TATACONSUM.NS", "RELIANCE.NS", "AXISBANK.NS", "INFY.NS", "MARUTI.NS",
    "ETERNAL.NS", "KOTAKBANK.NS", "LT.NS", "INDIGO.NS", "M&M.NS",
    "ADANIPORTS.NS", "SHRIRAMFIN.NS", "BAJFINANCE.NS", "SUNPHARMA.NS", "TCS.NS",
    "ITC.NS", "JIOFIN.NS", "HINDUNILVR.NS", "NTPC.NS", "HINDALCO.NS",
    "APOLLOHOSP.NS", "TATASTEEL.NS", "BEL.NS", "ASIANPAINT.NS", "ADANIENT.NS",
    "MAXHEALTH.NS", "HCLTECH.NS", "COALINDIA.NS", "BAJAJ-AUTO.NS", "POWERGRID.NS",
    "ULTRACEMCO.NS", "HDFCLIFE.NS", "EICHERMOT.NS", "NESTLEIND.NS", "TECHM.NS",
    "ONGC.NS", "DRREDDY.NS", "CIPLA.NS", "TRENT.NS", "WIPRO.NS",
    "GRASIM.NS", "TMPV.NS", "JSWSTEEL.NS", "SBILIFE.NS", "BAJAJFINSV.NS",
]

NIFTY_500_EXTRA = [
    "IDEA.NS", "MCX.NS", "BSE.NS", "HFCL.NS", "ABB.NS",
    "AFFLE.NS", "ATHERENERG.NS", "SCI.NS", "KALYANKJIL.NS", "JBMA.NS",
    "HSCL.NS", "CANBK.NS", "ETERNAL.NS", "MAPMYINDIA.NS", "COFORGE.NS",
    "INDIGO.NS", "VEDL.NS", "HYUNDAI.NS", "GROWW.NS", "LUPIN.NS",
    "BHEL.NS", "BANKBARODA.NS", "ADANIPOWER.NS", "DIXON.NS", "SWIGGY.NS",
    "SAIL.NS", "ADANIENSOL.NS", "CRAFTSMAN.NS", "HAL.NS", "SHRIRAMFIN.NS",
    "ADANIGREEN.NS", "NETWEB.NS", "KAYNES.NS", "UPL.NS", "BIOCON.NS",
    "MEESHO.NS", "NIVABUPA.NS", "BANKINDIA.NS", "JIOFIN.NS", "YESBANK.NS",
    "OLAELEC.NS", "GRSE.NS", "POWERINDIA.NS", "CGPOWER.NS", "MAZDOCK.NS",
    "URBANCO.NS", "SONACOMS.NS", "LAURUSLABS.NS", "SUZLON.NS", "HDFCAMC.NS",
    "SIEMENS.NS", "LENSKART.NS", "INDUSTOWER.NS", "HINDCOPPER.NS", "THERMAX.NS",
    "WOCKPHARMA.NS", "BEL.NS", "FEDERALBNK.NS", "OLECTRA.NS", "MAXHEALTH.NS",
    "WAAREEENER.NS", "TEJASNET.NS", "CDSL.NS", "TMCV.NS", "GALLANTT.NS",
    "DATAPATTNS.NS", "AMBER.NS", "CHOLAFIN.NS", "DALBHARAT.NS", "KIMS.NS",
    "BHARATFORG.NS", "GODREJCP.NS", "EMMVEE.NS", "PPLPHARMA.NS", "JSWENERGY.NS",
    "TORNTPHARM.NS", "ASHOKLEY.NS", "VIJAYA.NS", "CUMMINSIND.NS", "PVRINOX.NS",
    "FORTIS.NS", "SYNGENE.NS", "NATIONALUM.NS", "HINDZINC.NS", "SHYAMMETL.NS",
    "POLYCAB.NS", "FSL.NS", "BANDHANBNK.NS", "MARICO.NS", "KEI.NS",
    "PFC.NS", "PNB.NS", "JAINREC.NS", "GSPL.NS", "COCHINSHIP.NS",
    "SOLARINDS.NS", "ANANTRAJ.NS", "PAYTM.NS", "FORCEMOT.NS", "LICHSGFIN.NS",
    "CREDITACC.NS", "HINDPETRO.NS", "NBCC.NS", "GMDCLTD.NS", "GLENMARK.NS",
    "TVSMOTOR.NS", "SYRMA.NS", "TRENT.NS", "CARTRADE.NS", "MAHABANK.NS",
    "TATAPOWER.NS", "NAUKRI.NS", "GMRAIRPORT.NS", "MUTHOOTFIN.NS", "GVT&D.NS",
    "AMBUJACEM.NS", "PERSISTENT.NS", "NEULANDLAB.NS", "NLCINDIA.NS", "ASTERDM.NS",
    "RBLBANK.NS", "INDIANB.NS", "INDHOTEL.NS", "RECLTD.NS", "IEX.NS",
    "SRF.NS", "ABREL.NS", "MANKIND.NS", "PWL.NS", "CUB.NS",
    "IOC.NS", "SAGILITY.NS", "LODHA.NS", "TIINDIA.NS", "ACUTAAS.NS",
    "POLICYBZR.NS", "MFSL.NS", "LALPATHLAB.NS", "JSWINFRA.NS", "WELCORP.NS",
    "GODREJPROP.NS", "GRANULES.NS", "NATCOPHARM.NS", "APLAPOLLO.NS", "DELHIVERY.NS",
    "UNIONBANK.NS", "TMPV.NS", "IFCI.NS", "ANGELONE.NS", "GODFRYPHLP.NS",
    "KPITTECH.NS", "NUVAMA.NS", "ACMESOLAR.NS", "MOTHERSON.NS", "M&MFIN.NS",
    "LICI.NS", "AUROPHARMA.NS", "VBL.NS", "BDL.NS", "ZEEL.NS",
    "MRPL.NS", "PIDILITIND.NS", "CAMS.NS", "SAMMAANCAP.NS", "JBCHEPHARM.NS",
    "COLPAL.NS", "ACC.NS", "PGEL.NS", "OIL.NS", "RVNL.NS",
    "IDFCFIRSTB.NS", "NHPC.NS", "DLF.NS", "MANAPPURAM.NS", "AUBANK.NS",
    "OBEROIRLTY.NS", "HUDCO.NS", "OFSS.NS", "ZENTEC.NS", "NMDC.NS",
    "ENDURANCE.NS", "BLUESTARCO.NS", "ABCAPITAL.NS", "TARIL.NS", "LLOYDSME.NS",
    "INOXWIND.NS", "ABBOTINDIA.NS", "GESHIP.NS", "360ONE.NS", "NAM-INDIA.NS",
    "VMM.NS", "JPPOWER.NS", "LTF.NS", "NH.NS", "HBLENGINE.NS",
    "CROMPTON.NS", "RRKABEL.NS", "TATATECH.NS", "PRESTIGE.NS", "NAVINFLUOR.NS",
    "ESCORTS.NS", "DABUR.NS", "RADICO.NS", "SBICARD.NS", "CHENNPETRO.NS",
    "SONATSOFTW.NS", "AWL.NS", "ZYDUSLIFE.NS", "FINCABLES.NS", "TITAGARH.NS",
    "LTM.NS", "IRFC.NS", "APARINDS.NS", "KARURVYSYA.NS", "LGEINDIA.NS",
    "COROMANDEL.NS", "JINDALSTEL.NS", "GRAPHITE.NS", "AEGISLOG.NS", "PREMIERENE.NS",
    "PNBHOUSING.NS", "IREDA.NS", "VOLTAS.NS", "ENRIN.NS", "IPCALAB.NS",
    "PARADEEP.NS", "RKFORGE.NS", "KFINTECH.NS", "GPIL.NS", "ENGINERSIN.NS",
    "RPOWER.NS", "ATGL.NS", "ICICIGI.NS", "HAVELLS.NS", "INTELLECT.NS",
    "MOTILALOFS.NS", "BALKRISIND.NS", "ASTRAL.NS", "GRAVITA.NS", "UNOMINDA.NS",
    "DMART.NS", "POONAWALLA.NS", "ANANDRATHI.NS", "BOSCHLTD.NS", "SAILIFE.NS",
    "IKS.NS", "ICICIAMC.NS", "TATAELXSI.NS", "ZFCVINDIA.NS", "ECLERX.NS",
    "ICICIPRULI.NS", "CONCOR.NS", "ANURAS.NS", "EXIDEIND.NS", "IIFL.NS",
    "AARTIIND.NS", "VTL.NS", "PATANJALI.NS", "CEATLTD.NS", "CEMPRO.NS",
    "CCL.NS", "KEC.NS", "KAJARIACER.NS", "GAIL.NS", "TATACHEM.NS",
    "BELRISE.NS", "MRF.NS", "DEEPAKNTR.NS", "NAVA.NS", "APTUS.NS",
    "REDINGTON.NS", "HEG.NS", "PIRAMALFIN.NS", "UNITDSPR.NS", "JSL.NS",
    "CYIENT.NS", "JUBLFOOD.NS", "ACE.NS", "NYKAA.NS", "ITCHOTELS.NS",
    "FIVESTAR.NS", "PETRONET.NS", "HEXT.NS", "NTPCGREEN.NS", "ARE&M.NS",
    "CESC.NS", "NCC.NS", "BEML.NS", "J&KBANK.NS", "IRCTC.NS",
    "EMCURE.NS", "MPHASIS.NS", "ONESOURCE.NS", "UBL.NS", "RAINBOW.NS",
    "TRITURBINE.NS", "BLUEDART.NS", "AEGISVOPAK.NS", "DEEPAKFERT.NS", "COHANCE.NS",
    "IRCON.NS", "TORNTPOWER.NS", "WELSPUNLIV.NS", "MGL.NS", "LTTS.NS",
    "ABSLAMC.NS", "TATACAP.NS", "JYOTICNC.NS", "KIRLOSENG.NS", "JINDALSAW.NS",
    "BAJAJHFL.NS", "DEVYANI.NS", "MEDANTA.NS", "APOLLOTYRE.NS", "JWL.NS",
    "BAJAJHLDNG.NS", "NEWGEN.NS", "RAMCOCEM.NS", "CPPLUS.NS", "TIMKEN.NS",
    "LEMONTREE.NS", "BRIGADE.NS", "PIIND.NS", "SUPREMEIND.NS", "RAILTEL.NS",
    "CASTROLIND.NS", "ELECON.NS", "LINDEINDIA.NS", "STARHEALTH.NS", "BALRAMCHIN.NS",
    "PHOENIXLTD.NS", "GLAND.NS", "ZENSARTECH.NS", "CHAMBLFERT.NS", "ZYDUSWELL.NS",
    "USHAMART.NS", "ANTHEM.NS", "IDBI.NS", "PAGEIND.NS", "AJANTPHARM.NS",
    "ALKEM.NS", "HONASA.NS", "CGCL.NS", "GABRIEL.NS", "CRISIL.NS",
    "TATAINVEST.NS", "SHREECEM.NS", "CHOLAHLDNG.NS", "PINELABS.NS", "JUBLINGREA.NS",
    "INDIAMART.NS", "LATENTVIEW.NS", "IGL.NS", "PCBL.NS", "CHOICEIN.NS",
    "SCHNEIDER.NS", "CLEAN.NS", "TENNIND.NS", "SBFC.NS", "SOBHA.NS",
    "IRB.NS", "HDBFS.NS", "GILLETTE.NS", "DCMSHRIRAM.NS", "SUNDARMFIN.NS",
    "JUBLPHARMA.NS", "TATACOMM.NS", "SWANCORP.NS", "HOMEFIRST.NS", "CONCORDBIO.NS",
    "TBOTEK.NS", "BLS.NS", "BSOFT.NS", "JKTYRE.NS", "JMFINANCIL.NS",
    "MSUMI.NS", "GODREJIND.NS", "SAPPHIRE.NS", "FLUOROCHEM.NS", "WHIRLPOOL.NS",
    "PTCIL.NS", "SARDAEN.NS", "SJVN.NS", "SCHAEFFLER.NS", "MMTC.NS",
    "BHARTIHEXA.NS", "ABFRL.NS", "NSLNISP.NS", "KPRMILL.NS", "AIIL.NS",
    "POLYMED.NS", "CARBORUNIV.NS", "ABDL.NS", "CENTRALBK.NS", "NUVOCO.NS",
    "ABLBL.NS", "EMAMILTD.NS", "INDGN.NS", "TECHNOE.NS", "SIGNATURE.NS",
    "AFCONS.NS", "AAVAS.NS", "ATUL.NS", "JKCEMENT.NS", "JSWDULUX.NS",
    "FIRSTCRY.NS", "UTIAMC.NS", "HONAUT.NS", "ELGIEQUIP.NS", "CANFINHOME.NS",
    "BERGEPAINT.NS", "BLUEJET.NS", "ITI.NS", "SAREGAMA.NS", "GICRE.NS",
    "FACT.NS", "TRIDENT.NS", "NIACL.NS", "EIDPARRY.NS", "PFIZER.NS",
    "UCOBANK.NS", "JSWCEMENT.NS", "RITES.NS", "LTFOODS.NS", "CAPLIPOINT.NS",
    "SUMICHEM.NS", "BBTC.NS", "CANHLIFE.NS", "TTML.NS", "3MINDIA.NS",
    "AADHARHFC.NS", "IOB.NS", "BATAINDIA.NS", "KPIL.NS", "ASAHIINDIA.NS",
    "GLAXO.NS", "MINDACORP.NS", "IGIL.NS", "SUNTV.NS", "BAYERCROP.NS",
    "INDIACEM.NS", "ERIS.NS", "GODIGIT.NS", "SPLPETRO.NS", "DOMS.NS",
    "CHALET.NS", "RHIM.NS", "THELEELA.NS", "TEGA.NS", "EIHOTEL.NS",
    "AIAENG.NS", "BIKAJI.NS", "TRAVELFOOD.NS",
]

SP500 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AVGO", "JPM", "LLY",
    "V", "UNH", "XOM", "MA", "JNJ",
    "COST", "HD", "PG", "ABBV", "CVX",
    "MRK", "KO", "WMT", "BAC", "NFLX",
    "CRM", "AMD", "ORCL", "ACN", "TMO",
    "CSCO", "LIN", "ABT", "TXN", "PM",
    "PEP", "DHR", "INTC", "VZ", "ADBE",
    "DIS", "CMCSA", "MCD", "IBM", "GE",
    "CAT", "RTX", "HON", "UPS", "GS",
    "MS", "SPGI", "BLK", "AXP", "LOW",
    "AMGN", "ISRG", "AMAT", "BKNG", "TJX",
    "ELV", "SCHW", "BRK.B", "LMT", "NOC",
    "BA", "GILD", "REGN", "BIIB", "SYK",
    "SLB", "EOG", "COP", "MPC", "PSX",
    "VLO", "MOS", "CF", "ALB", "NEM",
    "GG", "VALE", "FCX", "HLI", "SCCO",
    "AA", "X", "STLD", "CLF", "MT",
    "NUE", "CMC", "AEE", "AEP", "CEG",
    "ED", "EXC", "NEE", "NRG", "PCG",
    "PEG", "PPL", "SO", "SRE", "WEC",
    "XEL", "DUK", "DTE", "EIX", "EQT",
    "ES", "ETR", "EVRG", "FE", "FIS",
    "IT", "MCO", "ADSK", "ASML", "CDNS",
    "CHTR", "CTAS", "ENPH", "FTNT", "GDDY",
    "IDXX", "ILMN", "INTU", "KEYS", "LRCX",
    "MNST", "NFLX", "NOW", "NVDA", "OKTA",
    "PAYX", "ROST", "SMCI", "SNPS", "SPLK",
    "TEAM", "TSLA", "TTD", "TWTC", "VEEV",
    "VRSK", "VRSN", "WDAY", "WKME", "WLTW",
    "XBLX", "ZM", "ZSCALER", "AME", "AKAM",
    "ALSK", "ANSS", "AON", "APH", "ARW",
    "APTV", "ATGE", "ATSG", "ATVI", "AUPH",
    "AVB", "AVT", "AWI", "AXON", "AYI",
    "AZO", "B", "BALL", "BAND", "BAP",
    "BBY", "BC", "BDX", "BEN", "BEST",
    "BF.B", "BG", "BGS", "BIDU", "BIO",
    "BKFS", "BKR", "BLK", "BLOW", "BLS",
    "BLUA", "BMI", "BMY", "BODY", "BOX",
    "BP", "BPOP", "BRKR", "BRX", "BSM",
    "BSMX", "BUD", "BUDS", "BUI", "BUR",
    "BWA", "BXP", "BYD", "CABK", "CAKE",
    "CAL", "CALM", "CALX", "CAME", "CAMP",
    "CAN", "CANG", "CANO", "CAR", "CARE",
    "CARS", "CART", "CASA", "CASE", "CASS",
    "CAT", "CATH", "CATO", "CAVM", "CBOE",
    "CBRE", "CBRL", "CBS", "CBSH", "CCJ",
    "CCK", "CCL", "CCMP", "CCU", "CCUR",
    "CCV", "CDC", "CDK", "CDNA", "CDNS",
    "CDT", "CDW",
]

UNIVERSES = {
    "Nifty 50 (NSE)": NIFTY_50,
    "Nifty 500 (NSE)": NIFTY_50 + NIFTY_500_EXTRA,
    "S&P 500 (NYSE)": SP500,
}

PE_DATA_CAP = {
    "Nifty 50 (NSE)":    300,
    "Nifty 500 (NSE)":   300,
    "S&P 500 (NYSE)":    500,
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


def compute_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram) at last bar, or (nan,nan,nan)."""
    if closes is None or len(closes) < slow + signal + 2:
        return (np.nan, np.nan, np.nan)
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    sig_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig_line
    return (
        round(float(macd_line.iloc[-1]), 4),
        round(float(sig_line.iloc[-1]), 4),
        round(float(hist.iloc[-1]), 4),
    )


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    if len(close) < period + 2:
        return np.nan
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return round(float(atr), 4) if pd.notna(atr) else np.nan


def compute_bollinger_pct_b(closes: pd.Series, window: int = 20, num_std: float = 2.0):
    """
    Bollinger %B: 0 at lower band, 1 at upper band.
    Also returns (middle, upper, lower) at last bar.
    """
    if len(closes) < window + 1:
        return np.nan, np.nan, np.nan, np.nan
    mid = closes.rolling(window).mean()
    std = closes.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    m = float(mid.iloc[-1])
    u = float(upper.iloc[-1])
    ell = float(lower.iloc[-1])
    px = float(closes.iloc[-1])
    if u == ell:
        pct_b = 0.5
    else:
        pct_b = (px - ell) / (u - ell)
    return round(float(np.clip(pct_b, -0.5, 1.5)), 4), round(m, 4), round(u, 4), round(ell, 4)


def ma_cross_recent(ma_fast: pd.Series, ma_slow: pd.Series, lookback: int = 5) -> bool:
    """True if golden cross (fast crossed above slow) within last `lookback` bars."""
    if ma_fast is None or ma_slow is None or len(ma_fast) < lookback + 2:
        return False
    for i in range(1, lookback + 1):
        if (
            float(ma_fast.iloc[-i]) > float(ma_slow.iloc[-i])
            and float(ma_fast.iloc[-i - 1]) <= float(ma_slow.iloc[-i - 1])
        ):
            return True
    return False


def pct_vs_ma(price: float, ma_val: float) -> float:
    if not ma_val or ma_val == 0:
        return np.nan
    return round((price - ma_val) / ma_val * 100.0, 2)


def compute_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """
    Classic slow stochastic %K / %D (simple smoothing on raw stochastic).
    %K_raw = 100 * (C - LL_k) / (HH_k - LL_k); %K = SMA(%K_raw, d_period); %D = SMA(%K, d_period).
    """
    if high is None or low is None or close is None:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    ll = low.rolling(k_period).min()
    hh = high.rolling(k_period).max()
    denom = (hh - ll).replace(0, np.nan)
    raw_k = ((close - ll) / denom).clip(lower=0, upper=1) * 100.0
    pct_k = raw_k.rolling(d_period).mean()
    pct_d = pct_k.rolling(d_period).mean()
    return pct_k, pct_d


def stochastic_last_and_crosses(pct_k: pd.Series, pct_d: pd.Series) -> dict[str, Any]:
    """Latest %K/%D and bullish/bearish crossover on the last closed bar."""
    out = {
        "stoch_k": None,
        "stoch_d": None,
        "stoch_cross_up": False,
        "stoch_cross_down": False,
    }
    if pct_k is None or pct_d is None or len(pct_k) < 3 or len(pct_d) < 3:
        return out
    k_now = pct_k.iloc[-1]
    d_now = pct_d.iloc[-1]
    k_prev = pct_k.iloc[-2]
    d_prev = pct_d.iloc[-2]
    if pd.notna(k_now):
        out["stoch_k"] = round(float(k_now), 2)
    if pd.notna(d_now):
        out["stoch_d"] = round(float(d_now), 2)
    if all(pd.notna(v) for v in (k_now, d_now, k_prev, d_prev)):
        out["stoch_cross_up"] = bool(k_prev <= d_prev and k_now > d_now)
        out["stoch_cross_down"] = bool(k_prev >= d_prev and k_now < d_now)
    return out


def compute_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Session / cumulative VWAP series (typical price × volume, cumulative)."""
    if high is None or low is None or close is None or volume is None:
        return pd.Series(dtype=float)
    if len(close) < 2:
        return pd.Series(dtype=float)
    typ = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    vol = volume.astype(float).clip(lower=0)
    pv = typ * vol
    cum_v = vol.cumsum().replace(0, np.nan)
    return (pv.cumsum() / cum_v)


def relative_strength_vs_benchmark(
    stock_hist: pd.DataFrame,
    bench_hist: pd.DataFrame,
    bars: int = 20,
) -> Optional[float]:
    """
    Excess return (percentage points) of stock vs benchmark over last `bars` bars on aligned dates.
    """
    if stock_hist is None or bench_hist is None:
        return None
    if stock_hist.empty or bench_hist.empty:
        return None
    try:
        left = stock_hist[["Close"]].copy()
        right = bench_hist[["Close"]].copy()
        right.columns = ["Bench"]
        joined = left.join(right, how="inner").dropna()
        if len(joined) < bars + 1:
            return None
        tail = joined.iloc[-(bars + 1) :]
        s0, s1 = float(tail["Close"].iloc[0]), float(tail["Close"].iloc[-1])
        b0, b1 = float(tail["Bench"].iloc[0]), float(tail["Bench"].iloc[-1])
        if s0 <= 0 or b0 <= 0:
            return None
        stock_ret = (s1 / s0 - 1.0) * 100.0
        bench_ret = (b1 / b0 - 1.0) * 100.0
        return round(float(stock_ret - bench_ret), 2)
    except Exception:
        return None


def benchmark_ticker_for(raw_ticker: str) -> str:
    return NIFTY_BENCHMARK if str(raw_ticker).upper().endswith((".NS", ".BO")) else SPY_BENCHMARK


def fetch_nse_fii_dii_equity_snapshot(ttl_seconds: int = 3600) -> Optional[str]:
    """
    Best-effort aggregate NSE equity FII/DII net figures (crores) from nseindia.com JSON.
    This is **market-wide** provisional activity, not per-stock flow; requires cookie handshake.
    """
    global _NSE_FII_CACHE
    now = time.time()
    ts, cached = _NSE_FII_CACHE
    if cached and (now - ts) < ttl_seconds:
        return cached

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    home = urllib.request.Request(
        "https://www.nseindia.com/",
        headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
        method="GET",
    )
    api = urllib.request.Request(
        "https://www.nseindia.com/api/fiidiiTradeReact",
        headers={
            "User-Agent": ua,
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.nseindia.com/",
        },
        method="GET",
    )
    text: Optional[str] = None
    try:
        with urllib.request.urlopen(home, timeout=12) as resp:  # noqa: S310 — curated NSE URL
            resp.read()
        with urllib.request.urlopen(api, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        rows = data if isinstance(data, list) else data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            _NSE_FII_CACHE = (now, None)
            return None
        # Typical rows: category name + buy/sell/net values in INR crores
        fii_net = dii_net = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            cat = str(row.get("category") or row.get("categoryName") or "").upper()
            net = row.get("fnNetAmount") or row.get("netValue") or row.get("net")
            try:
                net_v = float(net)
            except (TypeError, ValueError):
                continue
            if "FII" in cat or "FPI" in cat:
                fii_net = net_v
            if "DII" in cat:
                dii_net = net_v
        bits = []
        if fii_net is not None:
            bits.append(f"FII/FPI net ₹{fii_net:,.0f} Cr")
        if dii_net is not None:
            bits.append(f"DII net ₹{dii_net:,.0f} Cr")
        text = " · ".join(bits) if bits else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        text = None
    _NSE_FII_CACHE = (now, text)
    return text


_OHLCV_ALIASES: dict[str, tuple[str, ...]] = {
    "Open": ("Open", "open"),
    "High": ("High", "high"),
    "Low": ("Low", "low"),
    "Close": ("Close", "close", "Adj Close", "adj close"),
    "Volume": ("Volume", "volume"),
}


def hist_series(hist: pd.DataFrame, col: str) -> pd.Series:
    """Return an OHLCV column from yfinance history (handles alias / MultiIndex shapes)."""
    empty = pd.Series(dtype=float)
    if hist is None or hist.empty:
        return empty
    names = _OHLCV_ALIASES.get(col, (col,))
    if isinstance(hist.columns, pd.MultiIndex):
        for name in names:
            if name in hist.columns.get_level_values(0):
                s = hist[name]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                return s.astype(float)
        return empty
    for name in names:
        if name in hist.columns:
            s = hist[name]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            return s.astype(float)
    return empty


def fetch_price_history(ticker: str, interval_key: str = "1d") -> pd.DataFrame:
    """
    interval_key: '1d' | '1h' | '15m'
    Enough history for MA50 / MACD on daily; intraday uses Yahoo limits.

    NSE/BSE (.NS / .BO): uses ICICI Breeze when [breeze] secrets/env are set,
    otherwise Yahoo Finance via yfinance.
    """
    empty = pd.DataFrame()
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        try:
            from breeze_data import fetch_breeze_price_history

            bdf = fetch_breeze_price_history(ticker, interval_key)
            if bdf is not None and not bdf.empty:
                return bdf
        except Exception:
            pass

    stk = yf.Ticker(ticker)
    try:
        if interval_key == "1d":
            end = datetime.today()
            start = end - timedelta(days=180)
            df = stk.history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=True,
            )
        elif interval_key == "1h":
            df = stk.history(period="730d", interval="1h", auto_adjust=True)
        elif interval_key == "15m":
            df = stk.history(period="60d", interval="15m", auto_adjust=True)
        else:
            df = stk.history(period="120d", interval="1d", auto_adjust=True)
        return df if df is not None and not df.empty else empty
    except Exception:
        return empty


def min_bars_for_screen(interval_key: str) -> int:
    return {"1d": 55, "1h": 120, "15m": 200}.get(interval_key, 55)


def get_sector_industry(ticker_obj: yf.Ticker) -> tuple[str, str]:
    try:
        info = ticker_obj.info or {}
        sec = (info.get("sector") or "").strip()
        ind = (info.get("industry") or "").strip()
        return sec, ind
    except Exception:
        return "", ""


def next_earnings_label(ticker_obj: yf.Ticker) -> str:
    try:
        cal = ticker_obj.calendar
        if cal is None:
            return ""
        if isinstance(cal, pd.DataFrame) and not cal.empty:
            row = cal.iloc[0]
            for key in ("Earnings Date", "earningsDate"):
                if key in cal.columns:
                    val = row[key]
                    if hasattr(val, "strftime"):
                        return val.strftime("%Y-%m-%d")
                    return str(val)[:10]
            return ""
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date") or cal.get("earningsDate")
            if ed is None:
                return ""
            if isinstance(ed, (list, tuple)) and ed:
                ed = ed[0]
            if hasattr(ed, "strftime"):
                return ed.strftime("%Y-%m-%d")
            return str(ed)[:10]
    except Exception:
        pass
    return ""


def fetch_quote_news(raw_ticker: str, limit: int = 3) -> list[str]:
    """Short headlines from yfinance (best-effort)."""
    try:
        t = yf.Ticker(raw_ticker)
        news = getattr(t, "news", None) or []
        out = []
        for item in news[:limit]:
            title = item.get("title") if isinstance(item, dict) else None
            if title:
                out.append(str(title).strip())
        return out
    except Exception:
        return []


_RECOMMENDATION_LABELS: dict[str, str] = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
    "underperform": "Underperform",
    "outperform": "Outperform",
    "none": "—",
}


def raw_ticker_from_display(display_ticker: str, universe_name: str = "") -> str:
    """Map table ticker to yfinance symbol (e.g. RELIANCE → RELIANCE.NS)."""
    s = str(display_ticker or "").strip()
    if not s:
        return ""
    up = s.upper()
    if up.endswith(".NS") or up.endswith(".BO"):
        return s
    if "NSE" in str(universe_name).upper():
        return f"{s}.NS"
    return s


def _format_recommendation_key(key: Optional[str]) -> str:
    if not key:
        return "—"
    k = str(key).strip().lower().replace(" ", "_")
    return _RECOMMENDATION_LABELS.get(k, key.replace("_", " ").title())


def _ratings_breakdown_from_frame(rec: pd.DataFrame) -> str:
    """Latest period row from yfinance `recommendations` (0m = current month)."""
    if rec is None or rec.empty:
        return ""
    row = rec.iloc[0]
    parts: list[str] = []
    for col, label in (
        ("strongBuy", "Strong Buy"),
        ("buy", "Buy"),
        ("hold", "Hold"),
        ("sell", "Sell"),
        ("strongSell", "Strong Sell"),
    ):
        try:
            n = int(row[col])
        except (KeyError, TypeError, ValueError):
            continue
        if n > 0:
            parts.append(f"{n} {label}")
    return ", ".join(parts)


def fetch_analyst_recommendation(raw_ticker: str, *, current_price: Optional[float] = None) -> dict[str, Any]:
    """
    Analyst consensus from Yahoo Finance (`Ticker.info` + `recommendations`).
    Best-effort; NSE coverage varies. Educational only.
    """
    empty: dict[str, Any] = {
        "consensus": None,
        "mean_score": None,
        "analyst_count": None,
        "target_mean": None,
        "target_high": None,
        "target_low": None,
        "upside_pct": None,
        "ratings_breakdown": "",
        "summary": "—",
    }
    if not raw_ticker:
        return empty

    try:
        stk = yf.Ticker(raw_ticker)
        info = stk.info or {}
    except Exception:
        return empty

    def _gf(keys: tuple[str, ...]) -> Optional[float]:
        for k in keys:
            v = info.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
                if np.isnan(fv):
                    continue
                return fv
            except (TypeError, ValueError):
                continue
        return None

    key_raw = info.get("recommendationKey") or info.get("recommendation_key")
    consensus = _format_recommendation_key(key_raw if key_raw else None)
    mean_score = _gf(("recommendationMean", "recommendation_mean"))
    analyst_count = info.get("numberOfAnalystOpinions") or info.get("number_of_analyst_opinions")
    try:
        analyst_count = int(analyst_count) if analyst_count is not None else None
    except (TypeError, ValueError):
        analyst_count = None

    target_mean = _gf(("targetMeanPrice", "target_mean_price"))
    target_high = _gf(("targetHighPrice", "target_high_price"))
    target_low = _gf(("targetLowPrice", "target_low_price"))

    px = current_price
    if px is None:
        px = _gf(("currentPrice", "regularMarketPrice", "previousClose"))

    upside_pct: Optional[float] = None
    if px and px > 0 and target_mean and target_mean > 0:
        upside_pct = round((target_mean / px - 1.0) * 100.0, 1)

    breakdown = ""
    try:
        rec = stk.recommendations
        if rec is not None and not rec.empty:
            breakdown = _ratings_breakdown_from_frame(rec)
    except Exception:
        pass

    summary_parts = [consensus]
    if mean_score is not None:
        summary_parts.append(f"mean {mean_score:.2f}/5")
    if analyst_count is not None:
        summary_parts.append(f"{analyst_count} analysts")
    if target_mean is not None:
        summary_parts.append(f"target {target_mean:.2f}")
    if upside_pct is not None:
        summary_parts.append(f"upside {upside_pct:+.1f}%")
    summary = " · ".join(p for p in summary_parts if p and p != "—") or "—"
    if breakdown:
        summary = f"{summary} ({breakdown})" if summary != "—" else breakdown

    return {
        "consensus": consensus if consensus != "—" else None,
        "mean_score": round(mean_score, 3) if mean_score is not None else None,
        "analyst_count": analyst_count,
        "target_mean": round(target_mean, 2) if target_mean is not None else None,
        "target_high": round(target_high, 2) if target_high is not None else None,
        "target_low": round(target_low, 2) if target_low is not None else None,
        "upside_pct": upside_pct,
        "ratings_breakdown": breakdown,
        "summary": summary,
    }


def enrich_dataframe_analyst_recommendations(
    df: pd.DataFrame,
    *,
    universe_name: str = "",
    ticker_col: str = "Ticker",
    raw_ticker_col: Optional[str] = None,
    delay_sec: float = 0.2,
) -> pd.DataFrame:
    """
    Add analyst recommendation columns via per-row Yahoo Finance calls.
    Use on export-sized result sets only (rate-limit aware).
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    price_col = "Price" if "Price" in out.columns else None

    consensus_l: list[Optional[str]] = []
    mean_l: list[Optional[float]] = []
    count_l: list[Optional[int]] = []
    tgt_l: list[Optional[float]] = []
    upside_l: list[Optional[float]] = []
    breakdown_l: list[str] = []
    summary_l: list[str] = []

    for idx, row in out.iterrows():
        if raw_ticker_col and raw_ticker_col in out.columns:
            raw = str(row[raw_ticker_col] or "").strip()
        else:
            raw = raw_ticker_from_display(str(row.get(ticker_col, "")), universe_name)
        px = None
        if price_col:
            try:
                px = float(row[price_col])
            except (TypeError, ValueError):
                px = None
        rec = fetch_analyst_recommendation(raw, current_price=px)
        consensus_l.append(rec.get("consensus"))
        mean_l.append(rec.get("mean_score"))
        count_l.append(rec.get("analyst_count"))
        tgt_l.append(rec.get("target_mean"))
        upside_l.append(rec.get("upside_pct"))
        breakdown_l.append(rec.get("ratings_breakdown") or "")
        summary_l.append(rec.get("summary") or "—")
        if delay_sec > 0:
            time.sleep(delay_sec)

    out["Analyst consensus"] = consensus_l
    out["Analyst mean (1-5)"] = mean_l
    out["Analyst count"] = count_l
    out["Analyst target mean"] = tgt_l
    out["Upside to target %"] = upside_l
    out["Analyst ratings mix"] = breakdown_l
    out["Analyst recommendation"] = summary_l
    return out


def _return_pct_over_bars(closes: pd.Series, bars: int) -> Optional[float]:
    if closes is None or len(closes) < bars + 1:
        return None
    try:
        s0 = float(closes.iloc[-(bars + 1)])
        s1 = float(closes.iloc[-1])
    except (TypeError, ValueError, IndexError):
        return None
    if s0 <= 0:
        return None
    return round((s1 / s0 - 1.0) * 100.0, 1)


def fetch_historical_summary(
    raw_ticker: str,
    *,
    current_price: Optional[float] = None,
    hist: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """
    ~1 year of daily OHLCV from Yahoo — returns summary stats for table/CSV columns.
    """
    empty: dict[str, Any] = {
        "hist_start": None,
        "hist_end": None,
        "high_52w": None,
        "low_52w": None,
        "pct_below_52w_high": None,
        "return_1m_pct": None,
        "return_3m_pct": None,
        "return_6m_pct": None,
        "return_1y_pct": None,
        "avg_volume_20d": None,
        "summary": "—",
        "detail": "—",
    }
    if not raw_ticker:
        return empty

    try:
        if hist is None or hist.empty:
            hist = yf.Ticker(raw_ticker).history(period="1y", interval="1d", auto_adjust=True)
    except Exception:
        return empty

    if hist is None or hist.empty or len(hist) < 22:
        return empty

    closes = hist_series(hist, "Close") if "Close" not in hist.columns else hist["Close"].astype(float)
    highs = hist_series(hist, "High")
    lows = hist_series(hist, "Low")
    vols = hist_series(hist, "Volume")

    if closes.empty:
        return empty

    px = current_price
    if px is None:
        try:
            px = float(closes.iloc[-1])
        except (TypeError, ValueError):
            px = None

    high_52w = float(highs.max()) if not highs.empty else None
    low_52w = float(lows.min()) if not lows.empty else None

    pct_below: Optional[float] = None
    if px and high_52w and high_52w > 0:
        pct_below = round((1.0 - px / high_52w) * 100.0, 1)

    r1m = _return_pct_over_bars(closes, 21)
    r3m = _return_pct_over_bars(closes, 63)
    r6m = _return_pct_over_bars(closes, 126)
    r1y = _return_pct_over_bars(closes, min(252, len(closes) - 1))

    avg_vol = None
    if not vols.empty and len(vols) >= 20:
        avg_vol = round(float(vols.iloc[-20:].mean()), 0)

    try:
        hist_start = str(closes.index[0])[:10]
        hist_end = str(closes.index[-1])[:10]
    except Exception:
        hist_start = hist_end = None

    parts = []
    if r1m is not None:
        parts.append(f"1M {r1m:+.1f}%")
    if r3m is not None:
        parts.append(f"3M {r3m:+.1f}%")
    if r6m is not None:
        parts.append(f"6M {r6m:+.1f}%")
    if r1y is not None:
        parts.append(f"1Y {r1y:+.1f}%")
    if pct_below is not None:
        parts.append(f"{pct_below:.0f}% below 52w high")
    summary = " · ".join(parts) if parts else "—"

    detail_bits = [
        f"Range {hist_start} → {hist_end}" if hist_start and hist_end else "",
    ]
    if high_52w is not None and low_52w is not None:
        detail_bits.append(f"52w H {high_52w:.2f} / L {low_52w:.2f}")
    if avg_vol is not None:
        detail_bits.append(f"avg vol 20d {avg_vol:,.0f}")
    detail = " · ".join(b for b in detail_bits if b) or summary

    return {
        "hist_start": hist_start,
        "hist_end": hist_end,
        "high_52w": round(high_52w, 2) if high_52w is not None else None,
        "low_52w": round(low_52w, 2) if low_52w is not None else None,
        "pct_below_52w_high": pct_below,
        "return_1m_pct": r1m,
        "return_3m_pct": r3m,
        "return_6m_pct": r6m,
        "return_1y_pct": r1y,
        "avg_volume_20d": avg_vol,
        "summary": summary,
        "detail": detail,
    }


def _analyst_from_info(stk: yf.Ticker, info: dict, *, current_price: Optional[float] = None) -> dict[str, Any]:
    """Analyst block using an already-open Ticker + info dict."""

    def _gf(keys: tuple[str, ...]) -> Optional[float]:
        for k in keys:
            v = info.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
                if np.isnan(fv):
                    continue
                return fv
            except (TypeError, ValueError):
                continue
        return None

    key_raw = info.get("recommendationKey") or info.get("recommendation_key")
    consensus = _format_recommendation_key(key_raw if key_raw else None)
    mean_score = _gf(("recommendationMean", "recommendation_mean"))
    analyst_count = info.get("numberOfAnalystOpinions") or info.get("number_of_analyst_opinions")
    try:
        analyst_count = int(analyst_count) if analyst_count is not None else None
    except (TypeError, ValueError):
        analyst_count = None

    target_mean = _gf(("targetMeanPrice", "target_mean_price"))
    target_high = _gf(("targetHighPrice", "target_high_price"))
    target_low = _gf(("targetLowPrice", "target_low_price"))

    px = current_price
    if px is None:
        px = _gf(("currentPrice", "regularMarketPrice", "previousClose"))

    upside_pct: Optional[float] = None
    if px and px > 0 and target_mean and target_mean > 0:
        upside_pct = round((target_mean / px - 1.0) * 100.0, 1)

    breakdown = ""
    try:
        rec = stk.recommendations
        if rec is not None and not rec.empty:
            breakdown = _ratings_breakdown_from_frame(rec)
    except Exception:
        pass

    summary_parts = [consensus]
    if mean_score is not None:
        summary_parts.append(f"mean {mean_score:.2f}/5")
    if analyst_count is not None:
        summary_parts.append(f"{analyst_count} analysts")
    if target_mean is not None:
        summary_parts.append(f"target {target_mean:.2f}")
    if upside_pct is not None:
        summary_parts.append(f"upside {upside_pct:+.1f}%")
    summary = " · ".join(p for p in summary_parts if p and p != "—") or "—"
    if breakdown:
        summary = f"{summary} ({breakdown})" if summary != "—" else breakdown

    return {
        "consensus": consensus if consensus != "—" else None,
        "mean_score": round(mean_score, 3) if mean_score is not None else None,
        "analyst_count": analyst_count,
        "target_mean": round(target_mean, 2) if target_mean is not None else None,
        "target_high": round(target_high, 2) if target_high is not None else None,
        "target_low": round(target_low, 2) if target_low is not None else None,
        "upside_pct": upside_pct,
        "ratings_breakdown": breakdown,
        "summary": summary,
    }


def enrich_dataframe_yahoo_context(
    df: pd.DataFrame,
    *,
    universe_name: str = "",
    ticker_col: str = "Ticker",
    raw_ticker_col: Optional[str] = None,
    include_analyst: bool = True,
    include_history: bool = True,
    delay_sec: float = 0.15,
) -> pd.DataFrame:
    """
    One Yahoo Ticker fetch per row — analyst consensus + ~1y historical summary columns.
    """
    if df is None or df.empty or (not include_analyst and not include_history):
        return df

    out = df.copy()
    price_col = "Price" if "Price" in out.columns else None

    analyst_cols: dict[str, list] = {
        "Analyst consensus": [],
        "Analyst mean (1-5)": [],
        "Analyst count": [],
        "Analyst target mean": [],
        "Upside to target %": [],
        "Analyst ratings mix": [],
        "Analyst recommendation": [],
    }
    hist_cols: dict[str, list] = {
        "Hist start": [],
        "Hist end": [],
        "52w high": [],
        "52w low": [],
        "% below 52w high": [],
        "Return 1M %": [],
        "Return 3M %": [],
        "Return 6M %": [],
        "Return 1Y %": [],
        "Avg volume 20d": [],
        "Historical snapshot": [],
        "Historical detail": [],
    }

    for _, row in out.iterrows():
        if raw_ticker_col and raw_ticker_col in out.columns:
            raw = str(row[raw_ticker_col] or "").strip()
        else:
            raw = raw_ticker_from_display(str(row.get(ticker_col, "")), universe_name)

        px = None
        if price_col:
            try:
                px = float(row[price_col])
            except (TypeError, ValueError):
                px = None

        hist_df: Optional[pd.DataFrame] = None
        try:
            stk = yf.Ticker(raw)
        except Exception:
            stk = None

        if include_history and stk is not None:
            try:
                hist_df = stk.history(period="1y", interval="1d", auto_adjust=True)
            except Exception:
                hist_df = None

        if include_analyst:
            try:
                if stk is not None:
                    info = stk.info or {}
                    rec = _analyst_from_info(stk, info, current_price=px)
                else:
                    rec = fetch_analyst_recommendation(raw, current_price=px)
            except Exception:
                rec = fetch_analyst_recommendation(raw, current_price=px)
            analyst_cols["Analyst consensus"].append(rec.get("consensus"))
            analyst_cols["Analyst mean (1-5)"].append(rec.get("mean_score"))
            analyst_cols["Analyst count"].append(rec.get("analyst_count"))
            analyst_cols["Analyst target mean"].append(rec.get("target_mean"))
            analyst_cols["Upside to target %"].append(rec.get("upside_pct"))
            analyst_cols["Analyst ratings mix"].append(rec.get("ratings_breakdown") or "")
            analyst_cols["Analyst recommendation"].append(rec.get("summary") or "—")
        elif include_history:
            # still need delay if only history
            pass

        if include_history:
            h = fetch_historical_summary(raw, current_price=px, hist=hist_df)
            hist_cols["Hist start"].append(h.get("hist_start"))
            hist_cols["Hist end"].append(h.get("hist_end"))
            hist_cols["52w high"].append(h.get("high_52w"))
            hist_cols["52w low"].append(h.get("low_52w"))
            hist_cols["% below 52w high"].append(h.get("pct_below_52w_high"))
            hist_cols["Return 1M %"].append(h.get("return_1m_pct"))
            hist_cols["Return 3M %"].append(h.get("return_3m_pct"))
            hist_cols["Return 6M %"].append(h.get("return_6m_pct"))
            hist_cols["Return 1Y %"].append(h.get("return_1y_pct"))
            hist_cols["Avg volume 20d"].append(h.get("avg_volume_20d"))
            hist_cols["Historical snapshot"].append(h.get("summary") or "—")
            hist_cols["Historical detail"].append(h.get("detail") or "—")

        if delay_sec > 0:
            time.sleep(delay_sec)

    if include_analyst:
        for k, vals in analyst_cols.items():
            out[k] = vals
    if include_history:
        for k, vals in hist_cols.items():
            out[k] = vals
    return out


def enrich_dataframe_analyst_recommendations(
    df: pd.DataFrame,
    *,
    universe_name: str = "",
    ticker_col: str = "Ticker",
    raw_ticker_col: Optional[str] = None,
    delay_sec: float = 0.2,
) -> pd.DataFrame:
    """Add analyst recommendation columns (delegates to combined Yahoo enrich)."""
    return enrich_dataframe_yahoo_context(
        df,
        universe_name=universe_name,
        ticker_col=ticker_col,
        raw_ticker_col=raw_ticker_col,
        include_analyst=True,
        include_history=False,
        delay_sec=delay_sec,
    )


def rsi_series_wilder(closes: pd.Series, period: int = 14) -> pd.Series:
    """Full RSI series (Wilder / EMA), same convention as signals._full_rsi."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def fetch_weekly_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Weekly bars for multi-timeframe context."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1wk", auto_adjust=True)
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def weekly_buy_alignment(closes_w: pd.Series, rsi_floor: float = 45.0) -> bool:
    """
    Weekly uptrend filter for long-bias scans: last weekly close above ~10-week MA
    and weekly RSI(14) above rsi_floor.
    """
    if closes_w is None or closes_w.empty or len(closes_w) < 15:
        return False
    ma10 = closes_w.rolling(10).mean().iloc[-1]
    rsi_s = rsi_series_wilder(closes_w, 14)
    rsi_now = rsi_s.iloc[-1]
    if pd.isna(ma10) or pd.isna(rsi_now):
        return False
    px = float(closes_w.iloc[-1])
    return px >= float(ma10) * 0.998 and float(rsi_now) >= rsi_floor


def calendar_days_until(date_label: Optional[str]) -> Optional[int]:
    """Days from today to next earnings date string YYYY-MM-DD (best-effort)."""
    if not date_label or len(str(date_label)) < 10:
        return None
    try:
        from datetime import date as date_cls

        s = str(date_label)[:10]
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        tgt = date_cls(y, m, d)
        return (tgt - date_cls.today()).days
    except Exception:
        return None


def index_regime(index_ticker: str = NIFTY_BENCHMARK, ma_period: int = 200) -> dict[str, Any]:
    """
    Simple regime: last close vs long MA on daily bars (cached-friendly single fetch).
    """
    out: dict[str, Any] = {
        "ticker": index_ticker,
        "price": None,
        "ma": None,
        "above_ma": None,
        "pct_vs_ma": None,
        "error": None,
    }
    try:
        hist = fetch_price_history(index_ticker, "1d")
        if hist.empty or len(hist) < ma_period + 5:
            out["error"] = "Insufficient index history"
            return out
        close = hist["Close"]
        ma = close.rolling(ma_period).mean().iloc[-1]
        px = float(close.iloc[-1])
        ma_v = float(ma)
        out["price"] = round(px, 2)
        out["ma"] = round(ma_v, 2)
        out["above_ma"] = px >= ma_v
        out["pct_vs_ma"] = pct_vs_ma(px, ma_v)
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def us_market_status_label(now_utc: Optional[datetime] = None) -> str:
    """Rough NYSE regular-session hint (educational, not live calendar-aware)."""
    now = now_utc or datetime.now(tz=ZoneInfo("UTC"))
    ny = now.astimezone(ZoneInfo("America/New_York"))
    wd = ny.weekday()
    if wd >= 5:
        return "US equity markets typically closed (weekend). Quotes reflect last close."
    hm = ny.hour * 60 + ny.minute
    open_m = 9 * 60 + 30
    close_m = 16 * 60
    if hm < open_m:
        return "NYSE/Nasdaq pre-open — US quotes usually reflect prior close until regular session."
    if hm > close_m:
        return "US regular session ended — data is as of today's close (or last trading day)."
    return "US regular trading hours (approx.) — intraday refresh may lag Yahoo Finance."


def compute_score(pe, vol_ratio, rsi):
    pe_score  = max(0.0, min(40.0, (50 - pe)  / 45 * 40)) if pe  and pe  > 0  else 0.0
    vol_score = max(0.0, min(30.0, (vol_ratio - 1) / 4 * 30)) if vol_ratio     else 0.0
    rsi_score = max(0.0, min(30.0, (rsi - 50) / 30 * 30)) if rsi and rsi > 50 else 0.0
    return round(pe_score + vol_score + rsi_score, 1)


# Buy / Hold / Avoid decision matrix (composite 0–100 + scenario signal overrides)
DECISION_ZONES: tuple[tuple[float, str, str], ...] = (
    (80.0, "Strong Buy", "PE + volume + RSI composite ≥ 80 — aligned momentum and valuation."),
    (60.0, "Buy / Watch", "Composite 60–79 — constructive; confirm with chart/news before entry."),
    (40.0, "Neutral / Wait", "Composite 40–59 — mixed; avoid aggressive new positions."),
    (0.0, "Avoid", "Composite < 40 — weak vs standard PE / vol / RSI weights."),
)


def composite_action_zone(score: Optional[float]) -> str:
    """Map StockSight composite score (0–100) to action zone label."""
    if score is None:
        return "—"
    try:
        s = float(score)
        if np.isnan(s):
            return "—"
    except (TypeError, ValueError):
        return "—"
    for threshold, label, _note in DECISION_ZONES:
        if s >= threshold:
            return label
    return "Avoid"


def matrix_decision_note(decision: str) -> str:
    for _thr, label, note in DECISION_ZONES:
        if label == decision:
            return note
    extra = {
        "Sell / Trim": "Scenario exit signal — consider reducing or tightening stops.",
        "Cautious Buy": "Scenario allows entry only with catalyst and tight risk control.",
        "Neutral / Wait": "No clear edge — wait for confirmation.",
    }
    return extra.get(decision, "Educational matrix only — not financial advice.")


def matrix_decision(
    *,
    score: Optional[float] = None,
    signal_label: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> str:
    """
    Unified buy/sell matrix: scenario signal (BUY/SELL/WAIT) plus composite score when available.
    """
    sig = (signal_label or "").upper().replace("HOLD-WAIT", "WAIT").strip()
    sid = (scenario_id or "").lower()

    if sid == "overbought_exit" or sig == "SELL":
        return "Sell / Trim"
    if sid == "volume_no_confirm" or sig == "WAIT":
        return "Neutral / Wait"
    if sig == "CAUTIOUS BUY" or sid == "extreme_oversold":
        zone = composite_action_zone(score) if score is not None else "Buy / Watch"
        if zone == "Strong Buy":
            return "Cautious Buy"
        if zone in ("Buy / Watch", "Neutral / Wait", "Avoid"):
            return "Cautious Buy" if zone != "Avoid" else "Neutral / Wait"
        return "Cautious Buy"

    if score is not None:
        return composite_action_zone(score)
    if sig == "BUY":
        return "Buy / Watch"
    return "Neutral / Wait"


def decision_from_metrics(
    pe: Optional[float],
    vol_ratio: Optional[float],
    rsi: Optional[float],
    *,
    score: Optional[float] = None,
    signal_label: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> tuple[str, float, str]:
    """Returns (decision_label, composite_score, matrix_note)."""
    comp = score
    if comp is None and pe is not None and vol_ratio is not None and rsi is not None:
        try:
            if not (np.isnan(float(pe)) or np.isnan(float(vol_ratio)) or np.isnan(float(rsi))):
                comp = compute_score(float(pe), float(vol_ratio), float(rsi))
        except (TypeError, ValueError):
            comp = None
    decision = matrix_decision(score=comp, signal_label=signal_label, scenario_id=scenario_id)
    comp_out = round(float(comp), 1) if comp is not None and not np.isnan(float(comp)) else float("nan")
    return decision, comp_out, matrix_decision_note(decision)


def add_decision_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add Decision + Matrix note (+ Composite if missing) to a results dataframe."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if "Score" in out.columns and "Composite" not in out.columns:
        out["Composite"] = out["Score"]

    def _row_decision(row: pd.Series) -> str:
        pe = row.get("PE Ratio", row.get("PE"))
        vol = row.get("Volume Ratio", row.get("Vol×"))
        rsi = row.get("RSI")
        sc = row.get("Composite", row.get("Score"))
        dec, _, _ = decision_from_metrics(pe, vol, rsi, score=sc)
        return dec

    out["Decision"] = out.apply(_row_decision, axis=1)
    out["Matrix note"] = out["Decision"].map(matrix_decision_note)
    return out


def extract_yfinance_fundamentals(info: dict) -> dict[str, Optional[float]]:
    """Pull ROE / debt / revenue growth from Yahoo `info` (keys vary). Percent-style normalization."""

    def gf(keys: tuple[str, ...]) -> Optional[float]:
        for k in keys:
            v = info.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
                if np.isnan(fv):
                    continue
                return fv
            except (TypeError, ValueError):
                continue
        return None

    roe = gf(("returnOnEquity", "return_on_equity"))
    if roe is not None and abs(roe) <= 1.0:
        roe *= 100.0

    de = gf(("debtToEquity", "totalDebtToEquity"))

    rg = gf(("revenueGrowth", "revenue_growth"))
    if rg is not None and abs(rg) <= 1.0:
        rg *= 100.0

    return {"roe_pct": roe, "debt_equity": de, "revenue_growth_pct": rg}


def normalize_debt_equity(v: Optional[float]) -> Optional[float]:
    """Yahoo often reports D/E as percent (e.g. 39); values > 1 are scaled to a ratio."""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(fv):
        return None
    if fv > 1.0:
        fv = fv / 100.0
    return round(fv, 3)


def drawdown_pct_from_52w_high(price: float, week52_high: Optional[float]) -> Optional[float]:
    """Percent below the 52-week high (e.g. 25.0 = 25% drawdown)."""
    if week52_high is None or week52_high <= 0 or price <= 0:
        return None
    return round((1.0 - float(price) / float(week52_high)) * 100.0, 1)


def extract_healthy_dip_fundamentals(info: dict) -> dict[str, Optional[float]]:
    """Fundamentals for quality-at-dip screens (Yahoo `info`, best-effort)."""

    def gf(keys: tuple[str, ...]) -> Optional[float]:
        for k in keys:
            v = info.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
                if np.isnan(fv):
                    continue
                return fv
            except (TypeError, ValueError):
                continue
        return None

    base = extract_yfinance_fundamentals(info)
    de = normalize_debt_equity(base.get("debt_equity"))

    pb = gf(("priceToBook", "price_to_book"))
    peg = gf(("pegRatio", "trailingPegRatio"))

    ic = gf(("interestCoverage", "interest_coverage"))
    pm = gf(("profitMargins", "profit_margin"))
    if pm is not None and abs(pm) <= 1.0:
        pm *= 100.0

    wk_high = gf(("fiftyTwoWeekHigh", "52WeekHigh"))
    wk_low = gf(("fiftyTwoWeekLow", "52WeekLow"))

    return {
        **base,
        "debt_equity": de,
        "price_to_book": pb,
        "peg_ratio": peg,
        "interest_coverage": ic,
        "profit_margin_pct": pm,
        "week52_high": wk_high,
        "week52_low": wk_low,
    }


def fetch_daily_history_min_bars(ticker: str, min_bars: int = 220) -> pd.DataFrame:
    """Daily OHLCV with enough history for long moving averages (up to ~2y via Yahoo)."""
    hist = fetch_price_history(ticker, "1d")
    if hist is not None and len(hist) >= min_bars:
        return hist
    try:
        ext = yf.Ticker(ticker).history(period="2y", interval="1d", auto_adjust=True)
        if ext is not None and not ext.empty:
            if hist is None or hist.empty or len(ext) >= len(hist):
                return ext
    except Exception:
        pass
    return hist if hist is not None else pd.DataFrame()


# ─────────────────────────────────────────────
# Main Screening Function
# ─────────────────────────────────────────────

def screen_stocks(
    universe_name="Nifty 50 (NSE)",
    pe_threshold=30.0,
    vol_multiplier=1.5,
    rsi_min=50.0,
    progress_callback=None,
    interval_key: str = "1d",
    sector_filter: str = "",
    require_above_ma20: bool = False,
    require_macd_bullish: bool = False,
    *,
    min_roe_pct: Optional[float] = None,
    max_debt_equity: Optional[float] = None,
    min_revenue_growth_pct: Optional[float] = None,
    exclude_earnings_within_days: int = 0,
    min_rs_vs_bench: Optional[float] = None,
):
    tickers = UNIVERSES.get(universe_name, NIFTY_50)
    pe_cap  = PE_DATA_CAP.get(universe_name, 400)
    results = []
    total   = len(tickers)
    min_bar = min_bars_for_screen(interval_key)
    sector_needle = (sector_filter or "").strip().lower()

    bench_sym = NIFTY_BENCHMARK if "NSE" in str(universe_name).upper() else SPY_BENCHMARK
    bench_hist = fetch_price_history(bench_sym, interval_key)

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i + 1, total, ticker)

        try:
            stock = yf.Ticker(ticker)

            hist = fetch_price_history(ticker, interval_key)
            if hist.empty or len(hist) < min_bar:
                continue

            closes  = hist["Close"]
            highs   = hist["High"]
            lows    = hist["Low"]
            volumes = hist["Volume"]
            current_price = round(float(closes.iloc[-1]), 2)

            sector_guess, _ind = get_sector_industry(stock)
            if sector_needle and sector_needle not in (sector_guess or "").lower():
                continue

            pe = get_pe(stock)
            if pe is None or pe <= 0 or pe > pe_cap:
                continue
            pe = round(pe, 2)

            try:
                info = stock.info or {}
            except Exception:
                info = {}
            fund = extract_yfinance_fundamentals(info)
            if min_roe_pct is not None:
                if fund["roe_pct"] is None or fund["roe_pct"] < float(min_roe_pct):
                    continue
            if max_debt_equity is not None:
                if fund["debt_equity"] is None or fund["debt_equity"] > float(max_debt_equity):
                    continue
            if min_revenue_growth_pct is not None:
                if fund["revenue_growth_pct"] is None or fund["revenue_growth_pct"] < float(min_revenue_growth_pct):
                    continue

            earn_raw = next_earnings_label(stock)
            d_earn = calendar_days_until(earn_raw)
            if exclude_earnings_within_days > 0 and d_earn is not None:
                if 0 <= d_earn <= int(exclude_earnings_within_days):
                    continue

            vol_ratio = compute_volume_ratio(volumes)
            if vol_ratio is None or np.isnan(vol_ratio):
                continue

            rsi = compute_rsi(closes)
            if rsi is None or np.isnan(rsi):
                continue

            if pe        > pe_threshold:   continue
            if vol_ratio < vol_multiplier: continue
            if rsi       < rsi_min:        continue

            rs_excess = relative_strength_vs_benchmark(hist, bench_hist, bars=20)
            if min_rs_vs_bench is not None:
                thr_rs = float(min_rs_vs_bench)
                if rs_excess is None or rs_excess < thr_rs:
                    continue

            ma20_s = closes.rolling(20).mean()
            ma50_s = closes.rolling(50).mean()
            ma20 = float(ma20_s.iloc[-1]) if len(closes) >= 20 else np.nan
            ma50 = float(ma50_s.iloc[-1]) if len(closes) >= 50 else np.nan
            if require_above_ma20 and not np.isnan(ma20) and current_price < ma20:
                continue

            macd_l, macd_s, macd_h = compute_macd(closes)
            if require_macd_bullish:
                if np.isnan(macd_h) or macd_h <= 0:
                    continue

            bb_pct_b, _bb_m, _bb_u, bb_l = compute_bollinger_pct_b(closes)
            atr_v = compute_atr(highs, lows, closes)
            gc = ma_cross_recent(ma20_s, ma50_s, lookback=5)

            score    = compute_score(pe, vol_ratio, rsi)
            decision, _, matrix_note = decision_from_metrics(
                pe, vol_ratio, rsi, score=score, signal_label="BUY"
            )
            is_nse   = ticker.endswith(".NS") or ticker.endswith(".BO")
            currency = "₹" if is_nse else "$"
            links    = get_stock_links(ticker)
            lk       = list(links.keys())

            row = {
                "Ticker":        ticker.replace(".NS", "").replace(".BO", ""),
                "Currency":      currency,
                "Interval":      interval_key,
                "Sector":        sector_guess or "—",
                "Price":         current_price,
                "PE Ratio":      pe,
                "Volume Ratio":  vol_ratio,
                "RSI":           rsi,
                "RS vs Idx":     rs_excess,
                "MACD Hist":     macd_h if not np.isnan(macd_h) else None,
                "% vs MA20":     pct_vs_ma(current_price, ma20) if not np.isnan(ma20) else None,
                "MA20×Golden50": "Yes" if gc else "—",
                "%B Bollinger":  bb_pct_b if bb_pct_b is not None and not np.isnan(bb_pct_b) else None,
                "ATR14":         atr_v if not np.isnan(atr_v) else None,
                "Next Earnings": earn_raw or "—",
                "ΔEarn(d)":      d_earn,
                "ROE %":         fund["roe_pct"],
                "D/E":           fund["debt_equity"],
                "Rev growth %":  fund["revenue_growth_pct"],
                "Score":         score,
                "Composite":     score,
                "Decision":      decision,
                "Matrix note":   matrix_note,
                lk[0]:           links[lk[0]],
                lk[1]:           links[lk[1]],
                lk[2]:           links[lk[2]],
            }

            results.append(row)

        except Exception:
            continue

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("Score", ascending=False).reset_index(drop=True)
    df.index += 1
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
