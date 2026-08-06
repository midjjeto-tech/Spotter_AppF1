# Push-to-talk хоткей + звук-маркер «слушаю» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Настраиваемый пользователем глобальный хоткей запускает существующий push-to-talk
(`ask_voice_question()`), а сам конвейер сначала играет короткий радио-щелчок как маркер
«AI начал слушать».

**Architecture:** `core/hotkeys.py::GlobalHotkeyManager` регистрирует 6-й, читаемый из
`settings["ptt_hotkey"]` хоткей рядом с 5 уже существующими фиксированными (Win32
`RegisterHotKey`), дёргающий `engine.ask_voice_question()` — тот же метод, что вызывает кнопка
«Спросить» в топбаре. `voice/tts.py::Voice.play_beep()` — новый метод, переиспользующий уже
существующий синтез `radio_fx.squelch()`, воспроизводит через отдельный `sd.OutputStream` с
`close()`/`abort()` строго под `self._stream_lock` (тот же паттерн, что закрыл access violation
в `ucrtbase.dll` в предыдущей сессии — критично не открывать эту гонку заново).
`core/engine.py::_run_voice_question()` зовёт `play_beep()` перед записью — единая точка для
хоткея и клика в UI. Фронтенд (`NewSpotterUI/components/spotter/views/hotkeys.tsx`) получает
новую строку с захватом комбинации клавиш через `keydown`, сохраняет через уже существующий
`saveSettings()`.

**Tech Stack:** Python (Win32 `ctypes`/`RegisterHotKey`, `sounddevice`, `pytest`), Next.js/React/
TypeScript (уже существующие `Panel`/`KeyCap`/`Button` компоненты, `saveSettings()`).

**Проект не под git** (`CONTEXT.md`: «Проект НЕ под git») — шаги `git commit` из шаблона плана
заменены на «отметить задачу выполненной»; фактических git-команд в этом плане нет.

---

### Task 1: `core/settings.py` — дефолт для `ptt_hotkey`

**Files:**
- Modify: `core/settings.py:19-47` (`DEFAULTS`)

- [ ] **Step 1: Добавить ключ в `DEFAULTS`**

В `core/settings.py`, внутри словаря `DEFAULTS` (после `"mic_device": None,` — последний
существующий ключ), добавить:

```python
    # Push-to-talk хоткей (глобальный, работает пока F1 25 в фокусе) — единственная
    # пользовательски настраиваемая горячая клавиша в приложении, см.
    # core/hotkeys.py::GlobalHotkeyManager и docs/superpowers/specs/
    # 2026-07-14-ptt-hotkey-radio-beep-design.md. Смена применяется после
    # перезапуска Spotter App (регистрация хоткеев — один раз при старте потока).
    "ptt_hotkey": {"ctrl": True, "alt": True, "shift": False, "key": "V"},
```

- [ ] **Step 2: Проверить, что существующие тесты settings не сломались**

Run: `py -3.12 -u -m pytest tests/test_settings.py -q`
Expected: все тесты проходят (новый ключ появляется в `load()`/`reset()` автоматически —
логика `DEFAULTS`-based, отдельного кода под конкретный ключ не требуется).

- [ ] **Step 3: Отметить задачу выполненной**

---

### Task 2: `core/hotkeys.py` — 6-й хоткей, конфигурируемый

**Files:**
- Modify: `core/hotkeys.py`
- Test: `tests/test_hotkeys.py` (новый файл)

- [ ] **Step 1: Написать падающий тест на конвертацию настройки в (mods, vk)**

Создать `tests/test_hotkeys.py`:

