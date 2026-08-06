# Voice Q&A (Push-to-Talk) — Design Spec

**Дата:** 2026-07-01
**Статус:** утверждён (дизайн + 3 правки пользователя), готов к плану реализации
**Источник:** запрос пользователя — голосовые вопросы во время гонки, без риска перебить critical-озвучку.

## 1. Обзор

Пользователь жмёт кнопку микрофона, задаёт короткий вопрос голосом во время гонки.
Вопрос распознаётся (Yandex SpeechKit STT), передаётся LLM вместе с тем же контекстом
гонки, что уже видит комментатор, и короткий ответ озвучивается обычным приоритетом —
так, чтобы НИКОГДА не перебить критическую озвучку (RCWN, флаги и т.п.).

Fallback-first во всём: нет микрофона / STT недоступен / LLM недоступен / генерация
зависла — пользователь получает короткое честное сообщение, гонка не ломается.

## 2. Правки пользователя (обязательны, зафиксированы при апруве)

1. **Push-to-talk — базовый режим.** Всегда-слушающий режим НЕ делаем (не-цель v1).
2. **Явный гейт «критика важнее».** Если СЕЙЧАС играет critical-приоритетная реплика —
   новый вопрос не запускаем вообще (ни запись, ни STT, ни LLM), сразу отвечаем
   `{"ok": false, "busy": true, "reason": "critical"}`. Причина: не тратить 5–8 секунд
   записи+STT+LLM на ответ, который всё равно лёг бы в очередь позади критики, и не
   создавать у пользователя ощущение «завис» в момент, когда важнее всего послушать радио.
3. **Таймаут-фолбэк в `query.py` + инъектируемый recorder с первого дня.** LLM-вызов в
   voice-Q&A должен иметь СВОЙ (более жёсткий, чем у ambient-комментария) таймаут — если
   генерация затягивается, не держим пользователя, отдаём safe-фолбэк. `voice/listener.py`
   с самого начала принимает recorder через конструктор — тесты никогда не трогают
   реальное аудио-устройство.

## 3. Цели и не-цели

**Цели**
- Push-to-talk (кнопка микрофона в Race-view), ответ голосом при обычном приоритете.
- STT — Yandex SpeechKit (v1 REST), тот же облачный стек, что TTS/GPT.
- Ответ ≤ `VOICE_ANSWER_MAX_WORDS` слов, ТОЛЬКО по данным контекста гонки (анти-галлюцинация).
- Гейт «не отвечаем поверх critical» (правка 2) — busy вместо запуска конвейера.
- Таймаут-ограниченный LLM-вызов (правка 3) — не более `VOICE_ANSWER_TIMEOUT_S` секунд ожидания.
- Один вопрос единовременно (busy-guard) — конкурентные запросы отклоняются, не встают в очередь.
- Побочный канал: вопрос ВСЕГДА обрабатывается (не режется `SessionGuard`/`SituationDedup`,
  не проходит через `event_queue`) — единственная причина отказа: critical-гейт или busy-guard.

**Не-цели (YAGNI v1)**
- Всегда-слушающий режим (см. правку 1).
- Многоходовый диалог / память предыдущих вопросов — каждый вопрос независим.
- Очередь из нескольких вопросов — конкурентный вопрос получает busy, не встаёт в очередь.
- Даккинг/заглушение TTS-плеера во время записи — push-to-talk даёт пользователю
  самому выбрать момент (заметка на будущее, если окажется проблемой на практике).
- Браузерный/удалённый деплой (микрофон только локальный, как в десктопном pywebview).
- Перепроверка critical-гейта в середине конвейера (см. §6) — гейт только на входе.

## 4. Архитектура (юниты и границы)

