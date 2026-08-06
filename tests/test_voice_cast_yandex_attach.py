"""Каст должен пережить ПОДКЛЮЧЕНИЕ Yandex, а не только пересчёт настроек.

Ловушка, из-за которой этот файл существует. `YandexSpeech` держит оверрайды
голосов у себя (`_overrides`) отдельно от `Voice._voice_overrides`, а
синхронизирует их только `Voice.set_voice_overrides()` — и лишь если Yandex
прицеплен в тот момент. При старте порядок обратный: каст считается в
`F1Engine.__init__`, когда Yandex ещё None, а источник синтеза появляется
позже, в `F1Engine._start_yandex()`.

Пока `set_yandex()` не переносил оверрайды сам, новый клиент уходил в синтез
пустым и резолвил слоты ролей по голым каталожным дефолтам
(`voices.DEFAULT_PERSONA_VOICE["engineer"/"spotter"]`). Итог: при persona=tv и
toxic инженер получал голос комментатора — то есть ровно та коллизия, ради
запрета которой существует `core/radio/voice_cast.py`.

Почему это не ловили прежние тесты: все они читают `Voice._voice_overrides`
(он всегда корректен) и ни один не проверяет, что уехало в сам источник
синтеза. Поэтому здесь проверяется именно объект Yandex, а не `Voice`.
"""
import itertools

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import voice_cast
from yandex_ai import voices


ALL_PERSONAS = tuple(
    p for p in voices.DEFAULT_PERSONA_VOICE
    if p not in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER)
)


class _FakeSpeech:
    """Двойник `YandexSpeech` ровно в той части, которой пользуется `Voice`."""

    tts_version = "v3"

    def __init__(self) -> None:
        self._overrides: dict = {}

    def set_overrides(self, overrides: dict) -> None:
        self._overrides = overrides


@pytest.fixture
def engine_factory(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    return F1Engine


def test_attaching_yandex_carries_the_cast_into_the_speech_client(engine_factory):
    engine = engine_factory({"persona": "tv", "engineer_character": "volkov"})
    speech = _FakeSpeech()

    engine.voice.set_yandex(speech)

    assert speech._overrides, "оверрайды не доехали до клиента синтеза"
    assert (speech._overrides[voice_cast.SLOT_ENGINEER]
            == engine.voice._voice_overrides[voice_cast.SLOT_ENGINEER])


@pytest.mark.parametrize("persona,character",
                         list(itertools.product(ALL_PERSONAS, voice_cast.CHARACTERS)))
def test_roles_never_share_a_voice_in_what_reaches_the_synthesizer(
        engine_factory, persona, character):
    """Инвариант проверяется на том, что РЕАЛЬНО уедет в SpeechKit.

    Прежняя проверка смотрела на `voice_cast.resolve()` — чистую функцию,
    которая всегда была права. Ошибка жила на участке между ней и синтезом.
    """
    engine = engine_factory({"persona": persona, "engineer_character": character})
    speech = _FakeSpeech()
    engine.voice.set_yandex(speech)

    sent = speech._overrides
    voiced = {
        voices.resolve(persona, sent)["voice"],
        voices.resolve(voice_cast.SLOT_ENGINEER, sent)["voice"],
        voices.resolve(voice_cast.SLOT_SPOTTER, sent)["voice"],
    }
    assert len(voiced) == 3, f"совпали голоса: {sorted(voiced)}"


def test_reattaching_a_new_client_carries_the_cast_again(engine_factory):
    """Переподключение (ручной ввод ключа поверх работающего) ставит НОВЫЙ
    объект синтеза — оверрайды прежнего ему не достаются."""
    engine = engine_factory({"persona": "toxic", "engineer_character": "grom"})
    engine.voice.set_yandex(_FakeSpeech())

    second = _FakeSpeech()
    engine.voice.set_yandex(second)

    assert second._overrides[voice_cast.SLOT_ENGINEER]["voice"] == "anton"


def test_settings_change_after_attach_still_reaches_the_client(engine_factory):
    """Обратный порядок — сначала клиент, потом смена настроек. Этот путь
    работал и раньше (`set_voice_overrides` синхронизирует прицепленный
    Yandex), но он обязан продолжать работать после правки `set_yandex`."""
    engine = engine_factory({"persona": "calm", "engineer_character": "volkov"})
    speech = _FakeSpeech()
    engine.voice.set_yandex(speech)

    engine.apply_settings({"engineer_character": "grom"})

    assert speech._overrides[voice_cast.SLOT_ENGINEER]["voice"] == "anton"
