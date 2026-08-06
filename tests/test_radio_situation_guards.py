"""Проверки «ситуация ещё та же» и cache key (Task 4, §5/§11).

Числа обновить недостаточно: реплика может стать неверной не потому, что
значение устарело, а потому, что закончилась сама ситуация. Свежий гэп до
ДРУГОГО пилота — это не обновление, а ложь.
"""
import pytest

from core.radio import resolver
from core.radio.message import RadioCancelReason, ResolvedRadioMessage, build_message
from core.radio.resolver import Cancellation, resolve_for_playback


def _msg(phrase, *, code, phrase_code=None, event_snapshot=None, mono=0.0):
    event = {"event_code": code, "speaker": "engineer",
             "created_at": 1000.0, "created_mono": mono}
    return build_message(event, phrase=phrase, phrase_code=phrase_code,
                         now=1000.0, now_mono=mono, telemetry=event_snapshot)


def _reason(result):
    assert isinstance(result, Cancellation), result
    return result.reason


def _ok(result):
    assert isinstance(result, ResolvedRadioMessage), result
    return result.text


# ── Флаги: порядок фаз Safety Car ───────────────────────────────────────────

def test_deployed_does_not_speak_after_the_track_went_green():
    message = _msg("Safety Car на трассе.", code="SAFETY_CAR_DEPLOYED",
                   phrase_code="flag.safety_car_deployed")
    assert _reason(resolve_for_playback(
        message, {"safety_car_status": 0}, 1.0)) is RadioCancelReason.SITUATION_ENDED


def test_ending_does_not_speak_after_the_track_went_green():
    message = _msg("Safety Car уходит.", code="SAFETY_CAR_ENDING",
                   phrase_code="flag.safety_car_ending")
    assert _reason(resolve_for_playback(
        message, {"safety_car_status": 0}, 1.0)) is RadioCancelReason.SITUATION_ENDED


def test_deployed_still_speaks_while_the_safety_car_is_out():
    message = _msg("Safety Car на трассе.", code="SAFETY_CAR_DEPLOYED",
                   phrase_code="flag.safety_car_deployed")
    assert _ok(resolve_for_playback(message, {"safety_car_status": 1}, 1.0))


def test_clear_does_not_speak_if_the_safety_car_came_back_out():
    """«Возобновляемся» после нового выезда машины безопасности — прямая ложь."""
    message = _msg("Зелёный флаг.", code="SAFETY_CAR_CLEAR",
                   phrase_code="flag.safety_car_clear")
    assert _reason(resolve_for_playback(
        message, {"safety_car_status": 2}, 1.0)) is RadioCancelReason.SITUATION_ENDED


def test_clear_speaks_when_the_track_is_actually_green():
    message = _msg("Зелёный флаг.", code="SAFETY_CAR_CLEAR",
                   phrase_code="flag.safety_car_clear")
    assert _ok(resolve_for_playback(message, {"safety_car_status": 0}, 1.0))


def test_vsc_counts_as_an_active_safety_car_phase():
    message = _msg("Машина безопасности.", code="SAFETY_CAR_DEPLOYED",
                   phrase_code="flag.safety_car_deployed")
    assert _ok(resolve_for_playback(message, {"safety_car_status": 2}, 1.0))


def test_missing_safety_car_status_does_not_silence_the_flag():
    """Нет данных о фазе — не повод молчать о красном/жёлтом: гейт пропускает."""
    message = _msg("Safety Car на трассе.", code="SAFETY_CAR_DEPLOYED",
                   phrase_code="flag.safety_car_deployed")
    assert _ok(resolve_for_playback(message, {}, 1.0))


def test_red_flag_is_a_stable_critical_fact():
    """Красный флаг не отменяется ни по TTL, ни по фазе SC."""
    message = _msg("Красный флаг. В боксы.", code="RDFL",
                   phrase_code="flag.red")
    assert message.ttl is None
    assert _ok(resolve_for_playback(message, {"safety_car_status": 0}, 100_000.0))


# ── Смена цели ──────────────────────────────────────────────────────────────

def test_gap_is_cancelled_when_the_rival_ahead_changed():
    message = _msg("Отрыв впереди {gap}.", code="ENGINEER_GAP_DIGEST",
                   event_snapshot={"gap_target_idx": 7})
    assert _reason(resolve_for_playback(
        message, {"gap_target_idx": 4, "gap_front_ms": 1300}, 1.0
    )) is RadioCancelReason.TARGET_CHANGED


def test_gap_is_cancelled_when_the_target_disappeared():
    message = _msg("Отрыв впереди {gap}.", code="ENGINEER_GAP_DIGEST",
                   event_snapshot={"gap_target_idx": 7})
    assert _reason(resolve_for_playback(
        message, {"gap_target_idx": None, "gap_front_ms": 1300}, 1.0
    )) is RadioCancelReason.TARGET_CHANGED


def test_gap_speaks_when_the_target_is_still_the_same():
    message = _msg("Отрыв впереди {gap}.", code="ENGINEER_GAP_DIGEST",
                   event_snapshot={"gap_target_idx": 7})
    assert "1,3" in _ok(resolve_for_playback(
        message, {"gap_target_idx": 7, "gap_front_ms": 1300}, 1.0))


def test_a_message_without_a_recorded_target_is_not_guarded():
    """Старые события не несут `gap_target_idx` — их нельзя отменять поголовно."""
    message = _msg("Отрыв впереди {gap}.", code="ENGINEER_GAP_DIGEST")
    assert _ok(resolve_for_playback(message, {"gap_front_ms": 1300}, 1.0))


