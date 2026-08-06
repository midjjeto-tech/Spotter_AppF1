# Каст голосов, этап 1 (каркас) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Развести голоса трёх радио-каналов (комментатор / инженер / споттер) так, чтобы они никогда не совпадали, дать пользователю выбор персонажа инженера и наложить эффект рации только на инженера со споттером.

**Architecture:** Роль становится полноправным «слотом голоса» рядом с четырьмя персонами комментатора в `yandex_ai/voices.py`. Новый чистый модуль `core/radio/voice_cast.py` раздаёт голоса по правилу «первый свободный из своего списка» в порядке комментатор → инженер → споттер и отдаёт результат через УЖЕ существующий, но сегодня мёртвый механизм `Voice.set_voice_overrides()`. Движок перестаёт вычислять голос сам и начинает читать `RadioMessage.voice_persona`, который правильно вычислен по каналу с самого начала и до сих пор игнорировался.

**Tech Stack:** Python 3 / pytest, Next.js 16 + React 19 (NewSpotterUI), Yandex SpeechKit v3, Piper (фолбэк).

**Спека:** `docs/superpowers/specs/2026-08-01-voice-cast-design.md` (этапы 2 и 3 получат свои планы после этого).

---

## Отклонение от спеки — прочти до начала

Спека (§5, этап 1) просит «оживить `persona_voice` в `settings.DEFAULTS` и в UI». План делает **не это**, и намеренно.

`persona_voice` — это «переопредели голос для персоны». Но настройка, которую на самом деле выбирает пользователь, — это **персонаж инженера**, а голос из неё вычисляется вместе с персоной комментатора (иначе не удержать инвариант несовпадения). Если оставить пользователю прямой доступ к `persona_voice`, он сможет руками выставить инженеру голос комментатора — и сломать ровно то, ради чего всё делается.

Поэтому: в настройках появляется `engineer_character`, а механизм `set_voice_overrides()` остаётся внутренним каналом доставки — его теперь кормит `voice_cast.resolve()`, а не пользователь. Мёртвый блок чтения `settings["persona_voice"]` из `apply_settings` удаляется (Task 5, Step 4): после этой работы он не просто мёртв, он вреден — затирал бы оверрайды каста.

Итог тот же, что просила спека — голос инженера выбирается из UI, — но через ручку, которой нельзя выстрелить себе в ногу.

---

## ВАЖНО: в этом проекте нет git

`git rev-parse` → «not a repository». Шагов `git commit` в плане нет и быть не может. Вместо коммита каждая задача заканчивается **чекпойнтом**: прогоном затронутых тестов, а в конце — полного набора. Не пытайся инициализировать репозиторий — это не входит в задачу.

## Оболочка и команды

В плане есть команды для двух разных оболочек. **У каждого блока указано, какая именно** — не запускай вслепую:

- `Shell: любая` — работает и в Git Bash, и в PowerShell (все команды `python …`).
- `Shell: PowerShell` — только PowerShell (`robocopy`, `$LASTEXITCODE`).
- `Shell: Git Bash` — только bash (`grep`, `head`, конвейеры).

**Никаких `VAR=value команда`** — эта запись не работает в PowerShell. Для UTF-8 используй флаг интерпретатора, он кросс-оболочечный.

## Как запускать тесты

`Shell: любая`

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q
```

Одиночный файл:

```
cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -v
```

**`-X utf8` обязателен.** Без него консоль Windows глотает сводку pytest: видны только точки прогресса, нет ни «N passed», ни списка упавших — красный прогон выглядит зелёным. Код возврата при этом честный (0 = зелено), так что при сомнениях смотри на него или снимай точные числа через `--junit-xml`.

## Когда гонять ПОЛНЫЙ набор

Полный прогон мутирует боевые файлы пользователя (`commentator_memory.json`, `race_cache.json`) — см. ниже. Пока изоляция не починена, гоняй его **ровно три раза**, а не после каждой задачи:

1. **до начала работ** — снять базовую линию (иначе «столько же провалов, сколько было» не с чем сравнивать);
2. **после backend-части** (задачи 1–6) — там, где менялось поведение;
3. **в финале**.

Между ними хватает точечных прогонов затронутых файлов. Исполнителям задач полный прогон запрещён — его делает контроллер.

## Резервная копия перед началом

`Shell: PowerShell`

Git в проекте нет, а план меняет десяток Python-файлов и выполняет `robocopy /MIR`, который зеркалит и **удаляет** из `webui/` всё, чего нет в новой сборке. Отката из коробки не существует. Перед первой правкой:

```powershell
$stamp = "voice-cast-stage1-" + (Get-Date -Format "yyyy-MM-dd_HHmm")
$dst = "G:\Spotter App\_backup\$stamp"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item "G:\Spotter App\webui" -Destination "$dst\webui" -Recurse
foreach ($f in @("core\engine.py","core\settings.py","voice\tts.py",
                 "core\radio\policy.py","core\radio\speakers.py",
                 "yandex_ai\voices.py","new_tts\piper_tts.py")) {
    $t = Join-Path $dst $f
    New-Item -ItemType Directory -Force (Split-Path $t) | Out-Null
    Copy-Item (Join-Path "G:\Spotter App" $f) $t
}
Get-ChildItem $dst -Recurse -File | Get-FileHash | Export-Csv "$dst\hashes.csv" -NoTypeInformation
"backup -> $dst"
```

В проекте уже есть такая конвенция (`_backup_pre_newui_2026-06-23`, `_backup_pre_yandex_2026-06-22`) — держись её.

**Базовый прогон перед началом работ (2026-08-01): полностью зелёный** — 3542 passed, 1 skipped (пропущен `test_ergast_client.py::test_live_smoke_get_current_drivers`, живой сетевой тест). Значит любой провал на чекпойнте — настоящая регрессия, а не унаследованный шум. Ничего «уже красного» списывать нельзя.

**Две особенности окружения, найденные на Task 1:**

1. **Полный прогон пишет в боевой `commentator_memory.json`.** `commentator/brain.py:67` создаёт `PhraseMemory()` без пути, дефолт — `config.DATA_DIR / "commentator_memory.json"`, а в dev-режиме `DATA_DIR` это корень проекта. То есть каждый полный прогон мутирует живой файл пользователя. Проблема существовала до этой работы и чинится отдельно. **Следствие для исполнителей: полный прогон гоняй только там, где он реально нужен как чекпойнт, а не после каждого шага.** Для точечной проверки хватает файлов из задачи.
2. **Сводная строка pytest не печатается без UTF-8-режима** — консоль Windows глотает вывод на не-ASCII. Как запускать, см. раздел «Как запускать тесты» выше: флаг `-X utf8`, а не переменная окружения (та не работает в PowerShell).

---

## Структура файлов

| Файл | Ответственность | Действие |
|---|---|---|
| `core/radio/voice_cast.py` | персонажи инженера + раздача голосов по ролям | **создать** |
| `tests/test_voice_cast.py` | перебор всех сочетаний персона × персонаж | **создать** |
| `yandex_ai/voices.py` | каталог голосов; добавить слоты `engineer` / `spotter` | изменить |
| `new_tts/piper_tts.py` | то же для Piper-фолбэка | изменить |
| `core/radio/policy.py` | `_VOICE_PERSONA` → имена слотов | изменить |
| `core/radio/speakers.py` | `voice_persona` профилей → имена слотов | изменить |
| `core/engine.py` | читать `message.voice_persona`; пересчёт каста при смене настроек | изменить |
| `core/settings.py` | ключ `engineer_character` | изменить |
| `voice/tts.py` | поканальный radio_fx; защита `set_persona` | изменить |
| `NewSpotterUI/lib/spotter-data.ts` | список персонажей для UI | изменить |
| `NewSpotterUI/components/spotter/views/voice.tsx` | панель выбора инженера | изменить |

Почему `voice_cast.py` отдельным модулем, а не функцией в `policy.py`: раздача голосов зависит от ДВУХ пользовательских настроек сразу (персона комментатора + персонаж инженера), а `policy.py` по своему контракту — чистые таблицы решений без пользовательского состояния.

---

### Task 1: Модуль раздачи голосов

**Files:**
- Create: `core/radio/voice_cast.py`
- Test: `tests/test_voice_cast.py`

- [ ] **Step 1: Написать падающий тест**

Создай `tests/test_voice_cast.py`:

```python
"""Раздача голосов по ролям: комментатор / инженер / споттер."""
import itertools

