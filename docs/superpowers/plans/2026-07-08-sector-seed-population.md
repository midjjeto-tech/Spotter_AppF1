# SECTOR_SEED Population Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `core/openf1_seed.py::SECTOR_SEED` with real 2025-season sector times for all 24 circuits, via a reusable dev script that queries OpenF1.

**Architecture:** A standalone script (`seed_sectors.py`, repo root, not part of the shipped app) composes two already-existing lookup tables (`TRACK_ID_TO_CIRCUIT`, `TRACK_ID_TO_GP`) to get GP names without a new API call, queries `OpenF1Client` per circuit, sanity-filters results, and prints a ready-to-paste Python dict literal. The literal is then pasted into `core/openf1_seed.py` by hand, alongside a docstring update.

**Tech Stack:** Python 3.12, existing `core.openf1_client.OpenF1Client` (stdlib-only HTTP client).

**Design doc:** `docs/superpowers/specs/2026-07-08-sector-seed-population-design.md`

**Note on git:** this project is not under version control. No `git commit` steps — each task ends with a verification checkpoint instead.

---

### Task 1: Write `seed_sectors.py`

**Files:**
- Create: `seed_sectors.py` (repo root)

- [ ] **Step 1: Write the file**

```python
"""Наполняет core/openf1_seed.py::SECTOR_SEED реальными секторными эталонами
из OpenF1. Одноразовый/редко запускаемый dev-инструмент — печатает готовый
Python-литерал в stdout, вставка в openf1_seed.py вручную. Перезапустить с
другим YEAR, когда понадобится обновить сид (например, после завершения
следующего сезона). Не часть приложения — не импортируется и не вшивается в EXE."""
from __future__ import annotations

from analytics.loader import TRACK_ID_TO_GP
from core.f1_benchmark import TRACK_ID_TO_CIRCUIT
from core.openf1_client import OpenF1Client

YEAR = 2025
MAX_SECTOR_MS = 90_000   # санити-фильтр: сектор длиннее 90с — считаем мусором


def main() -> None:
    client = OpenF1Client()
    seed: dict[str, dict] = {}
    for track_id, circuit_id in sorted(TRACK_ID_TO_CIRCUIT.items()):
        gp_name = TRACK_ID_TO_GP.get(track_id, ("", ""))[1]
        session_key = client.get_session_key(YEAR, circuit_id)
        if session_key is None:
            reason = "заблокирован (live-сессия)" if client.blocked_by_live_session else "нет session_key"
            print(f"# {circuit_id}: пропущена — {reason}")
            continue
        sectors = client.get_best_sectors(session_key)
        if sectors is None:
            print(f"# {circuit_id}: пропущена — нет валидных секторов")
            continue
        if any(not (0 < ms <= MAX_SECTOR_MS) for ms in sectors.values()):
            print(f"# {circuit_id}: пропущена — санити-фильтр не пройден ({sectors})")
            continue
        seed[circuit_id] = {"year": YEAR, "event": gp_name, "sectors": sectors}

    print("\nSECTOR_SEED: dict[str, dict] = {")
    for circuit_id, entry in seed.items():
        print(f'    "{circuit_id}": {entry!r},')
    print("}")
    print(f"\n# Итого: {len(seed)}/{len(TRACK_ID_TO_CIRCUIT)} трасс")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-check the file parses and imports resolve**

Run: `py -3.12 -c "import ast; ast.parse(open('seed_sectors.py', encoding='utf-8').read())"`
Expected: no output, exit code 0 (confirms valid Python syntax before making a network call)

- [ ] **Step 3: Checkpoint**

Confirm `seed_sectors.py` exists at repo root and parses cleanly. No git commit needed (project has no git repo). Move to Task 2.

---

### Task 2: Run the script and populate `SECTOR_SEED`

**Files:**
- Modify: `core/openf1_seed.py`

- [ ] **Step 1: Run the script**

Run: `py -3.12 seed_sectors.py`

Expected: after ~1.5-2 minutes (OpenF1 client rate-limits itself to 1 request per 2s, ~48 requests total for 24 circuits × 2 endpoints), stdout shows:
- Zero or more `# <circuit_id>: пропущена — <reason>` lines for circuits OpenF1 couldn't resolve (not a failure — see design doc "Отсутствующие трассы — не ошибка")
- A `SECTOR_SEED: dict[str, dict] = {...}` block with one `"<circuit_id>": {...}` entry per successfully-resolved circuit
- A final `# Итого: N/24 трасс` line

