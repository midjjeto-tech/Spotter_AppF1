"""
core/telemetry.py
==================
Тонкая обёртка над UDP-сокетом. Отдаёт сырые пакеты, а заодно сообщает,
жива ли связь с игрой (через таймаут) — это используется в UI для "огней".
"""

import socket
import threading


class Telemetry:

    def __init__(self, ip: str, port: int, timeout: float = 5.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((ip, port))
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
