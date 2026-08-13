"""Тест рации не уезжает в живой эфир.

Разбор заезда 2026-08-11: «Проверка радио. Голос работает, поехали!» прозвучала
посреди гонки четыре раза (15:09:05, 15:13:14, 15:13:37, 15:13:48 — две последние
подряд, разными голосами). Кнопка теста ставила фразу в ту же очередь, что и
споттер с инженером, и никакого запрета на это не было.

Отказ обязан быть НАБЛЮДАЕМЫМ: метод возвращает структурированный ответ, а UI
(dashboard.tsx / voice.tsx) его показывает — иначе кнопка молча ничего не делает.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


@pytest.fixture
def voice_ready(engine, monkeypatch):
    """Голос доступен и нем: в тестовой среде его нет, а нам нужен путь ПОСЛЕ
    проверки доступности. test_say глушим, чтобы тест не ходил в сеть."""
    monkeypatch.setattr(type(engine.voice), "is_available",
                        property(lambda self: True))
    monkeypatch.setattr(engine.voice, "test_say", lambda text: True)
    return engine


def test_voice_test_is_refused_during_an_active_session(voice_ready):
    voice_ready._session_active = True
    try:
        result = voice_ready.test_voice()
    finally:
        voice_ready._session_active = False

    assert result["ok"] is False
    # Причина, а не пустой отказ: пользователю нужно понять, почему кнопка молчит.
    assert "сесси" in (result.get("error") or "").lower()


def test_voice_test_is_allowed_outside_a_session(voice_ready):
    voice_ready._session_active = False
    assert voice_ready.test_voice()["ok"] is True


def test_unavailable_voice_is_reported_as_such_not_as_a_session(engine, monkeypatch):
    """Порядок проверок: сперва доступность движка, потом сессия. Один отказ не
    должен маскироваться другим — иначе пользователь чинит не то."""
    engine._session_active = True
    monkeypatch.setattr(type(engine.voice), "is_available",
                        property(lambda self: False))
    try:
        result = engine.test_voice()
    finally:
        engine._session_active = False

    assert result["ok"] is False
    assert "сесси" not in (result.get("error") or "").lower()
