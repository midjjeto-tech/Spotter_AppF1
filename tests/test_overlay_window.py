import ctypes
import os
import sys
import threading
from types import SimpleNamespace

import core.overlay_window as overlay_window_module
from core.overlay_window import (
    GameWindow,
    HUD_WIDGETS,
    OverlayWindowController,
    _Win32OverlayBackend,
)


class _Window:
    def __init__(self):
        self.scripts = []
        self.destroyed = False

    def evaluate_js(self, script):
        self.scripts.append(script)

    def destroy(self):
        self.destroyed = True


class _Backend:
    def __init__(self, game=None, foreground=0, rect=None):
        self.game = game
        self.foreground = foreground
        # Where the native window "really" is; None = backend cannot tell.
        self.rect = rect
        self.calls = []

    def window_rect(self, _hwnd):
        return self.rect

    def resolve_overlay(self, _title):
        return 123

    def find_game_window(self):
        return self.game

    def foreground_window(self):
        return self.foreground

    def root_window(self, hwnd):
        return hwnd

    def apply_interaction_mode(self, hwnd, editable):
        self.calls.append(("interaction", hwnd, editable))

    def place(self, hwnd, game):
        self.calls.append(("place", hwnd, game))

    def prepare(self, hwnd, game):
        self.calls.append(("prepare", hwnd, game))

    def show(self, hwnd):
        self.calls.append(("show", hwnd))

    def hide(self, hwnd):
        self.calls.append(("hide", hwnd))

    def apply_shape(self, hwnd, primitives):
        self.calls.append(("shape", hwnd, primitives))

    def focus(self, hwnd):
        self.calls.append(("focus", hwnd))


def _install_win32(monkeypatch, initial_style=0):
    calls = []
    gui = SimpleNamespace(
        GetWindowLong=lambda hwnd, index: initial_style,
        SetWindowLong=lambda hwnd, index, style: calls.append(("style", hwnd, style)),
        SetWindowPos=lambda *args: calls.append(("pos", *args)),
        SetForegroundWindow=lambda hwnd: calls.append(("focus", hwnd)),
        ShowWindow=lambda hwnd, command: calls.append(("show", hwnd, command)),
        FindWindow=lambda _klass, _title: 123,
    )
    con = SimpleNamespace(
        HWND_TOPMOST=-1,
        SWP_NOMOVE=0x0002,
        SWP_NOSIZE=0x0001,
        SWP_NOACTIVATE=0x0010,
        SWP_FRAMECHANGED=0x0020,
        SW_SHOWNOACTIVATE=4,
        SW_HIDE=0,
    )
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32con", con)
    return calls


def _install_game_discovery(monkeypatch, process_name):
    gui = SimpleNamespace(
        IsWindowVisible=lambda _hwnd: True,
        IsIconic=lambda _hwnd: False,
        GetClientRect=lambda _hwnd: (0, 0, 1600, 900),
        ClientToScreen=lambda _hwnd, point: (point[0] + 100, point[1] + 50),
        EnumWindows=lambda callback, extra: callback(456, extra),
        GetForegroundWindow=lambda: 456,
        GetAncestor=lambda hwnd, _kind: hwnd,
    )
    process = SimpleNamespace(
        Process=lambda _pid: SimpleNamespace(name=lambda: process_name)
    )
    process_api = SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (10, 20)
    )
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", process_api)
    monkeypatch.setitem(sys.modules, "psutil", process)


def test_resolve_overlay_selects_window_owned_by_current_process(monkeypatch):
    title = "Spotter Overlay"
    other_hwnd = 111
    own_hwnd = 222
    gui = SimpleNamespace(
        # This is exactly the live failure: FindWindow returns an older zombie
        # HUD which happens to have the same title.
        FindWindow=lambda _klass, _title: other_hwnd,
        EnumWindows=lambda callback, extra: [
            callback(other_hwnd, extra),
            callback(own_hwnd, extra),
        ],
        GetWindowText=lambda hwnd: title if hwnd in (other_hwnd, own_hwnd) else "",
    )
    process_api = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (
            1,
            os.getpid() if hwnd == own_hwnd else os.getpid() + 1000,
        )
    )
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", process_api)

    assert _Win32OverlayBackend().resolve_overlay(title) == own_hwnd


