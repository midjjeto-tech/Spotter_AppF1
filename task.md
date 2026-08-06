ТЗ: Улучшить работу с данными пилотов через Jolpica F1 API (преемник Ergast)
Цель
Сделать обогащение данных пилотов надёжным, быстрым и устойчивым к отсутствию сети. Сейчас в проекте используется только статический словарь F1_2025_BY_NUMBER. Нужно добавить умный слой с Jolpica API + кэшированием.
Требования

Новый модуль core/ergast_client.py
Класс JolpicaClient (или ErgastClient для совместимости).
Base URL: https://api.jolpi.ca/ergast/f1/
Поддержка JSON-ответов.
Кэширование запросов в DATA_DIR/ergast_cache/ (json-файлы + timestamp, TTL 30 дней для исторических данных, 1 час для текущего сезона).
Retry + backoff (3 попытки, exponential).
Rate limit guard (максимум 1 запрос в 2 секунды + токен-бакет).

Интеграция в core/f1_metadata.py
Обновить функцию enrich_driver(vehicle_idx, participant_data):
Сначала статический словарь F1_2025_BY_NUMBER (приоритет).
Затем кэш.
Затем запрос к Jolpica (/drivers.json + фильтр по номеру/фамилии).
Фолбэк: "гонщик" / "соперник" (как сейчас).

Добавить метод enrich_all_drivers(participants) —批量 обогащение.
Сохранять русские имена (если добавим маппинг).

Дополнительно
Поддержка получения полного списка пилотов текущего сезона.
Поддержка constructors (команды).
Логирование (info при кэш-хите, warning при сети).
Тесты: tests/test_ergast_client.py (моки + live smoke-тест).


Технические детали

Использовать requests (или httpx если уже есть).
Кэш: json + pathlib, имя файла = hash(query).
Конфиг: добавить в config.py ERGast_CACHE_DIR, ERGast_TTL_DAYS.
Не ломать текущую работу без сети (статический словарь всегда первый).
Обработка ошибок: таймауты, 429, 404, JSON decode — всё gracefully.

Критерии приёмки

При запуске без сети — работает как раньше (только статика).
С сетью — обогащает недостающие имена пилотов 2025/2026.
Кэш работает (повторные запросы мгновенные).
Все новые тесты зелёные.
Код чистый, с типами (если используешь), docstring'ами и комментариями.

Приоритет: Высокий (чтобы приложение лучше работало с кастомными/новыми пилотами в карьере F1 25).

Задача
Добавить в Spotter App надёжный слой обогащения данных пилотов и команд через Jolpica F1 API (актуальный преемник Ergast).
Цель

Сохранить скорость и оффлайн-работу (статический словарь остаётся приоритетом).
Автоматически подтягивать актуальные данные для новых/кастомных пилотов (карьера, My Team и т.д.).
Кэшировать результаты, чтобы не спамить API.


Техническое задание
1. Новый модуль
Создать файл: core/ergast_client.py
Pythonclass JolpicaClient:
    BASE_URL = "https://api.jolpi.ca/ergast/f1"
    
    def __init__(self):
        self.cache_dir = config.DATA_DIR / "ergast_cache"
        self.cache_dir.mkdir(exist_ok=True)
    
    def get_driver_by_number(self, number: int, season: int = 2025) -> dict | None:
        """Получить данные пилота по номеру"""
    
    def get_driver(self, driver_id: str) -> dict | None:
        """Поиск по driverId (verstappen, leclerc и т.д.)"""
    
    def get_current_drivers(self, season: int = 2025) -> list:
        """Список всех пилотов сезона"""
    
    def search_driver(self, family_name: str) -> dict | None:
        """Поиск по фамилии"""
2. Обновление core/f1_metadata.py
Pythonfrom .ergast_client import JolpicaClient

class F1Metadata:
    def __init__(self):
        self.client = JolpicaClient()
        # существующий статический словарь F1_2025_BY_NUMBER
    
    def enrich_driver(self, vehicle_idx: int, participant: dict) -> dict:
        # 1. Статический словарь (приоритет)
        # 2. Кэш
        # 3. Jolpica API
        # 4. Фолбэк "гонщик"
3. Кэширование

Папка: DATA_DIR/ergast_cache/
Имя файла: driver_{number}_{season}.json или hash-запроса.
TTL: 30 дней для исторических данных, 1 час для текущего сезона.
Автоочистка старого кэша (опционально).

4. Rate limit и устойчивость

Минимум 2 секунды между запросами.
Retry 3 раза с backoff.
Graceful degradation при ошибках сети / 429 / таймаутах.

5. Тесты

tests/test_ergast_client.py (моки + smoke)
Обновить существующие тесты в test_driver_names.py


Что нужно сделать (чек-лист)

Создать core/ergast_client.py
Обновить f1_metadata.py (enrich_driver + enrich_all_drivers)
Добавить настройки в config.py
Написать тесты
Обновить CONTEXT.md после реализации

Рекомендация: OpenF1 (openf1.org)
Это лучший выбор для вашего Spotter App, потому что он даёт реал-тайм данные:

Telemetry (скорость, газ, тормоз, DRS, шины и т.д.)
Lap times + сектора
Позиции на трассе
Race control messages
Team radio (частично)
Weather и т.д.

Base URL: https://api.openf1.org/v1/
ТЗ для интеграции OpenF1
Цель: Дополнить UDP-телеметрию из F1 25 данными из OpenF1 (особенно для live-сессий).
Задачи:

Создать core/openf1_client.py
Добавить в core/engine.py периодический polling во время сессии.
Обогатить state["race"] и state["telemetry"] данными (позиции, gaps, шины, lap times).
Кэш + rate limit handling.
UI-панель (опционально — "Live Data Source: OpenF1").

