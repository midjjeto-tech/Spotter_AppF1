# Voice Radio Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-form LLM voice Q&A with a closed, deterministic "engineer radio" (weather/gap/tyres, keyword-classified, no LLM) and move the mic button from the Race-view panel into the always-visible topbar.

**Architecture:** New pure module `commentator/radio_answer.py` (keyword topic classification + deterministic phrase building from telemetry already tracked on `F1Engine`) replaces `commentator/query.py` in `core/engine.py::_run_voice_question`. Frontend: mic control moves from `race.tsx`'s conditional panel into `topbar.tsx` (always rendered, disabled without telemetry), with a popover for the last Q&A instead of an inline panel.

**Tech Stack:** Python 3 (pytest), Next.js/React/TypeScript (NewSpotterUI), Tailwind.

**Spec:** `docs/superpowers/specs/2026-07-12-voice-radio-mode-design.md`

---

### Task 1: `radio_answer.py` — topic classification

**Files:**
- Create: `commentator/radio_answer.py`
- Test: `tests/test_radio_answer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_radio_answer.py
from commentator import radio_answer


def test_classify_weather_topic():
    assert radio_answer.classify_topic("какая погода") == "weather"
    assert radio_answer.classify_topic("Будет дождь?") == "weather"
    assert radio_answer.classify_topic("сухо сейчас на трассе?") == "weather"


def test_classify_gap_topic():
    assert radio_answer.classify_topic("какой гэп до лидера") == "gap"
    assert radio_answer.classify_topic("что там впереди") == "gap"
    assert radio_answer.classify_topic("сзади кто-то есть?") == "gap"


def test_classify_tyres_topic():
    assert radio_answer.classify_topic("как шины") == "tyres"
    assert radio_answer.classify_topic("какой износ резины") == "tyres"
    assert radio_answer.classify_topic("покрышки ещё живы?") == "tyres"


def test_classify_unknown_topic_returns_none():
    assert radio_answer.classify_topic("какая тут музыка играет") is None


def test_classify_empty_question_returns_none():
    assert radio_answer.classify_topic("") is None
    assert radio_answer.classify_topic("   ") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'commentator.radio_answer'`

- [ ] **Step 3: Write minimal implementation**

```python
# commentator/radio_answer.py
"""
commentator/radio_answer.py
=============================
Voice Q&A "инженерское радио" — закрытый набор тем (погода/гэп/шины),
keyword-классификация без LLM, детерминированные ответы из данных телеметрии
(тот же паттерн, что commentator/radio.py, core/strategy_ai/weather_advisory.py,
core/strategy_ai/gap_digest.py). См. docs/superpowers/specs/2026-07-12-voice-radio-mode-design.md.

Заменяет commentator/query.py (свободный LLM-ответ) целиком.
"""
from __future__ import annotations

import re

OFF_TOPIC_ANSWER = "Возьми фокус на гонку, пока не можем ответить."

_TOPIC_STEMS: dict[str, tuple[str, ...]] = {
    "weather": ("погод", "дожд", "сухо", "мокро"),
    "gap": ("гэп", "отрыв", "разрыв", "впереди", "сзади", "соперник", "лидер"),
    "tyres": ("шин", "резин", "износ", "покрышк"),
}


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", (text or "").lower())


def classify_topic(question: str) -> str | None:
    """Первая совпавшая тема по стему подстроки (без учёта порядка слов).
    Порядок словаря = приоритет при совпадении нескольких тем сразу."""
    normalized = _normalize(question)
    if not normalized:
        return None
    for topic, stems in _TOPIC_STEMS.items():
        if any(stem in normalized for stem in stems):
            return topic
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add commentator/radio_answer.py tests/test_radio_answer.py
git commit -m "feat: add radio topic classification for voice Q&A"
```

---

### Task 2: `radio_answer.py` — weather answer

