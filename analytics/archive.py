"""Atomic JSON read/write layer for game sessions and F1 reference data."""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from config import DATA_DIR

_log = logging.getLogger(__name__)

_DATA = Path(DATA_DIR)
_GAME_SESSIONS = _DATA / "game_sessions"
_RACE_ARCHIVE = _DATA / "race_archive"
_SEASON = _DATA / "season"

# Нормализация типа сессии для архива: и legacy-коды (старые записи писали "R"),
# и читаемые значения engine ("race"/"practice"/...) сводим к единому набору,
# по которому UI фильтрует список сессий.
_SESSION_TYPE_NORMALIZE = {
    "R": "race", "race": "race",
    "Q": "qualifying", "qualifying": "qualifying",
    "P": "practice", "practice": "practice",
    "S": "sprint", "sprint": "sprint",
}


def _normalize_session_type(value) -> str:
    return _SESSION_TYPE_NORMALIZE.get(value, "unknown") if value else "unknown"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# --- Game sessions ---

def save_game_session(data: dict) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    path = _GAME_SESSIONS / f"{ts}.json"
    _atomic_write(path, data)
    return path


def load_game_session(path: str | Path) -> dict | None:
    return _load(Path(path))


def iter_game_sessions():
    """Весь архив заездов целиком, новые первыми: пары (путь, документ).

    Существует ради потребителей, которым нужен не только заголовок сессии.
    Раньше они брали `list_game_sessions()` — а та уже читает и разбирает КАЖДЫЙ
    файл — и следом звали `load_game_session()` на подходящие, то есть
    разбирали архив ДВАЖДЫ. Архив при этом ничем не чистится и растёт с каждой
    гонкой.

    Битый файл пропускается с предупреждением, а не роняет перебор: один
    испорченный заезд не должен лишать пилота всей истории."""
    if not _GAME_SESSIONS.exists():
        return
    for f in sorted(_GAME_SESSIONS.glob("*.json"), reverse=True):
        try:
            d = _load(f)
        except (OSError, json.JSONDecodeError):
            _log.warning("Skipping corrupt or unreadable session file: %s", f)
            continue
        if d is None:
            continue
        yield f, d


def list_game_sessions() -> list[dict]:
    return [{
        "path": str(f),
        "track_name": d.get("track_name"),
        "track_id": d.get("track_id"),
        "timestamp": d.get("timestamp"),
        "final_position": d.get("final_position"),
        "game_year": d.get("game_year"),
        "session_type": _normalize_session_type(d.get("session_type")),
    } for f, d in iter_game_sessions()]


def get_last_race() -> dict | None:
    """Самая свежая сессия с session_type == "race", независимо от трассы.
    None, если в архиве ещё нет ни одной завершённой гонки (первая гонка
    карьеры) — list_game_sessions() уже отсортирован новыми-first, поэтому
    это первое совпадение, без доп. сортировки."""
    for s in list_game_sessions():
        if s.get("session_type") == "race":
            return s
    return None


# --- Season championship results (one JSON per finished race, points included) ---

def save_season_result(data: dict) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    path = _SEASON / f"{ts}.json"
    _atomic_write(path, data)
    return path


def list_season_results(limit: int | None = None) -> list[dict]:
    """Full race records, newest-first, optionally truncated to `limit`."""
    if not _SEASON.exists():
        return []
    files = sorted(_SEASON.glob("*.json"), reverse=True)
    if limit is not None:
        files = files[:limit]
    result: list[dict] = []
    for f in files:
        try:
            d = _load(f)
        except (OSError, json.JSONDecodeError):
            _log.warning("Skipping corrupt season file: %s", f)
            continue
        if d is not None:
            result.append(d)
    return result


# --- F1 reference data ---

def save_f1(track_id: int, year: int, stype: str, data: dict) -> Path:
    path = _RACE_ARCHIVE / f"{year}_{track_id}_{stype}_f1.json"
    _atomic_write(path, data)
    return path


def load_f1(track_id: int, year: int, stype: str) -> dict | None:
    path = _RACE_ARCHIVE / f"{year}_{track_id}_{stype}_f1.json"
    return _load(path)


# --- Compare data ---

def save_compare(
    game_path: str | Path,
    track_id: int,
    data: dict,
) -> Path:
    """Сохранить результат сравнения заезда.

    Параметры `year`/`stype` убраны 2026-08-08: они описывали сезон и тип
    РЕАЛЬНОЙ сессии F1, с которой шло сравнение, а этого источника больше нет
    (см. analytics/loader.py и NOTICE). Эталон теперь однозначен — свой лучший
    заезд на той же трассе, — и различать файлы по сезону не нужно. Имя файла
    из-за этого изменилось; старые *_compare.json читаются по-прежнему, их
    формат внутри не менялся."""
    game_stem = Path(game_path).stem
    path = _RACE_ARCHIVE / f"{game_stem}_{track_id}_own_compare.json"
    _atomic_write(path, data)
    return path


def load_compare(compare_path: str | Path) -> dict | None:
    return _load(Path(compare_path))


# --- Story (post-race recap) ---

def attach_story(path: str | Path, text: str) -> None:
    """Дописать пост-гоночную историю в существующий JSON сессии (read-modify-write).
    Безопасно при отсутствии файла — просто ничего не делает."""
    p = Path(path)
    data = _load(p)
    if data is None:
        return
    data["story"] = text
    _atomic_write(p, data)
