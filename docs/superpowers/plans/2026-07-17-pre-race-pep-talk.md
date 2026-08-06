# Пре-гоночная реплика инженера («пеп-ток») Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** На экране подготовки к гонке (выбор стратегии, до старта) инженер один раз озвучивает итог последней гонки карьеры (любая трасса) — тон зависит от того, был подиум, очки или провал — и молчит на первой гонке карьеры, когда сравнивать не с чем.

**Architecture:** Новая чистая функция `analytics/archive.py::get_last_race()` находит последнюю по времени гонку в архиве. Новый модуль `core/pre_race_pep_talk.py` превращает её в тир (`podium`/`points`/`struggled`). Новый модуль `commentator/pre_race_pep_talk.py` строит LLM-промпт и офлайн-фолбэк (зеркало `commentator/story.py`, но вперёд-смотрящее). `core/engine.py` цепляет фон-поток к переходу `session_type -> "race"` (до `SSTA`), с 4-секундной задержкой, гвард-флагом (сбрасывается при выходе из `"race"`, не на `SSTA`) и гейтингом на `engineer_chatter_enabled`. Голос — `voice.say(text, persona="calm")` напрямую, в обход очереди событий (LLM-генерация асинхронна), тот же паттерн, что `_generate_story`.

**Tech Stack:** Python 3.12, pytest, существующие `analytics/archive.py`/`commentator/ai_provider.py`/`core/engine.py` — новых зависимостей не требуется.

**Спека:** `docs/superpowers/specs/2026-07-17-pre-race-pep-talk-design.md`

**Проект не под git** — шагов `git commit` в этом плане нет; каждая задача заканчивается проверочным чекпоинтом (запуск тестов) вместо коммита.

---

### Task 1: `analytics/archive.py::get_last_race()`

**Files:**
- Modify: `analytics/archive.py` (добавить функцию после `list_game_sessions()`, строка 91)
- Test: `tests/test_archive_sessions.py` (добавить в конец файла)

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_archive_sessions.py`:

```python
def test_get_last_race_returns_none_when_archive_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    assert archive.get_last_race() is None


def test_get_last_race_ignores_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "practice", "final_position": 1})
    assert archive.get_last_race() is None


def test_get_last_race_returns_most_recent_by_time_not_track(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "race", "final_position": 2})
    archive._atomic_write(tmp_path / "2026-01-03_10-00-00_000001.json",
                          {"track_name": "Baku", "session_type": "race", "final_position": 9})
    archive._atomic_write(tmp_path / "2026-01-02_10-00-00_000001.json",
                          {"track_name": "Spa", "session_type": "race", "final_position": 1})
    last = archive.get_last_race()
    assert last["track_name"] == "Baku"      # самая свежая по timestamp в имени файла
    assert last["final_position"] == 9


def test_get_last_race_skips_newer_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "race", "final_position": 3})
    archive._atomic_write(tmp_path / "2026-01-02_10-00-00_000001.json",
                          {"track_name": "Baku", "session_type": "qualifying", "final_position": 1})
    last = archive.get_last_race()
    assert last["track_name"] == "Monza"     # квалификация новее, но не гонка — пропускается


