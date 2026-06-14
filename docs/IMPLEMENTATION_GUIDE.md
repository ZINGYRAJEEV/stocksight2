# Quick Implementation Guide

## To Enable Enhanced Main Screen with TradingView Analyst Data

### Step 1: Import the New Modules

In your main page file (e.g., `stocksight/pages/StockSight.py`):

```python
from enhanced_columns import (
    create_optimized_column_config,
    add_buy_signal_indicators,
    get_optimal_columns_for_screen,
    render_column_selector_panel,
)
```

### Step 2: After Running Screen

```python
# Your existing screen code
results_df = screen_stocks(
    universe=universe,
    max_pe=pe_max,
    min_volume_mult=vol_mult,
    min_rsi=rsi_min,
    # ... other parameters
)

# ADD THIS: Enhance with analyst data and signals
results_df = add_buy_signal_indicators(results_df)
```

### Step 3: Display with Optimized Columns

```python
# Option A: Use recommended columns
col_config = create_optimized_column_config()
st.dataframe(
    results_df,
    column_config=col_config,
    use_container_width=True,
    height=600,
)

# Option B: Let user customize columns
selected_cols = render_column_selector_panel(results_df, key="scan")
st.dataframe(
    results_df[selected_cols],
    use_container_width=True,
)
```

### Step 4: Add Explanation Banner

```python
with st.expander("📊 How to read the results", expanded=False):
    st.markdown("""
### Signal Strength Color Codes:
- 🟢 **Strong Buy** (Green) - High conviction, 80+ score
- 🟢 **Buy** (Light Blue) - Good opportunity, 65+ score  
- 🟡 **Hold** (Yellow) - Monitor, 50+ score
- 🟠 **Weak** (Orange) - Wait for confirmation, 35+ score
- 🔴 **Avoid** (Red) - Poor setup, < 35 score

### Key Indicators:
- **RSI**: Green (>70) = Overbought, Red (<30) = Oversold
- **Vol×**: Green (≥3×) = High volume spike
- **PE**: Green (<10) = Very cheap, Red (>40) = Overvalued
- **TradingView**: Real-time analyst consensus from multiple sources

### How to Use:
1. Look for 🟢 **Strong Buy** or **Buy** signals
2. Check TradingView rating confirms the signal
3. Verify PE is reasonable for the sector
4. Look at Volume × - higher is better confirmation
5. Check RSI isn't overbought (< 70)
    """)
```

---

## For All Scan Pages (Intraday, Breakout, etc.)

Apply to any scan page using this pattern:

```python
# After getting results from your screener
results_df = your_screener_function(...)

# Enhance with signals
results_df = add_buy_signal_indicators(results_df)

# Display
col_config = create_optimized_column_config()
st.dataframe(results_df, column_config=col_config)
```

---

## Testing the Integration

### Test 1: TradingView Analyst Data
```python
# Run this in terminal or notebook
python -c "
from stocksight.tradeview_analyst import fetch_tradeview_analyst_data
data = fetch_tradeview_analyst_data('RELIANCE', market='NSE')
print(data)
"
```

Expected output:
```python
{
    'consensus': 'Buy',
    'analyst_count': None,
    'target_mean': None,
    'target_high': None,
    'target_low': None,
    'upside_pct': None,
    'source': 'TradingView',
    'summary': 'Buy · Score 75/100'
}
```

### Test 2: Signal Scoring
```python
import pandas as pd
from enhanced_columns import add_buy_signal_indicators

# Create sample data
df = pd.DataFrame({
    'Ticker': ['RELIANCE', 'TCS', 'INFY'],
    'RSI': [65, 45, 70],
    'Vol×': [2.5, 1.2, 3.5],
    'PE': [18, 28, 32],
    'Composite': [72, 55, 81],
    'Analyst consensus': ['Buy', 'Hold', 'Buy']
})

# Add signals
df = add_buy_signal_indicators(df)
print(df[['Ticker', 'Signal Strength', 'Signal Type']])
```

Expected output:
```
    Ticker  Signal Strength Signal Type
0  RELIANCE              68      🟢 Buy
1      TCS              40  🟠 Weak
2     INFY              75  🟢 Buy
```

---

## Color Customization

Edit `stocksight/enhanced_columns.py` to customize colors:

```python
# Change Strong Buy color to different shade
SIGNAL_COLORS = {
    "Strong Buy": "#00ff00",  # Bright green
    "Buy": "#0088ff",         # Different blue
    # ... other colors
}

# Also update background colors
SIGNAL_BG_COLORS = {
    "Strong Buy": "#001100",  # Dark green
    # ... other colors
}
```

---

## Integration with Existing Features

### With Quality Gate
```python
results_df = screen_stocks(...)
results_df = add_buy_signal_indicators(results_df)
results_df = apply_quality_gate_columns(results_df)  # Existing function
```

### With Market Sentiment
```python
results_df = screen_stocks(...)
results_df = add_market_sentiment_columns(results_df)  # Existing
results_df = add_buy_signal_indicators(results_df)     # New
```

### With News Scanner
```python
results_df = screen_stocks(...)
results_df = enrich_results_news(results_df)            # Existing
results_df = add_buy_signal_indicators(results_df)      # New
```

---

## Performance Optimization

For large scans (>100 stocks), consider:

```python
# Only fetch analyst data for top N stocks
top_n = 50
if len(results_df) > top_n:
    top_df = results_df.head(top_n).copy()
    top_df = add_buy_signal_indicators(top_df)
    results_df = pd.concat([top_df, results_df[top_n:]], ignore_index=True)
else:
    results_df = add_buy_signal_indicators(results_df)
```

Or use caching:

```python
@st.cache_data(ttl=3600)
def get_enhanced_results(universe, filters):
    df = screen_stocks(universe, **filters)
    df = add_buy_signal_indicators(df)
    return df
```

---

## Troubleshooting

### Issue: Import Error
```
ModuleNotFoundError: No module named 'enhanced_columns'
```
**Solution:** Ensure files are in `stocksight/` directory

### Issue: No analyst data showing
**Solution:** Check TradingView connection and symbol format

### Issue: Colors not displaying
**Solution:** 
1. Clear Streamlit cache: `streamlit cache clear`
2. Hard refresh browser: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)

### Issue: Slow performance
**Solution:** Reduce number of stocks or disable TradingView fallback

---

## Next Steps

1. ✅ Update main StockSight page
2. ✅ Add to other scan pages
3. ✅ Test with live data
4. ✅ Gather user feedback
5. ⏳ Optimize based on feedback
6. ⏳ Add A/B testing for colors
7. ⏳ Export custom presets

---

For detailed documentation, see [MAIN_SCREEN_ENHANCEMENTS.md](MAIN_SCREEN_ENHANCEMENTS.md)
