# RaceFeed: оживить комментарии и учитывать фазу сессии

Status: done

## Problem

Комментарии под завершившими гонку публикациями иногда продолжают говорить о
гонке как о незавершённой: например, под постом о финише появляется реплика
«это ещё не конец». Это ломает правдоподобие RaceFeed.

Сейчас comment-generation получает только `reporter_id`, `category` и готовый
текст поста. Явного факта `session_phase` / `race_finished` в его interface нет.
Детерминированный fallback также состоит преимущественно из live-race реплик
вроде «до финиша далеко» и «один неудачный пит — и всё перевернётся».

## Expected behavior

- Комментарии знают, опубликован пост во время гонки или после финиша.
- Под `CHQF`, итогами чемпионата, milestone и career recap не появляются
  предположения о будущих кругах, пит-стопах или ещё не определившемся результате.
- Live-публикации сохраняют напряжённые и осторожные реакции.
- Комментарии остаются разнообразными и связаны с конкретным содержанием поста.

## Acceptance criteria

- В publication context появляется явный структурированный признак фазы сессии;
  распознавание не строится на парсинге текста поста.
- LLM prompt различает как минимум `live` и `finished`.
- Offline fallback имеет отдельный post-finish пул реплик.
- Regression-тест запрещает фразы «ещё не конец», «до финиша далеко» и
  предположения о будущем пите для завершённой гонки.
- Regression-тест подтверждает, что live-race пул не стал стерильным.
- Существующие comment parsing, reply links и progressive reveal не ломаются.

## Likely files

- `core/racefeed/models.py`
- `core/racefeed/engine.py`
- `core/racefeed/comments.py`
- `tests/racefeed/test_comments.py`
- `tests/racefeed/test_race_feed_engine.py`

## Comments

- Добавлено по пользовательскому репорту 2026-07-26: комментарий «это ещё не
  конец» появился под постом уже после финиша.
- Предпочтительное направление: передавать фазу как narrative fact publication,
  а не выводить её из `story_id`, категории или сгенерированного текста.
- 2026-08-13: закрыто. Обнаружено при разборе «что осталось» — реализовано в
  одной из сессий 08-10…08-11, но строка `Status:` осталась прежней, и задача
  числилась открытой. Все шесть критериев приёмки сверены по коду и тестам:
  `Post.session_phase` (`core/racefeed/models.py:162`), выставляется движком
  (`engine.py:391`), `_phase_of()` читает поле, а не текст поста;
  `_PHASE_INSTRUCTION` различает live/finished в промпте; `_PHASE_POOLS`
  держит отдельный post-finish пул для offline-ветки. Тесты:
  `test_finished_phase_threads_never_speculate_about_the_rest_of_the_race`
  (запрещает «ещё не конец», «до финиша далеко», предположения о будущем пите),
  парный тест на то, что live-пул не стал стерильным,
  `test_llm_prompt_carries_the_session_phase`,
  `test_post_race_categories_are_finished_even_without_the_field`. Прогон
  `tests/racefeed/` — 306 тестов, зелено.