import pytest

from core.radio import voice_cast
from yandex_ai import voices


ALL_PERSONAS = ("tv", "hype", "calm", "toxic")


@pytest.mark.parametrize("persona,character",
                         list(itertools.product(ALL_PERSONAS, voice_cast.CHARACTERS)))
def test_three_roles_never_share_a_voice(persona, character):
    """Главный инвариант: ни при каком сочетании настроек два канала не звучат
    одним голосом. 4 персоны x 3 персонажа = 12 сочетаний, перебираются все."""
    cast = voice_cast.resolve(persona, character)
    commentator = voices.resolve(persona)["voice"]
    engineer = cast[voice_cast.SLOT_ENGINEER]["voice"]
    spotter = cast[voice_cast.SLOT_SPOTTER]["voice"]
    assert len({commentator, engineer, spotter}) == 3


def test_character_keeps_its_preferred_voice_when_free():
    """Персона toxic занимает kirill — alexander свободен, Волков его получает."""
    cast = voice_cast.resolve("toxic", "volkov")
    assert cast[voice_cast.SLOT_ENGINEER]["voice"] == "alexander"


def test_character_yields_when_commentator_took_its_voice():
    """persona=tv занимает alexander — Волков уходит на запасной kirill."""
    cast = voice_cast.resolve("tv", "volkov")
    assert cast[voice_cast.SLOT_ENGINEER]["voice"] == "kirill"


def test_spotter_needs_its_third_preference():
    """persona=hype берёт anton, Гром уходит на kirill — споттеру остаётся
    только третий пункт списка. Тест фиксирует, что два пункта у споттера НЕ
    сработали бы: это не запас на всякий случай."""
    cast = voice_cast.resolve("hype", "grom")
    assert cast[voice_cast.SLOT_SPOTTER]["voice"] == "alexander"


def test_unknown_character_falls_back_to_default():
    assert voice_cast.character("нет такого").character_id == voice_cast.DEFAULT_CHARACTER
    assert voice_cast.character(None).character_id == voice_cast.DEFAULT_CHARACTER


def test_resolve_shape_matches_voice_overrides_contract():
    """Формат обязан совпадать с тем, что принимает Voice.set_voice_overrides()
    и yandex_ai.voices.resolve(persona, overrides) — иначе оверрайд молча
    проигнорируется (voices.resolve отбрасывает неизвестные ключи)."""
    cast = voice_cast.resolve("tv", "volkov")
    for slot in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER):
        assert set(cast[slot]) == {"voice", "emotion", "speed"}


def test_every_character_voice_exists_in_the_catalogue():
    """Опечатка в имени голоса даёт 400 от SpeechKit и МОЛЧАЛИВЫЙ уход на
    Piper — ловим её тестом, а не ушами в гонке."""
    for character in voice_cast.CHARACTERS.values():
        for voice in character.voices:
            assert voice in voices.AVAILABLE_VOICES
    for voice in voice_cast.SPOTTER_VOICES:
        assert voice in voices.AVAILABLE_VOICES
```

- [ ] **Step 2: Запустить и убедиться, что тест падает**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.radio.voice_cast'`

- [ ] **Step 3: Написать модуль**

Создай `core/radio/voice_cast.py`:

```python
"""
core/radio/voice_cast.py
========================
Кто каким голосом говорит: раздача голосов Yandex по трём ролям.

Почему отдельный модуль. `policy.py` отвечает на вопрос «кто говорит» (канал),
`speakers.py` — «как подписать карточку в кадре», этот — «каким голосом».
Смешивать их нельзя: раздача голосов зависит от ДВУХ пользовательских настроек
сразу (персона комментатора и персонаж инженера), а `policy.py` по своему
контракту держит чистые таблицы решений без пользовательского состояния.

Причина существования модуля — арифметика. Премиальных нейроголосов четыре
(`yandex_ai/voices.py`), ролей три, и голос комментатора жёстко задан его
персоной. Значит инженер и споттер обязаны уметь уступать занятый голос.
Правило одно: «первый свободный из своего списка», роли разрешаются по порядку
комментатор → инженер → споттер.

Длина списка диктуется позицией в очереди: роли, разрешаемой N-й по счёту,
нужен список из N голосов — перед ней занято ровно N-1, поэтому N-й пункт
гарантированно свободен. Инженеру хватает двух, споттеру нужно три, и третий
пункт у споттера реально срабатывает (persona=hype + Виктор Гром), а не лежит
запасом.

Споттеру выбор голоса НЕ даётся намеренно: safety-канал должен быть одинаково
узнаваем у всех пользователей.

Имена персонажей вымышленные — то же правило, что в `speakers.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from yandex_ai import voices

#: Слоты голоса. Совпадают с ключами `voices.DEFAULT_PERSONA_VOICE` и
#: `new_tts.piper_tts.PERSONA_VOICE`: движок передаёт слот туда, где раньше
#: передавал персону, поэтому вся цепочка синтеза и ключ кэша работают без
#: правок.
SLOT_ENGINEER = "engineer"
SLOT_SPOTTER = "spotter"


@dataclass(frozen=True, slots=True)
class EngineerCharacter:
    """Персонаж инженера: подпись, голоса по убыванию предпочтения, темп."""

    character_id: str
    display_name: str
    #: Минимум ДВА голоса — инженер разрешается вторым (см. шапку модуля).
    voices: tuple[str, ...]
    speed: float


