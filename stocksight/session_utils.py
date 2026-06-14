"""
Session state management and duplicate prevention utilities for StockSight.

Provides:
- Safe session initialization
- Proper cache invalidation
- Duplicate prevention mechanisms
- Data cleanup utilities
"""

import streamlit as st
import pandas as pd
from typing import Optional, Any, Dict
import hashlib
import json


def initialize_session_state(key: str, default_value: Any = None, force_reset: bool = False) -> None:
    """
    Safely initialize a session state variable.
    
    Args:
        key: Session state key name
        default_value: Default value (DataFrame/dict/list/etc)
        force_reset: If True, always reset to default even if key exists
    """
    if force_reset or key not in st.session_state:
        if default_value is None:
            default_value = pd.DataFrame() if "df" in key.lower() or "results" in key.lower() else None
        st.session_state[key] = default_value


def clear_scan_cache(pattern: str = "") -> None:
    """
    Clear scan-related cache to prevent duplicate data.
    
    Args:
        pattern: If provided, only clear keys matching pattern (e.g., "app1_", "bha_")
    """
    keys_to_remove = []
    for key in st.session_state.keys():
        if "cache" in key.lower() or "news_" in key.lower() or "_yahoo_" in key.lower():
            if not pattern or pattern in key:
                keys_to_remove.append(key)
    
    for key in keys_to_remove:
        st.session_state.pop(key, None)


def safe_update_dataframe(session_key: str, new_df: pd.DataFrame) -> None:
    """
    Safely update a dataframe in session state, preventing duplicates.
    
    Always replaces rather than appends. Clears related cache.
    
    Args:
        session_key: Session state key for the dataframe
        new_df: New dataframe to store
    """
    # Clear any related cache
    clear_scan_cache(pattern=session_key.split("_")[0])
    
    # Replace (never append)
    st.session_state[session_key] = new_df.copy() if isinstance(new_df, pd.DataFrame) else new_df
    
    # Mark timestamp for tracking
    st.session_state[f"{session_key}_updated_at"] = pd.Timestamp.now()


def get_dataframe_hash(df: pd.DataFrame) -> str:
    """Get hash of dataframe for change detection."""
    if df is None or df.empty:
        return "empty"
    try:
        content = df.to_csv(index=False).encode('utf-8')
        return hashlib.md5(content).hexdigest()[:8]
    except:
        return "error"


def detect_duplicate_rows(df: pd.DataFrame, subset: Optional[list[str]] = None) -> pd.DataFrame:
    """
    Detect and return only unique rows from dataframe.
    
    Args:
        df: Input dataframe
        subset: Columns to check for duplicates (default: all columns)
    
    Returns:
        Dataframe with duplicate rows removed
    """
    if df is None or df.empty:
        return df
    
    # Use Ticker + Price as default uniqueness key
    if subset is None:
        if "Ticker" in df.columns and "Price" in df.columns:
            subset = ["Ticker", "Price"]
        elif "Ticker" in df.columns:
            subset = ["Ticker"]
        else:
            subset = list(df.columns)
    
    # Drop duplicates keeping first occurrence
    return df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)


def cleanup_scan_results(session_prefix: str) -> None:
    """
    Full cleanup for a scan session (e.g., 'app1', 'bha', 'volume_led').
    
    Removes all related session state and cache for that scan.
    
    Args:
        session_prefix: Prefix of session keys (e.g., 'app1', 'bha')
    """
    keys_to_remove = []
    for key in st.session_state.keys():
        if key.startswith(session_prefix):
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        st.session_state.pop(key, None)


def should_rerun_scan(session_key: str, check_interval: int = 60) -> bool:
    """
    Check if scan should be rerun based on time interval.
    
    Args:
        session_key: Session key for last run timestamp
        check_interval: Seconds between reruns
    
    Returns:
        True if enough time has passed since last run
    """
    last_run = st.session_state.get(f"{session_key}_last_run")
    if last_run is None:
        return False
    
    elapsed = (pd.Timestamp.now() - last_run).total_seconds()
    return elapsed >= check_interval


def validate_dataframe_consistency(df: pd.DataFrame) -> bool:
    """
    Validate dataframe doesn't have obvious data quality issues.
    
    Returns:
        True if dataframe looks good, False if issues detected
    """
    if df is None or df.empty:
        return True
    
    # Check for obvious duplicates
    if len(df) != len(df.drop_duplicates()):
        return False
    
    # Check for required columns
    required_cols = ["Ticker", "Price"]
    if not all(col in df.columns for col in required_cols):
        return False
    
    # Check for NaN in Ticker column
    if df["Ticker"].isna().any():
        return False
    
    return True


class SessionStateManager:
    """Context manager for safe session state operations."""
    
    def __init__(self, prefix: str):
        """
        Initialize session state manager.
        
        Args:
            prefix: Prefix for all session keys (e.g., 'app1', 'volume_led')
        """
        self.prefix = prefix
        self.results_key = f"{prefix}_results_df"
        self.last_run_key = f"{prefix}_last_run"
        self.is_running_key = f"{prefix}_is_running"
    
    def initialize(self) -> None:
        """Initialize all session state variables."""
        initialize_session_state(self.results_key, pd.DataFrame())
        initialize_session_state(self.last_run_key, None)
        initialize_session_state(self.is_running_key, False)
    
    def set_results(self, df: pd.DataFrame) -> None:
        """Set results and mark as updated."""
        safe_update_dataframe(self.results_key, df)
        st.session_state[self.last_run_key] = pd.Timestamp.now()
    
    def get_results(self) -> pd.DataFrame:
        """Get current results."""
        return st.session_state.get(self.results_key, pd.DataFrame())
    
    def get_last_run(self) -> Optional[pd.Timestamp]:
        """Get last run timestamp."""
        return st.session_state.get(self.last_run_key)
    
    def clear(self) -> None:
        """Clear all session state for this prefix."""
        cleanup_scan_results(self.prefix)
    
    def set_running(self, is_running: bool) -> None:
        """Mark scan as running/complete."""
        st.session_state[self.is_running_key] = is_running
    
    def is_running(self) -> bool:
        """Check if scan is currently running."""
        return st.session_state.get(self.is_running_key, False)


def deduplicate_scan_results(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove duplicate records from scan results.
    
    Keeps first occurrence of each unique Ticker.
    
    Args:
        df: Scan results dataframe
    
    Returns:
        Dataframe with duplicates removed
    """
    if df is None or df.empty:
        return df
    
    if "Ticker" not in df.columns:
        return df
    
    # Sort by index to keep chronologically first records
    df_sorted = df.sort_index()
    
    # Drop duplicates by Ticker, keeping first
    df_dedup = df_sorted.drop_duplicates(subset=["Ticker"], keep="first")
    
    # Reset index to clean order
    return df_dedup.reset_index(drop=True)
