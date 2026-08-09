"""
analytics/loader.py
===================
Эталон для послегоночного сравнения — СВОЙ прошлый заезд на той же трассе.

ИСТОЧНИК СМЕНИЛСЯ 2026-08-08. Раньше здесь грузилась реальная сессия Формулы-1
через OpenF1 (сезоны с 2023) или FastF1 (раньше 2023). Обе службы разрешают
только некоммерческое использование, а данные FastF1 приходят из неофициального
источника F1 без коммерческого разрешения вовсе (см. NOTICE) — для продаваемой
сборки это блокер. Сети здесь больше нет.

Сравнивать архивный заезд теперь не с чем, кроме собственной истории, и это
честнее: чужой Гран-при шёл на другой физике и другом регламенте, а свой
прошлый заезд отличается только тем, что реально сравнимо — темпом пилота.
Формат отдаваемого словаря НЕ менялся (`fastest_lap` с секторами), поэтому
analytics/comparator.py::compare() принимает его без единой правки.
"""
from __future__ import annotations

from analytics import archive

# m_trackId — фиксированный enum игры (НЕ порядок календаря), подтверждён официальной
# EA/Codemasters UDP-спекой и независимыми парсерами (f1-2019-telemetry docs, f1-24-udp).
# Индексы стабильны с F1 2019 и просто дополняются новыми трассами по мере выхода игр.
TRACK_ID_TO_GP: dict[int, tuple[str, str]] = {
    0:  ("Melbourne",         "Australian Grand Prix"),
    1:  ("Paul Ricard",       "French Grand Prix"),
    2:  ("Shanghai",          "Chinese Grand Prix"),
    3:  ("Sakhir",            "Bahrain Grand Prix"),
    4:  ("Barcelona",         "Spanish Grand Prix"),
    5:  ("Monaco",            "Monaco Grand Prix"),
    6:  ("Montreal",          "Canadian Grand Prix"),
    7:  ("Silverstone",       "British Grand Prix"),
    8:  ("Hockenheim",        "German Grand Prix"),
    9:  ("Budapest",          "Hungarian Grand Prix"),
    10: ("Spa",               "Belgian Grand Prix"),
    11: ("Monza",             "Italian Grand Prix"),
    12: ("Singapore",         "Singapore Grand Prix"),
    13: ("Suzuka",            "Japanese Grand Prix"),
    14: ("Abu Dhabi",         "Abu Dhabi Grand Prix"),
    15: ("Austin",            "United States Grand Prix"),
    16: ("São Paulo",         "São Paulo Grand Prix"),
    17: ("Spielberg",         "Austrian Grand Prix"),
    18: ("Sochi",             "Russian Grand Prix"),
    19: ("Mexico City",       "Mexico City Grand Prix"),
    20: ("Baku",              "Azerbaijan Grand Prix"),
    21: ("Sakhir Short",      "Bahrain Grand Prix (Short)"),
    22: ("Silverstone Short", "British Grand Prix (Short)"),
    23: ("Austin Short",      "United States Grand Prix (Short)"),
    24: ("Suzuka Short",      "Japanese Grand Prix (Short)"),
    25: ("Hanoi",             "Vietnamese Grand Prix"),
    26: ("Zandvoort",         "Dutch Grand Prix"),
    27: ("Imola",             "Emilia-Romagna Grand Prix"),
    28: ("Portimão",          "Portuguese Grand Prix"),
    29: ("Jeddah",            "Saudi Arabian Grand Prix"),
    30: ("Miami",             "Miami Grand Prix"),
    31: ("Las Vegas",         "Las Vegas Grand Prix"),
    32: ("Lusail",            "Qatar Grand Prix"),
}


def _best_lap_of(session: dict) -> dict | None:
    """Лучший круг игрока в сохранённой сессии. None — валидных кругов нет.

    Секторы отдаём только полным набором: частичный дал бы гэп по одному
    сектору и молчание по двум, что читается как «там всё в порядке»."""
    valid = [l for l in (session.get("player_laps") or [])
             if (l.get("last_lap_ms") or 0) > 0]
    if not valid:
        return None
    best = min(valid, key=lambda l: l["last_lap_ms"])
    out: dict = {"time_ms": best["last_lap_ms"], "lap": best.get("lap")}
    if all((best.get(f"s{n}_ms") or 0) > 0 for n in (1, 2, 3)):
        for n in (1, 2, 3):
            out[f"s{n}_ms"] = best[f"s{n}_ms"]
    return out


def load_own_reference_session(track_id: int,
                               exclude_path: str | None = None
                               ) -> tuple[dict | None, str | None]:
    """Самый быстрый СВОЙ заезд на этой трассе. Возвращает (данные, ошибка).

    `exclude_path` — сессия, которую как раз разбирают: сравнивать её с самой
    собой бессмысленно (гэп всегда ноль), поэтому она исключается из поиска.

    Формат результата совместим с прежним ответом реальной сессии F1, чтобы
    comparator и фронтенд не знали о смене источника: ключ `fastest_lap` с
    временем круга и (если есть) секторами.
    """
    entry = TRACK_ID_TO_GP.get(track_id)
    if entry is None:
        return None, "unknown_track"

    best_lap: dict | None = None
    best_meta: dict | None = None
    for summary in archive.list_game_sessions():
        if summary.get("track_id") != track_id:
            continue
        path = summary.get("path")
        if exclude_path and str(path) == str(exclude_path):
            continue
        data = archive.load_game_session(path)
        if not data:
            continue
        lap = _best_lap_of(data)
        if lap is None:
            continue
        if best_lap is None or lap["time_ms"] < best_lap["time_ms"]:
            best_lap = lap
            best_meta = {"timestamp": data.get("timestamp", ""),
                         "session_type": data.get("session_type", ""),
                         "path": str(path)}

    if best_lap is None:
        return None, "no_own_sessions_for_track"

    return {
        "fastest_lap": {"driver": "твой прошлый заезд", **best_lap},
        "event": entry[1],
        "reference_session": best_meta,
    }, None
