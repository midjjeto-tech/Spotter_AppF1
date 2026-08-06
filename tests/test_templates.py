"""commentator.templates.render() — маршрутизация strategy-AI кодов в strategist.py."""
import pytest

from commentator import templates
from commentator.templates import SIMPLE

# Формулировки box-call живут в банке (`core/radio/phrases.py::box.call_*`), а
# не в этом модуле: `templates.render` маршрутизирует STRAT_BOX_CALL_* в
# strategist, тот — в банк. Сверяем маршрут и смысл, а не литерал: иначе тест
# ломается на каждой правке формулировки, ничего при этом не защищая.
_BOX_CALL_CODES = ("STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3")


@pytest.mark.parametrize("code", _BOX_CALL_CODES)
def test_render_strat_box_call_routes_to_the_bank(code):
    from commentator.strategist import strategy_phrase_code
    from core.radio import phrases

    out = templates.render({"event_code": code}, "tv")
    spec = phrases.spec_for(strategy_phrase_code(code.lower().replace("strat_", "")))
    assert out in spec.variants


@pytest.mark.parametrize("code", _BOX_CALL_CODES)
def test_box_call_stays_an_order(code):
    """Эскалация — команда: пилот должен узнать её с первого слога."""
    assert "бокс" in templates.render({"event_code": code}, "tv").lower()


def test_pit_call_notice_has_template_phrases():
    out = templates.render({"event_code": "PIT_CALL_NOTICE"}, "tv")
    assert out in SIMPLE["PIT_CALL_NOTICE"]        # реальная фраза, не фолбэк на код


def test_commentator_pools_have_race_length_variety():
    assert all(len(pool) >= 6 for pool in SIMPLE.values())
    recurring = {
        "DRSE", "DRSD", "PUSH_LAP", "TYRE_CLIFF", "ATTACK_ZONE",
        "DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_TYRE_CRITICAL",
        "DAMAGE_HEAVY", "PIT_EXIT", "PIT_IN", "PIT_OUT",
        "TYRE_WEAR_HIGH",
    }
    for persona, events in templates.PERSONA.items():
        assert all(len(events[code]) >= 5 for code in recurring), persona


# --------------------------------------------------------------------------- #
# Phase B (Safety Car/VSC/красный флаг) — SIMPLE + все 3 персоны, {sc_type}
# подставляется render()'ом. См. docs/superpowers/plans/
# 2026-07-19-safety-car-vsc-red-flag.md.
# --------------------------------------------------------------------------- #

_SC_CODES = ("SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING", "SAFETY_CAR_CLEAR")
_ALL_NEW_CODES = _SC_CODES + ("RDFL",)


@pytest.mark.parametrize("code", _ALL_NEW_CODES)
def test_simple_pool_exists_and_nonempty(code):
    assert SIMPLE.get(code)


@pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _ALL_NEW_CODES)
def test_persona_pool_exists_and_nonempty(code, persona):
    assert templates.PERSONA[persona].get(code)


@pytest.mark.parametrize("code", _SC_CODES)
def test_sc_type_placeholder_substituted_no_leftover_braces(code):
    out = templates.render(
        {"event_code": code, "sc_type": "Virtual Safety Car"}, "tv")
    assert "{" not in out and "}" not in out


def test_rdfl_render_no_leftover_braces():
    out = templates.render({"event_code": "RDFL"}, "tv")
    assert "{" not in out and "}" not in out


@pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _ALL_NEW_CODES)
def test_render_all_personas_no_leftover_braces(code, persona):
    out = templates.render(
        {"event_code": code, "sc_type": "Safety car"}, persona)
    assert "{" not in out and "}" not in out
