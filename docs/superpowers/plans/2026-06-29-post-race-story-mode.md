# Post-Race Story Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** На финише гонки автоматически генерировать голосовой итог-репортаж по реальным фактам гонки игрока и показывать его в Debrief.

**Architecture:** core собирает факты за всю гонку (`RaceStoryCollector`) → commentator превращает в прозу через LLM с офлайн-фолбэком (`StoryGenerator`) → engine оркестрирует на CHQF в фоновом потоке → web/UI показывают `state["race_story"]`.

**Tech Stack:** Python 3.12, YandexGPT (`AIProvider`), pytest; фронт — Next/React (`NewSpotterUI`), Bottle API.

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Поэтому шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `core/race_story.py` | создать | `RaceStoryCollector` — накопление фактов за гонку |
| `commentator/story.py` | создать | `StoryGenerator` — промпт + LLM-генерация + офлайн-фолбэк |
| `analytics/archive.py` | изменить | `attach_story(path, text)` — дописать историю в JSON сессии |
| `core/session_recorder.py` | изменить | `laps()` — публичный доступ к кругам |
| `core/engine.py` | изменить | сбор фактов, триггер на CHQF, фон. генерация, `race_story` в state, replay/generate_now |
| `web_server.py` | изменить | `POST /api/story/generate`, `POST /api/story/replay` |
| `NewSpotterUI/lib/api.ts` | изменить | тип `RaceStory`, поле `race_story?`, функции `generateStory`/`replayStory` |
| `NewSpotterUI/components/spotter/views/debrief.tsx` | изменить | панель «История гонки» |
| `tests/test_story_collector.py` | создать | тесты коллектора |
| `tests/test_story_generator.py` | создать | тесты генератора |
| `tests/test_engine_story.py` | создать | тесты оркестрации |

---

## Task 1: Archive — `attach_story`

**Files:**
- Modify: `analytics/archive.py`
- Test: `tests/test_archive_story.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_archive_story.py
from analytics import archive


def test_attach_story_adds_key(tmp_path, monkeypatch):
    p = tmp_path / "sess.json"
    archive._atomic_write(p, {"track_name": "Монца", "player_laps": []})
    archive.attach_story(p, "Отличная гонка.")
    data = archive._load(p)
    assert data["story"] == "Отличная гонка."
    assert data["track_name"] == "Монца"          # существующие поля целы


def test_attach_story_missing_file_is_safe(tmp_path):
    archive.attach_story(tmp_path / "nope.json", "x")   # без исключений
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_archive_story.py -q`
Expected: FAIL — `AttributeError: module 'analytics.archive' has no attribute 'attach_story'`

- [ ] **Step 3: Implement**

Добавить в конец `analytics/archive.py`:

```python
# --- Story (post-race recap) ---

def attach_story(path: str | Path, text: str) -> None:
    """Дописать пост-гоночную историю в существующий JSON сессии (read-modify-write).
    Безопасно при отсутствии файла — просто ничего не делает."""
    p = Path(path)
    data = _load(p)
    if data is None:
        return
    data["story"] = text
    _atomic_write(p, data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_archive_story.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 2: SessionRecorder — публичный доступ к кругам

**Files:**
- Modify: `core/session_recorder.py`
- Test: `tests/test_session_recorder_laps.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_recorder_laps.py
from core.session_recorder import SessionRecorder


