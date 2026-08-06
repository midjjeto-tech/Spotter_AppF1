"""core/overlay_layout.py — per-widget HUD positions.

Kept out of settings.json on purpose: six overlay processes write these
concurrently, and settings.save() rewrites the whole document.
"""
import json
from pathlib import Path

import core.overlay_layout as overlay_layout


def _use_tmp_dir(monkeypatch, tmp_path) -> Path:
    target = tmp_path / "overlay_layout"
    monkeypatch.setattr(overlay_layout, "_DIR", target)
    return target


def test_save_then_load_round_trips_the_offset(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)

    overlay_layout.save("lap", 400, 350)

    assert overlay_layout.load("lap") == (400, 350)


def test_load_returns_none_when_never_saved(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)

    assert overlay_layout.load("tower") is None


def test_load_survives_corrupt_file(monkeypatch, tmp_path):
    directory = _use_tmp_dir(monkeypatch, tmp_path)
    directory.mkdir(parents=True)
    (directory / "radar.json").write_text("{not json", encoding="utf-8")

    # Fail-safe like the settings store: fall back to the default position.
    assert overlay_layout.load("radar") is None


def test_each_widget_owns_its_own_file_so_processes_cannot_clobber(
        monkeypatch, tmp_path):
    directory = _use_tmp_dir(monkeypatch, tmp_path)

    overlay_layout.save("lap", 10, 20)
    overlay_layout.save("radio", 30, 40)

    assert overlay_layout.load("lap") == (10, 20)
    assert overlay_layout.load("radio") == (30, 40)
    assert json.loads((directory / "lap.json").read_text(encoding="utf-8")) == {
        "dx": 10, "dy": 20}


def test_save_leaves_no_temp_files_behind(monkeypatch, tmp_path):
    directory = _use_tmp_dir(monkeypatch, tmp_path)

    overlay_layout.save("car", 1, 2)

    assert [p.name for p in directory.iterdir()] == ["car.json"]


def test_save_never_raises_when_the_directory_is_unusable(monkeypatch, tmp_path):
    # A file where the directory should be: mkdir fails, save must stay silent.
    blocked = tmp_path / "blocked"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setattr(overlay_layout, "_DIR", blocked)

    overlay_layout.save("lap", 1, 1)  # must not raise

    assert overlay_layout.load("lap") is None


# ── Масштаб ─────────────────────────────────────────────────────────────────

def test_scale_defaults_to_one_and_is_not_written_when_default(
        monkeypatch, tmp_path):
    directory = _use_tmp_dir(monkeypatch, tmp_path)

    overlay_layout.save("lap", 10, 20)

    assert overlay_layout.load_scale("lap") == 1.0
    # Дефолт не занимает места в документе: старые файлы неотличимы от новых.
    assert "scale" not in json.loads(
        (directory / "lap.json").read_text(encoding="utf-8"))


def test_scale_and_offset_do_not_clobber_each_other(monkeypatch, tmp_path):
    # Позицию пишет процесс виджета, масштаб — главное окно. Слепая перезапись
    # молча теряла бы то, чем владеет другая сторона.
    _use_tmp_dir(monkeypatch, tmp_path)

    overlay_layout.save("tower", 100, 200)
    overlay_layout.save_scale("tower", 1.4)

    assert overlay_layout.load("tower") == (100, 200)
    assert overlay_layout.load_scale("tower") == 1.4

    overlay_layout.save("tower", 111, 222)

    assert overlay_layout.load_scale("tower") == 1.4


def test_scale_is_clamped_and_junk_degrades_to_default(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)

    overlay_layout.save_scale("radar", 99)
    assert overlay_layout.load_scale("radar") == overlay_layout.MAX_SCALE

    overlay_layout.save_scale("radar", 0.01)
    assert overlay_layout.load_scale("radar") == overlay_layout.MIN_SCALE

    overlay_layout.save_scale("radar", "не число")
    assert overlay_layout.load_scale("radar") == overlay_layout.DEFAULT_SCALE


def test_revision_changes_when_the_document_is_rewritten(monkeypatch, tmp_path):
    # По этой отметке процесс виджета замечает чужую правку без разбора JSON.
    _use_tmp_dir(monkeypatch, tmp_path)

    assert overlay_layout.revision("pu") == 0.0

    overlay_layout.save("pu", 1, 2)

    assert overlay_layout.revision("pu") > 0.0


# ── Пресеты ─────────────────────────────────────────────────────────────────

WIDGETS = ("lap", "tower", "radar")


def test_preset_round_trips_positions_and_scales(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    overlay_layout.save("lap", 10, 20)
    overlay_layout.save_scale("tower", 1.5)

    assert overlay_layout.save_preset("Гонка", WIDGETS)

    # Всё переставили — пресет обязан вернуть исходное.
    overlay_layout.save("lap", 900, 900)
    overlay_layout.save_scale("tower", 0.7)

    assert overlay_layout.apply_preset("Гонка")
    assert overlay_layout.load("lap") == (10, 20)
    assert overlay_layout.load_scale("tower") == 1.5


def test_applying_a_preset_leaves_untouched_widgets_at_their_default(
        monkeypatch, tmp_path):
    # Виджет, который не двигали на момент сохранения, не должен получить (0,0):
    # это утащило бы его в угол экрана вместо штатного места.
    _use_tmp_dir(monkeypatch, tmp_path)
    overlay_layout.save_scale("radar", 1.2)
    overlay_layout.save_preset("Квала", WIDGETS)

    assert overlay_layout.apply_preset("Квала")
    assert overlay_layout.load("radar") is None
    assert overlay_layout.load_scale("radar") == 1.2


def test_unknown_preset_is_reported_not_applied(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)

    assert overlay_layout.apply_preset("нет такого") is False
    assert overlay_layout.delete_preset("нет такого") is False


def test_blank_preset_name_is_rejected(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)

    assert overlay_layout.save_preset("   ", WIDGETS) is False
    assert overlay_layout.presets_state(WIDGETS)["names"] == []


def test_deleting_the_active_preset_clears_the_active_marker(
        monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    overlay_layout.save_preset("Стрим", WIDGETS)

    assert overlay_layout.presets_state(WIDGETS)["active"] == "Стрим"

    overlay_layout.delete_preset("Стрим")

    state = overlay_layout.presets_state(WIDGETS)
    assert state["active"] is None
    assert state["names"] == []


def test_presets_survive_a_corrupt_presets_file(monkeypatch, tmp_path):
    directory = _use_tmp_dir(monkeypatch, tmp_path)
    directory.mkdir(parents=True)
    (directory / "presets.json").write_text("{broken", encoding="utf-8")

    # Fail-safe: битый файл читается как «пресетов нет», а не как исключение.
    assert overlay_layout.presets_state(WIDGETS)["names"] == []
    assert overlay_layout.save_preset("Гонка", WIDGETS)
    assert overlay_layout.presets_state(WIDGETS)["names"] == ["Гонка"]


def test_reset_drops_saved_geometry(monkeypatch, tmp_path):
    _use_tmp_dir(monkeypatch, tmp_path)
    overlay_layout.save("lap", 5, 6)
    overlay_layout.save_scale("lap", 1.3)

    overlay_layout.reset(WIDGETS)

    assert overlay_layout.load("lap") is None
    assert overlay_layout.load_scale("lap") == 1.0
