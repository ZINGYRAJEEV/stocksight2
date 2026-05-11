import requests
import json

# Fetch Nifty 50
url_nifty50 = 'https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

response = requests.get(url_nifty50, headers=headers, timeout=10)
nifty50_data = response.json()
nifty50_symbols = [item['symbol'] for item in nifty50_data['data'] if item['symbol'] != 'NIFTY 50']

# Common S&P 500 stocks (using a comprehensive list)
sp500_symbols = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "JNJ", "COST",
    "HD", "PG", "ABBV", "CVX", "MRK", "KO", "WMT", "BAC", "NFLX",
    "CRM", "AMD", "ORCL", "ACN", "TMO", "CSCO", "LIN", "ABT", "TXN",
    "PM", "PEP", "DHR", "INTC", "VZ", "ADBE", "DIS", "CMCSA", "MCD",
    "IBM", "GE", "CAT", "RTX", "HON", "UPS", "GS", "MS", "SPGI",
    "BLK", "AXP", "LOW", "AMGN", "ISRG", "AMAT", "BKNG", "TJX", "ELV",
    "SCHW", "BRK.B", "LMT", "NOC", "BA", "GILD", "REGN", "BIIB",
    "SYK", "SLB", "EOG", "COP", "MPC", "PSX", "VLO", "MOS",
    "CF", "ALB", "NEM", "GG", "VALE", "FCX", "HLI", "SCCO",
    "AA", "X", "STLD", "CLF", "MT", "NUE", "CMC",
    "AEE", "AEP", "CEG", "ED", "EXC", "NEE", "NRG", "PCG", "PEG",
    "PPL", "SO", "SRE", "WEC", "XEL", "DUK", "DTE", "EIX", "EQT",
    "ES", "ETR", "EVRG", "FE", "FIS", "IT", "MCO", "ADSK", "ASML",
    "CDNS", "CHTR", "CTAS", "ENPH", "FTNT", "GDDY", "IDXX", "ILMN",
    "INTU", "KEYS", "LRCX", "MNST", "NFLX", "NOW", "NVDA", "OKTA",
    "PAYX", "ROST", "SMCI", "SNPS", "SPLK", "TEAM", "TSLA", "TTD",
    "TWTC", "VEEV", "VRSK", "VRSN", "WDAY", "WKME", "WLTW", "XBLX",
    "ZM", "ZSCALER", "AME", "AKAM", "ALSK", "ANSS", "AON", "APH",
    "ARW", "APTV", "ATGE", "ATSG", "ATVI", "AUPH", "AVB", "AVT",
    "AWI", "AXON", "AYI", "AZO", "B", "BALL", "BAND", "BAP",
    "BBY", "BC", "BDX", "BEN", "BEST", "BF.B", "BG", "BGS",
    "BIDU", "BIO", "BKFS", "BKR", "BLK", "BLOW", "BLS", "BLUA",
    "BMI", "BMY", "BODY", "BOX", "BP", "BPOP", "BRKR", "BRX",
    "BSM", "BSMX", "BUD", "BUDS", "BUI", "BUR", "BWA", "BXP",
    "BYD", "CABK", "CAKE", "CAL", "CALM", "CALX", "CAME", "CAMP",
    "CAN", "CANG", "CANO", "CAR", "CARE", "CARS", "CART", "CASA",
    "CASE", "CASS", "CAT", "CATH", "CATO", "CAVM", "CBOE", "CBRE",
    "CBRL", "CBS", "CBSH", "CCJ", "CCK", "CCL", "CCMP", "CCU",
    "CCUR", "CCV", "CDC", "CDK", "CDNA", "CDNS", "CDT", "CDW"
]

# Generate Python code for Nifty 50
print("NIFTY_50 = [")
for i in range(0, len(nifty50_symbols), 5):
    symbols_line = nifty50_symbols[i:i+5]
    print('    ' + ', '.join(f'"{s}.NS"' for s in symbols_line) + ',')
print("]")
print()

# Generate Python code for S&P 500
print("SP500 = [")
for i in range(0, len(sp500_symbols), 5):
    symbols_line = sp500_symbols[i:i+5]
    print('    ' + ', '.join(f'"{s}"' for s in symbols_line) + ',')
print("]")
print(f"\n# S&P 500 count: {len(sp500_symbols)}")
