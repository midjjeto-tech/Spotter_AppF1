# TTS Latency Cache + Persona Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сократить задержку озвучки повторяющихся/шаблонных фраз почти до нуля через дисковый WAV-кэш, и дать персонам комментатора разные голоса Silero.

**Architecture:** Новый модуль `voice/cache.py` (`TTSCache`) хранит WAV по `sha1(text|speaker)` в `DATA_DIR/tts_cache/`. `voice/tts.py` проверяет кэш перед обращением к модели; при промахе генерирует, атомарно сохраняет в кэш, играет. Персона → спикер Silero через словарь `PERSONA_SPEAKER`, переключается `Voice.set_persona()`, вызывается из `core/engine.py` при смене настройки.

**Tech Stack:** Python 3.12, torch (CPU), Silero v4_ru, winsound, hashlib, os.

**Примечание по git:** проект не инициализирован как git-репозиторий (`git status` вне репо) — шаги коммита из шаблона пропущены. Если нужно — попросить пользователя `git init` отдельно.

**Примечание по тестам:** в проекте нет pytest/тестового фреймворка (только сторонние библиотеки в `.venv`, `whisper-main`, `Fast-F1-main` содержат свои тесты — это не наш код). Проверка — короткие `python -c` скрипты через venv-интерпретатор, как и описано в спеке.

---

### Task 1: `voice/cache.py` — TTSCache

**Files:**
- Create: `voice/cache.py`

- [ ] **Step 1: Написать `voice/cache.py`**

```python
"""
voice/cache.py
==============
Дисковый кэш сгенерированных WAV-файлов TTS.
Кэш-файл — это и есть файл воспроизведения: никакого отдельного шага
"сгенерировать во временный файл и удалить после игры" для повторных фраз.
"""

from __future__ import annotations

import hashlib
import os


class TTSCache:
    def __init__(self, cache_dir: str, max_files: int = 3000, max_mb: int = 300):
        self.cache_dir = cache_dir
        self.max_files = max_files
        self.max_bytes = max_mb * 1024 * 1024
        os.makedirs(self.cache_dir, exist_ok=True)

    def path_for(self, text: str, speaker: str) -> str:
        key = hashlib.sha1(f"{text}|{speaker}".encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{key}.wav")

    def evict_if_needed(self) -> None:
        """Удаляет самые старые (по mtime) файлы, если превышены лимиты."""
        try:
            entries = [
                (e.path, e.stat().st_mtime, e.stat().st_size)
                for e in os.scandir(self.cache_dir)
                if e.is_file()
            ]
        except OSError:
            return

        total_bytes = sum(size for _, _, size in entries)
        count = len(entries)
        if count <= self.max_files and total_bytes <= self.max_bytes:
            return

        entries.sort(key=lambda e: e[1])  # старые сначала
        for path, _, size in entries:
            if count <= self.max_files and total_bytes <= self.max_bytes:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            count -= 1
            total_bytes -= size
```

- [ ] **Step 2: Проверить `path_for` — детерминированность и зависимость от speaker**

Run:
```bash
cd "G:/Spotter App" && rm -rf _tmp_cache_test && \
".venv/Scripts/python.exe" -c "
from voice.cache import TTSCache
c = TTSCache('_tmp_cache_test')
p1 = c.path_for('hello', 'baya')
p2 = c.path_for('hello', 'baya')
p3 = c.path_for('hello', 'xenia')
print(p1 == p2, p1 != p3)
"
```
Expected output: `True True`

- [ ] **Step 3: Проверить `evict_if_needed` — вытеснение по лимиту файлов**

Run:
```bash
cd "G:/Spotter App" && \
".venv/Scripts/python.exe" -c "
import os, time
from voice.cache import TTSCache
c = TTSCache('_tmp_cache_test2', max_files=2, max_mb=300)
for i in range(3):
    p = os.path.join(c.cache_dir, f'f{i}.wav')
    open(p, 'wb').write(b'x' * 10)
    os.utime(p, (time.time() + i, time.time() + i))
c.evict_if_needed()
print(len(os.listdir('_tmp_cache_test2')))
"
```
Expected output: `2`

