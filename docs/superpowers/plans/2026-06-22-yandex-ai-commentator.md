# Yandex AI-комментатор — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить TTS/текст-пайплайн (Piper + Anthropic) на ИИ-комментатора Yandex (YandexGPT + SpeechKit), сохранив гибрид с шаблонами и Piper как офлайн-резерв.

**Architecture:** Двухпоточный движок не трогаем. Сеть к Яндексу — отдельный пакет `yandex_ai/` с выделенным asyncio-loop в своём потоке (общий `YandexClient` для GPT и TTS). Текст и голос подключаются за теми же интерфейсами (`AIProvider.generate`, `Voice.say`), что движок уже вызывает. При сбое/без ключа — мягкий откат на шаблоны + Piper.

**Tech Stack:** Python 3.12 (системный интерпретатор), `aiohttp` (async HTTP), `numpy`/`sounddevice`/`soundfile` (уже есть), DPAPI через `ctypes` (без pywin32), `pytest` (новый dev-dep).

**Спека:** `docs/superpowers/specs/2026-06-22-yandex-ai-commentator-design.md`

---

## ВАЖНЫЕ ЗАМЕЧАНИЯ ПЕРЕД СТАРТОМ

1. **Интерпретатор:** приложение работает на **системном Python 3.12**
   (`C:\Users\Artem\AppData\Local\Programs\Python\Python312\python.exe`), там весь стек
   (bottle/pywebview/sounddevice/soundfile/piper). Все команды используют `py -3.12`.
   `.venv` — стале­е окружение для PyInstaller, **не трогаем**.
2. **Git:** проект **НЕ под git** (CONTEXT.md). Шаги «Checkpoint» — это верификационные
   ворота (прогон тестов). Коммит-команды даны опционально: выполнять, только если
   пользователь сам инициализировал git (спросить отдельно). Не запускать `git init` без
   разрешения.
3. **Кодировка вывода:** в shell использовать UTF-8; кириллица в коде — только в строковых
   литералах (как в существующих файлах). НЕ добавлять кириллицу в `build.ps1` (ломает CP1251).
4. **Стоимость:** YandexGPT и SpeechKit платные. Smoke-тесты с реальным ключом (Task 13)
   запускать осознанно. Юнит-тесты сети не делают (моки).

---

## File Structure

**Новые файлы:**
- `pytest.ini` — конфиг тестов (pythonpath, testpaths).
- `tests/__init__.py` — пустой.
- `tests/conftest.py` — общие фикстуры (tmp creds path).
- `yandex_ai/__init__.py` — пустой package marker.
- `yandex_ai/voices.py` — каталог голосов + `resolve(persona, overrides)`.
- `yandex_ai/credentials.py` — `Credentials`, DPAPI(ctypes) шифрование, load/save/clear, auth_header, mask.
- `yandex_ai/client.py` — `YandexClient`: loop-поток, aiohttp-сессия, `submit`, `post_json`/`post_form`, `validate`.
- `yandex_ai/gpt.py` — `YandexGPT`: `acomplete` (async), `generate` (sync-обёртка).
- `yandex_ai/speech.py` — `YandexSpeech`: `asynthesize` (async, LPCM→numpy), `synthesize` (sync-обёртка).
- `tests/test_voices.py`, `tests/test_credentials.py`, `tests/test_client.py`, `tests/test_gpt.py`, `tests/test_speech.py`, `tests/test_ai_provider.py`, `tests/test_queue_priority.py`, `tests/test_voice_cache_key.py`, `tests/test_engine_settings.py`
- `tests/smoke_yandex.py` — ручной smoke с реальным ключом (не pytest).

**Изменяемые:** `config.py`, `commentator/ai_provider.py`, `new_tts/queue_handler.py`,
`voice/tts.py`, `core/engine.py`, `web_server.py`, `index.html`, `requirements.txt`,
`CONTEXT.md`.

**Без изменений:** `commentator/brain.py`, `commentator/personas.py`, `commentator/templates.py`,
`voice/cache.py`, `voice/radio_fx.py`, `new_tts/piper_tts.py`, `core/telemetry.py`,
`core/packets.py`, `core/race_state.py`, `analytics/*`, `app.pyw`.

> Примечание по спеке: `client.validate()` возвращает **3-кортеж** `(ok, code, message)`
> (уточнение §5 ради единых кодов §11). `acomplete()` **пробрасывает** исключения (для
> классификации в validate); `generate()` их глотает → `None`. GPT-запрос — **не-стриминговый**
> (для фраз ≤20 слов выигрыш стриминга ничтожен; non-stream проще/надёжнее; стриминг —
> задокументированный будущий флаг). Prewarm кэша — **только текущая персона** (контроль
> стоимости).

---

## Task 0: Dev-окружение и каркас тестов

**Files:**
- Create: `pytest.ini`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Установить зависимости**

Run:
```bash
py -3.12 -m pip install aiohttp pytest
```
Expected: `Successfully installed aiohttp-... pytest-...`

- [ ] **Step 2: Создать `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 3: Создать `tests/__init__.py`** (пустой файл)

```python
```

- [ ] **Step 4: Создать `tests/conftest.py`**

```python
"""Общие фикстуры тестов Yandex-комментатора."""
import os
import sys

import pytest

# Гарантируем, что корень проекта в sys.path (config, yandex_ai, ...)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_creds(tmp_path, monkeypatch):
    """Перенаправляет файл креденшелов в tmp и возвращает путь."""
    import config
    path = os.path.join(str(tmp_path), "yandex_creds.json")
    monkeypatch.setattr(config, "YANDEX_CREDS_FILE", path, raising=False)
    return path
```

- [ ] **Step 5: Проверить, что pytest стартует (тестов ещё нет — это нормально)**

Run: `py -3.12 -m pytest`
Expected: `no tests ran` (или collected 0 items), без ошибок импорта.

- [ ] **Step 6: Checkpoint** — окружение готово. (Опц. коммит, если git есть.)

---

## Task 1: `config.py` — константы Yandex

**Files:**
- Modify: `config.py` (добавить в конец)

- [ ] **Step 1: Добавить блок в конец `config.py`**

```python

# --- Yandex Cloud (AI-комментатор) ---
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
YANDEX_GPT_MODEL = "yandexgpt-lite"          # gpt://<folder>/yandexgpt-lite/latest
YANDEX_TTS_SAMPLE_RATE = 48000               # LPCM 48 kHz mono
YANDEX_GPT_CONNECT_TIMEOUT = 2.0
YANDEX_GPT_TOTAL_TIMEOUT = 6.0
YANDEX_TTS_CONNECT_TIMEOUT = 2.0
YANDEX_TTS_TOTAL_TIMEOUT = 5.0
YANDEX_CREDS_FILE = os.path.join(DATA_DIR, "yandex_creds.json")
YANDEX_PREWARM = False                        # прогрев кэша Yandex на старте (платно, опц.)
```

- [ ] **Step 2: Проверить импорт**

Run: `py -3.12 -c "import config; print(config.YANDEX_GPT_URL, config.YANDEX_CREDS_FILE)"`
Expected: печатает URL и путь к creds-файлу, без ошибок.

- [ ] **Step 3: Checkpoint.**

---

## Task 2: `yandex_ai/voices.py` — каталог и резолвер голосов

**Files:**
- Create: `yandex_ai/__init__.py` (пустой)
- Create: `yandex_ai/voices.py`
- Test: `tests/test_voices.py`

- [ ] **Step 1: Написать падающий тест `tests/test_voices.py`**

```python
from yandex_ai import voices


def test_resolve_default_tv():
    assert voices.resolve("tv") == {"voice": "filipp", "emotion": "neutral", "speed": 1.0}


def test_resolve_unknown_persona_falls_back_to_tv():
    assert voices.resolve("nope")["voice"] == "filipp"


