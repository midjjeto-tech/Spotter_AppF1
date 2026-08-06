# Session Awareness, Entity Resolution & Output Channels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix practice commentary spam, resolve driver names instead of car numbers, add anti-spam cooldowns per session type, separate commentary/radio/overlay channels, harden telemetry parsing.

**Architecture:** Four new modules (`core/session_guard.py`, `core/entity_resolver.py`, `commentator/radio.py`, `commentator/channel_router.py`) wired into the existing `_commentary_loop` and `_telemetry_loop`. All changes additive — no existing public API removed. Task 6 (EXE tracks bundling) was already completed in a prior session and only requires a one-line verification.

**Tech Stack:** Python 3.12, existing `core/engine.py` / `core/packets.py` / `core/race_state.py` patterns. Test runner: `py -3.12 -m pytest`. All new modules in pure Python — no new deps.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `core/packets.py:179-184` | `parse_session` → add `session_type_raw` + `session_type`; `SESSION_TYPE_MAP`; sanity guards in `parse_player_telemetry` |
| Modify | `core/race_state.py:43-77` | `driver()` — return `"гонщик"` generic fallback instead of `"#N"` string |
| Modify | `core/engine.py` | Integrate `SessionGuard`, `EntityResolver`, `ChannelRouter`; store `_session_type`; propagate to events |
| Create | `core/session_guard.py` | `SessionGuard`: per-session and per-event cooldown logic |
| Create | `core/entity_resolver.py` | `resolve_driver_name`, `resolve_team_name`, `resolve_opponent_name` |
| Create | `commentator/radio.py` | Short radio/cockpit dialogue templates |
| Create | `commentator/channel_router.py` | `ChannelRouter`: map event → "commentary"/"radio"/"overlay" |
| Create | `tests/test_session_type.py` | Tests for `parse_session` session_type field |
| Create | `tests/test_session_guard.py` | Tests for `SessionGuard` |
| Create | `tests/test_entity_resolver.py` | Tests for entity resolution helpers |
| Create | `tests/test_channel_router.py` | Tests for `ChannelRouter` |
| Create | `tests/test_telemetry_sanity.py` | Tests for speed/gear sanity guards |

---

## Task 1: Parse Session Type in `core/packets.py`

**Files:** Modify `core/packets.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_session_type.py`:

```python
"""Tests for session type parsing in parse_session."""
import struct
import pytest
from core.packets import parse_session, HEADER_SIZE, SESSION_TYPE_MAP


def _make_session_packet(total_laps: int, session_type_raw: int, track_id: int = 5) -> bytes:
    """Minimal session packet: header + 8 bytes payload."""
    header = b"\x00" * HEADER_SIZE
    # offset 0: weather, 1: trackTemp(i8), 2: airTemp(i8), 3: totalLaps
    # 4-5: trackLength(u16), 6: sessionType(u8), 7: trackId(i8)
    payload = struct.pack("<BBbBHBb",
        0,             # weather
        25,            # trackTemp
        20,            # airTemp  (signed)
        total_laps,    # totalLaps
        5793,          # trackLength
        session_type_raw,
        track_id,
    )
    return header + payload


def test_practice_p1_maps_to_practice():
    data = _make_session_packet(20, session_type_raw=1)
    result = parse_session(data)
    assert result["session_type"] == "practice"


def test_practice_p3_maps_to_practice():
    data = _make_session_packet(20, session_type_raw=3)
    result = parse_session(data)
    assert result["session_type"] == "practice"


def test_qualifying_q1_maps_to_qualifying():
    data = _make_session_packet(0, session_type_raw=5)
    result = parse_session(data)
    assert result["session_type"] == "qualifying"


def test_race_maps_to_race():
    data = _make_session_packet(58, session_type_raw=10)
    result = parse_session(data)
    assert result["session_type"] == "race"


def test_unknown_type_maps_to_unknown():
    data = _make_session_packet(20, session_type_raw=99)
    result = parse_session(data)
    assert result["session_type"] == "unknown"


def test_time_trial_maps_to_practice():
    data = _make_session_packet(0, session_type_raw=13)
    result = parse_session(data)
    assert result["session_type"] == "practice"


def test_session_type_raw_preserved():
    data = _make_session_packet(20, session_type_raw=3)
    result = parse_session(data)
    assert result["session_type_raw"] == 3


def test_total_laps_still_present():
    data = _make_session_packet(58, session_type_raw=10)
    result = parse_session(data)
    assert result["total_laps"] == 58


def test_too_short_returns_empty():
    result = parse_session(b"\x00" * 5)
    assert result == {}
```

- [ ] **Step 2: Run test — expect FAIL**

```
py -3.12 -m pytest tests/test_session_type.py -v
```
Expected: `AttributeError: module 'core.packets' has no attribute 'SESSION_TYPE_MAP'` or similar.

- [ ] **Step 3: Add `SESSION_TYPE_MAP` and update `parse_session` in `core/packets.py`**

In `core/packets.py`, after the `EVENT_DESCRIPTIONS` dict (around line 64), add:

```python
# F1 25 Session packet: m_sessionType (uint8) at HEADER_SIZE+6
# Values: 1-4=Practice, 5-9=Qualifying, 10-12=Race, 13=Time Trial
SESSION_TYPE_MAP: dict[int, str] = {
    0: "unknown",
    1: "practice", 2: "practice", 3: "practice", 4: "practice",
    5: "qualifying", 6: "qualifying", 7: "qualifying",
    8: "qualifying", 9: "qualifying",
    10: "race", 11: "race", 12: "race",
    13: "practice",   # Time Trial treated as practice (low-frequency commentary)
}
```

