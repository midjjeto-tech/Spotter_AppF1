"""
core/f1_metadata.py
===================
Обогащение данных пилотов/команд для live-телеметрии F1 25.

Слои (в порядке приоритета внутри enrich_driver):
1. Статический русский словарь F1_2025_BY_NUMBER по номеру — авторитетно и
   мгновенно для реальной сетки 2025 (русский TTS коверкает латиницу, см. ru_names).
2. Jolpica/Ergast (через core/ergast_client.JolpicaClient) — добивает НЕИЗВЕСТНЫЕ
   номера (новички/2026/карьера), команды и национальности. Сеть идёт в ФОНОВОМ
   потоке (_load) с дисковым кэшем; горячий путь читает готовые карты в памяти.
3. Точные имена/фамилии реальных пилотов (core/transliterate.py) — whitelist
   действующего ростера, где буквенная транслитерация ниже
   документированно ошибается (Verstappen, Sainz/Perez и т.п.). Проверяется
   и по сырому UDP-имени (если Jolpica вообще ничего не нашла), и по
   Jolpica-имени — ДО общей транслитерации.
4. Транслитерация (core/transliterate.py::to_cyrillic) — если имя всё ещё
   латиница и его нет ни в статическом словаре, ни в KNOWN_SURNAMES,
   приблизительная кириллица лучше, чем сырая латиница в Yandex TTS.
5. Фолбэк «гонщик»/«соперник» — в race_state, если ничего не нашли.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

from core.ergast_client import JolpicaClient
from core import transliterate

_log = logging.getLogger(__name__)

# Temporary enrichment diagnostics. Enable with SPOTTER_DIAG=1 to trace, per car,
# what number/name arrives from UDP and what name/team enrichment resolves it to.
_DIAG = os.environ.get("SPOTTER_DIAG") == "1"

DEFAULT_SEASON = "2026"

# Статичный словарь сезона F1 2025: постоянный номер → (русское имя, команда).
# Работает как мгновенный фолбэк когда Ergast API не загружен или имя в UDP пустое.
F1_2025_BY_NUMBER: dict[int, tuple[str, str]] = {
    1:  ("Макс Ферстаппен",       "Red Bull Racing"),
    4:  ("Ландо Норрис",          "McLaren"),
    5:  ("Габриэль Бортолето",    "Sauber"),
    6:  ("Исак Хаджар",           "RB"),
    7:  ("Джек Дун",              "Alpine"),
    10: ("Пьер Гасли",            "Alpine"),
    12: ("Андреа Кими Антонелли", "Mercedes"),
    14: ("Фернандо Алонсо",       "Aston Martin"),
    16: ("Шарль Леклер",          "Ferrari"),
    18: ("Лэнс Стролл",           "Aston Martin"),
    22: ("Юки Цунода",            "Red Bull Racing"),
    23: ("Александр Албон",       "Williams"),
    27: ("Нико Хюлькенберг",      "Sauber"),
    30: ("Лиам Лоусон",           "RB"),
    31: ("Эстебан Окон",          "Haas"),
    43: ("Франко Колапинто",      "Alpine"),
    44: ("Льюис Хэмилтон",        "Ferrari"),
    55: ("Карлос Сайнс",          "Williams"),
    63: ("Джордж Расселл",        "Mercedes"),
    81: ("Оскар Пиастри",         "McLaren"),
    87: ("Оливер Бирман",         "Haas"),
}

# Статичный словарь сезона F1 2026: новый регламент + новый грид. НОМЕРА ПЕРЕСЕКАЮТСЯ
# с F1_2025_BY_NUMBER (Ферстаппен 1→3, Норрис →1, Перес 11, Боттас 77 и т.д.) —
# поэтому выбор словаря идёт ТОЛЬКО через roster_by_number(game_year), никогда напрямую.
F1_2026_BY_NUMBER: dict[int, tuple[str, str]] = {
    1:  ("Ландо Норрис",          "McLaren"),
    81: ("Оскар Пиастри",         "McLaren"),
    3:  ("Макс Ферстаппен",       "Red Bull Racing"),
    6:  ("Исак Хаджар",           "Red Bull Racing"),
    16: ("Шарль Леклер",          "Ferrari"),
    44: ("Льюис Хэмилтон",        "Ferrari"),
    63: ("Джордж Расселл",        "Mercedes"),
    12: ("Андреа Кими Антонелли", "Mercedes"),
    23: ("Александр Албон",       "Williams"),
    55: ("Карлос Сайнс",          "Williams"),
    30: ("Лиам Лоусон",           "Racing Bulls"),
    41: ("Арвид Линдблад",        "Racing Bulls"),
    14: ("Фернандо Алонсо",       "Aston Martin"),
    18: ("Лэнс Стролл",           "Aston Martin"),
    31: ("Эстебан Окон",          "Haas"),
    87: ("Оливер Бирман",         "Haas"),
    5:  ("Габриэль Бортолето",    "Audi"),
    27: ("Нико Хюлькенберг",      "Audi"),
    10: ("Пьер Гасли",            "Alpine"),
    43: ("Франко Колапинто",      "Alpine"),
    11: ("Серхио Перес",          "Cadillac"),
    77: ("Валттери Боттас",       "Cadillac"),
}


def roster_by_number(game_year: int) -> dict[int, tuple[str, str]]:
    """Выбор статичного словаря номер→(имя, команда) по году игровой сессии.

    Номера машин переиспользуются между сезонами (см. Ферстаппен 1→3 в 2026) —
    поэтому НИКОГДА нельзя резолвить по номеру без привязки к сезону. game_year=0
    (неизвестно/старые записи без заголовка) — дефолт на 2025, как и раньше."""
    return F1_2026_BY_NUMBER if game_year >= 2026 else F1_2025_BY_NUMBER


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


class F1Metadata:
    """Кэш метаданных сезона F1 из Ergast."""

    def __init__(self, season: str = DEFAULT_SEASON,
                 client: JolpicaClient | None = None):
        self.season = season
        self._game_year: int = 0
        self._client = client or JolpicaClient(current_season=season)
        self._drivers: dict[str, dict[str, Any]] = {}     # normalized name/code/number → info
        self._by_number: dict[int, dict[str, Any]] = {}    # permanentNumber → info
        self._teams: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._error: str | None = None
        self._load_thread: threading.Thread | None = None
        self._stopped = False

    def start(self) -> None:
        """Start background enrichment explicitly; construction is passive."""
        if self._load_thread is not None or self._stopped:
            return
        self._start_load()

    def stop(self, timeout: float = 1.0) -> None:
        self._stopped = True
        thread = self._load_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def _start_load(self) -> None:
        if self._stopped:
            return
        self._load_thread = threading.Thread(
            target=self._load, daemon=True, name="ergast-load")
        self._load_thread.start()

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def game_year(self) -> int:
        return self._game_year

    @game_year.setter
    def game_year(self, year: int) -> None:
        """Проставляется Engine'ом из заголовка UDP-пакета (может прилетать на каждом
        пакете — сравнение ниже делает повторные установки того же года no-op).

        Двигает и выбор ТЕЛЕМЕТРИЙНОГО ростера по номеру (roster_by_number в
        enrich_driver), И — если год реально расходится с уже загруженным сезоном
        Jolpica — сезон фонового обогащения резервных/незаявленных пилотов. Без
        этого резервный пилот в реальной 2026-сессии обогащался бы данными Jolpica
        за self.season по умолчанию (config.F1_SEASON), а не за фактический год игры.
        Старые per-season карты сбрасываются перед перезапуском — иначе номер,
        существовавший только в предыдущем сезоне, остался бы призрачно резолвиться.
        """
        self._game_year = year
        if year and str(year) != self.season:
            self.season = str(year)
            self._drivers = {}
            self._by_number = {}
            self._teams = {}
            self._loaded = False
            self._start_load()

    def _load(self):
        """Фоновая загрузка ростера сезона через кэширующий JolpicaClient.

        Строит карты по имени и по номеру. Любой сбой сети деградирует тихо —
        приложение остаётся на статическом словаре. НИКОГДА не дёргать из потока
        телеметрии (блокирует сеть): enrich_driver читает только готовые карты.
        """
        data = self._client.get_json(f"{self.season}/driverStandings.json")
        if not data:
            self._error = "Jolpica недоступна — работаем на статическом словаре"
            return

        try:
            standings = data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
        except (KeyError, IndexError, TypeError):
            self._error = "Неверный формат ответа Jolpica"
            return

        for entry in standings:
            driver = entry.get("Driver", {})
            constructor = entry.get("Constructors", [{}])[0]
            full_name = f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip()
            code = driver.get("code") or ""
            number = driver.get("permanentNumber") or entry.get("position")
            team = constructor.get("name", "")

            info = {
                "name": full_name,
                "code": code,
                "number": int(number) if str(number).isdigit() else None,
                "team": team,
                "nationality": driver.get("nationality", ""),
            }

            for key in filter(None, [full_name, code, driver.get("familyName")]):
                self._drivers[_normalize_key(str(key))] = info

            if info["number"] is not None:
                self._by_number[info["number"]] = info

            if team:
                self._teams[_normalize_key(team)] = {
                    "name": team,
                    "id": constructor.get("constructorId", ""),
                }

        self._loaded = True
        self._error = None

    def enrich_driver(self, name: str | None, team: str | None, number: int | None) -> dict[str, Any]:
        """Дополняет данные пилота. Русское имя по номеру — ПРИОРИТЕТ.

        UDP-пакет участников (и Ergast) отдают ЛАТИНСКИЕ имена («Verstappen»),
        которые русский Yandex TTS произносит мусором (звучит как «Рэйм»).
        Поэтому для реальной сетки берём русское имя из статичного словаря
        (roster_by_number(self.game_year)) по постоянному номеру. Кастомные
        пилоты (карьера, неизвестный номер) сохраняют своё UDP-имя.
        """
        result: dict[str, Any] = {}

        # 1. Русское имя по постоянному номеру — авторитетно для сетки текущего сезона.
        if number is not None:
            try:
                static = roster_by_number(self.game_year).get(int(number))
            except (TypeError, ValueError):
                static = None
            if static:
                result["name"] = static[0]
                if not team:
                    result["team"] = static[1]

        # 2. Jolpica по номеру (готовая карта в памяти) — для номеров ВНЕ
        #    статического словаря (новички/2026/карьера). Работает и без UDP-имени.
        if not result.get("name") and self._loaded and number is not None:
            try:
                meta = self._by_number.get(int(number))
            except (TypeError, ValueError):
                meta = None
            if meta:
                if meta.get("name"):
                    result["name"] = meta["name"]
                if not result.get("team") and meta.get("team"):
                    result["team"] = meta["team"]

        # 3. Jolpica по имени/коду — если номер не дал результата.
        if not result.get("name") and self._loaded and name:
            keys = [_normalize_key(name)]
            parts = name.split()
            if parts:
                keys.append(_normalize_key(parts[-1]))
            if number is not None:
                keys.append(_normalize_key(str(number)))

            for key in keys:
                meta = self._drivers.get(key)
                if meta:
                    if meta.get("name"):
                        result["name"] = meta["name"]
                    if meta.get("team"):
                        result["team"] = meta["team"]
                    break

        # 4. Нормализация названия команды через Jolpica (не зависит от имени).
        if self._loaded and team and self._teams.get(_normalize_key(team)):
            result["team"] = self._teams[_normalize_key(team)]["name"]

        # 5а. Точные имена/фамилии реальных пилотов (known_driver_name) —
        #     проверяем ДАЖЕ по сырому UDP-имени, если Jolpica ничего не нашла:
        #     новичок (напр. Линдблад) может отсутствовать в driverStandings.json
        #     (там только очковые пилоты), но уже быть в этом whitelist.
        #     Whitelist только из реальных имён — кастомных/карьерных пилотов
        #     не задевает (см. tests/test_driver_names.py::
        #     test_custom_driver_keeps_udp_name_for_unknown_number).
        candidate = result.get("name") or name
        known = transliterate.known_driver_name(candidate) if candidate else None
        if known:
            result["name"] = known
        # 5б. Общая транслитерация — прежнее поведение, без изменений: только
        #     для того, что уже нашла Jolpica (result["name"]), не для сырого
        #     UDP-имени. Лучше приблизительная кириллица, чем сырая латиница в
        #     Yandex TTS. Точные случаи — в F1_2025_BY_NUMBER/F1_2026_BY_NUMBER
        #     и KNOWN_SURNAMES выше, это не замена им (см. core/transliterate.py).
        elif result.get("name") and transliterate.is_latin(result["name"]):
            result["name"] = transliterate.to_cyrillic(result["name"])

        return result

    def enrich_drivers(self, drivers: dict[int, dict]) -> dict[int, dict]:
        # Всегда применяем обогащение: статический словарь работает без API.
        enriched: dict[int, dict] = {}
        for idx, info in drivers.items():
            merged = dict(info)
            extra = self.enrich_driver(info.get("name"), info.get("team"), info.get("number"))
            merged.update({k: v for k, v in extra.items() if v})
            enriched[idx] = merged
            if _DIAG:
                _log.warning(
                    "DIAG enrich idx=%s number=%s raw_name=%r -> name=%r team=%r "
                    "(jolpica_loaded=%s)",
                    idx, info.get("number"), info.get("name"),
                    merged.get("name"), merged.get("team"), self._loaded,
                )
        return enriched

    # Алиас под имя из ТЗ (батч-обогащение участников).
    enrich_all_drivers = enrich_drivers