VOLKOV = EngineerCharacter(
    character_id="volkov",
    display_name="ИГОРЬ ВОЛКОВ",
    voices=("alexander", "kirill"),
    speed=1.0,
)
SOKOLOVA = EngineerCharacter(
    character_id="sokolova",
    display_name="МАРИНА СОКОЛОВА",
    voices=("marina", "alexander"),
    speed=0.95,
)
GROM = EngineerCharacter(
    character_id="grom",
    display_name="ВИКТОР ГРОМ",
    voices=("anton", "kirill"),
    speed=1.1,
)

CHARACTERS: MappingProxyType[str, EngineerCharacter] = MappingProxyType({
    c.character_id: c for c in (VOLKOV, SOKOLOVA, GROM)
})

#: Дефолт — действующий персонаж карточки инженера (`speakers.RACE_ENGINEER`).
DEFAULT_CHARACTER = VOLKOV.character_id

#: Споттер: три голоса — необходимость, а не запас (см. шапку).
SPOTTER_VOICES: tuple[str, ...] = ("kirill", "anton", "alexander")
SPOTTER_SPEED = 1.1

#: Роли говорят ровно нейтрально: «характер» несёт ТЕКСТ и темп, не legacy-роль
#: SpeechKit. Премиальные нейроголоса эмоции всё равно не поддерживают
#: (см. комментарий над `voices.DEFAULT_PERSONA_VOICE`).
_EMOTION = "neutral"


def character(character_id: str | None) -> EngineerCharacter:
    """Персонаж по id. Неизвестный или None -> дефолтный."""
    return CHARACTERS.get(character_id or "", VOLKOV)


def _first_free(preferences: tuple[str, ...], taken: set[str]) -> str:
    for voice in preferences:
        if voice not in taken:
            return voice
    # Списки подобраны так, что сюда не дойти — это проверяет тест на все 12
    # сочетаний. Но падать здесь нельзя: молчащая рация хуже совпавшего тембра.
    return preferences[-1]


def resolve(persona: str, character_id: str | None = None) -> dict[str, dict]:
    """Оверрайды голосов для слотов инженера и споттера.

    Формат совпадает с контрактом `voice.Voice.set_voice_overrides()` и
    `yandex_ai.voices.resolve()`: {слот: {voice, emotion, speed}}. Комментатора
    в результате НЕТ намеренно: его голос задан персоной и не смещается — он
    первый в очереди и всегда получает своё.
    """
    commentator_voice = voices.resolve(persona)["voice"]
    taken = {commentator_voice}

    engineer = character(character_id)
    engineer_voice = _first_free(engineer.voices, taken)
    taken.add(engineer_voice)

    spotter_voice = _first_free(SPOTTER_VOICES, taken)

    return {
        SLOT_ENGINEER: {
            "voice": engineer_voice, "emotion": _EMOTION, "speed": engineer.speed,
        },
        SLOT_SPOTTER: {
            "voice": spotter_voice, "emotion": _EMOTION, "speed": SPOTTER_SPEED,
        },
    }
```

- [ ] **Step 4: Запустить тест — должен пройти**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q`
Expected: PASS, 18 passed (12 параметризованных + 6 отдельных)

- [ ] **Step 5: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: зелено (базовый прогон был зелёный — см. шапку). Модуль пока никем не используется, поэтому сломать что-либо он не может; любой провал здесь — повод остановиться и разобраться.

---

### Task 2: Слоты ролей в каталогах голосов

**Files:**
- Modify: `yandex_ai/voices.py:38-44`
- Modify: `new_tts/piper_tts.py:35-40`
- Modify: `voice/tts.py:250-251`
- Test: `tests/test_voice_cast.py` (дополнить)

- [ ] **Step 1: Написать падающие тесты**

Допиши в конец `tests/test_voice_cast.py`:

```python
def test_role_slots_exist_in_both_catalogues():
    """Слот роли обязан быть в ОБОИХ каталогах. Пропуск в Piper не заметен по
    основному пути, но при отказе Yandex озвучка уходит на фолбэк, и там
    отсутствующий ключ молча свалится в дефолтный голос — то есть роли
    схлопнутся в одну ровно в тот момент, когда сеть легла."""
    from new_tts.piper_tts import PERSONA_VOICE

    for slot in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER):
        assert slot in voices.DEFAULT_PERSONA_VOICE
        assert slot in PERSONA_VOICE


def test_piper_role_slots_differ_from_each_other():
    """В models/piper/ лежат ровно ЧЕТЫРЕ модели (ruslan, denis, irina,
    dmitri), и все четыре уже розданы персонам комментатора. Свободной модели
    под роль нет, а путь Piper не умеет оверрайды (PERSONA_VOICE.get(persona)
    статичен) — то есть динамически уступать голос, как это делает
    voice_cast.resolve() для Yandex, фолбэк не может.

    Поэтому здесь гарантия СЛАБЕЕ и это осознанно: инженер и споттер обязаны
    отличаться друг от друга, но могут совпасть с комментатором при одной из
    персон. Полная гарантия живёт в основном пути (Yandex); Piper — аварийный
    фолбэк, и в проекте он намеренно не развивается."""
    from new_tts.piper_tts import PERSONA_VOICE

    engineer = PERSONA_VOICE[voice_cast.SLOT_ENGINEER][0]
    spotter = PERSONA_VOICE[voice_cast.SLOT_SPOTTER][0]
    assert engineer != spotter


def test_piper_role_models_exist_on_disk():
    """Несуществующее имя модели даёт found:false в UI и тишину вместо голоса —
    ловим тестом, а не в гонке."""
    import os

    from new_tts.piper_tts import PERSONA_VOICE, _PIPER_DIR

    for slot in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER):
        name = PERSONA_VOICE[slot][0]
        assert os.path.isfile(
            os.path.join(str(_PIPER_DIR), f"ru_RU-{name}-medium.onnx")), name


def test_set_persona_rejects_role_slots():
    """Слоты ролей попали в PERSONA_VOICE, и set_persona() пропускал бы их
    своей проверкой `persona in PERSONA_VOICE`. Тогда сохранённое
    persona="engineer" отдало бы КОММЕНТАТОРУ голос инженера. Комментатор
    выбирается только из четырёх персон."""
    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._current_persona = "tv"
    v.set_persona(voice_cast.SLOT_ENGINEER)
    assert v._current_persona == "tv"
    v.set_persona("hype")
    assert v._current_persona == "hype"
```

