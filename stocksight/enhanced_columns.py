"""
Enhanced column configuration and color indicators for StockSight main screen.

Provides:
- Color-coded buy/hold/sell signals
- Optimized column display for better decision-making
- Quality gates and confidence indicators
- Visual hierarchy for key metrics
"""

import streamlit as st
import pandas as pd
from typing import Optional, Dict, Any
import numpy as np


# ─────────────────────────────────────────────────────────────
# Color codes for analyst recommendations
# ─────────────────────────────────────────────────────────────

SIGNAL_COLORS = {
    "Strong Buy": "#00e5a0",      # Bright green
    "Buy": "#4db8ff",             # Light blue
    "Outperform": "#4db8ff",      # Light blue
    "Hold": "#f0b429",            # Orange/Yellow
    "Neutral": "#f0b429",         # Orange/Yellow
    "Sell": "#ff9d42",            # Darker orange
    "Underperform": "#ff9d42",    # Darker orange
    "Strong Sell": "#ff4d4d",     # Red
    "—": "#7abeac",               # Gray
}

SIGNAL_BG_COLORS = {
    "Strong Buy": "#0a2e1e",      # Dark green bg
    "Buy": "#0a1f2e",             # Dark blue bg
    "Outperform": "#0a1f2e",      # Dark blue bg
    "Hold": "#2e1a00",            # Dark orange bg
    "Neutral": "#2e1a00",         # Dark orange bg
    "Sell": "#2e1400",            # Darker orange bg
    "Underperform": "#2e1400",    # Darker orange bg
    "Strong Sell": "#2e0a0a",     # Dark red bg
    "—": "#1a1a1a",               # Dark gray bg
}

# RSI levels and color coding
RSI_COLOR_LEVELS = {
    "oversold": "#ff4d4d",        # Red (RSI < 30)
    "weak": "#ff9d42",            # Orange (30 <= RSI < 50)
    "neutral": "#f0b429",         # Yellow (50 <= RSI < 60)
    "strong": "#4db8ff",          # Light blue (60 <= RSI < 70)
    "overbought": "#00e5a0",      # Green (RSI >= 70)
}

# Volume ratio colors
VOLUME_COLOR_LEVELS = {
    "low": "#7abeac",             # Gray (< 1.5×)
    "normal": "#f0b429",          # Yellow (1.5× - 2×)
    "high": "#4db8ff",            # Light blue (2× - 3×)
    "very_high": "#00e5a0",       # Green (>= 3×)
}

# PE ratio colors (lower is better for value)
PE_COLOR_LEVELS = {
    "very_cheap": "#00e5a0",      # Green (PE < 10)
    "cheap": "#4db8ff",           # Light blue (10 <= PE < 15)
    "fair": "#f0b429",            # Yellow (15 <= PE < 25)
    "expensive": "#ff9d42",       # Orange (25 <= PE < 40)
    "overvalued": "#ff4d4d",      # Red (PE >= 40)
}

# Momentum indicators colors
MOMENTUM_COLORS = {
    "bullish": "#00e5a0",         # Green
    "moderately_bullish": "#4db8ff",  # Light blue
    "neutral": "#f0b429",         # Yellow
    "moderately_bearish": "#ff9d42",  # Orange
    "bearish": "#ff4d4d",         # Red
}


def get_rsi_color(rsi: Optional[float]) -> str:
    """Get color code based on RSI value."""
    if rsi is None or rsi != rsi:  # NaN check
        return "#7abeac"
    if rsi < 30:
        return RSI_COLOR_LEVELS["oversold"]
    elif rsi < 50:
        return RSI_COLOR_LEVELS["weak"]
    elif rsi < 60:
        return RSI_COLOR_LEVELS["neutral"]
    elif rsi < 70:
        return RSI_COLOR_LEVELS["strong"]
    else:
        return RSI_COLOR_LEVELS["overbought"]


def get_volume_color(vol_ratio: Optional[float]) -> str:
    """Get color code based on volume ratio."""
    if vol_ratio is None or vol_ratio != vol_ratio:  # NaN check
        return "#7abeac"
    if vol_ratio < 1.5:
        return VOLUME_COLOR_LEVELS["low"]
    elif vol_ratio < 2.0:
        return VOLUME_COLOR_LEVELS["normal"]
    elif vol_ratio < 3.0:
        return VOLUME_COLOR_LEVELS["high"]
    else:
        return VOLUME_COLOR_LEVELS["very_high"]


def get_pe_color(pe: Optional[float]) -> str:
    """Get color code based on PE ratio."""
    if pe is None or pe != pe:  # NaN check
        return "#7abeac"
    if pe < 10:
        return PE_COLOR_LEVELS["very_cheap"]
    elif pe < 15:
        return PE_COLOR_LEVELS["cheap"]
    elif pe < 25:
        return PE_COLOR_LEVELS["fair"]
    elif pe < 40:
        return PE_COLOR_LEVELS["expensive"]
    else:
        return PE_COLOR_LEVELS["overvalued"]


