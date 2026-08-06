# Phrase Bank Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three gaps in the Free-mode (no-LLM) phrase bank: `PIT_EXIT` has no template at all (falls back to a bare event code), the final laps of a race sound exactly like the middle of it, and `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` only have one neutral phrasing shared across all four personas.

**Architecture:** A new `FINAL_LAPS` dict, structurally parallel to the existing `BATTLE` dict (same shape, same `OVTK`-only scope), gets checked FIRST in `render()`'s pool-selection chain — ahead of `battle` — since ready-made template sentences can't be composed together the way `build_plan()`'s LLM-directive markers can. `PIT_EXIT` gets a `SIMPLE` entry plus `hype`/`calm`/`toxic` entries in `PERSONA` (no tyre-compound mention — this path has no LLM to translate the raw compound code). `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` get `hype`/`calm`/`toxic` entries added to the existing `PERSONA` dict.

**Tech Stack:** Python 3.12, standard library, pytest. No frontend changes in this plan.

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-05-phrase-bank-expansion-design.md`](../specs/2026-07-05-phrase-bank-expansion-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `commentator/templates.py` | изменить | `FINAL_LAPS` (новый словарь) + `_FINAL_LAPS_THRESHOLD`; `render()` — приоритет `final_laps`; `SIMPLE`/`PERSONA` — `PIT_EXIT`; `PERSONA` — `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` для 3 персон |
| `tests/test_phrases.py` | изменить | новые тест-классы: `TestFinalLapsPool`, `TestRenderFinalLaps`, `TestPitExitPool`, `TestRenderPitExit`, `TestPersonaVariantsForPitAndTyre` |
| `CONTEXT.md` | изменить | запись новой сессии |

---

## Task 1: `FINAL_LAPS` — новый пул + приоритет в `render()`

**Files:**
- Modify: `commentator/templates.py`
- Modify: `tests/test_phrases.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_phrases.py`:

```python
# ---------------------------------------------------------------------------
# FINAL_LAPS pool
# ---------------------------------------------------------------------------

class TestFinalLapsPool:
    def test_ovtk_present_and_non_empty(self):
        assert "OVTK" in FINAL_LAPS
        assert len(FINAL_LAPS["OVTK"]) >= 4

    def test_phrases_mention_final_laps(self):
        """Маркер-слово для теста приоритета пулов ниже — SIMPLE/BATTLE["OVTK"]
        сознательно не содержат "последн", чтобы substring-проверка была
        однозначной."""
        assert all("последн" in p.lower() for p in FINAL_LAPS["OVTK"])


class TestRenderFinalLaps:
    def _event(self, code, **kwargs):
        return {"event_code": code, "driver": "Ферстаппен", "target": "Леклер", **kwargs}

    def test_final_laps_pool_used_when_laps_remaining_low(self):
        evt = self._event("OVTK", laps_remaining=2)
        result = render(evt, persona="tv")
        assert "последн" in result.lower()
        assert "{" not in result and "}" not in result

    def test_final_laps_pool_not_used_when_laps_remaining_high(self):
        evt = self._event("OVTK", laps_remaining=10)
        result = render(evt, persona="tv")
        assert "последн" not in result.lower()

    def test_final_laps_pool_not_used_when_laps_remaining_none(self):
        evt = self._event("OVTK")
        result = render(evt, persona="tv")
        assert "последн" not in result.lower()

    def test_final_laps_overrides_battle(self):
        """Готовые фразы нельзя скомпоновать, как маркеры build_plan() —
        final_laps побеждает battle, когда оба условия верны одновременно
        (design spec 2026-07-05-phrase-bank-expansion)."""
        evt = self._event("OVTK", laps_remaining=2, battle=True)
        result = render(evt, persona="tv")
        assert "последн" in result.lower()

    def test_battle_still_used_when_not_final_laps(self):
        evt = self._event("OVTK", laps_remaining=10, battle=True)
        result = render(evt, persona="tv")
        assert "последн" not in result.lower()
