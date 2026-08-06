"""
voice/listener.py
==================
Push-to-talk запись вопроса с микрофона: sounddevice.InputStream -> int16 LPCM mono bytes.

recorder инъектируется через конструктор с первого дня (VoiceListener(recorder=...)) —
тесты никогда не трогают реальное аудио-устройство. Нет микрофона / исключение -> None,
вызывающий код (core/engine.py) деградирует в safe-фолбэк без падения приложения.

device (имя устройства строкой, из list_input_devices(), или None = системный дефолт)
живёт на VoiceListener, а не в сигнатуре инжектируемого recorder — контракт
recorder(max_sec, sr) не меняется, чтобы не трогать существующие тесты/вызовы.
"""
from __future__ import annotations

import logging
from typing import Callable

_log = logging.getLogger(__name__)


def _default_recorder(max_sec: float, sr: int, device: str | int | None = None) -> bytes | None:
    import sounddevice as sd
    frames = int(max_sec * sr)
    # Выделенный InputStream, НЕ модульные sd.rec/sd.wait: голый sd.wait() ждёт
    # ПОСЛЕДНИЙ глобальный стрим процесса, а TTS-воркер (voice/tts.py::_play_wav)
    # использует ту же глобальную пару sd.play/sd.wait — параллельная озвучка
    # перехватывала бы наше ожидание (обрезанный вопрос) и наоборот.
    with sd.InputStream(samplerate=sr, channels=1, dtype="int16", device=device) as stream:
        data, _overflowed = stream.read(frames)
    return data.tobytes()


def list_input_devices() -> list[dict]:
    """Устройства записи (max_input_channels > 0) для выбора в настройках.
    Любой сбой PortAudio -> [] (fail-safe, как остальной voice-стек)."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default = sd.default.device
        default_idx = default[0] if isinstance(default, (list, tuple)) else default
        return [
            {"name": d["name"], "index": i, "is_default": i == default_idx}
            for i, d in enumerate(devices)
            if d.get("max_input_channels", 0) > 0
        ]
    except Exception as exc:  # noqa: BLE001
        _log.warning("list_input_devices failed: %s", exc)
        return []


def play_back(audio: bytes, sr: int = 48000) -> None:
    """Проиграть записанный int16 LPCM mono через ОТДЕЛЬНЫЙ OutputStream — тот же
    паттерн, что voice/tts.py::_play_wav (не модульный sd.play()/sd.wait(), который
    делит глобальный указатель стрима с TTS-плеером — см. _default_recorder выше)."""
    import numpy as np
    import sounddevice as sd
    data = np.frombuffer(audio, dtype=np.int16)
    with sd.OutputStream(samplerate=sr, channels=1, dtype="int16") as stream:
        stream.write(data)


class VoiceListener:
    def __init__(self, recorder: Callable[[float, int], bytes | None] | None = None,
                 device: str | int | None = None):
        self._custom_recorder = recorder
        self._device = device

    def set_device(self, device: str | int | None) -> None:
        self._device = device

    def record(self, max_sec: float, sr: int = 48000) -> bytes | None:
        """Записать до max_sec секунд с микрофона. None — нет устройства/сбой."""
        try:
            if self._custom_recorder is not None:
                data = self._custom_recorder(max_sec, sr)
            else:
                data = _default_recorder(max_sec, sr, self._device)
        except Exception as exc:  # noqa: BLE001
            _log.warning("VoiceListener record failed: %s", exc)
            return None
        return data or None