Then replace `parse_session` (currently around line 179-184):

```python
def parse_session(data: bytes) -> dict:
    """Session type, total laps, track ID from Session Data (packet 1).

    F1 25 Session payload offsets (relative to HEADER_SIZE):
      +3: m_totalLaps (uint8)
      +6: m_sessionType (uint8)
      +7: m_trackId (int8, signed; -1 = unknown)
    """
    if len(data) < HEADER_SIZE + 8:
        return {}
    track_id = struct.unpack_from("<b", data, HEADER_SIZE + 7)[0]
    session_type_raw = data[HEADER_SIZE + 6]
    return {
        "total_laps": data[HEADER_SIZE + 3],
        "track_id": int(track_id),
        "session_type_raw": session_type_raw,
        "session_type": SESSION_TYPE_MAP.get(session_type_raw, "unknown"),
    }
```

- [ ] **Step 4: Run test — expect PASS**

```
py -3.12 -m pytest tests/test_session_type.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Run full suite — no regressions**

```
py -3.12 -m pytest --ignore=tests/test_gpt.py -q
```
Expected: same count as before + 9 new (322 → 331 passed).

- [ ] **Step 6: No commit yet** — this task is one piece; we commit after all 7 tasks.

---

## Task 2: `core/session_guard.py` — Session-Aware Anti-Spam

**Files:** Create `core/session_guard.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_session_guard.py`:

```python
"""Tests for SessionGuard per-session spam prevention."""
import time
import pytest
from core.session_guard import SessionGuard


# ---------------------------------------------------------------------------
# Practice cooldowns
# ---------------------------------------------------------------------------

def test_practice_first_event_passes():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "FTLP"}) is True


def test_practice_same_event_blocked_within_cooldown():
    g = SessionGuard()
    g.set_session_type("practice")
    g.should_emit({"event_code": "FTLP"})      # first: pass
    assert g.should_emit({"event_code": "FTLP"}) is False   # second: blocked


def test_practice_different_events_both_pass():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "FTLP"}) is True
    assert g.should_emit({"event_code": "SSTA"}) is True


def test_practice_suppresses_race_only_events():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "STRAT_PUSH"}) is False
    assert g.should_emit({"event_code": "FINAL_LAP"}) is False


def test_practice_critical_always_passes():
    g = SessionGuard()
    g.set_session_type("practice")
    g.should_emit({"event_code": "CHQF"})   # first pass + record
    # Critical ignores cooldown
    assert g.should_emit({"event_code": "CHQF", "priority": "critical"}) is True


def test_race_less_strict_than_practice():
    g_practice = SessionGuard()
    g_practice.set_session_type("practice")
    g_race = SessionGuard()
    g_race.set_session_type("race")
    # Both pass on first emit
    g_practice.should_emit({"event_code": "OVTK"})
    g_race.should_emit({"event_code": "OVTK"})
    # practice blocks, race may pass (race cooldown < practice cooldown)
    assert g_practice.should_emit({"event_code": "OVTK"}) is False
    # Race cooldown is also nonzero so second is blocked there too
    assert g_race.should_emit({"event_code": "OVTK"}) is False


def test_session_type_change_resets_state():
    g = SessionGuard()
    g.set_session_type("practice")
    g.should_emit({"event_code": "OVTK"})   # record
    # Change session → state clears
    g.set_session_type("race")
    assert g.should_emit({"event_code": "OVTK"}) is True  # fresh after reset


def test_qualifying_has_moderate_cooldowns():
    g = SessionGuard()
    g.set_session_type("qualifying")
    assert g.should_emit({"event_code": "FTLP"}) is True
    assert g.should_emit({"event_code": "FTLP"}) is False


def test_unknown_session_uses_race_defaults():
    g = SessionGuard()
    g.set_session_type("unknown")
    assert g.should_emit({"event_code": "OVTK"}) is True


def test_default_session_is_unknown():
    g = SessionGuard()
    assert g.should_emit({"event_code": "OVTK"}) is True
```

- [ ] **Step 2: Run test — expect FAIL**

```
py -3.12 -m pytest tests/test_session_guard.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.session_guard'`.

- [ ] **Step 3: Create `core/session_guard.py`**

