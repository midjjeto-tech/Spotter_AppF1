import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_FORMAT, PACKET_EVENT


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None              # без Yandex/сети → фолбэк-история
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_generate_story_sets_state(engine):
    engine.settings["autovoice_enabled"] = False    # без TTS-побочек в тесте
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine.story_collector.note_event("OVTK", 10, driver="player", target="Албон")
    engine._player_pos = 4
    engine._generate_story(None)                     # синхронно (без потока)
    rs = engine.get_state().get("race_story")
    assert rs is not None and rs["text"]
    assert rs["final_position"] == 4


def test_generate_story_prefers_final_classification_position(engine):
    """Официальная позиция из Final Classification (packet 8) точнее live-
    снимка `_player_pos` из последнего LapData — предпочитается, если уже
    доступна к моменту генерации истории (best-effort, без ожидания —
    см. docs/superpowers/plans/2026-07-19-tyre-sets-final-classification.md)."""
    engine.settings["autovoice_enabled"] = False
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine.story_collector.note_event("OVTK", 10, driver="player", target="Албон")
    engine._player_pos = 4                            # live-снимок — устарел
    engine._final_classification = {"position": 2}     # официальный — точнее
    try:
        engine._generate_story(None)
        rs = engine.get_state().get("race_story")
        assert rs["final_position"] == 2
    finally:
        engine._final_classification = None


def test_generate_story_now_requires_data(engine):
    engine.recorder.reset()
    engine.story_collector.reset()
    assert engine.generate_story_now() is False      # нет кругов/старта → нечего рассказывать


def test_replay_returns_false_without_story(engine):
    engine._ui_state.set_race_story(None)
    assert engine.replay_story() is False


_CHQF_PACKET = struct.pack(HEADER_FORMAT, 2025, 25, 1, 0, 1, PACKET_EVENT,
                          12345, 0.0, 1, 1, 0, 255) + b"CHQF"


class _FakeTelemetry:
    """Stand-in for core.telemetry.Telemetry — yields exactly one packet then
    stops, so _telemetry_loop's `for data, connected in telemetry.listen()`
    processes one iteration and returns (no real UDP socket involved)."""

    def __init__(self, *_args, **_kwargs):
        pass

    def listen(self):
        yield _CHQF_PACKET, True


@pytest.mark.parametrize("session_type,should_fire", [
    ("race", True),
    ("qualifying", True),
    ("practice", True),
    ("sprint", False),
    ("unknown", False),
])
def test_chqf_auto_trigger_gated_by_session_type(engine, monkeypatch, session_type, should_fire):
    engine.settings["autovoice_enabled"] = False
    engine._session_type = session_type
    engine._story_fired = False
    # Each parametrized case models a separate source session even though the
    # compact fixture reuses the same synthetic UDP session UID and frame.
    engine._raw_event_seen.clear()
    engine._raw_event_source_seen.clear()
    engine._raw_event_source_session_id = None
    # Empty laps -> recorder.finalize() no-ops (no disk I/O), isolating this
    # test to the auto-trigger gate condition itself.
    engine.recorder.reset()
    monkeypatch.setattr(eng_mod, "Telemetry", _FakeTelemetry)
    engine._telemetry_loop()   # fake generator yields one packet then stops
    assert engine._story_fired is should_fire


def test_generate_story_includes_career_stats_in_context(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "1.json", {
        "track_id": 11, "session_type": "race", "final_position": 3,
        "timestamp": "2026-01-01T10:00:00",
    })
    engine.settings["autovoice_enabled"] = False
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine._player_pos = 4
    engine._generate_story(None)
    assert engine._career_stats_context_line is not None
    assert "Карьерная статистика" in engine._career_stats_context_line
    assert engine._career_stats_context_line in (engine.commentator.analytics_context or "")


def test_generate_story_excludes_career_stats_from_prompt_for_non_race_sessions(
        engine, tmp_path, monkeypatch):
    """Regression test: race_story.facts() already suppresses career_stats for
    qualifying/practice (Item 3), but _generate_story used to pass the SAME
    self.commentator.analytics_context (which also carries the career-stats
    context line) as gp_context into every story prompt regardless of
    session_type — a second channel that bypassed the facts-level gate.
    The engine-wide analytics_context itself must stay populated (Voice Q&A
    outside the story flow benefits from it for any session_type) — only the
    STORY's own prompt should omit it for non-race sessions."""
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "1.json", {
        "track_id": 11, "session_type": "race", "final_position": 3,
        "timestamp": "2026-01-01T10:00:00",
    })
    engine.settings["autovoice_enabled"] = False
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine._player_pos = 4
    engine._session_type = "qualifying"

    captured = {}

    class _FakeAI:
        available = True

        def generate(self, prompt, persona):
            captured["prompt"] = prompt
            return "итог квалификации"

    orig_ai = engine.ai
    engine.ai = _FakeAI()
    try:
        engine._generate_story(None)
    finally:
        engine.ai = orig_ai
        engine._session_type = "race"   # don't leak into later tests

    # Still computed/tracked engine-wide (Voice Q&A benefits regardless of session_type)
    assert engine._career_stats_context_line is not None
    assert engine._career_stats_context_line in (engine.commentator.analytics_context or "")
    # But NOT leaked into the story prompt itself for a non-race session
    assert "Карьерная статистика" not in captured["prompt"]


def test_race_story_state_carries_text_source(engine):
    """Без источника UI не может отличить шаблонный итог от написанного
    моделью — в тестовом окружении ai.available=False, значит "fallback"."""
    engine.settings["autovoice_enabled"] = False
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine._player_pos = 4
    engine._generate_story(None)
    assert engine.get_state()["race_story"]["source"] == "fallback"
