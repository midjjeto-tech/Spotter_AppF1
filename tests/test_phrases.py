"""
tests/test_phrases.py
======================
Tests for expanded phrase pools in commentator/templates.py and radio.py.
"""
import random
import pytest

from commentator.templates import (
    SIMPLE,
    PERSONA,
    BATTLE,
    FINAL_LAPS,
    _AMBIENT_POOL,
    RARE_POOL,
    render,
    render_ambient,
    render_rare,
)
from commentator.radio import _RADIO_CODE, get_radio_line
from commentator.phrase_pool import reset_phrase_cycles


# ---------------------------------------------------------------------------
# SIMPLE pool coverage
# ---------------------------------------------------------------------------

class TestSimplePool:
    def test_core_event_codes_present(self):
        required = {"SSTA", "FTLP", "RTMT", "CHQF", "RCWN", "PENA", "OVTK", "DRSE", "DRSD"}
        missing = required - set(SIMPLE.keys())
        assert not missing, f"Missing core event codes in SIMPLE: {missing}"

    def test_each_code_has_at_least_three_variants(self):
        short = {k: v for k, v in SIMPLE.items() if len(v) < 3}
        assert not short, f"Codes with fewer than 3 phrases: {short.keys()}"

    def test_no_empty_phrases(self):
        for code, phrases in SIMPLE.items():
            for p in phrases:
                assert p.strip(), f"Empty phrase found for code {code}"

    def test_ovtk_has_drs_variant(self):
        ovtk = SIMPLE["OVTK"]
        assert any("DRS" in p for p in ovtk), "OVTK should have at least one DRS variant"

    def test_ssta_has_light_variant(self):
        ssta = SIMPLE["SSTA"]
        assert any("огн" in p.lower() or "свет" in p.lower() for p in ssta)

    def test_ftlp_has_purple_sector_variant(self):
        phrases = SIMPLE["FTLP"]
        assert any("фиол" in p.lower() or "пурпур" in p.lower() for p in phrases)

    def test_pit_codes_present(self):
        assert "PIT_IN" in SIMPLE
        assert "PIT_OUT" in SIMPLE
        assert "PIT_WINDOW_OPEN" in SIMPLE

    def test_tyre_cliff_present(self):
        assert "TYRE_CLIFF" in SIMPLE

    def test_push_lap_present(self):
        assert "PUSH_LAP" in SIMPLE

    def test_damage_event_codes_present(self):
        required = {"DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_TYRE_CRITICAL", "DAMAGE_HEAVY"}
        missing = required - set(SIMPLE.keys())
        assert not missing, f"Missing damage event codes in SIMPLE: {missing}"

    def test_damage_events_at_least_four_variants(self):
        for code in ("DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_TYRE_CRITICAL", "DAMAGE_HEAVY"):
            assert len(SIMPLE[code]) >= 4, f"{code} has fewer than 4 variants"


# ---------------------------------------------------------------------------
# PERSONA pools
# ---------------------------------------------------------------------------

class TestPersonaPool:
    PERSONAS = ("hype", "calm", "toxic")

    def test_all_personas_present(self):
        for p in self.PERSONAS:
            assert p in PERSONA, f"Persona '{p}' missing"

    def test_tv_persona_absent_from_persona_dict(self):
        assert "tv" not in PERSONA, (
            "'tv' must not be in PERSONA dict — it uses SIMPLE as fallback"
        )

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_ovtk_at_least_six_variants(self, persona):
        phrases = PERSONA[persona].get("OVTK", [])
        assert len(phrases) >= 6, f"{persona}/OVTK has only {len(phrases)} variants"

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_drse_present(self, persona):
        assert "DRSE" in PERSONA[persona], f"{persona} missing DRSE phrases"

    def test_hype_uses_caps_in_ovtk(self):
        ovtk = PERSONA["hype"]["OVTK"]
        assert any(p != p.lower() and any(c.isupper() for c in p) for p in ovtk)

    def test_calm_no_exclamation_in_rcwn(self):
        rcwn = PERSONA["calm"]["RCWN"]
        # calm style should be measured — most phrases shouldn't end in "!"
        exclaim_count = sum(1 for p in rcwn if p.strip().endswith("!"))
        assert exclaim_count < len(rcwn), "calm/RCWN has too many exclamation phrases"

    def test_toxic_sarcasm_in_ovtk(self):
        ovtk = PERSONA["toxic"]["OVTK"]
        sarcasm_markers = ("ну ", "наконец", "ждал", "ясно", "кто бы")
        assert any(any(m in p.lower() for m in sarcasm_markers) for p in ovtk), (
            "toxic/OVTK should have sarcastic phrases"
        )

    def test_push_lap_present_in_hype(self):
        assert "PUSH_LAP" in PERSONA["hype"]

    def test_tyre_cliff_present_in_toxic(self):
        assert "TYRE_CLIFF" in PERSONA["toxic"]

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_damage_codes_in_all_personas(self, persona):
        for code in ("DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_TYRE_CRITICAL", "DAMAGE_HEAVY"):
            assert code in PERSONA[persona], f"{persona} missing {code}"
            assert len(PERSONA[persona][code]) >= 3, (
                f"{persona}/{code} has fewer than 3 phrases"
            )


