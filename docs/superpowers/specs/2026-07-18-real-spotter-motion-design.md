# Настоящий споттер (car left/right) — дизайн

Дата: 2026-07-18
Статус: утверждён пользователем (диалог 2026-07-18), реализация — по плану в
`docs/superpowers/plans/`.

## Контекст

По итогам обзора конкурентов (Crew Chief V4, GridFather.ai, DRE, Trophi.ai)
выявлен единственный объективный функциональный пробел: приложение
называется Spotter App, но настоящей споттер-функции («держи слева!»,
«чисто») в нём нет — единственная область, где бесплатный Crew Chief V4 на
F1 25 объективно сильнее. Причина — `PACKET_MOTION` (id 0, мировые
координаты всех машин) вообще не парсится; без него определить, с какой
именно стороны идёт соперник, невозможно (только «кто-то рядом», не «слева
или справа»).

Пользователь принял 4 ключевых решения в диалоге:
1. Голос — существующий `SPEAKER_ENGINEER` (calm), новый голос не заводим.
2. Гейт по типу сессии — нет, звучит во всех сессиях (race/qualifying/practice).
3. Повтор — только вход/выход/смена стороны (edge-triggered), без
   периодических «ещё раз» во время долгой борьбы борт-о-борт.
4. Тумблер `engineer_chatter_enabled` — НЕ гейтует (как `PENA`/box-call:
   безопасность, не «болтовня»).

Плюс архитектурное решение (гибрид, а не полный Motion-расчёт для всех 22
машин и не эвристика по рангу позиции без Motion вообще) и принятое
v1-ограничение (заворот дистанции на финишной прямой не обрабатывается —
в проекте нет справочника длины трасс в метрах, заводить 24 константы ради
редкого краевого случая не стали).

## Решение

### 1. Дешёвый фильтр — `lap_distance_m` для всех машин (`core/packets.py`)

`parse_lap_data()` уже читает 22 машины в цикле (позиции/круги/pit_status/
гэп) — добавляем ещё одно поле на офсете `+20` (тот же, что уже подтверждён
для игрока в `parse_player_lap`), без нового риска по офсетам:

```python
def parse_lap_data(data: bytes) -> dict:
    ...
    lap_distances: dict[int, float] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        if base + 35 > len(data):
            break
        ...
        val = struct.unpack_from("<f", data, base + 20)[0]
        lap_distances[idx] = val if 0.0 <= val <= 10000.0 else None
    return {..., "lap_distances": lap_distances}
```

Сравнение — **сырая дистанция по кругу, не ранг позиции**. Машина на круг (и
более) позади по итоговой позиции физически может идти рядом с игроком
прямо сейчас (обгон отстающего/lapping) — именно этот момент важнее всего
не пропустить. Ранг же (`P{n-1}`/`P{n+1}`) в принципе не гарантирует
физическую близость на трассе (кто-то может быть в пит-лейн, кто-то —
на другом круге).

### 2. Motion-пакет (`core/packets.py`, новое)

```python
PACKET_MOTION = 0
MOTION_SIZE = 60  # CarMotionData: см. верификацию ниже

def _motion_fields(data: bytes, base: int) -> dict:
    x, _y, z = struct.unpack_from("<fff", data, base + 0)
    rx, _ry, rz = struct.unpack_from("<hhh", data, base + 30)
    return {
        "world_x": x, "world_z": z,
        "right_x": rx / 32767.0, "right_z": rz / 32767.0,
    }

def parse_motion_all(data: bytes) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * MOTION_SIZE
        if base + MOTION_SIZE > len(data):
            break
        out[idx] = _motion_fields(data, base)
    return out
```

Читаем X/Z (горизонтальная плоскость трассы, Y/высота не нужна для
лево/право) и вектор "право" машины — **только используем его для игрока**,
но парсим единообразно для всех 22 (тот же принцип, что `_car_status_fields`:
один хелпер, engine.py сам решает, что ему нужно из какого индекса).
Игра уже отдаёт единичный вектор "право" машины (`m_worldRightDirX/Z`) —
проекция вектора игрок→соперник на него даёт знак (лево/право) напрямую,
без дополнительной геометрии (cross product и т.п. не нужен).

