"""Tests for entity resolution helpers."""
import pytest
from core.entity_resolver import resolve_driver_name, resolve_team_name, resolve_opponent_name


# ---------------------------------------------------------------------------
# resolve_driver_name
# ---------------------------------------------------------------------------

def test_resolve_driver_name_from_event_driver_field():
    event = {"driver": "Льюис Хэмилтон", "team": "Ferrari"}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


def test_resolve_driver_name_fallback_from_number():
    # driver field absent or placeholder; number triggers F1_2025_BY_NUMBER lookup
    event = {"driver": "", "number": 44}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


def test_resolve_driver_name_generic_when_unknown():
    event = {"driver": "", "number": 99}  # 99 not in static dict
    assert resolve_driver_name(event) == "гонщик"


def test_resolve_driver_name_hash_placeholder_triggers_lookup():
    # "#44" is a placeholder — should resolve via number 44
    event = {"driver": "#44"}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


# --- 2026 season: car numbers get reused (Verstappen 1->3, Norris ->1) ---

def test_resolve_driver_name_2026_number_1_is_norris():
    event = {"driver": "", "number": 1}
    assert resolve_driver_name(event, 2026) == "Ландо Норрис"


def test_resolve_driver_name_default_game_year_number_1_is_still_verstappen():
    # regression guard: без game_year поведение не должно измениться
    event = {"driver": "", "number": 1}
    assert resolve_driver_name(event) == "Макс Ферстаппен"


def test_resolve_driver_name_no_number_returns_generic():
    event = {}
    assert resolve_driver_name(event) == "гонщик"


def test_resolve_driver_name_generic_label_with_number_triggers_lookup():
    # race_state returns "гонщик" when PARTICIPANTS not yet received,
    # but the event may still carry a number field — resolver must bypass the label
    event = {"driver": "гонщик", "number": 16}
    assert resolve_driver_name(event) == "Шарль Леклер"


def test_resolve_driver_name_pilot_label_with_number_triggers_lookup():
    event = {"driver": "пилот", "number": 44}
    assert resolve_driver_name(event) == "Льюис Хэмилтон"


# ---------------------------------------------------------------------------
# resolve_team_name
# ---------------------------------------------------------------------------

def test_resolve_team_name_from_event():
    event = {"team": "McLaren"}
    assert resolve_team_name(event) == "McLaren"


def test_resolve_team_name_generic_when_absent():
    event = {}
    assert resolve_team_name(event) == "команда"


def test_resolve_team_name_hash_placeholder_returns_generic():
    event = {"team": "#5"}
    assert resolve_team_name(event) == "команда"


# ---------------------------------------------------------------------------
# resolve_opponent_name
# ---------------------------------------------------------------------------

def test_resolve_opponent_name_from_target_field():
    event = {"target": "Макс Ферстаппен"}
    assert resolve_opponent_name(event) == "Макс Ферстаппен"


def test_resolve_opponent_name_generic_when_absent():
    event = {}
    assert resolve_opponent_name(event) == "соперник"


def test_resolve_opponent_name_hash_placeholder_returns_generic():
    event = {"target": "#1"}
    assert resolve_opponent_name(event) == "соперник"
