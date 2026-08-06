# Голос инженера отдельно от комментатора — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Командные реплики (box-вызов, advisory, будущие Фазы 2-4) озвучивает
голос инженера (персона `calm`, Yandex `marina`), а выбранная персона
комментатора даёт поверх свою короткую реплику в третьем лице — через
per-utterance persona override, протащенный явным параметром сквозь очередь TTS.

**Architecture:** `Voice.say(persona=...)` → `TTSQueue` несёт `(prio, seq, text,
persona)` → `_play_blocking(text, persona)`. Низ пайплайна (`_voice_key`,
`_synthesize`, кэш) уже параметризован персоной. Маршрутизация — признак
`event["speaker"] = "engineer"` в `core/engine.py`. Новое событие
`PIT_CALL_NOTICE` (только с tier 1 box-вызова) идёт обычным LLM-пайплайном
голосом комментатора.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git — шаги «commit»
отсутствуют, каждая задача заканчивается зелёным прогоном тестов.

**Спека:** `docs/superpowers/specs/2026-07-09-engineer-voice-split-design.md`

---

### Task 1: `TTSQueue` несёт персону

**Files:**
- Modify: `new_tts/queue_handler.py`
- Modify: `tests/test_queue_priority.py` (существующие однорукие speak_fn-лямбды
  сломаются от нового контракта — обновляются здесь же)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_queue_priority.py`:

```python
def test_enqueue_delivers_persona_to_speak_fn():
    seen = []
    q = TTSQueue(speak_fn=lambda t, p: seen.append((t, p)))
    q.enqueue("фраза", persona="calm")
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == [("фраза", "calm")]
    q.stop()


def test_enqueue_without_persona_delivers_none():
    seen = []
    q = TTSQueue(speak_fn=lambda t, p: seen.append((t, p)))
    q.enqueue("фраза")
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == [("фраза", None)]
    q.stop()


def test_critical_enqueue_carries_persona():
    seen = []
    q = TTSQueue(speak_fn=lambda t, p: seen.append((t, p)))
    q.enqueue("боксы", priority="critical", persona="calm")
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == [("боксы", "calm")]
    q.stop()
```

- [ ] **Step 2: Прогнать, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_queue_priority.py -k persona -q`
Expected: FAIL — `TypeError` (speak_fn зовётся с 1 аргументом / enqueue не
знает `persona`).

- [ ] **Step 3: Обновить `new_tts/queue_handler.py`**

Заменить `enqueue` и `_worker` (и тип очереди в `__init__`):

```python
        self._queue: "queue.PriorityQueue[tuple[int, int, str, str | None]]" = queue.PriorityQueue(maxsize=maxsize)
```

```python
    def enqueue(self, text: str, priority: str = "normal",
                persona: str | None = None) -> None:
        """Добавить фразу. priority: 'normal' | 'critical'.
        persona: озвучить конкретной персоной (None = текущая на момент
        проигрывания — поведение как раньше)."""
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
            item = (prio, self._seq, text, persona)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            pass
```

```python
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                prio, _seq, text, persona = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if prio == 0:
                self._critical_active.set()
            try:
                self._speak_fn(text, persona)
            except Exception:  # noqa: BLE001
                pass
            finally:
                if prio == 0:
                    self._critical_active.clear()
```

Обновить докстринг класса (строки 3-5) — добавить строку про persona.

- [ ] **Step 4: Обновить существующие speak_fn в тестах файла**

В `tests/test_queue_priority.py` все фейковые speak_fn становятся двурукими
(поведение прежнее, второй аргумент игнорируется):

- `test_critical_calls_stop_fn_immediately`: `lambda t: time.sleep(0.5)` →
  `lambda t, p: time.sleep(0.5)`
- `test_critical_clears_pending`: `def speak(t):` → `def speak(t, p):`
- `test_normal_enqueue_plays`: `lambda t: spoken.append(t)` →
  `lambda t, p: spoken.append(t)`
