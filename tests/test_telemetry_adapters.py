from core.telemetry_adapters import (
    ConnectionChanged,
    F1TelemetryAdapter,
    IRacingTelemetryAdapter,
    SourceStatus,
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
    PACKET_MOTION_EX = 12
    PACKET_CAR_SETUPS = 13

    @staticmethod
    def parse_player_setup(_data, _player):
        return {"brake_bias": 54, "diff_on_throttle": 75}

    @staticmethod
    def parse_motion_ex(_data):
        return {"slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": -0.4, "fr": 0.0}}

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

    # Первым идёт статус самого источника: сокет открылся. Только потом —
    # «идут ли пакеты». Эти два вопроса намеренно разведены, см. SourceStatus.
    assert messages[0] == SourceStatus("ok")
    assert messages[1:3] == [ConnectionChanged(False), ConnectionChanged(True)]
    assert messages[3] == TelemetryDelta(
        "lap_data",
        {"lap_info": {"positions": {3: 4}}, "player_lap": {"position": 4}},
        player_car_index=3,
        game_year=25,
    )


def test_motion_ex_packet_yields_motion_ex_delta():
    """Пакет 13 доезжает ОТДЕЛЬНЫМ kind: PACKET_MOTION — про взаимное
    расположение машин (споттер), MotionEx — про собственное сцепление (коуч).
    Смешивать их в один kind нельзя, у потребителей нет ничего общего."""
    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777, transport_factory=_Transport, decoder=_Decoder)

    messages = list(adapter._decode(bytes([_Decoder.PACKET_MOTION_EX])))

    assert messages == [TelemetryDelta(
        "motion_ex",
        {"slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": -0.4, "fr": 0.0}},
        player_car_index=3,
        game_year=25,
    )]


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


def test_car_setups_packet_yields_car_setup_delta():
    """Пакет 5 нужен коучу в дебрифе (баланс тормозов, дифференциал), а не в
    живом эфире: сетап посреди заезда не меняется."""
    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777, transport_factory=_Transport, decoder=_Decoder)

    messages = list(adapter._decode(bytes([_Decoder.PACKET_CAR_SETUPS])))

    assert messages == [TelemetryDelta(
        "car_setup", {"brake_bias": 54, "diff_on_throttle": 75},
        player_car_index=3, game_year=25,
    )]
