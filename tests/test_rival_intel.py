"""Инженер произносит разведданные о сопернике впереди.

Стиль пилотажа, возраст резины и недавние ошибки соперников `RivalTracker`
собирал и раньше — но уезжало это только в контекст LLM-комментатора и
стратегии. Инженер, который по смыслу должен быть глазами пилота, не говорил
из этого ничего. Данные лежали готовыми.
"""
import pytest

from core.radio import phrases, policy
from core.rivals.intel import (
    CODE_MISTAKE, CODE_STYLE_AGGRESSIVE, CODE_STYLE_FADING,
    CODE_TYRES_FRESHER, CODE_TYRES_OLDER, MIN_TYRE_DELTA_LAPS,
    RivalIntelTracker,
)


RIVAL = 7
OTHER = 11


@pytest.fixture
def intel():
    return RivalIntelTracker(cooldown=45.0)


def _check(intel, *, idx=RIVAL, delta=None, mistake=False, style=None, now=0.0):
    return intel.check(rival_idx=idx, tyre_delta=delta,
                       recent_mistake=mistake, style=style, now=now)


# ── Что стоит эфира ──────────────────────────────────────────────────────────

def test_nothing_to_say_stays_silent(intel):
    assert _check(intel, style="consistent", now=100.0) is None


def test_no_rival_ahead_stays_silent(intel):
    assert _check(intel, idx=None, mistake=True, now=100.0) is None


def test_a_small_tyre_difference_is_not_news(intel):
    """Два круга разницы на слух не существуют, а реплика с точным числом
    звучала бы как важное сообщение. Порог — та величина, с которой разница
    начинает быть слышна в темпе."""
    assert _check(intel, delta=MIN_TYRE_DELTA_LAPS - 1, now=100.0) is None


def test_older_tyres_are_reported_with_the_gap_in_laps(intel):
    code, fields = _check(intel, delta=8, now=100.0)
    assert code == CODE_TYRES_OLDER
    assert fields == {"laps": 8}


def test_fresher_tyres_are_a_different_message(intel):
    """Знак разницы меняет СМЫСЛ на противоположный: у него резина свежее —
    это предупреждение, а не возможность. Перепутать знак значит советовать
    давить там, где надо беречь."""
    code, fields = _check(intel, delta=-8, now=100.0)
    assert code == CODE_TYRES_FRESHER
    assert fields == {"laps": 8}


@pytest.mark.parametrize("style,expected", [
    ("aggressive", CODE_STYLE_AGGRESSIVE),
    ("fading", CODE_STYLE_FADING),
])
def test_worthwhile_styles_are_reported(intel, style, expected):
    code, _ = _check(intel, style=style, now=100.0)
    assert code == expected


@pytest.mark.parametrize("style", ["consistent", "charging", None, "чушь"])
def test_uninformative_styles_stay_silent(intel, style):
    """`charging` намеренно молчит: «он набирает» уже слышно по сокращающемуся
    разрыву, это озвучит сводка."""
    assert _check(intel, style=style, now=100.0) is None


# ── Сколько и как часто ──────────────────────────────────────────────────────

def test_only_one_fact_at_a_time(intel):
    """Знаем три вещи сразу — говорим одну. «Шины старше, и он ошибся, и он
    агрессивный» — это не разведка, это поток."""
    first = _check(intel, delta=9, mistake=True, style="aggressive", now=100.0)
    assert first is not None
    assert _check(intel, delta=9, mistake=True, style="aggressive",
                  now=101.0) is None


def test_the_most_actionable_fact_wins(intel):
    """Окно для атаки после чужой ошибки живёт секунды, разница по шинам —
    круги. Порядок — по срочности для действия, а не по редкости."""
    code, _ = _check(intel, delta=9, mistake=True, style="aggressive", now=100.0)
    assert code == CODE_MISTAKE


def test_the_same_fact_about_the_same_rival_is_said_once(intel):
    """Возраст резины растёт непрерывно. Без этого правила инженер пересказывал
    бы его каждый круг."""
    assert _check(intel, delta=9, now=100.0) is not None
    assert _check(intel, delta=10, now=200.0) is None


def test_the_same_fact_about_a_different_rival_is_new(intel):
    """Обгон состоялся, впереди другой — про него мы ещё ничего не говорили."""
    assert _check(intel, idx=RIVAL, delta=9, now=100.0) is not None
    assert _check(intel, idx=OTHER, delta=9, now=200.0) is not None


def test_cooldown_separates_even_different_facts(intel):
    """Даже разные факты подряд превращают инженера в диктора статистики."""
    assert _check(intel, mistake=True, now=100.0) is not None
    assert _check(intel, delta=9, now=110.0) is None
    assert _check(intel, delta=9, now=150.0) is not None


