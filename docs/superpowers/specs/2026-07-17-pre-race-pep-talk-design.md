# Пре-гоночная реплика инженера («пеп-ток») — дизайн

Дата: 2026-07-17
Статус: утверждён пользователем (диалог 2026-07-17).

## Проблема

В реальных гонках (и в игре F1 25 со штатным инженером) на экране подготовки к
гонке (выбор стратегии/шин, до включения светофора) инженер резюмирует итог
**прошлой гонки этой же карьеры** — например, «в прошлый раз ты показал
отличный темп и взял подиум, давай повторим» или «прошлая гонка не задалась,
пора взять реванш». Сейчас в Spotter такой реплики нет вовсе:

- `SPEAKER_ENGINEER`-реплики (`core/engine.py`, `core/strategy_ai/*`) — все
  ПО ХОДУ гонки (DRS, трек-лимиты, окно пит-стопа, позиционные calls).
- Post-Race Story Mode (`core/race_story.py` + `commentator/story.py`) —
  ретроспектива, звучит ПОСЛЕ финиша, голосом текущей персоны комментатора
  (не инженера).
- `core/career_memory.py` сравнивает только визиты на ОДНУ И ТУ ЖЕ трассу —
  не то, что нужно: пользователь явно уточнил (см. диалог), что речь идёт про
  **финишную позицию в прошлой гонке карьеры, независимо от трассы** — не
  про темп/секторы на этой же трассе в прошлый раз.
- `core/career_stats.py` — агрегат за ВСЮ карьеру (сколько всего побед и т.п.),
  тоже не то: нужна именно ПОСЛЕДНЯЯ гонка, не аккумулятор.
- Готовой функции «последняя гонка карьеры, любая трасса» в архиве нет —
  добавляется тривиально поверх уже существующего
  `analytics/archive.py::list_game_sessions()` (сортирован новыми-first).

## Согласованный объём

- **Триггер:** переход `session_type -> "race"` в `core/engine.py` (строки
  ~969-974 в `_update_telemetry`, ветка `PACKET_SESSION`) — это происходит ЕЩЁ
  на экране стратегии/выбора шин, задолго ДО `SSTA` (вспышка светофора). Найдено
  при исследовании: `SSTA` слишком поздно для этой фичи — это уже старт гонки.
  Только `session_type == "race"` (не квалификация/практика — там нет понятия
  «подиум прошлой гонки»).
- **Задержка:** ~4 секунды после срабатывания триггера (фон-поток, `time.sleep`)
  — по решению пользователя, чтобы дать игроку осмотреться на экране, не
  спорить с другими стартовыми репликами. Формационный круг/выбор стратегии
  занимает намного больше 4с, так что риска не успеть — нет.
- **Данные:** финишная позиция в ПОСЛЕДНЕЙ по времени гонке карьеры,
  **независимо от трассы**. Без сравнения темпа/секторов между разными
  трассами (это физически бессмысленно — разные круги). Без подсчёта очков
  чемпионата/турнирной таблицы (это отдельная, более крупная фича — Spotter не
  трекает результаты AI-соперников за сезон, только результаты игрока по
  сессиям; см. «Вне рамок»).
- **Тиры по финишной позиции последней гонки:**
  - P1–P3 → «подиум» — тон: отличный темп, повторить успех.
  - P4–P10 → «очки» — тон: неплохо, но есть куда расти.
  - P11+ или сход (`final_position` отсутствует/`None`) → «провал» — тон:
    прошлая не задалась, пора взять реванш.
- **Первая гонка карьеры (архив пуст / нет ни одной сессии с
  `session_type == "race"`):** реплика НЕ звучит вообще — инженеру не с чем
  сравнивать. Тот же паттерн отказоустойчивости, что у `CareerMemory.load()
  -> False` / `compute_career_stats() -> None`.
- **Генерация текста:** LLM (YandexGPT, голос персоны `"calm"` — зафиксированный
  голос инженера, `_SPEAKER_VOICE = {SPEAKER_ENGINEER: "calm"}`) с офлайн-
  фолбэком на 3 захардкоженные фразы (по одной на тир) — тот же принцип
  отказоустойчивости, что `commentator/story.py::generate()`.
- **Гейтинг:** существующий тумблер `engineer_chatter_enabled` (тот же, что у
  DRS/трек-лимитов/окна пит-стопа) — новый переключатель в настройках не
  нужен. Плюс общий `_should_voice()` (уважает `autovoice_enabled`/
  `critical_events_enabled`, приоритет `"normal"`).