```python
"""
core/session_guard.py
======================
Session-aware per-event cooldown and spam prevention.

Practice sessions use strict cooldowns and suppress race-only events.
Qualifying uses moderate sector-driven cooldowns.
Race uses the most permissive cooldowns.
Critical events always bypass all cooldowns.
"""
from __future__ import annotations

import time


class SessionGuard:
    """Per-session and per-event spam prevention.

    Call set_session_type() whenever the session packet arrives.
    Call should_emit(event) before queuing commentary — returns False to suppress.
    """

    # Events that only make sense in a race context — silence in practice
    _PRACTICE_SUPPRESS: frozenset[str] = frozenset({
        "STRAT_PUSH", "STRAT_SAVE", "STRAT_FUEL", "STRAT_PIT",
        "STRAT_UNDERCUT", "STRAT_OVERCUT",
        "FINAL_LAP",
    })

    # Per-event cooldowns (seconds) by session type.
    # "default" applies to any code not explicitly listed.
    _COOLDOWNS: dict[str, dict[str, float]] = {
        "practice": {
            "FTLP": 60.0,   # one fast-lap mention per minute max
            "OVTK": 25.0,
            "DRSE": 45.0,
            "DRSD": 45.0,
            "TMPT": 90.0,
            "SPTP": 90.0,
            "STLG": 300.0,
            "ATTACK": 60.0,
            "BATTLE": 40.0,
            "AMBIENT": 60.0,
            "default": 20.0,
        },
        "qualifying": {
            "FTLP": 12.0,   # sector/attempt-driven
            "OVTK": 10.0,
            "DRSE": 20.0,
            "DRSD": 20.0,
            "TMPT": 30.0,
            "ATTACK": 20.0,
            "BATTLE": 15.0,
            "default": 10.0,
        },
        "race": {
            "DRSE": 8.0,
            "DRSD": 8.0,
            "SPTP": 30.0,
            "TMPT": 30.0,
            "default": 4.0,
        },
        "unknown": {
            "default": 4.0,
        },
    }

    def __init__(self) -> None:
        self._session_type: str = "unknown"
        self._last: dict[str, float] = {}   # event_code -> last_emit timestamp

    def set_session_type(self, session_type: str) -> None:
        """Update session type; resets all per-event cooldown state."""
        if session_type != self._session_type:
            self._session_type = session_type
            self._last.clear()

    def should_emit(self, event: dict) -> bool:
        """Return True if this event should be sent to commentary.

        False = suppress (cooldown active or race-only event in practice).
        Critical events always bypass all cooldowns.
        """
        if event.get("priority") == "critical":
            return True

        code: str = event.get("event_code", "")
        st = self._session_type

        if st == "practice" and code in self._PRACTICE_SUPPRESS:
            return False

        cooldowns = self._COOLDOWNS.get(st, self._COOLDOWNS["unknown"])
        cooldown = cooldowns.get(code, cooldowns["default"])

        now = time.time()
        last = self._last.get(code, 0.0)
        if now - last < cooldown:
            return False

        self._last[code] = now
        return True
```

- [ ] **Step 4: Run test — expect PASS**

```
py -3.12 -m pytest tests/test_session_guard.py -v
```
Expected: 10 passed.

---

## Task 3: `core/entity_resolver.py` + Fix Generic Driver Fallback

**Files:** Create `core/entity_resolver.py`; modify `core/race_state.py:43-77`

- [ ] **Step 1: Write failing test**

Create `tests/test_entity_resolver.py`:

```python
"""Tests for entity resolution helpers."""
import pytest
from core.entity_resolver import resolve_driver_name, resolve_team_name, resolve_opponent_name


# ---------------------------------------------------------------------------
# resolve_driver_name
# ---------------------------------------------------------------------------

def test_resolve_driver_name_from_event_driver_field():
    event = {"driver": "Льюис Хэмилтон", "team": "Ferrari"}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


def test_resolve_driver_name_fallback_from_number():
    # driver field absent or placeholder; number triggers F1_2025_BY_NUMBER lookup
    event = {"driver": "", "number": 44}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


def test_resolve_driver_name_generic_when_unknown():
    event = {"driver": "", "number": 99}  # 99 not in static dict
    assert resolve_driver_name(event) == "гонщик"


def test_resolve_driver_name_hash_placeholder_triggers_lookup():
    # "#44" is a placeholder — should resolve via number 44
    event = {"driver": "#44"}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


def test_resolve_driver_name_no_number_returns_generic():
    event = {}
    assert resolve_driver_name(event) == "гонщик"


# ---------------------------------------------------------------------------
# resolve_team_name
# ---------------------------------------------------------------------------

def test_resolve_team_name_from_event():
    event = {"team": "McLaren"}
    assert resolve_team_name(event) == "McLaren"


def test_resolve_team_name_generic_when_absent():
    event = {}
    assert resolve_team_name(event) == "команда"


def test_resolve_team_name_hash_placeholder_returns_generic():
    event = {"team": "#5"}
    assert resolve_team_name(event) == "команда"


# ---------------------------------------------------------------------------
# resolve_opponent_name
# ---------------------------------------------------------------------------

def test_resolve_opponent_name_from_target_field():
    event = {"target": "Макс Ферстаппен"}
    assert resolve_opponent_name(event) == "Макс Ферстаппен"


def test_resolve_opponent_name_generic_when_absent():
    event = {}
    assert resolve_opponent_name(event) == "соперник"


def test_resolve_opponent_name_hash_placeholder_returns_generic():
    event = {"target": "#1"}
    assert resolve_opponent_name(event) == "соперник"
```

- [ ] **Step 2: Run test — expect FAIL**

```
py -3.12 -m pytest tests/test_entity_resolver.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.entity_resolver'`.

- [ ] **Step 3: Create `core/entity_resolver.py`**

```python
"""
core/entity_resolver.py
========================
Human-readable name resolution for events.

These functions are the commentary layer's public API over race_state.driver().
They never return bare car numbers — fall back to Russian generic labels instead.
"""
from __future__ import annotations

from core.f1_metadata import F1_2025_BY_NUMBER

_GENERIC_DRIVER = "гонщик"
_GENERIC_TEAM = "команда"
_GENERIC_OPPONENT = "соперник"


def resolve_driver_name(event: dict) -> str:
    """Return human-readable driver name from event dict.

    Resolution order:
    1. event["driver"] if it's a real name (not empty or "#N" placeholder)
    2. F1_2025_BY_NUMBER lookup by event["number"] or event["driver_number"]
    3. Generic fallback "гонщик"
    """
    name: str = event.get("driver") or ""
    if name and not name.startswith("#"):
        return name

    for key in ("number", "driver_number"):
        raw = event.get(key)
        if raw is not None:
            try:
                static = F1_2025_BY_NUMBER.get(int(raw))
                if static:
                    return static[0]
            except (TypeError, ValueError):
                pass

    return _GENERIC_DRIVER


def resolve_team_name(event: dict) -> str:
    """Return human-readable team name from event dict.

    Falls back to "команда" if unavailable or placeholder.
    """
    team: str = event.get("team") or ""
    if team and not team.startswith("#"):
        return team
    return _GENERIC_TEAM


def resolve_opponent_name(event: dict) -> str:
    """Return human-readable opponent/target name from event dict.

    Uses event["target"]; falls back to "соперник".
    """
    target: str = event.get("target") or ""
    if target and not target.startswith("#"):
        return target
    return _GENERIC_OPPONENT
```

