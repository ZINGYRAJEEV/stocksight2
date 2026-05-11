import requests

url = 'https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

response = requests.get(url, headers=headers)
data = response.json()
full_symbols = [item['symbol'] for item in data['data'] if item['symbol'] != 'NIFTY 500']

NIFTY_50_symbols = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'BHARTIARTL', 'ICICIBANK',
    'INFOSYS', 'SBIN', 'HINDUNILVR', 'INFY', 'ITC',
    'KOTAKBANK', 'LT', 'HCLTECH', 'AXISBANK', 'BAJFINANCE',
    'WIPRO', 'ASIANPAINT', 'MARUTI', 'SUNPHARMA', 'TITAN',
    'NTPC', 'POWERGRID', 'ULTRACEMCO', 'NESTLEIND', 'BAJAJFINSV',
    'ADANIENT', 'ADANIPORTS', 'JSWSTEEL', 'TATASTEEL', 'TATACONSUM',
    'HINDALCO', 'DIVISLAB', 'CIPLA', 'DRREDDY', 'APOLLOHOSP',
    'EICHERMOT', 'HEROMOTOCO', 'M&M', 'BAJAJ-AUTO', 'TATAMOTORS',
    'COALINDIA', 'ONGC', 'INDUSINDBK', 'BPCL', 'BRITANNIA',
    'GRASIM', 'TECHM', 'SBILIFE', 'HDFCLIFE', 'LTIM'
]

NIFTY_500_EXTRA_symbols = [s for s in full_symbols if s not in NIFTY_50_symbols]

NIFTY_500_EXTRA = [s + '.NS' for s in NIFTY_500_EXTRA_symbols]

print('NIFTY_500_EXTRA = [')
for i in range(0, len(NIFTY_500_EXTRA), 5):
    print('    ' + ', '.join(f'"{s}"' for s in NIFTY_500_EXTRA[i:i+5]) + ',')
print(']')