# ---------------------------------------------------------------------------
# BATTLE pool
# ---------------------------------------------------------------------------

class TestBattlePool:
    def test_ovtk_present_and_non_empty(self):
        assert "OVTK" in BATTLE
        assert len(BATTLE["OVTK"]) >= 4

    def test_drse_present(self):
        assert "DRSE" in BATTLE


# ---------------------------------------------------------------------------
# Ambient pool
# ---------------------------------------------------------------------------

class TestAmbientPool:
    def test_all_personas_have_pool(self):
        for p in ("tv", "hype", "calm", "toxic"):
            assert p in _AMBIENT_POOL, f"Ambient pool missing for persona '{p}'"

    def test_each_persona_at_least_eight_variants(self):
        for persona, pool in _AMBIENT_POOL.items():
            assert len(pool) >= 8, f"Ambient pool for '{persona}' has only {len(pool)} phrases"

    def test_render_ambient_returns_nonempty(self):
        for persona in ("tv", "hype", "calm", "toxic"):
            result = render_ambient(persona)
            assert result and result.strip()

    def test_render_ambient_unknown_persona_falls_back_to_tv(self):
        result = render_ambient("nonexistent_persona")
        assert result in _AMBIENT_POOL["tv"]


# ---------------------------------------------------------------------------
# Rare pool
# ---------------------------------------------------------------------------

class TestRarePool:
    def test_known_keys_present(self):
        expected = {"overtake_brilliant", "drs_chain", "pit_undercut_nailed", "tyre_gamble"}
        missing = expected - set(RARE_POOL.keys())
        assert not missing

    def test_weights_are_positive(self):
        for key, pool in RARE_POOL.items():
            for phrase, weight in pool:
                assert weight > 0, f"Non-positive weight in {key}: {weight!r}"

    def test_render_rare_returns_string(self):
        result = render_rare("overtake_brilliant")
        assert isinstance(result, str) and result.strip()

    def test_render_rare_unknown_key_returns_none(self):
        assert render_rare("not_a_key") is None

    def test_weighted_selection_is_deterministic_with_seed(self):
        random.seed(42)
        r1 = render_rare("overtake_brilliant")
        random.seed(42)
        r2 = render_rare("overtake_brilliant")
        assert r1 == r2

    def test_rare_phrase_actually_rare_relative_to_low_weight(self):
        # The lowest-weight phrase should be chosen less often than the highest.
        pool = RARE_POOL["overtake_brilliant"]
        phrases = [p for p, _ in pool]
        weights = [w for _, w in pool]
        if len(pool) < 2:
            pytest.skip("Pool too small to test relative frequency")
        max_idx = weights.index(max(weights))
        min_idx = weights.index(min(weights))
        counts = {p: 0 for p in phrases}
        random.seed(0)
        for _ in range(1000):
            counts[render_rare("overtake_brilliant")] += 1
        assert counts[phrases[max_idx]] > counts[phrases[min_idx]]


# ---------------------------------------------------------------------------
# render() function
# ---------------------------------------------------------------------------

