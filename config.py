"""Настройки пользователя. Это единственный файл, который обычно нужно менять."""

import os
import sys

# В PyInstaller onefile ресурсы распаковываются во временную папку _MEIPASS
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# Папка для записи (рядом с EXE в frozen-режиме, корень проекта в dev)
DATA_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)

# --- Офлайн-синтез Piper ---
# Piper распространяется под GPL-3.0-or-later и поэтому НЕ вшивается в наш
# закрытый EXE, а ставится отдельным компонентом установщика рядом с ним и
# запускается как отдельный процесс (см. NOTICE и new_tts/piper_tts.py).
# В дереве разработки бинарника нет — там подхватывается пакет из окружения.
PIPER_HOME = os.path.join(DATA_DIR, "piper")
PIPER_EXE = os.path.join(PIPER_HOME, "piper.exe")
PIPER_VOICES_DIR = os.path.join(PIPER_HOME, "voices")
#: Голоса в дереве разработки (в дистрибутив не входят).
PIPER_VOICES_DEV_DIR = os.path.join(BASE_DIR, "models", "piper")

# --- Телеметрия ---
UDP_IP = "127.0.0.1"
UDP_PORT = 20777

# Порт локального HTTP-API и UI. Живёт здесь, а не в web_server.py, потому что
# нужен и движку (адрес второго экрана для телефона), а импорт web_server в
# core/engine.py замкнул бы граф импортов. web_server его реэкспортирует.
API_PORT = 8765

# --- LLM ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-haiku-4-5-20251001"

# Провайдер «мозга» (генерация текста комментатора). Голос (TTS) от этого НЕ
# зависит — он всегда Yandex SpeechKit (см. engine._start_yandex). "yandex" —
# YandexGPT через yandex_ai/. "gigachat" — Sber GigaChat через gigachat_ai/.
# Дефолт "gigachat": live-проверен 2026-07-25 (free-тариф физлиц, ~0.2–0.5с/фраза,
# рубли/0₽). Откат на YandexGPT — вернуть "yandex". Ключ GigaChat — gigachat_creds.json.
LLM_PROVIDER = "gigachat"                     # "yandex" | "gigachat"

# --- Комментатор ---
PERSONA = "tv"

# Минимальная пауза между фразами (сек). 4.0 давал почти непрерывную болтовню в
# насыщенных гонках (auto-режим находит значимое событие каждые 4-8с) — поднято
# до темпа, ближе к живому радио-комментатору.
MIN_COMMENT_GAP = 9.0

# Семантический дедуп: как долго (сек) не переозвучивать ОДНУ И ТУ ЖЕ ситуацию
# (тот же сосед в той же полосе дистанции). Смена дистанции/цели — озвучиваем сразу.
SITUATION_DEDUP_COOLDOWN = 20.0

# Флэшбек (перемотка игрока): после отката сливаем очередь до-флэшбековых событий,
# сбрасываем транзитное состояние и молчим столько секунд (не комментируем переигровку).
FLASHBACK_SILENCE = 4.0

# Максимум событий в ленте UI
MAX_FEED_ITEMS = 30

# Автономный ИИ-комментатор: АДАПТИВНЫЙ "медленный тик" — ИИ периодически смотрит на
# ситуацию и решает, есть ли что прокомментировать (может молчать). Интервал тика
# зависит от активности гонки: затишье → реже, буря событий → чаще (см. core/engine.py).
AMBIENT_BASE_INTERVAL = 20.0   # обычная активность (1–2 значимых события в окне)
AMBIENT_MIN_INTERVAL = 12.0    # буря событий (≥ AMBIENT_BUSY_EVENTS) — комментируем чаще
AMBIENT_MAX_INTERVAL = 45.0    # затишье (0 событий в окне) — реже беспокоим пилота
AMBIENT_BUSY_EVENTS = 3        # порог «буря»: столько значимых событий в окне → MIN-интервал
ACTIVITY_WINDOW = 60.0         # окно (сек) подсчёта недавних значимых событий
COOLDOWN_AFTER_EVENT = 18.0    # тишина ambient после значимого озвученного события (сек)
LLM_MIN_INTERVAL = 8.0         # "лёгкий" throttle: мин. пауза между ambient-LLM-запросами (сек)
# Сколько последних снимков/событий гонки держим в памяти (скользящее окно).
TIMELINE_SNAPSHOTS = 15
TIMELINE_EVENTS = 15