def test_target_change_is_checked_before_the_numbers():
    """Считать свежий гэп до другого пилота незачем — отмена раньше подстановки."""
    message = _msg("Отрыв впереди {gap}.", code="ENGINEER_GAP_DIGEST",
                   event_snapshot={"gap_target_idx": 7})
    # Гэпа в снимке нет вообще: если бы порядок был обратный, причина была бы
    # DATA_UNAVAILABLE.
    assert _reason(resolve_for_playback(
        message, {"gap_target_idx": 4}, 1.0)) is RadioCancelReason.TARGET_CHANGED


# ── Шины: смена комплекта ───────────────────────────────────────────────────

def test_tyre_warning_is_cancelled_after_a_pit_stop():
    """Предупреждение про старый комплект нельзя переносить на новый."""
    message = _msg("Износ {wear}.", code="TYRE_WARN",
                   event_snapshot={"tyre_set_id": 18})
    assert _reason(resolve_for_playback(
        message, {"tyre_set_id": 0, "tyre_wear": 50.0}, 1.0
    )) is RadioCancelReason.SITUATION_ENDED


def test_tyre_warning_speaks_on_the_same_set():
    message = _msg("Износ {wear}.", code="TYRE_WARN",
                   event_snapshot={"tyre_set_id": 18})
    assert "50" in _ok(resolve_for_playback(
        message, {"tyre_set_id": 18, "tyre_wear": 50.0}, 1.0))


def test_wear_is_refreshed_on_the_same_set():
    message = _msg("Износ {wear}.", code="TYRE_WARN",
                   event_snapshot={"tyre_set_id": 18, "tyre_wear": 30.0})
    text = _ok(resolve_for_playback(
        message, {"tyre_set_id": 18, "tyre_wear": 62.0}, 1.0))
    assert "62" in text and "30" not in text


# ── Пит-окно ────────────────────────────────────────────────────────────────

def test_pit_window_notice_is_cancelled_once_the_player_pits():
    message = _msg("Окно пит-стопа открылось.", code="PIT_WINDOW_APPROACH",
                   phrase_code="box.window_open")
    assert _reason(resolve_for_playback(
        message, {"pit_status": 1}, 1.0)) is RadioCancelReason.SITUATION_ENDED


def test_pit_window_notice_is_cancelled_once_the_window_closed():
    message = _msg("Окно пит-стопа открылось.", code="PIT_WINDOW_APPROACH",
                   phrase_code="box.window_open",
                   event_snapshot={"pit_window_open": True})
    assert _reason(resolve_for_playback(
        message, {"pit_status": 0, "pit_window_open": False}, 1.0
    )) is RadioCancelReason.SITUATION_ENDED


def test_pit_window_notice_speaks_while_the_window_is_open():
    message = _msg("Окно пит-стопа открылось.", code="PIT_WINDOW_APPROACH",
                   phrase_code="box.window_open",
                   event_snapshot={"pit_window_open": True})
    assert _ok(resolve_for_playback(
        message, {"pit_status": 0, "pit_window_open": True}, 1.0))


# ── Guard'ы централизованы и опрашиваемы ────────────────────────────────────

def test_check_situation_is_a_public_entry_point():
    message = _msg("Safety Car на трассе.", code="SAFETY_CAR_DEPLOYED",
                   phrase_code="flag.safety_car_deployed")
    assert resolver.check_situation(message, {"safety_car_status": 0}) is not None
    assert resolver.check_situation(message, {"safety_car_status": 1}) is None


def test_categories_without_a_guard_are_never_cancelled_by_one():
    message = _msg("Батарея {ers}.", code="STRAT_ERS_SAVE")
    assert resolver.check_situation(message, {"safety_car_status": 0}) is None


# ── Cache key строится по РЕЗОЛВЛЕННОМУ тексту (§11) ────────────────────────

def test_different_ers_values_produce_different_cache_keys(tmp_path):
    from voice.cache import TTSCache

    cache = TTSCache(str(tmp_path), version="test-v1")
    message = _msg("Батарея {ers}.", code="ENGINEER_GAP_DIGEST")

    at_60 = _ok(resolve_for_playback(message, {"ers_percent": 60.0}, 1.0))
    at_14 = _ok(resolve_for_playback(message, {"ers_percent": 14.0}, 1.0))

    assert cache.path_for(at_60, "y:v1:filipp|neutral|1.0") != \
        cache.path_for(at_14, "y:v1:filipp|neutral|1.0")


def test_a_message_with_an_omitted_clause_gets_the_key_of_its_short_text(tmp_path):
    from voice.cache import TTSCache

    cache = TTSCache(str(tmp_path), version="test-v1")
    message = _msg("Батарея {ers}. Отрыв впереди {gap}.",
                   code="ENGINEER_GAP_DIGEST")

    short = _ok(resolve_for_playback(
        message, {"ers_percent": None, "gap_front_ms": 1300}, 1.0))
    plain = "Отрыв впереди 1,3."

    assert short == plain
    assert cache.path_for(short, "piper:calm") == cache.path_for(plain, "piper:calm")


def test_a_string_with_unresolved_tokens_never_reaches_the_cache():
    """Резолвер физически не отдаёт такой текст — он возвращает Cancellation."""
    message = _msg("Батарея {ers}.", code="ENGINEER_GAP_DIGEST")
    result = resolve_for_playback(message, {}, 1.0)
    assert isinstance(result, Cancellation)


def test_speaker_namespace_stays_separate(tmp_path):
    """Piper-фолбэк не должен попасть под Yandex-ключ (баг «yandex-v2»)."""
    from voice.cache import TTSCache

    cache = TTSCache(str(tmp_path), version="test-v1")
    text = "Отрыв впереди 1,3."
    assert cache.path_for(text, "y:v1:filipp|neutral|1.0") != \
        cache.path_for(text, "piper:calm")