def test_resolve_applies_partial_override():
    out = voices.resolve("tv", {"tv": {"voice": "jane"}})
    assert out["voice"] == "jane"
    assert out["emotion"] == "neutral"  # не затёрто


def test_resolve_ignores_unknown_keys():
    out = voices.resolve("tv", {"tv": {"bogus": 1}})
    assert "bogus" not in out


def test_catalog_has_default_voices():
    for spec in voices.DEFAULT_PERSONA_VOICE.values():
        assert spec["voice"] in voices.AVAILABLE_VOICES
```

- [ ] **Step 2: Запустить — упадёт (нет модуля)**

Run: `py -3.12 -m pytest tests/test_voices.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yandex_ai'`.

- [ ] **Step 3: Создать `yandex_ai/__init__.py`** (пустой)

```python
```

- [ ] **Step 4: Создать `yandex_ai/voices.py`**

```python
"""Каталог голосов Yandex SpeechKit + резолвер персона -> (voice, emotion, speed).

Маппинг конфигурируемый: дефолты ниже переопределяются пользовательскими оверрайдами
(приходят через настройки UI). Матрица emotion ниже — ориентировочная, точная поддержка
подтверждается мелким TTS-пробом на этапе интеграции.
"""
from __future__ import annotations

# voice -> поддерживаемые эмоции (для UI-пикера).
AVAILABLE_VOICES: dict[str, list[str]] = {
    "filipp":    ["neutral"],
    "ermil":     ["neutral", "good"],
    "alena":     ["neutral", "good"],
    "zahar":     ["neutral", "good", "evil"],
    "jane":      ["neutral", "good", "evil"],
    "omazh":     ["neutral", "evil"],
    "madirus":   ["neutral"],
    "dasha":     ["neutral", "good", "friendly"],
    "julia":     ["neutral"],
    "lera":      ["neutral"],
    "marina":    ["neutral", "whisper"],
    "alexander": ["neutral"],
    "kirill":    ["neutral"],
    "anton":     ["neutral"],
}

DEFAULT_PERSONA_VOICE: dict[str, dict] = {
    "tv":    {"voice": "filipp", "emotion": "neutral", "speed": 1.0},
    "hype":  {"voice": "ermil",  "emotion": "good",    "speed": 1.1},
    "calm":  {"voice": "alena",  "emotion": "neutral", "speed": 0.95},
    "toxic": {"voice": "zahar",  "emotion": "evil",    "speed": 1.0},
}

_ALLOWED_KEYS = ("voice", "emotion", "speed")


def resolve(persona: str, overrides: dict | None = None) -> dict:
    """Вернуть {voice, emotion, speed} для персоны с учётом частичных оверрайдов.

    overrides — dict вида {"tv": {"voice": "jane"}}. Неизвестная персона -> дефолт 'tv'.
    Неизвестные ключи в оверрайде игнорируются.
    """
    base = dict(DEFAULT_PERSONA_VOICE.get(persona, DEFAULT_PERSONA_VOICE["tv"]))
    if overrides and isinstance(overrides.get(persona), dict):
        base.update({k: v for k, v in overrides[persona].items() if k in _ALLOWED_KEYS})
    return base
```

- [ ] **Step 5: Запустить — должно пройти**

Run: `py -3.12 -m pytest tests/test_voices.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Checkpoint.**

---

## Task 3: `yandex_ai/credentials.py` — хранение и шифрование ключа

**Files:**
- Create: `yandex_ai/credentials.py`
- Test: `tests/test_credentials.py`

- [ ] **Step 1: Написать падающий тест `tests/test_credentials.py`**

```python
import sys

import pytest

from yandex_ai import credentials as c
from yandex_ai.credentials import Credentials


def test_auth_header_api_key():
    creds = Credentials(api_key="AQVN123", folder_id="fld", auth_mode="api_key")
    assert c.auth_header(creds) == {"Authorization": "Api-Key AQVN123"}


def test_auth_header_iam():
    creds = Credentials(api_key="t0ken", folder_id="fld", auth_mode="iam")
    assert c.auth_header(creds) == {"Authorization": "Bearer t0ken"}


def test_mask():
    assert c.mask("ABCDEFGH").endswith("EFGH")
    assert c.mask("ABCDEFGH").count("•") == 4
    assert c.mask("") == ""


def test_save_load_roundtrip(tmp_creds):
    creds = Credentials(api_key="secret-key-1234", folder_id="b1gfolder", auth_mode="api_key")
    c.save(creds)
    loaded = c.load()
    assert loaded is not None
    assert loaded.api_key == "secret-key-1234"
    assert loaded.folder_id == "b1gfolder"
    assert loaded.auth_mode == "api_key"


def test_load_missing_returns_none(tmp_creds):
    assert c.load() is None


def test_clear(tmp_creds):
    c.save(Credentials("k", "f"))
    c.clear()
    assert c.load() is None


def test_plaintext_fallback_when_dpapi_unavailable(tmp_creds, monkeypatch):
    monkeypatch.setattr(c, "dpapi_encrypt", lambda s: None)
    c.save(Credentials("plainkey", "fld"))
    import json
    with open(tmp_creds, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["encrypted"] is False
    assert raw["api_key"] == "plainkey"
    # читается даже без DPAPI
    loaded = c.load()
    assert loaded.api_key == "plainkey"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI только Windows")
def test_dpapi_roundtrip_windows():
    enc = c.dpapi_encrypt("super-secret")
    assert enc is not None and enc != "super-secret"
    assert c.dpapi_decrypt(enc) == "super-secret"
```

- [ ] **Step 2: Запустить — упадёт**

Run: `py -3.12 -m pytest tests/test_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError` / нет `credentials`.

- [ ] **Step 3: Создать `yandex_ai/credentials.py`**

```python
"""Хранение и валидация Yandex-ключа.

Шифрование — Windows DPAPI через ctypes (crypt32.dll), без зависимости от pywin32.
Привязано к Windows-аккаунту: файл бесполезен на другой машине/юзере. Если DPAPI
недоступен — плейнтекст-фолбэк с предупреждением в лог.
"""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass

import config

_log = logging.getLogger(__name__)


@dataclass
class Credentials:
    api_key: str
    folder_id: str
    auth_mode: str = "api_key"   # "api_key" | "iam"


# ----------------------------- DPAPI (ctypes) ----------------------------- #

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_in(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, int(blob.cbData))


def dpapi_encrypt(plaintext: str) -> str | None:
    """DPAPI-шифр строки -> base64. None, если DPAPI недоступен."""
    try:
        blob_in = _blob_in(plaintext.encode("utf-8"))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            enc = _blob_bytes(blob_out)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return base64.b64encode(enc).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — DPAPI может отсутствовать (не Windows и т.п.)
        _log.warning("DPAPI encrypt unavailable: %s", exc)
        return None


def dpapi_decrypt(b64: str) -> str | None:
    try:
        blob_in = _blob_in(base64.b64decode(b64.encode("ascii")))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            dec = _blob_bytes(blob_out)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return dec.decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        _log.warning("DPAPI decrypt failed: %s", exc)
        return None


# ----------------------------- persistence -------------------------------- #

def save(creds: Credentials) -> None:
    enc = dpapi_encrypt(creds.api_key)
    payload: dict = {"folder_id": creds.folder_id, "auth_mode": creds.auth_mode}
    if enc is not None:
        payload["api_key_enc"] = enc
        payload["encrypted"] = True
    else:
        payload["api_key"] = creds.api_key
        payload["encrypted"] = False
        _log.warning("Yandex creds saved WITHOUT encryption (DPAPI unavailable)")
    path = config.YANDEX_CREDS_FILE
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def load() -> Credentials | None:
    path = config.YANDEX_CREDS_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if payload.get("encrypted"):
        api_key = dpapi_decrypt(payload.get("api_key_enc", ""))
    else:
        api_key = payload.get("api_key", "")
    if not api_key or not payload.get("folder_id"):
        return None
    return Credentials(api_key=api_key,
                       folder_id=payload["folder_id"],
                       auth_mode=payload.get("auth_mode", "api_key"))


def clear() -> None:
    try:
        os.remove(config.YANDEX_CREDS_FILE)
    except FileNotFoundError:
        pass


# ------------------------------- helpers ---------------------------------- #

def auth_header(creds: Credentials) -> dict:
    if creds.auth_mode == "iam":
        return {"Authorization": f"Bearer {creds.api_key}"}
    return {"Authorization": f"Api-Key {creds.api_key}"}


def mask(secret: str) -> str:
    if not secret:
        return ""
    return ("•" * max(0, len(secret) - 4)) + secret[-4:]
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `py -3.12 -m pytest tests/test_credentials.py -v`
Expected: PASS (на Windows — 8 passed; на не-Windows DPAPI-тест skipped).

- [ ] **Step 5: Checkpoint.**

---

## Task 4: `yandex_ai/client.py` — asyncio-loop, сессия, валидация

**Files:**
- Create: `yandex_ai/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: Написать падающий тест `tests/test_client.py`**

```python
import aiohttp
import pytest

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials


def _client():
    return YandexClient(Credentials("k", "fld", "api_key"))


def test_submit_runs_coroutine():
    cl = _client()
    cl.start()
    try:
        async def add():
            return 40 + 2
        assert cl.submit(add()).result(timeout=3) == 42
    finally:
        cl.stop()


def test_headers_include_auth():
    cl = _client()
    h = cl.headers({"X-Test": "1"})
    assert h["Authorization"] == "Api-Key k"
    assert h["X-Test"] == "1"


def test_validate_invalid_key(monkeypatch):
    cl = _client()
    cl.start()
    try:
        req = aiohttp.RequestInfo(url="http://x", method="POST",
                                  headers=aiohttp.typedefs.CIMultiDict(), real_url="http://x")

        async def boom(*a, **k):
            raise aiohttp.ClientResponseError(req, (), status=401)

        monkeypatch.setattr(cl, "post_json", boom)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_CRED_INVALID"
    finally:
        cl.stop()


def test_validate_network_error(monkeypatch):
    cl = _client()
    cl.start()
    try:
        async def boom(*a, **k):
            raise aiohttp.ClientConnectionError("dns")

        monkeypatch.setattr(cl, "post_json", boom)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_NETWORK_ERROR"
    finally:
        cl.stop()


def test_validate_success(monkeypatch):
    cl = _client()
    cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "ок"}}]}}

        async def fake_form(*a, **k):
            return b"\x00\x00\x01\x00"

        monkeypatch.setattr(cl, "post_json", fake_json)
        monkeypatch.setattr(cl, "post_form", fake_form)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is True and code == "OK"
    finally:
        cl.stop()
