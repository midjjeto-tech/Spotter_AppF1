# Каст голосов, этап 2 (характеры и фразы) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Инженер начинает говорить ПО-РАЗНОМУ, а не только звучать по-разному: обращается к пилоту по имени, хвалит за удачные моменты, открывает и закрывает сессию, и три персонажа получают свои формулировки там, где характер действительно слышен.

**Architecture:** Характер входит в банк фраз точечно — `PhraseSpec` получает необязательный словарь `character_variants`, и он есть только у тех спек, где характер читается. Боевые команды (споттер, box-call) остаются буквально одинаковыми у всех троих: пилот обязан узнавать их с первого слога. Обращение по имени — не переписывание 61 спеки, а необязательный префикс, который навешивается в единственной точке рендера. Вся правка проходит через `core/engine.py::_render_engineer_phrase` — через него уже идут все 10 мест, публикующих инженерские реплики.

**Tech Stack:** Python 3 / pytest, Next.js 16 + React 19 (NewSpotterUI), Yandex SpeechKit v3.

**Спека:** `docs/superpowers/specs/2026-08-01-voice-cast-design.md` (§3.3, §3.6, §3.7)
**Предшественник:** `docs/superpowers/plans/2026-08-01-voice-cast-stage1.md` — выполнен 2026-08-02

---

## Решение по объёму (пользователь, 2026-08-02)

Характер меняет формулировки **точечно, там где читается**, а не полным банком на каждого персонажа. Причины:

- полный банк — это ~500 новых фраз, и качество на таком объёме неизбежно просядет;
- у половины спек характеру взяться неоткуда: «Слева машина!» одинаково у всех по определению;
- **безопасность важнее вариативности.** `phrases.py:116` уже требует, чтобы точные команды имели 1–3 почти одинаковых варианта — пилот должен узнать команду, а не разгадывать очередную формулировку. Характер в box-call прямо противоречит этому.

Итого характер получают ~15–20 спек из 61: похвала, ритуалы сессии, советы по шинам и темпу, стратегия, ambient. Безопасность (`spotter.*`, `box.call_*`, `flag.red`, `damage.*_critical`, `penalty.*`) — вне характера, и на это ставится тест.

---

## Что уже готово и переиспользуется

Разведано перед планированием, не выдумано:

- **`core/ru_names.py::first_name_of()`** — уже существует именно «для обращения по радио», корректно отдаёт `None` для кастомного пилота («Моя команда») и для непришедших UDP-данных. Изобретать нечего.
- **`core/engine.py::_render_engineer_phrase()`** — единственная точка рендера, через неё идут все 10 публикующих мест. И характер, и обращение по имени вставляются здесь один раз.
- **`core/radio/resolver.py`** фразу НЕ перерисовывает — читает только `spec_for(code).volatile_fields`. Значит вторая точка входа отсутствует.
- **`OVTK`** несёт `overtaking_idx` / `being_overtaken_idx`, есть `_event_involves(event, idx)` — «игрок обогнал» детектируется без новой телеметрии.
- **`voice_cast.EngineerCharacter`** — готовое место для частоты обращения по имени.

## Оболочка, тесты, бэкап

