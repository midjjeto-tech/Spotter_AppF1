"""Persisted geometry for the per-widget in-game HUD windows.

Deliberately NOT part of ``core/settings.py``: every HUD widget lives in its own
process (see ``core/overlay_process.py``), and ``settings.save()`` rewrites the
whole settings document. Six overlay processes writing that one file would race
and could silently drop each other's position — or a real user setting such as
the TTS version. Each widget therefore owns one tiny file:
``DATA_DIR/overlay_layout/<widget_id>.json``.

Offsets are stored RELATIVE to the game's client-area top-left, so a HUD keeps
its spot when the game window is moved, and degrades sanely when the game runs
at a different resolution (the controller clamps into the client area).

Size is stored as a SCALE, not as width/height. The widget layouts are fitted to
the exact pixel budget of their native window (`HUD_WIDGETS`), so free-form
width/height would mean teaching all eight of them to reflow; a multiplier keeps
every proportion the designer checked and only changes how big the whole thing
is. `scale` is omitted from the file entirely when it equals 1.0 — the common
case stays a two-key document.

Named presets ("Гонка", "Квала", "Стрим") live in ONE extra file,
``presets.json``, written only by the main process: applying a preset rewrites
the per-widget files, and each widget process notices via mtime on its next
sync tick. A widget saving its own drag at the same moment as a preset apply is
last-write-wins and self-corrects on the following tick — the alternative,
locking eight processes against each other, would cost far more than a HUD
position that lands one tick late.

Fail-safe like the settings store: a missing or corrupt file simply means "use
the built-in default", never an exception.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_DIR = Path(config.DATA_DIR) / "overlay_layout"
_PRESETS_NAME = "presets.json"

#: Границы масштаба виджета. Ниже 0.6 подписи в 8 px перестают читаться на
#: скорости, выше 2.0 виджет закрывает трассу — а закрывать трассу оверлей,
#: который существует ради трассы, не должен.
MIN_SCALE = 0.6
MAX_SCALE = 2.0
DEFAULT_SCALE = 1.0


def _path(widget_id: str) -> Path:
    return _DIR / f"{widget_id}.json"


def clamp_scale(value: object) -> float:
    """Coerce anything into a usable scale; junk degrades to the default."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SCALE
    if number != number:  # NaN — float("nan") == float("nan") is False
        return DEFAULT_SCALE
    return max(MIN_SCALE, min(MAX_SCALE, number))


