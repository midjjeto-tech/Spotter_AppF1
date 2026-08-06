from commentator import pre_race_pep_talk as pep

_PODIUM_FACTS = {"tier": "podium", "position": 2, "track": "Монца"}
_POINTS_FACTS = {"tier": "points", "position": 7, "track": "Спа"}
_STRUGGLED_FACTS = {"tier": "struggled", "position": None, "track": "Баку"}


def test_build_prompt_contains_position_and_track():
    p = pep.build_prompt(_PODIUM_FACTS, "tv")
    assert "2" in p
    assert "Монца" in p
    assert "подиум" in p


def test_build_prompt_handles_missing_position():
    p = pep.build_prompt(_STRUGGLED_FACTS, "tv")
    assert "не финишировал" in p


def test_render_fallback_covers_all_three_tiers():
    podium = pep.render_fallback(_PODIUM_FACTS)
    points = pep.render_fallback(_POINTS_FACTS)
    struggled = pep.render_fallback(_STRUGGLED_FACTS)
    assert isinstance(podium, str) and len(podium) > 0
    assert isinstance(points, str) and len(points) > 0
    assert isinstance(struggled, str) and len(struggled) > 0
    assert podium != points != struggled


def test_render_fallback_deterministic():
    a = pep.render_fallback(_PODIUM_FACTS)
    b = pep.render_fallback(_PODIUM_FACTS)
    assert a == b


class _FakeAI:
    available = True

    def generate(self, context, persona):
        return "Прошлый раз — подиум, сегодня повторим."


def test_generate_uses_llm_text():
    assert pep.generate(_PODIUM_FACTS, _FakeAI(), "tv") == \
        "Прошлый раз — подиум, сегодня повторим."


class _DownAI:
    available = False

    def generate(self, context, persona):
        return None


def test_generate_falls_back_when_ai_unavailable():
    out = pep.generate(_PODIUM_FACTS, _DownAI(), "tv")
    assert out == pep.render_fallback(_PODIUM_FACTS)


def test_generate_falls_back_when_llm_returns_empty():
    class _EmptyAI:
        available = True

        def generate(self, context, persona):
            return "   "
    out = pep.generate(_POINTS_FACTS, _EmptyAI(), "tv")
    assert out == pep.render_fallback(_POINTS_FACTS)