def test_race_mode_is_click_through_and_notifies_browser(monkeypatch):
    calls = _install_win32(monkeypatch)
    window = _Window()
    controller = OverlayWindowController(window)
    controller._hwnd = 123

    assert controller.set_edit_mode(False) is False

    style = next(call[2] for call in calls if call[0] == "style")
    assert style & 0x00000020  # WS_EX_TRANSPARENT
    assert style & 0x08000000  # WS_EX_NOACTIVATE
    assert "detail:false" in window.scripts[-1]


def test_native_overlay_is_layered_and_opaque_clipped_to_panels(monkeypatch):
    calls = _install_win32(monkeypatch)
    user32 = SimpleNamespace(
        SetLayeredWindowAttributes=lambda hwnd, crkey, alpha, flags: calls.append(
            ("layered", hwnd, crkey, alpha, flags)
        )
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32))

    _Win32OverlayBackend().apply_interaction_mode(123, False)

    style = next(call[2] for call in calls if call[0] == "style")
    assert style & 0x00080000  # WS_EX_LAYERED (enables WS_EX_TRANSPARENT click-through)
    # Opaque panels: LWA_ALPHA(0x2) with alpha 255. Per-pixel transparency does
    # not work with WebView2 on this stack, so see-through is done geometrically
    # via SetWindowRgn (see _refresh_window_region), not the layered attributes.
    assert ("layered", 123, 0, 255, 0x2) in calls  # LWA_ALPHA, fully opaque


def test_editor_restores_interaction_and_can_toggle(monkeypatch):
    calls = _install_win32(monkeypatch, initial_style=0x00000020 | 0x08000000)
    window = _Window()
    controller = OverlayWindowController(window)
    controller._hwnd = 123

    assert controller.toggle_edit_mode() is True

    style = next(call[2] for call in calls if call[0] == "style")
    assert not style & 0x00000020
    assert not style & 0x08000000
    # Without a running game the editor is configured but never surfaced over
    # Spotter or another desktop application.
    assert not any(call[0] == "focus" for call in calls)
    assert "detail:true" in window.scripts[-1]


def test_close_destroys_overlay_window():
    window = _Window()
    controller = OverlayWindowController(window)
    controller.close()
    assert window.destroyed is True


def test_native_discovery_returns_f1_client_area(monkeypatch):
    _install_game_discovery(monkeypatch, "F1_25.exe")

    assert _Win32OverlayBackend().find_game_window() == GameWindow(
        hwnd=456, left=100, top=50, width=1600, height=900
    )


def test_native_discovery_ignores_unrelated_desktop_window(monkeypatch):
    _install_game_discovery(monkeypatch, "chrome.exe")

    assert _Win32OverlayBackend().find_game_window() is None


def test_overlay_stays_hidden_until_game_is_foreground():
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    backend = _Backend(game=game, foreground=999)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123

    controller.sync_once()

    assert ("hide", 123) in backend.calls
    assert not any(call[0] == "place" for call in backend.calls)


def test_overlay_is_placed_as_widget_sized_window_inside_game_client_area():
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    backend = _Backend(game=game, foreground=456)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    controller.sync_once()

    # Not the whole game window: each HUD gets its own compact widget-sized
    # rectangle positioned inside the game's client area.
    target = controller.spec.place_over(game)
    assert target.width == controller.spec.width
    assert target.height == controller.spec.height
    assert ("prepare", 123, target) in backend.calls
    assert ("show", 123) in backend.calls


def test_overlay_is_positioned_while_hidden_before_first_show():
    """Position while hidden, then show — never reveal at a stale location."""
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    backend = _Backend(game=game, foreground=456)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    controller.sync_once()

    assert backend.calls == [
        ("hide", 123),
        ("prepare", 123, controller.spec.place_over(game)),
        ("show", 123),
    ]


def _fake_layout_store(monkeypatch, saved=None, scales=None, enabled=None):
    """Replace the on-disk layout store with an in-memory one.

    `enabled` — тот же словарь, что передал тест: чтобы выключить виджет прямо
    посреди прогона, тест мутирует его и двигает отметку версии, как это сделал
    бы главный процесс на диске.
    """
    store = dict(saved or {})
    sizes = dict(scales or {})
    flags = enabled if enabled is not None else {}
    monkeypatch.setattr(
        overlay_window_module.overlay_layout, "load_enabled",
        lambda widget_id: flags.get(widget_id, True))
    # Отметка версии: по ней контроллер решает, перечитывать ли документ. В
    # памяти её двигает сам тест — так же, как на диске это делает чужой процесс.
    stamps = {"value": 0.0}
    monkeypatch.setattr(
        overlay_window_module.overlay_layout, "load",
        lambda widget_id: store.get(widget_id))
    monkeypatch.setattr(
        overlay_window_module.overlay_layout, "save",
        lambda widget_id, dx, dy: store.__setitem__(widget_id, (dx, dy)))
    monkeypatch.setattr(
        overlay_window_module.overlay_layout, "load_scale",
        lambda widget_id: sizes.get(widget_id, 1.0))
    monkeypatch.setattr(
        overlay_window_module.overlay_layout, "revision",
        lambda widget_id: stamps["value"])
    return store, sizes, stamps