- [ ] **Step 2: Запустить и убедиться, что тесты падают**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q -k "slots or set_persona"`
Expected: FAIL — `KeyError` / `AssertionError` (слотов ещё нет)

- [ ] **Step 3: Добавить слоты в каталог Yandex**

В `yandex_ai/voices.py`, сразу после закрывающей скобки `DEFAULT_PERSONA_VOICE` (строка 44), ВНУТРИ словаря — добавь два элемента перед `}`:

```python
DEFAULT_PERSONA_VOICE: dict[str, dict] = {
    "tv":    {"voice": "alexander", "emotion": "neutral", "speed": 1.05},
    "hype":  {"voice": "anton",     "emotion": "neutral", "speed": 1.15},
    "calm":  {"voice": "marina",    "emotion": "neutral", "speed": 0.95},
    "toxic": {"voice": "kirill",    "emotion": "neutral", "speed": 1.05},
    # Слоты РОЛЕЙ, а не персоны комментатора. Живут в одном словаре, потому что
    # вся цепочка синтеза (resolve -> _voice_key -> кэш -> speech.py) уже
    # принимает "персону" как строковый ключ: роль подставляется туда же и
    # получает ключ кэша, зависящий от РЕАЛЬНОГО голоса, бесплатно.
    # Значения ниже — только дефолт до первого применения оверрайдов из
    # core/radio/voice_cast.py (он же гарантирует несовпадение с комментатором).
    "engineer": {"voice": "alexander", "emotion": "neutral", "speed": 1.0},
    "spotter":  {"voice": "kirill",    "emotion": "neutral", "speed": 1.1},
}
```

- [ ] **Step 4: Добавить слоты в каталог Piper**

В `new_tts/piper_tts.py` замени блок на строках 35-40:

```python
PERSONA_VOICE: dict[str, tuple[str, float]] = {
    "tv":    ("ruslan", 1.0),
    "hype":  ("denis",  0.92),
    "calm":  ("irina",  1.08),
    "toxic": ("dmitri", 1.0),
    # Слоты ролей (см. yandex_ai/voices.py). Гарантия здесь СЛАБЕЕ, чем у
    # Yandex, и это осознанно: в models/piper/ лежат ровно четыре модели, и
    # все четыре уже розданы персонам выше — свободной под роль просто нет.
    # Динамически уступить голос, как это делает voice_cast.resolve(), путь
    # Piper тоже не может: PERSONA_VOICE.get(persona) статичен, механизма
    # оверрайдов у него нет.
    # Поэтому: инженер и споттер гарантированно отличаются ДРУГ ОТ ДРУГА и по
    # голосу, и по темпу, но могут совпасть с комментатором — при persona=toxic
    # с инженером, при persona=hype со споттером. Это аварийный фолбэк на
    # случай отказа сети, а не режим работы: качество голоса в проекте держится
    # на Yandex, и Piper намеренно не развивается.
    "engineer": ("dmitri", 1.0),
    "spotter":  ("denis",  1.12),
}
```

Имена моделей проверены по факту — в `models/piper/` лежат ровно `ru_RU-{ruslan,denis,irina,dmitri}-medium.onnx`. Не подставляй имя, которого нет на диске: `voice/voice_manager.py::_model_path()` покажет `found: false` в UI, а озвучка молча замолчит.

- [ ] **Step 5: Защитить `set_persona` от слотов ролей**

В `voice/tts.py` добавь константу уровня модуля (рядом с импортами):

```python
#: Персоны КОММЕНТАТОРА — единственное, что принимает set_persona(). Слоты
#: ролей (engineer/spotter) лежат в том же PERSONA_VOICE, поэтому прежней
#: проверки `persona in PERSONA_VOICE` стало недостаточно.
#: Литералы, а не импорт core.radio.voice_cast: voice/ не должен зависеть от
#: радио-конвейера, иначе тесты озвучки потянут его целиком.
_COMMENTATOR_PERSONAS: frozenset[str] = frozenset({"tv", "hype", "calm", "toxic"})
```

и замени строки 250-251:

```python
    def set_persona(self, persona: str) -> None:
        """Персона КОММЕНТАТОРА. Слот роли сюда не принимается: он тоже лежит в
        PERSONA_VOICE, и без этой проверки сохранённое persona="engineer"
        отдало бы КОММЕНТАТОРУ голос инженера."""
        self._current_persona = persona if persona in _COMMENTATOR_PERSONAS else "tv"
```

- [ ] **Step 6: Запустить тесты**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q`
Expected: PASS

- [ ] **Step 7: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: без новых провалов относительно Task 1.

---

### Task 3: Каналы указывают на слоты ролей

**Files:**
- Modify: `core/radio/policy.py:56-60`
- Modify: `core/radio/speakers.py:96,107`
- Modify: `tests/test_radio_policy.py:63-64`
- Modify: `tests/test_radio_message.py:42`
- Modify: `tests/test_radio_ptt_dialogue.py:325`

- [ ] **Step 1: Обновить ожидания в существующих тестах**

`tests/test_radio_policy.py`, строки 63-64 — заменить:

```python
    assert policy.voice_persona_for(policy.CHANNEL_ENGINEER) == "engineer"
    assert policy.voice_persona_for(policy.CHANNEL_SPOTTER) == "spotter"
```

`tests/test_radio_message.py`, строка 42 — заменить:

```python
    assert message.voice_persona == "engineer"
```

`tests/test_radio_ptt_dialogue.py`, строка 325 — заменить:

```python
    assert message.voice_persona == "engineer"
```

- [ ] **Step 2: Запустить и убедиться, что они падают**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_radio_policy.py tests/test_radio_message.py tests/test_radio_ptt_dialogue.py -q`
Expected: FAIL — `assert 'calm' == 'engineer'`

- [ ] **Step 3: Перевести таблицу политики на слоты**

В `core/radio/policy.py` замени блок на строках 52-60:

```python
# Слот голоса по каналу. Раньше здесь стояла персона комментатора "calm" — и
# это был источник главной поломки: при выбранной пользователем персоне "calm"
# все три канала звучали ОДНИМ голосом (marina), то есть разделение каналов
# существовало на бумаге и не существовало на слух. Теперь у ролей свои слоты
# (core/radio/voice_cast.py), а None у комментатора по-прежнему значит
# «говорить персоной, которую выбрал пользователь».
_VOICE_PERSONA: dict[str, str | None] = {
    CHANNEL_SPOTTER: "spotter",
    CHANNEL_ENGINEER: "engineer",
    CHANNEL_COMMENTATOR: None,
}
```

- [ ] **Step 4: Синхронизировать профили спикеров**

В `core/radio/speakers.py` замени `voice_persona="calm"` на `voice_persona="engineer"` в `RACE_ENGINEER` (строка 96) и на `voice_persona="spotter"` в `SPOTTER` (строка 107).

Там же обнови комментарий на строках 84-88:

```python
# `voice_persona` дублирует `policy._VOICE_PERSONA` дословно — на это стоит
# тест (tests/test_radio_projection.py). Значения — слоты голоса из
# core/radio/voice_cast.py, а не персоны комментатора: см.
# docs/superpowers/specs/2026-08-01-voice-cast-design.md.
```

- [ ] **Step 5: Запустить тесты**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_radio_policy.py tests/test_radio_message.py tests/test_radio_ptt_dialogue.py tests/test_radio_projection.py -q`
Expected: PASS

- [ ] **Step 6: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: без новых провалов.

---

### Task 4: Движок читает голос из сообщения

**Files:**
- Modify: `core/engine.py:178-187` (удалить `_SPEAKER_VOICE`, переписать комментарий)
- Modify: `core/engine.py:3246` (основной путь озвучки)
- Modify: `core/engine.py:2548` (ответ на PTT)
- Modify: `core/engine.py:2359` (предстартовая накачка — второй хардкод, найден на Task 3)
- Test: `tests/test_engine_voice_routing.py` (создать)

