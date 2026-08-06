# Снижение задержки озвучки (TTS cache + персона→голос)

Дата: 2026-06-16

## Цель

Сократить ощутимую задержку между событием гонки и озвучкой до уровня
"почти мгновенно" для повторяющихся/шаблонных фраз, оставаясь полностью
офлайн и бесплатным (без облачных TTS). Дополнительно — дать персонам
комментатора разные голоса Silero вместо одного `baya` для всех.

Не цель: догнать качество/латентность облачных TTS (ElevenLabs и т.п.) —
это физически недостижимо в офлайн-режиме на CPU.

## Архитектура

```
voice/
├── tts.py     — Voice: say(), _say_silero(), set_persona()
└── cache.py   — TTSCache: диск-кэш WAV по hash(text + speaker)
```

WAV-файл кэша одновременно служит файлом воспроизведения: при генерации
он сразу пишется в `DATA_DIR/tts_cache/<sha1>.wav` и не удаляется после
проигрывания (в отличие от текущего поведения с tempfile).

## Компоненты

### `voice/cache.py` — `TTSCache`

```python
class TTSCache:
    def __init__(self, cache_dir: Path, max_files=3000, max_mb=300): ...
    def path_for(self, text: str, speaker: str) -> Path:
        """DATA_DIR/tts_cache/<sha1(text|speaker)>.wav — не проверяет существование."""
    def evict_if_needed(self) -> None:
        """Удаляет самые старые по mtime файлы, если превышены лимиты."""
```

`path_for` — чистая функция (hash → путь). Наличие файла на диске и есть
признак cache hit/miss — отдельного индекса не нужно.

### `voice/tts.py` — изменения

- `PERSONA_SPEAKER = {"tv": "baya", "hype": "xenia", "calm": "kseniya", "toxic": "aidar"}`
- `Voice.__init__`: `self._current_speaker = _SILERO_SPEAKER` (дефолт `baya`),
  `self._cache = TTSCache(config.DATA_DIR / "tts_cache")`
- `Voice.set_persona(persona: str)`: `self._current_speaker = PERSONA_SPEAKER.get(persona, _SILERO_SPEAKER)`
- `_say_silero(text)`:
  1. `path = self._cache.path_for(text, self._current_speaker)`
  2. если `path.exists()` → сразу `_winsound_play(path)`, выход (cache hit, без модели)
  3. иначе → `apply_tts(..., speaker=self._current_speaker)` → `_write_wav(audio, path, sample_rate)` →
     `self._cache.evict_if_needed()` → `_winsound_play(path)`
- `_play_tensor` переименовать в `_write_wav(audio, final_path, sample_rate)`:
  пишет WAV во временный файл (`tempfile.NamedTemporaryFile`), затем
  `os.replace(tmp, final_path)` — атомарный перенос в кэш. Если `os.replace`
  не удался (диск полон, нет прав) — не падаем, возвращаем путь к tempfile
  для проигрывания, а кэш на этот раз просто не пополняется.
- `_winsound_play(path)` — отдельная функция воспроизведения, файл не удаляет
  (кэш — постоянный; tempfile-fallback из предыдущего пункта удаляется после
  проигрывания, поскольку не попал в `tts_cache/`).
- После успешной загрузки модели в `_init_silero` — запустить
  `threading.Thread(target=self._prewarm_cache, daemon=True)`:
  проходит по `templates.SIMPLE`, берёт фразы без `{` (без подстановок),
  генерирует и кэширует их для `self._current_speaker`, если их там ещё нет.

### `core/engine.py` — изменения

В `apply_settings`, рядом со строкой 116 (`self.commentator.persona = settings["persona"]`),
добавить `self.voice.set_persona(settings["persona"])`.

## Поток данных

```
event → commentator.generate_phrase() → text
                                          │
                                          ▼
                              Voice.say(text) [non-blocking thread]
                                          │
                              cache.path_for(text, speaker)
                                  │exists           │missing
                                  ▼                 ▼
                          play immediately   apply_tts() → write to
                                              cache path → play
```

## Обработка ошибок

- Повреждённый/нечитаемый файл кэша → `winsound.PlaySound` бросает исключение →
  ловим, удаляем битый файл, генерируем заново (без падения воспроизведения).
- Ошибка записи в кэш (диск полон, нет прав на `os.replace`) → логируем в
  `status_message`, проигрывание идёт из tempfile-fallback (см. `_write_wav` выше),
  кэш просто не пополняется в этот раз.
- Прогрев (`_prewarm_cache`) оборачивается в `try/except` целиком — сбой прогрева
  не должен ронять инициализацию голоса, только пропускается.

## Тестирование

Ручная проверка (нет тестового фреймворка в проекте):

1. `test_say("Привет")` дважды подряд — второй вызов должен быть заметно быстрее
   (залогировать время начала/конца в `status_message` или консоль на время теста).
2. Смена персоны в UI → `test_say(...)` → голос должен звучать другим спикером.
3. Старт приложения → через несколько секунд проверить, что
   `DATA_DIR/tts_cache/` содержит файлы для фраз без подстановок (`SSTA`, `CHQF`, `SPTP`).
4. Удалить/повредить один файл в `tts_cache/` вручную → `test_say` с тем же текстом
   не должен падать, должен перегенерировать.

## Вне рамок

- Облачные TTS — исключено явным решением пользователя (офлайн/бесплатно).
- Предгенерация всех комбинаций шаблон×пилот при сборке — отклонено
  (комбинаторный взрыв, не помогает LLM-тексту).
- Склейка аудио по словам/слогам для частично кэшированных фраз с разными
  именами — не рассматривается, избыточная сложность для данного масштаба.
