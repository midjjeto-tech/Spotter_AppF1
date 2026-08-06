# MOSS-TTS-Nano Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Qwen3-TTS-0.6B (GPU/PyTorch) with MOSS-TTS-Nano-100M-ONNX (CPU/ONNX, torch-free) across the Spotter F1 App.

**Architecture:**
- `new_tts/moss_tts.py` replaces `new_tts/qwen3_tts.py` — same public interface (`is_ready`, `status`, `sample_rate`, `channels`, `synthesize`, `synthesize_streaming`).
- `voice/tts.py` updated: imports MossTTS, stereo 48kHz playback, soundfile-based WAV I/O.
- `new_tts/queue_handler.py` и `voice/cache.py` — **не меняются совсем**.
- ONNX-модели лежат в `models/` и бандлятся в EXE через spec.
- Референс-голоса для персон (`assets/voices/*.wav`) — EN-сэмплы из репо MOSS-TTS-Nano, заменяемые пользователем на русские записи.

**Tech Stack:** `moss-tts-nano`, `onnxruntime>=1.20.0`, `soundfile` (existing), `sounddevice` (existing), `numpy` (existing)

---

## File Map

| Действие | Файл |
|----------|------|
| DELETE | `new_tts/qwen3_tts.py` |
| DELETE | `rthook_torch.py` |
| CREATE | `new_tts/moss_tts.py` |
| CREATE | `assets/voices/tv.wav`, `hype.wav`, `calm.wav`, `toxic.wav` |
| MODIFY | `voice/tts.py` |
| MODIFY | `requirements.txt` |
| MODIFY | `SpotterApp.spec` |
| MODIFY | `build.ps1` |
| UNCHANGED | `new_tts/__init__.py`, `new_tts/queue_handler.py`, `voice/__init__.py`, `voice/cache.py`, всё остальное |

---

## Task 1: Удалить старые TTS-файлы

**Files:**
- Delete: `new_tts/qwen3_tts.py`
- Delete: `rthook_torch.py`

- [ ] **Шаг 1: Удалить qwen3_tts.py**

```powershell
Remove-Item "new_tts\qwen3_tts.py" -Force
```

- [ ] **Шаг 2: Удалить rthook_torch.py**

```powershell
Remove-Item "rthook_torch.py" -Force
```

- [ ] **Шаг 3: Очистить TTS-кэш (WAV-файлы от старой модели)**

```powershell
$cacheDir = "tts_cache"
if (Test-Path $cacheDir) {
    Remove-Item "$cacheDir\*.wav" -Force -ErrorAction SilentlyContinue
    Write-Host "TTS cache cleared."
}
```

- [ ] **Шаг 4: Удалить qwen-tts из pip (опционально, освобождает ~место)**

```powershell
pip uninstall qwen-tts -y
```

- [ ] **Шаг 5: Убедиться, что нет импортов qwen_tts**

```powershell
Select-String -Path "*.py", "**\*.py" -Pattern "qwen_tts|qwen3_tts|Qwen3TTS" -Recurse -ErrorAction SilentlyContinue
```

Ожидаемый результат: пусто.

---

## Task 2: Установить зависимости + скачать модели и голоса

**Files:**
- Create dir: `models/MOSS-TTS-Nano-100M-ONNX/`
- Create dir: `models/MOSS-Audio-Tokenizer-Nano-ONNX/`
- Create dir: `assets/voices/`

- [ ] **Шаг 1: Установить пакеты**

```powershell
pip install moss-tts-nano "onnxruntime>=1.20.0" soundfile
```

Проверить установку:
```powershell
python -c "from onnx_tts_runtime import OnnxTtsRuntime; print('onnx_tts_runtime OK')"
python -c "import soundfile; print('soundfile OK')"
```

Ожидаемый результат: обе строки без ошибок.

- [ ] **Шаг 2: Создать директории**

```powershell
New-Item -ItemType Directory -Force -Path "models", "assets\voices"
```

- [ ] **Шаг 3: Скачать ONNX TTS-модель**

```powershell
huggingface-cli download OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX `
    --local-dir models/MOSS-TTS-Nano-100M-ONNX
```

Проверить:
```powershell
Test-Path "models\MOSS-TTS-Nano-100M-ONNX\model.onnx"
```
Ожидаемый результат: `True`

- [ ] **Шаг 4: Скачать ONNX Audio Tokenizer**

```powershell
huggingface-cli download OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX `
    --local-dir models/MOSS-Audio-Tokenizer-Nano-ONNX
```

