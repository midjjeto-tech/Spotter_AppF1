"""Comment Planner wiring в F1Engine: очередь по важности, _enqueue_event(),
_plan_context(). См. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md.
"""
import time

import pytest

import config
import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, PACKET_SESSION
from tests.telemetry import consume_f1_packet, set_connection


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    return drained


def _speak_threshold(engine, now):
    return engine._commentary_runtime.speak_threshold(
        now, mode=engine._get_setting("commentary_mode", "live"))


def _muted_by_threshold(engine, event, now):
    return engine._commentary_runtime.muted_by_threshold(
        event, now, mode=engine._get_setting("commentary_mode", "live"))


# --------------------------------------------------------------------------- #
# _enqueue_event
# --------------------------------------------------------------------------- #

def test_enqueue_event_computes_importance(engine):
    _drain(engine)
    engine._session_type = "race"           # база проверяется в контексте гонки, не "unknown"
    engine._commentary_events.publish({"event_code": "OVTK", "priority": "normal"})
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 60          # база OVTK, без модификаторов (нет "battle" и т.п.)
    engine._session_type = "unknown"        # вернуть __init__-дефолт для последующих тестов


def test_enqueue_event_respects_precomputed_importance(engine):
    _drain(engine)
    engine._commentary_events.publish({"event_code": "OVTK", "importance": 99})
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 99          # уже посчитана - не пересчитываем


