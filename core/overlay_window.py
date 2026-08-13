"""Native Windows lifecycle for the in-game HUD.

The overlay is born hidden.  It is shown only while a supported simulator is
the foreground application, follows that window's client area, and remains
mouse-transparent during a race.  Ctrl+Alt+O temporarily enables interaction
without detaching the HUD from the game window.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import threading
import time
from typing import Callable

from core import overlay_layout, overlay_shape

_log = logging.getLogger(__name__)

_TITLE = "Spotter HUD · lap"
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_LAYERED = 0x00080000
_LWA_ALPHA = 0x2
_LWA_COLORKEY = 0x1

_GAME_PROCESS_NAMES = frozenset({
    "f1_23.exe",
    "f1_24.exe",
    "f1_25.exe",
    "f1_26.exe",
    "iracingsim64dx11.exe",
    "iracingsim64dx11_obfuscated.exe",
})


@dataclass(frozen=True)
class GameWindow:
    """Screen-space client area of a supported simulator window."""

    hwnd: int
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class HudWidgetSpec:
    """Native compact window contract for one independently hosted HUD."""

    widget_id: str
    width: int
    height: int

    @property
    def title(self) -> str:
        return f"Spotter HUD · {self.widget_id}"

    def place_over(self, game: GameWindow, scale: float = 1.0) -> GameWindow:
        """Return the widget's screen-space rectangle inside the game client.

        `scale` multiplies the base geometry: the layouts are fitted to these
        exact pixel budgets, so the user resizes a widget by making the whole
        thing bigger, not by reflowing it (see core/overlay_layout.py).
        """
        width = min(max(1, round(self.width * scale)), game.width)
        height = min(max(1, round(self.height * scale)), game.height)
        if self.widget_id == "hud":
            # Dashboard pill sits centred along the bottom edge, like the
            # reference HUD and the game's own MFD.
            x = (game.width - width) // 2
            y = game.height - height - 24
        elif self.widget_id == "inputs":
            x = (game.width - width) // 2
            y = game.height - height - 150
        elif self.widget_id == "lap":
            x, y = 18, 54
        elif self.widget_id == "tower":
            x, y = 18, 254
        elif self.widget_id == "pu":
            x = game.width - width - 18
            y = 54
        elif self.widget_id == "engineer":
            x = game.width - width - 18
            y = 176
        elif self.widget_id == "radar":
            x = game.width - width - 34
            y = game.height - height - 220
        else:  # radio
            # Телевизионная карточка радио: по центру снизу, как в трансляции.
            #
            # Отступ 290, а не 64–110 из ТЗ §6, потому что нижняя середина уже
            # занята: таблетка `hud` стоит на `height-24`, полосы `inputs` — на
            # `height-150`. Карточка с маленьким отступом легла бы на оба, а
            # перекрывать постоянный HUD ради временной карточки нельзя (то же
            # ТЗ, §1 и §23). 290 — первая свободная полоса над кластером.
            x = (game.width - width) // 2
            y = game.height - height - 290
        return GameWindow(
            hwnd=game.hwnd,
            left=game.left + max(6, min(game.width - width - 6, x)),
            top=game.top + max(6, min(game.height - height - 6, y)),
            width=width,
            height=height,
        )


# Must match the frontend panel fill (`PANEL` in in-game-overlay.tsx). The HUD
# windows are opaque, so any pixel the page has not painted yet shows this
# colour — keeping them equal means a mounting widget looks like the panel
# instead of a stray light-grey block over the game.
OVERLAY_BACKGROUND = "#0c0c10"

# Sizes mirror the reference overlays' base geometry (pits-n-giggles 4.2.0
# QML `baseWidth`/`baseHeight`) and MUST match WIDGET_SIZE in
# NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx.
HUD_WIDGETS: dict[str, HudWidgetSpec] = {
    "hud": HudWidgetSpec("hud", 470, 116),
    "lap": HudWidgetSpec("lap", 280, 180),
    "tower": HudWidgetSpec("tower", 264, 288),
    "inputs": HudWidgetSpec("inputs", 450, 120),
    "radar": HudWidgetSpec("radar", 300, 300),
    "pu": HudWidgetSpec("pu", 220, 106),
    "engineer": HudWidgetSpec("engineer", 304, 154),
    "radio": HudWidgetSpec("radio", 430, 178),
}


def primary_screen_size() -> tuple[int, int]:
    """Return the primary monitor size, with a safe HD fallback."""
    try:
        import ctypes

        width = int(ctypes.windll.user32.GetSystemMetrics(0))
        height = int(ctypes.windll.user32.GetSystemMetrics(1))
        if width > 0 and height > 0:
            return width, height
    except Exception:  # noqa: BLE001 - window sizing must not block startup
        pass
    return 1920, 1080


def game_window_region() -> dict | None:
    """The game window's client area as an mss-style region, or None when the
    game window can't be found (mss then falls back to the primary monitor)."""
    win = _Win32OverlayBackend().find_game_window()
    if win is None or win.width <= 0 or win.height <= 0:
        return None
    return {"left": win.left, "top": win.top, "width": win.width, "height": win.height}


