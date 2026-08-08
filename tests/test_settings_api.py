"""HTTP-контракт настроек (web_server.py, POST /api/settings).

Зачем отдельно от test_settings.py: там проверен МОДУЛЬ (load/save/reset), а
самые дорогие баги живут между корректным ядром и тем, что реально уезжает
наружу. Обработчик мог бы иметь собственный список разрешённых ключей, и новая
настройка молча терялась бы при зелёном test_settings.py.

Проверяется через WSGI напрямую — тем же приёмом, что и test_overlay_layout_api.py:
Bottle-приложение это обычный WSGI-callable, поднимать порт и поток незачем.
"""
import io
import json
from types import SimpleNamespace

import pytest

import core.settings as core_settings
import web_server


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Приложение вместе с теми же dict-ами, которые оно правит.

    `settings` здесь — НЕ копия: ровно этот словарь `/api/state` отдаёт оверлею,
    и проверять надо изменение именно в нём, иначе тест не отличит «настройка
    доехала» от «настройка записалась на диск и потерялась в памяти».
    """
    monkeypatch.setattr(core_settings, "_PATH", tmp_path / "settings.json")
    applied: list[dict] = []
    engine = SimpleNamespace(
        radio_session=SimpleNamespace(set_persona_provider=lambda _provider: None),
        settings={},
        apply_settings=applied.append,
    )
    settings = core_settings.load()
    app = web_server.create_app(engine, settings, str(tmp_path))
    app.catchall = False
    return SimpleNamespace(app=app, settings=settings, applied=applied)


def post(app, path, body):
    payload = json.dumps(body).encode("utf-8")
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        # Гейт удалённого доступа (core/remote_access.py) закрыт по умолчанию
        # и fail-closed: без REMOTE_ADDR клиент считается чужим и получает 401.
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "8765",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(payload),
        "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "http",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(payload)),
    }
    captured: dict = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    raw = b"".join(app(environ, start_response))
    return captured["status"], json.loads(raw.decode("utf-8"))


@pytest.mark.parametrize("theme", ["cockpit", "radio", "broadcast"])
def test_overlay_theme_reaches_memory_and_disk(harness, theme):
    status, payload = post(harness.app, "/api/settings", {"overlay_theme": theme})

    assert status.startswith("200")
    assert payload == {"ok": True}
    # В памяти — это то, что увидят восемь окон оверлея на следующем опросе
    # /api/state, то есть в течение 250 мс и без перезапуска.
    assert harness.settings["overlay_theme"] == theme
    # На диске — чтобы тема пережила перезапуск.
    assert core_settings.load()["overlay_theme"] == theme


def test_overlay_theme_does_not_disturb_other_settings(harness):
    before = dict(harness.settings)

    post(harness.app, "/api/settings", {"overlay_theme": "cockpit"})

    changed = {k for k in before if before[k] != harness.settings[k]}
    assert changed == {"overlay_theme"}
