"""core/radio/resolver.py — финальное разрешение волатильных данных.

Проверяется главное обещание Task 4: число, вписанное в текст, соответствует
моменту ОЗВУЧКИ, а не моменту публикации события. Между ними — очередь событий,
пауза до 9 с, очередь воспроизведения и сетевой синтез.
"""
import pytest

from core.radio import resolver
from core.radio.message import RadioCancelReason, ResolvedRadioMessage, build_message
from core.radio.resolver import Cancellation, FieldPolicy, resolve_for_playback


def _msg(phrase, *, code="ENGINEER_GAP_DIGEST", mono=0.0, snapshot=None,
         phrase_code=None):
    event = {"event_code": code, "speaker": "engineer",
             "created_at": 1000.0, "created_mono": mono}
    return build_message(event, phrase=phrase, phrase_code=phrase_code,
                         now=1000.0, now_mono=mono, telemetry=snapshot)


def _text(result):
    assert isinstance(result, ResolvedRadioMessage), result
    return result.text


def _reason(result):
    assert isinstance(result, Cancellation), result
    return result.reason


# ── Главный сценарий: собрано при 60%, звучит при 14% ────────────────────────

def test_value_from_playback_time_wins_over_publish_time():
    message = _msg("Батарея {ers}.", snapshot={"ers_percent": 60.0})
    result = resolve_for_playback(message, {"ers_percent": 14.0}, 1.0)

    assert "14" in _text(result)
    assert "60" not in _text(result)


def test_resolution_happens_after_all_the_waiting():
    """Резолв берёт снимок, переданный вызывающим, и ничего не запоминает —
    поэтому его можно (и нужно) вызывать сколь угодно поздно."""
    message = _msg("Батарея {ers}.")
    early = resolve_for_playback(message, {"ers_percent": 60.0}, 0.5)
    late = resolve_for_playback(message, {"ers_percent": 14.0}, 5.0)

    assert "60" in _text(early)
    assert "14" in _text(late)


# ── ERS ─────────────────────────────────────────────────────────────────────

def test_ers_clause_is_dropped_when_telemetry_disappeared():
    message = _msg("Батарея {ers}. Отрыв впереди {gap}.")
    result = resolve_for_playback(
        message, {"ers_percent": None, "gap_front_ms": 1300}, 1.0)

    text = _text(result)
    assert "атарея" not in text          # клауза убрана целиком
    assert "1,3" in text                  # гэп-часть осталась


def test_ers_zero_is_a_valid_value():
    message = _msg("Батарея {ers}.")
    assert "0" in _text(resolve_for_playback(message, {"ers_percent": 0.0}, 1.0))


def test_ers_out_of_range_drops_the_clause_instead_of_speaking_nonsense():
    """Уехавший после патча игры офсет давал «Батарея 4200%»."""
    message = _msg("Батарея {ers}. Отрыв впереди {gap}.")
    result = resolve_for_playback(
        message, {"ers_percent": 4200.0, "gap_front_ms": 1300}, 1.0)

    assert "4200" not in _text(result)
    assert "1,3" in _text(result)


def test_negative_ers_never_reaches_tts():
    message = _msg("Батарея {ers}. Отрыв впереди {gap}.")
    result = resolve_for_playback(
        message, {"ers_percent": -5.0, "gap_front_ms": 1300}, 1.0)
    assert "-5" not in _text(result)


def test_no_placeholder_ever_survives_resolution():
    message = _msg("Батарея {ers}.")
    result = resolve_for_playback(message, {"ers_percent": 42.0}, 1.0)
    assert "{" not in _text(result)


# ── Gap ─────────────────────────────────────────────────────────────────────

def test_gap_is_refreshed_before_synthesis():
    message = _msg("Отрыв впереди {gap}.")
    result = resolve_for_playback(message, {"gap_front_ms": 2400}, 1.0)
    assert "2,4" in _text(result)


def test_missing_gap_cancels_the_whole_line():
    """«Отрыв впереди» без числа не значит ничего — в отличие от сводки без
    клаузы про батарею."""
    message = _msg("Отрыв впереди {gap}.")
    assert _reason(resolve_for_playback(
        message, {"gap_front_ms": None}, 1.0)) is RadioCancelReason.DATA_UNAVAILABLE


def test_negative_gap_is_rejected_as_invalid():
    message = _msg("Отрыв впереди {gap}.")
    assert _reason(resolve_for_playback(
        message, {"gap_front_ms": -400}, 1.0)) is RadioCancelReason.INVALID_DATA


