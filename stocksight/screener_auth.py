"""
Screener.in session refresh — validate cookies and re-login when expired.

Requires ``email`` + ``password`` in ``[screener]`` (secrets.toml or env) to refresh
without manual DevTools copy. ``sessionid`` / ``csrftoken`` are written back to
``.streamlit/secrets.toml`` automatically.

Educational / personal use only — respect Screener.in terms of service.
"""

from __future__ import annotations

import http.cookiejar
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SCREENER_BASE = "https://www.screener.in"
SCREENER_LOGIN_URL = f"{SCREENER_BASE}/login/"
SCREENER_TEST_URL = f"{SCREENER_BASE}/full-text-search/?q=order&type=announcements"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; StockSight/1.0; +https://github.com/ZINGYRAJEEV/stocksight2)"
)
_TIMEOUT = 20

_AUTH_FAIL_MARKERS = (
    "Register - Screener",
    "Get a free account",
    "Login required",
    "Welcome back!",
)


@dataclass
class ScreenerAuthResult:
    ok: bool
    refreshed: bool
    message: str
    cookies: dict[str, str]


def _secrets_paths() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    return [
        root / ".streamlit" / "secrets.toml",
        Path(".streamlit") / "secrets.toml",
        Path("stocksight") / ".streamlit" / "secrets.toml",
    ]


def find_secrets_toml() -> Optional[Path]:
    for path in _secrets_paths():
        if path.is_file():
            return path
    return None


def _load_toml() -> dict:
    try:
        import tomllib
    except ImportError:
        return {}
    path = find_secrets_toml()
    if not path:
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_screener_block() -> dict[str, str]:
    """All [screener] keys from env + secrets.toml."""
    out: dict[str, str] = {}
    for key in ("email", "password", "sessionid", "csrftoken"):
        env = os.environ.get(f"SCREENER_{key.upper()}", "").strip()
        if env:
            out[key] = env
    block = _load_toml().get("screener") or {}
    if isinstance(block, dict):
        for key in ("email", "password", "sessionid", "csrftoken"):
            val = str(block.get(key, "") or "").strip()
            if val:
                out[key] = val
    return out


