"""Карьерный эталон из архива сессий (core/coach_ai/reference_store.py)."""
from core.coach_ai import reference_store as store


_CORNER = {"corner_id": 3, "brake_point_m": 100.0, "min_speed_kmh": 120.0,
           "throttle_point_m": 140.0, "duration_ms": 4000}


def _session(track_id: int, lap_ms: int, corners: dict) -> dict:
    return {"track_id": track_id,
            "reference_lap": {"lap_time_ms": lap_ms, "corners": corners}}


def _patch(monkeypatch, sessions: list[dict]):
    """Архив подменяется целиком: живой каталог game_sessions/ тесты трогать не
    должны.

    Подменяется `iter_game_sessions` — единственный проход по архиву, на который
    перешёл загрузчик. Раньше здесь стояли `list_game_sessions` +
    `load_game_session`, и это ровно отражало то, что архив разбирался дважды."""
    monkeypatch.setattr(
        store.archive, "iter_game_sessions",
        lambda: iter([(f"{i}.json", s) for i, s in enumerate(sessions)]))


def test_returns_fastest_lap_for_the_track(monkeypatch):
    _patch(monkeypatch, [
        _session(1, 95000, {"3": _CORNER}),
        _session(1, 91000, {"3": {**_CORNER, "min_speed_kmh": 130.0}}),
        _session(2, 80000, {"3": _CORNER}),
    ])

    ref = store.load_career_reference(track_id=1)

    assert ref.lap_time_ms == 91000
    assert ref.corners[3].min_speed_kmh == 130.0
    assert ref.source == "career"


def test_json_string_keys_become_int_corner_ids(monkeypatch):
    """JSON всегда отдаёт строковые ключи, а сравнение ключует по int."""
    _patch(monkeypatch, [_session(1, 91000, {"3": _CORNER})])

    ref = store.load_career_reference(track_id=1)

    assert set(ref.corners) == {3}


def test_returns_none_when_track_never_visited(monkeypatch):
    _patch(monkeypatch, [_session(2, 80000, {"3": _CORNER})])
    assert store.load_career_reference(track_id=1) is None


def test_the_archive_is_parsed_only_once(monkeypatch):
    """Регрессия на причину правки, а не на её форму.

    Перебор архива идёт по документам, которые уже разобраны, и второй заход за
    тем же файлом означал бы, что двойное чтение вернулось. Архив ничем не
    чистится, поэтому цена этого растёт с каждой гонкой."""
    _patch(monkeypatch, [_session(1, 91000, {"3": _CORNER})])

    def _forbidden(_path):
        raise AssertionError("архив разбирается второй раз")

    monkeypatch.setattr(store.archive, "load_game_session", _forbidden)

    assert store.load_career_reference(track_id=1).lap_time_ms == 91000


def test_sessions_without_reference_lap_are_skipped(monkeypatch):
    """Сессии, записанные до фазы 2, эталона не содержат и не должны ронять
    загрузку."""
    old = {"track_id": 1, "player_laps": [{"lap": 1, "last_lap_ms": 90000}]}
    _patch(monkeypatch, [old, _session(1, 95000, {"3": _CORNER})])

    ref = store.load_career_reference(track_id=1)

    assert ref.lap_time_ms == 95000


def test_corrupt_reference_entry_is_skipped(monkeypatch):
    """Один испорченный файл не должен лишать пилота эталона целиком."""
    _patch(monkeypatch, [
        _session(1, 95000, {"3": {"corner_id": 3}}),   # без метрик
        _session(1, 96000, {"3": _CORNER}),
    ])

    ref = store.load_career_reference(track_id=1)

    assert ref.lap_time_ms == 96000


def test_unreadable_session_does_not_raise(monkeypatch):
    summaries = [{"path": "x", "track_id": 1}]
    monkeypatch.setattr(store.archive, "list_game_sessions", lambda: summaries)
    monkeypatch.setattr(store.archive, "load_game_session", lambda path: None)

    assert store.load_career_reference(track_id=1) is None