def test_leader_zero_gap_does_not_become_a_false_line():
    """gap_front=0 у лидера — это «машины впереди нет», а не «отрыв 0,0».
    Ноль обязан отсекаться ДО резолвера (так делают gap_digest и
    situation_dedup); резолвер лишь не должен превращать его в «0,0»
    молча — он отдаёт валидный текст, поэтому ответственность остаётся на
    вызывающем, и этот тест фиксирует границу."""
    message = _msg("Отрыв впереди {gap}.")
    result = resolve_for_playback(message, {"gap_front_ms": 0}, 1.0)
    # Ноль формально в допустимом диапазоне: резолвер его пропустит.
    assert "0,0" in _text(result)


def test_huge_gap_is_rejected():
    message = _msg("Отрыв впереди {gap}.")
    assert _reason(resolve_for_playback(
        message, {"gap_front_ms": 9_000_000}, 1.0)) is RadioCancelReason.INVALID_DATA


# ── Position ────────────────────────────────────────────────────────────────

def test_current_position_is_refreshed():
    message = _msg("Ты {position}.", code="POSITION_CALL")
    assert "пятый" in _text(resolve_for_playback(message, {"position": 5}, 1.0))


def test_position_is_spoken_as_a_word_not_a_bare_number():
    message = _msg("Ты {position}.", code="POSITION_CALL")
    text = _text(resolve_for_playback(message, {"position": 3}, 1.0))
    assert "третий" in text


def test_impossible_position_is_rejected():
    message = _msg("Ты {position}.", code="POSITION_CALL")
    assert _reason(resolve_for_playback(
        message, {"position": 99}, 1.0)) is RadioCancelReason.INVALID_DATA


# ── Исторические факты ──────────────────────────────────────────────────────

def test_rival_name_is_a_historical_fact_and_is_not_refreshed():
    """«Норрис атакует» не должно превратиться в реплику про другого пилота
    только потому, что рядом теперь кто-то ещё."""
    message = _msg("{rival} атакует.", code="BATTLE",
                   snapshot={"rival": "Норрис"})
    result = resolve_for_playback(message, {"rival": "Албон"}, 1.0)
    assert "Норрис" in _text(result)
    assert "Албон" not in _text(result)


def test_compound_is_a_historical_fact():
    message = _msg("Комплект {compound}.", snapshot={"compound": "софт"})
    result = resolve_for_playback(message, {"compound": "хард"}, 1.0)
    assert "софт" in _text(result)


def test_historical_field_without_a_snapshot_value_cancels():
    message = _msg("{rival} атакует.", code="BATTLE")
    assert isinstance(resolve_for_playback(message, {}, 1.0), Cancellation)


def test_field_policies_are_centralised_and_queryable():
    assert resolver.policy_for("ers") is FieldPolicy.REFRESH
    assert resolver.policy_for("rival") is FieldPolicy.KEEP_ORIGINAL
    assert resolver.missing_policy_for("ers") is FieldPolicy.OMIT_CLAUSE
    # OMIT_CLAUSE: сводка склеивается из частей, и пропажа одного разрыва не
    # должна убивать реплику про другой. Одиночная гэп-реплика всё равно
    # отменяется — выброс единственной клаузы оставляет пустой текст.
    assert resolver.missing_policy_for("gap") is FieldPolicy.OMIT_CLAUSE


def test_unknown_field_is_not_refreshed_from_nowhere():
    assert resolver.policy_for("whatever") is FieldPolicy.KEEP_ORIGINAL


# ── Fuel: критическое предупреждение не теряется из-за числа ────────────────

def test_fuel_warning_survives_a_missing_number():
    """ТЗ §5: критическое предупреждение нельзя отменять только потому, что нет
    точного десятичного значения — команда остаётся."""
    message = _msg("Топлива {fuel}. Режим экономии.", code="STRAT_FUEL")
    result = resolve_for_playback(message, {"fuel_kg": None}, 1.0)

    text = _text(result)
    assert "Режим экономии." in text
    assert "{" not in text


def test_fuel_value_is_refreshed_with_its_unit():
    message = _msg("Топлива {fuel}.", code="STRAT_FUEL")
    text = _text(resolve_for_playback(message, {"fuel_kg": 2.4}, 1.0))
    assert "2,4" in text
    assert "килограмм" in text


# ── Tyres ───────────────────────────────────────────────────────────────────

def test_tyre_wear_is_refreshed():
    message = _msg("Износ {wear}.", code="TYRE_WARN")
    assert "48" in _text(resolve_for_playback(message, {"tyre_wear": 48.0}, 1.0))


def test_missing_wear_drops_the_clause_not_the_message():
    message = _msg("Износ {wear}. Береги резину.", code="TYRE_WARN")
    text = _text(resolve_for_playback(message, {"tyre_wear": None}, 1.0))
    assert "Береги резину." in text
    assert "Износ" not in text


# ── Weather ─────────────────────────────────────────────────────────────────