Те же правила, что на этапе 1 — не повторяются здесь целиком, см. `docs/superpowers/plans/2026-08-01-voice-cast-stage1.md`, разделы «Оболочка и команды», «Как запускать тесты», «Когда гонять ПОЛНЫЙ набор», «Резервная копия перед началом». Кратко:

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q
```

`-X utf8` обязателен. Git в проекте нет. Полный прогон мутирует боевые файлы — исполнителям задач запрещён, делает контроллер: до начала, после backend-части, в финале. Бэкап перед первой правкой обязателен.

**Базовая линия на 2026-08-02: 3590 passed, 1 skipped.**

---

## Структура файлов

| Файл | Ответственность | Действие |
|---|---|---|
| `core/radio/phrases.py` | `character_variants` в `PhraseSpec`, новые секции похвалы и ритуалов | изменить |
| `core/radio/address.py` | обращение к пилоту по имени: решение «навешивать ли» + рендер | **создать** |
| `core/radio/voice_cast.py` | `address_rate` у персонажа | изменить |
| `core/engine.py` | прокинуть характер и имя в рендер; хуки похвалы и ритуалов | изменить |
| `commentator/personas.py` | персона `calm` → «спокойный аналитик» | изменить |
| `commentator/engineer.py` | схлопывается в банк | **удалить** |
| `commentator/brain.py`, `commentator/templates.py` | снять зависимость от удаляемого модуля | изменить |
| `NewSpotterUI/lib/spotter-data.ts` | описания персонажей — теперь можно про манеру | изменить |

Почему `address.py` отдельным модулем, а не функцией в `phrases.py`: банк отвечает на вопрос «как коротко сказать», а обращение — это решение «уместно ли сейчас назвать пилота по имени», зависящее от персонажа, ситуации и наличия имени. Смешивать значит заставить банк знать про настройки.

---

### Task 1: Характер в банке фраз

**Files:**
- Modify: `core/radio/phrases.py` (`PhraseSpec`, `select_variant`, `render`)
- Modify: `core/engine.py::_render_engineer_phrase`
- Test: `tests/test_phrase_characters.py` (создать)

- [ ] **Step 1: Написать падающие тесты**

Создай `tests/test_phrase_characters.py`:

```python
"""Характер персонажа меняет формулировку — но только там, где это безопасно.

Боевые команды обязаны звучать одинаково у всех троих: пилот должен узнать
команду с первого слога, а не разгадывать очередную формулировку
(core/radio/phrases.py, комментарий над реестром). Тест на это стоит здесь, а
не в общем файле банка, потому что это правило про ХАРАКТЕР, а не про длину.
"""
import pytest

from core.radio import phrases, voice_cast


#: Спеки, где характер запрещён. Список закрытый и проверяется тестом:
#: добавление сюда новой безопасной команды должно быть осознанным.
SAFETY_CODES = (
    "spotter.left", "spotter.right", "spotter.both", "spotter.clear",
    "box.call_1", "box.call_2", "box.call_3",
    "flag.red", "penalty.received",
    "damage.wing_critical", "damage.engine_critical",
)


def test_safety_specs_have_no_character_variants():
    for code in SAFETY_CODES:
        spec = phrases.spec_for(code)
        assert not spec.character_variants, f"{code}: характер в боевой команде"


@pytest.mark.parametrize("character", list(voice_cast.CHARACTERS))
def test_safety_phrases_are_identical_for_every_character(character):
    """Не просто «нет вариантов в спеке» — проверяем сам рендер."""
    for code in SAFETY_CODES:
        base = phrases.render(code, selector_key="k")
        with_char = phrases.render(code, selector_key="k", character=character)
        assert base == with_char, code


def test_character_changes_the_wording_where_it_is_allowed():
    """Хотя бы одна спека обязана реально различаться — иначе механика есть,
    а эффекта нет, и это заметят только ушами."""
    code = "praise.overtake"
    said = {phrases.render(code, selector_key="k", character=c)
            for c in voice_cast.CHARACTERS}
    assert len(said) > 1, "все персонажи сказали одно и то же"


def test_unknown_character_falls_back_to_the_shared_pool():
    code = "praise.overtake"
    assert (phrases.render(code, selector_key="k", character="нет такого")
            == phrases.render(code, selector_key="k"))


def test_character_variants_respect_the_length_limit():
    """Лимит длины — свойство СИТУАЦИИ (срочность), а не персонажа. Вариант
    характера не имеет права быть длиннее общего."""
    for spec in phrases.specs():
        for variants in spec.character_variants.values():
            for text in variants:
                assert phrases.word_count(text) <= spec.max_words, text
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_phrase_characters.py -q`
Expected: FAIL — у `PhraseSpec` нет `character_variants`, у `render` нет параметра `character`, спеки `praise.overtake` не существует.

- [ ] **Step 3: Расширить `PhraseSpec`**

В `core/radio/phrases.py`, в датакласс `PhraseSpec`, добавь поле:

```python
    #: Формулировки под конкретного персонажа инженера: {character_id: варианты}.
    #: Пусто у большинства спек и ОБЯЗАНО быть пустым у боевых команд — пилот
    #: должен узнавать команду с первого слога, а не разгадывать, каким
    #: персонажем она сегодня сказана (то же правило, что ограничивает
    #: вариативность spotter.* и box.call_*). Персонаж, которого здесь нет,
    #: получает общий пул `variants`.
    character_variants: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict)
```

`Mapping` уже импортирован в модуле; `field` тоже.

- [ ] **Step 4: Научить выбор варианта характеру**

В `core/radio/phrases.py` добавь функцию рядом с `select_variant`:

```python
def variants_for(spec: PhraseSpec, character: str | None) -> tuple[str, ...]:
    """Пул формулировок для персонажа. Неизвестный персонаж и спека без
    характера дают общий пул — деградация к общему тону безопасна, в отличие от
    молчания."""
    if not character:
        return spec.variants
    return spec.character_variants.get(character) or spec.variants
