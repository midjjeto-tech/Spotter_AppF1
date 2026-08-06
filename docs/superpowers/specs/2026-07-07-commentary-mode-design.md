# Commentary Mode (live/calm/story) — дизайн

Дата: 2026-07-07
Статус: утверждён пользователем (диалог 2026-07-07), реализация — по плану в
`docs/superpowers/plans/`.

## Проблема

Из исходного UI-пожелания пользователя (после того как «расширение банка фраз» закрыло
цепочку мини-фич поверх Comment Planner): пользователь хочет переключатель live/calm/
story-mode. Это НЕ то же самое, что уже существующая фича «Post-Race Story Mode»
(`core/race_story.py`/`commentator/story.py`) — та генерирует итог-репортаж ПОСЛЕ
финиша. Здесь речь о режиме, который меняет поведение комментатора ВО ВРЕМЯ гонки.

Это также НЕ дублирует `persona` (`tv`/`hype`/`calm`/`toxic`) — `persona` это ХАРАКТЕР
голоса (кто говорит), новый `commentary_mode` это ТЕМП/СТИЛЬ повествования (как часто и
как подробно говорит), независимая ось. Обе оси могут комбинироваться свободно (напр.
persona=toxic + commentary_mode=calm — токсичный, но редкий комментатор).

## Согласованный объём

- **`live`** — сегодняшнее поведение, без изменений (дефолт).
- **`calm`** — МЕНЯЕТ ТОЛЬКО частоту: реже говорит. Тон/длина реплики не меняются.
- **`story`** — та же частота, что и `calm` (реже), ПЛЮС реплики длиннее и связнее
  (используют уже существующие маркеры истории — `battle_count`, `driver_style`/
  `target_style` — и получают лёгкий стилевой намёк для LLM «свяжи с ходом гонки»).
- UI: экран Voice, отдельная панель «Стиль повествования» — рядом с персоной, но НЕ
  внутри неё (разные оси, разные панели).
- Free-mode (без LLM, `templates.py`) деградирует: `story` ведёт себя как `calm`
  (частота снижена, связности неоткуда взяться без LLM) — тот же принцип, что уже
  применён для TTS v3→v1 фолбэка.

## Дизайн

### 1. `core/settings.py` — новый ключ

```python
DEFAULTS: dict = {
    ...
    "commentary_mode": "live",   # "live" | "calm" | "story"
}
```
Никакой валидации значения на этом уровне — `load()`/`save()` уже фильтруют по
известным ключам, лишнего не запишут. Некорректное значение (если когда-то попадёт
в JSON руками) обрабатывается на стороне потребителя (`_speak_threshold()`/
`build_plan()`) через `.get(mode, <live-поведение>)` — молчаливый фолбэк на `live`.

### 2. `core/engine.py::_speak_threshold()` — частота

Текущий код:
```python
def _speak_threshold(self, now: float) -> float:
    elapsed = now - self._last_voiced_at
    if elapsed >= config.PLAN_THRESHOLD_DECAY_S:
        return config.PLAN_BASE_THRESHOLD
    span = config.PLAN_SPIKE_THRESHOLD - config.PLAN_BASE_THRESHOLD
    return config.PLAN_SPIKE_THRESHOLD - span * (elapsed / config.PLAN_THRESHOLD_DECAY_S)
```

Новое: смещение `+20` к обеим границам (`base`/`spike`) для `calm`/`story`, `0` для
`live`. Новая константа в `config.py`:
```python
COMMENTARY_MODE_THRESHOLD_OFFSET = {"live": 0, "calm": 20, "story": 20}
```
```python
def _speak_threshold(self, now: float) -> float:
    offset = config.COMMENTARY_MODE_THRESHOLD_OFFSET.get(
        self._commentary_mode(), 0)
    base = config.PLAN_BASE_THRESHOLD + offset
    spike = config.PLAN_SPIKE_THRESHOLD + offset
    elapsed = now - self._last_voiced_at
    if elapsed >= config.PLAN_THRESHOLD_DECAY_S:
        return base
    span = spike - base
    return spike - span * (elapsed / config.PLAN_THRESHOLD_DECAY_S)
```
`self._commentary_mode()` — маленький хелпер, читающий `self.settings.get(
"commentary_mode", "live")` (тот же паттерн доступа, что уже используют другие настройки
в engine.py).

**Гарантия критических событий:** `score_importance()` уже форсирует `>= 90` для
`priority == "critical"`. Верхняя граница спайка при офсете `+20` — `85` (`65+20`),
что СТРОГО меньше 90 — критические события проходят порог в любом режиме. Это
инвариант, который явно проверяется тестом (offset не должен подниматься до значений,
где `PLAN_SPIKE_THRESHOLD + offset >= 90`).

`_is_stale_backlog_event()` не трогаем — у него свой порог важности
(`PLAN_STALE_IMPORTANCE = 70`), не связанный с частотой речи, режим на него не влияет.

### 3. `commentator/planner.py::build_plan()` — стиль `story`

Новый параметр `mode: str = "live"`. Новое поле в `CommentPlan`:
```python
@dataclass(frozen=True)
class CommentPlan:
    focus: str
    reaction: str
    length: str
    emotion: str
    importance: int
    must_mention: tuple[str, ...] = ()
    narrative: bool = False
```