Проверить:
```powershell
Test-Path "models\MOSS-Audio-Tokenizer-Nano-ONNX\model.onnx"
```
Ожидаемый результат: `True`

- [ ] **Шаг 5: Скачать референс-голоса для персон**

Используем EN-сэмплы из GitHub-репо MOSS-TTS-Nano как заглушки.
Пользователь может позже заменить на русские записи (3-10 сек русской речи).

```powershell
$base = "https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS-Nano/main/assets/audio"
Invoke-WebRequest "$base/en_2.wav" -OutFile "assets\voices\tv.wav"
Invoke-WebRequest "$base/en_3.wav" -OutFile "assets\voices\hype.wav"
Invoke-WebRequest "$base/en_6.wav" -OutFile "assets\voices\calm.wav"
Invoke-WebRequest "$base/en_8.wav" -OutFile "assets\voices\toxic.wav"
```

Проверить:
```powershell
Get-ChildItem "assets\voices\" | Select-Object Name, Length
```
Ожидаемый результат: 4 файла по несколько KB/сотен KB.

---

## Task 3: Создать new_tts/moss_tts.py

**Files:**
- Create: `new_tts/moss_tts.py`

- [ ] **Шаг 1: Создать файл**

Содержимое `new_tts/moss_tts.py`:

```python
"""
new_tts/moss_tts.py
====================
MOSS-TTS-Nano-100M-ONNX wrapper — torch-free CPU inference.
Output: 48 kHz stereo float32 [N, 2].
Public interface identical to Qwen3TTS:
  is_ready, status, sample_rate, channels, synthesize(), synthesize_streaming()
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import traceback
from pathlib import Path

import numpy as np

import config

_log = logging.getLogger(__name__)

_TTS_MODEL_DIR = str(Path(config.BASE_DIR) / "models" / "MOSS-TTS-Nano-100M-ONNX")
_VOICES_DIR    = str(Path(config.BASE_DIR) / "assets" / "voices")
_FALLBACK_VOICE = "Junhao"  # built-in preset if no reference .wav found


class MossTTS:
    def __init__(self):
        self._runtime = None
        self._lock = threading.Lock()  # one inference at a time
        self.sample_rate = 48000
        self.channels = 2
        self.is_ready = False
        self.status = "Загрузка MOSS-TTS-Nano..."
        threading.Thread(target=self._load, daemon=True, name="moss-load").start()

    def _load(self) -> None:
        try:
            from onnx_tts_runtime import OnnxTtsRuntime
            self._runtime = OnnxTtsRuntime(
                model_dir=_TTS_MODEL_DIR,
                thread_count=4,      # не захватываем все ядра
                execution_provider="cpu",
            )
            self.is_ready = True
            self.status = "MOSS-TTS-Nano ready (CPU, ONNX)"
        except Exception as exc:
            self.status = f"MOSS-TTS: {exc}"
            _log.error("MOSS-TTS load failed:\n%s", traceback.format_exc())

    def synthesize(
        self, text: str, speaker: str = "tv"
    ) -> tuple[np.ndarray | None, int]:
        """Full synthesis. Returns (audio float32 [N,2] stereo, sample_rate)."""
        if not self.is_ready or not text.strip():
            return None, 0
        with self._lock:
            try:
                import soundfile as sf

                ref_path = self._ref_path(speaker)

                # Temp file must be on same drive as DATA_DIR to avoid
                # cross-drive os.replace() failure (Windows restriction).
                fd, tmp_path = tempfile.mkstemp(
                    suffix=".wav", dir=config.DATA_DIR
                )
                os.close(fd)

                try:
                    self._runtime.synthesize(
                        text=text.strip(),
                        # voice=None triggers voice-cloning from prompt_audio_path;
                        # fallback to built-in preset when no reference file found.
                        voice=None if ref_path else _FALLBACK_VOICE,
                        prompt_audio_path=ref_path,
                        output_audio_path=tmp_path,
                        streaming=True,
                        do_sample=True,
                        sample_mode="fixed",
                    )
                    audio, sr = sf.read(tmp_path, dtype="float32")
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

                if audio.ndim == 1:
                    # Mono output → duplicate to stereo
                    audio = np.column_stack([audio, audio])
                self.sample_rate = int(sr)
                return audio, int(sr)

            except Exception as exc:
                self.status = f"Синтез: {exc}"
                _log.error("Synthesis error: %s", exc)
                return None, 0

    def synthesize_streaming(self, text: str, speaker: str = "tv"):
        """Streaming by sentences. Yields (np.ndarray float32 [N,2], int)."""
        if not self.is_ready:
            return
        for sentence in _split_text(text):
            audio, sr = self.synthesize(sentence, speaker)
            if audio is not None and len(audio) > 0:
                yield audio, sr

    def _ref_path(self, speaker: str) -> str | None:
        """Returns path to reference WAV for speaker, or None if file absent."""
        path = os.path.join(_VOICES_DIR, f"{speaker}.wav")
        return path if os.path.exists(path) else None


def _split_text(text: str) -> list[str]:
    """Split on sentence boundaries for streaming."""
    parts = re.split(r'(?<=[.!?,;])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]
```

