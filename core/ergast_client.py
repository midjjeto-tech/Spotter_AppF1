"""
core/ergast_client.py
=====================
Надёжный клиент Jolpica F1 API (актуальный преемник Ergast).

Задачи модуля:
- Дисковый кэш ответов (DATA_DIR/ergast_cache/*.json) с TTL: 30 дней для архивных
  сезонов, 1 час для текущего — чтобы не дёргать API на каждом запуске.
- Retry с экспоненциальным backoff (сетевые сбои / 429 / 5xx).
- Rate-limit guard (минимум ERGAST_MIN_INTERVAL секунд между запросами).
- Graceful degradation: при отсутствии сети отдаём УСТАРЕВШИЙ кэш, если он есть,
  иначе None — приложение продолжает работать на статическом словаре.

Зависимостей нет: только стандартная библиотека (urllib/json/pathlib). Это важно
для офлайн-работы и упаковки в EXE (PyInstaller) — никаких requests/httpx.

ВАЖНО: сетевые вызовы блокирующие. Их нельзя дёргать из потока телеметрии —
F1Metadata дёргает клиент в ФОНОВОМ потоке и кладёт результат в карту по номеру,
а горячий путь читает только готовую карту (см. core/f1_metadata.py).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import config

_log = logging.getLogger(__name__)

_USER_AGENT = "SpotterApp/1.0 (F1 commentator)"


def _laptime_to_ms(t: str | None) -> int | None:
    """«1:21.046» → 81046, «58.4» → 58400. Мусор/None → None."""
    if not t:
        return None
    try:
        t = t.strip()
        if ":" in t:
            mm, ss = t.split(":", 1)
            return int(mm) * 60000 + round(float(ss) * 1000)
        return round(float(t) * 1000)
    except (ValueError, TypeError):
        return None


class JolpicaClient:
    """Кэширующий, устойчивый к сбоям клиент Jolpica/Ergast F1 API."""

    BASE_URL = "https://api.jolpi.ca/ergast/f1"

    def __init__(self, cache_dir: str | Path | None = None,
                 current_season: str | None = None):
        self.cache_dir = Path(cache_dir or config.ERGAST_CACHE_DIR)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 — кэш не критичен, продолжаем без него
            _log.warning("Ergast cache dir unavailable (%s): %s", self.cache_dir, exc)
        self._current_season = str(current_season or config.F1_SEASON)
        self._rate_lock = threading.Lock()
        self._last_request_t = 0.0

    # ------------------------------------------------------------------ #
    # Низкий уровень: кэш + сеть
    # ------------------------------------------------------------------ #

    def _cache_path(self, path: str) -> Path:
        digest = hashlib.sha1(path.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _ttl_for(self, path: str) -> float:
        """TTL в секундах: текущий сезон обновляем часто, архив — редко."""
        if self._current_season and self._current_season in path:
            return float(config.ERGAST_TTL_CURRENT_SECONDS)
        return float(config.ERGAST_TTL_DAYS) * 86400.0

    def _read_cache(self, path: str) -> tuple[dict | None, bool]:
        """Вернуть (data, fresh). fresh=False, если кэша нет или он протух."""
        cp = self._cache_path(path)
        if not cp.exists():
            return None, False
        try:
            payload = json.loads(cp.read_text(encoding="utf-8"))
            ts = float(payload.get("ts", 0))
            data = payload.get("data")
        except (OSError, ValueError, TypeError):
            return None, False
        fresh = (time.time() - ts) < self._ttl_for(path)
        return data, fresh

    def _write_cache(self, path: str, data: dict) -> None:
        cp = self._cache_path(path)
        try:
            tmp = cp.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ts": time.time(), "data": data},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(cp)
        except OSError as exc:  # noqa: BLE001
            _log.debug("Ergast cache write failed (%s): %s", cp, exc)

    def _respect_rate_limit(self) -> None:
        """Гарантируем минимум ERGAST_MIN_INTERVAL секунд между сетевыми вызовами."""
        with self._rate_lock:
            wait = config.ERGAST_MIN_INTERVAL - (time.time() - self._last_request_t)
            if wait > 0:
                time.sleep(wait)
            self._last_request_t = time.time()

    def _fetch(self, path: str) -> dict | None:
        """Один сетевой запрос с retry/backoff. None при неустранимом сбое.

        404 → None без повторов. 429/5xx/сеть → backoff и повтор. Сидит в фоновом
        потоке, поэтому блокирующий sleep здесь допустим.
        """
        url = f"{self.BASE_URL}/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        last_err: str | None = None
        for attempt in range(config.ERGAST_MAX_RETRIES):
            self._respect_rate_limit()
            try:
                with urllib.request.urlopen(req, timeout=config.ERGAST_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    _log.info("Ergast 404 for %s — no data", path)
                    return None
                if exc.code not in (429, 500, 502, 503, 504):
                    _log.warning("Ergast HTTP %s for %s", exc.code, path)
                    return None
                last_err = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_err = str(exc)
            # Промежуточные попытки — тихо (DEBUG), чтобы не спамить WARNING'ами офлайн.
            _log.debug("Ergast attempt %d/%d failed for %s: %s",
                       attempt + 1, config.ERGAST_MAX_RETRIES, path, last_err)
            if attempt < config.ERGAST_MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))   # backoff: 0.5, 1.0, 2.0 ...
        # Один итоговый WARNING вместо N — обычный случай «нет сети» не зашумляет лог.
        _log.warning("Ergast unreachable for %s after %d attempts: %s",
                     path, config.ERGAST_MAX_RETRIES, last_err)
        return None

    def get_json(self, path: str) -> dict | None:
        """Кэш → (если протух/нет) сеть. При сбое сети отдаём устаревший кэш."""
        cached, fresh = self._read_cache(path)
        if fresh and cached is not None:
            _log.info("Ergast cache hit: %s", path)
            return cached

        data = self._fetch(path)
        if data is not None:
            self._write_cache(path, data)
            return data

        # Сеть недоступна, но есть устаревший кэш — лучше старое, чем ничего (это
        # штатная деградация, поэтому INFO, а не WARNING).
        if cached is not None:
            _log.info("Ergast offline — serving stale cache for %s", path)
            return cached
        return None

    # ------------------------------------------------------------------ #
    # Высокий уровень: пилоты и команды
    # ------------------------------------------------------------------ #

    @staticmethod
    def _drivers_from(data: dict | None) -> list[dict]:
        try:
            return data["MRData"]["DriverTable"]["Drivers"]  # type: ignore[index]
        except (KeyError, TypeError):
            return []

    def get_current_drivers(self, season: str | int | None = None) -> list[dict]:
        """Список пилотов сезона (Driver-объекты Ergast). [] при сбое."""
        season = str(season or self._current_season)
        return self._drivers_from(self.get_json(f"{season}/drivers.json"))

    def get_driver_by_number(self, number: int | None,
                             season: str | int | None = None) -> dict | None:
        """Пилот по постоянному номеру машины. None если не найден."""
        if number is None:
            return None
        try:
            number = int(number)
        except (TypeError, ValueError):
            return None
        for d in self.get_current_drivers(season):
            pn = d.get("permanentNumber")
            if pn is not None and str(pn) == str(number):
                return d
        return None

    def get_driver(self, driver_id: str) -> dict | None:
        """Пилот по driverId (verstappen, leclerc …). None если не найден."""
        if not driver_id:
            return None
        return next(iter(self._drivers_from(self.get_json(f"drivers/{driver_id}.json"))), None)

    def search_driver(self, family_name: str,
                      season: str | int | None = None) -> dict | None:
        """Пилот по фамилии (без учёта регистра). None если не найден."""
        if not family_name:
            return None
        needle = family_name.strip().lower()
        for d in self.get_current_drivers(season):
            if str(d.get("familyName", "")).lower() == needle:
                return d
        return None

    def get_constructors(self, season: str | int | None = None) -> list[dict]:
        """Список команд сезона (Constructor-объекты Ergast). [] при сбое."""
        season = str(season or self._current_season)
        data = self.get_json(f"{season}/constructors.json")
        try:
            return data["MRData"]["ConstructorTable"]["Constructors"]  # type: ignore[index]
        except (KeyError, TypeError):
            return []

    # ------------------------------------------------------------------ #
    # Высокий уровень: эталонные времена трассы (Real-F1 Benchmark)
    # ------------------------------------------------------------------ #

    def get_circuit_fastest_lap(self, year, circuit_id: str) -> dict | None:
        """Быстрейший круг гонки на трассе: {"driver": familyName, "time_ms": int} | None."""
        if not circuit_id:
            return None
        data = self.get_json(f"{year}/circuits/{circuit_id}/results.json")
        try:
            races = data["MRData"]["RaceTable"]["Races"]  # type: ignore[index]
        except (KeyError, TypeError):
            return None
        if not races:
            return None
        best: dict | None = None
        for r in races[0].get("Results", []):
            fl = r.get("FastestLap") or {}
            ms = _laptime_to_ms((fl.get("Time") or {}).get("time"))
            if ms is None:
                continue
            surname = (r.get("Driver") or {}).get("familyName")
            if str(fl.get("rank")) == "1":
                return {"driver": surname, "time_ms": ms}
            if best is None or ms < best["time_ms"]:
                best = {"driver": surname, "time_ms": ms}
        return best

    def get_circuit_pole(self, year, circuit_id: str) -> dict | None:
        """Фолбэк: поул-тайм (лучшее из Q3→Q2→Q1 у P1). {"driver","time_ms"} | None."""
        if not circuit_id:
            return None
        data = self.get_json(f"{year}/circuits/{circuit_id}/qualifying.json")
        try:
            races = data["MRData"]["RaceTable"]["Races"]  # type: ignore[index]
        except (KeyError, TypeError):
            return None
        if not races:
            return None
        for q in races[0].get("QualifyingResults", []):
            if str(q.get("position")) == "1":
                for k in ("Q3", "Q2", "Q1"):
                    ms = _laptime_to_ms(q.get(k))
                    if ms is not None:
                        return {"driver": (q.get("Driver") or {}).get("familyName"),
                                "time_ms": ms}
        return None


# Совместимость: исторически в проекте «Ergast».
ErgastClient = JolpicaClient