- `test_critical_active_true_only_while_critical_plays`: `def speak(t):` →
  `def speak(t, p):`
- `test_critical_active_false_for_normal_priority`: `lambda t: time.sleep(0.05)`
  → `lambda t, p: time.sleep(0.05)`
- `test_critical_active_clears_when_speak_fn_raises`: `def speak(t):` →
  `def speak(t, p):`

- [ ] **Step 5: Прогнать весь файл, зелёный**

Run: `py -3.12 -u -m pytest tests/test_queue_priority.py -q`
Expected: 9 passed (6 существующих + 3 новых)

---

### Task 2: `Voice` — per-utterance persona

**Files:**
- Modify: `voice/tts.py`
- Modify: `tests/test_tts_playback_stream.py` (новые тесты; хелпер `_make_voice`
  и фикстура `fake_sd` уже есть в файле — переиспользовать)

- [ ] **Step 1: Написать падающий тест на кэш-ключ по переданной персоне**

Добавить в конец `tests/test_tts_playback_stream.py`:

```python
# ---------------------------------------------------------------------------
# Per-utterance persona override (engineer voice split, spec 2026-07-09)
# ---------------------------------------------------------------------------

def test_play_blocking_uses_explicit_persona_for_cache_key(fake_sd, tmp_path):
    """_play_blocking(persona='calm') должен кэшировать под ключом calm,
    даже когда _current_persona = 'tv'."""
    v = _make_voice(cache_dir=tmp_path)
    v._current_persona = "tv"
    v._yandex = None                    # путь Piper: ключ piper:<persona>
    v._engine = types.SimpleNamespace(
        is_ready=True,
        sample_rate=22050,
        synthesize=lambda text, persona: (np.zeros(64, dtype=np.float32), 22050),
    )
    v._play_blocking("привет", persona="calm")
    assert os.path.exists(v._cache.path_for("привет", "piper:calm"))
    assert not os.path.exists(v._cache.path_for("привет", "piper:tv"))


def test_play_blocking_without_persona_uses_current(fake_sd, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._current_persona = "tv"
    v._yandex = None
    v._engine = types.SimpleNamespace(
        is_ready=True,
        sample_rate=22050,
        synthesize=lambda text, persona: (np.zeros(64, dtype=np.float32), 22050),
    )
    v._play_blocking("привет")
    assert os.path.exists(v._cache.path_for("привет", "piper:tv"))


def test_effective_volume_uses_explicit_persona(fake_sd):
    v = _make_voice()
    v._global_vol = 100
    v._persona_vol = {"calm": 40, "tv": 80}
    v._current_persona = "tv"
    assert v._effective_volume("calm") == 0.4
    assert v._effective_volume() == 0.8          # без аргумента — текущая
```

Примечание: `_make_voice` не выставляет `_engine.is_ready`/`synthesize` —
тест задаёт свой SimpleNamespace поверх, это уже принятый в файле стиль
(см. `_FakeYandexStreamOK` и `v._engine = types.SimpleNamespace(...)` в хелпере).
Если `_synthesize` требует ещё каких-то атрибутов движка — смотреть его код
(`voice/tts.py::_synthesize`, ветка Piper) и дополнять SimpleNamespace, не
менять продакшен-код под тест.

- [ ] **Step 2: Прогнать, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_tts_playback_stream.py -k persona -q`
Expected: FAIL — `TypeError: _play_blocking() got an unexpected keyword
argument 'persona'` (и аналогично для `_effective_volume`).

- [ ] **Step 3: Обновить `voice/tts.py`**

3a. `say` (строка ~264):
```python
    def say(self, text: str, priority: str = "normal",
            persona: str | None = None) -> bool:
        """Ставит фразу в очередь воспроизведения. Возвращает True сразу.
        persona: озвучить конкретной персоной (например, "calm" = голос
        инженера для команд), None = текущая персона."""
        if not text or not text.strip() or not self.is_available:
            return False
        if self._queue is not None:
            self._queue.enqueue(text.strip(), priority=priority, persona=persona)
            return True
        return False
