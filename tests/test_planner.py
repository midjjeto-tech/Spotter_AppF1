"""Comment Planner: важность события + план реплики (фокус/тип/длина/эмоция).
Чистые функции, без I/O — см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md
"""
from commentator.planner import PlanContext, score_importance, build_plan

_CTX = PlanContext()


# --------------------------------------------------------------------------- #
# score_importance
# --------------------------------------------------------------------------- #

def test_score_default_for_unknown_code():
    assert score_importance({"event_code": "WTF"}, _CTX) == 50


def test_score_base_table_ovtk():
    assert score_importance({"event_code": "OVTK"}, _CTX) == 60


def test_score_base_table_ambient():
    assert score_importance({"event_code": "AMBIENT"}, _CTX) == 20


def test_score_base_table_safety_car_codes():
    for code in ("SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING",
                 "SAFETY_CAR_CLEAR", "RDFL"):
        assert score_importance({"event_code": code}, _CTX) == 90


def test_score_player_involved_modifier():
    ctx = PlanContext(player_involved=True)
    assert score_importance({"event_code": "OVTK"}, ctx) == 80


def test_score_battle_modifier():
    ctx = PlanContext(battle=True)
    assert score_importance({"event_code": "OVTK"}, ctx) == 75


def test_score_laps_remaining_modifier():
    ctx = PlanContext(laps_remaining=2)
    assert score_importance({"event_code": "OVTK"}, ctx) == 70


def test_score_laps_remaining_above_threshold_no_modifier():
    ctx = PlanContext(laps_remaining=10)
    assert score_importance({"event_code": "OVTK"}, ctx) == 60


def test_score_non_race_session_penalizes_ovtk_ftlp():
    ctx = PlanContext(session_type="practice")
    assert score_importance({"event_code": "OVTK"}, ctx) == 50
    assert score_importance({"event_code": "FTLP"}, ctx) == 45


def test_score_non_race_session_does_not_affect_other_codes():
    ctx = PlanContext(session_type="practice")
    assert score_importance({"event_code": "PENA"}, ctx) == 88


def test_score_clamped_to_100():
    ctx = PlanContext(player_involved=True, battle=True, laps_remaining=1)
    # 60 + 20 + 15 + 10 = 105 -> зажато в 100
    assert score_importance({"event_code": "OVTK"}, ctx) == 100


def test_score_clamped_to_0():
    # синтетический случай: код с отрицательной эффективной важностью не встречается
    # в реальной таблице, но зажим должен работать в обе стороны
    ctx = PlanContext(session_type="practice")
    event = {"event_code": "FTLP"}
    assert score_importance(event, ctx) >= 0


def test_score_critical_priority_floors_at_90():
    # низкий базовый код, но помечен critical -> обязан получить пол 90
    assert score_importance({"event_code": "WTF", "priority": "critical"}, _CTX) == 90


def test_score_critical_does_not_lower_already_higher_score():
    ctx = PlanContext(player_involved=True, battle=True)
    # COLL: база 90 + 20 + 15 = 125 -> уже выше пола, max() не понижает до 90
    assert score_importance({"event_code": "COLL", "priority": "critical"}, ctx) == 100


# --------------------------------------------------------------------------- #
# build_plan
# --------------------------------------------------------------------------- #

def test_build_plan_focus_with_target():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри"}
    plan = build_plan(event, importance=80, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"
    assert plan.reaction == "атака"
    assert plan.must_mention == ("Норрис", "Пиастри")


def test_build_plan_focus_driver_only():
    event = {"event_code": "FTLP", "driver": "Ферстаппен"}
    plan = build_plan(event, importance=55, persona="tv")
    assert plan.focus == "рекорд круга: Ферстаппен"
    assert plan.must_mention == ("Ферстаппен",)


def test_build_plan_focus_no_names():
    event = {"event_code": "SSTA"}
    plan = build_plan(event, importance=70, persona="tv")
    assert plan.focus == "старт"
    assert plan.must_mention == ()


def test_build_plan_unknown_code_uses_default_reaction():
    event = {"event_code": "WTF"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.reaction == "ремарка"
    assert plan.focus == "ремарка"


def test_build_plan_length_short_above_threshold():
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_length_normal_mid_tier():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="tv")
    assert plan.length == "обычная"
    assert plan.emotion == "оживлённо"


def test_build_plan_length_normal_low_tier():
    event = {"event_code": "AMBIENT"}
    plan = build_plan(event, importance=20, persona="tv")
    assert plan.length == "обычная"
    assert plan.emotion == "спокойно"


def test_build_plan_persona_calm_lowers_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="calm")
    assert plan.emotion == "спокойно"          # "оживлённо" на ступень ниже


