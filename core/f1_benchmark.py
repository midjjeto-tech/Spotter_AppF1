"""
core/f1_benchmark.py
====================
Живой бенчмарк темпа игрока против РЕАЛЬНОГО F1 (killer-фича #2).

Эталон — быстрейший круг реального GP этой трассы из Jolpica (фолбэк — поул).
Сравнение по ВРЕМЕНИ КРУГА (Ergast не отдаёт сектора). Секторный эталон — ОТДЕЛЬНО,
из OpenF1 («лучшие секторы гонки», не привязаны к тому же пилоту/кругу, что и
полный-круга-эталон — см. design spec docs/superpowers/specs/2026-07-02-f1-sector-benchmark-design.md).
Чистый юнит: хранит эталон и считает гэп; сеть только в `load` (engine зовёт её в фоновом потоке).

Ergast отдаёт ЛАТИНСКИЕ фамилии — мапим в кириллицу (core.transliterate.KNOWN_SURNAMES)
перед склонением через core.ru_names, иначе TTS произнесёт латиницу и без падежа.
"""
from __future__ import annotations

import logging

from analytics.loader import TRACK_ID_TO_GP
from core import transliterate
from core.ergast_client import JolpicaClient
from core.openf1_seed import SECTOR_SEED
from core.ru_names import decline, surname_of
from core.f1_comparison_language import (
    COMPARISON_DISCLAIMER,
    SHORT_COMPARISON_DISCLAIMER,
    describe_time_difference,
)

_log = logging.getLogger(__name__)

# track_id (m_trackId, фиксированный enum игры — см. analytics/loader.TRACK_ID_TO_GP)
# → ergast circuitId. Только текущий календарь; legacy-трассы (Paul Ricard/Hockenheim/
# Sochi/Hanoi/short-варианты) сюда не включены — load() для них корректно вернёт False.
TRACK_ID_TO_CIRCUIT: dict[int, str] = {
    0: "albert_park", 2: "shanghai", 3: "bahrain", 4: "catalunya", 5: "monaco",
    6: "villeneuve", 7: "silverstone", 9: "hungaroring", 10: "spa", 11: "monza",
    12: "marina_bay", 13: "suzuka", 14: "yas_marina", 15: "americas",
    16: "interlagos", 17: "red_bull_ring", 19: "rodriguez", 20: "baku",
    26: "zandvoort", 27: "imola", 29: "jeddah", 30: "miami", 31: "vegas",
    32: "losail",
}

# Первый год нового регламентного цикла (2026: -30% прижимной силы, -55%
# сопротивления, без DRS — принципиально другая машина). Эталон трассы НЕ
# должен откатываться на год из другой эры (см. load()) — иначе гэп игрока
# сравнивается с физически несопоставимым временем круга. При объявлении
# следующего сброса регламента — обновить эту константу.
_NEW_ERA_START_YEAR = 2026


def _ru_driver(latin: str | None) -> str:
    if not latin:
        return ""
    return transliterate.known_surname(latin) or transliterate.to_cyrillic(latin)


