"""Эффект рации применяется поканально — проверка на путях воспроизведения.

Тест на сам `_radio_for()` не доказывает, что пути его зовут: откат любой из
двух точек применения (`_play_streaming`, `_play_wav`) прошёл бы мимо него.
Здесь перехватывается `voice.radio_fx.bandpass` — если его не позвали, значит
реплика прозвучала чистым эфиром.

Мокаем `sounddevice.OutputStream` тем же приёмом, что и
tests/test_tts_playback_stream.py (fake-модуль в sys.modules, без реального
звукового устройства).
"""
import sys
import threading
import types

import numpy as np
import pytest
import soundfile as sf

from core.radio import voice_cast
from voice import radio_fx


class FakeOutputStream:
    """Минимальная замена sounddevice.OutputStream — только то, что читают
    _play_streaming/_play_wav (start/write/stop/close, плюс abort на случай
    прерывания)."""

    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False
        self.closed = False
        self.aborted = False
        self.written = []

    def start(self):
        self.started = True

    def write(self, data):
        self.written.append(data)

    def stop(self):
        self.stopped = True

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_sd(monkeypatch):
    module = types.ModuleType("sounddevice")
    module.OutputStream = FakeOutputStream
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


@pytest.fixture()
def bandpass_calls(monkeypatch):
    """Перехватывает voice.radio_fx.bandpass, считая вызовы вместо того, чтобы
    реально фильтровать звук.

    radio_fx.squelch() тоже вызывает bandpass() внутри себя (см.
    voice/radio_fx.py) — это не мешает проверке: squelch звучит только когда
    рация уже включена (оба места вызова в tts.py стоят под `if radio:` /
    `if self._radio_for(persona):`), так что рост счётчика по-прежнему
    однозначно означает «эффект применён», откуда бы вызов ни пришёл.
    """
    calls: list[int] = []

    def fake_bandpass(audio, sr, drive=1.6):
        calls.append(len(np.asarray(audio)))
        return np.asarray(audio, dtype=np.float32)

    monkeypatch.setattr(radio_fx, "bandpass", fake_bandpass)
    return calls


@pytest.fixture()
def start_beep_calls(monkeypatch):
    calls: list[int] = []

    def fake_start_beep(sr, ms=110.0, level=0.18):
        calls.append(sr)
        return np.full(4, 0.05, dtype=np.float32)

    monkeypatch.setattr(radio_fx, "start_beep", fake_start_beep)
    return calls


def _make_voice(cache_dir=None):
    """Voice с патченным I/O — тот же приём, что _make_voice в
    test_tts_playback_stream.py. Радио включено по умолчанию (в отличие от
    того файла): весь смысл этого файла — проверить путь С рацией."""
    from unittest.mock import patch
    from voice.cache import TTSCache
    from voice.tts import Voice
    with (
        patch("voice.tts.TTSQueue"),
        patch("voice.tts.PiperVoiceEngine"),
        patch("voice.tts.TTSCache"),
        patch("threading.Thread"),
    ):
        v = Voice.__new__(Voice)
        v._stream_lock = threading.Lock()
        v._current_stream = None
        v._playback_interrupt = threading.Event()
        v._portaudio_lock = threading.Lock()
        v._stop_event = threading.Event()
        v._radio_enabled = True
        v._global_vol = 100
        v._persona_vol = {}
        v._current_persona = "tv"
        v._yandex = None
        v._yandex_healthy = True
        v._voice_overrides = {}
        v._health_reporter = None
        v._last_engine = ""
        v._last_fallback = False
        v.status_message = ""
        v._engine = types.SimpleNamespace(
            sample_rate=22050,
            synthesize_streaming=lambda text, persona: iter(()))
        v._cache = TTSCache(str(cache_dir), version="test") if cache_dir else None
        return v


class _FakeYandexStream:
    """Двухчанковый успешный стрим v3-grpc — минимум, нужный _play_streaming
    (тот же приём, что _FakeYandexStreamOK в test_tts_playback_stream.py)."""
    tts_version = "v3-grpc"

    def synthesize_streaming(self, text, persona, speed_scale=1.0):
        yield np.array([0.1, 0.2], dtype=np.float32), 22050
        yield np.array([0.3, 0.4], dtype=np.float32), 22050


# ---------------------------------------------------------------------------
# Путь 1: _play_streaming (Yandex v3-grpc, чанки на лету)
# ---------------------------------------------------------------------------

def test_play_streaming_applies_radio_to_engineer_not_commentator(
        fake_sd, bandpass_calls, start_beep_calls, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStream()

    ok = v._play_streaming("привет", voice_cast.SLOT_ENGINEER)
    assert ok is True
    assert len(bandpass_calls) > 0, "инженер должен звучать через рацию"
    assert len(start_beep_calls) == 1
    assert start_beep_calls[0] > 0

    bandpass_calls.clear()
    start_beep_calls.clear()
    ok = v._play_streaming("привет", "tv")
    assert ok is True
    assert bandpass_calls == [], "комментатор должен звучать чистым эфиром"
    assert start_beep_calls == []


# ---------------------------------------------------------------------------
# Путь 2: _play_wav (кэшированный «сухой» WAV, эффект накладывается на лету)
# ---------------------------------------------------------------------------

def test_play_wav_applies_radio_to_spotter_not_commentator(
        fake_sd, bandpass_calls, tmp_path):
    wav_path = tmp_path / "phrase.wav"
    sf.write(str(wav_path), np.zeros(400, dtype=np.float32), 8000,
             format="WAV", subtype="PCM_16")

    v = _make_voice()

    v._play_wav(str(wav_path), voice_cast.SLOT_SPOTTER)
    assert len(bandpass_calls) > 0, "споттер должен звучать через рацию"

    bandpass_calls.clear()
    v._play_wav(str(wav_path), "tv")
    assert bandpass_calls == [], "комментатор должен звучать чистым эфиром"


def test_formula_start_beep_opens_radio_but_not_commentary(
        fake_sd, start_beep_calls, tmp_path):
    wav_path = tmp_path / "phrase.wav"
    sf.write(str(wav_path), np.zeros(400, dtype=np.float32), 8000,
             format="WAV", subtype="PCM_16")
    v = _make_voice()

    v._play_wav(str(wav_path), voice_cast.SLOT_ENGINEER)
    assert start_beep_calls == [8000]

    start_beep_calls.clear()
    v._play_wav(str(wav_path), "tv")
    assert start_beep_calls == []
