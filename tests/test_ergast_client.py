"""
tests/test_ergast_client.py
===========================
Тесты кэширующего Jolpica-клиента: кэш, TTL, graceful-offline, парсинг, rate-limit.
Сеть не дёргаем (мокаем _fetch). Живой smoke — только при SPOTTER_LIVE_TESTS=1.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from core.ergast_client import JolpicaClient, ErgastClient


def _client(tmp_path) -> JolpicaClient:
    return JolpicaClient(cache_dir=tmp_path, current_season="2025")


# --- кэш + сеть --------------------------------------------------------------

def test_get_json_caches_and_avoids_refetch(tmp_path, monkeypatch):
    c = _client(tmp_path)
    calls = {"n": 0}

    def fake_fetch(path):
        calls["n"] += 1
        return {"hello": "world", "path": path}

    monkeypatch.setattr(c, "_fetch", fake_fetch)

    first = c.get_json("2024/drivers.json")   # архивный сезон → длинный TTL
    second = c.get_json("2024/drivers.json")
    assert first == second == {"hello": "world", "path": "2024/drivers.json"}
    assert calls["n"] == 1, "second call must be a cache hit"


def test_cache_file_written_to_disk(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "_fetch", lambda path: {"ok": True})
    c.get_json("2024/drivers.json")
    files = list(tmp_path.glob("*.json"))
    assert files, "expected a cache file on disk"
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["data"] == {"ok": True}
    assert "ts" in payload


def test_current_season_uses_short_ttl(tmp_path):
    c = _client(tmp_path)
    assert c._ttl_for("2025/drivers.json") < c._ttl_for("2020/drivers.json")


def test_stale_cache_served_when_offline(tmp_path, monkeypatch):
    c = _client(tmp_path)
    # Запишем заведомо протухший кэш вручную.
    cp = c._cache_path("2025/drivers.json")
    cp.write_text(json.dumps({"ts": time.time() - 10 * 86400, "data": {"stale": 1}}),
                  encoding="utf-8")
    monkeypatch.setattr(c, "_fetch", lambda path: None)   # сеть «упала»
    out = c.get_json("2025/drivers.json")
    assert out == {"stale": 1}, "stale cache must be served when network is down"


def test_returns_none_when_no_cache_and_network_down(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "_fetch", lambda path: None)
    assert c.get_json("2025/drivers.json") is None


# --- высокоуровневые методы --------------------------------------------------

_DRIVERS_DATA = {
    "MRData": {"DriverTable": {"Drivers": [
        {"driverId": "verstappen", "permanentNumber": "1",
         "givenName": "Max", "familyName": "Verstappen", "nationality": "Dutch"},
        {"driverId": "leclerc", "permanentNumber": "16",
         "givenName": "Charles", "familyName": "Leclerc", "nationality": "Monegasque"},
    ]}}
}


def test_get_current_drivers_parses_list(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "get_json", lambda path: _DRIVERS_DATA)
    drivers = c.get_current_drivers()
    assert len(drivers) == 2
    assert drivers[0]["familyName"] == "Verstappen"


def test_get_driver_by_number(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "get_json", lambda path: _DRIVERS_DATA)
    d = c.get_driver_by_number(16)
    assert d is not None and d["driverId"] == "leclerc"


def test_get_driver_by_number_unknown_returns_none(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "get_json", lambda path: _DRIVERS_DATA)
    assert c.get_driver_by_number(99) is None
    assert c.get_driver_by_number(None) is None


def test_search_driver_by_family_name(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "get_json", lambda path: _DRIVERS_DATA)
    assert c.search_driver("verstappen")["driverId"] == "verstappen"   # case-insensitive
    assert c.search_driver("nobody") is None


def test_malformed_payload_yields_empty_list(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "get_json", lambda path: {"unexpected": True})
    assert c.get_current_drivers() == []
    assert c.get_driver_by_number(1) is None


# --- rate limit --------------------------------------------------------------

def test_rate_limit_enforces_min_interval(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "ERGAST_MIN_INTERVAL", 0.1)
    c = _client(tmp_path)
    c._respect_rate_limit()           # первый вызов «бесплатный»
    t0 = time.time()
    c._respect_rate_limit()           # второй должен подождать ~0.1с
    assert time.time() - t0 >= 0.09


# --- совместимость / live smoke ---------------------------------------------

def test_ergast_alias_is_jolpica():
    assert ErgastClient is JolpicaClient


@pytest.mark.skipif(os.environ.get("SPOTTER_LIVE_TESTS") != "1",
                    reason="live network test — set SPOTTER_LIVE_TESTS=1 to run")
def test_live_smoke_get_current_drivers(tmp_path):
    c = _client(tmp_path)
    drivers = c.get_current_drivers("2024")
    assert isinstance(drivers, list) and len(drivers) > 10