```python
from core.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, _vk_from_settings


def test_vk_from_settings_valid_letter():
    assert _vk_from_settings(
        {"ctrl": True, "alt": True, "shift": False, "key": "V"}
    ) == (MOD_CONTROL | MOD_ALT, ord("V"))


def test_vk_from_settings_lowercase_key_normalized():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "v"}
    ) == (MOD_CONTROL, ord("V"))


def test_vk_from_settings_digit():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "5"}
    ) == (MOD_CONTROL, ord("5"))


def test_vk_from_settings_function_key():
    assert _vk_from_settings(
        {"ctrl": False, "alt": True, "shift": False, "key": "F5"}
    ) == (MOD_ALT, 0x70 + 4)


def test_vk_from_settings_f12_upper_bound():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "F12"}
    ) == (MOD_CONTROL, 0x70 + 11)


def test_vk_from_settings_shift_modifier():
    assert _vk_from_settings(
        {"ctrl": False, "alt": False, "shift": True, "key": "Q"}
    ) == (MOD_SHIFT, ord("Q"))


def test_vk_from_settings_requires_modifier():
    assert _vk_from_settings(
        {"ctrl": False, "alt": False, "shift": False, "key": "V"}
    ) is None


def test_vk_from_settings_rejects_disallowed_key():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": "ESCAPE"}
    ) is None


def test_vk_from_settings_none_input():
    assert _vk_from_settings(None) is None


def test_vk_from_settings_missing_key():
    assert _vk_from_settings(
        {"ctrl": True, "alt": False, "shift": False, "key": ""}
    ) is None
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_hotkeys.py -q`
Expected: FAIL — `ImportError: cannot import name '_vk_from_settings' from 'core.hotkeys'`
(и `MOD_SHIFT` тоже отсутствует).

- [ ] **Step 3: Реализовать `_vk_from_settings` + `MOD_SHIFT` + `_PTT_HOTKEY_ID`**

В `core/hotkeys.py`, после строки `WM_QUIT = 0x0012` добавить:

```python
MOD_SHIFT = 0x0004

_PTT_HOTKEY_ID = 6

_VK_F1 = 0x70

_ALLOWED_KEYS = frozenset(
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + [f"F{n}" for n in range(1, 13)]
)


def _vk_from_settings(hk: dict | None) -> "tuple[int, int] | None":
    """Конвертирует settings["ptt_hotkey"] ({"ctrl","alt","shift","key"}) в
    (mods, vk) для RegisterHotKey. None — настройка отсутствует/невалидна
    (нет модификатора, неразрешённая клавиша) — 6-й хоткей просто не
    регистрируется, fail-safe как остальной хоткей-стек. Разрешённые key:
    A-Z, 0-9, F1-F12 — не даём забиндить произвольную клавишу, которая может
    понадобиться самой игре."""
    if not isinstance(hk, dict):
        return None
    key = str(hk.get("key") or "").upper()
    if key not in _ALLOWED_KEYS:
        return None
    mods = 0
    if hk.get("ctrl"):
        mods |= MOD_CONTROL
    if hk.get("alt"):
        mods |= MOD_ALT
    if hk.get("shift"):
        mods |= MOD_SHIFT
    if mods == 0:
        return None
    if len(key) == 1:
        vk = ord(key)
    else:
        vk = _VK_F1 + int(key[1:]) - 1
    return (mods, vk)
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `py -3.12 -u -m pytest tests/test_hotkeys.py -q`
Expected: PASS, 10 passed.

- [ ] **Step 5: Зарегистрировать 6-й хоткей в `_loop()` и добавить dispatch**

В `core/hotkeys.py`, метод `_loop`, заменить:

```python
    def _loop(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        registered = []
        for hk_id, (mods, vk) in _HOTKEYS.items():
            if ctypes.windll.user32.RegisterHotKey(None, hk_id, mods, vk):
                registered.append(hk_id)

        msg = ctypes.wintypes.MSG()
```

на:

```python
    def _loop(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        registered = []
        for hk_id, (mods, vk) in _HOTKEYS.items():
            if ctypes.windll.user32.RegisterHotKey(None, hk_id, mods, vk):
                registered.append(hk_id)

        ptt = _vk_from_settings(self._settings.get("ptt_hotkey"))
        if ptt is not None and ptt not in _HOTKEYS.values():
            if ctypes.windll.user32.RegisterHotKey(None, _PTT_HOTKEY_ID, ptt[0], ptt[1]):
                registered.append(_PTT_HOTKEY_ID)

        msg = ctypes.wintypes.MSG()
```

Затем в `_dispatch`, заменить:

```python
    def _dispatch(self, hk_id: int) -> None:
        actions = {
            1: self._toggle_commentary,
            2: self._next_persona,
            3: self._test_voice,
            4: self._clear_feed,
            5: self._toggle_window,
        }
        action = actions.get(hk_id)
        if action:
            action()
```

на:

```python
    def _dispatch(self, hk_id: int) -> None:
        actions = {
            1: self._toggle_commentary,
            2: self._next_persona,
            3: self._test_voice,
            4: self._clear_feed,
            5: self._toggle_window,
            _PTT_HOTKEY_ID: self._push_to_talk,
        }
        action = actions.get(hk_id)
        if action:
            action()
```

Затем, после метода `_toggle_window` (в конце класса), добавить:

```python

    def _push_to_talk(self) -> None:
        self._engine.ask_voice_question()
```

- [ ] **Step 6: Полный прогон тестов хоткеев**

Run: `py -3.12 -u -m pytest tests/test_hotkeys.py -q`
Expected: PASS, 10 passed (регистрация в `_loop`/`_dispatch` не покрыта юнит-тестами — требует
реального Win32-потока, как и 5 уже существующих хоткеев, не тестировавшихся раньше; это
осознанное продолжение уже принятого в файле паттерна, не пробел этого плана).

- [ ] **Step 7: Отметить задачу выполненной**

---

### Task 3: `voice/tts.py` — `Voice.play_beep()`

**Files:**
- Modify: `voice/tts.py` (после метода `_interrupt_playback`, перед `def say`)
- Test: `tests/test_tts_playback_stream.py`

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_tts_playback_stream.py`, после теста
`test_play_wav_close_and_interrupt_playback_are_mutually_exclusive` (в конце файла перед
`test_effective_volume_uses_explicit_persona` — вставить как отдельный блок), добавить:

```python
def test_play_beep_interrupts_current_playback_first(fake_sd):
    v = _make_voice()
    calls = []
    v._interrupt_playback = lambda: calls.append("interrupt")
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        calls.append("stream_created")

    FakeOutputStream.__init__ = tracking_init
    try:
        v.play_beep()
    finally:
        FakeOutputStream.__init__ = orig_init

    assert calls == ["interrupt", "stream_created"]


def test_play_beep_creates_single_stream_and_cleans_up(fake_sd):
    v = _make_voice()
    created = []
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)

    FakeOutputStream.__init__ = tracking_init
    try:
        v.play_beep()
    finally:
        FakeOutputStream.__init__ = orig_init

    assert len(created) == 1
    assert created[0].started is True
    assert created[0].stopped is True
    assert created[0].closed is True
    assert created[0].aborted is False
    assert len(created[0].written) == 1
    assert v._current_stream is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_tts_playback_stream.py -k play_beep -v`
Expected: FAIL — `AttributeError: 'Voice' object has no attribute 'play_beep'`.

- [ ] **Step 3: Реализовать `Voice.play_beep()`**

В `voice/tts.py`, сразу после конца метода `_interrupt_playback` (после блока
`except Exception:  # noqa: BLE001` / `pass`, перед `def say(self, ...)`), вставить:

```python
    def play_beep(self) -> None:
        """Короткий рут-сквелч — маркер «AI начал слушать» (push-to-talk, см.
        core/engine.py::_run_voice_question). Сначала глушит текущую фразу
        (_interrupt_playback — как реальная рация: входящая передача обрывает
        прежнюю), затем играет squelch через ОТДЕЛЬНЫЙ sd.OutputStream.
        close() — под тем же self._stream_lock, что и в _play_wav/
        _interrupt_playback (см. их докстринги про access violation в
        ucrtbase.dll, найдено 07-09/07-13, фикс 07-14) — не открывать эту
        гонку заново. radio_fx.squelch() — тот же синтез, что уже обрамляет
        фразы при включённом radio-эффекте (voice/radio_fx.py), играется
        ВСЕГДА (не зависит от self._radio_enabled — это отдельный,
        осознанный UX-сигнал, не часть тумблера «радио-эффект»)."""
        self._interrupt_playback()
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            return
        sr = 22050
        try:
            audio = radio_fx.squelch(sr)
        except Exception:  # noqa: BLE001
            return
        if audio.size == 0:
            return
        stream = None
        try:
            stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32", latency="low")
            with self._stream_lock:
                self._current_stream = stream
            stream.start()
            stream.write(np.ascontiguousarray(audio.reshape(-1, 1), dtype="float32"))
            stream.stop()
        except Exception:  # noqa: BLE001
            pass
        finally:
            with self._stream_lock:
                if self._current_stream is stream:
                    self._current_stream = None
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `py -3.12 -u -m pytest tests/test_tts_playback_stream.py -v`
Expected: PASS, все тесты файла (включая 2 новых).

- [ ] **Step 5: Отметить задачу выполненной**

---

### Task 4: `core/engine.py` — вызов `play_beep()` перед записью

**Files:**
- Modify: `core/engine.py:1473-1486` (`_run_voice_question`)
- Test: `tests/test_engine_voice.py`

- [ ] **Step 1: Добавить `play_beep` в `FakeVoice` и написать падающие тесты**

В `tests/test_engine_voice.py`, класс `FakeVoice`, заменить:

```python
    def __init__(self):
        self.is_critical_active = False
        self.said = []

    def say(self, text, priority="normal"):
        self.said.append((text, priority))
        return True
```

на:

```python
    def __init__(self):
        self.is_critical_active = False
        self.said = []
        self.beeped = False

    def say(self, text, priority="normal"):
        self.said.append((text, priority))
        return True

    def play_beep(self):
        self.beeped = True
```

`engine` — module-scoped фикстура (один и тот же `FakeVoice` живёт все тесты файла) —
подмена `engine.voice.play_beep` должна ОТКАТЫВАТЬСЯ в `finally`, иначе последующие тесты
в файле получат заглушку вместо реального `FakeVoice.play_beep`. Также добавить сброс
`beeped` в `_reset()`, чтобы состояние не утекало из предыдущих тестов.

В `_reset(engine)`, после `engine.voice.said.clear()`, добавить строку:

```python
    engine.voice.beeped = False
```

Затем, после функции `_reset`, перед первым тестом, добавить:

```python
def test_run_voice_question_plays_beep_before_recording(engine):
    _reset(engine)
    order = []
    orig_play_beep = engine.voice.play_beep

    def tracking_beep():
        order.append("beep")

    engine.voice.play_beep = tracking_beep
    orig_record = engine._voice_listener.record

    def tracking_record(max_sec, sr=48000):
        order.append("record")
        return orig_record(max_sec, sr)

    engine._voice_listener.record = tracking_record
    try:
        engine._run_voice_question()
        assert order == ["beep", "record"]
    finally:
        engine.voice.play_beep = orig_play_beep


def test_run_voice_question_no_beep_when_stt_unavailable(engine):
    _reset(engine)
    engine._stt = None
    engine._run_voice_question()
    assert engine.voice.beeped is False
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_engine_voice.py -k "beep" -v`
Expected: `test_run_voice_question_plays_beep_before_recording` FAILs (`order == ["record"]`,
`play_beep` никогда не вызывается); `test_run_voice_question_no_beep_when_stt_unavailable`
PASSes уже сейчас (несущественно — `beeped` и так `False` до реализации, но подтверждаем это
явно, чтобы после Step 3 иметь регрессионный тест на оба случая).

- [ ] **Step 3: Вставить вызов `play_beep()`**

В `core/engine.py`, метод `_run_voice_question`, заменить:

```python
        try:
            if self._stt is None or not self._yandex_healthy:
                self._set_voice_query(status="error", error="Распознавание недоступно")
                return

            audio = self._voice_listener.record(config.VOICE_QUESTION_MAX_SEC)
```

на:

```python
        try:
            if self._stt is None or not self._yandex_healthy:
                self._set_voice_query(status="error", error="Распознавание недоступно")
                return

            self.voice.play_beep()
            audio = self._voice_listener.record(config.VOICE_QUESTION_MAX_SEC)
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `py -3.12 -u -m pytest tests/test_engine_voice.py -v`
Expected: PASS, все тесты файла (включая 2 новых).

- [ ] **Step 5: Отметить задачу выполненной**

---

### Task 5: Фронтенд — типы (`lib/api.ts`)

**Files:**
- Modify: `NewSpotterUI/lib/api.ts:36-55` (`SettingsState`)

- [ ] **Step 1: Добавить тип `PttHotkey` и поле в `SettingsState`**

В `NewSpotterUI/lib/api.ts`, перед `export type SettingsState = {`, добавить:

```typescript
export type PttHotkey = { ctrl: boolean; alt: boolean; shift: boolean; key: string }
```

В `SettingsState`, после `mic_device: string | null`, добавить:

```typescript
  ptt_hotkey: PttHotkey
```

- [ ] **Step 2: Проверить типы**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: без новых ошибок (использований `SettingsState`/`ptt_hotkey` пока нет — это чисто
структурное добавление, следующий таск начнёт его использовать).

- [ ] **Step 3: Отметить задачу выполненной**

---

### Task 6: Фронтенд — захват комбинации в `hotkeys.tsx`

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/hotkeys.tsx` (полная замена файла)
- Modify: `NewSpotterUI/app/page.tsx:54`

- [ ] **Step 1: Переписать `hotkeys.tsx`**

Заменить содержимое `NewSpotterUI/components/spotter/views/hotkeys.tsx` целиком на:

```tsx
"use client"

import { Fragment, useEffect, useState } from "react"
import { PageHeader, Panel, KeyCap } from "../ui"
import { Button } from "@/components/ui/button"
import { hotkeys } from "@/lib/spotter-data"
import { saveSettings, type PttHotkey, type SpotterState } from "@/lib/api"

const ALLOWED_KEY_RE = /^([A-Z0-9]|F[1-9]|F1[0-2])$/
const FIXED_KEYS = new Set(["C", "P", "T", "X", "S"])

export function HotkeysView({ state }: { state: SpotterState | null }) {
  const [ptt, setPtt] = useState<PttHotkey | null>(null)
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (state?.settings?.ptt_hotkey) setPtt(state.settings.ptt_hotkey)
  }, [state?.settings?.ptt_hotkey])

  useEffect(() => {
    if (!recording) return
    const onKeyDown = (e: KeyboardEvent) => {
      e.preventDefault()
      if (e.key === "Control" || e.key === "Alt" || e.key === "Shift") return
      const key = e.key.toUpperCase()
      setRecording(false)
      if (!ALLOWED_KEY_RE.test(key)) {
        setError("Разрешены A-Z, 0-9, F1-F12")
        return
      }
      const candidate: PttHotkey = { ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, key }
      if (!candidate.ctrl && !candidate.alt && !candidate.shift) {
        setError("Нужен хотя бы один модификатор (Ctrl/Alt/Shift)")
        return
      }
      const collidesWithFixed =
        candidate.ctrl && candidate.alt && !candidate.shift && FIXED_KEYS.has(candidate.key)
      if (collidesWithFixed) {
        setError("Эта комбинация уже занята одним из хоткеев выше")
        return
      }
      setError("")
      setPtt(candidate)
      void saveSettings({ ptt_hotkey: candidate })
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [recording])

  const pttParts: string[] = ptt
    ? [ptt.ctrl && "Ctrl", ptt.alt && "Alt", ptt.shift && "Shift", ptt.key].filter(
        (v): v is string => Boolean(v),
      )
    : []

  return (
    <div>
      <PageHeader
        title="Hotkeys"
        subtitle="Глобальные сочетания — работают, когда F1 25 в фокусе"
      />

      <Panel bodyClassName="p-0">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <span className="label-mono text-[10px] text-muted-foreground">Действие</span>
          <span className="label-mono text-[10px] text-muted-foreground">Клавиши</span>
        </div>
        <ul>
          {hotkeys.map((h) => (
            <li
              key={h.action}
              className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 hover:bg-secondary/40"
            >
              <span className="text-sm font-medium text-foreground">{h.action}</span>
              <div className="flex items-center gap-1.5">
                {h.keys.map((k, i) => (
                  <Fragment key={k}>
                    {i > 0 && <span className="text-xs text-muted-foreground">+</span>}
                    <KeyCap>{k}</KeyCap>
                  </Fragment>
                ))}
              </div>
            </li>
          ))}
          <li className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 last:border-0 hover:bg-secondary/40">
            <div>
              <span className="text-sm font-medium text-foreground">
                Спросить голосом (push-to-talk)
              </span>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Изменения вступят в силу после перезапуска Spotter App.
              </p>
              {error && <p className="mt-1 text-[11px] text-destructive">{error}</p>}
            </div>
            <div className="flex items-center gap-2">
              {recording ? (
                <span className="text-xs text-muted-foreground">Нажмите комбинацию…</span>
              ) : pttParts.length > 0 ? (
                <div className="flex items-center gap-1.5">
                  {pttParts.map((k, i) => (
                    <Fragment key={`${k}-${i}`}>
                      {i > 0 && <span className="text-xs text-muted-foreground">+</span>}
                      <KeyCap>{k}</KeyCap>
                    </Fragment>
                  ))}
                </div>
              ) : (
                <span className="text-xs text-muted-foreground">Не задано</span>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setError("")
                  setRecording(true)
                }}
              >
                Записать
              </Button>
            </div>
          </li>
        </ul>
      </Panel>
    </div>
  )
}
```

- [ ] **Step 2: Передать `state` в `HotkeysView`**

В `NewSpotterUI/app/page.tsx`, заменить:

```tsx
            {view === "hotkeys" && <HotkeysView />}
```

на:

```tsx
            {view === "hotkeys" && <HotkeysView state={state} />}
```

- [ ] **Step 3: Проверить типы**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 4: Отметить задачу выполненной**

---

### Task 7: Финальная верификация

**Files:** нет изменений — только проверка.

- [ ] **Step 1: Полный прогон бэкенд-тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed (весь существующий сьют + новые тесты из Task 2/3/4).

- [ ] **Step 2: Проверка типов фронтенда**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: без ошибок.

- [ ] **Step 3: Ручная браузер-проверка (dev-сервер NewSpotterUI)**

- Открыть страницу Hotkeys — новая строка «Спросить голосом (push-to-talk)» видна, показывает
  дефолт `Ctrl+Alt+V` (или сохранённое значение).
- Клик «Записать» → текст меняется на «Нажмите комбинацию…».
- Нажать, например, `Ctrl+Alt+C` (уже занято) → показывается ошибка «Эта комбинация уже
  занята одним из хоткеев выше», сохранение НЕ уходит.
- Нажать `V` без модификатора → ошибка «Нужен хотя бы один модификатор».
- Нажать валидную новую комбинацию (например `Ctrl+Shift+M`) → `KeyCap`-и обновляются,
  `POST /api/settings` уходит с `ptt_hotkey` (без реального Python-бэкенда в dev-сервере —
  ожидаем сетевую ошибку в консоли, это нормально для этого окружения, как и в прошлых сессиях
  с dev-сервером без бэкенда).
- Значение переживает `F5` (если бэкенд доступен) — либо остаётся видимым в рамках текущей
  сессии компонента (если бэкенда нет).

- [ ] **Step 4: Обновить `CONTEXT.md`**

Добавить запись сессии (после самой свежей записи в разделе «На чём остановились»,
следуя уже принятому в файле формату) с кратким описанием: что сделано (6-й
хоткей + `play_beep()` + UI захвата), где искать (файлы из Task 1-6), что не
проверено вживую (реальный хоткей в игре — нужен физический F1 25 + клавиатура).

- [ ] **Step 5: Отметить весь план выполненным**