- [ ] **Step 4: Убрать тестовые папки**

Run:
```bash
cd "G:/Spotter App" && rm -rf _tmp_cache_test _tmp_cache_test2
```

---

### Task 2: `voice/tts.py` — интеграция кэша и `set_persona`

**Files:**
- Modify: `voice/tts.py` (полная замена содержимого — изменения затрагивают большую часть файла)

- [ ] **Step 1: Заменить весь файл `voice/tts.py`**

```python
"""
voice/tts.py
=============
Озвучка через Silero TTS v4_ru (CPU, русский язык).
Резерв — pyttsx3 (если установлен).
Воспроизведение через winsound — без subprocess, без CMD-окон, без кражи фокуса.
Сгенерированные фразы кэшируются на диск (voice/cache.py) — повтор фразы
воспроизводится мгновенно, без обращения к модели.

Зависимости: pip install torch
Модель: models/silero/v4_ru.pt (локальный файл, без сети)
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import wave

import config
from voice.cache import TTSCache
from commentator.templates import SIMPLE

_SILERO_SPEAKER     = "baya"   # дефолт / альтернативы: aidar, xenia, eugene, kseniya
_SILERO_SAMPLE_RATE = 48000    # v4_ru поддерживает 8000 / 24000 / 48000

PERSONA_SPEAKER = {
    "tv":    "baya",
    "hype":  "xenia",
    "calm":  "kseniya",
    "toxic": "aidar",
}


class Voice:
    def __init__(self, *_args, **_kwargs):
        self.silero_model        = None
        self._silero_sample_rate = None
        self.pyttsx3_engine      = None
        self.status_message      = "Инициализация Silero..."
        self._lock               = threading.Lock()
        self._current_speaker    = _SILERO_SPEAKER
        self._cache              = TTSCache(os.path.join(config.DATA_DIR, "tts_cache"))
        self._configure_stdout()
        threading.Thread(target=self._init_silero, daemon=True, name="silero-load").start()

    # ------------------------------------------------------------------ #
    # Инициализация                                                        #
    # ------------------------------------------------------------------ #

    def _configure_stdout(self):
        stdout = getattr(sys, "stdout", None)
        encoding = getattr(stdout, "encoding", None)
        if encoding is None or encoding.lower() != "utf-8":
            try:
                if stdout is not None:
                    stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

    def _init_silero(self):
        try:
            import torch

            torch.set_num_threads(2)
            device = torch.device("cpu")

            current_dir  = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            model_path   = os.path.join(project_root, "models", "silero", "v4_ru.pt")

            if not os.path.exists(model_path):
                model_path = os.path.join("models", "silero", "v4_ru.pt")
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Silero model not found: {model_path}")

            model = torch.package.PackageImporter(model_path).load_pickle("tts_models", "model")
            model.to(device)

            self.silero_model        = model
            self._silero_sample_rate = _SILERO_SAMPLE_RATE
            self.status_message = f"Silero v4_ru ready (offline, speaker: {self._current_speaker})"
            threading.Thread(target=self._prewarm_cache, daemon=True, name="tts-prewarm").start()
        except Exception as exc:
            self.status_message = f"Silero: {exc}"
            self._init_pyttsx3()

    def _init_pyttsx3(self):
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
        except ImportError:
            self.status_message = f"{self.status_message} | pyttsx3 not installed"
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"

    def _prewarm_cache(self):
        """Кэширует фразы без подстановок (старт, финиш, спид-трэп и т.п.)
        для текущего спикера в фоне. Best-effort — сбой не валит инициализацию."""
        try:
            for phrases in SIMPLE.values():
                for phrase in phrases:
                    if "{" in phrase:
                        continue
                    if self.silero_model is None:
                        return
                    self._ensure_cached(phrase.strip(), self._current_speaker)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Публичный интерфейс (не менять — engine.py зависит от этих полей)   #
    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self.silero_model is not None or self.pyttsx3_engine is not None

    @property
    def engine_name(self) -> str:
        if self.silero_model is not None:
            return "Silero"
        if self.pyttsx3_engine is not None:
            return "pyttsx3"
        return "Нет"

    def set_persona(self, persona: str) -> None:
        self._current_speaker = PERSONA_SPEAKER.get(persona, _SILERO_SPEAKER)

    def say(self, text: str) -> bool:
        """Запускает озвучку в фоновом потоке. Возвращает True сразу."""
        if not text or not text.strip() or not self.is_available:
            return False
        threading.Thread(target=self._say_bg, args=(text,), daemon=True, name="tts-play").start()
        return True

    def test_say(self, text: str) -> bool:
        return self.say(text)

    # ------------------------------------------------------------------ #
    # Фоновое воспроизведение                                              #
    # ------------------------------------------------------------------ #

    def _say_bg(self, text: str):
        if not self._lock.acquire(blocking=False):
            return  # уже играет — пропускаем устаревший комментарий
        try:
            if self.silero_model is not None:
                self._say_silero(text)
            else:
                self._say_pyttsx3(text)
        finally:
            self._lock.release()

    def _say_silero(self, text: str) -> bool:
        path = self._ensure_cached(text.strip(), self._current_speaker)
        if path is None:
            return False
        return self._winsound_play(path)

    def _ensure_cached(self, text: str, speaker: str) -> str | None:
        """Путь к WAV для text+speaker. Генерирует и кэширует при промахе."""
        cache_path = self._cache.path_for(text, speaker)
        if os.path.exists(cache_path):
            return cache_path

        try:
            import torch
            with torch.no_grad():
                audio = self.silero_model.apply_tts(
                    text=text,
                    speaker=speaker,
                    sample_rate=self._silero_sample_rate,
                    put_accent=True,
                    put_yo=True,
                )
        except Exception as exc:
            self.status_message = f"Silero: {exc}"
            return None

        path = self._write_wav(audio, cache_path, self._silero_sample_rate)
        if path is not None:
            self._cache.evict_if_needed()
        return path

    def _write_wav(self, audio, final_path: str, sample_rate: int) -> str | None:
        """torch.Tensor (float32, 1-D) → WAV во временный файл → атомарный
        перенос в кэш. При сбое переноса возвращает путь к tempfile —
        воспроизведение не падает, кэш просто не пополняется в этот раз."""
        try:
            pcm = (audio.clamp(-1.0, 1.0) * 32767).short().numpy()
        except Exception as exc:
            self.status_message = f"Конвертация аудио: {exc}"
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name

        try:
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm.tobytes())
        except Exception as exc:
            self.status_message = f"Запись WAV: {exc}"
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return None

        try:
            os.replace(tmp_path, final_path)
            return final_path
        except OSError as exc:
            self.status_message = f"Кэш TTS: {exc}"
            return tmp_path

    def _winsound_play(self, wav_path: str) -> bool:
        is_cached = os.path.dirname(os.path.abspath(wav_path)) == os.path.abspath(self._cache.cache_dir)
        try:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(
                    wav_path,
                    winsound.SND_FILENAME | winsound.SND_NODEFAULT,
                )
            else:
                import time
                with wave.open(wav_path, "rb") as wf:
                    duration = wf.getnframes() / float(wf.getframerate())
                time.sleep(max(duration, 0.1))
            return True
        except Exception as exc:
            self.status_message = f"Воспроизведение: {exc}"
            if is_cached:
                try:
                    os.remove(wav_path)  # битый кэш-файл — перегенерируем в следующий раз
                except OSError:
                    pass
            return False
        finally:
            if not is_cached:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    # pyttsx3 (резерв)                                                     #
    # ------------------------------------------------------------------ #

    def _say_pyttsx3(self, text: str) -> bool:
        try:
            self.pyttsx3_engine.say(text)
            self.pyttsx3_engine.runAndWait()
            return True
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"
            return False
```