**Files:**
- Modify: `commentator/radio_answer.py`
- Test: `tests/test_radio_answer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_radio_answer.py

def _answer(question, weather=None, rain_forecast=None,
            gap_front_ms=None, gap_behind_ms=None, tyre_wear=None):
    return radio_answer.answer_radio_question(
        question, weather=weather, rain_forecast=rain_forecast,
        gap_front_ms=gap_front_ms, gap_behind_ms=gap_behind_ms, tyre_wear=tyre_wear)


def test_weather_answer_no_rain_in_forecast():
    weather = {"weather": 0, "track_temp": 30, "air_temp": 22}
    answer = _answer("какая погода", weather=weather)
    assert answer == "Ясно, 30° на трассе. Дождя не ожидается."


def test_weather_answer_rain_in_forecast():
    weather = {"weather": 1, "track_temp": 28, "air_temp": 20}
    rain_forecast = {"minutes": 15, "rain_pct": 60, "weather": 3}
    answer = _answer("будет дождь?", weather=weather, rain_forecast=rain_forecast)
    assert answer == "Облачно, 28° на трассе. Дождь через 15 минут, вероятность 60%."


def test_weather_answer_no_data():
    answer = _answer("какая погода", weather=None)
    assert answer == "Данные о погоде пока недоступны."


def test_weather_answer_rain_minute_pluralization():
    weather = {"weather": 0, "track_temp": 25, "air_temp": 18}
    rain_forecast = {"minutes": 1, "rain_pct": 40, "weather": 3}
    answer = _answer("погода?", weather=weather, rain_forecast=rain_forecast)
    assert "через 1 минуту" in answer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: FAIL with `AttributeError: module 'commentator.radio_answer' has no attribute 'answer_radio_question'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to commentator/radio_answer.py, after the imports (add these imports at top)
from core.num_to_words import ru_plural
from core.packets import WEATHER_LABEL

# append at end of file

def _weather_answer(weather: dict | None, rain_forecast: dict | None) -> str:
    if weather is None:
        return "Данные о погоде пока недоступны."
    label = WEATHER_LABEL.get(weather["weather"], "неизвестно")
    base = f"{label.capitalize()}, {weather['track_temp']}° на трассе."
    if rain_forecast is not None:
        minutes = rain_forecast["minutes"]
        pct = rain_forecast["rain_pct"]
        min_word = ru_plural(minutes, "минуту", "минуты", "минут")
        return f"{base} Дождь через {minutes} {min_word}, вероятность {pct}%."
    return f"{base} Дождя не ожидается."


def answer_radio_question(question: str, *, weather: dict | None,
                           rain_forecast: dict | None,
                           gap_front_ms: int | None, gap_behind_ms: int | None,
                           tyre_wear: float | None) -> str:
    """Всегда возвращает непустую строку. Пустой/нераспознанный вопрос -> OFF_TOPIC_ANSWER."""
    topic = classify_topic(question)
    if topic == "weather":
        return _weather_answer(weather, rain_forecast)
    return OFF_TOPIC_ANSWER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add commentator/radio_answer.py tests/test_radio_answer.py
git commit -m "feat: add weather topic answer to voice radio"
```

---

### Task 3: `radio_answer.py` — gap answer

**Files:**
- Modify: `commentator/radio_answer.py`
- Test: `tests/test_radio_answer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_radio_answer.py

def test_gap_answer_front_and_behind():
    answer = _answer("какой гэп", gap_front_ms=1200, gap_behind_ms=2500)
    assert answer == "Отрыв впереди 1.2. Отрыв сзади 2.5."


def test_gap_answer_front_only():
    answer = _answer("что впереди", gap_front_ms=800, gap_behind_ms=None)
    assert answer == "Отрыв впереди 0.8."


def test_gap_answer_behind_only():
    answer = _answer("кто сзади", gap_front_ms=None, gap_behind_ms=3000)
    assert answer == "Отрыв сзади 3.0."


def test_gap_answer_leader_when_no_gaps():
    answer = _answer("какой гэп", gap_front_ms=None, gap_behind_ms=None)
    assert answer == "Вы лидируете."


def test_gap_answer_leader_when_gaps_zero():
    answer = _answer("какой гэп", gap_front_ms=0, gap_behind_ms=0)
    assert answer == "Вы лидируете."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: FAIL — gap questions currently fall through to `OFF_TOPIC_ANSWER` (assertion mismatch)

- [ ] **Step 3: Write minimal implementation**

```python
# add to commentator/radio_answer.py, after _weather_answer

def _gap_answer(gap_front_ms: int | None, gap_behind_ms: int | None) -> str:
    if not gap_front_ms and not gap_behind_ms:
        return "Вы лидируете."
    parts = []
    if gap_front_ms:
        parts.append(f"Отрыв впереди {gap_front_ms / 1000:.1f}.")
    if gap_behind_ms:
        parts.append(f"Отрыв сзади {gap_behind_ms / 1000:.1f}.")
    return " ".join(parts)
```

