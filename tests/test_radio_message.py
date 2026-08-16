"""core/radio/message.py — RadioMessage: сборка, неизменяемость, состояния."""
import json

import pytest

from core.radio import plumbing, policy
from core.radio.message import (
    RadioCancelReason,
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_INTERRUPTED,
    STATE_PLAYING,
    STATE_QUEUED,
    STATE_SYNTHESIZING,
    RadioMessage,
    build_message,
)


def _event(**overrides):
    event = {
        "event_code": "ENGINEER_GAP_DIGEST",
        "priority": "normal",
        "importance": 50,
        "speaker": "engineer",
    }
    event.update(overrides)
    return event


# ── Сборка ───────────────────────────────────────────────────────────────────

def test_build_fills_channel_urgency_ttl_and_policy_from_the_event():
    message = build_message(_event(), phrase="До Норриса 1,3.", now=1000.0,
                            now_mono=50.0)

    assert message.event_code == "ENGINEER_GAP_DIGEST"
    assert message.channel == policy.CHANNEL_ENGINEER
    assert message.category == "gap_digest"
    assert message.urgency == policy.URGENCY_NORMAL
    assert message.speaker == policy.speaker_label_for(policy.CHANNEL_ENGINEER)
    assert message.voice_persona == "engineer"
    assert message.phrase == "До Норриса 1,3."
    assert message.created_at == 1000.0
    assert message.created_mono == 50.0
    assert message.ttl == policy.ttl_for("ENGINEER_GAP_DIGEST")
    assert message.expires_mono == 50.0 + policy.ttl_for("ENGINEER_GAP_DIGEST")
    # `interrupt_policy` удалена 2026-08-14: очередь её не читала, а два из
    # четырёх её значений не были реализованы вовсе. Прерывание определяют
    # `urgency` и `category` — их и проверяем.
    assert message.category == "gap_digest"
    assert message.state == STATE_QUEUED


def test_created_at_prefers_the_event_time_over_the_build_time():
    """TTL отсчитывается от МОМЕНТА СОБЫТИЯ, не от попадания в TTS (ТЗ §7).
    Событие могло простоять в очереди события десятки секунд до сборки."""
    message = build_message(
        _event(created_at=900.0, created_mono=40.0), phrase="Текст",
        now=1000.0, now_mono=50.0)
    assert message.created_at == 900.0
    assert message.created_mono == 40.0
    assert message.expires_mono == 40.0 + policy.ttl_for("ENGINEER_GAP_DIGEST")


# ── Две шкалы времени ────────────────────────────────────────────────────────

def test_ttl_is_measured_on_the_monotonic_scale():
    """Wall-clock на Windows прыгает (NTP, зимнее время). Прыжок назад на час
    превратил бы просроченное сообщение в «истечёт через час»."""
    message = build_message(
        _event(event_code="SPOTTER_CAR_LEFT", priority="critical"),
        phrase="Держи слева!", now=1000.0, now_mono=500.0)

    ttl = policy.ttl_for("SPOTTER_CAR_LEFT")
    assert not message.is_expired(500.0 + ttl - 0.01)
    assert message.is_expired(500.0 + ttl + 0.01)


def test_a_wall_clock_jump_backwards_does_not_revive_an_expired_message():
    message = build_message(
        _event(event_code="SPOTTER_CAR_LEFT", priority="critical",
               created_at=1000.0, created_mono=500.0),
        phrase="Держи слева!", now=1000.0, now_mono=500.0)

    # Часы уехали на час назад, монотонная шкала — нет.
    assert message.is_expired(500.0 + policy.ttl_for("SPOTTER_CAR_LEFT") + 1.0)


def test_wall_clock_expiry_is_only_derived_for_the_ui():
    message = build_message(_event(created_at=1000.0, created_mono=7.0),
                            phrase="Текст", now=0.0, now_mono=0.0)
    assert message.expires_at == 1000.0 + policy.ttl_for("ENGINEER_GAP_DIGEST")


