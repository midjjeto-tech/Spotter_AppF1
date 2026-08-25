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

# Версия приложения — ЕДИНСТВЕННЫЙ источник правды. Уезжает в лог при старте, в
# /api/diagnostics (поддержке нужно знать, какая сборка у пользователя) и
# сверяется с AppVersion в installer/SpotterApp.iss гейтом build.ps1: Inno Setup
# питоновский модуль прочитать не может, а разошедшиеся версии — это когда
# пользователь называет одну, а в логе стоит другая.
APP_VERSION = "0.2.0-rc.1"

# --- Телеметрия ---
UDP_IP = "127.0.0.1"
UDP_PORT = 20777

# Порт локального HTTP-API и UI. Живёт здесь, а не в web_server.py, потому что
# нужен и движку (адрес второго экрана для телефона), а импорт web_server в
# core/engine.py замкнул бы граф импортов. web_server его реэкспортирует.
API_PORT = 8765

# --- LLM ---
# ANTHROPIC_API_KEY и LLM_MODEL убраны 2026-08-09: Anthropic заменён на
# YandexGPT ещё в июне, SDK выкинут из зависимостей, и обе константы с тех пор
# никем не читались — но выглядели как действующая настройка провайдера.

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

# То же для споттера, но ключ другой: «та же машина с той же стороны»
# (core/radio/situations.py -> spotter:{side}:vehicle_{idx}). Сосед, который
# висит рядом и колеблется на границе порога, не переобъявляется столько
# секунд; ДРУГОЙ сосед объявляется сразу, без ожидания. Разбор живого заезда
# 2026-08-11 дал 32 боковых предупреждения за 5 минут квалификации.
# Снятие предупреждения (SPOTTER_CLEAR) под этот кулдаун НЕ попадает:
# промолчать про то, что рядом снова чисто, хуже, чем повториться.
SPOTTER_SITUATION_COOLDOWN = 8.0

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

# --- Метаданные F1 ---
# Реальный календарный F1-сезон: дефолтный год ростера в core/f1_metadata.py,
# когда игра ещё не сообщила свой (game_year). НЕ связан с Season Pack напрямую —
# это просто "какой сейчас год по календарю", бампать раз в год.
#
# Сетевых источников за этой константой больше нет: Jolpica/Ergast удалены
# 2026-08-08 вместе с кэшем и TTL (некоммерческая лицензия, см. NOTICE).
# Оставшиеся на диске папки ergast_cache/ и openf1_cache/ можно удалить руками —
# приложение в них больше не заглядывает.
F1_SEASON = "2026"
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
# 4.0, а не 5.0: это ВТОРАЯ попытка озвучить ту же реплику, и она складывается с
# уже потраченным таймаутом v3. Реплика, доехавшая через 20 секунд, описывает
# другую гонку — молчание дешевле.
YANDEX_TTS_TOTAL_TIMEOUT = 4.0
YANDEX_CREDS_FILE = os.path.join(DATA_DIR, "yandex_creds.json")
YANDEX_PREWARM = False                        # прогрев кэша Yandex на старте (платно, опц.)
YANDEX_TTS_V3_URL = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
YANDEX_TTS_V3_CONNECT_TIMEOUT = 4.0   # v3 streams; needs more connect headroom than v1
# 9.0, а не 14.0. Прежнее значение подбиралось под САМУЮ длинную реплику
# комментатора, но платит его каждая: на живой гонке 13 фраз подряд ушли в
# `future timeout (15s)`, и к моменту звука ситуация уже менялась. Длинную фразу
# при неудаче подхватывает откат на v1 — цена ошибки здесь заметно ниже цены
# ожидания.
YANDEX_TTS_V3_TOTAL_TIMEOUT = 9.0
# Предохранитель на v3. Даже укороченный таймаут остаётся дорогим, а платить его
# КАЖДОЙ фразой, когда v3 уже явно лежит, бессмысленно: после трёх подряд
# неудач сессия переходит на v1 целиком и не трогает v3 до конца остывания.
# Побочный и не менее важный эффект — стабильность тембра: пофразный откат
# заставлял одного и того же персонажа звучать то премиальным голосом, то
# легаси-подменой (см. _V1_VOICE_FALLBACK).
YANDEX_TTS_V3_FAILURE_THRESHOLD = 3
YANDEX_TTS_V3_BREAKER_COOLDOWN = 120.0   # секунд
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

