# Фаза A «дешёвых» реплик инженера — дизайн

Дата: 2026-07-13
Статус: утверждён пользователем (диалог 2026-07-13), реализация — по плану в
`docs/superpowers/plans/`.

## Контекст

Продолжение «замены внутриигрового инженера F1 25». После закрытия всех 4
исходных фаз + тумблера (см. `docs/superpowers/specs/2026-07-11-track-limits-
engineer-toggle-design.md`) пользователь предоставил развёрнутый разбор
типов реплик реального инженера F1 25 (21 категория) и попросил ревизию
покрытия. По итогам сверки с кодом (не по памяти — грепом) выявлены пробелы,
разбитые на независимые фазы; пользователь выбрал **Фазу A** — четыре
реплики, не требующие новой непроверенной телеметрии (три используют уже
трекаемые поля, одна — поле `m_drsAllowed`, чей офсет уже статически
подтверждён и закреплён golden-master тестом `_CAR_STATUS_LAYOUT` при работе
над ERS 2026-07-10).

Дизайн выработан итеративно: пользователь предложил детальные уточнения к
каждому компоненту (единый `update()` для DRS вместо двух методов из-за
непредсказуемого порядка UDP-пакетов; классификация причины смены позиции;
debounce для смены лидера; переиспользование `laps_left` для pit-window;
маппинг приоритета на существующую `_BASE_IMPORTANCE`) — все приняты, один
пункт (полная 6-причинная классификация position calls) сознательно урезан
до 3 корзин по совместному решению (полная версия не окупает сложность для
«дешёвой» фазы).

## Решение

Все 4 компонента — периодическая «болтовня» инженера, гейтуются
`engineer_chatter_enabled` (как гэп-дайджест/ERS-советы/rain-advisory/
трек-лимиты). Фразы — пулы (`random.choice`), не одна фиксированная строка
(отличие от предыдущих трекеров этой сессии — осознанный выбор пользователя
именно для этой фичи, DRS-события частые и должны звучать разнообразно).

### 1. `DRSAdvisoryTracker` — DRS-подсказки

Единый метод `update(gap_front_ms, drs_allowed, now)` вместо двух
независимых — LapData (`gap_front_ms`) и CarStatusData (`drs_allowed`)
приходят разными пакетами в непредсказуемом порядке; единая точка входа с
двумя последними известными значениями делает результат детерминированным
независимо от того, какой пакет обработан первым в этот тик.

Гистерезис по гэпу (защита от дребезга на границе): вход в зону — `gap ≤
1000` мс, выход — `gap > 1200` мс; между ними состояние не меняется.
`drs_allowed` — edge-triggered on/off без гистерезиса (булево поле дребезжать
не может).

Если два условия становятся истинными одновременно (вход в зону при уже
разрешённой DRS, или разрешение DRS при уже близком гэпе) — составная фраза
вместо двух отдельных (по явной просьбе пользователя: «естественнее,
меньше радиопереговоров»).

**`gap_front_ms is None` (нет машины впереди) → `_in_range` принудительно
`False`** (не «оставить как есть», как в первой версии спеки — найдено
ревью: машина впереди уходит в боксы → `gap=None` → старое `_in_range=True`
зависает → появляется НОВАЯ машина сразу близко (`gap=800`) → переход
`True→True` не детектится как «вход», фраза не звучит вовсе). Только
`_in_range` сбрасывается, `_drs_allowed` — сессионное состояние, к наличию
машины впереди отношения не имеет.

**Anti-repeat `MIN_REPEAT_S=5.0`** для входа/выхода из зоны конкретно (не
для allowed/disabled — редкий чистый edge-trigger, дребезжать нечему):
гистерезис 1000/1200мс не гарантирует защиту от дребезга в плотной борьбе на
прямой (гэп может колебаться в узком диапазоне вокруг границ). Повторное
«вошёл»/«вышел» того же типа в течение 5с после предыдущего — не звучит
(внутреннее состояние `_in_range` при этом всё равно обновляется корректно).

Гейт по сессии: везде (информационное, не только гонка — по общему принципу
пользователя «информационные сообщения — во всех режимах»).

