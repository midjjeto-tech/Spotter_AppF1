"""Tests for core/broadcast/ — Broadcast Director Layer."""
from __future__ import annotations

import time
import pytest

# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------
from core.broadcast.models import BroadcastMessage


def test_broadcast_message_dataclass():
    msg = BroadcastMessage(text="Sainz атакует!", style="tv", priority="high", source="llm")
    assert msg.text == "Sainz атакует!"
    assert msg.style == "tv"
    assert msg.priority == "high"
    assert msg.source == "llm"


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------
from core.broadcast.context import BroadcastContext


def test_context_was_recent_true():
    ctx = BroadcastContext()
    ctx.add("attack", "Sainz атакует!")
    assert ctx.was_recent("attack", seconds=5.0) is True


def test_context_was_recent_false_wrong_type():
    ctx = BroadcastContext()
    ctx.add("attack", "Sainz атакует!")
    assert ctx.was_recent("battle", seconds=5.0) is False


def test_context_recent_phrases_limit():
    ctx = BroadcastContext(maxlen=10)
    for i in range(8):
        ctx.add("attack", f"phrase {i}")
    phrases = ctx.recent_phrases(n=5)
    assert len(phrases) == 5
    assert phrases[-1] == "phrase 7"


def test_context_deque_maxlen():
    ctx = BroadcastContext(maxlen=3)
    for i in range(5):
        ctx.add("attack", f"p{i}")
    # maxlen=3 keeps last 3
    assert len(ctx.recent_phrases(n=10)) == 3


def test_context_clear_starts_new_race_clean():
    ctx = BroadcastContext()
    ctx.add("attack", "Sainz атакует!")

    ctx.clear()

    assert ctx.recent_phrases() == []


# ---------------------------------------------------------------------------
# prompts.py
# ---------------------------------------------------------------------------
from core.broadcast.prompts import build_prompt, _format_facts


def test_build_prompt_contains_driver():
    event = {
        "race_ai_type": "attack",
        "driver": "Sainz",
        "priority": "high",
        "race_ai_data": {"gap": 0.8, "drs": True, "confidence": 0.9},
    }
    prompt = build_prompt(event, "tv", [])
    assert "Sainz" in prompt


def test_build_prompt_contains_facts():
    event = {
        "race_ai_type": "attack",
        "driver": "Norris",
        "priority": "high",
        "race_ai_data": {"gap": 0.7, "drs": True},
    }
    prompt = build_prompt(event, "calm", [])
    assert "0.7" in prompt
    assert "DRS" in prompt


def test_build_prompt_avoids_recent():
    event = {"race_ai_type": "attack", "driver": "Max", "priority": "high", "race_ai_data": {}}
    recent = ["Max атакует, держись!", "Он давит сзади."]
    prompt = build_prompt(event, "hype", recent)
    assert "Max атакует, держись!" in prompt


def test_build_prompt_keeps_five_recent_delivery_patterns():
    recent = [f"Фраза {i}" for i in range(6)]

    prompt = build_prompt(_attack_event(), "tv", recent)

    assert "Фраза 0" not in prompt
    assert "Фраза 1" in prompt
    assert "Фраза 5" in prompt
    assert "синтаксис или ритм" in prompt


# ---------------------------------------------------------------------------
# validator.py
# ---------------------------------------------------------------------------
from core.broadcast.validator import validate


def test_validate_empty_fails():
    ok, reason = validate("", {"driver": "Sainz"})
    assert ok is False
    assert reason == "empty"


def test_validate_too_long_fails():
    long_text = " ".join(["слово"] * 35)
    ok, reason = validate(long_text, {})
    assert ok is False
    assert "too_long" in reason


def test_validate_ok():
    ok, reason = validate("Sainz атакует! DRS активен, защищайся.", {"driver": "Sainz"})
    assert ok is True
    assert reason == "ok"


def test_validate_driver_missing_soft_fail():
    ok, reason = validate("Атака продолжается!", {"driver": "Norris"})
    assert ok is False
    assert reason == "driver_missing"


def test_validate_player_driver_skips_check():
    # driver="player" should not trigger driver_missing
    ok, reason = validate("Держи позицию!", {"driver": "player"})
    assert ok is True


# ---------------------------------------------------------------------------
# director.py
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock
from core.broadcast.director import BroadcastDirector, _COOLDOWNS


def _make_ai(response: str | None = "Sainz атакует! DRS активен."):
    ai = MagicMock()
    ai.available = response is not None
    ai.generate.return_value = response
    return ai


def _attack_event():
    return {
        "race_ai_type": "attack",
        "driver": "Sainz",
        "priority": "high",
        "race_ai_data": {"gap": 0.8, "drs": True, "confidence": 0.9},
    }


def test_director_generates_message():
    d = BroadcastDirector()
    ai = _make_ai("Sainz атакует! DRS активен.")
    msg = d.generate(_attack_event(), ai, "tv", ai_ok=True)
    assert msg is not None
    assert "Sainz" in msg.text
    assert msg.source == "llm"


def test_director_cooldown_blocks():
    d = BroadcastDirector()
    ai = _make_ai("Sainz атакует!")
    d.generate(_attack_event(), ai, "tv", ai_ok=True)      # first — OK
    msg2 = d.generate(_attack_event(), ai, "tv", ai_ok=True)  # within cooldown
    assert msg2 is None


def test_director_fallback_on_ai_failure():
    d = BroadcastDirector()
    ai = _make_ai(None)  # AI unavailable
    msg = d.generate(_attack_event(), ai, "tv", ai_ok=True)
    assert msg is None   # caller must use engineer template


def test_director_fallback_when_ai_ok_false():
    d = BroadcastDirector()
    ai = _make_ai("Sainz атакует!")
    msg = d.generate(_attack_event(), ai, "tv", ai_ok=False)
    assert msg is None


def test_director_records_context():
    d = BroadcastDirector()
    ai = _make_ai("Sainz атакует! DRS активен.")
    d.generate(_attack_event(), ai, "tv", ai_ok=True)
    phrases = d._ctx.recent_phrases()
    assert len(phrases) == 1
    assert "Sainz" in phrases[0]


def test_director_reset_session_clears_context_and_cooldowns():
    d = BroadcastDirector()
    ai = _make_ai("Sainz атакует! DRS активен.")
    d.generate(_attack_event(), ai, "tv", ai_ok=True)

    d.reset_session()

    assert d._ctx.recent_phrases() == []
    assert d._last_t == {}