- **Голос:** `self.voice.say(text, priority="normal", persona="calm")` —
  прямой вызов, В ОБХОД очереди событий (`_enqueue_event`), по паттерну
  `_generate_story` (LLM-генерация асинхронна, может занять пару секунд,
  очередь событий рассчитана на уже готовые фразы). `persona="calm"`
  зафиксирован явно (не берётся из `self.commentator.persona`) — это реплика
  ИНЖЕНЕРА, а не текущего комментатора, как и остальные `SPEAKER_ENGINEER`-
  реплики.
- **Одноразовость за «пребывание» в race:** гвард-флаг
  `self._pre_race_pep_talk_fired`, выставляется в `True` сразу при спавне
  фон-потока (не дожидаясь результата генерации) — защита от дребезга
  `session_type` (не от одного и того же перехода — внешний `new_st !=
  self._session_type` и так гарантирует однократность на КАЖДОЕ изменение).
  Сбрасывается в ТОМ ЖЕ блоке перехода, когда `new_st` меняется на что-то
  ОТЛИЧНОЕ от `"race"` (меню/квалификация/практика) — НЕ на `SSTA` (в отличие
  от `_story_fired`). Так рестарт/flashback ВНУТРИ той же гонки (session_type
  всё это время остаётся `"race"`, `SSTA` может срабатывать многократно) не
  переспрашивает реплику по кругу, а если игрок ОТМЕНИЛ подготовку и вышёл в
  меню, не дойдя до `SSTA`, — следующий заход в race-сессию всё равно
  получит реплику (флаг уже сброшен переходом race → не-race, ждать `SSTA`
  для этого не нужно).
- **Поверхности:** голос + одна строка в `state["feed"]` (как у остальных
  `SPEAKER_ENGINEER`-реплик, цвет `"#38BDF8"`). Никакой отдельной UI-панели,
  никакого replay-слота в `state` (в отличие от `state["race_story"]`) —
  не запрошено, YAGNI.

## Дизайн

### 1. `analytics/archive.py` — новая функция

```python
def get_last_race() -> dict | None:
    """Самая свежая сессия с session_type == "race", независимо от трассы.
    None, если в архиве ещё нет ни одной завершённой гонки (первая гонка
    карьеры) — list_game_sessions() уже отсортирован новыми-first, поэтому
    это первое совпадение, без доп. сортировки."""
    for s in list_game_sessions():
        if s.get("session_type") == "race":
            return s
    return None
```

Возвращает `{"path", "track_name", "track_id", "timestamp", "final_position",
"game_year", "session_type"}` (те же поля, что и элементы
`list_game_sessions()`) — `final_position` может быть `None` (сход/не
финишировал), это валидный случай, не ошибка.

### 2. `core/pre_race_pep_talk.py` (новый файл) — тир по фактам, без I/O/LLM

```python
"""
core/pre_race_pep_talk.py
==========================
Классификация финишной позиции ПОСЛЕДНЕЙ гонки карьеры (независимо от трассы)
в тир для пред-гоночной реплики инженера. Чистый модуль: без I/O и LLM —
данные приходят уже готовыми из analytics/archive.py::get_last_race().

Не путать с core/career_memory.py (трек-специфичная память) и
core/career_stats.py (агрегат за всю карьеру) — здесь нужна ИМЕННО последняя
гонка, любая трасса, только финишная позиция.
"""
from __future__ import annotations

PODIUM, POINTS, STRUGGLED = "podium", "points", "struggled"


def facts(last_race: dict | None) -> dict | None:
    """None, если гонок в карьере ещё не было (первая гонка) — реплика не
    звучит вообще. Иначе {"tier", "position", "track"}."""
    if last_race is None:
        return None
    pos = last_race.get("final_position")
    if pos is None or pos > 10:
        tier = STRUGGLED
    elif pos <= 3:
        tier = PODIUM
    else:
        tier = POINTS
    return {"tier": tier, "position": pos, "track": last_race.get("track_name")}
```

### 3. `commentator/pre_race_pep_talk.py` (новый файл) — промпт + офлайн-фолбэк

Зеркало `commentator/story.py`, но вперёд-смотрящее (не ретроспектива):