- [ ] **Step 4: Fix generic fallback in `core/race_state.py`**

In `race_state.driver()`, replace the two fallback returns that produce `"#N"` style strings.

Old code (lines ~65-77):
```python
        if num:
            static = F1_2025_BY_NUMBER.get(int(num))
            if static:
                return {
                    "name": static[0],
                    "team": info.get("team") or static[1],
                    "color": info.get("color", "#9CA3AF"),
                    "number": num,
                }
            return {
                "name": f"#{num}",          # ← bare number
                "team": info.get("team", ""),
                "color": info.get("color", "#9CA3AF"),
                "number": num,
            }
        return {
            "name": f"#{vehicle_idx}",      # ← bare vehicle idx
            "team": info.get("team", ""),
            "color": info.get("color", "#9CA3AF"),
        }

    return {"name": f"#{vehicle_idx}", "team": "", "color": "#9CA3AF"}  # ← last line
```

New code — replace those returns:
```python
        if num:
            static = F1_2025_BY_NUMBER.get(int(num))
            if static:
                return {
                    "name": static[0],
                    "team": info.get("team") or static[1],
                    "color": info.get("color", "#9CA3AF"),
                    "number": num,
                }
            # number known but not in static dict (custom driver, MY TEAM etc.)
            return {
                "name": "гонщик",
                "team": info.get("team", ""),
                "color": info.get("color", "#9CA3AF"),
                "number": num,
            }
        return {
            "name": "гонщик",
            "team": info.get("team", ""),
            "color": info.get("color", "#9CA3AF"),
        }

    return {"name": "гонщик", "team": "", "color": "#9CA3AF"}
```

- [ ] **Step 5: Run entity resolver tests — expect PASS**

```
py -3.12 -m pytest tests/test_entity_resolver.py -v
```
Expected: 11 passed.

- [ ] **Step 6: Run full suite — no regressions**

```
py -3.12 -m pytest --ignore=tests/test_gpt.py -q
```
Expected: same as before + 11 new tests passing. Note: some existing tests that assert `"#44"` fallback format may need updating — fix them to expect `"гонщик"` if they test the ultimate fallback path.

---

## Task 4: `commentator/radio.py` + `commentator/channel_router.py`

**Files:** Create `commentator/radio.py`; create `commentator/channel_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_channel_router.py`:

```python
"""Tests for channel routing and radio templates."""
import pytest
from commentator.channel_router import route_event, CHANNEL_COMMENTARY, CHANNEL_RADIO, CHANNEL_OVERLAY
from commentator.radio import get_radio_line


# ---------------------------------------------------------------------------
# channel routing
# ---------------------------------------------------------------------------

def test_ovtk_routes_to_commentary_in_race():
    assert route_event({"event_code": "OVTK"}, "race") == CHANNEL_COMMENTARY


def test_drse_routes_to_radio():
    assert route_event({"event_code": "DRSE"}, "race") == CHANNEL_RADIO


def test_drsd_routes_to_radio():
    assert route_event({"event_code": "DRSD"}, "race") == CHANNEL_RADIO


def test_strategy_pit_routes_to_radio():
    assert route_event({"event_code": "STRAT_PIT"}, "race") == CHANNEL_RADIO


def test_tyre_warn_routes_to_radio():
    assert route_event({"event_code": "TYRE_WARN"}, "race") == CHANNEL_RADIO


def test_major_events_always_commentary():
    for code in ("SSTA", "CHQF", "RCWN", "RTMT", "PENA"):
        channel = route_event({"event_code": code}, "practice")
        assert channel == CHANNEL_COMMENTARY, f"{code} should be commentary"


def test_drse_in_practice_routes_to_overlay():
    assert route_event({"event_code": "DRSE"}, "practice") == CHANNEL_OVERLAY


def test_ambient_always_commentary():
    assert route_event({"event_code": "AMBIENT"}, "race") == CHANNEL_COMMENTARY
    assert route_event({"event_code": "AMBIENT"}, "practice") == CHANNEL_COMMENTARY


def test_sptp_in_practice_is_overlay():
    assert route_event({"event_code": "SPTP"}, "practice") == CHANNEL_OVERLAY


def test_unknown_event_defaults_to_commentary():
    assert route_event({"event_code": "XYZZ"}, "race") == CHANNEL_COMMENTARY


# ---------------------------------------------------------------------------
# radio templates
# ---------------------------------------------------------------------------

def test_radio_drse_returns_string():
    line = get_radio_line("DRSE")
    assert isinstance(line, str) and len(line) > 0


def test_radio_unknown_code_returns_none():
    assert get_radio_line("NONEXISTENT") is None


def test_radio_tyre_warn_returns_string():
    line = get_radio_line("TYRE_WARN")
    assert isinstance(line, str) and len(line) > 0


def test_radio_strat_save_returns_string():
    line = get_radio_line("STRAT_SAVE")
    assert isinstance(line, str) and len(line) > 0


def test_channel_constants_are_distinct():
    assert CHANNEL_COMMENTARY != CHANNEL_RADIO != CHANNEL_OVERLAY
```

