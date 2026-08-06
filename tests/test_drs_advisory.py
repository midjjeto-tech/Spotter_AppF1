"""DRSAdvisoryTracker — единый update(gap_front_ms, drs_allowed, now),
детерминированный независимо от порядка UDP-пакетов (LapData/CarStatusData).
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from core.strategy_ai.drs_advisory import MIN_REPEAT_S, DRSAdvisoryTracker


def test_enters_range_below_1000ms():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)   # baseline: не в зоне
    phrase = t.update(gap_front_ms=900, drs_allowed=False, now=101.0)
    assert phrase is not None


def test_stays_in_hysteresis_band_no_change():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)     # вошёл
    phrase = t.update(gap_front_ms=1100, drs_allowed=False, now=101.0)  # в полосе 1000-1200
    assert phrase is None


def test_exits_range_above_1200ms():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)
    # Exit must clear the anti-repeat window shared with entries (symmetric
    # suppression, see test_anti_repeat_suppresses_exit_within_window_of_prior_entry)
    # or it would itself be suppressed as "too soon after the last transition".
    phrase = t.update(gap_front_ms=1300, drs_allowed=False,
                       now=100.0 + MIN_REPEAT_S + 0.1)
    assert phrase is not None


def test_gap_none_forces_out_of_range():
    """Машина впереди пропала (пит/сход) -> _in_range сбрасывается
    принудительно, иначе новая близкая машина не даст 'вход'."""
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)          # вошёл
    t.update(gap_front_ms=None, drs_allowed=False, now=100.5)         # машина пропала
    # Anti-repeat 5с ещё не истёк с предыдущего входа -> следующий вход подавлен,
    # проверяем внутреннее состояние по следующему тесту с достаточным разрывом.
    phrase = t.update(gap_front_ms=800, drs_allowed=False, now=110.0)  # новая близкая машина
    assert phrase is not None   # без фикса None молчал бы (уже "в зоне")


def test_drs_allowed_edge_trigger_on():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    phrase = t.update(gap_front_ms=1500, drs_allowed=True, now=101.0)
    assert phrase is not None


def test_drs_allowed_edge_trigger_off():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=True, now=100.0)
    phrase = t.update(gap_front_ms=1500, drs_allowed=False, now=101.0)
    assert phrase is not None


def test_combined_phrase_when_entering_range_already_allowed():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=True, now=100.0)   # DRS уже разрешена
    phrase = t.update(gap_front_ms=900, drs_allowed=True, now=101.0)  # входит в зону
    # Трекер отдаёт семантический код, не готовую строку: формулировки
    # живут в core/radio/phrases.py.
    from core.strategy_ai.drs_advisory import CODE_IN_RANGE_AND_ENABLED
    assert phrase == CODE_IN_RANGE_AND_ENABLED


def test_combined_phrase_when_allowed_turns_on_already_in_range():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)   # уже в зоне
    phrase = t.update(gap_front_ms=900, drs_allowed=True, now=101.0)  # DRS включается
    # Трекер отдаёт семантический код, не готовую строку: формулировки
    # живут в core/radio/phrases.py.
    from core.strategy_ai.drs_advisory import CODE_IN_RANGE_AND_ENABLED
    assert phrase == CODE_IN_RANGE_AND_ENABLED


def test_anti_repeat_suppresses_second_enter_within_window():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    t.update(gap_front_ms=900, drs_allowed=False, now=101.0)    # вошёл, фраза 1, timer=101.0
    t.update(gap_front_ms=1300, drs_allowed=False, now=102.0)   # выход подавлен (< 5с от timer), timer не двигается
    phrase = t.update(gap_front_ms=900, drs_allowed=False, now=103.0)  # вошёл снова, всё ещё < 5с от timer=101.0
    assert phrase is None


def test_anti_repeat_allows_enter_after_window():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    t.update(gap_front_ms=900, drs_allowed=False, now=101.0)
    t.update(gap_front_ms=1300, drs_allowed=False, now=102.0)
    phrase = t.update(gap_front_ms=900, drs_allowed=False,
                       now=101.0 + MIN_REPEAT_S + 0.1)
    assert phrase is not None


def test_anti_repeat_suppresses_exit_within_window_of_prior_entry():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    t.update(gap_front_ms=900, drs_allowed=False, now=101.0)     # enters, timer=101.0
    phrase = t.update(gap_front_ms=1300, drs_allowed=False, now=102.0)  # exits 1s later, < 5s window
    assert phrase is None


def test_reset_clears_state():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=True, now=100.0)
    t.reset()
    phrase = t.update(gap_front_ms=1500, drs_allowed=False, now=100.5)
    assert phrase is None   # после сброса это не "выход", а исходное состояние