**Офсеты — реконструкция по публичному формату F1 UDP, ТРЕБУЮТ той же
верификации, что уже применялась к ERS/погоде/трек-лимитам:** официальный
EA-PDF («Data Output from F1 25») + независимый парсер (MacManley/f1-25-udp
или аналог) как два независимых источника, golden-master тест полной
раскладки `CarMotionData` (по образцу `_CAR_STATUS_LAYOUT`), плюс
`SPOTTER_DIAG=1` лог для живой сверки (сравнить с положением машины на
мини-карте HUD игры). До подтверждения — код безопасен (диапазон X/Z
разумно ограничен по размеру трассы, мусор не проходит дальше в вычисления
без валидации).

### 3. `SpotterTracker` (`core/strategy_ai/spotter.py`, новый)

Pure edge-triggered, без I/O — тот же паттерн, что `DRSAdvisoryTracker`.
Не парсит и не знает про пакеты — engine.py уже посчитал латеральное
смещение и сторону для кандидатов, прошедших дешёвый фильтр:

**Ревизия после code-quality-ревью первой версии:** общий `_last_change_t`
на КОМБИНИРОВАННОЕ состояние `(left, right)` — реальный баг, не только
стилистика. Пример: t=0 машина слева → «Держи слева!» (`_last_change_t=0`);
t=1 (тот же тик или следующий) она уходит, а СПРАВА появляется другая
машина → это `changed=True`, но `1-0=1 < MIN_REPEAT_S(3.0)` → подавлено
ОБЩИМ таймером, хотя причина подавления (недавний переход СЛЕВА) не имеет
отношения к новой опасности СПРАВА. Водитель слышит не просто тишину, а
УСТАРЕВШУЮ И УЖЕ НЕВЕРНУЮ команду («слева», хотя опасность теперь справа) —
для safety-функции это хуже отсутствия объявления. Исправление — раздельный
анти-дребезг по каждой стороне (`_last_left_change_t`/`_last_right_change_t`),
по образцу `DRSAdvisoryTracker`, где `entered`/`exited` (одно измерение) и
`allowed_on`/`allowed_off` (независимое измерение) НЕ делят один таймер.
Если анти-дребезг проходит хотя бы одна сторона — объявляется фраза,
отражающая ТЕКУЩЕЕ правдивое комбинированное состояние (`self._left`/
`self._right`), а не то, что именно изменилось (это уже не имеет значения:
слушатель должен узнать, что происходит ПРЯМО СЕЙЧАС, а не что именно
поменялось с прошлого объявления).

