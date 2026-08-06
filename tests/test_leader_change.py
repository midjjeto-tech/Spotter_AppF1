"""LeaderChangeTracker — debounce 2с, первое наблюдение = базовая линия
(не объявляется), откат до истечения debounce не оставляет устаревший
_pending. См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from core.strategy_ai.leader_change import DEBOUNCE_S, LeaderChangeTracker


def test_first_observation_sets_baseline_no_announcement():
    t = LeaderChangeTracker()
    assert t.check(leader_idx=3, now=100.0) is None


def test_same_leader_no_announcement():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)
    assert t.check(leader_idx=3, now=101.0) is None


def test_new_leader_announced_after_debounce():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)             # базовая линия
    assert t.check(leader_idx=7, now=101.0) is None   # pending, ждёт debounce
    result = t.check(leader_idx=7, now=101.0 + DEBOUNCE_S + 0.1)
    assert result == 7


def test_new_leader_not_announced_before_debounce_elapses():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)
    t.check(leader_idx=7, now=101.0)
    result = t.check(leader_idx=7, now=101.0 + DEBOUNCE_S - 0.1)
    assert result is None


def test_revert_before_debounce_does_not_announce_and_clears_pending():
    """3->7->3 откат до истечения debounce -> не объявляет 7, и следующая
    настоящая смена на 7 позже ждёт полные DEBOUNCE_S заново (не мгновенно
    по старому таймеру) — найдено самопроверкой спеки. leader_idx — int
    (vehicle_idx), как в остальных тестах файла и в проде."""
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)              # базовая линия
    t.check(leader_idx=7, now=101.0)               # pending 7
    result_revert = t.check(leader_idx=3, now=101.5)  # откат до истечения debounce
    assert result_revert is None

    # Спустя долгое время (>> DEBOUNCE_S с первого pending на 7) — настоящая смена на 7.
    result_too_soon = t.check(leader_idx=7, now=101.6)   # только что переармировали
    assert result_too_soon is None

    # Различающая проверка (найдено ревью: без неё тест не отличал бы
    # исправленную версию от "сломанной", где _pending не чистится при
    # откате). Устаревший таймер (от первого pending@101.0) истёк бы уже к
    # 103.0 (101.0+DEBOUNCE_S); правильный, перезапущенный при откате
    # таймер (от re-arm@101.6) истекает только к 103.6. Момент 103.3 лежит
    # СТРОГО между ними: "сломанная" версия уже объявила бы 7 здесь
    # (103.3-101.0=2.3>=2.0), исправленная — ещё нет (103.3-101.6=1.7<2.0).
    result_discriminating = t.check(leader_idx=7, now=103.3)
    assert result_discriminating is None

    result = t.check(leader_idx=7, now=101.6 + DEBOUNCE_S + 0.1)
    assert result == 7


def test_reset_clears_state():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)
    t.check(leader_idx=7, now=101.0)
    t.reset()
    assert t.check(leader_idx=7, now=200.0) is None   # снова базовая линия
