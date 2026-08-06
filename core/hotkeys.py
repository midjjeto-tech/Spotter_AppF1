"""
core/hotkeys.py
================
Глобальные хоткеи через Win32 RegisterHotKey.
Работают когда F1 25 в фокусе — не требуют фокуса окна Spotter.

Ctrl+Alt+C  — включить/выключить комментарий
Ctrl+Alt+P  — следующая персона (tv→hype→calm→toxic→tv)
Ctrl+Alt+T  — тест голоса
Ctrl+Alt+X  — очистить ленту событий
Ctrl+Alt+S  — скрыть/показать окно Spotter поверх игры
Ctrl+Alt+O  — включить/выключить редактор игрового HUD
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.engine import F1Engine

_log = logging.getLogger(__name__)

MOD_ALT     = 0x0001
MOD_CONTROL = 0x0002
WM_HOTKEY   = 0x0312
WM_QUIT     = 0x0012

MOD_SHIFT = 0x0004

_PTT_HOTKEY_ID = 6
_OVERLAY_EDIT_HOTKEY_ID = 7

_VK_F1 = 0x70
_VK_NUMPAD0 = 0x60

# Canonical names persisted by the UI. Letters/digits, function keys and
# numpad digits are handled algorithmically below; this table covers the rest
# of the ordinary keyboard plus browser/media keys exposed by KeyboardEvent.
_NAMED_KEY_VKS: dict[str, int] = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGE_UP": 0x21,
    "PAGE_DOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "ARROW_LEFT": 0x25,
    "ARROW_UP": 0x26,
    "ARROW_RIGHT": 0x27,
    "ARROW_DOWN": 0x28,
    "PRINT_SCREEN": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "CONTEXT_MENU": 0x5D,
    "NUM_MULTIPLY": 0x6A,
    "NUM_ADD": 0x6B,
    "NUM_SUBTRACT": 0x6D,
    "NUM_DECIMAL": 0x6E,
    "NUM_DIVIDE": 0x6F,
    "NUMLOCK": 0x90,
    "SCROLLLOCK": 0x91,
    "BROWSER_BACK": 0xA6,
    "BROWSER_FORWARD": 0xA7,
    "BROWSER_REFRESH": 0xA8,
    "BROWSER_STOP": 0xA9,
    "BROWSER_SEARCH": 0xAA,
    "BROWSER_FAVORITES": 0xAB,
    "BROWSER_HOME": 0xAC,
    "VOLUME_MUTE": 0xAD,
    "VOLUME_DOWN": 0xAE,
    "VOLUME_UP": 0xAF,
    "MEDIA_NEXT": 0xB0,
    "MEDIA_PREVIOUS": 0xB1,
    "MEDIA_STOP": 0xB2,
    "MEDIA_PLAY_PAUSE": 0xB3,
    "LAUNCH_MAIL": 0xB4,
    "SEMICOLON": 0xBA,
    "EQUAL": 0xBB,
    "COMMA": 0xBC,
    "MINUS": 0xBD,
    "PERIOD": 0xBE,
    "SLASH": 0xBF,
    "BACKQUOTE": 0xC0,
    "BRACKET_LEFT": 0xDB,
    "BACKSLASH": 0xDC,
    "BRACKET_RIGHT": 0xDD,
    "QUOTE": 0xDE,
    "OEM_102": 0xE2,
}


def _vk_for_key(key: str) -> int | None:
    """Resolve one canonical UI key name to a Win32 virtual-key code."""
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        return ord(key)
    if key.startswith("F") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return _VK_F1 + number - 1
    if key.startswith("NUM") and key[3:].isdigit() and len(key) == 4:
        return _VK_NUMPAD0 + int(key[3:])
    return _NAMED_KEY_VKS.get(key)


def _vk_from_settings(hk: dict | None) -> "tuple[int, int] | None":
    """Конвертирует settings["ptt_hotkey"] ({"ctrl","alt","shift","key"}) в
    (mods, vk) для RegisterHotKey. None — настройка отсутствует/невалидна
    — 6-й хоткей просто не регистрируется, fail-safe как остальной хоткей-стек.
    Модификатор не обязателен: пользователь может выбрать одну обычную клавишу
    (Space, Enter, стрелку, numpad, punctuation, media key и т.д.). Чистые
    Ctrl/Alt/Shift не являются key и поэтому сюда не попадают."""
    if not isinstance(hk, dict):
        return None
    key = str(hk.get("key") or "").strip().upper()
    vk = _vk_for_key(key)
    if vk is None:
        return None
    mods = 0
    if hk.get("ctrl"):
        mods |= MOD_CONTROL
    if hk.get("alt"):
        mods |= MOD_ALT
    if hk.get("shift"):
        mods |= MOD_SHIFT
    return (mods, vk)


_HOTKEYS = {
    1: (MOD_CONTROL | MOD_ALT, ord('C')),
    2: (MOD_CONTROL | MOD_ALT, ord('P')),
    3: (MOD_CONTROL | MOD_ALT, ord('T')),
    4: (MOD_CONTROL | MOD_ALT, ord('X')),
    5: (MOD_CONTROL | MOD_ALT, ord('S')),
    _OVERLAY_EDIT_HOTKEY_ID: (MOD_CONTROL | MOD_ALT, ord('O')),
}

# Подписи для UI: id → (действие, отображаемая комбинация). Держать в одном
# месте с _HOTKEYS, иначе экран «Горячие клавиши» снова начнёт врать про то,
# что реально зарегистрировано (раньше он вообще хардкодил свой список).
_HOTKEY_LABELS: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("Вкл / выкл комментарий", ("Ctrl", "Alt", "C")),
    2: ("Следующая персона", ("Ctrl", "Alt", "P")),
    3: ("Тест голоса", ("Ctrl", "Alt", "T")),
    4: ("Очистить ленту", ("Ctrl", "Alt", "X")),
    5: ("Показать / скрыть окно", ("Ctrl", "Alt", "S")),
    _OVERLAY_EDIT_HOTKEY_ID: ("Редактировать игровой HUD", ("Ctrl", "Alt", "O")),
    _PTT_HOTKEY_ID: ("Вопрос инженеру (push-to-talk)", ()),
}

# Коды состояния регистрации, уходящие в UI (см. web_server.py
# /api/hotkeys/status). "ok" — RegisterHotKey вернул успех; всё остальное
# означает, что клавиша НЕ работает, хотя на экране выглядит настроенной.
STATUS_OK = "ok"
STATUS_TAKEN = "taken"          # комбинацию уже держит другая программа
STATUS_NOT_CONFIGURED = "not_configured"   # ptt_hotkey не задан/невалиден
STATUS_CONFLICT = "conflict"    # ptt_hotkey совпал со встроенным хоткеем

_ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_PERSONAS = ["tv", "hype", "calm", "toxic"]


def _describe_ptt(hk: dict | None) -> tuple[str, ...]:
    """Комбинация push-to-talk как её показывает UI. Пустой кортеж — не задана."""
    if not isinstance(hk, dict):
        return ()
    key = str(hk.get("key") or "").strip().upper()
    if not key:
        return ()
    parts = []
    if hk.get("ctrl"):
        parts.append("Ctrl")
    if hk.get("alt"):
        parts.append("Alt")
    if hk.get("shift"):
        parts.append("Shift")
    parts.append(key)
    return tuple(parts)


class GlobalHotkeyManager:
    def __init__(self, engine: "F1Engine", window, settings: dict,
                 overlay_controller=None):
        self._engine   = engine
        self._window   = window
        self._settings = settings
        self._overlay_controller = overlay_controller
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._visible  = True
        self._ready = threading.Event()
        # Итог RegisterHotKey по каждому id. Раньше провал (комбинацию занял
        # другой процесс) проглатывался молча: хоткей выглядел настроенным и
        # просто не работал. _status_lock — потому что читает HTTP-поток.
        self._status: dict[int, str] = {}
        self._status_lock = threading.Lock()
        self._registration_done = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hotkeys")
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._ready.wait(timeout=min(0.5, max(0.0, timeout)))
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def registration_status(self) -> dict:
        """Что реально удалось зарегистрировать в Windows. Вызывается из HTTP-
        потока (web_server.py /api/hotkeys/status), поэтому читает снимок под
        локом. `ready=False` — поток хоткеев ещё не дошёл до регистрации."""
        with self._status_lock:
            status = dict(self._status)
        ptt_keys = _describe_ptt(self._settings.get("ptt_hotkey"))
        hotkeys = []
        for hk_id, (action, keys) in _HOTKEY_LABELS.items():
            combo = ptt_keys if hk_id == _PTT_HOTKEY_ID else keys
            state = status.get(hk_id, "")
            hotkeys.append({
                "id": hk_id,
                "action": action,
                "keys": list(combo),
                "registered": state == STATUS_OK,
                "status": state,
            })
        return {"ready": self._registration_done.is_set(), "hotkeys": hotkeys}

    def _record(self, hk_id: int, status: str) -> None:
        with self._status_lock:
            self._status[hk_id] = status

    def _register(self, hk_id: int, mods: int, vk: int) -> bool:
        """RegisterHotKey + запись результата. Провал НЕ фатален (остальные
        хоткеи продолжают работать), но больше не невидим: warning в лог и
        статус для UI."""
        if ctypes.windll.user32.RegisterHotKey(None, hk_id, mods, vk):
            self._record(hk_id, STATUS_OK)
            return True
        err = ctypes.windll.kernel32.GetLastError()
        self._record(hk_id, STATUS_TAKEN)
        action = _HOTKEY_LABELS.get(hk_id, ("?", ()))[0]
        _log.warning(
            "RegisterHotKey failed for id=%s (%s): GetLastError=%s%s",
            hk_id, action, err,
            " (already registered by another application)"
            if err == _ERROR_HOTKEY_ALREADY_REGISTERED else "")
        return False

    def _loop(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._ready.set()
        registered = []
        for hk_id, (mods, vk) in _HOTKEYS.items():
            if self._register(hk_id, mods, vk):
                registered.append(hk_id)

        ptt = _vk_from_settings(self._settings.get("ptt_hotkey"))
        if ptt is None:
            self._record(_PTT_HOTKEY_ID, STATUS_NOT_CONFIGURED)
        elif ptt in _HOTKEYS.values():
            # Совпадение со встроенным хоткеем: раньше это тоже был тихий
            # no-op — пользователь видел настроенный push-to-talk, который
            # ничего не делает.
            self._record(_PTT_HOTKEY_ID, STATUS_CONFLICT)
            _log.warning("push-to-talk hotkey duplicates a built-in Ctrl+Alt "
                         "combination; not registered")
        elif self._register(_PTT_HOTKEY_ID, ptt[0], ptt[1]):
            registered.append(_PTT_HOTKEY_ID)

        self._registration_done.set()

        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._dispatch(int(msg.wParam))
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        for hk_id in registered:
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)

    def _dispatch(self, hk_id: int) -> None:
        actions = {
            1: self._toggle_commentary,
            2: self._next_persona,
            3: self._test_voice,
            4: self._clear_feed,
            5: self._toggle_window,
            _PTT_HOTKEY_ID: self._push_to_talk,
            _OVERLAY_EDIT_HOTKEY_ID: self._toggle_overlay_editor,
        }
        action = actions.get(hk_id)
        if action:
            action()

    def _toggle_commentary(self) -> None:
        enabled = self._settings.get("commentary_enabled", True)
        self._engine.apply_settings({"commentary_enabled": not enabled})

    def _next_persona(self) -> None:
        current = self._settings.get("persona", "tv")
        idx = _PERSONAS.index(current) if current in _PERSONAS else 0
        self._engine.apply_settings({"persona": _PERSONAS[(idx + 1) % len(_PERSONAS)]})

    def _test_voice(self) -> None:
        self._engine.test_voice()

    def _clear_feed(self) -> None:
        self._engine.clear_feed()

    def _toggle_window(self) -> None:
        try:
            if self._visible:
                self._window.hide()
                self._visible = False
            else:
                self._window.show()
                self._bring_to_front()
                self._visible = True
        except Exception:
            pass

    def _bring_to_front(self) -> None:
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, "Spotter App")
            if hwnd:
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _push_to_talk(self) -> None:
        self._engine.ask_voice_question()

    def _toggle_overlay_editor(self) -> None:
        if self._overlay_controller is not None:
            self._overlay_controller.toggle_edit_mode()