# OpenF1 удалён 2026-08-08 вместе с его кэшем и лимитами: лицензия
# CC BY-NC-SA 4.0 несовместима с продаваемой сборкой (см. NOTICE). Секторный
# эталон теперь приходит из session history самой игры — core/f1_benchmark.py.
OPENF1_TIMEOUT = 8.0

# --- Sber GigaChat (альтернативный «мозг», активен при LLM_PROVIDER="gigachat") ---
# Работает через официальный SDK `gigachat` (ai-forever/gigachat): он сам делает
# OAuth (Authorization key -> access token на 30 мин, авто-рефреш) и берёт на себя
# TLS-сертификат Минцифры. Голос при этом остаётся Yandex SpeechKit.
GIGACHAT_MODEL = "GigaChat"                   # Lite (бесплатный тариф физлиц). Ещё: "GigaChat-Pro", "GigaChat-Max"
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"          # физлица (free). Юрлица: GIGACHAT_API_B2B / _CORP
GIGACHAT_TIMEOUT = 6.0                        # таймаут одного запроса (сек), тот же порядок что YandexGPT
# Предохранитель и ретрай — по образцу YANDEX_TTS_V3_* (см. yandex_ai/speech.py).
# Разбор живого заезда 2026-08-11: за гонку 31 отвал по таймауту, 6 ответов 429 и
# 3 rate-limit, и КАЖДЫЙ стоил полного GIGACHAT_TIMEOUT, потому что ретраев и
# предохранителя не было вовсе — комментатор просто молчал по шесть секунд
# подряд, снова и снова.
#
# Ретрай ровно ОДИН и только на 429: сервер прямо говорит «слишком часто», и
# короткая пауза его чинит. На таймаут ретрая нет намеренно — это ровно тот
# размен, который уже сделан для голоса: реплика, доехавшая через 12 секунд,
# описывает другую гонку, и молчание дешевле.
GIGACHAT_RETRY_ON_RATE_LIMIT = 1
GIGACHAT_RETRY_BACKOFF = 1.5                  # секунд перед единственным ретраем
# После скольких неудач подряд перестаём звонить вовсе и на сколько. Это и есть
# главная экономия: платить таймаут каждой фразой, когда провайдер явно лежит,
# бессмысленно — шаблоны отвечают мгновенно.
GIGACHAT_FAILURE_THRESHOLD = 3
GIGACHAT_BREAKER_COOLDOWN = 90.0              # секунд
# PEM-бандл корневых сертификатов НУЦ Минцифры (Russian Trusted Root CA + Sub
# CA) плюс публичные корни certifi. Если файл есть, provider передаёт его SDK
# явно; если нет — остаётся строгая проверка через системное хранилище, и
# небезопасного verify=False в приложении по-прежнему нет.
#
# «Необязательный» здесь означает только «код не падает без него». Работать без
# него GigaChat НЕ БУДЕТ: 2026-08-25 рукопожатие с ngw.devices.sberbank.ru и
# gigachat.devices.sberbank.ru через `ssl.create_default_context()` вернуло
# `self-signed certificate in certificate chain`, а с бандлом — Russian Trusted
# Sub CA. Та же ошибка держала провайдера мёртвым весь заезд 08-19.
# Собрать: `python scripts/setup_gigachat_certs.py`.
#
# Ищем в ДВУХ местах, и порядок важен:
#   1. DATA_DIR — бандл, собранный скриптом рядом с приложением. Идёт первым,
#      чтобы пользователь мог подложить свой, не пересобирая EXE.
#   2. BASE_DIR — бандл, вшитый в дистрибутив (в onefile это _MEIPASS, который
#      с DATA_DIR НЕ совпадает). Без этой ветки вшитый в EXE сертификат просто
#      не находился бы, и релизная сборка молча работала бы без проверки TLS.
# dict.fromkeys — дедуп с сохранением порядка: в дереве разработки DATA_DIR и
# BASE_DIR совпадают, и без него диагностика печатала бы один и тот же путь дважды.
_GIGACHAT_CA_CANDIDATES = tuple(dict.fromkeys((
    os.path.join(DATA_DIR, "certs", "gigachat_ca_bundle.pem"),
    os.path.join(BASE_DIR, "certs", "gigachat_ca_bundle.pem"),
)))
GIGACHAT_CA_BUNDLE = next(
    (p for p in _GIGACHAT_CA_CANDIDATES if os.path.exists(p)), "")
GIGACHAT_CREDS_FILE = os.path.join(DATA_DIR, "gigachat_creds.json")