- [ ] **Step 2: Run test — expect FAIL**

```
py -3.12 -m pytest tests/test_channel_router.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `commentator/radio.py`**

```python
"""
commentator/radio.py
=====================
Short cockpit radio dialogue templates.

These are brief engineer-to-driver or driver-to-engineer lines — not full
commentary narration. Used when channel_router routes an event to CHANNEL_RADIO.
"""
from __future__ import annotations
import random

_RADIO: dict[str, list[str]] = {
    "DRSE": [
        "DRS открыт.",
        "DRS активен, атакуем.",
        "DRS включён.",
    ],
    "DRSD": [
        "DRS закрыт.",
        "Теряем DRS.",
        "DRS выключен — держи позицию.",
    ],
    "TYRE_WARN": [
        "Шины на пределе.",
        "Деградация растёт — аккуратнее.",
        "Береги резину, обрати внимание.",
    ],
    "STRAT_SAVE": [
        "Береги шины.",
        "Экономим резину.",
        "Тише с шинами — нужен следующий стинт.",
    ],
    "STRAT_PUSH": [
        "Давай темп!",
        "Атакуй — момент есть.",
        "Полный газ, окно открыто.",
    ],
    "STRAT_FUEL": [
        "Экономь топливо.",
        "Режим экономии топлива.",
        "Топлива мало — смотри расход.",
    ],
    "STRAT_PIT": [
        "Готовимся к боксу.",
        "Пит-стоп в этом окне.",
        "Зайди в боксы — окно открыто.",
    ],
    "STRAT_UNDERCUT": [
        "Зайди раньше — андеркат доступен.",
        "Ранний пит-стоп, андеркат.",
    ],
    "STRAT_OVERCUT": [
        "Держись — оверкат в игре.",
        "Не заходи, оверкат работает.",
    ],
    "ATTACK": [
        "Машина сзади.",
        "Атака сзади — держи.",
        "Сзади давят — защищайся.",
    ],
}


def get_radio_line(event_code: str) -> str | None:
    """Return a random radio line for the given event code, or None if none defined."""
    pool = _RADIO.get(event_code)
    if not pool:
        return None
    return random.choice(pool)
```

- [ ] **Step 4: Create `commentator/channel_router.py`**

```python
"""
commentator/channel_router.py
==============================
Routes an event to the correct output channel.

Channels:
  CHANNEL_COMMENTARY — full spoken narration (LLM or template)
  CHANNEL_RADIO      — short cockpit dialogue (commentator/radio.py templates)
  CHANNEL_OVERLAY    — silent feed entry only (no voice)

Routing rules:
  - Major lifecycle events (SSTA/CHQF/RCWN/RTMT/PENA/OVTK/FTLP) → commentary
  - Cockpit telemetry events (DRSE/DRSD) in race → radio; in practice → overlay
  - Strategy advice (STRAT_*) → radio
  - Race AI tactical (ATTACK/BATTLE/TYRE_WARN) → radio for TYRE_WARN; commentary for ATTACK/BATTLE
  - AMBIENT/FINAL_LAP → commentary
  - Everything else → commentary (safe default)
"""
from __future__ import annotations

CHANNEL_COMMENTARY = "commentary"
CHANNEL_RADIO      = "radio"
CHANNEL_OVERLAY    = "overlay"

# Events that always route to commentary regardless of session type
_ALWAYS_COMMENTARY: frozenset[str] = frozenset({
    "SSTA", "CHQF", "RCWN", "RTMT", "PENA",
    "OVTK", "FTLP", "AMBIENT", "FINAL_LAP",
    "ATTACK", "BATTLE",
})

# Events routed to radio in a race context
_RADIO_IN_RACE: frozenset[str] = frozenset({
    "DRSE", "DRSD",
    "STRAT_PIT", "STRAT_UNDERCUT", "STRAT_OVERCUT",
    "STRAT_SAVE", "STRAT_PUSH", "STRAT_FUEL",
    "TYRE_WARN",
})

# Events silenced to overlay-only in practice (no voice at all)
_PRACTICE_OVERLAY: frozenset[str] = frozenset({
    "DRSE", "DRSD", "SPTP", "STLG", "FLBK", "TMPT",
})


def route_event(event: dict, session_type: str = "race") -> str:
    """Return the output channel for this event and session type.

    Parameters
    ----------
    event : dict
        Event dict (must have "event_code").
    session_type : str
        "race", "qualifying", "practice", or "unknown".

    Returns
    -------
    str
        One of CHANNEL_COMMENTARY, CHANNEL_RADIO, CHANNEL_OVERLAY.
    """
    code: str = event.get("event_code", "")

    if code in _ALWAYS_COMMENTARY:
        return CHANNEL_COMMENTARY

    if session_type == "practice" and code in _PRACTICE_OVERLAY:
        return CHANNEL_OVERLAY

    if code in _RADIO_IN_RACE:
        return CHANNEL_RADIO

    return CHANNEL_COMMENTARY   # safe default
