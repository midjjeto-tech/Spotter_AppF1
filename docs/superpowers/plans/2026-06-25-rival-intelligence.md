# Rival Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `core/rivals/` — a lightweight, deterministic rival-tracking layer that turns per-tick grid updates into style classification, pit detection, and nearest-rival awareness, exposed via `state["rivals"]` and a Dashboard panel.

**Architecture:** No new UDP parser work required — feeds entirely from `state["race"]["grid"]` which is updated each telemetry tick. `RivalTracker.update(grid, player_idx)` is called by engine each tick; it maintains per-rival position history, detects pits from position spikes, and classifies driving style. State exposed via `engine.state["rivals"]`, `GET /api/rivals`, and a "Соперники" Dashboard panel.

**Tech Stack:** Python 3.12 dataclasses + `collections.deque`, no external deps, pure math. TypeScript/React for UI panel.

---

## Data Sources

Engine already maintains `state["race"]["grid"]` as a list of `GridEntry`-like dicts (from `_update_telemetry`). Each entry has:
```python
{ "vehicle_idx": int, "position": int, "driver": str, "team": str, "color": str, "lap": int }
```

This is updated every telemetry tick from LAP_DATA packets. `vehicle_idx == 0` for some player index — engine stores `self._player_vehicle_idx` (verify in Step 1 of Task 3).

Also available: `state["telemetry"]["position"]` (player position as string).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `core/rivals/__init__.py` | Create | Export `RivalTracker` |
| `core/rivals/models.py` | Create | `RivalSnapshot`, `RivalProfile` dataclasses |
| `core/rivals/tracker.py` | Create | `RivalTracker.update(grid, player_position)`, `get_state()` |
| `tests/test_rivals.py` | Create | All rival tests (14 tests) |
| `core/engine.py` | Modify | Instantiate tracker, call update each tick, add `state["rivals"]` |
| `NewSpotterUI/lib/api.ts` | Modify | `RivalEntry` type + `rivals?` field in `SpotterState` |
| `NewSpotterUI/components/spotter/views/dashboard.tsx` | Modify | "Соперники" panel |

---

## Task 1: Models

**Files:**
- Create: `core/rivals/__init__.py`
- Create: `core/rivals/models.py`
- Test: `tests/test_rivals.py` (first 2 tests)

- [ ] **Step 1: Create `core/rivals/__init__.py`**

```python
from core.rivals.tracker import RivalTracker

__all__ = ["RivalTracker"]
```

- [ ] **Step 2: Create `core/rivals/models.py`**

```python
"""
core/rivals/models.py
======================
Data types for the Rival Intelligence layer.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RivalSnapshot:
    vehicle_idx: int
    driver: str
    team: str
    position: int
    lap: int


@dataclass
class RivalProfile:
    vehicle_idx: int
    driver: str
    team: str
    pit_count: int
    lap_count: int
    current_position: int
    style: str                          # "consistent"|"aggressive"|"charging"|"fading"
    nearby: bool                        # within ±3 positions of player
    position_history: deque = field(default_factory=lambda: deque(maxlen=10))
```

- [ ] **Step 3: Create `tests/test_rivals.py` (first 2 model tests)**

```python
"""tests/test_rivals.py — Rival Intelligence unit tests."""
from core.rivals.models import RivalSnapshot, RivalProfile


def test_rival_snapshot_fields():
    snap = RivalSnapshot(
        vehicle_idx=3,
        driver="Carlos Sainz",
        team="Ferrari",
        position=5,
        lap=20,
    )
    assert snap.vehicle_idx == 3
    assert snap.driver == "Carlos Sainz"
    assert snap.position == 5


def test_rival_profile_fields():
    profile = RivalProfile(
        vehicle_idx=3,
        driver="Carlos Sainz",
        team="Ferrari",
        pit_count=1,
        lap_count=20,
        current_position=5,
        style="consistent",
        nearby=True,
    )
    assert profile.pit_count == 1
    assert profile.style == "consistent"
    assert profile.nearby is True
```

- [ ] **Step 4: Run model tests**

```
py -3.12 -m pytest tests/test_rivals.py::test_rival_snapshot_fields tests/test_rivals.py::test_rival_profile_fields -v
```
Expected: 2 passed.

---

## Task 2: Tracker

**Files:**
- Create: `core/rivals/tracker.py`
- Modify: `tests/test_rivals.py` (append 12 tests)

- [ ] **Step 1: Append tracker tests to `tests/test_rivals.py`**

