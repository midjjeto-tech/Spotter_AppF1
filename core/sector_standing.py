"""
core/sector_standing.py
========================
Где пилот в ПОЛЕ по каждому сектору — место, отрыв до лучшего и кто его держит.

Данные для этого лежали в движке с 2026-07-20 и почти не использовались:
`Session History` (пакет 11) циклически приносит лучшие секторы КАЖДОЙ из 22
машин, а читали их трое — дуэль с напарником (постфактум), эталон темпа
(`f1_benchmark`) и сравнение ровно с ОДНИМ ближайшим соперником в сводке по
разрывам (`core/strategy_ai/sector_comparison.py`, только в гонке). Поля целиком
не видел никто.

Разница между «ты на три десятых медленнее соседа» и «твой второй сектор
восемнадцатый из двадцати» — это разница между фактом и диагнозом. Первое
зависит от того, кто случайно едет рядом; второе говорит, где на самом деле
теряется круг.

**Отдельный вопрос от коуча, и намеренно.** Коуч (`core/coach_ai/`) отвечает
«где ты теряешь относительно СЕБЯ» и разбирает это до поворота и причины. Здесь
ответ на «где ты теряешь относительно НИХ», и разрешение грубее — сектор.
Смешивать их нельзя: первое лечится техникой, второе бывает и вопросом машины.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

#: Меньше машин со временем в секторе — «место в поле» не значит ничего:
#: третий из трёх и третий из двадцати это разные новости.
MIN_FIELD_CARS = 4

#: Ниже этого отрыв до лучшего в поле не считается отрывом. То же число, что
#: `num_to_words.MIN_SPOKEN_MS`: величину меньше десятой доли секунды не
#: произнести, а показывать на экране то, о чём нельзя сказать, — расхождение
#: между экраном и эфиром на ровном месте.
MIN_GAP_MS = 100


@dataclass
class SectorStanding:
    """Положение игрока в одном секторе."""
    sector: int              # 1..3
    player_ms: int
    best_ms: int
    best_holder: str | None  # None — имя ещё не приехало из метаданных
    rank: int                # 1-based, среди машин с временем в этом секторе
    field_size: int
    gap_ms: int              # player_ms - best_ms, никогда не отрицательный

    @property
    def is_best(self) -> bool:
        return self.rank == 1

    def to_dict(self) -> dict:
        return {
            "sector": self.sector, "player_ms": self.player_ms,
            "best_ms": self.best_ms, "best_holder": self.best_holder,
            "rank": self.rank, "field_size": self.field_size,
            "gap_ms": self.gap_ms,
        }


@dataclass
class FieldPace:
    """Раскладка по всем секторам, где сравнение вообще возможно."""
    sectors: list[SectorStanding]
    weakest: SectorStanding | None    # наибольший отрыв до лучшего в поле
    strongest: SectorStanding | None  # лучшее место
    lap_rank: int | None
    lap_field_size: int
    lap_gap_ms: int | None

    def to_dict(self) -> dict:
        return {
            "sectors": [s.to_dict() for s in self.sectors],
            "weakest": self.weakest.to_dict() if self.weakest else None,
            "strongest": self.strongest.to_dict() if self.strongest else None,
            "lap_rank": self.lap_rank,
            "lap_field_size": self.lap_field_size,
            "lap_gap_ms": self.lap_gap_ms,
        }


def build(history: dict[int, dict], player_idx: int,
          name_of: Callable[[int], str | None] | None = None,
          ) -> FieldPace | None:
    """Раскладка по полю, либо None — если сравнивать пока не с чем.

    `history` — кэш `Session History` по индексу машины (движок хранит его как
    есть). `name_of` может бросить или вернуть пустое: имя приезжает из
    метаданных позже телеметрии, и его отсутствие не повод терять всю раскладку.
    """
    player = history.get(player_idx)
    if not isinstance(player, dict):
        return None

    standings: list[SectorStanding] = []
    for sector in (1, 2, 3):
        standing = _sector_standing(history, player_idx, sector, name_of)
        if standing is not None:
            standings.append(standing)

    lap_rank, lap_field, lap_gap = _lap_standing(history, player_idx)
    if not standings and lap_rank is None:
        return None

    # Слабейший — по ОТРЫВУ, а не по месту: восемнадцатое место с отрывом в
    # сотую и третье место с отрывом в полсекунды требуют разного, и работать
    # надо там, где лежит время.
    weakest = max((s for s in standings if s.gap_ms >= MIN_GAP_MS),
                  key=lambda s: (s.gap_ms, -s.sector), default=None)
    strongest = min(standings, key=lambda s: (s.rank, s.gap_ms, s.sector),
                    default=None)
    return FieldPace(sectors=standings, weakest=weakest, strongest=strongest,
                     lap_rank=lap_rank, lap_field_size=lap_field,
                     lap_gap_ms=lap_gap)


def _sector_standing(history: dict[int, dict], player_idx: int, sector: int,
                     name_of: Callable[[int], str | None] | None,
                     ) -> SectorStanding | None:
    times: dict[int, int] = {}
    for car_idx, entry in history.items():
        value = _sector_ms(entry, sector)
        if value is not None:
            times[car_idx] = value

    player_ms = times.get(player_idx)
    if player_ms is None or len(times) < MIN_FIELD_CARS:
        return None

    best_idx = min(times, key=lambda idx: (times[idx], idx))
    best_ms = times[best_idx]
    # Строго быстрее: одинаковое время не отодвигает пилота назад.
    rank = 1 + sum(1 for ms in times.values() if ms < player_ms)
    return SectorStanding(
        sector=sector, player_ms=player_ms, best_ms=best_ms,
        best_holder=_safe_name(name_of, best_idx),
        rank=rank, field_size=len(times), gap_ms=max(0, player_ms - best_ms))


def _lap_standing(history: dict[int, dict], player_idx: int,
                  ) -> tuple[int | None, int, int | None]:
    times: dict[int, int] = {}
    for car_idx, entry in history.items():
        value = _positive_int(entry.get("best_lap_ms")
                              if isinstance(entry, dict) else None)
        if value is not None:
            times[car_idx] = value

    player_ms = times.get(player_idx)
    if player_ms is None or len(times) < MIN_FIELD_CARS:
        return None, len(times), None
    rank = 1 + sum(1 for ms in times.values() if ms < player_ms)
    return rank, len(times), max(0, player_ms - min(times.values()))


def _sector_ms(entry: object, sector: int) -> int | None:
    if not isinstance(entry, dict):
        return None
    best = entry.get("best_sector_ms")
    if not isinstance(best, dict):
        return None
    # Ключи из пакета — int, но тот же словарь переживает круг через JSON в
    # архиве, где они станут строками. Принимаем оба, чтобы модуль годился и
    # для разбора сохранённой сессии.
    return _positive_int(best.get(sector, best.get(str(sector))))


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if number > 0 else None


def _safe_name(name_of: Callable[[int], str | None] | None,
               car_idx: int) -> str | None:
    if name_of is None:
        return None
    try:
        name = name_of(car_idx)
    except Exception:  # noqa: BLE001 — имя не повод потерять раскладку
        return None
    name = (name or "").strip()
    return name or None