```

- [ ] **Step 2: Запустить — упадёт**

Run: `py -3.12 -m pytest tests/test_client.py -v`
Expected: FAIL — нет `yandex_ai.client`.

- [ ] **Step 3: Создать `yandex_ai/client.py`**

```python
"""Общий клиент Yandex Cloud: asyncio-loop в выделенном потоке + aiohttp-сессия.

Потоковые вызыватели подают корутины через submit() и ждут future.result(timeout=...).
Блокируется только их собственный поток — поток телеметрии/UI не затрагивается.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading

import aiohttp

from yandex_ai import credentials as creds_mod
from yandex_ai.credentials import Credentials

_log = logging.getLogger(__name__)


class YandexClient:
    def __init__(self, creds: Credentials):
        self._creds = creds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ready = threading.Event()

    # ------------------------------ lifecycle ----------------------------- #
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="yandex-loop")
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            _log.error("YandexClient loop did not start in time")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._session = aiohttp.ClientSession()
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def stop(self) -> None:
        if self._loop is None:
            return
        async def _close():
            if self._session:
                await self._session.close()
        try:
            asyncio.run_coroutine_threadsafe(_close(), self._loop).result(timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    def submit(self, coro) -> concurrent.futures.Future:
        if self._loop is None:
            raise RuntimeError("YandexClient not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ------------------------------- helpers ------------------------------ #
    @property
    def folder_id(self) -> str:
        return self._creds.folder_id

    def headers(self, extra: dict | None = None) -> dict:
        h = dict(creds_mod.auth_header(self._creds))
        if extra:
            h.update(extra)
        return h

    async def post_json(self, url: str, payload: dict, *, connect: float, total: float,
                        extra_headers: dict | None = None) -> dict:
        timeout = aiohttp.ClientTimeout(total=total, connect=connect)
        headers = self.headers({"Content-Type": "application/json", **(extra_headers or {})})
        async with self._session.post(url, json=payload, headers=headers,
                                      timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post_form(self, url: str, data: dict, *, connect: float, total: float) -> bytes:
        timeout = aiohttp.ClientTimeout(total=total, connect=connect)
        async with self._session.post(url, data=data, headers=self.headers(),
                                      timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.read()

    # ------------------------------ validate ------------------------------ #
    async def validate(self) -> tuple[bool, str, str]:
        """(ok, code, message). Дешёвые пробы GPT и TTS."""
        from yandex_ai.gpt import YandexGPT
        from yandex_ai.speech import YandexSpeech
        # --- GPT ---
        try:
            gpt = YandexGPT(self)
            txt = await gpt.acomplete("Ты тестовый ассистент.", "пинг", max_tokens=1)
            if not txt:
                return (False, "YANDEX_CRED_INVALID", "GPT не вернул ответ")
        except aiohttp.ClientResponseError as e:
            if e.status in (401, 403):
                return (False, "YANDEX_CRED_INVALID", "Ключ или Folder ID неверны")
            if e.status == 429:
                return (False, "YANDEX_RATE_LIMIT", "Превышен лимит запросов")
            return (False, "YANDEX_NETWORK_ERROR", f"HTTP {e.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return (False, "YANDEX_NETWORK_ERROR", "Нет связи с Yandex Cloud")
        # --- TTS ---
        try:
            sp = YandexSpeech(self)
            pcm = await sp.asynthesize("тест", "filipp", "neutral", 1.0)
            if pcm is None or len(pcm) == 0:
                return (False, "YANDEX_TTS_ERROR", "SpeechKit не вернул аудио")
        except Exception:  # noqa: BLE001
            return (False, "YANDEX_TTS_ERROR", "SpeechKit недоступен")
        return (True, "OK", "Yandex подключён")
```

- [ ] **Step 4: Запустить — пройдёт** (использует `gpt.py`/`speech.py` только в `validate`,
  а те тесты мокают `post_json`/`post_form`, поэтому реальные модули нужны — они появятся в
  Task 5/6. Поэтому **этот тест-файл запускать после Task 6**, либо временно пропустить
  `test_validate_*`.)

> **Порядок:** реализуй Task 5 и Task 6, затем вернись и прогони `tests/test_client.py`.
> До этого `test_submit_runs_coroutine` и `test_headers_include_auth` уже проходят:
> Run: `py -3.12 -m pytest tests/test_client.py -k "submit or headers" -v` → PASS.

- [ ] **Step 5: Checkpoint.**

---

## Task 5: `yandex_ai/gpt.py` — генерация текста

**Files:**
- Create: `yandex_ai/gpt.py`
- Test: `tests/test_gpt.py`

- [ ] **Step 1: Написать падающий тест `tests/test_gpt.py`**

```python
import pytest

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.gpt import YandexGPT


def _client():
    return YandexClient(Credentials("k", "fld"))


@pytest.mark.asyncio_skip  # без плагина asyncio — гоняем через client.submit ниже
def _unused():
    pass


def test_acomplete_parses_text(monkeypatch):
    cl = _client(); cl.start()
    try:
        captured = {}

        async def fake_json(url, payload, **kw):
            captured["url"] = url
            captured["payload"] = payload
            return {"result": {"alternatives": [{"message": {"text": "  Поехали!  "}}]}}

        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        txt = cl.submit(gpt.acomplete("sys", "user")).result(timeout=3)
        assert txt == "Поехали!"
        assert captured["payload"]["modelUri"] == "gpt://fld/yandexgpt-lite/latest"
        roles = [m["role"] for m in captured["payload"]["messages"]]
        assert roles == ["system", "user"]
    finally:
        cl.stop()


def test_acomplete_empty_alternatives_returns_none(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": []}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert cl.submit(gpt.acomplete("s", "u")).result(timeout=3) is None
    finally:
        cl.stop()


def test_generate_swallows_errors(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def boom(*a, **k):
            raise RuntimeError("net down")
        monkeypatch.setattr(cl, "post_json", boom)
        gpt = YandexGPT(cl)
        # generate (sync) не должен бросать — возвращает None
        assert gpt.generate({"event_code": "OVTK"}, "tv") is None
    finally:
        cl.stop()


def test_generate_returns_phrase(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "Обгон!"}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate({"event_code": "OVTK"}, "tv") == "Обгон!"
    finally:
        cl.stop()
```

(Заметка: маркер `asyncio_skip` — это no-op имя, чтобы не тянуть `pytest-asyncio`; реальные
корутины гоняются через `cl.submit(...).result()`. Удали функцию `_unused`, если линтер
ругается.)

- [ ] **Step 2: Запустить — упадёт**

Run: `py -3.12 -m pytest tests/test_gpt.py -v`
Expected: FAIL — нет `yandex_ai.gpt`.

- [ ] **Step 3: Создать `yandex_ai/gpt.py`**

```python
"""YandexGPT: генерация коротких реплик комментатора.