```
[Кнопка микрофона, Race-view] → POST /api/voice/ask
        │
        ▼
engine.ask_voice_question()
  ├─ Voice.is_critical_active? → да → {"ok": false, "busy": true, "reason": "critical"}
  ├─ voice_query.status уже listening/recognizing/thinking? → {"ok": false, "busy": true, "reason": "in_progress"}
  └─ иначе: state["voice_query"] = {status: listening,...}; фоновый поток → _run_voice_question()
                │
                ▼
        voice/listener.py  record(VOICE_QUESTION_MAX_SEC) → LPCM bytes | None
                │ (None → status=error, "Микрофон недоступен")
                ▼ status → recognizing
        yandex_ai/stt.py   YandexSTT.recognize(bytes) → текст | None
                │ (None → status=error, "Не расслышал вопрос")
                ▼ status → thinking
        commentator/query.py  answer_question(text, context, ai, persona) → короткий ответ
                │ (таймаут/сбой/AI недоступен → FALLBACK_ANSWER, это НЕ error-статус)
                ▼
        voice.say(answer, priority="normal") + запись в feed (event_code="USER_Q")
                ▼ status → done, answer записан
```

### 4.1 `commentator/query.py` (новый)
`answer_question(question, context, ai, persona) -> str`. Строит fact-only промпт
(«отвечай ОДНОЙ фразой ≤N слов СТРОГО по контексту; если данных мало — ответь ровно
FALLBACK_ANSWER»). LLM-вызов идёт в отдельном потоке с `.join(timeout=VOICE_ANSWER_TIMEOUT_S)`
(правка 3) — если поток не успел, забираем FALLBACK_ANSWER и не ждём (осиротевший поток
доиграет и тихо потеряет результат). Пустой вопрос / `ai` недоступен / таймаут / пустой
ответ → `FALLBACK_ANSWER = "Пока нет уверенного сигнала."`. Успешный ответ обрезается до
`VOICE_ANSWER_MAX_WORDS` слов и ~140 символов. Мирроит `commentator/story.py` по духу
(build_prompt/generate раздельно), но не «чистый» модуль в строгом смысле — сам управляет
таймаут-потоком (осознанное отступление от исходного плана ради правки 3).

### 4.2 `yandex_ai/stt.py` (новый) + `yandex_ai/client.py::post_audio`
`YandexSTT.recognize(audio: bytes, sr=48000) -> str | None` — мирроит `YandexSpeech`:
синхронная обёртка, `submit()`+`fut.result(timeout=...)`, любое исключение → None (лог
WARNING). `client.post_audio(url, audio, params, *, connect, total) -> bytes` — как
`post_form`, но raw-body POST + query-параметры (Yandex STT recognize: LPCM в теле,
`folderId/lang/format/sampleRateHertz` в query-строке, не в форме).

### 4.3 `voice/listener.py` (новый)
`VoiceListener(recorder=None)` — правка 3: recorder инъектируется в конструктор с первого
дня (`_default_recorder` — `sounddevice.rec` → int16 LPCM mono bytes). `record(max_sec, sr)
-> bytes | None`; нет устройства / исключение → None (лог WARNING, не падение).

### 4.4 `new_tts/queue_handler.py` + `voice/tts.py` — критический гейт (новое, из правки 2)
`TTSQueue` получает `critical_active` (property на `threading.Event`, ставится/снимается
воркером вокруг `_speak_fn` ТОЛЬКО для `prio==0`/critical). `Voice.is_critical_active`
пробрасывает флаг наружу. Это единственный источник истины для «сейчас играет critical» —
эксплицитно вводится этой фичей, в кодовой базе раньше не было надобности это знать.

### 4.5 `core/engine.py` — оркестрация
`self._voice_listener`, `self._stt` (создаётся в `_start_yandex`, как `YandexSpeech`),
`state["voice_query"]`. `ask_voice_question()` — гейты (критика → busy, занят → busy),
иначе фоновый поток `_run_voice_question()` (приватный, синхронный — тестируется напрямую,
как `_generate_story` vs `generate_story_now`). Использует `self._build_ai_context(...)`
(тот же timeline+analytics, что видит комментатор) и `self._should_voice(...)` (уважает
`autovoice_enabled`, как остальная озвучка). Пишет короткую запись в `feed`
(`event_code: "USER_Q"`), НЕ трогает `event_queue`/`SessionGuard`/`SituationDedup`.

### 4.6 `web_server.py`
`POST /api/voice/ask` → `_json(engine.ask_voice_question())`. `state["voice_query"]`
уезжает в UI автоматически через уже существующий `/api/state` (без нового GET-эндпоинта).

