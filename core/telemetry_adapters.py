"""Deep telemetry adapters for F1 UDP and iRacing shared memory.

The adapters own source-specific transport, decoding and dispatch.  Consumers
see only connection changes, typed domain deltas and already-decoded race
events; they never need packet ids, byte offsets or synthetic F1 headers.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable, Iterator, Literal

from core import iracing_packets
from core import packets
from core.iracing_telemetry import IRacingTelemetry
from core.telemetry import Telemetry


DeltaKind = Literal[
    "session",
    "lap_data",
    "car_telemetry",
    "car_status",
    "car_damage",
    "motion",
    "tyre_sets",
    "final_classification",
    "final_classification_grid",
    "session_history",
    "participants",
]


@dataclass(frozen=True, slots=True)
class ConnectionChanged:
    connected: bool


@dataclass(frozen=True, slots=True)
class TelemetryDelta:
    kind: DeltaKind
    payload: Any
    player_car_index: int = 255
    game_year: int = 0


@dataclass(frozen=True, slots=True)
class TelemetryRaceEvent:
    event: dict


TelemetryMessage = ConnectionChanged | TelemetryDelta | TelemetryRaceEvent


class F1TelemetryAdapter:
    """Translate the F1 UDP protocol into source-neutral telemetry messages."""

    def __init__(
        self,
        ip: str,
        port: int,
        *,
        transport_factory: Callable[..., Telemetry] = Telemetry,
        decoder=packets,
    ) -> None:
        self._ip = ip
        self._port = port
        self._transport_factory = transport_factory
        self._decoder = decoder
        self._transport: Telemetry | None = None
        self._closed = threading.Event()

    def listen(self, stop_event: threading.Event | None = None) -> Iterator[TelemetryMessage]:
        transport = self._transport_factory(self._ip, self._port)
        self._transport = transport
        try:
            for data, connected in transport.listen():
                if self._closed.is_set() or (stop_event and stop_event.is_set()):
                    break
                yield ConnectionChanged(connected)
                if not connected or data is None or len(data) < self._decoder.HEADER_SIZE:
                    continue
                yield from self._decode(data)
        finally:
            self.close()
            if self._transport is transport:
                self._transport = None

    def _decode(self, data: bytes) -> Iterator[TelemetryMessage]:
        header = self._decoder.parse_header(data)
        packet_id = header["packet_id"]
        player = header.get("player_car_index", 255)
        game_year = header.get("game_year", 0)
        packet_format = header.get("packet_format", 0)
        # The Season Pack runs inside F1 25 (m_gameYear may stay 25) while its
        # official UDP protocol identifies the 2026 season via packetFormat.
        telemetry_year = 2026 if packet_format >= 2026 else game_year

        if packet_id == self._decoder.PACKET_SESSION:
            yield TelemetryDelta("session", self._decoder.parse_session(data), player, telemetry_year)
        elif packet_id == self._decoder.PACKET_LAP_DATA:
            lap_info = self._decoder.parse_lap_data(data)
            player_lap = self._decoder.parse_player_lap(data, player) if player < 22 else {}
            yield TelemetryDelta(
                "lap_data", {"lap_info": lap_info, "player_lap": player_lap}, player, telemetry_year)
        elif packet_id == self._decoder.PACKET_CAR_TELEMETRY:
            payload = self._decoder.parse_player_telemetry(data, player) if player < 22 else {}
            yield TelemetryDelta("car_telemetry", payload, player, telemetry_year)
        elif packet_id == self._decoder.PACKET_CAR_STATUS:
            payload = {
                "player": self._decoder.parse_player_status(data, player) if player < 22 else {},
                "all": self._decoder.parse_car_status_all(data),
            }
            yield TelemetryDelta("car_status", payload, player, telemetry_year)
        elif packet_id == self._decoder.PACKET_CAR_DAMAGE:
            payload = {
                "player": self._decoder.parse_player_damage(data, player) if player < 22 else {},
                "all": self._decoder.parse_car_damage_all(data),
            }
            yield TelemetryDelta("car_damage", payload, player, telemetry_year)
        elif packet_id == self._decoder.PACKET_MOTION:
            yield TelemetryDelta("motion", self._decoder.parse_motion_all(data), player, telemetry_year)
        elif packet_id == self._decoder.PACKET_TYRE_SETS:
            yield TelemetryDelta("tyre_sets", self._decoder.parse_tyre_sets(data), player, telemetry_year)
        elif packet_id == self._decoder.PACKET_FINAL_CLASSIFICATION:
            payload = self._decoder.parse_final_classification(data, player)
            yield TelemetryDelta("final_classification", payload, player, telemetry_year)
            grid = self._decoder.parse_final_classification_grid(data)
            yield TelemetryDelta("final_classification_grid", grid, player, telemetry_year)
        elif packet_id == self._decoder.PACKET_SESSION_HISTORY:
            yield TelemetryDelta(
                "session_history", self._decoder.parse_session_history(data), player, telemetry_year)
        elif packet_id == self._decoder.PACKET_PARTICIPANTS:
            full_year = (
                2026 if packet_format >= 2026
                else ((2000 + game_year) if 0 < game_year < 100 else game_year)
            )
            yield TelemetryDelta(
                "participants", self._decoder.parse_participants(data, full_year),
                player, telemetry_year,
            )
        elif packet_id == self._decoder.PACKET_EVENT:
            event = self._decoder.parse_event(data)
            if event is not None:
                yield TelemetryRaceEvent(event)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        transport = self._transport
        if transport is not None:
            close = getattr(transport, "close", None)
            if close is not None:
                close()


class IRacingTelemetryAdapter:
    """Translate one iRacing shared-memory snapshot into domain deltas."""

    def __init__(
        self,
        *,
        transport_factory: Callable[..., IRacingTelemetry] = IRacingTelemetry,
        decoder=iracing_packets,
    ) -> None:
        self._transport_factory = transport_factory
        self._decoder = decoder
        self._transport: IRacingTelemetry | None = None
        self._closed = threading.Event()
        self._previous: dict | None = None

    def listen(self, stop_event: threading.Event | None = None) -> Iterator[TelemetryMessage]:
        transport = self._transport_factory()
        self._transport = transport
        try:
            for data, connected in transport.listen():
                if self._closed.is_set() or (stop_event and stop_event.is_set()):
                    break
                yield ConnectionChanged(connected)
                if not connected or data is None:
                    continue
                yield from self._decode(data)
                self._previous = data
        finally:
            self.close()
            if self._transport is transport:
                self._transport = None

    def _decode(self, data: dict) -> Iterator[TelemetryMessage]:
        player = data.get("PlayerCarIdx", 255)
        lap_info = self._decoder.parse_lap_data(data)
        player_lap = self._decoder.parse_player_lap(data, player) if player < 255 else {}
        yield TelemetryDelta(
            "lap_data", {"lap_info": lap_info, "player_lap": player_lap}, player, 0)
        yield TelemetryDelta(
            "car_telemetry", self._decoder.parse_player_telemetry(data, player), player, 0)
        yield TelemetryDelta("participants", self._decoder.parse_participants(data, 0), player, 0)
        for event in self._decoder.synthesize_events(self._previous, data):
            yield TelemetryRaceEvent(event)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        transport = self._transport
        if transport is not None:
            close = getattr(transport, "close", None)
            if close is not None:
                close()