Ключевые эндпоинты OpenF1:

/drivers — список пилотов
/laps — времена кругов
/car_data — телеметрия
/position — позиции на трассе
/race_control — сообщения от дирекции гонки
/weather — погода

Rate limits: 3 req/sec, 30 req/min (бесплатно).
Что именно получаем в итоге
1. Для Spotter (комментатор)

Jolpica → точные имена, фамилии, национальности пилотов (особенно полезно для ru_names.py и склонения).
OpenF1 → живые данные для LLM-персоны (gap to leader, шины, DRS, sector times, race control messages) → более умные и timely комментарии.

2. Для Race page / Dashboard

Точная таблица позиций (OpenF1 даёт более частые обновления, чем UDP).
Gap'ы, отставания, пит-стопы.
Weather + track temperature (OpenF1).
Race Control события («Safety Car», «Virtual Safety Car», флаги).

3. Для Strategy / Coach AI

OpenF1 даёт реальные lap times + sector times → точный анализ consistency и pace.
Jolpica — исторические сравнения (лучшее время на этой трассе и т.д.).

4. Для Broadcast / Overlay

Более богатый контекст для LLM (OpenF1 + timeline).

Предлагаемая архитектура (рекомендую)
Python# core/data_sources.py
class F1DataHub:
    def __init__(self):
        self.jolpica = JolpicaClient()
        self.openf1 = OpenF1Client()
    
    def get_driver_info(self, number: int):
        # Сначала статика → Jolpica → кэш
        ...
    
    def get_live_state(self, session_key=None):
        # Основной источник — OpenF1
        ...
Плюсы такого подхода:

Максимальная точность и свежесть данных.
Резервирование (если OpenF1 упал — падаем на UDP + Jolpica).
Хорошая производительность (агрессивный кэш).

Вот готовый пример класса F1DataHub — единая точка доступа к обоим источникам.
Создай файл core/f1_data_hub.py:
Pythonimport time
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from config import DATA_DIR
from .ergast_client import JolpicaClient   # или как вы назвали
from .openf1_client import OpenF1Client

logger = logging.getLogger(__name__)

class F1DataHub:
    """
    Единая точка правды для всех данных F1.
    Комбинирует Jolpica (исторические + стабильные) и OpenF1 (live).
    """
    
    def __init__(self):
        self.jolpica = JolpicaClient()
        self.openf1 = OpenF1Client()
        self.current_session_key: Optional[int] = None
        self.last_openf1_update = 0

    # ====================== Общие методы ======================

    def enrich_driver(self, vehicle_idx: int, participant: Dict) -> Dict:
        """
        Основной метод обогащения пилота (используется в race_state и telemetry).
        Приоритет: статический → Jolpica → OpenF1 → фолбэк
        """
        number = participant.get("number") or participant.get("m_driverId")

        # 1. Статический словарь (самый быстрый)
        driver_info = self._get_static_driver(number)
        if driver_info:
            return {**participant, **driver_info}

        # 2. Jolpica (исторические + актуальные пилоты сезона)
        jolpica_info = self.jolpica.get_driver_by_number(number)
        if jolpica_info:
            return {**participant, **jolpica_info}

        # 3. OpenF1 (live данные)
        openf1_info = self._get_openf1_driver(number)
        if openf1_info:
            return {**participant, **openf1_info}

        # Фолбэк
        return {**participant, "name": f"Гонщик #{number or vehicle_idx}", "team": "Unknown"}

    def _get_static_driver(self, number: int) -> Dict | None:
        """Существующий статический словарь из f1_metadata.py"""
        from .f1_metadata import F1_2025_BY_NUMBER
        return F1_2025_BY_NUMBER.get(number)

    def _get_openf1_driver(self, number: int) -> Dict | None:
        if not self.current_session_key:
            return None
        drivers = self.openf1.get_drivers(self.current_session_key)
        for d in drivers:
            if d.get("driver_number") == number:
                return {
                    "name": f"{d.get('first_name', '')} {d.get('last_name', '')}".strip(),
                    "family_name": d.get("last_name"),
                    "team": d.get("team_name"),
                    "driver_number": d.get("driver_number")
                }
        return None

    # ====================== Live polling ======================

    def update_live_session(self):
        """Вызывать из engine каждые несколько секунд"""
        try:
            session_data = self.openf1.get_current_session()
            if session_data and len(session_data) > 0:
                self.current_session_key = session_data[0].get("session_key")
                self.last_openf1_update = time.time()
                return True
        except Exception as e:
            logger.debug(f"OpenF1 session update failed: {e}")
        return False

    def get_live_state(self) -> Dict[str, Any]:
        """Возвращает обогащённое live-состояние для engine.state"""
        if not self.current_session_key:
            return {}

        return {
            "session_key": self.current_session_key,
            "last_update": time.strftime("%H:%M:%S", time.localtime(self.last_openf1_update)),
            "positions": self.openf1.get_positions(self.current_session_key)[:10],  # топ-10
            "race_control": self.openf1.get_race_control(self.current_session_key)[-5:],  # последние 5
            # Можно добавить laps, weather, car_data и т.д.
        }

    # ====================== Утилиты ======================

    def is_live_available(self) -> bool:
        return bool(self.current_session_key and 
                   (time.time() - self.last_openf1_update) < 30)
Как использовать в engine.py
Python# В __init__
self.data_hub = F1DataHub()

# В telemetry loop
if packet_type == PACKET_SESSION:
    self.data_hub.update_live_session()

# При обогащении
driver = self.data_hub.enrich_driver(vehicle_idx, raw_driver_data)

# В get_state
state["openf1"] = self.data_hub.get_live_state()