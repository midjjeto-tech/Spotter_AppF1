"""Фокус сессии (core/coach_ai/focus.py) — одна работа за раз и подтверждение,
что она сделана.

Тесты делятся на две группы, и обе одинаково важны:

    что коуч ГОВОРИТ  — взял работу, стало лучше, закрыли;
    чего он НЕ говорит — не мечется между поворотами, не хвалит за один удачный
                         круг, не бросает то, что уже начало получаться.

Вторая группа здесь главная: молчание в нужный момент отличает тренера от
сирены, и сломать его правкой легче всего.
"""
from core.coach_ai.diagnosis import CornerDiagnosis
from core.coach_ai.focus import (CONFIRM_LAPS, EVENT_COOLDOWN_LAPS,
                                 MIN_FOCUS_COST_MS, MIN_LAPS_BEFORE_SWITCH,
                                 PROGRESS_MIN_MS, RELAPSE_LAPS, SessionFocus)


def _d(corner_id: int, cost_ms: float, cause: str | None = "lockup",
       ) -> CornerDiagnosis:
    return CornerDiagnosis(
        corner_id=corner_id, corner_name=f"Turn {corner_id}", cost_ms=cost_ms,
        share=1.0, laps=5, cause=cause,
        cause_kind="mistake" if cause else None,
        occurrences=5 if cause else 0,
        evidence="блокировка колёс на торможении — 5 раз за сессию" if cause else "")


def _run(focus: SessionFocus, rows_by_lap: dict[int, list[CornerDiagnosis]],
         laps: range) -> list:
    """Прогнать сессию и собрать все события."""
    events = []
    for lap in laps:
        event = focus.update(rows_by_lap.get(lap, []), lap)
        if event is not None:
            events.append(event)
    return events


# ── Что коуч говорит ─────────────────────────────────────────────────────────

def test_the_most_expensive_actionable_problem_becomes_the_work():
    focus = SessionFocus()

    event = focus.update([_d(3, 200.0), _d(7, 450.0), _d(2, 130.0)], lap=4)

    assert event is not None
    assert event.kind == "set"
    assert event.corner_id == 7
    assert event.cost_ms == 450.0
    assert focus.state is not None
    assert focus.state.baseline_ms == 450.0
    assert focus.state.status == "working"


def test_progress_is_confirmed_and_said_out_loud():
    """Единственная обратная связь, ради которой пилот вообще слушает."""
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)

    improved = [_d(7, 400.0 - PROGRESS_MIN_MS - 20)]
    events = _run(focus, {lap: improved for lap in range(2, 10)}, range(2, 10))

    assert [e.kind for e in events] == ["progress"]
    assert events[0].corner_id == 7
    assert events[0].gain_ms >= PROGRESS_MIN_MS
    assert focus.state is not None
    assert focus.state.status == "improving"


def test_progress_is_said_exactly_once_per_focus():
    """Второй раз о том же прогрессе — уже не подтверждение, а болтовня."""
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    improved = [_d(7, 150.0)]

    events = _run(focus, {lap: improved for lap in range(2, 30)}, range(2, 30))

    assert [e.kind for e in events].count("progress") == 1


def test_corner_that_dropped_out_of_the_problem_list_is_closed():
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)

    events = _run(focus, {}, range(2, 10))

    assert [e.kind for e in events] == ["fixed"]
    assert events[0].corner_id == 7
    assert focus.state is None


def test_after_closing_one_corner_the_next_becomes_the_work():
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    rows = {lap: [_d(3, 300.0)] for lap in range(2, 20)}

    events = _run(focus, rows, range(2, 20))

    kinds = [(e.kind, e.corner_id) for e in events]
    assert ("fixed", 7) in kinds
    assert ("set", 3) in kinds
    assert kinds.index(("fixed", 7)) < kinds.index(("set", 3))


# ── Чего коуч НЕ говорит ─────────────────────────────────────────────────────

def test_corner_without_a_cause_never_becomes_the_work():
    """«Здесь ты теряешь время» — это не работа, это констатация.

    Ровно такие указания и делали коуча бесполезным: применить их нельзя.
    """
    focus = SessionFocus()

    assert focus.update([_d(7, 900.0, cause=None)], lap=4) is None
    assert focus.state is None


def test_cheap_problem_is_not_worth_a_session():
    focus = SessionFocus()

    assert focus.update([_d(7, MIN_FOCUS_COST_MS - 1)], lap=4) is None


def test_slightly_bigger_rival_does_not_steal_the_work():
    """Без запаса коуч метался бы каждый круг — это хуже, чем работать над
    вторым по важности."""
    focus = SessionFocus()
    focus.update([_d(7, 300.0)], lap=1)
    rows = {lap: [_d(7, 300.0), _d(3, 330.0)] for lap in range(2, 20)}

    events = _run(focus, rows, range(2, 20))

    assert events == []
    assert focus.state is not None
    assert focus.state.corner_id == 7


def test_much_bigger_rival_takes_over_after_the_driver_had_a_chance():
    focus = SessionFocus()
    focus.update([_d(7, 200.0)], lap=1)
    rows = {lap: [_d(7, 200.0), _d(3, 800.0)] for lap in range(2, 20)}

    events = _run(focus, rows, range(2, 20))

    assert [e.kind for e in events] == ["set"]
    assert events[0].corner_id == 3
    assert events[0].lap >= 1 + MIN_LAPS_BEFORE_SWITCH


