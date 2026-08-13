"""Семантическая дедупликация ситуаций (core/situation_dedup.py) — анти-спам погони."""
from core.situation_dedup import SituationDedup, gap_band


# Базовый набор «нет соседей/лидера», переопределяем только нужное в тесте.
_NONE = dict(gap_front_ms=None, gap_behind_ms=None, gap_leader_ms=None,
             ahead_name=None, behind_name=None, leader_name=None)


def _sig(d: SituationDedup, code="OVTK", **over):
    kw = {**_NONE, **over}
    return d.signature({"event_code": code}, **kw)


# --------------------------------------------------------------------------- #
# gap_band
# --------------------------------------------------------------------------- #

def test_gap_band_boundaries():
    assert gap_band(None) is None
    assert gap_band(0) is None
    assert gap_band(400) == "vclose"
    assert gap_band(700) == "close"
    assert gap_band(1500) == "near"
    assert gap_band(3000) == "far"


# --------------------------------------------------------------------------- #
# Сигнатура: что считается «ситуацией»
# --------------------------------------------------------------------------- #

def test_non_proximity_event_has_no_signature():
    d = SituationDedup()
    sig = _sig(d, code="PENA", gap_front_ms=400, ahead_name="Албон")
    assert sig is None
    # None всегда пропускается (дедуп не для этого кода)
    assert d.should_emit(sig, now=100.0) is True


def test_dominant_fight_is_closest_neighbor():
    d = SituationDedup()
    # впереди 1.5с (near), сзади 0.4с (vclose) → доминирует тыл
    sig = _sig(d, code="BATTLE", gap_front_ms=1500, gap_behind_ms=400,
               ahead_name="Албон", behind_name="Расселл")
    assert sig == ("back", "Расселл", "vclose")


def test_leader_fallback_when_no_neighbors():
    d = SituationDedup()
    sig = _sig(d, gap_leader_ms=1500, leader_name="Ферстаппен")
    assert sig == ("leader", "Ферстаппен", "near")


# --------------------------------------------------------------------------- #
# Дедуп: подавление и пропуск «материальных изменений»
# --------------------------------------------------------------------------- #

def test_same_situation_suppressed_within_cooldown():
    d = SituationDedup(cooldown=20)
    s1 = _sig(d, code="OVTK", gap_front_ms=400, ahead_name="Албон")
    assert d.should_emit(s1, now=100.0) is True
    # 4с спустя, другой код но та же погоня (та же band, тот же сосед) → молчим
    s2 = _sig(d, code="ATTACK", gap_front_ms=450, ahead_name="Албон")
    assert d.should_emit(s2, now=104.0) is False


def test_band_change_emits():
    d = SituationDedup(cooldown=20)
    d.should_emit(_sig(d, gap_front_ms=400, ahead_name="Албон"), now=100.0)   # vclose
    s2 = _sig(d, gap_front_ms=1500, ahead_name="Албон")                        # near
    assert d.should_emit(s2, now=104.0) is True   # дистанция реально изменилась


def test_target_change_emits():
    d = SituationDedup(cooldown=20)
    d.should_emit(_sig(d, gap_front_ms=400, ahead_name="Албон"), now=100.0)
    s2 = _sig(d, gap_front_ms=400, ahead_name="Леклер")   # обгон состоялся → новый впереди
    assert d.should_emit(s2, now=104.0) is True


def test_cooldown_expiry_emits_again():
    d = SituationDedup(cooldown=20)
    d.should_emit(_sig(d, gap_front_ms=400, ahead_name="Албон"), now=100.0)
    s2 = _sig(d, gap_front_ms=400, ahead_name="Албон")
    assert d.should_emit(s2, now=125.0) is True   # 25с > cooldown


def test_reset_clears_memory():
    d = SituationDedup(cooldown=20)
    d.should_emit(_sig(d, gap_front_ms=400, ahead_name="Албон"), now=100.0)
    d.reset()
    s2 = _sig(d, gap_front_ms=400, ahead_name="Албон")
    assert d.should_emit(s2, now=101.0) is True   # после reset — озвучиваем, хоть и та же/скоро


# --------------------------------------------------------------------------- #
# Контакт: сигнатура по УЧАСТНИКАМ, а не по дистанции.
# Разбор заезда 2026-08-11: 32 COLL за гонку, один инцидент — десяток пересказов.
# --------------------------------------------------------------------------- #

def _coll_sig(d: SituationDedup, driver, target, code="COLL", **over):
    """Сигнатура контакта. Отдельный помощник: базовый `_sig` выше собирает
    событие без участников, а для контакта важны именно они."""
    kw = {**_NONE, **over}
    return d.signature(
        {"event_code": code, "driver": driver, "target": target}, **kw)


def test_same_contact_is_one_situation_regardless_of_gap():
    """Отрыв в момент контакта скачет — он не должен делать инцидент новым."""
    d = SituationDedup(cooldown=20.0)
    first = _coll_sig(d, "Леклер", "Хэмилтон", gap_front_ms=400)
    second = _coll_sig(d, "Леклер", "Хэмилтон", gap_front_ms=9000)
    assert first == second
    assert d.should_emit(first, now=100.0) is True
    assert d.should_emit(second, now=101.0) is False


def test_contact_pair_is_unordered():
    """«Леклер задел Хэмилтона» и наоборот — один контакт, не два."""
    d = SituationDedup(cooldown=20.0)
    assert (_coll_sig(d, "Леклер", "Хэмилтон")
            == _coll_sig(d, "Хэмилтон", "Леклер"))


def test_contact_with_another_driver_is_a_new_situation():
    d = SituationDedup(cooldown=20.0)
    assert d.should_emit(_coll_sig(d, "Леклер", "Хэмилтон"), now=100.0) is True
    assert d.should_emit(_coll_sig(d, "Леклер", "Норрис"), now=101.0) is True


def test_contact_speaks_again_after_cooldown():
    d = SituationDedup(cooldown=20.0)
    sig = _coll_sig(d, "Леклер", "Хэмилтон")
    assert d.should_emit(sig, now=100.0) is True
    assert d.should_emit(sig, now=105.0) is False
    assert d.should_emit(sig, now=121.0) is True


def test_graded_contact_codes_share_the_situation():
    """COLL_LIGHT/COLL/COLL_HEAVY — градация ОДНОГО касания, не три новости."""
    d = SituationDedup(cooldown=20.0)
    assert (_coll_sig(d, "Леклер", "Хэмилтон", code="COLL_LIGHT")
            == _coll_sig(d, "Леклер", "Хэмилтон", code="COLL_HEAVY"))


def test_contact_without_participants_is_not_deduped():
    """Некого сравнивать — молчать на основании неизвестного нельзя."""
    assert _coll_sig(SituationDedup(), "", "") is None