```

- [ ] **Step 5: Run tests — expect PASS**

```
py -3.12 -m pytest tests/test_channel_router.py -v
```
Expected: 15 passed.

---

## Task 5: Telemetry Sanity Guards in `core/packets.py`

**Files:** Modify `core/packets.py:254-267`

- [ ] **Step 1: Write failing tests**

Create `tests/test_telemetry_sanity.py`:

```python
"""Tests for telemetry sanity guards in parse_player_telemetry."""
import struct
import pytest
from core.packets import (
    parse_player_telemetry, HEADER_SIZE, CAR_TELEMETRY_FORMAT, CAR_TELEMETRY_SIZE,
)


def _make_telemetry_packet(player_idx: int, speed: int, gear: int) -> bytes:
    """Build minimal CAR_TELEMETRY packet for one player at player_idx."""
    # CAR_TELEMETRY_FORMAT = "<HfffBbHBBBBHHHHbbbbHffffBBBB"
    # fields[0]=speed(H), [1]=throttle(f), [2]=steer(f), [3]=brake(f),
    # [4]=clutch(B), [5]=gear(b), ...
    header = b"\x00" * HEADER_SIZE
    # 1 extra byte (numActiveCars) before the array
    prefix = b"\x16"   # 22 cars
    # pad player_idx * CAR_TELEMETRY_SIZE zeros before our entry
    padding = b"\x00" * (player_idx * CAR_TELEMETRY_SIZE)
    entry = struct.pack(CAR_TELEMETRY_FORMAT,
        speed,          # H speed km/h
        0.0,            # f throttle
        0.0,            # f steer
        0.0,            # f brake
        0,              # B clutch
        gear,           # b gear
        5000,           # H engineRPM
        0, 0, 0, 0,     # BBBB
        0, 0, 0, 0,     # HHHH
        0, 0, 0, 0,     # bbbb
        0,              # H
        0.0, 0.0, 0.0, 0.0,  # ffff
        0, 0, 0, 0,     # BBBB
    )
    return header + prefix + padding + entry


def test_valid_speed_returned():
    data = _make_telemetry_packet(0, speed=280, gear=5)
    result = parse_player_telemetry(data, 0)
    assert result["speed"] == 280


def test_zero_speed_allowed():
    data = _make_telemetry_packet(0, speed=0, gear=0)
    result = parse_player_telemetry(data, 0)
    assert result["speed"] == 0


def test_max_realistic_speed_allowed():
    data = _make_telemetry_packet(0, speed=400, gear=8)
    result = parse_player_telemetry(data, 0)
    assert result["speed"] == 400


def test_absurd_speed_filtered_out():
    data = _make_telemetry_packet(0, speed=65535, gear=5)
    result = parse_player_telemetry(data, 0)
    assert "speed" not in result


def test_reverse_gear_returned():
    data = _make_telemetry_packet(0, speed=5, gear=-1)
    result = parse_player_telemetry(data, 0)
    assert result["gear"] == "R"


def test_neutral_gear_returned():
    data = _make_telemetry_packet(0, speed=0, gear=0)
    result = parse_player_telemetry(data, 0)
    assert result["gear"] == "N"


def test_gear_8_returned():
    data = _make_telemetry_packet(0, speed=350, gear=8)
    result = parse_player_telemetry(data, 0)
    assert result["gear"] == "8"


def test_absurd_gear_filtered_out():
    # struct.pack signed byte wraps; test 100 → would be out of range
    # gear is int8 so max is 127; valid range is -1..8
    # We can't pass 100 via PARTICIPANT_FORMAT easily due to struct,
    # but we can patch to check the guard: use gear=50 (valid in struct but invalid for F1)
    data = _make_telemetry_packet(0, speed=100, gear=50)
    result = parse_player_telemetry(data, 0)
    assert "gear" not in result
```

- [ ] **Step 2: Run test — expect FAIL (speed 65535 currently passes through)**

```
py -3.12 -m pytest tests/test_telemetry_sanity.py -v
```
Expected: `test_absurd_speed_filtered_out` FAILS (no guard yet), others may pass.

- [ ] **Step 3: Add sanity guards in `core/packets.py:254-267`**

Replace `parse_player_telemetry` with:

```python
def parse_player_telemetry(data: bytes, player_idx: int) -> dict:
    """Speed (km/h) and gear from CarTelemetry (packet 6).

    Sanity-checked: speed > 400 km/h or gear outside [-1, 8] are silently
    dropped (logged at WARNING level). This prevents absurd UI values when
    the packet format has changed or endian/sign confusion exists.
    """
    import logging

    base = HEADER_SIZE + 1 + player_idx * CAR_TELEMETRY_SIZE
    chunk = data[base:base + CAR_TELEMETRY_SIZE]
    if len(chunk) < CAR_TELEMETRY_SIZE:
        return {}
    try:
        fields = struct.unpack_from(CAR_TELEMETRY_FORMAT, chunk, 0)
    except struct.error:
        return {}

    result: dict = {}
    speed: int = fields[0]          # uint16 km/h
    gear: int = fields[5]           # int8

    if 0 <= speed <= 400:
        result["speed"] = speed
    else:
        logging.getLogger(__name__).warning(
            "suspicious speed %d km/h for car_idx=%d — dropped", speed, player_idx
        )

    if -1 <= gear <= 8:
        result["gear"] = "N" if gear == 0 else ("R" if gear == -1 else str(gear))
    else:
        logging.getLogger(__name__).warning(
            "suspicious gear %d for car_idx=%d — dropped", gear, player_idx
        )

    return result
