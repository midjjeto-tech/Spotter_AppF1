# Дизайн: Yandex AI-комментатор (замена Piper-пайплайна)

- **Дата:** 2026-06-22
- **Статус:** утверждён (brainstorming), ожидает ревью спеки → план реализации
- **Автор:** Claude (Opus) + Artem

## 1. Контекст и цель

Spotter App — десктопное Python-приложение-компаньон для F1 25: принимает UDP-телеметрию
игры (порт 20777), генерирует голосовые комментарии. Сейчас текст генерируется гибридно
(шаблоны + опционально Anthropic), голос — локальный Piper (ONNX, CPU, русский).

**Цель:** заменить пайплайн на динамического ИИ-комментатора на технологиях Яндекса:
- **Текст** — YandexGPT (Yandex Foundation Models).
- **Голос** — Yandex SpeechKit (TTS).

**Ключевой архитектурный факт:** F1 25 — **отдельный процесс**. Мы только принимаем его
UDP. Наши сетевые вызовы к Яндексу физически не могут «лагать игру» — в худшем случае
задерживают комментарий. Требование «async» здесь означает: (а) не блокировать поток
приёма телеметрии и UI, (б) конвейер GPT→TTS ради низкой задержки реплики.

## 2. Принятые решения (brainstorming 2026-06-22)

1. **Async-модель:** оставляем потоковую модель приложения. Сеть к Яндексу — отдельный
   модуль с выделенным `asyncio`-loop в своём потоке (GPT и TTS через него). Без полного
   asyncio-рефактора движка.
2. **Стратегия текста — гибрид:** YandexGPT на важные события (`critical` / `battle` — как
   уже решает `brain.py`, эту логику не меняем), мгновенные шаблоны на рутину. Дёшево,
   низкая задержка, нейросеть там, где нужен нюанс. (Отдельно: что вообще озвучивать —
   решает фильтр `_should_commentate` в engine, его тоже не трогаем.)
3. **Судьба Piper:** оставляем **тихим офлайн-резервом**. Yandex — основной голос; при
   невалидном ключе / отсутствии сети — мягкая ошибка в лог + автопереключение на Piper,
   комментатор не замолкает.

## 3. Подтверждённые контракты Yandex API

### YandexGPT (Foundation Models)
- **Эндпоинт:** `POST https://llm.api.cloud.yandex.net/foundationModels/v1/completion`
- **Авторизация:** `Authorization: Api-Key <key>` либо `Authorization: Bearer <iam-token>`
  (для IAM также нужен заголовок `x-folder-id: <folder>`).
- **Тело:**
  ```json
  {
    "modelUri": "gpt://<folder_id>/yandexgpt-lite/latest",
    "completionOptions": {"stream": true, "temperature": 0.6, "maxTokens": "100"},
    "messages": [
      {"role": "system", "text": "<системный промпт персоны>"},
      {"role": "user", "text": "<событие гонки>"}
    ]
  }
  ```
- **Стриминг:** `completionOptions.stream = true` → ответ построчным NDJSON, каждый чанк —
  накопленный (не дельта) `result.alternatives[0].message.text`.
- **Ответ (sync):** `result.alternatives[0].message.text`, плюс `result.usage`.
- **Модель:** `yandexgpt-lite` (быстрее/дешевле Pro; достаточно для коротких реплик).

### SpeechKit v1 TTS
- **Эндпоинт:** `POST https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize`
- **Авторизация:** та же (`Api-Key` / `Bearer`).
- **Content-Type:** `application/x-www-form-urlencoded`.
- **Параметры:** `text`, `voice` (по умолч. `oksana`), `emotion` (`neutral`/`good`/`evil` —
  у поддерживающих голосов), `speed` (0.1–3.0, дефолт 1.0), `lang=ru-RU`,
  `format=lpcm`, `sampleRateHertz` (48000/16000/8000), `folderId`.
- **LPCM:** сырой PCM, 16-бит, little-endian, signed, **без WAV-заголовка** → напрямую в
  sounddevice (`np.frombuffer(buf, dtype=np.int16)` → float32 / 32768).
