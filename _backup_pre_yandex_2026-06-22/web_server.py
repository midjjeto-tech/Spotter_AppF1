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
from bottle import Bottle, WSGIRefServer, request, response, static_file

from analytics import archive as _archive
from analytics.loader import load_f1_session, TRACK_ID_TO_GP
from analytics.normalizer import normalize as _normalize
from analytics.comparator import compare as _compare


class _ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _ThreadedServer(WSGIRefServer):
    def run(self, handler):
        make_server(self.host, self.port, handler, _ThreadedWSGIServer).serve_forever()

API_PORT = 8765


def _json(data: dict) -> str:
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def create_app(engine, settings: dict, base_dir: str) -> Bottle:
    app = Bottle()

    @app.route("/")
    def index():
        return static_file("index.html", root=base_dir)

    @app.route("/api/state")
    def api_state():
        state = engine.get_state()
        mem = psutil.virtual_memory()
        state["cpu"] = f"{psutil.cpu_percent(interval=None):.0f}%"
        state["ram"] = f"{mem.percent:.0f}% ({round(mem.used / (1024 ** 3), 1)} GB)"
        state["settings"] = dict(settings)
        return _json(state)

    @app.route("/api/settings", method="POST")
    def api_settings():
        body = request.json or {}
        if body:
            engine.apply_settings(body)
            settings.update(body)
        return _json({"ok": True})

    @app.route("/api/test_voice")
    def api_test_voice():
        voice = engine.voice
        if not voice.is_available:
            return _json({"ok": False, "error": voice.status_message})

        def _run():
            voice.test_say("Проверка радио. Голос работает, поехали!")

        threading.Thread(target=_run, daemon=True).start()
        return _json({"ok": True, "engine": voice.engine_name})

    @app.route("/api/clear_logs")
    def api_clear_logs():
        engine.clear_feed()
        return _json({"ok": True})

    @app.route("/api/voices")
    def api_voices():
        from voice.voice_manager import voice_status
        return _json(voice_status())

    @app.route("/api/sessions", method="GET")
    def api_sessions():
        response.content_type = "application/json"
        return json.dumps(_archive.list_game_sessions(), ensure_ascii=False)

    @app.route("/api/load_f1", method="POST")
    def api_load_f1():
        response.content_type = "application/json"
        try:
            body = json.loads(request.body.read().decode("utf-8"))
            year = int(body.get("year", 2025))
            stype = str(body.get("stype", "R"))
            game_path = body.get("game_session_path", "")
        except Exception as exc:
            response.status = 400
            return json.dumps({"error": f"bad_request: {exc}"}, ensure_ascii=False)

        game = _archive.load_game_session(game_path) or {"player_laps": [], "events": []}
        try:
            track_id = int(game.get("track_id") or -1)
        except (TypeError, ValueError):
            track_id = -1

        session, err = load_f1_session(track_id, year, stype)
        if err:
            response.status = 400
            return json.dumps({"error": err}, ensure_ascii=False)

        f1_data = _normalize(session)
        entry = TRACK_ID_TO_GP.get(track_id)
        if entry:
            f1_data["event"] = entry[1]
        _archive.save_f1(track_id, year, stype, f1_data)

        compare_result = _compare(game, f1_data)
        cpath = _archive.save_compare(game_path or "no_game", track_id, year, stype, compare_result)

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

    return app


def start_api_server(engine, settings: dict, port: int = API_PORT, base_dir: str | None = None):
    """Запускает Bottle в фоновом потоке."""
    root = base_dir or os.path.dirname(os.path.abspath(__file__))
    app = create_app(engine, settings, root)

    def _run():
        app.run(host="127.0.0.1", port=port, quiet=True, server=_ThreadedServer)

    threading.Thread(target=_run, daemon=True, name="web-api").start()
    return port