def test_place_over_scales_the_widget_rectangle():
    """Размер задаётся множителем: вёрстка виджета подогнана под базовые пиксели."""
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    spec = HUD_WIDGETS["tower"]

    scaled = spec.place_over(game, 1.5)

    assert (scaled.width, scaled.height) == (
        round(spec.width * 1.5), round(spec.height * 1.5))


def test_scale_never_exceeds_the_game_client_area():
    """Виджет крупнее окна игры обрезается до окна, а не уезжает за экран."""
    game = GameWindow(hwnd=456, left=0, top=0, width=320, height=200)
    spec = HUD_WIDGETS["tower"]

    scaled = spec.place_over(game, 2.0)

    assert scaled.width <= game.width
    assert scaled.height <= game.height


def test_scale_written_by_another_process_resizes_the_window(monkeypatch):
    """Уголок размера и пресеты живут в ГЛАВНОМ окне, а окно виджета — здесь.

    Изменение доезжает только через файл раскладки, поэтому контроллер обязан
    заметить новую отметку версии и переставить окно на следующем тике.
    """
    _store, sizes, stamps = _fake_layout_store(monkeypatch)
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    backend = _Backend(game=game, foreground=456)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    controller.sync_once()
    assert controller._placed_over.width == controller.spec.width

    # Главное окно записало новый масштаб — файл изменился.
    sizes[controller.spec.widget_id] = 1.5
    stamps["value"] = 1.0
    controller.sync_once()

    assert controller._placed_over.width == round(controller.spec.width * 1.5)
    assert ("prepare", 123, controller._placed_over) in backend.calls


def test_unchanged_layout_file_is_not_re_read(monkeypatch):
    """Один stat на тик вместо разбора JSON: восемь процессов по 4 раза в секунду."""
    _store, sizes, _stamps = _fake_layout_store(monkeypatch)
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    controller = OverlayWindowController(
        _Window(), backend=_Backend(game=game, foreground=456))
    controller._hwnd = 123
    controller._initialized = True

    # Значение подменено, но отметка версии та же — контроллер его не увидит.
    sizes[controller.spec.widget_id] = 1.8
    controller.sync_once()

    assert controller._scale == 1.0


def test_dragging_the_hud_in_edit_mode_persists_its_offset(monkeypatch):
    store, _sizes, _stamps = _fake_layout_store(monkeypatch)
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    # The user dragged the window to (500, 400) on screen.
    dragged = GameWindow(hwnd=123, left=500, top=400, width=280, height=122)
    backend = _Backend(game=game, foreground=123, rect=dragged)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True
    controller._visible = True
    controller._placed_over = controller.spec.place_over(game)
    controller._edit_mode = True

    controller.sync_once()

    # Offset is stored relative to the game's client area, not screen absolute.
    assert store[controller.spec.widget_id] == (400, 350)
    # The HUD is left where the user dropped it — no repositioning this tick.
    assert not any(call[0] == "prepare" for call in backend.calls)


def test_drag_in_the_same_tick_does_not_swallow_a_new_scale(monkeypatch):
    """Подхват перетаскивания не должен объявлять применённым новый размер.

    Размещение на этом тике пропускается — окно остаётся прежних габаритов. Если
    записать в `_placed_over` целевой размер, следующий тик сравнит цель сам с
    собой, решит, что делать нечего, и виджет навсегда останется в старом
    размере: масштаб уедет на диск, а окно его не получит никогда.
    """
    _store, sizes, stamps = _fake_layout_store(monkeypatch)
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    spec = HUD_WIDGETS["lap"]
    # Окно уже переехало под курсором и всё ещё БАЗОВОГО размера.
    dragged = GameWindow(
        hwnd=123, left=500, top=400, width=spec.width, height=spec.height)
    backend = _Backend(game=game, foreground=123, rect=dragged)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True
    controller._visible = True
    controller._placed_over = controller.spec.place_over(game)
    controller._edit_mode = True

    # В этот же тик главное окно записало новый масштаб.
    sizes[controller.spec.widget_id] = 0.6
    stamps["value"] = 1.0
    controller.sync_once()

    assert not any(call[0] == "prepare" for call in backend.calls)
    assert controller._placed_over.width == spec.width  # что на экране, то и тут

    # Следующий тик обязан довести размер до окна.
    backend.rect = None
    controller.sync_once()

    target = next(c[2] for c in backend.calls if c[0] == "prepare")
    assert target.width == round(spec.width * 0.6)
    assert target.height == round(spec.height * 0.6)


