# Voice Q&A → «Радио-режим» + Topbar — Design Spec

**Дата:** 2026-07-12
**Статус:** утверждён (дизайн, все секции подтверждены пользователем), готов к плану реализации
**Источник:** запрос пользователя — (1) кнопка push-to-talk не видна вне активной гонки;
(2) хочет, чтобы ответы соответствовали радио игры (F1 25 engineer radio) — закрытый набор
тем с точными данными, а не свободная LLM-генерация.
**Предшествует:** `docs/superpowers/specs/2026-07-01-voice-qa-design.md` (первая версия
push-to-talk, LLM-путь). Этот спек заменяет LLM-путь детерминированным.

## 1. Обзор

Два независимых, но связанных изменения:

1. **Видимость.** Кнопка микрофона переезжает из панели «Голосовой вопрос» (Race-view,
   видна только при `hasData`) в topbar — видна всегда, на любой вкладке, задизейблена
   без активной телеметрии.
2. **«Радио-режим».** Вместо свободного LLM-ответа на любой вопрос — закрытый набор из
   3 тем (**погода**, **гэп**, **шины**), которые распознаются по ключевым словам
   (без LLM) и отвечаются детерминированными фразами из реальных данных телеметрии —
   тем же паттерном, что `commentator/radio.py`, `core/strategy_ai/weather_advisory.py`,
   `core/strategy_ai/gap_digest.py`. Вопрос вне этих тем получает фиксированный ответ
   «Возьми фокус на гонку, пока не можем ответить» — не LLM-фолбэк.

LLM-путь (`commentator/query.py`, `self.ai`, `VOICE_ANSWER_TIMEOUT_S`/`VOICE_ANSWER_MAX_WORDS`)
**полностью убирается** из voice-Q&A — осознанное решение пользователя (не оставляем как
запасной вариант). Конвейер становится синхронным сразу после STT — нет второго фонового
потока с join-таймаутом.

## 2. Цели и не-цели

**Цели**
- Кнопка микрофона в topbar, видна на любой вкладке, disabled без `state.connected`.
- 3 темы v1: погода (текущая + прогноз дождя), гэп (впереди/сзади), шины (износ).
- Классификация темы — простые ключевые слова по нормализованному тексту вопроса, без LLM.
- Вопрос вне 3 тем → фиксированный ответ `OFF_TOPIC_ANSWER`.
- Тема распознана, но данных нет (нет телеметрии по этому аспекту) → тематический
  «данные недоступны» ответ (не общий `OFF_TOPIC_ANSWER`).
- Текущая погода (`weather`/`track_temp`/`air_temp` из `parse_session`) сохраняется в
  `self._current_weather` (сейчас парсится, но не хранится).
- Race-view: панель «Голосовой вопрос» удаляется (миграция в topbar), остальные панели
  (Track Map, Лидер гонки, Личный рекорд, Повреждения) не трогаем.
- Topbar: поповер с последним вопросом/ответом (авто-показ на `done`/`error`).

**Не-цели (YAGNI v1)**
- Свободные LLM-ответы на произвольные вопросы (сознательно убраны).
- Расширение набора тем сверх погоды/гэпа/шин (позиция, топливо, стратегия — будущее).
- Дублирование панели в Race-view и кнопки в topbar.
- Изменение гейтов critical/busy — переносятся как есть из v1 (§6).
- Даккинг TTS-плеера, always-on режим, многоходовый диалог — как в исходном спеке.

## 3. Архитектура

```
[Кнопка микрофона, topbar — disabled если !state.connected] → POST /api/voice/ask
        │
        ▼
engine.ask_voice_question()           # без изменений: critical/busy-гейты как в v1
        │
        ▼
voice/listener.py  record() → LPCM bytes | None
        │
        ▼ status → recognizing
yandex_ai/stt.py   YandexSTT.recognize(bytes) → текст | None
        │
        ▼ status → thinking (кратковременно, без LLM-ожидания)
commentator/radio_answer.py  answer_radio_question(question, weather=self._current_weather,
    rain_forecast=self._rain_forecast, gap_front_ms=self._player_gap_front,
    gap_behind_ms=self._player_gap_behind, tyre_wear=self._player_tyre_wear) → строка
        │
        ▼
voice.say(answer, priority="normal") + запись в feed (event_code="USER_Q")
        ▼ status → done, answer записан
```

