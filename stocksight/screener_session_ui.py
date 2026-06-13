"""Shared Screener.in session status + refresh controls for Streamlit pages."""

from __future__ import annotations

import streamlit as st

from screener_auth import ensure_screener_session, is_screener_session_valid, load_screener_block
from screener_buyback import set_screener_cookie_override


def _setup_markdown(*, extra_links: str = "") -> str:
    base = """
**Setup** — add to `.streamlit/secrets.toml` (gitignored):

```toml
[screener]
email = "your@email.com"
password = "your-screener-password"
sessionid = "auto-updated"
csrftoken = "auto-updated"
```

**Auto-refresh (recommended)** — add `email` + `password`; use **Refresh session** below when cookies expire.

**Manual cookies** — DevTools → Application → Cookies → `www.screener.in` → copy `sessionid` and `csrftoken`.

Or run: `python scripts/refresh_screener_session.py`
"""
    if extra_links.strip():
        return base + "\n" + extra_links.strip()
    return base


def clear_screener_feed_caches() -> None:
    """Clear Streamlit caches on pages that fetch Screener feeds."""
    for mod_name in ("bulk_order_page", "nse_intraday_intel_page", "buyback_page"):
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue
        for attr in dir(mod):
            if not attr.startswith("_cached"):
                continue
            fn = getattr(mod, attr, None)
            if callable(fn) and hasattr(fn, "clear"):
                try:
                    fn.clear()
                except Exception:
                    pass


def render_screener_session_panel(
    *,
    key_prefix: str = "screener_sess",
    success_message: str = "Screener.in session active.",
    extra_setup_links: str = "",
    expand_setup_when_invalid: bool = True,
) -> bool:
    """
    Status row + Check / Refresh / Force login buttons.

    Returns True when the current session passes a live full-text check.
    """
    block = load_screener_block()
    cookies = {k: block[k] for k in ("sessionid", "csrftoken") if block.get(k)}
    has_login = bool(cookies.get("sessionid"))
    has_auto = bool(block.get("email") and block.get("password"))
    valid = is_screener_session_valid(cookies) if has_login else False

    if has_login and valid:
        st.success(success_message)
    elif has_login:
        st.warning(
            "Screener session **expired or invalid** — click **Refresh session** "
            "(requires email + password in secrets.toml)."
        )
    else:
        st.info(
            "Screener login not configured — add `[screener]` to `.streamlit/secrets.toml`."
        )

    b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
    with b1:
        check = st.button("🔍 Check session", key=f"{key_prefix}_check", use_container_width=True)
    with b2:
        refresh = st.button("🔄 Refresh session", key=f"{key_prefix}_refresh", use_container_width=True)
    with b3:
        force = st.button("🔁 Force re-login", key=f"{key_prefix}_force", use_container_width=True)
    with b4:
        if has_login:
            tag = "valid" if valid else "expired"
            auto = "auto-refresh on" if has_auto else "manual cookies only"
            st.caption(f"Session: **{tag}** · {auto}")

    if check:
        live = load_screener_block()
        live_cookies = {k: live[k] for k in ("sessionid", "csrftoken") if live.get(k)}
        if is_screener_session_valid(live_cookies):
            st.toast("Screener session is valid.", icon="✅")
        else:
            st.toast("Screener session expired or missing.", icon="⚠️")

    if refresh or force:
        with st.spinner("Refreshing Screener.in session…"):
            result = ensure_screener_session(force=force, save=True)
        if result.ok:
            set_screener_cookie_override(result.cookies)
            clear_screener_feed_caches()
            st.toast(result.message, icon="✅")
            st.rerun()
        else:
            st.error(result.message)

    show_setup = expand_setup_when_invalid and (not has_login or not valid)
    with st.expander(
        "🔐 Screener.in login setup",
        expanded=show_setup and not has_login,
    ):
        st.markdown(_setup_markdown(extra_links=extra_setup_links))

    return valid