def test_monotonic_stamp_is_assigned_once_and_survives_every_transform():
    """`created_mono` не должен пересоздаваться ни в одном преобразовании —
    иначе TTL перезапускался бы на каждом шаге конвейера."""
    message = build_message(_event(), phrase="Батарея {ers_clause}",
                            now=1000.0, now_mono=50.0)

    resolved = message.with_phrase("Батарея 18%.")
    playing = resolved.with_state(STATE_PLAYING, now=1234.0)
    done = playing.with_state(STATE_COMPLETED, now=1240.0)

    for stage in (resolved, playing, done):
        assert stage.created_mono == 50.0
        assert stage.created_at == 1000.0
        assert stage.expires_mono == message.expires_mono


def test_spotter_message_is_critical_and_interrupts():
    message = build_message(
        _event(event_code="SPOTTER_CAR_LEFT", priority="critical"),
        phrase="Держи слева!", now=0.0)

    assert message.channel == policy.CHANNEL_SPOTTER
    assert message.urgency == policy.URGENCY_CRITICAL
    assert message.urgency == policy.URGENCY_CRITICAL


def test_ids_are_unique_and_stable_within_an_instance():
    first = build_message(_event(), phrase="a", now=0.0)
    second = build_message(_event(), phrase="b", now=0.0)

    assert first.id != second.id
    assert first.id.startswith("radio-")
    assert first.id == first.id


def test_situation_and_dedupe_keys_are_attached():
    message = build_message(
        _event(event_code="SPOTTER_CAR_RIGHT", priority="critical",
               **plumbing.attach(neighbour_idx=7)),
        phrase="Держи справа!", now=0.0)

    assert message.situation_id == "spotter:right:vehicle_7"
    assert message.dedupe_key is not None


def test_source_snapshot_is_captured_and_isolated_from_later_mutation():
    telemetry = {"ers_percent": 60.0, "gap_front_ms": 1300}
    message = build_message(_event(), phrase="Текст", now=0.0, telemetry=telemetry)
    telemetry["ers_percent"] = 14.0

    assert message.source_snapshot["ers_percent"] == 60.0


def test_source_snapshot_cannot_be_mutated_through_the_message():
    """`frozen=True` защищает только сами поля — вложенный dict остался бы
    изменяемым, и снимок «на момент события» тихо поехал бы."""
    message = build_message(_event(), phrase="Текст", now=0.0,
                            telemetry={"ers_percent": 60.0})

    with pytest.raises(TypeError):
        message.source_snapshot["ers_percent"] = 14.0     # type: ignore[index]
    assert message.source_snapshot["ers_percent"] == 60.0


def test_nested_snapshot_values_are_deep_copied():
    telemetry = {"tyres": {"front": 48}}
    message = build_message(_event(), phrase="Текст", now=0.0, telemetry=telemetry)
    telemetry["tyres"]["front"] = 99

    assert message.source_snapshot["tyres"]["front"] == 48


def test_message_without_telemetry_has_an_immutable_empty_snapshot():
    message = build_message(_event(), phrase="Текст", now=0.0)
    assert message.source_snapshot == {}
    with pytest.raises(TypeError):
        message.source_snapshot["x"] = 1                  # type: ignore[index]


def test_volatile_fields_are_detected_from_the_phrase_tokens():
    message = build_message(
        _event(), phrase="До Норриса 1,3. {ers_clause}", now=0.0)
    assert "ers_clause" in message.volatile_fields


def test_no_volatile_fields_when_the_phrase_has_no_tokens():
    message = build_message(_event(), phrase="До Норриса 1,3.", now=0.0)
    assert message.volatile_fields == ()


def test_ui_title_is_human_readable_and_never_the_raw_code():
    message = build_message(_event(event_code="STRAT_BOX_CALL_1",
                                   priority="critical"),
                            phrase="Бокс, бокс.", now=0.0)
    assert "STRAT_BOX_CALL_1" not in message.ui_title
    assert message.ui_title