- [ ] **Шаг 2: Убедиться, что файл синтаксически корректен**

```powershell
python -c "import ast; ast.parse(open('new_tts/moss_tts.py').read()); print('syntax OK')"
```

Ожидаемый результат: `syntax OK`

---

## Task 4: Обновить voice/tts.py

**Files:**
- Modify: `voice/tts.py`

Ключевые изменения:
- `Qwen3TTS` → `MossTTS`
- `PERSONA_SPEAKER` значения: именованные голоса → ключи персон (`tv`, `hype`, `calm`, `toxic`)
- `_play_streaming`: `samplerate=48000, channels=2, blocksize=4800`
- `_save_wav`: `wave` модуль → `soundfile.write` (поддерживает стерео)
- `_play_wav`: ручной разбор int16 → `soundfile.read` (автоматически обрабатывает стерео)
- Строки статуса: "Qwen3-TTS" → "MOSS-TTS-Nano"

- [ ] **Шаг 1: Полностью заменить содержимое voice/tts.py**

```python
"""
voice/tts.py
============
Озвучка через MOSS-TTS-Nano-100M-ONNX (CPU, ONNX, torch-free).
Резерв — pyttsx3 (если MOSS-TTS недоступен).
Streaming: первый чанк через ~300-500ms (sounddevice OutputStream).
Кэш фраз на диск (voice/cache.py) — повтор без обращения к модели.
Queue: события не перебивают и не накладываются.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

import config
from voice.cache import TTSCache
from commentator.templates import SIMPLE
from new_tts.moss_tts import MossTTS
from new_tts.queue_handler import TTSQueue

_log = logging.getLogger(__name__)

# Maps persona name → reference voice key (filename stem in assets/voices/)
PERSONA_SPEAKER = {
    "tv":    "tv",
    "hype":  "hype",
    "calm":  "calm",
    "toxic": "toxic",
}


class Voice:
    def __init__(self, *_args, **_kwargs):
        self._moss: MossTTS = MossTTS()
        self.pyttsx3_engine = None
        self.status_message = "Загрузка MOSS-TTS-Nano..."
        self._cache = TTSCache(os.path.join(config.DATA_DIR, "tts_cache"))
        self._queue: TTSQueue | None = None
        self._current_speaker = "tv"
        self._configure_stdout()
        threading.Thread(target=self._wait_and_setup, daemon=True, name="tts-setup").start()

    def _configure_stdout(self) -> None:
        stdout = getattr(sys, "stdout", None)
        if getattr(stdout, "encoding", None) not in (None, "utf-8"):
            try:
                stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

    def _wait_and_setup(self) -> None:
        """Ждёт загрузки MOSS-TTS, затем создаёт Queue и прогревает кэш."""
        for _ in range(120):  # до 60 сек
            if self._moss.is_ready or self._moss.status.startswith("MOSS-TTS:"):
                break
            time.sleep(0.5)

        if self._moss.is_ready:
            self._queue = TTSQueue(speak_fn=self._play_blocking)
            self.status_message = self._moss.status
            threading.Thread(
                target=self._prewarm_cache, daemon=True, name="tts-prewarm"
            ).start()
        else:
            moss_err = self._moss.status
            self._init_pyttsx3()
            if self.pyttsx3_engine is not None:
                self._queue = TTSQueue(speak_fn=self._say_pyttsx3_blocking)
            else:
                self.status_message = moss_err

    def _init_pyttsx3(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            for voice in engine.getProperty("voices"):
                name = (voice.name or "").lower()
                vid  = (voice.id or "").lower()
                if "russian" in name or "ru" in vid:
                    engine.setProperty("voice", voice.id)
                    break
            self.pyttsx3_engine = engine
            self.status_message = "pyttsx3 активирован (резерв)"
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"

    def _prewarm_cache(self) -> None:
        """Кэширует статичные фразы для всех спикеров в фоне."""
        try:
            all_speakers = list(set(PERSONA_SPEAKER.values()))
            for phrases in SIMPLE.values():
                for phrase in phrases:
                    if "{" in phrase or not self._moss.is_ready:
                        continue
                    if self._queue is not None and not self._queue._queue.empty():
                        _log.debug("prewarm: pausing, queue has pending items")
                        time.sleep(0.2)
                        continue
                    for speaker in all_speakers:
                        cache_path = self._cache.path_for(phrase.strip(), speaker)
                        if not os.path.exists(cache_path):
                            self._generate_and_cache_speaker(phrase.strip(), speaker)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Публичный интерфейс (engine.py зависит от этих полей и методов)     #
    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self._moss.is_ready or self.pyttsx3_engine is not None

    @property
    def engine_name(self) -> str:
        if self._moss.is_ready:
            return "MOSS-TTS-Nano"
        if self.pyttsx3_engine is not None:
            return "pyttsx3"
        return "Нет"

    def set_persona(self, persona: str) -> None:
        self._current_speaker = PERSONA_SPEAKER.get(persona, "tv")

    def say(self, text: str) -> bool:
        """Ставит фразу в очередь. Возвращает True сразу."""
        if not text or not text.strip() or not self.is_available:
            return False
        if self._queue is not None:
            self._queue.enqueue(text.strip())
            return True
        return False

    def test_say(self, text: str) -> bool:
        """Тестовое воспроизведение: очищает очередь, ставит фразу первой."""
        if self._queue is not None:
            self._queue.clear()
        t0 = time.monotonic()
        ok = self.say(text)
        _log.debug("test_say enqueued in %.1f ms", (time.monotonic() - t0) * 1000)
        return ok

    # ------------------------------------------------------------------ #
    # Воспроизведение (вызывается из TTSQueue._worker в фоновом потоке)   #
    # ------------------------------------------------------------------ #

    def _play_blocking(self, text: str) -> None:
        self.status_message = self._moss.status

        speaker = self._current_speaker
        cache_path = self._cache.path_for(text, speaker)
        if os.path.exists(cache_path):
            t0 = time.monotonic()
            self._play_wav(cache_path)
            _log.debug("playback from cache: %.0f ms", (time.monotonic() - t0) * 1000)
            return

        t0 = time.monotonic()
        self._play_streaming(text, cache_path, speaker)
        _log.debug("playback synthesized+streamed: %.0f ms", (time.monotonic() - t0) * 1000)

    def _play_streaming(
        self, text: str, cache_path: str, speaker: str = "tv"
    ) -> None:
        """Streaming: воспроизводит чанки по мере генерации, кэширует полную версию."""
        try:
            import sounddevice as sd
            import numpy as np

            chunks: list[np.ndarray] = []
            n_ch = self._moss.channels  # 2 for MOSS-TTS-Nano

            with sd.OutputStream(
                samplerate=self._moss.sample_rate,
                channels=n_ch,
                dtype="float32",
                blocksize=4800,  # 100ms at 48 kHz
            ) as stream:
                for chunk, _ in self._moss.synthesize_streaming(text, speaker):
                    if chunk.ndim == 1:
                        chunk = np.column_stack([chunk, chunk])  # mono → stereo
                    stream.write(chunk)
                    chunks.append(chunk)

            if chunks:
                full = np.concatenate(chunks, axis=0)
                self._save_wav(full, self._moss.sample_rate, cache_path)
                self._cache.evict_if_needed()

        except ImportError:
            # sounddevice не установлен — синтезируем целиком, играем через winsound
            audio, sr = self._moss.synthesize(text, speaker)
            if audio is not None:
                self._save_wav(audio, sr, cache_path)
                self._play_wav(cache_path)
        except Exception as exc:
            self.status_message = f"Воспроизведение: {exc}"

    def _generate_and_cache(self, text: str) -> str | None:
        return self._generate_and_cache_speaker(text, self._current_speaker)

    def _generate_and_cache_speaker(self, text: str, speaker: str) -> str | None:
        """Генерирует и кэширует без воспроизведения для указанного спикера."""
        cache_path = self._cache.path_for(text, speaker)
        if os.path.exists(cache_path):
            return cache_path
        audio, sr = self._moss.synthesize(text, speaker=speaker)
        if audio is not None:
            self._save_wav(audio, sr, cache_path)
            return cache_path
        return None

    def _save_wav(self, audio, sample_rate: int, path: str) -> None:
        """Saves float32 audio (mono or stereo) as int16 WAV. Atomic write."""
        try:
            import soundfile as sf
            import numpy as np
            pcm = np.clip(audio, -1.0, 1.0)
            # tmp on same drive as final path — avoids cross-drive os.replace() failure
            tmp = path + ".tmp"
            sf.write(tmp, pcm, sample_rate, subtype="PCM_16")
            os.replace(tmp, path)
        except Exception as exc:
            self.status_message = f"Кэш TTS: {exc}"

    def _play_wav(self, path: str) -> None:
        try:
            import sounddevice as sd
            import soundfile as sf
            audio, sr = sf.read(path, dtype="float32")
            sd.play(audio, sr)
            sd.wait()
        except ImportError:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except Exception as exc:
            self.status_message = f"WAV play: {exc}"

    # ------------------------------------------------------------------ #
    # pyttsx3 (резерв, если MOSS-TTS не загрузился)                       #
    # ------------------------------------------------------------------ #

    def _say_pyttsx3_blocking(self, text: str) -> None:
        try:
            self.pyttsx3_engine.say(text)
            self.pyttsx3_engine.runAndWait()
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"
```

