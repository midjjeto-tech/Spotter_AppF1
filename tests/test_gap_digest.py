"""GapDigestTracker — детерминированная радио-сводка по гэпам инженера.
См. docs/superpowers/specs/2026-07-10-engineer-gap-digest-design.md.
"""
from core.strategy_ai.gap_digest import (
    CODE_ERS,
    TREND_THRESHOLD_MS,
    GapDigestTracker,
)


def test_first_reading_has_no_trend_word():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None)
    assert out == ("gap.front_first",)


def test_both_gaps_combined_in_one_phrase():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=2500)
    assert out == ("gap.front_first", "gap.behind_first")


def test_no_data_returns_none():
    t = GapDigestTracker()
    assert t.build(gap_front_ms=None, gap_behind_ms=None) is None


def test_zero_gap_filtered_as_no_car():
    """0 = сам лидер / нет машины (конвенция commentator/timeline.py::_fmt_gap),
    не «нулевой отрыв»."""
    t = GapDigestTracker()
    assert t.build(gap_front_ms=0, gap_behind_ms=None) is None


def test_closing_trend_after_second_reading():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    out = t.build(gap_front_ms=1800 - TREND_THRESHOLD_MS, gap_behind_ms=None)
    assert out == ("gap.front_closing",)


def test_opening_trend_after_second_reading():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    out = t.build(gap_front_ms=1800 + TREND_THRESHOLD_MS, gap_behind_ms=None)
    assert out == ("gap.front_growing",)


def test_steady_trend_when_change_below_threshold():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    out = t.build(gap_front_ms=1800 + TREND_THRESHOLD_MS - 1, gap_behind_ms=None)
    assert out == ("gap.front_stable",)   # 1800+299=2099мс → 2.1, фраза озвучивает ТЕКУЩИЙ гэп


def test_reset_clears_trend_memory():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    t.reset()
    out = t.build(gap_front_ms=1800 - TREND_THRESHOLD_MS, gap_behind_ms=None)
    assert out[0].startswith("gap.front_")          # без тренда — как первый замер


def test_leader_to_real_gap_transition_has_no_false_trend():
    """Игрок был лидером (0, отфильтровано) -> появилась машина впереди —
    это НОВЫЙ замер без реального тренда, а не "растёт с нуля"."""
    t = GapDigestTracker()
    t.build(gap_front_ms=0, gap_behind_ms=None)    # лидер, gap=0 отфильтрован
    out = t.build(gap_front_ms=1800, gap_behind_ms=None)
    assert out == ("gap.front_first",)            # не "растёт"


def test_ers_clause_is_deferred_not_baked_in():
    """Процент батареи НЕ вписывается при сборке: между сборкой и озвучкой
    проходят десятки секунд, а заряд успевает пройти полный цикл."""
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None, ers_percent=62.5)
    assert out == ("gap.front_first", CODE_ERS)
    assert "62" not in out


def test_ers_percent_none_not_appended():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None, ers_percent=None)
    assert out == ("gap.front_first",)


def test_ers_percent_alone_does_not_trigger_digest():
    """Батарея без гэпов НЕ запускает дайджест (анти-болтливость, spec п.3)."""
    t = GapDigestTracker()
    out = t.build(gap_front_ms=None, gap_behind_ms=None, ers_percent=62.0)
    assert out is None


# --- sector_comparison (Session History, packet 11) — та же схема, что ers_percent ---

def test_sector_comparison_appended_when_gap_present():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None,
                  sector_comparison="Ты быстрее Норрис в 2-м секторе на 0.7с.")
    assert out[0].startswith("gap.front_")


def test_sector_comparison_none_not_appended():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None, sector_comparison=None)
    assert out == ("gap.front_first",)


def test_sector_comparison_alone_does_not_trigger_digest():
    """Как и ERS — сравнение секторов без гэпов не запускает дайджест."""
    t = GapDigestTracker()
    out = t.build(gap_front_ms=None, gap_behind_ms=None,
                  sector_comparison="Ты быстрее Норрис в 2-м секторе на 0.7с.")
    assert out is None


