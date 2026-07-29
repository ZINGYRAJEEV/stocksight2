"""Lightweight sidebar/nav chrome — keep Overview free of heavy ui_components imports."""

from __future__ import annotations

APP_CHROME_CSS = """
<style>
/* Sidebar nav — dark panel, light text (do not use html/body/[class*="css"] globals). */
section[data-testid="stSidebar"],
[data-testid="stSidebar"] {
    background-color: #0d1f18 !important;
    border-right: 1px solid #1a3b31 !important;
    color: #e8f7ef !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    background-color: #0d1f18 !important;
    color: #e8f7ef !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] a,
[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNavLink"],
[data-testid="stSidebarNavLink"] span {
    color: #e8f7ef !important;
}
[data-testid="stSidebarNavLink"][aria-current="page"],
[data-testid="stSidebarNavLink"][aria-current="page"] span {
    color: #25d366 !important;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
    color: #a3d8b8 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #1a3b31 !important;
}
[data-testid="stSidebar"] button[kind="header"] {
    color: #e8f7ef !important;
}
</style>
"""


def inject_app_chrome() -> None:
    """Sidebar + nav styling — call once from Overview.py so every page has a readable menu."""
    try:
        import streamlit as st
    except ImportError:
        return
    if st.session_state.get("_app_chrome_injected"):
        return
    st.markdown(APP_CHROME_CSS, unsafe_allow_html=True)
    st.session_state["_app_chrome_injected"] = True