```python
from core.rivals.tracker import RivalTracker


def _grid(*entries) -> list[dict]:
    """Build a grid list from (vehicle_idx, position, lap, driver) tuples."""
    return [
        {"vehicle_idx": vi, "position": pos, "lap": lap,
         "driver": drv, "team": "Team", "color": "#fff"}
        for vi, pos, lap, drv in entries
    ]


# --- basic update ---

def test_tracker_registers_rivals():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"), (2, 3, 1, "Leclerc"))
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    assert state["rival_count"] == 2   # player excluded
    names = [r["driver"] for r in state["rivals"]]
    assert "Sainz" in names
    assert "Leclerc" in names


def test_tracker_player_excluded():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 3, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    assert all(r["driver"] != "Player" for r in state["rivals"])


def test_tracker_nearby_flag():
    t = RivalTracker()
    # Player P5, Sainz P4, Leclerc P10
    grid = _grid((0, 5, 3, "Player"), (1, 4, 3, "Sainz"), (2, 10, 3, "Leclerc"))
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    leclerc = next(r for r in state["rivals"] if r["driver"] == "Leclerc")
    assert sainz["nearby"] is True    # P4 is within ±3 of P5
    assert leclerc["nearby"] is False  # P10 is 5 places away


def test_nearby_count():
    t = RivalTracker()
    grid = _grid(
        (0, 5, 3, "Player"),
        (1, 4, 3, "A"),
        (2, 6, 3, "B"),
        (3, 3, 3, "C"),
        (4, 10, 3, "D"),
    )
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    assert state["nearby_count"] == 3   # A(P4), B(P6), C(P3) all ±3


# --- pit detection ---

def test_pit_detected_on_large_position_drop():
    t = RivalTracker()
    # Tick 1: Sainz P3
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz")), player_vehicle_idx=0)
    # Tick 2: Sainz P18 (pitted)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz")), player_vehicle_idx=0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 1


def test_pit_not_detected_on_small_position_change():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz")), player_vehicle_idx=0)
    t.update(_grid((0, 1, 6, "Player"), (1, 5, 6, "Sainz")), player_vehicle_idx=0)  # +2 only
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 0


def test_pit_count_increments():
    t = RivalTracker()
    grid1 = _grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz"))
    grid2 = _grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz"))  # pit 1
    grid3 = _grid((0, 1, 6, "Player"), (1, 8, 7, "Sainz"))   # recovering
    grid4 = _grid((0, 1, 7, "Player"), (1, 3, 7, "Sainz"))   # back
    grid5 = _grid((0, 1, 8, "Player"), (1, 19, 8, "Sainz"))  # pit 2
    for g in [grid1, grid2, grid3, grid4, grid5]:
        t.update(g, player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 2


# --- style classification ---

def test_style_consistent_on_stable_positions():
    t = RivalTracker()
    for lap in range(1, 8):
        t.update(_grid((0, 5, lap, "Player"), (1, 3, lap, "Sainz")), player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["style"] == "consistent"


def test_style_charging_when_position_improves():
    t = RivalTracker()
    for pos in [15, 13, 11, 9, 7, 5]:
        lap = 15 - pos + 1
        t.update(_grid((0, 1, lap, "Player"), (1, pos, lap, "Sainz")), player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["style"] in ("charging", "aggressive")


def test_style_fading_when_position_worsens():
    t = RivalTracker()
    for pos in [3, 5, 7, 9, 11, 13]:
        lap = pos - 2
        t.update(_grid((0, 1, lap, "Player"), (1, pos, lap, "Sainz")), player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["style"] in ("fading", "aggressive")


# --- get_state contract ---

def test_get_state_has_all_keys():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0)
    state = t.get_state()
    for key in ("rivals", "rival_count", "nearby_count"):
        assert key in state


def test_rival_entry_has_all_fields():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0)
    rival = t.get_state()["rivals"][0]
    for key in ("driver", "team", "position", "lap", "pit_count", "style", "nearby"):
        assert key in rival
```

Run to verify FAIL:
```
py -3.12 -m pytest tests/test_rivals.py -v -k "tracker"
```
Expected: ImportError on `RivalTracker`

- [ ] **Step 2: Create `core/rivals/tracker.py`**

