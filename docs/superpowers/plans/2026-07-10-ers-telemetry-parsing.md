# ERS-телеметрия: парсинг + диагностика — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Распарсить `m_ersStoreEnergy`/`m_ersDeployMode` из `CarStatusData` в
`ers_percent`/`ers_deploy_mode`, с throttled DIAG-логом для живой верификации
офсетов пользователем. **Никакой advisory-логики — только парсинг.**

**Architecture:** Расширение `core/packets.py::_car_status_fields()` (общий
хелпер для игрока и соперников) двумя новыми полями на реконструированных (не
подтверждённых вживую) офсетах 37/41. Throttled `_log.warning` в
`parse_player_status` при `SPOTTER_DIAG=1`.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git — без commit-шагов.

**Спека:** `docs/superpowers/specs/2026-07-10-ers-telemetry-parsing-design.md`
— **офсеты реконструированы по знанию спецификации, требуют живой проверки
пользователем после сборки EXE** (см. спеку, раздел «Тестирование»). Это НЕ
обычная задача «готово после зелёных тестов» — юнит-тесты подтверждают только
что байты читаются с ЗАЯВЛЕННЫХ офсетов, не что офсеты верны для игры.

---

### Task 1: Парсинг + диагностика

**Files:**
- Modify: `core/packets.py`
- Modify: `tests/test_packets_gaps_tyre.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_packets_gaps_tyre.py`, сразу после существующего
`test_parse_player_status_tyre_compound` (в той же секции «parse_player_status
— топливо + маппинг визуального компаунда шин»):

```python
@pytest.mark.parametrize("deploy_mode", [0, 1, 2, 3])
def test_parse_player_status_ers_fields(deploy_mode):
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 37, 2_000_000.0)   # m_ersStoreEnergy @37 = 50%
    buf[base + 41] = deploy_mode                            # m_ersDeployMode @41

    out = packets.parse_player_status(buf, 0)
    assert out["ers_percent"] == 50.0
    assert out["ers_deploy_mode"] == deploy_mode


def test_parse_player_status_ers_missing_when_packet_too_short():
    # len(buf) = HEADER_SIZE + 41 — на 1 байт короче требуемого base+42, но
    # достаточно для fuel(base+9)/tyre(base+28): проверяем именно ERS-гейт
    # (base+42 <= len), а не более раннюю проверку в parse_player_status.
    buf = _buf(HEADER_SIZE + 41)
    struct.pack_into("<f", buf, HEADER_SIZE + 5, 42.5)
    out = packets.parse_player_status(buf, 0)
    assert out.get("fuel") == 42.5
    assert "ers_percent" not in out
    assert "ers_deploy_mode" not in out


def test_ers_diag_throttle_skips_second_call_within_window(monkeypatch):
    """DIAG-лог на КАЖДЫЙ CarStatus-пакет (десятки раз/сек) захлестнул бы лог —
    троттлинг раз в 2с. Проверяем сам факт троттлинга, не завязываясь на
    реальный logging-вывод: считаем вызовы _log.warning через monkeypatch."""
    import time as time_mod
    from core import packets as pk

    monkeypatch.setattr(pk, "_DIAG", True)
    monkeypatch.setattr(pk, "_last_ers_diag_t", 0.0)
    calls = []
    monkeypatch.setattr(pk._log, "warning", lambda *a, **kw: calls.append(a))

    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 37, 2_000_000.0)
    buf[base + 41] = 2

    pk.parse_player_status(buf, 0)                 # первый вызов — логирует
    assert len(calls) == 1

    pk.parse_player_status(buf, 0)                 # сразу второй — троттлинг молчит
    assert len(calls) == 1

    monkeypatch.setattr(pk, "_last_ers_diag_t", time_mod.time() - 3.0)  # "прошло" 3с
    pk.parse_player_status(buf, 0)
    assert len(calls) == 2
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -k ers -q`
Expected: FAIL — `KeyError: 'ers_percent'` (поля ещё не парсятся).

- [ ] **Step 3: Добавить парсинг в `core/packets.py`**