- [ ] **Шаг 2: Проверить синтаксис**

```powershell
python -c "import ast; ast.parse(open('voice/tts.py').read()); print('syntax OK')"
```

Ожидаемый результат: `syntax OK`

---

## Task 5: Обновить requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Шаг 1: Заменить содержимое requirements.txt**

```
bottle>=0.13
pywebview>=5.0
psutil>=5.9
pyttsx3>=2.90
moss-tts-nano
onnxruntime>=1.20.0
sounddevice>=0.4
soundfile>=0.12
numpy>=1.24
```

Удалено: `qwen-tts`, `torch>=2.1`, `torchaudio`
Добавлено: `moss-tts-nano`, `onnxruntime>=1.20.0`, `numpy>=1.24` (явно)

- [ ] **Шаг 2: Убедиться, что все пакеты из requirements.txt установлены**

```powershell
pip install -r requirements.txt
```

---

## Task 6: Обновить SpotterApp.spec

**Files:**
- Modify: `SpotterApp.spec`

- [ ] **Шаг 1: Полностью заменить содержимое SpotterApp.spec**

```python
# -*- mode: python ; coding: utf-8 -*-
#
# MOSS-TTS-Nano ONNX models bundled in models/ — no internet needed on first run.
# EXE significantly smaller than torch-based version (no 1.5 GB torch DLLs).
from PyInstaller.utils.hooks import collect_all

datas = [
    ('voice',        'voice'),
    ('core',         'core'),
    ('commentator',  'commentator'),
    ('new_tts',      'new_tts'),
    ('analytics',    'analytics'),
    ('index.html',   '.'),
    ('config.py',    '.'),
    ('app.pyw',      '.'),
    ('web_server.py', '.'),
    # MOSS-TTS-Nano ONNX models
    ('models/MOSS-TTS-Nano-100M-ONNX',       'models/MOSS-TTS-Nano-100M-ONNX'),
    ('models/MOSS-Audio-Tokenizer-Nano-ONNX', 'models/MOSS-Audio-Tokenizer-Nano-ONNX'),
    # Reference voices for persona voice-cloning
    ('assets/voices', 'assets/voices'),
]

binaries = []

hiddenimports = [
    'webview',
    'webview.platforms.winforms',
    'webview.platforms',
    'webview.servers',
    'webview.http',
    'bottle',
    'psutil',
    'psutil._pswindows',
    'psutil._psutil_windows',
    # MOSS-TTS-Nano ONNX runtime
    'onnx_tts_runtime',
    'moss_tts_nano',
    'onnxruntime',
    'onnxruntime.capi',
    'sentencepiece',
    # audio
    'sounddevice',
    'soundfile',
    'numpy',
    # analytics (lazy-imported)
    'fastf1',
    'fastf1.exceptions',
    'fastf1.core',
    'pandas',
    'requests',
]

tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('bottle')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('psutil')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('onnx_tts_runtime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('soundfile')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.pyw'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],  # rthook_torch.py deleted — no torch needed
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'qwen_tts', 'transformers', 'accelerate',
        'sklearn', 'scipy',
        'matplotlib', 'PIL', 'IPython', 'cv2',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SpotterApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

---

## Task 7: Обновить build.ps1

**Files:**
- Modify: `build.ps1`

- [ ] **Шаг 1: Полностью заменить содержимое build.ps1**

```powershell
# build.ps1 - SpotterApp.exe build script
# Usage: .\build.ps1