# Инженер: периодическая сводка по гэпам (Фаза 2, gap-digest design).
# Фиксированный интервал (НЕ адаптивный, в отличие от AMBIENT_*) — рутинная
# осведомлённость не должна подстраиваться под драму гонки.
ENGINEER_DIGEST_INTERVAL_S = 40.0

# Пред-гоночная реплика инженера: задержка после входа в экран стратегии
# (session_type -> "race", до SSTA), чтобы дать игроку осмотреться.
PRE_RACE_PEP_TALK_DELAY_S = 4.0

# --- Comment Planner: важность события управляет порогом/очередью/гэпом/прерыванием ---
# (см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md)
PLAN_BASE_THRESHOLD = 35.0       # порог "говорить" вне спайка (обычное затишье)
PLAN_SPIKE_THRESHOLD = 65.0      # порог сразу после озвученной фразы
PLAN_THRESHOLD_DECAY_S = 45.0    # за сколько секунд спайк линейно спадает к базе
PLAN_STALE_S = 20.0              # старше этого в очереди + importance < PLAN_STALE_IMPORTANCE -> пропуск
PLAN_STALE_IMPORTANCE = 70       # порог важности, ниже которого работает вытеснение по staleness
PLAN_GAP_SKIP_THRESHOLD = 90     # importance >= это -> MIN_COMMENT_GAP игнорируется целиком
PLAN_GAP_HALF_THRESHOLD = 80     # importance в [80, 90) -> гэп режется вдвое
# ВАЖНО: должен совпадать с PLAN_GAP_SKIP_THRESHOLD — иначе критические события
# потеряют гарантию "гэп пропущен И озвучка прервана" одновременно (проверено
# test_gap_skip_and_interrupt_thresholds_share_same_value в tests/test_engine_planner.py).
PLAN_INTERRUPT_THRESHOLD = 90    # importance >= это -> voice.say(priority="critical")

# Commentary Mode (live/calm/story, design spec 2026-07-07): офсет к порогу
# "говорить/молчать" (PLAN_BASE_THRESHOLD/PLAN_SPIKE_THRESHOLD) по режиму.
# ИНВАРИАНТ: PLAN_SPIKE_THRESHOLD + offset должен оставаться < 90 (_CRITICAL_FLOOR
# в commentator/planner.py) для ЛЮБОГО режима — иначе критические события
# (авария/штраф/финиш) потеряют гарантию "всегда проходит порог" в calm/story.
COMMENTARY_MODE_THRESHOLD_OFFSET = {"live": 0, "calm": 20, "story": 20}

# ── Стиль радио (ТЗ §17) ─────────────────────────────────────────────────────
# НЕЗАВИСИМАЯ ось от `commentary_mode`. Их легко перепутать, поэтому разница:
# `commentary_mode` — как рассказывает КОММЕНТАТОР (темп повествования),
# `radio_style` — сколько говорит ИНЖЕНЕР (объём служебного радиообмена).
# Один пилот хочет живой репортаж и молчаливого инженера, другой наоборот.
#
# Настройка НЕ является таймером «говорить раз в N секунд»: она меняет три
# вещи сразу — порог важности некритичных событий, разрешённость аналитических
# реплик и минимальный интервал между ними.
#
# ИНВАРИАНТ: ни один профиль не отключает critical и споттера. Гейты, на
# которые он влияет, к ним не применяются — см. core/engine.py::_muted_by_style.
RADIO_STYLE_PROFILE: dict[str, dict] = {
    # Только безопасность и команды: аналитика молчит, порог поднят.
    "minimal":  {"threshold_offset": 25, "analytics": False, "gap_scale": 1.5},
    # Рекомендуемый режим — сегодняшнее поведение без изменений.
    "standard": {"threshold_offset": 0,  "analytics": True,  "gap_scale": 1.0},
    # Больше сводок и аналитики, короче паузы.
    "verbose":  {"threshold_offset": -15, "analytics": True, "gap_scale": 0.6},
}
RADIO_STYLE_DEFAULT = "standard"

