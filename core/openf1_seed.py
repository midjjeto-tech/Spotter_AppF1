"""
core/openf1_seed.py
====================
Статический (зашитый в код) фолбэк секторных эталонов — на случай, когда для
трассы нет ни живого ответа OpenF1, ни ранее закэшированного (диск-кэш в
core/openf1_client.py, OPENF1_TTL_DAYS). Такое бывает на "холодном старте" —
трасса, к которой ни разу не обращались успешно, впервые запрошена ИМЕННО во
время блокировки (OpenF1 отдаёт 401 всем анонимным запросам, включая прошлые
сезоны, пока идёт live-сессия — см. core/openf1_client.py::blocked_by_live_session).

Ключ — circuit_id (как в core/openf1_client.CIRCUIT_ID_TO_OPENF1_LOCATION).
Значение — {"year": int, "event": str, "sectors": {1: ms, 2: ms, 3: ms}}.

СТАТУС (2026-07-08): наполнено по сезону 2025 —
24/24 трасс покрыто (см. вывод seed_sectors.py при последнем запуске для
списка пропущенных, если N < 24). Обновить: перезапустить `seed_sectors.py`
с новым `YEAR` и вставить свежий вывод сюда — например, после завершения
сезона 2026 (первый год новой регламентной эры, см.
core/f1_benchmark.py::_NEW_ERA_START_YEAR). Отсутствие записи для трассы —
не баг, штатное "пока нет данных" (core/f1_benchmark.py::_load_sectors просто
не найдёт сид, секторный HUD останется скрытым, как и раньше).
"""
from __future__ import annotations

SECTOR_SEED: dict[str, dict] = {
    "albert_park": {'year': 2025, 'event': 'Australian Grand Prix', 'sectors': {1: 28553, 2: 17831, 3: 34890}},
    "shanghai": {'year': 2025, 'event': 'Chinese Grand Prix', 'sectors': {1: 25334, 2: 28437, 3: 41177}},
    "bahrain": {'year': 2025, 'event': 'Bahrain Grand Prix', 'sectors': {1: 30457, 2: 41215, 3: 23261}},
    "catalunya": {'year': 2025, 'event': 'Spanish Grand Prix', 'sectors': {1: 22500, 2: 30476, 3: 22567}},
    "monaco": {'year': 2025, 'event': 'Monaco Grand Prix', 'sectors': {1: 19145, 2: 34690, 3: 19379}},
    "villeneuve": {'year': 2025, 'event': 'Canadian Grand Prix', 'sectors': {1: 20624, 2: 23410, 3: 29598}},
    "silverstone": {'year': 2025, 'event': 'British Grand Prix', 'sectors': {1: 28701, 2: 36333, 3: 24299}},
    "hungaroring": {'year': 2025, 'event': 'Hungarian Grand Prix', 'sectors': {1: 28557, 2: 27940, 3: 22273}},
    "spa": {'year': 2025, 'event': 'Belgian Grand Prix', 'sectors': {1: 30421, 2: 45439, 3: 28409}},
    "monza": {'year': 2025, 'event': 'Italian Grand Prix', 'sectors': {1: 26794, 2: 27252, 3: 26564}},
    "marina_bay": {'year': 2025, 'event': 'Singapore Grand Prix', 'sectors': {1: 27993, 2: 39392, 3: 26423}},
    "suzuka": {'year': 2025, 'event': 'Japanese Grand Prix', 'sectors': {1: 31235, 2: 41404, 3: 17700}},
    "yas_marina": {'year': 2025, 'event': 'Abu Dhabi Grand Prix', 'sectors': {1: 17272, 2: 37457, 3: 31433}},
    "americas": {'year': 2025, 'event': 'United States Grand Prix', 'sectors': {1: 25832, 2: 38904, 3: 32131}},
    "interlagos": {'year': 2025, 'event': 'São Paulo Grand Prix', 'sectors': {1: 18386, 2: 37083, 3: 16536}},
    "red_bull_ring": {'year': 2025, 'event': 'Austrian Grand Prix', 'sectors': {1: 17082, 2: 30284, 3: 20441}},
    "rodriguez": {'year': 2025, 'event': 'Mexico City Grand Prix', 'sectors': {1: 27935, 2: 31082, 3: 20587}},
    "baku": {'year': 2025, 'event': 'Azerbaijan Grand Prix', 'sectors': {1: 36446, 2: 41638, 3: 24655}},
    "zandvoort": {'year': 2025, 'event': 'Dutch Grand Prix', 'sectors': {1: 24661, 2: 25567, 3: 21760}},
    "imola": {'year': 2025, 'event': 'Emilia-Romagna Grand Prix', 'sectors': {1: 24534, 2: 26965, 3: 26070}},
    "jeddah": {'year': 2025, 'event': 'Saudi Arabian Grand Prix', 'sectors': {1: 33499, 2: 28888, 3: 29113}},
    "miami": {'year': 2025, 'event': 'Miami Grand Prix', 'sectors': {1: 29833, 2: 34124, 3: 25335}},
    "vegas": {'year': 2025, 'event': 'Las Vegas Grand Prix', 'sectors': {1: 26350, 2: 31156, 3: 35756}},
    "losail": {'year': 2025, 'event': 'Qatar Grand Prix', 'sectors': {1: 30636, 2: 28093, 3: 23851}},
}
