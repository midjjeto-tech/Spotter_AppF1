"""Разные срабатывания одного кода обязаны звучать по-разному.

Живой заезд 2026-08-09: инженер 21 раз подряд сказал «Чисто сделано. Дальше по
плану.» — при шести написанных вариантах похвалы за обгон. Тем же заездом
«Интервал вырос, DRS не будет.» прозвучало пять раз, слово в слово.

Причина не в банке и не в анти-повторе, а в КЛЮЧЕ выбора варианта
(`F1Engine._phrase_selector`). Он берёт `situations.dedupe_key`, а тот по своему
контракту возвращает None для «самостоятельных новостей» — похвалы, рекорда,
DRS, смены лидера. На None селектор вырождался в `{session_id}:{event_code}`,
то есть в КОНСТАНТУ на весь заезд: crc32 от неё даёт один и тот же индекс, и
пул из шести строк схлопывается в одну. Анти-повтор (`core/radio/variety.py`)
помочь не мог — он закрепляет решение за ключом, а ключ был один.

Тесты ниже стоят на проводке, а не на чистой функции: `variety.index_for` сам
по себе всегда был исправен, и юнит-тесты банка проходили, пока пилот слушал
одну строку весь заезд.

Второй тест здесь же стережёт свойство, которое чинить нельзя: у реплики С
ситуацией повторная телеметрия обязана давать ТУ ЖЕ строку, иначе она
перепишет уже произнесённую.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import variety


PLAYER = 3
RIVALS = (7, 8, 11, 14, 16, 19)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"engineer_chatter_enabled": True})
    e._player_car_index = PLAYER
    e._session_type = "race"
    variety.reset()
    yield e
    variety.reset()


def _phrases(engine, code: str) -> list[str]:
    out = []
    while not engine._commentary_events.empty():
        event = engine._commentary_events.get_nowait()
        if event.get("event_code") == code:
            out.append(event.get("phrase", ""))
    return out


def test_repeated_overtakes_do_not_collapse_into_one_phrase(engine):
    """Шесть обгонов — не шесть копий одной строки.

    Порог намеренно мягкий (≥4 из 6): закрепление за ситуацией и анти-повтор
    оставляют выбору свободу, и требовать шесть различных строк значило бы
    зафиксировать конкретный алгоритм. Провал бага, который это ловит, даёт
    ровно одну уникальную строку — от порога он не зависит.
    """
    for rival in RIVALS:
        engine._handle_race_event({
            "event_code": "OVTK", "overtaking_idx": PLAYER,
            "being_overtaken_idx": rival,
        })
    said = _phrases(engine, "PRAISE_OVERTAKE")
    assert len(said) == len(RIVALS), said
    assert len(set(said)) >= 4, said


def test_repeated_fastest_laps_do_not_collapse_into_one_phrase(engine):
    for _ in range(6):
        engine._handle_race_event({"event_code": "FTLP", "vehicle_idx": PLAYER})
    said = _phrases(engine, "PRAISE_FASTEST_LAP")
    assert len(said) == 6, said
    assert len(set(said)) >= 4, said


def test_repeated_drs_advice_does_not_collapse_into_one_phrase(engine, monkeypatch):
    """Тот же баг на другом коде — в живом логе он дал пять одинаковых
    «Интервал вырос, DRS не будет.» подряд."""
    from core.strategy_ai import drs_advisory as _drs

    monkeypatch.setattr(engine._race_engineer, "drs_advisory",
                        lambda *a, **kw: _drs.CODE_OUT_OF_RANGE)
    for _ in range(6):
        engine._drs_advisory_tick()
    said = _phrases(engine, "DRS_PROXIMITY_EXIT")
    assert len(said) == 6, said
    assert len(set(said)) >= 4, said


def test_a_situation_backed_line_keeps_its_wording(engine):
    """Инвариант, который фикс ломать не имеет права.

    У кода С ситуацией (споттер знает соседа) ключ приходит из `dedupe_key`, и
    повторная телеметрия по той же ситуации обязана дать ту же строку. Иначе
    второй пакет перепишет реплику, которую пилот уже слышит.
    """
    draft = {"event_code": "SPOTTER_CAR_LEFT", "neighbour_idx": 7}
    keys = {engine._phrase_selector(dict(draft)) for _ in range(5)}
    assert len(keys) == 1, keys


def test_selector_distinguishes_utterances_without_a_situation(engine):
    """Прямая проверка корня: у «самостоятельной новости» ситуации нет, значит
    закреплять нечего — каждое высказывание должно получить свой ключ."""
    keys = [engine._phrase_selector({"event_code": "PRAISE_OVERTAKE"})
            for _ in range(5)]
    assert len(set(keys)) == 5, keys