### 2. `PositionCallTracker` — позиционные calls

Три корзины вместо полной 6-причинной классификации:
- **OVERTAKE/OVERTAKEN** (свежий `OVTK` с участием игрока, окно 3с как
  резервный таймер-фолбэк) → не озвучивать (уже покрыто существующей
  `OVTK`-репликой комментатора).
- **Свой пит-стоп** (`note_own_pit_exit`, переиспользует edge-детект из
  `_maybe_announce_pit_exit`) → отдельная фраза «После пит-стопа ты теперь
  P{n}», но НЕ мгновенно — settle-окно 1.5-2с: если позиция продолжает
  меняться, таймер перезапускается; максимум ожидания 8с (защита от
  бесконечного молчания, если позиция никогда не стабилизируется).
- **Всё остальное** (сход соперника, чужой пит-стоп, штраф сопернику,
  неизвестно) → общая фраза «Теперь ты P{n}», settle-окно 2с (короче, чем у
  своего пит-стопа) — тот же механизм debounce, не мгновенное срабатывание.
  **Найдено ревью:** мгновенное объявление на КАЖДОЕ изменение позиции при
  быстрой волне (несколько сходов подряд, P10→P9→P8 за пару секунд) звучало
  бы как очередь отдельных реплик подряд; settle коалесцирует до одной
  фразы с финальным значением, не теряя информацию (в отличие от простого
  cooldown, который бы просто не сказал про P8 вовсе).

Гейт по сессии: только race (как гэп-дайджест — вне гонки позиционная борьба
не несёт смысла).

### 3. `LeaderChangeTracker` — смена лидера

Только race (**поправка к изначальному предложению пользователя**: в
квали/практике «смена лидера» = «сменился обладатель быстрейшего времени
сессии» — это ТО ЖЕ событие, что уже озвучивает существующий `FTLP`
(`"{driver} показывает новый быстрейший круг!"`); отдельный трекер для
квали/практики дублировал бы `FTLP` в тот же тик. Согласовано с
пользователем в диалоге.).

Debounce 2с: новый лидер объявляется только если продержался ≥2с без смены
— защита от «Леклер... Норрис... Леклер...» на волне пит-стопов/рестартов
после Safety Car.

Первое наблюдение лидера (старт сессии) не объявляется — это не «смена», а
установление базовой линии.

**Ключ — `vehicle_idx`, не `driverId` (рассмотрено и отклонено).**
`driverId` нигде не парсится сейчас (только упомянут в комментарии про сырую
структуру `ParticipantData`) — использовать его означало бы новую
телеметрию, что противоречит смыслу «дешёвой» фазы. `vehicle_idx` уже
служит стабильным ключом ВЕЗДЕ в проекте (box-call, гэп-дайджест, rivals,
трек-лимиты) — по спецификации F1 UDP это позиция в массиве участников,
назначается один раз на сессию, flashback/reconnect новую сессию не создают
(SSTA не срабатывает) → массив не переразмечается. Единственный реальный
кейс переразметки — новая сессия, там уже штатно `reset()`.

Отдельный anti-repeat cooldown не нужен — debounce 2с уже выполняет ту же
роль (не даёт объявлять транзитные состояния).

### 4. `PitWindowApproachTracker` — приближение к окну пит-стопа

Переиспользует уже существующий `detect_pit_window()`'s `laps_left`
(третий элемент кортежа, возвращается даже когда `open=False`) — это НЕ
фиксированное «N кругов до финиша», а постоянно пересчитываемая оценка «до
принудительной замены шин» из темпа деградации (`_laps_to_pit`), уже
адаптивная к разным стратегиям/трассам без дополнительной работы.

`open=False and laps_left <= 8` → одна фраза «Приближаемся к окну пит-стопа»
**один раз за стинт** (флаг `_announced_this_stint`, сброс только при
завершении собственного пит-стопа — переиспользует тот же хук, что и
`PositionCallTracker.note_own_pit_exit`, плюс обычные сессионные сбросы).
Без этого флага фраза повторялась бы на каждом пересечении порога при
колебаниях `laps_left` (смена стратегии/темпа) внутри одного стинта —
найдено пользователем как реальный риск.