```

Добавить `FINAL_LAPS` в импорт из `commentator.templates` в начале файла.

Найти:

```python
from commentator.templates import (
    SIMPLE,
    PERSONA,
    BATTLE,
    _AMBIENT_POOL,
    RARE_POOL,
    render,
    render_ambient,
    render_rare,
)
```

Заменить на:

```python
from commentator.templates import (
    SIMPLE,
    PERSONA,
    BATTLE,
    FINAL_LAPS,
    _AMBIENT_POOL,
    RARE_POOL,
    render,
    render_ambient,
    render_rare,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_phrases.py -q`
Expected: FAIL — `ImportError: cannot import name 'FINAL_LAPS'`

- [ ] **Step 3: `FINAL_LAPS` — новый словарь + константа**

Найти:

```python
BATTLE = {
    "OVTK": [
        "Колёса к колёсам! {driver} атакует {target_acc}!",
        "Вот это борьба! {driver} забирает позицию у {target_gen}!",
        "Они обмениваются позициями уже не первый раз — {driver} снова впереди {target_gen}!",
        "Каждый тормозной конус — сражение. {driver} выиграл этот!",
        "Жёсткая война на трассе. {driver} берёт позицию у {target_gen}!",
    ],
    "DRSE": [
        "DRS в зоне борьбы — {driver} на хвосте у {target_gen}!",
        "DRS открыт прямо за спиной {target_gen}. {driver} готовится!",
    ],
}

# Per-persona ambient observations — used when LLM is unavailable during ambient ticks.
```

Заменить на:

```python
BATTLE = {
    "OVTK": [
        "Колёса к колёсам! {driver} атакует {target_acc}!",
        "Вот это борьба! {driver} забирает позицию у {target_gen}!",
        "Они обмениваются позициями уже не первый раз — {driver} снова впереди {target_gen}!",
        "Каждый тормозной конус — сражение. {driver} выиграл этот!",
        "Жёсткая война на трассе. {driver} берёт позицию у {target_gen}!",
    ],
    "DRSE": [
        "DRS в зоне борьбы — {driver} на хвосте у {target_gen}!",
        "DRS открыт прямо за спиной {target_gen}. {driver} готовится!",
    ],
}

# Порог "последних кругов" для Free-режима — СОБСТВЕННАЯ константа, НЕ импорт из
# commentator/planner.py (design spec 2026-07-05-phrase-bank-expansion): это два
# независимых кодовых пути (LLM-директива vs готовая фраза), у каждого своя копия
# порога, тот же принцип, что уже применён для battle/BATTLE_THRESHOLD — оба пути
# читают уже вычисленное поле события (event["laps_remaining"]), не общий импорт.
_FINAL_LAPS_THRESHOLD = 3

# Готовые фразы (в отличие от build_plan(), где маркеры "последние N кругов"/
# "N-я попытка" компонуются в одну строку) нельзя просто сложить с BATTLE —
# render() выбирает ОДИН пул, FINAL_LAPS первым в очереди проверок (см. ниже).
FINAL_LAPS = {
    "OVTK": [
        "Последний рывок! {driver} обходит {target_acc} на последних кругах!",
        "Это решающий момент гонки — {driver} проходит {target_acc}!",
        "Прямо перед финишем! {driver} забирает позицию у {target_gen}!",
        "На последних кругах — {driver} находит путь мимо {target_gen}!",
        "Ва-банк на исходе гонки! {driver} обходит {target_acc}!",
    ],
}

# Per-persona ambient observations — used when LLM is unavailable during ambient ticks.
```

- [ ] **Step 4: `render()` — приоритет `final_laps`**

Найти:

```python
    if event.get("battle") and code in BATTLE:
        pool = BATTLE[code]
        key = f"battle:{code}"
    else:
        persona_pool = PERSONA.get(persona, {}).get(code)
        pool = persona_pool or SIMPLE.get(code)
        key = f"{persona if persona_pool else 'simple'}:{code}"
```

Заменить на:

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

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_phrases.py -q`
Expected: PASS (все тесты файла, включая 7 новых)

- [ ] **Step 6: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `PIT_EXIT` — `SIMPLE` + `PERSONA`

**Files:**
- Modify: `commentator/templates.py`
- Modify: `tests/test_phrases.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_phrases.py`:

```python
# ---------------------------------------------------------------------------
# PIT_EXIT pool
# ---------------------------------------------------------------------------

class TestPitExitPool:
    def test_present_in_simple(self):
        assert "PIT_EXIT" in SIMPLE
        assert len(SIMPLE["PIT_EXIT"]) >= 4

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_present_in_persona(self, persona):
        assert "PIT_EXIT" in PERSONA[persona]
        assert len(PERSONA[persona]["PIT_EXIT"]) >= 3

    def test_no_tyre_compound_placeholder(self):
        """Согласованное сужение объёма (design spec): PIT_EXIT НЕ упоминает
        состав шин — эта строка не должна ссылаться на {tyre_compound}."""
        all_phrases = list(SIMPLE["PIT_EXIT"])
        for persona in ("hype", "calm", "toxic"):
            all_phrases += PERSONA[persona]["PIT_EXIT"]
        assert all("{tyre_compound}" not in p for p in all_phrases)


class TestRenderPitExit:
    def _event(self, **kwargs):
        return {"event_code": "PIT_EXIT", "driver": "Ферстаппен", **kwargs}

    def test_render_simple(self):
        result = render(self._event(), persona="tv")
        assert result and result.strip()
        assert "{" not in result and "}" not in result

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    def test_render_persona(self, persona):
        result = render(self._event(), persona=persona)
        assert result and result.strip()
        assert "{" not in result and "}" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_phrases.py -q`
Expected: FAIL — `assert "PIT_EXIT" in SIMPLE` (KeyError-style AssertionError, ключа нет)

- [ ] **Step 3: `PIT_EXIT` в `SIMPLE`**

Найти:

```python
    "DAMAGE_HEAVY": [
        "{driver} получил серьёзные повреждения. Гонка под угрозой.",
        "Тяжёлые повреждения машины {driver_gen} — продолжение под вопросом.",
        "Серьёзный ущерб у {driver_gen}. Инженеры принимают решение.",
        "{driver} едет на повреждённой машине — риск очень высок.",
        "Массированный ущерб. Выживет ли машина {driver_gen} до финиша?",
    ],
}

# "tv" намеренно отсутствует
```

Заменить на:

```python
    "DAMAGE_HEAVY": [
        "{driver} получил серьёзные повреждения. Гонка под угрозой.",
        "Тяжёлые повреждения машины {driver_gen} — продолжение под вопросом.",
        "Серьёзный ущерб у {driver_gen}. Инженеры принимают решение.",
        "{driver} едет на повреждённой машине — риск очень высок.",
        "Массированный ущерб. Выживет ли машина {driver_gen} до финиша?",
    ],
    "PIT_EXIT": [
        "{driver} выезжает из боксов!",
        "{driver} возвращается на трассу после остановки.",
        "Пит-стоп {driver_gen} завершён — снова в гонке.",
        "{driver} покидает пит-лейн.",
        "Свежий комплект, {driver} снова на трассе.",
    ],
}

# "tv" намеренно отсутствует
```

**Важно:** «Найти» текст выше включает первую строку следующего комментария
(`# "tv" намеренно отсутствует`) только для уникальности якоря — сам комментарий
не меняется, только добавляется новая запись `PIT_EXIT` перед закрывающей
скобкой словаря `SIMPLE`.

- [ ] **Step 4: `PIT_EXIT` в `PERSONA["hype"]`**

Найти:

```python
        "DAMAGE_HEAVY": [
            "СЕРЬЁЗНОЕ ПОПАДАНИЕ! {driver} едет на металлоломе — гонка под угрозой!",
            "ВОТ ЭТО УЩЕРБ! {driver_gen} машина почти не машина уже!",
            "{driver} с ОГРОМНЫМИ ПОВРЕЖДЕНИЯМИ! Как вообще едет, не понимаю!",
        ],
    },
    "calm": {
```

Заменить на:

```python
        "DAMAGE_HEAVY": [
            "СЕРЬЁЗНОЕ ПОПАДАНИЕ! {driver} едет на металлоломе — гонка под угрозой!",
            "ВОТ ЭТО УЩЕРБ! {driver_gen} машина почти не машина уже!",
            "{driver} с ОГРОМНЫМИ ПОВРЕЖДЕНИЯМИ! Как вообще едет, не понимаю!",
        ],
        "PIT_EXIT": [
            "{driver} ВЫЛЕТАЕТ ИЗ БОКСОВ! Погнали дальше!",
            "БЫСТРАЯ ОСТАНОВКА! {driver} снова в деле!",
            "{driver} возвращается на трассу — не теряем ни секунды!",
            "Пит-стоп сделан! {driver} рвётся обратно в бой!",
        ],
    },
    "calm": {
```

- [ ] **Step 5: `PIT_EXIT` в `PERSONA["calm"]`**

Найти:

```python
        "DAMAGE_HEAVY": [
            "Серьёзные повреждения подтверждены. Оцениваем возможность продолжения для {driver_gen}.",
            "Массированный ущерб у {driver_gen}. Машина за гранью рабочего окна.",
            "Тяжёлые повреждения. {driver} — данные по балансу и прижиму критически изменились.",
        ],
    },
    "toxic": {
```

Заменить на:

```python
        "DAMAGE_HEAVY": [
            "Серьёзные повреждения подтверждены. Оцениваем возможность продолжения для {driver_gen}.",
            "Массированный ущерб у {driver_gen}. Машина за гранью рабочего окна.",
            "Тяжёлые повреждения. {driver} — данные по балансу и прижиму критически изменились.",
        ],
        "PIT_EXIT": [
            "{driver} покидает пит-лейн. Остановка выполнена по плану.",
            "Пит-стоп {driver_gen} завершён. Возврат на трассу.",
            "{driver} возвращается в гонку. Время остановки — в пределах нормы.",
            "Выезд из боксов подтверждён для {driver_gen}.",
        ],
    },
    "toxic": {
```

- [ ] **Step 6: `PIT_EXIT` в `PERSONA["toxic"]`**

Найти:

```python
        "DAMAGE_HEAVY": [
            "Ну и картина... {driver} едет на обломках. Это конец, очевидно.",
            "Серьёзные повреждения у {driver_gen}. Ожидаемо, честно говоря.",
            "Машина {driver_gen} разваливается на ходу. Удивительно, что ещё едет.",
        ],
    },
}

BATTLE = {
```

Заменить на:

```python
        "DAMAGE_HEAVY": [
            "Ну и картина... {driver} едет на обломках. Это конец, очевидно.",
            "Серьёзные повреждения у {driver_gen}. Ожидаемо, честно говоря.",
            "Машина {driver_gen} разваливается на ходу. Удивительно, что ещё едет.",
        ],
        "PIT_EXIT": [
            "{driver} выехал из боксов. Ну, хоть не забыли колесо прикрутить.",
            "Пит-стоп {driver_gen} закончен. Посмотрим, помогло ли.",
            "{driver} снова на трассе. Шины новые, результат — тот же, скорее всего.",
            "Выезжает {driver}. Команда постаралась, теперь очередь за пилотом.",
        ],
    },
}

BATTLE = {
```

**Важно:** этот якорь (`BATTLE = {`) в файле теперь встречается один раз в
контексте закрытия `PERSONA`, но убедись, что редактируешь именно закрывающую
скобку блока `"toxic": {...}` (последний персона-блок перед `BATTLE = {`), а не
случайно более раннее вхождение — в файле есть только одно место, где закрытие
`PERSONA` словаря сразу сопровождается началом `BATTLE = {`.

- [ ] **Step 7: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_phrases.py -q`
Expected: PASS (все тесты файла, включая новые из Task 1 и Task 2)

- [ ] **Step 8: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` — персона-варианты

**Files:**
- Modify: `commentator/templates.py`
- Modify: `tests/test_phrases.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_phrases.py`:

```python
# ---------------------------------------------------------------------------
# Persona variants for previously SIMPLE-only pit/tyre codes
# ---------------------------------------------------------------------------

class TestPersonaVariantsForPitAndTyre:
    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    @pytest.mark.parametrize("code", ["PIT_IN", "PIT_OUT", "TYRE_WEAR_HIGH"])
    def test_persona_has_code(self, persona, code):
        assert code in PERSONA[persona], f"{persona} missing {code}"
        assert len(PERSONA[persona][code]) >= 3

    @pytest.mark.parametrize("persona", ["hype", "calm", "toxic"])
    @pytest.mark.parametrize("code", ["PIT_IN", "PIT_OUT", "TYRE_WEAR_HIGH"])
    def test_render_persona_variant(self, persona, code):
        evt = {"event_code": code, "driver": "Ферстаппен"}
        result = render(evt, persona=persona)
        assert result and result.strip()
        assert "{" not in result and "}" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_phrases.py -q`
Expected: FAIL — `assert 'PIT_IN' in PERSONA['hype']` (и аналогично для остальных
9 комбинаций код×персона)

- [ ] **Step 3: Добавить `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` в `PERSONA["hype"]`**

**Важно (сверено с фактическим состоянием файла после Task 2):** третья фраза
`PIT_EXIT` для `hype` была переформулирована на этапе код-ревью Task 2 —
сейчас в файле `"{driver} ВОЗВРАЩАЕТСЯ! Ни секунды на раскачку!"`, а не
`"{driver} возвращается на трассу — не теряем ни секунды!"`, как в исходном
плане Task 2. «Найти» ниже — АКТУАЛЬНЫЙ текст; если он всё же не совпадёт
дословно — остановись и сверься с файлом напрямую, не подгоняй вслепую.

Найти:

```python
        "PIT_EXIT": [
            "{driver} ВЫЛЕТАЕТ ИЗ БОКСОВ! Погнали дальше!",
            "БЫСТРАЯ ОСТАНОВКА! {driver} снова в деле!",
            "{driver} ВОЗВРАЩАЕТСЯ! Ни секунды на раскачку!",
            "Пит-стоп сделан! {driver} рвётся обратно в бой!",
        ],
    },
    "calm": {
```

Заменить на:

```python
        "PIT_EXIT": [
            "{driver} ВЫЛЕТАЕТ ИЗ БОКСОВ! Погнали дальше!",
            "БЫСТРАЯ ОСТАНОВКА! {driver} снова в деле!",
            "{driver} ВОЗВРАЩАЕТСЯ! Ни секунды на раскачку!",
            "Пит-стоп сделан! {driver} рвётся обратно в бой!",
        ],
        "PIT_IN": [
            "{driver} НЫРЯЕТ В БОКСЫ! Стратегия в действии!",
            "Пит-стоп! {driver} заходит на остановку прямо сейчас!",
            "{driver} в пит-лейне! Механики, за работу!",
        ],
        "PIT_OUT": [
            "{driver} ВЫЛЕТАЕТ ИЗ БОКСОВ НА СВЕЖИХ ШИНАХ!",
            "Новые шины у {driver_gen} — теперь держитесь!",
            "{driver} снова на трассе — атака продолжается!",
        ],
        "TYRE_WEAR_HIGH": [
            "ШИНЫ ГОРЯТ! Деградация растёт на глазах!",
            "Резина на пределе! Скоро придётся решать!",
            "Износ реальный — темп начнёт падать в любой момент!",
        ],
    },
    "calm": {
```

- [ ] **Step 4: Добавить `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` в `PERSONA["calm"]`**

Найти:

```python
        "PIT_EXIT": [
            "{driver} покидает пит-лейн. Остановка выполнена по плану.",
            "Пит-стоп {driver_gen} завершён. Возврат на трассу.",
            "{driver} возвращается в гонку. Время остановки — в пределах нормы.",
            "Выезд из боксов подтверждён для {driver_gen}.",
        ],
    },
    "toxic": {
```

Заменить на:

```python
        "PIT_EXIT": [
            "{driver} покидает пит-лейн. Остановка выполнена по плану.",
            "Пит-стоп {driver_gen} завершён. Возврат на трассу.",
            "{driver} возвращается в гонку. Время остановки — в пределах нормы.",
            "Выезд из боксов подтверждён для {driver_gen}.",
        ],
        "PIT_IN": [
            "{driver} заходит в боксы. Плановая остановка.",
            "Пит-стоп {driver_gen} — по расчётному окну.",
            "{driver} в пит-лейне. Смена резины ожидается.",
        ],
        "PIT_OUT": [
            "{driver} выходит из боксов на новом комплекте.",
            "Смена шин завершена. {driver} возвращается на трассу.",
            "{driver} снова в гонке. Темп будет понятен через круг-два.",
        ],
        "TYRE_WEAR_HIGH": [
            "Износ резины растёт. Пит-окно приближается.",
            "Деградация шин выше расчётной. Мониторим темп.",
            "Уровень износа требует внимания команды.",
        ],
    },
    "toxic": {
```

- [ ] **Step 5: Добавить `PIT_IN`/`PIT_OUT`/`TYRE_WEAR_HIGH` в `PERSONA["toxic"]`**

Найти:

```python
        "PIT_EXIT": [
            "{driver} выехал из боксов. Ну, хоть не забыли колесо прикрутить.",
            "Пит-стоп {driver_gen} закончен. Посмотрим, помогло ли.",
            "{driver} снова на трассе. Шины новые, результат — тот же, скорее всего.",
            "Выезжает {driver}. Команда постаралась, теперь очередь за пилотом.",
        ],
    },
}

BATTLE = {
```

Заменить на:

```python
        "PIT_EXIT": [
            "{driver} выехал из боксов. Ну, хоть не забыли колесо прикрутить.",
            "Пит-стоп {driver_gen} закончен. Посмотрим, помогло ли.",
            "{driver} снова на трассе. Шины новые, результат — тот же, скорее всего.",
            "Выезжает {driver}. Команда постаралась, теперь очередь за пилотом.",
        ],
        "PIT_IN": [
            "{driver} в боксах. Наконец-то, шины уже дымились.",
            "Заезд {driver_gen} на пит-стоп. Давно пора было.",
            "{driver} сворачивает в боксы. Посмотрим, не запорют ли остановку.",
        ],
        "PIT_OUT": [
            "{driver} выехал. Новые шины — старые проблемы, подозреваю.",
            "Свежая резина у {driver_gen}. Поглядим, надолго ли.",
            "{driver} снова на трассе. Ну, хоть попытка есть.",
        ],
        "TYRE_WEAR_HIGH": [
            "Шины сыпятся. Ждём, когда допрут заехать в боксы.",
            "Износ растёт. Классика — тянут до последнего.",
            "Резина уже не резина. Но кто там слушает инженера.",
        ],
    },
}

BATTLE = {
```

- [ ] **Step 6: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_phrases.py -q`
Expected: PASS (все тесты файла — из ядра + Task 1 + Task 2 + Task 3)

- [ ] **Step 7: Checkpoint** — тесты задачи зелёные.

---

## Task 4: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят. Новые тесты этого плана: 7 (FINAL_LAPS) + 9
(PIT_EXIT: 5 в TestPitExitPool с учётом параметризации по 3 персонам + 4 в
TestRenderPitExit) + 18 (персона-варианты PIT_IN/PIT_OUT/TYRE_WEAR_HIGH: 3 кода
× 3 персоны × 2 теста) = +34 к бейслайну 911 passed / 1 skipped на момент
старта этой фичи (см. CONTEXT.md, сессия Race Memory v1, 2026-07-05). Точное
итоговое число — по факту прогона, а не арифметикой. Если итоговая строка не
пропечаталась — считать через `grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import commentator.templates"`
Expected: без ошибок

- [ ] **Step 3: Обновить CONTEXT.md**

Прочитать текущий `CONTEXT.md` целиком, следовать существующей структуре/конвенции
(~100-пунктовый лимит, ~3 последние сессии целиком, архивация старейшей из них
в `docs/CONTEXT_ARCHIVE.md` — ТОЛЬКО если добавление новой записи реально
превышает 3 полных сессии; сначала сосчитать текущее число заголовков `##
Сессия` через `grep -n "^## Сессия" CONTEXT.md`, не предполагать). Добавить
запись новой сессии (3 задачи — FINAL_LAPS, PIT_EXIT, персона-варианты),
реальный тест-бейслайн из Step 1. Явно зафиксировать:

- `templates.py` — Free-режим (без LLM), полностью независимый код-путь от
  `commentator/planner.py`/`build_plan()`. `FINAL_LAPS`/`_FINAL_LAPS_THRESHOLD`
  — СВОИ, не импортированы из `planner.py` (два независимых пути, каждый со
  своей копией порога — тот же принцип, что уже применён для `battle`).
- Готовые фразы (в отличие от компонуемых маркеров `build_plan()`) не
  складываются — `render()` выбирает ОДИН пул; `final_laps` перебивает
  `battle`, когда оба условия верны одновременно.
- `PIT_EXIT` сознательно НЕ упоминает состав шин (`tyre_compound`) — в этом
  пути нет LLM, чтобы перевести код состава на лету; заводить в `templates.py`
  третью копию маппинга код→слово (после `packets.py::TYRE_VISUAL` и
  `personas.py::_TYRE_GLOSSARY`) — осознанно отклонено.
- Сознательно НЕ в этом цикле (по design-спеке): «защита» (успешно отбился от
  атаки) — в конвейере нет события для этого, добавление — отдельная будущая
  мини-фича с новой логикой детекции, не расширение банка фраз.

- [ ] **Step 4: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