def _fmt_lap(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    total = ms / 1000.0
    m = int(total // 60)
    s = total - m * 60
    return f"{m}:{s:06.3f}" if m else f"{s:.1f}"


class F1Benchmark:
    def __init__(self, client=None, openf1_client=None):
        self._client = client
        self._openf1_client = openf1_client
        self.reference: dict | None = None

    @property
    def _c(self):
        if self._client is None:
            self._client = JolpicaClient()
        return self._client

    @property
    def _openf1(self):
        if self._openf1_client is None:
            from core.openf1_client import OpenF1Client
            self._openf1_client = OpenF1Client()
        return self._openf1_client

    @property
    def ready(self) -> bool:
        return self.reference is not None

    def reset(self) -> None:
        self.reference = None

    def load(self, track_id: int, year: int) -> bool:
        """Загрузить эталон трассы: fastest lap (year, year-1), иначе поул. True если найден.
        Дополнительно (не критично для основного результата) тянет секторный эталон
        из OpenF1 — сбой не влияет на возврат True/False (см. _load_sectors)."""
        circuit = TRACK_ID_TO_CIRCUIT.get(track_id)
        if not circuit:
            return False
        event = TRACK_ID_TO_GP.get(track_id, ("", ""))[1]
        years = [year]
        # year-1 фолбэк (для трасс, ещё не прошедших в текущем сезоне) — только
        # внутри той же регламентной эры. 2026 никогда не откатывается на 2025:
        # другой регламент делает время круга физически несопоставимым.
        prev_same_era = (year - 1 >= _NEW_ERA_START_YEAR) == (year >= _NEW_ERA_START_YEAR)
        if year > 2024 and prev_same_era:
            years.append(year - 1)
        for y in years:
            fl = self._c.get_circuit_fastest_lap(y, circuit)
            if fl:
                self.reference = {"driver": _ru_driver(fl["driver"]), "time_ms": fl["time_ms"],
                                  "year": y, "event": event, "source": "fastest_lap"}
                self._load_sectors(circuit, y)
                return True
        for y in years:
            pole = self._c.get_circuit_pole(y, circuit)
            if pole:
                self.reference = {"driver": _ru_driver(pole["driver"]), "time_ms": pole["time_ms"],
                                  "year": y, "event": event, "source": "pole"}
                self._load_sectors(circuit, y)
                return True
        return False

    def _load_sectors(self, circuit: str, year: int) -> None:
        """Секторный эталон OpenF1 — надстройка поверх основного эталона.
        OpenF1Client сам гасит сетевые сбои (возвращает None) — здесь трансляция
        в self.reference["sector_ms"] + запись источника/причины отсутствия:

        - живые/кэшированные данные есть → sector_ms=словарь, sectors_source="api"
        - данных нет, НО известен статический сид (core/openf1_seed.py) для этой
          трассы → sector_ms=сид, sectors_source="seed" (используется, только если
          нет НИ живых, НИ кэшированных данных — реальные данные всегда в приоритете)
        - данных нет вообще → sector_ms=None, sectors_source=None
        sectors_blocked=True, если ПОСЛЕДНЯЯ сетевая попытка получила 401 (live-сессия
        F1 блокирует анонимный доступ) — отдельно от «трассы просто нет в данных»,
        чтобы HUD мог объяснить пользователю ПОЧЕМУ секторов нет (см. race.tsx)."""
        session_key = self._openf1.get_session_key(year, circuit)
        sectors = self._openf1.get_best_sectors(session_key)
        self.reference["sectors_blocked"] = self._openf1.blocked_by_live_session
        if sectors is not None:
            self.reference["sector_ms"] = sectors
            self.reference["sectors_source"] = "api"
            return
        seed = SECTOR_SEED.get(circuit)
        if seed:
            self.reference["sector_ms"] = seed["sectors"]
            self.reference["sectors_source"] = "seed"
        else:
            self.reference["sector_ms"] = None
            self.reference["sectors_source"] = None

    def compare(self, player_laps: list[dict]) -> dict | None:
        """Гэп лучшего круга игрока к эталону. None если не готов / нет валидных кругов.
        Ключи "sectors"/"sectors_source"/"sectors_blocked" присутствуют ВСЕГДА
        (словарь/None, "api"|"seed"|None, bool) — контракт для HUD/Voice/Story,
        чтобы не делать hasattr-проверки у потребителей."""
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
            "sectors_blocked": ref.get("sectors_blocked", False),
            "interpretation": describe_time_difference(
                best["last_lap_ms"] - ref["time_ms"], decimals=3),
            "comparison_disclaimer": COMPARISON_DISCLAIMER,
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
        Post-Race Story: weak_sector_vs_f1 — НЕ то же самое, что coach_ai.weak_sector,
        который про собственный темп игрока, а не про реальный F1). None — эталонных
        секторов нет ИЛИ ни один круг не дал валидных s1/s2/s3.
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

    def _ref_word(self, case: str = "nom") -> str:
        """"поул"/"быстрейший круг" (им.) или "поула"/"быстрейшего круга" (род.).
        Родительный нужен там, где слово стоит после "от"/"быстрее" — раньше
        всегда возвращался именительный, что давало "от быстрейший круг X"."""
        is_pole = (self.reference or {}).get("source") == "pole"
        if case == "gen":
            return "поула" if is_pole else "быстрейшего круга"
        return "поул" if is_pole else "быстрейший круг"

    def _is_player_reference(self, cmp: dict, player_name: str | None) -> bool:
        """True если пилот-эталон реального Гран-при — тот же, за кого сейчас
        играет пользователь (по фамилии). В этом случае нельзя называть его в
        третьем лице ("ты быстрее Ферстаппена"), когда игрок и есть Ферстаппен."""
        return bool(player_name) and surname_of(player_name) == cmp["f1_driver"]

    def context_line(self, cmp: dict, player_name: str | None = None) -> str:
        """Строка-сверка для контекста LLM (не озвучивается напрямую)."""
        if self._is_player_reference(cmp, player_name):
            return (f"Эталон трассы — твой же {self._ref_word()} в реальном {cmp['event']} "
                    f"{_fmt_lap(cmp['f1_time_ms'])}. Твой лучший {_fmt_lap(cmp['player_best_ms'])}. "
                    f"{describe_time_difference(cmp['gap_ms'])} "
                    f"{SHORT_COMPARISON_DISCLAIMER}")
        drv = decline(cmp["f1_driver"], "gen")
        return (f"Эталон трассы — {self._ref_word()} {drv} {_fmt_lap(cmp['f1_time_ms'])} "
                f"({cmp['event']}). Твой лучший {_fmt_lap(cmp['player_best_ms'])}. "
                f"{describe_time_difference(cmp['gap_ms'])} "
                f"{SHORT_COMPARISON_DISCLAIMER}")

    def pb_line(self, cmp: dict, player_name: str | None = None) -> str:
        """Озвучиваемая реплика на личном рекорде круга (гэп словами, без сырого времени круга).

        Если игрок в игре управляет машиной того же пилота, что и реальный
        эталон (player_name), не называем эталон по фамилии в третьем лице —
        иначе фраза звучит как обращение к постороннему ("ты быстрее
        Ферстаппена"), хотя игрок и есть Ферстаппен."""
        difference = describe_time_difference(cmp["gap_ms"])
        if self._is_player_reference(cmp, player_name):
            return (f"Личный рекорд круга! {difference} Ориентир — твой же "
                    f"{self._ref_word()} в реальном Гран-при. Условия напрямую "
                    f"не сопоставимы.")
        drv = decline(cmp["f1_driver"], "gen")
        return (f"Личный рекорд круга! {difference} Ориентир — "
                f"{self._ref_word()} {drv}. Условия напрямую не сопоставимы.")

    def sector_pb_line(self, sector_n: int, sector_cmp: dict) -> str:
        """Озвучиваемая реплика на личном рекорде СЕКТОРА (не путать с pb_line — там полный круг)."""
        difference = describe_time_difference(sector_cmp["gap_ms"])
        return (f"Сектор {sector_n} — твой лучший в сессии. {difference} "
                f"Условия напрямую не сопоставимы.")
