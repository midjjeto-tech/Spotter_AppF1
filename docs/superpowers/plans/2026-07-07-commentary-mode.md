# Commentary Mode (live/calm/story) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `commentary_mode` setting (`live`/`calm`/`story`) that changes how OFTEN the
commentator speaks (`calm`/`story`) and how NARRATIVE its phrasing is (`story` only) —
completely independent of `persona` (character/voice).

**Architecture:** New settings key read at two existing decision points —
`core/engine.py::_speak_threshold()` (frequency, via a fixed offset per mode) and
`commentator/planner.py::build_plan()` (forces normal-length phrasing + a `narrative`
flag for `story`, consumed by `commentator/brain.py`'s LLM directive). Free-mode
(`templates.py`) has no LLM to add narrative flourish, so `story` there degrades to
`calm`'s frequency-only behavior automatically (it never sees the `narrative` flag).

**Tech Stack:** Python (pytest), TypeScript/React (Next.js static export, no test runner
for the frontend in this repo — verify UI changes by hand in a browser).

**Repo note:** NOT a git repository. Every "Commit" step below is a **Checkpoint**
instead — run the task's tests and confirm they pass. Do not run any git commands.

**Spec:** `docs/superpowers/specs/2026-07-07-commentary-mode-design.md`

---

### Task 1: `config.py` + `core/settings.py` — new setting and threshold-offset table

**Files:**
- Modify: `config.py` (near `PLAN_BASE_THRESHOLD`/`PLAN_SPIKE_THRESHOLD`, currently
  lines 59-63)
- Modify: `core/settings.py:34-38` (`DEFAULTS` dict, right after `yandex_tts_version`)
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_defaults_include_commentary_mode():
    from core.settings import DEFAULTS
    assert DEFAULTS["commentary_mode"] == "live"


def test_save_and_load_roundtrip_commentary_mode():
    from core.settings import load, save
    save({"commentary_mode": "story"})
    assert load()["commentary_mode"] == "story"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_settings.py -v`
Expected: the two new tests FAIL with `KeyError: 'commentary_mode'` (first test) — the
key doesn't exist in `DEFAULTS` yet.

- [ ] **Step 3: Add the config constant**

In `config.py`, right after the existing block:

```python
PLAN_BASE_THRESHOLD = 35.0       # порог "говорить" вне спайка (обычное затишье)
PLAN_SPIKE_THRESHOLD = 65.0      # порог сразу после озвученной фразы
PLAN_THRESHOLD_DECAY_S = 45.0    # за сколько секунд спайк линейно спадает к базе
PLAN_STALE_S = 20.0              # старше этого в очереди + importance < PLAN_STALE_IMPORTANCE -> пропуск
PLAN_STALE_IMPORTANCE = 70       # порог важности, ниже которого работает вытеснение по staleness
```

add:

```python

# Commentary Mode (live/calm/story, design spec 2026-07-07): офсет к порогу
# "говорить/молчать" (PLAN_BASE_THRESHOLD/PLAN_SPIKE_THRESHOLD) по режиму.
# ИНВАРИАНТ: PLAN_SPIKE_THRESHOLD + offset должен оставаться < 90 (CRITICAL_FLOOR
# в commentator/planner.py) для ЛЮБОГО режима — иначе критические события
# (авария/штраф/финиш) потеряют гарантию "всегда проходит порог" в calm/story.
COMMENTARY_MODE_THRESHOLD_OFFSET = {"live": 0, "calm": 20, "story": 20}
```

- [ ] **Step 4: Add the settings key**

In `core/settings.py`, the `DEFAULTS` dict currently ends:

```python
    # v3 = современный нейро-рендер (живая интонация, поддержка role-хинтов) —
    # дефолт с 2026-07-01 (жалоба «звучит как робот» на v1+filipp). speech.py
    # гарантирует per-phrase фолбэк v3→v1 при любом сбое — деградация безопасна.
    "yandex_tts_version":      "v3",
}
```

Change to:

```python
    # v3 = современный нейро-рендер (живая интонация, поддержка role-хинтов) —
    # дефолт с 2026-07-01 (жалоба «звучит как робот» на v1+filipp). speech.py
    # гарантирует per-phrase фолбэк v3→v1 при любом сбое — деградация безопасна.
    "yandex_tts_version":      "v3",
    # live/calm/story — темп и стиль повествования, НЕЗАВИСИМАЯ ось от persona
    # (persona = характер голоса, commentary_mode = как часто/подробно говорит).
    # См. docs/superpowers/specs/2026-07-07-commentary-mode-design.md.
    "commentary_mode":         "live",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_settings.py -v`
Expected: all tests PASS (7 existing + 2 new = 9 passed).

- [ ] **Step 6: Checkpoint**

Run: `py -3.12 -m pytest tests/test_settings.py -q`
Expected: `9 passed`

---

### Task 2: `commentator/planner.py` — `mode` parameter, `narrative` field, forced normal length

**Files:**
- Modify: `commentator/planner.py:28-38` (`CommentPlan` dataclass), `:156-228`
  (`build_plan()`)
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_planner.py`:

