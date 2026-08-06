"""Test builders that cross the engine's normalized telemetry interface.

Raw packet decoding belongs to adapter/packet tests.  Engine scenarios may use
these builders to keep their existing byte fixtures while delivering only
canonical messages to ``F1Engine``.
"""

from core import packets
from core.telemetry_adapters import ConnectionChanged, TelemetryDelta, TelemetryRaceEvent


def set_connection(engine, connected: bool) -> None:
    engine._consume_telemetry_message(ConnectionChanged(connected))


def consume_f1_packet(engine, header: dict, packet_id: int, data: bytes) -> None:
    player = header.get("player_car_index", 255)
    game_year = header.get("game_year", 0)

    if packet_id == packets.PACKET_SESSION:
        message = TelemetryDelta(
            "session", packets.parse_session(data), player, game_year)
    elif packet_id == packets.PACKET_LAP_DATA:
        message = TelemetryDelta(
            "lap_data",
            {
                "lap_info": packets.parse_lap_data(data),
                "player_lap": (
                    packets.parse_player_lap(data, player)
                    if player < 255 else {}
                ),
            },
            player,
            game_year,
        )
    elif packet_id == packets.PACKET_CAR_TELEMETRY:
        payload = (
            packets.parse_player_telemetry(data, player)
            if player < 255 else {}
        )
        message = TelemetryDelta(
            "car_telemetry", payload, player, game_year)
    elif packet_id == packets.PACKET_CAR_STATUS:
        message = TelemetryDelta(
            "car_status",
            {
                "player": (
                    packets.parse_player_status(data, player)
                    if player < 255 else {}
                ),
                "all": packets.parse_car_status_all(data),
            },
            player,
            game_year,
        )
    elif packet_id == packets.PACKET_CAR_DAMAGE:
        message = TelemetryDelta(
            "car_damage",
            {
                "player": (
                    packets.parse_player_damage(data, player)
                    if player < 255 else {}
                ),
                "all": packets.parse_car_damage_all(data),
            },
            player,
            game_year,
        )
    else:
        raise ValueError(f"unsupported F1 test packet id: {packet_id}")

    engine._consume_telemetry_message(message)


def consume_f1_event_packet(engine, data: bytes) -> None:
    event = packets.parse_event(data)
    if event is not None:
        engine._consume_telemetry_message(TelemetryRaceEvent(event))