def test_rain_horizon_is_refreshed_with_correct_russian_agreement():
    message = _msg("Дождь через {minutes}.", code="ENGINEER_RAIN_ADVISORY")
    assert "1 минуту" in _text(resolve_for_playback(message, {"rain_minutes": 1}, 1.0))
    assert "2 минуты" in _text(resolve_for_playback(message, {"rain_minutes": 2}, 1.0))
    assert "5 минут" in _text(resolve_for_playback(message, {"rain_minutes": 5}, 1.0))


def test_vanished_forecast_cancels_the_rain_advisory():
    message = _msg("Дождь через {minutes}.", code="ENGINEER_RAIN_ADVISORY")
    assert _reason(resolve_for_playback(
        message, {"rain_minutes": None}, 1.0)) is RadioCancelReason.DATA_UNAVAILABLE


# ── TTL: monotonic, многократные проверки ───────────────────────────────────

def test_expired_message_is_cancelled_with_a_reason():
    message = _msg("Держи слева!", code="SPOTTER_CAR_LEFT", mono=0.0)
    assert _reason(resolve_for_playback(
        message, {}, 500.0)) is RadioCancelReason.EXPIRED


def test_message_inside_its_ttl_resolves():
    message = _msg("Держи слева!", code="SPOTTER_CAR_LEFT", mono=0.0)
    assert isinstance(resolve_for_playback(message, {}, 0.5), ResolvedRadioMessage)


def test_ttl_uses_monotonic_not_wall_clock():
    """Прыжок wall-clock назад не должен «оживлять» просроченное сообщение."""
    message = _msg("Держи слева!", code="SPOTTER_CAR_LEFT", mono=100.0)
    # Wall-clock у сообщения 1000.0; проверяем по монотонной шкале.
    assert isinstance(resolve_for_playback(message, {}, 100.5), ResolvedRadioMessage)
    assert _reason(resolve_for_playback(
        message, {}, 1000.0)) is RadioCancelReason.EXPIRED


def test_message_without_ttl_never_expires():
    message = _msg("Есть штраф.", code="PENA", mono=0.0)
    assert isinstance(resolve_for_playback(message, {}, 100_000.0),
                      ResolvedRadioMessage)


def test_resolved_message_records_when_it_was_resolved():
    message = _msg("Батарея {ers}.")
    result = resolve_for_playback(message, {"ers_percent": 30.0}, 7.5)
    assert result.resolved_at_mono == 7.5
    assert result.message_id == message.id
    assert result.source_message is message


# ── Отказы и устойчивость ───────────────────────────────────────────────────

def test_empty_phrase_is_cancelled_not_spoken():
    message = _msg("")
    assert _reason(resolve_for_playback(
        message, {}, 1.0)) is RadioCancelReason.DATA_UNAVAILABLE


def test_all_clauses_omitted_cancels_instead_of_speaking_nothing():
    message = _msg("Батарея {ers}.")
    assert _reason(resolve_for_playback(
        message, {"ers_percent": None}, 1.0)) is RadioCancelReason.DATA_UNAVAILABLE


def test_resolver_never_raises_even_on_a_broken_snapshot():
    """Резолвер стоит на пути живого воркера: исключение остановило бы озвучку
    целиком."""
    class Hostile(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("снимок сломан")

    message = _msg("Батарея {ers}.")
    result = resolve_for_playback(message, Hostile(), 1.0)
    assert _reason(result) is RadioCancelReason.RESOLVE_FAILED


def test_unknown_token_is_reported_not_spoken():
    message = _msg("Что-то {совсем_неизвестное}.")
    result = resolve_for_playback(message, {}, 1.0)
    assert isinstance(result, Cancellation)


def test_resolved_text_is_whitespace_normalised():
    message = _msg("Батарея {ers}.   Отрыв впереди {gap}.")
    text = _text(resolve_for_playback(
        message, {"ers_percent": 30.0, "gap_front_ms": 1000}, 1.0))
    assert "  " not in text


def test_cancellation_reason_never_leaks_into_the_text():
    message = _msg("Отрыв впереди {gap}.")
    result = resolve_for_playback(message, {"gap_front_ms": None}, 1.0)
    assert isinstance(result, Cancellation)
    assert not hasattr(result, "text")


# ── Волатильные поля сообщения ──────────────────────────────────────────────

def test_volatile_fields_come_from_the_spec_when_the_code_is_known():
    message = _msg("Батарея {ers}.", phrase_code="ers.level")
    assert resolver.volatile_fields_of(message) == {"ers"}


def test_volatile_fields_fall_back_to_the_tokens_in_the_text():
    """Часть фраз собирают трекеры напрямую, без спеки банка."""
    message = _msg("Отрыв впереди {gap}. {ers_clause}")
    assert resolver.volatile_fields_of(message) == {"gap", "ers_clause"}


def test_sanity_ranges_are_exposed_for_tests():
    assert resolver.is_sane("ers", 0.0)
    assert resolver.is_sane("ers", 100.0)
    assert not resolver.is_sane("ers", 101.0)
    assert not resolver.is_sane("ers", -1.0)
