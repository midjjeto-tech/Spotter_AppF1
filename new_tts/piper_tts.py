"""
new_tts/piper_tts.py
====================
PiperVoiceEngine — офлайн-синтез русской речи через Piper, ОТДЕЛЬНЫМ ПРОЦЕССОМ.

Почему процессом, а не библиотекой. Piper распространяется под GPL-3.0-or-later,
а Spotter App раздаётся закрытым EXE — вшивать GPL-код внутрь нельзя. Поэтому
Piper ставится отдельным компонентом установщика и запускается как независимая
программа; мы общаемся с ней через stdin и файлы. Подробности — в NOTICE.

Что это дало кроме лицензионной чистоты: разовая загрузка модели (≈3 с) теперь
происходит ОДИН раз на голос, а не на каждую фразу. Замерено на живом бинарнике:
первая фраза 2.98 с, последующие 0.14–0.25 с.

ГРАБЛИ, СТОИВШАЯ ИЗМЕРЕНИЙ: без ``PYTHONIOENCODING=utf-8`` дочерний процесс
читает русский текст в системной кодировке, получает мусор и ОЗВУЧИВАЕТ его,
не падая. «Бокс.» превращалось из 0.39 с в 2.69 с невнятицы. Переменная
обязательна; на это стоит тест.

Публичный интерфейс не менялся — voice/tts.py остаётся тонким:
  is_ready, status, sample_rate, channels, wait_until_ready(),
  synthesize(text, persona), synthesize_streaming(text, persona)
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from pathlib import Path

import numpy as np

import config
from new_tts import ru_textnorm

_log = logging.getLogger(__name__)

# persona -> (voice name, length_scale).  length_scale < 1 = faster, > 1 = slower
# Ruslan = лучший по качеству, поэтому он на основной (дефолтной) персоне tv.
PERSONA_VOICE: dict[str, tuple[str, float]] = {
    "tv":    ("ruslan", 1.0),
    "hype":  ("denis",  0.92),
    "calm":  ("irina",  1.08),
    "toxic": ("dmitri", 1.0),
    # Слоты ролей (см. yandex_ai/voices.py). Гарантия здесь СЛАБЕЕ, чем у
    # Yandex, и это осознанно: голосов ровно четыре, и все четыре уже розданы
    # персонам выше — свободной под роль просто нет.
    # Динамически уступить голос, как это делает voice_cast.resolve(), путь
    # Piper тоже не может: PERSONA_VOICE.get(persona) статичен, механизма
    # оверрайдов у него нет.
    # Поэтому: инженер и споттер гарантированно отличаются ДРУГ ОТ ДРУГА и по
    # голосу, и по темпу, но могут совпасть с комментатором — при persona=toxic
    # с инженером, при persona=hype со споттером. Это аварийный фолбэк на
    # случай отказа сети, а не режим работы: качество голоса в проекте держится
    # на Yandex, и Piper намеренно не развивается.
    "engineer": ("dmitri", 1.0),
    "spotter":  ("denis",  1.12),
}
_DEFAULT_VOICE = "ruslan"

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')
_CLAUSE_SPLIT = re.compile(r'(?<=[,;:—–])\s+')
_MAX_SEGMENT_CHARS = 90  # split longer sentences at clause boundaries for latency

#: Сколько процессов Piper держим живыми одновременно. Три — по числу каналов
#: каста (комментатор, инженер, споттер). Каждый процесс держит свою ONNX-модель
#: в памяти, а приложение работает рядом с запущенной F1 на скромном железе —
#: поднимать лимит нельзя, ронять до одного тоже: вытеснение процесса споттера
#: означало бы трёхсекундную паузу ровно там, где предупреждение и нужно.
_MAX_LIVE_VOICES = 3

#: Сколько ждём появления готового WAV после отправки строки.
_SYNTH_TIMEOUT_S = 30.0
#: Сколько ждём ПЕРВУЮ фразу голоса: там же разовая загрузка модели.
_FIRST_SYNTH_TIMEOUT_S = 90.0


def _voice_dir() -> Path:
    """Где лежат ru_RU-*.onnx: сначала установленный компонент, потом дерево
    разработки. В дистрибутиве второго пути не существует."""
    installed = Path(config.PIPER_VOICES_DIR)
    if installed.is_dir() and any(installed.glob("ru_RU-*.onnx")):
        return installed
    return Path(config.PIPER_VOICES_DEV_DIR)


def _voice_path(name: str) -> Path:
    return _voice_dir() / f"ru_RU-{name}-medium.onnx"


def _resolve_runtime() -> tuple[list[str], str]:
    """Чем запускать Piper: (аргументы команды, вид).

    ``exe`` — установленный компонент рядом с приложением, единственный вариант
    у пользователя. ``module`` — пакет из окружения разработки, чтобы правки
    можно было проверять без сборки бинарника. ``none`` — Piper не установлен;
    это не ошибка, а рабочее состояние: голос уходит на системный SAPI5.
    """
    exe = Path(config.PIPER_EXE)
    if exe.is_file():
        return [str(exe)], "exe"
    if not getattr(sys, "frozen", False):
        try:
            import importlib.util
            if importlib.util.find_spec("piper") is not None:
                return [sys.executable, "-m", "piper"], "module"
        except Exception:  # noqa: BLE001 - отсутствие пакета не должно падать
            pass
    return [], "none"


def _child_env() -> dict:
    """Окружение дочернего процесса.

    ``PYTHONIOENCODING`` — не украшение: без него Piper читает stdin в системной
    кодировке, принимает кириллицу за мусор и озвучивает этот мусор, НЕ падая.
    Единственный признак поломки — речь становится длиннее и бессмысленной.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _split_segments(text: str) -> list[str]:
    """Split text into short speakable segments for low-latency streaming."""
    out: list[str] = []
    for sentence in _SENT_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= _MAX_SEGMENT_CHARS:
            out.append(sentence)
            continue
        buf = ""
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            if len(buf) + len(clause) + 1 <= _MAX_SEGMENT_CHARS:
                buf = (buf + " " + clause).strip()
            else:
                if buf:
                    out.append(buf)
                buf = clause
        if buf:
            out.append(buf)
    return out


