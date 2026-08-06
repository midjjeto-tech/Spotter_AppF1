import json
import urllib.error
import urllib.request

from core.openf1_client import OpenF1Client


def _client(tmp_path):
    return OpenF1Client(cache_dir=tmp_path)


class _FakeResponse:
    """Минимальная имитация http.client.HTTPResponse: используется как context
    manager, .read() отдаёт bytes — как в реальном urllib.request.urlopen()."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_get_session_key_found(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: [{"session_key": 9161}])
    assert cl.get_session_key(2025, "monza") == 9161


def test_get_session_key_forwards_non_race_session_name(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []
    monkeypatch.setattr(
        cl,
        "_fetch",
        lambda path, params: calls.append((path, dict(params))) or [{"session_key": 9160}],
    )

    assert cl.get_session_key(2025, "monza", session_name="Qualifying") == 9160
    assert calls == [("sessions", {
        "year": 2025, "location": "Monza", "session_name": "Qualifying",
    })]


def test_get_session_key_unknown_circuit_returns_none_without_network(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []
    monkeypatch.setattr(cl, "_fetch", lambda path, params: calls.append(1) or [{"session_key": 1}])
    assert cl.get_session_key(2025, "nonexistent_circuit") is None
    assert calls == []          # неизвестная трасса -> сеть не дёргаем вовсе


def test_get_session_key_empty_response_returns_none(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: [])
    assert cl.get_session_key(2025, "monza") is None


def test_get_best_sectors_takes_min_across_laps(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    laps = [
        {"duration_sector_1": 26.966, "duration_sector_2": 38.657, "duration_sector_3": 26.12},
        {"duration_sector_1": 26.5, "duration_sector_2": 39.0, "duration_sector_3": 25.9},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 26500, 2: 38657, 3: 25900}


def test_get_best_sectors_ignores_null_and_zero_sectors(tmp_path, monkeypatch):
    """Регресс-гард: невалидный сектор (None/0) не должен побеждать в MIN()."""
    cl = _client(tmp_path)
    laps = [
        {"duration_sector_1": None, "duration_sector_2": 0, "duration_sector_3": 26.0},
        {"duration_sector_1": 27.0, "duration_sector_2": 38.0, "duration_sector_3": 26.5},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 27000, 2: 38000, 3: 26000}


def test_get_best_sectors_ignores_pit_out_lap(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    laps = [
        {"duration_sector_1": 20.0, "duration_sector_2": 20.0, "duration_sector_3": 20.0,
         "is_pit_out_lap": True},
        {"duration_sector_1": 27.0, "duration_sector_2": 38.0, "duration_sector_3": 26.5},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 27000, 2: 38000, 3: 26500}


def test_get_best_sectors_incomplete_data_returns_none(tmp_path, monkeypatch):
    """Если хотя бы один сектор никогда не валиден — не отдаём частичные данные."""
    cl = _client(tmp_path)
    laps = [{"duration_sector_1": 27.0, "duration_sector_2": None, "duration_sector_3": 26.5}]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) is None


def test_get_best_sectors_none_session_key_returns_none(tmp_path):
    cl = _client(tmp_path)
    assert cl.get_best_sectors(None) is None


def test_get_best_sectors_network_failure_returns_none(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: None)
    assert cl.get_best_sectors(9161) is None


def test_cache_hit_avoids_second_fetch(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []

    def fake_fetch(path, params):
        calls.append(1)
        return [{"session_key": 9161}]

    monkeypatch.setattr(cl, "_fetch", fake_fetch)
    assert cl.get_session_key(2025, "monza") == 9161
    assert cl.get_session_key(2025, "monza") == 9161
    assert len(calls) == 1                              # второй раз — из кэша


def test_fetch_rejects_non_list_json_response(tmp_path, monkeypatch):
    """Регресс-гард: OpenF1 иногда отдаёт HTTP 200 с JSON-объектом вместо массива
    (например тело restriction/error-ответа) — _fetch должен вернуть None, а не
    сырой dict, иначе get_session_key упадёт на sessions[0] (KeyError на dict).
    Мокаем ровно границу сети (urlopen), чтобы реально прогнать тело _fetch, а не
    обойти isinstance-проверку, как случилось бы при моке самого _fetch."""
    cl = _client(tmp_path)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse({"detail": "Live F1 session in progress"}),
    )
    assert cl.get_session_key(2025, "monza") is None


def _raise_http_error(code, body=b"{}"):
    def _raiser(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, None)
    return _raiser


def test_401_sets_blocked_by_live_session_flag(tmp_path, monkeypatch):
    """OpenF1 отдаёт 401 «Live F1 session in progress» анонимным запросам во время
    live-сессии — это НЕ баг, но UI должен уметь отличить это от «нет данных
    вообще» (см. core/f1_benchmark.py::_load_sectors, race.tsx)."""
    cl = _client(tmp_path)
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http_error(401))
    assert cl.blocked_by_live_session is False
    assert cl.get_session_key(2025, "monza") is None
    assert cl.blocked_by_live_session is True


def test_other_http_errors_do_not_set_blocked_flag(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http_error(404))
    assert cl.get_session_key(2025, "monza") is None
    assert cl.blocked_by_live_session is False


def test_successful_fetch_resets_blocked_flag(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    cl.blocked_by_live_session = True   # simulate a prior 401
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse([{"session_key": 9161}]),
    )
    assert cl.get_session_key(2025, "monza") == 9161
    assert cl.blocked_by_live_session is False


def test_pure_cache_hit_does_not_touch_blocked_flag(tmp_path, monkeypatch):
    """Флаг отражает ПОСЛЕДНЮЮ реальную сетевую попытку — чистый кэш-хит (без
    похода в сеть) не должен его трогать."""
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: [{"session_key": 9161}])
    cl.get_session_key(2025, "monza")   # populates cache
    cl.blocked_by_live_session = True   # simulate a stale 401 from elsewhere

    def _fail_if_called(path, params):
        raise AssertionError("should be served from cache, not network")
    monkeypatch.setattr(cl, "_fetch", _fail_if_called)
    assert cl.get_session_key(2025, "monza") == 9161
    assert cl.blocked_by_live_session is True   # untouched


def test_get_session_key_tries_alias_location_when_primary_returns_empty(tmp_path, monkeypatch):
    """OpenF1 переименовал Miami -> 'Miami Gardens' начиная с сезона 2025 (сверено
    с живым API 2026-07-05, см. CONTEXT.md) — вторая попытка по алиасу, если
    основное имя не нашло сессию."""
    cl = _client(tmp_path)
    calls = []

    def fake_fetch(path, params):
        calls.append(dict(params))
        if params.get("location") == "Miami Gardens":
            return [{"session_key": 42}]
        return []

    monkeypatch.setattr(cl, "_fetch", fake_fetch)
    assert cl.get_session_key(2025, "miami") == 42
    assert [c["location"] for c in calls] == ["Miami", "Miami Gardens"]


def test_get_session_key_does_not_try_alias_when_primary_found(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []

    def fake_fetch(path, params):
        calls.append(dict(params))
        return [{"session_key": 9161}]

    monkeypatch.setattr(cl, "_fetch", fake_fetch)
    assert cl.get_session_key(2025, "miami") == 9161
    assert len(calls) == 1


def test_get_session_key_no_alias_for_circuits_without_one(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []
    monkeypatch.setattr(cl, "_fetch", lambda path, params: calls.append(1) or [])
    assert cl.get_session_key(2025, "monza") is None
    assert len(calls) == 1     # нет алиаса для monza -> только один запрос


def test_get_best_sectors_skips_non_dict_lap_entries(tmp_path, monkeypatch):
    """Список с не-dict элементом -> пропускаем его, не крашимся."""
    cl = _client(tmp_path)
    laps = [
        "unexpected string entry",
        {"duration_sector_1": 27.0, "duration_sector_2": 38.0, "duration_sector_3": 26.5},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 27000, 2: 38000, 3: 26500}
