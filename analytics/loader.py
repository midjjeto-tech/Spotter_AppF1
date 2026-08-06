from __future__ import annotations
from pathlib import Path
import config
from analytics.openf1_loader import load_openf1_session

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

_CACHE = Path(config.DATA_DIR) / "fastf1_cache"
_CACHE.mkdir(parents=True, exist_ok=True)

_fastf1_cache_enabled = False


def _ensure_fastf1():
    """Lazy-import fastf1 and enable its disk cache once."""
    global _fastf1_cache_enabled
    import fastf1  # noqa: PLC0415 — intentionally lazy
    if not _fastf1_cache_enabled:
        fastf1.Cache.enable_cache(str(_CACHE))
        _fastf1_cache_enabled = True
    return fastf1


def load_f1_session(track_id: int, year: int = 2025,
                    session_type: str = "R") -> tuple[object | None, str | None]:
    """Returns (session, error). session=None on failure."""
    entry = TRACK_ID_TO_GP.get(track_id)
    if entry is None:
        return None, "no_fastf1_data"

    # OpenF1 provides free historical data from 2023 onwards and is already the
    # application's source for real-F1 sector benchmarks. Prefer it for modern
    # seasons: the upstream F1 live-timing host can be region-blocked (HTTP 403)
    # while FastF1's experimental mirror may not contain the requested session.
    # Calling FastF1 in that state produces one warning per internal data channel
    # and still returns an empty Session because those exceptions are swallowed.
    if year >= 2023:
        return load_openf1_session(track_id, year, session_type)

    _, gp_name = entry
    try:
        ff1 = _ensure_fastf1()
    except ImportError:
        return None, "fastf1_not_installed"
    try:
        session = ff1.get_session(year, gp_name, session_type)
    except Exception as exc:
        return None, f"session_not_found: {exc}"
    try:
        session.load(laps=True, telemetry=False, weather=True, messages=True)
    except Exception as exc:
        # Check for rate limit by class name — avoids importing fastf1.exceptions
        # here (that import is unnecessary and, when fastf1 is absent, would itself
        # raise ImportError and be misreported below as a bogus "load_error").
        if "RateLimitExceededError" in type(exc).__name__:
            return None, "rate_limit"
        return None, f"load_error: {exc}"

    # fastf1 ловит SessionNotAvailableError на КАЖДОМ под-запросе (session_info,
    # driver_info, laps, weather, race_control...) внутри себя и не пробрасывает
    # исключение наружу — session.load() выше отработает "успешно" даже если
    # реально не получено ни результатов, ни кругов. Без этой проверки
    # api_load_f1 в web_server.py считает это успехом и отдаёт фронтенду пустой
    # f1_data (results_top10=[], f1_fastest_ms=None) вместо явной ошибки.
    results = getattr(session, "results", None)
    laps = getattr(session, "laps", None)
    no_results = results is None or results.empty
    no_laps = laps is None or laps.empty
    if no_results and no_laps:
        return None, "no_data_for_session"

    return session, None