- [ ] **Step 2: Проверить, что модуль импортируется без ошибок синтаксиса**

Run:
```bash
cd "G:/Spotter App" && ".venv/Scripts/python.exe" -c "import ast; ast.parse(open('voice/tts.py', encoding='utf-8').read()); print('OK')"
```
Expected output: `OK`

- [ ] **Step 3: Проверить `set_persona` меняет спикер (без реальной генерации — мок модели)**

Run:
```bash
cd "G:/Spotter App" && ".venv/Scripts/python.exe" -c "
import sys, types
sys.modules['pyttsx3'] = types.ModuleType('pyttsx3')  # на случай отсутствия пакета
from voice.tts import Voice, PERSONA_SPEAKER, _SILERO_SPEAKER
v = Voice.__new__(Voice)  # без запуска __init__/потоков
v._current_speaker = _SILERO_SPEAKER
v.set_persona('hype')
print(v._current_speaker == PERSONA_SPEAKER['hype'])
v.set_persona('unknown_persona')
print(v._current_speaker == _SILERO_SPEAKER)
"
```
Expected output:
```
True
True
```

---

### Task 3: `core/engine.py` — связать персону с голосом

**Files:**
- Modify: `core/engine.py:47-49` (инициализация)
- Modify: `core/engine.py:115-118` (apply_settings)

