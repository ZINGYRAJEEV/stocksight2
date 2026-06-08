"""Claude validation layer — optional AI review of rule compliance."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional

from central_brain.config import CentralBrainConfig
from central_brain.validators import ValidationResult


def claude_validate_signal(
    cfg: CentralBrainConfig,
    *,
    payload: dict[str, Any],
    rules_result: ValidationResult,
    rules_excerpt: dict[str, Any],
) -> tuple[bool, str, Optional[dict]]:
    """
    Ask Claude to confirm or reject based on rules.json + indicator values.
    Falls back to rules_result when API key missing.
    """
    if not cfg.use_claude_validation or not cfg.anthropic_api_key:
        if rules_result.approved:
            return True, "Rule engine approved (Claude validation disabled or no API key).", None
        return False, rules_result.summary(), None

    system = (
        "You are the Central Brain trading intermediary. "
        "Validate TradingView signals against rules.json with 100% compliance. "
        "If ANY criterion fails, respond with approved=false and explicit reasoning. "
        "Respond ONLY with JSON: {\"approved\": bool, \"reasoning\": string}."
    )
    user_content = json.dumps(
        {
            "signal": payload,
            "rules": rules_excerpt,
            "rule_engine": {
                "approved": rules_result.approved,
                "reasons": rules_result.reasons,
                "checks": rules_result.checks,
            },
        },
        default=str,
    )

    body = {
        "model": cfg.claude_model,
        "max_tokens": 512,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": cfg.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = ""
        for block in raw.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        verdict = json.loads(text)
        approved = bool(verdict.get("approved"))
        reasoning = str(verdict.get("reasoning", ""))
        if not approved and not reasoning:
            reasoning = "Claude rejected signal."
        return approved, reasoning, verdict
    except Exception as exc:
        # Fail closed — defer to deterministic rules
        if rules_result.approved:
            return True, f"Claude unavailable ({exc}); rule engine approved.", None
        return False, f"Claude unavailable; {rules_result.summary()}", None
