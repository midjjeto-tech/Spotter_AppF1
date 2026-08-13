"""
scripts/audit_tracks.py
========================
Полнота карт трасс: сколько круга коуч вообще способен привязать к повороту.

Зачем. Коуч называет поворот и причину, но привязать ошибку он может только
там, где в `tracks/*.json` есть поворот. Разбор живого заезда 2026-08-11
(Майами) показал, чем оборачивается неполная карта: шесть из семи ошибок заезда
получили `corner_id: null` и `phase: "straight"`, а следом `occurrences: 0` у
каждой потери и `cause: null` у двух главных. Снаружи это выглядит как «коуч
ничего не понял», хотя понимать ему было нечем.

Дыра в карте — НЕ всегда дефект: у Монцы пятая часть круга это настоящая
прямая. Поэтому скрипт ничего не чинит и ничего не предлагает дописать, он
только показывает, где смотреть. Доли поворотов брать неоткуда, кроме
измерения по своей телеметрии: выдумывать их нельзя — по этой карте коуч потом
выносит суждения о пилотаже.

Запуск:
    python scripts/audit_tracks.py            # таблица по всем трассам
    python scripts/audit_tracks.py --csv      # то же в CSV
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.track_ai.corners import (  # noqa: E402
    BRAKING_OFFSET, braking_offset_for, get_corner,
)
from core.track_ai.loader import _TRACK_FILES, load_track  # noqa: E402

#: Шаг обхода круга при замере покрытия. 2000 точек — это 2-3 метра на трассу,
#: мельче не нужно: границы поворотов заданы с точностью до тысячных доли круга.
SAMPLES = 2000


def _rows() -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for city, fname in _TRACK_FILES.items():
        if fname in seen:
            continue
        seen.add(fname)
        track = load_track(city)
        if track is None:
            out.append({"track": fname, "error": "не загружается"})
            continue
        corners = sorted(track.corners, key=lambda c: c.start)
        offset = braking_offset_for(track.length_m)

        attributed = sum(
            1 for i in range(SAMPLES)
            if get_corner(i / SAMPLES, track.corners, offset) is not None)
        legacy = sum(
            1 for i in range(SAMPLES)
            if get_corner(i / SAMPLES, track.corners, BRAKING_OFFSET) is not None)

        # Крупнейший участок круга без поворота (сам поворот, без торможения).
        gaps: list[float] = []
        prev_end = corners[-1].end - 1.0 if corners else 0.0
        for corner in corners:
            if corner.start > prev_end:
                gaps.append(corner.start - prev_end)
            prev_end = max(prev_end, corner.end)
        if corners:
            gaps.append(1.0 + corners[0].start - prev_end)

        out.append({
            "track": fname,
            "length_m": track.length_m,
            "corners": len(corners),
            "attributed": attributed / SAMPLES,
            "legacy": legacy / SAMPLES,
            "biggest_gap": max(gaps, default=0.0),
        })
    out.sort(key=lambda r: r.get("attributed", 1.0))
    return out


def main() -> int:
    # Консоль Windows по умолчанию не в UTF-8, и весь вывод ниже превратился бы
    # в кракозябры. В этом проекте на кодировке уже горели дважды — см.
    # CONTEXT.md про вынос Piper в отдельный процесс.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", action="store_true", help="вывод в CSV")
    args = parser.parse_args()

    rows = _rows()
    broken = [r for r in rows if r.get("error")]

    if args.csv:
        print("track,length_m,corners,attributed_pct,biggest_gap_pct,biggest_gap_m")
        for r in rows:
            if r.get("error"):
                continue
            print(f'{r["track"]},{r["length_m"]:.0f},{r["corners"]},'
                  f'{r["attributed"] * 100:.1f},{r["biggest_gap"] * 100:.1f},'
                  f'{r["biggest_gap"] * r["length_m"]:.0f}')
    else:
        print(f"{'трасса':<14}{'длина':>7}{'пов.':>6}{'привязка':>10}"
              f"{'макс. дыра':>13}")
        for r in rows:
            if r.get("error"):
                print(f'{r["track"]:<14}  {r["error"]}')
                continue
            gap_m = r["biggest_gap"] * r["length_m"]
            print(f'{r["track"]:<14}{r["length_m"]:>7.0f}{r["corners"]:>6}'
                  f'{r["attributed"] * 100:>9.0f}%'
                  f'{r["biggest_gap"] * 100:>8.0f}% / {gap_m:>4.0f} м')
        good = [r for r in rows if not r.get("error")]
        if good:
            avg = sum(r["attributed"] for r in good) / len(good)
            print(f"\nв среднем привязывается {avg * 100:.0f}% круга")
            print("дыра — не всегда дефект: у Монцы это настоящая прямая. "
                  "Доли поворотов берутся только измерением по своей\n"
                  "телеметрии, выдумывать их нельзя — по этой карте коуч "
                  "судит о пилотаже.")

    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
