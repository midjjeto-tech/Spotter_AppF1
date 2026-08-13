"""Второй экран: токен обязан доехать до СТИЛЕЙ и СКРИПТОВ, а не только до fetch.

Эти тесты — про проводку, а не про политику: `core/remote_access.py` со своей
задачей справлялся, а фича всё равно не работала. Токен ехал двумя путями —
один раз в адресе (`/?token=…`) и заголовком `X-Spotter-Token` в fetch-ах, —
а CSS, JS и шрифты браузер запрашивает САМ, без заголовка и без query. Гейт
стоит перед всей раздачей, включая статику, поэтому телефон получал документ
(200) и 401 на каждый его подресурс: голый HTML без стилей и без гидратации.

Поэтому здесь ходят настоящие WSGI-запросы к настоящему приложению и смотрят на
заголовки ответа. Тест только на `RemoteAccessPolicy.allows()` этот класс
дефектов не ловит в принципе.
"""
import io
from types import SimpleNamespace

import pytest

import web_server
from core.remote_access import COOKIE_NAME

TOKEN = "secret-token-123"
PHONE = "192.168.1.50"

#: Любой подресурс страницы. Браузер просит его сам — ни заголовка, ни query.
ASSET = "/_next/static/chunks/app.css"


@pytest.fixture
def app(tmp_path):
    """Приложение с включённым вторым экраном и настоящей статикой на диске."""
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    asset = tmp_path / "_next" / "static" / "chunks"
    asset.mkdir(parents=True)
    (asset / "app.css").write_text("body{}", encoding="utf-8")

    engine = SimpleNamespace(
        radio_session=SimpleNamespace(set_persona_provider=lambda _provider: None),
        settings={},
        # Единственная ручка движка, которую трогают эти тесты: нужна живая
        # 200-ка, чтобы проверить, что куки хватает и для fetch-ов.
        get_hotkey_status=lambda: {"enabled": True},
    )
    settings = {"remote_access_enabled": True, "remote_access_token": TOKEN}
    built = web_server.create_app(engine, settings, str(tmp_path))
    built.catchall = False
    return built


def call(app, path, *, query="", addr=PHONE, cookie=None, method="GET"):
    """Одиночный WSGI-вызов. Возвращает (статус, заголовки, тело)."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "REMOTE_ADDR": addr,
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "8765",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "http",
        "CONTENT_LENGTH": "0",
    }
    if cookie is not None:
        environ["HTTP_COOKIE"] = cookie
    captured: dict = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def set_cookie_header(headers) -> str:
    values = [value for name, value in headers if name.lower() == "set-cookie"]
    return values[0] if values else ""


def issued_cookie(headers) -> str:
    """Кука из ответа в том виде, в каком её вернёт браузер следующим запросом."""
    return set_cookie_header(headers).split(";", 1)[0]


# ── Документ выдаёт куку ─────────────────────────────────────────────────────

def test_document_with_valid_token_issues_a_cookie(app):
    """Именно на статике `index.html` кука и обязана появиться.

    Ловушка Bottle 0.13: `HTTPResponse.apply()` перезатирает `_headers` и
    `_cookies` глобального ответа целиком, и вызывается ДВАЖДЫ — в `_handle()`
    и ещё раз в `_cast()`, то есть уже после хуков. `static_file()` возвращает
    как раз `HTTPResponse`, поэтому кука, выставленная и в `before_request`, и
    в `after_request`, молча исчезает ровно здесь — на том единственном ответе,
    который обязан её принести. Проверено обоими способами, прежде чем кука
    переехала на сам объект ответа."""
    status, headers, _ = call(app, "/", query=f"token={TOKEN}")

    assert status.startswith("200")
    assert COOKIE_NAME in set_cookie_header(headers)


def test_cookie_is_not_readable_by_scripts_and_not_sent_cross_site(app):
    _status, headers, _ = call(app, "/", query=f"token={TOKEN}")
    raw = set_cookie_header(headers).lower()

    assert "httponly" in raw
    assert "samesite=strict" in raw
    # `secure` сделала бы куку неотправляемой: второй экран живёт по HTTP в LAN.
    assert "secure" not in raw


def test_wrong_token_gets_no_cookie_and_no_page(app):
    status, headers, _ = call(app, "/", query="token=wrong")

    assert status.startswith("401")
    assert set_cookie_header(headers) == ""


# ── Подресурсы: ради этого всё и затевалось ──────────────────────────────────

def test_asset_is_denied_without_the_cookie(app):
    """Исходный дефект: телефон получал документ и 401 на каждый его подресурс."""
    status, _headers, _ = call(app, ASSET)

    assert status.startswith("401")


def test_asset_is_served_with_the_cookie_from_the_document(app):
    _status, headers, _ = call(app, "/", query=f"token={TOKEN}")

    status, _headers, body = call(app, ASSET, cookie=issued_cookie(headers))

    assert status.startswith("200")
    assert body == b"body{}"


def test_reload_of_a_clean_url_survives(app):
    """Второй дефект: токен вычищается из адресной строки после загрузки, и F5
    по «чистому» адресу давал 401 уже на самом документе."""
    _status, headers, _ = call(app, "/", query=f"token={TOKEN}")

    status, _headers, _ = call(app, "/", cookie=issued_cookie(headers))

    assert status.startswith("200")


def test_api_is_reachable_with_the_cookie(app):
    """Куки достаточно и для fetch-ов: заголовок `X-Spotter-Token` остаётся
    вторым путём, но больше не единственным."""
    _status, headers, _ = call(app, "/", query=f"token={TOKEN}")

    status, _headers, _ = call(app, "/api/hotkeys/status",
                               cookie=issued_cookie(headers))

    assert status.startswith("200")


# ── Кука не расширяет права ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/yandex/credentials",
                                  "/api/gigachat/credentials",
                                  "/api/remote-access"])
def test_cookie_does_not_open_local_only_paths(app, path):
    """Ключи Yandex/GigaChat и сам токен остаются доступны только с этой машины.
    Кука — способ донести токен, а не повышение прав."""
    _status, headers, _ = call(app, "/", query=f"token={TOKEN}")

    status, _headers, _ = call(app, path, cookie=issued_cookie(headers),
                               method="POST")

    assert status.startswith("401")


def test_stale_cookie_is_rejected_after_the_token_changes(app):
    status, _headers, _ = call(app, ASSET, cookie=f"{COOKIE_NAME}=old-token")

    assert status.startswith("401")


def test_disabled_feature_ignores_the_cookie(tmp_path):
    """Выключенный второй экран токен не стирает — но и не пускает по нему."""
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    engine = SimpleNamespace(
        radio_session=SimpleNamespace(set_persona_provider=lambda _provider: None),
        settings={},
    )
    built = web_server.create_app(
        engine, {"remote_access_enabled": False, "remote_access_token": TOKEN},
        str(tmp_path))
    built.catchall = False

    status, headers, _ = call(built, "/", query=f"token={TOKEN}")

    assert status.startswith("401")
    assert set_cookie_header(headers) == ""


# ── Локальный клиент ─────────────────────────────────────────────────────────

def test_loopback_still_needs_nothing(app):
    """Само приложение ходит в своё же API без токена — и куки ему не нужны."""
    status, headers, _ = call(app, "/", addr="127.0.0.1")

    assert status.startswith("200")
    # Ставить куку локальному клиенту незачем: он и так разрешён всегда.
    assert set_cookie_header(headers) == ""