def test_unknown_code_still_gets_a_non_empty_ui_title():
    message = build_message(_event(event_code="TOTALLY_NEW_CODE"),
                            phrase="Текст", now=0.0)
    assert message.ui_title
    assert "TOTALLY_NEW_CODE" not in message.ui_title


# ── Неизменяемость и переходы состояний ──────────────────────────────────────

def test_message_is_frozen():
    message = build_message(_event(), phrase="Текст", now=0.0)
    with pytest.raises(Exception):
        message.phrase = "Другой"  # type: ignore[misc]


def test_with_state_returns_a_new_message_and_leaves_the_original_alone():
    queued = build_message(_event(), phrase="Текст", now=0.0)
    playing = queued.with_state(STATE_PLAYING, now=5.0)

    assert queued.state == STATE_QUEUED
    assert playing.state == STATE_PLAYING
    assert playing.id == queued.id
    assert playing.started_at == 5.0
    assert queued.started_at is None


@pytest.mark.parametrize("path,state", [
    ([], STATE_CANCELLED),
    ([STATE_PLAYING], STATE_COMPLETED),
    ([STATE_PLAYING], STATE_INTERRUPTED),
])
def test_terminal_states_stamp_ended_at(path, state):
    message = build_message(_event(), phrase="Текст", now=0.0)
    for step in path:
        message = message.with_state(step, now=1.0)
    done = message.with_state(
        state, now=9.0,
        reason=RadioCancelReason.EXPIRED if state == STATE_CANCELLED else None)

    assert done.ended_at == 9.0
    assert done.is_terminal


def test_synthesizing_and_playing_are_not_terminal():
    message = build_message(_event(), phrase="Текст", now=0.0)
    assert not message.with_state(STATE_SYNTHESIZING, now=1.0).is_terminal
    assert not message.with_state(STATE_PLAYING, now=2.0).is_terminal


# ── Разрешённые и запрещённые переходы ───────────────────────────────────────

@pytest.mark.parametrize("path", [
    [STATE_SYNTHESIZING, STATE_PLAYING, STATE_COMPLETED],
    [STATE_PLAYING, STATE_COMPLETED],
    [STATE_CANCELLED],
    [STATE_SYNTHESIZING, STATE_CANCELLED],
    [STATE_SYNTHESIZING, STATE_INTERRUPTED],
    [STATE_PLAYING, STATE_INTERRUPTED],
])
def test_allowed_transition_paths(path):
    message = build_message(_event(), phrase="Текст", now=0.0)
    for index, state in enumerate(path):
        message = message.with_state(
            state, now=float(index),
            reason=RadioCancelReason.EXPIRED if state == STATE_CANCELLED else None)
    assert message.state == path[-1]


@pytest.mark.parametrize("path,forbidden", [
    # Прервать можно только то, что уже звучало. Снятое из очереди до синтеза —
    # это cancelled, и различать их нужно: история радио должна показывать
    # «не успело зазвучать» иначе, чем «оборвали на полуслове».
    ([], STATE_INTERRUPTED),
    # Звук уже в динамике — отменить задним числом нельзя, только прервать.
    ([STATE_PLAYING], STATE_CANCELLED),
    # Назад по конвейеру не ходим.
    ([STATE_PLAYING], STATE_QUEUED),
    ([STATE_PLAYING], STATE_SYNTHESIZING),
    # Из конечных состояний переходов нет вообще.
    ([STATE_PLAYING, STATE_COMPLETED], STATE_PLAYING),
    ([STATE_CANCELLED], STATE_PLAYING),
    ([STATE_PLAYING, STATE_INTERRUPTED], STATE_COMPLETED),
])
def test_forbidden_transitions_raise(path, forbidden):
    message = build_message(_event(), phrase="Текст", now=0.0)
    for index, state in enumerate(path):
        message = message.with_state(
            state, now=float(index),
            reason=RadioCancelReason.EXPIRED if state == STATE_CANCELLED else None)

    assert not message.can_transition_to(forbidden)
    with pytest.raises(ValueError, match="forbidden"):
        message.with_state(forbidden, now=99.0)