```

- [ ] **Step 4: Run tests — expect PASS**

```
py -3.12 -m pytest tests/test_telemetry_sanity.py -v
```
Expected: 8 passed.

---

## Task 6: Wire Everything into `core/engine.py`

**Files:** Modify `core/engine.py`

This task integrates all the new modules. Read the current engine.py carefully before editing.

- [ ] **Step 1: Add imports at the top of `core/engine.py`** (after existing imports)

```python
from core.session_guard import SessionGuard
from core.entity_resolver import resolve_driver_name, resolve_team_name, resolve_opponent_name
from commentator.channel_router import route_event, CHANNEL_RADIO, CHANNEL_OVERLAY
from commentator.radio import get_radio_line
from core.packets import SESSION_TYPE_MAP
```

- [ ] **Step 2: Add `_session_type` and `_session_guard` to `F1Engine.__init__`**

After the line `self._player_car_index = 255` (around line 80), add:

```python
        self._session_type: str = "unknown"
        self._session_guard = SessionGuard()
```

Also add `session_type` to the shared state dict (around line 129 where `self.state = {...}`):

```python
            "session_type": "unknown",      # "practice"/"qualifying"/"race"/"unknown"
```

- [ ] **Step 3: Update `_update_telemetry` to track session type on PACKET_SESSION**

In `_update_telemetry`, inside the `if packet_id == PACKET_SESSION:` block (around line 550), after the existing `if session.get("track_id", -1) >= 0:` block, add:

```python
            new_st = session.get("session_type", "unknown")
            if new_st and new_st != self._session_type:
                self._session_type = new_st
                self._session_guard.set_session_type(new_st)
                with self.state_lock:
                    self.state["session_type"] = new_st
```

- [ ] **Step 4: Propagate `session_type` to events in `_telemetry_loop`**

In `_telemetry_loop`, just before `self.event_queue.put(enriched)` (around line 903), add:

```python
            enriched["session_type"] = self._session_type
```

- [ ] **Step 5: Add entity resolver fallback in `_commentary_loop`**

In `_commentary_loop`, after `event = self.event_queue.get()` (around line 913), add a post-processing step to ensure resolved names are present:

```python
            # Ensure human-readable names — resolver fills gaps left by enrichment
            if not event.get("driver") or event["driver"].startswith("#"):
                event["driver"] = resolve_driver_name(event)
            if "target" in event and (not event.get("target") or event["target"].startswith("#")):
                event["target"] = resolve_opponent_name(event)
```

- [ ] **Step 6: Wire `SessionGuard` and `ChannelRouter` into `_commentary_loop`**

In `_commentary_loop`, after the entity resolver block, add channel routing before the phrase generation:

```python
            # Session-aware spam guard: suppress over-frequent events in practice
            if not self._session_guard.should_emit(event):
                continue

            # Determine output channel for this event
            channel = route_event(event, self._session_type)

            # Overlay-only events: add to feed silently, no voice
            if channel == CHANNEL_OVERLAY:
                with self.state_lock:
                    self.state["feed"].insert(0, {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "event_code": event["event_code"],
                        "phrase": event.get("description", event["event_code"]),
                        "color": event.get("color", "#9CA3AF"),
                        "driver": event.get("driver", ""),
                        "muted": True,
                        "channel": "overlay",
                    })
                    self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
                continue
```

Then, for radio events, generate the radio phrase instead of commentary:

```python
            if channel == CHANNEL_RADIO:
                phrase = get_radio_line(event["event_code"])
                if not phrase:
                    # Fall through to commentary if no radio template
                    channel = CHANNEL_COMMENTARY
```

The existing phrase-generation block for commentary runs for `channel == CHANNEL_COMMENTARY` (i.e., the existing code that calls `strategist.get_message`, `create_broadcast`, `create`).

> **NOTE:** The existing code after the routing block handles phrase generation. Restructure so that:
> 1. If channel == CHANNEL_OVERLAY → feed + continue (done above)
> 2. If channel == CHANNEL_RADIO → phrase from get_radio_line (done above)
> 3. Otherwise → existing phrase generation logic unchanged

The simplest way is to add the routing block above the existing phrase-generation if-elif chain, then let radio fall through to the `if not phrase:` check below, with `should_voice` determined normally.

Full restructured `_commentary_loop` (key section only — replace from `while True:` until the `last_speak_time = time.time()` line):

```python
    def _commentary_loop(self):
        last_speak_time = 0.0

        while True:
            event = self.event_queue.get()

            if self._is_paused():
                continue

            # ── Entity resolution: fill gaps in driver/target names ──────────
            if not event.get("driver") or str(event.get("driver", "")).startswith("#"):
                event["driver"] = resolve_driver_name(event)
            if "target" in event and (
                    not event.get("target") or str(event["target"]).startswith("#")):
                event["target"] = resolve_opponent_name(event)

            # ── Session-aware spam guard ─────────────────────────────────────
            if not self._session_guard.should_emit(event):
                continue

            # ── Channel routing ──────────────────────────────────────────────
            channel = route_event(event, self._session_type)

            if channel == CHANNEL_OVERLAY:
                with self.state_lock:
                    self.state["feed"].insert(0, {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "event_code": event["event_code"],
                        "phrase": event.get("description", event["event_code"]),
                        "color": event.get("color", "#9CA3AF"),
                        "driver": event.get("driver", ""),
                        "muted": True,
                        "channel": "overlay",
                    })
                    self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
                continue

            # ── Phrase generation ────────────────────────────────────────────
            phrase = ""
            if channel == CHANNEL_RADIO:
                phrase = get_radio_line(event["event_code"]) or ""

            if not phrase:
                with self.state_lock:
                    broadcast_on = self.state.get("broadcast_mode_enabled", False)
                if event.get("strategy_ai_type"):
                    from commentator import strategist
                    phrase = strategist.get_message(
                        event.get("strategy_ai_type", "stable"),
                        event.get("strategy_ai_data"),
                    )
                elif broadcast_on and event.get("race_ai_type"):
                    phrase = self.commentator.create_broadcast(
                        event, ai_ok=self._yandex_healthy)
                else:
                    phrase = self.commentator.create(
                        event, self._build_ai_context(event), ai_ok=self._yandex_healthy)

            if not phrase:
                continue

            should_voice = self._should_voice(event)

            if should_voice and event.get("priority") != "critical":
                min_gap = self._get_setting("min_comment_gap", config.MIN_COMMENT_GAP)
                wait = min_gap - (time.time() - last_speak_time)
                if wait > 0:
                    time.sleep(wait)

            with self.state_lock:
                self.state["now_speaking"] = phrase if should_voice else ""
                self.state["speaking"] = should_voice
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event["event_code"],
                    "phrase": phrase,
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": not should_voice,
                    "channel": channel,
                })
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]

            if should_voice:
                priority = "critical" if event.get("priority") == "critical" else "normal"
                self.voice.say(phrase, priority=priority)

            with self.state_lock:
                self.state["speaking"] = False
                self.state["now_speaking"] = ""

            last_speak_time = time.time()
