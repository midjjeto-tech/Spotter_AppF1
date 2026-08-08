"""
core/f1_metadata.py
===================
Обогащение данных пилотов/команд для live-телеметрии F1 25.

СЕТИ ЗДЕСЬ БОЛЬШЕ НЕТ. До 2026-08-08 вторым слоем стояла Jolpica/Ergast, но её
TERMS разрешают только некоммерческое использование, а содержимое отдано под
CC BY-NC-SA 4.0 (см. NOTICE) — для продаваемой сборки это блокер. Слой удалён
целиком; статические ростеры ниже покрывают обе реальные сетки полностью, а
всё остальное добирают whitelist и транслитерация. Не возвращать сетевой
источник, не проверив его условия.

Слои (в порядке приоритета внутри enrich_driver):
1. Статический русский словарь по номеру (roster_by_number → F1_2025_BY_NUMBER
   или F1_2026_BY_NUMBER) — авторитетно и мгновенно для реальной сетки
   (русский TTS коверкает латиницу, см. ru_names).
2. Точные имена/фамилии реальных пилотов (core/transliterate.py) — whitelist
   действующего ростера, где буквенная транслитерация документированно
   ошибается (Verstappen, Sainz/Perez и т.п.). Проверяется по сырому
   UDP-имени — новичок может отсутствовать в статическом словаре.
3. Транслитерация (core/transliterate.py::to_cyrillic) — приблизительная
   кириллица лучше, чем сырая латиница в Yandex TTS.
4. Фолбэк «гонщик»/«соперник» — в race_state, если ничего не нашли.

Кастомные пилоты карьеры сохраняют своё UDP-имя: whitelist состоит только из
реальных имён и их не задевает.
"""

from __future__ import annotations

import logging
import os
from typing import Any

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


class F1Metadata:
    """Обогащение имён пилотов из статических ростеров. Без сети и без потоков."""

    def __init__(self, season: str = DEFAULT_SEASON):
        self.season = season
        self._game_year: int = 0

    def start(self) -> None:
        """Совместимость с прежним жизненным циклом: фонового обогащения больше
        нет, загружать нечего. Метод оставлен, чтобы владелец (core/runtime.py,
        core/engine.py) не менял порядок запуска ради удалённой сети."""

    def stop(self, timeout: float = 1.0) -> None:
        """См. start(): останавливать больше нечего."""

    @property
    def loaded(self) -> bool:
        """Данные готовы всегда: ростеры статические, ждать нечего.

        Флаг уезжает в UI как `metadata_loaded` (core/ui_state.py). Вернуть
        False значило бы вечное «обогащение не готово» при полностью рабочем
        обогащении."""
        return True

    @property
    def error(self) -> str | None:
        """Сломаться больше негде — сети нет."""
        return None

    @property
    def game_year(self) -> int:
        return self._game_year

    @game_year.setter
    def game_year(self, year: int) -> None:
        """Проставляется Engine'ом из заголовка UDP-пакета (может прилетать на
        каждом пакете — повторная установка того же года ничего не делает).

        Двигает выбор ростера по номеру (roster_by_number в enrich_driver):
        номера переиспользуются между сезонами, Ферстаппен 1→3. Раньше этот же
        сеттер перезапускал фоновую загрузку сезона из Jolpica — сети больше
        нет, осталось только переключение словаря."""
        self._game_year = year
        if year and str(year) != self.season:
            self.season = str(year)

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

        # 2. Точные имена/фамилии реальных пилотов (known_driver_name) —
        #    проверяем ДАЖЕ по сырому UDP-имени: новичок (напр. Линдблад) мог
        #    ещё не попасть в статический словарь, но уже быть в whitelist.
        #    Whitelist только из реальных имён — кастомных/карьерных пилотов
        #    не задевает (см. tests/test_driver_names.py::
        #    test_custom_driver_keeps_udp_name_for_unknown_number).
        candidate = result.get("name") or name
        known = transliterate.known_driver_name(candidate) if candidate else None
        if known:
            result["name"] = known
        # 3. Общая транслитерация — только для имени, уже положенного в result,
        #    не для сырого UDP-имени: кастомный пилот карьеры обязан остаться
        #    собой. Ветка стала почти недостижимой (слой 1 кладёт сразу
        #    кириллицу), но остаётся страховкой на случай нового источника имён
        #    выше по списку. Точные случаи — в статических словарях и
        #    KNOWN_SURNAMES, это не замена им (см. core/transliterate.py).
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
                    "(roster_year=%s)",
                    idx, info.get("number"), info.get("name"),
                    merged.get("name"), merged.get("team"), self._game_year,
                )
        return enriched

    # Алиас под имя из ТЗ (батч-обогащение участников).
    enrich_all_drivers = enrich_drivers