def test_a_terminal_message_allows_no_transition_at_all():
    message = build_message(_event(), phrase="Текст", now=0.0)
    cancelled = message.with_state(STATE_CANCELLED, now=1.0,
                                     reason=RadioCancelReason.EXPIRED)

    for state in (STATE_QUEUED, STATE_SYNTHESIZING, STATE_PLAYING,
                  STATE_COMPLETED, STATE_INTERRUPTED, STATE_CANCELLED):
        assert not cancelled.can_transition_to(state)


def test_with_phrase_replaces_the_text_and_keeps_identity():
    message = build_message(_event(), phrase="Батарея {ers_clause}", now=0.0)
    resolved = message.with_phrase("Батарея 18%. Береги ERS.")

    assert resolved.id == message.id
    assert resolved.phrase == "Батарея 18%. Береги ERS."
    assert message.phrase == "Батарея {ers_clause}"


def test_rejects_an_unknown_state():
    message = build_message(_event(), phrase="Текст", now=0.0)
    with pytest.raises(ValueError):
        message.with_state("dancing", now=1.0)


# ── Срок жизни ───────────────────────────────────────────────────────────────

def test_message_without_ttl_never_expires():
    message = build_message(_event(event_code="PENA"), phrase="Штраф пять секунд.",
                            now=0.0, now_mono=0.0)
    assert message.expires_mono is None
    assert message.expires_at is None
    assert message.ttl is None
    assert not message.is_expired(10_000.0)


def test_the_set_of_never_expiring_categories_is_closed():
    """Бессрочность — обоснованное исключение, а не «на всякий случай»: либо
    сообщение требует ДЕЙСТВИЯ, либо пилот запросил его САМ. Новая категория без
    TTL должна требовать правки этого теста."""
    assert policy.never_expiring_categories() == {
        "penalty", "red_flag", "ptt_answer"}


# ── Проекция в UI ────────────────────────────────────────────────────────────

def test_ui_dict_is_json_serialisable_and_carries_a_human_title():
    message = build_message(
        _event(event_code="STRAT_BOX_CALL_1", priority="critical"),
        phrase="Бокс, бокс.", now=1000.0,
        telemetry={"ers_percent": 60.0})
    payload = message.to_ui_dict()

    json.dumps(payload, ensure_ascii=False)  # must not raise
    assert payload["ui_title"] == message.ui_title
    assert "STRAT_BOX_CALL_1" not in payload["ui_title"]

    assert payload["id"] == message.id
    assert payload["channel"] == policy.CHANNEL_ENGINEER
    assert payload["urgency"] == policy.URGENCY_CRITICAL
    assert payload["speaker"] == message.speaker
    assert payload["text"] == "Бокс, бокс."
    assert payload["state"] == STATE_QUEUED
    assert payload["created_at"] == 1000.0


def test_ui_dict_omits_the_raw_telemetry_snapshot():
    """source_snapshot нужен для ре-валидации на бэкенде, но это внутренние
    данные — в UI они не едут (ТЗ §18: не отдавать несериализуемое, не гнать
    лишние байты каждую секунду)."""
    message = build_message(_event(), phrase="Текст", now=0.0,
                            telemetry={"ers_percent": 60.0})
    assert "source_snapshot" not in message.to_ui_dict()


def test_message_type_survives_a_round_trip_through_json():
    message = build_message(_event(), phrase="Текст", now=0.0)
    assert json.loads(json.dumps(message.to_ui_dict())) == message.to_ui_dict()


def test_ui_dict_exposes_the_event_code_only_as_a_debug_field():
    """Код нужен диагностике (журнал, поддержка), но UI обязан показывать
    ui_title — критерий готовности №11. Поле называется явно."""
    message = build_message(_event(), phrase="Текст", now=0.0)
    payload = message.to_ui_dict()
    assert payload["debug_event_code"] == "ENGINEER_GAP_DIGEST"


def test_isinstance_contract():
    assert isinstance(build_message(_event(), phrase="Текст", now=0.0), RadioMessage)