$_pi = Get-Command pyinstaller -ErrorAction SilentlyContinue
$pyinstaller = if ($_pi) { $_pi.Source } else { $null }
$_py = Get-Command python -ErrorAction SilentlyContinue
$python = if ($_py) { $_py.Source } else { $null }

if (-not $pyinstaller) {
    Write-Host "ERROR: pyinstaller not found." -ForegroundColor Red
    Write-Host "  pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}

foreach ($pkg in @("onnxruntime", "onnx_tts_runtime", "sounddevice", "soundfile", "webview", "bottle", "psutil")) {
    & $python -c "import $pkg" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: '$pkg' is not installed." -ForegroundColor Red
        if ($pkg -eq "onnx_tts_runtime") {
            Write-Host "  pip install moss-tts-nano" -ForegroundColor Yellow
        } else {
            Write-Host "  pip install $pkg" -ForegroundColor Yellow
        }
        exit 1
    }
}

$modelDir     = "models\MOSS-TTS-Nano-100M-ONNX"
$tokenizerDir = "models\MOSS-Audio-Tokenizer-Nano-ONNX"

if (-not (Test-Path $modelDir)) {
    Write-Host "ERROR: TTS model not found at $modelDir" -ForegroundColor Red
    Write-Host "  huggingface-cli download OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX --local-dir $modelDir" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $tokenizerDir)) {
    Write-Host "ERROR: Audio tokenizer not found at $tokenizerDir" -ForegroundColor Red
    Write-Host "  huggingface-cli download OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX --local-dir $tokenizerDir" -ForegroundColor Yellow
    exit 1
}

