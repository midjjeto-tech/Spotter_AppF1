"""Отчёт по полевому журналу (core/diag_report.py).

Смысл отчёта — различать похожие снаружи состояния. «Коуч молчал, потому что
сигнала не было» и «коуч молчал, потому что порог не взят» требуют
противоположных действий, и каждая проверка обязана уметь сказать не только
«ОК»/«ПРОБЛЕМА», но и «НЕТ ДАННЫХ». Поэтому здесь на каждую проверку приходится
по несколько тестов: один на плохой исход, один на хороший, один на пустой.
"""
from core.diag_report import (NODATA, OK, PROBLEM, WARN, Report, build_report)


def _start(**over) -> dict:
    base = {
        "kind": "session_start", "t": 1000.0, "app_version": "0.1.0",
        "frozen": False, "telemetry_source": "f1", "udp": "127.0.0.1:20777",
        "llm_provider": "gigachat", "driving_coach_enabled": True,
        "persona": "calm", "radio_style": "standard",
        "coach_thresholds": {"lockup_slip": -0.25, "wheelspin_slip": 0.2},
    }
    base.update(over)
    return base


def _packets(*ids: int, lap: int = 1) -> dict:
    return {"kind": "packets", "lap": lap,
            "counts": {str(i): 100 for i in ids}}


_ALL_F1 = (0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13)


def _check(report: Report, number: int):
    return next(c for c in report.checks if c.number == number)


# ── 1. Окружение ─────────────────────────────────────────────────────────────

def test_environment_is_read_from_the_startup_snapshot():
    report = build_report([_start()])

    check = _check(report, 1)
    assert check.verdict == OK
    assert any("0.1.0" in line for line in check.lines)
    assert any("ВКЛ" in line for line in check.lines)


def test_a_disabled_coach_is_flagged_up_front():
    """Иначе следующие семь пунктов объясняются по отдельности, хотя причина
    одна и написана в первой строке."""
    report = build_report([_start(driving_coach_enabled=False)])

    check = _check(report, 1)
    assert check.verdict == WARN
    assert "выключен" in check.action


def test_a_journal_without_a_startup_snapshot_says_so():
    report = build_report([_packets(*_ALL_F1)])

    assert _check(report, 1).verdict == NODATA


# ── 2. Пакеты ────────────────────────────────────────────────────────────────

def test_all_packets_present_is_ok():
    report = build_report([_start(), _packets(*_ALL_F1)])

    assert _check(report, 2).verdict == OK


def test_a_missing_motion_ex_names_what_stops_working():
    """Главный случай: без пакета 13 молчит ВЕСЬ коуч, а по эфиру это выглядит
    как «коуч ничего не даёт»."""
    report = build_report([_start(), _packets(*[p for p in _ALL_F1 if p != 13])])

    check = _check(report, 2)
    assert check.verdict == PROBLEM
    assert any("НЕТ 13" in line and "коуч" in line for line in check.lines)


def test_a_missing_essential_packet_points_at_the_game_settings():
    report = build_report([_start(), _packets(0, 3, 4)])

    check = _check(report, 2)
    assert check.verdict == PROBLEM
    assert "UDP" in check.action


def test_iracing_is_reported_as_its_own_case_not_as_broken_udp():
    """Совет «включите UDP в F1 25» пользователю iRacing бесполезен."""
    report = build_report([_start(telemetry_source="iracing"),
                           {"kind": "packets", "lap": 1, "counts": {"-1": 500}}])

    check = _check(report, 2)
    assert check.verdict == WARN
    assert "iRacing" in check.lines[0]
    assert "UDP" not in (check.action or "")


def test_nothing_recognisable_says_nothing_arrives_not_a_bare_prefix():
    """`+` связывает раньше `or`, поэтому фолбэк «ничего» относился к уже
    склеенной строке — то есть был мёртв, и отчёт обрывался на «приходят: ».
    Журнал с нераспознаваемыми ключами переписи — не выдумка: строку могло
    порвать на середине при убитом приложении."""
    report = build_report([_start(), {"kind": "packets", "lap": 1,
                                     "counts": {"мусор": 5}}])

    check = _check(report, 2)
    assert check.lines[0] == "приходят: ничего"


def test_no_completed_lap_means_no_packet_census():
    report = build_report([_start()])

    assert _check(report, 2).verdict == NODATA


# ── 3. Трасса ────────────────────────────────────────────────────────────────

def test_track_layout_is_reported_with_its_corner_types():
    report = build_report([_start(), {"kind": "track", "track_id": 7,
                                      "track": "Monza", "corners": 11,
                                      "types": {"slow": 4, "fast": 7}}])

    check = _check(report, 3)
    assert check.verdict == OK
    assert any("Monza" in line for line in check.lines)
    assert any("slow 4" in line for line in check.lines)


