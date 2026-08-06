"""
core/screenshot.py
==================
Best-effort game screenshot for RaceFeed hero posts. Uses `mss` (lazy import)
to grab a region and write a PNG; a near-black frame (fullscreen-exclusive
DirectX capture returns black) is detected and skipped. Everything degrades
silently — a screenshot is never critical. All heavy work runs off the caller's
thread via capture_async.
"""
from __future__ import annotations

import logging
import threading

_log = logging.getLogger(__name__)

# Mean 0-255 brightness below this => treat the frame as a black capture failure.
_NEAR_BLACK_THRESHOLD = 12.0


def _is_near_black(rgb: bytes) -> bool:
    import numpy as np
    arr = np.frombuffer(rgb, dtype=np.uint8)
    if arr.size == 0:
        return True
    return float(arr.mean()) < _NEAR_BLACK_THRESHOLD


def _default_grab(region):
    import mss
    with mss.mss() as sct:
        return sct.grab(region or sct.monitors[1])  # monitors[1] = primary


def _default_write(rgb, size, path):
    import mss.tools
    mss.tools.to_png(rgb, size, output=path)


def capture_to(path: str, region: dict | None,
               grab=_default_grab, write=_default_write, is_black=_is_near_black) -> bool:
    """Grab `region` (primary monitor if None), skip near-black, write a PNG.
    Returns True iff a file was written. Never raises."""
    try:
        shot = grab(region)
        if shot is None or is_black(shot.rgb):
            return False
        write(shot.rgb, shot.size, path)
        return True
    except Exception:
        _log.debug("screenshot capture failed for %s", path, exc_info=True)
        return False


def capture_async(path: str, region: dict | None = None) -> None:
    """Fire-and-forget capture on a daemon thread (never blocks the caller)."""
    threading.Thread(target=capture_to, args=(path, region),
                     daemon=True, name="racefeed-shot").start()
