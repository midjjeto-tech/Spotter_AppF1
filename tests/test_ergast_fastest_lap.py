from core.ergast_client import JolpicaClient, _laptime_to_ms


def test_laptime_to_ms():
    assert _laptime_to_ms("1:21.046") == 81046
    assert _laptime_to_ms("58.4") == 58400
    assert _laptime_to_ms(None) is None
    assert _laptime_to_ms("garbage") is None


class _FakeClient(JolpicaClient):
    def __init__(self, payload):           # без super().__init__ — сеть/кэш не нужны
        self._payload = payload

    def get_json(self, path):
        return self._payload


def _results(*entries):
    return {"MRData": {"RaceTable": {"Races": [{"Results": list(entries)}]}}}


def test_fastest_lap_picks_rank_1():
    payload = _results(
        {"Driver": {"familyName": "Norris"},
         "FastestLap": {"rank": "2", "Time": {"time": "1:22.000"}}},
        {"Driver": {"familyName": "Verstappen"},
         "FastestLap": {"rank": "1", "Time": {"time": "1:21.046"}}},
    )
    assert _FakeClient(payload).get_circuit_fastest_lap(2025, "monza") == \
        {"driver": "Verstappen", "time_ms": 81046}


def test_fastest_lap_none_when_no_data():
    assert _FakeClient({"MRData": {"RaceTable": {"Races": []}}}).get_circuit_fastest_lap(2025, "monza") is None
    assert _FakeClient({}).get_circuit_fastest_lap(2025, "") is None


def test_pole_picks_best_quali_time():
    payload = {"MRData": {"RaceTable": {"Races": [{"QualifyingResults": [
        {"position": "1", "Driver": {"familyName": "Leclerc"},
         "Q1": "1:20.5", "Q2": "1:20.1", "Q3": "1:19.8"},
    ]}]}}}
    assert _FakeClient(payload).get_circuit_pole(2025, "monza") == \
        {"driver": "Leclerc", "time_ms": 79800}
