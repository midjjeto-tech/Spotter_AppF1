"""Офлайн-голос как отдельный процесс: лицензионная граница и её ловушки.

Piper вынесен из EXE под GPL (см. NOTICE), и вместе с процессом появились свои
способы сломаться молча — в первую очередь кодировка stdin. Тесты держат именно
их, а не форму вызова subprocess.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

import config
from new_tts import piper_tts


def test_child_process_is_told_to_read_utf8():
    """Без PYTHONIOENCODING дочерний Piper принимает кириллицу за мусор и
    ОЗВУЧИВАЕТ его, не падая: замерено, «Бокс.» растягивалось с 0.39 до 2.69 с.
    Ошибка не видна ни в логах, ни в кодах возврата — только на слух."""
    assert piper_tts._child_env()["PYTHONIOENCODING"] == "utf-8"


def test_missing_component_is_a_state_not_a_crash(monkeypatch, tmp_path):
    """Компонент офлайн-голоса необязательный. Его отсутствие обязано давать
    внятный статус и молчание, а не исключение в поток озвучки."""
    monkeypatch.setattr(config, "PIPER_EXE", str(tmp_path / "нет.exe"))
    monkeypatch.setattr(piper_tts, "_resolve_runtime", lambda: ([], "none"))

    engine = piper_tts.PiperVoiceEngine()
    engine.start()
    engine.wait_until_ready(10)

    assert engine.is_ready is False
    assert engine.status == "Piper не установлен"
    assert engine.synthesize("Машина слева.", "spotter") == (None, 0)
    engine.stop()


def test_installed_voices_win_over_the_development_tree(monkeypatch, tmp_path):
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "ru_RU-ruslan-medium.onnx").write_bytes(b"x")
    monkeypatch.setattr(config, "PIPER_VOICES_DIR", str(installed))
    monkeypatch.setattr(config, "PIPER_VOICES_DEV_DIR", str(tmp_path / "dev"))

    assert piper_tts._voice_dir() == installed


def test_development_tree_is_used_when_nothing_is_installed(monkeypatch, tmp_path):
    dev = tmp_path / "dev"
    monkeypatch.setattr(config, "PIPER_VOICES_DIR", str(tmp_path / "empty"))
    monkeypatch.setattr(config, "PIPER_VOICES_DEV_DIR", str(dev))

    assert piper_tts._voice_dir() == dev


class _GrowingFileProcess(piper_tts._VoiceProcess):
    """Процесс-дубль, который пишет WAV постепенно."""

    def __init__(self, directory: Path):
        self._command = []
        self._model = Path("model.onnx")
        self._length_scale = 1.0
        self._dir = directory
        self._proc = None
        self._first_done = True
        self.sample_rate = 22050

    def alive(self) -> bool:
        return True


def test_half_written_wav_is_never_returned(tmp_path):
    """Файл берётся только дописанным. Первая версия проверяла «размер не
    изменился за 20 мс» и отдавала недописанный файл: паузы записи длиннее
    любого разумного окна. Обрезанная реплика опаснее задержки — «машина
    слева» без «слева» дезинформирует."""
    import threading
    import wave as wave_mod

    process = _GrowingFileProcess(tmp_path)
    target = tmp_path / "phrase.wav"
    frames = (np.zeros(22050, dtype=np.int16)).tobytes()

    def write_slowly():
        with wave_mod.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            for _ in range(4):
                time.sleep(0.05)          # пауза длиннее прежнего окна ожидания
                handle.writeframes(frames)

    writer = threading.Thread(target=write_slowly, daemon=True)
    writer.start()
    found = process._await_wav(timeout=10.0)
    writer.join(timeout=5.0)

    assert found == target
    # Файл признан готовым только целиком: читается и содержит все 4 секунды.
    audio, rate = piper_tts._read_wav_int16(found)
    assert rate == 22050
    assert len(audio) == 4 * 22050


def test_a_wav_without_a_finished_header_is_not_ready(tmp_path):
    """Заголовок RIFF с непроставленным размером — верный признак того, что
    писавший процесс ещё не закрыл файл."""
    half = tmp_path / "half.wav"
    half.write_bytes(b"RIFF" + (0).to_bytes(4, "little") + b"WAVE" + b"\0" * 40)

    assert piper_tts._wav_is_complete(half) is False


def test_a_dead_process_does_not_hang_the_wait(tmp_path):
    process = _GrowingFileProcess(tmp_path)
    process.alive = lambda: False  # type: ignore[method-assign]

    started = time.monotonic()
    assert process._await_wav(timeout=30.0) is None
    assert time.monotonic() - started < 5.0, "ожидание не оборвалось на мёртвом процессе"


class _FakeProcess:
    def __init__(self, *_args, **_kwargs):
        self.stopped = False
        self.sample_rate = 22050

    def start(self):
        return None

    def alive(self):
        return not self.stopped

    def synthesize(self, _text):
        return np.zeros(10, dtype=np.int16)

    def stop(self):
        self.stopped = True


def test_live_voices_are_capped_so_the_game_keeps_its_memory(monkeypatch):
    """Каждый процесс держит свою ONNX-модель, а рядом работает F1 на скромном
    железе. Лимит — три по числу каналов каста."""
    monkeypatch.setattr(piper_tts, "_VoiceProcess", _FakeProcess)
    monkeypatch.setattr(piper_tts, "_resolve_runtime", lambda: (["piper"], "exe"))
    monkeypatch.setattr(piper_tts, "_voice_path", lambda name: Path(__file__))

    engine = piper_tts.PiperVoiceEngine()
    created = []
    for index, name in enumerate(("ruslan", "denis", "irina", "dmitri")):
        process = engine._ensure_process(name, 1.0 + index)
        created.append(process)

    assert len(engine._processes) == piper_tts._MAX_LIVE_VOICES
    assert created[0].stopped is True, "самый старый голос не вытеснен"
    assert created[-1].stopped is False


def test_reusing_a_voice_keeps_the_same_process(monkeypatch):
    monkeypatch.setattr(piper_tts, "_VoiceProcess", _FakeProcess)
    monkeypatch.setattr(piper_tts, "_resolve_runtime", lambda: (["piper"], "exe"))
    monkeypatch.setattr(piper_tts, "_voice_path", lambda name: Path(__file__))

    engine = piper_tts.PiperVoiceEngine()
    first = engine._ensure_process("ruslan", 1.0)
    again = engine._ensure_process("ruslan", 1.0)

    assert first is again, "модель перезагружалась бы на каждую фразу"


def test_a_dead_process_is_replaced_not_reused(monkeypatch):
    monkeypatch.setattr(piper_tts, "_VoiceProcess", _FakeProcess)
    monkeypatch.setattr(piper_tts, "_resolve_runtime", lambda: (["piper"], "exe"))
    monkeypatch.setattr(piper_tts, "_voice_path", lambda name: Path(__file__))

    engine = piper_tts.PiperVoiceEngine()
    first = engine._ensure_process("ruslan", 1.0)
    first.stopped = True                      # процесс упал сам
    second = engine._ensure_process("ruslan", 1.0)

    assert second is not first


@pytest.mark.skipif(piper_tts._resolve_runtime()[1] == "none",
                    reason="Piper не установлен в этом окружении")
def test_russian_text_survives_the_process_boundary():
    """Живая проверка кодировки: длительность речи должна соответствовать
    тексту. Мусор из-за неверной кодировки звучит в разы дольше."""
    engine = piper_tts.PiperVoiceEngine()
    engine.start()
    if not engine.wait_until_ready(120):
        engine.stop()
        pytest.skip(f"Piper не поднялся: {engine.status}")
    try:
        audio, rate = engine.synthesize("Бокс.", "tv")
        assert audio is not None and rate > 0
        seconds = len(audio) / rate
        assert seconds < 1.2, (
            f"«Бокс.» звучит {seconds:.2f} с — похоже на мусор из-за кодировки")
    finally:
        engine.stop()