```python
# modify answer_radio_question in commentator/radio_answer.py:
    if topic == "weather":
        return _weather_answer(weather, rain_forecast)
    if topic == "gap":
        return _gap_answer(gap_front_ms, gap_behind_ms)
    return OFF_TOPIC_ANSWER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add commentator/radio_answer.py tests/test_radio_answer.py
git commit -m "feat: add gap topic answer to voice radio"
```

---

### Task 4: `radio_answer.py` — tyres answer + off-topic/empty coverage

**Files:**
- Modify: `commentator/radio_answer.py`
- Test: `tests/test_radio_answer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_radio_answer.py

def test_tyres_answer_with_data():
    answer = _answer("как шины", tyre_wear=42.3)
    assert answer == "Износ шин 42%."


def test_tyres_answer_no_data():
    answer = _answer("какой износ", tyre_wear=None)
    assert answer == "Данные по износу пока недоступны."


def test_off_topic_question_returns_fixed_phrase():
    answer = _answer("какая тут музыка играет")
    assert answer == radio_answer.OFF_TOPIC_ANSWER


def test_empty_question_returns_fixed_phrase():
    assert _answer("") == radio_answer.OFF_TOPIC_ANSWER
    assert _answer("   ") == radio_answer.OFF_TOPIC_ANSWER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: FAIL on the two `test_tyres_answer_*` cases (fall through to `OFF_TOPIC_ANSWER` instead of tyre-specific text); off-topic/empty tests already pass.

- [ ] **Step 3: Write minimal implementation**

```python
# add to commentator/radio_answer.py, after _gap_answer

def _tyres_answer(tyre_wear: float | None) -> str:
    if tyre_wear is None:
        return "Данные по износу пока недоступны."
    return f"Износ шин {round(tyre_wear)}%."
```

```python
# modify answer_radio_question in commentator/radio_answer.py:
    if topic == "weather":
        return _weather_answer(weather, rain_forecast)
    if topic == "gap":
        return _gap_answer(gap_front_ms, gap_behind_ms)
    if topic == "tyres":
        return _tyres_answer(tyre_wear)
    return OFF_TOPIC_ANSWER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_radio_answer.py -v`
Expected: PASS (18 passed)

- [ ] **Step 5: Commit**

```bash
git add commentator/radio_answer.py tests/test_radio_answer.py
git commit -m "feat: add tyres topic answer to voice radio"
```

---

### Task 5: Engine — persist current weather

**Files:**
- Modify: `core/engine.py:142` (near `self._rain_forecast` init), `core/engine.py:835-838` (`_update_telemetry` PACKET_SESSION branch)
- Test: `tests/test_engine_voice.py` (used indirectly in Task 6; no standalone test here — matches existing convention where `_rain_forecast` wiring itself isn't unit-tested separately from `parse_session`)

- [ ] **Step 1: Add the instance attribute**

In `core/engine.py`, find (around line 142):

```python
        self._rain_forecast: dict | None = None
```

Change to:

```python
        self._rain_forecast: dict | None = None
        self._current_weather: dict | None = None
```

- [ ] **Step 2: Populate it from the session packet**

In `core/engine.py`, find (around line 835-838):

```python
        if packet_id == PACKET_SESSION:
            session = parse_session(data)
            self._rain_forecast = session.get("rain_forecast")
            _rain_phrase = self._rain_advisory.check(self._rain_forecast)
```

Change to:

```python
        if packet_id == PACKET_SESSION:
            session = parse_session(data)
            self._rain_forecast = session.get("rain_forecast")
            self._current_weather = {
                "weather": session["weather"],
                "track_temp": session["track_temp"],
                "air_temp": session["air_temp"],
            }
            _rain_phrase = self._rain_advisory.check(self._rain_forecast)
