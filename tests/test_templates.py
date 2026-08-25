"""commentator.templates.render() — маршрутизация strategy-AI кодов в strategist.py."""
import re

import pytest

from commentator import templates
from commentator.templates import SIMPLE
from core.ru_names import decline

# Формулировки box-call живут в банке (`core/radio/phrases.py::box.call_*`), а
# не в этом модуле: `templates.render` маршрутизирует STRAT_BOX_CALL_* в
# strategist, тот — в банк. Сверяем маршрут и смысл, а не литерал: иначе тест
# ломается на каждой правке формулировки, ничего при этом не защищая.
_BOX_CALL_CODES = ("STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3")


@pytest.mark.parametrize("code", _BOX_CALL_CODES)
def test_render_strat_box_call_routes_to_the_bank(code):
    from commentator.strategist import strategy_phrase_code
    from core.radio import phrases

    out = templates.render({"event_code": code}, "tv")
    spec = phrases.spec_for(strategy_phrase_code(code.lower().replace("strat_", "")))
    assert out in spec.variants


@pytest.mark.parametrize("code", _BOX_CALL_CODES)
def test_box_call_stays_an_order(code):
    """Эскалация — команда: пилот должен узнать её с первого слога."""
    assert "бокс" in templates.render({"event_code": code}, "tv").lower()


def test_pit_call_notice_has_template_phrases():
    out = templates.render({"event_code": "PIT_CALL_NOTICE"}, "tv")
    assert out in SIMPLE["PIT_CALL_NOTICE"]        # реальная фраза, не фолбэк на код


def test_commentator_pools_have_race_length_variety():
    assert all(len(pool) >= 6 for pool in SIMPLE.values())
    recurring = {
        "DRSE", "DRSD", "PUSH_LAP", "TYRE_CLIFF", "ATTACK_ZONE",
        "DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_TYRE_CRITICAL",
        "DAMAGE_HEAVY", "PIT_EXIT", "PIT_IN", "PIT_OUT",
        "TYRE_WEAR_HIGH",
    }
    for persona, events in templates.PERSONA.items():
        assert all(len(events[code]) >= 5 for code in recurring), persona


@pytest.mark.parametrize("code", ["ATTACK", "BATTLE", "FINAL_LAP"])
def test_commentary_events_do_not_use_engineer_radio_phrases(code, monkeypatch):
    monkeypatch.setattr(
        templates._radio, "race_ai_phrase",
        lambda *_args, **_kwargs: pytest.fail("engineer phrase bank was used"),
    )
    event = {
        "event_code": code,
        "driver": "Леклер",
        "target": "Норрис",
        "race_ai_data": {"advice": "hold_line"},
    }

    out = templates.render(event, "toxic")

    assert out


# --------------------------------------------------------------------------- #
# Phase B (Safety Car/VSC/красный флаг) — SIMPLE + все 3 персоны, {sc_type}
# подставляется render()'ом. См. docs/superpowers/plans/
# 2026-07-19-safety-car-vsc-red-flag.md.
# --------------------------------------------------------------------------- #

_SC_CODES = ("SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING", "SAFETY_CAR_CLEAR")
_ALL_NEW_CODES = _SC_CODES + ("RDFL",)


@pytest.mark.parametrize("code", _ALL_NEW_CODES)
def test_simple_pool_exists_and_nonempty(code):
    assert SIMPLE.get(code)


@pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _ALL_NEW_CODES)
def test_persona_pool_exists_and_nonempty(code, persona):
    assert templates.PERSONA[persona].get(code)


@pytest.mark.parametrize("code", _SC_CODES)
def test_sc_type_placeholder_substituted_no_leftover_braces(code):
    out = templates.render(
        {"event_code": code, "sc_type": "Virtual Safety Car"}, "tv")
    assert "{" not in out and "}" not in out


def test_rdfl_render_no_leftover_braces():
    out = templates.render({"event_code": "RDFL"}, "tv")
    assert "{" not in out and "}" not in out


@pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _ALL_NEW_CODES)
def test_render_all_personas_no_leftover_braces(code, persona):
    out = templates.render(
        {"event_code": code, "sc_type": "Safety car"}, persona)
    assert "{" not in out and "}" not in out