```

3b. `_play_blocking` (строка ~325) — сигнатура и первая строка:
```python
    def _play_blocking(self, text: str, persona: str | None = None) -> None:
        persona = persona or self._current_persona
```
(строка `persona = self._current_persona` удаляется — заменена на строку выше;
остальное тело метода не меняется, КРОМЕ двух вызовов `_play_wav` — см. 3d.)

3c. `_effective_volume` (строка ~206):
```python
    def _effective_volume(self, persona: str | None = None) -> float:
        vol = self._persona_vol.get(persona or self._current_persona,
                                    self._global_vol)
        return vol / 100.0
```

3d. `_play_wav` (строка ~502) — сигнатура и вызов волюма (строка ~520):
```python
    def _play_wav(self, path: str, persona: str | None = None) -> None:
```
внутри: `mul = self._effective_volume()` → `mul = self._effective_volume(persona)`.
Оба вызова из `_play_blocking`: `self._play_wav(cache_path)` →
`self._play_wav(cache_path, persona)`; `self._play_wav(save_path)` →
`self._play_wav(save_path, persona)`.

3e. `_play_streaming` (строка ~396): `mul = self._effective_volume()` →
`mul = self._effective_volume(persona)` (персона уже есть в сигнатуре).

3f. `_say_pyttsx3_blocking` (строка ~549):
```python
    def _say_pyttsx3_blocking(self, text: str, persona: str | None = None) -> None:
```
(тело не меняется — у pyttsx3 один системный голос, аргумент игнорируется).

- [ ] **Step 4: Прогнать, зелёный**

Run: `py -3.12 -u -m pytest tests/test_tts_playback_stream.py tests/test_volume.py tests/test_queue_priority.py -q`
Expected: все зелёные (test_volume.py задевает `_effective_volume` — сигнатура
обратно совместима, но проверить обязательно).

---

### Task 3: Маршрутизация в engine + `PIT_CALL_NOTICE`

**Files:**
- Modify: `core/engine.py`
- Modify: `commentator/templates.py` (фразы `PIT_CALL_NOTICE` в `SIMPLE`)
- Modify: `commentator/planner.py` (`_REACTION_BY_CODE` — директива для LLM)
- Modify: `tests/test_engine_planner.py`, `tests/test_templates.py`

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_engine_planner.py` РАСШИРИТЬ существующий
`test_box_call_enqueues_critical_event_on_decisive_strategy`: после строки
`assert found[0]["priority"] == "critical"` добавить:

```python
    assert found[0]["speaker"] == "engineer"
    notices = [e for e in drained if e["event_code"] == "PIT_CALL_NOTICE"]
    assert len(notices) == 1                      # реплика комментатора рядом с tier 1
    assert "speaker" not in notices[0]            # БЕЗ speaker → голос комментатора
```

И добавить новый тест:

```python
def test_box_call_tier2_does_not_emit_notice(engine, monkeypatch):
    """PIT_CALL_NOTICE ставится только с tier 1 — на эскалации не спамим."""
    _drain(engine)
    engine._box_call_tracker.reset()
    engine._player_lap = 30
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0
    engine._last_strategy_ai_event_t = time.time()

    class _FakeDecision:
        action = "pit"

    class _FakeEvent:
        decision = _FakeDecision()
        confidence = 0.9

    monkeypatch.setattr(engine.strategy_analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()                      # tier 1 (+notice)
    _drain(engine)
    engine._player_lap = 31
    engine._last_snap_t = 0.0
    engine._last_strategy_ai_event_t = time.time()
    engine._maybe_snapshot()                      # tier 2

    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    codes = [e["event_code"] for e in drained]
    assert "STRAT_BOX_CALL_2" in codes
    assert "PIT_CALL_NOTICE" not in codes

    engine._box_call_tracker.reset()
    engine._player_lap = None
    engine._player_pit_status = None
    engine._last_snap_t = 0.0
    engine._last_strategy_ai_event_t = 0.0
```

