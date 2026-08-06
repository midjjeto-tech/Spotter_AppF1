"""core/radio/policy.py — канал, срочность, TTL, политика прерывания.

Таблицы проверяются по списку кодов из аудита
docs/superpowers/specs/2026-07-29-f1-manager-radio-redesign.md §2.
"""
import pytest

from core.radio import policy


# ── Канал: кто говорит ───────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "SPOTTER_CAR_LEFT", "SPOTTER_CAR_RIGHT", "SPOTTER_CAR_BOTH", "SPOTTER_CLEAR",
])
def test_spotter_codes_route_to_spotter_channel(code):
    assert policy.channel_for({"event_code": code}) == policy.CHANNEL_SPOTTER


@pytest.mark.parametrize("code", [
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3",
    "PIT_CALL_NOTICE", "PIT_WINDOW_APPROACH", "PIT_EXIT",
    "STRAT_PIT", "STRAT_UNDERCUT", "STRAT_OVERCUT", "STRAT_SAVE", "STRAT_PUSH",
    "STRAT_FUEL", "STRAT_ERS_SAVE", "STRAT_ERS_OVERTAKE",
    "ENGINEER_GAP_DIGEST", "ENGINEER_RAIN_ADVISORY",
    "ENGINEER_TRACK_LIMITS_WARNING", "ENGINEER_PENA_TRACK_LIMITS",
    "DRS_PROXIMITY_ENTER", "DRS_PROXIMITY_EXIT", "DRS_ALLOWED_ON",
    "DRS_ALLOWED_OFF", "DRS_PROXIMITY_ENTER_AND_ALLOWED", "DRSE", "DRSD",
    "POSITION_CALL", "POSITION_CALL_OWN_PIT", "LEADER_CHANGE", "DEFENSE",
    "DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_GEARBOX", "DAMAGE_ENGINE",
    "TYRE_WARN", "PENA", "RDFL",
    "SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING", "SAFETY_CAR_CLEAR",
    "USER_Q", "PRE_RACE_PEP_TALK",
])
def test_engineer_codes_route_to_engineer_channel(code):
    assert policy.channel_for({"event_code": code}) == policy.CHANNEL_ENGINEER


@pytest.mark.parametrize("code", [
    "OVTK", "FTLP", "COLL", "RTMT", "RCWN", "CHQF", "SSTA", "AMBIENT",
    "ATTACK", "BATTLE", "MILESTONE", "CAREER_PB", "F1_BENCH", "STORY",
    "FINAL_LAP", "CHAMPIONSHIP",
])
def test_remaining_codes_route_to_commentator(code):
    assert policy.channel_for({"event_code": code}) == policy.CHANNEL_COMMENTATOR


def test_speaker_marker_wins_over_unknown_code():
    """Все инженерские трекеры ставят speaker="engineer" — новый код инженера
    не должен молча уехать в комментатора только потому, что его забыли внести
    в таблицу."""
    event = {"event_code": "ENGINEER_SOMETHING_NEW", "speaker": "engineer"}
    assert policy.channel_for(event) == policy.CHANNEL_ENGINEER


def test_unknown_code_without_marker_defaults_to_commentator():
    assert policy.channel_for({"event_code": "WAT"}) == policy.CHANNEL_COMMENTATOR


# ── Голос: у каждой роли свой слот ───────────────────────────────────────────
# Прежний контракт «инженер и споттер говорят персоной calm» отменён: он и был
# причиной того, что при persona="calm" все три канала звучали одним голосом.

def test_engineer_and_spotter_have_their_own_voice_slots():
    assert policy.voice_persona_for(policy.CHANNEL_ENGINEER) == "engineer"
    assert policy.voice_persona_for(policy.CHANNEL_SPOTTER) == "spotter"


def test_commentator_uses_the_users_persona():
    assert policy.voice_persona_for(policy.CHANNEL_COMMENTATOR) is None


def test_speaker_labels_are_human_readable():
    for channel in (policy.CHANNEL_SPOTTER, policy.CHANNEL_ENGINEER,
                    policy.CHANNEL_COMMENTATOR):
        label = policy.speaker_label_for(channel)
        assert label and not label.isupper()


# ── Срочность ────────────────────────────────────────────────────────────────

def test_critical_priority_wins_for_codes_the_table_does_not_name():
    event = {"event_code": "SOME_NEW_CODE", "priority": "critical", "importance": 5}
    assert policy.urgency_for(event) == policy.URGENCY_CRITICAL