Гейт по сессии: только race (пользователь подтвердил явно — «пит-окно
бессмысленно в practice/qualifying»).

Отдельный anti-repeat cooldown не нужен — `_announced_this_stint`
(армируется один раз за стинт) уже даёт более сильную гарантию, чем
временной cooldown: структурно не может повториться внутри стинта вообще,
а не просто «не чаще чем раз в N секунд».

**TODO (не в объёме этой фазы, зафиксировано по просьбе пользователя):**
полный пересчёт стратегии посреди стинта (например, дождь → смена на
интермедиэйты меняет расчёт `laps_left`) сейчас НЕ сбрасывает
`_announced_this_stint` — если «приближаемся к окну» уже прозвучало один
раз в стинте, повторно не прозвучит даже после резкого пересчёта стратегии.
Осознанно отложено — редкий кейс, не блокирует эту фазу.

### 5. Приоритет — существующая таблица, не новая система

`ImportanceQueue` (core/event_queue.py) — безлимитная `PriorityQueue`, НЕ
роняет события при переполнении (важное уточнение по итогам разбора —
изначальная формулировка пользователя предполагала dropping, которого в
системе нет). `importance` влияет на порядок озвучки и паузу между репликами
(`min_comment_gap` укорачивается для высокой важности) — практически тот же
эффект, что просил пользователь, через уже существующий механизм.

Новые записи в `commentator/planner.py::_BASE_IMPORTANCE`:
```python
"DRS_PROXIMITY_ENTER": 30, "DRS_PROXIMITY_EXIT": 30,
"DRS_ALLOWED_ON": 30, "DRS_ALLOWED_OFF": 30,
"POSITION_CALL": 55, "POSITION_CALL_OWN_PIT": 55,
"LEADER_CHANGE": 55,
"PIT_WINDOW_APPROACH": 55,
```
Плюс правка существующей записи: `"PIT_EXIT": 60` → `65` (найдено
ревью: подтверждённый факт «ты выехал на Pn» важнее прогноза «окно скоро
откроется» — теперь `PIT_EXIT (65) > PIT_WINDOW_APPROACH (55)`, обратный
порядок относительно первой версии спеки).

## Не входит в объём

- Полная 6-причинная классификация position calls (OVERTAKE/OVERTAKEN/PIT/
  RETIREMENT/PENALTY/UNKNOWN) — урезано до 3 корзин, см. «Решение».
- Отдельный трекер смены лидера для квали/практики — уже покрыто `FTLP`.
- Новое понятие `pit_window_opens_in` (оптимальный круг для окна по
  стратегии трассы) — не существует в `StrategyAnalyzer` сейчас, было бы
  отдельной крупной фичей; `laps_left` уже адаптивен, этого достаточно.
- Настоящий overflow-dropping очереди — `ImportanceQueue` безлимитная, не
  меняем это в этой фазе.
- Track-специфичные зоны DRS (детекция «после линии активации») —
  используется только гэп-порог, без привязки к позиции на трассе.

## Архитектура

### Новые файлы