```

И протяни `character` через `render()`: добавь в сигнатуру параметр `character: str | None = None`, а место, где сейчас берётся `spec.variants`, замени на `variants_for(spec, character)`.

**Важно:** `selector_key` НЕ меняй. Он закрепляет вариант за ситуацией, и подмешивать в него персонажа незачем — при смене персонажа пул и так другой.

- [ ] **Step 5: Прокинуть характер из настроек**

В `core/engine.py::_render_engineer_phrase`, в вызов `radio_phrases.render(...)` добавь:

```python
                character=self._get_setting(
                    "engineer_character", voice_cast.DEFAULT_CHARACTER),
```

`voice_cast` в `core/engine.py` уже импортирован.

- [ ] **Step 6: Добавить первую спеку с характером**

Чтобы тест `test_character_changes_the_wording_where_it_is_allowed` прошёл, нужна `praise.overtake`. Полностью секция похвалы делается в Task 3 — здесь заведи только эту спеку, в реестр `_SPECS`:

```python
    # ── Похвала ──────────────────────────────────────────────────────────────
    # Единственная секция, где персонажи расходятся сильнее всего: одобрение —
    # это и есть характер. Волков отмечает факт, Соколова радуется, Гром
    # признаёт сквозь зубы, и оттого его похвала весит больше.
    _spec("praise.overtake", _N, (
        "Позиция наша. Хорошо.",
        "Обгон засчитан. Работаем дальше.",
    ), action="praise", character_variants={
        "volkov": (
            "Позиция наша. Хорошо.",
            "Чисто сделано. Дальше по плану.",
        ),
        "sokolova": (
            "Отличный обгон! Так держать.",
            "Красиво прошёл. Молодец.",
        ),
        "grom": (
            "Вот так и надо. Не расслабляйся.",
            "Принято. Следующего давай.",
        ),
    }),
```

- [ ] **Step 7: Проверка**

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_phrase_characters.py tests/test_radio_phrases.py tests/test_voice_cast.py -q
```
Expected: зелено. (Если `tests/test_radio_phrases.py` называется иначе — найди файл тестов банка `grep -rln "phrases.render\|spec_for" tests/`.)

---

### Task 2: Обращение к пилоту по имени

**Files:**
- Create: `core/radio/address.py`
- Modify: `core/radio/voice_cast.py` (`address_rate`)
- Modify: `core/engine.py::_render_engineer_phrase`
- Test: `tests/test_radio_address.py` (создать)

Находка №1 ревизии банка: **ни одна из 61 спеки не обращается к пилоту по имени.** Личный инженер, который за гонку ни разу тебя не назвал, личным не ощущается. При этом промпт персоны `calm` это давно умеет (`commentator/personas.py`), а `core/ru_names.py::first_name_of()` существует ровно для этого.

- [ ] **Step 1: Написать падающие тесты**

Создай `tests/test_radio_address.py`:

```python
"""Обращение к пилоту по имени: «Макс, шины сдают.»

Не переписывание банка, а необязательный префикс. Требования, каждое из
которых ловит свою ошибку:
  - никогда без имени (кастомный пилот «Моя команда» → first_name_of() = None);
  - НЕ в каждой реплике — иначе приторно и перестаёт работать как акцент;
  - детерминированно: одна и та же ситуация не меняет решение между пакетами
    телеметрии, иначе повтор переписывал бы уже произнесённое;
  - никогда у споттера — там счёт на доли секунды, лишнее слово стоит места.
"""
import pytest

from core.radio import address, voice_cast


def test_no_name_means_no_address():
    assert address.apply("Шины сдают.", None, "sokolova", "k") == "Шины сдают."
    assert address.apply("Шины сдают.", "", "sokolova", "k") == "Шины сдают."


def test_address_is_deterministic_for_the_same_situation():
    first = address.apply("Шины сдают.", "Макс", "sokolova", "k")
    second = address.apply("Шины сдают.", "Макс", "sokolova", "k")
    assert first == second


def test_address_prefixes_the_name_when_it_fires():
    """Ищем ключ, на котором обращение срабатывает, и проверяем форму."""
    for i in range(50):
        out = address.apply("Шины сдают.", "Макс", "sokolova", f"k{i}")
        if out != "Шины сдают.":
            assert out == "Макс, шины сдают."
            return
    pytest.fail("обращение не сработало ни на одном из 50 ключей")


def test_frequency_differs_between_characters():
    """Частота — часть характера: наставник зовёт по имени чаще сухого
    профессионала. Если частоты совпадут, различие персонажей потеряется."""
    def rate(character: str) -> float:
        hits = sum(address.apply("Шины сдают.", "Макс", character, f"k{i}")
                   != "Шины сдают." for i in range(200))
        return hits / 200

    assert rate("sokolova") > rate("volkov")


def test_every_character_has_a_sane_rate():
    for character in voice_cast.CHARACTERS.values():
        assert 0.0 <= character.address_rate <= 0.5, character.character_id


def test_spotter_phrases_are_never_addressed():
    """У споттера счёт на доли секунды — имя стоит места, которого нет."""
    assert address.apply("Слева машина!", "Макс", "sokolova", "k",
                         allowed=False) == "Слева машина!"
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_radio_address.py -q`
Expected: FAIL — модуля нет.

