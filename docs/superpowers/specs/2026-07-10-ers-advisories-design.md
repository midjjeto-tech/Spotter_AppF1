# ERS-подсказки инженера (Фаза 3, шаг 2/3) — дизайн

Дата: 2026-07-10
Статус: утверждён пользователем по объёму (диалог 2026-07-10: три подсказки
выбраны явно), детали порогов приняты агентом — помечены ниже как требующие
review постфактум.

## Контекст

Фаза 3 «замены инженера» = топливо + ERS. Топливо готово (`fuel_save`).
Шаг 1 (парсинг ERS, `ers_percent`/`ers_deploy_mode`) закрыт и офсеты
подтверждены официальной спекой F1 25 (см.
`2026-07-10-ers-telemetry-parsing-design.md`). Этот шаг — три подсказки,
выбранные пользователем:
1. Совет экономить заряд при низком заряде батареи.
2. Подсказка «давай овертейк» при борьбе за позицию.
3. Периодический % заряда в гэп-дайджесте инженера (Фаза 2).

## Проблема

`ers_percent`/`ers_deploy_mode` парсятся (`parse_player_status`), но:
- НЕ сохраняются в `self._player_*` (`_update_telemetry` их игнорирует).
- НЕ доходят до `StrategyAnalyzer` (`st_snapshot` их не несёт).
- НЕ доходят до `GapDigestTracker`.

## Решение (одним абзацем)

Пробросить `ers_percent`/`ers_deploy_mode` из телеметрии в engine-state и
далее в `st_snapshot`/гэп-дайджест. Две новые детерминированные ветки в
`StrategyAnalyzer` (`ers_save`, `ers_overtake`) по образцу уже существующих
`fuel_save`/`push_pace` — они автоматически наследуют голос инженера
(`_st_code_map` уже помечает все `STRAT_*` как `speaker=engineer`), шаблонный
путь (`strategist.get_message`) и 20с-cooldown. Третья подсказка — опциональная
строка «Батарея N%» в конце гэп-дайджеста.

## Автономные решения (нужен review пользователя)

Пороги приняты по здравому смыслу F1, НЕ откалиброваны на слух:
1. **`ERS_LOW_PERCENT = 12`** — ниже этого «экономь заряд». Реальный инженер
   напоминает про батарею, когда деплой почти исчерпан.
2. **`ERS_OVERTAKE_MIN_PERCENT = 50`, `ERS_OVERTAKE_GAP_MS = 1200`** — «жми
   овертейк» когда заряда достаточно (≥50%) И соперник впереди близко
   (<1.2с, зона атаки/DRS) И режим отдачи ещё НЕ overtake (`deploy_mode != 2`).
3. **Батарея % — только ДОПОЛНЕНИЕ к гэп-дайджесту, не самостоятельный
   триггер.** Если гэпов нет (игрок один на трассе) — дайджест по-прежнему
   молчит (`None`), батарея одна не запускает сводку. Осознанно, против
   болтливости.
4. **ERS-советы идут через единое дерево `StrategyAnalyzer`** (одно событие
   за тик, конкурируют с pit/fuel по приоритету), а НЕ отдельным путём. Значит
   pit-вызов на том же тике вытеснит ERS-совет — это осознанно (pit важнее),
   и 20с-cooldown стратегии не даёт спамить. ERS-ветки ставятся НИЗКО в дереве
   (после fuel_save), чтобы pit/undercut/cover всегда выигрывали.
5. **Race-only** — `STRAT_ERS_SAVE`/`STRAT_ERS_OVERTAKE` добавляются в
   `session_guard._PRACTICE_SUPPRESS` (как уже сделано для сиблингов
   `STRAT_FUEL` и т.п.) — в практике/квалификации ERS-менеджмент не тот.

## Не входит в объём

- ERS соперников (парсится «бесплатно» общим хелпером, не используется).
- `m_ersHarvestedThisLap*`/`m_ersDeployedThisLap` — не парсятся, не нужны.
- Отдельный тумблер ERS-подсказок в настройках — как и у гэп-дайджеста, нет
  (открытый пункт на будущее).
- Подсказка про режим hotlap (`deploy_mode == 3`) — квалификационный, не
  гоночный, вне объёма.

## Архитектура

### Пламбинг (engine + snapshot)

`core/engine.py`:
- `__init__`: `self._player_ers_percent: float | None = None`,
  `self._player_ers_deploy_mode: int | None = None`.
- `_update_telemetry` (рядом с `fuel`):
  ```python
  if telem.get("ers_percent") is not None:
      self._player_ers_percent = telem["ers_percent"]
  if telem.get("ers_deploy_mode") is not None:
      self._player_ers_deploy_mode = telem["ers_deploy_mode"]
  ```
- `_maybe_snapshot`, `st_snapshot` (рядом с `"fuel"`):
  ```python
  "ers_percent": self._player_ers_percent,
  "ers_deploy_mode": self._player_ers_deploy_mode,
  ```
- `_maybe_emit_gap_digest`: передать ers в `build()`:
  ```python
  phrase = self._gap_digest.build(
      self._player_gap_front, self._player_gap_behind,
      ers_percent=self._player_ers_percent)
  ```

