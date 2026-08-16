"""Вердикт сессии (core/coach_ai/lesson.py).

Разбор обязан отвечать на три вопроса пилота: сколько я оставил на трассе, где
именно и что делать дальше. Тесты проверяют именно ответы, а не наличие полей —
блок с прочерками читается как поломка и хуже отсутствующего блока.
"""
from core.coach_ai.cost import LapPotential
from core.coach_ai.diagnosis import CornerDiagnosis
from core.coach_ai.focus import Focus
from core.coach_ai.lesson import TOP_LOSSES, build_lesson


def _d(corner_id: int, cost_ms: float, share: float,
       cause: str | None = "lockup") -> CornerDiagnosis:
    return CornerDiagnosis(
        corner_id=corner_id, corner_name=f"Turn {corner_id}", cost_ms=cost_ms,
        share=share, laps=6, cause=cause,
        cause_kind="mistake" if cause else None,
        occurrences=6 if cause else 0,
        evidence="блокировка колёс на торможении — 6 раз за сессию" if cause else "")


def _potential(best: int = 92_400, gain: int = 800) -> LapPotential:
    return LapPotential(best_lap_ms=best, potential_ms=best - gain, gain_ms=gain,
                        corners_counted=12, clamped=False)


def test_nothing_measured_yet_is_no_lesson_at_all():
    """None, а не блок с прочерками: прочерк пилот читает как поломку."""
    assert build_lesson([], None) is None


def test_potential_headline_names_the_lap_the_driver_already_drove():
    lesson = build_lesson([_d(7, 400.0, 0.7)], _potential(92_400, 800))

    assert lesson is not None
    assert lesson["potential_ms"] == 91_600
    assert lesson["gain_ms"] == 800
    assert "0,8 с" in lesson["headline"]
    assert "1:31,60" in lesson["headline"]     # потенциал
    assert "1:32,40" in lesson["headline"]     # лучший круг


def test_tiny_potential_is_not_promised():
    """Запас в пределах точности замера обещать нельзя."""
    lesson = build_lesson([_d(7, 400.0, 0.7), _d(3, 200.0, 0.3)],
                          _potential(92_400, gain=60))

    assert "потенциал" not in lesson["headline"]


def test_concentrated_loss_is_named_as_such():
    lesson = build_lesson([_d(7, 500.0, 0.5), _d(3, 300.0, 0.3),
                           _d(2, 200.0, 0.2)], None)

    assert "в поворотах 7 и 3" in lesson["headline"]
    assert "80%" in lesson["headline"]


def test_everything_in_two_corners_is_said_in_words_not_as_a_hundred_percent():
    """«100% потери» читается как артефакт округления там, где цифра точна.

    Найдено чтением вывода на синтетическом заезде, а не тестом: формально
    строка была верна, и все проверки на неё проходили.
    """
    lesson = build_lesson([_d(7, 500.0, 0.56), _d(3, 400.0, 0.44)], None)

    assert "Вся потеря круга — в поворотах 7 и 3" in lesson["headline"]
    assert "100%" not in lesson["headline"]


def test_single_dominant_corner_reads_naturally():
    lesson = build_lesson([_d(7, 500.0, 1.0)], None)

    assert "в повороте 7" in lesson["headline"]
    assert "0,5 с" in lesson["headline"]


def test_next_step_is_one_thing_and_carries_its_price_and_reason():
    lesson = build_lesson([_d(7, 420.0, 0.6), _d(3, 280.0, 0.4)], None)

    step = lesson["next_step"]
    assert "поворота 7" in step
    assert "блокировка" in step
    assert "0,42 с" in step
    assert "поворот 3" not in step.lower()


def test_next_step_skips_a_corner_with_no_known_cause():
    """Самый дорогой поворот без причины — не задание: делать с ним нечего."""
    lesson = build_lesson([_d(9, 600.0, 0.6, cause=None), _d(3, 400.0, 0.4)],
                          None)

    assert "поворота 3" in lesson["next_step"]


def test_next_step_is_honest_when_nothing_repeats():
    lesson = build_lesson([_d(9, 600.0, 1.0, cause=None)], None)

    assert "причины не видно" in lesson["next_step"]
    assert "разовые" in lesson["next_step"]


def test_losses_are_capped_to_the_top():
    rows = [_d(i, 500.0 - i * 10, 0.1) for i in range(1, 9)]

    lesson = build_lesson(rows, None)

    assert len(lesson["losses"]) == TOP_LOSSES
    assert lesson["losses"][0]["corner_id"] == 1
    # Сумма потерь считается по ВСЕМ поворотам, а не только по показанным.
    assert lesson["total_loss_ms"] == round(sum(r.cost_ms for r in rows))