- **Ответ:** аудио целиком (стриминг — только в v3/gRPC; см. §13).

## 4. Архитектура

```
F1 25 (отдельный процесс)
   │ UDP 20777
   ▼
_telemetry_loop (поток)  ──parse──▶ event_queue
   ▼
_commentary_loop (поток)
   │  ① Commentator.create(event)              ← ТЕКСТ (brain.py, гибрид, без изменений)
   │       routine   → templates.render()          мгновенно, бесплатно, офлайн
   │       important → AIProvider.generate() → YandexGPT (async/stream)   ← NEW
   │  ② Voice.say(phrase)                       ← ГОЛОС
   │       enqueue → TTSQueue worker
   │            cache hit → играем dry WAV
   │            miss      → YandexSpeech (LPCM) → играем + кэшируем        ← NEW
   │                        при ошибке → Piper synth                       ← NEW (fallback)
   ▼
sounddevice OutputStream  (+ radio_fx как сейчас)
```

**Async-ядро:** `YandexClient` владеет одним `asyncio`-loop в выделенном daemon-потоке и
общей `aiohttp.ClientSession`. GPT и TTS — корутины на этом loop. Синхронные вызыватели
(commentary-воркер, TTS-воркер) подают корутины через `run_coroutine_threadsafe(coro)` и
ждут `future.result(timeout=...)`. Блокируется только **их собственный фоновый поток** —
поток телеметрии и UI остаются свободными.

## 5. Новые модули (`yandex_ai/`)

Имя пакета — `yandex_ai` (не `yandex`), чтобы не конфликтовать с возможным pip-namespace.

### `yandex_ai/voices.py`
Каталог голосов + резолвер персона→голос (чтобы маппинг был конфигурируемым — см. §9).
```python
# Каталог: какие голоса доступны и какие эмоции поддерживают (для UI-пикера)
AVAILABLE_VOICES: dict[str, list[str]] = {
    "filipp": ["neutral"], "ermil": ["neutral", "good"],
    "alena": ["neutral", "good"], "zahar": ["neutral", "good", "evil"],
    "jane": ["neutral", "good", "evil"], "omazh": ["neutral", "evil"],
    "madirus": ["neutral"], "dasha": ["neutral", "good", "friendly"],
    # ... финальный список и матрица emotion подтверждаются TTS-пробом на этапе реализации
}
DEFAULT_PERSONA_VOICE: dict[str, dict] = { ... }   # дефолты из §9

def resolve(persona: str, overrides: dict | None = None) -> dict:
    """Вернуть {voice, emotion, speed} для персоны с учётом пользовательских оверрайдов."""
```

### `yandex_ai/credentials.py`
Хранение и валидация ключа.
```python
@dataclass
class Credentials:
    api_key: str          # Api-Key ИЛИ IAM-токен (auth-режим определяется флагом)
    folder_id: str
    auth_mode: str = "api_key"   # "api_key" | "iam"

def load() -> Credentials | None          # читает DATA_DIR/yandex_creds.json, расшифровывает
def save(creds: Credentials) -> None       # шифрует (DPAPI) и пишет
def clear() -> None
def auth_header(creds) -> dict[str,str]    # {"Authorization": "Api-Key ..."} | {"Bearer ..."}
```
- Файл: `DATA_DIR/yandex_creds.json`. Значения ключа/токена шифруются Windows DPAPI
  **через `ctypes` (crypt32.dll `CryptProtectData`/`CryptUnprotectData`) — без зависимости от
  pywin32** (на системном Python 3.12, где живёт стек приложения, pywin32 не установлен; ctypes
  в stdlib и работает всегда). Привязано к Windows-аккаунту: файл бесполезен на другой
  машине/юзере. Плейнтекст-фолбэк с предупреждением, если DPAPI недоступен. Folder ID не
  секрет — можно не шифровать.
- Никогда не логируется. В UI маскируется (последние 4 символа).

