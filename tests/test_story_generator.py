from commentator import story

_FACTS = {
    "track": "Монца", "start_position": 6, "final_position": 4,
    "positions_gained": 2, "total_laps": 53,
    "best_lap_ms": 84300, "best_lap_number": 28,
    "overtakes": [{"lap": 12, "target": "Албон"}],
    "incidents": [{"lap": 22, "code": "PENA", "driver": "player"}],
    "fastest_lap_flag": False, "weak_sector": 2,
    "consistency": 0.88, "leader": "Ферстаппен",
}


def test_build_prompt_contains_facts_and_glossary():
    p = story.build_prompt(_FACTS, "tv")
    assert "Албон" in p
    assert "Албоном" in p              # шпаргалка склонений (творительный)
    assert "ТОЛЬКО" in p               # инструкция анти-галлюцинации
    assert "4" in p                    # финишная позиция в фактах


class _FakeAI:
    available = True

    def generate(self, context, persona):
        return "Старт шестым, финиш четвёртым — крепкая гонка."


def test_generate_uses_llm_text():
    assert story.generate(_FACTS, _FakeAI(), "tv") == \
        "Старт шестым, финиш четвёртым — крепкая гонка."


class _DownAI:
    available = False

    def generate(self, context, persona):
        return None


def test_generate_falls_back_when_unavailable():
    out = story.generate(_FACTS, _DownAI(), "tv")
    assert isinstance(out, str) and len(out) > 0
    assert "4" in out                  # фолбэк упоминает финишную позицию


def test_fallback_offline_deterministic():
    a = story.render_fallback(_FACTS, "tv")
    b = story.render_fallback(_FACTS, "tv")
    assert a == b and len(a) > 0


def test_generate_handles_empty_facts():
    out = story.generate({}, _DownAI(), "tv")
    assert isinstance(out, str)        # не падает на пустых фактах


def test_format_facts_includes_weak_sector_vs_f1():
    from commentator.story import build_prompt
    facts = {"weak_sector_vs_f1": 3}
    prompt = build_prompt(facts, "tv")
    assert "S3" in prompt and "эталона F1" in prompt


def test_format_facts_omits_weak_sector_vs_f1_when_none():
    from commentator.story import build_prompt
    facts = {"weak_sector_vs_f1": None}
    prompt = build_prompt(facts, "tv")
    assert "эталона F1" not in prompt


def test_both_weak_sectors_appear_distinctly():
    """Оба факта — про собственный темп (coach_ai) и про реальный F1 — сосуществуют
    и не сливаются в одну строку/значение."""
    from commentator.story import build_prompt
    p = build_prompt({"weak_sector": 1, "weak_sector_vs_f1": 3}, "tv")
    assert "Слабый сектор: S1" in p
    assert "Слабее эталона F1 в секторе: S3" in p


