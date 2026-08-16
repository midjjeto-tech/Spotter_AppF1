"""
scripts/survey_track.py
========================
Промер трассы -> предложение карты, с диффом против действующей.

Зачем отдельный шаг, а не автоматическая подмена карты. По `tracks/*.json` коуч
выносит суждения о пилотаже: называет поворот и говорит, что в нём сделать
иначе. Карта, которая меняется сама после каждого заезда, означает совет,
который пилот не может ни предсказать, ни проверить, — и один смазанный круг
переписал бы разметку всей трассы. Поэтому приложение только ИЗМЕРЯЕТ
(`core/track_ai/survey.py`, пишет в `DATA_DIR/track_survey/`), а решение принимает
человек, глядя на дифф.

Что показывает дифф:
    СОВПАЛ    — поворот есть в обеих картах, доли сходятся;
    СДВИНУТ   — есть в обеих, но апекс разъехался больше допуска;
    НОВЫЙ     — промер нашёл поворот, которого в карте нет (это и есть дыры,
                из-за которых привязывается 66% круга);
    ПРОПАЛ    — в карте есть, промер не увидел. НЕ повод удалять: круг мог быть
                грязным, поворот мог пройтись без заметного бокового ускорения.

Запуск:
    python scripts/survey_track.py                 # что вообще промерено
    python scripts/survey_track.py suzuka          # дифф по трассе
    python scripts/survey_track.py suzuka --write  # записать tracks/suzuka.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.track_ai.loader import _TRACK_FILES, load_track  # noqa: E402
from core.track_ai.survey import coverage  # noqa: E402

#: Насколько апекс может разъехаться и всё ещё считаться тем же поворотом.
#: 1% круга — это 50-60 метров, то есть заметно меньше самого поворота.
MATCH_TOLERANCE = 0.010


def _survey_dir() -> Path:
    try:
        import config
        return Path(config.DATA_DIR) / "track_survey"
    except Exception:  # noqa: BLE001 — конфиг может не подняться вне приложения
        return Path(__file__).resolve().parent.parent / "track_survey"


def _load_survey(slug: str) -> dict | None:
    path = _survey_dir() / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _track_file_for(slug: str) -> str | None:
    """Имя файла карты по slug промера. Промер пишется по ИМЕНИ трассы из игры,
    карты лежат под своими короткими именами — сводим одно к другому."""
    if slug in set(_TRACK_FILES.values()):
        return slug
    for city, fname in _TRACK_FILES.items():
        if city.lower().replace(" ", "_") == slug:
            return fname
    return None


def _diff(measured: list[dict], existing) -> list[tuple[str, dict | None, object]]:
    """Пары «промер <-> карта», выровненные по ближайшему апексу."""
    rows: list[tuple[str, dict | None, object]] = []
    unused = list(existing)
    for corner in sorted(measured, key=lambda c: c["fraction"]):
        best = None
        for candidate in unused:
            apex = (candidate.start + candidate.end) / 2.0
            delta = abs(apex - corner["fraction"])
            if best is None or delta < best[0]:
                best = (delta, candidate)
        if best is not None and best[0] <= MATCH_TOLERANCE:
            rows.append(("СОВПАЛ", corner, best[1]))
            unused.remove(best[1])
        elif best is not None and best[0] <= MATCH_TOLERANCE * 3:
            rows.append(("СДВИНУТ", corner, best[1]))
            unused.remove(best[1])
        else:
            rows.append(("НОВЫЙ", corner, None))
    for leftover in unused:
        rows.append(("ПРОПАЛ", None, leftover))
    return rows


def _print_diff(slug: str, survey: dict) -> int:
    fname = _track_file_for(slug)
    track = None
    if fname:
        city = next((c for c, f in _TRACK_FILES.items() if f == fname), None)
        track = load_track(city) if city else None

    measured = survey.get("corners") or []
    existing = list(track.corners) if track else []
    print(f"Трасса : {survey.get('track_name')} ({fname or 'карты нет'})")
    print(f"Промер : круг {survey.get('lap')}, {survey.get('measured_at')}, "
          f"покрытие {float(survey.get('coverage') or 0) * 100:.0f}%")
    print(f"Поворотов: промер {len(measured)}, карта {len(existing)}")
    print()

    rows = _diff(measured, existing)
    print(f"{'статус':10s}{'промер':>10s}{'тип':>10s}{'сторона':>10s}"
          f"{'карта':>10s}")
    for status, corner, mapped in rows:
        measured_at = f"{corner['fraction']:.3f}" if corner else "—"
        kind = corner["type"] if corner else "—"
        side = corner["direction"] if corner else "—"
        if mapped is None:
            map_at = "—"
        else:
            map_at = f"{(mapped.start + mapped.end) / 2.0:.3f}"
        print(f"{status:10s}{measured_at:>10s}{kind:>10s}{side:>10s}{map_at:>10s}")

    new = sum(1 for status, _, _ in rows if status == "НОВЫЙ")
    print()
    print(f"Новых поворотов в промере: {new}")
    if new:
        print("Это и есть дыры карты — из-за них ошибка получает corner_id: null.")
    print("ПРОПАЛ ≠ «удалить»: круг мог быть грязным, а пологий поворот "
          "проходится\nбез заметного бокового ускорения.")
    return 0


def _write_map(slug: str, survey: dict) -> int:
    fname = _track_file_for(slug)
    if not fname:
        print(f"Не знаю, в какой файл писать трассу '{slug}'.")
        return 1
    path = Path(__file__).resolve().parent.parent / "tracks" / f"{fname}.json"
    measured = sorted(survey.get("corners") or [], key=lambda c: c["fraction"])
    if not measured:
        print("В промере нет поворотов — писать нечего.")
        return 1

    payload = {
        "name": survey.get("track_name") or fname,
        "length_m": int(survey.get("length_m") or 0),
        "corners": [
            {"id": i, "name": f"Turn {i}", "fraction": round(c["fraction"], 3),
             "type": c["type"], "direction": c["direction"]}
            for i, c in enumerate(measured, start=1)
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Записано: {path} ({len(measured)} поворотов)")
    print("Имена поворотов стали «Turn N» — исторические названия, если они были,"
          "\nнадо вернуть руками: промер их знать не может.")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("track", nargs="?", help="slug промера, напр. suzuka")
    parser.add_argument("--write", action="store_true",
                        help="перезаписать tracks/<трасса>.json промером")
    args = parser.parse_args()

    directory = _survey_dir()
    if not args.track:
        surveys = sorted(directory.glob("*.json")) if directory.is_dir() else []
        if not surveys:
            print(f"Промеров нет ({directory}).\n"
                  "Промер копится сам во время заезда: проедьте чистый круг —\n"
                  "файл появится после его завершения.")
            return 1
        print(f"{'трасса':16s}{'поворотов':>11s}{'покрытие':>10s}  измерено")
        for path in surveys:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                print(f"{path.stem:16s}  не читается")
                continue
            corners = data.get("corners") or []
            print(f"{path.stem:16s}{len(corners):>11d}"
                  f"{float(data.get('coverage') or 0) * 100:>9.0f}%"
                  f"  {data.get('measured_at')}")
        print("\nДифф по трассе: python scripts/survey_track.py <трасса>")
        return 0

    survey = _load_survey(args.track)
    if survey is None:
        print(f"Промера '{args.track}' нет в {directory}.")
        return 1
    if args.write:
        return _write_map(args.track, survey)
    return _print_diff(args.track, survey)


if __name__ == "__main__":
    raise SystemExit(main())
