"""Гейт удалённого доступа в самом HTTP-сервере.

Политика проверена отдельно (tests/test_remote_access.py) — здесь проверяется
ПРОВОДКА: что гейт реально стоит перед всеми ручками, читает токен из заголовка
и из query, и что локальный клиент ничего не заметил. Корректная политика,
которую забыли повесить на приложение, — ровно тот класс багов, который в этом
проекте стоит дороже всего.
"""
import io
import json

import pytest

import web_server


class _Engine:
    """Минимальная заглушка: гейт срабатывает раньше, чем ручка тронет движок."""

    settings = {"persona": "tv"}

    class _RadioSession:
        def set_persona_provider(self, fn):
            pass

    radio_session = _RadioSession()

    def get_state(self, radio_since=None):
        return {"ok": True}

    def apply_settings(self, body):
        self.applied = body

    def apply_yandex_credentials(self, *a, **kw):
        return True, "OK", ""


def _app(tmp_path, enabled=True, token="secret123"):
    settings = {"remote_access_enabled": enabled, "remote_access_token": token}
    return web_server.create_app(_Engine(), settings, str(tmp_path))


def _call(app, path, remote_addr, method="GET", token_header=None, query="",
          forwarded_for=None):
    """Один WSGI-запрос без поднятия сокета.

    `start_response` обязан принимать третий аргумент `exc_info`, а в environ
    обязаны быть `wsgi.errors` и файлоподобный `wsgi.input` — иначе Bottle
    падает внутри обработки ошибки, и тест «проходит» по совсем другой
    причине, чем думает автор."""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "REMOTE_ADDR": remote_addr,
        "SERVER_NAME": "test", "SERVER_PORT": "8765",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "CONTENT_LENGTH": "0",
    }
    if token_header:
        environ["HTTP_X_SPOTTER_TOKEN"] = token_header
    if forwarded_for:
        environ["HTTP_X_FORWARDED_FOR"] = forwarded_for
    body = b"".join(app(environ, start_response) or [])
    return captured.get("status"), body


def test_local_client_is_served(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/state", "127.0.0.1")
    assert status == 200


def test_remote_without_token_gets_401(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/state", "192.168.1.10")
    assert status == 401


def test_remote_with_header_token_is_served(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/state", "192.168.1.10",
                      token_header="secret123")
    assert status == 200


def test_remote_with_query_token_is_served(tmp_path):
    """Телефон должен как-то загрузить саму страницу — на первом заходе
    заголовок поставить неоткуда."""
    status, _ = _call(_app(tmp_path), "/api/state", "192.168.1.10",
                      query="token=secret123")
    assert status == 200


def test_remote_with_wrong_token_gets_401(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/state", "192.168.1.10",
                      token_header="nope")
    assert status == 401


def test_remote_is_denied_while_the_feature_is_off(tmp_path):
    app = _app(tmp_path, enabled=False)
    status, _ = _call(app, "/api/state", "192.168.1.10", token_header="secret123")
    assert status == 401


def test_credentials_are_refused_from_remote_even_with_a_token(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/yandex/credentials", "192.168.1.10",
                      method="POST", token_header="secret123")
    assert status == 401


def test_credentials_still_work_locally(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/yandex/credentials", "127.0.0.1",
                      method="POST")
    assert status != 401


def test_settings_write_from_remote_needs_a_token(tmp_path):
    app = _app(tmp_path)
    assert _call(app, "/api/settings", "192.168.1.10", method="POST")[0] == 401
    assert _call(app, "/api/settings", "192.168.1.10", method="POST",
                 token_header="secret123")[0] == 200


def test_denied_response_does_not_leak_the_token(tmp_path):
    _status, body = _call(_app(tmp_path), "/api/state", "192.168.1.10")
    assert b"secret123" not in body


# ── Подделка адреса заголовком ───────────────────────────────────────────────
# Гейт обязан смотреть на адрес СОКЕТА, а не на то, что клиент о себе написал.
# `request.remote_addr` в Bottle читает `X-Forwarded-For` раньше `REMOTE_ADDR`
# (BaseRequest.remote_route), и на этом гейт держался ровно до этих тестов:
# один заголовок отправлял чужого в ветку «локальный разрешён ВСЕГДА».

def test_forged_forwarded_for_does_not_grant_local_access(tmp_path):
    status, _ = _call(_app(tmp_path), "/api/state", "192.168.1.10",
                      forwarded_for="127.0.0.1")
    assert status == 401


def test_forged_forwarded_for_does_not_unlock_credentials(tmp_path):
    """Худший случай: ключи Yandex/GigaChat запрещены снаружи даже с ВЕРНЫМ
    токеном, поэтому подделка адреса не должна открывать их тем более."""
    status, _ = _call(_app(tmp_path), "/api/yandex/credentials", "192.168.1.10",
                      method="POST", token_header="secret123",
                      forwarded_for="127.0.0.1")
    assert status == 401


def test_forged_forwarded_for_does_not_expose_the_token_endpoint(tmp_path):
    status, body = _call(_app(tmp_path), "/api/remote-access", "192.168.1.10",
                         forwarded_for="127.0.0.1")
    assert status == 401
    assert b"secret123" not in body


def test_forged_forwarded_for_is_denied_while_the_feature_is_off(tmp_path):
    """Выключенная фича — самый частый случай на релизе: порт тогда висит на
    127.0.0.1, но политика обязана держаться и сама по себе."""
    status, _ = _call(_app(tmp_path, enabled=False), "/api/state",
                      "192.168.1.10", forwarded_for="127.0.0.1")
    assert status == 401


def test_forwarded_for_does_not_break_a_real_local_client(tmp_path):
    """Обратная сторона фикса: локальный клиент остаётся локальным, даже если
    заголовок в запросе оказался (браузерное расширение, отладочный прокси)."""
    status, _ = _call(_app(tmp_path), "/api/state", "127.0.0.1",
                      forwarded_for="10.0.0.7")
    assert status == 200