Номера строк проверены по факту на момент написания. Если не совпали — ищи по содержимому, а не правь вслепую по номеру:
```bash
cd "G:/Spotter App" && grep -n '_SPEAKER_VOICE\|persona="calm"' core/engine.py
```
Должно найтись ровно четыре места: определение таблицы, два её использования и прямой вызов с `persona="calm"`.

Сегодня движок вычисляет голос сам — `_SPEAKER_VOICE.get(event.get("speaker"))` — и получает "calm" и для инженера, и для споттера (оба публикуются с `speaker=SPEAKER_ENGINEER`, см. `_spotter_tick`). При этом `RadioMessage.voice_persona` вычислен правильно по КАНАЛУ ещё в `message.py` и просто игнорируется. Задача — начать его читать.

- [ ] **Step 1: Написать падающий тест**

Создай `tests/test_engine_voice_routing.py`:

```python
"""Голос выбирается по КАНАЛУ сообщения, а не по маркеру speaker.

Споттер и инженер публикуются с одним и тем же speaker=SPEAKER_ENGINEER
(core/engine.py::_spotter_tick), поэтому маркер их не различает, а канал —
различает."""
from core.radio.message import build_message


def _voice_persona_for_code(code: str, speaker: str = "engineer") -> str | None:
    message = build_message(
        {"event_code": code, "priority": "normal", "importance": 50,
         "speaker": speaker},
        phrase="тест", now=1000.0, now_mono=50.0)
    return message.voice_persona


def test_spotter_and_engineer_get_different_voice_slots():
    assert _voice_persona_for_code("SPOTTER_CAR_LEFT") == "spotter"
    assert _voice_persona_for_code("STRAT_BOX_CALL_1") == "engineer"


def test_commentator_keeps_the_user_persona():
    # speaker="" здесь обязателен: маркер "engineer" — страховочное правило в
    # policy.channel_for для кодов, забытых в _ENGINEER_CODES, и он увёл бы
    # OVTK в инженерский канал, хотя это реплика комментатора.
    assert _voice_persona_for_code("OVTK", speaker="") is None
```

- [ ] **Step 2: Запустить тест**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_engine_voice_routing.py -q`
Expected: PASS сразу — `message.py` уже вычисляет это правильно. Тест фиксирует контракт, на который сейчас обопрётся движок. Если падает — значит Task 3 сделан не полностью, вернись к нему.

- [ ] **Step 3: Переключить основной путь озвучки**

В `core/engine.py` замени строку 3246 (внутри `_commentary_loop`):

```python
                    persona=_SPEAKER_VOICE.get(event.get("speaker")),
```

на:

```python
                    # Голос берётся из КАНАЛА сообщения, а не из маркера
                    # speaker: споттер публикуется с тем же speaker="engineer",
                    # что и инженер (_spotter_tick), поэтому маркер их не
                    # различает. Фолбэк на случай несобравшегося message —
                    # прежнее поведение, лучше инженерский голос, чем None.
                    persona=(message.voice_persona if message is not None
                             else (SLOT_ENGINEER
                                   if event.get("speaker") == SPEAKER_ENGINEER
                                   else None)),
```

- [ ] **Step 4: Переключить путь ответа на PTT**

В `core/engine.py` замени строку 2548 (`_say_ptt_answer`):

```python
            persona=_SPEAKER_VOICE.get(SPEAKER_ENGINEER),
```

на:

```python
            persona=message.voice_persona,
```

(в этой ветке `message is None` уже отсечён проверкой парой строк выше).

- [ ] **Step 4b: Переключить путь предстартовой накачки**

Найдено на Task 3, в исходный план не входило. Хардкодов «calm» в движке ДВА, и этот минует `_SPEAKER_VOICE` целиком — строка 2359, внутри генерации `PRE_RACE_PEP_TALK`:

```python
                self.voice.say(text, priority="normal", persona="calm")
```

Заменить на:

```python
                self.voice.say(text, priority="normal", persona=SLOT_ENGINEER)
```

Почему это обязательно: `PRE_RACE_PEP_TALK` входит в `policy._ENGINEER_CODES` и по всем остальным признакам — реплика инженера. Оставь здесь `"calm"` — и напутствие перед стартом единственное из всего инженерского канала продолжит звучать голосом КОММЕНТАТОРА, причём именно в тот момент, когда игрок впервые слышит своего инженера в сессии.

Этот путь строит сообщение не через `_build_radio_message`, поэтому `message.voice_persona` тут недоступен, и слот подставляется константой напрямую — это единственное место, где так можно.

Вместе с этим ОБЯЗАТЕЛЬНО правится существующий тест `tests/test_engine_pre_race_pep_talk.py`: он закрепляет отменённый контракт (`assert persona == "calm"`, имя теста `..._speaks_with_calm_persona`). Без правки полный прогон краснеет одним тестом. Заменить ассерт на `voice_cast.SLOT_ENGINEER`, переименовать тест в `..._speaks_with_the_engineer_voice`, добавить импорт `from core.radio import voice_cast`.

- [ ] **Step 5: Удалить мёртвую таблицу и добавить импорт**

В `core/engine.py` удали строку 186 (`_SPEAKER_VOICE`) и перепиши комментарий на строках 178-185:

```python
# Маркер event["speaker"] = SPEAKER_ENGINEER помечает реплики инженерских
# трекеров. ГОЛОС по нему больше не выбирается — это делает канал сообщения
# (core/radio/policy.py::channel_for -> RadioMessage.voice_persona), потому что
# споттер публикуется с тем же маркером и отдельного голоса иначе не получал.
# Маркер остаётся: policy.channel_for() использует его как страховку для кодов,
# забытых в _ENGINEER_CODES.
SPEAKER_ENGINEER = "engineer"
```

Добавь импорт к остальным импортам `core.radio` в шапке `core/engine.py`:

```python
from core.radio.voice_cast import SLOT_ENGINEER
```

Проверь, что не осталось ссылок:

```bash
cd "G:/Spotter App" && grep -rn "_SPEAKER_VOICE" --include=*.py . | grep -v __pycache__
```
Expected: пусто.

- [ ] **Step 6: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: без новых провалов.

---

### Task 5: Настройка персонажа и пересчёт каста

**Files:**
- Modify: `core/settings.py` (DEFAULTS)
- Modify: `core/engine.py:496-515` (`apply_settings`)
- Test: `tests/test_voice_cast.py` (дополнить)

- [ ] **Step 1: Написать падающий тест**

Допиши в `tests/test_voice_cast.py`:

```python
def test_settings_default_character_matches_the_module():
    """settings.py не импортирует voice_cast (лишняя зависимость на старте),
    поэтому дефолт продублирован строкой. Тест держит копии синхронными."""
    from core.settings import DEFAULTS

    assert DEFAULTS["engineer_character"] == voice_cast.DEFAULT_CHARACTER
    assert DEFAULTS["engineer_character"] in voice_cast.CHARACTERS