def test_a_track_without_a_layout_is_a_problem():
    report = build_report([_start(), {"kind": "track", "track_id": 99,
                                      "track": "Unknown", "corners": 0}])

    check = _check(report, 3)
    assert check.verdict == PROBLEM
    assert "разметки" in check.action


# ── 4. Сигнал ────────────────────────────────────────────────────────────────

def _signals(minimum: float, maximum: float, over: int, lap: int = 1) -> dict:
    return {"kind": "signals", "lap": lap, "channels": {
        "lockup.slip_fl": {"n": 500, "min": minimum, "max": maximum,
                           "over": {"-0.25": over}},
        "wheelspin.slip_rl": {"n": 500, "min": 0.0, "max": maximum,
                              "over": {"0.2": over}},
    }}


def test_a_live_signal_that_crosses_thresholds_is_ok():
    report = build_report([_start(), _signals(-0.4, 0.3, over=12)])

    assert _check(report, 4).verdict == OK


def test_a_flat_signal_means_the_offsets_are_wrong():
    report = build_report([_start(), _signals(0.0, 0.0, over=0)])

    check = _check(report, 4)
    assert check.verdict == PROBLEM
    assert "нулями" in check.action


def test_a_live_signal_that_never_crosses_names_both_possibilities():
    """Различить «чистый заезд» и «завышенный порог» изнутри нельзя, и честнее
    назвать оба, чем выбрать один наугад."""
    report = build_report([_start(), _signals(-0.1, 0.05, over=0)])

    check = _check(report, 4)
    assert check.verdict == WARN
    assert "чистый заезд" in check.action and "завышены" in check.action


def test_no_signal_records_point_at_the_packet_check():
    report = build_report([_start()])

    check = _check(report, 4)
    assert check.verdict == NODATA
    assert "пункт 2" in check.action


# ── 5-9. Коуч и поле ─────────────────────────────────────────────────────────

def test_mistakes_are_grouped_by_kind_and_place():
    records = [_start()] + [
        {"kind": "coach_mistake", "mistake_kind": "lockup", "corner_id": 7,
         "speak": "pending"},
        {"kind": "coach_mistake", "mistake_kind": "lockup", "corner_id": 7,
         "speak": "gated_by_repeat_rule"},
        {"kind": "coach_mistake", "mistake_kind": "oversteer", "corner_id": 3,
         "speak": "gated_by_repeat_rule"},
    ]

    check = _check(build_report(records), 5)
    assert check.verdict == OK
    assert "lockup ×2" in check.lines[0]
    assert "поворот 7 ×2" in check.lines[1]
    assert "1 из 3" in check.lines[2]


def test_mistakes_mostly_outside_corners_are_flagged():
    """Срыв вне поворота коуч не озвучивает — назвать место нечем."""
    records = [_start()] + [
        {"kind": "coach_mistake", "mistake_kind": "oversteer",
         "corner_id": None, "speak": "pending"} for _ in range(4)
    ]

    check = _check(build_report(records), 5)
    assert check.verdict == WARN
    assert "вне поворотов" in check.action


def test_a_reference_with_too_few_corners_cannot_publish():
    records = [_start(), {"kind": "coach_reference_lap", "lap": 3,
                          "reference_source": "career", "reference_ms": 90000,
                          "corners_compared": 3, "advice": None}]

    check = _check(build_report(records), 6)
    assert check.verdict == PROBLEM
    assert "пяти" in check.action


def test_a_reference_that_never_finds_a_deviation_suspects_the_thresholds():
    records = [_start()] + [
        {"kind": "coach_reference_lap", "lap": i, "reference_source": "session",
         "reference_ms": 90000, "corners_compared": 9, "advice": None}
        for i in range(1, 6)
    ]

    check = _check(build_report(records), 6)
    assert check.verdict == WARN
    assert "compare.py" in check.action


def test_a_session_without_a_focus_explains_why():
    records = [_start(), {"kind": "coach_lesson", "lap": 8, "focus": None,
                          "focus_event": None, "potential": 91000, "top": []}]

    check = _check(build_report(records), 7)
    assert check.verdict == WARN
    assert "не назначалась" in check.action


def test_focus_events_and_the_current_work_are_listed():
    records = [_start(),
               {"kind": "coach_lesson", "lap": 4, "focus_event": "set",
                "focus": {"corner_id": 7, "baseline_ms": 400,
                          "current_ms": 400, "status": "working"},
                "potential": 91000,
                "top": [{"corner_id": 7, "cost_ms": 400}]},
               {"kind": "coach_lesson", "lap": 9, "focus_event": "progress",
                "focus": {"corner_id": 7, "baseline_ms": 400,
                          "current_ms": 180, "status": "improving"},
                "potential": 90800,
                "top": [{"corner_id": 7, "cost_ms": 180}]}]

    check = _check(build_report(records), 7)
    assert check.verdict == OK
    assert "set, progress" in check.lines[1]
    assert any("поворот 7" in line for line in check.lines)


