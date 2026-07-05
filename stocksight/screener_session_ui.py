"""Shared Screener.in session status + refresh controls for Streamlit pages."""

from __future__ import annotations

import streamlit as st

from screener_auth import (
    ensure_screener_session,
    is_screener_session_valid,
    load_screener_block,
    save_screener_credentials_and_refresh,
)
from screener_browser_login import playwright_available, save_screener_google_browser_login
from screener_buyback import set_screener_cookie_override


def _setup_markdown(*, extra_links: str = "") -> str:
    base = """
**Setup** — add to `.streamlit/secrets.toml` (gitignored):

```toml
[screener]
sessionid = "auto-updated"
csrftoken = "auto-updated"
```

**Google sign-in (recommended)** — click **Login with Google (Screener)** below. A browser opens on the same OAuth URL Screener uses; finish sign-in there and cookies are saved automatically.

**Email/password auto-refresh** — add `email` + `password` under `[screener]` for silent refresh without opening a browser.

**Manual cookies** — paste `sessionid` + `csrftoken` from DevTools until they expire.

Or run: `python scripts/refresh_screener_session.py` (email/password) or `python scripts/screener_google_login.py` (Google)
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

    if has_login and valid and has_auto:
        st.success(success_message)
    elif has_login and valid:
        st.warning(
            "Session is **valid** but uses **manual cookies only** — they will expire. "
            "Use **Login with Google** or **Configure auto-login** so **Refresh session** "
            "works without DevTools."
        )
    elif has_login and not has_auto:
        st.warning(
            "Only **manual cookies** are set — they expire. Use **Login with Google** "
            "or add **email + password** for auto-refresh."
        )
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
        if not has_auto:
            st.error(
                "Cannot refresh automatically — use **Login with Google (Screener)** "
                "or add **email + password** in the expander below."
            )
        else:
            with st.spinner("Refreshing Screener.in session…"):
                result = ensure_screener_session(force=force, save=True)
            if result.ok:
                set_screener_cookie_override(result.cookies)
                clear_screener_feed_caches()
                st.toast(result.message, icon="✅")
                st.rerun()
            else:
                st.error(result.message)

    google_col, _ = st.columns([1, 2])
    with google_col:
        google_login = st.button(
            "🔐 Login with Google (Screener)",
            key=f"{key_prefix}_google_login",
            use_container_width=True,
            help="Opens a browser on screener.in/login/google/ — same as Screener's Google button.",
        )
    if google_login:
        if not playwright_available():
            st.error(
                "Playwright is not installed. Run in your terminal:\n\n"
                "```\n"
                "pip install playwright\n"
                "playwright install chromium\n"
                "```"
            )
        else:
            with st.spinner(
                "Browser opening — sign in with Google in the Chromium window. "
                "This page updates when cookies are captured (up to 5 min)…"
            ):
                try:
                    cookies, msg = save_screener_google_browser_login(timeout_sec=300)
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    set_screener_cookie_override(cookies)
                    clear_screener_feed_caches()
                    st.success(msg)
                    st.rerun()

    show_setup = expand_setup_when_invalid and (not has_login or not valid or not has_auto)
    with st.expander(
        "🔐 Login with Google or email/password",
        expanded=show_setup and not has_auto,
    ):
        st.markdown(_setup_markdown(extra_links=extra_setup_links))
        st.caption(
            "Google users: use the button above. Email/password users: form below "
            "(same credentials as screener.in email sign-in)."
        )
        with st.form(f"{key_prefix}_auto_login_form"):
            email_in = st.text_input(
                "Screener email",
                value=block.get("email", ""),
                placeholder="you@email.com",
            )
            pass_in = st.text_input(
                "Screener password",
                type="password",
                placeholder="Your screener.in password",
                help="Saved to gitignored secrets.toml on this machine only.",
            )
            submitted = st.form_submit_button("💾 Save & refresh session", type="primary")
        if submitted:
            with st.spinner("Logging in to Screener.in…"):
                result = save_screener_credentials_and_refresh(email_in, pass_in)
            if result.ok:
                set_screener_cookie_override(result.cookies)
                clear_screener_feed_caches()
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

    if has_auto and not show_setup:
        with st.expander("🔐 Screener.in login setup", expanded=False):
            st.markdown(_setup_markdown(extra_links=extra_setup_links))

    return valid