def test_get_last_race_allows_missing_final_position(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "race", "final_position": None})
    last = archive.get_last_race()
    assert last is not None and last["final_position"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_archive_sessions.py -v`
Expected: FAIL — `AttributeError: module 'analytics.archive' has no attribute 'get_last_race'` (5 new tests fail, existing tests in the file still pass).

- [ ] **Step 3: Implement `get_last_race()`**

В `analytics/archive.py`, сразу после `list_game_sessions()` (после строки 91, перед `# --- F1 reference data ---`):

```python
def get_last_race() -> dict | None:
    """Самая свежая сессия с session_type == "race", независимо от трассы.
    None, если в архиве ещё нет ни одной завершённой гонки (первая гонка
    карьеры) — list_game_sessions() уже отсортирован новыми-first, поэтому
    это первое совпадение, без доп. сортировки."""
    for s in list_game_sessions():
        if s.get("session_type") == "race":
            return s
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_archive_sessions.py -v`
Expected: PASS (8 passed — 3 existing + 5 new).

- [ ] **Step 5: Checkpoint**

Confirm all 8 tests pass. No git commit needed (project has no git repo). Move to Task 2.

---

### Task 2: `core/pre_race_pep_talk.py` — тир по фактам

**Files:**
- Create: `core/pre_race_pep_talk.py`
- Test: `tests/test_pre_race_pep_talk.py`

- [ ] **Step 1: Write the failing tests**

Создать `tests/test_pre_race_pep_talk.py`:

```python
from core.pre_race_pep_talk import facts, PODIUM, POINTS, STRUGGLED


def test_facts_none_when_no_last_race():
    assert facts(None) is None


def test_facts_podium_tier_for_positions_1_to_3():
    for pos in (1, 2, 3):
        result = facts({"final_position": pos, "track_name": "Monza"})
        assert result["tier"] == PODIUM
        assert result["position"] == pos
        assert result["track"] == "Monza"


def test_facts_points_tier_for_positions_4_to_10():
    for pos in (4, 7, 10):
        assert facts({"final_position": pos})["tier"] == POINTS


def test_facts_struggled_tier_for_position_11_plus():
    for pos in (11, 15, 20):
        assert facts({"final_position": pos})["tier"] == STRUGGLED


def test_facts_struggled_tier_when_no_final_position():
    result = facts({"final_position": None, "track_name": "Baku"})
    assert result["tier"] == STRUGGLED
    assert result["position"] is None


def test_facts_track_defaults_to_none_when_missing():
    result = facts({"final_position": 1})
    assert result["track"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_pre_race_pep_talk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.pre_race_pep_talk'`.

- [ ] **Step 3: Implement `core/pre_race_pep_talk.py`**

```python
"""
core/pre_race_pep_talk.py
==========================
Классификация финишной позиции ПОСЛЕДНЕЙ гонки карьеры (независимо от трассы)
в тир для пред-гоночной реплики инженера. Чистый модуль: без I/O и LLM —
данные приходят уже готовыми из analytics/archive.py::get_last_race().

Не путать с core/career_memory.py (трек-специфичная память) и
core/career_stats.py (агрегат за всю карьеру) — здесь нужна ИМЕННО последняя
гонка, любая трасса, только финишная позиция.
"""
from __future__ import annotations

PODIUM, POINTS, STRUGGLED = "podium", "points", "struggled"


def facts(last_race: dict | None) -> dict | None:
    """None, если гонок в карьере ещё не было (первая гонка) — реплика не
    звучит вообще. Иначе {"tier", "position", "track"}."""
    if last_race is None:
        return None
    pos = last_race.get("final_position")
    if pos is None or pos > 10:
        tier = STRUGGLED
    elif pos <= 3:
        tier = PODIUM
    else:
        tier = POINTS
    return {"tier": tier, "position": pos, "track": last_race.get("track_name")}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_pre_race_pep_talk.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Checkpoint**

Confirm all 6 tests pass. No git commit needed (project has no git repo). Move to Task 3.

---

### Task 3: `commentator/pre_race_pep_talk.py` — промпт + офлайн-фолбэк

**Files:**
- Create: `commentator/pre_race_pep_talk.py`
- Test: `tests/test_pre_race_pep_talk_generator.py`

- [ ] **Step 1: Write the failing tests**

Создать `tests/test_pre_race_pep_talk_generator.py`:

```python
from commentator import pre_race_pep_talk as pep

_PODIUM_FACTS = {"tier": "podium", "position": 2, "track": "Монца"}
_POINTS_FACTS = {"tier": "points", "position": 7, "track": "Спа"}
_STRUGGLED_FACTS = {"tier": "struggled", "position": None, "track": "Баку"}


def test_build_prompt_contains_position_and_track():
    p = pep.build_prompt(_PODIUM_FACTS, "tv")
    assert "2" in p
    assert "Монца" in p
    assert "подиум" in p


def test_build_prompt_handles_missing_position():
    p = pep.build_prompt(_STRUGGLED_FACTS, "tv")
    assert "не финишировал" in p


def test_render_fallback_covers_all_three_tiers():
    podium = pep.render_fallback(_PODIUM_FACTS)
    points = pep.render_fallback(_POINTS_FACTS)
    struggled = pep.render_fallback(_STRUGGLED_FACTS)
    assert isinstance(podium, str) and len(podium) > 0
    assert isinstance(points, str) and len(points) > 0
    assert isinstance(struggled, str) and len(struggled) > 0
    assert podium != points != struggled


def test_render_fallback_deterministic():
    a = pep.render_fallback(_PODIUM_FACTS)
    b = pep.render_fallback(_PODIUM_FACTS)
    assert a == b


class _FakeAI:
    available = True

    def generate(self, context, persona):
        return "Прошлый раз — подиум, сегодня повторим."


def test_generate_uses_llm_text():
    assert pep.generate(_PODIUM_FACTS, _FakeAI(), "tv") == \
        "Прошлый раз — подиум, сегодня повторим."


class _DownAI:
    available = False

    def generate(self, context, persona):
        return None


def test_generate_falls_back_when_ai_unavailable():
    out = pep.generate(_PODIUM_FACTS, _DownAI(), "tv")
    assert out == pep.render_fallback(_PODIUM_FACTS)


def test_generate_falls_back_when_llm_returns_empty():
    class _EmptyAI:
        available = True

        def generate(self, context, persona):
            return "   "
    out = pep.generate(_POINTS_FACTS, _EmptyAI(), "tv")
    assert out == pep.render_fallback(_POINTS_FACTS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_pre_race_pep_talk_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'commentator.pre_race_pep_talk'`.

- [ ] **Step 3: Implement `commentator/pre_race_pep_talk.py`**

```python
"""
commentator/pre_race_pep_talk.py
==================================
Пред-гоночная реплика инженера: превращает тир последней гонки карьеры
(core/pre_race_pep_talk.py) в короткую фразу (1 предложение) голосом
инженера ("calm"). LLM-путь через AIProvider; фолбэк — захардкоженная
фраза на тир (приложение всегда что-то выдаёт).
"""
from __future__ import annotations

from core.broadcast.styles import get_style

_TIER_LABEL = {
    "podium": "подиум",
    "points": "очковая зона",
    "struggled": "провальная, за пределами очков или сход",
}

_FALLBACK = {
    "podium": "Прошлая гонка — подиум, отличный темп. Повторим результат.",
    "points": "В прошлой гонке набрал очки. Сегодня попробуем прибавить.",
    "struggled": "Прошлая гонка не задалась. Сегодня — реванш.",
}


def build_prompt(facts: dict, persona: str) -> str:
    tier_label = _TIER_LABEL[facts["tier"]]
    position = facts["position"] if facts["position"] is not None else "не финишировал"
    track = facts.get("track") or "неизвестна"
    return "\n".join([
        get_style(persona),
        "\nТы — гоночный ИНЖЕНЕР игрока, говоришь ПЕРЕД стартом новой гонки "
        "(экран выбора стратегии, до светофора). Обращение на «ты».",
        f"\nФАКТ: в прошлой гонке карьеры (трасса: {track}) игрок финишировал "
        f"на позиции {position} ({tier_label}).",
        "\nНАПИШИ короткую пред-гоночную реплику: ОДНО предложение, русский, "
        "без markdown/кавычек/эмодзи. Если тир 'podium' — похвали темп и "
        "предложи повторить. Если 'points' — отметь, что неплохо, но есть "
        "куда расти. Если 'struggled' — коротко подбодри, без разбора причин.",
    ])


def render_fallback(facts: dict) -> str:
    return _FALLBACK[facts["tier"]]


def generate(facts: dict, ai, persona: str) -> str:
    """LLM, при недоступности — офлайн-фолбэк. persona влияет только на
    ТОН промпта (через get_style) — итоговый ГОЛОС всегда "calm" (инженер),
    выбирается вызывающим кодом (core/engine.py), не этим модулем."""
    if ai is not None and getattr(ai, "available", False):
        text = ai.generate(build_prompt(facts, persona), persona)
        if text and text.strip():
            return text.strip()
    return render_fallback(facts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_pre_race_pep_talk_generator.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Checkpoint**

Confirm all 7 tests pass. No git commit needed (project has no git repo). Move to Task 4.

---

### Task 4: `core/engine.py` — триггер, гвард, озвучка

**Files:**
- Modify: `config.py` (новая константа, после строки 60)
- Modify: `core/engine.py` (импорты, `__init__`, триггер в `_update_telemetry`, два новых метода)
- Test: `tests/test_engine_pre_race_pep_talk.py`

- [ ] **Step 1: Add the delay constant**

В `config.py`, сразу после `ENGINEER_DIGEST_INTERVAL_S = 40.0` (строка 60):

```python
# Пред-гоночная реплика инженера: задержка после входа в экран стратегии
# (session_type -> "race", до SSTA), чтобы дать игроку осмотреться.
PRE_RACE_PEP_TALK_DELAY_S = 4.0
```

- [ ] **Step 2: Add imports to `core/engine.py`**

После строки 38 (`from commentator import story as _story`):

```python
from commentator import pre_race_pep_talk as _pep_talk
```

После строки 76 (`import core.career_stats as career_stats_mod`):

```python
import core.pre_race_pep_talk as _pep_talk_facts
```

(`_archive` уже импортирован строкой 50 — `from analytics import archive as _archive` — переиспользуется как есть.)

- [ ] **Step 3: Add the guard-flag attribute in `__init__`**

После строки 206 (`self._story_fired = False`):

```python

        # Pre-race pep talk (инженер, экран стратегии — см. design spec
        # 2026-07-17-pre-race-pep-talk-design.md). Сбрасывается НЕ на SSTA
        # (в отличие от _story_fired), а в самом блоке перехода session_type,
        # когда игрок уходит из "race" — см. _update_telemetry.
        self._pre_race_pep_talk_fired = False
```

- [ ] **Step 4: Write the failing engine-level tests**

Создать `tests/test_engine_pre_race_pep_talk.py`:

```python
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, PACKET_SESSION


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None              # без Yandex/сети → фолбэк
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _session_packet(session_type_raw: int, track_id: int = 5) -> bytes:
    """Собрать PACKET_SESSION с заданным сырым session_type (см.
    tests/test_session_type.py для расшифровки офсетов и SESSION_TYPE_MAP)."""
    header = b"\x00" * HEADER_SIZE
    payload = struct.pack("<BBbBHBb", 0, 25, 20, 10, 5793, session_type_raw, track_id)
    return header + payload


class _StubThread:
    """Стенд-ин threading.Thread: не выполняет target, только запоминает start()."""

    def __init__(self, target=None, daemon=None, name=None):
        pass

    def start(self):
        pass


def _patch_thread_spawn(monkeypatch, spawned: list) -> None:
    """monkeypatch eng_mod.threading.Thread так, чтобы имя треда попадало в
    spawned, а не запускался реальный поток (иначе _pre_race_pep_talk реально
    засыпает на config.PRE_RACE_PEP_TALK_DELAY_S секунд в фоне теста)."""
    def _fake_thread(target, daemon, name):
        spawned.append(name)
        return _StubThread()
    monkeypatch.setattr(eng_mod.threading, "Thread", _fake_thread)


def test_transition_to_race_spawns_thread_once(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "unknown"
    engine._pre_race_pep_talk_fired = False
    spawned: list = []
    _patch_thread_spawn(monkeypatch, spawned)

    engine._update_telemetry({"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=10))   # -> "race"
    assert spawned == ["pre-race-pep-talk"]
    assert engine._pre_race_pep_talk_fired is True

    # Повторный тик с тем же session_type НЕ меняет new_st != self._session_type,
    # значит блок вообще не выполняется — поток не спавнится второй раз.
    engine._update_telemetry({"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=10))
    assert spawned == ["pre-race-pep-talk"]


def test_leaving_race_resets_guard_and_reentering_refires(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._pre_race_pep_talk_fired = True
    spawned: list = []
    _patch_thread_spawn(monkeypatch, spawned)

    engine._update_telemetry({"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=5))    # -> "qualifying"
    assert engine._pre_race_pep_talk_fired is False
    assert spawned == []                                             # не гонка — не спавним

    engine._update_telemetry({"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=10))   # -> "race" снова
    assert spawned == ["pre-race-pep-talk"]
    assert engine._pre_race_pep_talk_fired is True


def test_engineer_chatter_disabled_suppresses_spawn(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    engine._session_type = "unknown"
    engine._pre_race_pep_talk_fired = False
    spawned: list = []
    _patch_thread_spawn(monkeypatch, spawned)

    engine._update_telemetry({"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=10))
    assert spawned == []
    assert engine._pre_race_pep_talk_fired is False   # не выставлен — включение тумблера сработает сразу
    engine.settings["engineer_chatter_enabled"] = True


def test_generate_pre_race_pep_talk_first_career_race_stays_silent(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)   # пустой архив
    engine.settings["autovoice_enabled"] = False
    engine._session_type = "race"
    said = []
    monkeypatch.setattr(engine.voice, "say", lambda *a, **kw: said.append(a) or True)
    engine._generate_pre_race_pep_talk()
    assert said == []


def test_generate_pre_race_pep_talk_speaks_with_calm_persona(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                              {"track_name": "Монца", "session_type": "race", "final_position": 2})
    engine.settings["autovoice_enabled"] = True
    engine.settings["critical_events_enabled"] = True
    engine._session_type = "race"
    said = []
    monkeypatch.setattr(engine.voice, "say",
                        lambda text, priority="normal", persona=None:
                        said.append((text, priority, persona)) or True)
    engine._generate_pre_race_pep_talk()
    assert len(said) == 1
    text, priority, persona = said[0]
    assert isinstance(text, str) and len(text) > 0
    assert priority == "normal"
    assert persona == "calm"


def test_generate_pre_race_pep_talk_skips_if_left_race_screen(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                              {"track_name": "Монца", "session_type": "race", "final_position": 2})
    engine._session_type = "qualifying"   # игрок вышел из подготовки
    said = []
    monkeypatch.setattr(engine.voice, "say", lambda *a, **kw: said.append(a) or True)
    engine._generate_pre_race_pep_talk()
    assert said == []
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_engine_pre_race_pep_talk.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_generate_pre_race_pep_talk'` (and the trigger tests fail too, since `_update_telemetry` doesn't spawn anything yet).

- [ ] **Step 6: Wire the trigger in `_update_telemetry`**

В `core/engine.py`, заменить существующий блок (строки 969-974):

```python
            if new_st and new_st != self._session_type:
                _log.info("DIAG session_type CHANGED: %s -> %s", self._session_type, new_st)
                self._session_type = new_st
                self._session_guard.set_session_type(new_st)
                with self.state_lock:
                    self.state["session_type"] = new_st
```

на:

```python
            if new_st and new_st != self._session_type:
                _log.info("DIAG session_type CHANGED: %s -> %s", self._session_type, new_st)
                self._session_type = new_st
                self._session_guard.set_session_type(new_st)
                with self.state_lock:
                    self.state["session_type"] = new_st
                if new_st == "race":
                    if (not self._pre_race_pep_talk_fired
                            and self._get_setting("engineer_chatter_enabled", True)):
                        self._pre_race_pep_talk_fired = True
                        threading.Thread(
                            target=self._pre_race_pep_talk, daemon=True,
                            name="pre-race-pep-talk").start()
                else:
                    # Уходим из race (в меню/квалификацию/практику) — сброс,
                    # чтобы следующий заход в race-сессию снова получил реплику.
                    self._pre_race_pep_talk_fired = False
```

- [ ] **Step 7: Add the two new methods**

Добавить в `core/engine.py` сразу после метода `_generate_story` (после строки 1513, перед `def generate_story_now`):

```python

    def _pre_race_pep_talk(self) -> None:
        """Точка входа фонового потока: пауза (даём игроку осмотреться на
        экране стратегии), затем основная логика. Разделено на два метода,
        чтобы тесты могли вызывать _generate_pre_race_pep_talk() напрямую,
        без реального ожидания config.PRE_RACE_PEP_TALK_DELAY_S секунд."""
        time.sleep(config.PRE_RACE_PEP_TALK_DELAY_S)
        self._generate_pre_race_pep_talk()

    def _generate_pre_race_pep_talk(self) -> None:
        """Собрать факты последней гонки карьеры, сгенерировать пред-гоночную
        реплику инженера, озвучить и показать в ленте."""
        try:
            if self._session_type != "race":
                return  # игрок успел выйти из подготовки до срабатывания
            last_race = _archive.get_last_race()
            facts = _pep_talk_facts.facts(last_race)
            if facts is None:
                return  # первая гонка карьеры — инженеру не с чем сравнивать
            text = _pep_talk.generate(facts, self.ai, self.commentator.persona)
            if not text:
                return
            voiced = self._should_voice({"event_code": "PRE_RACE_PEP_TALK", "priority": "normal"})
            with self.state_lock:
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": "PRE_RACE_PEP_TALK", "phrase": text,
                    "color": "#38BDF8", "driver": "",
                    "muted": not voiced, "channel": "commentary"})
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
            if voiced:
                self.voice.say(text, priority="normal", persona="calm")
        except Exception as exc:  # noqa: BLE001
            _log.warning("pre-race pep talk generation failed: %s", exc)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_engine_pre_race_pep_talk.py -v`
Expected: PASS (6 passed).

- [ ] **Step 9: Checkpoint**

Confirm all 6 tests pass. No git commit needed (project has no git repo). Move to Task 5.

---

### Task 5: Full regression

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: all passed, 0 failed, 0 errors (baseline + 5 + 6 + 7 + 6 = baseline + 24 new tests: Task 1 adds 5, Task 2 adds 6, Task 3 adds 7, Task 4 adds 6). Compare the "passed" count against the last known baseline in `CONTEXT.md` (search for the most recent full-suite run count) to confirm the delta matches exactly 24 new tests and nothing else broke.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.engine; import core.pre_race_pep_talk; import commentator.pre_race_pep_talk; import analytics.archive; print('OK')"`
Expected: prints `OK`, no exceptions.

- [ ] **Step 3: Checkpoint — done**

If both steps pass, the feature is complete. No git commit needed (project has no git repo). Update `CONTEXT.md` per the project's own convention (see header of that file) with what was done, following the existing session-entry format.
