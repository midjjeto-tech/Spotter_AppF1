"""TrackLimitsTracker — edge-triggered предупреждение по росту счётчика
m_cornerCuttingWarnings + подавление рядом с трек-лимитным PENA.
См. docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md.
"""
from core.strategy_ai import track_limits
from core.strategy_ai.track_limits import SUPPRESSION_WINDOW_S, TrackLimitsTracker


def test_first_tick_never_warns():
    t = TrackLimitsTracker()
    assert t.check_warning(count=1, now=100.0) is None


def test_warns_on_increase():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    phrase = t.check_warning(count=2, now=101.0)
    assert phrase == track_limits.CODE_WARNING


def test_no_warning_on_same_count():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    assert t.check_warning(count=1, now=101.0) is None


def test_no_warning_on_decrease():
    t = TrackLimitsTracker()
    t.check_warning(count=3, now=100.0)
    assert t.check_warning(count=0, now=101.0) is None


def test_penalty_suppresses_warning_within_window():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    t.note_penalty(now=101.0)
    result = t.check_warning(count=2, now=101.0 + SUPPRESSION_WINDOW_S - 0.1)
    assert result is None


def test_warning_resumes_after_suppression_window():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    t.note_penalty(now=101.0)
    phrase = t.check_warning(count=2, now=101.0 + SUPPRESSION_WINDOW_S + 0.1)
    assert phrase == track_limits.CODE_WARNING


def test_reset_clears_state():
    t = TrackLimitsTracker()
    t.check_warning(count=5, now=100.0)
    t.note_penalty(now=100.0)
    t.reset()
    assert t.check_warning(count=1, now=100.5) is None   # снова "первый тик"


def test_note_penalty_true_when_no_recent_warning():
    t = TrackLimitsTracker()
    assert t.note_penalty(now=100.0) is True


def test_live_warning_then_penalty_suppresses_companion():
    """Обратный порядок пакетов (живой тик раньше PENA того же инцидента) —
    ровно тот случай, что не ловился до симметричного фикса."""
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    phrase = t.check_warning(count=2, now=101.0)
    assert phrase == track_limits.CODE_WARNING
    should_announce = t.note_penalty(now=101.0 + SUPPRESSION_WINDOW_S - 0.1)
    assert should_announce is False


def test_note_penalty_true_after_suppression_window_since_warning():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    t.check_warning(count=2, now=101.0)
    should_announce = t.note_penalty(now=101.0 + SUPPRESSION_WINDOW_S + 0.1)
    assert should_announce is True


def test_note_penalty_always_records_even_when_suppressed():
    """note_penalty() обновляет _last_announcement_t БЕЗУСЛОВНО (даже когда
    возвращает False) — окно подавления для следующего живого тика должно
    сработать, а не остаться на старом (более раннем) значении."""
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    t.check_warning(count=2, now=101.0)               # живое предупреждение
    t.note_penalty(now=101.5)                          # PENA, подавлен (False)
    result = t.check_warning(count=3, now=101.5 + SUPPRESSION_WINDOW_S - 0.1)
    assert result is None                               # окно отсчитывается от PENA (101.5), не от 101.0
