"""
tools/coach_funnel.py
======================
Воронка коуча по архиву: от найденного срыва до произнесённого урока.

    ЗАПУСК (из корня проекта):

        .venv\\Scripts\\python.exe tools/coach_funnel.py

Зачем это есть. «Коуч молчит» — не одно состояние, а пять разных, и по самому
молчанию они неотличимы: детектор ничего не нашёл; нашёл, но не смог назвать
место; назвал, но ошибка не повторилась; повторилась, но другим видом; всё
сошлось, а тумблер выключен. Лечатся они по-разному, и выбирать лечение надо
по числам, а не по ощущению.

Считается по `game_sessions/*.json`: в каждом заезде лежит `coach_map` —
фактический выход детектора. Архив копился месяцами и включает заезды,
записанные ДО двух нынешних гейтов (`MIN_MOVING_KMH`, `MAX_EVENT_DURATION_S`),
поэтому строки сначала прогоняются через правила СЕГОДНЯШНЕГО детектора —
иначе воронка описывала бы приложение, которого больше нет.

Чего инструмент НЕ умеет и уметь не может: сказать, не завышены ли пороги
ОБНАРУЖЕНИЯ. В архив попадает только то, что детектор нашёл; сколько раз
сигнал не дотянул до порога, здесь не видно ни при каких вычислениях. На этот
вопрос отвечает полевой журнал (`core/field_log.py::observe` → отчёт
`tools/diagnose.py`, строка «порог взят N раз») — то есть один заезд с
`SPOTTER_DIAG=1`, а не ещё один проход по архиву.
"""
from __future__ import annotations

import argparse
import collections
import glob
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.coach_ai import slip  # noqa: E402
from core.coach_ai.diagnosis import MIN_MISTAKE_OCCURRENCES  # noqa: E402

#: Скорость, ниже которой «прямая» в разметке — почти наверняка дыра в карте, а
#: не настоящая прямая. Самый медленный поворот календаря проходится примерно
#: на 45–50 км/ч, и на прямой машина столько не едет нигде, кроме выезда из
#: боксов. Порог намеренно щедрый: он служит доводом, а не фильтром.
CORNER_SPEED_CEILING_KMH = 140.0


def _load(pattern: str) -> tuple[list[dict], int, int]:
    rows: list[dict] = []
    laps = races = 0
    for path in sorted(glob.glob(pattern)):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        races += 1
        laps += data.get("total_laps_completed") or 0
        for row in (data.get("coach_map") or []):
            row["_track"] = data.get("track_name") or "?"
            rows.append(row)
    return rows, laps, races


def _passes_current_gates(row: dict) -> tuple[bool, str]:
    """Прошла бы эта строка сегодняшний детектор.

    Гейты применяются в том же порядке и по тем же константам, что в
    `core/coach_ai/slip.py` — импортом, а не копией числа: разойтись они не
    могут по построению.
    """
    speed = row.get("speed_kmh")
    if speed is not None and float(speed) < slip.MIN_MOVING_KMH:
        return False, f"машина стоит (<{slip.MIN_MOVING_KMH:g} км/ч)"
    duration = float(row.get("duration_s") or 0.0)
    if duration > slip.MAX_EVENT_DURATION_S:
        return False, f"длиннее {slip.MAX_EVENT_DURATION_S:g} с"
    if duration < slip.MIN_EVENT_DURATION_S:
        return False, f"короче {slip.MIN_EVENT_DURATION_S:g} с"
    return True, ""


