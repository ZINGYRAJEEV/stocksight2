#!/usr/bin/env python3
"""
Refresh Screener.in sessionid + csrftoken when expired.

Usage:
  python scripts/refresh_screener_session.py          # refresh only if expired
  python scripts/refresh_screener_session.py --force  # always re-login
  python scripts/refresh_screener_session.py --check  # validate only, no login

Requires in .streamlit/secrets.toml (or environment variables):

  [screener]
  email = "your@email.com"
  password = "your-screener-password"
  sessionid = "..."   # updated automatically
  csrftoken = "..."   # updated automatically

Environment overrides: SCREENER_EMAIL, SCREENER_PASSWORD, SCREENER_SESSIONID, SCREENER_CSRFTOKEN

Schedule on Windows (daily before market open):
  schtasks /Create /TN "StockSight Screener Refresh" /TR ^
    "python C:\\path\\to\\stocksight2\\scripts\\refresh_screener_session.py" ^
    /SC DAILY /ST 08:45

Or run from StockSight repo root via Task Scheduler / cron.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_STOCKSIGHT = _REPO / "stocksight"
if str(_STOCKSIGHT) not in sys.path:
    sys.path.insert(0, str(_STOCKSIGHT))

from screener_auth import ensure_screener_session, is_screener_session_valid, load_screener_block  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Screener.in session cookies.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Always re-login even if current session appears valid.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check whether the current session is valid (exit 0=ok, 1=expired).",
    )
    args = parser.parse_args()

    block = load_screener_block()
    cookies = {k: block[k] for k in ("sessionid", "csrftoken") if block.get(k)}

    if args.check:
        if is_screener_session_valid(cookies):
            print("OK — Screener session is valid.")
            return 0
        print("EXPIRED — Screener session invalid or missing.")
        return 1

    result = ensure_screener_session(force=args.force, save=True)
    print(result.message)
    if result.ok:
        if result.refreshed:
            print(f"sessionid={result.cookies.get('sessionid', '')[:12]}…")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