### `yandex_ai/client.py`
```python
class YandexClient:
    def __init__(self, creds: Credentials): ...
    def start(self) -> None        # поднимает loop-поток + aiohttp.ClientSession
    def stop(self) -> None
    def submit(self, coro) -> concurrent.futures.Future   # run_coroutine_threadsafe
    @property
    def folder_id(self) -> str
    def headers(self, extra: dict | None = None) -> dict  # auth + extra
    async def validate(self) -> tuple[bool, str]          # live-проб (см. §7)
```

### `yandex_ai/gpt.py`
```python
class YandexGPT:
    def __init__(self, client: YandexClient, model: str = "yandexgpt-lite"): ...
    async def acomplete(self, system: str, user: str,
                        max_tokens: int = 100, temperature: float = 0.6) -> str | None
    # высокоуровневый, вызывается из ai_provider (sync-обёртка через client.submit):
    def generate(self, event: dict, persona: str,
                 analytics_context: str | None = None) -> str | None
```
- Системный промпт берётся из существующего `commentator/personas.py` (без изменений).
- `generate` блокирует свой поток через `submit(...).result(timeout=GPT_TOTAL)`; на любой
  ошибке/таймауте → `None` (тогда `brain.py` уходит в шаблоны).

### `yandex_ai/speech.py`
```python
class YandexSpeech:
    def __init__(self, client: YandexClient): ...
    async def asynthesize(self, text: str, voice: str, emotion: str,
                          speed: float, sr: int = 48000) -> np.ndarray | None  # float32 mono
    # sync-обёртка, совместимая с тем, что ждёт voice/tts.py:
    def synthesize(self, text: str, persona: str) -> tuple[np.ndarray | None, int]
```
- LPCM → `np.frombuffer(buf, np.int16).astype(np.float32) / 32768.0`.
- Персона → (voice, emotion, speed) из таблицы `config.YANDEX_PERSONA_VOICE` (§9).
- На ошибке → `(None, sr)` → `voice/tts.py` падает в Piper-fallback.

## 6. Точки интеграции (минимум правок в существующем коде)

| Файл | Изменение |
|------|-----------|
| `commentator/ai_provider.py` | `AIProvider` сохраняет **ту же форму** (`available`, `generate(event, persona, ctx)`), но внутри делегирует на `yandex_ai/gpt.py`. `brain.py` **не трогаем** — гибрид-логика уже там. |
| `voice/tts.py` | Ввести источник синтеза: сначала `YandexSpeech.synthesize`, при `None` — Piper `synthesize`. Кэш, `radio_fx`, очередь — **как есть**. Путь воспроизведения упрощается (Yandex отдаёт полный PCM за раз; посегментный стриминг остаётся Piper-фолбэком). |
| `new_tts/queue_handler.py` | Добавить приоритет + прерывание (см. §8). |
| `core/engine.py` | `self.ai` строится из `Credentials` (Yandex-backed `AIProvider`); ярлык `state["llm_engine"]` → `"YandexGPT"`/`"Шаблоны"`; `apply_settings` принимает смену голоса/speed; новый метод применить credentials. |
| `web_server.py` | `POST /api/yandex/credentials` (save + validate), `GET /api/yandex/status`; `/api/settings` расширить полями `persona_voice`, `speed`. |
| `index.html` | Страница настроек: поля **API Key** + **Folder ID**, кнопка «Проверить и сохранить», индикатор статуса; пикер голоса на персону, слайдер speed. |
| `config.py` | Yandex-эндпоинты, таймауты, `YANDEX_PERSONA_VOICE`, дефолт-модель. |
| `requirements.txt` | `+ aiohttp`. |

**Не трогаем:** `core/telemetry.py`, `core/packets.py`, `core/race_state.py`, `analytics/*`,
`commentator/personas.py`, `commentator/templates.py`, `voice/cache.py`, `voice/radio_fx.py`.

## 7. Валидация ключа

Перед включением комментатора — дешёвый live-проб в `YandexClient.validate()`:
1. Мелкий GPT-запрос (`maxTokens=1`, короткий prompt) — проверяет ключ + folder + доступ к GPT.
2. Крошечный TTS («тест», `format=lpcm`) — проверяет доступ к SpeechKit.

