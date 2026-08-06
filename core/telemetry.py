"""
core/telemetry.py
==================
Тонкая обёртка над UDP-сокетом. Отдаёт сырые пакеты, а заодно сообщает,
жива ли связь с игрой (через таймаут) — это используется в UI для "огней".
"""

import errno
import socket
import threading

# WSAEADDRINUSE. Windows не всегда кладёт POSIX-код в errno у сокет-ошибок,
# поэтому сверяем оба: errno.EADDRINUSE (98) и winerror 10048.
_WSAEADDRINUSE = 10048


class TelemetryUnavailable(Exception):
    """Источник недоступен по ПОНЯТНОЙ причине, а не из-за бага в нас.

    Отдельный тип нужен, чтобы вызывающий код мог показать пользователю
    внятную строку вместо traceback'а. Раньше bind() на занятом порту ронял
    поток телеметрии целиком: в оконном EXE traceback уходил в никуда, а UI
    навсегда оставался в «нет связи» без единого намёка на причину.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class Telemetry:

    def __init__(self, ip: str, port: int, timeout: float = 5.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((ip, port))
        except OSError as exc:
            # Сокет закрываем сами: без этого дескриптор течёт на каждой
            # попытке переподключения (а мы теперь ретраим раз в 5 секунд).
            self.sock.close()
            busy = (exc.errno == errno.EADDRINUSE
                    or getattr(exc, "winerror", None) == _WSAEADDRINUSE)
            code = "port_busy" if busy else "bind_failed"
            raise TelemetryUnavailable(code, f"{ip}:{port} — {exc}") from exc
        self.sock.settimeout(timeout)
        self._closed = threading.Event()

    def listen(self, stop_event: threading.Event | None = None):
        """Генератор: (data, connected). При таймауте data=None, connected=False."""
        while not self._closed.is_set() and not (stop_event and stop_event.is_set()):
            try:
                data, _ = self.sock.recvfrom(2048)
                yield data, True
            except socket.timeout:
                yield None, False
            except OSError:
                if self._closed.is_set() or (stop_event and stop_event.is_set()):
                    break
                raise

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.close()
        except OSError:
            pass
