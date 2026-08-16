"""Частные тумблеры инженера: сводка по разрывам и подсказки по батарее.

До них выбор был грубым: либо `engineer_chatter_enabled` целиком (вместе с
боксами, обороной, штрафами и погодой), либо громкость персоны. Тесты держат
главное правило обоих: общий тумблер ГЛАВНЕЕ частного, а по умолчанию ничего не
пропадает.
"""
from __future__ import annotations

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.settings import DEFAULTS


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    return F1Engine({})


def test_both_toggles_default_to_on():
    """Обновление не должно молча отнимать реплики."""
    assert DEFAULTS["engineer_digest_enabled"] is True
    assert DEFAULTS["ers_hints_enabled"] is True


# ── Сводка по разрывам ───────────────────────────────────────────────────────

def _ready_for_digest(engine):
    engine._session_type = "race"
    engine._session_active = True
    engine._telemetry_connected = True
    engine._player_gap_front = 1200
    engine._player_gap_behind = 900
    engine.settings.update({"engineer_chatter_enabled": True,
                            "engineer_digest_enabled": True})


def test_the_digest_toggle_silences_only_the_digest(engine):
    _ready_for_digest(engine)
    engine.settings["engineer_digest_enabled"] = False

    assert engine._maybe_emit_gap_digest(1000.0) is False


def test_the_general_chatter_toggle_still_wins(engine):
    """Частный тумблер включён, общий выключен — молчим."""
    _ready_for_digest(engine)
    engine.settings["engineer_chatter_enabled"] = False

    assert engine._maybe_emit_gap_digest(1000.0) is False


def test_the_gate_diagnostics_no_longer_spam_the_log(engine, caplog):
    """Раньше здесь стоял `_log.info` с пометкой «ВРЕМЕННАЯ диагностика», и он
    писал строку на КАЖДОМ тике всю гонку. Разбор гейтов уехал в полевой журнал,
    который включается флагом и для того и заведён."""
    _ready_for_digest(engine)
    engine._field.enabled = False
    with caplog.at_level("INFO"):
        engine._maybe_emit_gap_digest(1000.0)

    assert not [r for r in caplog.records if "DIAG gap_digest" in r.getMessage()]


# ── Подсказки по батарее ─────────────────────────────────────────────────────

@pytest.mark.parametrize("chatter, ers, expected", [
    (True,  True,  True),    # обе включены — совет звучит
    (True,  False, False),   # снят частный
    (False, True,  False),   # снят общий
    (False, False, False),
])
def test_ers_advice_needs_both_toggles(chatter, ers, expected):
    """Ровно та матрица, ради которой тумблер и заводился: батарею можно снять,
    не выключая инженера целиком."""
    from core.strategy_ai.module import _CHATTER_GATED_TYPES

    gated = ("ers_save" in _CHATTER_GATED_TYPES and not (chatter and ers))
    assert (not gated) is expected


def test_ers_types_are_the_only_ones_gated():
    """Тумблер батареи не должен глушить боксы и топливо заодно."""
    from core.strategy_ai.module import _CHATTER_GATED_TYPES

    assert _CHATTER_GATED_TYPES == {"ers_save", "ers_overtake"}