# --------------------------------------------------------------------------- #
# Покрытие банка КЛАССОМ, а не списком (2026-08-25).
#
# Выше лежит `_ALL_NEW_CODES` — четыре кода, вписанные руками под одну фичу
# Safety Car. Такой тест отвечает на вопрос «добавили ли пулы для ЭТОЙ фичи» и
# ничего не знает о следующей: новый `event_code` его не расширяет. Ровно
# поэтому градация контакта (`COLL`/`COLL_LIGHT`/`COLL_HEAVY`, 2026-08-11)
# прошла мимо: её аккуратно провели по planner/policy/situation_dedup/editorial/
# engine и не завели фраз. Отказ вышел молчаливым — `render()` отдаёт
# `event["description"]`, и в эфир ушло голое слово «Столкновение» (заезд
# 08-11, девять раз, приоритетом critical).
#
# Здесь множество кодов ВЫВОДИТСЯ из тех же таблиц, что и в проде, поэтому
# следующий код обязан либо получить фразы, либо быть исключённым явно и с
# причиной.
# --------------------------------------------------------------------------- #

from core import packets as _packets                            # noqa: E402
from commentator import planner as _planner                     # noqa: E402
from core.radio import policy as _policy                        # noqa: E402
from core.strategy_ai.safety_car import derive_safety_car_event  # noqa: E402
from commentator.channel_router import _ALWAYS_COMMENTARY        # noqa: E402

#: Коды, которые до `templates.render()` не доходят, и почему.
_NOT_COMMENTARY_TEMPLATES = {
    # У фонового наблюдения нет события: у него свой вход `render_ambient()`.
    "AMBIENT",
    # Сырой SCAR движок подменяет на SAFETY_CAR_* ДО канала комментатора
    # (`core/engine.py::_handle_race_event`). Исключение не на слово — ниже
    # `test_raw_scar_only_becomes_codes_that_have_phrases` проверяет, что всё,
    # во что SCAR превращается, покрыто этим же набором.
    "SCAR",
}


def _commentary_codes() -> list[str]:
    """Коды, которые обслуживает банк комментатора.

    Один код может звучать на ДВУХ каналах, и это не ошибка: `SAFETY_CAR_*`
    лежит и в `_ENGINEER_CODES` (инженер говорит это пилоту из
    `core/radio/phrases.py`), и в `_ALWAYS_COMMENTARY` (комментатор говорит это
    зрителю из своего банка). Поэтому множество — ОБЪЕДИНЕНИЕ двух ответов:

    * что не забрали банки кокпита (инженер и споттер), и
    * что маршрутизатор явно объявил вещанием.

    Второе слагаемое нужно именно из-за пересечения; первое — потому что
    `route_event` по умолчанию отвечает «комментарий» на всё незнакомое, и
    одного его было бы мало, чтобы отличить решение от умолчания."""
    known = set(_packets.EVENT_DESCRIPTIONS) | set(_planner._BASE_IMPORTANCE)
    not_cockpit = {
        code for code in known
        if code not in _policy._ENGINEER_CODES
        and code not in _policy._SPOTTER_CODES
    }
    codes = (not_cockpit | set(_ALWAYS_COMMENTARY)) - _NOT_COMMENTARY_TEMPLATES
    # `render()` сам уводит эти коды в другие банки первой же строкой — свой
    # пул им не нужен и не должен требоваться.
    codes -= set(templates._RACE_AI_CODES) | set(templates._STRATEGY_AI_CODES)
    return sorted(codes)


#: Описание пакета для синтетических кодов, у которых своего описания нет.
#: `_grade_contact` ПЕРЕпубликует исходное событие (`**pending["event"]`),
#: поэтому обе градации приезжают с описанием сырого `COLL` — и именно это
#: описание утекало в эфир. Подставить сюда пустую строку значило бы проверять
#: удобный случай вместо настоящего.
_INHERITED_DESCRIPTION = {
    "COLL_LIGHT": _packets.EVENT_DESCRIPTIONS.get("COLL"),
    "COLL_HEAVY": _packets.EVENT_DESCRIPTIONS.get("COLL"),
}


def _sample_event(code: str) -> dict:
    """Событие с полным набором полей: тест про наличие фраз, а не про то,
    что бывает, когда данных нет."""
    event = {
        "event_code": code,
        "driver": "Леклер",
        "target": "Норрис",
        "team": "Ferrari",
        "sc_type": "Safety car",
    }
    description = (_INHERITED_DESCRIPTION.get(code)
                   or _packets.EVENT_DESCRIPTIONS.get(code))
    if description:
        event["description"] = description
    return event