class _Win32OverlayBackend:
    """Small native boundary kept injectable for deterministic lifecycle tests."""

    def resolve_overlay(self, title: str) -> int:
        try:
            import win32gui
            import win32process

            current_pid = os.getpid()
            matches: list[int] = []

            def visit(hwnd, _extra) -> None:
                try:
                    if win32gui.GetWindowText(hwnd) != title:
                        return
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if int(pid) == current_pid:
                        matches.append(int(hwnd))
                except Exception:
                    return

            # Several Spotter restarts can temporarily leave same-title zombie
            # WebView2 hosts behind. FindWindow(title) is therefore unsafe: it
            # may return another process's HUD, causing the new controller to
            # move/clip the stale window while its own window stays off-screen.
            win32gui.EnumWindows(visit, None)
            return matches[0] if matches else 0
        except Exception:  # noqa: BLE001 - pywin32 is a degradable integration
            return 0

    def find_game_window(self) -> GameWindow | None:
        try:
            import psutil
            import win32gui
            import win32process

            candidates: list[GameWindow] = []

            def visit(hwnd, _extra) -> None:
                try:
                    if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                        return
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    process_name = psutil.Process(pid).name().casefold()
                    if process_name not in _GAME_PROCESS_NAMES:
                        return
                    client_left, client_top, client_right, client_bottom = (
                        win32gui.GetClientRect(hwnd)
                    )
                    left, top = win32gui.ClientToScreen(
                        hwnd, (client_left, client_top)
                    )
                    right, bottom = win32gui.ClientToScreen(
                        hwnd, (client_right, client_bottom)
                    )
                    width = int(right - left)
                    height = int(bottom - top)
                    if width >= 320 and height >= 180:
                        candidates.append(GameWindow(
                            hwnd=int(hwnd),
                            left=int(left),
                            top=int(top),
                            width=width,
                            height=height,
                        ))
                except Exception:  # a protected/stale window is simply skipped
                    return

            win32gui.EnumWindows(visit, None)
            if not candidates:
                return None

            foreground = self.root_window(self.foreground_window())
            return next(
                (item for item in candidates if item.hwnd == foreground),
                max(candidates, key=lambda item: item.width * item.height),
            )
        except Exception:  # noqa: BLE001 - no game means the HUD stays hidden
            return None

    def foreground_window(self) -> int:
        try:
            import win32gui

            return int(win32gui.GetForegroundWindow() or 0)
        except Exception:  # noqa: BLE001
            return 0

    def root_window(self, hwnd: int) -> int:
        if not hwnd:
            return 0
        try:
            import win32gui

            return int(win32gui.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT
        except Exception:  # noqa: BLE001
            return int(hwnd)

    def apply_interaction_mode(self, hwnd: int, editable: bool) -> None:
        import ctypes
        import win32con
        import win32gui

        style = win32gui.GetWindowLong(hwnd, _GWL_EXSTYLE)
        # The HUD does NOT rely on per-pixel transparency: WebView2 on this
        # WinForms host never composites its alpha out to the desktop. Every
        # window-level transparency trick was tried and rejected live on this
        # Win11/WebView2 stack — LWA_ALPHA → solid white, DWM "glass sheet" →
        # solid black, LWA_COLORKEY (even with --disable-gpu) → solid grey.
        # Instead each HUD is its OWN compact native window, sized to exactly
        # that widget (see HudWidgetSpec.place_over) — there is no fullscreen
        # surface left to show through, so nothing needs clipping. The window
        # stays opaque; WS_EX_LAYERED is kept only because WS_EX_TRANSPARENT
        # click-through in race mode depends on it.
        style |= _WS_EX_LAYERED
        if editable:
            style &= ~(_WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE)
        else:
            style |= _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE
        win32gui.SetWindowLong(hwnd, _GWL_EXSTYLE, style)
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, _LWA_ALPHA)
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE
            | win32con.SWP_NOSIZE
            | win32con.SWP_FRAMECHANGED
            | (0 if editable else win32con.SWP_NOACTIVATE),
        )

    def prepare(self, hwnd: int, game: GameWindow) -> None:
        """Size and position the overlay without making it visible."""
        import win32con
        import win32gui

        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            game.left,
            game.top,
            game.width,
            game.height,
            win32con.SWP_NOACTIVATE,
        )

    def show(self, hwnd: int) -> None:
        import win32con
        import win32gui

        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)

    def window_rect(self, hwnd: int) -> GameWindow | None:
        """Where the overlay window actually is, so user drags can be detected."""
        try:
            import win32gui

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return GameWindow(
                hwnd=int(hwnd),
                left=int(left),
                top=int(top),
                width=int(right - left),
                height=int(bottom - top),
            )
        except Exception:  # noqa: BLE001 - drag tracking is best-effort
            return None

    def apply_shape(self, hwnd: int, primitives) -> None:
        """Обрезать окно по форме виджета: вне формы будет видно трассу.

        Единственный доступный здесь способ убрать чёрный фон окна из-под
        круглого радара и скруглённой таблетки: прозрачности по пикселям этот
        стек не даёт (история попыток — в `app.pyw`), а регион даёт — замерено
        на живом окне, углы после эллипса показывают то, что под окном.

        Пустой список означает «прямоугольное окно» — ровно поведение до этой
        функции. `WS_EX_LAYERED` при этом трогать НЕЛЬЗЯ: со снятым стилем окно
        пропадает целиком (тоже замерено).
        """
        import ctypes

        region = overlay_shape.build_region(primitives)
        # Успешный SetWindowRgn забирает регион себе — удалять его после этого
        # нельзя. Ноль означает «региона нет».
        ctypes.windll.user32.SetWindowRgn(hwnd, region or 0, True)

    def place(self, hwnd: int, game: GameWindow) -> None:
        """Compatibility helper; the controller uses prepare/clip/show."""
        self.prepare(hwnd, game)
        self.show(hwnd)

    def hide(self, hwnd: int) -> None:
        import win32con
        import win32gui

        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    def focus(self, hwnd: int) -> None:
        import win32gui

        win32gui.SetForegroundWindow(hwnd)


