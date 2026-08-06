"""core/radio/situations.py — situation_id и dedupe_key.

Два разных ключа с разным смыслом (см. плана «Ключевые проектные решения»):
  situation_id — личность продолжающейся ситуации (группировка, закрытие);
  dedupe_key   — личность КОНКРЕТНОГО высказывания о ней (подавление повтора).
Один situation_id с разными dedupe_key = смысловое изменение, говорим снова.
"""
import pytest

from core.radio import situations
from core.radio.plumbing import attach as situations_plumbing


def _sid(event, **kwargs):
    return situations.situation_id(event, **kwargs)


def _dkey(event, **kwargs):
    return situations.dedupe_key(event, **kwargs)


# ── Формат из ТЗ §9 ──────────────────────────────────────────────────────────

def test_spotter_situation_format():
    event = {"event_code": "SPOTTER_CAR_RIGHT", **situations_plumbing(neighbour_idx=7)}
    assert _sid(event) == "spotter:right:vehicle_7"


def test_damage_situation_format():
    event = {"event_code": "DAMAGE_WING"}
    assert _sid(event, lap=12) == "damage:front_wing:lap_12"


def test_box_call_situation_format():
    event = {"event_code": "STRAT_BOX_CALL_2", **situations_plumbing(box_call_window=2)}
    assert _sid(event) == "box_call:window_2"


def test_weather_situation_format():
    event = {"event_code": "ENGINEER_RAIN_ADVISORY", **situations_plumbing(rain_front_id=1)}
    assert _sid(event) == "weather:rain_front_1"


def test_battle_situation_format():
    event = {"event_code": "BATTLE", "target": "Норрис"}
    assert _sid(event, lap=18) == "battle:norris:lap_18"


# ── Стабильность: повторная телеметрия не создаёт новую ситуацию ─────────────

def test_repeated_spotter_telemetry_keeps_one_situation():
    event = {"event_code": "SPOTTER_CAR_RIGHT", **situations_plumbing(neighbour_idx=7)}
    assert _sid(event) == _sid(dict(event))


def test_different_neighbour_is_a_different_situation():
    right_7 = {"event_code": "SPOTTER_CAR_RIGHT", **situations_plumbing(neighbour_idx=7)}
    right_9 = {"event_code": "SPOTTER_CAR_RIGHT", **situations_plumbing(neighbour_idx=9)}
    assert _sid(right_7) != _sid(right_9)


def test_other_side_is_a_different_situation():
    right = {"event_code": "SPOTTER_CAR_RIGHT", **situations_plumbing(neighbour_idx=7)}
    left = {"event_code": "SPOTTER_CAR_LEFT", **situations_plumbing(neighbour_idx=7)}
    assert _sid(right) != _sid(left)


def test_same_damage_on_a_later_lap_is_a_new_situation():
    event = {"event_code": "DAMAGE_WING"}
    assert _sid(event, lap=12) != _sid(event, lap=13)


def test_battle_with_another_rival_is_a_new_situation():
    norris = {"event_code": "BATTLE", "target": "Норрис"}
    albon = {"event_code": "BATTLE", "target": "Албон"}
    assert _sid(norris, lap=18) != _sid(albon, lap=18)


def test_missing_identity_data_degrades_but_never_raises():
    for code in ("SPOTTER_CAR_RIGHT", "DAMAGE_WING", "BATTLE",
                 "STRAT_BOX_CALL_1", "ENGINEER_RAIN_ADVISORY"):
        assert isinstance(_sid({"event_code": code}), str)


def test_codes_without_a_situation_return_none():
    """Самостоятельные новости (финиш, рекорд круга) не являются «ситуацией» —
    их не нужно ни группировать, ни закрывать."""
    for code in ("CHQF", "FTLP", "SSTA", "AMBIENT", "STORY"):
        assert _sid({"event_code": code}) is None


# ── dedupe_key: подавление без потери смысловых изменений ────────────────────

def test_repeated_spotter_statement_has_the_same_dedupe_key():
    event = {"event_code": "SPOTTER_CAR_RIGHT", **situations_plumbing(neighbour_idx=7)}
    assert _dkey(event) == _dkey(dict(event))


def test_safety_car_stages_share_a_situation_but_differ_in_dedupe_key():
    """Одна фаза SC — одна ситуация, но «выехал» / «уходит» / «чисто» это три
    разных высказывания. Дедуп по situation_id проглотил бы два из них."""
    deployed = {"event_code": "SAFETY_CAR_DEPLOYED", **situations_plumbing(sc_episode=1)}
    ending = {"event_code": "SAFETY_CAR_ENDING", **situations_plumbing(sc_episode=1)}
    clear = {"event_code": "SAFETY_CAR_CLEAR", **situations_plumbing(sc_episode=1)}

    assert _sid(deployed) == _sid(ending) == _sid(clear)
    keys = {_dkey(deployed), _dkey(ending), _dkey(clear)}
    assert len(keys) == 3


def test_box_call_escalation_shares_a_situation_but_escalates_dedupe_key():
    tiers = [
        {"event_code": f"STRAT_BOX_CALL_{tier}", **situations_plumbing(box_call_window=2)}
        for tier in (1, 2, 3)
    ]
    assert len({_sid(event) for event in tiers}) == 1
    assert len({_dkey(event) for event in tiers}) == 3


def test_battle_gap_band_change_is_a_meaningful_change():
    near = {"event_code": "BATTLE", "target": "Норрис", "gap_ms": 1500}
    close = {"event_code": "BATTLE", "target": "Норрис", "gap_ms": 400}
    assert _sid(near, lap=18) == _sid(close, lap=18)
    assert _dkey(near, lap=18) != _dkey(close, lap=18)


def test_battle_gap_jitter_inside_one_band_is_not_a_change():
    a = {"event_code": "BATTLE", "target": "Норрис", "gap_ms": 1100}
    b = {"event_code": "BATTLE", "target": "Норрис", "gap_ms": 1900}
    assert _dkey(a, lap=18) == _dkey(b, lap=18)


def test_dedupe_key_is_none_when_there_is_no_situation():
    assert _dkey({"event_code": "CHQF"}) is None


@pytest.mark.parametrize("part,slug", [
    ("WING", "front_wing"), ("FLOOR", "floor"),
    ("GEARBOX", "gearbox"), ("ENGINE", "engine"),
])
def test_damage_part_slugs(part, slug):
    event = {"event_code": f"DAMAGE_{part}"}
    assert _sid(event, lap=5) == f"damage:{slug}:lap_5"


def test_cyrillic_rival_names_are_transliterated_into_ascii_slugs():
    """Ключ уходит в лог и в UI-историю — кириллица в идентификаторе усложняет
    чтение логов и сравнение ключей между сессиями. Обратный маппинг на реальное
    латинское написание (Ферстаппен → Verstappen) НЕ нужен: ключ должен быть
    стабильным и различающим, а не типографски верным — этим занимается
    core/transliterate.py на пути в TTS, и дублировать его здесь незачем."""
    event = {"event_code": "BATTLE", "target": "Ферстаппен"}
    sid = _sid(event, lap=3)
    assert sid == "battle:ferstappen:lap_3"
    assert sid.isascii()


def test_rival_slug_separates_multiword_names_without_collapsing_them():
    event = {"event_code": "BATTLE", "target": "Макс Ферстаппен"}
    assert _sid(event, lap=3) == "battle:maks_ferstappen:lap_3"