def test_build_plan_persona_hype_raises_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="hype")
    assert plan.emotion == "на пределе"        # "оживлённо" на ступень выше


def test_build_plan_persona_toxic_raises_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="toxic")
    assert plan.emotion == "на пределе"


def test_build_plan_persona_hype_caps_at_top():
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="hype")
    assert plan.emotion == "на пределе"        # уже макс, +1 не уходит за пределы


def test_build_plan_persona_calm_caps_at_bottom():
    event = {"event_code": "AMBIENT"}
    plan = build_plan(event, importance=20, persona="calm")
    assert plan.emotion == "спокойно"          # уже мин, -1 не уходит за пределы


def test_build_plan_unknown_persona_does_not_shift():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="nonexistent")
    assert plan.emotion == "оживлённо"         # нет сдвига для неизвестной персоны


def test_build_plan_importance_is_carried_through():
    plan = build_plan({"event_code": "SSTA"}, importance=42, persona="tv")
    assert plan.importance == 42


# --------------------------------------------------------------------------- #
# build_plan: принудительная краткость/эмоция (последние круги / атака)
# --------------------------------------------------------------------------- #

def test_build_plan_final_laps_forces_short_length_even_at_low_importance():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "laps_remaining": 2}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_battle_forces_short_length_even_at_low_importance():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_final_laps_and_battle_both_still_force_urgent():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б",
             "laps_remaining": 1, "battle": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_neither_final_laps_nor_battle_uses_normal_scale():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "laps_remaining": 10}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "обычная"
    assert plan.emotion == "оживлённо"


def test_build_plan_final_laps_marker_in_focus_not_in_reaction_field():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри", "laps_remaining": 2}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (последние 2 круга гонки): Норрис и Пиастри"
    assert plan.reaction == "атака"          # категория остаётся чистой, без маркера


def test_build_plan_battle_without_final_laps_has_no_marker_in_focus():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри", "battle": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"     # без маркера кругов


def test_build_plan_forced_urgent_calm_persona_never_reaches_top_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="calm")
    assert plan.emotion == "оживлённо"     # -1 от "на пределе", не доходит до максимума


def test_build_plan_forced_urgent_hype_persona_stays_at_top():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="hype")
    assert plan.emotion == "на пределе"    # уже на верху, +1 не уходит за пределы


def test_build_plan_final_laps_does_not_force_urgent_above_threshold():
    """laps_remaining=4 не должен срабатывать — порог тот же, что и в
    score_importance (<=3), не отдельная константа."""
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "laps_remaining": 4}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "обычная"
    assert "последние" not in plan.focus


# --------------------------------------------------------------------------- #
# build_plan: PIT_EXIT
# --------------------------------------------------------------------------- #

def test_build_plan_pit_exit_focus_with_tyre_compound():
    event = {"event_code": "PIT_EXIT", "tyre_compound": "M"}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов: свежий комплект M"
    assert plan.reaction == "выезд из боксов"
    assert plan.must_mention == ()


def test_build_plan_pit_exit_focus_without_tyre_compound():
    event = {"event_code": "PIT_EXIT", "tyre_compound": None}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов"


def test_build_plan_pit_exit_in_final_laps_gets_marker_too():
    """PIT_EXIT не обходит общий механизм срочности стороной — focus_reaction
    общий для всех веток построения focus, включая tyre_compound-ветку."""
    event = {"event_code": "PIT_EXIT", "tyre_compound": "S", "laps_remaining": 1}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов (последние 1 круга гонки): свежий комплект S"
    assert plan.length == "короткая ударная"


def test_score_base_table_pit_exit():
    assert score_importance({"event_code": "PIT_EXIT"}, _CTX) == 65


# --------------------------------------------------------------------------- #
# build_plan: battle_count и rival style в focus (Race Memory v1)
# --------------------------------------------------------------------------- #

def test_build_plan_battle_count_marker_when_battle_true():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (3-я попытка обгона): Норрис и Пиастри"


def test_build_plan_no_battle_count_marker_when_battle_false():
    """battle_count может присутствовать (например 1 — первая попытка, ещё не
    battle), но маркер появляется только когда battle уже True — не дублируем
    порог BATTLE_THRESHOLD внутри planner.py."""
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": False, "battle_count": 1}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_final_laps_and_battle_count_markers_combine():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3, "laps_remaining": 2}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == ("атака (последние 2 круга гонки, 3-я попытка обгона): "
                          "Норрис и Пиастри")


def test_build_plan_driver_style_suffix():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_style": "charging"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис (в ударе) и Пиастри"


def test_build_plan_target_style_suffix():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "target_style": "fading"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри (теряет темп)"


def test_build_plan_both_style_suffixes_together():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_style": "aggressive", "target_style": "fading"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис (агрессивен) и Пиастри (теряет темп)"