```python
LONGITUDINAL_WINDOW_M = 6.0     # длина машины F1 + запас — НЕ откалибровано
LATERAL_ENTER_M = 2.5           # НЕ откалибровано, нужна живая проверка
LATERAL_EXIT_M = 4.0            # НЕ откалибровано, гистерезис как ENTER/EXIT_GAP_MS у DRS
MIN_REPEAT_S = 3.0              # НЕ откалибровано, анти-дребезг на границе порога

_LEFT_ENTER = ["Держи слева!", "Машина слева, не закрывайся!", "Слева атакует."]
_RIGHT_ENTER = ["Держи справа!", "Машина справа, не закрывайся!", "Справа атакует."]
_BOTH = ["Машины с обеих сторон! Держи руль ровно."]  # намеренно одна фраза — редкий и самый критичный случай, вариативность менее важна
_CLEAR = ["Чисто.", "Свободно сзади и по бокам."]


class SpotterTracker:
    """Анти-дребезг (MIN_REPEAT_S) — НЕЗАВИСИМО по каждой стороне (см. ревизию
    выше). Гасит только ВОЗВРАТ фразы, не внутреннее состояние — self._left/
    self._right всегда остаются правдивым снимком текущей геометрии,
    устаревшими не бывают. _last_left_change_t/_last_right_change_t
    обновляются ТОЛЬКО когда переход по этой стороне реально учтён в
    объявлении (не на каждую подавленную попытку этой же стороны) — иначе
    непрерывный дребезг быстрее MIN_REPEAT_S мог бы бесконечно откладывать
    таймер и никогда не объявить эту сторону."""

    def __init__(self) -> None:
        self._left = False
        self._right = False
        self._last_left_change_t = 0.0
        self._last_right_change_t = 0.0

    def update(self, candidates: list[tuple[float, str]], now: float) -> str | None:
        """candidates: [(lateral_abs_m, side), ...] — только те, что уже
        прошли продольный фильтр (LONGITUDINAL_WINDOW_M) в engine.py.
        side: "left" | "right". Возвращает готовую фразу, если хотя бы одна
        сторона прошла свой анти-дребезг, либо None."""
        left_dists = [d for d, s in candidates if s == "left"]
        right_dists = [d for d, s in candidates if s == "right"]
        prev_left, prev_right = self._left, self._right

        if left_dists and min(left_dists) <= LATERAL_ENTER_M:
            self._left = True
        elif not left_dists or min(left_dists) > LATERAL_EXIT_M:
            self._left = False

        if right_dists and min(right_dists) <= LATERAL_ENTER_M:
            self._right = True
        elif not right_dists or min(right_dists) > LATERAL_EXIT_M:
            self._right = False

        left_changed = self._left != prev_left
        right_changed = self._right != prev_right

        left_announceable = left_changed and (now - self._last_left_change_t >= MIN_REPEAT_S)
        right_announceable = right_changed and (now - self._last_right_change_t >= MIN_REPEAT_S)

        if left_announceable:
            self._last_left_change_t = now
        if right_announceable:
            self._last_right_change_t = now

        if not (left_announceable or right_announceable):
            return None

        if self._left and self._right:
            return random.choice(_BOTH)
        if self._left:
            return random.choice(_LEFT_ENTER)
        if self._right:
            return random.choice(_RIGHT_ENTER)
        return random.choice(_CLEAR)

    def reset(self) -> None:
        self._left = False
        self._right = False
        self._last_left_change_t = 0.0
        self._last_right_change_t = 0.0
```

Состояния: `clear` / `left` / `right` / `both`. Повтор того же состояния —
`None` (как договорились — никаких периодических напоминаний). Переход
между ЛЮБЫМИ двумя разными состояниями (включая `left→right` напрямую,
без промежуточного `clear`) — новая фраза.

### 4. Проводка в `core/engine.py`

На каждом Motion-тике (новая ветка `elif packet_id == PACKET_MOTION`):
1. `motion = parse_motion_all(data)`; взять `player = motion.get(self._player_car_index)`.
2. Если `player` есть и есть свежий `self._lap_distances` (из последнего LapData-тика) —
   для каждой другой машины с известной lap_distance и motion-записью:
   - `dx = |lap_distance[idx] - lap_distance[player_idx]|` (без учёта
     заворота круга — принятое v1-ограничение); если `dx > LONGITUDINAL_WINDOW_M` — пропустить.
   - `rel_x, rel_z = motion[idx]["world_x"] - player["world_x"], motion[idx]["world_z"] - player["world_z"]`
   - `lateral = rel_x * player["right_x"] + rel_z * player["right_z"]`
   - `side = "right" if lateral > 0 else "left"`, добавить `(abs(lateral), side)` в кандидаты.
3. `phrase = self._spotter.update(candidates, now)`.
4. Если `phrase` — `_enqueue_event({"event_code": f"SPOTTER_{...}", "phrase": phrase,
   "speaker": SPEAKER_ENGINEER, "bypass_speak_threshold": True, "priority": "critical", ...})`
   **БЕЗ** гейта `engineer_chatter_enabled` (как `PENA`/box-call).
5. `self._lap_distances` обновляется в ветке `PACKET_LAP_DATA` (из `lap_info["lap_distances"]`),
   читается здесь — те же «последние известные значения с любого пакета»,
   что уже применяется для DRS (`gap_front_ms`/`drs_allowed` из разных пакетов).
6. Сброс на SSTA/CHQF/flashback — те же 3 точки, что у остальных трекеров:
   `self._spotter.reset()`.