def _wav_is_complete(path: Path) -> bool:
    """Дописан ли WAV до конца.

    Проверяем не «размер перестал расти», а сам файл: у RIFF в заголовке лежит
    итоговый размер, и модуль ``wave`` проставляет его только при закрытии.
    Пауза записи может оказаться длиннее любого разумного окна ожидания — на
    этом первая версия и попалась, отдав наполовину записанный файл. Обрезанная
    реплика опаснее задержки: «машина слева» без «слева» — дезинформация.
    """
    try:
        size = path.stat().st_size
        if size < 44:
            return False
        with path.open("rb") as handle:
            header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            return False
        declared = int.from_bytes(header[4:8], "little")
        return declared > 4 and declared + 8 == size
    except OSError:
        return False


def _read_wav_int16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        return np.frombuffer(frames, dtype=np.int16), wav.getframerate()


class _VoiceProcess:
    """Один долгоживущий процесс Piper под одну пару (голос, темп).

    Нарезка по фразам сделана файлами, а не сырым потоком: у ``--output-raw``
    нет границ между репликами, и «конец фразы» пришлось бы угадывать по паузе
    в выдаче — на загруженной машине это обрезало бы речь. Процесс пишет по
    WAV-файлу на строку, и готовность файла проверяется точно.
    """

    def __init__(self, command: list[str], model: Path, length_scale: float) -> None:
        self._command = command
        self._model = model
        self._length_scale = length_scale
        self._dir = Path(tempfile.mkdtemp(prefix="spotter-piper-"))
        self._proc: subprocess.Popen | None = None
        self._first_done = False
        self.sample_rate = 22050
        # Лок ПРОЦЕССА, а не движка: у каждого голоса свой процесс, и синтез
        # одним голосом не обязан ждать другого. Общий лок стоил 6.2 с задержки
        # на первую фразу — фоновый разогрев инженера и споттера держал его,
        # пока грузил свои модели. Ровно та задержка, ради устранения которой
        # разогрев и делался.
        self._busy = threading.Lock()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [*self._command, "-m", str(self._model), "-d", str(self._dir),
             "--length-scale", str(self._length_scale)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, env=_child_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def synthesize(self, text: str) -> np.ndarray | None:
        """int16 PCM одной фразы либо None. Исключения наружу не выпускает."""
        with self._busy:
            return self._synthesize_locked(text)

    def _synthesize_locked(self, text: str) -> np.ndarray | None:
        if not self.alive():
            return None
        for stale in self._dir.glob("*.wav"):
            stale.unlink(missing_ok=True)

        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write((text.replace("\n", " ") + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (OSError, ValueError, AssertionError) as exc:
            _log.warning("Piper: не удалось передать текст процессу: %s", exc)
            return None

        timeout = _SYNTH_TIMEOUT_S if self._first_done else _FIRST_SYNTH_TIMEOUT_S
        path = self._await_wav(timeout)
        if path is None:
            _log.warning("Piper: фраза не синтезирована за %.0f с", timeout)
            return None
        try:
            audio, rate = _read_wav_int16(path)
            self.sample_rate = rate
            self._first_done = True
            return audio
        except Exception as exc:  # noqa: BLE001 - битый файл не должен ронять голос
            _log.warning("Piper: не прочитан WAV %s: %s", path.name, exc)
            return None
        finally:
            path.unlink(missing_ok=True)

    def _await_wav(self, timeout: float) -> Path | None:
        """Дождаться ДОПИСАННОГО файла (см. _wav_is_complete)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.alive():
                return None
            for candidate in sorted(self._dir.glob("*.wav")):
                if _wav_is_complete(candidate):
                    return candidate
            time.sleep(0.02)
        return None

    def stop(self) -> None:
        # Ждём фразу в работе: вытеснение по LRU не должно обрывать уже
        # начатый синтез на полуслове.
        with self._busy:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        shutil.rmtree(self._dir, ignore_errors=True)


class PiperVoiceEngine:
    def __init__(self) -> None:
        self._processes: dict[tuple[str, float], _VoiceProcess] = {}
        self._order: list[tuple[str, float]] = []   # LRU, самый свежий в конце
        self._lock = threading.RLock()              # синтез сериализован
        self._loaded = threading.Event()            # set on success or failure
        self.sample_rate = 22050
        self.channels = 1
        self.is_ready = False
        self.status = "Piper не запущен"
        self.runtime_kind = "none"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start model loading explicitly; construction itself is passive."""
        if self._started or self._stopped:
            return
        self._started = True
        self.status = "Загрузка Piper..."
        self._thread = threading.Thread(
            target=self._load, daemon=True, name="piper-load")
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Request cancellation and wait a bounded time for model loading."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        # Unblock Voice._wait_and_setup even when loading cannot be interrupted
        # immediately inside the child process.
        self._loaded.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        with self._lock:
            for process in self._processes.values():
                process.stop()
            self._processes.clear()
            self._order.clear()
        if not self.is_ready:
            self.status = "Piper остановлен"

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        try:
            if self._stop_event.is_set():
                return
            command, kind = _resolve_runtime()
            self.runtime_kind = kind
            if kind == "none":
                # Не ошибка: компонент офлайн-голоса просто не установлен.
                self.status = "Piper не установлен"
                _log.info("Piper не установлен (%s) — офлайн-голос недоступен",
                          config.PIPER_EXE)
                return
            default = _voice_path(_DEFAULT_VOICE)
            if not default.exists():
                self.status = f"Piper: нет голоса {default.name}"
                _log.warning("Piper: голос не найден: %s", default)
                return

            # Разогрев: первая фраза оплачивает загрузку модели один раз.
            process = self._ensure_process(_DEFAULT_VOICE, 1.0)
            if process is None or process.synthesize("Готов.") is None:
                self.status = "Piper: разогрев не удался"
                return
            if self._stop_event.is_set():
                return
            self.sample_rate = process.sample_rate
            self.is_ready = True
            self.status = ("Piper готов (отдельный процесс)" if kind == "exe"
                           else "Piper готов (пакет разработки)")
            _log.info("Piper готов: %d Гц, голос '%s', режим %s",
                      self.sample_rate, _DEFAULT_VOICE, kind)
            threading.Thread(target=self._prewarm_safety_voices, daemon=True,
                             name="piper-prewarm").start()
        except Exception as exc:  # noqa: BLE001
            self.status = f"Piper: {exc}"
            _log.error("Piper load failed:\n%s", traceback.format_exc())
        finally:
            self._loaded.set()

    def _prewarm_safety_voices(self) -> None:
        """Поднять голоса инженера и споттера заранее.

        Загрузка модели стоит ~3.5 с, и платить их в момент «машина слева»
        нельзя: предупреждение, опоздавшее на три секунды, хуже отсутствующего.
        Ровно эти два слота плюс дефолтный голос комментатора дают
        `_MAX_LIVE_VOICES` — вытеснения не будет. Персона комментатора, если
        она не дефолтная, догрузится по первому обращению: опоздавшая реплика
        репортажа безопасна, в отличие от опоздавшего предупреждения.
        """
        for persona in ("engineer", "spotter"):
            if self._stop_event.is_set():
                return
            name, scale = PERSONA_VOICE[persona]
            with self._lock:
                process = self._ensure_process(name, scale)
            # Разогрев ВНЕ общего лока: пока грузится модель инженера,
            # комментатор обязан продолжать говорить.
            if process is not None:
                process.synthesize("Готов.")

    def _ensure_process(self, name: str, length_scale: float) -> _VoiceProcess | None:
        """Живой процесс под (голос, темп). Вызывается под self._lock."""
        key = (name, length_scale)
        existing = self._processes.get(key)
        if existing is not None and existing.alive():
            self._touch(key)
            return existing
        if existing is not None:                     # умер сам — поднимаем заново
            existing.stop()
            self._processes.pop(key, None)
            if key in self._order:
                self._order.remove(key)

        model = _voice_path(name)
        if not model.exists():
            _log.warning("Piper: голос не найден: %s", model)
            return None
        command, kind = _resolve_runtime()
        if kind == "none":
            return None

        process = _VoiceProcess(command, model, length_scale)
        try:
            process.start()
        except Exception as exc:  # noqa: BLE001
            _log.error("Piper: не удалось запустить процесс: %s", exc)
            process.stop()
            return None
        self._processes[key] = process
        self._touch(key)
        self._evict_extra()
        return process

    def _touch(self, key: tuple[str, float]) -> None:
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)

    def _evict_extra(self) -> None:
        while len(self._order) > _MAX_LIVE_VOICES:
            victim = self._order.pop(0)
            process = self._processes.pop(victim, None)
            if process is not None:
                process.stop()

    # ------------------------------------------------------------------ #
    def synthesize(self, text: str, persona: str = "tv") -> tuple[np.ndarray | None, int]:
        """Full synthesis. Returns (audio float32 mono [-1,1], sample_rate)."""
        if not self.is_ready or not text.strip():
            return None, 0
        parts = list(self._stream_arrays(text, persona))
        if not parts:
            return None, 0
        return np.concatenate(parts).astype(np.float32), self.sample_rate

    def synthesize_streaming(self, text: str, persona: str = "tv"):
        """Yields (audio float32 mono, sample_rate) per segment for low latency."""
        if not self.is_ready:
            return
        for audio in self._stream_arrays(text, persona):
            yield audio, self.sample_rate

    def _stream_arrays(self, text: str, persona: str):
        norm = ru_textnorm.normalize(text)
        if not norm.strip():
            return
        name, length_scale = PERSONA_VOICE.get(persona, (_DEFAULT_VOICE, 1.0))
        for segment in _split_segments(norm):
            if self._stop_event.is_set():
                return
            # Общий лок держим только на поиске процесса — это доли миллисекунды.
            # Сам синтез сериализуется локом КОНКРЕТНОГО процесса, поэтому
            # разные голоса не ждут друг друга.
            with self._lock:
                process = self._ensure_process(name, length_scale)
            pcm = process.synthesize(segment) if process is not None else None
            if process is not None and pcm is not None:
                self.sample_rate = process.sample_rate
            if pcm is None:
                self.status = "Синтез: фраза не получена от Piper"
                continue
            audio = pcm.astype(np.float32) / 32768.0
            if len(audio):
                yield audio

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        self._loaded.wait(timeout=timeout)
        return self.is_ready
