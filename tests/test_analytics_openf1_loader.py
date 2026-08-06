from analytics.normalizer import normalize
from analytics.openf1_loader import load_openf1_session


class _Client:
    blocked_by_live_session = False

    def get_session_key(self, year, circuit_id, session_name="Race"):
        assert (year, circuit_id, session_name) == (2025, "miami", "Race")
        return 10033

    def get_session_record(self, session_key):
        return {"session_key": session_key, "session_name": "Race", "year": 2025}

    def get_drivers(self, session_key):
        return [
            {"driver_number": 81, "name_acronym": "PIA", "team_name": "McLaren"},
            {"driver_number": 4, "name_acronym": "NOR", "team_name": "McLaren"},
        ]

    def get_session_results(self, session_key):
        return [
            {"position": 1, "driver_number": 81, "gap_to_leader": 0},
            {"position": 2, "driver_number": 4, "gap_to_leader": 4.63},
        ]

    def get_laps(self, session_key):
        return [
            {"driver_number": 81, "lap_number": 52, "lap_duration": 89.746,
             "duration_sector_1": 30.0, "duration_sector_2": 33.0,
             "duration_sector_3": 26.746},
            {"driver_number": 4, "lap_number": 48, "lap_duration": 90.2,
             "duration_sector_1": 30.2, "duration_sector_2": 33.1,
             "duration_sector_3": 26.9},
        ]

    def get_weather(self, session_key):
        return [{"air_temperature": 26.5, "track_temperature": 39.9, "rainfall": 0}]

    def get_race_control(self, session_key):
        return [
            {"message": "SAFETY CAR DEPLOYED"},
            {"message": "CAR 4 - 5 SECOND TIME PENALTY"},
        ]


def test_openf1_adapter_preserves_existing_normalizer_contract():
    session, err = load_openf1_session(30, 2025, "R", client=_Client())

    assert err is None
    data = normalize(session)
    assert data["event"] == "Miami Grand Prix"
    assert data["year"] == 2025
    assert data["session"] == "Race"
    assert data["results_top10"][:2] == [
        {"pos": 1, "driver": "PIA", "team": "McLaren", "gap_s": None,
         "fastest_lap_ms": None},
        {"pos": 2, "driver": "NOR", "team": "McLaren", "gap_s": 4.63,
         "fastest_lap_ms": None},
    ]
    assert data["fastest_lap"] == {
        "driver": "PIA", "lap": 52, "time_ms": 89746,
        "s1_ms": 30000, "s2_ms": 33000, "s3_ms": 26746,
    }
    assert data["best_sectors"] == {"s1_ms": 30000, "s2_ms": 33000, "s3_ms": 26746}
    assert data["weather"] == {"air_temp": 26.5, "track_temp": 39.9, "rainfall": False}
    assert data["safety_cars"] == 1
    assert data["penalties"] == 1


def test_openf1_live_session_block_is_reported_without_fastf1_fallback():
    client = _Client()
    client.blocked_by_live_session = True
    client.get_session_key = lambda *args, **kwargs: None

    session, err = load_openf1_session(30, 2025, "R", client=client)

    assert session is None
    assert err == "openf1_live_session"
