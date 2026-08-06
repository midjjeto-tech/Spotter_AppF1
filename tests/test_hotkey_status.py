"""Статус регистрации глобальных хоткеев.

RegisterHotKey раньше проверялся только на "успех/не успех" для последующего
UnregisterHotKey, а провал (комбинацию держит другая программа) не оставлял
никакого следа: ни в логе, ни в UI. Экран «Горячие клавиши» при этом показывал
хоткей как настроенный. Эти тесты фиксируют, что провал теперь виден.
"""
from types import SimpleNamespace

import pytest

from core import hotkeys as hk


class _FakeUser32:
    """Минимальный user32: RegisterHotKey по сценарию, пустой message loop."""

    def __init__(self, results: dict[int, int]):
        self._results = results
        self.registered: list[int] = []
        self.unregistered: list[int] = []

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):  # noqa: N802
        ok = self._results.get(hk_id, 1)
        if ok:
            self.registered.append(hk_id)
        return ok

    def UnregisterHotKey(self, hwnd, hk_id):  # noqa: N802
        self.unregistered.append(hk_id)
        return 1

    def GetMessageW(self, *args):  # noqa: N802
        return 0  # сразу выходим из цикла сообщений


def _install_fake_ctypes(monkeypatch, results: dict[int, int]):
    user32 = _FakeUser32(results)
    kernel32 = SimpleNamespace(
        GetCurrentThreadId=lambda: 4242,
        GetLastError=lambda: hk._ERROR_HOTKEY_ALREADY_REGISTERED,
    )
    fake = SimpleNamespace(
        windll=SimpleNamespace(user32=user32, kernel32=kernel32),
        wintypes=SimpleNamespace(MSG=lambda: SimpleNamespace(message=0, wParam=0)),
        byref=lambda x: x,
    )
    monkeypatch.setattr(hk, "ctypes", fake)
    return user32


def _manager(settings: dict) -> hk.GlobalHotkeyManager:
    return hk.GlobalHotkeyManager(engine=object(), window=object(), settings=settings)


def test_status_before_registration_is_not_ready():
    manager = _manager({})
    status = manager.registration_status()
    assert status["ready"] is False
    # Все известные хоткеи перечислены даже до регистрации — UI не должен
    # додумывать список сам (раньше он его хардкодил).
    assert {row["id"] for row in status["hotkeys"]} == set(hk._HOTKEY_LABELS)
    assert all(row["registered"] is False for row in status["hotkeys"])


def test_all_builtin_hotkeys_registered(monkeypatch):
    _install_fake_ctypes(monkeypatch, {})
    manager = _manager({})
    manager._loop()

    status = manager.registration_status()
    assert status["ready"] is True
    by_id = {row["id"]: row for row in status["hotkeys"]}
    for hk_id in hk._HOTKEYS:
        assert by_id[hk_id]["registered"] is True
        assert by_id[hk_id]["status"] == hk.STATUS_OK


def test_taken_combination_is_reported_not_swallowed(monkeypatch, caplog):
    # Ctrl+Alt+C уже держит другая программа.
    _install_fake_ctypes(monkeypatch, {1: 0})
    manager = _manager({})
    with caplog.at_level("WARNING"):
        manager._loop()

    by_id = {row["id"]: row for row in manager.registration_status()["hotkeys"]}
    assert by_id[1]["registered"] is False
    assert by_id[1]["status"] == hk.STATUS_TAKEN
    # Остальные не страдают — провал одного хоткея не фатален.
    assert by_id[2]["registered"] is True
    assert "RegisterHotKey failed" in caplog.text


def test_failed_hotkey_is_not_unregistered_on_shutdown(monkeypatch):
    user32 = _install_fake_ctypes(monkeypatch, {1: 0})
    _manager({})._loop()
    assert 1 not in user32.unregistered
    assert 2 in user32.unregistered


def test_ptt_not_configured_is_distinct_from_taken(monkeypatch):
    _install_fake_ctypes(monkeypatch, {})
    manager = _manager({})
    manager._loop()

    row = next(r for r in manager.registration_status()["hotkeys"]
               if r["id"] == hk._PTT_HOTKEY_ID)
    assert row["status"] == hk.STATUS_NOT_CONFIGURED
    assert row["keys"] == []


def test_ptt_duplicating_builtin_reports_conflict(monkeypatch, caplog):
    _install_fake_ctypes(monkeypatch, {})
    manager = _manager({"ptt_hotkey": {"ctrl": True, "alt": True, "key": "C"}})
    with caplog.at_level("WARNING"):
        manager._loop()

    row = next(r for r in manager.registration_status()["hotkeys"]
               if r["id"] == hk._PTT_HOTKEY_ID)
    assert row["status"] == hk.STATUS_CONFLICT
    assert row["registered"] is False
    assert row["keys"] == ["Ctrl", "Alt", "C"]
    assert "duplicates a built-in" in caplog.text


def test_ptt_registered_reports_its_combination(monkeypatch):
    _install_fake_ctypes(monkeypatch, {})
    manager = _manager({"ptt_hotkey": {"ctrl": False, "alt": False,
                                       "shift": False, "key": "V"}})
    manager._loop()

    row = next(r for r in manager.registration_status()["hotkeys"]
               if r["id"] == hk._PTT_HOTKEY_ID)
    assert row["registered"] is True
    assert row["keys"] == ["V"]


@pytest.mark.parametrize("settings, expected", [
    (None, ()),
    ({}, ()),
    ({"key": ""}, ()),
    ({"key": "v"}, ("V",)),
    ({"ctrl": True, "shift": True, "key": "F5"}, ("Ctrl", "Shift", "F5")),
])
def test_describe_ptt(settings, expected):
    assert hk._describe_ptt(settings) == expected


def test_labels_cover_every_registered_hotkey():
    """Забытая подпись = строка без действия в UI. Держим карты синхронными."""
    assert set(hk._HOTKEYS) | {hk._PTT_HOTKEY_ID} == set(hk._HOTKEY_LABELS)


# ── Проводка движок → HTTP ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    import core.engine as eng_mod
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None      # без сети
    try:
        yield eng_mod.F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_engine_reports_unavailable_without_provider(engine):
    """Окна нет (headless) или хоткеи не поднялись — честное available=False,
    а не выдуманный список «всё работает»."""
    engine.set_hotkey_status_provider(None)
    assert engine.get_hotkey_status() == {
        "available": False, "ready": False, "hotkeys": []}


def test_engine_passes_through_manager_status(engine, monkeypatch):
    _install_fake_ctypes(monkeypatch, {1: 0})
    manager = _manager({})
    manager._loop()
    engine.set_hotkey_status_provider(manager.registration_status)
    try:
        status = engine.get_hotkey_status()
        assert status["available"] is True and status["ready"] is True
        assert next(r for r in status["hotkeys"] if r["id"] == 1)["status"] == \
            hk.STATUS_TAKEN
    finally:
        engine.set_hotkey_status_provider(None)


def test_engine_survives_broken_provider(engine):
    def boom():
        raise RuntimeError("hotkey thread died")

    engine.set_hotkey_status_provider(boom)
    try:
        assert engine.get_hotkey_status()["available"] is False
    finally:
        engine.set_hotkey_status_provider(None)