def _showing_controller(monkeypatch, widget="radar", **store_kwargs):
    """Контроллер над видимой игрой, готовый к одному тику."""
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    parts = _fake_layout_store(monkeypatch, **store_kwargs)
    backend = _Backend(game=game, foreground=456)
    controller = OverlayWindowController(
        _Window(), spec=HUD_WIDGETS[widget], backend=backend)
    controller._hwnd = 123
    controller._initialized = True
    return controller, backend, parts


def test_window_is_clipped_to_the_shape_the_page_reports(monkeypatch):
    """Круглый радар не должен таскать за собой чёрный квадрат окна.

    Прозрачности по пикселям этот стек не даёт, поэтому лишнее убирается
    регионом окна — а форму знает только страница: она зависит от темы и от
    состояния виджета.
    """
    controller, backend, _ = _showing_controller(monkeypatch)

    controller.apply_page_shape(
        {"visible": True, "shapes": [
            {"kind": "ellipse", "x": 24, "y": 24, "w": 252, "h": 252}]})
    controller.sync_once()

    shape = next(call for call in backend.calls if call[0] == "shape")
    assert [item.kind for item in shape[2]] == ["ellipse"]
    assert shape[2][0].box == (24, 24, 276, 276)


def test_shape_follows_the_window_when_the_scale_changes(monkeypatch):
    """Регион задан в пикселях окна: на новых габаритах он обрезал бы не то."""
    controller, backend, (_store, sizes, stamps) = _showing_controller(monkeypatch)
    controller.apply_page_shape(
        {"visible": True, "shapes": [
            {"kind": "ellipse", "x": 0, "y": 0, "w": 300, "h": 300}]})
    controller.sync_once()

    sizes["radar"] = 0.6
    stamps["value"] = 1.0
    backend.calls.clear()
    controller.sync_once()

    shape = next(call for call in backend.calls if call[0] == "shape")
    assert shape[2][0].box == (0, 0, 180, 180)


def test_unchanged_shape_is_not_re_applied_every_tick(monkeypatch):
    """Форма меняется от смены темы, а не от гонки — тикать по ней незачем."""
    controller, backend, _ = _showing_controller(monkeypatch)
    controller.apply_page_shape(
        {"visible": True, "shapes": [{"kind": "rect", "x": 0, "y": 0, "w": 300, "h": 300}]})
    controller.sync_once()
    backend.calls.clear()

    controller.sync_once()

    assert not any(call[0] == "shape" for call in backend.calls)


def test_a_silent_page_leaves_the_window_rectangular(monkeypatch):
    """Старая сборка webui/ или превью в браузере ничего не сообщают.

    Такое окно обязано вести себя ровно как до появления формы — прямоугольным
    и видимым, а не исчезнуть с экрана.
    """
    controller, backend, _ = _showing_controller(monkeypatch)

    controller.sync_once()

    assert not any(call[0] == "shape" for call in backend.calls)
    assert any(call[0] == "show" for call in backend.calls)


def test_shape_is_re_applied_after_the_window_is_shown_again(monkeypatch):
    """Регион живёт на HWND и теряется при переоткрытии окна.

    Показ идёт не только из контроллера: pywebview зовёт form.Show()/Activate()
    напрямую при каждой навигации WebView2 и при восстановлении после сбоя.
    Кэш «эта форма уже применена» после такого показа описывает окно, которого
    больше нет, и `_refresh_shape` молча выходил по совпадению — окно навсегда
    оставалось прямоугольным. Для рации это 60 пикселей чёрного фона под
    карточкой поверх трассы, которые сами уже не чинились.
    """
    controller, backend, _ = _showing_controller(monkeypatch, widget="radio")
    controller.apply_page_shape(
        {"visible": True, "shapes": [
            {"kind": "rect", "x": 0, "y": 10, "w": 430, "h": 108}]})
    controller.sync_once()
    assert any(call[0] == "shape" for call in backend.calls)

    # Окно переоткрыли в обход контроллера — ровно то, что делает pywebview.
    controller._visible = False
    backend.calls.clear()
    controller.sync_once()

    assert any(call[0] == "shape" for call in backend.calls), (
        "форма не переприменена после переоткрытия окна")


