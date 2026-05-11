from screener import screen_stocks

# Test the screening
df = screen_stocks("Nifty 500 (NSE)")
print(f"Total stocks screened: {len(df)}")
print(df.head())