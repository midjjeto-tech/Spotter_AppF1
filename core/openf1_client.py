"""
core/openf1_client.py
======================
Клиент OpenF1 API — секторные эталоны реальных гонок (Real-F1 Benchmark: секторы).

Ergast/Jolpica не отдаёт секторы (core/ergast_client.py) — OpenF1 отдаёт per-lap
duration_sector_1/2/3 для каждого пилота каждой гонки. Используем ТОЛЬКО «лучшие
секторы гонки» (MIN среди валидных кругов) — не пытаемся сопоставить конкретного
пилота/круг с полным-круга-эталоном Ergast (см. design spec, §2 не-цели).

Зависимостей нет: только стандартная библиотека (urllib/json/pathlib), как и
core/ergast_client.py — важно для офлайн-работы и упаковки в EXE.

Кэш практически бессрочный (OPENF1_TTL_DAYS): завершённая гонка не меняется, в
отличие от Ergast, где «текущий сезон» может обновляться.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_USER_AGENT = "SpotterApp/1.0 (F1 commentator)"


class OpenF1Client:
    """Кэширующий, устойчивый к сбоям клиент OpenF1 (секторные эталоны)."""

    BASE_URL = "https://api.openf1.org/v1"

    # Ergast circuit_id (core/f1_benchmark.TRACK_ID_TO_CIRCUIT) → короткое имя
    # трассы в OpenF1 (/v1/sessions?location=...). Строки НЕ гарантированно
    # идентичны Ergast — отдельная таблица.
    CIRCUIT_ID_TO_OPENF1_LOCATION: dict[str, str] = {
        "albert_park": "Melbourne", "shanghai": "Shanghai", "bahrain": "Sakhir",
        "catalunya": "Barcelona", "monaco": "Monaco", "villeneuve": "Montréal",
        "silverstone": "Silverstone", "hungaroring": "Budapest", "spa": "Spa-Francorchamps",
        "monza": "Monza", "marina_bay": "Marina Bay", "suzuka": "Suzuka",
        "yas_marina": "Yas Island", "americas": "Austin", "interlagos": "São Paulo",
        "red_bull_ring": "Spielberg", "rodriguez": "Mexico City", "baku": "Baku",
        "zandvoort": "Zandvoort", "imola": "Imola", "jeddah": "Jeddah", "miami": "Miami",
        "vegas": "Las Vegas", "losail": "Lusail",
    }

    # Сверено с живым API 2026-07-05 (GET /v1/sessions?year=2023..2025&session_name=Race,
    # см. CONTEXT.md «Открытые баги/задачи» #3 — блокировка снята): 4 значения выше
    # исправлены (villeneuve/interlagos — диакритика Montréal/São Paulo; marina_bay —
    # реально "Marina Bay", не "Singapore"; yas_marina — реально "Yas Island", не "Yas
    # Marina Circuit"). Отдельно OpenF1 переименовал Miami → "Miami Gardens" начиная с
    # сезона 2025 — единственный circuit_id с СМЕНОЙ имени между годами, остальные 23
    # стабильны на 2023-2025. Алиас — вторая попытка в get_session_key(), если основное
    # имя не нашло сессию (см. ниже).
    CIRCUIT_ID_OPENF1_LOCATION_ALIASES: dict[str, str] = {
        "miami": "Miami Gardens",
    }

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir or config.OPENF1_CACHE_DIR)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 — кэш не критичен, продолжаем без него
            _log.warning("OpenF1 cache dir unavailable (%s): %s", self.cache_dir, exc)
        self._rate_lock = threading.Lock()
        self._last_request_t = 0.0
        # True после HTTP 401 «Live F1 session in progress» на последней сетевой
        # попытке — отличает «сейчас live-сессия блокирует анонимный доступ» от
        # прочих сбоев (нет трассы в маппинге, сеть недоступна, 404). Трогается
        # ТОЛЬКО реальной сетевой попыткой в _fetch() — чистый кэш-хит его не меняет.
        self.blocked_by_live_session: bool = False

    # ------------------------------------------------------------------ #
    # Низкий уровень: кэш + сеть
    # ------------------------------------------------------------------ #

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, key: str) -> tuple[list | None, bool]:
        """Вернуть (data, fresh). fresh=False, если кэша нет или он протух."""
        cp = self._cache_path(key)
        if not cp.exists():
            return None, False
        try:
            payload = json.loads(cp.read_text(encoding="utf-8"))
            ts = float(payload.get("ts", 0))
            data = payload.get("data")
        except (OSError, ValueError, TypeError):
            return None, False
        fresh = (time.time() - ts) < (config.OPENF1_TTL_DAYS * 86400.0)
        return data, fresh

    def _write_cache(self, key: str, data) -> None:
        cp = self._cache_path(key)
        try:
            tmp = cp.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ts": time.time(), "data": data},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(cp)
        except OSError as exc:  # noqa: BLE001
            _log.debug("OpenF1 cache write failed (%s): %s", cp, exc)

    def _respect_rate_limit(self) -> None:
        """Гарантируем минимум OPENF1_MIN_INTERVAL секунд между сетевыми вызовами."""
        with self._rate_lock:
            wait = config.OPENF1_MIN_INTERVAL - (time.time() - self._last_request_t)
            if wait > 0:
                time.sleep(wait)
            self._last_request_t = time.time()

    def _fetch(self, path: str, params: dict) -> list | None:
        """Один сетевой запрос с retry/backoff. None при неустранимом сбое.

        OpenF1 возвращает JSON-массив записей, не объект. 404 → None без повторов.
        429/5xx/сеть → backoff и повтор. Сидит в фоновом потоке, поэтому
        блокирующий sleep здесь допустим.
        """
        url = f"{self.BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        last_err: str | None = None
        for attempt in range(config.OPENF1_MAX_RETRIES):
            self._respect_rate_limit()
            try:
                with urllib.request.urlopen(req, timeout=config.OPENF1_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.blocked_by_live_session = False
                    return data if isinstance(data, list) else None
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    # Штатный, ожидаемый случай (не баг) — OpenF1 закрывает анонимный
                    # доступ на время live-сессии, включая прошлые сезоны. INFO, не
                    # WARNING; без повторов — сеть не восстановит доступ сама.
                    self.blocked_by_live_session = True
                    _log.info("OpenF1 401 for %s — live session in progress, "
                             "anonymous access blocked", path)
                    return None
                if exc.code == 404:
                    _log.info("OpenF1 404 for %s — no data", path)
                    return None
                if exc.code not in (429, 500, 502, 503, 504):
                    _log.warning("OpenF1 HTTP %s for %s", exc.code, path)
                    return None
                last_err = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_err = str(exc)
            # Промежуточные попытки — тихо (DEBUG), чтобы не спамить WARNING'ами офлайн.
            _log.debug("OpenF1 attempt %d/%d failed for %s: %s",
                       attempt + 1, config.OPENF1_MAX_RETRIES, path, last_err)
            if attempt < config.OPENF1_MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))   # backoff: 0.5, 1.0, 2.0 ...
        # Один итоговый WARNING вместо N — обычный случай «нет сети» не зашумляет лог.
        _log.warning("OpenF1 unreachable for %s after %d attempts: %s",
                     path, config.OPENF1_MAX_RETRIES, last_err)
        return None

    def _get(self, path: str, params: dict) -> list | None:
        """Кэш → (если протух/нет) сеть. При сбое сети отдаём устаревший кэш."""
        key = f"{path}?{urllib.parse.urlencode(sorted(params.items()))}"
        cached, fresh = self._read_cache(key)
        if fresh and cached is not None:
            _log.info("OpenF1 cache hit: %s", key)
            return cached
        data = self._fetch(path, params)
        if data is not None:
            self._write_cache(key, data)
            return data
        # Сеть недоступна, но есть устаревший кэш — лучше старое, чем ничего (штатная
        # деградация, поэтому INFO, а не WARNING).
        if cached is not None:
            _log.info("OpenF1 offline — serving stale cache for %s", key)
            return cached
        return None

    # ------------------------------------------------------------------ #
    # Высокий уровень: session_key + лучшие секторы
    # ------------------------------------------------------------------ #

    def get_session_key(self, year: int, circuit_id: str,
                        session_name: str = "Race") -> int | None:
        """Трасса+год+тип → session_key. None — нет в таблице/нет данных.

        Если основное имя location не нашло сессию — вторая попытка по алиасу
        (CIRCUIT_ID_OPENF1_LOCATION_ALIASES), только для трасс, у которых OpenF1
        менял имя между сезонами (сейчас — только Miami → Miami Gardens, 2025)."""
        location = self.CIRCUIT_ID_TO_OPENF1_LOCATION.get(circuit_id)
        if not location:
            _log.warning("OpenF1: no session_key mapping for %s/%s", year, circuit_id)
            return None
        sessions = self._get("sessions", {"year": year, "location": location,
                                          "session_name": session_name})
        if not sessions:
            alias = self.CIRCUIT_ID_OPENF1_LOCATION_ALIASES.get(circuit_id)
            if alias:
                sessions = self._get("sessions", {"year": year, "location": alias,
                                                  "session_name": session_name})
        if not sessions:
            return None
        return sessions[0].get("session_key")

    def get_session_record(self, session_key: int) -> dict | None:
        records = self._get("sessions", {"session_key": session_key})
        return records[0] if records else None

    def get_drivers(self, session_key: int) -> list | None:
        return self._get("drivers", {"session_key": session_key})

    def get_session_results(self, session_key: int) -> list | None:
        return self._get("session_result", {"session_key": session_key})

    def get_laps(self, session_key: int) -> list | None:
        return self._get("laps", {"session_key": session_key})

    def get_weather(self, session_key: int) -> list | None:
        return self._get("weather", {"session_key": session_key})

    def get_race_control(self, session_key: int) -> list | None:
        return self._get("race_control", {"session_key": session_key})

    def get_best_sectors(self, session_key: int | None) -> dict[int, int] | None:
        """MIN(duration_sector_N) среди валидных кругов гонки. None — нет данных
        ИЛИ хотя бы один сектор ни разу не был валиден (не отдаём частичные данные)."""
        if session_key is None:
            return None
        laps = self.get_laps(session_key)
        if not laps:
            return None
        best: dict[int, float] = {}
        for lap in laps:
            if not isinstance(lap, dict):
                continue
            if lap.get("is_pit_out_lap"):
                continue
            for n in (1, 2, 3):
                dur = lap.get(f"duration_sector_{n}")
                if not dur:            # None или 0 — невалидный сектор
                    continue
                if n not in best or dur < best[n]:
                    best[n] = dur
        if len(best) != 3:
            return None
        result = {n: round(ms * 1000) for n, ms in best.items()}
        _log.info("OpenF1 OK: session=%s sectors=%s", session_key, result)
        return result
