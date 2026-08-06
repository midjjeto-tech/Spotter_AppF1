from core.telemetry_adapters import (
    ConnectionChanged,
    F1TelemetryAdapter,
    IRacingTelemetryAdapter,
    TelemetryDelta,
)


class _Decoder:
    HEADER_SIZE = 1
    PACKET_SESSION = 1
    PACKET_LAP_DATA = 2
    PACKET_CAR_TELEMETRY = 3
    PACKET_CAR_STATUS = 4
    PACKET_CAR_DAMAGE = 5
    PACKET_MOTION = 6
    PACKET_TYRE_SETS = 7
    PACKET_FINAL_CLASSIFICATION = 8
    PACKET_SESSION_HISTORY = 9
    PACKET_PARTICIPANTS = 10
    PACKET_EVENT = 11

    @staticmethod
    def parse_header(data):
        return {"packet_id": data[0], "player_car_index": 3, "game_year": 25}

    @staticmethod
    def parse_lap_data(_data):
        return {"positions": {3: 4}}

    @staticmethod
    def parse_player_lap(_data, player):
        return {"position": player + 1}


class _Transport:
    def __init__(self, *_args):
        self.closed = False

    def listen(self):
        yield None, False
        yield bytes([_Decoder.PACKET_LAP_DATA]), True

    def close(self):
        self.closed = True


def test_f1_adapter_decodes_packet_into_domain_delta():
    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777, transport_factory=_Transport, decoder=_Decoder)

    messages = list(adapter.listen())

    assert messages[:2] == [ConnectionChanged(False), ConnectionChanged(True)]
    assert messages[2] == TelemetryDelta(
        "lap_data",
        {"lap_info": {"positions": {3: 4}}, "player_lap": {"position": 4}},
        player_car_index=3,
        game_year=25,
    )


def test_iracing_adapter_emits_same_delta_kinds_without_unknown_f1_fields():
    snapshot = {
        "PlayerCarIdx": 0,
        "CarIdxPosition": [1, 2],
        "CarIdxLap": [4, 4],
        "CarIdxOnPitRoad": [False, False],
        "CarIdxLapDistPct": [0.4, 0.2],
        "Speed": 50.0,
        "Gear": 5,
        "_drivers": [{"CarIdx": 0, "UserName": "Driver", "TeamName": "Team"}],
    }

    messages = list(IRacingTelemetryAdapter()._decode(snapshot))
    deltas = [m for m in messages if isinstance(m, TelemetryDelta)]

    assert [d.kind for d in deltas] == ["lap_data", "car_telemetry", "participants"]
    player_telemetry = deltas[1].payload
    assert player_telemetry["speed"] == 180
    assert player_telemetry["gear"] == "5"
    assert "ers_percent" not in player_telemetry
    assert all(d.game_year == 0 for d in deltas)
