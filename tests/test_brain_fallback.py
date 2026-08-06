"""tests/test_brain_fallback.py — brain fallback logic: no LLM / network down."""
from unittest.mock import MagicMock

from commentator.brain import Commentator
from commentator.ai_provider import AIProvider


def _make_commentator(available: bool, generate_returns=None) -> Commentator:
    """Create Commentator with a mocked AIProvider."""
    ai = MagicMock(spec=AIProvider)
    ai.available = available
    ai.generate = MagicMock(return_value=generate_returns)
    return Commentator(ai, "tv")


# --- create() fallback ---

def test_create_uses_template_when_ai_unavailable():
    brain = _make_commentator(available=False)
    result = brain.create({"event_code": "OVTK", "driver": "VER", "target": "HAM"}, ai_ok=True)
    assert result != ""
    brain.ai.generate.assert_not_called()


def test_create_uses_template_when_ai_unhealthy():
    brain = _make_commentator(available=True, generate_returns="phrase")
    result = brain.create({"event_code": "OVTK", "driver": "VER", "target": "HAM"}, ai_ok=False)
    assert result != ""
    brain.ai.generate.assert_not_called()


def test_create_uses_llm_when_available_and_healthy():
    brain = _make_commentator(available=True, generate_returns="LLM phrase")
    result = brain.create({"event_code": "OVTK", "driver": "VER", "target": "HAM"}, ai_ok=True)
    assert result == "LLM phrase"


def test_create_falls_to_template_when_llm_returns_none():
    brain = _make_commentator(available=True, generate_returns=None)
    result = brain.create({"event_code": "OVTK", "driver": "VER", "target": "HAM"}, ai_ok=True)
    assert result != ""


def test_create_ambient_silent_when_llm_returns_empty():
    """LLM intentionally returns '' → respect silence, don't use ambient pool."""
    brain = _make_commentator(available=True, generate_returns="")
    result = brain.create_ambient("some context", ai_ok=True)
    assert result == ""


# --- create_ambient() fallback ---

def test_create_ambient_uses_template_when_unavailable():
    brain = _make_commentator(available=False)
    result = brain.create_ambient("context", ai_ok=True)
    assert result != ""


def test_create_ambient_uses_template_when_unhealthy():
    brain = _make_commentator(available=True, generate_returns="phrase")
    result = brain.create_ambient("context", ai_ok=False)
    assert result != ""


def test_create_ambient_template_covers_all_personas():
    brain = _make_commentator(available=False)
    for persona in ("tv", "hype", "calm", "toxic"):
        brain.persona = persona
        result = brain.create_ambient("", ai_ok=False)
        assert isinstance(result, str) and len(result) > 0