# Аналитические категории инженерского канала — то, что молчит в «Минимуме».
# Здесь НЕТ box_call, damage, penalty, red_flag, safety_car, weather и
# spotter_*: это безопасность и команды, они звучат в любом стиле.
RADIO_ANALYTIC_CATEGORIES = frozenset({
    "gap_digest", "position", "drs", "defense", "battle",
    "secondary_analytics", "ambient", "tyres", "fuel", "ers",
})

# --- Метаданные F1 (Jolpica/Ergast API, как в Fast-F1) ---
# Реальный календарный F1-сезон — управляет и TTL кэша Ergast (core/ergast_client.py:
# "текущий сезон" = свежий кэш 1ч, иначе 30 дней архив), и дефолтным сезоном
# Jolpica-обогащения резервных пилотов (core/f1_metadata.py). НЕ связан с Season Pack/
# game_year напрямую — это просто "какой сейчас год по календарю", бампать раз в год.
F1_SEASON = "2026"

# Дисковый кэш Jolpica (core/ergast_client.py). Имена/команды/национальности
# пилотов кэшируются на диск, чтобы не дёргать API на каждый старт.
ERGAST_CACHE_DIR = os.path.join(DATA_DIR, "ergast_cache")
ERGAST_TTL_DAYS = 30                 # архивные сезоны меняться не будут
ERGAST_TTL_CURRENT_SECONDS = 3600    # текущий сезон обновляем раз в час
ERGAST_MIN_INTERVAL = 2.0            # rate-limit: мин. пауза между запросами (сек)
ERGAST_MAX_RETRIES = 3               # попытки при сетевом сбое / 429 / 5xx
ERGAST_TIMEOUT = 8.0                 # таймаут одного HTTP-запроса (сек)

# --- Yandex Cloud (AI-комментатор) ---
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
YANDEX_GPT_MODEL = "yandexgpt"               # pro: gpt://<folder>/yandexgpt/latest
YANDEX_TTS_SAMPLE_RATE = 48000               # LPCM 48 kHz mono
YANDEX_GPT_CONNECT_TIMEOUT = 2.0
YANDEX_GPT_TOTAL_TIMEOUT = 6.0
YANDEX_TTS_CONNECT_TIMEOUT = 2.0
YANDEX_TTS_TOTAL_TIMEOUT = 5.0
YANDEX_CREDS_FILE = os.path.join(DATA_DIR, "yandex_creds.json")
YANDEX_PREWARM = False                        # прогрев кэша Yandex на старте (платно, опц.)
YANDEX_TTS_V3_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
YANDEX_TTS_V3_CONNECT_TIMEOUT = 4.0   # v3 streams; needs more connect headroom than v1
YANDEX_TTS_V3_TOTAL_TIMEOUT = 14.0   # v3 NDJSON stream can take 10+ s for long phrases
YANDEX_TTS_GRPC_ENDPOINT = "tts.api.cloud.yandex.net:443"
YANDEX_TTS_GRPC_TIMEOUT = 10.0   # секунд, тот же порядок что YANDEX_TTS_V3_TOTAL_TIMEOUT
YANDEX_TTS_STREAMING_PLAYBACK = True   # kill-switch: Этап B (потоковое воспроизведение v3-grpc)

