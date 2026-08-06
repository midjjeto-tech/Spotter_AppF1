"""
core/race_state.py
===================
Хранит то, что комментатор должен "помнить": кто есть кто (имена/команды),
и недавнюю историю событий — чтобы отличать разовый обгон от затяжной борьбы
за позицию между двумя пилотами.
"""

from __future__ import annotations

from collections import deque
from core.f1_metadata import roster_by_number

# Сколько последних событий храним для анализа "борьбы"
HISTORY_SIZE = 12

# Если между теми же двумя пилотами было >= этого числа обгонов
# за последние HISTORY_SIZE событий — считаем это battle (борьбой)
BATTLE_THRESHOLD = 2


class RaceState:

    def __init__(self):
        self.drivers: dict[int, dict] = {}  # vehicle_idx -> {"name", "team", "color"}
        self.history: deque[dict] = deque(maxlen=HISTORY_SIZE)
        # Год игровой сессии (Engine проставляет из заголовка UDP-пакета) — двигает
        # выбор ростера по номеру машины (roster_by_number), номера переиспользуются
        # между сезонами (Ферстаппен 1→3 в 2026). 0 = неизвестно → дефолт на 2025.
        self.game_year: int = 0

    # ------------------------------------------------------------
    # Обновление состояния
    # ------------------------------------------------------------

    def update_drivers(self, drivers: dict[int, dict]):
        if drivers:
            self.drivers.update(drivers)

    def record_event(self, event: dict):
        self.history.append(event)

    # ------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------

    def driver(self, vehicle_idx) -> dict:
        # Driver name resolution order:
        # 1. name from UDP participants packet (already enriched)
        # 2. roster_by_number(self.game_year) lookup by race number (season-aware —
        #    numbers get reused across seasons, e.g. Verstappen 1->3 in 2026)
        # 3. neutral "#N" label — never "машина N" or "пилот N"
        if vehicle_idx is None:
            return {"name": "пилот", "team": "", "color": "#9CA3AF"}

        info = self.drivers.get(vehicle_idx)
        if info:
            if info.get("name"):
                return info
            num = info.get("number")
            if num:
                static = roster_by_number(self.game_year).get(int(num))
                if static:
                    return {
                        "name": static[0],
                        "team": info.get("team") or static[1],
                        "color": info.get("color", "#9CA3AF"),
                        "number": num,
                    }
                return {
                    "name": "гонщик",
                    "team": info.get("team", ""),
                    "color": info.get("color", "#9CA3AF"),
                    "number": num,
                }
            return {
                "name": "гонщик",
                "team": info.get("team", ""),
                "color": info.get("color", "#9CA3AF"),
            }

        return {"name": "гонщик", "team": "", "color": "#9CA3AF"}

    def _count_recent_overtakes(self, vehicle_a: int, vehicle_b: int) -> int:
        """Сколько раз эта пара пилотов обгоняла друг друга за последние
        HISTORY_SIZE событий (переиспользуется is_battle() и enrich()'ом для
        build_plan() — см. design spec 2026-07-05-race-memory)."""
        pair = frozenset((vehicle_a, vehicle_b))
        count = 0
        for past in self.history:
            if past.get("event_code") != "OVTK":
                continue
            past_pair = frozenset((past.get("overtaking_idx"), past.get("being_overtaken_idx")))
            if past_pair == pair:
                count += 1
        return count

    def is_battle(self, vehicle_a: int, vehicle_b: int) -> bool:
        """Были ли недавно повторяющиеся обгоны между этими двумя пилотами.
        Контракт (bool, порог BATTLE_THRESHOLD) стабилен — подсчёт вынесен в
        переиспользуемый _count_recent_overtakes()."""
        return self._count_recent_overtakes(vehicle_a, vehicle_b) >= BATTLE_THRESHOLD

    def enrich(self, event: dict) -> dict:
        """Добавляет к событию читаемые имена/команды и флаг 'battle'."""
        enriched = dict(event)

        if "vehicle_idx" in event:
            info = self.driver(event["vehicle_idx"])
            enriched["driver"] = info["name"]
            enriched["team"] = info["team"]
            enriched["color"] = info["color"]

        if "overtaking_idx" in event:
            a = self.driver(event["overtaking_idx"])
            b = self.driver(event["being_overtaken_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            enriched["battle_count"] = self._count_recent_overtakes(
                event["overtaking_idx"], event["being_overtaken_idx"]
            )
            enriched["battle"] = enriched["battle_count"] >= BATTLE_THRESHOLD

        if "vehicle1_idx" in event:
            a = self.driver(event["vehicle1_idx"])
            b = self.driver(event["vehicle2_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            # battle — только для повторяющихся обгонов (is_battle читает историю
            # OVTK-событий); для аварии это понятие не определено, оставляем дефолт.

        enriched.setdefault("color", "#9CA3AF")
        enriched.setdefault("battle", False)
        return enriched
