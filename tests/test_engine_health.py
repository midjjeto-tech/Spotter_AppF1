"""Health-monitor «мягкая проверка» Yandex (фикс «моргания» + авто-восстановление)."""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    # Один движок на модуль: F1Engine поднимает Voice (загрузка Piper) — не плодим
    # тяжёлые фоновые потоки на каждый тест. Каждый тест сам задаёт health-состояние.
    import core.engine as m
    orig = m.yc.load
    m.yc.load = lambda: None        # без креденшелов — Yandex-клиент не поднимается
    try:
        yield F1Engine({})
    finally:
        m.yc.load = orig


def test_soft_check_needs_three_failures(engine):
    engine._yandex_healthy = True
    engine._yandex_fail_streak = 0
    # 2 сбоя подряд — одиночные блипы, статус НЕ роняем
    engine.record_yandex_result(False)
    engine.record_yandex_result(False)
    assert engine._yandex_healthy is True
    # 3-й сбой подряд — роняем
    engine.record_yandex_result(False)
    assert engine._yandex_healthy is False
    assert engine._yandex_status["connected"] is False
    assert engine.get_state()["llm_engine"] == "Шаблоны"


def test_success_recovers_immediately(engine):
    engine._yandex_healthy = False
    engine._yandex_fail_streak = 9
    engine.record_yandex_result(True)
    assert engine._yandex_healthy is True
    assert engine._yandex_fail_streak == 0
    assert engine._yandex_status["connected"] is True
    assert engine.get_state()["llm_engine"] == "YandexGPT"


def test_blip_after_success_does_not_drop(engine):
    engine._yandex_healthy = True
    engine._yandex_fail_streak = 2          # был на грани
    engine.record_yandex_result(True)       # успех сбрасывает счётчик
    assert engine._yandex_fail_streak == 0
    engine.record_yandex_result(False)      # одиночный блип после восстановления
    assert engine._yandex_healthy is True   # не падаем


def test_full_validate_syncs_llm_engine_on_failure(engine):
    """_apply_full_validate — второе место, где _yandex_healthy может
    флипнуться (стартовая проба), должно держать llm_engine в паре с
    yandex_ok так же, как record_yandex_result."""
    client = object()
    engine._yandex_client = client
    engine._yandex_healthy = True
    engine._apply_full_validate(client, False, "YANDEX_NETWORK_ERROR", "boom")
    assert engine._yandex_healthy is False
    assert engine.get_state()["yandex_ok"] is False
    assert engine.get_state()["llm_engine"] == "Шаблоны"


def test_full_validate_syncs_llm_engine_on_recovery(engine):
    client = object()
    engine._yandex_client = client
    engine._yandex_healthy = False
    engine._apply_full_validate(client, True, "OK", "ключ проверен")
    assert engine._yandex_healthy is True
    assert engine.get_state()["yandex_ok"] is True
    assert engine.get_state()["llm_engine"] == "YandexGPT"


def test_health_pushed_to_voice_on_flip(engine, monkeypatch):
    pushed = []
    monkeypatch.setattr(engine.voice, "set_yandex_healthy", lambda ok: pushed.append(ok))
    engine._yandex_healthy = True
    engine._yandex_fail_streak = 0
    for _ in range(3):
        engine.record_yandex_result(False)  # 3 сбоя -> flip в False (1 пуш)
    engine.record_yandex_result(True)       # успех -> flip в True (2-й пуш)
    assert pushed == [False, True]
