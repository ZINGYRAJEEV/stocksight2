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
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SCREENER_BASE = "https://www.screener.in"
SCREENER_LOGIN_URL = f"{SCREENER_BASE}/login/"
SCREENER_GOOGLE_LOGIN_URL = f"{SCREENER_BASE}/login/google/"
SCREENER_TEST_URL = f"{SCREENER_BASE}/full-text-search/?q=order&type=announcements"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_LOGIN_UA = _USER_AGENT
_TIMEOUT = 20
_SESSION_VALID_CACHE_TTL_SEC = 180.0
_session_valid_cache: dict[str, tuple[float, bool]] = {}

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

    cache_key = sid[:16]
    now = time.time()
    hit = _session_valid_cache.get(cache_key)
    if hit and (now - hit[0]) < _SESSION_VALID_CACHE_TTL_SEC:
        return hit[1]

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
        _session_valid_cache[cache_key] = (now, False)
        return False
    if any(m in html for m in _AUTH_FAIL_MARKERS):
        _session_valid_cache[cache_key] = (now, False)
        return False
    ok = "overflow-wrap-anywhere" in html or "change-list" in html or "full-text" in html.lower()
    _session_valid_cache[cache_key] = (now, ok)
    return ok


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
    opener.addheaders = [("User-Agent", _LOGIN_UA)]

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
            "Screener login did not return sessionid. "
            "Use email/password login (not Google-only). Check credentials or disable 2FA."
        )
    return cookies


def _toml_quote(val: str) -> str:
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _set_toml_key(text: str, key: str, val: str) -> str:
    """Insert or replace one key under [screener] (or append section)."""
    val = (val or "").strip()
    if not val:
        return text
    line = f"{key} = {_toml_quote(val)}"
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=\s*.+$", re.MULTILINE)
    if pat.search(text):
        return pat.sub(line, text, count=1)
    if "[screener]" in text:
        return re.sub(r"(\[screener\]\s*\n)", rf"\1{line}\n", text, count=1)
    return text.rstrip() + f"\n\n[screener]\n{line}\n"


def patch_secrets_toml(
    cookies: dict[str, str],
    *,
    path: Optional[Path] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> Path:
    """Update [screener] keys in secrets.toml (preserves comments and other sections)."""
    target = path or find_secrets_toml()
    if not target or not target.is_file():
        raise FileNotFoundError(
            "No .streamlit/secrets.toml found — create one with a [screener] section first."
        )

    text = target.read_text(encoding="utf-8")
    if "[screener]" not in text:
        text = text.rstrip() + "\n\n[screener]\n"

    if email is not None and email.strip():
        text = _set_toml_key(text, "email", email.strip())
    if password is not None and password.strip():
        text = _set_toml_key(text, "password", password)

    for key in ("sessionid", "csrftoken"):
        val = (cookies.get(key) or "").strip()
        if val:
            text = _set_toml_key(text, key, val)

    target.write_text(text, encoding="utf-8")
    return target


def save_screener_credentials_and_refresh(
    email: str,
    password: str,
    *,
    force: bool = True,
) -> ScreenerAuthResult:
    """Save email/password to secrets.toml, login, and write fresh cookies."""
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        return ScreenerAuthResult(
            ok=False,
            refreshed=False,
            message="Email and password are required.",
            cookies={},
        )
    try:
        patch_secrets_toml({}, email=email, password=password)
    except FileNotFoundError as exc:
        return ScreenerAuthResult(ok=False, refreshed=False, message=str(exc), cookies={})

    try:
        new_cookies = login_screener(email, password)
    except RuntimeError as exc:
        return ScreenerAuthResult(ok=False, refreshed=False, message=str(exc), cookies={})

    if not is_screener_session_valid(new_cookies):
        return ScreenerAuthResult(
            ok=False,
            refreshed=False,
            message=(
                "Login returned cookies but full-text check failed — "
                "wrong password, Google-only account, or Screener blocked the request."
            ),
            cookies=new_cookies,
        )

    try:
        saved = str(patch_secrets_toml(new_cookies, email=email, password=password))
    except FileNotFoundError as exc:
        return ScreenerAuthResult(
            ok=True,
            refreshed=True,
            message=f"Logged in but could not save cookies: {exc}",
            cookies=new_cookies,
        )

    _session_valid_cache.clear()
    return ScreenerAuthResult(
        ok=True,
        refreshed=True,
        message=f"Screener auto-login configured. Cookies saved to {saved}.",
        cookies=new_cookies,
    )


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
                    "[screener] in .streamlit/secrets.toml, or use Login with Google "
                    "in the app to capture fresh cookies."
                ),
                cookies=cookies,
            )
        return ScreenerAuthResult(
            ok=False,
            refreshed=False,
            message=(
                "Auto-refresh needs Screener **email + password** in secrets.toml "
                "(not just sessionid/csrftoken). Use **Login with Google** or "
                "**Configure auto-login** below."
            ),
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
