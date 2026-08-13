"""Аудит полноты карт трасс (scripts/audit_tracks.py).

Смысл теста не в цифрах покрытия — они меняются вместе с картами. Смысл в том,
что аудит обязан ПРОЙТИ по всем трассам и заметить сломанную: если файл трассы
перестал загружаться или остался без поворотов, коуч на ней молча теряет
привязку ошибок, и снаружи это выглядит как «коуч ничего не понял».
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "audit_tracks",
    Path(__file__).resolve().parent.parent / "scripts" / "audit_tracks.py")
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


@pytest.fixture(scope="module")
def rows():
    return audit._rows()


def test_every_track_file_loads(rows):
    broken = [r["track"] for r in rows if r.get("error")]
    assert broken == []


def test_every_track_has_corners(rows):
    empty = [r["track"] for r in rows if not r.get("error") and not r["corners"]]
    assert empty == []


def test_coverage_is_a_fraction(rows):
    for row in rows:
        if row.get("error"):
            continue
        assert 0.0 <= row["attributed"] <= 1.0
        assert 0.0 <= row["biggest_gap"] <= 1.0


def test_metre_based_braking_zone_attributes_at_least_as_much(rows):
    """Зона в метрах не должна привязывать МЕНЬШЕ, чем прежняя доля круга.

    Смысл правки был именно в этом: на коротких трассах фиксированные 1,8%
    круга давали слишком узкое окно торможения.
    """
    for row in rows:
        if row.get("error"):
            continue
        assert row["attributed"] >= row["legacy"], row["track"]


def test_short_tracks_gained_the_most():
    """Проверка направления эффекта, а не конкретных чисел: Монако (3,3 км)
    от перевода в метры выигрывает заметно больше, чем Спа (7 км)."""
    by_track = {r["track"]: r for r in audit._rows() if not r.get("error")}
    monaco = by_track["monaco"]["attributed"] - by_track["monaco"]["legacy"]
    spa = by_track["spa"]["attributed"] - by_track["spa"]["legacy"]
    assert monaco > spa
