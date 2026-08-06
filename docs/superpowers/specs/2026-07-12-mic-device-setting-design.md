# Настройка выбора микрофона — Design Spec

**Дата:** 2026-07-12
**Статус:** утверждён, готов к плану реализации
**Источник:** запрос пользователя — «какой микрофон выбирает приложение? Надо добавить настройку»

## 1. Обзор

Сейчас `voice/listener.py::_default_recorder` открывает `sd.InputStream` без параметра
`device` — всегда системный микрофон по умолчанию (тот, что выставлен в Windows), выбора
внутри приложения нет. Добавляем настройку выбора устройства записи (для push-to-talk
voice Q&A, см. `docs/superpowers/specs/2026-07-01-voice-qa-design.md` и
`2026-07-12-voice-radio-mode-design.md`) + кнопку «Проверить» (запись 2 сек + воспроизведение
обратно), по образцу уже существующей «Тест рации» для TTS.

## 2. Правки пользователя

1. **Кнопка «Проверить микрофон» — обязательна** (не просто dropdown). Пользователь явно
   выбрал вариант с проверкой: без неё узнать о неверном выборе устройства можно только
   когда push-to-talk уже не распознаёт вопросы в гонке — слишком поздно.
2. **Место — вкладка «Voice & Engineer»**, новая панель «Микрофон» рядом с уже существующими
   панелями голосового движка/громкости (симметрично: там выход, здесь вход).

## 3. Цели и не-цели

**Цели**
- Список доступных устройств записи, выбор сохраняется в настройках (переживает рестарт).
- Смена устройства применяется без перезапуска приложения.
- Кнопка «Проверить»: запись 2 сек текущим выбранным устройством, воспроизведение обратно
  через колонки того же компьютера (локальный десктоп-pywebview, как и остальной voice-стек).
- Устройство отключили физически / выбранное больше не существует → тот же safe-фолбэк, что
  уже есть у push-to-talk («Микрофон недоступен»), без новой обработки ошибок.

**Не-цели (YAGNI)**
- Live level-meter / визуализация громкости в реальном времени.
- Выбор устройства ВЫВОДА звука (колонки) — не в скоупе этого запроса.
- Тест конкретного (не сохранённого) устройства до сохранения — выбор в dropdown сохраняется
  сразу (как остальные настройки в этой вкладке), «Проверить» тестирует уже сохранённое.

## 4. Архитектура

```
[Панель «Микрофон», Voice-view]
  ├─ GET /api/mic_devices → список устройств (dropdown)
  ├─ выбор → POST /api/settings {mic_device: name|null} → engine.apply_settings
  │            → self._voice_listener.set_device(name|null)
  └─ «Проверить» → POST /api/mic_test → engine.test_mic()
                     ├─ self._voice_listener.record(config.MIC_TEST_SEC)
                     │    None → {"ok": false, "error": "Микрофон недоступен"}
                     └─ voice/listener.py::play_back(audio) → колонки
                          сбой → {"ok": false, "error": "Не удалось воспроизвести"}
```

### 4.1 `voice/listener.py`
- `_default_recorder(max_sec, sr, device=None)` — новый параметр `device`, пробрасывается в
  `sd.InputStream(..., device=device)`. Контракт инжектируемого `recorder` в конструкторе
  (2 аргумента `(max_sec, sr)`, см. `tests/test_listener.py`) НЕ меняется — `device` живёт на
  `VoiceListener`, кастомный recorder его не получает (тесты не трогает).
- `VoiceListener.__init__(recorder=None, device: str | int | None = None)` — хранит
  `self._device`. `record()`: если задан кастомный `recorder` — вызывает его как раньше
  (2 арг.); иначе вызывает `_default_recorder(max_sec, sr, self._device)`.
- `VoiceListener.set_device(device)` — обновляет `self._device` на лету (без пересоздания
  объекта — тот же `self._voice_listener` живёт всё время работы движка).
- Новая `list_input_devices() -> list[dict]`: `sd.query_devices()`, фильтр
  `max_input_channels > 0`, `[{"name": str, "index": int, "is_default": bool}]`. Любое
  исключение (PortAudio недоступен и т.п.) → `[]`, лог WARNING — fail-safe, как остальной
  voice-стек.
- Новая `play_back(audio: bytes, sr: int = 48000) -> None`: воспроизведение int16 LPCM mono
  через **отдельный** `sd.OutputStream` (НЕ модульный `sd.play()`/`sd.wait()` — та же гонка с
  глобальным указателем стрима, что уже задокументирована в этом файле и решена в
  `voice/tts.py::_play_wav`/`_interrupt_playback` для TTS-плеера).

### 4.2 `core/settings.py`
Новый ключ в `DEFAULTS`: `"mic_device": None` (имя устройства строкой, как возвращает
`list_input_devices()`; `None` = системное устройство по умолчанию — обратная совместимость
с текущим поведением).

