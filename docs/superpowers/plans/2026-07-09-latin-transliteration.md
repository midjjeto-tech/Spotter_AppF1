# Latin Transliteration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a rule-based Latin→Cyrillic practical transliteration fallback so driver names outside the curated static dictionaries don't reach Russian TTS as raw, mangled Latin script.

**Architecture:** A new standalone module `core/transliterate.py` provides `to_cyrillic()`/`is_latin()` — pure string functions, no I/O. Two existing call sites (`core/f1_metadata.py::enrich_driver`, `core/f1_benchmark.py::_ru_driver`) each gain one new fallback line using this module, applied only when their existing curated-dictionary lookup misses.

**Tech Stack:** Python 3.12, pytest. No new dependencies.

**Design doc:** `docs/superpowers/specs/2026-07-09-latin-transliteration-design.md`

**Note on git:** this project is not under version control. No `git commit` steps — each task ends with a verification checkpoint instead.

---

### Task 1: `core/transliterate.py` — the transliteration module

**Files:**
- Create: `core/transliterate.py`
- Test: `tests/test_transliterate.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transliterate.py`:

```python
from core.transliterate import is_latin, to_cyrillic


# --- known-good matches (calibrated against this project's own static dicts) ---

def test_bearman_matches_static_dict_via_ea_digraph():
    assert to_cyrillic("Bearman") == "Бирман"


def test_norris():
    assert to_cyrillic("Norris") == "Норрис"


def test_piastri():
    assert to_cyrillic("Piastri") == "Пиастри"


def test_tsunoda_matches_static_dict_via_ts_digraph():
    assert to_cyrillic("Tsunoda") == "Цунода"


def test_alonso():
    assert to_cyrillic("Alonso") == "Алонсо"


def test_antonelli():
    assert to_cyrillic("Antonelli") == "Антонелли"


def test_colapinto():
    assert to_cyrillic("Colapinto") == "Колапинто"


def test_gasly():
    assert to_cyrillic("Gasly") == "Гасли"


def test_ocon():
    assert to_cyrillic("Ocon") == "Окон"


def test_stroll():
    assert to_cyrillic("Stroll") == "Стролл"


def test_albon():
    assert to_cyrillic("Albon") == "Албон"


def test_lawson_matches_static_dict_via_aw_digraph():
    assert to_cyrillic("Lawson") == "Лоусон"


def test_hadjar_matches_static_dict_via_dj_digraph():
    assert to_cyrillic("Hadjar") == "Хаджар"


# --- accepted mismatch (documented limitation, not a bug) ---

def test_verstappen_mismatches_static_dict_this_is_expected():
    """Static dict says "Ферстаппен" (Dutch pronunciation: 'V' sounds like 'f').
    Letter-based rules can't know this — they produce the English-style
    reading. This is the documented, accepted limitation: the algorithm is a
    fallback for names NOT in the static dict, not a replacement for it. If
    this assertion ever starts failing because someone "fixed" the algorithm
    to special-case Dutch names, that's scope creep — put the exact name in
    F1_2025_BY_NUMBER/F1_2026_BY_NUMBER instead."""
    assert to_cyrillic("Verstappen") == "Верстаппен"


def test_sainz_mismatches_static_dict_this_is_expected():
    """Static dict says "Сайнс" (Spanish-origin surname, softer final
    consonant). Letter rules map the final "z" to "з" (the general English
    convention), giving "Сайнз" instead. Same class of accepted limitation as
    Verstappen above — do not "fix" this in the algorithm, add exact names to
    the static dict instead."""
    assert to_cyrillic("Sainz") == "Сайнз"


# --- multi-word names ---

def test_full_name_transliterated_word_by_word():
    assert to_cyrillic("Oliver Bearman") == "Оливер Бирман"


# --- is_latin() ---

def test_is_latin_true_for_latin_text():
    assert is_latin("Bearman") is True


def test_is_latin_false_for_cyrillic_text():
    assert is_latin("Бирман") is False


def test_is_latin_false_for_mixed_text():
    assert is_latin("Bearman Бирман") is False


def test_is_latin_false_for_empty_string():
    assert is_latin("") is False


def test_is_latin_false_for_none():
    assert is_latin(None) is False


def test_is_latin_true_for_hyphenated_name():
    assert is_latin("Jean-Eric") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_transliterate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.transliterate'`

- [ ] **Step 3: Implement**

Create `core/transliterate.py`:

```python
"""
core/transliterate.py
======================
Правило-базовая практическая транслитерация латиницы в кириллицу — подстраховка
для имён ВНЕ статических словарей (core/f1_metadata.py::F1_2025_BY_NUMBER/
F1_2026_BY_NUMBER, core/f1_benchmark.py::_LATIN_TO_RU). Русский Yandex TTS
озвучивает сырую латиницу мусором — транслитерированная кириллица звучит
лучше, даже когда неточна.

ВАЖНО: правила калиброваны на английскую орфографию. Фамилии не-английского
происхождения могут транслитерироваться неверно (пример: "Verstappen" —
голландское произношение с "V" как "ф" — этот модуль даст "Верстаппен", не
"Ферстаппен", как в статическом словаре). Это ПРИНЯТОЕ ограничение, не баг —
для точных случаев имя фиксируется вручную в соответствующем словаре, этот
модуль — только фолбэк для того, чего там ещё нет.
"""
from __future__ import annotations

import re

_LATIN_RE = re.compile(r"^[A-Za-z\s\-'.]+$")

# Диграфы — длиннее совпадение приоритетнее однобуквенного. Порядок в списке
# ниже важен только для читаемости, сопоставление всегда идёт по длине.
_DIGRAPHS: dict[str, str] = {
    "th": "т", "ch": "ч", "sh": "ш", "ph": "ф", "ck": "к", "qu": "кв",
    "wh": "в", "ea": "и", "ee": "и", "oo": "у", "ai": "ай", "ay": "ай",
    "ey": "ей", "oy": "ой", "ow": "оу", "ou": "ау", "aw": "оу", "ew": "ью",
    "dj": "дж", "ts": "ц", "kh": "х", "zh": "ж", "gh": "г",
}

_LETTERS: dict[str, str] = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з",
}

_MAX_DIGRAPH_LEN = max(len(k) for k in _DIGRAPHS)


def _transliterate_word(word: str) -> str:
    lower = word.lower()
    out: list[str] = []
    i = 0
    while i < len(lower):
        matched = False
        for length in range(_MAX_DIGRAPH_LEN, 1, -1):
            chunk = lower[i:i + length]
            if chunk in _DIGRAPHS:
                out.append(_DIGRAPHS[chunk])
                i += length
                matched = True
                break
        if matched:
            continue
        ch = lower[i]
        out.append(_LETTERS.get(ch, ch))   # не-буква (дефис, апостроф) — как есть
        i += 1
    result = "".join(out)
    return result[:1].upper() + result[1:] if result else result


def is_latin(text: str) -> bool:
    """True, если строка целиком латиница (плюс пробелы/дефис/апостроф) —
    значит транслитерация имеет смысл; кириллицу/смешанный текст не трогаем."""
    return bool(text) and bool(_LATIN_RE.match(text))


def to_cyrillic(latin: str) -> str:
    """Транслитерировать латинское имя (одно слово или полное имя из
    нескольких слов — каждое обрабатывается независимо, разделители
    сохраняются) в кириллицу. Не проверяет is_latin() сама — вызывающий код
    решает, когда транслитерация нужна."""
    if not latin:
        return latin
    return " ".join(_transliterate_word(w) if w else w for w in latin.split(" "))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_transliterate.py -v`
Expected: all PASS

If any of the "known-good matches" tests fail (i.e. the digraph table produces a different result than expected for one of these names), read the actual character-by-character trace and adjust the specific digraph/letter mapping causing the mismatch — do NOT weaken the test's expected value to match a wrong output. These test values were derived by hand-tracing the algorithm against this project's real static dictionaries before this plan was written, so a failure here means an implementation bug, not a wrong test expectation.

- [ ] **Step 5: Checkpoint**

Confirm all tests pass. No git commit needed (project has no git repo). Move to Task 2.

---

### Task 2: `core/f1_metadata.py::enrich_driver` — transliteration fallback

**Files:**
- Modify: `core/f1_metadata.py`
- Test: `tests/test_driver_names.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_driver_names.py`:

```python
def test_jolpica_latin_name_outside_static_dict_gets_transliterated():
    """Number 99 is not in F1_2025_BY_NUMBER/F1_2026_BY_NUMBER. Simulate
    Jolpica resolving it to a Latin name that isn't in either static dict —
    the transliteration fallback should kick in rather than passing raw
    Latin through to TTS."""
    m = _meta_no_ergast()
    m._loaded = True
    m._by_number[99] = {"name": "Bearman", "code": "BEA", "number": 99,
                        "team": "Haas", "nationality": "British"}
    out = m.enrich_drivers({0: {"name": "Bearman", "team": "Haas", "number": 99}})
    assert out[0]["name"] == "Бирман"


def test_custom_driver_keeps_udp_name_for_unknown_number_still_works():
    """Regression: the new transliteration fallback must NOT affect drivers
    who never resolved through Jolpica at all (enrich_driver's result stays
    empty, so the caller keeps the original UDP name unchanged) — this test
    already existed before this plan; re-asserting it here as an explicit
    regression guard for this specific change."""
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "Кастомный Гонщик", "team": "X", "number": 99}})
    assert out[0]["name"] == "Кастомный Гонщик"
```