В `tests/test_templates.py` добавить:

```python
def test_pit_call_notice_has_template_phrases():
    out = templates.render({"event_code": "PIT_CALL_NOTICE"}, "tv")
    assert out                                    # непустая фраза из SIMPLE
```

- [ ] **Step 2: Прогнать, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py tests/test_templates.py -k "box_call or notice" -q`
Expected: FAIL — `KeyError: 'speaker'` / notices пуст / render вернул пустую
строку для неизвестного кода.

- [ ] **Step 3: `core/engine.py` — speaker-метки + notice**

3a. Блок box-вызова в `_maybe_snapshot()` (сейчас заканчивается на
`"driver": "player", "color": "#EF4444",`):

```python
        if box_tier is not None:
            self._enqueue_event({
                "event_code": f"STRAT_BOX_CALL_{box_tier}",
                "priority": "critical",
                "driver": "player", "color": "#EF4444",
                "speaker": "engineer",
            })
            # Реплика комментатора В ТРЕТЬЕМ ЛИЦЕ рядом с командой инженера —
            # только на tier 1, на эскалации не спамим. Без "speaker" →
            # озвучит выбранная персона обычным LLM-пайплайном.
            if box_tier == 1:
                self._enqueue_event({
                    "event_code": "PIT_CALL_NOTICE", "priority": "normal",
                    "driver": "", "color": "#38BDF8",
                })
```

3b. Advisory-блок (`_st_code_map`, `_enqueue_event({...})` со
`strategy_ai_type`): добавить в тот же dict строку
```python
                    "speaker": "engineer",
```

3c. `_commentary_loop`, вызов озвучки
(`self.voice.say(phrase, priority=voice_priority)`):

```python
                self.voice.say(
                    phrase, priority=voice_priority,
                    persona="calm" if event.get("speaker") == "engineer" else None)
```

- [ ] **Step 4: `commentator/templates.py` — фразы**

В `SIMPLE`, после блока `"PIT_EXIT": [...]` (последний элемент словаря):

```python
    # Реплика комментатора рядом с box-вызовом инженера (speaker="engineer"
    # у самой команды; это событие — БЕЗ speaker, голос комментатора).
    "PIT_CALL_NOTICE": [
        "Гонщику дали команду — в этом круге едет на пит.",
        "Инженер зовёт в боксы. Смотрим, послушается ли.",
        "Команда с мостика: пит-стоп в этом круге.",
        "С пит-уолла прозвучало «бокс» — ждём заезда.",
    ],
```

- [ ] **Step 5: `commentator/planner.py` — директива LLM**

В `_REACTION_BY_CODE` (после `"PIT_EXIT": "выезд из боксов",`):

```python
    "PIT_CALL_NOTICE": "команда с пит-уолла: пит-стоп в этом круге",
```

(В `_BASE_IMPORTANCE` НЕ добавлять — дефолт 50 и есть утверждённая важность.)

- [ ] **Step 6: Прогнать, зелёный**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py tests/test_templates.py tests/test_planner.py -q`
Expected: все зелёные.

---

### Task 4: Полный прогон + CONTEXT.md

- [ ] **Step 1: Полный прогон**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed (было 1134 passed / 1 skipped + новые).

- [ ] **Step 2: CONTEXT.md**

Раздел «На чём остановились»: добавить сессию — голос инженера отделён от
комментатора (per-utterance persona через очередь, speaker="engineer" на
strategy-AI событиях, PIT_CALL_NOTICE с tier 1); спека+план; отметить
**не проверено вживую** (два голоса подряд нужно услышать в игре);
счётчик задач.

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_queue_priority.py tests/test_tts_playback_stream.py tests/test_volume.py tests/test_engine_planner.py tests/test_templates.py tests/test_planner.py -q`.
- Живая проверка (слышно ли два разных голоса: marina-инженер командует,
  выбранная персона комментирует следом) — у пользователя после сборки EXE.
