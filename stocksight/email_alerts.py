"""
SMTP email alerts for StockSight (watchlist rule hits after a scan).

Configuration (pick one):

1) Streamlit secrets — `.streamlit/secrets.toml`:

    [smtp]
    host = "smtp.gmail.com"
    port = 587
    username = "you@gmail.com"
    password = "your-app-password"
    from_address = "you@gmail.com"
    to_addresses = ["you@gmail.com"]   # or a single string

2) Environment variables:

    STOCKSIGHT_SMTP_HOST
    STOCKSIGHT_SMTP_PORT   (default 587)
    STOCKSIGHT_SMTP_USER
    STOCKSIGHT_SMTP_PASSWORD
    STOCKSIGHT_SMTP_FROM
    STOCKSIGHT_SMTP_TO     (comma-separated)

Uses STARTTLS on port 587 (default). Set port 465 only if your provider requires implicit SSL (not implemented here).
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Optional


def _smtp_from_streamlit_secrets() -> Optional[dict[str, Any]]:
    try:
        import streamlit as st  # type: ignore

        sec = getattr(st, "secrets", None)
        if sec is None or "smtp" not in sec:
            return None
        sm = dict(sec["smtp"])
        host = sm.get("host")
        if not host:
            return None
        port = int(sm.get("port") or 587)
        user = sm.get("username") or sm.get("user")
        password = sm.get("password")
        from_addr = sm.get("from_address") or sm.get("from") or user
        to_raw = sm.get("to_addresses") or sm.get("to") or user
        if isinstance(to_raw, str):
            to_list = [x.strip() for x in to_raw.split(",") if x.strip()]
        elif isinstance(to_raw, (list, tuple)):
            to_list = [str(x).strip() for x in to_raw if str(x).strip()]
        else:
            to_list = []
        if not from_addr or not to_list:
            return None
        return {
            "host": str(host),
            "port": port,
            "user": str(user) if user else "",
            "password": str(password) if password else "",
            "from_address": str(from_addr),
            "to_addresses": to_list,
        }
    except Exception:
        return None


def _smtp_from_environ() -> Optional[dict[str, Any]]:
    host = os.environ.get("STOCKSIGHT_SMTP_HOST") or os.environ.get("SMTP_HOST")
    if not host:
        return None
    port = int(os.environ.get("STOCKSIGHT_SMTP_PORT") or os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("STOCKSIGHT_SMTP_USER") or os.environ.get("SMTP_USER") or ""
    password = os.environ.get("STOCKSIGHT_SMTP_PASSWORD") or os.environ.get("SMTP_PASSWORD") or ""
    from_addr = os.environ.get("STOCKSIGHT_SMTP_FROM") or os.environ.get("SMTP_FROM") or user
    to_raw = os.environ.get("STOCKSIGHT_SMTP_TO") or os.environ.get("SMTP_TO") or ""
    to_list = [x.strip() for x in str(to_raw).split(",") if x.strip()]
    if not from_addr or not to_list:
        return None
    return {
        "host": str(host),
        "port": port,
        "user": str(user),
        "password": str(password),
        "from_address": str(from_addr),
        "to_addresses": to_list,
    }


def resolve_smtp_settings() -> Optional[dict[str, Any]]:
    """Return SMTP dict or None if not configured."""
    return _smtp_from_streamlit_secrets() or _smtp_from_environ()


def send_plain_email(*, subject: str, body: str, smtp: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    """Send a plain-text email. Returns (ok, error_message)."""
    cfg = smtp or resolve_smtp_settings()
    if not cfg:
        return False, "SMTP is not configured (secrets.toml [smtp] or env vars)."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = ", ".join(cfg["to_addresses"])
    msg.set_content(body)

    host = cfg["host"]
    port = int(cfg["port"])
    user = cfg.get("user") or ""
    password = cfg.get("password") or ""

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=25) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            if user:
                server.login(user, password)
            server.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)


def send_watchlist_alert_email(page_hint: str, lines: list[str]) -> tuple[bool, str]:
    """Email watchlist alert bullet lines."""
    title = (page_hint or "StockSight").strip()
    subj = f"[StockSight] Watchlist alerts — {title}"
    body = (
        f"Scan context: {title}\n\n"
        "The following watchlist alert rules matched at least one hit in this scan:\n\n"
        + "\n".join(f"- {x}" for x in lines)
        + "\n\n— Sent automatically by StockSight (educational tooling)."
    )
    return send_plain_email(subject=subj, body=body)


def send_test_email() -> tuple[bool, str]:
    """Simple connectivity check."""
    return send_plain_email(
        subject="[StockSight] Test email",
        body="StockSight SMTP test — if you received this, outbound mail is configured correctly.",
    )
