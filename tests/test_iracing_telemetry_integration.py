"""Интеграционный тест core/iracing_telemetry.py::IRacingTelemetry с
подменённым (мок) модулем irsdk — без реального pyirsdk/живой сессии iRacing.

В отличие от tests/test_iracing_packets.py (чистые dict -> dict функции),
здесь проверяется сама обёртка над SDK: connected/disconnected переходы,
форма (data, connected), сбор _drivers из DriverInfo, и деградация, когда
pyirsdk вообще не установлен — три сценария из "Логирование и деградация"
(design doc 2026-07-19-iracing-telemetry-mapping-design.md).
"""
from core import iracing_telemetry as it


class _FakeIRSDK:
    """Мок pyirsdk.IRSDK: управляемые is_initialized/is_connected + словарь
    переменных, отдаваемый через __getitem__ (как настоящий SDK)."""

    def __init__(self, connected: bool = True, drivers: list | None = None,
                 values: dict | None = None):
        self.is_initialized = connected
        self.is_connected = connected
        self._drivers = drivers if drivers is not None else []
        self._values = values if values is not None else {}
        self.startup_calls = 0
        self.shutdown_calls = 0
        self.freeze_calls = 0

    def startup(self) -> bool:
        self.startup_calls += 1
        self.is_initialized = True
        self.is_connected = True
        return True

    def shutdown(self):
        self.shutdown_calls += 1

    def freeze_var_buffer_latest(self):
        self.freeze_calls += 1

    def __getitem__(self, key):
        if key == "DriverInfo":
            return {"Drivers": self._drivers}
        return self._values.get(key)


def _make_source(monkeypatch, fake_ir):
    """core.iracing_telemetry.irsdk подменяется на объект с .IRSDK() -> fake_ir,
    без реального импорта pyirsdk (сценарий CI/линукс-раннера без Windows)."""
    fake_module = type("FakeIrsdkModule", (), {"IRSDK": lambda: fake_ir})
    monkeypatch.setattr(it, "irsdk", fake_module)
    return it.IRacingTelemetry(poll_hz=1000.0)  # быстрый интервал — тест не ждёт


def test_poll_returns_disconnected_when_pyirsdk_not_installed(monkeypatch):
    """Сценарий 1 из design doc: пакет не установлен -> irsdk=None в модуле ->
    поведение идентично таймауту UDP в core/telemetry.py (connected=False)."""
    monkeypatch.setattr(it, "irsdk", None)
    source = it.IRacingTelemetry()
    data, connected = source.poll()
    assert data is None
    assert connected is False


def test_poll_returns_disconnected_when_iracing_not_running(monkeypatch):
    """Сценарий 2: pyirsdk установлен, но startup() не может подключиться
    (iRacing не запущен) — poll() не должен падать, только (None, False)."""
    fake_ir = _FakeIRSDK(connected=False)
    fake_ir.startup = lambda: False  # имитация "sim не запущен"
    source = _make_source(monkeypatch, fake_ir)

    data, connected = source.poll()

    assert data is None
    assert connected is False


def test_poll_connects_and_returns_expected_shape(monkeypatch):
    """Подключённая сессия: .poll() отдаёт (dict, True) с ожидаемыми ключами,
    включая _drivers, собранный из DriverInfo.Drivers (не polled var)."""
    values = {
        "CarIdxPosition": [1, 2],
        "CarIdxLap": [3, 3],
        "CarIdxOnPitRoad": [False, False],
        "CarIdxLapDistPct": [0.1, 0.2],
        "PlayerCarIdx": 0,
        "Speed": 55.0,
        "Gear": 4,
    }
    drivers = [{"CarIdx": 0, "UserName": "Test Driver", "TeamName": "", "CarNumber": "7"}]
    fake_ir = _FakeIRSDK(connected=True, drivers=drivers, values=values)
    source = _make_source(monkeypatch, fake_ir)

    data, connected = source.poll()

    assert connected is True
    assert data is not None
    for key in values:
        assert data[key] == values[key]
    assert data["_drivers"] == drivers
    assert fake_ir.freeze_calls == 1


def test_poll_reconnect_after_disconnect_calls_startup_again(monkeypatch):
    """Сценарий 3: связь была, потом пропала (is_connected -> False), потом
    восстановилась — .poll() должен вызвать shutdown()+startup() заново на
    цикле восстановления, а не тихо повторно использовать старый handle."""
    fake_ir = _FakeIRSDK(connected=True)
    source = _make_source(monkeypatch, fake_ir)

    data, connected = source.poll()
    assert connected is True
    assert source._was_connected is True

    fake_ir.is_connected = False
    data, connected = source.poll()
    assert connected is True  # startup() внутри poll() тут же восстанавливает
    assert fake_ir.shutdown_calls == 1
    assert fake_ir.startup_calls == 1


def test_poll_read_exception_degrades_to_disconnected(monkeypatch):
    """Если чтение переменных бросает исключение (повреждённый SDK-хендл и
    т.п.), poll() логирует и отдаёт (None, False) вместо падения всего
    _iracing_telemetry_loop в core/engine.py.

    Дандер-методы Python ищет на КЛАССЕ, а не на инстансе — переопределить
    __getitem__ присваиванием на fake_ir не сработает (тихо не сработает
    исключение), поэтому нужен отдельный подкласс с реальным переопределением.
    """
    class _BoomingIRSDK(_FakeIRSDK):
        def __getitem__(self, key):
            raise RuntimeError("shared memory read failed")

    fake_ir = _BoomingIRSDK(connected=True)
    source = _make_source(monkeypatch, fake_ir)

    data, connected = source.poll()

    assert data is None
    assert connected is False


def test_listen_generator_yields_poll_shaped_tuples(monkeypatch):
    """.listen() — тонкий генератор поверх .poll(), форма (data, connected)
    совпадает с core.telemetry.Telemetry.listen() для module-swap seam в
    core/engine.py."""
    fake_ir = _FakeIRSDK(connected=True)
    source = _make_source(monkeypatch, fake_ir)

    gen = source.listen()
    data, connected = next(gen)

    assert connected is True
    assert isinstance(data, dict)