If the very first few circuits all print "заблокирован (live-сессия)" — OpenF1 is currently blocked by a live F1 session; stop and report this rather than proceeding with an empty result (retry later, this is not something to work around in code).

- [ ] **Step 2: Read the current `core/openf1_seed.py`**

Read the file to get its exact current content (needed before editing — the docstring header is prose that must be edited by hand, not templated).

- [ ] **Step 3: Replace the `SECTOR_SEED` dict**

Replace the current line:

```python
SECTOR_SEED: dict[str, dict] = {
    # "monza": {"year": 2024, "event": "Italian Grand Prix",
    #           "sectors": {1: 26500, 2: 38657, 3: 25900}},
}
```

with the exact `SECTOR_SEED = {...}` block the script printed to stdout in Step 1 (paste it verbatim — do not hand-edit the values).

- [ ] **Step 4: Update the module docstring**

Replace the paragraph starting with `СТАТУС (2026-07-04): практически ПУСТОЙ...` (the whole paragraph, through `...секторный HUD останется скрытым, как и раньше).`) with:

```
СТАТУС (обновить датой реального запуска): наполнено по сезону {YEAR} —
{N}/24 трасс покрыто (см. вывод seed_sectors.py при последнем запуске для
списка пропущенных, если N < 24). Обновить: перезапустить `seed_sectors.py`
с новым `YEAR` и вставить свежий вывод сюда — например, после завершения
сезона 2026 (первый год новой регламентной эры, см.
core/f1_benchmark.py::_NEW_ERA_START_YEAR). Отсутствие записи для трассы —
не баг, штатное "пока нет данных" (core/f1_benchmark.py::_load_sectors просто
не найдёт сид, секторный HUD останется скрытым, как и раньше).
```

Fill in the actual date, `{YEAR}` (2025, per Task 1's script), and `{N}` (the real count from the script's `# Итого:` line) — do not leave template placeholders in the file.

- [ ] **Step 5: Checkpoint**

Confirm `core/openf1_seed.py` has real entries (not the old commented-out example) and an accurate docstring. No git commit needed (project has no git repo). Move to Task 3.

---

### Task 3: Verify no regressions

**Files:**
- No files modified — verification only

- [ ] **Step 1: Run the benchmark test file**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -v`
Expected: all PASS (these tests exercise `_load_sectors`/`SECTOR_SEED` consumption — confirms the new dict's shape, e.g. `{"year": int, "event": str, "sectors": {1: ms, 2: ms, 3: ms}}`, is exactly what the existing code expects)

- [ ] **Step 2: Run the full suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed, same or higher pass count than the pre-existing baseline (no test in the suite should depend on `SECTOR_SEED` being empty)

- [ ] **Step 3: Import smoke test**

Run: `py -3.12 -c "import core.openf1_seed; print(len(core.openf1_seed.SECTOR_SEED))"`
Expected: prints a number > 0 (unless OpenF1 was fully blocked during Task 2, in which case report that back rather than silently accepting 0)

- [ ] **Step 4: Add a short CONTEXT.md note**

Following this project's convention (see the "Соперники: недавняя ошибка" session entry for the format), add a short session entry near the top of `CONTEXT.md` (above the current newest session) noting: SECTOR_SEED populated from 2025 season data via new `seed_sectors.py`, N/24 circuits covered, closes "Открытые баги/задачи" #4. Update the "На чём остановились" counter to reflect this closure.

- [ ] **Step 5: Checkpoint (final)**

Confirm full suite green, `SECTOR_SEED` non-empty, `CONTEXT.md` updated. Feature complete.

---

## Plan Self-Review Notes

- **Spec coverage:** year=2025 (Task 1's `YEAR` constant), GP-name composition without a new API call (Task 1, imports from `analytics.loader`/`core.f1_benchmark`), reusable script at repo root (Task 1), stdout-literal-not-autowrite (Task 2), sanity filter (Task 1's `MAX_SECTOR_MS`), no-unit-tests (no test task for the script itself, only for the consuming code in Task 3) — all covered.
- **No placeholders:** Task 2 Step 4's docstring template has explicit instructions to fill in real values before considering the step done — not left as literal `{YEAR}`/`{N}` text in the shipped file.
- **Type consistency:** `SECTOR_SEED[circuit_id]` shape (`{"year": int, "event": str, "sectors": {1: ms, 2: ms, 3: ms}}`) matches exactly what `core/f1_benchmark.py::_load_sectors` already reads (confirmed by reading that function during design) and what `tests/test_f1_benchmark.py` already exercises.
