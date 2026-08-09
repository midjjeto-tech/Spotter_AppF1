"""Готов ли Spotter к работе — один снимок, понятный человеку.

Зачем отдельный модуль, если `/api/state` и так отдаёт `connected`, `llm_engine`
и `yandex_ok`. Потому что `connected: false` отвечает сразу на три разных
вопроса — «игра не запущена», «UDP выключен в настройках игры», «порт занят
чужим приложением» — а совет пользователю в этих случаях нужен противоположный.
Визард первого запуска, построенный на одном булеве, выродился бы в тот самый
абзац текста «проверьте всё подряд», ради ухода от которого он и делается.

`collect()` — чистая функция без I/O: все факты передаются аргументами. Так
коды проверяются питоновскими тестами, а не глазами в браузере, и тот же снимок
годится для поддержки («пришлите скриншот диагностики» вместо разбора логов).

ЧЕСТНОСТЬ КОДОВ. `ok` означает, что подсистема реально работает СЕЙЧАС, а не
что она настроена. Телеметрия без свежих пакетов — `waiting`, а не `ok`, даже
когда сокет открыт: игра может быть не запущена. Голос без ключа — `piper`,
а не `none`: офлайн-резерв действительно звучит, и врать пользователю, что
озвучки нет, нельзя ровно так же, как нельзя обещать несуществующее.
"""
from __future__ import annotations

import time

# Сколько секунд без пакетов считаем «связь ещё жива». Сокет отдаёт таймаут раз
# в 5 с (core/telemetry.py), поэтому окно должно быть заметно шире одного тика,
# иначе статус будет мигать между ok и waiting на ровном месте.
PACKET_FRESH_S = 12.0

# Коды, при которых виноват не пользователь и не игра, а другое приложение или
# отсутствующая зависимость. UI показывает их отдельной плашкой с конкретным
# советом, а не общим «нет связи».
SOURCE_FAULT_CODES = frozenset({"port_busy", "bind_failed", "iracing_no_lib"})


def _telemetry(*, source_code: str, source_detail: str, connected: bool,
               last_packet_at: float, source: str, udp_ip: str, udp_port: int,
               now: float) -> dict:
    if source_code in SOURCE_FAULT_CODES:
        return {"status": source_code, "detail": source_detail,
                "source": source, "udp_ip": udp_ip, "udp_port": udp_port}

    fresh = bool(last_packet_at) and (now - last_packet_at) <= PACKET_FRESH_S
    status = "ok" if (connected and fresh) else "waiting"
    return {"status": status, "detail": "", "source": source,
            "udp_ip": udp_ip, "udp_port": udp_port}


def _voice(*, engine_name: str, yandex_healthy: bool, available: bool) -> dict:
    """Каким голосом приложение говорит ПРЯМО СЕЙЧАС.

    Четыре состояния, а не три: офлайн-голос Piper — отдельный компонент
    установщика (он под GPL и живёт вне EXE, см. NOTICE), и его может не быть.
    Тогда остаётся системный голос Windows. Схлопывать `system` в `piper`
    нельзя: пользователь слышит разницу мгновенно, а UI обещал бы не то.
    """
    if not available:
        return {"status": "none", "detail": engine_name}
    name = (engine_name or "").lower()
    if yandex_healthy and "yandex" in name:
        return {"status": "yandex", "detail": engine_name}
    if "piper" in name:
        return {"status": "piper", "detail": engine_name}
    return {"status": "system", "detail": engine_name}


def _brain(*, provider: str, provider_connected: bool) -> dict:
    if not provider_connected:
        # Не ошибка, а рабочий бесплатный режим: commentator/brain.py берёт
        # шаблон для реального события. Молчит только ambient-тик.
        return {"status": "templates", "detail": ""}
    return {"status": provider, "detail": ""}


def collect(*, source_code: str, source_detail: str, connected: bool,
            last_packet_at: float, telemetry_source: str,
            udp_ip: str, udp_port: int,
            voice_engine: str, voice_available: bool, yandex_healthy: bool,
            llm_provider: str, llm_connected: bool,
            mic_devices: int, hotkeys_ready: bool,
            app_version: str = "",
            now: float | None = None) -> dict:
    """Снимок готовности. Все аргументы — уже добытые факты, без обращений вовне."""
    moment = time.time() if now is None else now

    checks = {
        "telemetry": _telemetry(
            source_code=source_code, source_detail=source_detail,
            connected=connected, last_packet_at=last_packet_at,
            source=telemetry_source, udp_ip=udp_ip, udp_port=udp_port,
            now=moment),
        "voice": _voice(engine_name=voice_engine, yandex_healthy=yandex_healthy,
                        available=voice_available),
        "brain": _brain(provider=llm_provider, provider_connected=llm_connected),
        "mic": {"status": "ok" if mic_devices > 0 else "no_device",
                "detail": str(mic_devices)},
        "hotkeys": {"status": "ok" if hotkeys_ready else "unavailable",
                    "detail": ""},
    }

    # «Готов» — это только про то, без чего приложение не выполняет свою работу:
    # телеметрия и хоть какая-то озвучка. Ключи, микрофон и горячие клавиши в
    # это условие НЕ входят: без них продукт беднее, но работает, и визард не
    # имеет права держать пользователя ради них.
    checks["ready"] = (checks["telemetry"]["status"] == "ok"
                       and checks["voice"]["status"] != "none")
    # Версия — не проверка, а факт для поддержки, поэтому лежит рядом с
    # проверками, а НЕ внутри них: попасть в `ready` она не должна.
    checks["app_version"] = app_version
    return checks