def test_cache_key_follows_the_resolved_voice_not_the_slot_name():
    """Риск №4 спеки. Ключ кэша строится из слота ("engineer"), и если бы он
    зависел только от ИМЕНИ слота, то после смены персонажа проигрывались бы
    WAV, озвученные прежним голосом, — молча и до очистки кэша.

    Спасает то, что `_voice_key` резолвит слот через `voices.resolve(slot,
    overrides)` и кладёт в ключ РЕАЛЬНЫЕ параметры синтеза. Этот тест
    фиксирует свойство, чтобы будущая «оптимизация» ключа его не потеряла."""
    import types

    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._yandex = types.SimpleNamespace(tts_version="v3")

    v._voice_overrides = voice_cast.resolve("calm", "volkov")
    key_volkov = v._voice_key(voice_cast.SLOT_ENGINEER)

    v._voice_overrides = voice_cast.resolve("calm", "grom")
    key_grom = v._voice_key(voice_cast.SLOT_ENGINEER)

    assert key_volkov != key_grom
```

- [ ] **Step 2: Запустить, убедиться в падении**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q -k "settings_default or cache_key"`
Expected: FAIL — `KeyError: 'engineer_character'` у первого теста. Второй (`cache_key`) должен пройти сразу: `_voice_key` уже сегодня строит ключ из реальных параметров. Если он ПАДАЕТ — значит `resolve()` из Task 1 отдал одинаковый голос для volkov и grom при persona=calm, и надо вернуться к Task 1.

- [ ] **Step 3: Добавить ключ в настройки**

В `core/settings.py`, в словарь `DEFAULTS`, рядом с `"persona"` (строка 27) добавь:

```python
    # Персонаж инженера: "volkov" | "sokolova" | "grom". Ось, НЕЗАВИСИМАЯ от
    # persona (та — характер КОММЕНТАТОРА). Строка продублирована из
    # core.radio.voice_cast.DEFAULT_CHARACTER намеренно: settings загружается
    # на старте раньше радио-конвейера, тянуть сюда его импорт незачем.
    # Синхронность копий держит тест test_voice_cast.py.
    "engineer_character":      "volkov",
```

- [ ] **Step 4: Пересчитывать каст при смене настроек**

В `core/engine.py::apply_settings` **удали** блок на строках 511-515:

```python
        if "persona_voice" in settings:
            try:
                self.voice.set_voice_overrides(settings["persona_voice"])
            except Exception:  # noqa: BLE001
                pass
```

Он мёртвый (`persona_voice` нет в `settings.DEFAULTS`, `load()` выбрасывает неизвестные ключи) и после этой задачи стал бы вредным: он затирал бы оверрайды каста.

Вместе с удалением ОБЯЗАТЕЛЬНО переписывается `tests/test_engine_settings.py::test_apply_settings_persona_voice` — он закрепляет именно этот блок и иначе краснеет. Заменить на два теста нового контракта: смена `engineer_character` и смена `persona` каждая пересчитывают каст и отдают в озвучку оба слота.

На его место добавь:

```python
        if "persona" in settings or "engineer_character" in settings:
            self._apply_voice_cast()
```

И новый метод рядом с `apply_settings`:

```python
    def _apply_voice_cast(self) -> None:
        """Пересчитать голоса инженера и споттера под текущие настройки.

        Зовётся при смене ЛЮБОЙ из двух настроек: голос инженера зависит и от
        выбранного персонажа, и от того, какой голос уже занял комментатор
        своей персоной (core/radio/voice_cast.py::resolve)."""
        persona = self._get_setting("persona", config.PERSONA)
        character = self._get_setting("engineer_character",
                                      voice_cast.DEFAULT_CHARACTER)
        try:
            self.voice.set_voice_overrides(voice_cast.resolve(persona, character))
        except Exception:  # noqa: BLE001
            _log.warning("voice cast resolve failed", exc_info=True)
```

Добавь импорт модуля в шапку `core/engine.py`:

```python
from core.radio import voice_cast
```

- [ ] **Step 5: Починить старт — иначе инвариант ломается на живой машине**

Проверено на факте: `apply_settings` при запуске НЕ вызывается ни разу (`core/runtime.py` строит `F1Engine(settings)` и зовёт `engine.start()`; единственные вызывающие `apply_settings` — POST `/api/settings`, голосовые команды и хоткеи). А `F1Engine.__init__` ставит голос строкой

```python
        self.voice.set_persona(config.PERSONA)
```

то есть **из конфига, а не из сохранённых настроек**. Сохранённая персона доезжает до озвучки только когда пользователь что-то поменяет в UI.

Само по себе это давняя болячка, но для каста она смертельна. На живых настройках (`persona: "calm"`, дефолтный персонаж Волков) получается:

| | голос |
|---|---|
| комментатор РЕАЛЬНО звучит | `alexander` (из `config.PERSONA = "tv"`) |
| каст считает занятым | `marina` (из `settings["persona"] = "calm"`) |
| каст выдаёт инженеру | `alexander` |

Инженер и комментатор получают ОДИН голос — ровно то, что вся работа устраняет. Проверено запуском, коллизия воспроизводится.

Поэтому в `F1Engine.__init__` замени строку `self.voice.set_persona(config.PERSONA)` на:

```python
        # Персона из СОХРАНЁННЫХ настроек, а не из config: apply_settings при
        # старте не вызывается ни разу (см. core/runtime.py), поэтому иначе
        # выбор пользователя доезжал бы до озвучки только после первой правки
        # в UI. Для каста это не косметика: voice_cast.resolve() считает
        # занятым голос ПЕРСОНЫ, и рассинхрон между реально звучащим
        # комментатором и тем, кого считает каст, отдаёт инженеру голос
        # комментатора.
        self.voice.set_persona(self.settings.get("persona", config.PERSONA))
        self._apply_voice_cast()
```

`_apply_voice_cast()` обязан быть определён до этой точки либо быть методом класса (он метод — порядок определения в классе роли не играет). Голос (`self.voice`) к этому моменту уже создан.

- [ ] **Step 5b: Не терять каст при подключении Yandex**

`core/engine.py:938` пересоздаёт клиента синтеза при успешном подключении Yandex:

```python
            self.voice.set_yandex(YandexSpeech(self._yandex_client,
                                               self.settings.get("persona_voice")))
```

`persona_voice` в настройках нет (ключа нет в `DEFAULTS`), то есть сюда всегда уезжает `None` — и новый клиент стартует БЕЗ оверрайдов, затирая уже применённый каст. Yandex подключается асинхронно, уже после `__init__`, так что это не теория.

Замени на:

```python
            self.voice.set_yandex(YandexSpeech(self._yandex_client))
            # Каст переприменяется ПОСЛЕ пересоздания клиента: set_yandex()
            # ставит новый YandexSpeech, и оверрайды, применённые до него,
            # достались бы прежнему объекту.
            self._apply_voice_cast()
```

Проверь сигнатуру `YandexSpeech.__init__` — если второй аргумент обязателен, передай `None` явно и оставь переприменение каста следующей строкой.