def test_laps_accessor_returns_copy():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000)
    laps = r.laps()
    assert laps == [{"lap": 1, "last_lap_ms": 95000,
                     "s1_ms": 30000, "s2_ms": 33000, "s3_ms": 32000}]
    laps.append({"x": 1})            # мутация копии не трогает внутренний список
    assert len(r.laps()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_session_recorder_laps.py -q`
Expected: FAIL — `AttributeError: 'SessionRecorder' object has no attribute 'laps'`

- [ ] **Step 3: Implement**

Добавить метод в класс `SessionRecorder` (после `on_lap_complete`):

```python
    def laps(self) -> list[dict]:
        """Копия списка завершённых кругов (для генератора истории)."""
        return list(self._laps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_session_recorder_laps.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `RaceStoryCollector`

**Files:**
- Create: `core/race_story.py`
- Test: `tests/test_story_collector.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_story_collector.py
from core.race_story import RaceStoryCollector


def test_start_position_set_once():
    c = RaceStoryCollector()
    c.note_start_position(6)
    c.note_start_position(4)                      # игнор — старт уже зафиксирован
    f = c.facts(final_position=4, laps=[])
    assert f["start_position"] == 6
    assert f["positions_gained"] == 2            # 6 - 4


def test_only_notable_events_kept():
    c = RaceStoryCollector()
    c.note_event("DRSE", 5)                       # не значимое — игнор
    c.note_event("OVTK", 12, driver="player", target="Албон")
    f = c.facts(final_position=3, laps=[])
    assert len(f["overtakes"]) == 1
    assert f["overtakes"][0]["target"] == "Албон"


def test_best_lap_picks_min_positive():
    c = RaceStoryCollector()
    laps = [{"lap": 1, "last_lap_ms": 95000},
            {"lap": 2, "last_lap_ms": 93200},
            {"lap": 3, "last_lap_ms": 0}]        # 0 игнор
    f = c.facts(final_position=1, laps=laps)
    assert f["best_lap_ms"] == 93200
    assert f["best_lap_number"] == 2


def test_incidents_collected():
    c = RaceStoryCollector()
    c.note_event("PENA", 22, driver="player")
    f = c.facts(final_position=5, laps=[])
    assert f["incidents"][0]["code"] == "PENA"
    assert f["incidents"][0]["lap"] == 22


def test_coach_state_merged():
    c = RaceStoryCollector()
    f = c.facts(final_position=4, laps=[],
                coach_state={"weak_sector": 2, "consistency_score": 0.9})
    assert f["weak_sector"] == 2
    assert f["consistency"] == 0.9


def test_event_cap():
    c = RaceStoryCollector()
    for i in range(20):
        c.note_event("OVTK", i, target=f"D{i}")
    f = c.facts(final_position=1, laps=[])
    assert len(f["overtakes"]) <= 12


def test_reset_clears():
    c = RaceStoryCollector()
    c.note_start_position(6)
    c.note_event("OVTK", 1, target="X")
    c.reset()
    f = c.facts(final_position=2, laps=[])
    assert f["start_position"] is None
    assert f["overtakes"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_story_collector.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.race_story'`

- [ ] **Step 3: Implement**

```python
# core/race_story.py
"""
core/race_story.py
==================
Накопитель фактов гонки для пост-гоночной истории (Post-Race Story Mode).

RaceTimeline — скользящее окно (windowed), для полного рассказа не годится.
Здесь копим за ВСЮ гонку только то, из чего строится нарратив: старт-позиция,
ключевые события игрока (обгоны/штрафы/сходы/быстрейший круг). На финише facts()
сводит всё в плоский факт-блок для commentator/story.py.

Чистый модуль: без I/O, сети и LLM. Вовлечённость игрока определяет вызывающий
(engine): сюда передаются уже отфильтрованные, разрешённые имена.
"""
from __future__ import annotations

# События, попадающие в историю (передаются engine'ом уже как игрок-релевантные).
_NOTABLE = {"OVTK", "PENA", "RTMT", "FTLP"}
_MAX_EVENTS = 12


class RaceStoryCollector:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Очистить (вызывать на SSTA)."""
        self._start_position: int | None = None
        self._events: list[dict] = []

    def note_start_position(self, position: int | None) -> None:
        """Зафиксировать стартовую позицию (только первая известная)."""
        if self._start_position is None and position:
            self._start_position = position

    def note_event(self, code: str, lap: int | None,
                   driver: str | None = None, target: str | None = None) -> None:
        """Запомнить значимое игрок-событие. Незначимые коды игнорируются."""
        if code not in _NOTABLE:
            return
        if len(self._events) >= _MAX_EVENTS:
            self._events.pop(len(self._events) // 2)   # выкидываем из середины
        self._events.append({"code": code, "lap": lap,
                             "driver": driver, "target": target})

    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None) -> dict:
        """Свести накопленное + финальные данные в плоский факт-блок для LLM."""
        best_ms: int | None = None
        best_lap: int | None = None
        for lp in laps:
            ms = lp.get("last_lap_ms") or 0
            if ms > 0 and (best_ms is None or ms < best_ms):
                best_ms, best_lap = ms, lp.get("lap")

        overtakes = [{"lap": e["lap"], "target": e["target"]}
                     for e in self._events if e["code"] == "OVTK" and e.get("target")]
        incidents = [{"lap": e["lap"], "code": e["code"], "driver": e.get("driver")}
                     for e in self._events if e["code"] in ("PENA", "RTMT")]
        gained = (self._start_position - final_position
                  if self._start_position and final_position else None)
        coach = coach_state or {}
        return {
            "track": track,
            "start_position": self._start_position,
            "final_position": final_position,
            "positions_gained": gained,
            "total_laps": total_laps,
            "best_lap_ms": best_ms,
            "best_lap_number": best_lap,
            "overtakes": overtakes,
            "incidents": incidents,
            "fastest_lap_flag": any(e["code"] == "FTLP" for e in self._events),
            "weak_sector": coach.get("weak_sector"),
            "consistency": coach.get("consistency_score"),
            "leader": leader_name,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_story_collector.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 4: `StoryGenerator`

**Files:**
- Create: `commentator/story.py`
- Test: `tests/test_story_generator.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_story_generator.py
from commentator import story

_FACTS = {
    "track": "Монца", "start_position": 6, "final_position": 4,
    "positions_gained": 2, "total_laps": 53,
    "best_lap_ms": 84300, "best_lap_number": 28,
    "overtakes": [{"lap": 12, "target": "Албон"}],
    "incidents": [{"lap": 22, "code": "PENA", "driver": "player"}],
    "fastest_lap_flag": False, "weak_sector": 2,
    "consistency": 0.88, "leader": "Ферстаппен",
}


def test_build_prompt_contains_facts_and_glossary():
    p = story.build_prompt(_FACTS, "tv")
    assert "Албон" in p
    assert "Албоном" in p              # шпаргалка склонений (творительный)
    assert "ТОЛЬКО" in p               # инструкция анти-галлюцинации
    assert "4" in p                    # финишная позиция в фактах


class _FakeAI:
    available = True
    def generate(self, context, persona):
        return "Старт шестым, финиш четвёртым — крепкая гонка."


def test_generate_uses_llm_text():
    assert story.generate(_FACTS, _FakeAI(), "tv") == \
        "Старт шестым, финиш четвёртым — крепкая гонка."


class _DownAI:
    available = False
    def generate(self, context, persona):
        return None


def test_generate_falls_back_when_unavailable():
    out = story.generate(_FACTS, _DownAI(), "tv")
    assert isinstance(out, str) and len(out) > 0
    assert "4" in out                  # фолбэк упоминает финишную позицию


def test_fallback_offline_deterministic():
    a = story.render_fallback(_FACTS, "tv")
    b = story.render_fallback(_FACTS, "tv")
    assert a == b and len(a) > 0


def test_generate_handles_empty_facts():
    out = story.generate({}, _DownAI(), "tv")
    assert isinstance(out, str)        # не падает на пустых фактах
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_story_generator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'commentator.story'`

- [ ] **Step 3: Implement**

```python
# commentator/story.py
"""
commentator/story.py
====================
Post-Race Story Mode: превращает факт-блок гонки (core/race_story.py) в короткий
итог-репортаж (3–5 предложений) голосом текущей персоны.

LLM-путь через AIProvider; при недоступном LLM — детерминированный офлайн-фолбэк
из тех же фактов (приложение всегда что-то выдаёт). Имена склоняются через
core/ru_names.py: в промпт кладём шпаргалку, чтобы модель не коверкала фамилии.
"""
from __future__ import annotations

from core.broadcast.styles import get_style
from core.ru_names import glossary


def _fmt_lap(ms: int | None) -> str:
    if not ms or ms <= 0:
        return ""
    total = ms / 1000.0
    m = int(total // 60)
    s = total - m * 60
    return f"{m}:{s:06.3f}" if m else f"{s:.1f}с"


def _names_in_facts(facts: dict) -> list[str]:
    names: list[str] = []
    for o in facts.get("overtakes", []):
        if o.get("target"):
            names.append(o["target"])
    for i in facts.get("incidents", []):
        if i.get("driver"):
            names.append(i["driver"])
    if facts.get("leader"):
        names.append(facts["leader"])
    return names


def _format_facts(facts: dict) -> str:
    L: list[str] = []
    sp, fp = facts.get("start_position"), facts.get("final_position")
    if sp:
        L.append(f"- Старт: позиция {sp}")
    if fp:
        L.append(f"- Финиш: позиция {fp}")
    g = facts.get("positions_gained")
    if g:
        L.append(f"- {'Отыграно' if g > 0 else 'Потеряно'} позиций: {abs(g)}")
    if facts.get("total_laps"):
        L.append(f"- Всего кругов: {facts['total_laps']}")
    lap = _fmt_lap(facts.get("best_lap_ms"))
    if lap:
        bl = facts.get("best_lap_number")
        L.append(f"- Лучший круг: {lap}" + (f" (круг {bl})" if bl else ""))
    for o in facts.get("overtakes", []):
        L.append(f"- Обгон: прошёл {o['target']}"
                 + (f" на круге {o['lap']}" if o.get("lap") else ""))
    for i in facts.get("incidents", []):
        label = "штраф" if i["code"] == "PENA" else "сход"
        L.append(f"- {label.capitalize()}"
                 + (f" на круге {i['lap']}" if i.get("lap") else ""))
    if facts.get("fastest_lap_flag"):
        L.append("- Был быстрейший круг гонки")
    if facts.get("weak_sector"):
        L.append(f"- Слабый сектор: S{facts['weak_sector']}")
    c = facts.get("consistency")
    if c is not None:
        L.append(f"- Консистентность: {int(c * 100)}%")
    return "\n".join(L) if L else "- мало данных"


def build_prompt(facts: dict, persona: str, gp_context: str | None = None) -> str:
    """Структурный fact-only промпт для итог-репортажа."""
    parts = [
        get_style(persona),
        "\nТы подводишь ИТОГ уже ЗАВЕРШЁННОЙ гонки игрока — как спортивный "
        "журналист. Ретроспектива, прошедшее время.",
        "\nФАКТЫ ГОНКИ (опирайся ТОЛЬКО на них, ничего не выдумывай):\n"
        + _format_facts(facts),
    ]
    if gp_context:
        parts.append("\nСверка с реальным Гран-при:\n" + gp_context)
    gloss = glossary(_names_in_facts(facts))
    if gloss:
        parts.append("\nСКЛОНЕНИЕ ИМЁН (бери фамилии ТОЛЬКО в этих формах):\n" + gloss)
    parts.append(
        "\nНАПИШИ итог: 3–5 предложений, ОДИН абзац, русский, без markdown, "
        "кавычек и эмодзи. Числа — словами. Если фактов мало — короткий честный итог."
    )
    return "\n".join(parts)


def render_fallback(facts: dict, persona: str = "tv") -> str:
    """Детерминированный офлайн-итог из фактов (без LLM)."""
    parts: list[str] = []
    sp, fp = facts.get("start_position"), facts.get("final_position")
    if fp and sp:
        parts.append(f"Финиш на позиции {fp} со старта {sp}.")
    elif fp:
        parts.append(f"Финиш на позиции {fp}.")
    lap = _fmt_lap(facts.get("best_lap_ms"))
    if lap:
        bl = facts.get("best_lap_number")
        parts.append(f"Лучший круг — {lap}" + (f" на {bl}-м." if bl else "."))
    n = len(facts.get("overtakes", []))
    if n:
        parts.append(f"Обгонов за гонку: {n}.")
    if facts.get("weak_sector"):
        parts.append(f"Слабый сектор — S{facts['weak_sector']}.")
    return " ".join(parts) or "Гонка завершена."


def generate(facts: dict, ai, persona: str, gp_context: str | None = None) -> str:
    """Сгенерировать историю: LLM, при недоступности — офлайн-фолбэк."""
    if ai is not None and getattr(ai, "available", False):
        text = ai.generate(build_prompt(facts, persona, gp_context), persona)
        if text and text.strip():
            return text.strip()
    return render_fallback(facts, persona)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_story_generator.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 5: Engine — оркестрация

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_story.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_story.py
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None              # без Yandex/сети → фолбэк-история
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_generate_story_sets_state(engine):
    engine.settings["autovoice_enabled"] = False    # без TTS-побочек в тесте
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine.story_collector.note_event("OVTK", 10, driver="player", target="Албон")
    engine._player_pos = 4
    engine._generate_story(None)                     # синхронно (без потока)
    rs = engine.get_state().get("race_story")
    assert rs is not None and rs["text"]
    assert rs["final_position"] == 4


def test_generate_story_now_requires_data(engine):
    engine.recorder.reset()
    engine.story_collector.reset()
    assert engine.generate_story_now() is False      # нет кругов/старта → нечего рассказывать


def test_replay_returns_false_without_story(engine):
    with engine.state_lock:
        engine.state["race_story"] = None
    assert engine.replay_story() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_story.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute 'story_collector'`

- [ ] **Step 3a: Imports** — в `core/engine.py` рядом с другими core-импортами добавить:

```python
from core.race_story import RaceStoryCollector
from commentator import story as _story
from analytics import archive as _archive
```

- [ ] **Step 3b: `__init__`** — после строки `self._situation_dedup = SituationDedup(config.SITUATION_DEDUP_COOLDOWN)` (или рядом с race-analyzer блоком) добавить:

```python
        # Post-Race Story Mode
        self.story_collector = RaceStoryCollector()
        self._story_fired = False
```

И в словарь `self.state = {...}` добавить ключ (рядом с `"broadcast_mode_enabled": False,`):

```python
            "race_story": None,
```

- [ ] **Step 3c: старт-позиция** — в `_update_telemetry`, в ветке `PACKET_LAP_DATA`, сразу после строк:

```python
                if pl.get("position"):
                    telem["position"] = pl["position"]
                    self._player_pos = pl["position"]
```

добавить:

```python
                    self.story_collector.note_start_position(pl["position"])
```

- [ ] **Step 3d: SSTA-сброс** — в `_telemetry_loop`, в блоке `if code == "SSTA":` (рядом с `self.recorder.reset()`) добавить:

```python
                self.story_collector.reset()
                self._story_fired = False
                with self.state_lock:
                    self.state["race_story"] = None
```

- [ ] **Step 3e: кормление событий** — в `_telemetry_loop`, после `self.race_state.record_event(event)` добавить вызов:

```python
            self._note_story_event(event, enriched)
```

- [ ] **Step 3f: финиш-триггер** — в `_telemetry_loop`, в ветке `elif code in ("CHQF", "SEND"):`, заменить строку
`self.recorder.finalize(` вызов так, чтобы захватить путь и запустить историю. Найди существующий блок:

```python
                self.recorder.finalize(
                    track_id=self._track_id, track_name=track_name,
                    session_type="R", final_position=pos,
                    events=list(self._session_events),
                    game_year=self._game_year,
                )
```

и замени на:

```python
                saved_path = self.recorder.finalize(
                    track_id=self._track_id, track_name=track_name,
                    session_type="R", final_position=pos,
                    events=list(self._session_events),
                    game_year=self._game_year,
                )
                if (code == "CHQF" and self._session_type == "race"
                        and not self._story_fired):
                    self._story_fired = True
                    threading.Thread(
                        target=self._generate_story, args=(saved_path,),
                        daemon=True, name="race-story").start()
```

- [ ] **Step 3g: методы** — добавить в класс `F1Engine` (рядом с `_handle_flashback`/`_neighbor_names`):

```python
    def _note_story_event(self, event: dict, enriched: dict) -> None:
        """Передать игрок-релевантное событие коллектору истории."""
        code = event.get("event_code")
        if code not in ("OVTK", "PENA", "RTMT", "FTLP"):
            return
        lap = self._player_lap
        pidx = self._player_car_index
        if code == "OVTK":
            if event.get("overtaking_idx") == pidx:
                target = self.race_state.driver(
                    event.get("being_overtaken_idx"))["name"]
                self.story_collector.note_event("OVTK", lap, driver="player",
                                                target=target)
            return
        if event.get("vehicle_idx") == pidx:
            self.story_collector.note_event(code, lap,
                                            driver=enriched.get("driver"))

    def _generate_story(self, saved_path=None) -> None:
        """Собрать факты, сгенерировать историю, озвучить и показать. Фоновый поток."""
        try:
            with self.state_lock:
                grid = self.state.get("race", {}).get("grid") or []
                coach = dict(self.state.get("coach_ai", {}))
            final_pos = next(
                (e.get("position") for e in grid
                 if e.get("vehicle_idx") == self._player_car_index),
                self._player_pos)
            track = TRACK_ID_TO_GP.get(self._track_id, ("Unknown",))[0]
            facts = self.story_collector.facts(
                final_position=final_pos, laps=self.recorder.laps(),
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track)
            text = _story.generate(facts, self.ai, self.commentator.persona,
                                   self.commentator.analytics_context)
            if not text:
                return
            import time as _t
            with self.state_lock:
                self.state["race_story"] = {
                    "text": text, "track": track,
                    "final_position": final_pos, "ts": _t.time()}
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": "STORY", "phrase": text,
                    "color": "#A78BFA", "driver": "",
                    "muted": not self._should_voice({"event_code": "STORY",
                                                     "priority": "normal"}),
                    "channel": "commentary"})
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
            if self._should_voice({"event_code": "STORY", "priority": "normal"}):
                self.voice.say(text, priority="normal")
            if saved_path is not None:
                try:
                    _archive.attach_story(saved_path, text)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            _log.warning("race story generation failed: %s", exc)

    def generate_story_now(self) -> bool:
        """Ручной триггер истории (API). False если данных нет."""
        if not self.recorder.laps() and self.story_collector._start_position is None:
            return False
        threading.Thread(target=self._generate_story, daemon=True,
                         name="race-story-manual").start()
        return True

    def replay_story(self) -> bool:
        """Переозвучить текущую историю. False если её нет."""
        with self.state_lock:
            rs = self.state.get("race_story")
        if not rs or not rs.get("text"):
            return False
        self.voice.say(rs["text"], priority="normal")
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_story.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 6: Web API — маршруты story

**Files:**
- Modify: `web_server.py`

- [ ] **Step 1: Implement** — добавить рядом с `api_highlight` (использует тот же `engine` и `_json`):

```python
    @app.route("/api/story/generate", method="POST")
    def api_story_generate():
        return _json({"ok": engine.generate_story_now()})

    @app.route("/api/story/replay", method="POST")
    def api_story_replay():
        return _json({"ok": engine.replay_story()})
```

- [ ] **Step 2: Smoke-check импорта**

Run: `py -3.12 -c "import web_server; print('ok')"`
Expected: `ok` (без ошибок импорта/синтаксиса)

- [ ] **Step 3: Checkpoint** — импорт сервера успешен.

---

## Task 7: UI — типы и клиент API

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`

- [ ] **Step 1: Implement** — добавить тип после `export type SessionItem` (около стр. 223):

```typescript
export type RaceStory = {
  text: string
  track: string | null
  final_position: number | null
  ts: number
}
```

Добавить поле в `SpotterState` (рядом с `yandex_ok?: boolean`):

```typescript
  race_story?: RaceStory | null
```

Добавить функции после `export const highlight = ...`:

```typescript
export const generateStory = () =>
  fetch("/api/story/generate", { method: "POST" }).then((r) => asJson<{ ok: boolean }>(r))

export const replayStory = () =>
  fetch("/api/story/replay", { method: "POST" }).then((r) => asJson<{ ok: boolean }>(r))
```

- [ ] **Step 2: Type-check**

Run: `cd NewSpotterUI; npx tsc --noEmit`
Expected: без ошибок (или те же предсуществующие, что и до правки)

- [ ] **Step 3: Checkpoint** — типы компилируются.

---

## Task 8: UI — панель «История гонки» в Debrief

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/debrief.tsx`

- [ ] **Step 1: Implement** — обновить импорты в начале файла:

```typescript
import { Panel, Readout, SectionLabel } from "../ui"
import type { SpotterState } from "@/lib/api"
import { generateStory, replayStory } from "@/lib/api"
import { feedToEvent } from "@/lib/feed"
import { Trophy, TrendingUp, Target, Users, Radio, BookOpen } from "lucide-react"
```

Внутри `DebriefView`, перед `return (`, добавить чтение истории:

```typescript
  const story = state?.race_story ?? null
```

Добавить панель сразу после открывающего `<div className="flex flex-col gap-5">` блока с заголовком (перед `<div className="grid grid-cols-1 gap-5 lg:grid-cols-2">`):

```tsx
      {/* Race Story */}
      <Panel label="История гонки" action={
        <div className="flex items-center gap-1.5">
          <BookOpen className="h-3 w-3 text-muted-foreground" />
          <span className="label-mono text-[10px] text-muted-foreground">
            {story ? "ИТОГ ГОТОВ" : "НЕТ ИТОГА"}
          </span>
        </div>
      }>
        {story ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm leading-relaxed text-foreground/90">{story.text}</p>
            <button
              onClick={() => { void replayStory() }}
              className="self-start rounded-md bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90 hover:bg-secondary"
            >
              Переозвучить
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-start gap-2">
            <p className="text-xs text-muted-foreground">
              Итог появится автоматически после финиша гонки.
            </p>
            <button
              onClick={() => { void generateStory() }}
              className="rounded-md bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90 hover:bg-secondary"
            >
              Сгенерировать итог
            </button>
          </div>
        )}
      </Panel>
```

- [ ] **Step 2: Type-check**

Run: `cd NewSpotterUI; npx tsc --noEmit`
Expected: без новых ошибок

- [ ] **Step 3: Checkpoint** — компонент компилируется.

---

## Task 9: Полная верификация

- [ ] **Step 1: Полный прогон Python-тестов**

Run: `py -3.12 -m pytest --ignore=tests/test_gpt.py -q`
Expected: все прошлые + новые тесты зелёные (ожидаемо ~592 + новые), 1 pre-existing skip/warning.

- [ ] **Step 2: Импорт-смоук ключевых модулей**

Run: `py -3.12 -c "import core.engine, commentator.story, core.race_story, web_server; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Обновить CONTEXT.md** — дописать раздел «На чём остановились» (новая фича Post-Race Story Mode: файлы, поведение, тест-бейслайн) и сбросить счётчик согласно правилу проекта.

- [ ] **Step 4: Checkpoint** — фича готова, тесты зелёные, документация обновлена.

---

## Self-Review (выполнено при написании плана)

- **Покрытие спеки:** RaceStoryCollector (T3), StoryGenerator+фолбэк (T4), engine-триггер на CHQF/не-гонка/анти-дабл-файр (T5), API (T6), UI панель+replay+manual (T7–T8), архив (T1), офлайн-фолбэк (T4), граничные случаи (T4 пустые факты, T5 нет данных). ✓
- **Типы/сигнатуры согласованы:** `facts(final_position, laps, coach_state, leader_name, total_laps, track)` одинаково в T3/T5; `generate(facts, ai, persona, gp_context)` в T4/T5; `attach_story(path, text)` в T1/T5; `race_story` форма в T5/T7/T8. ✓
- **Без плейсхолдеров:** весь код приведён дословно. ✓
- **No-git:** «Commit» заменён на «Checkpoint» (прогон тестов). ✓
