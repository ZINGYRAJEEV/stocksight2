"""
Compatibility entry — Streamlit Cloud may use `app.py` or `Overview.py`.

The full multipage app (st.navigation + all screeners) lives in Overview.py.
"""
from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "Overview.py"), run_name="__main__")