### 3.1 `commentator/radio_answer.py` (новый, заменяет `commentator/query.py`)

Детерминированный модуль без сети/LLM — тот же паттерн, что `commentator/radio.py` /
`core/strategy_ai/weather_advisory.py` / `core/strategy_ai/gap_digest.py`.

```python
OFF_TOPIC_ANSWER = "Возьми фокус на гонку, пока не можем ответить."

def classify_topic(question: str) -> str | None:
    """lower + без пунктуации, keyword-match -> "weather" | "gap" | "tyres" | None."""

def answer_radio_question(question: str, *, weather: dict | None,
                           rain_forecast: dict | None,
                           gap_front_ms: int | None, gap_behind_ms: int | None,
                           tyre_wear: float | None) -> str:
    """Всегда возвращает непустую строку. Пустой вопрос -> OFF_TOPIC_ANSWER."""
```

Ключевые слова по темам (нормализованные, финальный список фиксируется в реализации):
- **weather**: погода, дождь, дождик, сухо, мокро
- **gap**: гэп, отрыв, разрыв, впереди, сзади, соперник, лидер
- **tyres**: шины, резина, износ, покрышки

Формат ответов (пример, финализируется в плане реализации):
- Погода, дождь в горизонте: `"{WEATHER_LABEL}, {track_temp}° трасса. Дождь через N минут, вероятность M%."`
- Погода, дождя нет: `"{WEATHER_LABEL}, {track_temp}° трасса. Дождя не ожидается."`
- Гэп: переиспользует форматирование `core/strategy_ai/gap_digest._gap_phrase` (без
  мутации trend-состояния трекера — отдельная лёгкая формулировка внутри
  `radio_answer.py`, т.к. `GapDigestTracker.build()` держит `_prev_front_ms`/`_prev_behind_ms`
  для периодических дайджестов и не должен вызываться из voice-Q&A).
- Гэп, лидер (`gap_front_ms` пуст/0): `"Вы лидируете."`
- Шины: `"Износ шин {N}%."`
- Шины, нет данных: `"Данные по износу пока недоступны."`

### 3.2 `core/engine.py`

- `self._current_weather: dict | None = None` — новый инстанс-атрибут, рядом с
  `self._rain_forecast`. В `_update_telemetry` при `packet_id == PACKET_SESSION`:
  `self._current_weather = {"weather": session["weather"], "track_temp": session["track_temp"],
  "air_temp": session["air_temp"]}`.
- `_run_voice_question()`: убираем `self._build_ai_context(...)`, `self.ai`,
  `self.commentator.persona`, `_query.answer_question(...)`. Вместо этого —
  `_radio_answer.answer_radio_question(question, weather=self._current_weather,
  rain_forecast=self._rain_forecast, gap_front_ms=self._player_gap_front,
  gap_behind_ms=self._player_gap_behind, tyre_wear=self._player_tyre_wear)`.
- Гейты `ask_voice_question()` (critical/busy), запись в `feed` (`event_code="USER_Q"`),
  `_should_voice(...)` — без изменений (см. §6 старого спека, переносится как есть).
- `VOICE_ANSWER_TIMEOUT_S`, `VOICE_ANSWER_MAX_WORDS` (config.py) — становятся неиспользуемыми,
  удаляются вместе с `commentator/query.py`.

### 3.3 UI — `NewSpotterUI`

- **`components/spotter/topbar.tsx`**: кнопка-микрофон (лейбл по статусу: «Спросить» /
  «Слушаю…» / «Распознаю…» / «Думаю…»), `disabled` при `!state?.connected`. Поповер под
  кнопкой с последним вопросом/ответом — авто-показ при переходе `voice_query.status`
  в `done`/`error`, закрывается по клику вне или по следующему вопросу.
