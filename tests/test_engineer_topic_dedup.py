"""Одна новость — один раз, каким бы кодом она ни пришла.

Третья ось повторения, которую не видит ничто из уже существующего:

  * `variety.py` сравнивает СТРОКИ внутри одной спеки — разные коды ему не видны;
  * `SituationDedup` покрывает только проксимити-коды КОММЕНТАТОРА
    (OVTK/ATTACK/BATTLE/ATTACK_ZONE), спеки инженера в него не входят;
  * каждый трекер инженера (`core/race_engineer.py` — фасад над девятью) имеет
    свой кулдаун и НЕ знает про остальных.

Следствие, измеренное на живом коде: пилот подъезжает к сопернику на 0,9 с, и
DRS-трекер по переходу границы зоны говорит «Ты в зоне DRS», а сводка по
разрывам своим тактом — «Отрыв впереди 0,9». Одна новость, два кода, разные
слова. Ухо слышит повтор, метрики показывают ноль.
"""
import pytest

from core.radio import policy
from core.situation_dedup import EngineerTopicDedup, gap_band


AHEAD = "Норрис"


@pytest.fixture
def dedup():
    return EngineerTopicDedup(cooldown=20.0)


def _emit(dedup, code, *, band="close", neighbour=AHEAD, now=0.0):
    topic = policy.topic_for(code)
    return dedup.should_emit(topic, neighbour, band, now)


# ── Таблица тем ──────────────────────────────────────────────────────────────

def test_gap_digest_and_drs_share_one_topic():
    """Собственно тот коллапс, ради которого всё это писалось: обе реплики
    сообщают «ты вплотную к машине впереди»."""
    assert (policy.topic_for("ENGINEER_GAP_DIGEST")[0]
            == policy.topic_for("DRS_PROXIMITY_ENTER")[0])


def test_codes_outside_the_table_are_not_deduped():
    """Тема — белый список. Код, которого в ней нет, обязан проходить: молчание
    по умолчанию куда хуже повтора."""
    assert policy.topic_for("SPOTTER_CAR_LEFT") is None
    assert policy.topic_for("STRAT_BOX_CALL_3") is None
    assert policy.topic_for("НЕТ_ТАКОГО_КОДА") is None


def test_the_rank_scale_has_exactly_two_levels():
    """Ранг = факт (0) против руководства к действию (1), и дробить его тоньше
    нельзя. С тремя уровнями почти каждая реплика оказывается «чуть действеннее»
    предыдущей и пробивает окно — дедуп перестаёт дедуплицировать. Проверено на
    себе: с рангами 0/1/2 сводку по разрывам пробивал даже обычный вход в зону
    DRS, и оба теста ниже падали."""
    ranks = {rank for _topic, rank in
             (policy.topic_for(c) for c in ("ENGINEER_GAP_DIGEST",
                                            "DRS_PROXIMITY_ENTER",
                                            "DRS_PROXIMITY_ENTER_AND_ALLOWED"))}
    assert ranks == {0, 1}

    _, digest = policy.topic_for("ENGINEER_GAP_DIGEST")
    _, enter = policy.topic_for("DRS_PROXIMITY_ENTER")
    _, attack = policy.topic_for("DRS_PROXIMITY_ENTER_AND_ALLOWED")
    assert digest == enter < attack


# ── Поведение ────────────────────────────────────────────────────────────────

def test_the_same_news_twice_is_said_once(dedup):
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", now=100.0)
    assert not _emit(dedup, "DRS_PROXIMITY_ENTER", now=102.0)


def test_a_more_actionable_line_breaks_through(dedup):
    """Информационная сводка НЕ имеет права заглушить руководство к действию.
    Без этого правила выбор решался бы порядком прихода пакетов, то есть
    случайно."""
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", now=100.0)
    assert _emit(dedup, "DRS_PROXIMITY_ENTER_AND_ALLOWED", now=102.0)


def test_a_less_actionable_line_does_not_break_through(dedup):
    """Обратное направление: сказав «DRS открыта, атакуй», пересказывать это
    сводкой по разрывам незачем."""
    assert _emit(dedup, "DRS_PROXIMITY_ENTER_AND_ALLOWED", now=100.0)
    assert not _emit(dedup, "ENGINEER_GAP_DIGEST", now=102.0)


def test_the_same_line_does_not_repeat_within_the_window(dedup):
    assert _emit(dedup, "DRS_PROXIMITY_ENTER", now=100.0)
    assert not _emit(dedup, "DRS_PROXIMITY_ENTER", now=105.0)