`core/strategy_ai/drs_advisory.py::DRSAdvisoryTracker`:
```python
ENTER_GAP_MS = 1000
EXIT_GAP_MS = 1200
MIN_REPEAT_S = 5.0

class DRSAdvisoryTracker:
    def __init__(self) -> None:
        self._in_range = False
        self._drs_allowed = False
        self._last_range_change_t = 0.0

    def update(self, gap_front_ms: int | None, drs_allowed: bool | None,
               now: float) -> str | None:
        prev_in_range, prev_allowed = self._in_range, self._drs_allowed
        if gap_front_ms is None:
            self._in_range = False          # нет машины впереди -> точно не в зоне
        elif gap_front_ms <= ENTER_GAP_MS:
            self._in_range = True
        elif gap_front_ms > EXIT_GAP_MS:
            self._in_range = False
        # иначе (в полосе гистерезиса 1000-1200) -> состояние не меняется
        if drs_allowed is not None:
            self._drs_allowed = bool(drs_allowed)

        entered = self._in_range and not prev_in_range
        exited = (not self._in_range) and prev_in_range
        allowed_on = self._drs_allowed and not prev_allowed
        allowed_off = (not self._drs_allowed) and prev_allowed

        if (entered or exited) and now - self._last_range_change_t < MIN_REPEAT_S:
            entered = exited = False        # anti-repeat: только вход/выход, allowed/disabled не гасим
        if entered or exited:
            self._last_range_change_t = now

        if (entered and self._drs_allowed) or (allowed_on and self._in_range):
            return random.choice(_ENTERED_AND_ALLOWED)
        if entered:
            return random.choice(_ENTERED_RANGE)
        if allowed_on:
            return random.choice(_DRS_ALLOWED)
        if exited:
            return random.choice(_EXITED_RANGE)
        if allowed_off:
            return random.choice(_DRS_DISABLED)
        return None

    def reset(self) -> None:
        self._in_range = False
        self._drs_allowed = False
        self._last_range_change_t = 0.0
```
Пулы фраз (буквально предложенные пользователем варианты для 4 состояний +
3 составные для случая «оба условия сразу»).

`core/strategy_ai/position_calls.py::PositionCallTracker`:

**Изменение относительно первой версии спеки (найдено ревью):** «сторонние»
изменения позиции теперь тоже идут через settle, не мгновенно — единый
механизм на оба случая (свой пит-стоп / сторонняя причина), различается
только итоговая фраза. Мгновенное срабатывание при быстрой волне (несколько
сходов подряд) звучало бы как очередь реплик подряд; settle коалесцирует до
одной фразы с финальным значением.

```python
OVTK_SUPPRESS_WINDOW_S = 3.0
SETTLE_S = 1.5
SETTLE_MAX_WAIT_S = 8.0

class PositionCallTracker:
    def __init__(self) -> None:
        self._last_pos: int | None = None
        self._recent_ovtk_t = 0.0
        self._pending = False
        self._pending_pos: int | None = None
        self._pending_since = 0.0
        self._pending_armed_at = 0.0
        self._pending_own_pit = False

    def note_ovtk_involving_player(self, now: float) -> None:
        self._recent_ovtk_t = now

    def note_own_pit_exit(self, position: int | None, now: float) -> None:
        self._arm(position, now, own_pit=True)

    def _arm(self, position: int | None, now: float, own_pit: bool) -> None:
        self._pending = True
        self._pending_pos = position
        self._pending_since = now
        self._pending_armed_at = now
        self._pending_own_pit = own_pit

    def check(self, position: int | None, now: float) -> str | None:
        if position is None:
            return None
        if self._pending:
            if position != self._pending_pos:
                self._pending_pos = position
                self._pending_since = now       # ждём стабилизации заново
            settled = now - self._pending_since >= SETTLE_S
            timed_out = now - self._pending_armed_at >= SETTLE_MAX_WAIT_S  # от МОМЕНТА armed, не сбрасывается
            if settled or timed_out:
                own_pit, final_pos = self._pending_own_pit, self._pending_pos
                self._pending = False
                self._last_pos = final_pos
                if own_pit:
                    return f"После пит-стопа ты теперь P{final_pos}."
                return f"Теперь ты P{final_pos}."
            return None
        if self._last_pos is not None and position != self._last_pos:
            if now - self._recent_ovtk_t < OVTK_SUPPRESS_WINDOW_S:
                self._last_pos = position        # OVTK/OVERTAKEN — не озвучиваем вовсе
                return None
            self._arm(position, now, own_pit=False)
            return None
        self._last_pos = position
        return None

    def reset(self) -> None:
        self._last_pos = None
        self._recent_ovtk_t = 0.0
        self._pending = False
        self._pending_pos = None
        self._pending_own_pit = False
```