- [ ] **Step 1: Задать спикер при старте**

В `core/engine.py`, заменить:
```python
        self.voice = Voice()
        self.ai = AIProvider(config.ANTHROPIC_API_KEY, config.LLM_MODEL)
        self.commentator = Commentator(self.ai, config.PERSONA)
```
на:
```python
        self.voice = Voice()
        self.voice.set_persona(config.PERSONA)
        self.ai = AIProvider(config.ANTHROPIC_API_KEY, config.LLM_MODEL)
        self.commentator = Commentator(self.ai, config.PERSONA)
```

- [ ] **Step 2: Переключать спикер при смене персоны в настройках**

В `core/engine.py`, заменить:
```python
        if "persona" in settings:
            self.commentator.persona = settings["persona"]
            with self.state_lock:
                self.state["persona"] = settings["persona"]
```
на:
```python
        if "persona" in settings:
            self.commentator.persona = settings["persona"]
            self.voice.set_persona(settings["persona"])
            with self.state_lock:
                self.state["persona"] = settings["persona"]
```

- [ ] **Step 3: Проверить, что `core/engine.py` импортируется без синтаксических ошибок**

Run:
```bash
cd "G:/Spotter App" && ".venv/Scripts/python.exe" -c "import ast; ast.parse(open('core/engine.py', encoding='utf-8').read()); print('OK')"
```
Expected output: `OK`

---

### Task 4: Сквозная ручная проверка (требует установленных torch + локальной модели)

**Files:** нет изменений, только проверка поведения.

- [ ] **Step 1: Запустить приложение**

Run: `python app.pyw` (или через текущий способ запуска, если отличается)

- [ ] **Step 2: Подождать ~5-15 сек (загрузка модели + прогрев кэша), затем проверить, что кэш заполнился**

Run:
```bash
ls "G:/Spotter App/tts_cache"
```
(в dev-режиме `config.DATA_DIR` = корень проекта, см. `config.py:10-14`)
Ожидается: несколько `.wav`-файлов (по числу фраз без `{}` в `templates.SIMPLE`).

- [ ] **Step 3: В UI нажать «Проверить TTS» дважды с одинаковой фразой (через `/api/test_voice`, текст фиксирован — "Голос Spotter App работает.")**

Ожидается: второй вызов после первого — звук должен начаться заметно быстрее (фраза одинаковая → второй раз читается из кэша).

- [ ] **Step 4: Сменить персону в UI (Настройки → Персона) и снова нажать «Проверить TTS»**

Ожидается: голос звучит другим спикером Silero (другой тембр), `voice_status` в `/api/state` отражает текущий движок без ошибок.

- [ ] **Step 5: Вручную удалить один файл из `tts_cache/` во время работы приложения, повторить «Проверить TTS» с фразой, которая была в этом файле**

Ожидается: приложение не падает, фраза генерируется заново и кэшируется повторно (можно проверить, что файл с тем же hash появился снова).

---

## Итог

После выполнения всех тасков:
- `voice/cache.py` — новый модуль кэша.
- `voice/tts.py` — кэш встроен в `_say_silero`, добавлен `set_persona`, прогрев при старте.
- `core/engine.py` — персона из настроек/конфига применяется и к голосу, не только к тексту.