В `build_plan()`:
```python
narrative = mode == "story"
...
if force_urgent:
    length = _LENGTH_SHORT
    emotion = _shift_emotion(_EMOTION_TOP, persona)
else:
    length = _LENGTH_SHORT if importance >= _LENGTH_SHORT_THRESHOLD else _LENGTH_NORMAL
    emotion = _shift_emotion(_base_emotion(importance), persona)

if narrative:
    length = _LENGTH_NORMAL   # story ВСЕГДА обычная длина, даже force_urgent
```
`narrative` форсирует `_LENGTH_NORMAL` ПОСЛЕ обычной логики (включая `force_urgent`
ветку) — «связнее» важнее «ударнее» в story-режиме. `emotion` НЕ трогаем — пользователь
подтвердил, что `story` меняет только частоту+длину, не тон.

Маркеры (`battle_count`, `driver_style`/`target_style`) уже добавляются в `focus`
независимо от режима — ничего нового считать не нужно, `story` их не создаёт, только
получает бонусом за счёт того, что при сниженной частоте эти маркеры чаще встречаются
у событий, которые вообще проходят порог.

### 4. `commentator/brain.py` — намёк для LLM

Прототип текущей композиции директивы (см. `_compose()` или эквивалент) получает одну
условную строку, добавляемую в промпт ТОЛЬКО когда `plan.narrative`:
```python
if plan.narrative:
    directive_lines.append("Стиль: свяжи с ходом гонки, не отдельная реплика.")
```
Free-mode (`templates.py`) не видит `CommentPlan` вообще (отдельный код-путь,
см. Phrase Bank Expansion) — там `narrative` физически не существует, `story`
дотягивается только через уже применённый частотный офсет в `_speak_threshold()`
(п.2), это и есть механизм деградации до `calm`.

### 5. UI — `NewSpotterUI/components/spotter/views/voice.tsx`

Новая `Panel label="Стиль повествования"`, визуально как существующий блок «Yandex
SpeechKit · Версия синтеза» (карточки-кнопки, активная подсвечена), три варианта
live/calm/story с короткими подписями:
- live — «Как сейчас»
- calm — «Реже»
- story — «Реже и связнее»

`saveSettings({ commentary_mode: id })`, синхронизация текущего значения из
`state.settings.commentary_mode` — тот же паттерн `useEffect`, что уже используют
`ttsVersion`/`radioFx`/персона на этом экране.

**Подсказка про независимость от персоны:** прямо под заголовком панели — короткая
строка пояснения (как уже есть у блока «Yandex SpeechKit · Версия синтеза», см.
`voice.tsx:250-253`, тот же визуальный паттерн `text-xs text-muted-foreground`), явно
разводящая понятия: «Это про то, КАК ЧАСТО и КАК ПОДРОБНО говорит комментатор — не про
характер. Характер (весёлый/спокойный/токсичный) настраивается в панели выше, "Профиль
инженера"». Убирает риск, что пользователь примет `calm` (частота) за смену тона голоса
(то, за что уже отвечает persona=`calm`-подобный toxic/hype spectrum — важно не путать
одинаковое слово "calm" в разных осях, оно и в `persona`, и в `commentary_mode`, но
означает РАЗНОЕ: `persona`-то это скорее нейтральный/сдержанный характер, а
`commentary_mode="calm"` — только реже, тон не трогает).

## Файлы

| Файл | Действие |
|---|---|
| `config.py` | новая константа `COMMENTARY_MODE_THRESHOLD_OFFSET` |
| `core/settings.py` | новый ключ `commentary_mode` в `DEFAULTS` |
| `core/engine.py` | `_speak_threshold()` учитывает офсет режима; новый маленький хелпер чтения режима |
| `commentator/planner.py` | `build_plan()` — параметр `mode`, поле `CommentPlan.narrative`, форс `_LENGTH_NORMAL` |
| `commentator/brain.py` | добавление строки-намёка в директиву LLM при `plan.narrative` |
| `NewSpotterUI/components/spotter/views/voice.tsx` | новая панель «Стиль повествования» |
| `tests/test_planner.py` (или аналог) | `build_plan(mode="story")` — форс normal-длины даже при `force_urgent`/высокой важности; `narrative` True только для story |
| `tests/test_engine*.py` | `_speak_threshold()` — офсет по режиму; инвариант «спайк+офсет < 90» для всех режимов |
| `tests/test_settings.py` | `DEFAULTS` содержит `commentary_mode: "live"`; roundtrip load/save |

## Отказоустойчивость

- Некорректное/отсутствующее значение `commentary_mode` → `.get(..., "live")` на всех
  местах чтения — эквивалент `live`, ничего не падает.
- `_is_stale_backlog_event()` и весь остальной пайплайн вытеснения/дедупа не меняются.
- Free-mode деградация `story` → `calm`-частота — уже описано, не требует доп. кода
  защиты (просто отсутствие `narrative`-логики в этом код-пути).

## Не входит в объём

- «Почему эта фраза» (показ importance/topic в ленте событий) — отдельная будущая
  мини-фича, следующая по списку UI-пунктов.
- Дополнительные ручные регуляторы тон/скорость — persona picker и per-persona
  громкость на экране Voice уже это покрывают, отдельного объёма не требуется, пока не
  запрошено явно.
- Настройка числового значения офсета (`+20`) через UI — фиксированная константа в
  `config.py`, не выведена наружу пользователю в этом цикле.