`core/strategy_ai/leader_change.py::LeaderChangeTracker`:
```python
DEBOUNCE_S = 2.0

class LeaderChangeTracker:
    def __init__(self) -> None:
        self._current: int | None = None
        self._pending: int | None = None
        self._pending_since = 0.0

    def check(self, leader_idx: int | None, now: float) -> int | None:
        if leader_idx is None:
            return None
        if self._current is None:
            self._current = leader_idx      # базовая линия, не "смена"
            return None
        if leader_idx == self._current:
            self._pending = None            # откатился до истечения debounce — не копим устаревший таймер
            return None
        if leader_idx != self._pending:
            self._pending = leader_idx
            self._pending_since = now
            return None
        if now - self._pending_since >= DEBOUNCE_S:
            self._current = leader_idx
            self._pending = None
            return leader_idx
        return None

    def reset(self) -> None:
        self._current = None
        self._pending = None
```
**Найдено самопроверкой спеки (2 бага в первой версии псевдокода):**
1. Без явной обработки `self._current is None` первый же наблюдаемый лидер
   (старт сессии) объявлялся бы как «смена» через 2с — исправлено прямым
   присвоением `_current` на первом вызове, без debounce/объявления.
2. Без сброса `_pending` при откате (`leader_idx == self._current`)
   быстрый фликер A→B→A с последующей ПОВТОРНОЙ сменой на B позже мог бы
   мгновенно «промотировать» B по устаревшему `_pending_since` от первого
   фликера, не дожидаясь полных 2с от настоящей смены — исправлено явным
   сбросом `_pending` при откате.

`core/strategy_ai/pit_window.py` — новый класс `PitWindowApproachTracker`
рядом с существующими функциями:
```python
APPROACH_LAPS_THRESHOLD = 8

class PitWindowApproachTracker:
    def __init__(self) -> None:
        self._announced_this_stint = False

    def check(self, open_: bool, laps_left: int | None) -> str | None:
        if self._announced_this_stint:
            return None
        if not open_ and laps_left is not None and laps_left <= APPROACH_LAPS_THRESHOLD:
            self._announced_this_stint = True
            return "Приближаемся к окну пит-стопа."
        return None

    def reset(self) -> None:
        self._announced_this_stint = False
```

### Проводка в `core/engine.py`

- Новое состояние: `self._player_drs_allowed: bool | None = None`.
- `_update_telemetry`, ветка `PACKET_CAR_STATUS`: после чтения существующих
  ERS-полей — читать `m_drsAllowed@22` (offset уже в golden-master), звать
  `self._drs_advisory.update(self._player_gap_front, self._player_drs_allowed, now)`.
- `_update_telemetry`, ветка `PACKET_LAP_DATA`: после обновления
  `self._player_gap_front` — звать `self._drs_advisory.update(...)` тоже
  (симметрично, оба источника могут прийти первыми).
- Там же: `self._leader_change.check(self._leader_idx, now)`,
  `self._position_calls.check(self._player_pos, now)`.
- `_maybe_snapshot()` (или рядом, где уже есть `st_snapshot` с
  `tyre_compound`/`tyre_age`/`tyre_wear`/`fuel`): вызов
  `detect_pit_window(...)` уже даёт `(open, confidence, laps_left)` —
  прокинуть в `self._pit_window_approach.check(open, laps_left)`.
- OVTK-обогащение (существующий блок в `_handle_event_packet`): если
  `overtaking_idx`/`being_overtaken_idx` == `self._player_car_index` —
  звать `self._position_calls.note_ovtk_involving_player(time.time())`.
- `_maybe_announce_pit_exit`: звать
  `self._position_calls.note_own_pit_exit(self._player_pos, time.time())` и
  `self._pit_window_approach.reset()` в существующей ветке `prev_status in
  (1,2) and new_status==0 and session_type=="race"`.
- Сброс на SSTA/CHQF/flashback (три уже существующие точки, как у всех
  предыдущих трекеров): `self._drs_advisory.reset()`,
  `self._position_calls.reset()`, `self._leader_change.reset()`,
  `self._pit_window_approach.reset()`.
