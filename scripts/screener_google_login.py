#!/usr/bin/env python3
"""
Sign in to Screener.in via Google OAuth in a local browser window.

Usage:
  python scripts/screener_google_login.py

Requires:
  pip install playwright
  playwright install chromium
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_STOCKSIGHT = _REPO / "stocksight"
if str(_STOCKSIGHT) not in sys.path:
    sys.path.insert(0, str(_STOCKSIGHT))

from screener_browser_login import (  # noqa: E402
    playwright_available,
    save_screener_google_browser_login,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Screener.in Google login — opens browser, saves cookies to secrets.toml.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for you to finish Google sign-in (default 300).",
    )
    args = parser.parse_args()

    if not playwright_available():
        print("ERROR: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    print("Opening browser on https://www.screener.in/login/google/ …")
    print("Complete Google sign-in in the Chromium window.")
    try:
        _cookies, msg = save_screener_google_browser_login(timeout_sec=args.timeout)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