```python
"""
commentator/pre_race_pep_talk.py
==================================
Пред-гоночная реплика инженера: превращает тир последней гонки карьеры
(core/pre_race_pep_talk.py) в короткую фразу (1 предложение) голосом
инженера ("calm"). LLM-путь через AIProvider; фолбэк — захардкоженная
фраза на тир (приложение всегда что-то выдаёт).
"""
from __future__ import annotations

from core.broadcast.styles import get_style

_FALLBACK = {
    "podium": "Прошлая гонка — подиум, отличный темп. Повторим результат.",
    "points": "В прошлой гонке набрал очки. Сегодня попробуем прибавить.",
    "struggled": "Прошлая гонка не задалась. Сегодня — реванш.",
}


def build_prompt(facts: dict, persona: str) -> str:
    tier_label = {"podium": "подиум", "points": "очковая зона",
                  "struggled": "провальная, за пределами очков или сход"}[facts["tier"]]
    return "\n".join([
        get_style(persona),
        "\nТы — гоночный ИНЖЕНЕР игрока, говоришь ПЕРЕД стартом новой гонки "
        "(экран выбора стратегии, до светофора). Обращение на «ты».",
        f"\nФАКТ: в прошлой гонке карьеры (трасса: {facts.get('track') or 'неизвестна'}) "
        f"игрок финишировал на позиции {facts['position'] or 'не финишировал'} "
        f"({tier_label}).",
        "\nНАПИШИ короткую пред-гоночную реплику: ОДНО предложение, русский, "
        "без markdown/кавычек/эмодзи. Если тир 'podium' — похвали темп и "
        "предложи повторить. Если 'points' — отметь, что неплохо, но есть "
        "куда расти. Если 'struggled' — коротко подбодри, без разбора причин.",
    ])


def render_fallback(facts: dict) -> str:
    return _FALLBACK[facts["tier"]]


def generate(facts: dict, ai, persona: str) -> str:
    """LLM, при недоступности — офлайн-фолбэк. persona влияет только на
    ТОН промпта (через get_style) — итоговый ГОЛОС всегда "calm" (инженер),
    выбирается вызывающим кодом (core/engine.py), не этим модулем."""
    if ai is not None and getattr(ai, "available", False):
        text = ai.generate(build_prompt(facts, persona), persona)
        if text and text.strip():
            return text.strip()
    return render_fallback(facts)
```

### 4. `core/engine.py` — оркестрация

**Константа задержки** — рядом с остальными тайминг-константами модуля (или
в `config.py`, по аналогии с `AMBIENT_BASE/MAX_INTERVAL`):

```python
PRE_RACE_PEP_TALK_DELAY_S = 4.0
```

**Триггер** — в `_update_telemetry`, сразу после существующего блока (было
только логирование, строки ~969-974):

```python
            if new_st and new_st != self._session_type:
                _log.info("DIAG session_type CHANGED: %s -> %s", self._session_type, new_st)
                self._session_type = new_st
                self._session_guard.set_session_type(new_st)
                with self.state_lock:
                    self.state["session_type"] = new_st
                if new_st == "race":
                    if (not self._pre_race_pep_talk_fired
                            and self._get_setting("engineer_chatter_enabled", True)):
                        self._pre_race_pep_talk_fired = True
                        threading.Thread(
                            target=self._pre_race_pep_talk, daemon=True,
                            name="pre-race-pep-talk").start()
                else:
                    # Уходим из race (в меню/квалификацию/практику) — сброс,
                    # чтобы следующий заход в race-сессию снова получил реплику.
                    self._pre_race_pep_talk_fired = False
```

**Новый метод** (по паттерну `_generate_story`, но без сбора фактов гонки —
только последняя гонка карьеры из архива):

```python
    def _pre_race_pep_talk(self) -> None:
        """Пред-гоночная реплика инженера: итог последней гонки карьеры
        (любая трасса), с задержкой. Фоновый поток — спавнится при переходе
        session_type -> "race" (экран стратегии, до SSTA)."""
        try:
            time.sleep(PRE_RACE_PEP_TALK_DELAY_S)
            if self._session_type != "race":
                return  # игрок успел выйти из подготовки до срабатывания
            last_race = _archive.get_last_race()
            facts = _pep_talk_facts.facts(last_race)
            if facts is None:
                return  # первая гонка карьеры — инженеру не с чем сравнивать
            text = _pep_talk.generate(facts, self.ai, self.commentator.persona)
            if not text:
                return
            voiced = self._should_voice({"event_code": "PRE_RACE_PEP_TALK", "priority": "normal"})
            with self.state_lock:
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": "PRE_RACE_PEP_TALK", "phrase": text,
                    "color": "#38BDF8", "driver": "",
                    "muted": not voiced, "channel": "commentary"})
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
            if voiced:
                self.voice.say(text, priority="normal", persona="calm")
        except Exception as exc:  # noqa: BLE001
            _log.warning("pre-race pep talk generation failed: %s", exc)
```