def test_the_window_expires(dedup):
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", now=100.0)
    assert not _emit(dedup, "DRS_PROXIMITY_ENTER", now=110.0)
    assert _emit(dedup, "DRS_PROXIMITY_ENTER", now=121.0)


def test_a_changed_distance_band_is_material_news(dedup):
    """Дистанция реально изменилась — это новая новость, а не пересказ. Тот же
    принцип, что у SituationDedup."""
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", band="near", now=100.0)
    assert _emit(dedup, "DRS_PROXIMITY_ENTER", band="vclose", now=102.0)


def test_a_changed_neighbour_is_material_news(dedup):
    """Обгон состоялся, впереди уже другой — молчать нельзя."""
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", neighbour="Норрис", now=100.0)
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", neighbour="Расселл", now=102.0)


def test_no_topic_always_speaks(dedup):
    """Реплика вне тем не трогается вовсе — сколько бы раз ни пришла."""
    for t in range(5):
        assert dedup.should_emit(None, AHEAD, "close", 100.0 + t)


def test_reset_forgets_everything(dedup):
    assert _emit(dedup, "ENGINEER_GAP_DIGEST", now=100.0)
    dedup.reset()
    assert _emit(dedup, "DRS_PROXIMITY_ENTER", now=101.0)


def test_missing_band_is_not_a_match(dedup):
    """Дистанции нет (машины впереди нет вовсе) — сравнивать не с чем, и
    подавлять на основании неизвестного нельзя."""
    assert dedup.should_emit(policy.topic_for("ENGINEER_GAP_DIGEST"),
                             AHEAD, None, 100.0)
    assert dedup.should_emit(policy.topic_for("DRS_PROXIMITY_ENTER"),
                             AHEAD, None, 101.0)


# ── Проводка ─────────────────────────────────────────────────────────────────
# Корректный класс сам по себе ничего не гарантирует: самые дорогие баги этого
# проекта жили между рабочим ядром и тем, что реально уезжало наружу.

@pytest.fixture
def engine(monkeypatch):
    import core.engine as eng_mod
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = eng_mod.F1Engine({})
    e._player_gap_front = 900          # 0,9 с — полоса "close"
    return e


def test_engine_suppresses_the_second_telling(engine):
    assert engine._engineer_topic_allows(
        {"event_code": "ENGINEER_GAP_DIGEST"}, 100.0)
    assert not engine._engineer_topic_allows(
        {"event_code": "DRS_PROXIMITY_ENTER"}, 102.0)


def test_engine_lets_the_call_to_action_through(engine):
    assert engine._engineer_topic_allows(
        {"event_code": "ENGINEER_GAP_DIGEST"}, 100.0)
    assert engine._engineer_topic_allows(
        {"event_code": "DRS_PROXIMITY_ENTER_AND_ALLOWED"}, 102.0)


def test_engine_never_touches_safety_codes(engine):
    """Споттер и вызов в боксы обязаны проходить всегда — сколько бы раз ни
    пришли. Это и есть причина, по которой таблица тем — белый список."""
    for _ in range(5):
        assert engine._engineer_topic_allows(
            {"event_code": "SPOTTER_CAR_LEFT"}, 100.0)
        assert engine._engineer_topic_allows(
            {"event_code": "STRAT_BOX_CALL_3"}, 100.0)


def test_engine_speaks_again_when_nobody_is_ahead(engine):
    """Машины впереди нет — полосы дистанции не существует, и подавлять на
    основании неизвестного нельзя."""
    engine._player_gap_front = None
    assert engine._engineer_topic_allows(
        {"event_code": "ENGINEER_GAP_DIGEST"}, 100.0)
    assert engine._engineer_topic_allows(
        {"event_code": "DRS_PROXIMITY_ENTER"}, 101.0)


def test_flashback_clears_the_held_topics(engine):
    """После перемотки пилот не слышал того, что «уже говорили» — эпизод
    переигрывается заново."""
    assert engine._engineer_topic_allows(
        {"event_code": "ENGINEER_GAP_DIGEST"}, 100.0)
    engine._handle_flashback()
    assert engine._engineer_topic_allows(
        {"event_code": "DRS_PROXIMITY_ENTER"}, 101.0)


def test_gap_band_helper_is_reused_not_reinvented():
    """Полосы дистанции обязаны совпадать с теми, что уже использует
    SituationDedup, иначе два дедупа начнут считать «ту же ситуацию» по-разному."""
    assert gap_band(400) == "vclose"
    assert gap_band(900) == "close"
    assert gap_band(1500) == "near"
    assert gap_band(5000) == "far"