**Найдено финальным сквозным ревью (реальный баг, не отловленный ни Task 4,
ни Task 5 по отдельности):** `bypass_speak_threshold=True` + `"priority":
"normal"` НЕ дают того, что обещано дизайном («безопасность, как
PENA/box-call»). `bypass_speak_threshold` освобождает только от ДВУХ
конкретных гейтов (`_muted_by_threshold`, `_is_stale_backlog_event`) — это
спроектировано для лёгких РЕПЛИК-КОМПАНЬОНОВ рядом с уже прозвучавшим
critical-событием (`PIT_CALL_NOTICE`/`ENGINEER_GAP_DIGEST`), не для самого
критического предупреждения. Два других гейта его НЕ проверяют вовсе:
1. `SessionGuard.should_emit()` (`core/session_guard.py`) бустрапится
   только по `event["priority"] == "critical"` — при `"normal"` уходит в
   общий per-code cooldown (`_COOLDOWNS["race"]["default"] = 4.0`, без
   явной записи `SPOTTER_*`).
2. Пауза `MIN_COMMENT_GAP` (`_commentary_loop`, `core/engine.py`) блокирует
   поток `time.sleep()` на величину `min_gap` (по умолчанию 9.0с), если
   `importance < PLAN_GAP_SKIP_THRESHOLD (90)` — при важности 70 условие
   всегда истинно, полная 9-секундная пауза применяется целиком.

Реальный сценарий: игрок идёт борт-о-борт, кто-то другой (амбиент/DRS/OVTK)
отговорил в последние 9с → `_spotter_tick` формирует «Держи слева!» → поток
блокируется `time.sleep()` до 9 секунд ПЕРЕД тем, как фраза дойдёт до
озвучки — к этому моменту ситуация борт-о-борт почти наверняка уже
разрешилась (обгон совершён или контакт уже случился). Именно та задержка,
которую фича должна была устранить.

**Исправление — тот же приём, что уже применён к `STRAT_BOX_CALL_*`**
(единственное реально мгновенное синтетическое событие в проекте):
`"priority": "critical"` вместо `"normal"` (флаг `bypass_speak_threshold=True`
остаётся, вреда не несёт, но приоритет — главный механизм). `score_importance()`
уже флорит `importance` до ≥90 для любого `priority=="critical"` события
(`_CRITICAL_FLOOR=90`, `commentator/planner.py`) — это ОДНО изменение
автоматически: (1) обходит `SessionGuard`-cooldown, (2) обходит паузу
`MIN_COMMENT_GAP` (`importance>=90 >= PLAN_GAP_SKIP_THRESHOLD`), (3) обходит
`situation_dedup`/flashback-тишину (обе проверки — `if event.get("priority")
!= "critical"`), (4) даёт `voice_priority="critical"` в `voice.say()` — то
есть реальное ПРЕРЫВАНИЕ уже звучащей фразы (`PLAN_INTERRUPT_THRESHOLD`),
что для споттера семантически ВЕРНО (реальный споттер прерывает болтовню
инженера ради «держи слева!», а не ждёт своей очереди).

Событийные коды: `SPOTTER_CAR_LEFT`, `SPOTTER_CAR_RIGHT`, `SPOTTER_CAR_BOTH`,
`SPOTTER_CLEAR` (определяются в engine.py по факту нового состояния трекера,
не отдельными вызовами `update()`). `commentator/planner.py::_BASE_IMPORTANCE`
получает все 4 записи (70) — при `priority="critical"` не влияет на итоговую
важность (флор 90 её всё равно перекрывает), но запись оставлена для
консистентности с остальными кодами таблицы (тот же паттерн, что у
`STRAT_BOX_CALL_*`, чей код тоже в таблице, хотя реально не используется
при priority=critical).

**Почему пит-лейн не требует отдельной обработки:** машина в пит-лейн может
случайно совпасть с игроком по `lap_distance` (пит-лейн — параллельный
путь, дистанция вдоль него мапится в похожие значения), но её мировые X/Z
физически далеко от основной трассы (пит-лейн отделён от трассы на
десятки метров) — латеральный порог (~2.5-4 м) отсекает её на втором шаге
без специального кода.