Write-Host "Dependencies OK. Cleaning dist/ build/..." -ForegroundColor Cyan
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
& $pyinstaller --clean --noconfirm SpotterApp.spec

if ($LASTEXITCODE -eq 0) {
    $exe = Get-Item "dist\SpotterApp.exe" -ErrorAction SilentlyContinue
    $mb  = if ($exe) { [math]::Round($exe.Length / 1MB) } else { "?" }
    Write-Host "Done! dist\SpotterApp.exe ($mb MB)" -ForegroundColor Green
    Write-Host "NOTE: MOSS-TTS-Nano models are bundled — no internet needed on first run." -ForegroundColor Cyan
} else {
    Write-Host "Build failed! Exit code: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
```

---

## Task 8: Smoke test

**Files:**
- Create (temporary): `test_moss_tts.py` — удалить после прохождения теста

- [ ] **Шаг 1: Создать test_moss_tts.py**

```python
"""Minimal smoke test for MOSS-TTS-Nano integration. Delete after passing."""
import os, sys, time
sys.path.insert(0, ".")

# Simulate dev-mode paths
import config
config.DATA_DIR = os.path.dirname(os.path.abspath(__file__))
config.BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from new_tts.moss_tts import MossTTS
import soundfile as sf
import numpy as np

print("Loading MOSS-TTS-Nano...", flush=True)
tts = MossTTS()

for _ in range(120):
    if tts.is_ready or "MOSS-TTS:" in tts.status:
        break
    time.sleep(0.5)
    print(".", end="", flush=True)
print()

if not tts.is_ready:
    print(f"FAIL: {tts.status}")
    sys.exit(1)

print(f"OK: {tts.status}")
print(f"sample_rate={tts.sample_rate} Hz, channels={tts.channels}")

# Test synthesis
audio, sr = tts.synthesize("Привет, это тест голосового синтеза.")
if audio is None:
    print(f"FAIL synthesis: {tts.status}")
    sys.exit(1)

print(f"OK: audio shape={audio.shape}, sr={sr}")
assert audio.ndim == 2 and audio.shape[1] == 2, f"Expected stereo [N,2], got {audio.shape}"
assert sr == 48000, f"Expected 48000 Hz, got {sr}"

sf.write("test_moss.wav", audio, sr, subtype="PCM_16")
print("Saved: test_moss.wav")

# Test streaming
chunks = list(tts.synthesize_streaming("Машина первая лидирует. Разрыв растёт."))
assert len(chunks) > 0, "No chunks from synthesize_streaming"
print(f"OK: streaming returned {len(chunks)} chunks")

print("\nALL CHECKS PASSED")
```

- [ ] **Шаг 2: Запустить тест**

```powershell
python test_moss_tts.py
```

Ожидаемый результат:
```
Loading MOSS-TTS-Nano...
..(несколько точек)
OK: MOSS-TTS-Nano ready (CPU, ONNX)
sample_rate=48000 Hz, channels=2
OK: audio shape=(N, 2), sr=48000
Saved: test_moss.wav
OK: streaming returned 2 chunks
ALL CHECKS PASSED
```

- [ ] **Шаг 3: Убедиться, что GPU не используется**

Во время прогона теста:
```powershell
nvidia-smi --query-gpu=memory.used --format=csv,noheader
```

Ожидаемый результат: использование VRAM не должно расти (F1 25 забирает ~4-6 GB, TTS не добавляет).

- [ ] **Шаг 4: Проверить, что WAV корректный**

```powershell
python -c "
import soundfile as sf
info = sf.info('test_moss.wav')
print(f'Channels: {info.channels}, SR: {info.samplerate}, Duration: {info.duration:.1f}s')
assert info.channels == 2, 'Expected stereo'
assert info.samplerate == 48000, 'Expected 48kHz'
assert info.duration > 0.5, 'Audio too short'
print('WAV check PASSED')
"
```

Ожидаемый результат: `Channels: 2, SR: 48000, Duration: X.Xs` + `WAV check PASSED`

- [ ] **Шаг 5: Запустить app.pyw и проверить голос вживую**

```powershell
python app.pyw
```

В UI: открыть вкладку Voice → нажать TEST RADIO. Убедиться, что слышен голос.

- [ ] **Шаг 6: Очистить тестовые файлы**

```powershell
Remove-Item test_moss_tts.py, test_moss.wav -ErrorAction SilentlyContinue
```

---

## Если что-то пошло не так

### Проблема: `OnnxTtsRuntime` не принимает `model_dir` — ищет оба каталога в одной папке

Возможно, конструктор ожидает родительский каталог, содержащий оба `MOSS-TTS-Nano-100M-ONNX` и `MOSS-Audio-Tokenizer-Nano-ONNX`. В этом случае изменить в `moss_tts.py`:

```python
_TTS_MODEL_DIR = str(Path(config.BASE_DIR) / "models")
# и передавать:
OnnxTtsRuntime(model_dir=_TTS_MODEL_DIR, ...)
```

### Проблема: `voice=None` с `prompt_audio_path=None` вызывает ошибку

Добавить жёсткий fallback-голос:
```python
voice=None if ref_path else _FALLBACK_VOICE,
prompt_audio_path=ref_path,
# если всё равно падает — убрать `voice=None`, оставить только:
# voice=_FALLBACK_VOICE, prompt_audio_path=ref_path
```

### Проблема: `sentencepiece` не найден при сборке EXE

Добавить в SpotterApp.spec:
```python
tmp_ret = collect_all('sentencepiece')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
```

### Проблема: аудио моно вместо стерео (shape `[N]` вместо `[N, 2]`)

Код в `moss_tts.py` и `voice/tts.py` уже обрабатывает это через `np.column_stack([chunk, chunk])`.

---

## Обновить CONTEXT.md после завершения

После успешного прохождения Task 8 добавить в `CONTEXT.md` раздел «Голосовой движок» запись о MOSS-TTS-Nano, отметить Qwen3-TTS как удалённый, обновить таблицу технологий и список открытых задач.
