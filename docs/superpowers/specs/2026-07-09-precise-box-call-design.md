# Точный box-вызов — дизайн (Фаза 1 из 4, «замена внутриигрового инженера»)

Дата: 2026-07-09
Статус: утверждён пользователем (диалог 2026-07-09), реализация — по плану в
`docs/superpowers/plans/`.

## Контекст

Пользователь попросил, чтобы Spotter App мог полностью заменить внутриигрового
инженера F1 25 — «те же слова в те же моменты». Это большая фича, разбита на
4 независимые фазы (обсуждение 2026-07-09):

1. **Точный box-вызов** ← этот спек.
2. Регулярные сводки по гэпу/секторам (радио-инженер стиль).
3. Топливо/ERS менеджмент (нужна новая телеметрия — `PacketCarStatusData` эти поля
   сейчас вообще не парсит).
4. Погода/трек-лимиты (тоже новая телеметрия — прогноз погоды, FIA-флаги).

Пункты 2-4 — отдельные последующие спеки, не входят в объём этого документа.

## Проблема

`core/strategy_ai/strategy.py::StrategyAnalyzer` уже на каждом тике (~1с) считает
`action`/`confidence`/`reason` для pit/undercut/overcut/cover-opponent — но
результат уходит в очередь как ОДИН советующий тон («Окно пит-стопа открыто»,
`STRAT_PIT`/`STRAT_UNDERCUT`/...), сформулированный творчески через LLM
(`commentator/brain.py::create()` отправляет ЛЮБОЕ событие в LLM, если он
доступен — шаблон это лишь оффлайн-фолбэк). Проблемы:

- Нет момента «вот теперь точно нужно ехать» — совет может звучать одинаково мягко
  и за 4 круга до пит-стопа, и когда шины уже «упали с обрыва» (`tyre_status ==
  "cliff"`).
- Событие может повторяться каждые 20с, пока условие держится (`core/engine.py`
  rate-limit), — это не «команда на конкретный круг», а фоновый нагоняющий совет.
- LLM-путь непредсказуем по времени и формулировке — для решающей команды это
  риск (задержка, невнятная фраза в критический момент).

## Решение (одним абзацем)

Вводим **единый порог уверенности** (`confidence >= 0.85`) поверх уже готовых
`StrategyEvent` от `StrategyAnalyzer` — если `action == "pit"` и уверенность выше
порога (неважно, из-за критического износа шин, ИЛИ высокой уверенности андерката,
ИЛИ cover-opponent), это классифицируется как решительная команда, а не совет.
Новый маленький конечный автомат `core/strategy_ai/box_call.py::BoxCallTracker`
следит за этим состоянием per-круг и отдаёт эскалацию (1→2→3, потом плато),
пока не увидит `pit_status` (игрок реально заехал) или пока решительное состояние
не снимется само. Три новых события (`STRAT_BOX_CALL_1/2/3`) идут **напрямую
через шаблон**, в обход LLM — гарантированная, мгновенная, ровно одобренная
формулировка.

## Не входит в объём

- Отдельная детекция «точного круга» — переиспользуем существующие
  `detect_pit_window`/`detect_undercut`/`OpponentPitDetector.should_cover` из
  `core/strategy_ai/pit_window.py` и `opponents.py` как есть, без изменений.
- Гейт по `session_type` (квалификация/практика) — намеренно не добавляется в этой
  фазе, см. «Граничные случаи» ниже.
- Гистерезис вокруг порога 0.85 — принятое ограничение первой версии, не
  усложняем.
- Персистентность состояния трекера между перезапусками приложения — ephemeral,
  как остальные трекеры движка.

## Архитектура

### Новый модуль `core/strategy_ai/box_call.py`

Чистый детерминированный класс, без I/O, без сети — полностью юнит-тестируем.

```python
DECISIVE_CONFIDENCE = 0.85
MAX_TIER = 3

class BoxCallTracker:
    def __init__(self) -> None:
        self._armed_lap: int | None = None
        self._last_called_lap: int | None = None
        self._tier: int = 0

    def update(self, player_lap: int | None, action: str, confidence: float,
                pit_status: int | None) -> int | None:
        """Возвращает номер эскалации (1..MAX_TIER) или None (молчать)."""
        if pit_status:
            self.reset()
            return None
        if action != "pit" or confidence < DECISIVE_CONFIDENCE or player_lap is None:
            self.reset()
            return None
        if self._armed_lap is None:
            self._armed_lap = self._last_called_lap = player_lap
            self._tier = 1
            return self._tier
        if player_lap == self._last_called_lap:
            return None
        # новый круг, всё ещё не заехал
        self._last_called_lap = player_lap
        self._tier = min(MAX_TIER, self._tier + 1)
        return self._tier

    def reset(self) -> None:
        self._armed_lap = self._last_called_lap = None
        self._tier = 0
```

### Проводка в `core/engine.py`

В существующем блоке обработки `strategy_event` (~строка 1045, сразу после
`strategy_event = self.strategy_analyzer.update(st_snapshot)`):