```

- [ ] **Step 7: Run full test suite**

```
py -3.12 -m pytest --ignore=tests/test_gpt.py -q
```
Expected: all prior tests pass + new tests from Tasks 1-5. Count should be ~322 + ~50 new = ~370+ passed.

---

## Task 7: Verify EXE Readiness (Quick Check)

**Files:** `SpotterApp.spec`, `build.ps1` — read-only verification, no changes expected.

- [ ] **Step 1: Verify `SpotterApp.spec` has tracks**

```
python -c "data = open('SpotterApp.spec').read(); print('OK' if \"('tracks', 'tracks')\" in data else 'MISSING')"
```
Expected: `OK` (added in prior session Task 7). If `MISSING`, add it to the `datas` list.

- [ ] **Step 2: Verify `build.ps1` validates tracks**

```
python -c "data = open('build.ps1').read(); print('OK' if 'tracks' in data.lower() else 'MISSING')"
```
Expected: `OK`.

- [ ] **Step 3: No changes needed if both print OK**

---

## Final Verification

- [ ] **Run complete test suite**

```
py -3.12 -m pytest --ignore=tests/test_gpt.py -v 2>&1 | tail -20
```
Expected: all pass, no regressions.

- [ ] **Import smoke test (no crashes)**

```
py -3.12 -c "from core.session_guard import SessionGuard; from core.entity_resolver import resolve_driver_name; from commentator.channel_router import route_event; from commentator.radio import get_radio_line; print('imports OK')"
```

- [ ] **Update CONTEXT.md**

Add a section under the latest task log:

```
## Session Task — Session Awareness + Anti-Spam + Entity Resolution + Channels + Telemetry (2026-06-25)

**New modules:**
- `core/session_guard.py` — SessionGuard: per-session event cooldown; practice suppresses STRAT_PUSH/FINAL_LAP etc.
- `core/entity_resolver.py` — resolve_driver_name/resolve_team_name/resolve_opponent_name; never returns bare car numbers
- `commentator/radio.py` — short cockpit radio dialogue templates (DRSE/DRSD/STRAT/TYRE_WARN)
- `commentator/channel_router.py` — routes events to commentary/radio/overlay per session type

**Modified:**
- `core/packets.py` — SESSION_TYPE_MAP; parse_session returns session_type; parse_player_telemetry sanity guards (speed≤400, gear -1..8)
- `core/race_state.py` — driver() final fallback is "гонщик" not "#N"
- `core/engine.py` — _session_type/_session_guard; session_type in state/events; entity resolver in loop; channel router in loop

**Behaviour changes:**
- Practice sessions: STRAT_PUSH/FINAL_LAP suppressed; DRSE/DRSD go to overlay; all events have much longer cooldowns
- Driver names: "гонщик"/"соперник"/"команда" for unresolvable names instead of "#4"/"#10"
- Feed items now carry a "channel" field: "commentary"/"radio"/"overlay"
```

---

## Self-Review

**Spec coverage check:**
1. ✅ Session awareness (`_session_type`, `SessionGuard`, `SESSION_TYPE_MAP`) — Tasks 1, 2, 6
2. ✅ Entity resolution (`resolve_driver_name`, `resolve_team_name`, `resolve_opponent_name`) — Tasks 3, 6
3. ✅ Anti-spam controls (`SessionGuard.should_emit`, per-session cooldowns) — Task 2, 6
4. ✅ Separate output channels (`channel_router`, `radio.py`, channel field in feed) — Tasks 4, 6
5. ✅ Telemetry reliability (speed ≤ 400 guard, gear -1..8 guard, logging.warning) — Task 5
6. ✅ EXE readiness (`('tracks','tracks')` in spec) — Task 7 (prior session, verify only)

**Placeholder scan:** No TBD/TODO/placeholder content. All code shown in full.

**Type consistency:**
- `SessionGuard.should_emit(event: dict) -> bool` — used consistently in Task 6
- `route_event(event: dict, session_type: str) -> str` — returns CHANNEL_* constants
- `get_radio_line(event_code: str) -> str | None` — checked for None before use in Task 6
- `resolve_driver_name(event: dict) -> str` — always returns a string

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-25-session-entity-channels-telemetry.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
