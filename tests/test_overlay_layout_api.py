"""HTTP-контракт геометрии оверлея (web_server.py, /api/overlay/*).

Проверяется через WSGI напрямую: Bottle-приложение — обычный WSGI-callable, и
поднимать ради этого настоящий сервер (порт, поток, движок) незачем. Движок
подменён заглушкой — ни один из этих маршрутов его не трогает, вся работа идёт
через core/overlay_layout.py.
"""
import io
import json
from types import SimpleNamespace

import pytest

import core.overlay_layout as overlay_layout
import web_server


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(overlay_layout, "_DIR", tmp_path / "overlay_layout")
    engine = SimpleNamespace(
        radio_session=SimpleNamespace(set_persona_provider=lambda _provider: None),
        settings={},
    )
    built = web_server.create_app(engine, {}, str(tmp_path))
    # Без catchall Bottle не превращает исключение в HTML-страницу 500 — падение
    # маршрута должно быть видно в тесте как настоящий traceback.
    built.catchall = False
    return built


def call(app, path, method="GET", body=None):
    """Одиночный WSGI-вызов; возвращает (статус, разобранный JSON)."""
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        # Гейт удалённого доступа (core/remote_access.py) закрыт по умолчанию
        # и fail-closed: без REMOTE_ADDR клиент считается чужим и получает 401.
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "8765",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(payload),
        # Именно текстовый поток: WSGI требует str, и BytesIO здесь маскирует
        # настоящую ошибку маршрута под TypeError внутри Bottle.
        "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "http",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(payload)),
    }
    captured: dict = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    return captured["status"], json.loads(raw.decode("utf-8"))


def test_layout_is_reported_for_every_hud_widget(app):
    status, payload = call(app, "/api/overlay/layout")

    assert status.startswith("200")
    # Список виджетов ведёт HUD_WIDGETS — фронт рисует ползунки ровно по нему.
    assert set(payload["widgets"]) == set(web_server._HUD_WIDGET_IDS)
    assert all(entry["scale"] == 1.0 for entry in payload["widgets"].values())
    assert payload["names"] == []


def test_scale_round_trips_through_the_api(app):
    status, payload = call(
        app, "/api/overlay/layout", "POST", {"widget": "tower", "scale": 1.4})

    assert status.startswith("200")
    assert payload["ok"] is True
    assert payload["widgets"]["tower"]["scale"] == 1.4
    assert overlay_layout.load_scale("tower") == 1.4


def test_unknown_widget_is_rejected_instead_of_creating_a_file(app):
    status, payload = call(
        app, "/api/overlay/layout", "POST", {"widget": "нет-такого", "scale": 1.2})

    assert status.startswith("400")
    assert payload["ok"] is False
    assert overlay_layout.load_scale("нет-такого") == 1.0


def test_preset_save_apply_and_delete(app):
    call(app, "/api/overlay/layout", "POST", {"widget": "lap", "scale": 1.3})
    call(app, "/api/overlay/presets", "POST", {"action": "save", "name": "Гонка"})

    call(app, "/api/overlay/layout", "POST", {"widget": "lap", "scale": 0.8})
    status, payload = call(
        app, "/api/overlay/presets", "POST", {"action": "apply", "name": "Гонка"})

    assert status.startswith("200")
    assert payload["widgets"]["lap"]["scale"] == 1.3
    assert payload["active"] == "Гонка"

    status, payload = call(
        app, "/api/overlay/presets", "POST", {"action": "delete", "name": "Гонка"})

    assert payload["names"] == []


def test_applying_a_missing_preset_answers_400(app):
    status, payload = call(
        app, "/api/overlay/presets", "POST", {"action": "apply", "name": "нет"})

    assert status.startswith("400")
    assert payload["ok"] is False


def test_reset_returns_every_widget_to_the_default_scale(app):
    call(app, "/api/overlay/layout", "POST", {"widget": "radar", "scale": 1.9})

    status, payload = call(app, "/api/overlay/layout/reset", "POST", {})

    assert status.startswith("200")
    assert payload["widgets"]["radar"]["scale"] == 1.0
