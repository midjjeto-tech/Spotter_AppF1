"""
web_server.py
=============
Локальный HTTP API для index.html (обзор, настройки, тест голоса).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

import psutil

import config
from bottle import Bottle, HTTPResponse, request, response, static_file

from analytics import archive as _archive
from analytics.loader import load_own_reference_session
from analytics.comparator import compare as _compare
from core import overlay_layout as _layout
from core.remote_access import (COOKIE_MAX_AGE, COOKIE_NAME,
                                RemoteAccessPolicy, bind_host, is_loopback)
from core.overlay_window import HUD_WIDGETS as _HUD_WIDGETS

#: Порядок важен только для UI — список виджетов, у которых есть геометрия.
_HUD_WIDGET_IDS = tuple(_HUD_WIDGETS)


class _ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    # WSGIServer defaults to SO_REUSEADDR. On Windows that can allow two live
    # listeners on the same port, defeating synchronous mandatory-start checks.
    allow_reuse_address = False


class LocalWebServer:
    """Owns the local HTTP listener and its worker thread."""

    def __init__(self, app: Bottle, host: str = "127.0.0.1", port: int = 8765):
        self._app = app
        self.host = host
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False

    def start(self) -> None:
        if self._started or self._stopped:
            return
        # Bind synchronously: a busy port is a mandatory startup failure and
        # must be visible to the runtime before the UI tries to load it.
        self._server = make_server(
            self.host, self.port, self._app, _ThreadedWSGIServer)
        self.port = int(self._server.server_port)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="web-api",
        )
        self._thread.start()
        self._started = True

    def stop(self, timeout: float = 2.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        server = self._server
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

#: Реэкспорт из config: константа переехала туда, чтобы движок мог
#: построить адрес второго экрана, не импортируя web_server.
API_PORT = config.API_PORT


def _json(data: dict) -> str:
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def _trim_unchanged_radio_history(state: dict, since: str | None) -> None:
    """Не пересылать историю радио, если она не менялась (ТЗ §11).

    Оверлей опрашивает `/api/state` четыре раза в секунду, а история — самая
    крупная часть секции: до 150 строк. Клиент присылает известную ему
    ревизию, и при совпадении история заменяется на `None` с флагом
    `history_unchanged`.

    Почему параметр, а не отдельный роут: снимок состояния должен остаться
    ОДНИМ запросом. Второй роут ради истории добавил бы третий поллинг в
    оверлее и рассинхрон между секциями (история от одного момента, активная
    передача от другого).

    Без параметра поведение прежнее — «Обзор» и старые клиенты получают полную
    нагрузку и ничего не знают про ревизии."""
    radio = state.get("radio")
    if not isinstance(radio, dict) or since is None:
        return
    try:
        known = int(since)
    except (TypeError, ValueError):
        # Мусор в query — отдаём полную историю. Ошибка клиента не повод
        # оставить панель без данных.
        return
    if known != radio.get("revision"):
        return
    radio["history"] = None
    radio["history_unchanged"] = True


def create_app(engine, settings: dict, base_dir: str) -> Bottle:
    import core.settings as _ss
    app = Bottle()

    # Гейт удалённого доступа стоит ПЕРЕД всеми ручками — и API, и статикой.
    # Вешать его на отдельные маршруты нельзя: забытый маршрут здесь означает
    # открытую наружу ручку, а через это API меняют настройки и пишут ключи.
    # Сама политика — core/remote_access.py, здесь только проводка.
    @app.hook("before_request")
    def _guard_remote_access():
        policy = RemoteAccessPolicy(
            enabled=bool(settings.get("remote_access_enabled", False)),
            token=str(settings.get("remote_access_token", "")),
        )
        # Три источника, потому что путей у токена ровно три и каждый нужен:
        # заголовок ставит `lib/api.ts` на fetch-ах, query приезжает один раз
        # по ссылке из панели, а куку браузер прикладывает САМ — и только она
        # доносит токен до стилей, скриптов и шрифтов. Без неё телефон получал
        # документ и 401 на каждый его подресурс (см. COOKIE_NAME).
        token = (request.get_header("X-Spotter-Token")
                 or request.query.get("token")
                 or request.get_cookie(COOKIE_NAME)
                 or None)
        # REMOTE_ADDR из environ, а НЕ `request.remote_addr`: последний в Bottle
        # читает заголовок `X-Forwarded-For` раньше адреса сокета (см.
        # BaseRequest.remote_route), а заголовок ставит сам клиент. Через
        # `remote_addr` любой в сети присылал `X-Forwarded-For: 127.0.0.1`,
        # попадал в ветку «локальный разрешён ВСЕГДА» и получал ровно то, что
        # политика и создана запрещать: токен, чужие ключи Yandex/GigaChat и
        # запись настроек — причём БЕЗ токена и даже при выключенной фиче.
        # Прокси перед этим сервером не бывает (он локальный), поэтому доверять
        # заголовку незачем в принципе.
        client = request.environ.get("REMOTE_ADDR")
        if not policy.allows(client, request.path, request.method, token):
            # Тело без подробностей: чужому клиенту незачем знать, выключена
            # фича, неверен токен или ручка запрещена в принципе.
            raise HTTPResponse(status=401, body="unauthorized")
        # Ссылка из панели сработала — дальше пусть токен носит браузер.
        # Локальному клиенту кука не нужна: он разрешён всегда.
        if not is_loopback(client) and policy.accepts_token(request.query.get("token")):
            request.environ["spotter.issue_cookie"] = request.query.get("token")

    # Кука ставится плагином — на САМ объект ответа, а не на глобальный
    # `response`, и это не стилистика. В Bottle 0.13 `HTTPResponse.apply()`
    # перезатирает `_headers` и `_cookies` глобального ответа ЦЕЛИКОМ, и
    # вызывается дважды: в `_handle()` и ещё раз в `_cast()` — то есть уже
    # после хука `after_request`. `static_file()` возвращает как раз
    # `HTTPResponse`, поэтому кука, поставленная в любом из хуков, молча
    # пропадала бы ровно на том ответе, который обязан её принести — на
    # документе. Плагин же оборачивает сам маршрут и работает ДО первого
    # `apply()`, а тот переносит куку с объекта ответа на глобальный.
    # Плагин, а не пара маршрутов: забытый маршрут здесь означает страницу,
    # которая грузится один раз и умирает после F5.
    def _issue_remote_cookie(callback):
        def wrapper(*args, **kwargs):
            result = callback(*args, **kwargs)
            token = request.environ.get("spotter.issue_cookie")
            if token:
                target = result if isinstance(result, HTTPResponse) else response
                target.set_cookie(
                    COOKIE_NAME, token,
                    path="/",
                    max_age=COOKIE_MAX_AGE,
                    # Скриптам кука не нужна: свой токен фронт держит в
                    # localStorage, а HttpOnly убирает её из досягаемости
                    # чужого кода на странице.
                    httponly=True,
                    # Запрос со стороннего сайта куку не унесёт.
                    samesite="strict",
                    # `secure` НЕ ставим осознанно: второй экран живёт по HTTP
                    # в локальной сети, и с ним кука не уехала бы вообще.
                )
            return result
        return wrapper

    app.install(_issue_remote_cookie)

    # UI — статический экспорт Next.js в webui/ (исходники в NewSpotterUI).
    # Фоллбэк на base_dir сохранён на случай старого одиночного index.html.
    webui_dir = os.path.join(base_dir, "webui")
    if not os.path.isdir(webui_dir):
        webui_dir = base_dir

    # Персона комментатора для подписи карточки. Провайдер, а не значение:
    # персона меняется и в настройках, и голосовой командой «смени
    # комментатора», а `engine.settings` — единственное место, где виден
    # актуальный выбор. Композиционная точка здесь, а не в `core/runtime.py`
    # (тот же приём, что у `set_hotkey_status_provider`), потому что create_app
    # уже получает и движок, и настройки; при следующей крупной правке runtime
    # эту строку логично перенести туда.
    engine.radio_session.set_persona_provider(
        lambda: engine.settings.get("persona"))

    @app.route("/")
    def index():
        return static_file("index.html", root=webui_dir)

    @app.route("/assets/radio/<filename>")
    def api_radio_portrait(filename):
        """Портреты говорящих для карточки рации.

        Файла может не быть — это штатный случай, а не ошибка развёртывания:
        карточка обязана рисоваться и без портрета (ТЗ §5), фронт по 404
        падает на инициалы. Поэтому здесь нет ни проверки существования, ни
        подстановки заглушки: 404 — часть контракта."""
        return static_file(filename, root=os.path.join(base_dir, "assets", "radio"))

    @app.route("/api/state")
    def api_state():
        state = engine.get_state()
        mem = psutil.virtual_memory()
        state["cpu"] = f"{psutil.cpu_percent(interval=None):.0f}%"
        state["ram"] = f"{mem.percent:.0f}% ({round(mem.used / (1024 ** 3), 1)} GB)"
        # Токен второго экрана вырезан: снимок состояния уходит и на телефон,
        # и в восемь окон оверлея четыре раза в секунду. Показать токен
        # пользователю — задача отдельной локальной ручки, а не каждого поллинга.
        state["settings"] = {k: v for k, v in settings.items()
                             if k != "remote_access_token"}
        _trim_unchanged_radio_history(state, request.query.get("radio_since"))
        return _json(state)

    @app.route("/api/race-ai")
    def api_race_ai():
        return _json(engine.get_race_ai_state())

    @app.route("/api/track-ai")
    def api_track_ai():
        return _json(engine.get_track_ai_state())

    @app.route("/api/strategy-ai")
    def api_strategy_ai():
        return _json(engine.get_strategy_ai_state())

    @app.route("/api/coach-ai")
    def api_coach_ai():
        return _json(engine.get_coach_ai_state())

    @app.route("/api/rivals")
    def api_rivals():
        return _json(engine.get_rivals_state())

    @app.route("/api/remote-access")
    def api_remote_access():
        """Адрес и токен второго экрана. Только с локальной машины — гейт выше
        держит этот путь в LOCAL_ONLY_PATHS."""
        return _json(engine.get_remote_access_info())

    @app.route("/api/race-map")
    def api_race_map():
        """Карта гонки — намеренно ОТДЕЛЬНЫЙ эндпоинт, а не поле /api/state:
        сетка позиций на 22 машины за 60 кругов весит больше тысячи чисел, а
        состояние опрашивают восемь окон оверлея каждые 250 мс. Дебриф читает
        её по запросу, когда пользователь открыл экран."""
        return _json(engine.get_race_map())

    @app.route("/api/overlay")
    def api_overlay():
        return _json(engine.get_overlay_state())

    @app.route("/api/racefeed")
    def api_racefeed():
        return _json(engine.get_racefeed_state())

    @app.route("/api/racefeed/stats")
    def api_racefeed_stats():
        return _json(engine.get_racefeed_stats())

    @app.route("/api/racefeed/archive")
    def api_racefeed_archive():
        return _json(engine.get_racefeed_archive())

    @app.route("/api/racefeed/react", method="POST")
    def api_racefeed_react():
        body = request.json or {}
        return _json(engine.racefeed_reader_action(
            "reaction",
            str(body.get("session_id", "")),
            str(body.get("post_id", "")),
            str(body.get("emoji", "")),
        ))

    @app.route("/api/racefeed/vote", method="POST")
    def api_racefeed_vote():
        body = request.json or {}
        return _json(engine.racefeed_reader_action(
            "vote",
            str(body.get("session_id", "")),
            str(body.get("post_id", "")),
            str(body.get("driver", "")),
        ))

    @app.route("/api/racefeed/comment", method="POST")
    def api_racefeed_comment():
        body = request.json or {}
        return _json(engine.racefeed_reader_comment(
            str(body.get("session_id", "")),
            str(body.get("post_id", "")),
            str(body.get("text", "")),
        ))

    @app.route("/api/racefeed/prediction", method="POST")
    def api_racefeed_prediction():
        body = request.json or {}
        return _json(engine.racefeed_prediction({
            "finish": body.get("finish"),
            "teammate": body.get("teammate"),
            "risk": body.get("risk"),
        }))

    @app.route("/api/racefeed/standings")
    def api_racefeed_standings():
        return _json(engine.get_season_standings())

    @app.route("/api/hotkeys/status")
    def api_hotkeys_status():
        return _json(engine.get_hotkey_status())

    @app.route("/api/diagnostics")
    def api_diagnostics():
        """Готовность подсистем для визарда первого запуска и для поддержки.
        Отдельно от /api/state намеренно: там «связь есть/нет» одним булевом,
        здесь — причина, по которой её нет."""
        return _json(engine.get_diagnostics())

    @app.route("/racefeed/media/<filename>")
    def api_racefeed_media(filename):
        import config
        from pathlib import Path
        root = str(Path(config.DATA_DIR) / "racefeed" / "screenshots")
        return static_file(filename, root=root)

    @app.route("/api/settings", method="POST")
    def api_settings():
        body = request.json or {}
        if body:
            engine.apply_settings(body)
            settings.update(body)
            _ss.save(settings)
        return _json({"ok": True})

    @app.route("/api/settings/reset", method="POST")
    def api_settings_reset():
        defaults = _ss.reset()
        engine.apply_settings(defaults)
        settings.update(defaults)
        return _json({"ok": True, "settings": defaults})

    # ── Геометрия игрового оверлея ──────────────────────────────────────────
    # Не через /api/settings: раскладку пишут ВОСЕМЬ отдельных процессов
    # виджетов (core/overlay_process.py), а settings.save() переписывает весь
    # документ настроек целиком — они бы затирали друг друга. Хранилище и
    # причины — в core/overlay_layout.py.

    @app.route("/api/overlay/layout")
    def api_overlay_layout():
        return _json(_layout.presets_state(_HUD_WIDGET_IDS))

    @app.route("/api/overlay/layout", method="POST")
    def api_overlay_layout_save():
        body = request.json or {}
        widget = str(body.get("widget") or "")
        if widget not in _HUD_WIDGET_IDS:
            response.status = 400
            return _json({"ok": False, "error": "unknown widget"})
        if "scale" in body:
            _layout.save_scale(widget, body.get("scale"))
        if "enabled" in body:
            # Дальше это доедет само: процесс виджета прячется по своей отметке
            # файла, а главный процесс закрывает или поднимает его в
            # OverlayProcessController.sync_enabled.
            _layout.save_enabled(widget, body.get("enabled"))
        if "dx" in body and "dy" in body:
            try:
                _layout.save(widget, int(body["dx"]), int(body["dy"]))
            except (TypeError, ValueError):
                response.status = 400
                return _json({"ok": False, "error": "bad offset"})
        return _json({"ok": True, **_layout.presets_state(_HUD_WIDGET_IDS)})

    @app.route("/api/overlay/layout/reset", method="POST")
    def api_overlay_layout_reset():
        _layout.reset(_HUD_WIDGET_IDS)
        return _json({"ok": True, **_layout.presets_state(_HUD_WIDGET_IDS)})

    @app.route("/api/overlay/presets", method="POST")
    def api_overlay_presets():
        """Сохранить / применить / удалить именованный пресет раскладки."""
        body = request.json or {}
        action = str(body.get("action") or "save")
        name = str(body.get("name") or "")
        if action == "save":
            ok = _layout.save_preset(name, _HUD_WIDGET_IDS)
        elif action == "apply":
            ok = _layout.apply_preset(name)
        elif action == "delete":
            ok = _layout.delete_preset(name)
        else:
            response.status = 400
            return _json({"ok": False, "error": "unknown action"})
        if not ok:
            response.status = 400
            return _json({"ok": False, "error": f"{action} failed for {name!r}"})
        return _json({"ok": True, **_layout.presets_state(_HUD_WIDGET_IDS)})

    @app.route("/api/test_voice")
    def api_test_voice():
        return _json(engine.test_voice())

    @app.route("/api/clear_logs")
    def api_clear_logs():
        engine.clear_feed()
        return _json({"ok": True})

    @app.route("/api/radio/clear_history", method="POST")
    def api_radio_clear_history():
        """Очистить ленту переговоров.

        Отдельно от `/api/clear_logs`: та чистит общую `state["feed"]`, которую
        читают три экрана, а эта — только историю радио. Активную передачу и
        «повтори» не трогает: пилот просил убрать ленту, а не забыть последнюю
        команду."""
        engine.radio_session.clear_history()
        return _json({"ok": True})

    @app.route("/api/highlight")
    def api_highlight():
        ok = engine.fire_highlight()
        return _json({"ok": ok})

    @app.route("/api/story/generate", method="POST")
    def api_story_generate():
        return _json({"ok": engine.generate_story_now()})

    @app.route("/api/story/replay", method="POST")
    def api_story_replay():
        return _json({"ok": engine.replay_story()})

    @app.route("/api/voice/ask", method="POST")
    def api_voice_ask():
        return _json(engine.ask_voice_question())

    @app.route("/api/voices")
    def api_voices():
        from voice.voice_manager import voice_status
        return _json(voice_status(
            yandex_attached=engine.voice._yandex is not None,
            yandex_healthy=engine._yandex_healthy,
            # Действующий каст: без него слоты ролей отдавались бы каталожными
            # дефолтами, и UI показывал бы не тот голос, что звучит.
            overrides=engine.voice._voice_overrides,
        ))

    @app.route("/api/mic_devices")
    def api_mic_devices():
        from voice.listener import list_input_devices
        return _json({"devices": list_input_devices()})

    @app.route("/api/mic_test", method="POST")
    def api_mic_test():
        return _json(engine.test_mic())

    @app.route("/api/sessions", method="GET")
    def api_sessions():
        response.content_type = "application/json"
        return json.dumps(_archive.list_game_sessions(), ensure_ascii=False)

    @app.route("/api/compare_own", method="POST")
    def api_compare_own():
        """Сравнить разбираемый заезд с самым быстрым СВОИМ на этой трассе.

        Раньше здесь грузилась реальная сессия F1 (OpenF1/FastF1) — источник
        удалён как непригодный для коммерческого распространения, см. NOTICE и
        analytics/loader.py. Параметры `year`/`stype` из тела запроса больше не
        читаются: выбирать сезон реального чемпионата стало не из чего, эталон
        определяется однозначно — свой лучший заезд на той же трассе.
        """
        response.content_type = "application/json"
        try:
            body = json.loads(request.body.read().decode("utf-8"))
            game_path = body.get("game_session_path", "")
        except Exception as exc:
            response.status = 400
            return json.dumps({"error": f"bad_request: {exc}"}, ensure_ascii=False)

        game = _archive.load_game_session(game_path) or {"player_laps": [], "events": []}
        try:
            track_id = int(game.get("track_id") or -1)
        except (TypeError, ValueError):
            track_id = -1

        f1_data, err = load_own_reference_session(track_id, exclude_path=game_path)
        if err:
            response.status = 400
            return json.dumps({"error": err}, ensure_ascii=False)

        compare_result = _compare(game, f1_data)
        cpath = _archive.save_compare(game_path or "no_game", track_id, compare_result)

        try:
            engine.set_analytics_context(compare_result.get("qwen_context"))
        except Exception:
            pass

        return json.dumps({
            "f1_meta": f1_data,
            "game_meta": {"track_name": game.get("track_name", "?"),
                          "timestamp": game.get("timestamp", ""),
                          "final_position": game.get("final_position"),
                          "total_laps": game.get("total_laps_completed", 0)},
            "compare": compare_result,
            "compare_id": Path(cpath).name,
        }, ensure_ascii=False)

    @app.route("/api/archive/<compare_id>", method="GET")
    def api_archive(compare_id):
        response.content_type = "application/json"
        import config as _cfg
        # Guard against path traversal
        safe = Path(compare_id).name
        if not safe or safe != compare_id:
            response.status = 400
            return json.dumps({"error": "invalid_id"})
        cpath = Path(_cfg.DATA_DIR) / "race_archive" / safe
        data = _archive.load_compare(cpath)
        if data is None:
            response.status = 404
            return json.dumps({"error": "not_found"})
        return json.dumps(data, ensure_ascii=False)

    @app.route("/api/yandex/credentials", method="POST")
    def api_yandex_creds():
        body = request.json or {}
        ok, code, msg = engine.apply_yandex_credentials(
            str(body.get("api_key", "")).strip(),
            str(body.get("folder_id", "")).strip(),
            str(body.get("auth_mode", "api_key")),
        )
        return _json({"ok": ok, "code": code, "message": msg})

    @app.route("/api/yandex/status")
    def api_yandex_status():
        return _json(engine.yandex_status())

    @app.route("/api/gigachat/credentials", method="POST")
    def api_gigachat_creds():
        body = request.json or {}
        ok, code, msg = engine.apply_gigachat_credentials(
            str(body.get("authorization_key", "")).strip(),
            str(body.get("scope", "")).strip() or None,
        )
        return _json({"ok": ok, "code": code, "message": msg})

    @app.route("/api/gigachat/status")
    def api_gigachat_status():
        return _json(engine.gigachat_status())

    @app.route("/api/yandex/voices")
    def api_yandex_voices():
        from yandex_ai import voices
        return _json({"available": voices.AVAILABLE_VOICES,
                      "defaults": voices.DEFAULT_PERSONA_VOICE})

    # Статические ассеты экспортированного UI (/_next/*, иконки, 404.html и т.д.).
    # Регистрируется ПОСЛЕДНИМ: Bottle матчит статические и ранее объявленные
    # правила (/, /api/*) раньше этого wildcard, так что API не перехватывается.
    @app.route("/<filepath:path>")
    def static_assets(filepath):
        return static_file(filepath, root=webui_dir)

    return app


def start_api_server(engine, settings: dict, port: int = API_PORT,
                     base_dir: str | None = None) -> LocalWebServer:
    """Bind and start the local HTTP server, returning its lifecycle owner."""
    root = base_dir or os.path.dirname(os.path.abspath(__file__))
    app = create_app(engine, settings, root)
    # Адрес привязки выбирается ОДИН раз на старте: перевесить уже слушающий
    # сокет на лету нельзя, а делать вид, что настройка применилась, — врать.
    # UI поэтому и говорит, что второй экран включается после перезапуска.
    server = LocalWebServer(
        app,
        host=bind_host(bool(settings.get("remote_access_enabled", False))),
        port=port,
    )
    server.start()
    # Движок обязан знать, что сокет открыл НА САМОМ ДЕЛЕ, а не что просили в
    # настройках: между этими двумя вещами целый перезапуск, и раньше панель
    # второго экрана показывала работающий адрес, пока порт висел на 127.0.0.1.
    # getattr — на случай тестовых заглушек движка без этого метода.
    report = getattr(engine, "set_bound_host", None)
    if callable(report):
        report(server.host)
    return server