- [ ] **Step 6: Запустить тесты**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py tests/test_engine_voice_routing.py tests/test_yandex_version.py -q`
Expected: PASS.

Отдельно проверь, что старт больше не даёт коллизии:

```bash
cd "G:/Spotter App" && python -X utf8 -c "
import core.engine as eng_mod
from core.engine import F1Engine
import core.settings as s
from yandex_ai import voices
from core.radio import voice_cast
eng_mod.yc.load = lambda: None
e = F1Engine(s.load())
persona = e.voice._current_persona
ov = e.voice._voice_overrides
row = (voices.resolve(persona)['voice'],
       ov[voice_cast.SLOT_ENGINEER]['voice'],
       ov[voice_cast.SLOT_SPOTTER]['voice'])
print('персона:', persona, '| голоса:', row)
assert len(set(row)) == 3, 'КОЛЛИЗИЯ: ' + str(row)
print('OK — три разных голоса на старте')
"
```
Expected: `персона: calm | голоса: ('marina', 'alexander', 'kirill')` и `OK`.

- [ ] **Step 7: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: без новых провалов.

---

### Task 6: Рация только на инженере и споттере

**Files:**
- Modify: `voice/tts.py` (добавить `_RADIO_SLOTS` и `_radio_for`)
- Modify: `voice/tts.py:616`
- Modify: `voice/tts.py:738`
- Test: `tests/test_voice_cast.py` (дополнить)

Сегодня `set_radio_fx` — один глобальный флаг, и bandpass со щелчками накладывается в том числе на телекомментатора, который в эфире на командной частоте не сидит.

- [ ] **Step 1: Написать падающий тест**

Допиши в `tests/test_voice_cast.py`:

```python
def test_radio_effect_applies_only_to_radio_slots():
    """Комментатор звучит чисто, инженер и споттер — через рацию. Глобальный
    тумблер radio_fx при этом главнее: выключен — молчат все эффекты."""
    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._current_persona = "tv"
    v._radio_enabled = True

    assert v._radio_for(voice_cast.SLOT_ENGINEER) is True
    assert v._radio_for(voice_cast.SLOT_SPOTTER) is True
    assert v._radio_for("tv") is False
    assert v._radio_for(None) is False       # None -> текущая персона (tv)

    v._radio_enabled = False
    assert v._radio_for(voice_cast.SLOT_ENGINEER) is False
```

- [ ] **Step 2: Запустить, убедиться в падении**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q -k radio_effect`
Expected: FAIL — `AttributeError: 'Voice' object has no attribute '_radio_for'`

- [ ] **Step 3: Добавить помощник**

В `voice/tts.py` рядом с `set_radio_fx` (строка 253) добавь константу уровня модуля и метод:

```python
#: Слоты, звучащие ЧЕРЕЗ РАЦИЮ. Телекомментатор ведёт эфир, а не переговоры на
#: командной частоте, поэтому bandpass и щелчки к нему не применяются — это
#: разделяет каналы на слух раньше тембра и работает даже при совпавших
#: голосах. Строки, а не импорт voice_cast: tts не должен зависеть от
#: core.radio (иначе тесты озвучки тянут радио-конвейер).
_RADIO_SLOTS: frozenset[str] = frozenset({"engineer", "spotter"})
```

```python
    def _radio_for(self, persona: str | None) -> bool:
        """Накладывать ли эффект рации на эту конкретную реплику.

        Глобальный пользовательский тумблер главнее: выключенный radio_fx
        снимает эффект со всех каналов."""
        if not self._radio_enabled:
            return False
        return (persona or self._current_persona) in _RADIO_SLOTS
```

- [ ] **Step 4: Применить в стриминговом пути**

В `voice/tts.py` замени строку 616:

```python
        radio = self._radio_for(persona)
```

- [ ] **Step 5: Применить в пути кэшированного WAV**

В `voice/tts.py` замени строку 738:

```python
            if self._radio_for(persona):
```

Кэш от этого не страдает: `_play_wav` читает СУХОЙ wav и накладывает эффект на лету (см. её докстринг), поэтому один и тот же файл корректно звучит и с рацией, и без.

**Не трогай строку 351** — там squelch для PTT-бипа, он намеренно не зависит от `_radio_enabled`.

- [ ] **Step 6: Запустить тесты**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py tests/test_tts_playback_stream.py -q`
Expected: PASS

- [ ] **Step 7: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: без новых провалов.

---

### Task 7: Выбор персонажа в интерфейсе

**Files:**
- Modify: `NewSpotterUI/lib/spotter-data.ts`
- Modify: `NewSpotterUI/components/spotter/views/voice.tsx`

**КРИТИЧНО:** приложение отдаёт статику из `webui/`, а НЕ из `NewSpotterUI/`. Без пересборки (Step 4) правка UI до пользователя не доедет.

**Бэкенд не трогаем.** Список персонажей живёт в `spotter-data.ts` — ровно так же, как список `personas` живёт там сегодня, хотя персоны есть и в Python (`commentator/personas.py`). Заводить ради трёх строк эндпоинт `/api/yandex/voices` (он возвращает `{"available", "defaults"}` и о персонажах ничего не знает) значило бы завести второй способ делать то же самое. Сохранение выбора и так идёт через общий `saveSettings`, который уже умеет любой ключ настроек.

- [ ] **Step 1: Добавить список персонажей в данные UI**

В `NewSpotterUI/lib/spotter-data.ts`, рядом с `personas` (строка 125), добавь:

```ts
// Персонажи инженера. id обязаны совпадать с core/radio/voice_cast.py::CHARACTERS
// — тот же контракт «две копии списка», что и у personas выше.
export type EngineerCharacter = {
  id: string
  name: string
  tagline: string
  description: string
}

export const engineerCharacters: EngineerCharacter[] = [
  {
    id: "volkov",
    name: "Игорь Волков",
    tagline: "Сухой профессионал",
    description: "Ровный, собранный тон. Ни одного лишнего слова: кто — цифра — вывод.",
  },
  {
    id: "sokolova",
    name: "Марина Соколова",
    tagline: "Спокойный наставник",
    description: "Мягче и теплее. Чаще обращается по имени, чаще подбадривает.",
  },
  {
    id: "grom",
    name: "Виктор Гром",
    tagline: "Жёсткий требовательный",
    description: "Резкий командный тон, высокий темп. Похвала скупая и оттого весомая.",
  },
]
```

- [ ] **Step 2: Переименовать существующую панель**

В `NewSpotterUI/components/spotter/views/voice.tsx` панель персон комментатора сейчас озаглавлена «Профиль инженера» (строка 143) — это и есть та самая путаница, ради которой всё затевалось. Замени:

```tsx
        <Panel label="Характер комментатора">
```

Заодно поправь подзаголовок страницы (строка 139):

```tsx
      <PageHeader title="Voice & Engineer" subtitle="Комментатор и инженер — два разных голоса" />
