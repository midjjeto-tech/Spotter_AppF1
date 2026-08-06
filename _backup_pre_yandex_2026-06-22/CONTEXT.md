# Spotter App — Контекст разработки

## Правило ведения контекста

**После каждых 2 выполненных задач** — обновить раздел «На чём остановились» в этом файле:
- что сделано (кратко, по файлам)
- открытые задачи / баги
- следующие шаги

Счётчик задач с начала сессии: 0 / 2  *(сброшен — Piper-TTS миграция завершена 2026-06-21)*

## Что это

Десктопное приложение для F1 25. Принимает UDP-телеметрию от игры,
генерирует голосовые комментарии через Qwen3-TTS-0.6B (русский голос, GPU/CPU),
показывает UI через pywebview + HTML/JS.

**Проект НЕ под git** (`git status` вне репозитория). Если нужны коммиты/ветки —
сначала `git init`, явно спросив пользователя.

---

## Архитектура

```
app.pyw                  — точка входа
├── core/engine.py       — главный контроллер, запускает два потока
│   ├── telemetry_thread — UDP-приём пакетов F1 25 (порт 20777)
│   └── commentary_thread — очередь событий → фраза → озвучка
├── core/telemetry.py    — UDP-сокет, генератор пакетов
├── core/packets.py      — парсинг бинарных пакетов F1 25
├── core/race_state.py   — состояние гонки (позиции, пилоты)
├── core/f1_metadata.py  — метаданные пилотов/команд (Ergast API + статичный словарь)
├── commentator/
│   ├── brain.py         — выбор: LLM или шаблон
│   ├── ai_provider.py   — Anthropic API (опционально)
│   ├── templates.py     — шаблонные фразы (SIMPLE: event_code → список фраз)
│   └── personas.py      — стили комментатора (tv/hype/calm/toxic)
├── voice/
│   ├── tts.py           — Voice: Qwen3-TTS-0.6B (GPU fp32) + pyttsx3 (резерв)
│   └── cache.py         — TTSCache: диск-кэш сгенерированных WAV по hash(text+speaker)
├── new_tts/
│   ├── moss_tts.py      — MossTTS: обёртка OnnxTtsRuntime (CPU/ONNX, 48kHz стерео)
│   └── queue_handler.py — TTSQueue: threading.Queue, последовательное воспроизведение
├── onnx_tts_runtime.py  — копия из OpenMOSS/MOSS-TTS-Nano (не pip-пакет)
├── ort_cpu_runtime.py   — база OnnxTtsRuntime (только onnxruntime + numpy)
├── text_normalization_pipeline.py   — нормализация текста (lazy pynini)
├── tts_robust_normalizer_single_script.py
├── moss_tts_nano/       — stub-пакет: только defaults.py (DEFAULT_OUTPUT_DIR)
└── models/
    ├── MOSS-TTS-Nano-100M-ONNX/         — ONNX граф + веса (~200 MB total)
    └── MOSS-Audio-Tokenizer-Nano-ONNX/  — ONNX кодек (~80 MB total)
├── web_server.py        — Bottle HTTP API на порту 8765
├── index.html           — UI (чистый HTML/CSS/JS, без фреймворков)
└── config.py            — пути, порты, ключи, DATA_DIR
```

### Технологии

| Компонент | Библиотека |
|-----------|-----------|
| GUI | pywebview 6.2.1 (WebView2 / WinForms) |
| HTTP API | bottle 0.13.4 + wsgiref (однопоточный — см. открытые баги) |
| TTS | MOSS-TTS-Nano-100M-ONNX, CPU/ONNX, 48kHz stereo, русский язык |
| Телеметрия | UDP socket, бинарный парсинг |
| Упаковка | PyInstaller 6.21.0 (onefile) |

### Установленные пакеты (системный Python 3.12)

```
bottle==0.13.4
psutil==7.2.2
pywebview==6.2.1
pywin32==312
onnxruntime>=1.20.0     # CPU inference для MOSS-TTS-Nano ONNX моделей
sentencepiece           # токенизатор для MOSS-TTS
torchaudio              # нужен onnx_tts_runtime.py (импортируется на уровне модуля)
sounddevice==0.5.5      # streaming воспроизведение
soundfile==0.14.0       # чтение/запись WAV (stereo)
numpy>=1.24             # обработка аудио-данных
```

`pyttsx3` — установлен как резерв (fallback если MOSS-TTS не загрузится).

**Важно:** `onnx_tts_runtime.py` — НЕ pip-пакет. Лежит в корне проекта.
Скопирован из https://github.com/OpenMOSS/MOSS-TTS-Nano

---

## Голосовой движок (voice/tts.py) — MOSS-TTS-Nano-100M-ONNX

### История движков TTS

1. Piper (английский) → заменён на Silero (русский, офлайн)
2. Silero v4_ru (локальный `.pt`, torch CPU) → заменён на Qwen3-TTS (сессия 2026-06-19)
   - Причина замены: задержка Silero ~500ms, нет streaming, блокировал телеметрию
   - Silero-код и папка `silero-models/` полностью удалены
3. Qwen3-TTS-0.6B (GPU, CUDA) → **заменён на MOSS-TTS-Nano** (сессия 2026-06-20)
   - Причина: GPU жрало VRAM во время F1 25 → фризы игры; нужен чистый CPU

### Текущая архитектура (`Voice` + `new_tts/`)

**Модель:** OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX (CPU/ONNX, NOT a pip package)
**Важно:** модели bundled в `models/` (SpotterApp.spec включает `('models', 'models')`)

```python
# new_tts/moss_tts.py
from onnx_tts_runtime import OnnxTtsRuntime
rt = OnnxTtsRuntime(
    model_dir="models/",   # РОДИТЕЛЬСКАЯ папка (не TTS-subdir!)
    thread_count=4,
    execution_provider="cpu",
)
result = rt.synthesize(
    text="Привет!",
    voice=None,             # None = первый встроенный пресет
    prompt_audio_path=None, # None = без клонирования голоса
    enable_wetext=False,    # False = без pynini (не работает на Windows)
)
audio = result["waveform"]    # np.ndarray float32 [N, 2] стерео
sr    = result["sample_rate"] # 48000 Hz
```

**КРИТИЧНО: `model_dir`** — родительская папка с ОБОИМИ ONNX-репо:
- Верно: `models/`
- Неверно: `models/MOSS-TTS-Nano-100M-ONNX/` → падает FileNotFoundError на Audio-Tokenizer

**КРИТИЧНО: `enable_wetext=False`** — `pynini` не устанавливается на Windows; lazy import,
нельзя просто импортировать модуль — нужно явно передать False.

**ONNX external data:** модели используют external data format (`.data` файлы с весами).
Все 4 `.data` файла обязательны: `moss_tts_global_shared.data`, `moss_tts_local_shared.data`,
`moss_audio_tokenizer_encode.data`, `moss_audio_tokenizer_decode_shared.data`.
Без них ONNX Runtime падает с: `External data path does not exist`.

### Голоса по персонам

Voice cloning не реализован — все персоны используют встроенный пресет модели.

```python
PERSONA_SPEAKER = {
    "tv":    "tv",
    "hype":  "hype",
    "calm":  "calm",
    "toxic": "toxic",
}
```

### Путь воспроизведения (streaming + кэш)

```
say(text) → TTSQueue.enqueue(text)         # не дропает, ставит в очередь
  → TTSQueue._worker (фоновый поток)
    → _play_blocking(text)
         cache hit  → _play_wav(cache_path)  # soundfile.read → sd.play → sd.wait
         cache miss → _play_streaming(text)
              → moss.synthesize_streaming(text)  # делит на предложения regex
                   → runtime.synthesize(sentence)  → result["waveform"] [N,2] @ 48kHz
                   → sd.OutputStream(samplerate=48000, channels=2, blocksize=4800)
                   → stream.write(chunk)  ← первый звук ~200-500ms
              → soundfile.write(cache_path, pcm_int16, 48000, subtype="PCM_16")
```