@pytest.mark.parametrize("code,expected", [
    ("SAFETY_CAR_DEPLOYED", "high"),
    ("RTMT", "high"),
    ("COLL", "high"),
    ("CHQF", "high"),
    ("RCWN", "high"),
    ("AMBIENT", "low"),
])
def test_table_outranks_the_legacy_critical_priority(code, expected):
    """`core/packets.py::CRITICAL_EVENTS` помечает critical'ом финиш (CHQF) и
    победителя (RCWN) — это «важная новость», а не «требует реакции сейчас».
    Таблица обязана уметь понизить такие коды, иначе прерывать звучащую фразу
    будет половина гонки, и спотер утонет в общем потоке."""
    event = {"event_code": code, "priority": "critical", "importance": 88}
    assert policy.urgency_for(event) == expected


def test_spotter_stays_critical_even_though_the_table_can_demote():
    """Понижать умеет только таблица, и споттер в ней стоит как critical —
    новый порядок разрешения не может случайно его ослабить."""
    event = {"event_code": "SPOTTER_CAR_LEFT", "priority": "normal", "importance": 10}
    assert policy.urgency_for(event) == policy.URGENCY_CRITICAL


@pytest.mark.parametrize("code", [
    "SPOTTER_CAR_LEFT", "SPOTTER_CAR_RIGHT", "SPOTTER_CAR_BOTH", "SPOTTER_CLEAR",
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3",
    "RDFL", "PENA", "ENGINEER_PENA_TRACK_LIMITS",
])
def test_safety_and_mandatory_action_codes_are_critical(code):
    assert policy.urgency_for({"event_code": code}) == policy.URGENCY_CRITICAL


@pytest.mark.parametrize("code", [
    "SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING", "SAFETY_CAR_CLEAR",
    "ENGINEER_RAIN_ADVISORY", "PIT_WINDOW_APPROACH", "STRAT_FUEL",
])
def test_high_urgency_codes(code):
    assert policy.urgency_for({"event_code": code}) == policy.URGENCY_HIGH


def test_safety_car_is_high_not_critical_despite_importance_90():
    """Сегодня SC получает importance 90 и потому прерывает звучащую фразу.
    ТЗ §6: high не должна прерывать активного спотера — таблица кодов обязана
    перебить importance."""
    event = {"event_code": "SAFETY_CAR_DEPLOYED", "importance": 90}
    assert policy.urgency_for(event) == policy.URGENCY_HIGH


def test_damage_severity_splits_high_from_critical():
    base = {"event_code": "DAMAGE_WING"}
    assert policy.urgency_for({**base, "damage_severity": 25}) == policy.URGENCY_HIGH
    assert policy.urgency_for({**base, "damage_severity": 85}) == policy.URGENCY_CRITICAL


def test_damage_severity_outranks_a_normal_priority():
    """Повреждения публикуются с priority="normal" (core/engine.py::
    _update_damage) — критическая поломка не должна ждать очереди только из-за
    этого."""
    event = {"event_code": "DAMAGE_ENGINE", "priority": "normal",
             "damage_severity": 95}
    assert policy.urgency_for(event) == policy.URGENCY_CRITICAL


def test_damage_without_severity_falls_back_to_high():
    assert policy.urgency_for({"event_code": "DAMAGE_FLOOR"}) == policy.URGENCY_HIGH


@pytest.mark.parametrize("code", ["AMBIENT", "SEND", "FLBK", "F1_SECTOR_BENCH"])
def test_low_urgency_codes(code):
    assert policy.urgency_for({"event_code": code}) == policy.URGENCY_LOW


@pytest.mark.parametrize("importance,expected", [
    (95, "high"), (80, "high"), (79, "normal"), (50, "normal"), (49, "low"), (0, "low"),
])
def test_unlisted_codes_fall_back_to_importance(importance, expected):
    event = {"event_code": "UNLISTED_CODE", "importance": importance}
    assert policy.urgency_for(event) == expected


def test_importance_fallback_never_reaches_critical():
    """Critical выдаётся только явно (priority или таблица) — иначе любое
    событие с importance 90 (их много) молча получило бы право прерывать."""
    event = {"event_code": "UNLISTED_CODE", "importance": 100}
    assert policy.urgency_for(event) != policy.URGENCY_CRITICAL


