#!/usr/bin/env python3
"""
diag_names.py — проверяет, что в комментаторе никогда не появляется
"машина X" вместо реального имени пилота.

Запуск из корня проекта:
    python diag_names.py
"""
import sys
sys.path.insert(0, ".")

from core.race_state import RaceState
from core.f1_metadata import F1Metadata, F1_2025_BY_NUMBER
from core.packets import TEAM_INFO

BANNED = ("машина", "пилот #")  # эти подстроки недопустимы в финальном имени


def _raw(name, number, team_id=8):
    team_name, team_color = TEAM_INFO.get(team_id, ("?", "#9CA3AF"))
    return {"name": name or None, "team": team_name, "color": team_color, "number": number}


def check(label, results):
    fail = [(idx, n) for idx, n in results if any(b in n.lower() for b in BANNED)]
    if fail:
        print(f"FAIL [{label}]:")
        for idx, n in fail:
            print(f"  vehicle_idx={idx}: '{n}'")
        return False
    print(f"OK   [{label}]")
    return True


def test_real_drivers_no_udp_name():
    """Худший сценарий: имя в UDP пустое, только номер машины."""
    meta = F1Metadata()
    state = RaceState()
    raw = {i: _raw(None, num) for i, num in enumerate(F1_2025_BY_NUMBER.keys())}
    state.update_drivers(meta.enrich_drivers(raw))
    return check(
        "реальные пилоты F1 2025, имя из UDP пустое",
        [(i, state.driver(i)["name"]) for i in raw],
    )


def test_real_drivers_with_udp_name():
    """UDP присылает короткое имя (например, 'Verstappen')."""
    meta = F1Metadata()
    state = RaceState()
    short_names = {
        1: "Verstappen", 4: "Norris", 16: "Leclerc", 44: "Hamilton",
        63: "Russell", 81: "Piastri", 55: "Sainz", 14: "Alonso",
    }
    raw = {
        i: _raw(short_names.get(num), num)
        for i, num in enumerate(F1_2025_BY_NUMBER.keys())
    }
    state.update_drivers(meta.enrich_drivers(raw))
    return check(
        "реальные пилоты F1 2025, короткое имя из UDP",
        [(i, state.driver(i)["name"]) for i in raw],
    )


def test_unknown_number():
    """Машина с нестандартным номером (My Team / моды)."""
    state = RaceState()
    state.update_drivers({0: _raw(None, 99)})  # #99 не в реальной сетке
    name = state.driver(0)["name"]
    ok = name == "#99" and not any(b in name.lower() for b in BANNED)
    print(f"{'OK' if ok else 'FAIL'}   [неизвестный номер #99]: '{name}'")
    return ok


def test_completely_unknown():
    """vehicle_idx без каких-либо данных."""
    state = RaceState()
    name = state.driver(7)["name"]
    ok = name == "#7" and not any(b in name.lower() for b in BANNED)
    print(f"{'OK' if ok else 'FAIL'}   [нет данных, vehicle_idx=7]: '{name}'")
    return ok


def test_none_idx():
    """vehicle_idx=None — особый sentinel."""
    state = RaceState()
    name = state.driver(None)["name"]
    ok = name == "пилот"
    print(f"{'OK' if ok else 'FAIL'}   [vehicle_idx=None]: '{name}'")
    return ok


if __name__ == "__main__":
    results = [
        test_real_drivers_no_udp_name(),
        test_real_drivers_with_udp_name(),
        test_unknown_number(),
        test_completely_unknown(),
        test_none_idx(),
    ]
    print()
    if all(results):
        print("ALL PASS — 'машина X' не появляется")
        sys.exit(0)
    else:
        print("FAIL — см. строки выше")
        sys.exit(1)
