import core.engine as eng_mod
from core.engine import F1Engine
from tests.telemetry import consume_f1_event_packet


def test_race_feed_starts_disabled_by_default(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e._race_feed is None


def test_apply_settings_racefeed_enabled_true_starts_it(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    assert e._race_feed is not None
    e.apply_settings({"racefeed_enabled": False})  # cleanup: stop the thread


def test_apply_settings_racefeed_enabled_false_stops_it(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    assert e._race_feed is not None
    e.apply_settings({"racefeed_enabled": False})
    assert e._race_feed is None


def test_hot_disable_keeps_ownership_when_worker_has_not_stopped(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})

    class StillStopping:
        def stop(self):
            return False

    worker = StillStopping()
    e._race_feed = worker

    e._set_racefeed_enabled(False)

    assert e._race_feed is worker


def test_enqueue_event_does_not_touch_racefeed_when_disabled(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e._race_feed is None
    # Should not raise even though racefeed is off — the branch must be skipped.
    e._commentary_events.publish({"event_code": "PENA", "driver": "Norris", "vehicle_idx": 4})
    assert e._race_feed is None


def test_enqueue_event_forwards_to_racefeed_when_enabled(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    received = []
    monkeypatch.setattr(e._race_feed, "ingest", lambda event: received.append(event))

    e._commentary_events.publish({"event_code": "PENA", "driver": "Norris", "vehicle_idx": 4})

    assert len(received) == 1
    assert received[0].event_code == "PENA"
    assert received[0].session_type == e._session_type
    e.apply_settings({"racefeed_enabled": False})  # cleanup


def test_player_overtake_is_identified_from_two_car_event_fields(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e._player_car_index = 4
    e.apply_settings({"racefeed_enabled": True})
    received = []
    monkeypatch.setattr(e._race_feed, "ingest", received.append)

    e._commentary_events.publish({
        "event_code": "OVTK", "overtaking_idx": 4,
        "being_overtaken_idx": 7, "driver": "Norris", "target": "Russell",
    })
    e.apply_settings({"racefeed_enabled": False})

    assert received[0].is_player is True


def test_teammate_event_is_identified_for_players_garage(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e._player_car_index = 4
    e.race_state.update_drivers({
        4: {"name": "Norris", "team": "McLaren", "color": "#f60"},
    })
    e.apply_settings({"racefeed_enabled": True})
    received = []
    monkeypatch.setattr(e._race_feed, "ingest", received.append)

    e._commentary_events.publish({
        "event_code": "FTLP", "vehicle_idx": 5,
        "driver": "Piastri", "team": "McLaren",
    })
    e.apply_settings({"racefeed_enabled": False})

    assert received[0].is_player_team is True


def test_racefeed_state_snapshot_reads_player_fields(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e._player_fuel = 42.0
    e._player_gap_front = 1500
    snap = e._racefeed_state_snapshot()
    assert snap["player_fuel"] == 42.0
    assert snap["gap_front_ms"] == 1500
    assert snap["session_type"] == e._session_type


def test_racefeed_snapshot_exposes_pre_race_prediction_facts(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e._session_type = "race"
    e._track_id = 13
    e._player_car_index = 4
    e._positions = {4: 6, 5: 9}
    e._current_grid = [
        {"vehicle_idx": 4, "team": "Ferrari"},
        {"vehicle_idx": 5, "team": "Ferrari"},
    ]
    e.race_state.update_drivers({
        4: {"name": "Артём", "team": "Ferrari", "color": "#e00"},
        5: {"name": "Леклер", "team": "Ferrari", "color": "#e00"},
    })
    e._rain_forecast = {"minutes": 15, "rain_pct": 60}

    snap = e._racefeed_state_snapshot()

    assert snap["track_id"] == 13
    assert snap["player_driver"] == "Артём"
    assert snap["player_position"] == 6
    assert snap["teammate_driver"] == "Леклер"
    assert snap["teammate_position"] == 9
    assert snap["rain_forecast"]["rain_pct"] == 60


def test_get_racefeed_state_disabled_by_default(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e.get_racefeed_state() == {"enabled": False, "posts": []}


def _event_buf(code: str) -> bytes:
    """Same helper tests/test_engine_session_active.py uses to build a raw
    PACKET_EVENT buffer that _handle_event_packet/_parse_event can read."""
    from core.packets import HEADER_SIZE
    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = code.encode("ascii")
    return bytes(buf)


def test_start_picks_up_already_enabled_setting(monkeypatch):
    """F1Engine.start() itself spawns 5 real daemon threads and is never
    exercised elsewhere in this test suite (grepped: no other test calls it)
    — one of those threads (_telemetry_loop) binds a real UDP socket via
    Telemetry(config.UDP_IP, config.UDP_PORT) and loops forever with no way
    to join/stop it from a test. Calling the real start() here would leak a
    bound port and 5 daemon threads for the rest of the pytest session (risk
    of port-already-in-use flakiness in later tests). So instead we exercise
    exactly the one new line start() adds (Step 7 of the wiring plan) —
    self._set_racefeed_enabled(bool(self.settings.get("racefeed_enabled",
    False))) — directly, against an engine constructed with the setting
    already True (simulating a resumed session), without paying for the
    other 5 unrelated threads."""
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"racefeed_enabled": True})
    e._set_racefeed_enabled(bool(e.settings.get("racefeed_enabled", False)))
    assert e._race_feed is not None
    e._race_feed.stop()  # cleanup


def test_ssta_event_triggers_racefeed_reset(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    calls = []
    monkeypatch.setattr(
        e._race_feed, "reset", lambda **kwargs: calls.append(kwargs)
    )

    consume_f1_event_packet(e, _event_buf("SSTA"))

    assert calls == [{"session_type": e._session_type}]
    e.apply_settings({"racefeed_enabled": False})  # cleanup


def test_start_lights_lock_the_prediction_ticket(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})

    class Feed:
        def __init__(self):
            self.locked = 0

        def lock_prediction(self):
            self.locked += 1

        def ingest(self, _event):
            pass

    feed = Feed()
    e._race_feed = feed

    consume_f1_event_packet(e, _event_buf("STLG"))

    assert feed.locked == 1