```python
# Вызывается КАЖДЫЙ тик, не только когда strategy_event is not None — иначе
# трекер не сбросится, если решительное состояние исчезло резко (StrategyAnalyzer
# вернул None, а не просто confidence ниже 0.85).
_action = strategy_event.decision.action if strategy_event else "hold"
_confidence = strategy_event.confidence if strategy_event else 0.0
tier = self._box_call_tracker.update(
    self._player_lap, _action, _confidence, self._player_pit_status)
if tier is not None:
    self._enqueue_event({
        "event_code": f"STRAT_BOX_CALL_{tier}",
        "priority": "critical",
        "driver": "player", "color": "#EF4444",
    })
```
**Решено при реализации (найдено финальным сквозным ревью после Task 4):**
пока действует то же решительное окно (`action=="pit" and confidence >=
DECISIVE_CONFIDENCE`) — advisory-ветка `_st_code_map`/`STRAT_PIT` не
срабатывает вовсе, не только на тике самого box-вызова. Иначе игрок слышит
одновременно спокойное «окно открыто» и «боксы! боксы!» про одно и то же —
именно то, что этот спек должен был устранить.

`self._box_call_tracker = BoxCallTracker()` — инициализация рядом с остальными
per-race трекерами (`_situation_dedup` и т.п.).

**Сброс во флешбеке:** `core/engine.py::_handle_flashback()` уже сбрасывает
`race_analyzer.reset_transient()`/`situation_dedup.reset()` — туда же добавляется
`self._box_call_tracker.reset()`.

**Сброс на финише (CHQF):** там же, где сбрасываются остальные transient-счётчики
на финиш сессии.

### `priority: "critical"`

Тот же механизм, что уже используют `PENA`/`COLL`/`RTMT` — не глушится
flashback-тишиной, семантическим дедупом ситуаций, фильтром «позиции
комментатора» (`_should_commentate`) и порогом важности (`_speak_threshold`) —
все эти проверки уже пропускают `priority == "critical"` без изменений кода.

### `commentator/templates.py` — новые фразы (фиксированные, без LLM)

```python
"STRAT_BOX_CALL_1": ["Бокс в этом круге. Повторяю, бокс в этом круге."],
"STRAT_BOX_CALL_2": ["Бокс, бокс — заезжай сейчас."],
"STRAT_BOX_CALL_3": ["Ты теряешь время каждый круг — боксы!"],
```

### `commentator/brain.py::create()` — bypass LLM для этих кодов

В начале метода, до похода к `self.ai`:

```python
_TEMPLATE_ONLY_CODES = frozenset({
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3"})
...
if code in _TEMPLATE_ONLY_CODES:
    phrase = templates.render(event, self.persona)
    if phrase:
        self.memory.append(phrase, code)
    return phrase
```

## Граничные случаи

- **Нет данных о шинах/составе** — `detect_pit_window`/`detect_undercut` уже
  возвращают `confidence=0.0` при нехватке данных → трекер не взводится, ничего
  специально делать не нужно.
- **Квалификация/практика** — намеренно НЕ гейтуется по `session_type` в этой
  фазе (в отличие от `PIT_EXIT`, который race-only) — открытый пункт на будущее,
  не блокирует эту фазу.
- **Дребезг уверенности возле 0.85** — может раз сбросить эскалацию на tier 1
  вместо продолжения нарастания. Принятое ограничение первой версии.
- **Рестарт приложения посреди гонки** — трекер не персистится, начинает
  отслеживать заново с текущего тика (как остальные ephemeral-трекеры движка).
- **Задержка телеметрии на смене `pit_status`** — в худшем случае один лишний
  тик эскалации после фактического заезда, самокорректируется на следующем тике.

## Тестирование

`tests/test_box_call.py` (новый, без моков — чистая логика):
- взвод на первом решительном тике → tier 1
- повторный тик в том же круге → `None`
- новый круг, всё ещё не заехал → tier 2, потом tier 3, плато на 3
- `pit_status` truthy → сброс, `None`; следующий решительный тик снова tier 1
- `confidence < 0.85` или `action != "pit"` → сброс, `None`
- `player_lap is None` → `None`, без исключений

`tests/test_brain.py` (расширение, если файл уже существует — проверить):
- для `STRAT_BOX_CALL_*` `create()` возвращает шаблонную фразу, даже когда
  `ai.available=True` — мок AI-провайдера, который бы вернул маркерную фразу,
  если его вызвали; проверяем, что вызван НЕ был.

`tests/test_phrases.py` или аналог — фразы на месте, тексты совпадают с
одобренными.

Проводка в `engine.py` (вызов трекера, сброс во флешбеке/на финише) — как и
остальные бесконечные циклы движка (`_commentary_loop`, `_ambient_loop`), прямым
юнитом не покрывается; проверяется полным прогоном `pytest` + ручной проверкой
в игре пользователем (недоступно в среде разработки).