@pytest.mark.parametrize("persona", ["tv", "hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _commentary_codes())
def test_every_commentary_code_has_a_phrase(code, persona):
    """Код без фраз не падает — он ГОВОРИТ СОБОЙ, и это слышно в эфире."""
    out = templates.render(_sample_event(code), persona)

    # Пустая реплика не падает и не видна в тестах — она просто НЕ ЗВУЧИТ.
    # Молчание вместо фразы здесь такой же отказ, как код вслух.
    assert out.strip(), f"{code}/{persona}: реплика пустая"
    assert out != code, f"{code}/{persona}: в эфир уходит сам код события"
    description = _sample_event(code).get("description")
    assert not (description and out == description), (
        f"{code}/{persona}: в эфир уходит сырое описание пакета "
        f"({description!r}) вместо реплики комментатора")


@pytest.mark.parametrize("persona", ["tv", "hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _commentary_codes())
def test_every_commentary_code_renders_without_leftover_braces(code, persona):
    """`render()` на неизвестном ключе возвращает шаблон КАК ЕСТЬ — со
    скобками. Диктор при этом честно произносит «фигурная скобка драйвер»."""
    out = templates.render(_sample_event(code), persona)

    assert "{" not in out and "}" not in out, f"{code}/{persona}: {out!r}"


def test_raw_scar_only_becomes_codes_that_have_phrases():
    """Оправдание исключения SCAR из набора выше — проверкой, а не словом."""
    covered = set(_commentary_codes())
    derived = [
        derive_safety_car_event(sc_type, reason)
        for sc_type in range(4) for reason in range(4)
    ]
    codes = {d["event_code"] for d in derived if d}

    assert codes, "derive_safety_car_event не вернул ни одного события"
    assert codes <= covered, f"без фраз останутся: {sorted(codes - covered)}"


# --------------------------------------------------------------------------- #
# Неразрешённое имя не должно попадать в эфир (2026-08-25).
#
# `race_state.driver()` отвечает «гонщик», когда участник не сопоставлен, а
# `resolve_driver_name` тем же словом отвечает, что и вторая попытка не удалась.
# Дальше это слово шло прямо в шаблон: в заезде 08-19 победа гонки прозвучала
# как «Победа! гонщик первым пересекает финишную черту!», в 08-11 —
# «гонщик выезжает из боксов!». Плейсхолдер служебного слоя оказался словом,
# которое диктор произносит вслух.
# --------------------------------------------------------------------------- #

#: Заглушки во ВСЕХ падежах, которыми банк подставляет имя. Сравнение идёт по
#: словам, а не подстрокой: «соперники не разъезжаются» — нормальная русская
#: фраза, и она содержит «соперник». Подстрочная проверка запретила бы её и
#: заставила бы портить текст ради теста.
_GENERIC_FORMS = frozenset(
    decline(word, case)
    for word in ("гонщик", "пилот", "соперник")
    for case in ("nom", "gen", "dat", "acc")
)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.lower()))


def _name_codes() -> list[str]:
    """Коды, чьи фразы вообще произносят имя — только им нужен вариант без него.

    Берётся ВЕСЬ банк, а не подмножество канала комментатора. Первая версия
    этого теста считала по `_commentary_codes()` и пропустила `PIT_EXIT` —
    то есть ровно одну из двух утечек, ради которых всё и делалось
    (`'гонщик выезжает из боксов!'`, заезд 08-11). Код может звучать не на том
    канале, на котором его ищут, но пул он берёт отсюда.

    Множество ВЫВОДИТСЯ из банка, а не переписывается: фраза с `{driver}`,
    добавленная к любому коду завтра, попадёт сюда сама."""
    return sorted(templates._CODES_WITH_NAMES)


@pytest.mark.parametrize("persona", ["tv", "hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _name_codes())
def test_unresolved_name_never_reaches_the_air(code, persona):
    event = _sample_event(code)
    event["driver"] = "гонщик"
    event["target"] = "соперник"

    out = templates.render(event, persona)

    leaked = _words(out) & _GENERIC_FORMS
    assert not leaked, (
        f"{code}/{persona}: служебный плейсхолдер в эфире "
        f"({sorted(leaked)}) — {out!r}")
    assert out.strip(), f"{code}/{persona}: реплика пустая"
    assert "{" not in out and "}" not in out, f"{code}/{persona}: {out!r}"


@pytest.mark.parametrize("persona", ["tv", "hype", "calm", "toxic"])
@pytest.mark.parametrize("code", _name_codes())
def test_known_name_does_not_trigger_the_no_name_pool(code, persona):
    """Обратная сторона: подмена обязана срабатывать ТОЛЬКО на неразрешённом
    имени. Иначе она молча отнимет информацию у нормальной гонки.

    Проверяется именно НЕсрабатывание подмены, а не «в реплике есть фамилия»:
    пул бывает СМЕШАННЫМ. У `TYRE_CLIFF` часть фраз обходится без имени с
    самого начала («Клифф шин. Пит-стоп неизбежен.»), и требование фамилии
    объявило бы штатную фразу ошибкой."""
    out = templates.render(_sample_event(code), persona)

    assert out not in templates.NO_NAME.get(code, ()), (
        f"{code}/{persona}: имя известно, но сработал вариант без имени — {out!r}")
