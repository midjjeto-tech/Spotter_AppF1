"""Как поворот называется В РЕЧИ (core/radio/corner_words.py).

Почему номер, а не имя, — измеримо: из 325 поворотов 24 трасс имя есть у 109, и
все 109 латиницей. Тест на это стоит ниже и ходит в реальный справочник трасс:
если однажды имена появятся кириллицей, он об этом скажет.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.radio.corner_words import MAX_CORNER, ordinal_prepositional


@pytest.mark.parametrize("number,expected", [
    (1, "первом"), (2, "втором"), (3, "третьем"), (4, "четвёртом"),
    (7, "седьмом"), (10, "десятом"), (11, "одиннадцатом"),
    (14, "четырнадцатом"), (16, "шестнадцатом"), (20, "двадцатом"),
    (21, "двадцать первом"), (25, "двадцать пятом"), (30, "тридцатом"),
    (33, "тридцать третьем"),
])
def test_ordinal_is_in_the_prepositional_case(number, expected):
    """Падеж один и тот же для всех: банк ставит токен только после «в»."""
    assert ordinal_prepositional(number) == expected


@pytest.mark.parametrize("bad", [None, 0, -3, MAX_CORNER + 1, "семь", 2.5, True])
def test_unknown_corner_has_no_word(bad):
    """None, а не заглушка: подсказка без места обязана НЕ прозвучать вовсе.
    Заглушка вроде «в этом повороте» вернула бы ровно ту проблему, ради которой
    номер и появился."""
    assert ordinal_prepositional(bad) is None


def test_every_corner_of_every_track_can_be_named():
    """Главное свойство: номер есть у 100% поворотов справочника, поэтому коуч
    не онемеет ни на одной трассе. Имя такой гарантии не даёт — на двух третях
    поворотов его просто нет."""
    tracks = sorted(Path("tracks").glob("*.json"))
    assert tracks, "справочник трасс не найден — тест бессмыслен"

    unnamed = []
    for path in tracks:
        corners = json.loads(path.read_text(encoding="utf-8")).get("corners") or []
        for corner in corners:
            if ordinal_prepositional(corner.get("id")) is None:
                unnamed.append((path.name, corner.get("id")))
    assert not unnamed, f"поворотов без произносимого номера: {unnamed[:5]}"


def test_track_corner_names_are_still_unusable_for_speech():
    """Сторож решения. Имена поворотов в справочнике — латиница («Tamburello 1»,
    «La Source»), а русский синтез читает её как набор букв: тот же класс, что
    чинили для фамилий пилотов (core/transliterate.py). Если однажды справочник
    получит кириллические имена, этот тест упадёт — и решение «говорим номер»
    можно будет пересмотреть осознанно, а не забыть про него навсегда."""
    cyrillic = []
    for path in sorted(Path("tracks").glob("*.json")):
        corners = json.loads(path.read_text(encoding="utf-8")).get("corners") or []
        for corner in corners:
            name = corner.get("name") or ""
            if any("а" <= ch.lower() <= "я" for ch in name):
                cyrillic.append((path.name, name))
    assert not cyrillic, (
        "в справочнике появились кириллические имена поворотов — можно "
        f"пересмотреть выбор в пользу имён: {cyrillic[:5]}")
