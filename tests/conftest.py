"""Общие фикстуры тестов Yandex-комментатора."""
import os
import sys

import pytest

# Гарантируем, что корень проекта в sys.path (config, yandex_ai, ...)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Этот набор тестов написан под провайдер "yandex" (health-монитор Yandex,
# «нет креды → шаблоны», ярлык llm_engine и т.д.). Приложение по умолчанию
# работает на "gigachat" (config.LLM_PROVIDER, live-проверен 2026-07-25), но для
# тестов фиксируем "yandex" ЗДЕСЬ — до любых фикстур (модульная фикстура engine в
# test_engine_health строит F1Engine один раз при первом обращении). GigaChat-
# специфичные тесты (test_engine_gigachat, test_gigachat_provider) сами задают
# провайдер через monkeypatch и откатывают его после теста.
import config as _config  # noqa: E402
_config.LLM_PROVIDER = "yandex"


@pytest.fixture(scope="session", autouse=True)
def _isolate_data_dir_session(tmp_path_factory):
    """Сессионный слой изоляции `config.DATA_DIR` — см. `_isolate_data_dir`.

    Нужен отдельно от функционального слоя из-за порядка фикстур: pytest
    поднимает фикстуры от широкой области к узкой, поэтому module-фикстуры
    (`@pytest.fixture(scope="module")` — их в tests/ 32 штуки, почти все строят
    `F1Engine`) выполняются РАНЬШЕ любой function-autouse фикстуры. Без этого
    слоя такой движок успел бы прочитать и записать живые файлы до подмены."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            _config, "DATA_DIR",
            str(tmp_path_factory.mktemp("data_dir_session")), raising=False)
        yield


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Не давать тестам читать и ПЕРЕЗАПИСЫВАТЬ боевые данные пользователя.

    `config.DATA_DIR` в dev-режиме — корень проекта (config.py:10-14), и до
    2026-08-02 его ничто не подменяло. Любой прогон тестов (даже точечный, по
    5 файлам) писал в живые файлы, потому что все эти обращения к `DATA_DIR`
    происходят в рантайме:

      * `core/engine.py:484`  → `race_cache.json` (43 файла строят `F1Engine`);
      * `commentator/brain.py:67` → `PhraseMemory()` → `commentator_memory.json`
        (пишется на каждый `append()`);
      * `app.pyw:31` → `spotter.log` / `spotter-overlay-<widget>.log`.
        `test_app_overlay_entrypoint.py` вызывает настоящие `app.main()` и
        `app.overlay_main()`, а `_setup_logging()` вешает RotatingFileHandler на
        КОРНЕВОЙ логгер и не снимает его — после этого весь лог остальных тестов
        уходил в боевые файлы и выдавливал ротацией реальную историю приложения;
      * `voice/tts.py:68` → `tts_cache/`;
      * `core/racefeed/engine.py:594`, `core/engine.py:753` → `racefeed/`.

    Найдено 2026-08-02: точечный прогон 5 файлов затёр `race_cache.json`
    (все 22 пилота — плейсхолдер «гонщик») и `commentator_memory.json`
    (20 записей вида «фраза», «сфокусированная фраза»).

    ВАЖНО: подмена атрибута НЕ чинит константы, посчитанные на импорте модуля —
    `core/settings.py:120` `_PATH`, `analytics/archive.py:14` `_DATA`,
    `analytics/loader.py:45` `_CACHE`, `core/overlay_layout.py:45` `_DIR`
    (для последней есть отдельная `_isolate_overlay_layout`), а также
    производные из самого `config.py` (`ERGAST_CACHE_DIR`, `YANDEX_CREDS_FILE`,
    `OPENF1_CACHE_DIR`, `GIGACHAT_CREDS_FILE`). Их изолируют точечно."""
    data_dir = tmp_path / "data_dir"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(_config, "DATA_DIR", str(data_dir), raising=False)


@pytest.fixture(autouse=True)
def _isolate_overlay_layout(tmp_path_factory, monkeypatch):
    """Не давать тестам читать РЕАЛЬНУЮ раскладку оверлея разработчика.

    `core/overlay_layout.py` пишет `<DATA_DIR>/overlay_layout/<widget>.json`,
    когда пользователь перетаскивает виджет в игре, а `DATA_DIR` в dev-режиме —
    корень проекта. `test_overlay_window.py` сравнивал фактическое размещение с
    `spec.place_over()` (позиция по умолчанию), поэтому на машине, где виджеты
    когда-либо двигали, три теста падали, а на чистой — проходили.

    Найдено 2026-07-30: полный прогон был зелёным, а тот же файл в одиночку
    падал. Разница объяснялась тем, что в полном прогоне DATA_DIR успевал
    подмениться другим тестом — то есть зелёный результат держался на случайном
    порядке. Фикстура делает изоляцию явной и заодно гарантирует, что ни один
    тест не запишет мусор в живую раскладку пользователя."""
    import core.overlay_layout as overlay_layout

    monkeypatch.setattr(
        overlay_layout, "_DIR",
        tmp_path_factory.mktemp("overlay_layout"), raising=False)


@pytest.fixture
def tmp_creds(tmp_path, monkeypatch):
    """Перенаправляет файл креденшелов в tmp и возвращает путь."""
    import config
    path = os.path.join(str(tmp_path), "yandex_creds.json")
    monkeypatch.setattr(config, "YANDEX_CREDS_FILE", path, raising=False)
    return path
