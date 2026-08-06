"""core/broadcast/validator.py — hallucination guard for LLM output."""
from __future__ import annotations

MAX_WORDS = 30


def validate(text: str, event_dict: dict) -> tuple[bool, str]:
    """Return (valid, reason).

    Checks:
    1. Non-empty output.
    2. Length ≤ MAX_WORDS.
    3. Driver name present in output when it's a real (non-player) name.
    """
    if not text or not text.strip():
        return False, "empty"

    words = text.split()
    if len(words) > MAX_WORDS:
        return False, f"too_long:{len(words)}"

    driver = event_dict.get("driver", "")
    _skip = {"player", "оппонент", ""}
    if driver and driver.lower() not in _skip and driver not in text:
        return False, "driver_missing"

    return True, "ok"