acomplete() — низкоуровневая async-корутина, ПРОБРАСЫВАЕТ исключения (для классификации
в client.validate). generate() — синхронная обёртка для brain.py/ai_provider, исключения
ГЛОТАЕТ и возвращает None (тогда brain уходит в шаблоны).
Запрос НЕ-стриминговый: для фраз <=20 слов выигрыш стриминга ничтожен.
"""
from __future__ import annotations

import logging

import config
from commentator.personas import system_prompt

_log = logging.getLogger(__name__)


class YandexGPT:
    def __init__(self, client, model: str | None = None):
        self._client = client
        self._model = model or config.YANDEX_GPT_MODEL

    async def acomplete(self, system: str, user: str,
                        max_tokens: int = 100, temperature: float = 0.6) -> str | None:
        payload = {
            "modelUri": f"gpt://{self._client.folder_id}/{self._model}/latest",
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),
            },
            "messages": [
                {"role": "system", "text": system},
                {"role": "user", "text": user},
            ],
        }
        data = await self._client.post_json(
            config.YANDEX_GPT_URL, payload,
            connect=config.YANDEX_GPT_CONNECT_TIMEOUT,
            total=config.YANDEX_GPT_TOTAL_TIMEOUT,
            extra_headers={"x-folder-id": self._client.folder_id},
        )
        alts = data.get("result", {}).get("alternatives", [])
        if not alts:
            return None
        text = alts[0].get("message", {}).get("text", "").strip()
        return text or None

    def generate(self, event: dict, persona: str,
                 analytics_context: str | None = None) -> str | None:
        user = f"Событие в гонке F1 (с именами и командами): {event}. Прокомментируй это."
        if analytics_context:
            user = f"[Контекст реального GP: {analytics_context}]\n" + user
        try:
            fut = self._client.submit(self.acomplete(system_prompt(persona), user))
            return fut.result(timeout=config.YANDEX_GPT_TOTAL_TIMEOUT + 1.0)
        except Exception as exc:  # noqa: BLE001 — любой сбой -> шаблон
            _log.warning("YandexGPT generate failed: %s", exc)
            return None
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `py -3.12 -m pytest tests/test_gpt.py -v`
Expected: PASS (4 passed; функцию `_unused` можно удалить).

- [ ] **Step 5: Checkpoint.**

---

## Task 6: `yandex_ai/speech.py` — синтез речи (SpeechKit v1 LPCM)

**Files:**
- Create: `yandex_ai/speech.py`
- Test: `tests/test_speech.py`

- [ ] **Step 1: Написать падающий тест `tests/test_speech.py`**

```python
import numpy as np

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.speech import YandexSpeech


def _client():
    return YandexClient(Credentials("k", "fld"))


def test_asynthesize_lpcm_to_float(monkeypatch):
    cl = _client(); cl.start()
    try:
        # два сэмпла: 0 и 32767 (макс. int16)
        raw = np.array([0, 32767], dtype="<i2").tobytes()
        captured = {}

        async def fake_form(url, data, **kw):
            captured["url"] = url
            captured["data"] = data
            return raw

        monkeypatch.setattr(cl, "post_form", fake_form)
        sp = YandexSpeech(cl)
        pcm = cl.submit(sp.asynthesize("привет", "filipp", "neutral", 1.0)).result(timeout=3)
        assert pcm.dtype == np.float32
        assert pcm.shape == (2,)
        assert abs(pcm[1] - 0.99997) < 1e-3
        assert captured["data"]["voice"] == "filipp"
        assert captured["data"]["format"] == "lpcm"
        assert captured["data"]["folderId"] == "fld"
    finally:
        cl.stop()


def test_synthesize_persona_resolves_voice(monkeypatch):
    cl = _client(); cl.start()
    try:
        raw = np.array([100, -100], dtype="<i2").tobytes()
        captured = {}

        async def fake_form(url, data, **kw):
            captured["data"] = data
            return raw

        monkeypatch.setattr(cl, "post_form", fake_form)
        sp = YandexSpeech(cl)
        audio, sr = sp.synthesize("текст", "hype")  # hype -> ermil/good/1.1
        assert sr == 48000
        assert audio is not None
        assert captured["data"]["voice"] == "ermil"
        assert captured["data"]["emotion"] == "good"
        assert float(captured["data"]["speed"]) == 1.1
    finally:
        cl.stop()


def test_synthesize_error_returns_none(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def boom(*a, **k):
            raise RuntimeError("tts down")
        monkeypatch.setattr(cl, "post_form", boom)
        sp = YandexSpeech(cl)
        audio, sr = sp.synthesize("x", "tv")
        assert audio is None and sr == 48000
    finally:
        cl.stop()
```

- [ ] **Step 2: Запустить — упадёт**

Run: `py -3.12 -m pytest tests/test_speech.py -v`
Expected: FAIL — нет `yandex_ai.speech`.

- [ ] **Step 3: Создать `yandex_ai/speech.py`**

```python
"""Yandex SpeechKit v1 TTS: текст -> LPCM 48kHz mono -> numpy float32.