class OverlayWindowController:
    """Attach one pywebview HUD window to a supported foreground game."""

    def __init__(
        self,
        window,
        *,
        spec: HudWidgetSpec | None = None,
        title: str | None = None,
        backend=None,
        poll_interval: float = 0.25,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self.spec = spec or HUD_WIDGETS["lap"]
        self.window = window
        self.title = title or self.spec.title
        self._backend = backend or _Win32OverlayBackend()
        self._poll_interval = max(0.05, float(poll_interval))
        self._thread_factory = thread_factory
        self._hwnd: int = 0
        self._edit_mode = False
        self._visible: bool | None = None
        self._placed_over: GameWindow | None = None
        # Where the user dragged this HUD, relative to the game's client area.
        # None => use the built-in default spot from HudWidgetSpec.place_over.
        self._offset: tuple[int, int] | None = overlay_layout.load(
            self.spec.widget_id)
        # Множитель габаритов окна. Его меняет ДРУГОЙ процесс — главное окно
        # приложения, когда пилот тянет угол виджета или применяет пресет, —
        # поэтому рядом хранится отметка файла, по которой изменение замечается
        # без разбора JSON на каждом тике.
        self._scale: float = overlay_layout.load_scale(self.spec.widget_id)
        # Выключенный виджет прячется САМ, не дожидаясь, пока главное окно
        # закроет его процесс: между снятием галочки и закрытием проходит до
        # двух секунд, и всё это время он висел бы поверх игры.
        self._enabled: bool = overlay_layout.load_enabled(self.spec.widget_id)
        self._layout_revision: float = overlay_layout.revision(self.spec.widget_id)
        # Последнее расхождение «просили / получили» по габаритам окна. Нужно
        # только чтобы не писать одну и ту же жалобу в лог на каждом размещении.
        self._size_refusal: tuple[int, int, int, int] | None = None
        # Форма окна и «есть ли что показывать» — их сообщает САМА страница
        # (см. `apply_page_shape`). Значения по умолчанию описывают сегодняшнее
        # поведение: прямоугольное окно, которое всегда на экране. Страница,
        # которая ничего не сообщила (старая сборка webui/, превью в браузере),
        # поэтому ничего и не теряет.
        self._page_shape: object = None
        self._page_visible = True
        self._applied_shape: tuple[overlay_shape.Primitive, ...] = ()
        # Будит поток монитора, когда страница что-то сообщила: ждать до 250 мс,
        # чтобы показать карточку рации, значит опоздать к началу реплики.
        self._wake = threading.Event()
        self._started = False
        self._initialized = False
        self._lock = threading.Lock()
        self._initialization_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def edit_mode(self) -> bool:
        with self._lock:
            return self._edit_mode

    def start(self) -> None:
        """Start the persistent native-window monitor; safe to call repeatedly.

        pywebview invokes its GUI startup hook before WebView2 necessarily
        creates the native HWND. Initialization therefore cannot use a bounded
        wait and permanently give up: the monitor keeps polling and initializes
        once the window actually exists.
        """
        with self._lock:
            if self._started:
                return
            self._started = True

        self._thread = self._thread_factory(
            target=self._monitor_loop,
            daemon=True,
            name="overlay-window",
        )
        self._thread.start()

    # Backwards-compatible name used by older entrypoints/tests.
    initialize = start

    def _ensure_initialized(self) -> bool:
        """Initialize the Win32 host once its delayed HWND becomes available."""
        if self._initialized:
            return True
        hwnd = self._resolve_hwnd()
        if not hwnd:
            return False

        with self._initialization_lock:
            if self._initialized:
                return True
            try:
                self._prime_backdrop_colour()
                self._backend.apply_interaction_mode(hwnd, self.edit_mode)
                self._backend.hide(hwnd)
                self._visible = False
            except Exception:  # noqa: BLE001 - retry after transient startup failure
                _log.exception("Unable to initialize native overlay window")
                return False
            self._initialized = True

        self._notify_browser(self.edit_mode)
        return True

    def _prime_backdrop_colour(self) -> None:
        """Belt-and-braces: pin the WinForms host BackColor to the panel colour.

        ``app.pyw`` now creates these windows with ``transparent=False``, so
        pywebview assigns ``background_color`` itself (measured: BackColor
        becomes #0c0c10). With ``transparent=True`` it skipped that assignment
        and left the default light-grey ``Color [Control]`` — the grey block
        users saw over the game. This re-asserts the colour so a future
        transparent=True regression, or any host that skips the opaque branch,
        cannot bring the grey back.

        Degradable: on the deterministic lifecycle tests ``self.window`` is a
        fake without ``native`` and this is a no-op.
        """
        native = getattr(self.window, "native", None)
        if native is None:
            return
        try:
            from System import Action
            from System.Drawing import ColorTranslator

            def _apply() -> None:
                native.BackColor = ColorTranslator.FromHtml(OVERLAY_BACKGROUND)

            native.Invoke(Action(_apply))
        except Exception:  # noqa: BLE001 - background colour is best-effort
            _log.exception("Unable to prime overlay backdrop colour")

    def apply_page_shape(self, payload: object) -> bool:
        """Принять от страницы её форму и признак «есть что показывать».

        Форму знает только страница: она зависит от темы (фаска, радиус
        карточки рации) и от состояния (карточка рации есть или нет). Копия
        этой геометрии в Python молча разъехалась бы с вёрсткой.

        Вызывается из потока WebView2, поэтому здесь только запись значений и
        побудка монитора — вся работа с окном остаётся в его потоке.
        """
        shapes: object = None
        visible = True
        if isinstance(payload, dict):
            shapes = payload.get("shapes")
            if "visible" in payload:
                visible = bool(payload.get("visible"))
        with self._lock:
            self._page_shape = shapes
            self._page_visible = visible
        self._wake.set()
        return True

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        # Монитор ждёт на побудке, а не на стоп-событии: без этого выход
        # занимал бы лишний тик.
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def toggle_edit_mode(self) -> bool:
        return self.set_edit_mode(not self.edit_mode)

    def set_edit_mode(self, enabled: bool) -> bool:
        """Enable browser interaction or restore click-through race mode."""
        enabled = bool(enabled)
        with self._lock:
            self._edit_mode = enabled

        if self._ensure_initialized():
            hwnd = self._hwnd
            try:
                self._backend.apply_interaction_mode(hwnd, enabled)
                self.sync_once()
                if enabled and self._visible:
                    self._backend.focus(hwnd)
            except Exception:  # noqa: BLE001 - overlay remains degradable
                _log.exception("Unable to change overlay interaction mode")

        self._notify_browser(enabled)
        return enabled

    def _refresh_geometry(self) -> None:
        """Adopt position/scale changes written by another process.

        The resize handle and the preset switcher live in the main window, which
        writes this widget's document; the widget itself only ever learns about
        it here. Cheap by design: one `stat` per tick, a re-read only when the
        file actually changed.
        """
        revision = overlay_layout.revision(self.spec.widget_id)
        if revision == self._layout_revision:
            return
        self._layout_revision = revision
        self._offset = overlay_layout.load(self.spec.widget_id)
        self._scale = overlay_layout.load_scale(self.spec.widget_id)
        self._enabled = overlay_layout.load_enabled(self.spec.widget_id)

    def _target_for(self, game: GameWindow) -> GameWindow:
        """The widget's rectangle: its saved position, else the default spot.

        A saved offset is clamped into the game's client area, so a HUD dragged
        to the edge of a 2560-wide window does not end up off-screen when the
        game later runs windowed at 1280.
        """
        base = self.spec.place_over(game, self._scale)
        if self._offset is None:
            return base
        offset_x, offset_y = self._offset
        limit_x = max(0, game.width - base.width)
        limit_y = max(0, game.height - base.height)
        return GameWindow(
            hwnd=game.hwnd,
            left=game.left + max(0, min(limit_x, offset_x)),
            top=game.top + max(0, min(limit_y, offset_y)),
            width=base.width,
            height=base.height,
        )

    def _absorb_user_drag(self, hwnd: int, game: GameWindow) -> bool:
        """Adopt and persist a position the user dragged this HUD to.

        Dragging happens natively (pywebview's drag region moves the OS window),
        so the controller only learns about it by comparing the real window rect
        with where it last placed the window. Without this the next tick — or
        just alt-tabbing back into the game — would move the HUD home again.

        Returns True when the window is already where the user wants it, telling
        ``sync_once`` not to reposition it on this tick.
        """
        if not self.edit_mode or self._visible is not True:
            return False
        if self._placed_over is None:
            return False
        rect = self._backend.window_rect(hwnd)
        if rect is None:
            return False
        if (rect.left, rect.top) == (self._placed_over.left, self._placed_over.top):
            return False

        offset = (rect.left - game.left, rect.top - game.top)
        if offset != self._offset:
            self._offset = offset
            overlay_layout.save(self.spec.widget_id, offset[0], offset[1])
            # Своя же запись не должна выглядеть как чужое изменение на
            # следующем тике: иначе каждый сдвиг стоил бы лишнего разбора JSON.
            self._layout_revision = overlay_layout.revision(self.spec.widget_id)
            _log.info(
                "Overlay %s moved to offset %s within the game client area",
                self.spec.widget_id, offset,
            )
        # Record the clamped equivalent so the next tick compares equal and the
        # HUD is left alone instead of being nudged by a pixel.
        #
        # Габариты берутся из НАСТОЯЩЕГО окна, а не из цели: размещение на этом
        # тике пропускается, и записать сюда целевой размер значило бы объявить
        # применённым масштаб, которого окно ещё не получало. Следующий тик
        # увидел бы `target == _placed_over` и не переставил бы окно уже
        # никогда — виджет навсегда остался бы в старом размере.
        target = self._target_for(game)
        self._placed_over = GameWindow(
            hwnd=target.hwnd,
            left=target.left,
            top=target.top,
            width=rect.width,
            height=rect.height,
        )
        return True

    def sync_once(self) -> None:
        """Apply one deterministic game-window visibility/placement decision."""
        if not self._ensure_initialized():
            return
        self._refresh_geometry()
        hwnd = self._hwnd

        game = self._backend.find_game_window()
        foreground = self._backend.root_window(self._backend.foreground_window())
        with self._lock:
            page_visible = self._page_visible
        should_show = bool(
            game
            and self._enabled
            # Виджету нечего показать — окна на экране быть не должно вовсе.
            # Раньше окно рации держало тёмную карточку поверх игры всё время,
            # хотя её содержимое в покое пустое. Правило видимости знает только
            # страница (там же, где решается, рисовать карточку или нет).
            and page_visible
            and (
                foreground == game.hwnd
                or (self.edit_mode and foreground == hwnd)
            )
        )

        if should_show and game is not None:
            if self._absorb_user_drag(hwnd, game):
                return  # already exactly where the user dropped it this tick
            target = self._target_for(game)
            needs_safe_show = self._visible is not True or self._placed_over != target
            if needs_safe_show:
                # Each HUD is its own compact native window. There is no
                # game-sized backing surface and therefore nothing fullscreen
                # that could be exposed while WebView2 is mounting.
                self._backend.hide(hwnd)
                self._visible = False
                self._backend.prepare(hwnd, target)
                self._backend.show(hwnd)
                self._visible = True
                self._placed_over = target
                self._verify_size(hwnd, target)
                # Кэш применённой формы сбрасывается вместе с показом окна.
                #
                # `SetWindowRgn` живёт на HWND, и пересоздание/переоткрытие окна
                # его теряет. Показ идёт не только отсюда: pywebview зовёт
                # form.Show()/Activate() напрямую при каждой навигации WebView2
                # и при восстановлении после сбоя (см. комментарий в ветке
                # `else` ниже — там этот же обход уже учтён для видимости).
                # Без сброса `_refresh_shape` сравнивал бы новую форму со
                # СТАРОЙ записью «уже применено» и молча выходил, оставив окно
                # прямоугольным: под карточкой рации светили бы 60 пикселей
                # чёрного фона поверх трассы, и починиться это могло только
                # случайной сменой размера карточки.
                self._applied_shape = ()
            # После размещения, а не до: регион задан в пикселях окна, и на
            # старых габаритах он обрезал бы уже не то.
            self._refresh_shape(hwnd, target)
        else:
            # Unconditional, not "elif self._visible is not False": pywebview's
            # EdgeChrome backend calls form.Show()/Activate() directly on every
            # WebView2 navigation or crash-recovery reload for transparent
            # windows (platforms/edgechromium.py::on_navigation_start), bypassing
            # this controller. That external Show() can flip the real window
            # visible while our cache still says False, so trusting the cache
            # here would let the out-of-band reveal persist indefinitely instead
            # of being corrected within one poll_interval.
            self._backend.hide(hwnd)
            self._visible = False

    def _refresh_shape(self, hwnd: int, target: GameWindow) -> None:
        """Пересчитать форму под текущие габариты и применить, если изменилась.

        Дешёвая на холостом ходу: пересчёт — арифметика по нескольким фигурам,
        а до окна дело доходит только когда форма реально другая (сменилась
        тема, появилась карточка рации, потянули размер).
        """
        with self._lock:
            raw = self._page_shape
        primitives = overlay_shape.scale_primitives(
            raw,
            width=target.width,
            height=target.height,
            base_width=self.spec.width,
            base_height=self.spec.height,
        )
        if not primitives:
            # «Фигур нет» — это отсутствие сведений, а не форма «окно целиком».
            #
            # Страница присылает пустой список в переходные моменты: реплика
            # только началась, карточка ещё не смонтирована и мерить нечего
            # (см. test_widget_with_nothing_to_show_leaves_the_screen — окно в
            # этот момент обязано вернуться). Применить пустую форму значит
            # позвать SetWindowRgn(0) и СНЯТЬ регион с окна, а окно у виджета с
            # прозрачной оболочкой заметно больше содержимого: у рации карточка
            # занимает 108 пикселей из 178, и снятый регион выводит поверх
            # трассы остальные 70 чёрным прямоугольником — тот самый «обрубок».
            #
            # Поэтому старый регион сохраняется до прихода нового. Единственная
            # ситуация, когда региона нет вовсе, — окно, которому его ещё ни
            # разу не задавали: прямоугольное окно молчащей страницы, прежнее
            # и намеренное поведение.
            return
        if primitives == self._applied_shape:
            return
        try:
            self._backend.apply_shape(hwnd, primitives)
        except Exception:  # noqa: BLE001 - без формы окно просто прямоугольное
            _log.exception("Unable to apply overlay window shape")
            return
        self._applied_shape = primitives

    def _verify_size(self, hwnd: int, target: GameWindow) -> None:
        """Пожаловаться, когда окно не приняло запрошенные габариты.

        Отказ не возвращает ошибки: окно отвечает на WM_GETMINMAXINFO своим
        порогом, и SetWindowPos молча зажимается. Именно так виджеты и застряли
        в базовом размере при масштабе 0.6 — увидеть это можно было только
        глазами на скриншоте поверх игры. Проверка стоит один GetWindowRect и
        только на пути размещения (редкий), а одинаковое расхождение пишется в
        лог один раз, а не на каждом тике.
        """
        rect = self._backend.window_rect(hwnd)
        if rect is None:
            return
        if (rect.width, rect.height) == (target.width, target.height):
            self._size_refusal = None
            return
        refusal = (target.width, target.height, rect.width, rect.height)
        if refusal == self._size_refusal:
            return
        self._size_refusal = refusal
        _log.warning(
            "Overlay %s asked for %dx%d but the window stayed %dx%d — the OS "
            "refused the size (a window minimum still in force?)",
            self.spec.widget_id, *refusal,
        )

    def close(self) -> None:
        self.stop()
        try:
            self.window.destroy()
        except Exception:  # noqa: BLE001 - main window shutdown continues
            pass

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception:  # noqa: BLE001 - retry after transient Win32 errors
                _log.exception("Unable to synchronize overlay with game window")
            # Обычный шаг — по таймеру, но сообщение страницы («карточка рации
            # появилась») будит цикл сразу: ждать четверть секунды, чтобы
            # показать реплику, значит опоздать к её началу.
            self._wake.wait(self._poll_interval)
            self._wake.clear()

    def _resolve_hwnd(self) -> int:
        if self._hwnd:
            return self._hwnd
        self._hwnd = int(self._backend.resolve_overlay(self.title) or 0)
        return self._hwnd

    def _notify_browser(self, enabled: bool) -> None:
        script = (
            "window.dispatchEvent(new CustomEvent('spotter-overlay-edit',"
            f"{{detail:{str(enabled).lower()}}}));"
        )
        try:
            self.window.evaluate_js(script)
        except Exception:  # page may be closing; native mode is authoritative
            pass