(`_meta_no_ergast()` and `_OfflineClient` already exist at the top of `tests/test_driver_names.py` — reuse them, don't redefine.)

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `py -3.12 -m pytest tests/test_driver_names.py::test_jolpica_latin_name_outside_static_dict_gets_transliterated -v`
Expected: FAIL — `out[0]["name"] == "Bearman"` (raw Latin, not yet transliterated)

- [ ] **Step 3: Implement**

In `core/f1_metadata.py`, add an import near the top (alongside the existing `from core.ergast_client import JolpicaClient`):

```python
from core import transliterate
```

Then, in `enrich_driver()`, find the end of the method:

```python
        # 4. Нормализация названия команды через Jolpica (не зависит от имени).
        if self._loaded and team and self._teams.get(_normalize_key(team)):
            result["team"] = self._teams[_normalize_key(team)]["name"]

        return result
```

Change to:

```python
        # 4. Нормализация названия команды через Jolpica (не зависит от имени).
        if self._loaded and team and self._teams.get(_normalize_key(team)):
            result["team"] = self._teams[_normalize_key(team)]["name"]

        # 5. Транслитерация — последний фолбэк, если имя до сих пор латиница
        #    (Jolpica отдала непереведённое имя, номера нет в статическом
        #    словаре). Лучше приблизительная кириллица, чем сырая латиница в
        #    Yandex TTS. Точные случаи — в F1_2025_BY_NUMBER/F1_2026_BY_NUMBER,
        #    это не замена им (см. core/transliterate.py).
        if result.get("name") and transliterate.is_latin(result["name"]):
            result["name"] = transliterate.to_cyrillic(result["name"])

        return result
```

Read the actual current `core/f1_metadata.py` first to confirm the exact text of step 4 and the `return result` line — this is a small, surgical insertion right before the existing return statement, nothing else in the method changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_driver_names.py -v`
Expected: all PASS (including all pre-existing tests in the file, unchanged)

- [ ] **Step 5: Checkpoint**

Move to Task 3.

---

### Task 3: `core/f1_benchmark.py::_ru_driver` — transliteration fallback

**Files:**
- Modify: `core/f1_benchmark.py`
- Test: `tests/test_f1_benchmark.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_f1_benchmark.py`:

```python
def test_ru_driver_transliterates_names_outside_latin_to_ru_dict():
    from core.f1_benchmark import _ru_driver
    # "Bearman" is not a key in _LATIN_TO_RU (Oliver Bearman is resolved via
    # the static F1_2025_BY_NUMBER dict elsewhere in the app, not via this
    # benchmark-specific dict) — this proves the fallback kicks in instead of
    # returning raw Latin.
    assert _ru_driver("Bearman") == "Бирман"


def test_ru_driver_still_prefers_curated_dict_entry():
    from core.f1_benchmark import _ru_driver
    # "Verstappen" IS a key in _LATIN_TO_RU ("Ферстаппен") — the curated
    # dict must still win over the transliteration fallback, since the
    # algorithm alone would produce "Верстаппен" (see
    # tests/test_transliterate.py::test_verstappen_mismatches_static_dict_this_is_expected).
    assert _ru_driver("Verstappen") == "Ферстаппен"


def test_ru_driver_handles_none_and_empty():
    from core.f1_benchmark import _ru_driver
    assert _ru_driver(None) == ""
    assert _ru_driver("") == ""
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py::test_ru_driver_transliterates_names_outside_latin_to_ru_dict -v`
Expected: FAIL — `_ru_driver("Bearman") == "Bearman"` (raw Latin, not yet transliterated)

- [ ] **Step 3: Implement**

In `core/f1_benchmark.py`, add an import near the top (alongside the existing `from core.ergast_client import JolpicaClient`):

```python
from core import transliterate
```

Then find:

```python
def _ru_driver(latin: str | None) -> str:
    if not latin:
        return ""
    return _LATIN_TO_RU.get(latin, latin)   # неизвестное имя → как есть (латиница, без падежа)
```

Change to:

```python
def _ru_driver(latin: str | None) -> str:
    if not latin:
        return ""
    return _LATIN_TO_RU.get(latin, transliterate.to_cyrillic(latin))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -v`
Expected: all PASS (including all pre-existing tests in the file, unchanged)

- [ ] **Step 5: Checkpoint**

Move to Task 4.

---

### Task 4: Full regression + `CONTEXT.md` session note

**Files:**
- Modify: `CONTEXT.md`
- No further code changes

- [ ] **Step 1: Run the full test suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed. Note the exact "N passed, M skipped" line (baseline before this feature was 1039 passed, 1 skipped) — call this count `<TOTAL>` below.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.transliterate, core.f1_metadata, core.f1_benchmark"`
Expected: no output, exit code 0

- [ ] **Step 3: Add a new session section to `CONTEXT.md`**

Read the current `CONTEXT.md` first (it changes between sessions). Insert a new session section directly above the current newest session entry, and update "На чём остановились" to point at this closure. Use this template, filling in the real `<TOTAL>` from Step 1:

```markdown
## Сессия 2026-07-09 (продолжение) — Транслитерация латиницы вне статического словаря, 4/4 ✅

Закрывает последний пункт бэклога «Известных gotchas» — «Латиница от Jolpica
для пилотов ВНЕ статического словаря не транслитерируется». План:
`docs/superpowers/plans/2026-07-09-latin-transliteration.md`, спека:
`docs/superpowers/specs/2026-07-09-latin-transliteration-design.md`.

- **`core/transliterate.py`** (новый) — правило-базовая практическая
  транслитерация (диграфы th/ch/sh/ph/ea/ts/dj/... + однобуквенный фолбэк),
  без новых зависимостей. **Явно принятое ограничение:** калибровано на
  английскую орфографию — фамилии не-английского происхождения (голландские,
  французские) могут транслитерироваться неверно (пример: "Verstappen" →
  "Верстаппен" этим алгоритмом, не "Ферстаппен" как в статическом словаре —
  задокументировано тестом, не баг). Подстраховка «лучше так, чем сырая
  латиница в Yandex TTS», не замена ручной курации точных случаев.
- **`core/f1_metadata.py::enrich_driver`** — новый 5-й (последний) слой
  фолбэка: если имя после статического словаря и Jolpica всё ещё латиница —
  транслитерировать. Кастомные UDP-имена игрока (без Jolpica-резолва) не
  затрагиваются — `result` в этом случае пуст, регрессия проверена явным
  тестом.
- **`core/f1_benchmark.py::_ru_driver`** — тот же фолбэк вместо «латиница как
  есть» для имён вне `_LATIN_TO_RU` (24 записи). Курированный словарь
  по-прежнему выигрывает у алгоритма для уже известных имён.

**Верификация:** `tests/test_transliterate.py` (19 тестов, новый, включая явный
тест на принятое несовпадение Verstappen), расширения
`tests/test_driver_names.py`/`tests/test_f1_benchmark.py`. Полный прогон
`py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — **<TOTAL>** (было 1039
passed, 1 skipped). Импорт-смоук — без ошибок.
```

Replace `<TOTAL>` with the actual line from Step 1. Also update the "Известные gotchas" bullet that currently reads "Латиница от Jolpica для пилотов ВНЕ статического словаря не транслитерируется..." — mark it closed with a pointer to this session, following the same pattern already used for other closed gotcha items in this file (search for "ЗАКРЫТО" for examples of the convention).

- [ ] **Step 4: Checkpoint (final)**

Confirm `CONTEXT.md` renders correctly, full suite green, import smoke clean. Feature complete — this closes the last remaining item from the original backlog list.

---

## Plan Self-Review Notes

- **Spec coverage:** all 3 design sections (`core/transliterate.py`, `enrich_driver` integration, `_ru_driver` integration) map 1:1 to Tasks 1-3. The design's explicit "accepted limitation" (Verstappen mismatch) is captured as its own named test in Task 1, not glossed over.
- **Regression protection:** Task 2 explicitly re-asserts the pre-existing `test_custom_driver_keeps_udp_name_for_unknown_number` behavior (custom UDP names bypass this fallback entirely) as a named regression test, since that's the one existing behavior this change could plausibly have broken if the fallback were placed at the wrong point in `enrich_driver`.
- **Type/signature consistency:** `to_cyrillic(latin: str) -> str`, `is_latin(text: str) -> bool` — same names/signatures used consistently in Tasks 1-3 and their call sites (`transliterate.is_latin(...)`, `transliterate.to_cyrillic(...)`).
- **No placeholders:** all test values in Task 1 were derived by hand-tracing the actual algorithm against this project's real static dictionaries during the design phase (not guessed) — Step 4 of Task 1 explicitly instructs the implementer to trust these values over a differing implementation result, not the reverse.
