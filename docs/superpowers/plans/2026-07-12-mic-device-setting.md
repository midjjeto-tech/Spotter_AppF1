# Mic Device Setting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick which input device push-to-talk records from, persist it in settings, and verify the choice with a record-then-playback test button in Settings.

**Architecture:** `voice/listener.py` gains a `device` parameter threaded through `VoiceListener` (settable live via `set_device()`), plus `list_input_devices()` (enumeration) and `play_back()` (test playback) — all following the existing fake-`sounddevice`-module test pattern from `tests/test_tts_playback_stream.py`. `core/settings.py` persists the choice; `core/engine.py` wires it in at boot and on `apply_settings`, and exposes a synchronous `test_mic()`. Two new Bottle routes; one new panel in `NewSpotterUI`'s Voice view.

**Tech Stack:** Python 3 (pytest, sounddevice), Next.js/React/TypeScript, Tailwind.

**Spec:** `docs/superpowers/specs/2026-07-12-mic-device-setting-design.md`

---

### Task 1: `voice/listener.py` — device-aware recording

**Files:**
- Modify: `voice/listener.py`
- Test: `tests/test_listener.py`

- [ ] **Step 1: Write the failing tests**

Replace the top of `tests/test_listener.py` (imports) with:

```python
import sys
import types

from voice.listener import VoiceListener
```

Append to `tests/test_listener.py`:

```python
class _FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, frames):
        import numpy as np
        return np.zeros(frames, dtype=np.int16), False


def test_default_recorder_uses_configured_device(monkeypatch):
    captured = []

    class TrackingInputStream(_FakeInputStream):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.append(kwargs.get("device"))

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = TrackingInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    listener = VoiceListener(device="USB Mic")
    listener.record(1.0, sr=16000)

    assert captured == ["USB Mic"]


def test_set_device_changes_device_used_on_next_record(monkeypatch):
    captured = []

    class TrackingInputStream(_FakeInputStream):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.append(kwargs.get("device"))

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = TrackingInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    listener = VoiceListener()
    listener.record(1.0)
    listener.set_device("Другой микрофон")
    listener.record(1.0)

    assert captured == [None, "Другой микрофон"]


def test_custom_recorder_still_takes_two_args_regardless_of_device():
    calls = []

    def fake_recorder(max_sec, sr):
        calls.append((max_sec, sr))
        return b"\x00\x01"

    listener = VoiceListener(recorder=fake_recorder, device="Some Device")
    audio = listener.record(2.0, sr=16000)

    assert calls == [(2.0, 16000)]
    assert audio == b"\x00\x01"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_listener.py -v`
Expected: FAIL — `VoiceListener.__init__()` doesn't accept `device=`, no `set_device` method.

- [ ] **Step 3: Write the implementation**

Replace the contents of `voice/listener.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_listener.py -v`
Expected: PASS (8 tests: 5 original + 3 new)

- [ ] **Step 5: Commit**

```bash
git add voice/listener.py tests/test_listener.py
git commit -m "feat: thread device selection through VoiceListener"
```

---

### Task 2: `voice/listener.py` — device enumeration coverage

**Files:**
- Test: `tests/test_listener.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_listener.py` (add `list_input_devices` to the import line at the top:
`from voice.listener import VoiceListener, list_input_devices, play_back`):

```python
def test_list_input_devices_filters_and_marks_default(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "USB Mic", "max_input_channels": 2},
        {"name": "Built-in Mic", "max_input_channels": 1},
    ]
    fake_sd.default = types.SimpleNamespace(device=(2, 0))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert list_input_devices() == [
        {"name": "USB Mic", "index": 1, "is_default": False},
        {"name": "Built-in Mic", "index": 2, "is_default": True},
    ]


def test_list_input_devices_default_as_plain_int(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [{"name": "Mic A", "max_input_channels": 1}]
    fake_sd.default = types.SimpleNamespace(device=0)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert list_input_devices() == [{"name": "Mic A", "index": 0, "is_default": True}]


def test_list_input_devices_returns_empty_on_failure(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")

    def _boom():
        raise RuntimeError("no portaudio")

    fake_sd.query_devices = _boom
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert list_input_devices() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_listener.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_input_devices'` (already implemented
in Task 1's `voice/listener.py` rewrite — this step confirms the import line update; if Task 1
already landed, these should already PASS. If so, skip straight to Step 3.)

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_listener.py -v`
Expected: PASS (11 tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_listener.py
git commit -m "test: cover list_input_devices filtering and fail-safe behavior"
```

---

### Task 3: `voice/listener.py` — test playback coverage

**Files:**
- Test: `tests/test_listener.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_listener.py`:

```python
def test_play_back_writes_audio_through_output_stream(monkeypatch):
    captured = {}

    class FakeOutputStream:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, data):
            captured["data"] = list(data)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.OutputStream = FakeOutputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    play_back(b"\x01\x00\x02\x00", sr=16000)

    assert captured["kwargs"]["samplerate"] == 16000
    assert captured["kwargs"]["channels"] == 1
    assert captured["data"] == [1, 2]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_listener.py -v`
Expected: PASS (12 tests) — `play_back` was already implemented in Task 1's rewrite.

- [ ] **Step 3: Commit**

```bash
git add tests/test_listener.py
git commit -m "test: cover play_back output stream wiring"
```

---

### Task 4: Settings + config

**Files:**
- Modify: `core/settings.py:19-43` (`DEFAULTS`)
- Modify: `config.py:139` (near `VOICE_QUESTION_MAX_SEC`)
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings.py`:

```python
def test_defaults_include_mic_device():
    from core.settings import DEFAULTS
    assert DEFAULTS["mic_device"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -v`
Expected: FAIL with `KeyError: 'mic_device'`

- [ ] **Step 3: Add the setting and the test-duration constant**

In `core/settings.py`, find:

```python
    "engineer_chatter_enabled": True,
}
```

Change to:

```python
    "engineer_chatter_enabled": True,
    # Имя выбранного устройства записи (из voice.listener.list_input_devices()),
    # None = системное устройство по умолчанию. См.
    # docs/superpowers/specs/2026-07-12-mic-device-setting-design.md.
    "mic_device":               None,
}
```

In `config.py`, find:

```python
VOICE_QUESTION_MAX_SEC = 5.0    # максимальная длина записи вопроса push-to-talk
```

Change to:

```python
VOICE_QUESTION_MAX_SEC = 5.0    # максимальная длина записи вопроса push-to-talk
MIC_TEST_SEC = 2.0              # длина тестовой записи микрофона (Settings → Voice)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_settings.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add core/settings.py config.py tests/test_settings.py
git commit -m "feat: add mic_device setting and MIC_TEST_SEC constant"
```

---

### Task 5: Engine wiring — init, apply_settings, test_mic()

**Files:**
- Modify: `core/engine.py:47` (import), `core/engine.py:115` (init), `core/engine.py:326-371` (`apply_settings`), `core/engine.py` (new `test_mic` method, next to `_run_voice_question`)
- Test: `tests/test_engine_settings.py`, `tests/test_engine_voice.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_engine_settings.py`, append:

```python
def test_engine_init_applies_saved_mic_device(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"mic_device": "Saved Mic"})
    assert e._voice_listener._device == "Saved Mic"