```

- [ ] **Step 3: Run the existing packet/engine test suite to confirm nothing broke**

Run: `python -m pytest tests/test_packets_weather.py tests/test_engine_planner.py -v`
Expected: PASS (all existing tests still green — this change is additive)

- [ ] **Step 4: Commit**

```bash
git add core/engine.py
git commit -m "feat: persist current weather from session packet on engine"
```

---

### Task 6: Engine — rewire voice pipeline to radio_answer

**Files:**
- Modify: `core/engine.py:47` (import), `core/engine.py:1395-1439` (`_run_voice_question`)
- Modify: `tests/test_engine_voice.py`

- [ ] **Step 1: Update the failing test first**

In `tests/test_engine_voice.py`, replace the import and the fallback-pipeline test:

```python
# replace line 7:
# from commentator.query import FALLBACK_ANSWER
# with:
from commentator.radio_answer import OFF_TOPIC_ANSWER
```

```python
# replace test_full_pipeline_sets_done_with_fallback_answer with:
def test_full_pipeline_off_topic_question_returns_fixed_phrase(engine):
    """Вопрос не про погоду/гэп/шины -> OFF_TOPIC_ANSWER, весь конвейер
    (listening->recognizing->thinking->done) отрабатывает, голос вызван с priority=normal."""
    _reset(engine)
    engine._stt = FakeSTT("какая тут музыка играет")
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["question"] == "какая тут музыка играет"
    assert vq["answer"] == OFF_TOPIC_ANSWER
    assert engine.voice.said == [(OFF_TOPIC_ANSWER, "normal")]


def test_full_pipeline_weather_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("какая погода")
    engine._current_weather = {"weather": 0, "track_temp": 30, "air_temp": 22}
    engine._rain_forecast = None
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["answer"] == "Ясно, 30° на трассе. Дождя не ожидается."


def test_full_pipeline_gap_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("какой гэп впереди")
    engine._player_gap_front = 1500
    engine._player_gap_behind = None
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["answer"] == "Отрыв впереди 1.5."


def test_full_pipeline_tyres_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("как шины")
    engine._player_tyre_wear = 55.0
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["answer"] == "Износ шин 55%."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine_voice.py -v`
Expected: FAIL — engine still calls the old LLM path, `vq["answer"]` will be the old
`FALLBACK_ANSWER`/LLM text, not `OFF_TOPIC_ANSWER` or the telemetry-derived phrases.

- [ ] **Step 3: Rewire the implementation**

In `core/engine.py`, replace the import at line 47:

```python
from commentator import query as _query
```

with:

```python
from commentator import radio_answer as _radio_answer
```

Then in `core/engine.py`, find `_run_voice_question` (around line 1416-1420):

```python
            self._set_voice_query(status="thinking", question=question)
            context = self._build_ai_context({"event_code": "QUESTION"})
            answer = _query.answer_question(question, context, self.ai,
                                            self.commentator.persona,
                                            self.commentator.analytics_context)
```

Replace with:

```python
            self._set_voice_query(status="thinking", question=question)
            answer = _radio_answer.answer_radio_question(
                question, weather=self._current_weather,
                rain_forecast=self._rain_forecast,
                gap_front_ms=self._player_gap_front,
                gap_behind_ms=self._player_gap_behind,
                tyre_wear=self._player_tyre_wear)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine_voice.py -v`
Expected: PASS (all tests, including the 3 new topic tests and the renamed off-topic test)

- [ ] **Step 5: Run the full backend test suite**

Run: `python -m pytest -q`
Expected: All tests pass except `tests/test_query.py` (still references the soon-to-be-deleted
module — handled in Task 7).

- [ ] **Step 6: Commit**

```bash
git add core/engine.py tests/test_engine_voice.py
git commit -m "feat: rewire voice Q&A to deterministic radio answers"
```

---

### Task 7: Remove the old LLM path

**Files:**
- Delete: `commentator/query.py`
- Delete: `tests/test_query.py`
- Modify: `config.py:135-137`

- [ ] **Step 1: Delete the module and its test**

```bash
git rm commentator/query.py tests/test_query.py
```

- [ ] **Step 2: Remove the now-unused config constants**

In `config.py`, find (around line 135-137):

```python
# --- Voice Q&A (push-to-talk) ---
VOICE_ANSWER_MAX_WORDS = 20     # ответ голосового ассистента — коротко, не лекция
VOICE_ANSWER_TIMEOUT_S = 6.0    # жёстче ambient-таймаута GPT — это диалог, не фон
YANDEX_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
```

Change to:

```python
# --- Voice Q&A (push-to-talk) ---
YANDEX_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
```

- [ ] **Step 3: Run the full backend test suite**

Run: `python -m pytest -q`
Expected: All tests pass, no `ModuleNotFoundError` and no reference to the removed
`VOICE_ANSWER_MAX_WORDS`/`VOICE_ANSWER_TIMEOUT_S`.

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "chore: remove unused LLM voice-answer path (query.py, timeout/word-limit config)"
```