asynthesize() — async, пробрасывает исключения. synthesize() — sync-обёртка для voice/tts.py,
исключения глотает и возвращает (None, sr) -> Piper-фолбэк.
"""
from __future__ import annotations

import logging

import numpy as np

import config
from yandex_ai import voices

_log = logging.getLogger(__name__)


class YandexSpeech:
    def __init__(self, client, persona_overrides: dict | None = None):
        self._client = client
        self._overrides = persona_overrides or {}

    def set_overrides(self, overrides: dict | None) -> None:
        self._overrides = overrides or {}

    async def asynthesize(self, text: str, voice: str, emotion: str,
                          speed: float, sr: int | None = None) -> np.ndarray | None:
        sr = sr or config.YANDEX_TTS_SAMPLE_RATE
        data = {
            "text": text,
            "voice": voice,
            "emotion": emotion,
            "speed": str(speed),
            "lang": "ru-RU",
            "format": "lpcm",
            "sampleRateHertz": str(sr),
            "folderId": self._client.folder_id,
        }
        raw = await self._client.post_form(
            config.YANDEX_TTS_URL, data,
            connect=config.YANDEX_TTS_CONNECT_TIMEOUT,
            total=config.YANDEX_TTS_TOTAL_TIMEOUT,
        )
        if not raw:
            return None
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    def synthesize(self, text: str, persona: str) -> tuple[np.ndarray | None, int]:
        sr = config.YANDEX_TTS_SAMPLE_RATE
        spec = voices.resolve(persona, self._overrides)
        try:
            fut = self._client.submit(
                self.asynthesize(text, spec["voice"], spec["emotion"], float(spec["speed"]), sr))
            audio = fut.result(timeout=config.YANDEX_TTS_TOTAL_TIMEOUT + 1.0)
            return (audio, sr)
        except Exception as exc:  # noqa: BLE001 — любой сбой -> Piper
            _log.warning("YandexSpeech synth failed: %s", exc)
            return (None, sr)
```

- [ ] **Step 4: Запустить — пройдёт + вернуться к Task 4**

Run: `py -3.12 -m pytest tests/test_speech.py tests/test_client.py -v`
Expected: PASS (speech 3 + client 5).

- [ ] **Step 5: Checkpoint.**

---

## Task 7: `commentator/ai_provider.py` — делегат на YandexGPT

**Files:**
- Modify: `commentator/ai_provider.py` (полная замена содержимого)
- Test: `tests/test_ai_provider.py`

- [ ] **Step 1: Написать падающий тест `tests/test_ai_provider.py`**

```python
from commentator.ai_provider import AIProvider


def test_unavailable_without_client():
    ai = AIProvider(None)
    assert ai.available is False
    assert ai.generate({"event_code": "OVTK"}, "tv") is None


def test_delegates_to_gpt(monkeypatch):
    class FakeGPT:
        def __init__(self, *a, **k):
            pass
        def generate(self, event, persona, ctx=None):
            return f"phrase:{event['event_code']}:{persona}"

    import commentator.ai_provider as mod
    monkeypatch.setattr(mod, "YandexGPT", FakeGPT)
    ai = AIProvider(object())  # любой не-None «клиент»
    assert ai.available is True
    assert ai.generate({"event_code": "RCWN"}, "hype") == "phrase:RCWN:hype"
```

- [ ] **Step 2: Запустить — упадёт** (старый AIProvider требует api_key/anthropic).

Run: `py -3.12 -m pytest tests/test_ai_provider.py -v`
Expected: FAIL.

- [ ] **Step 3: Заменить `commentator/ai_provider.py` целиком**

```python
"""
commentator/ai_provider.py
============================
Тонкая обёртка над YandexGPT. Если клиент не передан (нет/невалиден ключ) —
provider недоступен, и brain.py использует шаблоны (Free-режим).
Форма класса сохранена: brain.py зависит только от .available и .generate(...).
"""
from __future__ import annotations

import config


class AIProvider:
    def __init__(self, client=None, model: str | None = None):
        self._gpt = None
        if client is not None:
            from yandex_ai.gpt import YandexGPT
            self._gpt = YandexGPT(client, model or config.YANDEX_GPT_MODEL)

    @property
    def available(self) -> bool:
        return self._gpt is not None

    def generate(self, event: dict, persona: str,
                 analytics_context: str | None = None) -> str | None:
        if self._gpt is None:
            return None
        return self._gpt.generate(event, persona, analytics_context)
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `py -3.12 -m pytest tests/test_ai_provider.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Checkpoint.**

---

## Task 8: `new_tts/queue_handler.py` — приоритет и прерывание

**Files:**
- Modify: `new_tts/queue_handler.py` (полная замена)
- Test: `tests/test_queue_priority.py`

- [ ] **Step 1: Написать падающий тест `tests/test_queue_priority.py`**

```python
import time

from new_tts.queue_handler import TTSQueue


def test_critical_calls_stop_fn_immediately():
    stopped = []
    # speak_fn долгая, чтобы воркер «застрял» — проверяем синхронный вызов stop_fn
    q = TTSQueue(speak_fn=lambda t: time.sleep(0.5),
                 stop_fn=lambda: stopped.append(1))
    q.enqueue("urgent", priority="critical")
    assert stopped == [1]   # stop_fn вызван синхронно в enqueue
    q.stop()


def test_critical_clears_pending():
    spoken = []
    started = []

    def speak(t):
        started.append(t)
        time.sleep(0.2)
        spoken.append(t)

    q = TTSQueue(speak_fn=speak)
    q.enqueue("a")
    q.enqueue("b")          # ждёт за «a»
    time.sleep(0.05)        # «a» уже играет
    q.enqueue("urgent", priority="critical")  # должно очистить «b»
    time.sleep(0.6)
    assert "urgent" in spoken
    assert "b" not in spoken   # вытеснено
    q.stop()


def test_normal_enqueue_plays():
    spoken = []
    q = TTSQueue(speak_fn=lambda t: spoken.append(t))
    q.enqueue("hello")
    time.sleep(0.3)
    assert spoken == ["hello"]
    q.stop()
```

- [ ] **Step 2: Запустить — упадёт** (старый `enqueue` без `priority`/`stop_fn`).

Run: `py -3.12 -m pytest tests/test_queue_priority.py -v`
Expected: FAIL — `TypeError: enqueue() got unexpected keyword 'priority'`.

- [ ] **Step 3: Заменить `new_tts/queue_handler.py` целиком**

```python
"""
new_tts/queue_handler.py
Очередь воспроизведения с приоритетом.
- normal: фраза становится в очередь, играется по порядку.
- critical: очищает ожидающие + прерывает текущее воспроизведение (stop_fn), играет первой.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable


class TTSQueue:
    def __init__(self, speak_fn: Callable[[str], None],
                 stop_fn: Callable[[], None] | None = None, maxsize: int = 8):
        self._speak_fn = speak_fn
        self._stop_fn = stop_fn            # прерывание текущего воспроизведения
        self._queue: "queue.PriorityQueue[tuple[int, int, str]]" = queue.PriorityQueue(maxsize=maxsize)
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="tts-queue")
        self._thread.start()

    def enqueue(self, text: str, priority: str = "normal") -> None:
        """Добавить фразу. priority: 'normal' | 'critical'."""
        if priority == "critical":
            self.clear()
            if self._stop_fn is not None:
                try:
                    self._stop_fn()
                except Exception:  # noqa: BLE001
                    pass
        prio = 0 if priority == "critical" else 1
        with self._seq_lock:
            self._seq += 1
            item = (prio, self._seq, text)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            pass

    def clear(self) -> None:
        """Очистить ожидающие (текущее воспроизведение не трогает)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        self._stop.set()

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                _prio, _seq, text = self._queue.get(timeout=0.1)
                self._speak_fn(text)
            except queue.Empty:
                continue
            except Exception:  # noqa: BLE001
                pass
```

> **Совместимость:** `voice/tts.py._prewarm_cache` обращается к `self._queue._queue.empty()` —
> `PriorityQueue.empty()` существует, ломаться не будет.

- [ ] **Step 4: Запустить — пройдёт**

Run: `py -3.12 -m pytest tests/test_queue_priority.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Checkpoint.**

---

## Task 9: `voice/tts.py` — Yandex основной, Piper резерв, ключ кэша, приоритет

**Files:**
- Modify: `voice/tts.py`
- Test: `tests/test_voice_cache_key.py`

Изменения внутри класса `Voice`:

- [ ] **Step 1: Тест ключа кэша `tests/test_voice_cache_key.py`**

```python
from voice.tts import Voice


def test_voice_key_yandex_when_available():
    v = Voice()
    v._yandex = object()                 # имитируем наличие Yandex-источника
    v._current_persona = "tv"
    v._voice_overrides = {}
    key = v._voice_key("tv")
    assert key.startswith("y:")
    assert "filipp" in key and "neutral" in key


def test_voice_key_changes_with_override():
    v = Voice()
    v._yandex = object()
    v._voice_overrides = {"tv": {"voice": "jane"}}
    assert "jane" in v._voice_key("tv")


def test_voice_key_piper_when_no_yandex():
    v = Voice()
    v._yandex = None
    assert v._voice_key("tv") == "piper:tv"
```

- [ ] **Step 2: Запустить — упадёт** (нет `_voice_key`, нет `_yandex`/`_voice_overrides`).

Run: `py -3.12 -m pytest tests/test_voice_cache_key.py -v`
Expected: FAIL.

- [ ] **Step 3: Правки в `voice/tts.py`**

3a. Импорт `voices` — добавить рядом с другими импортами (после строки `from new_tts.queue_handler import TTSQueue`):
```python
from yandex_ai import voices
```

3b. В `__init__` (после `self._radio_enabled = True`, до `self._configure_stdout()`) добавить:
```python
        self._yandex = None                 # YandexSpeech | None (ставится из engine)
        self._voice_overrides: dict = {}    # персона -> {voice/emotion/speed}
```
И сменить версию кэша:
```python
        self._cache = TTSCache(os.path.join(config.DATA_DIR, "tts_cache"), version="yandex-v1")
```
(заменяет существующую строку с `version="piper-22k-v2"`).

3c. Создание очереди: в `_wait_and_setup`, в ветке успешной загрузки Piper и в pyttsx3-ветке,
передать `stop_fn`:
```python
            self._queue = TTSQueue(speak_fn=self._play_blocking, stop_fn=self._interrupt_playback)
```
(в обеих ветках, где сейчас `TTSQueue(speak_fn=...)`).

3d. Добавить публичные методы (рядом с `set_persona`/`set_radio_fx`):
```python
    def set_yandex(self, speech_source) -> None:
        """Подключить Yandex как основной источник синтеза (None = только Piper)."""
        self._yandex = speech_source

    def set_voice_overrides(self, overrides: dict | None) -> None:
        self._voice_overrides = overrides or {}
        if self._yandex is not None and hasattr(self._yandex, "set_overrides"):
            self._yandex.set_overrides(self._voice_overrides)

    def _voice_key(self, persona: str) -> str:
        """Ключ кэша зависит от РЕАЛЬНЫХ параметров синтеза, не от имени персоны."""
        if self._yandex is not None:
            s = voices.resolve(persona, self._voice_overrides)
            return f"y:{s['voice']}|{s['emotion']}|{s['speed']}"
        return f"piper:{persona}"

    def _interrupt_playback(self) -> None:
        """Прервать текущее воспроизведение (для critical-приоритета)."""
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:  # noqa: BLE001
            pass
```

3e. Расширить `say` приоритетом:
```python
    def say(self, text: str, priority: str = "normal") -> bool:
        """Ставит фразу в очередь воспроизведения. Возвращает True сразу."""
        if not text or not text.strip() or not self.is_available:
            return False
        if self._queue is not None:
            self._queue.enqueue(text.strip(), priority=priority)
            return True
        return False
```

3f. Унифицировать синтез — добавить метод `_synthesize` (Yandex -> Piper):
```python
    def _synthesize(self, text: str, persona: str):
        """Вернуть (audio float32 mono, sr). Yandex первый, при неудаче — Piper."""
        if self._yandex is not None:
            audio, sr = self._yandex.synthesize(text, persona)
            if audio is not None and len(audio) > 0:
                return audio, sr
        # Piper-фолбэк
        if self._engine.is_ready:
            return self._engine.synthesize(text, persona)
        return None, self._engine.sample_rate
```

3g. Переписать `_play_blocking` на источник-агностичный путь и ключ `_voice_key`:
```python
    def _play_blocking(self, text: str) -> None:
        persona = self._current_persona
        vkey = self._voice_key(persona)
        cache_path = self._cache.path_for(text, vkey)
        if os.path.exists(cache_path):
            t0 = time.monotonic()
            self._play_wav(cache_path)
            _log.debug("playback from cache: %.0f ms", (time.monotonic() - t0) * 1000)
            return
        t0 = time.monotonic()
        audio, sr = self._synthesize(text, persona)
        if audio is None:
            return
        self._save_wav(audio, sr, cache_path)
        self._cache.evict_if_needed()
        self._play_wav(cache_path)
        _log.debug("playback synthesized: %.0f ms", (time.monotonic() - t0) * 1000)
```

3h. Обновить `_generate_and_cache` (prewarm) под новый ключ + источник:
```python
    def _generate_and_cache(self, text: str, persona: str) -> str | None:
        cache_path = self._cache.path_for(text, self._voice_key(persona))
        if os.path.exists(cache_path):
            return cache_path
        audio, sr = self._synthesize(text, persona)
        if audio is not None:
            self._save_wav(audio, sr, cache_path)
            return cache_path
        return None
```

3i. Prewarm — только текущая персона + флаг (контроль стоимости). Заменить тело
`_prewarm_cache` циклом по одной персоне:
```python
    def _prewarm_cache(self) -> None:
        """Кэширует статичные фразы ТЕКУЩЕЙ персоны (контроль стоимости Yandex)."""
        if not config.YANDEX_PREWARM and self._yandex is not None:
            return
        try:
            persona = self._current_persona
            for phrases in SIMPLE.values():
                for phrase in phrases:
                    if "{" in phrase:
                        continue
                    if self._queue is not None and not self._queue._queue.empty():
                        time.sleep(0.2)
                        continue
                    cache_path = self._cache.path_for(phrase.strip(), self._voice_key(persona))
                    if not os.path.exists(cache_path):
                        self._generate_and_cache(phrase.strip(), persona)
        except Exception:  # noqa: BLE001
            pass
```

> **Заметка о Piper-стриминге:** старый `_play_streaming` (посегментный, ~136 мс до первого
> звука) больше не вызывается из `_play_blocking`. Piper теперь резерв и синтезирует фразу
> целиком (приемлемо: резерв не обязан быть ультра-низколатентным). Метод `_play_streaming`
> можно удалить ИЛИ оставить мёртвым — оставь, чтобы не плодить диффы, но в плане отметь как
> неиспользуемый.

- [ ] **Step 4: Запустить тест ключа кэша**

Run: `py -3.12 -m pytest tests/test_voice_cache_key.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Проверить, что модуль импортируется и старые тесты целы**

Run: `py -3.12 -c "import voice.tts; print('ok')"`
Expected: `ok` (Piper грузится в фоне; импорт не должен падать).

- [ ] **Step 6: Checkpoint.**

---

## Task 10: `core/engine.py` — wiring Yandex (текст + голос + настройки)

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_settings.py`

- [ ] **Step 1: Тест `tests/test_engine_settings.py`**

```python
import core.engine as eng_mod
from core.engine import F1Engine


def test_engine_template_mode_without_creds(monkeypatch):
    # нет сохранённых креденшелов -> AIProvider недоступен, llm_engine = Шаблоны
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e.ai.available is False
    assert e.state["llm_engine"] == "Шаблоны"


def test_apply_settings_persona_voice(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    captured = {}
    monkeypatch.setattr(e.voice, "set_voice_overrides", lambda ov: captured.update(ov))
    e.apply_settings({"persona_voice": {"tv": {"voice": "jane"}}})
    assert captured == {"tv": {"voice": "jane"}}
```

- [ ] **Step 2: Запустить — упадёт**

Run: `py -3.12 -m pytest tests/test_engine_settings.py -v`
Expected: FAIL (нет `yc`, старый AIProvider-конструктор).

- [ ] **Step 3: Правки в `core/engine.py`**

3a. Импорты — заменить строку `from commentator.ai_provider import AIProvider` блоком:
```python
from commentator.ai_provider import AIProvider
from yandex_ai import credentials as yc
from yandex_ai.client import YandexClient
from yandex_ai.speech import YandexSpeech
```

3b. В `__init__` — заменить создание `self.ai`:
Было:
```python
        self.ai = AIProvider(config.ANTHROPIC_API_KEY, config.LLM_MODEL)
        self.commentator = Commentator(self.ai, config.PERSONA)
```
Стало:
```python
        self._yandex_client: YandexClient | None = None
        self._yandex_status = {"connected": False, "code": "YANDEX_NO_CREDENTIALS",
                               "message": "Ключ не задан"}
        creds = yc.load()
        if creds is not None:
            self._start_yandex(creds)        # поднимает клиент, проверять отдельно (UI)
        self.ai = AIProvider(self._yandex_client, config.YANDEX_GPT_MODEL)
        self.commentator = Commentator(self.ai, config.PERSONA)
```

3c. В словаре `self.state` — заменить строку `llm_engine`:
Было:
```python
            "llm_engine": "Claude" if self.ai.available else "Шаблоны",
```
Стало:
```python
            "llm_engine": "YandexGPT" if self.ai.available else "Шаблоны",
```

3d. Добавить методы (например, после `apply_settings`):
```python
    def _start_yandex(self, creds) -> None:
        """Поднять YandexClient и подключить голос. Без сетевой валидации."""
        try:
            self._yandex_client = YandexClient(creds)
            self._yandex_client.start()
            self.voice.set_yandex(YandexSpeech(self._yandex_client))
        except Exception as exc:  # noqa: BLE001
            self._yandex_client = None
            self._yandex_status = {"connected": False, "code": "YANDEX_INTERNAL",
                                   "message": str(exc)}

    def apply_yandex_credentials(self, api_key: str, folder_id: str,
                                 auth_mode: str = "api_key") -> tuple[bool, str, str]:
        """Проверить ключ live-пробой; при успехе сохранить и включить Yandex."""
        if not api_key or not folder_id:
            self._yandex_status = {"connected": False, "code": "YANDEX_NO_CREDENTIALS",
                                   "message": "Введите ключ и Folder ID"}
            return (False, "YANDEX_NO_CREDENTIALS", "Введите ключ и Folder ID")
        creds = yc.Credentials(api_key=api_key, folder_id=folder_id, auth_mode=auth_mode)
        client = YandexClient(creds)
        client.start()
        try:
            ok, code, msg = client.submit(client.validate()).result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            ok, code, msg = (False, "YANDEX_NETWORK_ERROR", str(exc))
        if not ok:
            client.stop()
            self._yandex_status = {"connected": False, "code": code, "message": msg}
            return (ok, code, msg)
        # успех: заменяем активный клиент
        old = self._yandex_client
        self._yandex_client = client
        self.ai = AIProvider(self._yandex_client, config.YANDEX_GPT_MODEL)
        self.commentator.ai = self.ai
        self.voice.set_yandex(YandexSpeech(self._yandex_client, self.settings.get("persona_voice")))
        yc.save(creds)
        if old is not None:
            old.stop()
        self._yandex_status = {"connected": True, "code": "OK", "message": msg}
        with self.state_lock:
            self.state["llm_engine"] = "YandexGPT"
        return (True, "OK", msg)

    def yandex_status(self) -> dict:
        creds = yc.load()
        st = dict(self._yandex_status)
        st["masked_key"] = yc.mask(creds.api_key) if creds else ""
        st["folder_id"] = creds.folder_id if creds else ""
        st["llm_engine"] = "YandexGPT" if self.ai.available else "Шаблоны"
        return st
```

3e. В `apply_settings` — обработать `persona_voice` (после блока `radio_fx`):
```python
        if "persona_voice" in settings:
            try:
                self.voice.set_voice_overrides(settings["persona_voice"])
            except Exception:  # noqa: BLE001
                pass
```

3f. В `_commentary_loop` — пробросить приоритет в `say` (заменить `self.voice.say(phrase)`):
```python
            if should_voice:
                priority = "critical" if event.get("priority") == "critical" else "normal"
                self.voice.say(phrase, priority=priority)
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `py -3.12 -m pytest tests/test_engine_settings.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Прогнать ВСЕ юнит-тесты**

Run: `py -3.12 -m pytest -v`
Expected: всё PASS (DPAPI-тест на Windows проходит).

- [ ] **Step 6: Checkpoint.**

---

## Task 11: `web_server.py` — эндпоинты креденшелов и статуса

**Files:**
- Modify: `web_server.py` (добавить роуты в `create_app`)

- [ ] **Step 1: Добавить роуты** (внутри `create_app`, перед `return app`)

```python
    @app.route("/api/yandex/credentials", method="POST")
    def api_yandex_creds():
        body = request.json or {}
        ok, code, msg = engine.apply_yandex_credentials(
            str(body.get("api_key", "")).strip(),
            str(body.get("folder_id", "")).strip(),
            str(body.get("auth_mode", "api_key")),
        )
        return _json({"ok": ok, "code": code, "message": msg})

    @app.route("/api/yandex/status")
    def api_yandex_status():
        return _json(engine.yandex_status())

    @app.route("/api/yandex/voices")
    def api_yandex_voices():
        from yandex_ai import voices
        return _json({"available": voices.AVAILABLE_VOICES,
                      "defaults": voices.DEFAULT_PERSONA_VOICE})
```

- [ ] **Step 2: Проверить импорт сервера**

Run: `py -3.12 -c "import web_server; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Smoke роутов без реального ключа** (валидация вернёт мягкую ошибку)

Run:
```bash
py -3.12 -c "
import threading, time, urllib.request, json
from web_server import create_app
import core.engine as em
em.yc.load = lambda: None
e = em.F1Engine({})
app = create_app(e, {}, '.')
from wsgiref.simple_server import make_server
srv = make_server('127.0.0.1', 8799, app)
threading.Thread(target=srv.handle_request, daemon=True).start()
time.sleep(0.2)
req = urllib.request.Request('http://127.0.0.1:8799/api/yandex/credentials',
    data=json.dumps({'api_key':'','folder_id':''}).encode(), headers={'Content-Type':'application/json'})
print(urllib.request.urlopen(req).read().decode())
"
```
Expected: JSON `{"ok": false, "code": "YANDEX_NO_CREDENTIALS", ...}`.

- [ ] **Step 4: Checkpoint.**

---

## Task 12: `index.html` — UI настроек (ключ, folder, голоса, speed)

**Files:**
- Modify: `index.html`

> Сначала прочитать `#page-settings` (строка ~994) и `#page-voice` (~1053) и JS-функции
> `saveSetting` (~1338), `syncSettings` (~1542), `loadVoiceStatus` (~1373). Вставлять, повторно
> используя существующие CSS-классы карточек/кнопок/инпутов.

- [ ] **Step 1: Карточка «Yandex Cloud» в `#page-settings`**

Вставить блок внутри `#page-settings` (подогнать классы под соседние карточки):
```html
<div class="card" id="yandex-card">
  <div class="sec-title">Yandex Cloud</div>
  <div class="field">
    <label>API Key (или IAM-токен)</label>
    <input type="password" id="yandex-key" placeholder="AQVN... / t1.9eud...">
  </div>
  <div class="field">
    <label>Folder ID</label>
    <input type="text" id="yandex-folder" placeholder="b1g...">
  </div>
  <div class="field">
    <label>Тип авторизации</label>
    <select id="yandex-auth">
      <option value="api_key">API Key</option>
      <option value="iam">IAM Token</option>
    </select>
  </div>
  <button class="btn" onclick="saveYandexCreds()">Проверить и сохранить</button>
  <div id="yandex-status" class="status-line">—</div>
</div>
```

- [ ] **Step 2: JS-функции** (добавить рядом с другими fetch-функциями)

```javascript
async function saveYandexCreds() {
  const el = document.getElementById('yandex-status');
  el.textContent = 'Проверка...';
  const body = {
    api_key: document.getElementById('yandex-key').value,
    folder_id: document.getElementById('yandex-folder').value,
    auth_mode: document.getElementById('yandex-auth').value,
  };
  try {
    const res = await fetch('/api/yandex/credentials', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    el.textContent = data.message || (data.ok ? 'OK' : 'Ошибка');
    el.className = 'status-line ' + (data.ok ? 'ok' : 'err');
    if (data.ok) document.getElementById('yandex-key').value = '';
    loadYandexStatus();
  } catch (e) {
    el.textContent = 'Сеть недоступна';
    el.className = 'status-line err';
  }
}

async function loadYandexStatus() {
  try {
    const res = await fetch('/api/yandex/status');
    const s = await res.json();
    const el = document.getElementById('yandex-status');
    el.textContent = (s.connected ? '● ' : '○ ') + (s.message || '') +
      (s.masked_key ? '  [' + s.masked_key + ' / ' + s.folder_id + ']' : '');
    el.className = 'status-line ' + (s.connected ? 'ok' : 'err');
  } catch (e) { /* тихо */ }
}
```

- [ ] **Step 3: Пикер голоса на персону в `#page-voice`**

В каждую `.voice-sample-card` (`#vscard-tv/hype/calm/toxic`) добавить `<select>`:
```html
<select class="voice-pick" data-persona="tv" onchange="saveVoicePick()"></select>
```
И JS, заполняющий списки и сохраняющий оверрайды:
```javascript
async function loadVoiceOptions() {
  const res = await fetch('/api/yandex/voices');
  const data = await res.json();
  document.querySelectorAll('.voice-pick').forEach(sel => {
    const persona = sel.dataset.persona;
    const def = (data.defaults[persona] || {}).voice;
    sel.innerHTML = '';
    Object.keys(data.available).forEach(v => {
      const o = document.createElement('option');
      o.value = v; o.textContent = v;
      if (v === def) o.selected = true;
      sel.appendChild(o);
    });
  });
}

function saveVoicePick() {
  const ov = {};
  document.querySelectorAll('.voice-pick').forEach(sel => {
    ov[sel.dataset.persona] = {voice: sel.value};
  });
  saveSetting('persona_voice', ov);   // существующая функция -> POST /api/settings
}
```

- [ ] **Step 4: Вызвать загрузчики при старте** — добавить в существующую init-логику
  (где вызывается `loadVoiceStatus()`):
```javascript
  loadYandexStatus();
  loadVoiceOptions();
```

- [ ] **Step 5: Ручная проверка UI**

Run: `py -3.12 app.pyw` → вкладка «Настройки»: видны поля Yandex; «Проверить и сохранить» без
ключа → мягкая ошибка. Вкладка «Голоса»: у персон есть выпадающий список голосов.

- [ ] **Step 6: Checkpoint.**

---

## Task 13: requirements, smoke с реальным ключом, CONTEXT.md

**Files:**
- Modify: `requirements.txt`, `CONTEXT.md`
- Create: `tests/smoke_yandex.py`

- [ ] **Step 1: `requirements.txt`** — добавить/убрать:
```
aiohttp>=3.9
```
(`anthropic` можно пометить опциональным комментарием; Piper-стек оставить для резерва.)

- [ ] **Step 2: Создать `tests/smoke_yandex.py`** (ручной, НЕ pytest — тратит платный API)

```python
"""Ручной smoke Yandex-комментатора. Запуск:
    set YA_KEY=AQVN... && set YA_FOLDER=b1g... && py -3.12 tests/smoke_yandex.py
