# Карьерная статистика (кросс-трековый агрегат) — дизайн

Дата: 2026-07-08
Статус: утверждён пользователем (диалог 2026-07-08).

## Проблема

`core/career_memory.py` (design spec `2026-07-03-career-memory-design.md`) сравнивает
игрока с его собственной историей, но **только на одной и той же трассе**
(`best_ever`/`last_visit` фильтруются по `track_id`). Та же спека явно относит
«кросс-трековую агрегированную статистику прогресса» к «Вне рамок (будущее)»
(§8) — этот пункт и висел в бэклоге CONTEXT.md как «кросс-гоночная карьерная
память».

## Согласованный объём

- **Метрики:** `total_races`, `wins`, `podiums`, `avg_position` — простой
  агрегат по всей истории, без трендов/серий/разбивки по трассам (явно
  отклонено пользователем в пользу самого простого варианта).
- **`total_races`** считается по гонкам **с известным `final_position`** (не
  «все гонки вообще») — иначе разойдётся с wins/podiums/avg, которые физически
  не могут быть посчитаны по гонкам без результата.
- **`podiums`** включает победы (`final_position <= 3`), как принято в F1-
  статистике («N побед, из них M подиумов» — победа тоже подиум).
- **Источник:** `analytics/archive.py::list_game_sessions()` — лёгкая сводка
  уже содержит `session_type`/`final_position` без загрузки полного JSON
  каждой сессии. Дополнительного I/O не требуется.
- **Не класс, а чистая функция.** В отличие от `CareerMemory` (стейтфул,
  live-обновление каждый круг во время гонки), карьерная статистика считается
  **один раз, в момент финиша** — состояние между вызовами не нужно.
- **Поверхности (по решению пользователя): ТОЛЬКО Post-Race Story факт +
  Voice Q&A контекст.** Никакой UI-панели, никакой отдельной голосовой
  реплики/события — сырой факт, как `weak_sector_vs_f1`/`vs_last_visit`,
  решение озвучивать ли и как принимает LLM.
- **Момент вычисления:** сразу после `finalize()` в `_generate_story` (тот же
  момент, что уже вызывает `career_memory.story_facts()`) — к этому моменту
  только что завершённая гонка уже сохранена на диск (`saved_path`), значит
  автоматически попадёт в подсчёт (без искусственного +1).
- **Офлайн-фолбэк истории (`render_fallback`) не трогаем** — он и сегодня не
  покрывает `vs_last_visit`/`weak_sector_vs_f1`, тот же принцип: только
  LLM-путь получает полный факт-лист.
- **Жизненный цикл контекстной строки:** сбрасывается на `SSTA` вместе с
  `_f1_context_line`/`_career_context_line` — тот же цикл, что у соседей, хотя
  технически данные валидны чуть дольше (до следующего финиша). Ради
  простоты/предсказуемости решено не выделять этот случай отдельно.
- **Нет данных** (архив пуст или ни одна гонка не имеет `final_position`) →
  `compute_career_stats()` возвращает `None`, факт молча отсутствует — тот же
  паттерн отказоустойчивости, что у `CareerMemory.load() -> False`.

## Дизайн

### 1. `core/career_stats.py` (новый файл)

```python
"""
core/career_stats.py
=====================
Карьерная статистика игрока — агрегат по ВСЕМ гоночным сессиям в архиве,
независимо от трассы (в отличие от core/career_memory.py, который сравнивает
только визиты на ОДНУ И ТУ ЖЕ трассу). Источник — analytics/archive.py
(DATA_DIR/game_sessions/*.json), без сети.

Чистая функция, не класс: в отличие от CareerMemory (live-обновление каждый
круг во время гонки), карьерная статистика считается ОДИН РАЗ, в момент
финиша — состояние между вызовами не нужно.
"""
from __future__ import annotations

from analytics import archive


def compute_career_stats() -> dict | None:
    """Агрегат по всем гонкам с известным final_position. None, если таких
    гонок нет (архив пуст / ни одна гонка не имеет зафиксированного
    результата) — тот же паттерн, что CareerMemory.load() -> False."""
    races = [s for s in archive.list_game_sessions()
             if s.get("session_type") == "race" and s.get("final_position") is not None]
    if not races:
        return None
    positions = [s["final_position"] for s in races]
    total = len(positions)
    return {
        "total_races": total,
        "wins": sum(1 for p in positions if p == 1),
        "podiums": sum(1 for p in positions if p <= 3),
        "avg_position": sum(positions) / total,
    }


def context_line(stats: dict) -> str:
    """Строка-сверка для контекста LLM (Voice Q&A через analytics_context,
    по аналогии с core/career_memory.py::context_line)."""
    return (f"Карьерная статистика игрока: {stats['total_races']} гонок, "
            f"{stats['wins']} побед, {stats['podiums']} подиумов, "
            f"средняя финишная позиция {stats['avg_position']:.1f}.")
```