def test_work_is_not_taken_away_before_the_driver_could_try():
    focus = SessionFocus()
    focus.update([_d(7, 200.0)], lap=1)
    rows = {lap: [_d(7, 200.0), _d(3, 900.0)]
            for lap in range(2, 1 + MIN_LAPS_BEFORE_SWITCH)}

    events = _run(focus, rows, range(2, 1 + MIN_LAPS_BEFORE_SWITCH))

    assert events == []
    assert focus.state.corner_id == 7


def test_improving_work_is_never_abandoned_for_a_bigger_problem():
    """Смена задания посреди прогресса стирает единственную обратную связь."""
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    rows = {lap: [_d(7, 150.0), _d(3, 900.0)] for lap in range(2, 30)}

    events = _run(focus, rows, range(2, 30))

    assert [e.corner_id for e in events] == [7]
    assert focus.state is not None
    assert focus.state.corner_id == 7


def test_one_lucky_lap_is_not_progress():
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    rows: dict[int, list[CornerDiagnosis]] = {}
    for lap in range(2, 20):
        rows[lap] = [_d(7, 100.0 if lap == 9 else 400.0)]

    events = _run(focus, rows, range(2, 20))

    assert events == []


def test_one_lucky_lap_does_not_close_a_corner():
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    rows: dict[int, list[CornerDiagnosis]] = {}
    for lap in range(2, 20):
        rows[lap] = [] if lap == 9 else [_d(7, 400.0)]

    events = _run(focus, rows, range(2, 20))

    assert events == []
    assert focus.state is not None


def test_closed_corner_is_not_taken_back_immediately():
    """Сразу после закрытия цена ещё дрожит около порога — вернуться туда
    на следующем круге значит объявить работу, которой нет."""
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    closed = _run(focus, {}, range(2, 10))          # закрыли седьмой
    assert [e.kind for e in closed] == ["fixed"]
    closed_at = closed[0].lap
    assert focus.state is None

    laps = range(closed_at + 1, closed_at + RELAPSE_LAPS)
    events = _run(focus, {lap: [_d(7, 400.0)] for lap in laps}, laps)

    assert events == []
    # А после карантина — снова полноценная работа, если проблема вернулась.
    assert focus.update([_d(7, 400.0)], closed_at + RELAPSE_LAPS) is not None


def test_events_never_come_closer_than_the_cooldown():
    """Три события на фокус и эта пауза вместе дают потолок болтливости."""
    focus = SessionFocus()
    rows: dict[int, list[CornerDiagnosis]] = {}
    for lap in range(1, 40):
        rows[lap] = [_d(lap % 5 + 1, 900.0)]        # каждый круг новая проблема

    events = _run(focus, rows, range(1, 40))

    laps = [e.lap for e in events]
    assert all(b - a >= EVENT_COOLDOWN_LAPS for a, b in zip(laps, laps[1:]))


def test_at_most_one_event_per_lap():
    focus = SessionFocus()
    for lap in range(1, 40):
        event = focus.update([_d(7, 400.0), _d(3, 900.0)], lap)
        assert event is None or isinstance(event.kind, str)


def test_silence_when_there_is_nothing_to_work_on():
    focus = SessionFocus()

    assert _run(focus, {lap: [] for lap in range(1, 20)}, range(1, 20)) == []
    assert focus.state is None
    assert focus.to_dict() is None


# ── Форма наружу ─────────────────────────────────────────────────────────────

def test_state_dict_carries_price_gain_and_evidence():
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)
    focus.update([_d(7, 250.0)], lap=2)

    data = focus.to_dict()

    assert data is not None
    assert data["corner_id"] == 7
    assert data["baseline_ms"] == 400
    assert data["current_ms"] == 250
    assert data["gain_ms"] == 150
    assert data["cause"] == "lockup"
    assert data["evidence"]
    assert data["since_lap"] == 1


def test_gain_is_never_negative():
    """Стало хуже — это не «отрицательный прогресс», это отсутствие прогресса."""
    focus = SessionFocus()
    focus.update([_d(7, 200.0)], lap=1)
    focus.update([_d(7, 600.0)], lap=2)

    assert focus.state.gain_ms == 0.0


def test_cause_is_refined_as_evidence_accumulates():
    """Сначала видно только отклонение техники, потом набирается повтор срыва."""
    focus = SessionFocus()
    focus.update([_d(7, 400.0, cause="brake")], lap=1)
    focus.update([_d(7, 380.0, cause="lockup")], lap=2)

    assert focus.state.cause == "lockup"
    assert focus.state.cause_kind == "mistake"


def test_reset_forgets_everything():
    focus = SessionFocus()
    focus.update([_d(7, 400.0)], lap=1)

    focus.reset()

    assert focus.state is None
    assert focus.update([_d(7, 400.0)], lap=2) is not None

def test_confirmation_takes_more_than_a_single_observation():
    """Страховка на само число: если CONFIRM_LAPS уедет в 1, тест упадёт."""
    assert CONFIRM_LAPS >= 2


def test_every_spoken_threshold_is_above_the_pronounceable_floor():
    """Порог события не может быть ниже порога произносимого.

    Иначе событие возникает, эфир его не произносит (величину нечем назвать), а
    фокус уже считает похвалу выданной: единственная обратная связь пропадает
    молча. Ровно тот класс отказа, который в этом проекте запрещён отдельно.
    """
    from core.num_to_words import MIN_SPOKEN_MS

    assert PROGRESS_MIN_MS >= MIN_SPOKEN_MS
    assert MIN_FOCUS_COST_MS >= MIN_SPOKEN_MS