Результаты:
- `401`/`403` → `(False, "Ключ или Folder ID неверны")`.
- Сетевая ошибка/таймаут → `(False, "Нет связи с Yandex Cloud")`.
- Успех → `(True, "Yandex подключён")`, ключ сохраняется, Yandex включается как основной.

До валидности: комментатор работает в режиме **шаблоны + Piper**. Валидация — по нажатию
кнопки в UI и при старте, если сохранённый ключ найден.

## 8. Очередь и приоритетное прерывание

ТЗ: «новые фразы не перекрывали друг друга кашей, а воспроизводились корректно или
прерывали старые по приоритету».

Сейчас `TTSQueue` дропает при переполнении и не прерывает. Изменения:
- `enqueue(text, priority="normal")` — добавить параметр приоритета.
- `priority="critical"`: очистить очередь ожидания **и** прервать текущее воспроизведение
  (`sounddevice.stop()` через флаг-Event, который проверяет play-функция) → проиграть срочную
  реплику. Обычные реплики — просто в очередь (как сейчас).
- В `engine._commentary_loop`: `voice.say(phrase, priority="critical" if event critical else "normal")`.
  → расширить `Voice.say(text, priority="normal")`.

## 9. Персона → голос/эмоция (конфигурируемо)

Дефолтная таблица в `yandex_ai/voices.py` (`DEFAULT_PERSONA_VOICE`):
```python
"tv":    {"voice": "filipp", "emotion": "neutral", "speed": 1.0},   # классика TV
"hype":  {"voice": "ermil",  "emotion": "good",    "speed": 1.1},
"calm":  {"voice": "alena",  "emotion": "neutral", "speed": 0.95},
"toxic": {"voice": "zahar",  "emotion": "evil",    "speed": 1.0},
```
**Конфигурируемость (по фидбэку):** маппинг переопределяется через настройки —
`POST /api/settings` поле `persona_voice` (частичный оверрайд на персону), оверрайды
персистятся вместе с остальными настройками. `voices.resolve(persona, overrides)` сливает
дефолт + оверрайд. UI-пикер заполняется из `voices.AVAILABLE_VOICES`, так что пользователь
может экспериментировать (`jane`, `madirus`, `omazh`…) без правки кода.

Системные промпты персон — из `personas.py`, без изменений (уже дают короткие RU-фразы ≤12 слов).

## 10. Латентность

- TTS LPCM 48k → numpy → прямо в sounddevice (без парсинга WAV).
- GPT стримингом; на важном событии ждём короткую (одно предложение, ≤20 слов) фразу,
  затем сразу TTS. Внутрифразового конвейера почти нет (фраза = одно предложение) — выигрыш
  async в неблокировании + таймаутах + параллелизме (прогрев кэша во время live).
- **Кэш остаётся ключевым:** прогретые шаблонные фразы (старт, финиш, спид-трэп…) Yandex
  синтезирует один раз → 0 латентности и **0 стоимости** на повторе. LLM-фразы уникальны
  (кэш-промах — норма, это ок).
- **Ключ кэша (важно — маппинг теперь конфигурируемый):** хэшировать нужно по реальным
  параметрам синтеза, не по имени персоны. Иначе ремап `tv→jane` отдаст старое аудио
  `filipp`. Реализация: в `voice/tts.py` передавать в `cache.path_for(text, speaker)`
  композитный `speaker = f"{voice}|{emotion}|{speed}"` + bump `version` тега на `"yandex-v1"`
  (новый api_version при будущем v3 — снова bump). Сам `voice/cache.py` **не меняется** —
  он просто хэширует `text + "|" + speaker` под версией.
- Таймауты: GPT connect 2с / total 6с; TTS connect 2с / total 5с. По таймауту → фолбэк.

## 11. Обработка ошибок (матрица)