def test_build_plan_consistent_style_produces_no_suffix():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_style": "consistent"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_missing_style_fields_unaffected():
    """Событие без driver_style/target_style/battle_count (сегодняшний путь —
    DAMAGE_*, PIT_EXIT, и т.п.) ведёт себя как раньше."""
    event = {"event_code": "PIT_EXIT", "tyre_compound": "M"}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов: свежий комплект M"


def test_build_plan_battle_count_marker_and_style_suffix_combine():
    """Маркер попытки обгона (общий для всей директивы, в скобках после
    reaction) и суффикс стиля (привязан к конкретному имени) — независимые
    механизмы, должны сочетаться в одном focus без конфликта."""
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3, "driver_style": "charging"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (3-я попытка обгона): Норрис (в ударе) и Пиастри"


# --------------------------------------------------------------------------- #
# build_plan: недавняя ошибка соперника + свежесть резины (2026-07-07)
# --------------------------------------------------------------------------- #

def test_build_plan_driver_recent_mistake_marker():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_recent_mistake": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Норрис только что ошибся): Норрис и Пиастри"


def test_build_plan_target_recent_mistake_marker():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "target_recent_mistake": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Пиастри только что ошибся): Норрис и Пиастри"


def test_build_plan_no_mistake_marker_when_false():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_recent_mistake": False, "target_recent_mistake": False}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_tyre_age_gap_marker_driver_fresher():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 2, "target_tyre_age": 10}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Норрис на более свежей резине): Норрис и Пиастри"


def test_build_plan_tyre_age_gap_marker_target_fresher():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 15, "target_tyre_age": 3}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Пиастри на более свежей резине): Норрис и Пиастри"


def test_build_plan_no_tyre_age_marker_below_threshold():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 5, "target_tyre_age": 7}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_no_tyre_age_marker_when_one_side_missing():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 2, "target_tyre_age": None}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_missing_mistake_and_tyre_fields_unaffected():
    """Событие без driver_recent_mistake/target_recent_mistake/*_tyre_age
    (сегодняшний путь) ведёт себя как раньше."""
    event = {"event_code": "PIT_EXIT", "tyre_compound": "M"}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов: свежий комплект M"


def test_build_plan_mistake_and_tyre_and_battle_markers_combine():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3, "laps_remaining": 2,
             "target_recent_mistake": True,
             "driver_tyre_age": 2, "target_tyre_age": 10}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == (
        "атака (последние 2 круга гонки, 3-я попытка обгона, "
        "Пиастри только что ошибся, Норрис на более свежей резине): "
        "Норрис и Пиастри")


# --------------------------------------------------------------------------- #
# build_plan: commentary_mode "story" forces normal length + narrative flag
# --------------------------------------------------------------------------- #

def test_build_plan_default_mode_is_live_and_narrative_false():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.narrative is False


def test_build_plan_explicit_live_mode_matches_pre_mode_short_length_behavior():
    """live должен быть документированным no-op, не просто побочным эффектом
    дефолтного аргумента — явно передаём mode="live" вместо того, чтобы
    полагаться на mode: str = "live" по умолчанию."""
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="live")
    assert plan.length == "короткая ударная"


def test_build_plan_story_mode_sets_narrative_true():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=50, persona="tv", mode="story")
    assert plan.narrative is True


def test_build_plan_story_mode_forces_normal_length_at_high_importance():
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="story")
    assert plan.length == "обычная"


def test_build_plan_story_mode_forces_normal_length_even_when_force_urgent():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="tv", mode="story")
    assert plan.length == "обычная"


def test_build_plan_story_mode_does_not_change_emotion():
    """Design decision: story меняет частоту+длину, НЕ тон/эмоцию персоны."""
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="story")
    assert plan.emotion == "на пределе"


def test_build_plan_calm_mode_does_not_set_narrative():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=50, persona="tv", mode="calm")
    assert plan.narrative is False


def test_build_plan_calm_mode_does_not_force_normal_length():
    """calm меняет ТОЛЬКО частоту (это делает core/engine.py, не planner.py) —
    длина/эмоция реплики остаются как в обычной шкале важности."""
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="calm")
    assert plan.length == "короткая ударная"


def test_commentary_mode_offset_never_lets_spike_reach_critical_floor():
    """Инвариант дизайна: критические события (пол >=90 в score_importance)
    должны проходить порог "говорить" в ЛЮБОМ режиме — офсет режима не должен
    поднимать spike-порог до 90 и выше."""
    import config
    for offset in config.COMMENTARY_MODE_THRESHOLD_OFFSET.values():
        assert config.PLAN_SPIKE_THRESHOLD + offset < 90