def test_format_facts_includes_vs_last_visit_faster_and_higher():
    from commentator.story import build_prompt
    facts = {"vs_last_visit": {"laptime_delta_ms": -1500, "position_delta": 3,
                               "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "прошлого визита" in prompt
    assert "быстрее на 1.5с" in prompt
    assert "выше на 3" in prompt


def test_format_facts_includes_vs_last_visit_slower_and_lower():
    from commentator.story import build_prompt
    facts = {"vs_last_visit": {"laptime_delta_ms": 800, "position_delta": -2,
                               "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "медленнее на 0.8с" in prompt
    assert "ниже на 2" in prompt


def test_format_facts_omits_vs_last_visit_when_none():
    from commentator.story import build_prompt
    facts = {"vs_last_visit": None}
    prompt = build_prompt(facts, "tv")
    assert "прошлого визита" not in prompt


def test_weak_sector_vs_f1_and_vs_last_visit_coexist():
    """Sanity check that F1 Sector Benchmark's fact and Career Memory's fact don't
    interfere with each other — both should appear, neither replacing the other."""
    from commentator.story import build_prompt
    facts = {"weak_sector_vs_f1": 2,
            "vs_last_visit": {"laptime_delta_ms": -500, "position_delta": 1,
                              "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "Слабее эталона F1 в секторе: S2" in prompt
    assert "прошлого визита" in prompt


def test_format_facts_includes_career_stats():
    from commentator.story import build_prompt
    facts = {"career_stats": {"total_races": 10, "wins": 2, "podiums": 4, "avg_position": 5.5}}
    prompt = build_prompt(facts, "tv")
    assert "Карьера: гонка №10" in prompt
    assert "побед 2" in prompt
    assert "подиумов 4" in prompt
    assert "средняя позиция 5.5" in prompt


def test_format_facts_omits_career_stats_when_none():
    from commentator.story import build_prompt
    facts = {"career_stats": None}
    prompt = build_prompt(facts, "tv")
    assert "Карьера:" not in prompt


def test_build_prompt_session_type_wording():
    p_race = story.build_prompt({}, "tv", session_type="race")
    p_quali = story.build_prompt({}, "tv", session_type="qualifying")
    p_practice = story.build_prompt({}, "tv", session_type="practice")
    assert "ЗАВЕРШЁННОЙ гонки" in p_race
    assert "ЗАВЕРШЁННОЙ квалификации" in p_quali
    assert "ЗАВЕРШЁННОЙ практики" in p_practice


def test_build_prompt_defaults_to_race_wording():
    p = story.build_prompt({}, "tv")
    assert "ЗАВЕРШЁННОЙ гонки" in p


def test_render_fallback_empty_facts_session_wording():
    assert story.render_fallback({}, "tv", session_type="race") == "Гонка завершена."
    assert story.render_fallback({}, "tv", session_type="qualifying") == "Квалификация завершена."
    assert story.render_fallback({}, "tv", session_type="practice") == "Практика завершена."


def test_generate_threads_session_type_into_prompt():
    captured = {}

    class _CapturingAI:
        available = True

        def generate(self, context, persona):
            captured["context"] = context
            return "текст"

    story.generate(_FACTS, _CapturingAI(), "tv", session_type="qualifying")
    assert "ЗАВЕРШЁННОЙ квалификации" in captured["context"]


def test_generate_threads_session_type_into_fallback():
    out = story.generate({}, _DownAI(), "tv", session_type="practice")
    assert out == "Практика завершена."


def test_career_stats_and_vs_last_visit_coexist():
    """Sanity check that the new career-wide fact and the existing per-track
    vs_last_visit fact don't interfere — both should appear, neither replacing
    the other."""
    from commentator.story import build_prompt
    facts = {"career_stats": {"total_races": 10, "wins": 2, "podiums": 4, "avg_position": 5.5},
            "vs_last_visit": {"laptime_delta_ms": -500, "position_delta": 1,
                              "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "Карьера: гонка №10" in prompt
    assert "прошлого визита" in prompt


# ── Происхождение текста итога ────────────────────────────────────────────────
# Шаблонный итог визуально неотличим от написанного моделью: экран «Разбор»
# показывал оба одинаково уверенно, хотя фолбэк беднее фактами.

class _EmptyAI:
    available = True

    def generate(self, context, persona):
        return "   "   # модель ответила пустотой


def test_generate_with_source_marks_llm_text():
    text, source = story.generate_with_source(_FACTS, _FakeAI(), "tv")
    assert source == "llm"
    assert text == "Старт шестым, финиш четвёртым — крепкая гонка."


def test_generate_with_source_marks_fallback_when_provider_down():
    text, source = story.generate_with_source(_FACTS, _DownAI(), "tv")
    assert source == "fallback"
    assert len(text) > 0


def test_blank_llm_answer_counts_as_fallback():
    """Провайдер «доступен», но вернул пустоту — это фолбэк, а не ИИ-текст."""
    _, source = story.generate_with_source(_FACTS, _EmptyAI(), "tv")
    assert source == "fallback"


def test_no_provider_at_all_is_fallback():
    _, source = story.generate_with_source(_FACTS, None, "tv")
    assert source == "fallback"


def test_generate_stays_a_thin_wrapper():
    """Старые вызовы generate() не должны заметить появления источника."""
    assert story.generate(_FACTS, _FakeAI(), "tv") == \
        story.generate_with_source(_FACTS, _FakeAI(), "tv")[0]