| Ситуация | Код (стабильный) | Поведение |
|----------|------------------|-----------|
| Нет ключа / не введён | `YANDEX_NO_CREDENTIALS` | Yandex выключен, лог-инфо, режим шаблоны+Piper. Игра/UI работают. |
| Невалидный ключ/folder (401/403) | `YANDEX_CRED_INVALID` | Мягкая ошибка в лог + UI-индикатор «красный», Yandex выключен, шаблоны+Piper. |
| Нет связи (DNS/connect) | `YANDEX_NETWORK_ERROR` | Лог + UI; Yandex выключен до повторной валидации. |
| Таймаут GPT | `YANDEX_GPT_TIMEOUT` | `generate()` → `None` → `brain.py` → шаблон. |
| Таймаут/ошибка TTS | `YANDEX_TTS_ERROR` | `synthesize()` → `None` → Piper-синтез той же фразы. |
| Лимит/квота (429) | `YANDEX_RATE_LIMIT` | Лог + временный откат на шаблоны+Piper. |
| Piper тоже недоступен | `TTS_UNAVAILABLE` | `say()` → `False` (как сейчас), тишина, без краша. |
| Исключение в loop-потоке | `YANDEX_INTERNAL` | Логируется, не пробрасывается в телеметрию/UI. |

**Единые коды для UI (по фидбэку):** `validate()` и `GET /api/yandex/status` возвращают
стабильный `code` + человекочитаемый `message`. Коды — стабильные идентификаторы (не для
показа), локализованные строки маппятся в `index.html`. Так UI-индикатор и лог говорят
одинаково, а тексты можно менять без правки бэкенда.

Принцип: **ни один сбой Yandex не валит приложение и не глушит игру.**

## 12. Тестирование (петля верификации)

- **Юнит:** DPAPI encrypt/decrypt round-trip; персона→голос маппинг; LPCM-байты→numpy;
  soft-fail пути (нет ключа / 401 / таймаут → `None`/фолбэк); приоритетная очередь.
- **Мок HTTP:** GPT-ответ → парсинг `result.alternatives[0].message.text`; TTS-ответ → PCM.
- **Smoke (нужен реальный ключ):** `validate()` OK; один GPT→TTS→воспроизведение;
  кэш-хит на повторе фразы; Piper-фолбэк при сбросе ключа; **прерывание — critical-событие
  во время длинной фразы обрывает текущее воспроизведение и играет срочную реплику**;
  смена голоса персоны → новый кэш-ключ (старое аудио не отдаётся).
- **Ручное:** live-сессия F1 25, смена персон на лету, прерывание на critical-событии.

## 13. Открытые вопросы / будущее (вне этой итерации)

- **SpeechKit v3 (gRPC) стриминг** — аудио по чанкам, ниже задержка первого звука. Требует
  `grpcio` + сгенерированные стабы. Оправдано только для длинных реплик; для ≤20 слов v1
  достаточно. Задокументировано как апгрейд.
- **IAM-токены** — поддержать как `auth_mode="iam"` (короткоживущие, 12ч, нужен авто-рефреш
  из OAuth/SA-ключа). v1 — основной режим API-Key (статический, проще для десктопа).
- **Сборка EXE** — `SpotterApp.spec` / `build.ps1` обновить под новый стек (`aiohttp`
  hidden imports; Piper-модели оставить для резерва). Отдельная задача после рабочего dev.

## 14. Сводка изменений файлов

**Новые:** `yandex_ai/__init__.py`, `yandex_ai/voices.py`, `yandex_ai/credentials.py`,
`yandex_ai/client.py`, `yandex_ai/gpt.py`, `yandex_ai/speech.py`.

**Изменяемые:** `commentator/ai_provider.py`, `voice/tts.py`, `new_tts/queue_handler.py`,
`core/engine.py`, `web_server.py`, `config.py`, `index.html`, `requirements.txt`.

**Без изменений:** `core/telemetry.py`, `core/packets.py`, `core/race_state.py`,
`core/f1_metadata.py`, `analytics/*`, `commentator/brain.py`, `commentator/personas.py`,
`commentator/templates.py`, `voice/cache.py`, `voice/radio_fx.py`,
`new_tts/piper_tts.py`, `new_tts/ru_textnorm.py`.