def report(pattern: str) -> list[str]:
    rows, laps, races = _load(pattern)
    out = [f"АРХИВ: {races} заездов, {laps} кругов, {len(rows)} срывов в картах"]
    if not rows:
        out.append("  (пусто — считать нечего)")
        return out

    kept, dropped = [], collections.Counter()
    for row in rows:
        ok, why = _passes_current_gates(row)
        kept.append(row) if ok else dropped.update([why])
    for why, count in dropped.most_common():
        out.append(f"  −{count:>3}  {why}")
    rate = len(kept) / laps if laps else 0.0
    out.append(f"  ={len(kept):>3}  прошли бы сегодняшний детектор "
               f"({rate:.2f} на круг)")

    with_corner = [r for r in kept if r.get("corner_id") is not None]
    groups = collections.Counter(
        (r["_track"], r["corner_id"], r["kind"]) for r in with_corner)
    lessons = sum(1 for c in groups.values() if c >= MIN_MISTAKE_OCCURRENCES)

    out += ["", "ВОРОНКА ДО УРОКА"]
    out.append(f"  срывов                              {len(kept):>3}")
    out.append(f"  с привязкой к повороту              {len(with_corner):>3}"
               f"  ({100 * len(with_corner) // max(len(kept), 1)}%)")
    out.append(f"  групп (трасса + поворот + вид)      {len(groups):>3}")
    sizes = dict(sorted(collections.Counter(groups.values()).items()))
    out.append(f"  размеры групп                       {sizes}")
    out.append(f"  прошло порог повтора ({MIN_MISTAKE_OCCURRENCES})             "
               f"{lessons:>3}   <- столько уроков могло прозвучать")

    out += ["", "ЧТО ИЗМЕНИЛИ БЫ ДРУГИЕ ПРАВИЛА ГРУППИРОВКИ"]
    for threshold in (2, 3):
        n = sum(1 for c in groups.values() if c >= threshold)
        mark = "  (сейчас)" if threshold == MIN_MISTAKE_OCCURRENCES else ""
        out.append(f"  тот же вид, порог {threshold}:            {n:>3} уроков{mark}")
    per_corner = collections.Counter(
        (r["_track"], r["corner_id"]) for r in with_corner)
    by_corner = sum(1 for c in per_corner.values()
                    if c >= MIN_MISTAKE_OCCURRENCES)
    out.append(f"  любой вид в одном повороте, порог {MIN_MISTAKE_OCCURRENCES}: "
               f"{by_corner:>3} уроков")
    for key, count in per_corner.items():
        if count >= MIN_MISTAKE_OCCURRENCES:
            kinds = ", ".join(f"{g[2]}x{n}" for g, n in groups.items()
                              if (g[0], g[1]) == key)
            out.append(f"      {key[0]}, поворот {key[1]}: {count} — {kinds}")

    # Привязка теряется там, где карта не знает поворота. Довод — скорость:
    # «прямая» на 76 км/ч прямой не бывает.
    no_corner = [r for r in kept if r.get("corner_id") is None]
    suspicious = [r for r in no_corner
                  if float(r.get("speed_kmh") or 0.0) <= CORNER_SPEED_CEILING_KMH]
    out += ["", "БЕЗ ПРИВЯЗКИ: дыра в карте или настоящая прямая"]
    out.append(f"  всего без поворота                  {len(no_corner):>3}")
    out.append(f"  из них на скорости <= {CORNER_SPEED_CEILING_KMH:g} км/ч   "
               f"{len(suspicious):>3}   <- на прямой так не едут")
    for track, count in collections.Counter(
            r["_track"] for r in suspicious).most_common():
        out.append(f"      {track}: {count}  → промерить круг "
                   f"(`scripts/survey_track.py`)")

    out += ["", "ЧЕГО ЭТОТ СЧЁТ НЕ ВИДИТ",
            "  Сколько раз сигнал НЕ ДОТЯНУЛ до порога обнаружения — в архив",
            "  попадает только найденное. Это меряет полевой журнал:",
            "  один заезд с SPOTTER_DIAG=1, затем tools/diagnose.py."]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[3])
    parser.add_argument("--sessions", default="game_sessions/*.json",
                        help="маска файлов заездов")
    args = parser.parse_args(argv)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("\n".join(report(args.sessions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
