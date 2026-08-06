"""One-way bridge from the Spotter race result to F1 Reality season mode.

The Spotter already owns F1's UDP port, so the mod deliberately does not start
a competing listener.  At the official final-classification packet it writes a
small JSON inbox item and asks the mod to prepare the next round.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


_log = logging.getLogger(__name__)
_ENV_MOD_DIR = "F1_REALITY_MOD_DIR"
_DEFAULT_MOD_DIR = Path(r"G:\F125 mods\F1 25 - 2026 Reality R10")


def locate_mod_dir() -> Path | None:
    configured = os.environ.get(_ENV_MOD_DIR)
    candidates = [Path(configured)] if configured else [_DEFAULT_MOD_DIR]
    for candidate in candidates:
        if (candidate / "mod.py").is_file():
            return candidate.resolve()
    return None


def auto_mode_enabled(mod_dir: Path) -> bool:
    path = mod_dir / "auto_state.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            return bool(json.load(handle).get("enabled"))
    except (OSError, ValueError, TypeError):
        return False


def build_result_payload(
    classification: list[dict[str, Any]], *, track_id: int, game_year: int
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "track_id": track_id,
        "game_year": game_year,
        "classification": classification,
    }


def _write_inbox(mod_dir: Path, payload: dict[str, Any]) -> Path:
    inbox = mod_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="result-", suffix=".json.tmp", dir=inbox)
    temp = Path(temp_name)
    target = temp.with_suffix("")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp, target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return target


def submit_final_classification(
    classification: list[dict[str, Any]], *, track_id: int, game_year: int
) -> bool:
    """Persist one race result and synchronously launch the next-round patch.

    Called from a Spotter task thread, never from the UDP receive loop.
    Returns False when auto mode is not installed/enabled or launching failed.
    """
    mod_dir = locate_mod_dir()
    if mod_dir is None or not auto_mode_enabled(mod_dir):
        return False
    result_file = _write_inbox(
        mod_dir,
        build_result_payload(classification, track_id=track_id, game_year=game_year),
    )
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        _log.error("F1 Reality auto mode: PowerShell not found; result kept at %s", result_file)
        return False
    completed = subprocess.run(
        [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(mod_dir / "F1Reality.ps1"), "auto-finish", "--result-file", str(result_file),
        ],
        cwd=mod_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        _log.error(
            "F1 Reality auto mode failed (%s): %s",
            completed.returncode,
            (completed.stderr or completed.stdout).strip(),
        )
        return False
    _log.info("F1 Reality auto mode: %s", completed.stdout.strip())
    return True