```python
# --------------------------------------------------------------------------- #
# build_plan: commentary_mode "story" forces normal length + narrative flag
# --------------------------------------------------------------------------- #

def test_build_plan_default_mode_is_live_and_narrative_false():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.narrative is False


def test_build_plan_story_mode_sets_narrative_true():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=50, persona="tv", mode="story")
    assert plan.narrative is True


def test_build_plan_story_mode_forces_normal_length_at_high_importance():
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="story")
    assert plan.length == "обычная"


def test_build_plan_story_mode_forces_normal_length_even_when_force_urgent():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="tv", mode="story")
    assert plan.length == "обычная"


def test_build_plan_story_mode_does_not_change_emotion():
    """Design decision: story меняет частоту+длину, НЕ тон/эмоцию персоны."""
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="story")
    assert plan.emotion == "на пределе"


def test_build_plan_calm_mode_does_not_set_narrative():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=50, persona="tv", mode="calm")
    assert plan.narrative is False


def test_build_plan_calm_mode_does_not_force_normal_length():
    """calm меняет ТОЛЬКО частоту (это делает core/engine.py, не planner.py) —
    длина/эмоция реплики остаются как в обычной шкале важности."""
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv", mode="calm")
    assert plan.length == "короткая ударная"


def test_commentary_mode_offset_never_lets_spike_reach_critical_floor():
    """Инвариант дизайна: критические события (пол >=90 в score_importance)
    должны проходить порог "говорить" в ЛЮБОМ режиме — офсет режима не должен
    поднимать spike-порог до 90 и выше."""
    import config
    for offset in config.COMMENTARY_MODE_THRESHOLD_OFFSET.values():
        assert config.PLAN_SPIKE_THRESHOLD + offset < 90
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_planner.py -v`
Expected: FAIL with `TypeError: build_plan() got an unexpected keyword argument 'mode'`
for the tests that pass `mode=`, and `AttributeError: 'CommentPlan' object has no
attribute 'narrative'` for `test_build_plan_default_mode_is_live_and_narrative_false`.
The invariant test (`test_commentary_mode_offset_never_lets_spike_reach_critical_floor`)
should already PASS once Task 1's constant exists (it doesn't touch `build_plan`).

- [ ] **Step 3: Add the `narrative` field to `CommentPlan`**

Current (`commentator/planner.py:28-38`):

```python
@dataclass(frozen=True)
class CommentPlan:
    """Директива для LLM: ЧТО комментировать и КАК. Собирается build_plan()
    ПОСЛЕ entity resolution — driver/target в event должны быть настоящими
    именами, не '#N'/'гонщик'."""
    focus: str
    reaction: str
    length: str
    emotion: str
    importance: int
    must_mention: tuple[str, ...] = ()
```

Change to:

```python
@dataclass(frozen=True)
class CommentPlan:
    """Директива для LLM: ЧТО комментировать и КАК. Собирается build_plan()
    ПОСЛЕ entity resolution — driver/target в event должны быть настоящими
    именами, не '#N'/'гонщик'."""
    focus: str
    reaction: str
    length: str
    emotion: str
    importance: int
    must_mention: tuple[str, ...] = ()
    narrative: bool = False
```

- [ ] **Step 4: Add the `mode` parameter and forced-normal-length logic to `build_plan()`**

Current (`commentator/planner.py:156-228`, the tail of the function):

```python
def build_plan(event: dict, importance: int, persona: str) -> CommentPlan:
    """Строит директиву для LLM. Вызывать ПОСЛЕ entity resolution — driver/target
    в event должны быть уже резолвнутыми именами (см. _commentary_loop в
    core/engine.py: entity resolution идёт раньше build_plan() в пайплайне).
    ...
    """
    code = event.get("event_code", "")
```