def get_signal_color(recommendation: Optional[str]) -> str:
    """Get color code for analyst recommendation."""
    if not recommendation:
        return SIGNAL_COLORS["—"]
    rec_str = str(recommendation).strip()
    return SIGNAL_COLORS.get(rec_str, SIGNAL_COLORS["—"])


def format_signal_cell(recommendation: Optional[str], count: Optional[int] = None) -> str:
    """
    Format analyst recommendation cell with color background.
    
    Returns HTML string with color styling.
    """
    if not recommendation or recommendation == "—":
        return "—"
    
    color = get_signal_color(recommendation)
    bg_color = SIGNAL_BG_COLORS.get(str(recommendation).strip(), SIGNAL_BG_COLORS["—"])
    
    text = str(recommendation)
    if count and count > 0:
        text += f" ({count} analysts)"
    
    return f'<div style="background-color: {bg_color}; color: {color}; padding: 4px 8px; border-radius: 4px; font-weight: bold; text-align: center;">{text}</div>'


def get_optimal_columns_for_screen() -> list[str]:
    """
    Return recommended columns for the main screen after scan.
    
    Optimized for quick stock selection with key indicators and colors.
    """
    return [
        "Ticker",
        "Price",
        "PE",
        "Vol×",
        "RSI",
        "Composite",  # or Score
        "Decision",
        "Analyst consensus",
        "TradingView rating",
        "Upside to target %",
        "MACD hist",
        "% vs MA20",
        "MA20×50",
        "%B",
        "Market sentiment",
        "News score",
        "Recent news (<4d)",
        "Entry",
        "Stop Loss",
        "Target 2",
        "RRR",
        "Confidence",
    ]


def create_optimized_column_config() -> Dict[str, Any]:
    """
    Create enhanced column configuration for main screen.
    
    Includes color indicators and better formatting for decision-making.
    """
    return {
        # Key metrics
        "Ticker": st.column_config.TextColumn("Ticker", width="small"),
        "Price": st.column_config.NumberColumn("Price", format="₹%.2f"),
        "PE": st.column_config.NumberColumn("P/E", format="%.1f"),
        "Vol×": st.column_config.NumberColumn("Vol×", format="%.2f"),
        "RSI": st.column_config.NumberColumn("RSI", format="%.1f"),
        
        # Scores and decisions
        "Composite": st.column_config.ProgressColumn(
            "Composite",
            min_value=0,
            max_value=100,
            format="%d"
        ),
        "Score": st.column_config.ProgressColumn(
            "Score",
            min_value=0,
            max_value=100,
            format="%d"
        ),
        "Decision": st.column_config.TextColumn("Decision", width="medium"),
        
        # Analyst recommendations
        "Analyst consensus": st.column_config.TextColumn("Analyst consensus", width="small"),
        "TradingView rating": st.column_config.TextColumn("TradingView rating", width="large"),
        "Analyst recommendation": st.column_config.TextColumn("Analyst recommendation", width="large"),
        "Upside to target %": st.column_config.NumberColumn("Upside %", format="%+.1f"),
        
        # Technical indicators
        "MACD hist": st.column_config.NumberColumn("MACD", format="%.4f"),
        "% vs MA20": st.column_config.NumberColumn("% vs MA20", format="%+.2f"),
        "MA20×50": st.column_config.TextColumn("MA20×50", width="small"),
        "%B": st.column_config.NumberColumn("%B", format="%.3f"),
        "ATR14": st.column_config.NumberColumn("ATR14", format="%.4f"),
        
        # Market data
        "Market sentiment": st.column_config.TextColumn("Market sentiment", width="medium"),
        "Sentiment why": st.column_config.TextColumn("Sentiment why", width="large"),
        "News score": st.column_config.ProgressColumn(
            "News score",
            min_value=0,
            max_value=100,
            format="%d"
        ),
        "Recent news (<4d)": st.column_config.TextColumn("Recent news", width="large"),
        
        # Trade levels
        "Entry": st.column_config.NumberColumn("Entry", format="₹%.2f"),
        "Stop Loss": st.column_config.NumberColumn("Stop", format="₹%.2f"),
        "Target 1": st.column_config.NumberColumn("T1", format="₹%.2f"),
        "Target 2": st.column_config.NumberColumn("T2", format="₹%.2f"),
        "Target 3": st.column_config.NumberColumn("T3", format="₹%.2f"),
        "RRR": st.column_config.NumberColumn("RRR", format="%.1f×"),
        "Risk %": st.column_config.NumberColumn("Risk %", format="%.1f"),
        
        # Confidence and metadata
        "Confidence": st.column_config.TextColumn("Confidence", width="small"),
        "First seen": st.column_config.TextColumn("First seen", width="small"),
        "Sector": st.column_config.TextColumn("Sector", width="medium"),
    }


