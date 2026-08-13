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


# --------------------------------------------------------------------------- #
# Эскалация компаньон-реплики к штрафу (track_limits.penalty_1/2/3).
# Разбор живого заезда 2026-08-11: одна захардкоженная строка прозвучала за
# гонку восемь раз дословно, дважды с разрывом в 11 секунд.
# --------------------------------------------------------------------------- #

def test_penalty_tier_escalates_then_saturates():
    t = TrackLimitsTracker()
    assert t.penalty_tier() == 1          # штрафов ещё не было — первая ступень
    t.note_penalty(now=100.0)
    assert t.penalty_tier() == 1
    t.note_penalty(now=200.0)
    assert t.penalty_tier() == 2
    t.note_penalty(now=300.0)
    assert t.penalty_tier() == 3
    t.note_penalty(now=400.0)
    assert t.penalty_tier() == 3          # «третий и дальше», не четвёртая ступень


def test_suppressed_companion_still_counts_toward_escalation():
    """Штраф случился независимо от того, объявили мы его или промолчали."""
    t = TrackLimitsTracker()
    t.check_warning(0, now=100.0)
    t.check_warning(1, now=101.0)                      # живое предупреждение
    assert t.note_penalty(now=101.5) is False          # компаньон подавлен
    assert t.penalty_tier() == 1
    assert t.note_penalty(now=200.0) is True
    assert t.penalty_tier() == 2                       # а не «снова первый»


def test_reset_clears_escalation():
    t = TrackLimitsTracker()
    t.note_penalty(now=100.0)
    t.note_penalty(now=200.0)
    t.reset()
    assert t.penalty_tier() == 1


def test_each_tier_has_its_own_wording():
    from core.radio import phrases
    said = {
        phrases.render(f"track_limits.penalty_{tier}", None,
                       selector_key="sess:penalty:lap_12")
        for tier in (1, 2, 3)
    }
    assert len(said) == 3


def test_third_tier_never_names_a_number():
    """Ступень 3 звучит и на четвёртом штрафе — числительное было бы враньём."""
    from core.radio import phrases
    spec = phrases.spec_for("track_limits.penalty_3")
    for variant in spec.variants:
        assert "трет" not in variant.lower()
