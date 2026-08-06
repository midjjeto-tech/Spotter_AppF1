import pytest

from voice.tts import Voice


@pytest.fixture(scope="module")
def speaker_voice():
    """Один Voice на модуль для проверок active_speaker (не плодим загрузку Piper)."""
    return Voice()


def test_voice_key_yandex_when_available():
    v = Voice()
    v._yandex = object()                 # имитируем наличие Yandex-источника
    v._current_persona = "tv"
    v._voice_overrides = {}
    key = v._voice_key("tv")
    assert key.startswith("y:")
    assert "alexander" in key and "neutral" in key


def test_voice_key_changes_with_override():
    v = Voice()
    v._yandex = object()
    v._voice_overrides = {"tv": {"voice": "jane"}}
    assert "jane" in v._voice_key("tv")


def test_voice_key_depends_on_tts_version():
    """v1 и v3 рендерят один голос по-разному — кэш не должен смешиваться."""
    v = Voice()
    v._voice_overrides = {}

    class FakeSpeech:
        tts_version = "v1"

    y = FakeSpeech()
    v._yandex = y
    key_v1 = v._voice_key("tv")
    y.tts_version = "v3"
    key_v3 = v._voice_key("tv")
    assert key_v1 != key_v3
    assert "v1" in key_v1 and "v3" in key_v3


def test_voice_key_without_version_attr_defaults_v1():
    """Голый объект без tts_version (старые фейки/тесты) не должен ронять ключ."""
    v = Voice()
    v._yandex = object()
    v._voice_overrides = {}
    assert v._voice_key("tv").startswith("y:v1:")


def test_voice_key_piper_when_no_yandex():
    v = Voice()
    v._yandex = None
    assert v._voice_key("tv") == "piper:tv"


def test_pronunciation_change_invalidates_old_audio_cache():
    v = Voice()
    assert v._cache.version == "yandex-v6"


def test_set_yandex_enables_availability_and_queue():
    """Yandex должен работать независимо от загрузки Piper: set_yandex
    включает is_available и сразу создаёт очередь воспроизведения."""
    v = Voice()

    class FakeSpeech:
        def synthesize(self, text, persona, speed_scale=1.0):
            return None, 48000

        def set_overrides(self, overrides):
            pass

    v.set_yandex(FakeSpeech())
    try:
        assert v.is_available is True
        assert v.engine_name == "Yandex SpeechKit"
        assert v._queue is not None
    finally:
        if v._queue is not None:
            v._queue.stop()


# ---- active_speaker: имя реального спикера для плашки UI (баг №3) ---- #

def test_active_speaker_yandex_label(speaker_voice):
    v = speaker_voice
    v._yandex = object()
    v._yandex_healthy = True
    v._current_persona = "tv"
    v._voice_overrides = {}
    v._last_engine = "Yandex SpeechKit"
    assert v.active_speaker == "Яндекс: Александр"


def test_active_speaker_yandex_override(speaker_voice):
    v = speaker_voice
    v._yandex = object()
    v._yandex_healthy = True
    v._current_persona = "tv"
    v._voice_overrides = {"tv": {"voice": "jane"}}
    v._last_engine = "Yandex SpeechKit"
    assert v.active_speaker == "Яндекс: Джейн"


def test_active_speaker_piper_label(speaker_voice):
    v = speaker_voice
    v._yandex = None
    v._current_persona = "tv"
    v._voice_overrides = {}
    v._last_engine = "Piper (RU)"
    assert v.active_speaker == "Piper: Ruslan"


# ---- circuit breaker: _synthesize не ходит в Yandex, пока он помечен упавшим (баг №2) ---- #

def test_synthesize_skips_yandex_when_unhealthy_and_resumes():
    v = Voice()
    calls = {"yandex": 0}

    class FakeY:
        def synthesize(self, text, persona, speed_scale=1.0):
            calls["yandex"] += 1
            return ([0.1, 0.2], 48000)

        def set_overrides(self, o):
            pass

    class FakeEngine:
        is_ready = True
        sample_rate = 22050
        status = "fake"

        def synthesize(self, text, persona, speed_scale=1.0):
            return ([0.0], 22050)

    v._yandex = FakeY()
    v._engine = FakeEngine()

    # упал -> сразу Piper, Yandex не дёргаем (нет таймаут-штрафа)
    v._yandex_healthy = False
    v._synthesize("привет", "tv")
    assert calls["yandex"] == 0
    assert v._last_engine == "Piper (RU)"
    assert v._last_fallback is True          # прицеплен, но сейчас на Piper

    # восстановился -> следующая фраза снова на Yandex
    v._yandex_healthy = True
    v._synthesize("привет", "tv")
    assert calls["yandex"] == 1
    assert v._last_engine == "Yandex SpeechKit"
    assert v._last_fallback is False