def test_an_empty_shape_does_not_strip_the_region_off_the_window(monkeypatch):
    """«Фигур нет» — это отсутствие сведений, а не форма «окно целиком».

    Пустой список приходит в переходные моменты: реплика началась, карточка
    ещё не смонтирована и мерить нечего. Применить его значит позвать
    SetWindowRgn(0) и снять регион — а окно рации заметно больше карточки
    (178 против 108 измеренных пикселей), и снятый регион показывает поверх
    трассы разницу чёрным прямоугольником. Окно при этом появиться ОБЯЗАНО
    (соседний тест), поэтому чинится не показ, а снятие формы."""
    controller, backend, _ = _showing_controller(monkeypatch, widget="radio")
    controller.apply_page_shape(
        {"visible": True, "shapes": [
            {"kind": "rect", "x": 0, "y": 10, "w": 430, "h": 108}]})
    controller.sync_once()

    backend.calls.clear()
    controller.apply_page_shape({"visible": True, "shapes": []})
    controller.sync_once()

    stripped = [call for call in backend.calls
                if call[0] == "shape" and not call[2]]
    assert not stripped, "регион снят с окна на пустой форме"


def test_widget_with_nothing_to_show_leaves_the_screen(monkeypatch):
    """Окно рации в покое держало тёмную карточку поверх игры всё время."""
    controller, backend, _ = _showing_controller(monkeypatch, widget="radio")

    controller.apply_page_shape({"visible": False, "shapes": []})
    controller.sync_once()

    assert not any(call[0] == "show" for call in backend.calls)
    assert ("hide", 123) in backend.calls

    # Реплика началась — окно обязано вернуться.
    backend.calls.clear()
    controller.apply_page_shape({"visible": True, "shapes": []})
    controller.sync_once()

    assert any(call[0] == "show" for call in backend.calls)


def test_disabled_widget_hides_itself_without_waiting_to_be_closed(monkeypatch):
    """Между снятием галочки и закрытием процесса проходит до двух секунд."""
    flags: dict[str, bool] = {}
    controller, backend, (_store, _sizes, stamps) = _showing_controller(
        monkeypatch, widget="lap", enabled=flags)
    controller.sync_once()
    assert any(call[0] == "show" for call in backend.calls)

    flags["lap"] = False
    stamps["value"] = 1.0
    backend.calls.clear()
    controller.sync_once()

    assert not any(call[0] == "show" for call in backend.calls)
    assert ("hide", 123) in backend.calls


def test_refused_window_size_is_logged_instead_of_passing_silently(caplog):
    """Windows не возвращает ошибку, когда зажимает размер окна своим порогом.

    Ровно так виджеты и застряли в базовом размере при масштабе 0.6: страница
    ужималась, окно — нет, и заметить это можно было только глазами на
    скриншоте. Расхождение обязано попадать в лог.
    """
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    spec = HUD_WIDGETS["lap"]
    # Окно «осталось» базовым, хотя контроллер просил другое.
    refused = GameWindow(
        hwnd=123, left=0, top=0, width=spec.width * 2, height=spec.height * 2)
    backend = _Backend(game=game, foreground=456, rect=refused)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    with caplog.at_level("WARNING", logger=overlay_window_module.__name__):
        controller.sync_once()

    assert "refused the size" in caplog.text
    assert f"{spec.width * 2}x{spec.height * 2}" in caplog.text

    # Одно и то же расхождение не заливает лог на каждом размещении.
    caplog.clear()
    with caplog.at_level("WARNING", logger=overlay_window_module.__name__):
        controller._visible = False
        controller.sync_once()

    assert caplog.text == ""


def test_saved_offset_survives_alt_tab_instead_of_snapping_home(monkeypatch):
    _fake_layout_store(monkeypatch, {"lap": (400, 350)})
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    backend = _Backend(game=game, foreground=456)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    controller.sync_once()

    # Re-showing after alt-tab must restore the SAVED spot, not place_over's.
    target = next(c[2] for c in backend.calls if c[0] == "prepare")
    assert (target.left, target.top) == (100 + 400, 50 + 350)
    assert target != controller.spec.place_over(game)