def test_focus_travels_with_the_lesson():
    focus = Focus(corner_id=7, corner_name="Turn 7", cause="lockup",
                  cause_kind="mistake", evidence="…", baseline_ms=400.0,
                  current_ms=150.0, since_lap=4, status="improving")

    lesson = build_lesson([_d(7, 150.0, 1.0)], None, focus=focus)

    assert lesson["focus"]["corner_id"] == 7
    assert lesson["focus"]["gain_ms"] == 250


# ── Прогресс относительно прошлого визита ────────────────────────────────────

def test_progress_reports_a_faster_visit_and_the_old_focus_corner():
    previous = {"best_lap_ms": 93_000,
                "focus": {"corner_id": 7, "current_ms": 400}}

    lesson = build_lesson([_d(7, 100.0, 1.0)], _potential(92_400, 500),
                          previous=previous)

    text = lesson["progress"]["text"]
    assert "Быстрее прошлого визита на 0,6 с" in text
    assert "поворотом 7" in text
    assert "было 0,4 с, стало 0,1 с" in text
    assert lesson["progress"]["best_delta_ms"] == -600


def test_progress_says_it_plainly_when_the_old_problem_came_back():
    previous = {"best_lap_ms": 92_000,
                "focus": {"corner_id": 7, "current_ms": 100}}

    lesson = build_lesson([_d(7, 500.0, 1.0)], _potential(92_400, 500),
                          previous=previous)

    text = lesson["progress"]["text"]
    assert "Медленнее прошлого визита" in text
    assert "стоит уже 0,5 с" in text


def test_progress_falls_back_to_the_biggest_previous_loss_without_a_focus():
    previous = {"best_lap_ms": 92_800,
                "losses": [{"corner_id": 3, "cost_ms": 300}]}

    lesson = build_lesson([_d(3, 120.0, 1.0)], _potential(92_400, 500),
                          previous=previous)

    assert lesson["progress"]["focus_corner_id"] == 3
    assert lesson["progress"]["focus_now_ms"] == 120


def test_a_corner_gone_from_the_map_counts_as_zero_not_as_missing_data():
    previous = {"focus": {"corner_id": 7, "current_ms": 400}}

    lesson = build_lesson([_d(3, 120.0, 1.0)], None, previous=previous)

    assert lesson["progress"]["focus_now_ms"] == 0
    assert "стало 0 с" in lesson["progress"]["text"]


def test_garbage_previous_lesson_does_not_cost_the_whole_debrief():
    """Прошлый урок приходит из архива обычным JSON — там может быть что угодно."""
    for previous in ({}, {"best_lap_ms": "быстро"}, {"focus": "седьмой"},
                     {"losses": [42]}, {"focus": {"corner_id": None}},
                     {"best_lap_ms": None, "focus": {}}):
        lesson = build_lesson([_d(7, 400.0, 1.0)], _potential(), previous=previous)

        assert lesson is not None
        assert lesson.get("progress") is None


def test_previous_lesson_of_a_wrong_type_is_ignored():
    lesson = build_lesson([_d(7, 400.0, 1.0)], _potential(), previous=["nope"])

    assert lesson.get("progress") is None


def test_lesson_survives_a_session_with_potential_but_no_priced_corners():
    lesson = build_lesson([], _potential(92_400, 700))

    assert lesson is not None
    assert lesson["losses"] == []
    assert lesson["total_loss_ms"] == 0
    assert lesson["next_step"] is None


def test_lap_time_under_a_minute_is_not_padded_with_a_fake_minute():
    lesson = build_lesson([], _potential(best=48_300, gain=900))

    assert "48,30" in lesson["headline"]
    assert ":" not in lesson["headline"].split("против")[-1]


# --------------------------------------------------------------------------- #
# Клампнутый потенциал не обещается вслух.
# Разбор живого заезда 2026-08-11: заголовок обещал «В круге осталось 11,42 с»
# при сумме найденных потерь 0,93 с и clamped=True, то есть само вычисление
# знало, что в него попало неправдоподобное.
# --------------------------------------------------------------------------- #

def _clamped_potential(best: int = 89_184, gain: int = 11_418) -> LapPotential:
    return LapPotential(best_lap_ms=best, potential_ms=best - gain, gain_ms=gain,
                        corners_counted=13, clamped=True)


def test_clamped_potential_is_not_promised_in_the_headline():
    lesson = build_lesson([_d(3, 366.0, 0.6), _d(17, 350.0, 0.4)],
                          _clamped_potential())

    assert "осталось" not in lesson["headline"]
    # Урок не исчезает — он говорит о том, что измерено надёжно.
    assert lesson["headline"]
    assert "3" in lesson["headline"]