---

### Task 8: Frontend — mic button + popover in topbar

**Files:**
- Modify: `NewSpotterUI/components/spotter/topbar.tsx`
- Modify: `NewSpotterUI/app/page.tsx:44`

- [ ] **Step 1: Rewrite `topbar.tsx`**

Replace the full contents of `NewSpotterUI/components/spotter/topbar.tsx` with:

```tsx
"use client"

import { useEffect, useRef, useState } from "react"
import { Mic } from "lucide-react"
import { Dot } from "./ui"
import { cn } from "@/lib/utils"
import { askVoice } from "@/lib/api"
import type { VoiceQuery } from "@/lib/api"

type Signal = { udp: boolean; voice: boolean; ai: boolean; ses: boolean }

export function Topbar({
  connected,
  signal,
  voiceQuery,
}: {
  connected: boolean
  signal: Signal
  voiceQuery: VoiceQuery | null
}) {
  const chips: { key: keyof Signal; label: string }[] = [
    { key: "udp", label: "UDP" },
    { key: "voice", label: "VOICE" },
    { key: "ai", label: "AI" },
    { key: "ses", label: "SES" },
  ]

  const vqBusy =
    voiceQuery?.status === "listening" ||
    voiceQuery?.status === "recognizing" ||
    voiceQuery?.status === "thinking"
  const vqLabel =
    voiceQuery?.status === "listening" ? "Слушаю…" :
    voiceQuery?.status === "recognizing" ? "Распознаю…" :
    voiceQuery?.status === "thinking" ? "Думаю…" :
    "Спросить"

  const [showPopover, setShowPopover] = useState(false)
  const lastStatus = useRef<string | null>(null)

  useEffect(() => {
    const status = voiceQuery?.status ?? null
    if (status !== lastStatus.current && (status === "done" || status === "error")) {
      setShowPopover(true)
    }
    lastStatus.current = status
  }, [voiceQuery?.status])

  return (
    <header className="relative flex h-12 shrink-0 items-center justify-between border-b border-border bg-card px-6">
      <div className="flex items-center gap-5">
        {chips.map((c) => (
          <div key={c.key} className="flex items-center gap-2">
            <Dot state={signal[c.key] ? "on" : "off"} />
            <span className="label-mono text-[10px] text-muted-foreground">{c.label}</span>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <div className="relative">
          <button
            onClick={() => {
              if (!connected || vqBusy) return
              setShowPopover(false)
              void askVoice()
            }}
            disabled={!connected || vqBusy}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium",
              !connected || vqBusy
                ? "cursor-not-allowed bg-secondary/40 text-muted-foreground"
                : "bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            <Mic className="h-3.5 w-3.5" />
            {vqLabel}
          </button>
          {showPopover && voiceQuery && (voiceQuery.status === "done" || voiceQuery.status === "error") && (
            <div className="absolute right-0 top-full z-10 mt-2 w-72 rounded-md border border-border bg-card p-3 shadow-lg">
              {voiceQuery.status === "error" ? (
                <p className="text-[11px] text-destructive">{voiceQuery.error}</p>
              ) : (
                <>
                  <p className="text-[11px] text-muted-foreground">«{voiceQuery.question}»</p>
                  <p className="mt-1 text-xs text-foreground/90">{voiceQuery.answer}</p>
                </>
              )}
              <button
                onClick={() => setShowPopover(false)}
                className="mt-2 text-[10px] text-muted-foreground hover:text-foreground"
              >
                Закрыть
              </button>
            </div>
          )}
        </div>

        <div
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-1.5",
            connected ? "border-success/40 bg-success/10" : "border-border bg-secondary",
          )}
        >
          <Dot state={connected ? "on" : "off"} />
          <span
            className={cn(
              "label-mono text-[10px] font-medium",
              connected ? "text-success" : "text-muted-foreground",
            )}
          >
            {connected ? "LIVE" : "NO SIGNAL"}
          </span>
        </div>
      </div>
    </header>
  )
}
```