```

- [ ] **Step 3: Добавить панель выбора инженера**

Импортируй список в шапке файла (строка 6 уже импортирует `personas`):

```tsx
import { personas, engineerCharacters } from "@/lib/spotter-data"
```

Добавь состояние рядом с существующим `active` (строка ~35):

```tsx
  const [engineer, setEngineer] = useState<string>("volkov")

  useEffect(() => {
    if (state?.settings?.engineer_character) setEngineer(state.settings.engineer_character)
  }, [state?.settings?.engineer_character])

  const pickEngineer = (id: string) => {
    setEngineer(id)
    saveSettings({ engineer_character: id })
  }
```

Сразу ПОСЛЕ закрывающего тега панели «Характер комментатора» вставь:

```tsx
        <Panel label="Инженер">
          <p className="mb-3 text-xs text-muted-foreground">
            Инженер говорит отдельным голосом через рацию. Если выбранный голос
            уже занят комментатором, инженер автоматически берёт запасной.
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {engineerCharacters.map((c) => {
              const isActive = engineer === c.id
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => pickEngineer(c.id)}
                  className={cn(
                    "flex flex-col rounded-lg border p-4 text-left transition-all",
                    isActive
                      ? "border-primary/50 bg-primary/8"
                      : "border-border bg-secondary/40 hover:border-border hover:bg-secondary",
                  )}
                >
                  <span className="font-heading text-base font-bold text-foreground">{c.name}</span>
                  <span className="label-mono mt-0.5 text-[10px] text-muted-foreground">{c.tagline}</span>
                  <span className="mt-2 text-xs text-muted-foreground">{c.description}</span>
                </button>
              )
            })}
          </div>
        </Panel>
```

- [ ] **Step 4: Пересобрать UI в `webui/`**

```bash
cd "G:/Spotter App/NewSpotterUI" && pnpm build
```
Expected: сборка без ошибок, появляется `NewSpotterUI/out/`.

Затем синхронизировать в `webui/` — той же командой, что делает `build.ps1:105`:

```bash
cd "G:/Spotter App" && robocopy NewSpotterUI/out webui /MIR /NFL /NDL /NJH /NJS /NP; if ($LASTEXITCODE -lt 8) { "OK" }
```

(Это PowerShell-строка — запускай через PowerShell, не через bash: `robocopy` и `$LASTEXITCODE` в bash не работают. Код возврата robocopy < 8 означает успех.)

- [ ] **Step 5: Чекпойнт**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: без новых провалов.

---

### Task 8: Живой TTS-проб трёх голосов

**Files:** нет правок кода — это проверка перед закреплением дефолтов.

Риск №2 из спеки: `anton` (голос персоны `hype`) может звучать слишком заводно для командного тона Виктора Грома. Проверяем ушами до того, как оставим в дефолтах.

- [ ] **Step 1: Синтезировать одну и ту же фразу тремя голосами**

```bash
cd "G:/Spotter App" && python -c "
from core.radio import voice_cast
for cid, c in voice_cast.CHARACTERS.items():
    print(f'{cid:10} {c.display_name:18} {c.voices[0]:10} speed={c.speed}')
"
```

Затем прогони живой синтез через существующий путь озвучки. Точную точку входа найди так:

```bash
cd "G:/Spotter App" && ls tools/ scripts/ && grep -rln "synthesize\|say(" tools/ scripts/ 2>/dev/null | head
```

Если готового скрипта нет — озвучь фразу «Бокс, бокс. Шины на исходе.» каждым из голосов `alexander`, `marina`, `anton` с соответствующими `speed`, обязательно **с включённым эффектом рации** (иначе проверка не про тот звук).

- [ ] **Step 2: Оценить и записать вывод**

Критерий: голос должен звучать как команда, а не как реакция болельщика. Если `anton` не проходит — замени первый голос `GROM` на `kirill`, а вторым поставь `anton`:

```python
GROM = EngineerCharacter(
    character_id="grom",
    display_name="ВИКТОР ГРОМ",
    voices=("kirill", "anton"),
    speed=1.1,
)
```

и перепроверь инвариант:

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/test_voice_cast.py -q`
Expected: PASS (тест на 12 сочетаний ловит поломку раздачи, если она возникнет).

Запиши результат пробы в раздел 6 спеки `docs/superpowers/specs/2026-08-01-voice-cast-design.md`, заменив формулировку риска №2 на факт.

---

### Task 9: Финальная проверка и документация

- [ ] **Step 1: Полный прогон тестов**

Run: `cd "G:/Spotter App" && python -X utf8 -m pytest tests/ -q`
Expected: PASS. Если падает тест, не связанный с этой работой — прогони его отдельно, прежде чем считать реальным: параллельные сессии без git иногда дают ложную гонку на `core/engine.py`.

- [ ] **Step 2: Проверить главный инвариант вручную**

```bash
cd "G:/Spotter App" && python -c "
from core.radio import voice_cast
from yandex_ai import voices
for p in ('tv','hype','calm','toxic'):
    for c in voice_cast.CHARACTERS:
        cast = voice_cast.resolve(p, c)
        row = (voices.resolve(p)['voice'],
               cast[voice_cast.SLOT_ENGINEER]['voice'],
               cast[voice_cast.SLOT_SPOTTER]['voice'])
        assert len(set(row)) == 3, (p, c, row)
        print(f'{p:6} {c:9} комментатор={row[0]:10} инженер={row[1]:10} споттер={row[2]}')
"
```
Expected: 12 строк, в каждой три разных голоса.

- [ ] **Step 3: Проверить живую настройку пользователя**

```bash
cd "G:/Spotter App" && python -c "
from core import settings
s = settings.load()
print('persona           =', s['persona'])
print('engineer_character=', s['engineer_character'])
"
```
Expected: `persona = calm`, `engineer_character = volkov`. То есть у текущего пользователя комментатор — marina, инженер — alexander, споттер — kirill. Ровно та ситуация, которая до этой работы давала одну marina на все три канала.

- [ ] **Step 4: Записать результат в CONTEXT.md**

Добавь в `CONTEXT.md` короткую запись (одна-две строки, не пересказ плана): что каст голосов по ролям введён, что `_SPEAKER_VOICE` и «персона calm для инженера» больше не существуют, что radio_fx стал поканальным, и ссылку на спеку. Держи файл в порядке — он уже разросся.

- [ ] **Step 5: Обновить статус спеки**

В `docs/superpowers/specs/2026-08-01-voice-cast-design.md` поменяй строку статуса на:

```markdown
**Статус:** этап 1 (каркас) выполнен; этапы 2 (каст и фразы) и 3 (диалог) ждут своих планов
```

---

## Что НЕ входит в этот план

Эти пункты спеки — этапы 2 и 3, у них будут отдельные планы:

- фразы инженера (обращение по имени, похвала, ритуалы сессии, `ambient.calm`);
- слияние `commentator/engineer.py` в `core/radio/phrases.py`;
- переписывание промпта персоны `calm` в «спокойного аналитика»;
- парные реплики комментатор + инженер на крупных событиях;
- портреты новых персонажей в `assets/radio/` (карточка рисуется и без файла — `speakers.py::initials`).

После этапа 1 инженер продолжит говорить теми же словами, что и сегодня, — но своим голосом и через рацию.
