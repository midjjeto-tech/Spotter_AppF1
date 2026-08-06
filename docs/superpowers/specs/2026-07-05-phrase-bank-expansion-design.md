# Phrase Bank Expansion — дизайн

Дата: 2026-07-05
Статус: утверждён пользователем (диалог 2026-07-05), реализация — по плану в
`docs/superpowers/plans/`.

## Проблема

Из исходного 18-пунктового пожелания пользователя: расширить банк фраз
(`commentator/templates.py`) — больше вариаций для атаки/защиты/пит-стопа/
износа шин/последних кругов. `templates.py` — это Free-режим (без LLM):
шаблонные фразы, используемые когда `commentator/brain.py::Commentator.create()`
не может вызвать LLM (Yandex недоступен/упал). Это ПОЛНОСТЬЮ независимый
код-путь от `commentator/planner.py`/`build_plan()` — тот путь LLM формулирует
текст сам по директиве, этот путь Python выбирает ГОТОВУЮ фразу из пула.

Расследование нашло три конкретных пробела:

1. **`PIT_EXIT`** (новое событие, заведено в сессии «Final Laps/Attacks/Pit-stop
   Mode») вообще не имеет шаблона. Если LLM откажет именно в момент выезда из
   боксов, `render()` дойдёт до `return event.get("description", code)` — на
   экране/в динамике окажется голый код события, а не фраза.
2. **«Последние круги»** как концепция не существует в `templates.py` вообще
   — только в `build_plan()`/LLM-пути через `event["laps_remaining"]`
   (см. сессию «Final Laps/Attacks/Pit-stop Mode»). Free-режим на последних
   кругах звучит так же ровно, как и в середине гонки.
3. **`PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH`** есть только в `SIMPLE` (3-4 нейтральных
   варианта на все персоны) — в отличие от `OVTK`/`DAMAGE_*`/`RCWN` и т.д., у
   которых уже есть `hype`/`calm`/`toxic` варианты в `PERSONA`.

## Согласованный объём

- **`PIT_EXIT`**: `SIMPLE` + `hype`/`calm`/`toxic` в `PERSONA`. Без упоминания
  состава шин (`tyre_compound`) — это чистый Python без LLM, раскодировать
  букву состава (S/M/H/I/W) в русское слово на лету некому; заводить в
  `templates.py` ТРЕТЬЮ копию того же маппинга (после `core/packets.py::
  TYRE_VISUAL` и `commentator/personas.py::_TYRE_GLOSSARY`) — осознанно
  отклонено пользователем.
- **`FINAL_LAPS`**: новый словарь, структурно параллельный существующему
  `BATTLE` — только для `OVTK`. Собственная локальная константа
  `_FINAL_LAPS_THRESHOLD = 3` (НЕ импортируется из `commentator/planner.py` —
  два независимых кодовых пути, тот же паттерн, что уже применён для
  `battle`/`BATTLE_THRESHOLD`: `templates.py` читает уже вычисленное поле
  `event["laps_remaining"]`, не переиспользует чужую константу напрямую).
- **`PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH`**: добавить `hype`/`calm`/`toxic` в
  `PERSONA` (по 3-4 варианта каждая, тот же порядок величины, что и у
  существующих небольших пулов вроде `DRSE`/`DRSD`/`PUSH_LAP`).
- **Явно НЕ в этом цикле:** «защита» (успешно отбился от атаки) — в конвейере
  нет события для этого (`OVTK` всегда описывает того, кто обогнал, никогда
  того, кто удержал позицию); заведение такого события — отдельная будущая
  мини-фича с новой логикой детекции, не расширение банка фраз.

## Дизайн

### 1. Приоритет пулов в `render()`

Сегодня:
```python
if event.get("battle") and code in BATTLE:
    pool = BATTLE[code]
    key = f"battle:{code}"
else:
    persona_pool = PERSONA.get(persona, {}).get(code)
    pool = persona_pool or SIMPLE.get(code)
    key = f"{persona if persona_pool else 'simple'}:{code}"
```

