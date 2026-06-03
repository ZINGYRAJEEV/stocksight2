"""Console + optional email / webhook alerts."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional

from intrabot.config import ALERT_EMAIL, ALERT_WEBHOOK
from intrabot.store import log_event


def emit(
    state: dict[str, Any],
    event: str,
    message: str,
    *,
    level: str = "info",
    market: str = "",
    console: bool = True,
    **extra: Any,
) -> None:
    log_event(state, event, message, level=level, market=market, **extra)
    if console:
        tag = level.upper()
        mk = f"[{market}] " if market else ""
        print(f"[IntraBot] {tag} {mk}{event}: {message}")
    if ALERT_WEBHOOK and level in ("warn", "error", "trade"):
        _post_webhook({"event": event, "message": message, "level": level, "market": market, **extra})


def _post_webhook(payload: dict) -> None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            ALERT_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def notify_email(subject: str, body: str) -> None:
    if not ALERT_EMAIL:
        return
    # Placeholder — wire smtp or sendgrid if needed
    print(f"[IntraBot] EMAIL → {ALERT_EMAIL}: {subject}")
