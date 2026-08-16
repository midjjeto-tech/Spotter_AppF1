# tests/test_engine_damage.py
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_event_involves_collision_either_side(engine):
    event = {"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7}
    assert engine._event_involves(event, 3) is True
    assert engine._event_involves(event, 7) is True
    assert engine._event_involves(event, 12) is False


def test_damage_state_updates_every_tick(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    dmg = {"wing_damage": 5, "floor_damage": 3, "gearbox_damage": 0, "engine_damage": 0}
    engine._update_damage(dmg)
    state = engine.get_state().get("damage")
    assert state == {"wing_damage": 5, "floor_damage": 3, "gearbox_damage": 0, "engine_damage": 0}


def test_damage_voice_fires_once_on_threshold_cross(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    engine._update_damage({"wing_damage": 25, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "DAMAGE_WING"
    assert "крыло" in evt["phrase"].lower()
    assert engine._damage_announced["wing"] is True

    # тот же тик снова >= порога -> тишина (флаг уже True)
    engine._update_damage({"wing_damage": 30, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine._commentary_events.empty()


def test_damage_voice_silent_below_threshold(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()
    engine._update_damage({"wing_damage": 19, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine._commentary_events.empty()
    assert engine._damage_announced["wing"] is False


def test_damage_voice_refires_after_repair_and_new_damage(engine):
    engine._damage_announced = {"wing": True, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    # ремонт в боксах -> падает ниже порога -> флаг сбрасывается, тишина
    engine._update_damage({"wing_damage": 0, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine._commentary_events.empty()
    assert engine._damage_announced["wing"] is False

    # новая поломка того же крыла -> объявляется заново
    engine._update_damage({"wing_damage": 45, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "DAMAGE_WING"
    assert engine._damage_announced["wing"] is True


def test_damage_voice_fires_independently_per_category(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    engine._update_damage({"wing_damage": 25, "floor_damage": 25, "gearbox_damage": 0, "engine_damage": 0})
    events = []
    while not engine._commentary_events.empty():
        events.append(engine._commentary_events.get_nowait())
    codes = {e["event_code"] for e in events}
    assert codes == {"DAMAGE_WING", "DAMAGE_FLOOR"}


# --------------------------------------------------------------------------- #
# Phrase variety (item 6 backlog: "формат комментариев" -> was one fixed
# string per category, no variation). See docs/superpowers/plans/2026-07-20-
# defense-event-damage-phrase-variety.md.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("category, damage_key, event_code", [
    ("wing", "wing_damage", "DAMAGE_WING"),
    ("floor", "floor_damage", "DAMAGE_FLOOR"),
    ("gearbox", "gearbox_damage", "DAMAGE_GEARBOX"),
    ("engine", "engine_damage", "DAMAGE_ENGINE"),
])
def test_damage_phrase_drawn_from_pool(engine, category, damage_key, event_code):
    """Вариативность теперь измеряется МЕЖДУ ситуациями, а не между повторами
    одной.

    Раньше выбор был случайным (`pick_phrase`), и тест гонял одно и то же
    повреждение 30 раз, ожидая разные строки. С переходом на банк выбор стал
    детерминированным по `dedupe_key`: одна ситуация — одна формулировка, чтобы
    повторный пакет телеметрии не переписывал уже произнесённую реплику. Поэтому
    30 повторов ОДНОГО повреждения на одном круге обязаны дать одну строку, а
    разные круги — разные."""
    from core.radio import phrases as radio_phrases

    spec = radio_phrases.spec_for(f"damage.{category}")

    def announce(lap):
        engine._player_lap = lap
        engine._damage_announced = {"wing": False, "floor": False,
                                    "gearbox": False, "engine": False}
        while not engine._commentary_events.empty():
            engine._commentary_events.get_nowait()
        engine._update_damage({"wing_damage": 0, "floor_damage": 0,
                               "gearbox_damage": 0, "engine_damage": 0,
                               damage_key: 45})
        evt = engine._commentary_events.get_nowait()
        assert evt["event_code"] == event_code
        assert evt["phrase"] in spec.variants
        return evt["phrase"]

    # Одна ситуация: формулировка закреплена.
    same_situation = {announce(12) for _ in range(10)}
    assert len(same_situation) == 1

    # Разные ситуации: банк отдаёт разные варианты.
    across_laps = {announce(lap) for lap in range(1, 40)}
    assert len(across_laps) > 1


# ---------------------------------------------------------------------------
# Градация контакта (2026-08-11)
# ---------------------------------------------------------------------------
#
# Проверяется ПРОВОДКА: раньше любое касание доезжало до LLM как «авария» с
# важностью 90, потому что COLL безусловно лежал в packets.CRITICAL_EVENTS.
# Тяжести в пакете нет вовсе, поэтому она выводится из последствия.

def _fresh(engine):
    """Чистый движок для одного сценария контакта."""
    engine._pending_contact = None
    engine._player_car_index = 3
    engine._positions = {3: 5}
    engine._player_damage = None
    engine._update_damage({"wing_damage": 0, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0})
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()


def _contact(engine):
    engine._handle_race_event(
        {"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7})


def _codes(engine):
    out = []
    while not engine._commentary_events.empty():
        out.append(engine._commentary_events.get_nowait()["event_code"])
    return out


def _grade(engine):
    """Коды, которые ВЫНЕС `_grade_contact`, независимо от того, дошли ли они
    до озвучки.

    Через очередь смотреть нельзя: COLL_LIGHT намеренно глушится фильтром и в
    неё не попадает вовсе, так что очередь ответила бы «ничего не решено» и на
    правильную работу, и на полную поломку градации."""
    seen = []
    original = engine._handle_race_event

    def spy(event):
        seen.append(event.get("event_code"))
        return original(event)

    engine._handle_race_event = spy
    try:
        engine._grade_contact(engine._pending_contact["deadline"] + 0.1)
    finally:
        engine._handle_race_event = original
    return seen


def test_contact_is_not_announced_before_the_consequence_is_known(engine):
    """Ключевой момент: в СЕКУНДУ удара судить не по чему."""
    _fresh(engine)
    _contact(engine)

    assert engine._pending_contact is not None
    assert "COLL" not in _codes(engine), "реплика ушла до появления последствия"


def test_a_scrape_without_damage_is_graded_light(engine):
    _fresh(engine)
    _contact(engine)

    assert _grade(engine) == ["COLL_LIGHT"]


def test_a_light_scrape_never_reaches_the_voice(engine):
    """Главное требование пользователя, и одной низкой важностью оно НЕ
    выполняется: порога озвучки по важности в проекте нет, `_should_voice`
    пропускает всё. Молчание обязан обеспечивать фильтр."""
    _fresh(engine)
    assert engine._should_commentate({"event_code": "COLL_LIGHT"}) is False


def test_a_real_contact_still_reaches_the_voice(engine):
    """Обратная сторона: глушить сам контакт нельзя, иначе градация
    превратится в цензуру."""
    _fresh(engine)
    assert engine._should_commentate(
        {"event_code": "COLL", "vehicle1_idx": 3}) is True


def test_damage_after_the_contact_makes_it_a_real_contact(engine):
    _fresh(engine)
    _contact(engine)
    engine._update_damage({"wing_damage": 12, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0})
    assert _grade(engine) == ["COLL"]


def test_heavy_damage_is_still_an_accident(engine):
    """Градация не должна глушить настоящую аварию — драма тут уместна."""
    _fresh(engine)
    _contact(engine)
    engine._update_damage({"wing_damage": 60, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0})
    assert _grade(engine) == ["COLL_HEAVY"]


def test_previous_damage_does_not_inflate_a_fresh_scrape(engine):
    """Считается ПРИРОСТ, а не абсолют: разбитое кругом раньше крыло не делает
    сегодняшнюю притирку аварией."""
    _fresh(engine)
    engine._update_damage({"wing_damage": 80, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0})
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    _contact(engine)

    assert _grade(engine) == ["COLL_LIGHT"]


def test_a_lost_position_counts_as_a_consequence_without_damage(engine):
    """Выбило с позиции без единого процента повреждения — это уже не притирка."""
    _fresh(engine)
    _contact(engine)
    engine._positions = {3: 8}

    assert _grade(engine) == ["COLL"]


def test_a_series_of_scrapes_is_one_episode(engine):
    """Три касания в одном повороте — один эпизод, а не три реплики."""
    _fresh(engine)
    _contact(engine)
    first_deadline = engine._pending_contact["deadline"]
    _contact(engine)
    _contact(engine)

    # `>=`, а не `>`: три вызова подряд укладываются в одно значение
    # monotonic(), и точность часов здесь ни при чём — проверяется, что окно
    # ПРОДЛЕВАЕТСЯ, а не что оно сдвинулось на измеримую величину.
    assert engine._pending_contact["deadline"] >= first_deadline
    assert len(_grade(engine)) == 1, "серия притирок дала больше одной реплики"


def test_a_graded_contact_does_not_loop_back_into_deferral(engine):
    """Опубликованное событие обязано пройти пайплайн насквозь: без флага
    `contact_graded` оценка ушла бы на второй круг и реплика не прозвучала бы
    никогда."""
    _fresh(engine)
    _contact(engine)

    assert _grade(engine) == ["COLL_LIGHT"]
    assert engine._pending_contact is None, "оценка ушла на второй круг"


def test_contact_not_involving_the_player_is_not_deferred(engine):
    """Чужой контакт откладывать нечего и незачем: данных о повреждении чужой
    машины у нас нет, а игрок этого касания не почувствовал."""
    _fresh(engine)
    engine._handle_race_event(
        {"event_code": "COLL", "vehicle1_idx": 11, "vehicle2_idx": 7})

    assert engine._pending_contact is None


def test_other_cars_crashes_are_still_covered(engine):
    """Регрессия, которую легко было внести незаметно.

    Чужие столкновения проходили фильтр «Позиция комментатора» в режиме `auto`
    зайцем — как побочный эффект безусловного `priority=critical` у COLL. Стоило
    убрать critical, и освещение чужих аварий исчезло бы молча, без единого
    падающего теста."""
    _fresh(engine)
    engine._handle_race_event(
        {"event_code": "COLL", "vehicle1_idx": 11, "vehicle2_idx": 7})

    assert "COLL" in _codes(engine)


def test_a_flashback_throws_away_a_contact_that_never_happened(engine):
    """Отложенный контакт — событие из ОТМЕНЁННОГО будущего.

    `_handle_flashback` сливает очередь комментариев именно для того, чтобы
    до-флэшбековые события не доехали до пилота, но `_pending_contact` ещё не
    опубликован и сливом не достаётся. Без явной чистки `_grade_contact`
    дозревал уже после перемотки, оценивал удар по пост-откатным повреждениям и
    позиции и выкладывал в ленту контакт, которого в игре больше нет.
    """
    _fresh(engine)
    _contact(engine)
    assert engine._pending_contact is not None

    engine._handle_flashback()

    assert engine._pending_contact is None
    # И следующий тик телеметрии его уже не дозреет: слот пуст, публиковать
    # нечего. Через `_grade` смотреть нельзя — тот сам читает `deadline`.
    engine._grade_contact(1e9)
    assert _codes(engine) == []


def test_a_heavy_crash_is_a_hero_shot_like_the_ungraded_collision_was(engine):
    """Скриншот привязан к КОДУ, а контакт игрока приезжает уже оценённым.

    Пока в наборе был только `COLL`, снимок получала притирка, прошедшая как
    средний контакт, а настоящая авария — нет.
    """
    assert "COLL_HEAVY" in eng_mod._HERO_SCREENSHOT_CODES
    assert "COLL" in eng_mod._HERO_SCREENSHOT_CODES
    # Притирка без последствий — снимать нечего.
    assert "COLL_LIGHT" not in eng_mod._HERO_SCREENSHOT_CODES