Импорты (блок импортов `core/engine.py`): `_archive` уже импортирован
(`from analytics import archive as _archive`, строка 50, используется
`_archive.attach_story`) — переиспользуется как есть, новый импорт не нужен.
Два новых импорта: `core.pre_race_pep_talk as _pep_talk_facts`,
`commentator.pre_race_pep_talk as _pep_talk`.

**Инициализация:** `__init__`: `self._pre_race_pep_talk_fired: bool = False`.
Сброс уже описан выше — в самом блоке перехода `session_type`, отдельного
изменения блока `SSTA` эта фича не требует.

## Отказоустойчивость

- `analytics.archive.get_last_race()` переиспользует уже отказоустойчивый
  `list_game_sessions()` (битые файлы архива пропускаются молча, см.
  `archive.py`) — новых точек отказа не добавляет.
- `core/pre_race_pep_talk.py::facts()` — чистая функция без исключений на
  любом валидном входе (`last_race=None`, `final_position=None` — оба
  обработаны явно).
- `_pre_race_pep_talk` целиком обёрнут в `try/except`, как `_generate_story` —
  сбой (сеть, LLM, архив) не роняет телеметрический поток и не блокирует
  остальную логику `_update_telemetry` (спавнится в отдельном потоке ДО сна,
  так что сама телеметрия не блокируется на 4 секунды).
- Повторная проверка `self._session_type != "race"` после `sleep()` — если
  игрок вышел из подготовки за эти 4 секунды (редкий, но дешёвый в проверке
  случай), реплика тихо не звучит вместо того, чтобы прозвучать не в тему.

## Тестирование

- `tests/test_archive.py` (или где живут тесты `analytics/archive.py`) —
  `get_last_race()`: пустой архив → `None`; несколько гонок на разных трассах
  → возвращает самую свежую по времени, а не по трассе; квалификация/практика
  в архиве не мешают (пропускаются, ищем именно `session_type == "race"`).
- `tests/test_pre_race_pep_talk.py` (новый) — `facts()`: `None` вход → `None`
  выход; позиция 1-3 → `"podium"`; 4-10 → `"points"`; 11+ и `None` → оба дают
  `"struggled"`. `commentator/pre_race_pep_talk.py`: `render_fallback()`
  покрывает все 3 тира без исключений; `generate()` уходит в фолбэк при
  `ai.available=False` или пустом ответе LLM (тот же паттерн, что
  `tests/test_story_generator.py` для `commentator/story.py`).
- `tests/test_engine_*.py` (новый или расширение существующего) —
  интеграционный тест: переход `session_type -> "race"` спавнит фон-поток
  ровно один раз; повторный переход в `"race"` БЕЗ промежуточного выхода не
  спавнит второй поток (гвард-флаг ещё не сброшен); переход `"race" ->
  "qualifying"` сбрасывает флаг, следующий переход обратно в `"race"` спавнит
  поток снова; отключённый `engineer_chatter_enabled` полностью гасит фичу
  (тред не спавнится, но флаг всё равно не выставляется в `True` — иначе
  включение тумблера обратно между двумя гонками не сработает, пока флаг не
  сбросят); переход в `"qualifying"`/`"practice"` из состояния, отличного от
  `"race"`, не триггерит фичу вообще.
- Полный `pytest --ignore=tests/test_gpt.py` — без регрессий.

## Вне рамок (явно отклонено/отложено)

- Подсчёт очков/позиции в чемпионате карьеры (турнирная таблица с учётом
  результатов AI-соперников за сезон) — Spotter не трекает результаты
  соперников по сессиям, только результаты игрока. Пользователь подтвердил:
  нужна именно финишная позиция в последней гонке, не турнирная таблица.
- Сравнение темпа/времени круга между разными трассами — физически
  бессмысленно (разные по длине и характеру трассы); track-специфичное
  сравнение уже покрыто `core/career_memory.py`, отдельная фича, не эта.
- Триггер на квалификацию/практику — только `session_type == "race"`.
- Новый переключатель в настройках — переиспользуется `engineer_chatter_enabled`.
- Отдельная UI-панель или replay-слот в `state` — только голос + строка в
  `feed`, как у остальных `SPEAKER_ENGINEER`-реплик.
