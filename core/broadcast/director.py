"""
core/broadcast/director.py
===========================
BroadcastDirector: takes a race_ai event dict, calls YandexGPT with a structured
fact-only prompt, validates output, manages per-priority cooldowns and context dedup.

No AI reference stored — caller passes AIProvider at call time so credential
updates in engine.py are automatically reflected.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core.broadcast.models import BroadcastMessage
from core.broadcast.context import BroadcastContext
from core.broadcast.prompts import build_prompt
from core.broadcast.validator import validate

if TYPE_CHECKING:
    from commentator.ai_provider import AIProvider

# Minimum seconds between broadcasts of the same event type, by priority
_COOLDOWNS: dict[str, float] = {
    "high":   5.0,
    "medium": 15.0,
    "low":    20.0,
}


class BroadcastDirector:
    """Orchestrates LLM-rewrite of race_ai events into styled commentary."""

    def __init__(self, context: BroadcastContext | None = None):
        self._ctx = context or BroadcastContext()
        self._last_t: dict[str, float] = {}  # event_type → last voiced timestamp

    def reset_session(self) -> None:
        """Reset cooldown and phrase context at the start of a new race."""
        self._last_t.clear()
        self._ctx.clear()

    def generate(
        self,
        event_dict: dict,
        ai: "AIProvider",
        persona: str,
        ai_ok: bool,
    ) -> BroadcastMessage | None:
        """Return BroadcastMessage or None (caller falls back to engineer template).

        Flow: priority cooldown → build structured prompt → LLM → validate → record.
        """
        event_type = event_dict.get("race_ai_type", "")
        priority = event_dict.get("priority", "low")
        now = time.monotonic()

        cooldown = _COOLDOWNS.get(priority, 20.0)
        if now - self._last_t.get(event_type, 0.0) < cooldown:
            return None

        text: str | None = None

        if ai_ok and ai.available:
            prompt = build_prompt(event_dict, persona, self._ctx.recent_phrases())
            raw = ai.generate(prompt, persona)
            if raw:
                ok, _ = validate(raw, event_dict)
                if ok:
                    text = raw

        if not text:
            return None  # caller uses engineer.get_message() fallback

        self._last_t[event_type] = now
        self._ctx.add(event_type, text)
        return BroadcastMessage(
            text=text,
            style=persona,
            priority=priority,
            source="llm",
        )