def is_screener_session_valid(cookies: Optional[dict[str, str]] = None) -> bool:
    """Return True if cookies unlock Screener full-text search (logged-in feed)."""
    creds = cookies or {}
    sid = (creds.get("sessionid") or "").strip()
    if not sid:
        return False
    try:
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Referer": SCREENER_BASE + "/",
            "Cookie": "; ".join(f"{k}={v}" for k, v in creds.items() if v),
        }
        req = urllib.request.Request(SCREENER_TEST_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return False
    if any(m in html for m in _AUTH_FAIL_MARKERS):
        return False
    return "overflow-wrap-anywhere" in html or "change-list" in html or "full-text" in html.lower()


def _cookie_dict_from_jar(jar: http.cookiejar.CookieJar) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in jar:
        if c.name in ("sessionid", "csrftoken") and c.value:
            out[c.name] = c.value
    return out


def login_screener(email: str, password: str) -> dict[str, str]:
    """
    POST to Screener login and return ``sessionid`` + ``csrftoken``.

    Raises ``RuntimeError`` on failure.
    """
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        raise RuntimeError("Screener email and password are required to refresh session.")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", _USER_AGENT)]

    with opener.open(SCREENER_LOGIN_URL, timeout=_TIMEOUT) as resp:
        html = resp.read().decode("utf-8", "replace")

    csrf_m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', html)
    if not csrf_m:
        raise RuntimeError("Could not parse csrfmiddlewaretoken from Screener login page.")

    csrftoken_cookie = _cookie_dict_from_jar(jar).get("csrftoken", "")
    payload = urllib.parse.urlencode({
        "csrfmiddlewaretoken": csrf_m.group(1),
        "username": email,
        "password": password,
        "next": "",
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": SCREENER_LOGIN_URL,
        "Origin": SCREENER_BASE,
    }
    if csrftoken_cookie:
        headers["X-CSRFToken"] = csrftoken_cookie

    req = urllib.request.Request(
        SCREENER_LOGIN_URL,
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        if "password" in body.lower() and "incorrect" in body.lower():
            raise RuntimeError("Screener login failed — check email/password.") from exc
        raise RuntimeError(f"Screener login HTTP {exc.code}") from exc

    cookies = _cookie_dict_from_jar(jar)
    if not cookies.get("sessionid"):
        raise RuntimeError(
            "Screener login did not return sessionid — verify email/password or 2FA status."
        )
    return cookies


def patch_secrets_toml(cookies: dict[str, str], *, path: Optional[Path] = None) -> Path:
    """Update sessionid/csrftoken in secrets.toml (preserves comments and other keys)."""
    target = path or find_secrets_toml()
    if not target or not target.is_file():
        raise FileNotFoundError(
            "No .streamlit/secrets.toml found — create one with [screener] email/password first."
        )

    text = target.read_text(encoding="utf-8")
    if "[screener]" not in text:
        text = text.rstrip() + "\n\n[screener]\n"

    for key in ("sessionid", "csrftoken"):
        val = (cookies.get(key) or "").strip()
        if not val:
            continue
        pat = re.compile(
            rf'^(\s*{re.escape(key)}\s*=\s*")[^"]*(")',
            re.MULTILINE,
        )
        if pat.search(text):
            text = pat.sub(rf"\1{val}\2", text, count=1)
        elif "[screener]" in text:
            text = re.sub(
                r"(\[screener\]\s*\n)",
                rf'\1{key} = "{val}"\n',
                text,
                count=1,
            )
        else:
            text += f'{key} = "{val}"\n'

    target.write_text(text, encoding="utf-8")
    return target


def ensure_screener_session(
    *,
    force: bool = False,
    save: bool = True,
    secrets_path: Optional[Path] = None,
) -> ScreenerAuthResult:
    """
    Validate cookies; re-login and patch secrets.toml when expired.

    Returns ``ScreenerAuthResult`` (``ok=False`` if email/password missing).
    """
    block = load_screener_block()
    cookies = {
        k: block[k]
        for k in ("sessionid", "csrftoken")
        if block.get(k)
    }
    email = block.get("email", "")
    password = block.get("password", "")

    if not force and cookies and is_screener_session_valid(cookies):
        return ScreenerAuthResult(
            ok=True,
            refreshed=False,
            message="Screener session is valid.",
            cookies=cookies,
        )

    if not email or not password:
        if cookies and not force:
            return ScreenerAuthResult(
                ok=False,
                refreshed=False,
                message=(
                    "Screener session expired or invalid. Add email + password under "
                    "[screener] in .streamlit/secrets.toml to enable auto-refresh."
                ),
                cookies=cookies,
            )
        return ScreenerAuthResult(
            ok=False,
            refreshed=False,
            message="Screener email/password not configured.",
            cookies=cookies,
        )

    try:
        new_cookies = login_screener(email, password)
    except RuntimeError as exc:
        return ScreenerAuthResult(
            ok=False,
            refreshed=False,
            message=str(exc),
            cookies=cookies,
        )

    if not is_screener_session_valid(new_cookies):
        return ScreenerAuthResult(
            ok=False,
            refreshed=False,
            message="Login succeeded but session still fails full-text check.",
            cookies=new_cookies,
        )

    saved_to = ""
    if save:
        try:
            saved_to = str(patch_secrets_toml(new_cookies, path=secrets_path))
        except FileNotFoundError as exc:
            return ScreenerAuthResult(
                ok=True,
                refreshed=True,
                message=f"Refreshed in memory only: {exc}",
                cookies=new_cookies,
            )

    msg = "Screener session refreshed."
    if saved_to:
        msg += f" Updated {saved_to}."
    return ScreenerAuthResult(
        ok=True,
        refreshed=True,
        message=msg,
        cookies=new_cookies,
    )