... (unchanged middle of the function) ...

```python
    if force_urgent:
        length = _LENGTH_SHORT
        emotion = _shift_emotion(_EMOTION_TOP, persona)
    else:
        length = _LENGTH_SHORT if importance >= _LENGTH_SHORT_THRESHOLD else _LENGTH_NORMAL
        emotion = _shift_emotion(_base_emotion(importance), persona)

    must_mention = tuple(name for name in (driver, target) if name)

    return CommentPlan(
        focus=focus,
        reaction=reaction,
        length=length,
        emotion=emotion,
        importance=importance,
        must_mention=must_mention,
    )
```

Change the signature line to:

```python
def build_plan(event: dict, importance: int, persona: str, mode: str = "live") -> CommentPlan:
```

Add one line to the docstring (after the existing Race Memory paragraph, before the
closing `"""`):

```python
    Commentary Mode (design spec 2026-07-07-commentary-mode): mode="story" forces
    normal-length phrasing (never the short/punchy variant, even when force_urgent
    would otherwise pick it) and sets narrative=True — a hint consumed by
    commentator/brain.py to nudge the LLM toward connective phrasing. mode="calm"
    changes ONLY frequency (core/engine.py::_speak_threshold()) — it does not
    touch length/emotion here. Emotion is never affected by mode, only by persona."""
```

Add `narrative = mode == "story"` right after the `code = event.get(...)` line, and
force normal length after the existing `if force_urgent: ... else: ...` block:

```python
    code = event.get("event_code", "")
    narrative = mode == "story"
    driver = event.get("driver") or ""
```

```python
    if force_urgent:
        length = _LENGTH_SHORT
        emotion = _shift_emotion(_EMOTION_TOP, persona)
    else:
        length = _LENGTH_SHORT if importance >= _LENGTH_SHORT_THRESHOLD else _LENGTH_NORMAL
        emotion = _shift_emotion(_base_emotion(importance), persona)

    if narrative:
        length = _LENGTH_NORMAL   # story: связнее важнее ударнее, даже force_urgent

    must_mention = tuple(name for name in (driver, target) if name)

    return CommentPlan(
        focus=focus,
        reaction=reaction,
        length=length,
        emotion=emotion,
        importance=importance,
        must_mention=must_mention,
        narrative=narrative,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_planner.py -v`
Expected: all PASS. Full file count: 49 existing + 8 new = 57 passed.

- [ ] **Step 6: Checkpoint**

Run: `py -3.12 -m pytest tests/test_planner.py tests/test_settings.py -q`
Expected: `66 passed` (57 + 9 from Task 1)

---

### Task 3: `core/engine.py` — mode-aware `_speak_threshold()` + `build_plan()` call wiring

**Files:**
- Modify: `core/engine.py:662-672` (`_speak_threshold()`), `:1614-1616` (`build_plan()`
  call site)
- Test: `tests/test_engine_planner.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_planner.py`:

```python
# --------------------------------------------------------------------------- #
# _speak_threshold: commentary_mode офсет (live/calm/story)
# --------------------------------------------------------------------------- #

def test_speak_threshold_live_mode_unchanged(engine):
    engine.settings["commentary_mode"] = "live"
    engine._last_voiced_at = 1000.0
    assert engine._speak_threshold(1000.0) == config.PLAN_SPIKE_THRESHOLD
    del engine.settings["commentary_mode"]


def test_speak_threshold_calm_mode_raises_spike_and_base(engine):
    engine.settings["commentary_mode"] = "calm"
    offset = config.COMMENTARY_MODE_THRESHOLD_OFFSET["calm"]
    engine._last_voiced_at = 1000.0
    assert engine._speak_threshold(1000.0) == config.PLAN_SPIKE_THRESHOLD + offset
    result = engine._speak_threshold(1000.0 + config.PLAN_THRESHOLD_DECAY_S)
    assert result == config.PLAN_BASE_THRESHOLD + offset
    del engine.settings["commentary_mode"]


def test_speak_threshold_story_mode_same_offset_as_calm(engine):
    engine.settings["commentary_mode"] = "story"
    engine._last_voiced_at = 1000.0
    assert engine._speak_threshold(1000.0) == (
        config.PLAN_SPIKE_THRESHOLD + config.COMMENTARY_MODE_THRESHOLD_OFFSET["story"])
    del engine.settings["commentary_mode"]


def test_speak_threshold_missing_setting_defaults_to_live(engine):
    engine._last_voiced_at = 1000.0
    assert engine._speak_threshold(1000.0) == config.PLAN_SPIKE_THRESHOLD
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -v`
Expected: the 3 mode-setting tests FAIL (`_speak_threshold` returns the unmodified
`config.PLAN_SPIKE_THRESHOLD`/`config.PLAN_BASE_THRESHOLD` regardless of
`engine.settings["commentary_mode"]` — the offset isn't read yet). The "missing
setting" test already passes (no behavior change for the default case).

- [ ] **Step 3: Update `_speak_threshold()`**

Current (`core/engine.py:662-672`):

```python
    def _speak_threshold(self, now: float) -> float:
        """Динамический порог 'говорить\молчать' по важности: сразу после
        озвученной фразы подскакивает, линейно спадает к базе за
        PLAN_THRESHOLD_DECAY_S секунд. НЕ применяется к AMBIENT — у него свой
        адаптивный каданс (_ambient_loop, Task #14); второй фильтр поверх задушил
        бы его насмерть (см. design spec — сознательное исключение)."""
        elapsed = now - self._last_voiced_at
        if elapsed >= config.PLAN_THRESHOLD_DECAY_S:
            return config.PLAN_BASE_THRESHOLD
        span = config.PLAN_SPIKE_THRESHOLD - config.PLAN_BASE_THRESHOLD
        return config.PLAN_SPIKE_THRESHOLD - span * (elapsed / config.PLAN_THRESHOLD_DECAY_S)
```

Change to:

```python
    def _speak_threshold(self, now: float) -> float:
        """Динамический порог 'говорить\молчать' по важности: сразу после
        озвученной фразы подскакивает, линейно спадает к базе за
        PLAN_THRESHOLD_DECAY_S секунд. НЕ применяется к AMBIENT — у него свой
        адаптивный каданс (_ambient_loop, Task #14); второй фильтр поверх задушил
        бы его насмерть (см. design spec — сознательное исключение).

        Commentary Mode (design spec 2026-07-07-commentary-mode): calm/story
        поднимают обе границы на config.COMMENTARY_MODE_THRESHOLD_OFFSET[mode] —
        реже проходят порог "говорить". Критические события (score_importance
        пол >=90) всё равно всегда проходят: см. инвариант-тест в test_planner.py."""
        offset = config.COMMENTARY_MODE_THRESHOLD_OFFSET.get(
            self._get_setting("commentary_mode", "live"), 0)
        base = config.PLAN_BASE_THRESHOLD + offset
        spike = config.PLAN_SPIKE_THRESHOLD + offset
        elapsed = now - self._last_voiced_at
        if elapsed >= config.PLAN_THRESHOLD_DECAY_S:
            return base
        span = spike - base
        return spike - span * (elapsed / config.PLAN_THRESHOLD_DECAY_S)
```

(`self._get_setting(key, default)` already exists at `core/engine.py:516-517` — reuse
it rather than adding a new helper method.)

- [ ] **Step 4: Wire `mode` into the `build_plan()` call site**

Current (`core/engine.py:1614-1616`):

```python
                    try:
                        plan = build_plan(event, event.get("importance", 50),
                                           self.commentator.persona)
                    except Exception:
```

Change to:

```python
                    try:
                        plan = build_plan(event, event.get("importance", 50),
                                           self.commentator.persona,
                                           mode=self._get_setting("commentary_mode", "live"))
                    except Exception:
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -v`
Expected: all PASS. Full file count: 21 existing + 4 new = 25 passed.

- [ ] **Step 6: Checkpoint**

Run: `py -3.12 -m pytest tests/test_engine_planner.py tests/test_planner.py tests/test_settings.py -q`
Expected: `91 passed` (25 + 66 from Tasks 1-2)

---

### Task 4: `commentator/brain.py` — narrative style hint in the LLM directive

**Files:**
- Modify: `commentator/brain.py:127-142` (`_compose()`)
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_brain.py`:

```python
def test_plan_narrative_true_adds_story_style_hint():
    ai = FakeAI(result="фраза")
    plan = CommentPlan(focus="атака: А и Б", reaction="атака", length="обычная",
                        emotion="оживлённо", importance=50, must_mention=(),
                        narrative=True)
    Commentator(ai, "tv").create({"event_code": "OVTK"}, "ctx", ai_ok=True, plan=plan)
    assert "свяжи с ходом гонки" in ai.calls[0][0]


def test_plan_narrative_false_omits_story_style_hint():
    ai = FakeAI(result="фраза")
    plan = CommentPlan(focus="атака: А и Б", reaction="атака", length="обычная",
                        emotion="оживлённо", importance=50, must_mention=(),
                        narrative=False)
    Commentator(ai, "tv").create({"event_code": "OVTK"}, "ctx", ai_ok=True, plan=plan)
    assert "свяжи с ходом гонки" not in ai.calls[0][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_brain.py -v`
Expected: `test_plan_narrative_true_adds_story_style_hint` FAILS (the hint line doesn't
exist yet — `"свяжи с ходом гонки" not in ai.calls[0][0]`).
`test_plan_narrative_false_omits_story_style_hint` already PASSES (nothing to omit
yet) — that's fine, it's there to catch a regression later, not to prove new behavior.

- [ ] **Step 3: Add the narrative hint**

Current (`commentator/brain.py:134-142`):

```python
        if plan is not None:
            directive = (
                f"ЗАДАЧА: прокомментируй ИМЕННО это: {plan.focus}.\n"
                f"Тип реакции: {plan.reaction}. Стиль: {plan.length}, {plan.emotion}."
            )
            if plan.must_mention:
                directive += f"\nОбязательно упомяни: {', '.join(plan.must_mention)}."
            directive += "\nОстальной контекст ниже — только фон, НЕ пересказывай его."
            parts.append(directive)
```

Change to:

```python
        if plan is not None:
            directive = (
                f"ЗАДАЧА: прокомментируй ИМЕННО это: {plan.focus}.\n"
                f"Тип реакции: {plan.reaction}. Стиль: {plan.length}, {plan.emotion}."
            )
            if plan.must_mention:
                directive += f"\nОбязательно упомяни: {', '.join(plan.must_mention)}."
            if plan.narrative:
                directive += "\nСтиль: свяжи с ходом гонки, не отдельная реплика."
            directive += "\nОстальной контекст ниже — только фон, НЕ пересказывай его."
            parts.append(directive)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_brain.py -v`
Expected: all PASS.

- [ ] **Step 5: Checkpoint**

Run: `py -3.12 -m pytest tests/test_brain.py tests/test_engine_planner.py tests/test_planner.py tests/test_settings.py -q`
Expected: all passed, no failures.

---

### Task 5: UI — "Стиль повествования" panel on the Voice screen

**Files:**
- Modify: `NewSpotterUI/lib/api.ts:36-52` (`SettingsState` type)
- Modify: `NewSpotterUI/components/spotter/views/voice.tsx`

No automated test runner covers this frontend in the repo — verify by hand in a
browser (Step 4 below).

- [ ] **Step 1: Add `commentary_mode` to the `SettingsState` type**

Current (`NewSpotterUI/lib/api.ts:36-52`):

```typescript
export type SettingsState = {
  persona: string
  commentary_enabled: boolean
  autovoice_enabled: boolean
  critical_events_enabled: boolean
  ambient_enabled: boolean
  radio_fx: boolean
  commentator_position: string
  min_comment_gap: number
  broadcast_mode_enabled: boolean
  volume: number
  volume_tv: number
  volume_hype: number
  volume_calm: number
  volume_toxic: number
  yandex_tts_version: "v1" | "v3"
}
```

Change the last line to:

```typescript
  yandex_tts_version: "v1" | "v3"
  commentary_mode: "live" | "calm" | "story"
}
```

- [ ] **Step 2: Add state, sync effect, and setter in `voice.tsx`**

Current (`NewSpotterUI/components/spotter/views/voice.tsx:13-21`):

```typescript
export function VoiceView({ state }: { state: SpotterState | null }) {
  const [active, setActive] = useState("tv")
  const [radioFx, setRadioFx] = useState(true)
  const [ttsVersion, setTtsVersion] = useState<"v1" | "v3">("v1")
  const [voices, setVoices] = useState<VoicesResponse | null>(null)
  const [globalVol, setGlobalVol] = useState(80)
  const [personaVols, setPersonaVols] = useState<Record<string, number>>({
    tv: 80, hype: 90, calm: 75, toxic: 80,
  })
```

Change to:

```typescript
export function VoiceView({ state }: { state: SpotterState | null }) {
  const [active, setActive] = useState("tv")
  const [radioFx, setRadioFx] = useState(true)
  const [ttsVersion, setTtsVersion] = useState<"v1" | "v3">("v1")
  const [commentaryMode, setCommentaryMode] = useState<"live" | "calm" | "story">("live")
  const [voices, setVoices] = useState<VoicesResponse | null>(null)
  const [globalVol, setGlobalVol] = useState(80)
  const [personaVols, setPersonaVols] = useState<Record<string, number>>({
    tv: 80, hype: 90, calm: 75, toxic: 80,
  })
```

Current (`NewSpotterUI/components/spotter/views/voice.tsx:32-36`):

```typescript
  // Sync Yandex TTS version from backend state.
  useEffect(() => {
    const v = state?.settings?.yandex_tts_version
    if (v === "v1" || v === "v3") setTtsVersion(v)
  }, [state?.settings?.yandex_tts_version])
```

Add right after it:

```typescript

  // Sync commentary mode (live/calm/story) from backend state.
  useEffect(() => {
    const m = state?.settings?.commentary_mode
    if (m === "live" || m === "calm" || m === "story") setCommentaryMode(m)
  }, [state?.settings?.commentary_mode])
```

Current (`NewSpotterUI/components/spotter/views/voice.tsx:55-58`):

```typescript
  const pickTtsVersion = (v: "v1" | "v3") => {
    setTtsVersion(v)
    saveSettings({ yandex_tts_version: v })
  }
```

Add right after it:

```typescript

  const pickCommentaryMode = (m: "live" | "calm" | "story") => {
    setCommentaryMode(m)
    saveSettings({ commentary_mode: m })
  }
```

- [ ] **Step 3: Add the panel**

Current (`NewSpotterUI/components/spotter/views/voice.tsx`, the `Personas` panel closes
right before the `{/* TTS engine */}` comment — around line 124-126):

```typescript
        </Panel>

        {/* TTS engine */}
```

Change to:

```typescript
        </Panel>

        {/* Commentary Mode — независимая ось от persona: НЕ характер, а темп/стиль */}
        <Panel label="Стиль повествования">
          <p className="mb-4 text-xs text-muted-foreground">
            Это про то, КАК ЧАСТО и КАК ПОДРОБНО говорит комментатор — не про характер.
            Характер (весёлый/спокойный/токсичный) настраивается выше, в панели
            «Профиль инженера».
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(
              [
                { id: "live" as const, name: "Live", tagline: "Как сейчас" },
                { id: "calm" as const, name: "Calm", tagline: "Реже" },
                { id: "story" as const, name: "Story", tagline: "Реже и связнее" },
              ]
            ).map((m) => {
              const isActive = commentaryMode === m.id
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => pickCommentaryMode(m.id)}
                  className={cn(
                    "flex flex-col rounded-lg border px-5 py-3 text-left transition-all",
                    isActive
                      ? "border-primary/50 bg-primary/8"
                      : "border-border bg-secondary/40 hover:bg-secondary",
                  )}
                >
                  <span className="font-heading text-sm font-bold text-foreground">
                    {m.name}
                    {isActive && <span className="ml-2 text-[10px] font-mono text-primary">АКТИВЕН</span>}
                  </span>
                  <span className="mt-0.5 text-xs text-muted-foreground">{m.tagline}</span>
                </button>
              )
            })}
          </div>
        </Panel>

        {/* TTS engine */}