# ── TTL ──────────────────────────────────────────────────────────────────────

def test_spotter_ttl_is_within_the_spec_window():
    assert 1.0 <= policy.ttl_for("SPOTTER_CAR_LEFT") <= 2.0
    assert 2.0 <= policy.ttl_for("SPOTTER_CLEAR") <= 3.0


def test_box_call_ttl_is_within_the_spec_window():
    for tier in (1, 2, 3):
        assert 8.0 <= policy.ttl_for(f"STRAT_BOX_CALL_{tier}") <= 12.0


@pytest.mark.parametrize("code,low,high", [
    ("DAMAGE_WING", 10.0, 20.0),
    ("ENGINEER_RAIN_ADVISORY", 20.0, 40.0),
    ("ENGINEER_GAP_DIGEST", 8.0, 15.0),
    ("POSITION_CALL", 8.0, 15.0),
    ("STRAT_ERS_SAVE", 3.0, 6.0),
    ("STRAT_FUEL", 8.0, 15.0),
    ("AMBIENT", 10.0, 20.0),
    ("OVTK", 10.0, 20.0),
])
def test_ttl_windows_from_spec(code, low, high):
    assert low <= policy.ttl_for(code) <= high


@pytest.mark.parametrize("code", ["PENA", "RDFL", "USER_Q"])
def test_mandatory_messages_never_expire(code):
    assert policy.ttl_for(code) is None


def test_expires_at_is_measured_from_the_event_not_from_tts():
    created = 1000.0
    assert policy.expires_at_for("SPOTTER_CAR_LEFT", created) == created + policy.ttl_for(
        "SPOTTER_CAR_LEFT")
    assert policy.expires_at_for("PENA", created) is None


# ── Политика прерывания ──────────────────────────────────────────────────────

def test_critical_interrupts():
    assert policy.interrupt_policy_for(
        policy.URGENCY_CRITICAL, "box_call") == policy.POLICY_INTERRUPT


def test_high_queues_next_and_does_not_interrupt():
    assert policy.interrupt_policy_for(
        policy.URGENCY_HIGH, "safety_car") == policy.POLICY_NEXT


def test_periodic_digest_replaces_its_stale_predecessor():
    assert policy.interrupt_policy_for(
        policy.URGENCY_NORMAL, "gap_digest") == policy.POLICY_REPLACE


def test_ordinary_normal_message_just_queues():
    assert policy.interrupt_policy_for(
        policy.URGENCY_NORMAL, "commentary") == policy.POLICY_NEXT


def test_low_is_dropped_when_radio_is_busy():
    assert policy.interrupt_policy_for(
        policy.URGENCY_LOW, "ambient") == policy.POLICY_DROP_IF_BUSY


# ── Категории ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,category", [
    ("SPOTTER_CAR_LEFT", "spotter_side"),
    ("SPOTTER_CLEAR", "spotter_clear"),
    ("STRAT_BOX_CALL_2", "box_call"),
    ("PIT_CALL_NOTICE", "box_call"),
    ("DAMAGE_GEARBOX", "damage"),
    ("ENGINEER_RAIN_ADVISORY", "weather"),
    ("ENGINEER_GAP_DIGEST", "gap_digest"),
    ("SAFETY_CAR_DEPLOYED", "safety_car"),
    ("PENA", "penalty"),
    ("USER_Q", "ptt_answer"),
    # Обгон/атака/борьба — одна категория "battle": от неё зависят TTL и
    # заголовок, а «борьба» точнее дефолтного «сообщение». Канал при этом
    # остаётся commentator — категория и канал независимы.
    ("OVTK", "battle"),
    ("ATTACK", "battle"),
    ("MILESTONE", "commentary"),
    ("FTLP", "commentary"),
])
def test_category_for(code, category):
    assert policy.category_for(code) == category


def test_battle_category_does_not_move_the_channel():
    assert policy.channel_for({"event_code": "OVTK"}) == policy.CHANNEL_COMMENTATOR


def test_every_ttl_category_is_reachable_from_some_code():
    """Защита от опечатки: категория с TTL, которую не выдаёт ни один код,
    означала бы, что настоящие события используют дефолт вместо своего окна."""
    reachable = {policy.category_for(code) for code in policy.known_codes()}
    orphans = set(policy.ttl_categories()) - reachable
    assert not orphans, f"TTL задан для недостижимых категорий: {sorted(orphans)}"