def test_saved_offset_is_clamped_into_a_smaller_game_window(monkeypatch):
    # Saved from a big window; the game now runs windowed and much smaller.
    _fake_layout_store(monkeypatch, {"lap": (2400, 1300)})
    game = GameWindow(hwnd=456, left=0, top=0, width=1280, height=720)
    backend = _Backend(game=game, foreground=456)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    controller.sync_once()

    target = next(c[2] for c in backend.calls if c[0] == "prepare")
    assert target.left + target.width <= game.width
    assert target.top + target.height <= game.height


def test_position_is_not_absorbed_outside_edit_mode(monkeypatch):
    # In race mode the window is click-through and cannot be dragged; a rect
    # mismatch there means something else moved it, so the controller must
    # reassert its own placement rather than persist a bogus offset.
    store, _sizes, _stamps = _fake_layout_store(monkeypatch)
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    stray = GameWindow(hwnd=123, left=900, top=700, width=280, height=122)
    backend = _Backend(game=game, foreground=456, rect=stray)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True
    controller._visible = True
    controller._placed_over = controller.spec.place_over(game)

    controller.sync_once()

    assert store == {}


def test_editor_remains_over_game_while_overlay_has_focus():
    game = GameWindow(hwnd=456, left=100, top=50, width=1600, height=900)
    backend = _Backend(game=game, foreground=123)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123

    controller.set_edit_mode(True)
    controller.sync_once()

    assert ("prepare", 123, controller.spec.place_over(game)) in backend.calls
    assert ("show", 123) in backend.calls
    assert ("focus", 123) in backend.calls


def test_sync_once_rehides_even_if_something_else_showed_the_window():
    # A prior tick already hid the overlay (cache says _visible=False), but
    # pywebview's on_navigation_start can call form.Show()/Activate() directly
    # without going through this controller. The next tick must still call
    # hide() rather than trusting the stale cache — otherwise that external
    # reveal is never corrected.
    backend = _Backend(game=None, foreground=999)
    controller = OverlayWindowController(_Window(), backend=backend)
    controller._hwnd = 123
    controller._initialized = True

    controller.sync_once()
    controller.sync_once()

    assert backend.calls.count(("hide", 123)) == 2


def test_start_hides_before_monitoring_and_is_idempotent():
    backend = _Backend()
    started = []

    class _Thread:
        def __init__(self, *, target, daemon, name):
            started.append((target, daemon, name))

        def start(self):
            started.append("started")

        def join(self, timeout):
            pass

    controller = OverlayWindowController(
        _Window(), backend=backend, thread_factory=_Thread
    )

    controller.start()
    controller.start()
    controller.sync_once()

    assert backend.calls[:2] == [
        ("interaction", 123, False),
        ("hide", 123),
    ]
    assert started.count("started") == 1


def test_start_keeps_monitoring_until_native_window_appears():
    class _DelayedBackend(_Backend):
        def __init__(self):
            super().__init__()
            self.hwnd = 0

        def resolve_overlay(self, _title):
            return self.hwnd

    class _FastStopEvent:
        def is_set(self):
            return False

        def wait(self, _timeout):
            return False

        def set(self):
            pass

    started = []

    class _Thread:
        def __init__(self, *, target, daemon, name):
            started.append((target, daemon, name))

        def start(self):
            started.append("started")

        def join(self, timeout):
            pass

    backend = _DelayedBackend()
    controller = OverlayWindowController(
        _Window(), backend=backend, thread_factory=_Thread
    )
    controller._stop_event = _FastStopEvent()

    # The GUI startup hook can run before WebView2 creates its HWND. Startup
    # must still launch the persistent monitor instead of giving up forever.
    controller.start()
    assert started.count("started") == 1
    assert backend.calls == []

    backend.hwnd = 123
    controller.sync_once()

    assert backend.calls[:2] == [
        ("interaction", 123, False),
        ("hide", 123),
    ]


import core.overlay_window as _ow


def test_game_window_region_maps_rect(monkeypatch):
    monkeypatch.setattr(_ow._Win32OverlayBackend, "find_game_window",
                        lambda self: _ow.GameWindow(hwnd=1, left=10, top=20, width=800, height=600))
    assert _ow.game_window_region() == {"left": 10, "top": 20, "width": 800, "height": 600}


def test_game_window_region_none_when_no_window(monkeypatch):
    monkeypatch.setattr(_ow._Win32OverlayBackend, "find_game_window", lambda self: None)
    assert _ow.game_window_region() is None