### Advisory A/B — `core/strategy_ai/analysis.py`

```python
ERS_LOW_PERCENT = 12.0
ERS_OVERTAKE_MIN_PERCENT = 50.0
ERS_OVERTAKE_GAP_MS = 1200

def ers_save_recommended(ers_percent: float | None) -> tuple[bool, float]:
    """Заряд почти исчерпан — беречь деплой."""
    if ers_percent is None or ers_percent >= ERS_LOW_PERCENT:
        return False, 0.0
    conf = 0.6 + (ERS_LOW_PERCENT - ers_percent) / ERS_LOW_PERCENT * 0.25
    return True, min(conf, 0.85)

def ers_overtake_recommended(
    ers_percent: float | None, ers_deploy_mode: int | None,
    gap_front_ms: int | None,
) -> tuple[bool, float]:
    """Есть заряд + близкий соперник впереди + ещё не в overtake-режиме."""
    if ers_percent is None or gap_front_ms is None:
        return False, 0.0
    if ers_deploy_mode == 2:            # уже overtake — не советуем повторно
        return False, 0.0
    if ers_percent < ERS_OVERTAKE_MIN_PERCENT or gap_front_ms > ERS_OVERTAKE_GAP_MS:
        return False, 0.0
    conf = 0.6 + (ERS_OVERTAKE_GAP_MS - gap_front_ms) / ERS_OVERTAKE_GAP_MS * 0.25
    return True, min(conf, 0.85)
```

### `core/strategy_ai/strategy.py`

`update()` берёт из snapshot `ers_percent`/`ers_deploy_mode`. Две новые ветки
ПОСЛЕ `fuel_save` (Priority 5), ПЕРЕД `pace_mode` (Priority 6):
- **Priority 5a: ERS overtake** (medium) — активнее, ставим раньше save.
- **Priority 5b: ERS save** (low).

Каждая — `StrategyEvent(type="ers_overtake"|"ers_save", ...)` в стиле
существующих веток. `_ADVICE_RU` пополняется двумя строками для UI-advice.

### `core/engine.py::_maybe_snapshot` — `_st_code_map`

```python
"ers_save":     "STRAT_ERS_SAVE",
"ers_overtake": "STRAT_ERS_OVERTAKE",
```

### `commentator/strategist.py` — `_MESSAGES`

```python
"ers_save": [
    "Заряд батареи на исходе — береги деплой.",
    "Мало энергии Э-эр-эс. Экономь на выходах из поворотов.",
],
"ers_overtake": [
    "Заряд есть — жми овертейк, атакуй сейчас.",
    "Полная батарея, соперник близко — режим атаки, вперёд.",
],
```
(«Э-эр-эс» — как в `new_tts/ru_textnorm._LEXICON["ERS"]`, но strategist пишет
кириллицей сразу, чтобы Yandex прочитал буквенную аббревиатуру верно.)

### `core/session_guard.py` — `_PRACTICE_SUPPRESS`

Добавить `"STRAT_ERS_SAVE"`, `"STRAT_ERS_OVERTAKE"` — race-only, как сиблинги.

### Advisory C — `core/strategy_ai/gap_digest.py`

```python
def build(self, gap_front_ms, gap_behind_ms, ers_percent=None) -> str | None:
    parts = [...]              # как раньше, гэпы
    if not parts:
        return None            # батарея одна НЕ запускает дайджест
    if ers_percent is not None:
        parts.append(f"Батарея {round(ers_percent)}%.")
    ...
```
(батарея добавляется только если уже есть гэп-часть — см. авт. решение 3.)

## Граничные случаи

- **ERS-поля отсутствуют** (пакет короче / старый патч) — `None`, все ветки
  и дайджест-хвост молча пропускаются.
- **Дребезг вокруг порогов** — 20с-cooldown стратегии + session_guard
  сглаживают; не усложняем гистерезисом (как и в box-call).
- **`ers_percent` округляется вниз к int в дайджесте** — «62%», не «62.5%»
  (никто не произносит десятые доли заряда).
- **overtake-совет при уже активном overtake-режиме** — подавлен
  (`deploy_mode == 2`).

## Тестирование

- `tests/test_strategy_ai.py` (или где тесты `StrategyAnalyzer`) —
  `ers_save_recommended`/`ers_overtake_recommended` чистые: порог,
  режим-гейт, gap-гейт, None-безопасность.
- Новые ветки дерева — snapshot с низким зарядом → `ers_save`-событие;
  snapshot с зарядом+близким соперником+не-overtake → `ers_overtake`.
- `tests/test_gap_digest.py` — `build(..., ers_percent=60)` добавляет
  «Батарея 60%.»; `ers_percent=None` не добавляет; батарея без гэпов → `None`.
- `tests/test_strategist.py` — фразы `ers_save`/`ers_overtake` на месте.
- `tests/test_session_guard.py` — `STRAT_ERS_*` подавлены в практике.
- Пламбинг engine (`_update_telemetry`/snapshot) — по образцу уже
  существующих тестов телеметрии, если есть; иначе покрывается косвенно.
- Живая проверка (звучат ли советы в нужные моменты, адекватны ли пороги) —
  у пользователя; пороги приняты автономно, нужен слух.