def add_buy_signal_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add composite buy signal indicators based on key metrics.
    
    Returns dataframe with additional scoring columns:
    - Signal strength (0-100)
    - Signal type (Strong Buy, Buy, Hold, Sell, etc.)
    - Action recommendation
    """
    if df is None or df.empty:
        return df
    
    out = df.copy()
    
    signal_scores = []
    signal_types = []
    
    for idx, row in out.iterrows():
        score = 0
        factors = []
        
        # RSI factor (0-20 points)
        try:
            rsi = float(row.get("RSI", 50))
            if rsi < 30:
                score += 15
                factors.append("Oversold")
            elif rsi < 50:
                score += 10
                factors.append("Weakening")
            elif rsi < 70:
                score += 5
                factors.append("Neutral RSI")
            else:
                score += 0
                factors.append("Overbought")
        except:
            pass
        
        # Volume factor (0-15 points)
        try:
            vol_ratio = float(row.get("Vol×", 1.0))
            if vol_ratio >= 3.0:
                score += 15
                factors.append("Very High Vol")
            elif vol_ratio >= 2.0:
                score += 12
                factors.append("High Vol")
            elif vol_ratio >= 1.5:
                score += 8
                factors.append("Above Avg Vol")
        except:
            pass
        
        # PE factor (0-15 points) - lower PE is better
        try:
            pe = float(row.get("PE", 25))
            if pe < 10:
                score += 15
                factors.append("Very Cheap")
            elif pe < 15:
                score += 12
                factors.append("Cheap")
            elif pe < 25:
                score += 8
                factors.append("Fair Value")
            elif pe < 40:
                score += 3
                factors.append("Expensive")
        except:
            pass
        
        # Composite/Score factor (0-25 points)
        try:
            composite = float(row.get("Composite", row.get("Score", 50)))
            if composite >= 75:
                score += 25
                factors.append("Strong Score")
            elif composite >= 60:
                score += 18
                factors.append("Good Score")
            elif composite >= 50:
                score += 10
                factors.append("Average Score")
        except:
            pass
        
        # Analyst factor (0-15 points)
        try:
            consensus = str(row.get("Analyst consensus", row.get("TradingView consensus", ""))).upper()
            if "STRONG BUY" in consensus or "STRONG_BUY" in consensus:
                score += 15
                factors.append("Strong Buy Signal")
            elif "BUY" in consensus:
                score += 12
                factors.append("Buy Signal")
            elif "OUTPERFORM" in consensus:
                score += 10
                factors.append("Outperform")
        except:
            pass
        
        # Determine signal type
        if score >= 80:
            signal_type = "🟢 Strong Buy"
        elif score >= 65:
            signal_type = "🟢 Buy"
        elif score >= 50:
            signal_type = "🟡 Hold"
        elif score >= 35:
            signal_type = "🟠 Weak"
        else:
            signal_type = "🔴 Avoid"
        
        signal_scores.append(score)
        signal_types.append(signal_type)
    
    out["Signal Strength"] = signal_scores
    out["Signal Type"] = signal_types
    
    return out


def render_column_selector_panel(df: pd.DataFrame, key: str = "col_select") -> list[str]:
    """
    Render a Streamlit panel for users to customize visible columns.
    
    Returns list of selected column names.
    """
    import streamlit as st
    
    if df is None or df.empty:
        return list(df.columns) if df is not None else []
    
    with st.expander("📋 Customize columns", expanded=False):
        st.caption("Select columns to display in the results table")
        
        all_cols = list(df.columns)
        recommended_cols = get_optimal_columns_for_screen()
        
        # Filter recommended columns to only those that exist in dataframe
        recommended_existing = [c for c in recommended_cols if c in all_cols]
        other_cols = [c for c in all_cols if c not in recommended_existing]
        
        # Multi-select with grouped options
        selected = st.multiselect(
            "Display columns",
            options=all_cols,
            default=recommended_existing[:15],  # Show first 15 by default
            key=f"{key}_select",
        )
        
        # Quick preset buttons
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📊 Recommended", key=f"{key}_preset_rec"):
                st.session_state[f"{key}_select"] = recommended_existing[:15]
                st.rerun()
        with col2:
            if st.button("📈 All columns", key=f"{key}_preset_all"):
                st.session_state[f"{key}_select"] = all_cols
                st.rerun()
        with col3:
            if st.button("🎯 Essential", key=f"{key}_preset_ess"):
                essential = ["Ticker", "Price", "PE", "Vol×", "RSI", "Composite", "Decision", "Analyst consensus", "TradingView rating"]
                st.session_state[f"{key}_select"] = [c for c in essential if c in all_cols]
                st.rerun()
        
        return selected or recommended_existing
    
    return recommended_existing
