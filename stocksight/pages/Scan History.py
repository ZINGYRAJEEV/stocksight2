"""Page: Scan History — local JSONL audit trail for StockSight + scenario scans."""

from __future__ import annotations

import streamlit as st
import pandas as pd

from scan_history_store import read_recent_lines
from ui_components import inject_css, safe_set_page_config

safe_set_page_config(page_title="Scan History | StockSight", page_icon="🗂️", layout="wide")
inject_css()

st.markdown("### 🗂️ Scan history")
st.caption("Reads `stocksight/.scan_history.jsonl` written after scenario scans and the main StockSight screener.")

limit = st.slider("Rows to load (newest first)", min_value=50, max_value=500, value=200, step=50)
rows = read_recent_lines(int(limit))

if not rows:
    st.info("No entries yet — run a scenario scan or **StockSight (Main Screener)**.")
else:
    df = pd.DataFrame(rows)
    if "symbols" in df.columns:

        def _preview(xs):
            if not isinstance(xs, list):
                return ""
            head = xs[:12]
            tail = " …" if len(xs) > len(head) else ""
            return ", ".join(head) + tail

        df["Symbols (preview)"] = df["symbols"].map(_preview)
        df = df.drop(columns=["symbols"])

    st.dataframe(df, use_container_width=True, hide_index=True)

st.markdown("---")
st.caption("Timestamps are UTC ISO strings from the logger.")