Проверяет: validate -> GPT -> TTS -> воспроизведение -> кэш-хит.
"""
import os
import time

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.gpt import YandexGPT
from yandex_ai.speech import YandexSpeech

key = os.environ.get("YA_KEY", "")
folder = os.environ.get("YA_FOLDER", "")
assert key and folder, "Задай YA_KEY и YA_FOLDER в окружении"

cl = YandexClient(Credentials(key, folder))
cl.start()
ok, code, msg = cl.submit(cl.validate()).result(timeout=20)
print("validate:", ok, code, msg)
assert ok, msg

gpt = YandexGPT(cl)
phrase = gpt.generate({"event_code": "OVTK", "driver": "Ферстаппен"}, "tv")
print("GPT:", phrase)
assert phrase

sp = YandexSpeech(cl)
audio, sr = sp.synthesize(phrase, "tv")
print("TTS samples:", None if audio is None else len(audio), "sr:", sr)
assert audio is not None

try:
    import sounddevice as sd
    sd.play(audio, sr); sd.wait()
    print("playback OK")
except Exception as e:
    print("playback skipped:", e)

cl.stop()
print("SMOKE PASSED")
```

- [ ] **Step 3: Прогнать smoke** (нужен реальный ключ)

Run: `set YA_KEY=... && set YA_FOLDER=... && py -3.12 tests/smoke_yandex.py`
Expected: `validate: True OK ...`, печать фразы GPT, число сэмплов TTS, `SMOKE PASSED`.

- [ ] **Step 4: Ручная проверка прерывания и смены голоса**
  - Запустить `app.pyw`, в UI задать ключ.
  - Симулировать длинную фразу и critical-событие (или дождаться live F1 25) → длинная фраза
    обрывается, играет срочная.
  - Сменить голос персоны tv на `jane` в UI → следующая реплика звучит новым голосом (новый
    кэш-ключ; старое аудио не отдаётся).

- [ ] **Step 5: Обновить `CONTEXT.md`** — добавить в начало раздела «На чём остановились»
  запись о миграции на Yandex (что сделано, ключ хранится DPAPI/ctypes, Piper — резерв,
  открытые задачи: EXE-spec под aiohttp, IAM, v3-стриминг). Сбросить счётчик задач.
  Поправить верх CONTEXT.md (Архитектура/Технологии всё ещё описывают MOSS/Qwen — обновить
  на Piper-резерв + Yandex основной).

- [ ] **Step 6: Финальная верификация**

Run: `py -3.12 -m pytest -q`
Expected: всё зелёное.
Run: `py -3.12 -c "import app" 2>&1 | head` — sanity импорта (или запустить `app.pyw` вручную).

- [ ] **Step 7: Checkpoint** — фича готова к ручному тесту в F1 25.

---

## Self-Review (выполнено при написании плана)

**Покрытие спеки:**
- §3 контракты GPT/TTS → Task 5/6 (URL, modelUri, LPCM, эмоции, speed). ✓
- §4 архитектура (loop-в-потоке) → Task 4. ✓
- §5 модули (voices/credentials/client/gpt/speech) → Task 2–6. ✓
- §6 интеграция (ai_provider/tts/queue/engine/web/index/config) → Task 1,7–12. ✓
- §7 валидация (GPT+TTS пробы, коды) → Task 4 `validate`, Task 10 `apply_yandex_credentials`. ✓
- §8 очередь+прерывание → Task 8 + Task 9 (`_interrupt_playback`) + Task 10 (priority в say). ✓
- §9 конфигурируемый маппинг → Task 2 `resolve` + Task 12 пикер + Task 10 `persona_voice`. ✓
- §10 латентность+кэш-ключ → Task 9 (`_voice_key`, version `yandex-v1`). ✓
- §11 коды ошибок → Task 4/10 (стабильные коды), Task 12 (UI). ✓
- §12 тесты → юнит в Task 2–10, smoke+прерывание в Task 13. ✓
- §4 безопасность (DPAPI/ctypes) → Task 3. ✓

**Плейсхолдеры:** нет (весь код приведён).

**Согласованность сигнатур:** `validate()->(ok,code,msg)` единообразно (client, engine, web, тесты);
`say(text, priority)`; `synthesize(text,persona)->(audio,sr)`; `resolve(persona,overrides)`;
`_voice_key`/`set_yandex`/`set_voice_overrides` совпадают между Task 9/10/тестами. ✓
