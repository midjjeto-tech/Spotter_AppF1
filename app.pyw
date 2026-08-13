"""
app.pyw  —  Spotter App
========================
Точка входа. Запускает F1Engine, локальный API и окно с web-интерфейсом.

Запуск:
    .venv\\Scripts\\pythonw.exe app.pyw
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import webview

import config
import core.settings as _settings_store
from core.runtime import AppRuntime
from core.overlay_window import HUD_WIDGETS, OVERLAY_BACKGROUND, OverlayWindowController
from core.overlay_process import OverlayCommandServer, OverlayProcessController
from web_server import API_PORT


def _setup_logging(filename: str = "spotter.log") -> None:
    """Пишем логи в DATA_DIR/spotter.log. В оконном (.pyw/EXE) приложении stderr
    не виден, поэтому проглоченные предупреждения (напр. сбой синтеза Yandex)
    иначе теряются. Ротация, чтобы файл не разрастался."""
    try:
        handler = RotatingFileHandler(
            os.path.join(config.DATA_DIR, filename),
            maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except Exception:  # noqa: BLE001 — логи не должны ронять запуск
        pass


def _show_startup_error(exc: Exception) -> None:
    logging.getLogger(__name__).exception("Spotter App startup failed", exc_info=exc)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Spotter App не удалось запустить:\n\n{exc}",
            "Spotter App — ошибка запуска",
            0x10,
        )
    except Exception:  # noqa: BLE001 — logging remains the fallback
        pass


def main() -> int:
    _setup_logging()
    # Первой строкой каждого запуска: без неё по присланному логу невозможно
    # сказать, какая сборка у пользователя, и разбор начинается с догадок.
    logging.getLogger(__name__).info(
        "Spotter App %s starting (frozen=%s)",
        config.APP_VERSION, getattr(sys, "frozen", False))
    settings = _settings_store.load()
    runtime = AppRuntime(settings, port=API_PORT, base_dir=config.BASE_DIR)
    # IPC proxy only (UDP + subprocess handle) — the actual HUD webview lives
    # in its own process so a HUD crash/hang can never freeze Spotter itself.
    overlay_process = OverlayProcessController(
        entrypoint=os.path.abspath(__file__), port=API_PORT + 1)
    exit_code = 0
    try:
        window = webview.create_window(
            "Spotter App",
            f"http://127.0.0.1:{API_PORT}",
            width=1360,
            height=840,
            min_size=(1100, 700),
            text_select=True,
        )
        overlay_process.start()
        runtime.start(window, overlay_controller=overlay_process)
        webview.start(debug=False)
    except Exception as exc:  # noqa: BLE001 — top-level rollback + visible error
        exit_code = 1
        _show_startup_error(exc)
    finally:
        runtime.stop()
        overlay_process.close()
    return exit_code


class _OverlayPageBridge:
    """Канал «страница → окно»: форма виджета и «есть ли что показывать».

    Push, а не опрос: опрашивать страницу из потока монитора нельзя — он
    отвечает за размещение HUD, а `evaluate_js` блокируется до ответа WebView2,
    и подвисшая страница заморозила бы позиционирование всех виджетов.

    Контроллер появляется ПОСЛЕ окна (окно нужно ему конструктором), поэтому
    мост создаётся пустым и получает контроллер следом. До этого момента вызовы
    со страницы просто игнорируются: окно всё равно ещё прямоугольное и
    спрятанное.

    Имя `_controller` — с подчёркиванием ОБЯЗАТЕЛЬНО. pywebview обходит все
    публичные атрибуты объекта js_api рекурсивно, чтобы выставить их методы в
    JS (`webview/util.py::get_functions`), а подчёркнутые пропускает. С
    публичным именем обход уходил в объектный граф WinForms и падал на
    «maximum recursion depth exceeded» — поймано живым щупом, в тестах с
    заглушкой окна такого графа просто нет.
    """

    def __init__(self) -> None:
        self._controller = None

    def set_shape(self, payload=None) -> bool:
        controller = self._controller
        if controller is None:
            return False
        return controller.apply_page_shape(payload)


def overlay_main(*, port: int, token: str, parent_pid: int, widget: str) -> int:
    """Run one compact HUD widget in its own one-window WebView2 process."""
    spec = HUD_WIDGETS.get(widget)
    if spec is None:
        raise ValueError(f"Unknown overlay widget: {widget!r}")
    _setup_logging(f"spotter-overlay-{widget}.log")
    overlay = None
    control = None
    bridge = _OverlayPageBridge()
    try:
        overlay_window = webview.create_window(
            spec.title,
            f"http://127.0.0.1:{API_PORT}/overlay.html?widget={widget}",
            width=spec.width,
            height=spec.height,
            x=-32000,
            y=-32000,
            # Нижнего порога у окна быть НЕ ДОЛЖНО. pywebview кладёт `min_size`
            # в MinimumSize формы, форма отвечает им на WM_GETMINMAXINFO — и
            # Windows МОЛЧА зажимает любой SetWindowPos меньше порога. С прежним
            # `min_size=(spec.width, spec.height)` это ломало ровно уменьшение:
            # place_over(game, 0.6) считал радару 180×180, prepare() их просил,
            # окно оставалось 300×300 (замерено вживую), содержимое страницы
            # честно ужималось трансформацией — и в освободившихся 40% окна
            # светил чёрный фон поверх трассы.
            #
            # Порог здесь не защищает ни от чего: окно не тянут руками
            # (frameless + resizable=False), его габариты целиком считает
            # OverlayWindowController, а разрешённый диапазон масштаба держит
            # overlay_layout.clamp_scale (0.6–2.0) — единственное место, где
            # порогу и место. Ставить сюда base × MIN_SCALE нельзя: MinimumSize
            # домножается на DPI окна (GetDpiForWindow/96), а цели контроллера
            # — физические пиксели клиентской области игры, так что при масштабе
            # экрана 125% тот же зажим вернулся бы, но уже только у части людей.
            min_size=(1, 1),
            resizable=False,
            frameless=True,
            easy_drag=True,
            shadow=False,
            focus=False,
            on_top=False,
            # Opaque on purpose. WebView2 on this WinForms host cannot composite
            # per-pixel alpha out to the desktop (LWA_ALPHA → white, DWM glass →
            # black, LWA_COLORKEY even with --disable-gpu → grey), and asking for
            # transparent=True made it *worse*: pywebview only assigns the form's
            # BackColor on its opaque branch, so a transparent window kept the
            # default light-grey `Color [Control]` — measured live, and that grey
            # backdrop is exactly the "grey rectangle" seen over the game. Each
            # HUD is its own widget-sized window now, so opacity costs nothing.
            background_color=OVERLAY_BACKGROUND,
            transparent=False,
            text_select=False,
            js_api=bridge,
        )
        overlay = OverlayWindowController(
            overlay_window,
            spec=spec,
            title=spec.title,
        )
        bridge._controller = overlay
        control = OverlayCommandServer(
            overlay,
            port=port,
            token=token,
            parent_pid=parent_pid,
        )
        # Redundant lifecycle signals are intentional. `start()` is idempotent,
        # while WebView2 timing differs between cold and warm starts.
        overlay_window.events.shown += overlay.start
        overlay_window.events.loaded += overlay.start
        control.start()
        # Start the native monitor from pywebview's GUI startup hook. In live
        # WebView2 sessions the ``loaded`` event can be missed for this tiny
        # initially off-screen transparent window, leaving it forever at
        # (-32000, -32000) with no monitor thread and therefore no HUD.
        # ``OverlayWindowController.start`` already waits for the HWND and
        # clips fail-closed while React is still mounting, so it is safe to
        # begin before the page's load event.
        webview.start(func=overlay.start, debug=False)
        return 0
    except Exception as exc:  # noqa: BLE001 - isolated process logs and exits
        logging.getLogger(__name__).exception(
            "Spotter Overlay startup failed", exc_info=exc)
        return 1
    finally:
        if control is not None:
            control.stop()
        if overlay is not None:
            overlay.stop()


def _cli_value(flag: str, default: str) -> str:
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except (ValueError, IndexError):
        return default


if __name__ == "__main__":
    if "--overlay" in sys.argv:
        sys.exit(overlay_main(
            port=int(_cli_value("--overlay-port", str(API_PORT + 1))),
            token=_cli_value("--overlay-token", ""),
            parent_pid=int(_cli_value("--parent-pid", "0")),
            widget=_cli_value("--overlay-widget", "lap"),
        ))
    sys.exit(main())
