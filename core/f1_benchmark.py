"""
core/f1_benchmark.py
====================
Живой бенчмарк темпа игрока против ПОЛЯ текущей сессии (killer-фича #2).

ИСТОЧНИК СМЕНИЛСЯ 2026-08-08, И ЭТО НЕ КОМПРОМИСС. Раньше эталоном был
быстрейший круг реального Гран-при из Jolpica плюс секторы из OpenF1. Обе
службы разрешают только некоммерческое использование (CC BY-NC-SA 4.0, см.
NOTICE) — для продаваемой сборки это блокер. Сети здесь больше нет.

Новый эталон приходит из самой игры: пакет Session History (id 11) отдаёт по
КАЖДОЙ машине best_lap_ms и best_sector_ms (core/packets.py::
parse_session_history), движок копит их в _session_history. Берём быстрейшую
машину поля, кроме самого игрока.

Сравнение при этом стало ЧЕСТНЕЕ, а не беднее. Реальный Гран-при шёл на другой
физике, другом топливе, другой резине и другом состоянии трассы — из-за этого
приходилось таскать дисклеймер о несопоставимости и специально следить, чтобы
разница времён не читалась как оценка мастерства. Круг соперника в той же
сессии сопоставим напрямую: та же трасса, та же погода, тот же регламент.

Отличие от core/career_memory.py: там эталон СВОЙ и исторический (архив прошлых
заездов), здесь — ЧУЖОЙ и сиюминутный (поле этой сессии). Вопросы разные:
«прогрессирую ли я» против «отстаю ли я от соперников прямо сейчас». Поэтому
модули независимы и события у них разные (CAREER_PB против F1_BENCH).

Чистый юнит: хранит эталон и считает гэп. Ни сети, ни диска, ни потоков.
"""
from __future__ import annotations

import logging

from core.ru_names import decline
from core.f1_comparison_language import describe_time_difference

_log = logging.getLogger(__name__)