3a. Импорт `time` (в начало файла, после `import struct`):
```python
import struct
import time
```

3b. Константы (рядом с `TYRE_VISUAL`, после её определения):
```python
# Регламент FIA — максимальный запас энергии ERS, 4 МДж. Технический
# параметр реального спорта, НЕ игровой — не должен меняться между версиями
# игры (в отличие от размеров структур пакетов).
ERS_MAX_JOULES = 4_000_000.0

# Для читаемости DIAG-лога при живой сверке офсетов с HUD игры.
_ERS_MODE_LABEL = {0: "none", 1: "medium", 2: "overtake", 3: "hotlap"}

_last_ers_diag_t = 0.0
```

3c. В `_car_status_fields()`, после существующего блока шин
(`out["tyre_age"] = data[base + 27]`), добавить:
```python
    if base + 42 <= len(data):
        ers_energy = struct.unpack_from("<f", data, base + 37)[0]
        out["ers_percent"] = round(ers_energy / ERS_MAX_JOULES * 100, 1)
        out["ers_deploy_mode"] = data[base + 41]
```

3d. В `parse_player_status()`, изменить тело так, чтобы завести
throttled DIAG-лог. Текущий код:
```python
def parse_player_status(data: bytes, player_idx: int) -> dict:
    """Топливо + шины (компаунд/возраст) из Car Status (packet 7) для игрока.
    F1 25: m_fuelInTank@5, m_visualTyreCompound@26, m_tyresAgeLaps@27.

    PacketCarStatusData = header + CarStatusData[22], NO numActiveCars prefix
    (only PacketParticipantsData has one). Same framing as parse_lap_data."""
    base = HEADER_SIZE + player_idx * CAR_STATUS_SIZE
    if base + 9 > len(data):
        return {}
    return _car_status_fields(data, base)
```
Заменить на:
```python
def parse_player_status(data: bytes, player_idx: int) -> dict:
    """Топливо + шины (компаунд/возраст) + ERS из Car Status (packet 7) для
    игрока. F1 25: m_fuelInTank@5, m_visualTyreCompound@26, m_tyresAgeLaps@27,
    m_ersStoreEnergy@37, m_ersDeployMode@41 — последние два РЕКОНСТРУИРОВАНЫ
    по спецификации, не подтверждены вживую (см. spec
    2026-07-10-ers-telemetry-parsing-design.md), сверить через SPOTTER_DIAG=1.

    PacketCarStatusData = header + CarStatusData[22], NO numActiveCars prefix
    (only PacketParticipantsData has one). Same framing as parse_lap_data."""
    base = HEADER_SIZE + player_idx * CAR_STATUS_SIZE
    if base + 9 > len(data):
        return {}
    result = _car_status_fields(data, base)
    if _DIAG and "ers_percent" in result:
        global _last_ers_diag_t
        now = time.time()
        if now - _last_ers_diag_t >= 2.0:
            _last_ers_diag_t = now
            mode = result["ers_deploy_mode"]
            _log.warning(
                "DIAG ers: ers_percent=%.1f%% deploy_mode=%d (%s)",
                result["ers_percent"], mode,
                _ERS_MODE_LABEL.get(mode, "?"),
            )
    return result
```

- [ ] **Step 4: Прогнать тесты, зелёные**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -q`
Expected: все тесты файла зелёные (существующие + 3 новых).

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_packets_gaps_tyre.py -k ers -q`.
- **Живая верификация (обязательна, не опциональна для этой задачи):**
  собрать EXE, запустить `SPOTTER_DIAG=1 SpotterApp.exe`, в игре открыть
  HUD с индикатором ERS (% батареи + текущий режим отдачи — руль/переключатель
  M/H/O), сравнить с строками `DIAG ers: ...` в `dist/spotter.log`
  (раз в ~2с). Если `ers_percent` вне 0-100% или `deploy_mode` не совпадает
  с выбранным в игре режимом — офсеты 37/41 в спеке неверны, нужна коррекция
  ПЕРЕД тем, как переходить к advisory-логике (следующий шаг Фазы 3).
