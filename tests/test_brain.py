"""Commentator — автономный режим: ИИ сам выбирает тему, право молчать, Free-режим."""
from commentator.brain import Commentator


class FakeAI:
    def __init__(self, available=True, result="фраза"):
        self._available = available
        self._result = result
        self.calls = []

    @property
    def available(self):
        return self._available

    def generate(self, context, persona):
        self.calls.append((context, persona))
        return self._result


def test_uses_ai_with_full_context():
    ai = FakeAI(result="Леклер атакует Хэмилтона!")
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Леклер"}, "СИТУАЦИЯ: круг 10", ai_ok=True)
    assert out == "Леклер атакует Хэмилтона!"
    assert "круг 10" in ai.calls[0][0]          # ИИ получил контекст таймлайна
    assert ai.calls[0][1] == "tv"


def test_empty_ai_response_is_silence_not_template():
    ai = FakeAI(result="")                        # ИИ осознанно молчит
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Леклер"}, "ctx", ai_ok=True)
    assert out == ""                              # тишина, а НЕ шаблон


def test_ai_failure_falls_back_to_template():
    ai = FakeAI(result=None)                       # сбой LLM
    out = Commentator(ai, "tv").create({"event_code": "SSTA"}, "ctx", ai_ok=True)
    assert out                                     # шаблон Free-режима, не пусто


def test_unhealthy_skips_ai_and_uses_template():
    ai = FakeAI(result="не должно прозвучать")
    out = Commentator(ai, "tv").create({"event_code": "SSTA"}, "ctx", ai_ok=False)
    assert ai.calls == []                          # Yandex упал — ИИ не дёргаем
    assert out                                     # шаблон


def test_ambient_without_llm_uses_template():
    ai = FakeAI(available=False)
    # Task 8: when LLM unavailable, ambient tick returns a template phrase (not silent)
    result = Commentator(ai, "tv").create_ambient("ctx", ai_ok=True)
    assert result != ""


def test_ambient_llm_failure_is_silent_not_template():
    ai = FakeAI(result=None)                       # сбой LLM на ambient
    # для ambient шаблонов нет — молчим, а не выдаём случайную заготовку
    assert Commentator(ai, "tv").create_ambient("ctx", ai_ok=True) == ""


def test_ai_echoes_silence_instruction_is_treated_as_silence():
    """Модель иногда не даёт truly-empty completion на просьбу молчать, а вместо
    этого повторяет саму инструкцию как ответ — это должно трактоваться как
    осознанная тишина, а не как реальная реплика для озвучки."""
    ai = FakeAI(result="Ничего не писать")
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Леклер"}, "ctx", ai_ok=True)
    assert out == ""


def test_silence_sentinel_is_treated_as_silence():
    """Сентинел ТИШИНА из контракта personas.py — молчание (в т.ч. с пунктуацией)."""
    for raw in ("ТИШИНА", "тишина.", "«Тишина»"):
        ai = FakeAI(result=raw)
        out = Commentator(ai, "tv").create(
            {"event_code": "OVTK", "driver": "Леклер"}, "ctx", ai_ok=True)
        assert out == "", raw


def test_real_phrase_containing_silence_word_is_not_filtered():
    """Фильтр — точное совпадение, а не подстрока: живую реплику не душим."""
    ai = FakeAI(result="Тишина в эфире закончилась — Леклер атакует!")
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Леклер"}, "ctx", ai_ok=True)
    assert out == "Тишина в эфире закончилась — Леклер атакует!"


from commentator.planner import CommentPlan


def test_plan_directive_is_composed_first_and_overrides_topic_choice():
    ai = FakeAI(result="сфокусированная фраза")
    plan = CommentPlan(focus="атака: Норрис и Пиастри", reaction="атака",
                        length="короткая ударная", emotion="на пределе",
                        importance=90, must_mention=("Норрис", "Пиастри"))
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри"},
        "СИТУАЦИЯ: старый контекст про другую драму", ai_ok=True, plan=plan)
    assert out == "сфокусированная фраза"

    composed_context = ai.calls[0][0]
    assert "ЗАДАЧА" in composed_context
    assert "атака: Норрис и Пиастри" in composed_context
    assert "Норрис" in composed_context and "Пиастри" in composed_context
    # директива обязана идти ПЕРВЫМ блоком, до старого таймлайна
    assert composed_context.index("ЗАДАЧА") < composed_context.index("старый контекст")


def test_create_without_plan_behaves_as_before():
    ai = FakeAI(result="фраза без плана")
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Леклер"}, "ctx", ai_ok=True, plan=None)
    assert out == "фраза без плана"
    assert "ЗАДАЧА" not in ai.calls[0][0]


def test_plan_without_must_mention_omits_that_line():
    ai = FakeAI(result="фраза")
    plan = CommentPlan(focus="старт", reaction="старт", length="обычная",
                        emotion="оживлённо", importance=70, must_mention=())
    Commentator(ai, "tv").create({"event_code": "SSTA"}, "ctx", ai_ok=True, plan=plan)
    assert "Обязательно упомяни" not in ai.calls[0][0]


def test_plan_narrative_true_adds_story_style_hint():
    ai = FakeAI(result="фраза")
    plan = CommentPlan(focus="атака: А и Б", reaction="атака", length="обычная",
                        emotion="оживлённо", importance=50, must_mention=(),
                        narrative=True)
    Commentator(ai, "tv").create({"event_code": "OVTK"}, "ctx", ai_ok=True, plan=plan)
    assert "свяжи с ходом гонки" in ai.calls[0][0]


def test_plan_narrative_false_omits_story_style_hint():
    ai = FakeAI(result="фраза")
    plan = CommentPlan(focus="атака: А и Б", reaction="атака", length="обычная",
                        emotion="оживлённо", importance=50, must_mention=(),
                        narrative=False)
    Commentator(ai, "tv").create({"event_code": "OVTK"}, "ctx", ai_ok=True, plan=plan)
    assert "свяжи с ходом гонки" not in ai.calls[0][0]


def test_box_call_bypasses_llm_even_when_available():
    ai = FakeAI(result="не должно прозвучать — LLM не должен вызываться")
    out = Commentator(ai, "tv").create(
        {"event_code": "STRAT_BOX_CALL_1"}, "ctx", ai_ok=True)
    assert ai.calls == []                                  # LLM не дёргали вообще
    # Формулировка приходит из банка; здесь важно, что LLM не вызывали и
    # что это команда в боксы, а не произвольный текст.
    assert "бокс" in out.lower()
