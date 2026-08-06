# Наполнение SECTOR_SEED реальными данными — дизайн

Дата: 2026-07-08
Статус: утверждён пользователем (диалог 2026-07-08).

## Проблема

`core/openf1_seed.py::SECTOR_SEED` — статический фолбэк секторных эталонов на
случай холодного старта без доступа к живому/кэшированному OpenF1 (см. докстринг
файла). Практически пуст с 2026-07-04 (OpenF1 был заблокирован 401). API
разблокировался 2026-07-05 (см. CONTEXT.md, «Открытые баги/задачи» #3), но сид
так и не наполняли — не было прямого запроса пользователя.

## Согласованный объём

- **Год данных: 2025** — последний полностью завершённый сезон старой эры (до
  `_NEW_ERA_START_YEAR=2026` из `core/f1_benchmark.py`), тот же принцип, что уже
  использует `load()` для основного эталона.
- **GP-имена — без нового API-запроса.** Композиция уже существующих в проекте
  таблиц: `core/f1_benchmark.TRACK_ID_TO_CIRCUIT` (track_id → circuit_id) +
  `analytics/loader.TRACK_ID_TO_GP` (track_id → (короткое имя, «Grand Prix»))
  даёт все 24 пары `circuit_id → GP-имя`.
- **Скрипт — переиспользуемый, в репозитории.** `seed_sectors.py` в корне
  проекта (тот же паттерн, что `diag_lap_offsets.py`/`diag_names.py` — dev-
  инструмент, не часть приложения, не вшивается в EXE/spec-файл). Год задаётся
  константой в начале файла — перезапустить с другим годом, когда понадобится
  обновить сид (например, после завершения сезона 2026).
- **Вывод скрипта — Python-литерал в stdout, не автозапись в файл.** Ручная
  вставка в `core/openf1_seed.py` — в рамках этой же задачи, но отдельным шагом,
  не автоматизирована (докстринг-статус файла требует человеческого решения о
  формулировке, автоматическая перезапись .py-файла с прозой рискованна).
- **Отсутствующие трассы — не ошибка.** Если для circuit_id нет `session_key`
  (нет в маппинге), нет валидных секторов, или OpenF1 временно заблокирован
  (`blocked_by_live_session`) — трасса пропускается с понятным сообщением в
  stdout, скрипт не падает и не завершается с ошибкой.
- **Санити-фильтр:** каждый сектор `0 < ms <= 90000` (90с) — отсекает
  теоретически возможный мусор из API, не более.
- **Без юнит-тестов.** Одноразовый (точнее — редко-запускаемый) dev-инструмент,
  не логика приложения — тот же принцип, что у `diag_lap_offsets.py`. Проверка —
  реальный запуск + `pytest tests/test_f1_benchmark.py` после вставки данных.

## Дизайн

### `seed_sectors.py` (новый файл, корень репозитория)

```python
"""Наполняет core/openf1_seed.py::SECTOR_SEED реальными секторными эталонами
из OpenF1. Одноразовый/редко запускаемый dev-инструмент — печатает готовый
Python-литерал в stdout, вставка в openf1_seed.py вручную. Перезапустить с
другим YEAR, когда понадобится обновить сид (например, после завершения
следующего сезона). Не часть приложения — не импортируется и не вшивается в EXE."""
from __future__ import annotations

from analytics.loader import TRACK_ID_TO_GP
from core.f1_benchmark import TRACK_ID_TO_CIRCUIT
from core.openf1_client import OpenF1Client

YEAR = 2025
MAX_SECTOR_MS = 90_000   # санити-фильтр: сектор длиннее 90с — считаем мусором


def main() -> None:
    client = OpenF1Client()
    seed: dict[str, dict] = {}
    for track_id, circuit_id in sorted(TRACK_ID_TO_CIRCUIT.items()):
        gp_name = TRACK_ID_TO_GP.get(track_id, ("", ""))[1]
        session_key = client.get_session_key(YEAR, circuit_id)
        if session_key is None:
            reason = "заблокирован (live-сессия)" if client.blocked_by_live_session else "нет session_key"
            print(f"# {circuit_id}: пропущена — {reason}")
            continue
        sectors = client.get_best_sectors(session_key)
        if sectors is None:
            print(f"# {circuit_id}: пропущена — нет валидных секторов")
            continue
        if any(not (0 < ms <= MAX_SECTOR_MS) for ms in sectors.values()):
            print(f"# {circuit_id}: пропущена — санити-фильтр не пройден ({sectors})")
            continue
        seed[circuit_id] = {"year": YEAR, "event": gp_name, "sectors": sectors}

    print("\nSECTOR_SEED: dict[str, dict] = {")
    for circuit_id, entry in seed.items():
        print(f'    "{circuit_id}": {entry!r},')
    print("}")
    print(f"\n# Итого: {len(seed)}/{len(TRACK_ID_TO_CIRCUIT)} трасс")


if __name__ == "__main__":
    main()
```

### Ручная вставка в `core/openf1_seed.py`

После запуска — заменить текущий пустой `SECTOR_SEED = {...}` на напечатанный
литерал, и обновить докстринг-статус вверху файла (заменить абзац «СТАТУС
(2026-07-04): практически ПУСТОЙ...» на факт: наполнено по сезону 2025
DD.MM.2026, скриптом `seed_sectors.py`, сколько трасс покрыто из 24, что
делать при обновлении в будущем).

## Файлы

| Файл | Действие |
|---|---|
| `seed_sectors.py` | Новый — одноразовый/переиспользуемый dev-скрипт |
| `core/openf1_seed.py` | `SECTOR_SEED` заполняется реальными данными; докстринг обновляется |

## Верификация

- Реальный запуск `py -3.12 seed_sectors.py`, проверка вывода на плейсхолдеры/аномалии.
- После вставки данных: `py -3.12 -m pytest tests/test_f1_benchmark.py -v` — зелёный.
- Полный прогон `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — без регрессий.