Готовые фразы (в отличие от `build_plan()`, где маркеры компонуемые —
"последние N кругов, 3-я попытка" собираются в одну строку) нельзя просто
сложить, если одновременно верны и `battle`, и последние круги — нужно
выбрать ОДИН пул. `final_laps` идёт ПЕРВЫМ (перебивает `battle`) — концовка
гонки более редкий и драматичный контекст, чем борьба за позицию в середине
дистанции, и фразы `FINAL_LAPS` уже сами по себе подразумевают напряжённость
борьбы:

```python
laps_remaining = event.get("laps_remaining")
final_laps = laps_remaining is not None and laps_remaining <= _FINAL_LAPS_THRESHOLD

if final_laps and code in FINAL_LAPS:
    pool = FINAL_LAPS[code]
    key = f"final_laps:{code}"
elif event.get("battle") and code in BATTLE:
    pool = BATTLE[code]
    key = f"battle:{code}"
else:
    persona_pool = PERSONA.get(persona, {}).get(code)
    pool = persona_pool or SIMPLE.get(code)
    key = f"{persona if persona_pool else 'simple'}:{code}"
```

### 2. `FINAL_LAPS` — новый словарь

Структурно идентичен `BATTLE` (`dict[str, list[str]]`, ключ — `event_code`),
только `OVTK`. Фразы должны звучать острее/короче, чем обычные `SIMPLE`/
`BATTLE`-варианты — концовка гонки, а не рядовой обгон. 4-5 вариантов.

### 3. `PIT_EXIT` — `SIMPLE` + `PERSONA`

`SIMPLE["PIT_EXIT"]`: 4-5 нейтральных вариантов, паттерн `{driver}` (как
`PIT_IN`/`PIT_OUT`). `PERSONA["hype"/"calm"/"toxic"]["PIT_EXIT"]`: по 3-4
варианта каждая, в характере персоны — как уже сделано для `OVTK`/`DAMAGE_*`.
Без `{tyre_compound}` — см. «Согласованный объём» выше.

### 4. `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` — добавить `PERSONA`

`SIMPLE`-варианты остаются как есть (не трогаем — на случай persona,
отсутствующей в `PERSONA`, но такого сегодня нет: все 4 персоны определены).
Добавить `hype`/`calm`/`toxic` записи для этих трёх кодов в уже существующие
блоки `PERSONA["hype"]`/`PERSONA["calm"]`/`PERSONA["toxic"]` (не создавать
новые персона-блоки).

## Файлы

| Файл | Действие |
|---|---|
| `commentator/templates.py` | `FINAL_LAPS` (новый словарь) + `_FINAL_LAPS_THRESHOLD`; `render()` — приоритет `final_laps` над `battle`; `SIMPLE`/`PERSONA` — записи `PIT_EXIT`; `PERSONA` — записи `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` для `hype`/`calm`/`toxic` |
| `tests/test_phrases.py` | существующий файл тестов `commentator/templates.py` (НЕ `test_templates.py`) — новые тесты на `PIT_EXIT` (simple+3 персоны), `FINAL_LAPS` (выбор пула, приоритет над battle), персона-варианты `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH`; следовать существующей конвенции файла (class-based группировка `TestXxxPool`, параметризация по персонам) |

## Отказоустойчивость

Ничего нового не добавляется поверх существующей защиты `render()`: если пул
пуст/не найден — `if not pool: return event.get("description", code)` уже
покрывает любой будущий пробел (в т.ч. пока не заполненные комбинации персона×
код). `_pick()` (анти-повтор) переиспользуется без изменений — новые пулы
проходят через тот же механизм.

## Верификация

- Новые тесты в `tests/test_templates.py`: `PIT_EXIT` рендерится (не падает в
  `event.get("description", code)`) для `SIMPLE` и всех трёх персон;
  `FINAL_LAPS` выбирается когда `laps_remaining <= 3`, ИГНОРИРУЕТСЯ когда
  `laps_remaining` больше порога или `None`; `final_laps` перебивает `battle`,
  когда оба условия верны одновременно; `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH`
  реально возвращают персона-специфичный текст (не молча падают на `SIMPLE`)
  для всех трёх персон.
- Полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` —
  бейслайн 911 passed, 1 skipped (сессия Race Memory v1, 2026-07-05) должен
  остаться зелёным плюс новые тесты.