```python
"""
core/rivals/tracker.py
=======================
RivalTracker: per-tick rival position monitoring, pit detection,
style classification. Deterministic, no LLM, <0.5 ms per tick.
"""
from __future__ import annotations

from collections import deque
from statistics import mean, stdev

from core.rivals.models import RivalProfile, RivalSnapshot

_NEARBY_WINDOW = 3          # positions ±N = nearby
_PIT_DROP_THRESHOLD = 8     # position jump >= this = suspected pit
_MIN_HISTORY_STYLE = 4      # need at least N ticks for style judgment
_STYLE_VARIANCE_HIGH = 4.0  # std dev threshold for "aggressive"
_STYLE_TREND_THRESHOLD = 2  # avg delta > this magnitude = charging/fading


class RivalTracker:
    """Stateful per-session rival tracker. Call update() each telemetry tick."""

    def __init__(self) -> None:
        self._profiles: dict[int, RivalProfile] = {}   # vehicle_idx → profile
        self._player_position: int = 0

    def update(self, grid: list[dict], player_vehicle_idx: int) -> None:
        player_pos = 0
        for entry in grid:
            if entry["vehicle_idx"] == player_vehicle_idx:
                player_pos = entry["position"]
                break
        self._player_position = player_pos

        for entry in grid:
            vi = entry["vehicle_idx"]
            if vi == player_vehicle_idx:
                continue
            pos = entry.get("position", 0)
            lap = entry.get("lap", 0)
            driver = entry.get("driver", f"Car #{vi}")
            team = entry.get("team", "—")

            if vi not in self._profiles:
                self._profiles[vi] = RivalProfile(
                    vehicle_idx=vi,
                    driver=driver,
                    team=team,
                    pit_count=0,
                    lap_count=lap,
                    current_position=pos,
                    style="consistent",
                    nearby=False,
                )

            profile = self._profiles[vi]
            # Update name/team (may arrive empty early on)
            if driver and driver != f"Car #{vi}":
                profile.driver = driver
                profile.team = team

            prev_pos = profile.current_position
            profile.current_position = pos
            profile.lap_count = lap
            profile.nearby = player_pos > 0 and abs(pos - player_pos) <= _NEARBY_WINDOW

            if pos > 0:
                profile.position_history.append(pos)

            # Pit detection: position jumped UP by threshold (higher number = worse)
            if prev_pos > 0 and pos > 0 and pos - prev_pos >= _PIT_DROP_THRESHOLD:
                profile.pit_count += 1

            profile.style = _classify_style(profile.position_history)

    def get_state(self) -> dict:
        rivals = [
            {
                "driver": p.driver,
                "team": p.team,
                "position": p.current_position,
                "lap": p.lap_count,
                "pit_count": p.pit_count,
                "style": p.style,
                "nearby": p.nearby,
            }
            for p in sorted(self._profiles.values(), key=lambda x: x.current_position)
        ]
        nearby_count = sum(1 for r in rivals if r["nearby"])
        return {
            "rivals": rivals,
            "rival_count": len(rivals),
            "nearby_count": nearby_count,
        }


def _classify_style(history: deque) -> str:
    positions = [p for p in history if p > 0]
    if len(positions) < _MIN_HISTORY_STYLE:
        return "consistent"
    try:
        sd = stdev(positions)
    except Exception:
        sd = 0.0
    if sd >= _STYLE_VARIANCE_HIGH:
        return "aggressive"
    if len(positions) >= 2:
        deltas = [positions[i] - positions[i - 1] for i in range(1, len(positions))]
        avg_delta = mean(deltas)
        if avg_delta <= -_STYLE_TREND_THRESHOLD:
            return "charging"
        if avg_delta >= _STYLE_TREND_THRESHOLD:
            return "fading"
    return "consistent"
```

- [ ] **Step 3: Run all rival tests**

```
py -3.12 -m pytest tests/test_rivals.py -v
```
Expected: **14 passed**.

- [ ] **Step 4: Run full suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: all passed (no failures).

---

## Task 3: Engine Integration

**Files:**
- Modify: `core/engine.py`

- [ ] **Step 1: Find the player vehicle index attribute**

Search `core/engine.py` for how it identifies the player car. Common patterns:
- `self._player_vehicle_idx`
- `self.player_car_index`
- `self._player_idx`
- Or it may use `state["telemetry"]["position"]`

Read the engine's `__init__` and the LAP_DATA handler (`_update_telemetry`) to find the exact attribute name. The lap data uses `player_lap` extraction which compares against some index.

- [ ] **Step 2: Add import**

Find `from core.coach_ai import DriverCoach`. Add immediately after:
```python
from core.rivals import RivalTracker
```

- [ ] **Step 3: Instantiate `RivalTracker` in `Engine.__init__`**

Find `self.driver_coach = DriverCoach()`. Add immediately after:
```python
        self.rival_tracker = RivalTracker()
```

- [ ] **Step 4: Add `rivals` to initial state**

Find the `"coach_ai"` initial state dict. Add immediately after it:
```python
            "rivals": {
                "rivals": [],
                "rival_count": 0,
                "nearby_count": 0,
            },
```

- [ ] **Step 5: Call `rival_tracker.update()` each tick**

Find where `state["race"]["grid"]` is updated (inside `_update_telemetry`, inside the `if any(v > 0 for v in positions.values()):` guard, after `self.state["race"] = {...}` update).