- [ ] **Step 3: Написать модуль**

Создай `core/radio/address.py`:

```python
"""
core/radio/address.py
=====================
Обращение к пилоту по имени: «Макс, шины сдают.»

Почему отдельный модуль. `phrases.py` отвечает на вопрос «как коротко сказать»,
а здесь решается другой — «уместно ли СЕЙЧАС назвать пилота по имени». Ответ
зависит от персонажа, от ситуации и от того, известно ли имя вообще; тянуть эти
три источника в банк значило бы заставить его знать про настройки.

Почему не в каждой реплике. Обращение — акцент: инженер зовёт по имени, когда
хочет, чтобы услышали именно это. Сказанное в каждой фразе, оно перестаёт
работать и становится приторным. Ту же оговорку несёт промпт персоны `calm`
(`commentator/personas.py`): «делай так не в каждой фразе».

Решение детерминировано по ключу ситуации — тем же crc32, что и выбор варианта
в `phrases.select_variant`, и по той же причине: повторный пакет телеметрии по
той же ситуации не должен переписывать уже произнесённую реплику.
"""
from __future__ import annotations

import zlib

from core.radio import voice_cast

#: Точность решения о частоте. 100 — читаемо в отладке и достаточно точно:
#: разницы между 12% и 12.5% на слух не существует.
_SCALE = 100


def apply(phrase: str, name: str | None, character: str | None,
          selector_key: str, *, allowed: bool = True) -> str:
    """Навесить обращение по имени, если сейчас уместно.

    `allowed=False` — канал, где обращение запрещено безусловно (споттер).
    Отсутствие имени, неизвестный персонаж и пустая фраза дают исходный текст:
    молча не обратиться безопасно, а вот выдумать имя — нет.
    """
    if not allowed or not phrase or not name:
        return phrase
    rate = voice_cast.character(character).address_rate
    if rate <= 0:
        return phrase
    bucket = zlib.crc32(f"addr:{selector_key}".encode("utf-8")) % _SCALE
    if bucket >= rate * _SCALE:
        return phrase
    return f"{name}, {phrase[0].lower()}{phrase[1:]}"
```

- [ ] **Step 4: Частота обращения у персонажей**

В `core/radio/voice_cast.py` добавь поле в `EngineerCharacter`:

```python
    #: Доля реплик, начинающихся с обращения по имени. Часть характера:
    #: наставник зовёт по имени чаще сухого профессионала. Ноль означает
    #: «никогда»; выше 0.5 не поднимать — обращение в каждой второй фразе
    #: перестаёт быть акцентом.
    address_rate: float = 0.15
```

и проставь значения: `VOLKOV` — `0.12`, `SOKOLOVA` — `0.30`, `GROM` — `0.15`.

Дефолт у поля обязателен: `EngineerCharacter` — frozen dataclass, и поле без дефолта после полей с дефолтом не соберётся.

- [ ] **Step 5: Подключить в единственной точке рендера**

В `core/engine.py::_render_engineer_phrase`, после получения фразы из банка и ДО возврата, навесь обращение:

```python
        phrase = radio_phrases.render(...)   # существующий вызов
        return radio_address.apply(
            phrase,
            ru_names.first_name_of(self._player_driver_name()),
            self._get_setting("engineer_character", voice_cast.DEFAULT_CHARACTER),
            selector,
            # Споттеру имя не навешивается: там счёт на доли секунды.
            allowed=radio_policy.channel_for(draft) != radio_policy.CHANNEL_SPOTTER,
        )
```