def test_field_pace_reports_place_and_silence():
    records = [_start(),
               {"kind": "field_pace", "lap": 5, "topic": "weak", "sector": 2,
                "rank": 7, "field_size": 12, "gap_ms": 1230},
               {"kind": "field_pace_silent", "why": "repeat_rule"},
               {"kind": "field_pace_silent", "why": "repeat_rule"}]

    check = _check(build_report(records), 8)
    assert check.verdict == OK
    assert "7 из 12" in check.lines[0]
    assert "repeat_rule ×2" in check.lines[2]


def test_silence_reasons_are_ranked_and_translated():
    records = [_start()] + [
        {"kind": "coach_silent", "why": "off_focus"} for _ in range(3)
    ] + [{"kind": "coach_silent", "why": "no_corner_to_name"}]

    check = _check(build_report(records), 9)
    assert check.verdict == OK
    assert check.lines[0].startswith("off_focus ×3")
    assert "—" in check.lines[0]        # человеческая формулировка рядом


def test_a_disabled_coach_dominating_the_silence_is_a_problem_with_an_action():
    records = [_start(driving_coach_enabled=False)] + [
        {"kind": "coach_silent", "why": "coach_disabled_in_settings"}
        for _ in range(5)
    ]

    check = _check(build_report(records), 9)
    assert check.verdict == PROBLEM
    assert "Голос" in check.action


# ── 10. Ошибки ───────────────────────────────────────────────────────────────

def test_log_errors_are_deduplicated_and_surfaced():
    errors = ["ERROR failed to speak", "ERROR failed to speak",
              "Traceback (most recent call last)"]

    check = _check(build_report([_start()], errors), 10)
    assert check.verdict == PROBLEM
    assert "различных: 2" in check.lines[0]


def test_a_clean_log_is_ok():
    assert _check(build_report([_start()], []), 10).verdict == OK


# ── Форма отчёта ─────────────────────────────────────────────────────────────

def test_the_report_ends_with_a_problem_summary():
    report = build_report([_start(), _packets(0, 1, 2)])

    text = report.to_text()
    assert "SPOTTER APP — ДИАГНОСТИКА ЗАЕЗДА" in text
    assert "ИТОГО: требуют внимания" in text
    assert report.problems


def test_a_healthy_session_says_so_plainly():
    records = [_start(), _packets(*_ALL_F1),
               {"kind": "track", "track_id": 7, "track": "Monza",
                "corners": 11, "types": {"slow": 4, "fast": 7}},
               _signals(-0.4, 0.3, over=12),
               {"kind": "coach_mistake", "mistake_kind": "lockup",
                "corner_id": 7, "speak": "pending"},
               {"kind": "coach_reference_lap", "lap": 3,
                "reference_source": "career", "reference_ms": 90000,
                "corners_compared": 9,
                "advice": {"metric": "brake", "corner_id": 7}},
               {"kind": "coach_lesson", "lap": 6, "focus_event": "set",
                "focus": {"corner_id": 7, "baseline_ms": 400,
                          "current_ms": 400, "status": "working"},
                "potential": 90500, "top": [{"corner_id": 7, "cost_ms": 400}]},
               {"kind": "field_pace", "lap": 6, "topic": "weak", "sector": 2,
                "rank": 7, "field_size": 12, "gap_ms": 1230},
               {"kind": "coach_silent", "why": "off_focus"}]

    report = build_report(records, [])

    assert report.problems == []
    assert "ИТОГО: проблем не найдено" in report.to_text()


def test_the_report_stays_small_enough_to_paste():
    """Отчёт, который не влезает в сообщение, повторяет судьбу журнала, который
    он сжимает."""
    records = [_start(), _packets(*_ALL_F1)]
    records += [{"kind": "coach_silent", "why": f"reason_{i % 7}"}
                for i in range(500)]
    records += [{"kind": "coach_mistake", "mistake_kind": "lockup",
                 "corner_id": i % 12, "speak": "pending"} for i in range(500)]

    text = build_report(records, [f"ERROR {i}" for i in range(200)]).to_text()

    assert len(text.splitlines()) < 120


def test_an_empty_journal_does_not_crash():
    report = build_report([], [])

    assert report.to_text()
    assert all(c.verdict == NODATA for c in report.checks
               if c.number not in (10,))


def test_garbage_records_do_not_crash_the_report():
    report = build_report([None, "мусор", 42, {"kind": None}, _start()], [])

    assert report.to_text()