```

- [ ] **Step 4: Manual browser verification**

Start the dev server for `NewSpotterUI` (check `package.json` for the exact script,
typically `npm run dev`), open the Voice screen, and confirm:
- A new "Стиль повествования" panel appears between "Профиль инженера" and "Движок
  озвучки", with the tooltip text explaining it's not about persona.
- Clicking Calm/Story/Live switches the active card and persists (reload the page —
  the previously selected mode should still be highlighted, confirming the round trip
  through `saveSettings`/`/api/state`).
- The persona panel above is unaffected by clicking commentary-mode cards (confirms
  the two axes are visually and functionally independent).

- [ ] **Step 5: Checkpoint**

No pytest for this task — the manual verification in Step 4 IS the checkpoint. Note
in your task report which of the three checks passed.

---

### Task 6: Full verification + CONTEXT.md

**Files:**
- No source changes — verification only.
- Modify: `CONTEXT.md`
- Modify (append only): `docs/CONTEXT_ARCHIVE.md`

- [ ] **Step 1: Full test run**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`

Expected: all tests pass. Baseline going into this plan (end of Phrase Bank Expansion,
2026-07-05) was **945 passed, 1 skipped**. This plan adds 2 (Task 1) + 8 (Task 2) + 4
(Task 3) + 2 (Task 4) = 16 new tests, so the arithmetic expectation is **961 passed, 1
skipped** — but use whatever the ACTUAL run reports, not this arithmetic (this
project's history shows the baseline sometimes shifts between writing a plan and
executing it). If the final summary line doesn't print cleanly (a known Windows/pytest
buffering quirk in this project), count pass/fail markers yourself, e.g.
`grep -o '[.sF]' <log> | sort | uniq -c`.

