"""Замеры поворотов по кругам в файле заезда.

Урок коуча и карта ошибок — это ВЫВОДЫ. Разбор 08-11 упёрся в то, что вход, из
которого они посчитаны, в архив не попадал: потенциал круга обещал 11,4 с при
0,93 с найденных потерь, а проверить, какой поворот и на каком круге дал выброс,
было нечем.
"""
from __future__ import annotations

from core.coach_ai.cost import CornerHistory
from core.coach_ai.models import CornerMetrics
from core.session_recorder import SessionRecorder


def _m(corner_id: int, duration: int) -> CornerMetrics:
    return CornerMetrics(corner_id=corner_id, brake_point_m=120.0,
                         min_speed_kmh=95.0, throttle_point_m=180.0,
                         duration_ms=duration)


def test_history_exports_the_numbers_the_lesson_stands_on():
    history = CornerHistory()
    history.add_lap(1, 92_000, {7: _m(7, 3200), 3: _m(3, 2100)})
    history.add_lap(2, 91_500, {7: _m(7, 3100)})

    rows = history.to_rows()

    assert [r["lap"] for r in rows] == [1, 2]
    assert rows[0]["lap_time_ms"] == 92_000
    # Ключи строками: JSON всё равно их такими сделает, и читатель архива не
    # должен гадать, какой тип он получит.
    assert set(rows[0]["corners"]) == {"3", "7"}
    assert rows[0]["corners"]["7"]["duration_ms"] == 3200
    assert rows[0]["corners"]["7"]["min_speed_kmh"] == 95.0


def test_an_empty_history_exports_nothing_rather_than_a_stub():
    assert CornerHistory().to_rows() == []


def test_the_recorder_carries_them_into_the_session_file(tmp_path, monkeypatch):
    import analytics.archive as archive_mod

    saved: dict = {}
    monkeypatch.setattr(archive_mod, "save_game_session",
                        lambda data: saved.update(data) or tmp_path / "s.json")

    recorder = SessionRecorder()
    recorder.on_lap_complete(lap_num=1, last_lap_ms=92_000,
                             s1_ms=30_000, s2_ms=31_000, s3_ms=31_000)
    history = CornerHistory()
    history.add_lap(1, 92_000, {7: _m(7, 3200)})
    recorder.set_coach_lap_metrics(history.to_rows())

    recorder.finalize(track_id=7, track_name="Monza", session_type="race",
                      final_position=4, events=[])

    assert saved["coach_lap_metrics"][0]["corners"]["7"]["duration_ms"] == 3200


def test_a_session_without_metrics_still_saves(tmp_path, monkeypatch):
    """Замеров нет (коуч выключен, эталона не было) — файл заезда обязан
    сохраниться как раньше, с пустым списком, а не упасть."""
    import analytics.archive as archive_mod

    saved: dict = {}
    monkeypatch.setattr(archive_mod, "save_game_session",
                        lambda data: saved.update(data) or tmp_path / "s.json")

    recorder = SessionRecorder()
    recorder.on_lap_complete(lap_num=1, last_lap_ms=92_000,
                             s1_ms=30_000, s2_ms=31_000, s3_ms=31_000)
    recorder.set_coach_lap_metrics(None)

    recorder.finalize(track_id=7, track_name="Monza", session_type="race",
                      final_position=4, events=[])

    assert saved["coach_lap_metrics"] == []


def test_reset_forgets_them():
    recorder = SessionRecorder()
    recorder.set_coach_lap_metrics([{"lap": 1}])

    recorder.reset()

    assert recorder._lap_metrics == []