- Логика (`askVoice()`, `vqBusy`, `vqLabel`) выносится из `race.tsx` в сам `topbar.tsx`
  (или общий хук `useVoiceQuery(state)`, если понадобится переиспользование) — не дублируется.
- **`components/spotter/views/race.tsx`**: панель «Голосовой вопрос» (текущие строки
  234–259) удаляется целиком. Импорт `Mic`, `askVoice` из `race.tsx` убирается (переезжают
  в `topbar.tsx`). `hasData`-условие на остальные панели не трогаем.
- `lib/api.ts`: тип `VoiceQuery`, `askVoice()` — без изменений (уже общие для всего app).

## 4. Модель данных

`state["voice_query"]` — без изменений в форме:
```python
{
    "status": "listening" | "recognizing" | "thinking" | "done" | "error",
    "question": str | None,
    "answer": str | None,
    "error": str | None,
}
```
(`status="thinking"` теперь кратковременный — до первого детерминированного вычисления,
не ждёт LLM.)

Новый внутренний атрибут движка: `self._current_weather: dict | None` —
`{"weather": int, "track_temp": int, "air_temp": int}` (коды `WEATHER_LABEL` из `core/packets.py`).

## 5. Обработка ошибок / граничные случаи

| Ситуация | Поведение |
|---|---|
| Critical-реплика играет сейчас | Без изменений — `{"ok": false, "busy": true, "reason": "critical"}`. |
| Уже идёт другой вопрос | Без изменений — `{"ok": false, "busy": true, "reason": "in_progress"}`. |
| Нет микрофона | Без изменений — `status="error"`, `"Микрофон недоступен"`. |
| Yandex STT недоступен | Без изменений — `status="error"`, `"Распознавание недоступно"`. |
| STT не расслышал | Без изменений — `status="error"`, `"Не расслышал вопрос"`. |
| Вопрос распознан, тема не одна из 3 | `status="done"`, `answer=OFF_TOPIC_ANSWER`. |
| Тема распознана, данных нет (напр. шины без сессии) | `status="done"`, тематический «нет данных» ответ (см. §3.1). |
| Кнопка нажата без телеметрии | Недостижимо — кнопка `disabled` в UI, пока `!state.connected`. |
| `autovoice_enabled=False` | Без изменений — ответ не проговаривается, но `feed`/`voice_query.answer` проставляются. |

## 6. Тестирование

- `tests/test_radio_answer.py` (новый) — классификация по каждой теме (синонимы, регистр,
  пунктуация); формирование фразы из данных (все 3 темы, включая «данные недоступны»
  и «вы лидируете»); вопрос вне тем → `OFF_TOPIC_ANSWER`; пустой вопрос → `OFF_TOPIC_ANSWER`.
- `tests/test_engine_voice.py` (обновление) — конвейер без `ai`/`persona`; проверка, что
  `answer_radio_question` вызывается с текущими `self._player_gap_front/behind`,
  `self._player_tyre_wear`, `self._current_weather`, `self._rain_forecast`; STT/mic/yandex-
  недоступность → `error` (без изменений); busy/critical-гейты (без изменений).
- `tests/test_packets_weather.py` (дополнение) — `self._current_weather` заполняется из
  `PACKET_SESSION` теми же полями, что `parse_session()["weather"/"track_temp"/"air_temp"]`.
- `tests/test_query.py` — удаляется вместе с `commentator/query.py`.
- Фронт: ручная проверка в браузер-превью — кнопка в topbar disabled/enabled по
  `state.connected`, поповер показывает ответ, панель в Race-view отсутствует.
- Полный прогон `pytest` + `npx tsc --noEmit` зелёные.

## 7. Вне рамок (будущее)

- Остальные темы радио-меню F1 (позиция/место, темп, топливо, стратегия).
- Возврат к LLM-ответам как fallback для нераспознанных тем (осознанно отклонено).
- Always-on listening, многоходовый диалог, даккинг TTS-плеера — как в исходном спеке.
