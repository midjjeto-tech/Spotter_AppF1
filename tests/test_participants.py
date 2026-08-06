"""Tests for parse_participants — driver number/name/team extraction.

The real bug (F1 25): PacketParticipantsData's ParticipantData struct grew between
game versions (livery colours appended), so a hardcoded 60-byte stride drifts the
read for every car after the first → garbage teamId/raceNumber → "гонщик". The
parser must DERIVE the stride from the packet length (array is a fixed [22]).
"""
import struct

import pytest

from core import packets
from core.packets import HEADER_SIZE, PARTICIPANTS_ARRAY_LEN


def _participants_packet(cars: dict[int, tuple[int, int, str]], stride: int) -> bytes:
    """Build a PacketParticipantsData with a chosen ParticipantData stride.

    cars: {idx: (team_id, race_number, name)}. Array is always 22 fixed slots.
    Identity fields placed at their stable offsets: teamId@3, raceNumber@5, name@7.
    """
    header = b"\x00" * HEADER_SIZE
    num_active = bytes([len(cars)])
    array = bytearray(stride * PARTICIPANTS_ARRAY_LEN)
    for idx, (team_id, race_no, name) in cars.items():
        base = idx * stride
        array[base + 3] = team_id
        array[base + 5] = race_no
        nb = name.encode("utf-8")[: stride - 8] + b"\x00"
        array[base + 7: base + 7 + len(nb)] = nb
    return header + num_active + bytes(array)


# Mercedes=0, Ferrari=1, McLaren=8 (from TEAM_INFO)
_GRID = {
    0: (8, 81, "PIASTRI"),    # McLaren
    1: (0, 63, "RUSSELL"),    # Mercedes
    2: (1, 16, "LECLERC"),    # Ferrari
    3: (8, 4, "NORRIS"),      # McLaren
}


@pytest.mark.parametrize("stride", [60, 70, 80, 112])
def test_all_cars_parse_regardless_of_struct_size(stride):
    """Self-correcting stride: every car reads correctly whatever the struct size.

    With the old hardcoded 60-byte stride this drifts and fails for stride != 60.
    """
    pkt = _participants_packet(_GRID, stride)
    out = packets.parse_participants(pkt)
    assert out[0]["number"] == 81 and out[0]["team"] == "McLaren"
    assert out[1]["number"] == 63 and out[1]["team"] == "Mercedes"
    assert out[2]["number"] == 16 and out[2]["team"] == "Ferrari"
    assert out[3]["number"] == 4 and out[3]["name"] == "NORRIS"


@pytest.mark.parametrize("stride", [60, 80])
def test_later_cars_not_garbage(stride):
    """The screenshot symptom: later cars had teamId=69 and unresolved numbers.
    No car should land on an out-of-range teamId when the stride is correct."""
    pkt = _participants_packet(_GRID, stride)
    out = packets.parse_participants(pkt)
    for idx, info in out.items():
        # every team in _GRID is a real one — none should fall through to "Команда #N"
        assert not info["team"].startswith("Команда #"), (
            f"car {idx} drifted to bogus team {info['team']!r}"
        )


def test_empty_ai_name_falls_back_to_number():
    """AI cars send all-zero name bytes; resolution must keep the number."""
    pkt = _participants_packet({0: (0, 63, "")}, stride=80)
    out = packets.parse_participants(pkt)
    assert out[0]["name"] is None
    assert out[0]["number"] == 63


def test_num_active_limits_parsed_cars():
    pkt = _participants_packet({0: (8, 81, "PIASTRI"), 1: (0, 63, "RUSSELL")}, stride=72)
    out = packets.parse_participants(pkt)
    assert set(out.keys()) == {0, 1}


def test_truncated_packet_does_not_crash():
    pkt = _participants_packet(_GRID, stride=80)[: HEADER_SIZE + 50]
    out = packets.parse_participants(pkt)
    assert isinstance(out, dict)  # no exception, partial or empty result


def test_2026_season_pack_participant_layout():
    """Official v10 layout: 24 slots, uint16 ids and shifted identity fields."""
    stride = 60
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<H", header, 0, 2026)
    array = bytearray(stride * 24)
    # ai@0, driverId@1:u16, networkId@3:u16, teamId@5:u16,
    # myTeam@7, raceNumber@8, nationality@9, name@10.
    struct.pack_into("<H", array, 5, 230)
    array[8] = 77
    array[10:17] = b"BOTTAS\x00"
    base = stride
    struct.pack_into("<H", array, base + 5, 220)
    array[base + 8] = 63
    array[base + 10:base + 18] = b"RUSSELL\x00"
    packet = bytes(header) + bytes([2]) + bytes(array)

    out = packets.parse_participants(packet, game_year=2026)

    assert out[0]["number"] == 77
    assert out[0]["team_id"] == 230
    assert out[0]["team"] == "Cadillac"
    assert out[1]["number"] == 63
    assert out[1]["team"] == "Mercedes"


def test_high_team_id_resolves_via_2026_table_even_on_classic_format_packet():
    """Real-world bug (reported by user, live game): F1 25 Season Pack v1.24 can
    emit teamId in the 220-230 range (already mapped in TEAM_INFO_2026) even on
    a packet that doesn't advertise packetFormat>=2026 and whose game_year isn't
    2026 either. team_info_for_year() then picks plain TEAM_INFO, which has no
    entry for 220-230, and the team name silently degraded to "Команда #228"
    instead of resolving via the table that already has the correct name."""
    pkt = _participants_packet({0: (228, 4, "NORRIS"), 1: (221, 16, "LECLERC")}, stride=80)
    out = packets.parse_participants(pkt, game_year=25)
    assert out[0]["team"] == "McLaren"
    assert out[1]["team"] == "Ferrari"


def test_rebrand_team_ids_resolve_correctly_pre_2026():
    pkt = _participants_packet({0: (9, 12, "HULKENBERG"), 1: (6, 22, "TSUNODA")}, stride=80)
    out = packets.parse_participants(pkt, game_year=2025)
    assert out[0]["team"] == "Sauber"
    assert out[1]["team"] == "RB"


def test_rebrand_team_ids_resolve_correctly_2026():
    pkt = _participants_packet({0: (9, 12, "HULKENBERG"), 1: (6, 22, "TSUNODA")}, stride=80)
    out = packets.parse_participants(pkt, game_year=2026)
    assert out[0]["team"] == "Audi"
    assert out[1]["team"] == "Racing Bulls"