### 4.3 `core/engine.py`
- `self._voice_listener = VoiceListener(device=self.settings.get("mic_device"))` в
  `__init__` (после `self.settings = settings or {}` на строке 110 — `self.settings` уже
  доступен на момент конструирования listener'а).
- `apply_settings()`: `if "mic_device" in settings: self._voice_listener.set_device(settings["mic_device"])`.
- Новый `test_mic() -> dict`: **синхронно** (не в фоновом потоке — в отличие от
  `ask_voice_question`, здесь нет пересечения с critical-гейтом TTS-очереди и не-цель v1 —
  очередь параллельных тестов). Записывает `config.MIC_TEST_SEC` секунд текущим
  `self._voice_listener`; `None` → `{"ok": False, "error": "Микрофон недоступен"}`; иначе
  `voice.listener.play_back(audio)` в `try/except` → сбой воспроизведения →
  `{"ok": False, "error": "Не удалось воспроизвести"}`; успех → `{"ok": True}`.

### 4.4 `config.py`
`MIC_TEST_SEC = 2.0` — длина тестовой записи (рядом с `VOICE_QUESTION_MAX_SEC`).

### 4.5 `web_server.py`
- `GET /api/mic_devices` → `{"devices": [...]}` (из `voice.listener.list_input_devices()`).
- `POST /api/mic_test` → `_json(engine.test_mic())`.

### 4.6 UI — `NewSpotterUI`
- `lib/api.ts`: `mic_device?: string | null` в `SettingsState`; тип
  `MicDevice = {name: string; index: number; is_default: boolean}`; `getMicDevices()`,
  `testMic()`.
- `components/spotter/views/voice.tsx`: новая `Panel label="Микрофон"` рядом с существующими
  панелями голоса. `<select>` со списком устройств (загрузка при монтировании, как `getVoices`
  в этом же файле), опция «Системный микрофон по умолчанию» = `""` → сохраняется как `null`.
  `onChange` сразу сохраняет через `saveSettings({mic_device: value || null})` — как остальные
  настройки в этой вкладке (persona, tts version — без отдельной кнопки «Сохранить»). Кнопка
  «Проверить» → `testMic()`, задизейблена на время запроса (~4 сек: запись + воспроизведение),
  после ответа коротко показывает результат (ok/error).

## 5. Обработка ошибок / граничные случаи

| Ситуация | Поведение |
|---|---|
| Выбранное устройство отключено физически | `sd.InputStream(device=...)` бросает исключение → уже перехватывается в `VoiceListener.record()` (существующий код) → `None` → и push-to-talk (`_run_voice_question`), и `test_mic()` получают уже знакомую ошибку `"Микрофон недоступен"`. Новой обработки не требуется. |
| PortAudio недоступен вообще (`list_input_devices()`) | `[]` — dropdown показывает только «Системный микрофон по умолчанию», кнопка «Проверить» всё равно доступна (использует `sd` напрямую через recorder, не через список). |
| Воспроизведение теста не удалось (нет колонок и т.п.) | `test_mic()` → `{"ok": False, "error": "Не удалось воспроизвести"}`, запись при этом не потеряна зря — просто не услышана. |
| `mic_device` в settings.json указывает на несуществующее имя (после переустановки/смены железа) | Тот же путь, что «отключено физически» — `None` от `record()`, safe-фолбэк. Настройка не сбрасывается автоматически (пользователь увидит «Микрофон недоступен» и перевыберет). |

## 6. Тестирование

- `tests/test_listener.py` — добавить: `VoiceListener(device=...)` пробрасывает `device` в
  дефолтный recorder (мокнуть `sd.InputStream` или проверить через monkeypatch модуля);
  `set_device()` меняет использующееся устройство между вызовами `record()`; кастомный
  `recorder` по-прежнему вызывается с 2 аргументами независимо от `device` (регрессия
  контракта); `list_input_devices()` — фильтрует по `max_input_channels`, помечает
  `is_default`, любое исключение → `[]`; `play_back()` — вызывает `sd.OutputStream` с
  правильным sr/каналами (мок).
- `tests/test_engine_voice.py` (или новый `tests/test_engine_mic_test.py`) — `test_mic()`:
  успех → `{"ok": True}`; `record()`→`None` → `{"ok": False, "error": "Микрофон недоступен"}`;
  сбой `play_back` → `{"ok": False, "error": "Не удалось воспроизвести"}`; `apply_settings({"mic_device": ...})`
  вызывает `set_device` на `self._voice_listener`.
- Полный прогон `pytest` + `npx tsc --noEmit` зелёные.
- Ручная браузер-проверка: dropdown показывает устройства, выбор сохраняется (переживает
  `F5`), кнопка «Проверить» задизейблена во время запроса.