def test_sector_comparison_is_appended_by_the_composer():
    """Сравнение секторов приходит свободной строкой из другого модуля —
    банк такие тексты не порождает, поэтому `compose` добавляет его как есть."""
    from core.radio import phrases

    t = GapDigestTracker()
    codes = t.build(gap_front_ms=1800, gap_behind_ms=None, ers_percent=62.5)
    assert codes == ("gap.front_first", CODE_ERS)

    sector = "Ты быстрее Норриса во втором секторе."
    text = phrases.compose(codes, selector_key="sit-1", extra=(sector,))
    assert text.endswith(sector)
    assert "{ers}" in text          # заряд ещё токен — его раскроет резолвер


def _spoken(codes, *, ers_percent, gap_front_ms=1800, extra=()):
    """Пройти путь фрагменты → compose → резолвер, как это делает движок."""
    from core.radio import phrases, resolver
    from core.radio.message import build_message

    text = phrases.compose(codes, selector_key="sit-1", extra=extra)
    message = build_message(
        {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer",
         "created_at": 0.0, "created_mono": 0.0},
        phrase=text, now=0.0, now_mono=0.0)
    return resolver.resolve_for_playback(
        message, {"ers_percent": ers_percent, "gap_front_ms": gap_front_ms}, 1.0)


def test_value_at_speak_time_wins_over_build_time():
    """Собрано при 62%, озвучено при 14% — звучит 14."""
    codes = GapDigestTracker().build(gap_front_ms=1800, gap_behind_ms=None,
                                     ers_percent=62.5)
    text = _spoken(codes, ers_percent=14.0).text
    assert "14" in text and "62" not in text


def test_clause_is_dropped_when_the_value_is_gone():
    """Телеметрия пропала — про батарею молчим, гэп говорим."""
    codes = GapDigestTracker().build(gap_front_ms=1800, gap_behind_ms=None,
                                     ers_percent=62.5)
    text = _spoken(codes, ers_percent=None).text
    assert "атаре" not in text
    assert "1,8" in text


def test_no_double_spaces_when_a_clause_is_dropped():
    codes = GapDigestTracker().build(
        gap_front_ms=1800, gap_behind_ms=None, ers_percent=62.5)
    text = _spoken(codes, ers_percent=None,
                   extra=("Ты быстрее Норриса во втором секторе.",)).text
    assert "  " not in text


def test_no_token_ever_leaks_into_speech():
    """Ни при каком значении в озвучку не должна утечь фигурная скобка."""
    codes = GapDigestTracker().build(gap_front_ms=1800, gap_behind_ms=None,
                                     ers_percent=62.5)
    for value in (0.0, 14.0, 100.0, None):
        result = _spoken(codes, ers_percent=value)
        assert "{" not in getattr(result, "text", "")


def test_zero_charge_is_spoken_not_dropped():
    """0% — валидные данные («батарея пустая»), не отсутствие данных."""
    codes = GapDigestTracker().build(gap_front_ms=1800, gap_behind_ms=None,
                                     ers_percent=0.0)
    assert "0 процентов" in _spoken(codes, ers_percent=0.0).text


def test_digest_survives_the_resolver_at_all():
    """Регрессия на реальный баг: сводка несла legacy-токен `{ers_clause}`,
    которого новый резолвер не знал, а неизвестное поле по умолчанию ОТМЕНЯЕТ
    сообщение. Самая частая реплика инженера молча пропадала целиком."""
    from core.radio.resolver import Cancellation

    codes = GapDigestTracker().build(gap_front_ms=1800, gap_behind_ms=2500,
                                     ers_percent=62.5)
    result = _spoken(codes, ers_percent=40.0)
    assert not isinstance(result, Cancellation), getattr(result, "reason", None)