Add right after the grid update:
```python
                    self.rival_tracker.update(
                        self.state["race"]["grid"],
                        player_vehicle_idx=self._player_vehicle_idx,
                    )
```

If the attribute is named differently (found in Step 1), use the correct name.

- [ ] **Step 6: Update `state["rivals"]` in `_maybe_snapshot()`**

Find `self.state["coach_ai"] = self.driver_coach.get_state()`. Add after:
```python
            self.state["rivals"] = self.rival_tracker.get_state()
```

- [ ] **Step 7: Add `get_rivals_state()` method**

Find `def get_coach_ai_state(self)`. Add after:
```python
    def get_rivals_state(self) -> dict:
        with self.state_lock:
            return dict(self.state.get("rivals", {}))
```

- [ ] **Step 8: Run full test suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: all passed.

---

## Task 4: API endpoint + UI panel

**Files:**
- Modify: `web_server.py`
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/dashboard.tsx`

- [ ] **Step 1: Add `/api/rivals` endpoint to `web_server.py`**

Find `GET /api/coach-ai` endpoint. Add right after:
```python
@app.route("/api/rivals")
def api_rivals():
    return _json(engine.get_rivals_state())
```

- [ ] **Step 2: Add `RivalsState` type to `NewSpotterUI/lib/api.ts`**

After the `CoachAIState` type, add:
```typescript
export type RivalEntry = {
  driver: string
  team: string
  position: number
  lap: number
  pit_count: number
  style: string
  nearby: boolean
}

export type RivalsState = {
  rivals: RivalEntry[]
  rival_count: number
  nearby_count: number
}
```

In `SpotterState`, add after `coach_ai?: CoachAIState`:
```typescript
  coach_ai?: CoachAIState
  rivals?: RivalsState
  yandex_ok?: boolean
```

- [ ] **Step 3: Add Rivals panel to `dashboard.tsx`**

After `const coachAi = state?.coach_ai`, add:
```tsx
  const rivals = state?.rivals
```

Label maps for styles:
```tsx
  const _STYLE_LABELS: Record<string, string> = {
    consistent: "стабильный",
    aggressive:  "агрессивный",
    charging:    "↑ прогресс",
    fading:      "↓ спад",
  }
```

Insert the Rivals panel between the Coach panel and the Live Events panel:
```tsx
        <Panel label="Соперники" action={
          <span className="label-mono text-[10px] text-muted-foreground">
            {rivals?.nearby_count ? `${rivals.nearby_count} рядом` : "—"}
          </span>
        }>
          {rivals?.rivals && rivals.rivals.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {rivals.rivals
                .filter((r) => r.nearby)
                .slice(0, 4)
                .map((r) => (
                  <li key={r.driver} className="rounded-md bg-secondary/60 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-foreground">
                        P{r.position} {r.driver}
                      </span>
                      <span className="label-mono text-[9px] text-muted-foreground">
                        {_STYLE_LABELS[r.style] ?? r.style}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="text-[10px] text-muted-foreground">{r.team}</span>
                      {r.pit_count > 0 && (
                        <span className="label-mono text-[9px] text-primary">
                          PIT ×{r.pit_count}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              {rivals.rivals.filter((r) => r.nearby).length === 0 && (
                <li className="py-4 text-center text-xs text-muted-foreground">
                  Нет соперников рядом
                </li>
              )}
            </ul>
          ) : (
            <div className="flex items-center justify-center py-8">
              <p className="text-xs text-muted-foreground">Ожидание данных гонки</p>
            </div>
          )}
        </Panel>
```

- [ ] **Step 4: Build frontend**

```
pnpm -C NewSpotterUI build
```
Expected: exit 0.

- [ ] **Step 5: Run final test suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: all passed (294 + 14 = 308 tests).

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Track opponent behavior → `RivalTracker.update()` processes all rivals each tick
- ✅ Style → "consistent"|"aggressive"|"charging"|"fading" from position history
- ✅ Pit history → `pit_count` incremented on position drop ≥ 8
- ✅ Nearby rivals → `nearby` flag + `nearby_count` in state
- ✅ Commentary-ready → `rivals` state consumable by any commentator module
- ✅ Tests required → 14 tests in `test_rivals.py`
- ✅ No LLM in calculations
- ✅ Integrates through existing state (`state["race"]["grid"]`)
- ✅ No telemetry parser changes

**Note on data limitations:** Only position/lap data from the existing grid is used. Lap times and tyre data for rivals require additional UDP parsing (excluded per task2.md "DO NOT rewrite telemetry parser" rule). Style classification is therefore position-based only, which is coarser than lap-time-based analysis but requires zero parser changes.
