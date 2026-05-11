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