def _read(widget_id: str) -> dict:
    """One widget's raw document; absent or corrupt reads as empty."""
    try:
        raw = json.loads(_path(widget_id).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - absent/corrupt means "use the default"
        return {}


def _write_json(path: Path, payload: dict) -> None:
    """Atomically replace one document. Raises; callers decide how to degrade."""
    _DIR.mkdir(parents=True, exist_ok=True)
    # The temp file must live in the SAME directory as the target: on Windows
    # os.replace cannot move a file across drives, and this project has hit
    # exactly that before (system TEMP on C: vs the project on G:).
    handle, tmp_path = tempfile.mkstemp(dir=str(_DIR), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _put(widget_id: str, **changes: object) -> None:
    """Merge changes into one widget's document, never dropping the other keys.

    Merging matters: position and scale are written by different callers (the
    widget process on drag, the main process on resize or preset apply), and a
    blind overwrite would silently reset whichever value the other one owns.
    """
    payload = _read(widget_id)
    payload.update(changes)
    # Дефолтный масштаб не пишется вовсе: типичный документ остаётся из двух
    # ключей, и старые файлы без `scale` ничем не отличаются от новых.
    if clamp_scale(payload.get("scale", DEFAULT_SCALE)) == DEFAULT_SCALE:
        payload.pop("scale", None)
    # То же и с «виджет включён»: в файле остаётся только выключение.
    if payload.get("enabled", True) is not False:
        payload.pop("enabled", None)
    try:
        _write_json(_path(widget_id), payload)
    except Exception:  # noqa: BLE001 - a lost position must not break the HUD
        _log.warning("overlay_layout write failed for %s", widget_id, exc_info=True)


def load(widget_id: str) -> tuple[int, int] | None:
    """Return the saved (dx, dy) offset for one widget, or None if unset."""
    raw = _read(widget_id)
    try:
        return int(raw["dx"]), int(raw["dy"])
    except Exception:  # noqa: BLE001 - absent/corrupt means "use the default"
        return None


def load_scale(widget_id: str) -> float:
    """Return the saved size multiplier, 1.0 when unset."""
    return clamp_scale(_read(widget_id).get("scale", DEFAULT_SCALE))


def load_enabled(widget_id: str) -> bool:
    """Нужен ли пилоту этот виджет. По умолчанию — да.

    Хранится здесь, а не в настройках, по той же причине, что позиция и размер:
    документ виджета мержится, и восемь процессов не затирают друг друга. Запись
    появляется в файле только когда виджет ВЫКЛЮЧИЛИ — типичный документ
    остаётся коротким, а старые файлы неотличимы от новых.
    """
    return _read(widget_id).get("enabled", True) is not False


def revision(widget_id: str) -> float:
    """Mtime of one widget's document; 0.0 when it does not exist.

    The widget processes poll this instead of re-parsing the file every tick:
    a preset applied from the main window has to reach eight separate processes,
    and one `stat` per 250 ms is the cheapest way to notice it.
    """
    try:
        return _path(widget_id).stat().st_mtime
    except OSError:
        return 0.0


def save(widget_id: str, dx: int, dy: int) -> None:
    """Persist one widget's offset. I/O problems are logged, never raised."""
    _put(widget_id, dx=int(dx), dy=int(dy))


def save_scale(widget_id: str, scale: object) -> None:
    """Persist one widget's size multiplier, leaving its position alone."""
    _put(widget_id, scale=clamp_scale(scale))


def save_enabled(widget_id: str, enabled: object) -> None:
    """Включить или выключить виджет, не трогая его позицию и размер."""
    _put(widget_id, enabled=bool(enabled))


def reset(widget_ids: Iterable[str]) -> None:
    """Drop saved geometry so the built-in defaults apply again."""
    for widget_id in widget_ids:
        try:
            _path(widget_id).unlink(missing_ok=True)
        except OSError:  # noqa: PERF203 - one unusable file must not stop the rest
            _log.warning("overlay_layout reset failed for %s", widget_id, exc_info=True)


# ── Именованные пресеты ─────────────────────────────────────────────────────

def _presets_path() -> Path:
    return _DIR / _PRESETS_NAME


def _read_presets() -> dict:
    try:
        raw = json.loads(_presets_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent/corrupt means "no presets yet"
        return {"active": None, "presets": {}}
    if not isinstance(raw, dict):
        return {"active": None, "presets": {}}
    presets = raw.get("presets")
    return {
        "active": raw.get("active") if isinstance(raw.get("active"), str) else None,
        "presets": presets if isinstance(presets, dict) else {},
    }


def _write_presets(document: dict) -> None:
    try:
        _write_json(_presets_path(), document)
    except Exception:  # noqa: BLE001 - a lost preset must not break the HUD
        _log.warning("overlay_layout presets write failed", exc_info=True)


def snapshot(widget_ids: Iterable[str]) -> dict:
    """Current geometry of every widget, in the shape a preset stores."""
    result: dict[str, dict] = {}
    for widget_id in widget_ids:
        offset = load(widget_id)
        entry: dict[str, float | int | bool] = {
            "scale": load_scale(widget_id),
            "enabled": load_enabled(widget_id),
        }
        if offset is not None:
            entry["dx"], entry["dy"] = offset
        result[widget_id] = entry
    return result


def presets_state(widget_ids: Iterable[str]) -> dict:
    """Everything the UI needs: names, which one is active, live geometry."""
    document = _read_presets()
    return {
        "active": document["active"],
        "names": sorted(document["presets"]),
        "widgets": snapshot(widget_ids),
        "min_scale": MIN_SCALE,
        "max_scale": MAX_SCALE,
    }


def save_preset(name: str, widget_ids: Iterable[str]) -> bool:
    """Store the current arrangement under `name`. Empty names are rejected."""
    label = str(name).strip()
    if not label:
        return False
    document = _read_presets()
    document["presets"][label] = snapshot(widget_ids)
    document["active"] = label
    _write_presets(document)
    return True


def apply_preset(name: str) -> bool:
    """Push a stored arrangement back onto the widgets. False when unknown."""
    document = _read_presets()
    stored = document["presets"].get(str(name))
    if not isinstance(stored, dict):
        return False
    for widget_id, entry in stored.items():
        if not isinstance(entry, dict):
            continue
        changes: dict[str, object] = {
            "scale": clamp_scale(entry.get("scale")),
            # Пресет «Стрим» может выключать башню, а «Гонка» — возвращать.
            # Отсутствие ключа у пресетов, сохранённых до этой возможности,
            # читается как «включён» — то есть как было.
            "enabled": entry.get("enabled", True) is not False,
        }
        try:
            changes["dx"] = int(entry["dx"])
            changes["dy"] = int(entry["dy"])
        except (KeyError, TypeError, ValueError):
            # Пресет сохранён до того, как виджет двигали: позиция остаётся
            # дефолтной, и затирать её нулями было бы хуже, чем не трогать.
            pass
        _put(widget_id, **changes)
    document["active"] = str(name)
    _write_presets(document)
    return True


def delete_preset(name: str) -> bool:
    """Forget a stored arrangement. False when there was nothing to forget."""
    document = _read_presets()
    if str(name) not in document["presets"]:
        return False
    document["presets"].pop(str(name))
    if document["active"] == str(name):
        document["active"] = None
    _write_presets(document)
    return True