### 2. `core/race_story.py` — новый kwarg

`RaceStoryCollector.facts()` получает `career_stats: dict | None = None`,
пробрасывается в возвращаемый словарь под тем же именем — точная копия
паттерна `weak_sector_vs_f1`/`vs_last_visit`.

### 3. `commentator/story.py::_format_facts()` — новая строка-буллет

Добавляется рядом с блоком `vs_last_visit`:

```python
    cs = facts.get("career_stats")
    if cs:
        L.append(f"- Карьера: гонка №{cs['total_races']}, побед {cs['wins']}, "
                 f"подиумов {cs['podiums']}, средняя позиция {cs['avg_position']:.1f}")
```

`render_fallback()` не меняется (см. «Согласованный объём»).

### 4. `core/engine.py` — оркестрация

В `_generate_story`, сразу после существующей строки
`vs_last_visit = self.career_memory.story_facts(final_pos, laps)["vs_last_visit"]`:

```python
        career_stats = career_stats_mod.compute_career_stats()
        facts = self.story_collector.facts(
            final_position=final_pos, laps=laps,
            coach_state=coach, leader_name=self._leader_name,
            total_laps=getattr(self, "_total_laps", None), track=track,
            weak_sector_vs_f1=weak_sector_vs_f1,
            vs_last_visit=vs_last_visit,
            career_stats=career_stats)
```

Плюс контекстная строка для Voice Q&A — сразу после `career_stats` вычислен:

```python
        self._career_stats_context_line = (
            career_stats_mod.context_line(career_stats) if career_stats else None)
        self._refresh_analytics_context()
```

`self._career_stats_context_line: str | None = None` — новый атрибут
(инициализация в `__init__`, сброс в блоке `SSTA` рядом с
`self._career_context_line = None`). `_refresh_analytics_context()` включает
его в список `parts` наравне с `_f1_context_line`/`_career_context_line`.

Импорт `core.career_stats as career_stats_mod` добавляется в блок импортов
`core/engine.py`.

## Отказоустойчивость

Чистая синхронная операция без сети/I/O сверх уже существующего
`list_game_sessions()`-скана (используется в нескольких местах проекта, тот же
профиль производительности). `compute_career_stats()` не бросает исключений на
пустом/повреждённом архиве — `list_game_sessions()` уже сам пропускает битые
файлы (см. `archive.py`). `_generate_story` уже целиком обёрнут в
`try/except` — сбой в новом коде не уронит генерацию истории, максимум
факт-строка не появится (то же поведение, что и у остальных источников
фактов в этом методе).

## Тестирование

- `tests/test_career_stats.py` (новый) — `compute_career_stats()`: пусто →
  `None`; гонки без `final_position` исключены из подсчёта; практика/квалификация
  исключены; wins/podiums/avg считаются корректно, podiums включает победы;
  `context_line()` форматирует все 4 поля.
- `tests/test_story_collector.py` — `career_stats` пробрасывается в `facts()`
  наравне с `vs_last_visit`, отсутствие (`None`) не ломает остальные факты.
- `tests/test_story_generator.py` (или где живут тесты `_format_facts`) —
  строка-буллет появляется при наличии `career_stats`, отсутствует при `None`,
  сосуществует с `vs_last_visit`/`weak_sector_vs_f1` в одном факт-листе.
- Полный `pytest` — без регрессий.
