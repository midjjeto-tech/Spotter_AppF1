"""
core/iracing_packets.py
========================
Перевод переменных iRacing SDK (опрос shared-memory, см.
core/iracing_telemetry.py) в СЛОВАРИ ТОЙ ЖЕ ФОРМЫ, что и core/packets.py
отдаёт для F1 UDP-пакетов. Имена и сигнатуры функций совпадают 1:1 с
packets.py (parse_lap_data, parse_player_lap, parse_player_telemetry,
parse_participants, ...) — это НЕ новая модель данных, а шим/переводчик,
чтобы core/engine.py::_update_telemetry и все трекеры (TrackLimitsTracker,
DriverCoach, RivalTracker и т.д.) работали без изменений независимо от
источника телеметрии. См. план
C:\\Users\\Artem\\.claude\\plans\\peaceful-humming-teacup.md.

ВАЖНО про лоссовость: у iRacing нет прямых аналогов части F1-полей (компаунд
шин по FIA-схеме, штатный 0-5 weather-код, дискретные push-события вроде
PENA). Там, где честного перевода нет, отдаём безопасный placeholder
(None/0/пустой dict), а не выдумываем данные — потребители уже умеют
пропускать отсутствующие поля (см. core/engine.py::_update_telemetry).

Ключи словарей ниже — те же имена, что использует core/engine.py при чтении
результата (например "positions", "gap_front_ms", "tyre_compound"), НЕ
внутренние имена iRacing SDK.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def parse_participants(vars: dict, game_year: int = 0) -> dict[int, dict]:
    """{vehicle_idx: {"name", "team", "color", "number"}} — из YAML session
    info (DriverInfo.Drivers), а не из опрашиваемых переменных: список
    пилотов не тикает каждый кадр, как позиция/круг.

    iRacing — классовые заезды (multiclass), а не команды реального мира,
    поэтому "team" — TeamName из iRacing (лига/livery), НЕ F1_metadata /
    TEAM_INFO (см. риски в плане: не пытаться сопоставить с F1-ростером).
    """
    result: dict[int, dict] = {}
    for driver in vars.get("_drivers", []):
        try:
            idx = int(driver["CarIdx"])
        except (KeyError, TypeError, ValueError):
            continue
        name = (driver.get("UserName") or "").strip() or None
        team = (driver.get("TeamName") or "").strip() or driver.get("CarClassShortName") or "iRacing"
        number = driver.get("CarNumber")
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = 0
        result[idx] = {
            "name": name,
            "team": team,
            "color": "#9CA3AF",   # нет офиц. цвета команды у iRacing — нейтральный (Phase 4: по классу)
            "number": number,
        }
    return result


def parse_lap_data(vars: dict) -> dict:
    """Аналог F1 parse_lap_data: позиции/круги/пит-статус всех машин + лидер.

    gaps_front и lap_distances (в метрах) НЕ переведены в Phase 1 — у iRacing
    нет прямого отрыва в мс без доп. расчёта по CarIdxEstTime, а
    CarIdxLapDistPct — это ДОЛЯ круга (0..1), не метры (нужна длина трассы,
    которой здесь ещё нет). Оставлены пустыми/None — потребители (RivalTracker,
    "дешёвый продольный фильтр" споттера) деградируют без этих полей, не падают.
    """
    positions_raw = vars.get("CarIdxPosition") or []
    laps_raw = vars.get("CarIdxLap") or []
    pit_raw = vars.get("CarIdxOnPitRoad") or []

    positions: dict[int, int] = {}
    laps: dict[int, int] = {}
    pit_status: dict[int, int] = {}
    for idx, pos in enumerate(positions_raw):
        if pos and pos > 0:
            positions[idx] = pos
            laps[idx] = laps_raw[idx] if idx < len(laps_raw) else 0
            pit_status[idx] = 2 if (idx < len(pit_raw) and pit_raw[idx]) else 0

    leader_idx = next((i for i, p in positions.items() if p == 1), None)
    return {
        "positions": positions,
        "laps": laps,
        "pit_status": pit_status,
        "leader_idx": leader_idx,
        "gaps_front": {},      # Phase 2/3 TODO — требует CarIdxEstTime
        "lap_distances": {},   # Phase 2/3 TODO — требует длину трассы
    }


def parse_player_lap(vars: dict, player_idx: int) -> dict:
    """Аналог F1 parse_player_lap для машины игрока. last_lap_ms=0 и
    s1/s2/s3=0 сознательно (не переведены в Phase 1) — engine.py's
    lap-complete analytics (`if lms > 0`) сама пропускает круг с lms=0,
    поэтому safer default = "не переведено", а не "круг был нулевым"."""
    positions_raw = vars.get("CarIdxPosition") or []
    laps_raw = vars.get("CarIdxLap") or []
    pit_raw = vars.get("CarIdxOnPitRoad") or []

    if player_idx >= len(positions_raw):
        return {}

    return {
        "position": positions_raw[player_idx] or 0,
        "current_lap": laps_raw[player_idx] if player_idx < len(laps_raw) else 0,
        "pit_status": 2 if (player_idx < len(pit_raw) and pit_raw[player_idx]) else 0,
        "last_lap_ms": 0,          # Phase 2/3 TODO — LapLastLapTime (сек) * 1000
        "s1_ms": 0, "s2_ms": 0, "s3_ms": 0,   # Phase 2/3 TODO
        "gap_front_ms": None,      # Phase 2/3 TODO
        "gap_leader_ms": None,     # Phase 2/3 TODO
        "lap_distance_m": None,    # Phase 2/3 TODO — нужна длина трассы
        "corner_cutting_warnings": None,   # нет аналога — track-limits для iRacing будет через synthesize_events (Phase 3)
    }


def parse_player_telemetry(vars: dict, player_idx: int) -> dict:
    """Speed (км/ч) и передача — единственные телеметрийные поля, которые
    iRacing действительно даёт per-tick для машины ИГРОКА (в отличие от F1,
    где CarTelemetry приходит для всех 22 машин, iRacing не транслирует
    подробную телеметрию чужих машин — фундаментальное ограничение SDK, не
    недосмотр). `player_idx` принимается для совпадения сигнатуры с F1,
    но не используется — тут всегда данные игрока."""
    result: dict = {}
    speed_ms = vars.get("Speed")
    if speed_ms is not None:
        speed_kmh = round(speed_ms * 3.6)
        if 0 <= speed_kmh <= 400:
            result["speed"] = speed_kmh

    gear = vars.get("Gear")
    if gear is not None and -1 <= gear <= 8:
        result["gear"] = "N" if gear == 0 else ("R" if gear == -1 else str(gear))

    return result


# --------------------------------------------------------------------------- #
# Phase 2/3 — намеренно НЕ реализовано в Phase 1 (см. план, раздел "Incremental
# delivery phases"). Заглушки нужны только чтобы core.engine.py могло
# единообразно привязать self._parse_x к core.packets ИЛИ core.iracing_packets
# по имени функции (module swap) без AttributeError, если/когда игра пришлёт
# соответствующий packet_id раньше, чем эти фазы реализованы.
# --------------------------------------------------------------------------- #

def parse_session(vars: dict) -> dict:
    """Phase 2 TODO: погода/сессия/трасса. Пока — пусто (session-ветка
    _update_telemetry просто не выполнит F1-специфичные действия)."""
    return {}


def parse_player_status(vars: dict, player_idx: int) -> dict:
    """Phase 2 TODO: топливо/шины/ERS для машины игрока."""
    return {}


def parse_car_status_all(vars: dict) -> dict[int, dict]:
    """Phase 2 TODO: топливо/шины/ERS для всех машин. iRacing не имеет ERS —
    поле будет отсутствовать (не 0), когда дойдёт очередь до реализации."""
    return {}


def parse_player_damage(vars: dict, player_idx: int) -> dict:
    """Phase 2 TODO: повреждения машины игрока."""
    return {}


def parse_car_damage_all(vars: dict) -> dict[int, dict]:
    """Phase 2 TODO: повреждения. iRacing даёт куда менее гранулярные данные
    о повреждениях по категориям — реализация будет заведомо lossy."""
    return {}


def parse_event(vars: dict) -> dict | None:
    """Phase 3 TODO: у iRacing нет push-событий (PENA/OVTK/COLL и т.п.) — их
    предстоит СИНТЕЗИРОВАТЬ из дельт опроса (флаги/инциденты/сравнение
    позиций между тиками), см. synthesize_events. Не путать одно с другим:
    parse_event здесь — заглушка для единообразия module-swap seam, реальная
    работа будет в synthesize_events."""
    return None


def synthesize_events(prev_vars: dict | None, vars: dict) -> list[dict]:
    """Phase 3 TODO: сравнить prev_vars/vars и вернуть список событий в форме
    core.packets.parse_event() (event_code/description/priority/...). Пока
    возвращает пустой список — commentary остаётся молчаливым на событиях
    для iRacing вплоть до Phase 3 (см. план)."""
    return []