### 4.7 UI — `NewSpotterUI`
`lib/api.ts`: тип `VoiceQuery`, поле `voice_query?` в `SpotterState`, `askVoice()`.
`views/race.tsx`: панель «Голосовой вопрос» — кнопка-микрофон (лейбл меняется по статусу),
последний вопрос+ответ, текст ошибки. Топбар — вне рамок v1 (по решению пользователя).

## 5. Модель данных

`state["voice_query"]` (в `/api/state`), изначально `None`:
```python
{
    "status": "listening" | "recognizing" | "thinking" | "done" | "error",
    "question": str | None,
    "answer": str | None,
    "error": str | None,
}
```

`ask_voice_question()` возвращает (НЕ пишет в state при отказе):
```python
{"ok": True}
{"ok": False, "busy": True, "reason": "critical"}      # правка 2
{"ok": False, "busy": True, "reason": "in_progress"}   # уже идёт другой вопрос
```

## 6. Обработка ошибок / граничные случаи

| Ситуация | Поведение |
|---|---|
| Critical-реплика играет сейчас (правка 2) | `ask_voice_question()` сразу `{"ok": false, "busy": true, "reason": "critical"}`; ничего не пишет в `voice_query`, микрофон не трогаем. Гейт проверяется ТОЛЬКО на входе — если critical стартует ПОЗЖЕ, пока наш ответ уже играет в очереди TTS, действует обычная семантика TTSQueue (critical чистит ожидающие и играет первым — как для любой обычной фразы; не вводим защиту «этот item нельзя вытеснить», см. §3 не-цели). |
| Уже идёт другой вопрос | `{"ok": false, "busy": true, "reason": "in_progress"}`. |
| Нет микрофона / устройство недоступно | `voice_query.status="error"`, `error="Микрофон недоступен"`. |
| Yandex недоступен (`_stt is None` или `_yandex_healthy=False`) | `status="error"`, `error="Распознавание недоступно"` — проверяется ДО записи (не тратим 5с на запись, если уже знаем, что распознавать нечем). |
| STT не расслышал (`recognize()→None`) | `status="error"`, `error="Не расслышал вопрос"`. |
| LLM недоступен / таймаут / пустой ответ | НЕ error — `status="done"`, `answer=FALLBACK_ANSWER` (правка 3: таймаут не должен «зависать»). |
| Ответ длиннее лимита | Обрезается в `query.py` до `VOICE_ANSWER_MAX_WORDS`/~140 символов до озвучки. |
| `autovoice_enabled=False` (глобальный мьют) | Как остальная озвучка: ответ НЕ проговаривается, но запись в `feed` и `voice_query.answer` всё равно проставляются (текстовый ответ виден в UI). |

## 7. Тестирование

- `tests/test_query.py` — LLM-ответ через фейковый `ai`; `ai` недоступен/пусто/долгий
  (монkeypatch задержки > `VOICE_ANSWER_TIMEOUT_S`) → `FALLBACK_ANSWER`; длинный ответ
  обрезается; пустой вопрос → фолбэк.
- `tests/test_client.py` (+тест) — `post_audio` шлёт raw bytes + query-параметры.
- `tests/test_stt.py` — `recognize()` парсит `{"result": "..."}`; пусто/исключение → None.
- `tests/test_listener.py` — инъектируемый `recorder`; исключение/None → None, без падения.
- `tests/test_queue_priority.py` (+тест) — `critical_active` True только пока критический
  `speak_fn` не вернул управление.
- `tests/test_engine_voice.py` — полный конвейер (фейк listener+stt, ai недоступен →
  фолбэк-ответ, `voice.say` вызван с `priority="normal"`); STT/mic/yandex-недоступность →
  `error`; busy-guard (параллельный вопрос); critical-гейт (busy, `voice_query` не тронут).
- Полный прогон `pytest` + `npx tsc --noEmit` зелёные.

## 8. Вне рамок (будущее)

- Always-on listening (осознанно отклонено, правка 1).
- Многоходовый диалог / история вопросов.
- Даккинг TTS-плеера во время записи микрофоном.
- Кнопка/статус в топбаре (сейчас только Race-view).
- Повторная проверка critical-гейта в середине конвейера (см. §6).