def test_reset_forgets_everything(intel):
    assert _check(intel, delta=9, now=100.0) is not None
    intel.reset("new session")
    assert _check(intel, delta=9, now=200.0) is not None


# ── Связь с банком и маршрутизацией ──────────────────────────────────────────

def test_every_produced_code_exists_in_the_bank():
    """Код без спеки — молчание в бою: рендер бросит PhraseError, и разведка
    просто не прозвучит, а тесты трекера при этом останутся зелёными."""
    for code in (CODE_MISTAKE, CODE_TYRES_OLDER, CODE_TYRES_FRESHER,
                 CODE_STYLE_AGGRESSIVE, CODE_STYLE_FADING):
        assert code in phrases.codes(), code


def test_tyre_specs_declare_the_laps_field():
    for code in (CODE_TYRES_OLDER, CODE_TYRES_FRESHER):
        assert phrases.spec_for(code).all_fields == {"laps"}


# ── Проводка ─────────────────────────────────────────────────────────────────
# Корректный трекер сам по себе ничего не даёт: разведка уже существовала как
# ДАННЫЕ и не доезжала до пилота именно потому, что её никто не публиковал.

PLAYER = 3


@pytest.fixture
def engine(monkeypatch):
    import core.engine as eng_mod
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = eng_mod.F1Engine({"engineer_chatter_enabled": True})
    e._player_car_index = PLAYER
    e._session_type = "race"
    e._player_pos = 4
    e._positions = {PLAYER: 4, RIVAL: 3}      # RIVAL идёт прямо впереди
    e._player_tyre_age = 2
    # Профиль соперника заводится ТОЛЬКО через update() с гридом: update_tyre()
    # молча игнорирует машину, которую ещё не видел (см. его docstring). Без
    # этой строки возраст шин остаётся None, и тик честно молчит.
    e.rival_tracker.update(
        [{"vehicle_idx": PLAYER, "position": 4, "lap": 10},
         {"vehicle_idx": RIVAL, "position": 3, "lap": 10}],
        PLAYER, 0.0)
    e.rival_tracker.update_tyre(RIVAL, 14)
    return e


def _drain_codes(engine) -> list[str]:
    out = []
    while not engine._commentary_events.empty():
        out.append(engine._commentary_events.get_nowait().get("event_code"))
    return out


def test_tick_publishes_intel_about_the_car_ahead(engine):
    engine._rival_intel_tick()
    assert "ENGINEER_RIVAL_INTEL" in _drain_codes(engine)


def test_the_spoken_line_carries_agreed_russian(engine):
    """`laps` — required-поле: `render()` подставляет значение КАК ЕСТЬ, поэтому
    согласовать числительное обязан вызывающий. Без этого прозвучало бы
    «на 12 круг старше»."""
    engine._rival_intel_tick()
    said = [e for e in [engine._commentary_events.get_nowait()]
            if e.get("event_code") == "ENGINEER_RIVAL_INTEL"]
    assert said and "кругов" in said[0]["phrase"], said[0]["phrase"]


def test_no_intel_outside_a_race(engine):
    """В практике «соперник впереди» — случайная машина на своём круге."""
    engine._session_type = "practice"
    engine._rival_intel_tick()
    assert "ENGINEER_RIVAL_INTEL" not in _drain_codes(engine)


def test_intel_respects_the_chatter_setting(engine):
    engine.settings["engineer_chatter_enabled"] = False
    engine._rival_intel_tick()
    assert "ENGINEER_RIVAL_INTEL" not in _drain_codes(engine)


def test_no_car_ahead_means_no_intel(engine):
    """Игрок лидирует — впереди никого, и разведывать нечего."""
    engine._player_pos = 1
    engine._positions = {PLAYER: 1, RIVAL: 2}
    engine._rival_intel_tick()
    assert "ENGINEER_RIVAL_INTEL" not in _drain_codes(engine)


def test_unknown_tyre_age_does_not_invent_a_number(engine):
    """Возраст шин игрока неизвестен — разницы не существует. Выдумать её
    значит назвать пилоту неверное число."""
    engine._player_tyre_age = None
    engine._rival_intel_tick()
    assert "ENGINEER_RIVAL_INTEL" not in _drain_codes(engine)


def test_rival_intel_is_its_own_topic():
    """Разведданные — НЕ та же новость, что дистанция: «отрыв 0,9» и «у него
    шины старше» дополняют друг друга, и душить второе первым нельзя. А вот три
    реплики подряд про одного соперника — повтор, поэтому тема своя."""
    intel_topic = policy.topic_for("ENGINEER_RIVAL_INTEL")
    assert intel_topic is not None
    assert intel_topic[0] != policy.topic_for("ENGINEER_GAP_DIGEST")[0]