def test_clamped_potential_still_reaches_the_screen_as_data():
    """Не обещаем вслух — но число остаётся в данных, вместе с признаком."""
    lesson = build_lesson([_d(3, 366.0, 1.0)], _clamped_potential())

    assert lesson["gain_ms"] == 11_418
    assert lesson["potential_clamped"] is True


def test_clean_potential_is_still_promised():
    lesson = build_lesson([_d(7, 400.0, 1.0)], _potential(92_400, 800))

    assert "осталось" in lesson["headline"]


# --------------------------------------------------------------------------- #
# Урок не спорит сам с собой.
# Разбор живого заезда 2026-08-11: в losses Turn 17 шёл с «причина не найдена»,
# а focus про ТОТ ЖЕ поворот говорил «проходишь апекс медленнее, чем умеешь».
# Расхождение законное по механике (сессия против последних кругов), но пилот
# читает оба блока сразу.
# --------------------------------------------------------------------------- #

def _t17_focus() -> Focus:
    return Focus(corner_id=17, corner_name="Turn 17", cause="min_speed",
                 cause_kind="technique",
                 evidence="проходишь апекс медленнее, чем умеешь",
                 baseline_ms=551.0, current_ms=268.0, since_lap=3,
                 status="improving")


def test_focus_cause_fills_a_loss_that_has_none():
    lesson = build_lesson([_d(17, 350.0, 1.0, cause=None)], None,
                          focus=_t17_focus())

    row = lesson["losses"][0]
    assert row["corner_id"] == 17
    assert row["cause"] == "min_speed"
    assert row["cause_kind"] == "technique"
    assert row["evidence"]


def test_focus_does_not_overwrite_a_cause_found_over_the_session():
    """Диагноз по всей сессии весомее: он про привычку, а не про последние круги."""
    lesson = build_lesson([_d(17, 350.0, 1.0, cause="lockup")], None,
                          focus=_t17_focus())

    assert lesson["losses"][0]["cause"] == "lockup"


def test_focus_does_not_touch_other_corners():
    lesson = build_lesson([_d(3, 366.0, 1.0, cause=None)], None,
                          focus=_t17_focus())

    assert lesson["losses"][0]["cause"] is None


def test_no_focus_leaves_an_unknown_cause_unknown():
    """Причину, которой не нашли оба, придумывать нельзя."""
    lesson = build_lesson([_d(3, 366.0, 1.0, cause=None)], None, focus=None)

    assert lesson["losses"][0]["cause"] is None


def test_unpriced_session_does_not_invent_a_fixed_corner():
    """Цену не считали — про поворот прошлого визита молчим.

    `CornerHistory.costs()` выходит ни с чем, когда эталон покрывает меньше
    `MIN_COMPARABLE_CORNERS` поворотов, а `potential()` при этом работает (он
    эталон не использует вовсе). Урок в этом случае собирается с пустыми
    `losses`, и раньше прогресс читал отсутствие поворота в них как ноль:
    «было 0,4 с, стало 0 с» — поздравление с исправлением того, что сегодня ни
    разу не измерили.
    """
    previous = {"best_lap_ms": 92_000, "focus": {"corner_id": 7, "current_ms": 400}}

    lesson = build_lesson([], _potential(92_400, 800), previous=previous)

    assert lesson is not None
    assert lesson["losses"] == []
    # Сравнение лучших кругов от цены поворотов не зависит и остаётся.
    assert lesson["progress"]["best_delta_ms"] == 400
    assert "Медленнее прошлого визита" in lesson["progress"]["text"]
    # А вот про поворот 7 сказать нечего.
    assert lesson["progress"]["focus_now_ms"] is None
    assert "поворот" not in lesson["progress"]["text"].lower()


def test_priced_session_still_calls_a_vanished_corner_fixed():
    """Контроль: расчёт состоялся и потери в повороте не нашёл — это ноль.

    Обратная сторона предыдущего теста; та же пара, что различает «нет данных» и
    «данные есть, значение нулевое».
    """
    previous = {"focus": {"corner_id": 7, "current_ms": 400}}

    lesson = build_lesson([_d(3, 120.0, 1.0)], None, previous=previous)

    assert lesson["progress"]["focus_now_ms"] == 0
    assert "стало 0 с" in lesson["progress"]["text"]


def test_unpriced_session_without_a_best_lap_has_no_progress_block_at_all():
    """Ни цены, ни лучшего круга — блока прогресса быть не должно."""
    previous = {"focus": {"corner_id": 7, "current_ms": 400}}

    lesson = build_lesson([], _potential(92_400, 800), previous=previous)

    assert lesson.get("progress") is None