class TestRender:
    def _event(self, code, **kwargs):
        return {"event_code": code, "driver": "Ферстаппен", "target": "Леклер", **kwargs}

    def test_render_simple_ssta(self):
        result = render(self._event("SSTA"), persona="tv")
        assert result in SIMPLE["SSTA"]

    def test_render_persona_ovtk_hype(self):
        result = render(self._event("OVTK"), persona="hype")
        # Surnames in correct case; no leftover placeholders.
        assert "Ферстаппен" in result
        assert "{" not in result and "}" not in result

    def test_render_ovtk_tv_falls_back_to_simple(self):
        # tv has no PERSONA entry — must come from SIMPLE; surnames declined.
        result = render(self._event("OVTK"), persona="tv")
        assert "Ферстаппен" in result
        assert "{" not in result and "}" not in result

    def test_render_battle_flag_uses_battle_pool(self):
        evt = self._event("OVTK", battle=True)
        result = render(evt, persona="tv")
        # battle phrases all mention both drivers as surnames
        assert "Ферстаппен" in result
        assert "{" not in result and "}" not in result

    def test_render_unknown_code_returns_description(self):
        evt = {"event_code": "ZZZZ", "description": "Неизвестное событие"}
        result = render(evt, persona="tv")
        assert result == "Неизвестное событие"

    def test_render_tyre_cliff(self):
        result = render(self._event("TYRE_CLIFF"), persona="toxic")
        assert result  # should not be empty

    def test_render_push_lap(self):
        result = render(self._event("PUSH_LAP"), persona="hype")
        assert result

    @pytest.mark.parametrize("code,persona", [
        ("DAMAGE_WING", "hype"), ("DAMAGE_WING", "calm"), ("DAMAGE_WING", "toxic"),
        ("DAMAGE_FLOOR", "hype"), ("DAMAGE_FLOOR", "tv"),
        ("DAMAGE_TYRE_CRITICAL", "toxic"), ("DAMAGE_HEAVY", "calm"),
    ])
    def test_render_damage_event(self, code, persona):
        evt = {"event_code": code, "driver": "Ферстаппен"}
        result = render(evt, persona=persona)
        assert result, f"render({code}, {persona}) returned empty"
        assert "{" not in result, f"Unresolved placeholder in: {result!r}"

    def test_render_avoids_back_to_back_repeats(self):
        """Anti-repetition: a multi-variant pool should not repeat the exact same
        line twice in a row — the core 'less robotic' logic."""
        evt = self._event("OVTK", driver="A", target="B")
        seen = [render(evt, persona="hype") for _ in range(40)]
        # no two consecutive renders identical
        assert all(seen[i] != seen[i + 1] for i in range(len(seen) - 1))

    def test_render_ambient_avoids_back_to_back_repeats(self):
        seen = [render_ambient("tv") for _ in range(40)]
        assert all(seen[i] != seen[i + 1] for i in range(len(seen) - 1))


# ---------------------------------------------------------------------------
# Radio
# ---------------------------------------------------------------------------

class TestRadio:
    """`commentator/radio.py` — карта event_code -> код банка.

    Пулы оттуда убраны: восемь из семнадцати не маршрутизировались в
    CHANNEL_RADIO ни в одном типе сессии, то есть пятьдесят фраз не могли
    прозвучать никогда. Единый банк делает такие дыры видимыми."""

    def test_map_covers_exactly_the_radio_channel_set(self):
        """Карта обязана совпадать с тем, что роутер шлёт в CHANNEL_RADIO.
        Лишний ключ — мёртвая запись, недостающий — событие без фразы."""
        from commentator.channel_router import _RADIO_IN_RACE

        assert set(_RADIO_CODE) == set(_RADIO_IN_RACE)

    def test_every_mapped_code_exists_in_the_bank(self):
        from core.radio import phrases

        for event_code, phrase_code in _RADIO_CODE.items():
            assert phrase_code in phrases.codes(), event_code

    def test_get_radio_line_returns_string(self):
        result = get_radio_line("DRSE")
        assert isinstance(result, str) and result.strip()

    def test_get_radio_line_unknown_returns_none(self):
        assert get_radio_line("NOT_A_CODE") is None

    def test_dead_pools_are_gone(self):
        """ATTACK/PIT_IN/PUSH_LAP/TYRE_CLIFF и остальные недостижимые коды
        больше не притворяются радио-репликами."""
        for dead in ("ATTACK", "ATTACK_ZONE", "PIT_IN", "PIT_OUT",
                     "PUSH_LAP", "QUALI_LAP", "SSTA", "TYRE_CLIFF"):
            assert get_radio_line(dead) is None, dead

    def test_selector_pins_the_variant(self):
        first = get_radio_line("DRSE", "situation-1")
        again = get_radio_line("DRSE", "situation-1")
        assert first == again

    def test_radio_lines_are_short(self):
        from core.radio import phrases

        for event_code, phrase_code in _RADIO_CODE.items():
            for line in phrases.spec_for(phrase_code).variants:
                assert len(line.split()) <= 12, (
                    f"Radio line too long for {event_code}: {line!r}")


