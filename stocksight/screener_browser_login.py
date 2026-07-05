"""
Browser-based Screener.in login (Google OAuth).

Opens the same redirect as screener.in's "Sign in with Google" button,
waits for you to finish in the browser, then reads sessionid + csrftoken.

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import time
from typing import Optional

SCREENER_GOOGLE_LOGIN_URL = "https://www.screener.in/login/google/"


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


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
    if not playwright_available():
        raise RuntimeError(_playwright_install_hint())

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
                    f"Chromium not installed for Playwright. Run:\n"
                    f"  playwright install chromium\n\nOriginal: {exc}"
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
    from screener_auth import is_screener_session_valid, patch_secrets_toml

    cookies = login_screener_via_google_browser(timeout_sec=timeout_sec)
    if validate and not is_screener_session_valid(cookies):
        raise RuntimeError(
            "Browser login returned cookies but Screener full-text check failed — "
            "try again or check your account."
        )

    saved = str(patch_secrets_toml(cookies))
    return cookies, f"Screener Google login OK. Cookies saved to {saved}."
