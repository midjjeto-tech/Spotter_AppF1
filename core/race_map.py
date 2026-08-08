"""
core/race_map.py
=================
Карта гонки: позиция каждой машины по кругам — тот самый «спагетти»-график,
на котором видно, где именно потеряна гонка.

**Строится из уже разобранных позиций**, а не из отдельного пакета игры.
Пакет 15 (Lap Positions) дал бы историю ещё и ДО запуска приложения, но это
третья реконструированная раскладка в очереди на живую сверку, и работает она
только в F1 — а `lap_data` приходит и от адаптера iRacing. Выигрыш узкий, риск
общий, поэтому не берём.

Снимок делается в момент, когда линию пересекает ИГРОК. Соперники в этот момент
могут быть на другом круге — это честное «на момент твоего пересечения», и
подпись на графике должна говорить именно так, а не изображать одновременность.
"""
from __future__ import annotations

from collections.abc import Callable


class RaceMap:
    """Один экземпляр на сессию."""

    def __init__(self, player_idx: int | None = None) -> None:
        self._player_idx = player_idx
        self._laps: list[int] = []
        self._pit_laps: list[int] = []
        # vehicle_idx -> позиции по кругам; длина выравнивается по self._laps
        self._tracks: dict[int, list[int | None]] = {}

    def reset(self) -> None:
        self._laps = []
        self._pit_laps = []
        self._tracks = {}

    def set_player(self, player_idx: int | None) -> None:
        self._player_idx = player_idx

    def observe_lap(self, lap: int, positions: dict[int, int],
                    player_pit: bool = False) -> None:
        """Снимок позиций на завершении круга игроком.

        Повторный вызов с уже записанным кругом игнорируется: LAP_DATA приходит
        десятки раз в секунду, и защита должна жить здесь, а не у вызывающего."""
        if lap in self._laps or not positions:
            return
        self._laps.append(lap)
        if player_pit:
            self._pit_laps.append(lap)
        depth = len(self._laps)

        for idx, position in positions.items():
            track = self._tracks.setdefault(idx, [])
            # Машина, появившаяся позже, добивается пустотами — иначе её круги
            # разъедутся с чужими и график соврёт.
            track.extend([None] * (depth - 1 - len(track)))
            track.append(position)

        # Кто пропал (сход, вылет из пакета) — тоже выравнивается.
        for idx, track in self._tracks.items():
            if len(track) < depth:
                track.extend([None] * (depth - len(track)))

    def laps(self) -> list[int]:
        return list(self._laps)

    def pit_laps(self) -> list[int]:
        return list(self._pit_laps)

    def rows(self, name_for: Callable[[int], str | None] | None = None) -> list[dict]:
        """По строке на машину. Сортировка — по последней известной позиции,
        чтобы легенда читалась сверху вниз как финишный протокол."""
        rows = []
        for idx, track in self._tracks.items():
            rows.append({
                "vehicle_idx": idx,
                "name": (name_for(idx) if name_for else None) or None,
                "is_player": idx == self._player_idx,
                "positions": list(track),
            })
        rows.sort(key=lambda r: _last_known(r["positions"]))
        return rows

    def summary(self) -> dict | None:
        """Где именно потеряна гонка. None, если игрока в карте нет."""
        if self._player_idx is None:
            return None
        track = self._tracks.get(self._player_idx)
        if not track:
            return None
        known = [(self._laps[i], p) for i, p in enumerate(track) if p is not None]
        if not known:
            return None

        worst_lap: int | None = None
        worst_delta = 0
        for (prev_lap, prev_pos), (lap, pos) in zip(known, known[1:]):
            # Позиции, потерянные на пит-круге, — это пит-стоп, а не проигранная
            # гонка. Назвать такой круг «здесь ты потерял гонку» было бы враньём.
            if lap in self._pit_laps:
                continue
            delta = prev_pos - pos
            if delta < worst_delta:
                worst_delta = delta
                worst_lap = lap

        return {
            "start_position": known[0][1],
            "end_position": known[-1][1],
            "net": known[0][1] - known[-1][1],
            "worst_lap": worst_lap,
            "worst_delta": worst_delta if worst_lap is not None else 0,
        }

    def to_dict(self, name_for: Callable[[int], str | None] | None = None) -> dict:
        return {
            "laps": self.laps(),
            "pit_laps": self.pit_laps(),
            "rows": self.rows(name_for),
            "summary": self.summary(),
        }


def _last_known(positions: list[int | None]) -> int:
    for value in reversed(positions):
        if value is not None:
            return value
    return 99