# ---------------------------------------------------------------------------
# FINAL_LAPS pool
# ---------------------------------------------------------------------------

class TestFinalLapsPool:
    def test_ovtk_present_and_non_empty(self):
        assert "OVTK" in FINAL_LAPS
        assert len(FINAL_LAPS["OVTK"]) >= 4

    def test_phrases_mention_final_laps(self):
        """Маркер-слово для теста приоритета пулов ниже — SIMPLE/BATTLE["OVTK"]
        сознательно не содержат "последн", чтобы substring-проверка была
        однозначной."""
        assert all("последн" in p.lower() for p in FINAL_LAPS["OVTK"])


class TestRenderFinalLaps:
    def _event(self, code, **kwargs):
        return {"event_code": code, "driver": "Ферстаппен", "target": "Леклер", **kwargs}

    def test_final_laps_pool_used_when_laps_remaining_low(self):
        evt = self._event("OVTK", laps_remaining=2)
        result = render(evt, persona="tv")
        assert "последн" in result.lower()
        assert "{" not in result and "}" not in result

    def test_final_laps_pool_not_used_when_laps_remaining_high(self):
        evt = self._event("OVTK", laps_remaining=10)
        result = render(evt, persona="tv")
        assert "последн" not in result.lower()

    def test_final_laps_pool_not_used_when_laps_remaining_none(self):
        evt = self._event("OVTK")
        result = render(evt, persona="tv")
        assert "последн" not in result.lower()

    def test_final_laps_overrides_battle(self):
        """Готовые фразы нельзя скомпоновать, как маркеры build_plan() —
        final_laps побеждает battle, когда оба условия верны одновременно
        (design spec 2026-07-05-phrase-bank-expansion)."""
        evt = self._event("OVTK", laps_remaining=2, battle=True)
        result = render(evt, persona="tv")
        assert "последн" in result.lower()

    def test_battle_still_used_when_not_final_laps(self):
        evt = self._event("OVTK", laps_remaining=10, battle=True)
        result = render(evt, persona="tv")
        assert "последн" not in result.lower()


# ---------------------------------------------------------------------------
# PIT_EXIT pool
# ---------------------------------------------------------------------------

class TestPitExitPool:
    def test_present_in_simple(self):
        assert "PIT_EXIT" in SIMPLE
        assert len(SIMPLE["PIT_EXIT"]) >= 4

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_present_in_persona(self, persona):
        assert "PIT_EXIT" in PERSONA[persona]
        assert len(PERSONA[persona]["PIT_EXIT"]) >= 3

    def test_no_tyre_compound_placeholder(self):
        """Согласованное сужение объёма (design spec): PIT_EXIT НЕ упоминает
        состав шин — эта строка не должна ссылаться на {tyre_compound}."""
        all_phrases = list(SIMPLE["PIT_EXIT"])
        for persona in ("hype", "calm", "toxic"):
            all_phrases += PERSONA[persona]["PIT_EXIT"]
        assert all("{tyre_compound}" not in p for p in all_phrases)


class TestRenderPitExit:
    def _event(self, **kwargs):
        return {"event_code": "PIT_EXIT", "driver": "Ферстаппен", **kwargs}

    def test_render_simple(self):
        result = render(self._event(), persona="tv")
        assert result and result.strip()
        assert "{" not in result and "}" not in result

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_render_persona(self, persona):
        result = render(self._event(), persona=persona)
        assert result and result.strip()
        assert "{" not in result and "}" not in result


# ---------------------------------------------------------------------------
# Persona variants for previously SIMPLE-only pit/tyre codes
# ---------------------------------------------------------------------------

class TestPersonaVariantsForPitAndTyre:
    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    @pytest.mark.parametrize("code", ["PIT_IN", "PIT_OUT", "TYRE_WEAR_HIGH"])
    def test_persona_has_code(self, persona, code):
        assert code in PERSONA[persona], f"{persona} missing {code}"
        assert len(PERSONA[persona][code]) >= 3

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    @pytest.mark.parametrize("code", ["PIT_IN", "PIT_OUT", "TYRE_WEAR_HIGH"])
    def test_render_persona_variant(self, persona, code):
        evt = {"event_code": code, "driver": "Ферстаппен"}
        result = render(evt, persona=persona)
        assert result and result.strip()
        assert "{" not in result and "}" not in result
