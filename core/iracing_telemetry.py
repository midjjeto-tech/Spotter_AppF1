"""
core/iracing_telemetry.py
==========================
Обёртка над iRacing SDK (pyirsdk) — общая память (memory-mapped file), а НЕ
push-пакеты по UDP, как в core/telemetry.py. Поэтому вместо блокирующего
recvfrom с таймаутом здесь ОПРОС (poll) с фиксированным интервалом, а
connected-статус берётся из ir.is_initialized/is_connected самого SDK.

.listen() отдаёт тот же (data, connected) формат, что и Telemetry.listen(),
чтобы F1Engine._iracing_telemetry_loop мог использовать тот же паттерн
итерации, что и _telemetry_loop. См. план
C:\\Users\\Artem\\.claude\\plans\\peaceful-humming-teacup.md, Phase 1.
"""
from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger(__name__)

try:
    import irsdk
except ImportError:
    # pyirsdk не установлен (не Windows / нет зависимости) — деградируем так
    # же, как F1Engine деградирует при отсутствии UDP-пакетов: connected=False.
    irsdk = None
    _log.warning(
        "iRacing: пакет pyirsdk не установлен — источник телеметрии "
        "'iracing' будет постоянно недоступен (connected=False). "
        "pip install -r requirements.txt (см. пин pyirsdk==1.1.7)."
    )

# Переменные iRacing, которые нужны для Phase 1 (позиция/круг/пит/скорость/
# передача/список пилотов). Fuel/шины/повреждения/погода/события — Phase 2/3.
_POLL_VARS = (
    "CarIdxPosition", "CarIdxLap", "CarIdxOnPitRoad", "CarIdxLapDistPct",
    "PlayerCarIdx", "Speed", "Gear",
)


class IRacingTelemetry:

    def __init__(self, poll_hz: float = 20.0):
        self._poll_interval = 1.0 / poll_hz
        self._ir = irsdk.IRSDK() if irsdk is not None else None
        self._was_connected = False
        self._closed = threading.Event()

    def poll(self) -> tuple[dict | None, bool]:
        """Один снимок телеметрии: (vars_dict, connected). В отличие от
        Telemetry.listen() здесь нет сетевого таймаута — вызывающий код сам
        выдерживает паузу между тиками (см. .listen() ниже)."""
        if self._ir is None:
            return None, False

        currently_connected = self._ir.is_initialized and self._ir.is_connected
        if not currently_connected:
            self._ir.shutdown()
            if self._was_connected:
                _log.info("iRacing: связь потеряна")
            self._was_connected = False
            if not (self._ir.startup() and self._ir.is_initialized and self._ir.is_connected):
                return None, False

        if not self._was_connected:
            _log.info("iRacing: подключено")
        self._was_connected = True

        try:
            self._ir.freeze_var_buffer_latest()
            data = {name: self._ir[name] for name in _POLL_VARS}
            data["_drivers"] = self._session_drivers()
        except Exception:
            _log.exception("iRacing: ошибка чтения переменных телеметрии")
            return None, False

        return data, True

    def _session_drivers(self) -> list[dict]:
        """Список пилотов сессии из YAML session info (DriverInfo.Drivers) —
        в отличие от живых переменных выше, это не polled var, а секция
        конфигурации сессии, которую SDK парсит отдельно."""
        info = self._ir["DriverInfo"] if self._ir is not None else None
        if not info:
            return []
        return info.get("Drivers", [])

    def listen(self, stop_event: threading.Event | None = None):
        """Генератор (data, connected), формой совместимый с
        core.telemetry.Telemetry.listen()."""
        while not self._closed.is_set() and not (stop_event and stop_event.is_set()):
            data, connected = self.poll()
            yield data, connected
            if self._closed.wait(self._poll_interval):
                break

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._ir is not None:
            try:
                self._ir.shutdown()
            except Exception:  # noqa: BLE001
                _log.exception("iRacing: ошибка завершения SDK")
