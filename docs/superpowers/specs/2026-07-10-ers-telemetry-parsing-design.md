# ERS-телеметрия: парсинг + диагностика (Фаза 3, шаг 1 из 3) — дизайн

Дата: 2026-07-10
Статус: утверждён пользователем (диалог 2026-07-10), реализация — по плану в
`docs/superpowers/plans/`.

## Контекст

Фаза 3 «замены инженера» (топливо/ERS) — топливная половина УЖЕ работает
(`fuel_save_recommended`/`FuelTracker`, событие `STRAT_FUEL`, уже унаследовало
голос инженера от прошлой сессии). Остаётся ERS — единственная часть, требующая
парсинга НОВЫХ полей телеметрии (`CarStatusData`), которых сейчас в
`core/packets.py` вообще нет.

Пользователь подтвердил порядок: сначала ТОЛЬКО парсинг + диагностика (этот
документ), пользователь проверяет офсеты вживую, ПОТОМ — три подсказки
(экономия при низком заряде, «давай овертейк» при борьбе, % в гэп-дайджесте) —
отдельным следующим циклом.

## Проблема

`core/packets.py::_car_status_fields()` уже читает топливо (`m_fuelInTank@5`)
и шины (`m_visualTyreCompound@26`, `m_tyresAgeLaps@27`) из `CarStatusData`
(`CAR_STATUS_SIZE = 55` байт/машина). ERS-поля (`m_ersStoreEnergy`,
`m_ersDeployMode`) не читаются вовсе.

**СТАТУС ОБНОВЛЁН 2026-07-10: офсеты ПОДТВЕРЖДЕНЫ без запуска игры.**
Изначально реконструированы по знанию спецификации; затем сверены с двумя
независимыми авторитетными источниками (эффективная статическая верификация
вместо живого прогона, по запросу пользователя):
1. **Официальная спецификация EA** «Data Output from F1 25 v3.pdf» (F1 Game
   Info Hub на forums.ea.com).
2. **Независимый F1 25-парсер** github.com/MacManley/f1-25-udp, выведенный из
   той же официальной спеки.
Оба дают идентичную раскладку: `m_ersStoreEnergy` — float @37,
`m_ersDeployMode` — uint8 @41, `CarStatusData` = 55 байт, `PacketCarStatusData`
= 1239 = 29 (заголовок) + 22×55. Три довода сходятся: (а) три уже рабочих поля
на своих местах, (б) сумма структуры = 55 = `CAR_STATUS_SIZE`, (в) прямое
совпадение с официальной спекой и независимым парсером. Делитель
`ERS_MAX_JOULES = 4_000_000` тоже подтверждён (ёмкость ES = 4 МДж, стандартная
формула % заряда). Полная golden-раскладка зафиксирована тестом
`tests/test_packets_gaps_tyre.py::_CAR_STATUS_LAYOUT` — будущий дрейф после
патча игры поймается тестом. `SPOTTER_DIAG=1` оставлен как доп. страховка, но
живая сверка больше НЕ является блокером для перехода к advisory-логике.

## Решение (одним абзацем)

Реконструированная раскладка `CarStatusData` (от `base = HEADER_SIZE +
car_idx * CAR_STATUS_SIZE`):

```
@0  m_tractionControl        uint8
@1  m_antiLockBrakes         uint8
@2  m_fuelMix                uint8
@3  m_frontBrakeBias         uint8
@4  m_pitLimiterStatus       uint8
@5  m_fuelInTank             float   ← уже читается
@9  m_fuelCapacity           float
@13 m_fuelRemainingLaps      float
@17 m_maxRPM                 uint16
@19 m_idleRPM                uint16
@21 m_maxGears               uint8
@22 m_drsAllowed             uint8
@23 m_drsActivationDistance  uint16
@25 m_actualTyreCompound     uint8
@26 m_visualTyreCompound     uint8   ← уже читается
@27 m_tyresAgeLaps           uint8   ← уже читается
@28 m_vehicleFiaFlags        int8
@29 m_enginePowerICE         float
@33 m_enginePowerMGUK        float
@37 m_ersStoreEnergy         float   ← НОВОЕ, эта задача
@41 m_ersDeployMode          uint8   ← НОВОЕ, эта задача
@42 m_ersHarvestedThisLapMGUK float
@46 m_ersHarvestedThisLapMGUH float
@50 m_ersDeployedThisLap     float
@54 m_networkPaused          uint8
= 55 байт
```

`_car_status_fields()` получает 2 новых поля: `ers_percent` (float, 0-100,
округлено до 1 знака — `m_ersStoreEnergy / ERS_MAX_JOULES * 100`) и
`ers_deploy_mode` (int, сырое значение 0-3, без сборки повышенной логики
поверх — это отдельная задача следующего шага).

`ERS_MAX_JOULES = 4_000_000.0` — техническая величина из регламента FIA
(максимальный запас ERS 4 МДж), не игровой параметр, стабильна между
версиями игры (в отличие от `PARTICIPANT_SIZE`, который реально менялся).

## Не входит в объём

- Любая advisory-логика (экономия/«давай овертейк») — следующий шаг, ПОСЛЕ
  подтверждения офсетов.
- ERS соперников — `_car_status_fields()` общий хелпер, поля появятся у
  соперников «бесплатно» (та же функция), но не используются нигде —
  сознательно не строю новую фичу под это сейчас.