Проверь фактические имена импортов в шапке `core/engine.py` (`radio_policy` уже есть; `ru_names` и `radio_address` может понадобиться добавить) и приведи вызов к ним.

- [ ] **Step 6: Проверка**

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_radio_address.py tests/test_engine_spotter.py tests/test_engine_position_calls.py tests/test_radio_ptt_dialogue.py -q
```
Expected: зелено.

Отдельно послушай глазами, как это выглядит на реальном имени:

```
cd "G:/Spotter App" && python -X utf8 -c "
from core.radio import address
for i in range(12):
    print(address.apply('Шины сдают, готовь заезд.', 'Макс', 'sokolova', f'sit{i}'))
"
```
Ожидается: часть строк с «Макс, шины сдают…», часть без. Если обращение в каждой — проверь `address_rate`.

---

### Task 3: Секция похвалы

**Files:**
- Modify: `core/radio/phrases.py` (новые спеки)
- Modify: `core/engine.py` (хуки на OVTK игрока и FTLP игрока)
- Test: `tests/test_engine_praise.py` (создать)

Находка №3 ревизии: на весь банк одна спека одобрения (`battle.held`). Инженер только предупреждает и командует — отсюда ощущение сухого ассистента, а не напарника.

- [ ] **Step 1: Написать падающие тесты**

Создай `tests/test_engine_praise.py`. Точка входа — `F1Engine._handle_race_event(event: dict)` (`core/engine.py:2838`): она принимает обычный словарь, поэтому крафтить бинарные пакеты не нужно. Дренаж очереди — тем же приёмом, что в `tests/test_engine_leader_change.py`.

```python
"""Инженер хвалит за удачные моменты — но только пилота и только по делу.

До этой работы на весь банк была одна спека одобрения (battle.held): инженер
только предупреждал и командовал, отсюда ощущение ассистента, а не напарника.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER


PLAYER = 3
RIVAL = 7


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"engineer_chatter_enabled": True})
    e._player_car_index = PLAYER
    e._session_type = "race"
    return e


def _drain(engine) -> list[dict]:
    out = []
    while not engine._commentary_events.empty():
        out.append(engine._commentary_events.get_nowait())
    return out


def _codes(engine) -> set[str]:
    return {e.get("event_code") for e in _drain(engine)}


def test_player_overtake_is_praised(engine):
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    assert "PRAISE_OVERTAKE" in _codes(engine)


def test_being_overtaken_is_not_praised(engine):
    """Игрока обогнали — это повод для обороны, а не для похвалы. Перепутать
    направление обгона значит поздравлять пилота с потерей позиции."""
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": RIVAL,
        "being_overtaken_idx": PLAYER,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)


def test_someone_elses_overtake_is_not_praised(engine):
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": RIVAL,
        "being_overtaken_idx": 11,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)


def test_praise_is_marked_as_an_engineer_line(engine):
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    praise = [e for e in _drain(engine) if e.get("event_code") == "PRAISE_OVERTAKE"]
    assert praise and praise[0]["speaker"] == SPEAKER_ENGINEER
    assert praise[0]["phrase"]


def test_praise_respects_the_chatter_setting(engine):
    """`engineer_chatter_enabled` — общий тумблер болтливости инженера. Похвала
    обязана его уважать, как и все остальные тики."""
    engine.settings["engineer_chatter_enabled"] = False
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)
```

**Прежде чем писать код:** проверь фактические имена полей события обгона —
```
cd "G:/Spotter App" && grep -n "overtaking_idx\|being_overtaken_idx" core/packets.py core/engine.py | head
```
Если поля называются иначе, приведи тест к реальным именам, а не подгоняй код под тест.

Быстрейший круг (`FTLP`, спека `praise.fastest_lap`) — по тому же образцу, игрок определяется через `engine._event_involves(event, PLAYER)`.

- [ ] **Step 2: Спеки похвалы**

Дополни секцию «Похвала» из Task 1 в `core/radio/phrases.py`:

```python
    _spec("praise.fastest_lap", _N, (
        "Быстрейший круг гонки. Отличная работа.",
        "Лучшее время в гонке — сильно.",
    ), action="praise", character_variants={
        "volkov": (
            "Быстрейший круг гонки. Отличная работа.",
            "Лучшее время. Так и держи.",
        ),
        "sokolova": (
            "Быстрейший круг! Ты сейчас лучший на трассе.",
            "Лучшее время гонки — блестяще.",
        ),
        "grom": (
            "Быстрейший круг. Наконец-то.",
            "Вот на что ты способен. Повтори.",
        ),
    }),
    _spec("praise.clean_pit_exit", _N, (
        "Хороший выезд. Разогревай шины.",
        "Чисто из боксов. Работаем.",
    ), action="praise", character_variants={
        "sokolova": (
            "Отличный выезд! Аккуратно на холодных.",
            "Чисто вышли, умница. Грей резину.",
        ),
        "grom": (
            "Нормально вышли. Не растеряй.",
            "Из боксов чисто. Догоняй.",
        ),
    }),
```

Обрати внимание: у `praise.clean_pit_exit` нет варианта `volkov` — он получит общий пул, и это нормально: сухому профессионалу отдельная реакция здесь не нужна, а пустой блок ради симметрии был бы шумом.

- [ ] **Step 3: Хуки в движке**

Похвала — реакция на УЖЕ существующие события, новой телеметрии не нужно.

`OVTK`: обработчик события уже есть (`core/engine.py`, поиск по `event.get("event_code") == "OVTK"`). Игрок-обгоняющий определяется как `event.get("overtaking_idx") == self._player_car_index`. Публикуй инженерский драфт с `event_code="PRAISE_OVERTAKE"`, `speaker=SPEAKER_ENGINEER`, фразой из `praise.overtake`.

`FTLP`: аналогично, игрок определяется через `self._event_involves(event, self._player_car_index)`.

Оба кода добавь в `core/radio/policy.py`: в `_ENGINEER_CODES` и в `_CATEGORY_BY_CODE` с категорией `"praise"`, и заведи `_TTL_BY_CATEGORY["praise"] = 12.0` — похвала уместна по горячим следам, а не через полминуты.

Обязательно уважай `engineer_chatter_enabled` — как это делают соседние тики.

- [ ] **Step 4: Проверка**

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_engine_praise.py tests/test_radio_policy.py tests/test_phrase_characters.py -q
```

---

### Task 4: Ритуалы старта и финиша

**Files:**
- Modify: `core/radio/phrases.py`
- Modify: `core/engine.py`
- Test: `tests/test_engine_session_rituals.py` (создать)

Находка №5: есть `session.pep_talk` перед стартом, но нет проверки радио и нет реакции на финиш. Начало и конец — самые запоминающиеся точки сессии, и они пустые.

- [ ] **Step 1: Спеки**

```python
    _spec("session.radio_check", _N, (
        "Проверка радио. Слышишь меня?",
        "Радио на связи. Как слышимость?",
    ), action="radio_check", character_variants={
        "sokolova": (
            "Проверка связи. Слышишь меня хорошо?",
            "Радио работает. Доброго заезда.",
        ),
        "grom": (
            "Радио. Проверка.",
            "Связь есть. Работаем.",
        ),
    }),
    _spec("session.result", _N, (
        "Финиш. {position} — так и запишем.",
        "Клетчатый. Ты {position}.",
    ), required_fields=frozenset({"position"}), action="session_result",
       character_variants={
        "sokolova": (
            "Финиш! {position} — отличная работа.",
            "Клетчатый флаг. {position}, ты молодец.",
        ),
        "grom": (
            "Финиш. {position}. Разберём.",
            "Клетчатый. {position} — есть над чем работать.",
        ),
    }),
```

`position` — `required_fields`, а НЕ volatile: итог сессии не меняется после флага, и обновлять его перед озвучкой нечего.

- [ ] **Step 2: Хуки**

`session.radio_check` — на старте сессии, рядом с тем местом, где сейчас запускается `PRE_RACE_PEP_TALK`. Проверка радио идёт РАНЬШЕ напутствия: сначала связь, потом разговор.

`session.result` — на `CHQF`, только когда финиширует игрок.

Оба кода — в `_ENGINEER_CODES` и `_CATEGORY_BY_CODE` (категория `"session"`, TTL `None`: итог сессии не устаревает).

- [ ] **Step 3: Тесты**

Создай `tests/test_engine_session_rituals.py`. Обязательные проверки, каждая ловит свою ошибку:

```python
def test_radio_check_fires_once_per_session(engine):
    """Проверка радио на КАЖДЫЙ пакет телеметрии — это не ритуал, это
    неисправность. Нужен edge-trigger, как у остальных тиков инженера."""


def test_radio_check_comes_before_the_pep_talk(engine):
    """Сначала связь, потом разговор. Напутствие в молчащую рацию бессмысленно."""


def test_result_is_announced_only_for_the_player(engine):
    """CHQF приходит на каждого финиширующего. Объявлять чужой результат как
    свой — прямая дезинформация пилота."""


def test_result_is_announced_once(engine):
    """Повторный CHQF (перезаезд, повтор пакета) не должен давать второй итог."""


def test_result_carries_the_finishing_position(engine):
    """`position` — required_fields: без него спека не соберётся, и вместо
    итога прозвучит тишина (PhraseError → пустая строка)."""
```

Тела допиши по образцу `tests/test_engine_praise.py` из Task 3 — тот же `engine`-фикстур и `_drain`. Точку входа для `CHQF` найди так:
```
cd "G:/Spotter App" && grep -n '"CHQF"' core/engine.py
```

- [ ] **Step 4: Проверка**

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_engine_session_rituals.py tests/test_engine_pre_race_pep_talk.py tests/test_radio_policy.py -q
```

---

### Task 5: Слияние двух банков

**Files:**
- Delete: `commentator/engineer.py`
- Modify: `commentator/brain.py`, `commentator/templates.py`
- Modify: `core/radio/phrases.py` (перенести недостающее)
- Test: существующие тесты `commentator/`

Находка №2: `commentator/engineer.py` живой — `brain.py:105` и `templates.py:865` зовут его как фолбэк при отказе LLM. Он покрывает attack / battle / tyre_warning / final_lap / stable — те же ситуации, что `battle.defend`, `tyres.cliff`, `strategy.*` в банке, но другими словами и с другим лимитом длины (20 слов против 9–18). **При сбое LLM инженер незаметно меняет манеру речи.**

- [ ] **Step 1: Свериться с таблицей покрытия**

Таблица составлена при планировании чтением обоих файлов — проверь её и поправь, если разошлось с кодом:

| Ситуация в `engineer.py` | Спека банка | Что делать |
|---|---|---|
| `attack`, `attack_high` | `battle.defend` | покрыто, выбросить |
| `battle` | `battle.defend` | покрыто, выбросить |
| `tyre_warning` | `tyres.cliff` | покрыто, выбросить |
| `stable` | `strategy.stable` | покрыто, выбросить |
| `attack_gap` (`{gap}`) | `gap.behind_closing` | покрыто, выбросить |
| `tyre_wear` (`{wear}`) | `tyres.wear` | покрыто, выбросить |
| **`final_lap`** | — | **ПЕРЕНЕСТИ**: спеки нет |
| **`laps_left`** (`{laps}`) | — | **ПЕРЕНЕСТИ**: спеки нет |
| **`attack_inside`, `attack_hold`, `attack_drs`, `attack_braking`, `attack_approach`** (`{corner}`) | — | **ПЕРЕНЕСТИ**: трек-ориентированной обороны в банке нет вообще |
| **`battle_braking`, `battle_line`** (`{corner}`) | — | **ПЕРЕНЕСТИ**: то же |

Главное, что нельзя потерять: **семь трек-ориентированных формулировок с подстановкой `{corner}`** — «Перед {corner} будет атака. Защити внутреннюю линию.» Это лучший контент удаляемого модуля, и в банке ему аналога нет. Плюс концовка гонки (`final_lap`, `laps_left`).

- [ ] **Step 2: Перенести в банк**

Новые спеки: `battle.defend_corner` (варианты по фазе поворота и по `defense_advice`, поля `{rival}` + `{corner}`), `session.final_laps` и `session.laps_left` (`{laps}`). Коды — в `_ENGINEER_CODES` и `_CATEGORY_BY_CODE`.

Правило выбора варианта по фазе (`braking` / `entry` / прочее) и по `defense_advice` живёт в `engineer.py::get_message` — перенеси эту логику в вызывающий код движка, а не в банк: банк выбирает КАК сказать, а не решает, какая сейчас фаза поворота.

- [ ] **Step 3: Переключить вызывающих и удалить модуль**

`commentator/brain.py:105` и `commentator/templates.py:865` зовут `engineer.get_message(...)` как фолбэк при отказе LLM. Замени на рендер из банка, затем удали `commentator/engineer.py`.

- [ ] **Step 3: Проверка**

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q -k "commentator or brain or templates or phrase"
```
Плюс убедиться, что ссылок не осталось:
```
cd "G:/Spotter App" && grep -rn "commentator.engineer\|from commentator import engineer" --include=*.py . | grep -v __pycache__
```

---

### Task 6: `ambient.calm` — содержание вместо воды

**Files:** `core/radio/phrases.py`, тесты банка

Находка №4: «Темп ровный» / «Ситуация под контролем» / «Всё стабильно» / «Держим как есть» — четыре способа ничего не сказать.

У спеки стоит `allow_llm=True` — это единственная секция, где разрешена генерация. Значит правильный ход не «переписать четыре пустые фразы на четыре другие пустые», а опереться на LLM там, где есть что сказать, и молчать, когда сказать нечего.

**Решение принято при планировании: шаблонный пул сужается до одного варианта, спека остаётся.** Удалять её целиком нельзя — `allow_llm=True` живёт на спеке, и без неё ambient-тик инженера потеряет право говорить вообще, а не только без LLM.

- [ ] **Step 1: Сузить пул**

```python
    _spec("ambient.calm", _L, (
        "Идём по плану.",
    ), allow_llm=True, action="ambient"),
```

Один вариант, а не четыре: когда LLM недоступен, инженер скажет это редко (категория `_L`, `POLICY_DROP_IF_BUSY` — на занятом радио реплика отбрасывается), и повтор одной честной фразы лучше ротации четырёх одинаково пустых.

- [ ] **Step 2: Тест**

Проверить, что `allow_llm` у спеки сохранился — иначе ambient-тик молча онемеет:

```python
def test_ambient_still_allows_generation():
    """`allow_llm` — единственное разрешение на генерацию во всём банке.
    Потеря флага при правке пула сделала бы ambient-тик немым, и заметили бы
    это только по тишине в гонке."""
    assert phrases.spec_for("ambient.calm").allow_llm is True
```

---

### Task 7: Персона `calm` — из инженера в аналитика

**Files:** `commentator/personas.py`, `tests/` персон

Спека §3.7. Промпт сейчас начинается словами «Ты — гоночный инженер на пит-уолле, говоришь пилоту по радио» — после разделения каналов это дубль настоящего инженера, который существует отдельно. Подпись в `speakers.py` уже говорит «ЛЕВ ТИХОНОВ, RACE ANALYST».

- [ ] **Step 1: Переписать промпт**

Тот же сдержанный тон без пафоса, но предмет речи — ГОНКА (аварии, обгоны, раскладка по отрывам), а не советы пилоту. Убрать из промпта блок про обращение к пилоту по имени — это теперь работа инженера, а не комментатора.

Ключ `persona: "calm"` остаётся валидным, миграция не нужна.

- [ ] **Step 2: Тест**

Промпт не должен содержать слов «инженер», «пит-уолл», «говоришь пилоту» — тест на подстроки дешёвый и ловит откат.

---

### Task 8: Описания персонажей в UI + пересборка

**Files:** `NewSpotterUI/lib/spotter-data.ts`, пересборка `webui/`

На этапе 1 описания сознательно урезали до голоса и темпа: манера у всех была общая, и обещать характер значило продавать несуществующее. После Task 1–4 характер появляется — описания можно вернуть к манере, но **только к тому, что реально реализовано**.

- [ ] **Step 1:** Обновить описания под фактическое поведение (частота обращения по имени, тон похвалы).
- [ ] **Step 2:** `pnpm build` + robocopy в `webui/`, проверить что доехало. Без этого правка до пользователя не дойдёт.

---

## Что НЕ входит

- Парные реплики комментатор + инженер на крупных событиях — это этап 3, свой план.
- Портреты новых персонажей в `assets/radio/` — карточка рисуется и без файла (`speakers.py::initials`).
- Расширение каста голосов — закрыто решением 2026-08-02: только премиальные.

## Риски

1. **Объём текста.** ~15–20 спек × 3 персонажа — порядка 80–100 новых формулировок. Писать их партиями по секциям и **читать вслух глазами**, а не полагаться на зелёные тесты: тесты ловят длину и токены, но не то, что фраза звучит по-русски криво.
2. **Похвала может превратиться в спам.** Обгон в плотном трафике идёт пачками. TTL 12 с и общий cooldown помогают, но нужен живой прогон — если инженер хвалит четыре раза за круг, это хуже, чем не хвалить вовсе.
3. **Обращение по имени на длинных фразах.** Префикс добавляет слово к уже посчитанной длине. Проверить, что `word_count` с обращением не вылезает за `max_words` у `_N`-спек, либо сознательно разрешить +1 слово и записать это решение.