## Не входит в объём

- Периодические «ещё раз» во время долгой борьбы борт-о-борт — только
  edge-triggered (решение пользователя).
- Гейт по типу сессии — звучит везде (решение пользователя).
- Обработка заворота `lap_distance` на финишной прямой — принятое
  v1-ограничение, нет справочника длины трасс в метрах.
- Отдельный голос «споттер», отличный от инженера — не заводим.
- Взаимодействие пар машин НЕ включающих игрока (например, борьба за
  P5 между двумя ИИ) — споттер сообщает только про машины относительно
  ИГРОКА, не общий трекер всех столкновений на трассе (это другая фича).
- Учёт `m_worldForwardDirX/Z` — не нужен, продольная близость уже даётся
  дёшево через `lap_distance`, а не через проекцию на forward-вектор.

## Граничные случаи

- **Нет кандидатов вообще** (игрок один на трассе/в отрыве) — `candidates=[]`,
  `SpotterTracker` держит `clear`, `update()` возвращает `None` (уже был
  `clear`, изменения нет) — не переспамливает «чисто» на каждый тик.
- **Игрок неизвестен в Motion-пакете** (`player_car_index` вне диапазона,
  либо буфер короче ожидаемого) — пропустить тик целиком, как и другие
  ветки `_update_telemetry` при недостаточных данных.
- **Флешбек** — `self._spotter.reset()`, как остальные трекеры.
- **Рестарт приложения посреди гонки** — трекер ephemeral, начинает с `clear`.
- **Резкий переход `left→right`** (соперник пересёк игрока по диагонали за
  один тик) — не проходит через промежуточный `clear`, сразу новая фраза
  (см. `SpotterTracker.update` — сравнение по паре `(left, right)` целиком).
- **Переход подавлен анти-дребезгом (`MIN_REPEAT_S`) — не откладывается,
  а теряется навсегда**, если состояние с тех пор не изменилось СНОВА. Та
  же семантика, что уже принята и задокументирована у `DRSAdvisoryTracker`
  (см. его docstring про anti-repeat) — сознательно не копим очередь
  пропущенных объявлений.

## Тестирование

- `tests/test_packets_motion.py` (новый) — golden-master раскладки
  `CarMotionData` (по образцу `_CAR_STATUS_LAYOUT`), `parse_motion_all` на
  синтетических байтах (известные X/Z/right_x/right_z на входе → ожидаемый
  словарь), усечённый буфер не падает.
- `tests/test_spotter.py` (новый) — вход слева/справа/обе стороны,
  гистерезис на границе `LATERAL_ENTER_M`/`LATERAL_EXIT_M`, anti-repeat
  `MIN_REPEAT_S` гасит дребезг у порога, `left→right` напрямую даёт новую
  фразу без промежуточного `clear`, повтор того же состояния — `None`,
  `reset()`.
- `tests/test_engine_spotter.py` (новый, по образцу `test_engine_planner.py`) —
  проводка Motion-тика: дешёвый фильтр по `lap_distance` действительно
  отсекает дальние машины ДО геометрии, событие уходит с `speaker`/
  `bypass_speak_threshold`, НЕ гасится `engineer_chatter_enabled=False`,
  сброс на SSTA/CHQF/flashback.
- Vacuous-тест-ловушка (найдена в проекте уже несколько раз для похожих
  трекеров) — явно проверить, что тест на «нет кандидатов» отличает
  «остался clear» от «был left, стал clear» (оба должны давать разный
  результат теста, не один и тот же assert).

Полный прогон `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` в конце.
Живая проверка в игре (звучание фраз, калибровка `LATERAL_ENTER_M`/
`LATERAL_EXIT_M`/`LONGITUDINAL_WINDOW_M`, сверка офсетов Motion через
`SPOTTER_DIAG=1` с мини-картой HUD) — отдельно пользователем, как и
предыдущие фазы; отражено в task #1 (живая проверка) очереди задач.