# --- Yandex IAM (auth_mode="iam" — OAuth-токен, авто-обмен на короткоживущий IAM) ---
YANDEX_IAM_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
YANDEX_IAM_CONNECT_TIMEOUT = 2.0
YANDEX_IAM_TOTAL_TIMEOUT = 6.0
# Консервативный TTL кэша IAM-токена. Реальный expiresAt от Yandex — ISO8601 с
# 9-значной дробной частью секунд, которую stdlib datetime.fromisoformat не
# парсит (максимум 6 знаков) — вместо парсинга берём фиксированный интервал
# заметно короче реального ~12ч времени жизни токена.
YANDEX_IAM_REFRESH_INTERVAL_SEC = 3600.0

# --- Yandex health-monitor («мягкая проверка» ключа, см. core/engine.py) ---
# Статус Yandex считается упавшим только после N неудачных проб ПОДРЯД —
# одиночные сетевые блипы не дёргают статус назад-вперёд (фикс «моргания»).
YANDEX_HEALTH_FAIL_THRESHOLD = 3
YANDEX_HEALTH_TIMEOUT = 2.5                   # таймаут одной пробы (≥2.0 c по ТЗ)
YANDEX_HEALTH_INTERVAL_OK = 30.0             # интервал проб, пока Yandex здоров
YANDEX_HEALTH_INTERVAL_DOWN = 8.0           # интервал проб, пока Yandex упал (быстрое восстановление)

# --- Voice Q&A (push-to-talk) ---
YANDEX_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
YANDEX_STT_CONNECT_TIMEOUT = 2.0
YANDEX_STT_TOTAL_TIMEOUT = 5.0
VOICE_QUESTION_MAX_SEC = 5.0    # максимальная длина записи вопроса push-to-talk
MIC_TEST_SEC = 2.0              # длина тестовой записи микрофона (Settings → Voice)

# --- OpenF1 (секторные эталоны реальных гонок, Real-F1 Benchmark — секторы) ---
OPENF1_CACHE_DIR = os.path.join(DATA_DIR, "openf1_cache")
OPENF1_TTL_DAYS = 3650          # практически бессрочно — завершённая гонка не меняется
OPENF1_MIN_INTERVAL = 2.0
OPENF1_MAX_RETRIES = 3
OPENF1_TIMEOUT = 8.0

# --- Sber GigaChat (альтернативный «мозг», активен при LLM_PROVIDER="gigachat") ---
# Работает через официальный SDK `gigachat` (ai-forever/gigachat): он сам делает
# OAuth (Authorization key -> access token на 30 мин, авто-рефреш) и берёт на себя
# TLS-сертификат Минцифры. Голос при этом остаётся Yandex SpeechKit.
GIGACHAT_MODEL = "GigaChat"                   # Lite (бесплатный тариф физлиц). Ещё: "GigaChat-Pro", "GigaChat-Max"
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"          # физлица (free). Юрлица: GIGACHAT_API_B2B / _CORP
GIGACHAT_TIMEOUT = 6.0                        # таймаут одного запроса (сек), тот же порядок что YandexGPT
# verify_ssl_certs: False — SDK не проверяет цепочку Минцифры (работает везде, но
# менее строго). Для продакшена — поставить True и подложить корневые сертификаты
# Минцифры (см. developers.sber.ru, "Сертификаты НУЦ Минцифры").
GIGACHAT_VERIFY_SSL = False
# Продакшен: путь к PEM-бандлу корневых сертификатов НУЦ Минцифры (Russian Trusted
# Root CA + Sub CA). Если файл есть — provider включает строгую проверку TLS
# (verify_ssl_certs=True + ca_bundle_file), игнорируя GIGACHAT_VERIFY_SSL. Нет —
# dev-режим. Собрать бандл: `python scripts/setup_gigachat_certs.py` (кладёт его
# ровно сюда). Подхват автоматический по факту существования файла.
_GIGACHAT_CA_DEFAULT = os.path.join(DATA_DIR, "certs", "gigachat_ca_bundle.pem")
GIGACHAT_CA_BUNDLE = _GIGACHAT_CA_DEFAULT if os.path.exists(_GIGACHAT_CA_DEFAULT) else ""
GIGACHAT_CREDS_FILE = os.path.join(DATA_DIR, "gigachat_creds.json")