- Каждое новое событие — `speaker: SPEAKER_ENGINEER`, `bypass_speak_threshold:
  True`, готовая фраза через `event["phrase"]` (в обход LLM/templates.py,
  тот же короткий путь, что у всех engineer-трекеров), гейт
  `self._get_setting("engineer_chatter_enabled", True)` перед каждым
  `_enqueue_event`.

## Граничные случаи

- **`gap_front_ms is None`** (нет машины впереди) — `DRSAdvisoryTracker`
  принудительно сбрасывает `_in_range=False` (см. «Решение», раздел 1) —
  НЕ «оставить как есть», это была ошибка первой версии спеки.
- **Рестарт приложения посреди гонки** — все 4 трекера ephemeral, начинают с
  нуля, как остальные трекеры движка.
- **Флешбек** — сброс всех 4 в `_handle_flashback()`, как остальные.
- **`_pending` (позиция) никогда не стабилизируется** (позиция дёргается
  >8с подряд, маловероятно, но защищено) — `SETTLE_MAX_WAIT_S` форсирует
  объявление по последней известной позиции, отсчёт от момента `_arm()`, не
  сбрасывается при повторных изменениях (иначе непрерывная волна изменений
  могла бы откладывать объявление бесконечно).
- **Игрок финиширует/сходит во время `_pending`** — не специальный случай:
  `check()` просто перестанет вызываться так же часто (сессия завершается),
  состояние сбросится на CHQF/SEND как обычно.

## Тестирование

Каждый новый файл — юнит-тесты чистой логики (без моков, без I/O), по
образцу `test_box_call.py`/`test_track_limits.py`:
- `tests/test_drs_advisory.py` — вход/выход из зоны, гистерезис на границе,
  edge-triggered allowed on/off, составная фраза при совпадении условий,
  независимость от порядка вызовов (LapData-first vs CarStatus-first дают
  одинаковый финальный результат), `gap_front_ms=None` сбрасывает `_in_range`
  (и корректно даёт «вход» на следующей близкой машине, а не молчит из-за
  устаревшего состояния), anti-repeat `MIN_REPEAT_S` гасит повторный
  вход/выход того же типа в течение 5с.
- `tests/test_position_calls.py` — подавление рядом с OVTK, settle-задержка
  ОБА случая (свой пит-стоп И сторонняя причина: перезапуск таймера при
  продолжающемся изменении, форс по `SETTLE_MAX_WAIT_S` от момента `_arm()`
  не сбрасывается повторными изменениями), первый тик не объявляет, разные
  итоговые фразы для own_pit=True/False.
- `tests/test_leader_change.py` — debounce (объявление только после ≥2с
  удержания), первое наблюдение НЕ объявляется (устанавливает базовую
  линию), откат до истечения debounce (A→B→A) не объявляет и не оставляет
  устаревший `_pending` (следующая настоящая смена на B ждёт полные 2с
  заново, не мгновенно по старому таймеру) — оба сценария найдены
  самопроверкой спеки, обязательны к покрытию тестами.
- `tests/test_pit_window.py` (расширение существующего, если тестового файла
  для `pit_window.py` ещё нет — создать) — `_announced_this_stint` не
  повторяется при колебаниях `laps_left` внутри стинта, сбрасывается после
  `reset()`.

`tests/test_engine_*.py` (расширения существующих файлов, engine-wiring):
- DRS: `_update_telemetry` из обеих веток (LapData, CarStatus) корректно
  вызывает `update()`, событие в очереди с `speaker`/`bypass_speak_threshold`.
- Position calls: `note_ovtk_involving_player`/`note_own_pit_exit` реально
  вызываются из существующих мест (OVTK-обогащение, `_maybe_announce_pit_exit`).
- Leader change: смена лидера в `_positions`/`leader_idx` доходит до трекера.
- Pit window: сброс `_announced_this_stint` при выезде из боксов.
- Тумблер `engineer_chatter_enabled=False` подавляет все 4 новых типа
  событий (по образцу существующих тестов гейтинга).
- Сброс на SSTA/CHQF/flashback для всех 4.

Полный прогон `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` в конце.
Живая проверка в игре — отдельно пользователем, как и предыдущие фазы.