**Важно о WAV-кэше:** MOSS выдаёт stereo float32 [N, 2] @ 48kHz. Кэш хранится как
PCM_16 stereo через `soundfile`. Нельзя использовать старый `wave` модуль — не умеет stereo.

### Воспроизведение

- Primary: `sounddevice.OutputStream` (streaming, float32 stereo, 48kHz)
- WAV чтение/запись: `soundfile` (поддерживает stereo PCM_16)
- Fallback (sounddevice не установлен): `winsound.PlaySound`
- Fallback TTS (MOSS не загрузился): `pyttsx3`

### TTS-кэш (voice/cache.py — `TTSCache`)

Добавлен для снижения задержки озвучки (запрос пользователя: "как у
gridfather.ai — near-zero latency", но строго офлайн/бесплатно).

- Ключ: `sha1(text + "|" + speaker)` → `DATA_DIR/tts_cache/<hash>.wav`
- WAV-файл кэша = файл воспроизведения, не временный (не удаляется)
- `evict_if_needed()` — LRU по mtime, лимиты `max_files=3000`, `max_mb=300`
- При старте — фоновый прогрев (`_prewarm_cache`): кэширует фразы из
  `templates.SIMPLE` без `{подстановок}` (старт, финиш, спид-трэп и т.п.)
  для текущего спикера
- Смена персоны в настройках → `engine.apply_settings()` → `voice.set_persona()`
  → следующие фразы озвучиваются другим спикером

**Подтверждено сквозным тестом:** повтор одинаковой фразы — 2.75с (генерация)
→ 0.0с (кэш-хит). 4 персоны → 4 разных файла/спикера. Повреждённый файл кэша
не валит приложение, перегенерируется на следующий запрос.

**Важный найденный и исправленный баг:** `tempfile.NamedTemporaryFile()` по
умолчанию создаёт файл на диске `C:` (системный TEMP), а кэш — на `G:`
(где лежит проект). `os.replace()` не может атомарно переносить файлы
между разными дисками Windows → кэш не работал до фикса. Решение:
`tempfile.NamedTemporaryFile(..., dir=os.path.dirname(final_path))` —
временный файл создаётся в той же папке, что и кэш, перенос становится
переносом в пределах одного диска.

### CPU-ограничения

```python
torch.set_num_threads(2)       # не захватывать все ядра
model.to(torch.device("cpu"))  # строго CPU, без CUDA
```

---

## Спеки и планы (docs/superpowers/)

Фича TTS-кэша + персональных голосов прошла полный цикл brainstorming →
spec → plan → subagent-driven реализация:

- `docs/superpowers/specs/2026-06-16-tts-latency-cache-design.md` — дизайн
- `docs/superpowers/plans/2026-06-16-tts-latency-cache.md` — план из 4 тасков

Реализация (`_ensure_cached` + явный `is_cached: bool`, прокидываемый через
весь вызов) — чуть чище, чем в спеке (там была идея сравнивать пути для
определения "это кэш или временный файл" — после фикса бага выше стало ясно,
что сравнение путей ненадёжно, поэтому в коде явный булев флаг). **Спека
формально устарела в этой детали — код важнее.**

---

## Кеширование состояния гонки (engine.py + config.py)

### Проблема (решена)

`_update_telemetry` обновлял `state["race"]` даже когда F1 25 присылал
`PACKET_LAP_DATA` с `position=0` (до старта / после рестарта сессии) —
перезаписывал живую таблицу пустой.

### Решение

**Guard в `_update_telemetry`:**
```python
positions = lap_info.get("positions", {})
if any(v > 0 for v in positions.values()):
    # строим grid и обновляем state["race"]
```

**JSON-кеш:**
- Путь: `config.DATA_DIR / "race_cache.json"`
- Читается при старте приложения → `state["race"]` восстанавливается
- Пишется каждый раз при успешном обновлении таблицы позиций
- Переживает перезапуск EXE

**Новые поля в `state["race"]`:**
```python
{
    "leader": "Макс Ферстаппен",
    "leader_idx": 0,
    "grid": [...],
    "last_update": "14:32:07",   # время последнего обновления
}
```

**UI:** метка `· данные на HH:MM:SS` отображается на странице «Гонка»
через `<span id="race-last-update">`.

---

## Маппинг пилотов (core/f1_metadata.py)

### Проблема (решена)

Когда F1 25 присылал UDP-пакет с пустым именем пилота (AI-машины, ранние пакеты),
`race_state.driver()` возвращал `"машина №X"` — это попадало в шаблоны и в LLM,
ломая погружение.

### Решение

Статичный словарь `F1_2025_BY_NUMBER` в `f1_metadata.py` (номер → имя, команда).
**Логика `enrich_driver`:** сначала Ergast API (если загружен и имя есть),
затем статичный фолбэк по номеру машины. Работает мгновенно без сети.

---

## Файлы сборки

| Файл | Назначение |
|------|-----------|
| `SpotterApp.spec` | Главный конфиг PyInstaller |
| `build.ps1` | Скрипт сборки (проверяет зависимости, вызывает venv-pyinstaller) |
| `dist/SpotterApp.exe` | Готовый EXE |

### SpotterApp.spec — актуальное состояние (после MOSS миграции)

- Убраны: `collect_all('torch')`, `collect_dynamic_libs('torch')`, qwen_tts, transformers, torchaudio, scipy, sklearn, `rthook_torch.py`
- Добавлены: `collect_all('onnxruntime')`, `collect_all('sentencepiece')`
- `datas` включает: MOSS runtime .py файлы + `moss_tts_nano/` + `('models', 'models')`
- **MOSS-TTS модели bundled** в EXE через `('models', 'models')` (~4 MB total)
- `runtime_hooks=[]` (пуст — rthook_torch.py удалён)
- **Ожидаемый EXE**: значительно меньше (~50-100 MB vs ~1.5 GB)
- **Spec не пересобирался** — нужна проверка после MOSS миграции

### build.ps1 — актуальное состояние

- Все строки **на английском** — PowerShell 5.1 читает `.ps1` в системной
  кодировке (CP1251), кириллица в скрипте ломает парсер. Не возвращать
  русский текст в этот файл без явного теста запуска.
- Проверяет перед сборкой: `onnxruntime`, `sentencepiece`, `sounddevice`, `webview`, `bottle`, `psutil`
- Проверяет существование папок `models/MOSS-TTS-Nano-100M-ONNX` и `models/MOSS-Audio-Tokenizer-Nano-ONNX`
- Выводит размер итогового EXE после успешной сборки

---

## Итог сессии (2026-06-20) — MOSS-TTS-Nano миграция ЗАВЕРШЕНА ✅

### Что сделано

**Цель:** убрать GPU из TTS-пути (Qwen3-TTS CUDA фризил F1 25), перейти на CPU-ONNX.

| # | Задача | Изменённые файлы |
|---|--------|-----------------|
| 1 | Удалены старые TTS-файлы | `new_tts/qwen3_tts.py` ❌, `rthook_torch.py` ❌ |
| 2 | Установлены зависимости + скачаны модели | `onnxruntime`, `sentencepiece`, `torchaudio` установлены; `onnx_tts_runtime.py`, `ort_cpu_runtime.py`, `text_normalization_pipeline.py`, `tts_robust_normalizer_single_script.py` скопированы из GitHub; `moss_tts_nano/` создан; модели в `models/` (724 MB) |
| 3 | Создан новый TTS-wrapper | `new_tts/moss_tts.py` ✅, `new_tts/__init__.py` ✅ |
| 4 | Переписан Voice | `voice/tts.py` — MossTTS, 48kHz stereo, soundfile, threading.Event |
| 5–7 | Build-файлы обновлены | `requirements.txt`, `SpotterApp.spec`, `build.ps1` |
| 8 | Smoke test — все тесты прошли | `test_moss_tts.py` |

### Smoke test (2026-06-20, PASSED)

```
[1] Import MossTTS         → OK
[2] No GPU usage           → OK
[3] Synthesis (русский):
    Audio: (161280, 2) float32 @ 48000 Hz
    Duration:  3.36s
    Synth:     2.69s  ← RTF < 1.0 (реальное время!)
[4] soundfile WAV round-trip stereo → OK
```

### Структура моделей на диске

```
models/
├── MOSS-TTS-Nano-100M-ONNX/
│   ├── moss_tts_global_shared.data   ← 420 MB (трансформер-веса)
│   ├── moss_tts_local_shared.data    ← 219 MB (локальный декодер)
│   ├── moss_tts_prefill.onnx         ← граф
│   ├── moss_tts_decode_step.onnx
│   ├── moss_tts_local_*.onnx (3 шт)
│   ├── tts_browser_onnx_meta.json    ← манифест
│   └── tokenizer.model
└── MOSS-Audio-Tokenizer-Nano-ONNX/
    ├── moss_audio_tokenizer_encode.data         ← 42 MB
    ├── moss_audio_tokenizer_decode_shared.data  ← 42 MB
    ├── moss_audio_tokenizer_encode.onnx
    ├── moss_audio_tokenizer_decode_*.onnx (2 шт)
    └── codec_browser_onnx_meta.json
```

### Следующий шаг

`python app.pyw` — проверить живую озвучку в F1 25.

---

## Текущий статус багов

### Решено (за все сессии)

| Баг | Файл | Что сделано |
|-----|------|-------------|
| GPU фризило F1 25 из-за Qwen3-TTS | voice/tts.py, new_tts/ | Мигрировали на MOSS-TTS-Nano (CPU/ONNX, 2026-06-20) |
| EXE не включал Piper DLL | SpotterApp.spec | (устарело — Piper убран целиком) |
| `--console` открывал CMD | build.ps1 | Убран флаг |
| Системный pyinstaller не видел venv-пакеты | build.ps1 | Явный вызов `.venv\Scripts\pyinstaller.exe` |
| Данные гонки сбрасывались при position=0 | engine.py | Guard `any(v > 0)` |
| Данные гонки терялись после перезапуска | engine.py | JSON-кеш race_cache.json |
| "машина №X" попадала в комментарий | f1_metadata.py | Статичный словарь F1_2025_BY_NUMBER |
| Piper не поддерживал русский | voice/tts.py | Заменён на Silero TTS v4_ru |
| Silero грузился из сети, серверы падали | voice/tts.py | Локальная загрузка `v4_ru.pt` через `torch.package.PackageImporter` |
| Ошибка Silero затиралась сообщением pyttsx3 | voice/tts.py | `status_message` теперь хранит обе причины |
| UI показывал путь к Piper в настройках | index.html | Заменено на "Silero модель: models/silero/v4_ru.pt" |
| `build.ps1` падал с ошибкой парсера PowerShell | build.ps1 | Кириллица заменена на английский (проблема кодировки CP1251) |
| SpotterApp.spec тащил мёртвые ссылки на Piper | SpotterApp.spec | Полностью убран Piper, добавлены torch/silero |
| TTS-кэш не работал — `os.replace` через диски | voice/cache.py, voice/tts.py | tempfile создаётся в той же папке, что и кэш (`dir=...`) |
| Файл модели лежал не там, где его ждал код | models/silero/v4_ru.pt | Скопирован из `silero-models/src/silero/model/v4_ru.pt` |
| EXE падал: WinError 1114 при загрузке torch DLL | SpotterApp.spec, rthook_torch.py | `collect_dynamic_libs('torch')` + runtime hook с `os.add_dll_directory` + ctypes preload |
| EXE не находил модель Silero | voice/tts.py | Путь через `config.BASE_DIR`/`config.DATA_DIR`; модель кладётся в `dist/models/silero/` |
| Дизайн UI — пустые экраны, красный везде, плоскость | index.html | Полный редизайн CSS (Design System v2) — см. раздел «UI Design System v2» ниже |

### Открытые баги / задачи

| # | Баг / Задача | Файл | Причина / Статус |
|---|-------------|------|-----------------|
| 1 | ~~EXE падает при запуске: `WinError 1114`~~ | SpotterApp.spec, rthook_torch.py | **Решено.** `collect_dynamic_libs('torch')` + runtime hook rthook_torch.py |
| 2 | ~~Silero-мусор в build.ps1 и spec~~ | build.ps1, SpotterApp.spec | **Решено (2026-06-19).** Убраны проверка silero, копирование v4_ru.pt; добавлены qwen_tts/transformers/sounddevice/soundfile |
| 3 | EXE: Queue TTS не создавался (qwen_tts не bundled) | SpotterApp.spec | **Решено (2026-06-19).** `collect_all('qwen_tts')` + deps в spec → `_wait_and_setup` создаст queue. **EXE не пересобирался — нужна проверка.** |
| 4 | Кнопки UI могут зависать | web_server.py | wsgiref → ThreadedServer (исправлено), но не тестировалось в новом EXE |
| 5 | pyttsx3 не установлен | .venv | Если MOSS-TTS не загрузится — нет резерва |
| 6 | ~~Кэш TTS ломался: `sf.write(.tmp)` без format='WAV'~~ | voice/tts.py | **Решено (2026-06-21).** Добавлен `format='WAV'` в `_save_wav` |

---

## Голосовые файлы (voice cloning)

### Архитектура (2026-06-21)

**Папка:** `DATA_DIR/voices/` (создаётся автоматически при старте)

**Конвенция именования:**
```
voices/tv.wav     → персона TV
voices/hype.wav   → персона Hype
voices/calm.wav   → персона Calm
voices/toxic.wav  → персона Toxic
```

**Поведение:**
- Файл есть → передаётся как `prompt_audio_path` в MOSS-TTS (voice cloning)
- Файл отсутствует → MOSS использует встроенный пресет (нет cloning), приложение НЕ падает
- При смене WAV-файла — нужно очистить `tts_cache/` (старые фразы закэшированы со старым голосом)

**Требования к WAV:** 48kHz, стерео, 5-10 сек, чистый голос без шума

**Модуль:** `voice/voice_manager.py` — `ensure_voices_dir()`, `get_voice_path(persona)`, `list_voices()`, `voice_status()`

**API:** `GET /api/voices` → JSON со статусом всех 4 файлов (found, size_kb)

**UI:** Voice страница → секция "Voice Samples" с индикаторами для каждой персоны

---

## На чём остановились

---

**Сессия 2026-06-21 (препроцессор текста + Руслан основным) — ЗАВЕРШЕНА ✅**

### Голос по умолчанию: Ruslan

`PERSONA_VOICE` в `new_tts/piper_tts.py` пересобран — Руслан (лучшее качество) на основной персоне `tv`:
- `tv → ruslan` (дефолт), `hype → denis` (0.92), `calm → irina` (1.08), `toxic → dmitri`
- `_DEFAULT_VOICE = "ruslan"`. UI (`/api/voices`) подхватывает маппинг автоматически.

### Расширенный `new_tts/ru_textnorm.py`

**ГЛАВНОЕ (проверено через `phonemize`): знак `+` для ударения в Piper НЕ работает** — espeak читает его как слово «плюс» (`з+амок`→«зэ плюс амок»). Акцент `́` (U+0301) и маркеры `ˈ`/`'` тоже игнорируются. **Не использовать `+`** — это сломает речь. Шапка модуля документирует что работает/нет.

Что реально внедрено:
- **Латиница → кириллица (rule 2, главный приём, работает на 100%):** словарь `_LEXICON` (Spotter App→Споттер Апп, Google→гугл, Setup→сетап, DRS→дэ-эр-эс, pit stop→пит-стоп, undercut→андеркат, P2→позиция 2, …) + **фолбэк-транслитерация** любого оставшегося латинского токена (короткие CAPS→по буквам «а-бэ-эс», длинные→транслит). Ни одно англ. слово не доходит до espeak сырым. Подтверждено фонемами: «Spotter App» `spˈɒtəɹ` (англ) → «Споттер Апп» `spˈotʲtʲir` (рус).
- **Дефектные фразы (rule 1):** `_PHRASE_FIXES` («работа спота об готова»→«Работа Споттера полностью завершена»).
- **Год → порядковое (rule 5):** «2026 год»→«две тысячи двадцать шестой год». Остальные числа espeak читает сам корректно.
- **Ударение (rule 3):** только пословным переписыванием через `_STRESS_FIXES` (пуст, расширяемый; трюк с «ё» работает, проверять каждым `phonemize`). Общего способа нет.
- **Паузы (rule 4):** уже делает `_split_segments` в piper_tts (дробление на короткие сегменты).

Тестовая фраза в `web_server.py` очищена от англ.: «Споттер на связи. Проверка радиосвязи, приём.»

**Кэш:** версия бампнута `piper-22k-v1` → `piper-22k-v2` (инвалидация под новый голос+нормализатор).

### Проверка — PASSED
normalize() на 10 кейсах ✓; фонемы после нормализации русские (англ. фонемы ушли) ✓; полный конвейер Voice→Ruslan→кэш на фразах с англ. терминами ✓.

### Находка: слово «связи» звучит криво (ограничение Piper medium)

Пользователь на слух: «связи»/«радиосвязи» произносятся криво и у Ruslan (tv), и у Denis (hype). Фонемы при этом **корректные** (`svʲˈɑʑɪ` = «свя́зи», верное ударение). Респелл `связі`→`svʲˈɑzi` (убирает `ʑ`) — **НЕ помог**, на слух тоже криво. Вывод: это ограничение акустической модели Piper medium на кластере «свя…зи», переписыванием текста не чинится. Решение: убрал слово из тестовой фразы. `_STRESS_FIXES` пуст — связі НЕ добавляли (бесполезно).

Тестовая фраза кнопки TEST RADIO теперь: **«Проверка радио. Голос работает, поехали!»** (чистые слова, проверено фонемами). Сэмпл: `generated_audio/NEW_test_dry.wav`.

### СЛЕДУЮЩЕЕ (завтра) — НЕ начато

- **Регулятор громкости комментаторов** (запрос пользователя). Дизайн-намётка:
  - Простейше — множитель амплитуды на аудио перед воспроизведением в `voice/tts.py`
    (и для кэш-хита `_play_wav`, и для стриминга `_play_streaming`). Либо поле
    `volume` в Piper `SynthesisConfig`. Масштабирование numpy надёжнее (бьёт оба пути).
  - Настройка `volume` (0–100) → `engine.apply_settings` → `voice.set_volume()`.
  - UI: слайдер на странице Voice или в controls на Overview.
  - **Уточнить:** громкость общая или отдельная на каждую персону («для комментаторов»).

---

**Сессия 2026-06-21 (МИГРАЦИЯ TTS: MOSS-TTS-Nano → Piper) — ЗАВЕРШЕНА ✅**

### Почему ушли с MOSS-TTS-Nano

**MOSS-TTS-Nano не умеет русский.** Доказано пятью независимыми способами:
- 18 встроенных голосов — только китайские/английские/японские, русских ноль
- OpenMOSS = Fudan (китайская лаба); README говорит "multilingual" но без списка языков
- Токенизатор дробит русское предложение на 42 токена-огрызка (по буквам) vs 18 чистых сабвордов для английского → русского почти не было в обучении
- Живой тест: русский генерит на 60% больше аудио на символ, чем английский (модель мучается)
- На слух: «ломаная речь, проглатывает себя, звучит по-английски»

**Voice cloning это НЕ чинит:** клонирование переносит тембр, но произношение берётся из выученного маппинга текст→звук. Модель без русского = твой тембр, читающий русский английскими фонемами. Поэтому WAV-клонирование (прошлая сессия) сделало только хуже.

### Новый движок: Piper (ONNX, CPU, нативный русский)

| Параметр | Значение |
|----------|----------|
| Пакет | `piper-tts` 1.4.2 (нативный Windows wheel, espeak-ng встроен) |
| Формат | 22050 Hz, моно |
| RTF | ~0.36 (быстрее реального времени на CPU) |
| Задержка первого сегмента | **136 мс** (после warmup) — цель <200мс достигнута |
| torch | **НЕ нужен** (Piper-путь полностью torch-free) |

**4 русских голоса** (medium, ~60MB каждый, в `models/piper/`):
- `ru_RU-denis-medium` → персона **tv** (length_scale 1.0)
- `ru_RU-ruslan-medium` → персона **hype** (0.92, быстрее)
- `ru_RU-irina-medium` → персона **calm** (1.08, медленнее, женский)
- `ru_RU-dmitri-medium` → персона **toxic** (1.0)

**ВАЖНО:** `ru_RU-denis-high` НЕ существует на HuggingFace (404). У русских Piper-голосов есть только `medium`. ТЗ просило `high` — недоступно, используется `medium` (потолок для русского).

### Новые/изменённые файлы

| Файл | Что |
|------|-----|
| `new_tts/piper_tts.py` ✅ | `PiperVoiceEngine`: 4 голоса (lazy load + warmup), сегментный стриминг для низкой задержки, `PERSONA_VOICE` маппинг |
| `new_tts/ru_textnorm.py` ✅ | `normalize()`: маппинг латиницы F1-жаргона в кириллицу (DRS→дэ-эр-эс, P2→позиция 2, box→бокс). Числа НЕ трогаем — espeak сам читает по-русски |
| `voice/radio_fx.py` ✅ | Эффект рации (numpy-only): FFT bandpass 300–3400 Гц + tanh-grit + squelch-щелчки. Без scipy |
| `voice/tts.py` 🔄 | Полностью на Piper. Кэш хранит «сухой» звук, радио-эффект на воспроизведении (toggle не портит кэш). `set_radio_fx()` |
| `voice/voice_manager.py` 🔄 | Перепрофилирован: статус 4 Piper-голосов для UI (клонирование WAV удалено) |
| `core/engine.py` 🔄 | `apply_settings`: обработка `radio_fx` toggle |
| `web_server.py` | `/api/voices` теперь отдаёт статус Piper-голосов |
| `index.html` 🔄 | Voice-страница: «Russian Voices · Piper», 4 голоса, тоггл Radio FX. Убраны MOSS/Qwen упоминания |
| `requirements.txt` 🔄 | + `piper-tts>=1.4.0`, убран `sentencepiece` |

### Проверка (verification loop) — PASSED

- ru_textnorm: DRS→дэ-эр-эс, box→бокс, P2→позиция 2 ✅
- radio_fx: bandpass + squelch работают ✅
- Все 4 персоны синтезируют чистый русский ✅
- Первый сегмент стриминга: 136 мс ✅
- Кэш round-trip (dry WAV) ✅
- Импорт voice.tts / core.engine / web_server без ошибок, torch не грузится ✅

### Открытые задачи (Piper)

1. **`SpotterApp.spec` и `build.ps1` всё ещё под MOSS** — для EXE надо: добавить `collect_all('piper')` (+ `espeak-ng-data`, `piper_phonemize` данные), datas `('models/piper','models/piper')`, убрать MOSS-модели (700MB). EXE НЕ пересобирался.
2. **Расстановка ударений (ТЗ §2.1)**: espeak ставит ударения сам (неидеально). Словарь `ru_RU-lexicon.txt` + `+` перед ударной НЕ внедрён — это апгрейд (можно `ruaccent`), отложено. Хук — в `ru_textnorm.py`.
3. **Старый MOSS-код** (`new_tts/moss_tts.py`, `onnx_tts_runtime.py`, `ort_cpu_runtime.py`, `models/MOSS-*`) — мёртвый, можно удалить для чистоты/размера.
4. Проверить радио-эффект и голоса вживую на слух (`python app.pyw`).

---

**Сессия 2026-06-21 (TTS cache fix + voice cloning per persona) — ЧАСТИЧНО УСТАРЕЛО:**

> ⚠️ Voice cloning (WAV в `voices/`) больше не используется — Piper не клонирует.
> Фикс кэша (`format='WAV'`) актуален и перенесён в новый `voice/tts.py`.

### Что сделано

| Файл | Изменение |
|------|-----------|
| `voice/cache.py` | Добавлен `cleanup_tmp()` — удаляет `.wav.tmp` файлы при старте |
| `voice/voice_manager.py` | **НОВЫЙ.** Сканирует `voices/`, даёт path для каждой персоны, создаёт папку при старте |
| `new_tts/moss_tts.py` | `synthesize()` и `synthesize_streaming()` теперь принимают `voice_path` → `prompt_audio_path` |
| `voice/tts.py` | Импорт voice_manager; `cleanup_tmp()` при старте; `format='WAV'` в `_save_wav` (главный баг); `voice_path` передаётся во все вызовы MOSS |
| `web_server.py` | `GET /api/voices` — статус WAV файлов |
| `index.html` | Voice страница: секция "Voice Samples" с индикаторами + CSS + `loadVoiceStatus()` JS |
| `voices/` | Папка создана, пустая — класть WAV файлы сюда |

### Корень бага TTS кэша

`soundfile.write(path+".tmp", ...)` без `format='WAV'` → soundfile не умеет определить формат по расширению `.tmp` → `NoFormatSpecified` exception → кэш не писался → каждый раз генерация.

### Следующие шаги

1. Положить в `voices/` четыре файла: `tv.wav`, `hype.wav`, `calm.wav`, `toxic.wav`
2. Запустить приложение — Voice страница покажет статус файлов
3. Если persona → другой голос — **очистить `tts_cache/`** (старые записи с дефолтным голосом)

---

**Сессия 2026-06-20 (UI Pitwall Terminal v3 + scipy/sklearn spec fix):**

### 1. SpotterApp.spec — исправлен баг scipy/sklearn

**Симптом:** EXE при запуске голосового движка выдавал `No module named 'scipy'`.

**Причина:** полная цепочка импортов:
`transformers.generation.candidate_generator` → `sklearn.metrics.roc_curve` → `sklearn.__init__` → `scipy.sparse`

Все три пакета импортируются на уровне модуля при загрузке transformers. Ранее sklearn и scipy были добавлены в `excludes` и удалены из `collect_all` — это ломало EXE.

**Что исправлено в `SpotterApp.spec`:**
- Возвращены `collect_all('scipy')` и `collect_all('sklearn')`
- Оба убраны из списка `excludes` (там остались только `torchvision`, `matplotlib`, `PIL`, `IPython`, `cv2`)

### 2. UI v2 — 10 улучшений (промежуточный этап, теперь включён в v3)

Перед полным редизайном были применены 10 точечных улучшений к старому UI:
- Carbon fiber texture на sidebar (repeating-linear-gradient 45°)
- Accent dot (`:before`) перед `.sec-title`
- Командный цвет (`--team-c`) на `.race-entry` через `border-left: 3px`
- Speed bar (2px прогресс-полоса) под значением скорости
- Цветовые пороги скорости: `spd-fast` (≥285) → amber, `spd-max` (≥330) → red glow
- SVG-иконки для персон вместо эмодзи (TV=монитор, Hype=молния, Calm=прицел, Toxic=черепушка)
- Now-speaking bar: цвет волны = цвет персоны через `--live-pc`
- P1 entry: тонкий красный градиент фона
- Gear ≥7: `.gear-high` → зелёный цвет
- State card при `is-speaking`: тёплый красный оттенок фона

### 3. Полный редизайн UI — Pitwall Terminal v3

**Файл:** `index.html` — полная перезапись CSS + HTML (JS скопирован без изменений).

**Что изменилось:**

| Зона | Изменение |
|------|-----------|
| **Header** | Сжат до 40px. Лейбл + версия слева. Dot-индикаторы с подписями UDP / VOICE / AI / SES справа. |
| **Sidebar** | 220px. Carbon fiber фон. Active item: `inset 3px 0 0 var(--accent)`. Снизу sys-bar: CPU / RAM / GPU READY (IDs `f-cpu`, `f-ram` перенесены сюда из footer). |
| **Footer** | Сжат до 24px. Только PERSONA / LLM / TTS / CONN. |
| **Overview** | Компактный session card: LED + state-main + state-sub + метрики 4×1. Now-speaking bar. Controls panel с 4 toggles + 4 кнопками. Telemetry: 22px mono числа + speed bar. |
| **Voice page** | Горизонтальная сетка 4 персоны (4-column). Отдельная строка: Qwen3-TTS + badge статуса + TEST RADIO. |
| **Events page** | Заголовок "Race Radio Feed". Формат event-big: колонка времени + цветная полоса + текст. |
| **Race page** | Team color left bar, P1 gradient, live standings. |
| **Кнопки** | `border-radius: 8px`, hover: red glow + border-color, active: `scale(.96)`. |
| **Анимации** | `dot-pulse`, `blink`, `fade-in` (page transitions), `wave-bounce`, `pulse-led`, `stop-breathe`. |

**Сохранено:** все JS-IDs, классы, polling-логика, API-запросы — не тронуты.
**Перенесено:** `f-cpu`, `f-ram` из `<footer>` в `.sys-bar` (JS находит по `getElementById`, позиция не важна).

**Цветовая схема:**
```
--bg: #07090D  --bg-panel: #0D1118  --bg-card: #151B26
--accent: #E4002B  --text: #E8EDF5  --text-sub: #77829A
```

### Открытые задачи

- **EXE не пересобирался** с исправлённым spec (scipy/sklearn) — нужен `.\build.ps1`
- **Верификация** `TRACK_ID_TO_GP` и офсетов секторов на live-данных F1 25 (через `diag_lap_offsets.py`)
- Диагностика пустых имён пилотов (если актуально) — см. раздел ниже

---

**Сессия 2026-06-19 (FastF1 analytics layer — РЕАЛИЗОВАНО, 10/10 задач):**

### Что реализовано (subagent-driven, все задачи завершены)

| Файл | Что сделано |
|------|-------------|
| `analytics/__init__.py` | Пустой package marker |
| `analytics/archive.py` | Атомарный JSON read/write: `save_game_session`, `load_game_session`, `list_game_sessions`, `save_f1`, `load_f1`, `save_compare`, `load_compare`. Timestamp с микросекундами (`_%f`) для уникальности. |
| `analytics/normalizer.py` | `normalize(session) -> dict`: FastF1 Session → plain dict. Возвращает event, year, results_top10, fastest_lap, best_sectors, safety_cars, penalties. Никогда не raises. |
| `analytics/loader.py` | `TRACK_ID_TO_GP: dict[int, tuple[str, str]]` (24 трека, ключи 0–23). `load_f1_session(track_id, year, session_type)`. FastF1 кэш в `fastf1_cache/`. Коды ошибок: "no_fastf1_data", "rate_limit", "session_not_found", "load_error". |
| `analytics/context.py` | `build_qwen_context(compare, f1_meta) -> str` ≤250 символов, русский, никогда не raises. `_fmt(ms)` обрабатывает ms=0 и отрицательные значения. |
| `analytics/comparator.py` | `compare(game, f1) -> dict`. Всегда возвращает все ключи: comparison_basis, source_coverage, player_best_lap_ms, f1_fastest_ms, gap_ms, qwen_context. Секторы — только при "full" coverage. |
| `core/session_recorder.py` | `SessionRecorder`: `on_lap_complete`, `finalize` (с `_done`-флагом от двойного вызова). `finalize` → `archive.save_game_session`. |
| `core/packets.py` | `parse_player_lap` расширен: `last_lap_ms`, `s1_ms`, `s2_ms`, `s3_ms`. `parse_session` расширен: `track_id` (int8 signed, -1=unknown). |
| `core/engine.py` | `recorder`, `_track_id`, `_prev_lap`, `_session_events` в `__init__`. Лап-детектор в `_update_telemetry`. Хуки SSTA/CHQF/SEND в `_telemetry_loop`. `set_analytics_context()`. |
| `commentator/brain.py` | `analytics_context: str | None = None`. Пробрасывается в `ai.generate()`. |
| `commentator/ai_provider.py` | `generate(..., analytics_context)` — контекст GP вставляется в начало промпта. |
| `web_server.py` | `GET /api/sessions`, `POST /api/load_f1`, `GET /api/archive/<id>`. Защита от path traversal (`Path(compare_id).name`). Корректные HTTP-статусы (400 при ошибках). |
| `index.html` | Вкладка «Архив» с `div.page#page-archive`: пикер сессии, загрузчик FastF1, таблица результатов, lap comparison, контекст Qwen. JS: `arcFmtMs`, `arcLoadSessions`, `arcLoad`, `arcRender`. XSS-защита через `textContent`. |

**Smoke test прошёл:** полный pipeline SessionRecorder → compare → qwen_context → engine.set_analytics_context.

**Важно:** `TRACK_ID_TO_GP` использует предполагаемый порядок 0–23. Для верификации — `diag_lap_offsets.py` (в корне проекта): UDP-листенер для запуска во время live-гонки F1 25. Офсеты секторов в `parse_player_lap` тоже предполагаемые — проверить с реальными пакетами.

**Открытые задачи:**
- Верификация `TRACK_ID_TO_GP` и офсетов секторов на live-данных F1 25
- Запуск `diag_lap_offsets.py` во время гонки и сравнение с ожидаемыми временами

---

**Сессия 2026-06-19 (диагностика: имена пилотов пустые) — НЕЗАВЕРШЕНО, продолжить:**

### Задача из task.md — Задача 1, направление «Телеметрия / имена пилотов»

**Симптом:** в комментаторе всегда выходит "МАШИНА 20 ОБОГНАЛА МАШИНУ 12" — имён нет ни у одного пилота, в любой момент гонки. Проблема НЕ разовая (не только в начале сессии).

**Что проверено:**
- `core/packets.py` — `parse_participants` возвращает `dict[vehicle_idx → {name, team, color, number}]`
- `core/f1_metadata.py` — `enrich_drivers` → `enrich_driver`: сначала Ergast (если загружен), потом `F1_2025_BY_NUMBER` по `number`. Словарь содержит 20 пилотов сезона 2025.
- `core/race_state.py` — `driver(vehicle_idx)` смотрит в `self.drivers`, три уровня фолбэка: имя → "машина №N" → "пилот #X"
- `core/engine.py` — `_telemetry_loop`: при `PACKET_PARTICIPANTS` вызывает `parse_participants → enrich_drivers → race_state.update_drivers`. При `PACKET_EVENT` вызывает `race_state.enrich(event)`.

**Гипотезы (по убыванию вероятности):**
1. **F1 25 изменил формат Participants-пакета** — как было с `LAP_DATA` (offset 28→32). `PARTICIPANT_FORMAT = "<BBBBBBB48sBBHB"` (60 байт) может не совпадать с F1 25. Тогда `_race_no` читает не тот байт → number = 0 или мусор → `F1_2025_BY_NUMBER.get(0)` = None → имя не заполняется.
2. **PARTICIPANTS-пакет не приходит** — UDP работает (телеметрия есть), но `race_state.drivers` остаётся пустым весь матч.
3. **Ergast загружается и перезаписывает** — если Ergast возвращает имя на английском вместо русского, имя технически есть, но это не наша проблема (не "машина X").

**Следующий диагностический вопрос (НЕ задан):**
> Вкладка «Гонка» в UI — там тоже нет имён (показывает "пилот #X")?
> Если да → `parse_participants` ломается или пакет не приходит.
> Если нет (в «Гонке» имена есть) → проблема в `race_state.enrich()` для событий.

**Файлы для изучения:**
- `core/packets.py` строки 67-68, 93-123 — `PARTICIPANT_SIZE`, `PARTICIPANT_FORMAT`, `parse_participants`
- `core/engine.py` строки 279-285 — обработка `PACKET_PARTICIPANTS`
- `core/f1_metadata.py` строки 119-154 — `enrich_driver`
- `core/race_state.py` строки 42-64 — `driver()`

**Если надо добавить диагностику:**
В `engine.py` строка 282, после `parse_participants(data)` добавить лог:
```python
import logging
logging.warning(f"PARTICIPANTS: {list(drivers.items())[:3]}")
```
Это покажет что реально приходит в первых трёх записях.

---

**Сессия 2026-06-19 (фикс сборки: убрать Silero, добавить Qwen3-TTS в spec):**

| Файл | Что сделано |
|------|-------------|
| `build.ps1` | Убрана проверка пакета `silero`; убрано копирование `v4_ru.pt` в dist; добавлена проверка `qwen_tts`, `sounddevice` |
| `SpotterApp.spec` | Убраны `collect_all('silero')` + hiddenimports silero; добавлены `new_tts` в datas, `collect_all` для qwen_tts/transformers/sounddevice/soundfile; обновлены hiddenimports |

**Корень бага Queue TTS в EXE:** `qwen_tts` не был в spec → `ImportError` в `_load` → `is_ready=False` → `_wait_and_setup` уходил в pyttsx3 (не установлен) → queue не создавался → `say()` возвращал `False` → тишина.

**Следующий шаг:** запустить `.\build.ps1` и проверить, что Queue TTS работает в EXE.

---

**Сессия 2026-06-19 (рефакторинг TTS: Silero → Qwen3-TTS):**

| Файл | Что сделано |
|------|-------------|
| `new_tts/__init__.py` | Создан пакет |
| `new_tts/qwen3_tts.py` | Обёртка `Qwen3TTS`: загрузка `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`, streaming по предложениям, `torch.float32` (fp16 падает на GTX 1660 SUPER) |
| `new_tts/queue_handler.py` | `TTSQueue`: `threading.Queue(maxsize=8)`, события не дропаются и не перебивают друг друга |
| `voice/tts.py` | Полная замена Silero → Qwen3-TTS, публичный интерфейс не изменён |
| `requirements.txt` | `qwen-tts`, `sounddevice>=0.4`, `soundfile>=0.12`, `torch>=2.1` |
| `environment.yml` | Создан (conda, Python 3.12) |
| `test_silero.py` | Удалён |
| `silero-models/` | Удалена вся папка |

**Установлено:** `torch 2.6.0+cu124`, `qwen-tts`, `sounddevice 0.5.5`, `soundfile 0.14.0`

**Тест прошёл:** `"Машина слева"` → 57600 сэмплов, 24000 Hz, ~2.4 сек аудио ✅

**Следующие шаги:**
- Запустить `python app.pyw` и проверить озвучку вживую
- Проверить, что SoX установлен (`sox --version`) — нужен qwen-tts для постобработки; без него работает, но могут быть предупреждения
- Обновить `SpotterApp.spec` под новый стек (убрать Silero/torch CPU, добавить qwen-tts)
- **EXE-сборка не тестировалась** с новым TTS-движком

---

**Сессия 2026-06-18 (фиксы парсинга F1 25 + имён + FTLP — завершено):**

| Файл | Что сделано |
|------|-------------|
| `core/packets.py` | `parse_lap_data` / `parse_player_lap`: убран `+1` из base, смещение позиции исправлено с 28 → **32** (в F1 25 `m_carPosition` сдвинулся из-за добавленных delta-полей). Без этого фикса safety car delta читалась как позиция → всегда 0 → таблица гонки вечно пустая, `race_cache.json` никогда не писался |
| `core/f1_metadata.py` | `enrich_drivers`: убран ранний `return drivers` когда Ergast не загружен — статический словарь `F1_2025_BY_NUMBER` теперь работает всегда |
| `core/race_state.py` | `driver()`: `info.get("number") is not None` → `info.get("number")` — число 0 (MY TEAM без номера) больше не даёт "машина №0", падает в "пилот #{vehicle_idx}" |
| `core/engine.py` | `_should_commentate` auto-режим: добавлен guard `FTLP` — быстрейший круг теперь всегда озвучивается независимо от того, чья машина |

---

**Сессия 2026-06-18 (фиксы багов — завершено):**

| Файл | Что сделано |
|------|-------------|
| `voice/tts.py` | Удалён осиротевший вызов `self._debug_log(...)` — Silero падал с `AttributeError` сразу после успешной загрузки |
| `web_server.py` | `wsgiref` → `_ThreadedServer` (`ThreadingMixIn + WSGIServer`) — кнопки UI больше не зависают во время синтеза |
| `voice/tts.py` | Per-key lock в `_ensure_cached` — двойная генерация при параллельном прогреве кэша + live `say()` устранена |
| `voice/cache.py` | `evict_if_needed()` фильтрует только `[a-f0-9]{40}.wav` — не удаляет залипшие tempfile |

Открытые баги после сессии: №2, №4 (низкий приоритет), №5 и №6 — закрыты.

---

**Сессия 2026-06-18 (персона-фразы + глобальные хоткеи — завершено):**

### Задача A: Персона-специфичные фразы (ВЫПОЛНЕНО)

Добавлены пулы фраз для каждой персоны в `commentator/templates.py`:

- `PERSONA` dict: `hype / calm / toxic` × 7 событий (`OVTK, RCWN, RTMT, PENA, CHQF, SSTA, FTLP`), 5–6 фраз на событие
- `tv` намеренно **отсутствует** в `PERSONA` — TV-стиль живёт в `SIMPLE` (fallback). Комментарий в коде предупреждает не добавлять `tv` туда.
- `render(event, persona)` — BATTLE-проверка идёт первой, потом `PERSONA.get(persona, {}).get(code) or SIMPLE.get(code)`
- `commentator/brain.py` line 34: `templates.render(event, self.persona)`

Спека и план в:
- `docs/superpowers/specs/2026-06-17-persona-phrases-design.md`
- `docs/superpowers/plans/2026-06-18-persona-phrases.md`

### Задача B: Глобальные хоткеи (ВЫПОЛНЕНО)

Новый файл `core/hotkeys.py` — `GlobalHotkeyManager` через Win32 `RegisterHotKey`.
**Нулевые новые зависимости** — pywin32==312 уже установлен.

| Хоткей | Действие |
|--------|----------|
| Ctrl+Alt+C | Вкл/выкл комментарий |
| Ctrl+Alt+P | Следующая персона (tv→hype→calm→toxic→tv) |
| Ctrl+Alt+T | Тест голоса |
| Ctrl+Alt+X | Очистить ленту событий |
| Ctrl+Alt+S | Скрыть/показать окно Spotter поверх F1 25 |

Архитектура:
- Daemon-поток с `GetMessageW` loop — не блокирует основной поток
- `RegisterHotKey(None, id, mods, vk)` → OS-уровень, работает когда F1 25 в фокусе
- `_toggle_window`: `window.hide()/show()` + `win32gui.SetForegroundWindow` для подъёма поверх игры
- `PostThreadMessageW(WM_QUIT)` для чистого завершения при выходе

`app.pyw` изменён:
```python
from core.hotkeys import GlobalHotkeyManager
# ...
hkm = GlobalHotkeyManager(engine, window, _settings)
hkm.start()
webview.start(debug=False)
hkm.stop()
```

`index.html` line 1092 обновлён: "не поддерживаются в браузере" → "работают глобально, даже когда F1 25 в фокусе"

### Задачи C/D (НЕ начаты)

- **C:** Persist quick settings между перезапусками — `_settings` сейчас сбрасывается к дефолтам при каждом старте. Нужно сохранять в JSON рядом с `race_cache.json`.
- **D:** Profile tab — дать реальный смысл. Сейчас вкладка «Профиль» пустая. Идея: статистика сессии (кол-во событий, любимый комментатор, топ событий).

### Задача E (отложена, пользователь сделает сам)

Иконки F1 25 и логотип проекта — пользователь решил сделать самостоятельно. Дизайн-варианты были показаны в brainstorming-сессии (шлем, болид сверху, руль, типографика F1).

---

**Сессия 2026-06-17 (UI редизайн — завершено):**

Полный редизайн `index.html` CSS без изменения HTML-структуры. Все классы остались прежними.
Детали — в разделе «UI Design System v2» ниже.

---

**Сессия 2026-06-17 (WinError 1114 — решено):**

EXE падал при запуске с:
```
Silero: [WinError 1114] Произошел сбой в программе инициализации библиотеки
динамической компоновки (DLL). Error loading "..._MEI138082\torch\lib\c10.dll"
or one of its dependencies. | pyttsx3 not installed
```

**Что проверили и отвергли:**
- UPX-сжатие (EXE пересобирался с `upx=False` — не помогло)
- Smart App Control / AppLocker / антивирус (порты/блокировки)
- Отсутствие VC++ Redistributable (EXE запускается на той же машине)
- "Файлы не успели распаковаться" — артефакт гонки при внешнем опросе FS

**Root cause — подтверждено:**
Из свежего запуска EXE в `_MEI87002` содержалось только:
```
PyQt5/
MSVCP140_ATOMIC_WAIT.dll
```
Каталога `torch/lib/` нет вообще — `collect_all('torch')` в `SpotterApp.spec`
**не собирает бинарные DLL torch** (`.dll` файлы в `torch/lib/`) на Windows.
Dev-режим (`python -c "import torch; print(torch.zeros(3))"`) работает штатно.

**Диагностическая инструментация в коде:**
В `voice/tts.py` добавлены временные методы `_debug_dump_meipass()` и `_debug_log()`
— пишут в `_debug_torch_load.log` рядом с EXE. **Удалить после фикса.**
`SpotterApp.spec` остался с `upx=False` (было `True`) — безвредно, но не откатано.

**Фикс применён (2026-06-17):**
- `SpotterApp.spec`: добавлен `collect_dynamic_libs('torch')` поверх `collect_all('torch')`
- `rthook_torch.py`: runtime hook — `os.add_dll_directory(torch/lib)` + предзагрузка DLL через ctypes
- `voice/tts.py`: путь к модели теперь через `config.BASE_DIR` → `config.DATA_DIR` (не через `__file__`)
- Модель `v4_ru.pt` кладётся рядом с EXE: `dist/models/silero/v4_ru.pt`

---

**Последняя сессия (2026-06-16):**

1. Полностью переписан `voice/tts.py` под Silero v4_ru — три итерации:
   pip-пакет `silero` → отклонён тикет про несуществующий "v5_ru" → локальная
   загрузка `.pt` через `torch.package.PackageImporter` (финальная версия).
2. Исправлены UI-баги: затёртая ошибка Silero, упоминания Piper в настройках.
3. Переписаны `build.ps1` (англ. строки, проверка зависимостей) и
   `SpotterApp.spec` (Piper убран, torch+silero добавлены).
4. **Большая фича:** TTS-кэш + голос под персону комментатора — полный цикл
   brainstorming → spec → plan → subagent-driven implementation (4 таска,
   каждый с двухэтапным ревью: spec compliance + code quality). По пути
   найден и исправлен реальный баг с кросс-дисковым `os.replace`, а также
   обнаружено и исправлено расхождение пути модели на диске.
5. Сквозная проверка пройдена программно (кэш-хиты, персоны, восстановление
   после повреждения). **Не проверено на слух** — естественность голоса и
   ощущение от реального запуска приложения нужно проверить руками.

**Следующие шаги (предложение, не выполнено):**
- Запустить приложение и послушать голос/смену персон вживую
- Прогнать `build.ps1` и проверить, что EXE с новым кодом (кэш + локальная
  модель) реально запускается — этого не делали
- Решить, нужно ли класть `models/silero/v4_ru.pt` в `datas` spec-файла
  для полностью автономного EXE, или это всегда отдельный файл рядом
- Установить `pyttsx3` для реального резерва, если Silero когда-нибудь
  откажет

---

## UI Design System v3 — Pitwall Terminal (index.html)

Финальный редизайн выполнен в сессии 2026-06-20. Полная замена CSS + HTML, JS скопирован без изменений.

### Актуальная палитра

```css
--bg: #07090D       /* основной фон */
--bg-sidebar: #0A0D13
--bg-panel:  #0D1118
--bg-card:   #151B26
--bg-elevated: #1C2333
--accent:    #E4002B
--text:      #E8EDF5
--text-sub:  #77829A
--text-muted: #3D4A60
--header-h:  40px   /* сжатый header */
--footer-h:  24px   /* минимальный footer */
--sidebar-w: 220px
```

### Ключевые структурные изменения v3

- `f-cpu`, `f-ram` перенесены из `<footer>` в `.sys-bar` в сайдбаре (JS не сломан)
- Sidebar: nav section label "NAVIGATION" + sys-bar (CPU/RAM/GPU READY) снизу
- Header: `hdr-indicators` с `hdr-dot-group` (`.light` + `.hdr-dot-label`) вместо старого `.lights`
- Overview: `state-card-header` (LED + state-main в ряд) + `state-sub` отдельно
- Voice page: `voice-layout` > `persona-grid` (4 колонки) + `voice-engine-row`
- Все кнопки: `border-radius: 8px`, hover: red glow + border-color, active: scale(.96)

### История версий дизайна

- **v1** (сессия 2026-06-16): исходный базовый CSS
- **v2** (сессия 2026-06-17): Design System — палитра, тени, elevation, пустые состояния, трасса
- **v2.1** (сессия 2026-06-20): 10 улучшений — carbon fiber, speed bar, persona icons, gear color, team colors, speaking warmth
- **v3** (сессия 2026-06-20): Pitwall Terminal — полная переработка под F1 TV / pitwall aesthetic

### Что сохраняется неизменным между версиями

- HTML id атрибуты — не меняются никогда
- JS polling и API — не меняются
- Имена классов, которые добавляет/убирает JS: `.state-led.ok`, `.state-led.speaking`, `.wave-icon.active`, `.now-text.speaking`, `.persona-card.selected`, `.nav-item.active`, `.btn-primary.stopping`, `.now-speaking-bar.persona-live`, `.state-card.is-speaking`, `.log-filter.active`, `.telem-value.spd-fast`, `.telem-value.spd-max`, `.telem-value.gear-high`, `.light.red`, `.light.green`

### Ключевые решения

**Палитра:** фоны стали глубже и немного синеватее (`--bg: #07090c`), система уровней
`bg → bg-panel → bg-card → bg-elevated`. Красный сохранён как акцент, но используется
в 3–4 местах (brand, активная навигация, P1, кнопка стоп) — не повсеместно.

**Система теней (elevation):**
```
--shadow-card:  0 1px 3px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.04)
--shadow-panel: 0 4px 16px rgba(0,0,0,.45), ... inset highlight
--shadow-hover: 0 6px 24px rgba(0,0,0,.55)
```

**Активный пункт сайдбара:** левый «нож» вместо красного фона:
```css
.nav-item.active { box-shadow: inset 3px 0 0 var(--accent); background: rgba(232,0,45,.07); }
```

**Персоны:** у каждой карточки `border-left: 3px solid var(--pc)` в своём цвете:
```
tv    → --p-tv:    #b0b8c8  (серебро)
hype  → --p-hype:  #fb923c  (оранжевый)
calm  → --p-calm:  #38bdf8  (голубой)
toxic → --p-toxic: #c084fc  (фиолетовый)
```
Работает через CSS-переменную `--pc` на самом элементе.

**Кнопка СТОП:** класс `.stopping` добавляется через JS (`updateCommentatorBtn`):
```css
.btn-primary.stopping { background: gradient(тёмный красный); animation: stop-breathe; }
```
JS-функция `updateCommentatorBtn()` теперь добавляет/убирает класс `.stopping`.

**Toggle-переключатель:** фон `var(--bg-elevated)`, бегунок серый → красный при включении.
Не ярко-красный фон трека как раньше.

**Пустые состояния — три уровня:**
- `.empty-events` — компактный (sidebar): иконка 36px, `<strong>` заголовок
- `.empty-full` — полноразмерный (страница событий, гонки): иконка 52px + шаги `01/02/03`
- Гонка и события: шаги с `<span class="empty-step-n">` (mono, цвет accent, opacity .65)

**Трасса:** `border-radius: 42% 52% 40% 54% / 48% 40% 52% 42%` — асимметричный органичный
овал вместо дефисного круга.

**Позиции в гонке:**
```css
.race-entry:first-child .position  → color: var(--accent) + text-shadow glow
.race-entry:nth-child(2/3) .position → color: #fff
/* P4+ */ .position                → color: var(--text-sub)
```

**Скроллбар:** нейтральный белый `rgba(255,255,255,.1)` вместо красного.

**Шрифтовая иерархия:** section labels 10px / 9px, 700, letter-spacing 2.2px.
Размеры в `telem-value` не менялись.

### Что НЕ менялось

- HTML-структура, id, data-атрибуты — не тронуты
- JS-логика, poll, события, API-запросы — не тронуты
- Имена классов — все старые имена сохранены, добавлены новые:
  `.empty-full`, `.empty-full-icon`, `.empty-full-title`, `.empty-full-desc`,
  `.empty-steps`, `.empty-step`, `.empty-step-n`, `.stopping`, `.bg-elevated`

---

## Важные пути

```
config.py → BASE_DIR       ← sys._MEIPASS в EXE, dirname(__file__) в dev (read-only ресурсы)
config.py → DATA_DIR       ← dirname(sys.executable) в EXE, dirname(__file__) в dev (запись)
race_cache.json            ← DATA_DIR/race_cache.json (кеш таблицы позиций)
~/.cache/huggingface/      ← модель Qwen3-TTS (~1.2 ГБ, скачивается автоматически при первом запуске)
DATA_DIR/tts_cache/        ← диск-кэш сгенерированных WAV-фраз (TTSCache)
```