def test_apply_settings_mic_device_calls_set_device(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    captured = {}
    monkeypatch.setattr(e._voice_listener, "set_device", lambda d: captured.update(device=d))
    e.apply_settings({"mic_device": "USB Mic"})
    assert captured == {"device": "USB Mic"}
```

In `tests/test_engine_voice.py`, append (uses the existing `engine` fixture and `FakeListener`
from the top of this file):

```python
def test_test_mic_success(engine, monkeypatch):
    _reset(engine)
    engine._voice_listener = FakeListener(b"\x00\x01")
    played = []
    monkeypatch.setattr(eng_mod, "play_back", lambda audio, sr=48000: played.append(audio))
    result = engine.test_mic()
    assert result == {"ok": True}
    assert played == [b"\x00\x01"]


def test_test_mic_no_microphone_is_error(engine):
    _reset(engine)
    engine._voice_listener = FakeListener(None)
    result = engine.test_mic()
    assert result == {"ok": False, "error": "Микрофон недоступен"}


def test_test_mic_playback_failure_is_error(engine, monkeypatch):
    _reset(engine)
    engine._voice_listener = FakeListener(b"\x00\x01")

    def _boom(audio, sr=48000):
        raise RuntimeError("no output device")

    monkeypatch.setattr(eng_mod, "play_back", _boom)
    result = engine.test_mic()
    assert result == {"ok": False, "error": "Не удалось воспроизвести"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine_settings.py tests/test_engine_voice.py -v`
Expected: FAIL — `e._voice_listener._device` doesn't exist yet as a settings-driven value,
`engine.test_mic()` / `eng_mod.play_back` don't exist.

- [ ] **Step 3: Wire the implementation**

In `core/engine.py`, find the import (around line 47):

```python
from voice.listener import VoiceListener
```

Change to:

```python
from voice.listener import VoiceListener, play_back
```

Find (around line 115):

```python
        self._voice_listener = VoiceListener()
```

Change to:

```python
        self._voice_listener = VoiceListener(device=self.settings.get("mic_device"))
```

In `apply_settings` (around line 342-346), find:

```python
        if "persona_voice" in settings:
            try:
                self.voice.set_voice_overrides(settings["persona_voice"])
            except Exception:  # noqa: BLE001
                pass
```

Add immediately after it:

```python
        if "mic_device" in settings:
            self._voice_listener.set_device(settings["mic_device"])
```

Find `_run_voice_question` and, right after its closing (before `_start_f1_benchmark_load`),
add the new method:

```python
    def test_mic(self) -> dict:
        """Push-to-talk diagnostics (Settings → Voice, кнопка «Проверить»): запись
        config.MIC_TEST_SEC + воспроизведение обратно текущим self._voice_listener.
        Синхронно (в отличие от ask_voice_question) — нет пересечения с
        critical-гейтом TTS-очереди, действие короткое и явно инициировано кликом."""
        audio = self._voice_listener.record(config.MIC_TEST_SEC)
        if audio is None:
            return {"ok": False, "error": "Микрофон недоступен"}
        try:
            play_back(audio)
        except Exception as exc:  # noqa: BLE001
            _log.warning("mic test playback failed: %s", exc)
            return {"ok": False, "error": "Не удалось воспроизвести"}
        return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_engine_settings.py tests/test_engine_voice.py -v`
Expected: PASS (all tests, including the 5 new ones)

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/engine.py tests/test_engine_settings.py tests/test_engine_voice.py
git commit -m "feat: wire mic_device setting and add engine.test_mic()"
```

---

### Task 6: Backend routes

**Files:**
- Modify: `web_server.py` (near the `/api/voices` route, around line 139-145)

- [ ] **Step 1: Add the routes**

In `web_server.py`, find:

```python
    @app.route("/api/voices")
    def api_voices():
        from voice.voice_manager import voice_status
        return _json(voice_status(
            yandex_attached=engine.voice._yandex is not None,
            yandex_healthy=engine._yandex_healthy,
        ))
```

Add immediately after it:

```python
    @app.route("/api/mic_devices")
    def api_mic_devices():
        from voice.listener import list_input_devices
        return _json({"devices": list_input_devices()})

    @app.route("/api/mic_test", method="POST")
    def api_mic_test():
        return _json(engine.test_mic())
```

- [ ] **Step 2: Sanity-check the module imports cleanly**

Run: `python -c "import web_server"`
Expected: No errors (Bottle app builds; routes register without exceptions).

- [ ] **Step 3: Commit**

```bash
git add web_server.py
git commit -m "feat: add /api/mic_devices and /api/mic_test routes"
```

---

### Task 7: Frontend — API client

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`

- [ ] **Step 1: Add the type field and new exports**

In `NewSpotterUI/lib/api.ts`, find the `SettingsState` type and add `mic_device` to it:

```tsx
export type SettingsState = {
  persona: string
  commentary_enabled: boolean
  autovoice_enabled: boolean
  critical_events_enabled: boolean
  ambient_enabled: boolean
  radio_fx: boolean
  commentator_position: string
  min_comment_gap: number
  broadcast_mode_enabled: boolean
  volume: number
  volume_tv: number
  volume_hype: number
  volume_calm: number
  volume_toxic: number
  yandex_tts_version: "v1" | "v3"
  commentary_mode: "live" | "calm" | "story"
  mic_device: string | null
}
```

Near `export type VoicesResponse = {...}`, add:

```tsx
export type MicDevice = { name: string; index: number; is_default: boolean }
```

Near `export const askVoice = ...`, add:

```tsx
export const getMicDevices = () =>
  fetch("/api/mic_devices").then((r) => asJson<{ devices: MicDevice[] }>(r))

export const testMic = () =>
  fetch("/api/mic_test", { method: "POST" }).then((r) => asJson<{ ok: boolean; error?: string }>(r))
```

- [ ] **Step 2: Type-check**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add NewSpotterUI/lib/api.ts
git commit -m "feat: add mic device API client functions"
```

---

### Task 8: Frontend — Microphone panel in Voice view

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/voice.tsx`

- [ ] **Step 1: Add imports and state**

In `NewSpotterUI/components/spotter/views/voice.tsx`, find:

```tsx
import { getVoices, saveSettings, testVoice, type SpotterState, type VoicesResponse } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Tv, Flame, Wind, Skull, Play, RotateCw, Radio } from "lucide-react"
```

Change to:

```tsx
import {
  getVoices, saveSettings, testVoice, getMicDevices, testMic,
  type SpotterState, type VoicesResponse, type MicDevice,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { Tv, Flame, Wind, Skull, Play, RotateCw, Radio, Mic } from "lucide-react"
```

Find:

```tsx
  const [voices, setVoices] = useState<VoicesResponse | null>(null)
```

Add immediately after it:

```tsx
  const [micDevices, setMicDevices] = useState<MicDevice[]>([])
  const [micDevice, setMicDevice] = useState<string | null>(null)
  const [micTesting, setMicTesting] = useState(false)
  const [micTestResult, setMicTestResult] = useState<{ ok: boolean; error?: string } | null>(null)
```

- [ ] **Step 2: Sync from backend state and fetch device list**

Find:

```tsx
  const refresh = () => {
    getVoices()
      .then(setVoices)
      .catch(() => {})
  }
  useEffect(() => {
    refresh()
  }, [])
```

Add immediately after it:

```tsx
  useEffect(() => {
    setMicDevice(state?.settings?.mic_device ?? null)
  }, [state?.settings?.mic_device])

  useEffect(() => {
    getMicDevices()
      .then((r) => setMicDevices(r.devices))
      .catch(() => {})
  }, [])
```

- [ ] **Step 3: Add the handlers**

Find:

```tsx
  const pick = (id: string) => {
    setActive(id)
    saveSettings({ persona: id })
  }
```

Add immediately after it:

```tsx
  const pickMicDevice = (value: string) => {
    const device = value === "" ? null : value
    setMicDevice(device)
    setMicTestResult(null)
    saveSettings({ mic_device: device })
  }

  const runMicTest = () => {
    setMicTesting(true)
    setMicTestResult(null)
    testMic()
      .then(setMicTestResult)
      .catch(() => setMicTestResult({ ok: false, error: "Ошибка запроса" }))
      .finally(() => setMicTesting(false))
  }
```

- [ ] **Step 4: Add the panel**

Find the closing of the "Radio FX" panel:

```tsx
        {/* Radio FX */}
        <Panel label="Radio FX">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                <Radio className="h-4.5 w-4.5" />
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">Эффект рации</p>
                <p className="text-xs text-muted-foreground">Полоса 300–3400 Гц + щелчки сквелча</p>
              </div>
            </div>
            <Toggle checked={radioFx} onChange={toggleRadioFx} label="Radio FX" />
          </div>
        </Panel>
```

Add immediately after it:

```tsx
        {/* Microphone input device */}
        <Panel
          label="Микрофон"
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={runMicTest}
              disabled={micTesting}
              className="h-8 border-border bg-secondary text-foreground hover:bg-elevated"
            >
              <Mic className="h-3.5 w-3.5" /> {micTesting ? "Проверка…" : "Проверить"}
            </Button>
          }
        >
          <p className="mb-4 text-xs text-muted-foreground">
            Устройство записи для голосовых вопросов (push-to-talk). «Проверить» запишет
            2 секунды и воспроизведёт их обратно через колонки.
          </p>
          <select
            value={micDevice ?? ""}
            onChange={(e) => pickMicDevice(e.target.value)}
            className="h-9 w-full max-w-sm rounded-md border border-input bg-secondary px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Системный микрофон по умолчанию</option>
            {micDevices.map((d) => (
              <option key={d.index} value={d.name}>
                {d.name}
                {d.is_default ? " (по умолчанию)" : ""}
              </option>
            ))}
          </select>
          {micTestResult && (
            <p className={cn("mt-3 text-[11px]", micTestResult.ok ? "text-success" : "text-destructive")}>
              {micTestResult.ok ? "Микрофон работает — запись воспроизведена." : micTestResult.error}
            </p>
          )}
        </Panel>
```

- [ ] **Step 5: Type-check**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add NewSpotterUI/components/spotter/views/voice.tsx
git commit -m "feat: add microphone device panel to Voice view"
```

---

### Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m pytest -q`
Expected: All tests pass, 0 failures.

- [ ] **Step 2: Run the full frontend type-check**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Manual browser verification**

Start the app's dev preview, open Voice view:
1. Confirm the "Микрофон" panel renders with a dropdown (system default + any real devices
   on the machine running the preview) and a "Проверить" button.
2. Change the selection; confirm it round-trips (reload the page, selection persists via
   `state.settings.mic_device`).
3. Click "Проверить"; confirm the button disables during the request and shows a result
   message after (ok or error — a browser-preview sandbox likely has no real mic/speakers,
   so an error result with a sensible message is an acceptable pass here — the important
   thing is the request completes and the UI doesn't hang).

- [ ] **Step 4: Update CONTEXT.md**

Append a dated entry to `CONTEXT.md` summarizing: mic device selection + test button added
to Settings/Voice view, `voice/listener.py` now supports `device`/`set_device`/
`list_input_devices`/`play_back`.

- [ ] **Step 5: Commit**

```bash
git add CONTEXT.md
git commit -m "docs: record mic device setting in CONTEXT.md"
```
