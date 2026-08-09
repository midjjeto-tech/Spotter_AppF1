"""
core/coach_ai/reference_store.py
=================================
Карьерный эталон — самый быстрый записанный круг на трассе вместе с метриками
его поворотов. Источник тот же, что у `core/career_memory.py`: архив игровых
сессий, без сети и без собственной базы данных.

Тип сессии здесь НЕ фильтруется — в отличие от `career_memory.load()`, который
берёт только гонки. Это осознанно: нормализация в `compare.py` нейтрализует
разницу в топливе и резине, а выбрасывать квалификационные круги значило бы
выбрасывать лучшую технику пилота.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analytics import archive
from core.coach_ai.models import CornerMetrics


@dataclass
class ReferenceLap:
    lap_time_ms: int
    corners: dict[int, CornerMetrics] = field(default_factory=dict)
    source: str = "session"      # "career" | "session"


def parse_corners(raw: dict | None) -> dict[int, CornerMetrics]:
    """Метрики поворотов из сохранённого JSON.

    Ключи в файле всегда строковые, а сравнение ключует по int — приводим
    здесь, по `corner_id` из самой записи. Битую запись пропускаем, а не роняем
    загрузку: один испорченный файл не должен лишать пилота эталона."""
    out: dict[int, CornerMetrics] = {}
    for value in (raw or {}).values():
        try:
            metrics = CornerMetrics.from_dict(value)
        except (KeyError, TypeError):
            continue
        if metrics.usable():
            out[metrics.corner_id] = metrics
    return out


def load_career_reference(track_id: int) -> ReferenceLap | None:
    """Самый быстрый круг на трассе среди всех сессий с записанным эталоном."""
    # iter_game_sessions, а не list_game_sessions + load_game_session: вторая
    # пара разбирала весь архив ДВАЖДЫ (список уже читает каждый файл целиком).
    best: ReferenceLap | None = None
    for _path, data in archive.iter_game_sessions():
        if data.get("track_id") != track_id:
            continue
        raw = data.get("reference_lap") or {}
        lap_ms = raw.get("lap_time_ms") or 0
        if lap_ms <= 0:
            continue
        corners = parse_corners(raw.get("corners"))
        if not corners:
            continue
        if best is None or lap_ms < best.lap_time_ms:
            best = ReferenceLap(lap_time_ms=lap_ms, corners=corners,
                                source="career")
    return best