- [ ] **Step 2: Import smoke tests**

Run:
```
py -3.12 -c "import commentator.planner; import commentator.brain; import core.engine; import core.settings"
```
Expected: no errors.

- [ ] **Step 3: Update `CONTEXT.md`**

Read `CONTEXT.md` in full first — it documents its own convention at the top (keep to
~100 "points" total, only the ~3 most recent sessions written out in full under
`## Сессия YYYY-MM-DD` headings, older ones compressed to one paragraph under
"Архив старых сессий" with full text moved to `docs/CONTEXT_ARCHIVE.md`).

- Count the CURRENT number of full `## Сессия` entries BEFORE adding yours (e.g.
  `grep -n "^## Сессия" CONTEXT.md`). Only archive the oldest one if adding your new
  entry would push the count above ~3 — do not archive anything if the count would
  stay at or below 3.
- Today's date is 2026-07-07, a NEW day relative to the neighboring `2026-07-05
  (продолжение)` entries — title your entry **without** "(продолжение)":
  `## Сессия 2026-07-07 — Commentary Mode: live/calm/story, 5/5 ✅` (adjust the task
  count if it differs from 5 by the time you run this).
- Cover, in this file's own terse technical voice (restate, don't copy the paragraphs
  above verbatim):
  - What `commentary_mode` is and why it's a separate axis from `persona` (persona =
    character, this = pace/style) — including the naming collision worth flagging:
    `persona` already has a value literally called `"calm"` (tv/hype/calm/toxic), and
    `commentary_mode` now ALSO has a value called `"calm"` — same word, two unrelated
    settings keys, UI tooltip added specifically to prevent user confusion.
  - The mechanism: `_speak_threshold()` offset (`COMMENTARY_MODE_THRESHOLD_OFFSET`,
    live=0/calm=20/story=20) controls frequency; `build_plan()`'s `narrative` flag
    (story only) forces normal length and adds an LLM style hint in `brain.py`.
  - The critical-floor safety invariant (spike threshold + offset must stay under 90)
    and that it's covered by a dedicated test, not just documentation.
  - Free-mode (`templates.py`) degradation: `story` behaves like `calm` there (no LLM
    to add narrative connectivity) — same graceful-degradation principle as TTS
    v3→v1.
  - The real test count from Step 1.
  - What's explicitly out of scope (see the design spec's "Не входит в объём"):
    "Почему эта фраза" UI display (next item on the user's UI wishlist), configurable
    threshold offset via UI.
- Update "На чём остановились" to reflect this feature is done; note that
  "Почему эта фраза" is the next UI item queued up (per the user's own ordering
  during brainstorming), not yet started.
- Self-review your diff: re-read the whole file top to bottom afterward, confirm no
  content was duplicated or lost, confirm "На чём остановились" is internally
  consistent with the rest of the file.

- [ ] **Step 4: Checkpoint**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` one more time after the
CONTEXT.md edit (docs changes shouldn't affect tests, but confirm nothing broke).
Expected: same pass/fail/skip counts as Step 1.

---

## Execution notes for whoever runs this plan

- Tasks 1-4 are backend-only and fully TDD-able; Task 5 is frontend-only with no
  pytest coverage (manual browser check instead); Task 6 is verification + docs.
- Tasks 1-4 must run in order (each depends on the previous one's code existing:
  Task 2 needs Task 1's config constant for its invariant test; Task 3 needs Task 2's
  `mode` parameter; Task 4 needs Task 2's `narrative` field).
- Task 5 can technically run in parallel with 1-4 (touches only frontend files) but
  wire it in after Task 3 if you want to manually verify the frequency change
  end-to-end in the browser too (optional, not required by Step 4 of Task 5).