- [ ] **Step 2: Wire the new prop in `page.tsx`**

In `NewSpotterUI/app/page.tsx`, find (line 44):

```tsx
        <Topbar connected={connected} signal={signal} />
```

Change to:

```tsx
        <Topbar connected={connected} signal={signal} voiceQuery={state?.voice_query ?? null} />
```

- [ ] **Step 3: Type-check**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add NewSpotterUI/components/spotter/topbar.tsx NewSpotterUI/app/page.tsx
git commit -m "feat: move voice mic button to always-visible topbar"
```

---

### Task 9: Frontend — remove voice panel from Race-view

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/race.tsx`

- [ ] **Step 1: Remove the now-unused imports and computed variables**

In `NewSpotterUI/components/spotter/views/race.tsx`, find (lines 1-7):

```tsx
"use client"

import { Mic } from "lucide-react"
import { PageHeader, Panel, TyreChip } from "../ui"
import type { SpotterState } from "@/lib/api"
import { askVoice } from "@/lib/api"
import { cn } from "@/lib/utils"
```

Change to:

```tsx
"use client"

import { PageHeader, Panel, TyreChip } from "../ui"
import type { SpotterState } from "@/lib/api"
import { cn } from "@/lib/utils"
```

Find (lines 35-41):

```tsx
  const vq = state?.voice_query ?? null
  const vqBusy = vq?.status === "listening" || vq?.status === "recognizing" || vq?.status === "thinking"
  const vqLabel =
    vq?.status === "listening" ? "Слушаю…" :
    vq?.status === "recognizing" ? "Распознаю…" :
    vq?.status === "thinking" ? "Думаю…" :
    "Спросить"
```

Delete these 7 lines entirely.

- [ ] **Step 2: Remove the voice panel**

In `NewSpotterUI/components/spotter/views/race.tsx`, find the panel that starts with:

```tsx
            <Panel label="Голосовой вопрос">
              <div className="flex flex-col gap-2">
                <button
                  onClick={() => { void askVoice() }}
```

and ends with:

```tsx
                {vq?.status === "done" && vq.question && (
                  <div className="rounded-md bg-secondary/60 p-2">
                    <p className="text-[11px] text-muted-foreground">«{vq.question}»</p>
                    <p className="text-xs text-foreground/90">{vq.answer}</p>
                  </div>
                )}
              </div>
            </Panel>
```

Delete the entire `<Panel label="Голосовой вопрос">...</Panel>` block (including its
surrounding blank lines so the remaining panels stay consistently spaced).

- [ ] **Step 3: Type-check**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: No errors (confirms no dangling references to `Mic`, `askVoice`, `vq`, `vqBusy`, `vqLabel`).

- [ ] **Step 4: Commit**

```bash
git add NewSpotterUI/components/spotter/views/race.tsx
git commit -m "chore: remove voice Q&A panel from Race-view (moved to topbar)"
```

---

### Task 10: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m pytest -q`
Expected: All tests pass, 0 failures.

- [ ] **Step 2: Run the full frontend type-check**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Manual browser verification**

Start the app's dev preview (see project's `run`/preview tooling), then:
1. Confirm the mic button renders in the topbar on every view (Dashboard, Race, Voice, Events, Settings), not just Race.
2. Without an active telemetry connection, confirm the button is visually disabled and does not trigger `/api/voice/ask` on click.
3. With telemetry connected (or by manually POSTing to `/api/voice/ask` against a running engine with fake STT/listener wired for a smoke test), confirm the button becomes clickable, the label cycles through the busy states, and the popover shows the question/answer on completion.
4. Confirm the Race-view no longer shows a "Голосовой вопрос" panel, and that `USER_Q` feed entries still show up on Dashboard/Events/Debrief/Logs.

- [ ] **Step 4: Update CONTEXT.md**

Append a dated entry to `CONTEXT.md` summarizing: voice Q&A is now closed-topic
(погода/гэп/шины), deterministic, no LLM; mic button moved to topbar, always visible,
disabled without telemetry; `commentator/query.py` removed.

- [ ] **Step 5: Commit**

```bash
git add CONTEXT.md
git commit -m "docs: record voice radio mode in CONTEXT.md"
```
