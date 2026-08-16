"""Проводка промера трассы: кормится ли он кадром и сохраняется ли на круге.

Отдельный файл от `test_track_survey.py` по тому же принципу, что и у коуча:
там проверяется ЧИСТАЯ функция на синтетическом круге, здесь — что она вообще
подключена. Самые дорогие баги этого проекта живут между корректным ядром и
тем, что реально уезжает наружу.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    monkeypatch.setattr(eng_mod.config, "DATA_DIR", str(tmp_path))
    return F1Engine({})


class _FakeTrack:
    """Минимальный TrackManager: промеру от него нужны только имя и длина."""
    track_name = "Suzuka"
    length_m = 5000.0

    def corners(self):
        return []

    def resolve(self, *a, **k):
        return None


def _survey_dir(tmp_path: Path) -> Path:
    return tmp_path / "track_survey"


def _lap(engine, *, corner_at=0.3, samples=1500):
    """Проехать круг мимо `observe()` — так же, как это делает `_coach_tick`."""
    for i in range(samples):
        fraction = i / samples
        speed, yaw = 300.0, 0.0
        if abs(fraction - corner_at) <= 0.02:
            depth = 1.0 - abs(fraction - corner_at) / 0.02
            speed = 300.0 - 200.0 * depth
            yaw = 30.0 * depth / max(1.0, speed / 3.6)
        engine.track_survey.observe(
            lap_distance_m=fraction * _FakeTrack.length_m,
            length_m=_FakeTrack.length_m, speed_kmh=speed, yaw_rate=yaw)


def test_a_clean_lap_writes_a_survey_file(engine, tmp_path):
    engine._track_manager = _FakeTrack()
    _lap(engine)

    engine._save_track_survey(lap=5, lap_was_pit=False)

    path = _survey_dir(tmp_path) / "suzuka.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["track_name"] == "Suzuka"
    assert payload["lap"] == 5
    assert len(payload["corners"]) == 1
    assert payload["corners"][0]["type"] == "slow"


def test_a_pit_lap_is_never_measured(engine, tmp_path):
    """На пит-лейне своя траектория — промер по ней описывает не трассу."""
    engine._track_manager = _FakeTrack()
    _lap(engine)

    engine._save_track_survey(lap=5, lap_was_pit=True)

    assert not (_survey_dir(tmp_path) / "suzuka.json").exists()
    # Кадры при этом выброшены, а не перенесены на следующий круг.
    assert engine.track_survey.sample_count == 0


def test_only_a_better_lap_overwrites_the_survey(engine, tmp_path):
    """Пишется ЛУЧШИЙ круг сессии: один смазанный не должен затирать удачный."""
    engine._track_manager = _FakeTrack()
    _lap(engine)                       # один поворот
    engine._save_track_survey(lap=1, lap_was_pit=False)
    first = json.loads((_survey_dir(tmp_path) / "suzuka.json").read_text("utf-8"))

    # Круг хуже: тот же поворот, но короче — покрытие меньше.
    for i in range(1500):
        fraction = i / 1500
        speed, yaw = 300.0, 0.0
        if abs(fraction - 0.3) <= 0.005:
            depth = 1.0 - abs(fraction - 0.3) / 0.005
            speed = 300.0 - 200.0 * depth
            yaw = 30.0 * depth / max(1.0, speed / 3.6)
        engine.track_survey.observe(lap_distance_m=fraction * 5000.0,
                                    length_m=5000.0, speed_kmh=speed, yaw_rate=yaw)
    engine._save_track_survey(lap=2, lap_was_pit=False)

    kept = json.loads((_survey_dir(tmp_path) / "suzuka.json").read_text("utf-8"))
    assert kept["lap"] == first["lap"] == 1


def test_a_new_track_starts_the_survey_over(engine, tmp_path):
    """Планка лучшего покрытия относится к КОНКРЕТНОЙ трассе. Без сброса первый
    круг на новой трассе не сохранился бы вовсе, если на прошлой было лучше."""
    engine._track_manager = _FakeTrack()
    _lap(engine)
    engine._save_track_survey(lap=1, lap_was_pit=False)
    assert engine._survey_best_coverage > 0.0

    # То, что движок делает на смене трассы.
    engine.track_survey.reset()
    engine._survey_best_coverage = 0.0

    class _Other(_FakeTrack):
        track_name = "Monza"

    engine._track_manager = _Other()
    _lap(engine, corner_at=0.6)
    engine._save_track_survey(lap=1, lap_was_pit=False)

    assert (_survey_dir(tmp_path) / "monza.json").exists()


def test_a_broken_survey_never_breaks_the_lap(engine, tmp_path, monkeypatch):
    """Промер обязан быть тише того, что измеряет: исключение здесь не имеет
    права ронять завершение круга."""
    engine._track_manager = _FakeTrack()
    _lap(engine)
    monkeypatch.setattr(engine.track_survey, "finish_lap",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    engine._save_track_survey(lap=5, lap_was_pit=False)   # не должно бросить

    assert not (_survey_dir(tmp_path) / "suzuka.json").exists()


def test_without_a_track_manager_nothing_is_written(engine, tmp_path):
    engine._track_manager = None
    _lap(engine)

    engine._save_track_survey(lap=5, lap_was_pit=False)

    assert not _survey_dir(tmp_path).exists()