def test_enqueue_event_falls_back_to_50_on_scoring_failure(engine, monkeypatch):
    _drain(engine)

    def _boom(event, ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(eng_mod, "score_importance", _boom)
    engine._commentary_events.publish({"event_code": "OVTK"})
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 50


def test_enqueue_event_stamps_enqueued_at(engine):
    _drain(engine)
    before = time.time()
    engine._commentary_events.publish({"event_code": "OVTK"})
    evt = engine._commentary_events.get_nowait()
    assert evt["enqueued_at"] >= before


def test_enqueue_event_drains_by_importance_not_fifo(engine):
    _drain(engine)
    engine._commentary_events.publish({"event_code": "AMBIENT", "ambient": True})            # importance 20
    engine._commentary_events.publish({"event_code": "COLL", "priority": "critical",
                            "vehicle1_idx": 1, "vehicle2_idx": 2})                # importance 90
    first = engine._commentary_events.get_nowait()
    assert first["event_code"] == "COLL"
    second = engine._commentary_events.get_nowait()
    assert second["event_code"] == "AMBIENT"


# --------------------------------------------------------------------------- #
# _plan_context
# --------------------------------------------------------------------------- #

def test_plan_context_player_involved(engine):
    engine._player_car_index = 3
    ctx = engine._plan_context({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert ctx.player_involved is True
    engine._player_car_index = 255


def test_plan_context_not_involved_when_other_cars(engine):
    engine._player_car_index = 9
    ctx = engine._plan_context({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert ctx.player_involved is False
    engine._player_car_index = 255


def test_plan_context_battle_flag_passthrough(engine):
    ctx = engine._plan_context({"event_code": "OVTK", "battle": True})
    assert ctx.battle is True


def test_plan_context_laps_remaining(engine):
    engine._player_lap = 18
    engine._total_laps = 20
    ctx = engine._plan_context({"event_code": "OVTK"})
    assert ctx.laps_remaining == 2
    engine._player_lap = None
    engine._total_laps = None


def test_plan_context_laps_remaining_none_when_unknown(engine):
    engine._player_lap = None
    engine._total_laps = None
    ctx = engine._plan_context({"event_code": "OVTK"})
    assert ctx.laps_remaining is None


def test_plan_context_session_type_passthrough(engine):
    engine._session_type = "practice"
    ctx = engine._plan_context({"event_code": "OVTK"})
    assert ctx.session_type == "practice"
    engine._session_type = "race"


# --------------------------------------------------------------------------- #
# _speak_threshold: динамический порог "говорить/молчать"
# --------------------------------------------------------------------------- #

def test_speak_threshold_spikes_right_after_voicing(engine):
    engine._commentary_runtime.last_voiced_at = 1000.0
    assert _speak_threshold(engine, 1000.0) == config.PLAN_SPIKE_THRESHOLD


def test_speak_threshold_decays_to_base_after_full_window(engine):
    engine._commentary_runtime.last_voiced_at = 1000.0
    result = _speak_threshold(engine, 1000.0 + config.PLAN_THRESHOLD_DECAY_S)
    assert result == config.PLAN_BASE_THRESHOLD


def test_speak_threshold_midpoint_is_halfway(engine):
    engine._commentary_runtime.last_voiced_at = 1000.0
    half = config.PLAN_THRESHOLD_DECAY_S / 2
    expected = config.PLAN_SPIKE_THRESHOLD - (
        config.PLAN_SPIKE_THRESHOLD - config.PLAN_BASE_THRESHOLD) * 0.5
    assert _speak_threshold(engine, 1000.0 + half) == pytest.approx(expected)


def test_speak_threshold_base_when_never_voiced(engine):
    engine._commentary_runtime.last_voiced_at = 0.0
    assert _speak_threshold(engine, time.time()) == config.PLAN_BASE_THRESHOLD


# --------------------------------------------------------------------------- #
# _muted_by_threshold: bypass_speak_threshold (PIT_CALL_NOTICE companion fix)
# --------------------------------------------------------------------------- #

def test_muted_by_threshold_mutes_default_importance_right_after_critical(engine):
    """Регрессия: без bypass_speak_threshold реплика-компаньон с обычной
    важностью (50) молча гасилась бы каждый раз, если её ставят в очередь
    сразу после только что озвученного critical-события (спайк порога)."""
    now = time.time()
    engine._commentary_runtime.last_voiced_at = now                  # как сразу после critical-фразы
    assert _muted_by_threshold(engine, {"event_code": "PIT_CALL_NOTICE"}, now) is True


def test_muted_by_threshold_bypass_flag_clears_fresh_spike(engine):
    now = time.time()
    engine._commentary_runtime.last_voiced_at = now
    event = {"event_code": "PIT_CALL_NOTICE", "bypass_speak_threshold": True}
    assert _muted_by_threshold(engine, event, now) is False


def test_muted_by_threshold_ambient_bypasses_regardless_of_importance(engine):
    now = time.time()
    engine._commentary_runtime.last_voiced_at = now
    assert _muted_by_threshold(engine, {"event_code": "AMBIENT", "ambient": True}, now) is False


def test_muted_by_threshold_high_importance_clears_gate_without_bypass_flag(engine):
    now = time.time()
    engine._commentary_runtime.last_voiced_at = now
    event = {"event_code": "COLL", "importance": 90}
    assert _muted_by_threshold(engine, event, now) is False


# --------------------------------------------------------------------------- #
# Гэп/прерывание по важности — покрыто через _speak_threshold/config константы
# напрямую (сам _commentary_loop не юнит-тестируется — бесконечный цикл с
# блокирующим get(), как и раньше в этом файле; см. Task 5 плана — код-ревью
# диффа, тот же подход, что и для SSTA-сброса в Damage plan).
# --------------------------------------------------------------------------- #

def test_gap_skip_and_interrupt_thresholds_share_same_value():
    """Design invariant: importance >= 90 должно одновременно (а) обнулять гэп и
    (б) прерывать текущую озвучку — иначе критические события сегодняшнего дня
    потеряли бы одну из двух гарантий. Обе константы обязаны совпадать."""
    assert config.PLAN_GAP_SKIP_THRESHOLD == config.PLAN_INTERRUPT_THRESHOLD == 90


def test_gap_half_threshold_is_below_skip_threshold():
    assert config.PLAN_GAP_HALF_THRESHOLD < config.PLAN_GAP_SKIP_THRESHOLD


def test_enqueue_event_stamps_laps_remaining(engine):
    _drain(engine)
    engine._player_lap = 18
    engine._total_laps = 20
    engine._commentary_events.publish({"event_code": "OVTK"})
    evt = engine._commentary_events.get_nowait()
    assert evt["laps_remaining"] == 2
    engine._player_lap = None
    engine._total_laps = None


def test_enqueue_event_laps_remaining_none_when_unknown(engine):
    _drain(engine)
    engine._player_lap = None
    engine._total_laps = None
    engine._commentary_events.publish({"event_code": "OVTK"})
    evt = engine._commentary_events.get_nowait()
    assert evt["laps_remaining"] is None


def test_enqueue_event_stamps_laps_remaining_even_with_precomputed_importance(engine):
    _drain(engine)
    engine._player_lap = 19
    engine._total_laps = 20
    engine._commentary_events.publish({"event_code": "OVTK", "importance": 99})
    evt = engine._commentary_events.get_nowait()
    assert evt["laps_remaining"] == 1
    assert evt["importance"] == 99
    engine._player_lap = None
    engine._total_laps = None


def test_enqueue_event_falls_back_when_plan_context_fails(engine, monkeypatch):
    _drain(engine)

    def _boom(event):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_plan_context", _boom)
    engine._commentary_events.publish({"event_code": "OVTK"})
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 50
    assert evt["laps_remaining"] is None


# --------------------------------------------------------------------------- #
# _speak_threshold: commentary_mode офсет (live/calm/story)
# --------------------------------------------------------------------------- #

def test_speak_threshold_live_mode_unchanged(engine):
    engine.settings["commentary_mode"] = "live"
    engine._commentary_runtime.last_voiced_at = 1000.0
    assert _speak_threshold(engine, 1000.0) == config.PLAN_SPIKE_THRESHOLD
    del engine.settings["commentary_mode"]


def test_speak_threshold_calm_mode_raises_spike_and_base(engine):
    engine.settings["commentary_mode"] = "calm"
    offset = config.COMMENTARY_MODE_THRESHOLD_OFFSET["calm"]
    engine._commentary_runtime.last_voiced_at = 1000.0
    assert _speak_threshold(engine, 1000.0) == config.PLAN_SPIKE_THRESHOLD + offset
    result = _speak_threshold(engine, 1000.0 + config.PLAN_THRESHOLD_DECAY_S)
    assert result == config.PLAN_BASE_THRESHOLD + offset
    del engine.settings["commentary_mode"]


def test_speak_threshold_story_mode_same_offset_as_calm(engine):
    engine.settings["commentary_mode"] = "story"
    engine._commentary_runtime.last_voiced_at = 1000.0
    assert _speak_threshold(engine, 1000.0) == (
        config.PLAN_SPIKE_THRESHOLD + config.COMMENTARY_MODE_THRESHOLD_OFFSET["story"])
    del engine.settings["commentary_mode"]


def test_speak_threshold_missing_setting_defaults_to_live(engine):
    engine._commentary_runtime.last_voiced_at = 1000.0
    assert _speak_threshold(engine, 1000.0) == config.PLAN_SPIKE_THRESHOLD


def test_speak_threshold_unrecognized_mode_falls_back_to_live_offset(engine):
    """COMMENTARY_MODE_THRESHOLD_OFFSET.get(mode, 0) должен молча деградировать
    к офсету live (0) для любого нераспознанного значения — не бросать KeyError."""
    engine.settings["commentary_mode"] = "invalid"
    engine._commentary_runtime.last_voiced_at = 1000.0
    assert _speak_threshold(engine, 1000.0) == config.PLAN_SPIKE_THRESHOLD
    del engine.settings["commentary_mode"]


# --------------------------------------------------------------------------- #
# Box call tracker wiring
# --------------------------------------------------------------------------- #

def test_box_call_enqueues_critical_event_on_decisive_strategy(engine, monkeypatch):
    _drain(engine)
    engine._strategy_module.box_call_tracker.reset()
    engine._player_lap = 20
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0                    # обойти троттлинг 1с
    # Не даём ветке STRAT_UNDERCUT/OVERCUT/... (не связанной с box-call,
    # существовавшей до этой задачи) обработать неполный _FakeEvent ниже —
    # это отдельный тротлинг в _maybe_snapshot(), не наш код.
    engine._strategy_module.last_advisory_at = time.time()

    class _FakeDecision:
        action = "pit"

    class _FakeEvent:
        decision = _FakeDecision()
        confidence = 0.9

    monkeypatch.setattr(engine._strategy_module.analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()

    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    found = [e for e in drained if e["event_code"] == "STRAT_BOX_CALL_1"]
    assert len(found) == 1
    assert found[0]["priority"] == "critical"
    assert found[0]["speaker"] == "engineer"
    notices = [e for e in drained if e["event_code"] == "PIT_CALL_NOTICE"]
    assert len(notices) == 1                      # реплика комментатора рядом с tier 1
    assert "speaker" not in notices[0]            # БЕЗ speaker → голос комментатора
    assert notices[0]["bypass_speak_threshold"] is True  # иначе спайк порога гасит её
    engine._strategy_module.box_call_tracker.reset()              # не протекать в следующие тесты
    # Вернуть __init__-дефолты — engine на module-scope фикстуре, следующие
    # тесты не должны унаследовать грязное состояние (см. конвенцию файла).
    engine._player_lap = None
    engine._player_pit_status = None
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = 0.0


def test_flashback_resets_box_call_tracker(engine):
    engine._strategy_module.box_call_tracker.update(player_lap=5, action="pit", confidence=0.9, pit_status=0)
    engine._handle_flashback()
    tier = engine._strategy_module.box_call_tracker.update(
        player_lap=6, action="pit", confidence=0.9, pit_status=0)
    assert tier == 1                              # не 2 — состояние было сброшено
    engine._strategy_module.box_call_tracker.reset()


def test_decisive_box_call_suppresses_soft_advisory_same_tick(engine, monkeypatch):
    """Пока идёт решительное окно (box-call), мягкий STRAT_PIT/STRAT_UNDERCUT
    не должен звучать параллельно — иначе игрок слышит одновременно спокойный
    совет и "боксы!" про одно и то же."""
    _drain(engine)
    engine._strategy_module.box_call_tracker.reset()
    engine._player_lap = 30
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = 0.0        # advisory-троттлинг точно не мешает

    class _FakeDecision:
        action = "pit"
        reason = "pit_window_open"

    class _FakeEvent:
        type = "pit_window"
        priority = "high"
        decision = _FakeDecision()
        confidence = 0.9                          # выше DECISIVE_CONFIDENCE (0.85)
        data = {}

    monkeypatch.setattr(engine._strategy_module.analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()

    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    codes = [e["event_code"] for e in drained]
    assert "STRAT_BOX_CALL_1" in codes
    assert "STRAT_PIT" not in codes               # advisory подавлен на решительном тике

    engine._strategy_module.box_call_tracker.reset()
    engine._player_lap = None
    engine._player_pit_status = None
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = 0.0


def test_box_call_tier2_does_not_emit_notice(engine, monkeypatch):
    """PIT_CALL_NOTICE ставится только с tier 1 — на эскалации не спамим."""
    _drain(engine)
    engine._strategy_module.box_call_tracker.reset()
    engine._player_lap = 30
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = time.time()

    class _FakeDecision:
        action = "pit"

    class _FakeEvent:
        decision = _FakeDecision()
        confidence = 0.9

    monkeypatch.setattr(engine._strategy_module.analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()                      # tier 1 (+notice)
    _drain(engine)
    engine._player_lap = 31
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = time.time()
    engine._maybe_snapshot()                      # tier 2

    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    codes = [e["event_code"] for e in drained]
    assert "STRAT_BOX_CALL_2" in codes
    assert "PIT_CALL_NOTICE" not in codes

    engine._strategy_module.box_call_tracker.reset()
    engine._player_lap = None
    engine._player_pit_status = None
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = 0.0


# --------------------------------------------------------------------------- #
# _maybe_emit_gap_digest / _engineer_digest_loop
# --------------------------------------------------------------------------- #

def test_engineer_digest_loop_enqueues_preset_phrase(engine):
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True                 # __init__-дефолт False — сессия должна быть "живой"
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._commentary_runtime.last_significant_event_at = 0.0        # вне cooldown
    set_connection(engine, True)              # __init__-дефолт False — иначе гейт отрубит всё

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is True
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "ENGINEER_GAP_DIGEST"
    # Текст собирается из фрагментов банка, число подставит резолвер.
    assert "{gap}" in evt["phrase"]
    assert evt["speaker"] == "engineer"
    assert evt["bypass_speak_threshold"] is True   # иначе гаснет в загруженной гонке
    assert _muted_by_threshold(engine, evt, time.time()) is False
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "unknown"
    engine._session_active = False
    engine._player_gap_front = None
    set_connection(engine, False)


def test_engineer_digest_survives_fresh_speak_threshold_spike(engine):
    """Регрессия (найдена ревью Task 2): без bypass_speak_threshold рутинная
    сводка (importance 50 по умолчанию) систематически гасла бы именно в
    загруженной гонке, где болтовня чаще держит свежий спайк порога (65,
    до 85 в calm/story) — обратное тому, что задумано."""
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)

    engine._maybe_emit_gap_digest(time.time())
    evt = engine._commentary_events.get_nowait()

    now = time.time()
    engine._commentary_runtime.last_voiced_at = now                   # как сразу после voiced-фразы
    assert _muted_by_threshold(engine, evt, now) is False

    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "unknown"
    engine._session_active = False
    engine._player_gap_front = None
    set_connection(engine, False)
    engine._commentary_runtime.last_voiced_at = 0.0


def test_engineer_digest_loop_skips_outside_race(engine):
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "qualifying"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine._commentary_events.empty()
    engine._session_type = "unknown"
    engine._session_active = False
    engine._player_gap_front = None
    set_connection(engine, False)


def test_engineer_digest_loop_skips_during_event_cooldown(engine):
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._commentary_runtime.last_significant_event_at = time.time()  # свежая драма
    set_connection(engine, True)

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine._commentary_events.empty()
    engine._session_type = "unknown"
    engine._session_active = False
    engine._player_gap_front = None
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, False)


def test_engineer_digest_loop_skips_when_no_gap_data(engine):
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = None
    engine._player_gap_behind = None
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine._commentary_events.empty()
    engine._session_type = "unknown"
    engine._session_active = False
    set_connection(engine, False)


def test_engineer_digest_loop_skips_when_not_connected(engine):
    """__init__-дефолт state["connected"]=False — если телеметрия не
    поднялась (или отвалилась), сводка молчит, как и _ambient_loop."""
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, False)

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine._commentary_events.empty()
    engine._session_type = "unknown"
    engine._session_active = False
    engine._player_gap_front = None


def test_engineer_digest_loop_skips_when_session_not_active(engine):
    """Баг: после SEND/CHQF connected и session_type могут остаться
    "живыми" (игра шлёт пакеты из меню/результатов) — только _session_active
    реально отражает, что сессия закончилась."""
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = False
    engine._player_gap_front = 1800
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine._commentary_events.empty()
    engine._session_type = "unknown"
    engine._player_gap_front = None
    set_connection(engine, False)


def test_gap_digest_includes_battery_when_ers_present(engine):
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._player_ers_percent = 60.0
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)

    engine._maybe_emit_gap_digest(time.time())
    evt = engine._commentary_events.get_nowait()
    # Процент НЕ вписан в опубликованную фразу: заряд ERS меняется быстрее,
    # чем событие доходит до динамика (очередь + MIN_COMMENT_GAP + синтез).
    # Значение подставляет резолвер на пороге озвучки (core/radio/resolver.py).
    assert "{ers}" in evt["phrase"]
    assert "60" not in evt["phrase"]

    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "unknown"
    engine._session_active = False
    engine._player_gap_front = None
    engine._player_ers_percent = None
    set_connection(engine, False)


def test_rain_advisory_enqueues_on_session_packet(engine, monkeypatch):
    _drain(engine)
    engine._race_engineer.rain_advisory_tracker.reset()

    monkeypatch.setattr(
        "core.packets.parse_session",
        lambda data: {"total_laps": 0, "track_id": -1, "session_type": "unknown",
                       "weather": 0, "track_temp": 30, "air_temp": 22,
                       "rain_forecast": {"minutes": 15, "rain_pct": 60, "weather": 3}})
    consume_f1_packet(engine, {"packet_id": 1}, 1, b"\x00" * 40)

    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    found = [e for e in drained if e["event_code"] == "ENGINEER_RAIN_ADVISORY"]
    assert len(found) == 1
    assert found[0]["speaker"] == "engineer"
    assert found[0]["bypass_speak_threshold"] is True
    # Горизонт дождя ВОЛАТИЛЕН: в опубликованном событии он остаётся токеном и
    # подставляется резолвером перед озвучкой (ТЗ §5). Вписанное здесь «15» к
    # моменту звука было бы враньём — прогноз меняется, пока фраза ждёт очереди.
    assert "{minutes}" in found[0]["phrase"]

    engine._race_engineer.rain_advisory_tracker.reset()


# --------------------------------------------------------------------------- #
# engineer_chatter_enabled — гейтинг периодической "болтовни" инженера
# --------------------------------------------------------------------------- #

def test_chatter_disabled_suppresses_gap_digest(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    engine._session_type = "race"
    engine._session_active = True
    engine._commentary_runtime.last_significant_event_at = 0.0
    monkeypatch.setattr(engine, "_is_paused", lambda: False)
    set_connection(engine, True)
    monkeypatch.setattr(engine._race_engineer.gap_digest_tracker, "build",
                        lambda *a, **kw: ("gap.front_first",))

    emitted = engine._maybe_emit_gap_digest(time.time())
    assert emitted is False

    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "unknown"
    engine._session_active = False


def test_chatter_enabled_allows_gap_digest(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._session_active = True
    engine._commentary_runtime.last_significant_event_at = 0.0
    monkeypatch.setattr(engine, "_is_paused", lambda: False)
    set_connection(engine, True)
    monkeypatch.setattr(engine._race_engineer.gap_digest_tracker, "build",
                        lambda *a, **kw: ("gap.front_first",))
    _drain(engine)

    emitted = engine._maybe_emit_gap_digest(time.time())
    assert emitted is True
    drained = _drain(engine)
    assert any(e["event_code"] == "ENGINEER_GAP_DIGEST" for e in drained)

    engine._session_type = "unknown"
    engine._session_active = False


def test_chatter_disabled_suppresses_rain_advisory(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    monkeypatch.setattr(engine._race_engineer.rain_advisory_tracker, "check", lambda forecast: "Дождь через 5 минут")
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 200)   # с запасом под Session-пакет, нулевой буфер безопасен
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION, bytes(buf))

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_RAIN_ADVISORY"]
    engine.settings["engineer_chatter_enabled"] = True


def test_chatter_disabled_suppresses_ers_advisory_but_not_fuel(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    _drain(engine)
    engine._player_lap = 20
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = 0.0

    class _FakeDecision:
        action = "hold"
        reason = "ers_save_recommended"

    class _FakeEvent:
        type = "ers_save"
        priority = "normal"
        decision = _FakeDecision()
        confidence = 0.3
        data = {}

    monkeypatch.setattr(engine._strategy_module.analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "STRAT_ERS_SAVE" not in codes

    # Тумблер по-прежнему выключен — но STRAT_FUEL (не ers_save/ers_overtake)
    # не должен гейтоваться этим тумблером вообще.
    engine._strategy_module.last_advisory_at = 0.0
    engine._last_snap_t = 0.0   # обойти троттлинг _maybe_snapshot(), иначе второй вызов молча вернётся

    class _FakeFuelDecision:
        action = "hold"
        reason = "fuel_save_recommended"

    class _FakeFuelEvent:
        type = "fuel_save"
        priority = "normal"
        decision = _FakeFuelDecision()
        confidence = 0.3
        data = {}

    monkeypatch.setattr(engine._strategy_module.analyzer, "update", lambda snap: _FakeFuelEvent())
    engine._maybe_snapshot()

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "STRAT_FUEL" in codes

    engine.settings["engineer_chatter_enabled"] = True
    engine._player_lap = None
    engine._player_pit_status = None
    engine._last_snap_t = 0.0
    engine._strategy_module.last_advisory_at = 0.0


def test_spoken_digest_uses_charge_at_speak_time_not_publish_time(engine):
    """Сквозная проверка жалобы «батарея вечно не те цифры»: сводка собрана при
    60%, но к моменту озвучки заряд уже 14% — озвучиваем 14, а не 60."""
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._player_ers_percent = 60.0
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)
    try:
        engine._maybe_emit_gap_digest(time.time())
        evt = engine._commentary_events.get_nowait()

        engine._player_ers_percent = 14.0        # игрок отработал деплой
        spoken = engine._display_text(
            engine._build_radio_message(evt, evt["phrase"]), evt["phrase"])
        assert "14 процентов" in spoken
        assert "60" not in spoken
    finally:
        engine._race_engineer.gap_digest_tracker.reset()
        engine._session_type = "unknown"
        engine._session_active = False
        engine._player_gap_front = None
        engine._player_ers_percent = None
        set_connection(engine, False)


def test_telemetry_lost_before_speaking_drops_battery_not_whole_digest(engine):
    _drain(engine)
    engine._race_engineer.gap_digest_tracker.reset()
    engine._session_type = "race"
    engine._session_active = True
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._player_ers_percent = 60.0
    engine._commentary_runtime.last_significant_event_at = 0.0
    set_connection(engine, True)
    try:
        engine._maybe_emit_gap_digest(time.time())
        evt = engine._commentary_events.get_nowait()

        engine._player_ers_percent = None
        spoken = engine._display_text(
            engine._build_radio_message(evt, evt["phrase"]), evt["phrase"])
        assert "1,8" in spoken
        assert "атаре" not in spoken       # клауза про заряд выброшена
    finally:
        engine._race_engineer.gap_digest_tracker.reset()
        engine._session_type = "unknown"
        engine._session_active = False
        engine._player_gap_front = None
        engine._player_ers_percent = None
        set_connection(engine, False)


def test_ordinary_phrases_pass_through_resolver_untouched(engine):
    """Резолвер стоит на общем пути всех фраз — не должен ничего менять
    в обычных репликах (в т.ч. с процентами, вписанными осознанно)."""
    for phrase in ("Держи слева!", "Износ резины 78%."):
        message = engine._build_radio_message({"event_code": "OVTK"}, phrase)
        assert engine._display_text(message, phrase) == phrase


def test_spoken_phrase_also_lands_on_the_in_game_hud(engine):
    """Реплика пишется на HUD независимо от озвучки — иначе с выключенной
    авто-озвучкой инженер пропадает из игры целиком."""
    engine._ui_state.clear_feed()
    engine._ui_state.set_radio_message("Бокс, бокс.", voiced=False)
    message = engine.get_state()["radio_message"]
    assert message["text"] == "Бокс, бокс."
    assert message["voiced"] is False
    engine._ui_state.clear_feed()