- `m_ersHarvestedThisLapMGUK/H`/`m_ersDeployedThisLap` — не нужны для трёх
  задуманных подсказок, не парсятся.
- Текстовая расшифровка `ers_deploy_mode` (0-3 → "none"/"medium"/etc.) —
  только для diag-лога (readability при верификации), не как поле в
  возвращаемом словаре — решение о лейблах для реальных фраз откладываю до
  advisory-шага, когда будет ясно, нужны ли они вообще для советов.

## Архитектура

### `core/packets.py`

```python
ERS_MAX_JOULES = 4_000_000.0  # регламент FIA — не игровой параметр

_ERS_MODE_LABEL = {0: "none", 1: "medium", 2: "overtake", 3: "hotlap"}
```

`_car_status_fields()` — добавить после существующего блока шин:
```python
    if base + 42 <= len(data):
        ers_energy = struct.unpack_from("<f", data, base + 37)[0]
        out["ers_percent"] = round(ers_energy / ERS_MAX_JOULES * 100, 1)
        out["ers_deploy_mode"] = data[base + 41]
```
(отдельная граница `base + 42 <= len(data)`, как уже сделано для блока шин
`base + 28 <= len(data)` — те же соображения: не падать, если структура
пакета окажется короче ожидаемого).

### Диагностика — throttled DIAG-лог в `parse_player_status`

`parse_player_status` дёргается на КАЖДЫЙ CarStatus-пакет (десятки раз в
секунду) — уже существующий `_DIAG`-паттерн (как у participants, который
естественно редкий) БЕЗ троттлинга захлестнёт лог. Новая throttle-метка на
уровне модуля:

```python
import time  # новый импорт

_last_ers_diag_t = 0.0

def parse_player_status(data: bytes, player_idx: int) -> dict:
    ...
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

## Граничные случаи

- **Пакет короче ожидаемого** (структура снова изменилась между патчами) —
  `base + 42 <= len(data)` защищает, поля просто не появятся в словаре
  (симметрично уже существующей защите для шин).
- **`ers_deploy_mode` вне 0-3** — если офсет неверный, сюда попадёт мусорный
  байт (0-255) — DIAG-лог покажет это как несовпадающий с `_ERS_MODE_LABEL`
  (`"?"` в выводе) — сигнал для пользователя, что офсет надо перепроверять.
- **`ers_percent` вне 0-100** — аналогично, прямой сигнал неверного офсета
  при живой проверке (батарея физически не может быть «150%» или
  отрицательной).

## Тестирование

- `tests/test_packets_gaps_tyre.py` (расширение, тот же файл, что уже тестит
  `_car_status_fields` для топлива/шин) — синтетический буфer с
  `struct.pack_into("<f", buf, base + 37, ers_energy)` и
  `buf[base + 41] = deploy_mode`, проверка `ers_percent`/`ers_deploy_mode` в
  результате. Плюс тест на короткий буфер (нет ERS-полей → их нет в словаре).
- DIAG-троттлинг — юнит-тест на throttle-логику (не дублирует раньше
  установленный `_last_ers_diag_t`, если вызвать дважды подряд).
- **Golden-раскладка (`_CAR_STATUS_LAYOUT`)** — новый тест кодирует ВСЮ
  структуру CarStatusData (25 полей → офсеты) по официальной спеке, плюс
  инвариант «сумма = 55 = CAR_STATUS_SIZE». Ловит будущий дрейф после патча
  игры автоматически. Отдельный тест
  `test_ers_read_from_37_not_adjacent_engine_power_field` — прямая страховка
  от путаницы с соседним `m_enginePowerMGUK@33` (см. находку ревью ниже).
- **Верификация офсетов ЗАКРЫТА статически** (обновление 2026-07-10, см.
  «Проблема» выше): сверка с официальной спекой EA + независимым парсером
  MacManley дала точное совпадение — живой прогон БОЛЬШЕ НЕ блокер для
  advisory-шага. `SPOTTER_DIAG=1` остаётся как доп. страховка на случай
  будущего патча игры, но не обязателен.

**Методологическая находка ревью (важно для самой проверки, не баг кода):**
«`ers_percent` в диапазоне 0-100%» — СЛАБЫЙ сигнал правильности сам по себе.
В реконструированной раскладке `m_enginePowerMGUK` (float, @33-37) стоит
ВПЛОТНУЮ перед `m_ersStoreEnergy` (float, @37-41) — оба поля одного порядка
величины (энергия/мощность). Если истинный офсет ERS смещён всего на 4 байта
(например, реально @33), код молча прочитает `enginePowerMGUK` вместо
`ersStoreEnergy` — а мощность MGU-K (~120 кВт), делённая на `ERS_MAX_JOULES`,
даёт ~3% — правдоподобное, но НЕВЕРНОЕ число. Поэтому при сверке приоритет:
1. **`deploy_mode` — сильный сигнал.** Должен быть строго 0-3 И совпадать с
   реально выбранным в игре режимом (переключатель на руле). Случайный байт
   попадает в 0-3 лишь с шансом ~1.6%.
2. **Стабильность `ers_percent` между кадрами.** Реальный заряд батареи
   меняется ПЛАВНО. Если число дёргается/скачет synchronно с педалью газа —
   это явно НЕ заряд, а что-то другое (например, спутанное поле мощности).
Одного взгляда «число похоже на процент» — недостаточно.
