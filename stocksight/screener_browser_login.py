"""
Browser-based Screener.in login (Google OAuth).

Opens the same redirect as screener.in's "Sign in with Google" button,
waits for you to finish in the browser, then reads sessionid + csrftoken.

**Local only** — Streamlit Cloud cannot open a browser on your machine, so Google
login must be done on a desktop, then paste cookies into Cloud secrets.

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import os
import time
from typing import Optional

SCREENER_GOOGLE_LOGIN_URL = "https://www.screener.in/login/google/"


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def is_streamlit_cloud() -> bool:
    """True when running on Streamlit Community Cloud (or similar remote host)."""
    return bool(
        os.environ.get("STREAMLIT_SHARING_MODE")
        or os.environ.get("STREAMLIT_SERVER_HEADLESS") == "true"
        and (
            os.environ.get("HOSTNAME", "").endswith(".streamlit.app")
            or "streamlit" in os.environ.get("HOME", "").lower()
            or os.path.exists("/home/appuser")
        )
        or os.environ.get("USER", "") == "appuser"
        or os.path.isdir("/home/appuser")
    )


def chromium_installed() -> bool:
    if not playwright_available():
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            return bool(path and os.path.isfile(path))
    except Exception:
        return False


def google_browser_login_supported() -> tuple[bool, str]:
    """
    Whether interactive Google login can work in this environment.

    Returns (ok, reason_if_not).
    """
    if is_streamlit_cloud():
        return False, (
            "**Login with Google** only works on your **local PC** — Streamlit Cloud "
            "cannot open Chromium on your screen.\n\n"
            "**On Cloud, do this instead:**\n"
            "1. On your PC: `python scripts/screener_google_login.py` (or run StockSight locally "
            "and click Login with Google)\n"
            "2. Copy `sessionid` + `csrftoken` from local `.streamlit/secrets.toml`\n"
            "3. Paste them into **Streamlit Cloud → App settings → Secrets** under `[screener]`, "
            "or use **Paste cookies** below (works for this session)\n\n"
            "Or use Screener **email + password** in Cloud secrets if your account has password login."
        )
    if not playwright_available():
        return False, (
            "Playwright is not installed. On your PC run:\n"
            "```\npip install playwright\nplaywright install chromium\n```"
        )
    if not chromium_installed():
        return False, (
            "Playwright is installed but **Chromium** is missing. On your PC run:\n"
            "```\nplaywright install chromium\n```\n\n"
            "This cannot be fixed on Streamlit Cloud — use **Paste cookies** or Cloud Secrets."
        )
    return True, ""


def _playwright_install_hint() -> str:
    return (
        "Playwright is required for Google login. Run:\n"
        "  pip install playwright\n"
        "  playwright install chromium"
    )


def login_screener_via_google_browser(
    *,
    timeout_sec: int = 300,
    login_url: str = SCREENER_GOOGLE_LOGIN_URL,
) -> dict[str, str]:
    """
    Launch a visible Chromium window on Screener's Google login URL.

    Complete sign-in in the browser. Returns ``sessionid`` and ``csrftoken``
    when Screener sets them. Raises ``RuntimeError`` on timeout or missing deps.
    """
    ok, reason = google_browser_login_supported()
    if not ok:
        raise RuntimeError(reason)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(_playwright_install_hint()) from exc

    deadline = time.time() + max(30, timeout_sec)
    cookies: dict[str, str] = {}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False)
        except Exception as exc:
            msg = str(exc).lower()
            if "executable doesn't exist" in msg or "browser" in msg:
                raise RuntimeError(
                    "Chromium not installed for Playwright.\n\n"
                    "On your **local PC** run:\n"
                    "  playwright install chromium\n\n"
                    "On **Streamlit Cloud** this button cannot work — use **Paste cookies** "
                    "or put sessionid/csrftoken in Cloud Secrets.\n\n"
                    f"Original: {exc}"
                ) from exc
            raise

        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")

        while time.time() < deadline:
            for c in context.cookies():
                domain = c.get("domain", "")
                if "screener.in" not in domain:
                    continue
                name = c.get("name", "")
                value = (c.get("value") or "").strip()
                if name in ("sessionid", "csrftoken") and value:
                    cookies[name] = value
            if cookies.get("sessionid"):
                break
            time.sleep(0.4)

        browser.close()

    if not cookies.get("sessionid"):
        raise RuntimeError(
            "Timed out waiting for Screener login — complete Google sign-in in the "
            "browser window, or try again."
        )
    return cookies


def save_screener_google_browser_login(
    *,
    timeout_sec: int = 300,
    validate: bool = True,
) -> tuple[dict[str, str], str]:
    """
    Google browser login + optional validation.

    Returns (cookies, message). Raises ``RuntimeError`` on failure.
    """
    from screener_auth import is_screener_session_valid, try_patch_secrets_toml

    cookies = login_screener_via_google_browser(timeout_sec=timeout_sec)
    if validate and not is_screener_session_valid(cookies):
        raise RuntimeError(
            "Browser login returned cookies but Screener full-text check failed — "
            "try again or check your account."
        )

    saved = try_patch_secrets_toml(cookies)
    if saved:
        return cookies, f"Screener Google login OK. Cookies saved to {saved}."
    return (
        cookies,
        "Screener Google login OK (in-memory only — could not write secrets.toml). "
        "On Streamlit Cloud, paste sessionid/csrftoken into App Secrets for persistence.",
    )