def _fmt_lap(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    total = ms / 1000.0
    m = int(total // 60)
    s = total - m * 60
    return f"{m}:{s:06.3f}" if m else f"{s:.1f}"


class F1Benchmark:
    def __init__(self):
        self.reference: dict | None = None

    @property
    def ready(self) -> bool:
        return self.reference is not None

    def reset(self) -> None:
        self.reference = None

    def update_from_field(self, history: dict[int, dict],
                          player_idx: int | None,
                          name_of) -> bool:
        """Пересобрать эталон из накопленной истории сессии. True — эталон
        появился или сменился.

        `history`: car_idx → результат parse_session_history.
        `name_of`: car_idx → отображаемое имя пилота (движок берёт его из
        race_state, там имя уже прошло обогащение и кириллицу).

        Машина игрока ИСКЛЮЧАЕТСЯ. Сравнивать игрока с самим собой бессмысленно
        (гэп всегда ноль), а «личный рекорд трассы» — задача career_memory.

        Круги без времени пропускаем: в session history пустой слот приходит
        нулём, и без фильтра ноль победил бы любой реальный круг.
        """
        best_idx: int | None = None
        best_ms: int | None = None
        for car_idx, entry in (history or {}).items():
            if player_idx is not None and car_idx == player_idx:
                continue
            lap_ms = (entry or {}).get("best_lap_ms")
            if not lap_ms or lap_ms <= 0:
                continue
            if best_ms is None or lap_ms < best_ms:
                best_ms, best_idx = lap_ms, car_idx

        if best_idx is None:
            return False

        # Секторы берём У ТОЙ ЖЕ машины, что дала эталонный круг, и только
        # полным набором 1/2/3. Частичный набор дал бы гэп по одному сектору и
        # молчание по двум — читается как «там ты в порядке», хотя данных
        # просто нет.
        sectors = (history[best_idx] or {}).get("best_sector_ms") or {}
        sector_ms = {n: sectors[n] for n in (1, 2, 3)} if all(
            sectors.get(n) for n in (1, 2, 3)) else None

        new_ref = {
            "driver": name_of(best_idx) or "",
            "time_ms": best_ms,
            "car_idx": best_idx,
            "sector_ms": sector_ms,
            "sectors_source": "field" if sector_ms else None,
            "source": "field",
            # Ключи контракта, оставшиеся от эталона реального Гран-при. Смысла
            # под новым источником у них нет (сессия и есть «событие»), но
            # потребители (HUD, ui_state) читают их безусловно — держим None,
            # а не выкидываем ключ.
            "event": None,
            "year": None,
        }
        if self.reference == new_ref:
            return False
        self.reference = new_ref
        return True

    def compare(self, player_laps: list[dict]) -> dict | None:
        """Гэп лучшего круга игрока к эталону. None если не готов / нет валидных кругов.
        Ключи "sectors"/"sectors_source" присутствуют ВСЕГДА (словарь/None,
        "field"|None) — контракт для HUD/Voice/Story, чтобы не делать
        hasattr-проверки у потребителей."""
        if not self.ready:
            return None
        valid = [l for l in player_laps if (l.get("last_lap_ms") or 0) > 0]
        if not valid:
            return None
        best = min(valid, key=lambda l: l["last_lap_ms"])
        ref = self.reference
        return {
            "gap_ms": best["last_lap_ms"] - ref["time_ms"],
            "player_best_ms": best["last_lap_ms"],
            "player_best_lap": best.get("lap"),
            "f1_time_ms": ref["time_ms"],
            "f1_driver": ref["driver"],
            "event": ref["event"],
            "year": ref["year"],
            "source": ref["source"],
            "sectors": self._sector_gaps(best, ref.get("sector_ms")),
            "sectors_source": ref.get("sectors_source"),
            "interpretation": describe_time_difference(
                best["last_lap_ms"] - ref["time_ms"], decimals=3),
        }

    def _sector_gaps(self, best_lap: dict, ref_sectors: dict[int, int] | None) -> dict | None:
        """Посекторный гэп ЛУЧШЕГО круга игрока (тот же круг, что дал player_best_ms)
        к эталонным секторам. None — эталонных секторов нет ИЛИ у лучшего круга
        игрока нет валидных s1/s2/s3 (не отдаём частичные/вводящие в заблуждение данные)."""
        if not ref_sectors:
            return None
        player = {1: best_lap.get("s1_ms"), 2: best_lap.get("s2_ms"), 3: best_lap.get("s3_ms")}
        if any(not player[n] for n in (1, 2, 3)):
            return None
        return {n: {"player_ms": player[n], "gap_ms": player[n] - ref_sectors[n]}
                for n in (1, 2, 3)}

    def race_weak_sector(self, player_laps: list[dict]) -> int | None:
        """Сектор с наибольшим СРЕДНИМ гэпом к эталону среди кругов гонки (для
        Post-Race Story: weak_sector_vs_f1). Не путать с coach_ai.weak_sector:
        там база сравнения — собственный лучший круг игрока, здесь — круг
        быстрейшего соперника. None — эталонных секторов нет ИЛИ ни один круг
        не дал валидных s1/s2/s3.
        Пит-круги (pit_lap=True) исключаются из усреднения — их секторные времена
        искажены пит-лейном, а не отражают реальный темп на трассе.
        При равенстве средних гэпов между секторами возвращается сектор с наименьшим
        номером (детерминированно — первый максимум в порядке 1→2→3)."""
        ref_sectors = (self.reference or {}).get("sector_ms")
        if not ref_sectors:
            return None
        totals = {1: 0, 2: 0, 3: 0}
        counts = {1: 0, 2: 0, 3: 0}
        for lap in player_laps:
            if lap.get("pit_lap"):
                continue
            for n in (1, 2, 3):
                v = lap.get(f"s{n}_ms")
                if v:
                    totals[n] += v - ref_sectors[n]
                    counts[n] += 1
        if not all(counts.values()):
            return None
        avg_gap = {n: totals[n] / counts[n] for n in (1, 2, 3)}
        return max(avg_gap, key=lambda n: avg_gap[n])

    def context_line(self, cmp: dict) -> str:
        """Строка-сверка для контекста LLM (не озвучивается напрямую).

        Проверки «а не сам ли игрок этот пилот» больше нет и не нужно: машина
        игрока исключена из поля в update_from_field, эталон всегда чужой.
        """
        drv = decline(cmp["f1_driver"], "gen") if cmp["f1_driver"] else "лидера"
        return (f"Эталон сессии — быстрейший круг {drv} {_fmt_lap(cmp['f1_time_ms'])}. "
                f"Твой лучший {_fmt_lap(cmp['player_best_ms'])}. "
                f"{describe_time_difference(cmp['gap_ms'])}")

    def pb_line(self, cmp: dict) -> str:
        """Озвучиваемая реплика на личном рекорде круга (гэп словами, без сырого
        времени круга)."""
        difference = describe_time_difference(cmp["gap_ms"])
        if not cmp["f1_driver"]:
            return f"Личный рекорд круга! {difference} Ориентир — быстрейший круг сессии."
        drv = decline(cmp["f1_driver"], "gen")
        return (f"Личный рекорд круга! {difference} "
                f"Ориентир — быстрейший круг {drv}.")

    def sector_pb_line(self, sector_n: int, sector_cmp: dict) -> str:
        """Озвучиваемая реплика на личном рекорде СЕКТОРА (не путать с pb_line — там полный круг)."""
        difference = describe_time_difference(sector_cmp["gap_ms"])
        return f"Сектор {sector_n} — твой лучший в сессии. {difference}"
