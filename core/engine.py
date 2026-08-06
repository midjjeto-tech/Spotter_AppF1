"""
core/engine.py
================
Главный контроллер. Запускает два фоновых потока:

1. telemetry_thread — принимает UDP, обновляет RaceState, кладёт
   релевантные события в очередь
2. commentary_thread — берёт события из очереди, решает фразу (Commentator),
   озвучивает (Voice), обновляет shared-состояние для UI

Внешний код (UI) получает изолированные снимки через UIStateProjection.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from core.telemetry import Telemetry
from core.iracing_telemetry import IRacingTelemetry
from core.telemetry_adapters import (
    ConnectionChanged,
    F1TelemetryAdapter,
    IRacingTelemetryAdapter,
    SourceStatus,
    TelemetryDelta,
    TelemetryRaceEvent,
)
from core import diagnostics
from core import reality_mod_bridge
from core.race_state import RaceState
from core.packets import TRACK_LIMITS_INFRINGEMENT_TYPES
from commentator.brain import Commentator
from commentator.ai_provider import AIProvider
from commentator.timeline import RaceTimeline
from commentator import story as _story
from commentator import pre_race_pep_talk as _pep_talk
from commentator.planner import PlanContext, score_importance, build_plan
from yandex_ai import credentials as yc
from yandex_ai.client import YandexClient
from yandex_ai.speech import YandexSpeech
from core.f1_metadata import F1Metadata
from voice.tts import Voice
from voice.listener import VoiceListener, play_back
from yandex_ai.stt import YandexSTT
from commentator import radio_answer as _radio_answer
from core.session_recorder import SessionRecorder
from analytics.loader import TRACK_ID_TO_GP
from analytics import archive as _archive
from core.race_ai.analyzer import RaceAnalyzer
from core.strategy_ai.agreement import StrategyAgreement
from core.strategy_ai.module import StrategyModule, StrategySnapshot
from core.strategy_ai.sector_comparison import compare_best_sectors
from core.strategy_ai import teammate as _teammate
from core.strategy_ai import drs_advisory as _drs

_DRS_EVENT_CODE: dict[str, str] = {
    _drs.CODE_IN_RANGE: "DRS_PROXIMITY_ENTER",
    _drs.CODE_OUT_OF_RANGE: "DRS_PROXIMITY_EXIT",
    _drs.CODE_ENABLED: "DRS_ALLOWED_ON",
    _drs.CODE_DISABLED: "DRS_ALLOWED_OFF",
    _drs.CODE_IN_RANGE_AND_ENABLED: "DRS_PROXIMITY_ENTER_AND_ALLOWED",
}
from core.strategy_ai import spotter as _spotter
from core.strategy_ai.spotter import LONGITUDINAL_WINDOW_M

# Семантический код банка фраз -> event_code игры. Одно направление: трекер
# больше не знает про event_code, движок больше не разбирает готовый текст.
# Сколько ситуаций держим в реестре вытеснения. Нужна только последняя по
# каждой, но за гонку их накапливается много.
_RADIO_SITUATION_LIMIT = 256

# «Говори чаще»: на сколько секунд укорачивать минимальную паузу за одну
# команду и ниже какого значения не опускаться. Пол не даёт пилоту довести
# инженера до непрерывной болтовни — MIN_COMMENT_GAP существует именно
# против неё (см. gotcha про каданс и бэклог в CONTEXT.md).
_TALK_MORE_GAP_STEP = 3.0
_TALK_MORE_GAP_FLOOR = 4.0

# Тема вопроса пилота -> код события ответа. Отсутствие темы в этой карте
# означает «справочный ответ»: он уходит под USER_Q и живёт без TTL. Перечислены
# только ДЕЙСТВЕННЫЕ темы — те, где устаревший ответ вреден, а не просто
# запоздал. От кода зависят категория, TTL и guard'ы (core/radio/policy.py).
_PTT_ANSWER_EVENT_CODE: dict[str, str] = {
    "should_pit": "USER_Q_PIT",
    "pit_window": "USER_Q_PIT",
    # Стратегия отвечает «остаёмся / идём в боксы» — это тоже про заезд.
    "strategy": "USER_Q_PIT",
    "gap": "USER_Q_GAP",
    "gap_ahead": "USER_Q_GAP",
    "gap_behind": "USER_Q_GAP",
    "rival": "USER_Q_GAP",
    "safety_car": "USER_Q_SAFETY_CAR",
}

# Семантический код позиции -> event_code. Отдельная карта, а не разбор текста
# (см. комментарий на месте использования).
_POSITION_EVENT_CODE: dict[str, str] = {
    "position.current": "POSITION_CALL",
    "position.after_pit": "POSITION_CALL_OWN_PIT",
}

_SPOTTER_EVENT_CODE: dict[str, str] = {
    _spotter.CODE_LEFT: "SPOTTER_CAR_LEFT",
    _spotter.CODE_RIGHT: "SPOTTER_CAR_RIGHT",
    _spotter.CODE_BOTH: "SPOTTER_CAR_BOTH",
    _spotter.CODE_CLEAR: "SPOTTER_CLEAR",
}
RADAR_WINDOW_M = 25.0  # шире голосового LONGITUDINAL_WINDOW_M — только для HUD-радара
from core.strategy_ai.safety_car import derive_safety_car_event
from core.coach_ai import DriverCoach
from core.rivals import RivalTracker
from core.rivals.intel import RivalIntelTracker
from core.broadcast.director import BroadcastDirector
from core.broadcast.context import BroadcastContext
from core.racefeed.engine import RaceFeedEngine
from core.track_ai.loader import load_track
from core.track_ai.track_manager import TrackManager
from core.session_guard import SessionGuard
from core.num_to_words import ru_plural
from core.situation_dedup import (
    EngineerTopicDedup, SituationDedup, gap_band as situation_gap_band)
from core.commentary_events import CommentaryEvents
from core.commentary_runtime import CommentaryRuntime
from core.radio.message import (
    STATE_COMPLETED, STATE_PLAYING, STATE_SYNTHESIZING, RadioCancelReason,
    RadioMessage, build_message as build_radio_message,
)
from core.radio import resolver as radio_resolver
from core.radio.session import RadioSession
from core.radio.plumbing import attach as radio_plumbing
from core.radio.voice_cast import SLOT_ENGINEER
from core.radio import voice_cast


def _strip_tokens(text: str) -> str:
    """Убрать нераскрытые `{токены}` из текста для показа.

    Пилот не должен читать фигурные скобки, даже если значения не нашлось."""
    import re as _re
    return " ".join(_re.sub(r"\{[^{}]*\}", "", text).split())
from core.radio import address as radio_address
from core.radio import phrases as radio_phrases
from core.radio import policy as radio_policy
from core.radio import variety as radio_variety
from core.radio.phrases import PhraseError
from core.radio.situations import dedupe_key as situation_dedupe_key
from core.race_engineer import RaceEngineer
from core.race_story import RaceStoryCollector
from core.f1_benchmark import F1Benchmark
from core.career_memory import CareerMemory
from core.lap_comparison import LapComparisonProgress
from core.ui_state import OverlayTelemetry, UIStateProjection, initial_ui_state
import core.career_stats as career_stats_mod
import core.season as season_mod
import core.milestones as milestones_mod
import core.driver_of_the_day as driver_of_the_day_mod
import core.post_race_interview as post_race_interview_mod
import core.race_recap as race_recap_mod
import core.weekend_duel as weekend_duel_mod
import core.screenshot as screenshot_mod
import core.overlay_window as overlay_window
import core.pre_race_pep_talk as _pep_talk_facts
from core.entity_resolver import resolve_driver_name, resolve_opponent_name
from core.ru_names import first_name_of
from commentator.channel_router import route_event, CHANNEL_RADIO, CHANNEL_OVERLAY
from commentator.radio import get_radio_line
# pick_phrase больше не нужен: последним его потребителем в движке были пулы
# повреждений, они переехали в core/radio/phrases.py. reset_phrase_cycles
# остаётся — им движок тасует колоды комментатора на старте новой гонки.
from commentator.phrase_pool import reset_phrase_cycles

import logging

import config

_log = logging.getLogger(__name__)

# Temporary field diagnostics. Enable with SPOTTER_DIAG=1 to dump the UDP packet
# format/game year once, to confirm F1 25 vs a newer layout when names look wrong.
_DIAG = os.environ.get("SPOTTER_DIAG") == "1"

# Маркер event["speaker"] = SPEAKER_ENGINEER помечает реплики инженерских
# трекеров. ГОЛОС по нему больше не выбирается — это делает канал сообщения
# (core/radio/policy.py::channel_for -> RadioMessage.voice_persona), потому что
# споттер публикуется с тем же маркером и отдельного голоса иначе не получал.
# Маркер остаётся: policy.channel_for() использует его как страховку для кодов,
# забытых в _ENGINEER_CODES.
SPEAKER_ENGINEER = "engineer"

# Повреждения кузова: порог "заметности" (%) для голосовой реплики — ниже не
# считаем поводом объявлять (мелкие царапины — постоянный шум телеметрии).
_DAMAGE_NOTICEABLE_THRESHOLD = 20
# Hero events that get an in-game screenshot attached to their RaceFeed post.
_HERO_SCREENSHOT_CODES = frozenset({
    "OVTK", "COLL", "PENA", "RTMT", "FTLP", "CHAMPIONSHIP",
    "POST_RACE_INTERVIEW",
})
# 5 вариантов на категорию (было по одной фиксированной фразе — item 6
# бэклога, docs/superpowers/plans/2026-07-20-defense-event-damage-phrase-
# variety.md). Выбор в _update_damage() идёт через общий shuffle-bag: все
# варианты категории прозвучат до первого повтора.
# Формулировки повреждений живут в банке (core/radio/phrases.py). Здесь — только
# выбор спеки: критическая поломка требует другой реплики, чем «есть
# повреждение, темп упадёт», и порог этого решения принадлежит policy.
_DAMAGE_CRITICAL_CODES: dict[str, str] = {
    "wing": "damage.wing_critical",
    "engine": "damage.engine_critical",
}


def _damage_phrase_code(category: str, severity: float) -> str:
    """Семантический код формулировки повреждения по детали и тяжести.

    Критическая спека есть не у каждой детали: разбитое крыло и умирающий мотор
    требуют немедленного бокса, а повреждение днища или коробки — нет, там
    «теряем прижим» остаётся верным на любой тяжести."""
    if severity >= radio_policy.CRITICAL_DAMAGE_SEVERITY:
        critical = _DAMAGE_CRITICAL_CODES.get(category)
        if critical is not None:
            return critical
    return f"damage.{category}"

# Voice Q&A команды (docs/superpowers/plans/2026-07-19-voice-qa-expansion.md)
# — тот же порядок цикла персон, что core/hotkeys.py::_PERSONAS (4-элементный
# литерал, не стоит межмодульного рефакторинга ради одного дубля).
_VOICE_COMMAND_PERSONAS = ["tv", "hype", "calm", "toxic"]
# Подписи персон КОММЕНТАТОРА для голосовой команды «смени персону».
# "calm" здесь раньше значилось как «инженера» — пережиток модели, где инженер
# и был персоной calm. Теперь инженер выбирается отдельно
# (settings["engineer_character"], core/radio/voice_cast.py), и эта команда его
# не трогает вовсе: она меняет только характер комментатора. Прежняя подпись
# вслух обещала пилоту не то, что происходит.
_VOICE_COMMAND_PERSONA_LABEL = {
    "tv": "телекомментатора", "hype": "хайп-фаната",
    "calm": "спокойного аналитика", "toxic": "токсика",
}


class F1Engine:
    def __init__(self, settings: dict | None = None):
        self._engine_lock = threading.RLock()
        self.settings = settings or {}
        # Источник выбирается один раз; source-specific transport и decoding
        # скрыты за deep telemetry adapter.
        self._telemetry_source = self.settings.get("telemetry_source", "f1")
        self.race_state = RaceState()
        self.metadata = F1Metadata(config.F1_SEASON)
        self.voice = Voice()
        # Состояние «инженер говорит» приходит из РЕАЛЬНОГО старта звука, а не из
        # момента постановки в очередь: say() возвращается мгновенно, и старый
        # паттерн держал флаг поднятым микросекунды (дефект, найденный в Task 1).
        self.voice.set_playback_observer(self._on_playback_event)
        # Персона из СОХРАНЁННЫХ настроек, а не из config: apply_settings при
        # старте не вызывается ни разу (см. core/runtime.py), поэтому иначе
        # выбор пользователя доезжал бы до озвучки только после первой правки
        # в UI. Для каста это не косметика: voice_cast.resolve() считает
        # занятым голос ПЕРСОНЫ, и рассинхрон между реально звучащим
        # комментатором и тем, кого считает каст, отдаёт инженеру голос
        # комментатора.
        self.voice.set_persona(self.settings.get("persona", config.PERSONA))
        self._apply_voice_cast()
        self._voice_listener = VoiceListener(device=self.settings.get("mic_device"))
        self._yandex_client: YandexClient | None = None
        self._yandex_status = {"connected": False, "code": "YANDEX_NO_CREDENTIALS",
                               "message": "Ключ не задан"}
        # Статус GigaChat-«мозга» (BYOK: пользователь вводит свой Authorization key).
        self._gigachat_status = {"connected": False, "code": "GIGACHAT_NO_CREDENTIALS",
                                 "message": "Ключ не задан"}
        # Health-monitor: _yandex_healthy — единый флаг «Yandex доступен» (роутинг TTS/GPT),
        # _yandex_fail_streak — счётчик неудач подряд для «мягкой проверки» статуса.
        self._yandex_healthy = False
        self._yandex_fail_streak = 0
        self._stt: YandexSTT | None = None
        # Credentials are cheap to read, but starting the async client is a
        # runtime side effect and therefore deferred to start().
        self._initial_yandex_creds = yc.load()
        self.ai = self._make_ai_provider()
        self.commentator = Commentator(self.ai, config.PERSONA)
        self.commentator.set_broadcast_director(BroadcastDirector(BroadcastContext()))

        self._commentary_events = CommentaryEvents(
            context_provider=lambda event: self._plan_context(dict(event)),
            race_feed_provider=lambda: self._race_feed,
            player_team_provider=self._racefeed_player_team,
            player_name_provider=self._player_driver_name,
            media_hook=self._capture_hero_screenshot,
            scorer=lambda event, context: score_importance(event, context),
        )
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_threads: list[threading.Thread] = []
        self._task_threads: list[threading.Thread] = []
        self._telemetry_instance = None
        self._started = False
        self._stopped = False
        self._player_car_index = 255
        self._session_type: str = "unknown"
        # True между SSTA и следующим CHQF/SEND — в отличие от "connected"
        # (жив ли UDP-сокет) и "_session_type" (не сбрасывается на SEND),
        # отражает именно "гонка/сессия сейчас реально идёт". См. _ambient_loop
        # и _maybe_emit_gap_digest — иначе они продолжают штамповать реплики
        # на устаревшей телеметрии, пока игра шлёт пакеты из меню/результатов.
        self._session_active: bool = False
        self._session_guard = SessionGuard()
        self._telemetry_connected = False
        # Доступность самого источника, отдельно от «идут ли пакеты».
        # "pending" — поток телеметрии ещё не сообщил ничего (старт приложения).
        self._telemetry_source_status: dict = {"code": "pending", "detail": ""}
        self._telemetry_last_packet_at: float = 0.0
        self._leader_idx: int | None = None
        self._positions: dict[int, int] = {}
        self._current_grid: list[dict] = []
        # car_idx -> визуальный состав резины ("S"/"M"/"H"/"I"/"W"). Пакет
        # Car Status приходит по всем машинам, но не каждый тик — храним
        # последнее известное, как _lap_distances/_current_grid.
        self._grid_tyre_compounds: dict[int, str] = {}
        self._radar: list[dict] = []
        self._safety_car_status: int = 0
        self.recorder = SessionRecorder()
        # Скользящее окно памяти гонки для автономного ИИ-аналитика.
        self.timeline = RaceTimeline(config.TIMELINE_SNAPSHOTS, config.TIMELINE_EVENTS)
        self._track_id: int = -1
        self._rain_forecast: dict | None = None
        self._current_weather: dict | None = None
        self._rain_seen_this_race: bool = False
        self._track_city: str | None = None
        self._track_manager: TrackManager | None = None
        self._lap_distance_m: float | None = None
        self._game_year: int = 0
        self._prev_lap: int = 0
        # Пит-стоп: накопление ИЛИ по тикам одного круга (см. design spec §2 —
        # 'pit_status' живой на момент тика, но круг мог включать заезд в боксы
        # ЗАДОЛГО до пересечения финишной черты, когда pit_status уже снова 0).
        self._current_lap_pit: bool = False
        self._last_completed_lap_was_pit: bool = False
        self._session_events: list[str] = []
        # Сырые числовые трекеры игрока для снимков таймлайна (формат UI — отдельно).
        self._player_pos: int | None = None
        self._player_lap: int | None = None
        self._player_pace_ms: int | None = None
        self._player_fuel = None
        self._leader_name: str | None = None
        self._last_snap_t: float = 0.0
        # Отрывы (мс) и состояние шин игрока для timeline.
        self._player_gap_leader: int | None = None
        self._player_gap_front: int | None = None
        self._player_gap_behind: int | None = None
        self._player_pit_status: int | None = None
        self._player_tyre_compound: str | None = None
        self._player_tyre_age: int | None = None
        self._player_tyre_wear: float | None = None
        self._player_ers_percent: float | None = None
        self._player_ers_deploy_mode: int | None = None
        # Voice Q&A "штрафы" (docs/superpowers/plans/2026-07-19-voice-qa-expansion.md)
        # — накопительно за сессию, инкремент в player-PENA ветке ниже.
        self._player_penalty_count: int = 0
        self._player_penalty_seconds: int = 0
        # Tyre Sets (packet 12) + Final Classification (packet 8) — см. docs/
        # superpowers/plans/2026-07-19-tyre-sets-final-classification.md.
        self._player_tyre_sets_available: dict[str, int] | None = None
        self._player_tyre_sets_fitted: dict | None = None
        self._final_classification: dict | None = None
        self._final_classification_grid: list[dict] = []
        self._reality_result_sent: bool = False
        self._player_damage: dict | None = None
        # Session History (packet 11) — ПОЦИКЛОВОЙ, кэш по car_idx, ВКЛЮЧАЯ
        # игрока (в отличие от Tyre Sets — нужны данные соперников). См.
        # docs/superpowers/plans/2026-07-20-session-history-sector-comparison.md.
        self._session_history: dict[int, dict] = {}
        self._player_drs_active: bool = False
        self._player_speed_kmh: float | None = None
        # Extra per-frame fields the in-game HUD widgets render (pedals, steering,
        # RPM/rev lights, ERS flow, PU power split, DRS zone distance, track
        # limits). Kept as one dict rather than a dozen more _player_* attributes:
        # nothing but the HUD reads them, and they travel to the overlay as a
        # block. Last-known-value, like _lap_distances/_current_grid.
        self._player_hud: dict = {}

        # Повреждения кузова: анти-спам "уже объявляли" по категории за сессию
        # (сбрасывается ниже порога — деталь починили в боксах, следующая поломка
        # снова объявится). См. design spec §5.
        self._damage_announced: dict[str, bool] = {
            "wing": False, "floor": False, "gearbox": False, "engine": False,
        }

        # Race Situation Intelligence Layer
        self.race_analyzer = RaceAnalyzer()
        self._last_race_ai_event_t: float = 0.0

        # Семантический дедуп ситуаций (анти-спам погони/борьбы) + флэшбек-тишина.
        self._situation_dedup = SituationDedup(config.SITUATION_DEDUP_COOLDOWN)
        # Дедуп реплик ИНЖЕНЕРА по теме новости. Отдельный от предыдущего:
        # тот дедупит поток комментатора по кодам игры, этот — свои коды
        # инженера, которые приходят от девяти независимых трекеров.
        self._engineer_topic_dedup = EngineerTopicDedup(
            config.SITUATION_DEDUP_COOLDOWN)
        self._flashback_until: float = 0.0

        # Post-Race Story Mode
        self.story_collector = RaceStoryCollector()
        self._story_fired = False

        # Итог заезда голосом инженера (`session.result`). Сбрасывается на SSTA,
        # как _story_fired: это ритуал ОДНОГО заезда, а повторный CHQF по тому
        # же заезду вторым итогом быть не должен.
        self._session_result_fired = False

        # Pre-race pep talk (инженер, экран стратегии — см. design spec
        # 2026-07-17-pre-race-pep-talk-design.md). Сбрасывается НЕ на SSTA
        # (в отличие от _story_fired), а в самом блоке перехода session_type,
        # когда игрок уходит из "race" — см. _update_telemetry.
        self._pre_race_pep_talk_fired = False

        # Real-F1 Benchmark (live)
        self.f1_benchmark = F1Benchmark()
        self._f1_comparison_progress = LapComparisonProgress()
        self._f1_context_line: str | None = None

        # Career Memory (личная история игрока по трассе, независимо от реального F1)
        self.career_memory = CareerMemory()
        self._career_comparison_progress = LapComparisonProgress()
        self._career_context_line: str | None = None

        # Career Stats (кросс-трековый агрегат: всего гонок/побед/подиумов/средняя
        # позиция) — НЕ путать с career_memory выше, которая привязана к трассе.
        self._career_stats_context_line: str | None = None

        # True если в ЭТОЙ гонке уже был побит личный рекорд (круг или сектор) —
        # используется _publish_career_recap() (Task 2) как один из сигналов
        # "improvement" для важности карьерного recap-поста на финише.
        self._career_pb_this_race: bool = False
        # Guards CHAMPIONSHIP capture/publish to once per race (reset at SSTA) —
        # the Final Classification packet can arrive more than once.
        self._championship_recorded: bool = False
        self._race_overtakes_by_driver: dict[int, int] = {}
        # Номер текущей фазы Safety Car в этой сессии. Инкремент только на
        # деплое; три SC-кода одной фазы делят номер и потому образуют одну
        # ситуацию (core/radio/situations.py). Сброс — на SSTA.
        self._sc_episode: int = 0
        # Стабильная идентичность заезда для радио-ситуаций. Локальные счётчики
        # трекеров (`front_id`, `window_id`, `sc_episode`) нумеруют ситуации
        # внутри заезда; без сессионного префикса первая ситуация новой гонки
        # столкнулась бы с первой ситуацией прошлой. Своя, а не из RaceFeed:
        # тот выключен по умолчанию, а радио работает всегда.
        self._radio_session_id: str = self._new_radio_session_id()
        # Состояния радио-сообщений по id. Пока это диагностический журнал и seam
        # для Task 5 (история радио в UI); ограничен по размеру, чтобы за длинную
        # гонку не расти без предела.
        # Владелец активной передачи, истории и «последнего завершённого»
        # инженерского сообщения (то, что повторяет команда «повтори»).
        self.radio_session = RadioSession()
        self._radio_lifecycle: dict[str, RadioMessage] = {}
        self._radio_lifecycle_lock = threading.Lock()
        # Самое новое сообщение по каждой ситуации. Нужно для вытеснения: tier 2
        # box-call делает ожидающий tier 1 неактуальным, а свежая сводка —
        # предыдущую. Без этого старый tier мог прозвучать ПОСЛЕ нового.
        self._radio_newest: dict[str, str] = {}
        # Номер ветки таймлайна. Растёт на каждом флэшбеке и входит только в
        # `dedupe_key`, не в `situation_id`: физическая ситуация после перемотки
        # осталась той же, а высказывание о ней пилот не слышал.
        self._timeline_revision: int = 0

        # Strategy AI — one deep module owns decisions, cooldown and calls.
        self._strategy_module = StrategyModule()
        self._race_engineer = RaceEngineer()
        self._player_drs_allowed: bool | None = None
        self._race_feed: RaceFeedEngine | None = None
        # Ставится AppRuntime после старта GlobalHotkeyManager (см.
        # set_hotkey_status_provider) — движок хоткеями не владеет.
        self._hotkey_status_provider = None
        self._last_overtaken_t: float = 0.0
        self._lap_distances: dict[int, float] = {}

        # ВРЕМЕННОЕ диагностическое состояние (см. чат — живая проверка Фазы A
        # показала почти полную тишину инженера, кроме battery/DRS). Убрать
        # вместе с DIAG-логами после диагностики.
        self._diag_last_cc: int | None = None

        # Driver Performance Coach
        self.driver_coach = DriverCoach()

        # Rival Intelligence
        self.rival_tracker = RivalTracker()
        # Что из знания о сопернике достойно эфира. Отдельно от трекера:
        # знание копится каждый тик, говорить можно редко.
        self._rival_intel = RivalIntelTracker()
        # До этого момента реплика пилота считается ОТВЕТОМ на вопрос инженера,
        # а не новым вопросом (см. _driver_query_tick).
        self._awaiting_driver_reply_until = 0.0
        # Договорённость по стратегическому предложению. Согласие пилота НЕ
        # заводит машину в боксы — приложение игрой не управляет; оно меняет
        # поведение инженера (см. core/strategy_ai/agreement.py).
        self._strategy_agreement = StrategyAgreement()

        # Deep runtime owns commentary thresholds, backlog and ambient timing.
        self._commentary_runtime = CommentaryRuntime()

        self._ui_state = UIStateProjection(
            initial_ui_state(
                llm_engine=self._llm_engine_label(),
                tts_engine=self.voice.engine_name,
                voice_status=self.voice.status_message,
                voice_available=self.voice.is_available,
                persona=config.PERSONA,
                yandex_ok=self.ai.available,
            ),
            max_feed_items=config.MAX_FEED_ITEMS,
        )
        self._race_cache_path = os.path.join(config.DATA_DIR, "race_cache.json")
        self._load_race_cache()

    # ------------------------------------------------------------
    # Race cache
    # ------------------------------------------------------------

    def _load_race_cache(self):
        try:
            if os.path.exists(self._race_cache_path):
                with open(self._race_cache_path, encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("grid"):
                    self._ui_state.set_race(cached)
        except Exception:
            pass

    def _save_race_cache(self, data: dict):
        try:
            with open(self._race_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------

    def apply_settings(self, settings: dict):
        with self._engine_lock:
            self.settings.update(settings)

        if "persona" in settings:
            self.commentator.persona = settings["persona"]
            self.voice.set_persona(settings["persona"])
            self._ui_state.set_preferences(persona=settings["persona"])

        if "radio_fx" in settings:
            try:
                self.voice.set_radio_fx(bool(settings["radio_fx"]))
            except Exception:
                pass

        if "persona" in settings or "engineer_character" in settings:
            self._apply_voice_cast()

        if "mic_device" in settings:
            self._voice_listener.set_device(settings["mic_device"])

        if "yandex_tts_version" in settings:
            version = settings["yandex_tts_version"]
            if version in ("v1", "v3", "v3-grpc"):
                try:
                    self.voice.set_tts_version(version)
                except Exception:  # noqa: BLE001
                    pass

        if "broadcast_mode_enabled" in settings:
            self._ui_state.set_preferences(
                broadcast_mode_enabled=bool(settings["broadcast_mode_enabled"]))

        if "racefeed_enabled" in settings:
            enabled = bool(settings["racefeed_enabled"])
            self._ui_state.set_preferences(racefeed_enabled=enabled)
            self._set_racefeed_enabled(enabled)

        # Персоны комментатора + слоты ролей (инженер/споттер, core/radio/
        # voice_cast.py). Роли озвучиваются не персоной, а своим слотом
        # (SLOT_ENGINEER/SLOT_SPOTTER), но ключ настройки следует тому же
        # шаблону volume_<slot> — поэтому один и тот же цикл собирает громкости
        # для обеих групп без дублирования кода.
        _PERSONAS = ("tv", "hype", "calm", "toxic",
                     voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER)
        if "volume" in settings or any(f"volume_{p}" in settings for p in _PERSONAS):
            try:
                global_vol = int(settings.get("volume", self.settings.get("volume", 80)))
                per = {
                    p: int(settings.get(f"volume_{p}", self.settings.get(f"volume_{p}", global_vol)))
                    for p in _PERSONAS
                    if f"volume_{p}" in settings or f"volume_{p}" in self.settings
                }
                self.voice.set_volume(global_vol, per)
            except Exception:  # noqa: BLE001
                pass

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
            _log.error("voice cast resolve failed", exc_info=True)

    def _racefeed_state_snapshot(self) -> dict:
        """Pull callback given to RaceFeedEngine — read-only snapshot of exactly
        the fields its periodic tick needs (see core/racefeed/engine.py::
        StoryBuilder.from_tick). Never reaches further into engine state than this."""
        with self._engine_lock:
            grid = list(self._current_grid)
            teammate_idx = _teammate.find_teammate_idx(
                grid, self._player_car_index
            )
            player_position = self._positions.get(
                self._player_car_index, self._player_pos
            )
            teammate_position = (
                self._positions.get(teammate_idx) if teammate_idx is not None
                else None
            )
            player_driver = self._player_driver_name()
            teammate_driver = ""
            if teammate_idx is not None:
                try:
                    teammate_driver = (
                        self.race_state.driver(teammate_idx).get("name") or ""
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {
                "session_type": self._session_type,
                # Editorial pacing scales its budget with race distance — a
                # 5-lap sprint must not get the same 20 posts as a full race
                # (see core/racefeed/editorial.py::scale_budgets).
                "total_laps": getattr(self, "_total_laps", None),
                # Labels the archived feed («Гран-при Монцы · 26 июля»); the
                # track is often still unknown at SSTA, so RaceFeed re-reads it
                # from the tick until it resolves.
                "track_name": TRACK_ID_TO_GP.get(self._track_id, (None,))[0],
                "track_id": self._track_id if self._track_id >= 0 else None,
                "player_team": self._racefeed_player_team(),
                "player_driver": player_driver,
                "player_position": player_position,
                "teammate_driver": teammate_driver,
                "teammate_position": teammate_position,
                "rain_forecast": dict(self._rain_forecast or {}),
                "gap_front_ms": self._player_gap_front,
                "gap_behind_ms": self._player_gap_behind,
                "gap_leader_ms": self._player_gap_leader,
                "player_fuel": self._player_fuel,
                "player_ers_percent": self._player_ers_percent,
                "player_tyre_wear": self._player_tyre_wear,
                "player_tyre_age": self._player_tyre_age,
                "player_tyre_compound": self._player_tyre_compound,
            }

    def _racefeed_player_team(self) -> str | None:
        if self._player_car_index >= 22:
            return None
        try:
            return self.race_state.driver(self._player_car_index).get("team") or None
        except Exception:  # noqa: BLE001
            return None

    def _player_driver_name(self) -> str:
        """The real driver the player races as — put on player-only RaceFeed
        events (championship/milestone/recap) so posts name them instead of
        writing the generic word "игрок"."""
        if self._player_car_index >= 22:
            return ""
        try:
            return self.race_state.driver(self._player_car_index).get("name") or ""
        except Exception:  # noqa: BLE001
            return ""

    def _set_racefeed_enabled(self, enabled: bool) -> None:
        """Hot start/stop — see docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md
        'Enable/disable': while disabled, self._race_feed is None, so event
        publication has no RaceFeed target and no worker thread exists."""
        if enabled:
            if self._race_feed is None:
                self._race_feed = RaceFeedEngine(
                    ai_provider=self.ai, state_provider=self._racefeed_state_snapshot,
                )
            self._race_feed.start()
        elif not enabled and self._race_feed is not None:
            if self._race_feed.stop():
                self._race_feed = None

    def get_racefeed_state(self) -> dict:
        from core.racefeed import ui_bridge
        return ui_bridge.get_posts(self._race_feed)

    def get_racefeed_stats(self) -> dict:
        from core.racefeed import ui_bridge
        return ui_bridge.get_stats(self._race_feed)

    def racefeed_reader_action(self, kind: str, session_id: str, post_id: str,
                               value: str) -> dict:
        """Reader's reaction or Driver-of-the-Day vote. Stored in the session's
        own file (see core/racefeed/reader.py), so it is still there when that
        race shows up in the archive."""
        from core.racefeed import reader
        if self._race_feed is None:
            return {"ok": False, "reason": "disabled"}
        try:
            if kind == "reaction":
                reader.react(self._race_feed.data_dir(), session_id, post_id, value)
            elif kind == "vote":
                reader.vote(self._race_feed.data_dir(), session_id, post_id, value)
            else:
                return {"ok": False, "reason": "unknown_action"}
        except reader.ReaderError as exc:
            return {"ok": False, "reason": str(exc)}
        except Exception:
            _log.warning("RaceFeed reader action failed", exc_info=True)
            return {"ok": False, "reason": "write_failed"}
        return {"ok": True}

    def racefeed_reader_comment(self, session_id: str, post_id: str,
                                text: str) -> dict:
        """Reader's own line in a thread. Returns it immediately; the personas'
        answers are generated by the worker and arrive with the next poll."""
        from core.racefeed import reader
        if self._race_feed is None:
            return {"ok": False, "reason": "disabled"}
        try:
            comment = self._race_feed.submit_reader_comment(
                session_id, post_id, text)
        except reader.ReaderError as exc:
            return {"ok": False, "reason": str(exc)}
        except Exception:
            _log.warning("RaceFeed reader comment failed", exc_info=True)
            return {"ok": False, "reason": "write_failed"}
        return {"ok": True, "comment": comment}

    def racefeed_prediction(self, ticket: dict) -> dict:
        if self._race_feed is None:
            return {"ok": False, "reason": "disabled"}
        try:
            return self._race_feed.submit_prediction(ticket)
        except Exception:
            _log.warning("RaceFeed prediction submit failed", exc_info=True)
            return {"ok": False, "reason": "write_failed"}

    def get_racefeed_archive(self) -> dict:
        """Feeds of previous races — the channel keeps a history between
        sessions instead of emptying on every SSTA. Cached per file in
        ui_bridge, so this is cheap to call repeatedly."""
        from core.racefeed import ui_bridge
        return ui_bridge.get_archive(self._race_feed)

    def get_season_standings(self) -> dict:
        from core.racefeed import ui_bridge
        return ui_bridge.get_standings(self._race_feed)

    def set_hotkey_status_provider(self, provider) -> None:
        """Колбэк от AppRuntime: GlobalHotkeyManager.registration_status.
        Движок хоткеями не владеет — он только даёт HTTP-слою один вход, как и
        для RaceFeed. Провайдера нет (окна нет / хоткеи не поднялись) →
        available=False, а не выдуманные нули."""
        self._hotkey_status_provider = provider

    def get_hotkey_status(self) -> dict:
        provider = getattr(self, "_hotkey_status_provider", None)
        if provider is None:
            return {"available": False, "ready": False, "hotkeys": []}
        try:
            return {"available": True, **provider()}
        except Exception as exc:  # noqa: BLE001
            _log.warning("hotkey status unavailable: %s", exc)
            return {"available": False, "ready": False, "hotkeys": []}

    def get_diagnostics(self) -> dict:
        """Снимок готовности для визарда первого запуска и для поддержки.

        Собирает факты (включая единственный обход PortAudio за списком
        микрофонов) и отдаёт их чистой `core.diagnostics.collect` — вся логика
        кодов живёт там и тестируется без движка.
        """
        try:
            from voice.listener import list_input_devices
            mic_devices = len(list_input_devices())
        except Exception:  # noqa: BLE001 - диагностика не имеет права падать
            mic_devices = 0

        try:
            hotkeys_ready = bool(self.get_hotkey_status().get("ready"))
        except Exception:  # noqa: BLE001
            hotkeys_ready = False

        status = self._telemetry_source_status or {}
        return diagnostics.collect(
            source_code=str(status.get("code", "pending")),
            source_detail=str(status.get("detail", "")),
            connected=self._telemetry_connected,
            last_packet_at=self._telemetry_last_packet_at,
            telemetry_source=self._telemetry_source,
            udp_ip=config.UDP_IP,
            udp_port=config.UDP_PORT,
            voice_engine=self.voice.engine_name,
            voice_available=self.voice.is_available,
            yandex_healthy=self._yandex_healthy,
            llm_provider=config.LLM_PROVIDER,
            llm_connected=bool(getattr(self.ai, "available", False)),
            mic_devices=mic_devices,
            hotkeys_ready=hotkeys_ready,
        )

    def _screenshots_dir(self) -> Path:
        d = Path(config.DATA_DIR) / "racefeed" / "screenshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _capture_hero_screenshot(self, values: dict, context) -> None:
        """Attach a screenshot to hero-moment player events. Sets values["image"]
        synchronously (cheap) and captures asynchronously so the file lands well
        before the post publishes. Only when RaceFeed is on and the player is
        involved."""
        if self._race_feed is None:
            return
        if (values.get("event_code") not in _HERO_SCREENSHOT_CODES
                or not context.player_involved):
            return
        image = f"{uuid.uuid4().hex}.png"
        values["image"] = image
        try:
            region = overlay_window.game_window_region()
            screenshot_mod.capture_async(str(self._screenshots_dir() / image), region)
        except Exception:  # noqa: BLE001 - never let capture break publishing
            _log.debug("hero screenshot dispatch failed", exc_info=True)

    def _make_ai_provider(self):
        """LLM-провайдер («мозг») по config.LLM_PROVIDER. Голос (TTS) от этого НЕ
        зависит — он всегда Yandex SpeechKit (см. _start_yandex). Для "gigachat"
        клиент Yandex игнорируется, а Authorization-ключ берётся из
        gigachat_creds.json — поэтому подключение Yandex для голоса не затирает
        мозг GigaChat, и наоборот."""
        if config.LLM_PROVIDER == "gigachat":
            from gigachat_ai.credentials import load as _gc_load
            from gigachat_ai.provider import GigaChatProvider
            return GigaChatProvider(_gc_load(), config.GIGACHAT_MODEL)
        return AIProvider(self._yandex_client, config.YANDEX_GPT_MODEL)

    def _llm_engine_label(self) -> str:
        """Ярлык активного «мозга» для UI (статичные точки: initial state,
        yandex_status)."""
        if not self.ai.available:
            return "Шаблоны"
        return "GigaChat" if config.LLM_PROVIDER == "gigachat" else "YandexGPT"

    def _provider_health_label(self, yandex_healthy: bool) -> str:
        """Ярлык мозга для health-монитора Yandex. В режиме "gigachat" мозг НЕ
        зависит от здоровья Yandex (тот обслуживает только голос) — ярлык остаётся
        "GigaChat", пока провайдер доступен. В режиме "yandex" — прежнее поведение:
        "YandexGPT", пока Yandex здоров, иначе "Шаблоны" (мозг ушёл в шаблоны)."""
        if config.LLM_PROVIDER == "gigachat":
            return "GigaChat" if self.ai.available else "Шаблоны"
        return "YandexGPT" if yandex_healthy else "Шаблоны"

    def _start_yandex(self, creds) -> None:
        """Поднять YandexClient и подключить голос. Проверку ведёт фоновый
        health-monitor (_yandex_health_loop, стартует в start()). До первой пробы
        статус — «проверяю», но роутинг оптимистично пробует Yandex."""
        try:
            self._yandex_client = YandexClient(creds)
            self._yandex_client.start()
            self.ai = self._make_ai_provider()
            self.commentator.ai = self.ai
            if self._race_feed is not None:
                self._race_feed.set_ai_provider(self.ai)
            speech = YandexSpeech(self._yandex_client)
            self._stt = YandexSTT(self._yandex_client)
            tts_ver = self.settings.get("yandex_tts_version", "v1")
            speech.set_tts_version(tts_ver)
            self.voice.set_yandex(speech)
            self.voice.set_yandex_health_reporter(self.record_yandex_result)
            self._yandex_healthy = True       # оптимистично: первая фраза попробует Yandex
            self._yandex_fail_streak = 0
            self.voice.set_yandex_healthy(True)
            self._ui_state.set_provider_health(
                healthy=True, engine=self._provider_health_label(True))
            self._yandex_status = {"connected": False, "code": "YANDEX_PENDING",
                                   "message": "Ключ сохранён — проверяю…"}
        except Exception as exc:  # noqa: BLE001
            self._yandex_client = None
            self._yandex_healthy = False
            self._yandex_status = {"connected": False, "code": "YANDEX_INTERNAL",
                                   "message": str(exc)}

    def record_yandex_result(self, ok: bool) -> None:
        """Единый учёт результата обращения к Yandex (проба монитора ИЛИ реальный синтез).

        «Мягкая проверка»: статус падает в False только после N неудач ПОДРЯД
        (YANDEX_HEALTH_FAIL_THRESHOLD) — одиночные сетевые блипы не дёргают статус
        (фикс «моргания»). Любой успех мгновенно поднимает статус и сбрасывает
        счётчик (авто-восстановление: следующая фраза уже уйдёт на Yandex)."""
        flipped_to = None
        with self._engine_lock:
            if ok:
                self._yandex_fail_streak = 0
                if not self._yandex_healthy:
                    self._yandex_healthy = True
                    flipped_to = True
                    self._yandex_status = {"connected": True, "code": "OK",
                                           "message": "Yandex активен (восстановлен)"}
                    self._ui_state.set_provider_health(
                        healthy=True, engine=self._provider_health_label(True))
                elif not self._yandex_status.get("connected"):
                    # были оптимистично-здоровы, но статус ещё PENDING — подтверждаем
                    self._yandex_status = {"connected": True, "code": "OK",
                                           "message": "Yandex активен (ключ проверен)"}
            else:
                self._yandex_fail_streak += 1
                if (self._yandex_healthy and
                        self._yandex_fail_streak >= config.YANDEX_HEALTH_FAIL_THRESHOLD):
                    self._yandex_healthy = False
                    flipped_to = False
                    self._yandex_status = {
                        "connected": False, "code": "YANDEX_NETWORK_ERROR",
                        "message": f"Нет связи с Yandex ({self._yandex_fail_streak} сбоя подряд) — резерв Piper",
                    }
                    self._ui_state.set_provider_health(
                        healthy=False, engine=self._provider_health_label(False))
        if flipped_to is not None:
            try:
                self.voice.set_yandex_healthy(flipped_to)
            except Exception:  # noqa: BLE001
                pass

    def _apply_full_validate(self, client, ok: bool, code: str, msg: str) -> None:
        """Результат ПОЛНОЙ стартовой пробы (validate: GPT+TTS) — точный статус для UI.
        Стартовая проба авторитетна: при провале помечаем недоступным сразу (быстрый
        цикл проб подхватит восстановление). Применяем, только если клиент актуален."""
        flipped_to = None
        with self._engine_lock:
            if self._yandex_client is not client:
                return
            if ok:
                self._yandex_fail_streak = 0
                if not self._yandex_healthy:
                    self._yandex_healthy = True
                    flipped_to = True
                    self._ui_state.set_provider_health(
                        healthy=True, engine=self._provider_health_label(True))
                self._yandex_status = {"connected": True, "code": code,
                                       "message": "Yandex активен (ключ проверен)"}
            else:
                if self._yandex_healthy:
                    self._yandex_healthy = False
                    flipped_to = False
                    self._ui_state.set_provider_health(
                        healthy=False, engine=self._provider_health_label(False))
                self._yandex_status = {"connected": False, "code": code,
                                       "message": f"Ключ не прошёл проверку: {msg}"}
        if flipped_to is not None:
            try:
                self.voice.set_yandex_healthy(flipped_to)
            except Exception:  # noqa: BLE001
                pass

    def _yandex_health_loop(self) -> None:
        """Фоновый health-monitor Yandex с «мягкой проверкой».

        Первая проба нового клиента — полная (validate: GPT+TTS, точное сообщение),
        дальше — лёгкие validate_quick (1 токен, без платного TTS). Статус падает
        только после порога неудач подряд; успех восстанавливает мгновенно. Интервал
        адаптивный: реже пока здоров, чаще пока упал (для быстрого возврата)."""
        last_client = None
        while not self._stop_event.is_set():
            client = self._yandex_client
            if client is None:
                last_client = None
                if self._stop_event.wait(config.YANDEX_HEALTH_INTERVAL_OK):
                    break
                continue
            if client is not last_client:
                last_client = client
                try:
                    ok, code, msg = client.submit(client.validate()).result(
                        timeout=config.YANDEX_GPT_TOTAL_TIMEOUT
                        + config.YANDEX_TTS_TOTAL_TIMEOUT + 3.0)
                except Exception as exc:  # noqa: BLE001
                    ok, code, msg = (False, "YANDEX_NETWORK_ERROR", str(exc))
                self._apply_full_validate(client, ok, code, msg)
            else:
                try:
                    ok = client.submit(
                        client.validate_quick(config.YANDEX_HEALTH_TIMEOUT)
                    ).result(timeout=config.YANDEX_HEALTH_TIMEOUT + 1.5)
                except Exception:  # noqa: BLE001
                    ok = False
                self.record_yandex_result(ok)
            if self._stop_event.wait(
                    config.YANDEX_HEALTH_INTERVAL_OK if self._yandex_healthy
                    else config.YANDEX_HEALTH_INTERVAL_DOWN):
                break

    def apply_yandex_credentials(self, api_key: str, folder_id: str,
                                 auth_mode: str = "api_key") -> tuple[bool, str, str]:
        """Проверить ключ live-пробой; при успехе сохранить и включить Yandex."""
        if not api_key or not folder_id:
            self._yandex_status = {"connected": False, "code": "YANDEX_NO_CREDENTIALS",
                                   "message": "Введите ключ и Folder ID"}
            return (False, "YANDEX_NO_CREDENTIALS", "Введите ключ и Folder ID")
        creds = yc.Credentials(api_key=api_key, folder_id=folder_id, auth_mode=auth_mode)
        client = YandexClient(creds)
        client.start()
        try:
            ok, code, msg = client.submit(client.validate()).result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            ok, code, msg = (False, "YANDEX_NETWORK_ERROR", str(exc))
        if not ok:
            client.stop()
            self._yandex_status = {"connected": False, "code": code, "message": msg}
            return (ok, code, msg)
        # успех: заменяем активный клиент. Сам swap — под локом (для читателей из
        # других потоков), а блокирующий I/O (yc.save, old.stop) — вне лока.
        old = self._yandex_client
        with self._engine_lock:
            self._yandex_client = client
            self.ai = self._make_ai_provider()
            self.commentator.ai = self.ai
            rf = self._race_feed
            if rf is not None:
                rf.set_ai_provider(self.ai)
            self.voice.set_yandex(YandexSpeech(self._yandex_client))
            # Каст переприменяется ПОСЛЕ пересоздания клиента: set_yandex()
            # ставит новый YandexSpeech, и оверрайды, применённые до него,
            # достались бы прежнему объекту.
            self._apply_voice_cast()
            self.voice.set_yandex_health_reporter(self.record_yandex_result)
            self._yandex_healthy = True       # свежепроверенный ключ — здоров
            self._yandex_fail_streak = 0
            self.voice.set_yandex_healthy(True)
            self._yandex_status = {"connected": True, "code": "OK", "message": msg}
            self._ui_state.set_provider_health(
                healthy=True, engine=self._provider_health_label(True))
        yc.save(creds)
        if old is not None:
            old.stop()
        return (True, "OK", msg)

    def yandex_status(self) -> dict:
        creds = yc.load()
        st = dict(self._yandex_status)
        st["masked_key"] = yc.mask(creds.api_key) if creds else ""
        st["folder_id"] = creds.folder_id if creds else ""
        st["llm_engine"] = self._llm_engine_label()
        return st

    def apply_gigachat_credentials(self, authorization_key: str,
                                   scope: str | None = None) -> tuple[bool, str, str]:
        """BYOK: проверить Authorization key GigaChat live-пробой; при успехе
        сохранить (шифрованно) и, если LLM_PROVIDER=="gigachat", подключить как
        активный «мозг». Голос (Yandex) не трогаем. Зеркалит apply_yandex_credentials."""
        from gigachat_ai import credentials as gcred
        from gigachat_ai.provider import GigaChatProvider
        key = (authorization_key or "").strip()
        if not key:
            self._gigachat_status = {"connected": False, "code": "GIGACHAT_NO_CREDENTIALS",
                                     "message": "Введите Authorization key"}
            return (False, "GIGACHAT_NO_CREDENTIALS", "Введите Authorization key")
        creds = gcred.GigaChatCredentials(key, scope or config.GIGACHAT_SCOPE)
        prov = GigaChatProvider(creds, config.GIGACHAT_MODEL)
        ok, code, msg = prov.validate()
        if not ok:
            self._gigachat_status = {"connected": False, "code": code, "message": msg}
            return (ok, code, msg)
        gcred.save(creds)
        with self._engine_lock:
            # Подключаем как активный мозг только если провайдер выбран gigachat —
            # иначе просто сохранили ключ на будущее (voice/yandex не затрагиваем).
            if config.LLM_PROVIDER == "gigachat":
                self.ai = prov
                self.commentator.ai = self.ai
                rf = self._race_feed
                if rf is not None:
                    rf.set_ai_provider(self.ai)
            self._gigachat_status = {"connected": True, "code": "OK", "message": msg}
        return (True, "OK", msg)

    def gigachat_status(self) -> dict:
        from gigachat_ai import credentials as gcred
        creds = gcred.load()
        st = dict(self._gigachat_status)
        # Сохранённый ключ с диска: если gigachat — активный мозг и провайдер
        # поднялся, отражаем «подключено», даже если apply_gigachat_credentials в
        # этой сессии не звался (иначе UI показал бы «ключ не задан» при рабочем мозге).
        if (creds and config.LLM_PROVIDER == "gigachat" and self.ai.available
                and not st.get("connected")):
            st = {"connected": True, "code": "OK",
                  "message": f"GigaChat активен ({config.GIGACHAT_MODEL})"}
        st["masked_key"] = yc.mask(creds.authorization_key) if creds else ""
        st["model"] = config.GIGACHAT_MODEL
        st["active"] = config.LLM_PROVIDER == "gigachat"
        return st

    def _get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def _is_paused(self) -> bool:
        return not self._get_setting("commentary_enabled", True)

    def _should_voice(self, event: dict) -> bool:
        if not self._get_setting("autovoice_enabled", True):
            return False
        if event.get("priority") == "critical":
            return self._get_setting("critical_events_enabled", True)
        return True

    def _event_involves(self, event: dict, vehicle_idx: int) -> bool:
        if vehicle_idx is None:
            return False
        involved = {
            event.get("vehicle_idx"),
            event.get("overtaking_idx"),
            event.get("being_overtaken_idx"),
            event.get("vehicle1_idx"),
            event.get("vehicle2_idx"),
        }
        return vehicle_idx in involved

    def _update_damage(self, dmg: dict) -> None:
        """Обновить HUD-состояние повреждений + голос один раз за категорию, когда
        она впервые пересекает порог заметности (см. design spec §5). Простая
        проверка текущего значения и текущего флага — без хранения "предыдущего
        тика"; сброс происходит, когда severity падает НИЖЕ порога (ремонт в
        боксах), готовя следующее объявление при новой поломке той же детали."""
        self._player_damage = {
            "wing_damage": dmg.get("wing_damage", 0),
            "floor_damage": dmg.get("floor_damage", 0),
            "gearbox_damage": dmg.get("gearbox_damage", 0),
            "engine_damage": dmg.get("engine_damage", 0),
        }
        self._ui_state.set_damage(self._player_damage)
        categories = {
            "wing": dmg.get("wing_damage", 0),
            "floor": dmg.get("floor_damage", 0),
            "gearbox": dmg.get("gearbox_damage", 0),
            "engine": dmg.get("engine_damage", 0),
        }
        for category, severity in categories.items():
            if severity >= _DAMAGE_NOTICEABLE_THRESHOLD and not self._damage_announced[category]:
                self._damage_announced[category] = True
                draft = {
                    "event_code": f"DAMAGE_{category.upper()}", "priority": "normal",
                    # ТЗ §6 различает «существенное» повреждение (high) и
                    # «критическое» (critical). Порог заметности выше — только
                    # «стоит ли объявлять вообще»; саму планку опасности ставит
                    # core/radio/policy.py::CRITICAL_DAMAGE_SEVERITY.
                    "damage_severity": severity,
                    "color": "#F97316", "driver": ""}
                draft["phrase"] = self._render_engineer_phrase(
                    draft, _damage_phrase_code(category, severity))
                self._commentary_events.publish(draft)
            elif severity < _DAMAGE_NOTICEABLE_THRESHOLD:
                self._damage_announced[category] = False

    def _update_tyre_sets(self, parsed: dict) -> None:
        """Tyre Sets (packet 12) — ПОЦИКЛОВОЙ пакет, одна машина за раз
        (parse_tyre_sets возвращает данные ДЛЯ ТОЙ машины, что была в
        пакете) — игнорируем всё, что не про игрока. См. docs/superpowers/
        plans/2026-07-19-tyre-sets-final-classification.md."""
        if not parsed or parsed.get("car_idx") != self._player_car_index:
            return
        self._player_tyre_sets_available = parsed["available_by_compound"]
        self._player_tyre_sets_fitted = {
            "compound": parsed["fitted_compound"], "wear": parsed["fitted_wear"],
        }

    def _update_final_classification(self, parsed: dict) -> None:
        """Final Classification (packet 8) — официальный подтверждённый
        результат, точнее live-снимка позиции на CHQF (см. _generate_story).
        Все 22 машины уже отфильтрованы до игрока в parse_final_classification."""
        if not parsed:
            return
        self._final_classification = parsed
        self._ui_state.set_final_classification(parsed)

    def _update_final_classification_grid(self, parsed: list[dict]) -> None:
        """Forward the authoritative full race result to season auto mode.

        The work is dispatched outside the UDP loop because rebuilding eleven
        ERP archives is intentionally much slower than packet processing.
        """
        if not parsed:
            return
        self._final_classification_grid = list(parsed)
        # Championship capture runs before the reality-mode gates below so it
        # fires for every race regardless of reality mode (it has its own guards).
        self._maybe_record_championship(parsed)
        if (self._reality_result_sent or self._telemetry_source != "f1"
                or self._session_type != "race"):
            return
        # Sprint classification uses the same packet/race session family, but
        # awards at most 8 points. Only the Sunday GP advances the season.
        if max((int(entry.get("points") or 0) for entry in parsed), default=0) < 15:
            return

        enriched: list[dict] = []
        for entry in parsed:
            vehicle_idx = int(entry.get("vehicle_idx", -1))
            identity = self.race_state.driver(vehicle_idx)
            raw_identity = self.race_state.drivers.get(vehicle_idx, {})
            enriched.append({
                **entry,
                "driver": identity.get("name"),
                "team": identity.get("team"),
                "team_id": raw_identity.get("team_id"),
                "race_number": raw_identity.get("number"),
            })

        self._reality_result_sent = True
        self._spawn_thread(
            self._submit_reality_result,
            args=(enriched, self._track_id, self._game_year),
            name="f1-reality-auto", task=True,
        )

    def _maybe_record_championship(self, grid: list[dict]) -> None:
        """On the authoritative Final Classification (points included), append
        this race to the season store and publish a CHAMPIONSHIP RaceFeed event.
        Once per race (flag reset at SSTA); races only; F1 only."""
        if (self._session_type != "race" or self._championship_recorded
                or self._telemetry_source != "f1" or not grid):
            return
        if self._race_feed is not None:
            try:
                self._race_feed.resolve_prediction(
                    grid,
                    self.race_state.driver,
                    self._player_car_index,
                    actual_risks={
                        "safety_car": self._sc_episode > 0,
                        "rain": self._rain_seen_this_race,
                        "penalty": "PENA" in self._session_events,
                    },
                )
            except Exception:
                _log.warning("RaceFeed prediction resolve failed", exc_info=True)
        classification = season_mod.build_classification(
            grid, self.race_state.driver, self._player_car_index)
        if not classification:
            return
        self._championship_recorded = True
        player_points = next(
            (row["points"] for row in classification if row["is_player"]), None)
        try:
            _archive.save_season_result({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "track_id": self._track_id,
                "game_year": self._game_year or None,
                "classification": classification,
            })
        except Exception:
            _log.warning("Season result save failed", exc_info=True)
            return
        self._publish_post_race_paddock(grid)
        # Career milestones read game_sessions (all-time), independent of the
        # season store — publish them before the season_summary early-return so
        # an achievement still fires when the sliding-window standings are empty.
        self._publish_milestone_if_any()
        summary = season_mod.season_summary(race_points=player_points)
        if summary is None:
            return
        rival = summary.get("rival")
        if rival:
            head_to_head = season_mod.race_head_to_head(classification, rival)
            if head_to_head is not None:
                summary.update(head_to_head)
        if summary.get("player_position") == 1:
            importance = 85
        elif player_points:
            importance = 70
        else:
            importance = 55
        self._commentary_events.publish({
            "event_code": "CHAMPIONSHIP", "priority": "normal",
            "driver": self._player_driver_name(), "color": "#FBBF24",
            "vehicle_idx": self._player_car_index,
            "importance": importance,
            **summary,
        })

    def _publish_post_race_paddock(self, grid: list[dict]) -> None:
        """Publish the fact recap, reconstructed interview and DOTD result."""
        recap = race_recap_mod.build(
            grid,
            self.race_state.driver,
            self._player_car_index,
            overtakes_by_idx=self._race_overtakes_by_driver,
        )
        if recap is not None:
            duel = weekend_duel_mod.build(
                grid, self.race_state.driver, self._player_car_index
            )
            if duel is not None:
                recap["weekend_duel"] = duel
            self._commentary_events.publish({
                "event_code": "RACE_RECAP",
                "priority": "normal",
                "driver": self._player_driver_name(),
                "vehicle_idx": self._player_car_index,
                "color": "#38BDF8",
                "importance": 86,
                **recap,
            })

        vote = driver_of_the_day_mod.compute(
            grid,
            self.race_state.driver,
            self._player_car_index,
            overtakes_by_idx=self._race_overtakes_by_driver,
        )
        if vote is None:
            return
        interview = post_race_interview_mod.build(
            grid,
            self.race_state.driver,
            self._player_car_index,
            vote=vote,
            overtakes_by_idx=self._race_overtakes_by_driver,
        )
        if interview is not None:
            self._commentary_events.publish({
                "event_code": "POST_RACE_INTERVIEW",
                "priority": "normal",
                "driver": self._player_driver_name(),
                "vehicle_idx": self._player_car_index,
                "color": "#C084FC",
                "importance": 82,
                **interview,
            })

        winner = vote["dotd_candidates"][0]
        self._commentary_events.publish({
            "event_code": "RACEFEED_DOTD",
            "priority": "normal",
            "driver": vote["dotd_driver"],
            "vehicle_idx": winner["vehicle_idx"],
            "color": "#FBBF24",
            "importance": 88,
            **vote,
        })

    def _publish_milestone_if_any(self) -> None:
        """Detect and publish the single highest-priority career milestone for
        the just-finished race (see core/milestones.py). The race is already in
        game_sessions (saved by recorder.finalize at CHQF), so it's index 0."""
        races = [s for s in _archive.list_game_sessions()
                 if s.get("session_type") == "race"]
        milestone = milestones_mod.detect(races)
        if milestone is None:
            return
        self._commentary_events.publish({
            "event_code": "MILESTONE", "priority": "normal",
            "driver": self._player_driver_name(), "color": "#F5C518",
            "vehicle_idx": self._player_car_index,
            **milestone,  # carries its own "importance"
        })

    @staticmethod
    def _submit_reality_result(
        classification: list[dict], track_id: int, game_year: int
    ) -> bool:
        return reality_mod_bridge.submit_final_classification(
            classification, track_id=track_id, game_year=game_year
        )

    def _update_session_history(self, parsed: dict) -> None:
        """Session History (packet 11) — ПОЦИКЛОВОЙ пакет, одна машина за
        раз. В отличие от Tyre Sets — НЕТ фильтра "только игрок": пакет
        цикличен по всем 22 машинам, и данные соперников — весь смысл
        сравнения лучших секторов в гэп-дайджесте. См. docs/superpowers/
        plans/2026-07-20-session-history-sector-comparison.md."""
        if not parsed:
            return
        self._session_history[parsed["car_idx"]] = parsed

    def _nearest_rival_idx(self) -> int | None:
        """car_idx соперника, с которым реально идёт борьба — тот из
        ближайших впереди/сзади (та же позиционная логика, что уже даёт
        _neighbor_names()), у кого МЕНЬШЕ гэп. None, если нет ни одного
        известного соседа."""
        pos = self._player_pos
        if not pos:
            return None
        idx_ahead = next((i for i, p in self._positions.items() if p == pos - 1), None)
        idx_behind = next((i for i, p in self._positions.items() if p == pos + 1), None)
        gap_front = self._player_gap_front
        gap_behind = self._player_gap_behind
        if idx_ahead is not None and idx_behind is not None:
            if gap_front is not None and gap_behind is not None:
                return idx_ahead if gap_front <= gap_behind else idx_behind
            return idx_ahead if gap_front is not None else idx_behind
        return idx_ahead if idx_ahead is not None else idx_behind

    def _teammate_idx(self) -> int | None:
        """car_idx напарника по команде. Считается по текущему гриду каждый
        раз, а не кэшируется: состав грида известен не сразу после старта
        сессии (метаданные пилотов доезжают позже), а поиск по 22 строкам
        дешевле, чем инвалидация кэша на каждый источник смены состава."""
        with self._engine_lock:
            grid = list(self._current_grid)
        return _teammate.find_teammate_idx(grid, self._player_car_index)

    def _teammate_report(self) -> str | None:
        """Готовый ответ инженера про напарника, либо None (напарник не
        определён). Собирает вместе то, что уже лежит в движке по отдельности:
        позиции, лучшие круги сессии, состав и возраст резины."""
        mate_idx = self._teammate_idx()
        if mate_idx is None:
            return None
        try:
            mate_name = self.race_state.driver(mate_idx).get("name") or "напарник"
        except Exception:  # noqa: BLE001
            mate_name = "напарник"
        player_hist = self._session_history.get(self._player_car_index) or {}
        mate_hist = self._session_history.get(mate_idx) or {}
        return _teammate.build_report(
            mate_name=mate_name,
            player_pos=self._player_pos,
            mate_pos=self._positions.get(mate_idx),
            player_best_ms=player_hist.get("best_lap_ms"),
            mate_best_ms=mate_hist.get("best_lap_ms"),
            mate_compound=self._grid_tyre_compounds.get(mate_idx),
            mate_tyre_age=self.rival_tracker.get_tyre_age(mate_idx),
        )

    def _teammate_race_result(self, final_pos: int | None) -> str | None:
        """Итог дуэли с напарником для послегоночной истории. Позиция напарника
        берётся из официальной классификации, если она уже пришла (packet 8) —
        как и позиция игрока в _generate_story; иначе из живого грида."""
        mate_idx = self._teammate_idx()
        if mate_idx is None:
            return None
        mate_pos = None
        for row in self._final_classification_grid:
            if row.get("vehicle_idx") == mate_idx:
                mate_pos = row.get("position")
                break
        if mate_pos is None:
            mate_pos = self._positions.get(mate_idx)
        return _teammate.race_result(final_pos, mate_pos)

    def _maybe_announce_pit_exit(self, prev_status: int | None, new_status: int | None) -> None:
        """Выезд из боксов — новое синтетическое событие (design spec
        2026-07-05-final-laps-attacks-pitstop). Едж-детект перехода "в боксах"
        (1/2) -> "не в боксах" (0): физически может сработать только один раз
        за заезд, отдельный анти-спам флаг не нужен (в отличие от
        _update_damage, где severity может держаться выше порога много тиков
        подряд). Только гонка — в практике/квалификации пит-стопы постоянны и
        не несут смысла (та же причина, по которой OVTK/FTLP уже приглушены
        вне гонки, см. score_importance)."""
        if prev_status in (1, 2) and new_status == 0 and self._session_type == "race":
            self._race_engineer.note_own_pit_exit(self._player_pos, time.time())
            self._strategy_module.note_pit_exit()
            self._commentary_events.publish({
                "event_code": "PIT_EXIT", "priority": "normal",
                "driver": "", "vehicle_idx": self._player_car_index,
                "color": "#38BDF8",
                "tyre_compound": self._player_tyre_compound,
            })
            # Реплика ИНЖЕНЕРА рядом с трансляционной. Комментатор говорит про
            # выезд в третьем лице («{driver} покидает пит-лейн»), и до этой
            # правки спека `box.exit` была недостижима вовсе — пилот не слышал
            # единственного, что ему на выезде нужно: резина холодная.
            self._publish_engineer_line("PIT_EXIT_ENGINEER", "box.exit")

    def _drs_advisory_tick(self) -> None:
        """Вызывается из ОБЕИХ веток _update_telemetry (LapData и CarStatus)
        — DRSAdvisoryTracker детерминирован независимо от того, какой пакет
        обработан первым. См. spec 2026-07-13-engineer-phase-a-cheap-calls-design.md.

        gap_front_ms==0 у лидера (машины впереди нет) — не "0 мс до
        соперника", это сырое значение телеметрии при отсутствии машины
        впереди (тот же gotcha, что уже обходят gap_digest.py:24 и
        situation_dedup.py:71 — найдено ревью, DRS-проводка изначально не
        повторила эту защиту)."""
        gap = self._player_gap_front if self._player_gap_front else None
        phrase_code = self._race_engineer.drs_advisory(
            gap, self._player_drs_allowed, time.time())
        if not phrase_code or not self._get_setting("engineer_chatter_enabled", True):
            return
        draft = {
            "event_code": _DRS_EVENT_CODE[phrase_code], "priority": "normal",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        }
        draft["phrase"] = self._render_engineer_phrase(draft, phrase_code)
        self._commentary_events.publish(draft)

    def _spotter_tick(self, motion_all: dict[int, dict]) -> None:
        """Вызывается на каждом PACKET_MOTION. self._lap_distances (из
        последнего PACKET_LAP_DATA) даёт дешёвый продольный фильтр ДО
        геометрии — считаем проекцию на player["right_x"]/["right_z"] только
        для машин, чей lap_distance близок к игроку. НЕ гейтуется
        engineer_chatter_enabled — решение пользователя 2026-07-18, споттер
        это безопасность (как PENA/box-call), не периодическая болтовня.
        См. spec 2026-07-18-real-spotter-motion-design.md.

        В этом же проходе метод также строит self._radar — более широкий
        снимок для HUD (визуальный радар). RADAR_WINDOW_M (25м) и
        LONGITUDINAL_WINDOW_M (6м, без изменений) — два намеренно разных
        окна для разных потребителей: HUD-радар (визуальный, шире) и
        голосовое предупреждение споттера (уже, безопасность). Это не
        дублирование — оба окна должны остаться."""
        player = motion_all.get(self._player_car_index)
        if player is None:
            return
        player_dist = self._lap_distances.get(self._player_car_index)
        if player_dist is None:
            return

        candidates: list[tuple[float, str]] = []
        radar: list[dict] = []
        for idx, m in motion_all.items():
            if idx == self._player_car_index:
                continue
            rival_dist = self._lap_distances.get(idx)
            if rival_dist is None:
                continue
            longitudinal = rival_dist - player_dist  # знак: + впереди, - позади
            if abs(longitudinal) > RADAR_WINDOW_M:
                # wide window: builds the visual HUD radar snapshot below
                continue
            rel_x = m["world_x"] - player["world_x"]
            rel_z = m["world_z"] - player["world_z"]
            lateral = rel_x * player["right_x"] + rel_z * player["right_z"]
            side = "right" if lateral > 0 else "left"
            radar.append({
                "vehicle_idx": idx, "side": side,
                "lateral_m": round(abs(lateral), 1),
                "longitudinal_m": round(longitudinal, 1),
            })
            if abs(longitudinal) <= LONGITUDINAL_WINDOW_M:
                # narrow window: unchanged voice-spotter safety threshold —
                # NOT redundant with the wide filter above, keep both
                candidates.append((abs(lateral), side))

        self._radar = sorted(radar, key=lambda c: abs(c["longitudinal_m"]))[:6]

        phrase_code = self._race_engineer.spotter_advisory(candidates, time.time())
        if not phrase_code:
            return
        # Трекер отдаёт семантический код, а движок переводит его в event_code.
        # Раньше здесь стояла обратная связь «сравнить фразу со списками» —
        # правка текста в spotter.py молча меняла event_code, а совпадение строк
        # между двумя списками сделало бы «машину слева» событием «чисто».
        code = _SPOTTER_EVENT_CODE[phrase_code]
        draft = {
            "event_code": code, "priority": "critical",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
            **radio_plumbing(
                neighbour_idx=self._spotter_neighbour_idx(code, radar)),
        }
        draft["phrase"] = self._render_engineer_phrase(draft, phrase_code)
        self._commentary_events.publish(draft)

    @staticmethod
    def _spotter_neighbour_idx(code: str, radar: list[dict]) -> int | None:
        """Машина, о которой споттер только что предупредил, либо None.

        Личность соседа для `situation_id` (core/radio/situations.py): пока
        рядом ТА ЖЕ машина, это одна ситуация, а смена соседа — новая. Сам
        SpotterTracker идентичность не хранит (он получает только
        `(lateral, side)`), поэтому берём её здесь из уже посчитанного radar —
        второй проход по геометрии не нужен.

        None для CLEAR (предупреждение снято, соседа нет) и для BOTH (машины с
        обеих сторон — ситуация про обстановку целиком, а не про одну машину).
        """
        side = {"SPOTTER_CAR_LEFT": "left", "SPOTTER_CAR_RIGHT": "right"}.get(code)
        if side is None:
            return None
        near = [
            entry for entry in radar
            if entry["side"] == side
            and abs(entry["longitudinal_m"]) <= LONGITUDINAL_WINDOW_M
        ]
        if not near:
            return None
        return min(near, key=lambda entry: entry["lateral_m"])["vehicle_idx"]

    def _leader_change_tick(self) -> None:
        """Вызывается каждый LapData-тик — только race (см. spec, квали/практика
        уже покрыты FTLP)."""
        if self._session_type != "race":
            return
        new_leader = self._race_engineer.leader_change(self._leader_idx, time.time())
        if new_leader is None or not self._get_setting("engineer_chatter_enabled", True):
            return
        if new_leader == self._player_car_index:
            # Игрок сам унаследовал лидерство (сход/пит-стоп прежнего лидера,
            # без OVTK) — POSITION_CALL уже озвучит «Теперь ты P1.», третье
            # лицо тут было бы избыточным и странным. Найдено финальным
            # сквозным ревью Фазы A.
            return
        driver_name = self.race_state.driver(new_leader)["name"]
        _log.info("DIAG LEADER_CHANGE firing: new_leader=%s driver=%s", new_leader, driver_name)
        draft = {
            "event_code": "LEADER_CHANGE", "priority": "normal",
            "speaker": SPEAKER_ENGINEER, "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        }
        # Имя лидера — ИСТОРИЧЕСКИЙ факт этой реплики (required, не volatile):
        # если к моменту озвучки лидер снова сменился, это уже другая новость, а
        # не обновление этой.
        draft["phrase"] = self._render_engineer_phrase(
            draft, "position.leader_change", {"rival": driver_name})
        if draft["phrase"]:
            self._commentary_events.publish(draft)

    def _engineer_topic_allows(self, event: dict, now: float) -> bool:
        """False = про это уже только что сказали другим кодом.

        Вынесено отдельным методом, а не оставлено строкой в `_commentary_loop`:
        цикл — бесконечный поток в фоновом потоке, и проверить решение там можно
        только запустив его целиком. Здесь же тест зовёт метод напрямую.

        Полоса дистанции берётся до машины ВПЕРЕДИ: сегодня все темы про неё.
        Когда появится тема про преследователя, сюда добавится выбор источника
        по теме, а не ещё один дедуп рядом."""
        topic = radio_policy.topic_for(str(event.get("event_code") or ""))
        if topic is None:
            return True
        ahead, _behind = self._neighbor_names()
        return self._engineer_topic_dedup.should_emit(
            topic, ahead, situation_gap_band(self._player_gap_front), now)

    def _publish_engineer_line(self, event_code: str, phrase_code: str,
                               fields: dict | None = None) -> None:
        """Реплика инженера без своего трекера: похвала и ритуалы сессии.

        Один метод, а не копия драфта на каждый повод: у этих реплик общий
        контракт — канал инженера, `bypass_speak_threshold`, категория и TTL из
        `core/radio/policy.py`. Расходиться им незачем, а разошедшись, они
        разойдутся молча.

        `engineer_chatter_enabled` уважается так же, как в соседних тиках: это
        общий тумблер болтливости инженера, и похвала с ритуалами — ровно та
        болтливость, которую им выключают.

        Пустая фраза (банк отказал — нет обязательного поля) не публикуется:
        молчание честнее, чем реплика с дырой на месте позиции."""
        if not self._get_setting("engineer_chatter_enabled", True):
            return
        draft = {
            "event_code": event_code, "priority": "normal",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        }
        draft["phrase"] = self._render_engineer_phrase(draft, phrase_code, fields)
        if draft["phrase"]:
            self._commentary_events.publish(draft)

    def _defense_tick(self) -> None:
        """Вызывается каждый тик после race_analyzer.update() (LapData-тик)
        — только race, как leader_change/pit_window (удержание позиции вне
        гонки не имеет смысла)."""
        if self._session_type != "race":
            return
        phrase_code = self._race_engineer.defense_advisory(
            self.race_analyzer.last_battle_active, time.time(), self._last_overtaken_t)
        if not phrase_code or not self._get_setting("engineer_chatter_enabled", True):
            return
        draft = {
            "event_code": "DEFENSE", "priority": "normal",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        }
        draft["phrase"] = self._render_engineer_phrase(draft, phrase_code)
        self._commentary_events.publish(draft)

    def _should_commentate(self, event: dict) -> bool:
        """Фильтр «Позиция комментатора»."""
        mode = self._get_setting("commentator_position", "auto")

        if mode == "all":
            return True

        if mode == "player":
            if self._player_car_index >= 22:
                return event.get("priority") == "critical"
            return self._event_involves(event, self._player_car_index)

        if mode == "leader":
            if self._leader_idx is None:
                return event.get("priority") == "critical"
            return self._event_involves(event, self._leader_idx)

        # auto — игрок + критические + борьба + быстрейший круг
        if event.get("priority") == "critical" or event.get("battle"):
            return True
        if event.get("event_code") == "FTLP":  # быстрейший круг всегда интересен
            return True
        if self._player_car_index < 22 and self._event_involves(event, self._player_car_index):
            return True
        player_pos = self._positions.get(self._player_car_index)
        if player_pos and event.get("event_code") == "OVTK":
            for idx in (event.get("overtaking_idx"), event.get("being_overtaken_idx")):
                other_pos = self._positions.get(idx)
                if other_pos and abs(other_pos - player_pos) <= 2:
                    return True
        return False

    # ------------------------------------------------------------
    # Comment Planner: важность события -> очередь/порог/гэп/прерывание
    # (см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md)
    # ------------------------------------------------------------

    def _plan_context(self, event: dict) -> PlanContext:
        """Срез состояния гонки для score_importance() — planner в engine-state
        напрямую не лезет, engine строит контекст по значению."""
        total_laps = getattr(self, "_total_laps", None)
        laps_remaining = (
            total_laps - self._player_lap
            if total_laps and self._player_lap is not None
            else None
        )
        return PlanContext(
            player_involved=self._event_involves(event, self._player_car_index),
            battle=bool(event.get("battle")),
            laps_remaining=laps_remaining,
            session_type=self._session_type,
        )

    # ------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------

    @staticmethod
    def _guarded(target, name: str):
        """Обёртка, из-за отсутствия которой падение воркера было невидимым.

        `threading` печатает traceback умершего потока в stderr, а у оконного
        приложения (`app.pyw`, frozen EXE) stderr никуда не ведёт. Поток
        телеметрии, умерший на занятом порту, выглядел для пользователя просто
        как вечное «нет связи». Логируем в файл — молчаливая смерть воркера
        запрещена независимо от причины.
        """

        def runner(*args):
            try:
                target(*args)
            except BaseException:  # noqa: BLE001 - последняя черта перед тишиной
                _log.exception("Поток %s упал", name)
                raise

        return runner

    def _spawn_thread(self, target, *, name: str, args: tuple = (),
                      task: bool = False) -> threading.Thread | None:
        """Start and retain an owned thread unless shutdown has begun."""
        if self._stop_event.is_set():
            return None
        kwargs = {"target": self._guarded(target, name), "daemon": True, "name": name}
        if args:
            kwargs["args"] = args
        thread = threading.Thread(**kwargs)
        (self._task_threads if task else self._worker_threads).append(thread)
        thread.start()
        return thread

    def start(self) -> None:
        """Start owned resources once. Construction itself is passive."""
        with self._lifecycle_lock:
            if self._started or self._stopped:
                return
            self._started = True

        # Optional modules degrade independently: a missing voice/model/network
        # must not prevent the local UI from starting.
        for label, starter in (
            ("voice", self.voice.start),
            ("metadata", self.metadata.start),
            ("commentator", self.commentator.start),
        ):
            try:
                starter()
            except Exception:  # noqa: BLE001
                _log.exception("%s startup failed; continuing degraded", label)

        if self._initial_yandex_creds is not None:
            self._start_yandex(self._initial_yandex_creds)

        self._spawn_thread(self._telemetry_loop, name="telemetry")
        self._spawn_thread(self._commentary_loop, name="commentary")
        self._spawn_thread(self._yandex_health_loop, name="yandex-health")
        self._spawn_thread(self._ambient_loop, name="ambient-tick")
        self._spawn_thread(self._engineer_digest_loop, name="engineer-digest")
        self._set_racefeed_enabled(bool(self.settings.get("racefeed_enabled", False)))

    def stop(self, timeout: float = 5.0) -> None:
        """Stop accepting work and release all owned resources boundedly."""
        with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopped = True
            self._stop_event.set()

        deadline = time.monotonic() + max(0.0, timeout)
        telemetry = self._telemetry_instance
        if telemetry is not None:
            try:
                telemetry.close()
            except Exception:  # noqa: BLE001
                _log.exception("telemetry shutdown failed")

        # Stop network/audio producers before joining callers blocked on them.
        client = self._yandex_client
        if client is not None:
            try:
                client.stop(timeout=min(
                    3.0, max(0.0, deadline - time.monotonic())))
            except Exception:  # noqa: BLE001
                _log.exception("Yandex shutdown failed")
        remaining = lambda: max(0.0, deadline - time.monotonic())
        race_feed = self._race_feed
        self._race_feed = None
        if race_feed is not None:
            try:
                race_feed.stop(timeout=remaining())
            except Exception:  # noqa: BLE001
                _log.exception("RaceFeed shutdown failed")

        for label, stopper in (
            ("voice", lambda: self.voice.stop(timeout=min(2.0, remaining()))),
            ("commentator", lambda: self.commentator.stop(timeout=min(1.0, remaining()))),
            ("metadata", lambda: self.metadata.stop(timeout=min(1.0, remaining()))),
        ):
            try:
                stopper()
            except Exception:  # noqa: BLE001
                _log.exception("%s shutdown failed", label)

        for thread in [*self._worker_threads, *self._task_threads]:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=remaining())
            if thread.is_alive():
                _log.warning("Thread %s did not stop before deadline", thread.name)

        self._telemetry_connected = False
        self._ui_state.set_connected(False)
        self._ui_state.set_speaking("", False)

    # ------------------------------------------------------------
    # Поток приёма телеметрии
    # ------------------------------------------------------------

    def _apply_telemetry_delta(self, delta: TelemetryDelta) -> None:
        """Apply one source-neutral telemetry delta to the race model."""
        self._apply_telemetry_identity(delta)

        telem: dict = {}

        if delta.kind == "session":
            session = delta.payload

            self._rain_forecast = session.get("rain_forecast")
            self._current_weather = {
                "weather": session["weather"],
                "track_temp": session["track_temp"],
                "air_temp": session["air_temp"],
            }
            if int(session.get("weather") or 0) >= 3:
                self._rain_seen_this_race = True
            self._safety_car_status = session.get("safety_car_status", 0)
            self._ui_state.set_safety_car_status(self._safety_car_status)
            _rain_code = self._race_engineer.rain_advisory(self._rain_forecast)
            if _rain_code is not None and self._get_setting("engineer_chatter_enabled", True):
                _rain_draft = {
                    "event_code": "ENGINEER_RAIN_ADVISORY", "priority": "normal",
                    "speaker": SPEAKER_ENGINEER,
                    "driver": "", "color": "#38BDF8",
                    "bypass_speak_threshold": True,
                    # Личность погодного фронта для situation_id — счётчик живёт
                    # в самом трекере, он один знает, когда эпизод закрылся.
                    **radio_plumbing(
                        rain_front_id=(
                            self._race_engineer.rain_advisory_tracker.front_id)),
                }
                # Горизонт НЕ подставляем здесь: `{minutes}` доживает до порога
                # озвучки, где резолвер возьмёт актуальное значение или отменит
                # реплику, если прогноз пропал.
                _rain_draft["phrase"] = self._render_engineer_phrase(
                    _rain_draft, _rain_code)
                if _rain_draft["phrase"]:
                    self._commentary_events.publish(_rain_draft)
            if session.get("total_laps"):
                telem["total_laps"] = session["total_laps"]
            if session.get("track_id", -1) >= 0:
                new_tid = session["track_id"]
                if new_tid != self._track_id:
                    self._track_id = new_tid
                    city = TRACK_ID_TO_GP.get(self._track_id, ("Unknown",))[0]
                    self._track_city = city
                    track_info = load_track(city)
                    self._track_manager = TrackManager(track_info) if track_info else None
                    self.f1_benchmark.reset()
                    self._f1_comparison_progress.reset()
                    self._f1_context_line = None
                    self._start_f1_benchmark_load(new_tid)
                    self.career_memory.reset()
                    self._career_comparison_progress.reset()
                    self._career_context_line = None
                    # _career_stats_context_line НЕ сбрасывается здесь: это кросс-
                    # трековый агрегат (см. __init__), он не привязан к трассе и
                    # переживает смену трассы — сбрасывается только на SSTA.
                    self._start_career_memory_load(new_tid)
                    self._refresh_analytics_context()
            new_st = session.get("session_type", "unknown")
            # ВРЕМЕННАЯ диагностика (см. чат): "unknown" держался весь заезд —
            # логируем СЫРОЙ байт раз в ~5с (не только при смене new_st, раз он
            # мог оставаться "unknown" стабильно), чтобы понять, что реально
            # шлёт игра в m_sessionType@6.
            _diag_now = time.time()
            if _diag_now - getattr(self, "_diag_last_session_log_t", 0.0) >= 5.0:
                self._diag_last_session_log_t = _diag_now
                _log.info("DIAG session_type_raw=%s -> mapped=%s (current=%s)",
                          session.get("session_type_raw"), new_st, self._session_type)
            if new_st and new_st != self._session_type:
                _log.info("DIAG session_type CHANGED: %s -> %s", self._session_type, new_st)
                self._session_type = new_st
                self._session_guard.set_session_type(new_st)
                self._ui_state.set_session_type(new_st)
                if new_st == "race":
                    if (not self._pre_race_pep_talk_fired
                            and self._get_setting("engineer_chatter_enabled", True)):
                        self._pre_race_pep_talk_fired = True
                        # Сначала связь, потом разговор: напутствие в молчащую
                        # рацию бессмысленно. Проверка публикуется синхронно, а
                        # напутствие уходит в поток с задержкой — порядок
                        # гарантирован самой этой строкой, не гонкой потоков.
                        self._publish_engineer_line(
                            "SESSION_RADIO_CHECK", "session.radio_check")
                        self._spawn_thread(
                            self._pre_race_pep_talk,
                            name="pre-race-pep-talk", task=True)
                else:
                    # Уходим из race (в меню/квалификацию/практику) — сброс,
                    # чтобы следующий заход в race-сессию снова получил реплику.
                    self._pre_race_pep_talk_fired = False

        elif delta.kind == "lap_data":
            lap_info = delta.payload["lap_info"]

            self._positions = lap_info.get("positions", {})
            self._lap_distances = lap_info.get("lap_distances", {})
            _new_leader_idx = lap_info.get("leader_idx")
            if _new_leader_idx != self._leader_idx:
                # ВРЕМЕННАЯ диагностика (см. чат): сырой поток leader_idx —
                # действительно ли лидер вообще менялся за заезд.
                _log.info("DIAG leader_idx raw: %s -> %s (player_car_index=%s)",
                          self._leader_idx, _new_leader_idx, self._player_car_index)
            self._leader_idx = _new_leader_idx
            self._leader_change_tick()
            positions = lap_info.get("positions", {})
            if any(v > 0 for v in positions.values()):
                gaps_front = lap_info.get("gaps_front", {})
                grid = []
                for vehicle_idx, position in sorted(positions.items(), key=lambda item: item[1] or 999):
                    driver_info = self.race_state.driver(vehicle_idx)
                    grid.append({
                        "vehicle_idx": vehicle_idx,
                        "position": position,
                        "driver": driver_info["name"],
                        "team": driver_info["team"],
                        "color": driver_info["color"],
                        "lap": lap_info.get("laps", {}).get(vehicle_idx, 0),
                        "pit_status": lap_info.get("pit_status", {}).get(vehicle_idx, 0),
                        # "" пока Car Status не принёс эту машину — UI покажет
                        # прочерк, но уже как «пока неизвестно», а не всегда.
                        "tyre_compound": self._grid_tyre_compounds.get(vehicle_idx, ""),
                        # gap_front_ms==0 у лидера — не "0 мс до соперника", а
                        # сырое значение при отсутствии машины впереди (тот же
                        # gotcha, что в _drs_advisory_tick выше). Это ЕЁ
                        # СОБСТВЕННЫЙ гэп до машины впереди НЕЁ (F1 UDP
                        # m_deltaToCarInFront) — core/overlay.py::_relative_rows
                        # зависит от этой точной семантики при накоплении гэпа
                        # "игрок -> дальняя машина"; менять её здесь без
                        # синхронной правки там нельзя.
                        "gap_front_ms": gaps_front.get(vehicle_idx),
                    })
                leader_name = self.race_state.driver(self._leader_idx)["name"] if self._leader_idx is not None else "—"
                self._leader_name = leader_name
                race_data = {
                    "leader": leader_name,
                    "leader_idx": self._leader_idx,
                    "grid": grid,
                    "last_update": datetime.now().strftime("%H:%M:%S"),
                }
                self._current_grid = list(grid)
                self._ui_state.set_race(race_data)
                self._save_race_cache(race_data)
                self.rival_tracker.update(
                    grid,
                    player_vehicle_idx=self._player_car_index,
                    now=time.time(),
                )
            if self._player_car_index < 22:
                pl = delta.payload["player_lap"]
                if pl.get("current_lap"):
                    telem["current_lap"] = pl["current_lap"]
                    self._player_lap = pl["current_lap"]
                if pl.get("position"):
                    telem["position"] = pl["position"]
                    self._player_pos = pl["position"]
                    self.story_collector.note_start_position(pl["position"])
                # Отрывы: к машине впереди и к лидеру — из пакета игрока;
                # к машине сзади — gap_front той машины, что на позицию ниже.
                self._player_gap_front = pl.get("gap_front_ms")
                self._player_gap_leader = pl.get("gap_leader_ms")
                _prev_pit_status = self._player_pit_status
                self._player_pit_status = pl.get("pit_status")
                self._maybe_announce_pit_exit(_prev_pit_status, self._player_pit_status)
                cc = pl.get("corner_cutting_warnings")
                if cc is not None and cc != self._diag_last_cc:
                    # ВРЕМЕННАЯ диагностика (см. чат): офсет cornerCuttingWarnings
                    # никогда не проверялся на живых байтах игры — логируем сырое
                    # значение при каждом изменении, чтобы подтвердить/опровергнуть.
                    _log.info("DIAG corner_cutting_warnings changed: %s -> %s", self._diag_last_cc, cc)
                    self._diag_last_cc = cc
                if cc is not None:
                    self._player_hud["corner_cutting_warnings"] = cc
                    tl_code = self._race_engineer.track_limits_warning(cc, time.time())
                    if tl_code and self._get_setting("engineer_chatter_enabled", True):
                        tl_draft = {
                            "event_code": "ENGINEER_TRACK_LIMITS_WARNING",
                            "priority": "normal",
                            "speaker": SPEAKER_ENGINEER,
                            "driver": "", "color": "#38BDF8",
                            "bypass_speak_threshold": True,
                        }
                        tl_draft["phrase"] = self._render_engineer_phrase(
                            tl_draft, tl_code)
                        if tl_draft["phrase"]:
                            self._commentary_events.publish(tl_draft)
                if self._session_type == "race":
                    pc_code = self._race_engineer.position_advisory(
                        self._player_pos, time.time())
                    if pc_code:
                        _log.info("DIAG POSITION_CALL firing: code=%r", pc_code)
                    if pc_code and self._get_setting("engineer_chatter_enabled", True):
                        # event_code выводится ИЗ СЕМАНТИЧЕСКОГО КОДА, а не из
                        # текста. Раньше здесь стояло `"пит-стопа" in pc_phrase`:
                        # любая правка формулировки молча меняла тип события — та
                        # самая обратная связь «строка → код», которую банк и
                        # должен был убрать.
                        pc_draft = {
                            "event_code": _POSITION_EVENT_CODE[pc_code],
                            "priority": "normal",
                            "speaker": SPEAKER_ENGINEER,
                            "driver": "", "color": "#38BDF8",
                            "bypass_speak_threshold": True,
                        }
                        pc_draft["phrase"] = self._render_engineer_phrase(
                            pc_draft, pc_code)
                        if pc_draft["phrase"]:
                            self._commentary_events.publish(pc_draft)
                if pl.get("pit_status"):
                    self._current_lap_pit = True
                if pl.get("lap_distance_m") is not None:
                    self._lap_distance_m = pl["lap_distance_m"]
                gaps_front = lap_info.get("gaps_front", {})
                ppos = pl.get("position")
                if ppos:
                    idx_behind = next((i for i, p in self._positions.items()
                                       if p == ppos + 1), None)
                    self._player_gap_behind = (gaps_front.get(idx_behind)
                                               if idx_behind is not None else None)
                # Lap recording for analytics
                if pl:
                    cur = pl.get("current_lap", 0)
                    lms = pl.get("last_lap_ms", 0)
                    if lms > 0:
                        self._player_pace_ms = lms   # последний завершённый круг (темп)
                    if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
                        lap_was_pit = self._current_lap_pit
                        self.recorder.on_lap_complete(
                            lap_num=self._prev_lap,
                            last_lap_ms=lms,
                            s1_ms=pl.get("s1_ms", 0),
                            s2_ms=pl.get("s2_ms", 0),
                            s3_ms=pl.get("s3_ms", 0),
                            pit_lap=lap_was_pit,
                        )
                        # Пит-круг искажает consistency/pace_delta/tyre_advice/
                        # weak_sector — не кормим coach вообще.
                        if not lap_was_pit:
                            self.driver_coach.add_lap(
                                lap_number=self._prev_lap,
                                lap_time_ms=lms,
                                s1_ms=pl.get("s1_ms", 0),
                                s2_ms=pl.get("s2_ms", 0),
                                s3_ms=pl.get("s3_ms", 0),
                                tyre_compound=self._player_tyre_compound,
                                tyre_age=self._player_tyre_age,
                                tyre_wear=self._player_tyre_wear,
                            )
                        self._last_completed_lap_was_pit = lap_was_pit
                        self._current_lap_pit = False
                        self._update_f1_benchmark()
                        self._update_career_memory()
                    if cur > 0:
                        self._prev_lap = cur
            self._maybe_snapshot()

        elif delta.kind == "car_telemetry" and self._player_car_index < 22:
            telem.update(delta.payload)

        elif delta.kind == "car_status" and self._player_car_index < 22:
            telem.update(delta.payload["player"])
            for idx, st in delta.payload["all"].items():
                # Состав резины парсится для ВСЕХ машин с самого начала, но
                # раньше выбрасывался: таблица позиций рисовала всем чип «—»,
                # что читалось как поломка. Держим последнее известное значение
                # по индексу машины — пакет приходит по кругу, не для всех сразу.
                compound = st.get("tyre_compound")
                if compound and compound != "?":
                    self._grid_tyre_compounds[idx] = compound
                if idx != self._player_car_index and st.get("tyre_age") is not None:
                    self.rival_tracker.update_tyre(idx, st["tyre_age"])

        elif delta.kind == "car_damage" and self._player_car_index < 22:
            dmg = delta.payload["player"]
            if dmg.get("tyre_wear") is not None:
                self._player_tyre_wear = dmg["tyre_wear"]
            # нет полей для state.telemetry — снимок подтянет износ на следующем LAP_DATA
            if dmg:
                self._update_damage(dmg)
            now = time.time()
            for idx, d in delta.payload["all"].items():
                if idx == self._player_car_index:
                    continue
                body = max(d.get("wing_damage", 0), d.get("floor_damage", 0),
                           d.get("gearbox_damage", 0), d.get("engine_damage", 0))
                self.rival_tracker.update_damage(
                    idx, body, threshold=_DAMAGE_NOTICEABLE_THRESHOLD, now=now)

        if not telem:
            return

        total = telem.get("total_laps", getattr(self, "_total_laps", None))
        if telem.get("total_laps"):
            self._total_laps = telem["total_laps"]
            total = telem["total_laps"]
        if telem.get("speed") is not None:
            self._player_speed_kmh = telem["speed"]
        if telem.get("fuel") is not None:
            self._player_fuel = telem["fuel"]
        if telem.get("tyre_compound") is not None:
            self._player_tyre_compound = telem["tyre_compound"]
        if telem.get("tyre_age") is not None:
            self._player_tyre_age = telem["tyre_age"]
        if telem.get("ers_percent") is not None:
            self._player_ers_percent = telem["ers_percent"]
        if telem.get("ers_deploy_mode") is not None:
            self._player_ers_deploy_mode = telem["ers_deploy_mode"]
        if telem.get("drs_allowed") is not None:
            self._player_drs_allowed = telem["drs_allowed"]
        for _hud_key in (
            "throttle_pct", "brake_pct", "steer", "rpm", "rev_lights_pct",
            "fuel_remaining_laps", "ers_harvested_pct", "ers_deployed_pct",
            "power_ice_kw", "power_mguk_kw", "drs_distance_m", "drs_allowed",
        ):
            if telem.get(_hud_key) is not None:
                self._player_hud[_hud_key] = telem[_hud_key]
        self._ui_state.update_telemetry(
            current_lap=telem.get("current_lap"),
            total_laps=total,
            position=telem.get("position"),
            speed=telem.get("speed"),
            gear=telem.get("gear"),
            fuel=telem.get("fuel"),
        )
        self._drs_advisory_tick()
        self._rival_intel_tick()
        self._driver_query_tick()

    #: Сколько секунд после вопроса инженера следующая реплика пилота считается
    #: ОТВЕТОМ, а не новым вопросом. Полминуты: пилот отвечает не мгновенно —
    #: сначала он доезжает поворот.
    DRIVER_REPLY_WINDOW_S = 30.0

    def _driver_query_tick(self) -> None:
        """Вопрос пилоту, если сейчас для него подходящий момент.

        Открывает окно ответа: следующая реплика пилота по PTT в пределах
        `DRIVER_REPLY_WINDOW_S` будет понята как ответ, а не как новый вопрос
        (см. `_ptt_reply_expected`). Без этого окна инженер отповедил бы на
        собственный вопрос — `radio_answer.OFF_TOPIC_ANSWER`."""
        if (self._session_type != "race"
                or not self._get_setting("engineer_chatter_enabled", True)):
            return
        phrase_code = self._race_engineer.driver_query(
            gap_front_ms=self._player_gap_front,
            gap_behind_ms=self._player_gap_behind,
            tyre_age=self._player_tyre_age,
            safety_car=bool(self._safety_car_status),
            now=time.time(),
        )
        if not phrase_code:
            return
        self._awaiting_driver_reply_until = time.time() + self.DRIVER_REPLY_WINDOW_S
        self._publish_engineer_line("ENGINEER_ASKS_DRIVER", phrase_code)

    def _ptt_reply_expected(self, now: float) -> bool:
        """True, пока реплика пилота считается ответом на вопрос инженера."""
        return now < self._awaiting_driver_reply_until

    def _resolve_strategy_decision(self, question: str) -> str | None:
        """Ответ инженера на «да»/«нет» пилота, либо None если это не решение.

        Возвращает готовую фразу, а действие (закрыть окно, запомнить решение)
        совершает здесь же — как `_execute_voice_command`.

        Решение разбирается ТОЛЬКО при живом предложении: `classify_decision`
        специально не входит в `classify_command`, потому что «да» и «нет» вне
        контекста — обычная речь, а не команда."""
        now = time.time()
        if self._strategy_agreement.pending(now) is None:
            return None
        decision = _radio_answer.classify_decision(question)
        if decision is None:
            return None
        if decision == "accept":
            self._strategy_agreement.accept(now)
            phrase_code = "decision.accepted"
        else:
            self._strategy_agreement.decline(now)
            phrase_code = "decision.declined"
        return self._render_engineer_phrase(
            {"event_code": "USER_Q"}, phrase_code)

    def _rival_intel_tick(self) -> None:
        """Разведка про машину ВПЕРЕДИ: чужая резина, чужие ошибки, чужая манера.

        Данные `RivalTracker` собирал и раньше, но уезжали они только в контекст
        LLM-комментатора и стратегии — инженер не произносил из них ничего.
        Новой телеметрии тик не требует.

        Только гонка: в практике и квалификации «соперник впереди» — случайная
        машина на своём круге, и разведка про неё бессмысленна (тот же гейт, что
        у остальных тиков инженера)."""
        if (self._session_type != "race"
                or not self._get_setting("engineer_chatter_enabled", True)):
            return
        pos = self._player_pos
        if not pos:
            return
        idx_ahead = next(
            (i for i, p in self._positions.items() if p == pos - 1), None)
        if idx_ahead is None:
            return
        now = time.time()
        rival_age = self.rival_tracker.get_tyre_age(idx_ahead)
        # Разница считается ЗДЕСЬ, а не в трекере: трекер знает только про
        # соперников и про шины игрока не осведомлён по конструкции.
        delta = (None if rival_age is None or self._player_tyre_age is None
                 else rival_age - self._player_tyre_age)
        found = self._rival_intel.check(
            rival_idx=idx_ahead,
            tyre_delta=delta,
            recent_mistake=self.rival_tracker.get_recent_mistake(idx_ahead, now),
            style=self.rival_tracker.get_style(idx_ahead),
            now=now,
        )
        if found is None:
            return
        phrase_code, fields = found
        if "laps" in fields:
            # Согласование числительного — тем же примитивом, что использует
            # резолвер: «8 кругов», а не «8 круг». Required-поле подставляется
            # как есть, поэтому согласовать обязан вызывающий.
            fields = {"laps": f"{fields['laps']} " + ru_plural(
                fields["laps"], "круг", "круга", "кругов")}
        self._publish_engineer_line(
            "ENGINEER_RIVAL_INTEL", phrase_code, fields)

    def _apply_telemetry_identity(self, delta: TelemetryDelta) -> None:
        player = delta.player_car_index
        if player < 22:
            self._player_car_index = player
        gy = delta.game_year
        if gy and gy > 0:
            self._game_year = (2000 + gy) if gy < 100 else int(gy)
            # Season-aware lookups (roster/team by car number) need this to pick
            # the right static dict — номера переиспользуются между сезонами.
            self.race_state.game_year = self._game_year
            self.metadata.game_year = self._game_year

    def _maybe_snapshot(self) -> None:
        """Записать снимок ситуации в таймлайн (троттлинг ~1 c). Сетку берём из
        свежего state.race; времена кругов/топливо — из сырых трекеров игрока."""
        now = time.time()
        if now - self._last_snap_t < 1.0:
            return
        self._last_snap_t = now
        with self._engine_lock:
            grid = list(self._current_grid) or None
            self.timeline.record_snapshot(
                lap=self._player_lap, position=self._player_pos,
                leader=self._leader_name, grid=grid,
                last_lap_ms=self._player_pace_ms, fuel=self._player_fuel,
                total_laps=getattr(self, "_total_laps", None),
                gap_leader_ms=self._player_gap_leader,
                gap_front_ms=self._player_gap_front,
                gap_behind_ms=self._player_gap_behind,
                tyre_compound=self._player_tyre_compound,
                tyre_age=self._player_tyre_age,
                tyre_wear=self._player_tyre_wear,
                session_type=self._session_type,
                pit_status=getattr(self, "_player_pit_status", None),
                pit_lap=self._last_completed_lap_was_pit)

        # Race Situation Engine: deterministic analysis, <5ms, no I/O
        driver_behind_name: str | None = None
        if self._player_pos is not None:
            idx_behind = next(
                (i for i, p in self._positions.items() if p == self._player_pos + 1),
                None)
            if idx_behind is not None:
                driver_behind_name = self.race_state.driver(idx_behind)["name"]

        ra_snapshot = {
            "gap_behind_ms": self._player_gap_behind,
            "gap_front_ms": self._player_gap_front,
            "drs_active": self._player_drs_active,
            "player_pos": self._player_pos,
            "player_lap": self._player_lap,
            "total_laps": getattr(self, "_total_laps", None),
            "driver_behind": driver_behind_name or "оппонент",
            "tyre_age": self._player_tyre_age,
            "tyre_wear": self._player_tyre_wear,
            "session_type": self._session_type,
        }
        race_event = self.race_analyzer.update(ra_snapshot)
        self._defense_tick()

        # Track Intelligence: resolve current track position (<1ms, no I/O)
        threat_active = (race_event is not None and race_event.type in ("attack", "battle"))
        track_ctx = None
        if self._track_manager and self._lap_distance_m is not None:
            track_ctx = self._track_manager.resolve(
                self._lap_distance_m,
                drs_active=self._player_drs_active,
                threat_active=threat_active,
            )

        strategy_result = self._strategy_module.tick(
            StrategySnapshot(
                player_lap=self._player_lap,
                total_laps=getattr(self, "_total_laps", None),
                player_pos=self._player_pos,
                gap_front_ms=self._player_gap_front,
                gap_behind_ms=self._player_gap_behind,
                gap_leader_ms=self._player_gap_leader,
                tyre_compound=self._player_tyre_compound,
                tyre_age=self._player_tyre_age,
                tyre_wear=self._player_tyre_wear,
                last_lap_ms=self._player_pace_ms,
                fuel=self._player_fuel,
                ers_percent=self._player_ers_percent,
                ers_deploy_mode=self._player_ers_deploy_mode,
                session_type=self._session_type,
                pit_status=self._player_pit_status,
            ),
            now,
            engineer_chatter_enabled=self._get_setting(
                "engineer_chatter_enabled", True),
        )

        self._ui_state.set_analysis(
            race_ai=self.race_analyzer.get_state(),
            strategy_ai=strategy_result.state,
            coach_ai=self.driver_coach.get_state(),
            rivals=self.rival_tracker.get_state(),
            track_ai=track_ctx.to_dict() if track_ctx is not None else None,
            track_name=(
                self._track_manager.track_name
                if self._track_manager is not None
                else self._track_city
            ),
        )

        for strategy_commentary_event in strategy_result.events:
            # Событие может нести СЕМАНТИЧЕСКИЙ КОД вместо готовой строки —
            # тогда формулировку даёт банк. Модуль стратегии до банка не
            # дотягивается сам: он чистый и не знает ни про сессию, ни про
            # dedupe_key, из которого берётся стабильный выбор варианта.
            code = strategy_commentary_event.pop("phrase_code", None)
            event_code = str(strategy_commentary_event.get("event_code") or "")
            # Пилот уже решил по этому предложению — не повторяем. Именно в
            # этом весь смысл петли: без подавления «нет» ничего не меняет.
            if (radio_policy.is_proposal(event_code)
                    and self._strategy_agreement.is_suppressed(event_code, now)):
                continue
            if code and not strategy_commentary_event.get("phrase"):
                strategy_commentary_event["phrase"] = self._render_engineer_phrase(
                    strategy_commentary_event, code)
                if not strategy_commentary_event["phrase"]:
                    continue
            if radio_policy.is_proposal(event_code):
                # Окно решения открывается на ПУБЛИКАЦИИ, а не на синтезе:
                # пилот может ответить сразу, как услышал.
                self._strategy_agreement.propose(event_code, now)
            self._commentary_events.publish(strategy_commentary_event)

        if race_event is not None:
            if now - self._last_race_ai_event_t >= 8.0:
                self._last_race_ai_event_t = now
                _code_map = {
                    "attack":       "ATTACK",
                    "battle":       "BATTLE",
                    "tyre_warning": "TYRE_WARN",
                    "final_lap":    "FINAL_LAP",
                }
                self._commentary_events.publish({
                    "event_code": _code_map.get(race_event.type, "ATTACK"),
                    "priority": race_event.priority,
                    "driver": race_event.driver,
                    "color": "#E4002B",
                    "race_ai_type": race_event.type,
                    "race_ai_data": {
                        **race_event.data,
                        "confidence": race_event.confidence,
                        "track": track_ctx.to_dict() if track_ctx else None,
                    },
                })

    def _build_ai_context(self, event: dict) -> str:
        """Собрать текстовый контекст гонки для ИИ. Для AMBIENT триггера нет
        (ИИ смотрит на общую картину); для реального события передаём его как триггер.

        Также передаём имя игрока (по машине, которой он реально управляет) —
        нужно персоне "calm", чтобы иногда обращаться по имени в духе реального
        радио (см. commentator/personas.py). None, если имя неизвестно — тогда
        персона не должна ничего придумывать."""
        trigger = None if event.get("event_code") == "AMBIENT" else event
        player_name = (first_name_of(self.race_state.driver(self._player_car_index)["name"])
                       if self._player_car_index < 22 else None)
        with self._engine_lock:
            return self.timeline.render(trigger, player_name=player_name)

    def _neighbor_names(self) -> tuple[str | None, str | None]:
        """Имена машин впереди/сзади игрока по текущим позициям (для дедупа ситуаций)."""
        ahead = behind = None
        pos = self._player_pos
        if pos:
            idx_ahead = next((i for i, p in self._positions.items() if p == pos - 1), None)
            idx_behind = next((i for i, p in self._positions.items() if p == pos + 1), None)
            if idx_ahead is not None:
                ahead = self.race_state.driver(idx_ahead)["name"]
            if idx_behind is not None:
                behind = self.race_state.driver(idx_behind)["name"]
        return ahead, behind

    def _handle_flashback(self) -> None:
        """Перемотка игрока: события до отката больше не актуальны.

        Сливаем очередь до-флэшбековых событий (иначе комментатор озвучит их уже
        после перемотки), сбрасываем транзитное состояние близости и дедуп, ставим
        короткую тишину. Лап-уровневую статистику (coach/strategy) не трогаем."""
        drained = self._commentary_events.clear()
        self.race_analyzer.reset_transient()
        self._situation_dedup.reset()
        self._engineer_topic_dedup.reset()
        self._strategy_module.reset("flashback")
        self._race_engineer.reset("flashback")
        self._session_history.clear()
        # Новая ветка таймлайна. Ревизия входит только в `dedupe_key`: физическая
        # ситуация (тот же погодный фронт, то же повреждение, та же фаза SC)
        # осталась той же, и дробить её историю нельзя — а вот высказывание о ней
        # пилот после перемотки не слышал и должен услышать снова. Заодно это
        # снимает блокировку дедупом по ключу из отменённого будущего.
        self._timeline_revision += 1
        self._cancel_pending_radio(RadioCancelReason.FLASHBACK)
        now = time.time()
        self._last_race_ai_event_t = now
        self._flashback_until = now + config.FLASHBACK_SILENCE
        _log.info("Flashback: drained %d queued event(s); timeline revision %d",
                  drained, self._timeline_revision)

    def _cancel_pending_radio(self, reason: RadioCancelReason) -> None:
        """Закрыть все ещё не прозвучавшие сообщения с указанной причиной.

        Без этого события «из будущего» остались бы в неизвестном состоянии:
        очередь их сбросила, а сами сообщения так и висели бы в `queued`."""
        with self._radio_lifecycle_lock:
            pending = [m for m in self._radio_lifecycle.values()
                       if not m.is_terminal]
        for message in pending:
            self._note_radio_cancel(message, reason)

    def _note_story_event(self, event: dict, enriched: dict) -> None:
        """Передать игрок-релевантное событие коллектору истории (Post-Race Story)."""
        code = event.get("event_code")
        if code not in ("OVTK", "PENA", "RTMT", "FTLP"):
            return
        lap = self._player_lap
        pidx = self._player_car_index
        if code == "OVTK":
            if event.get("overtaking_idx") == pidx:
                target = self.race_state.driver(
                    event.get("being_overtaken_idx"))["name"]
                self.story_collector.note_event("OVTK", lap, driver="player",
                                                target=target)
            return
        if event.get("vehicle_idx") == pidx:
            self.story_collector.note_event(code, lap,
                                            driver=enriched.get("driver"))

    def _generate_story(self, saved_path=None) -> None:
        """Собрать факты, сгенерировать историю, озвучить и показать. Фоновый поток."""
        try:
            if self._stop_event.is_set():
                return
            with self._engine_lock:
                grid = list(self._current_grid)
            coach = self.driver_coach.get_state()
            final_pos = next(
                (e.get("position") for e in grid
                 if e.get("vehicle_idx") == self._player_car_index),
                self._player_pos)
            # Final Classification (packet 8) — официальный подтверждённый
            # результат, если он УЖЕ пришёл к этому моменту (best-effort,
            # без ожидания — обычно приходит через несколько секунд ПОСЛЕ
            # CHQF, так что чаще всего это не сработает, но не стоит
            # усложнять поток блокировкой ради редкого случая). См. docs/
            # superpowers/plans/2026-07-19-tyre-sets-final-classification.md.
            if self._final_classification is not None:
                final_pos = self._final_classification.get("position", final_pos)
            track = TRACK_ID_TO_GP.get(self._track_id, ("Unknown",))[0]
            laps = self.recorder.laps()
            # Средний гэп по сектору за ВСЮ гонку к реальному F1 (Post-Race Story),
            # отдельно от per-lap sector-PB логики в _update_f1_benchmark (Task 3).
            weak_sector_vs_f1 = self.f1_benchmark.race_weak_sector(laps)
            # Прогресс с прошлого визита на эту трассу (Career Memory) — НЕ путать
            # с best_ever/личным рекордом из _update_career_memory.
            vs_last_visit = self.career_memory.story_facts(final_pos, laps)["vs_last_visit"]
            career_stats = career_stats_mod.compute_career_stats()
            self._career_stats_context_line = (
                career_stats_mod.context_line(career_stats) if career_stats else None)
            self._publish_career_recap(vs_last_visit, career_stats, final_pos)
            # analytics_context остаётся общим на весь движок (кормит и Voice
            # Q&A вне контекста истории — карьерная статистика там уместна
            # для любого session_type), поэтому пересчитываем его как обычно.
            self._refresh_analytics_context()
            facts = self.story_collector.facts(
                final_position=final_pos, laps=laps,
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track,
                weak_sector_vs_f1=weak_sector_vs_f1,
                vs_last_visit=vs_last_visit,
                career_stats=career_stats,
                teammate_result=self._teammate_race_result(final_pos),
                session_type=self._session_type)
            # Но в ПРОМПТ ИТОГА карьерная статистика не должна попадать для
            # квалификации/практики — facts() уже гасит её в факт-блоке (см.
            # core/race_story.py), а analytics_context (gp_context) — отдельный
            # канал, который её туда протаскивал в обход этого гейта. Вычитаем
            # именно эту часть только для истории, не трогая общий контекст.
            story_gp_context = self.commentator.analytics_context
            if self._session_type != "race" and self._career_stats_context_line:
                parts = [p for p in (self._f1_context_line, self._career_context_line) if p]
                story_gp_context = " ".join(parts) if parts else None
            text, text_source = _story.generate_with_source(
                facts, self.ai, self.commentator.persona, story_gp_context,
                session_type=self._session_type)
            if not text or self._stop_event.is_set():
                return
            voiced = self._should_voice({"event_code": "STORY", "priority": "normal"})
            self._ui_state.set_race_story({
                "text": text, "track": track,
                "final_position": final_pos, "session_type": self._session_type,
                # "llm" | "fallback" — шаблонный итог визуально неотличим от
                # написанного моделью, экран «Разбор» показывает это явно.
                "source": text_source,
                "ts": time.time(),
            })
            self._ui_state.append_feed({
                "time": datetime.now().strftime("%H:%M:%S"),
                "event_code": "STORY", "phrase": text,
                "color": "#A78BFA", "driver": "",
                "muted": not voiced, "channel": "commentary"})
            if voiced:
                self.voice.say(text, priority="normal")
            if saved_path is not None:
                try:
                    _archive.attach_story(saved_path, text)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            _log.warning("race story generation failed: %s", exc)

    def _pre_race_pep_talk(self) -> None:
        """Точка входа фонового потока: пауза (даём игроку осмотреться на
        экране стратегии), затем основная логика. Разделено на два метода,
        чтобы тесты могли вызывать _generate_pre_race_pep_talk() напрямую,
        без реального ожидания config.PRE_RACE_PEP_TALK_DELAY_S секунд."""
        if self._stop_event.wait(config.PRE_RACE_PEP_TALK_DELAY_S):
            return
        self._generate_pre_race_pep_talk()

    def _generate_pre_race_pep_talk(self) -> None:
        """Собрать факты последней гонки карьеры, сгенерировать пред-гоночную
        реплику инженера, озвучить и показать в ленте."""
        try:
            if self._session_type != "race":
                _log.info("DIAG pep_talk: aborted, session_type=%s (left before delay elapsed)",
                          self._session_type)
                return  # игрок успел выйти из подготовки до срабатывания
            last_race = _archive.get_last_race()
            facts = _pep_talk_facts.facts(last_race)
            if facts is None:
                _log.info("DIAG pep_talk: no facts (no prior archived race?) last_race=%s",
                          last_race)
                return  # первая гонка карьеры — инженеру не с чем сравнивать
            text = _pep_talk.generate(facts, self.ai, self.commentator.persona)
            if not text:
                _log.info("DIAG pep_talk: generate() returned empty text")
                return
            voiced = self._should_voice({"event_code": "PRE_RACE_PEP_TALK", "priority": "normal"})
            _log.info("DIAG pep_talk firing: voiced=%s text=%r", voiced, text)
            self._ui_state.append_feed({
                "time": datetime.now().strftime("%H:%M:%S"),
                "event_code": "PRE_RACE_PEP_TALK", "phrase": text,
                "color": "#38BDF8", "driver": "",
                "muted": not voiced, "channel": "commentary"})
            if voiced:
                self.voice.say(text, priority="normal", persona=SLOT_ENGINEER)
        except Exception as exc:  # noqa: BLE001
            _log.warning("pre-race pep talk generation failed: %s", exc)

    def generate_story_now(self) -> bool:
        """Ручной триггер истории (API). False если данных нет."""
        if not self.recorder.laps() and self.story_collector._start_position is None:
            return False
        self._spawn_thread(
            self._generate_story, name="race-story-manual", task=True)
        return True

    def replay_story(self) -> bool:
        """Переозвучить текущую историю. False если её нет."""
        rs = self._ui_state.race_story()
        if not rs or not rs.get("text"):
            return False
        self.voice.say(rs["text"], priority="normal")
        return True

    # ------------------------------------------------------------
    # Voice Q&A (push-to-talk)
    # ------------------------------------------------------------

    def ask_voice_question(self) -> dict:
        """Push-to-talk: слушает вопрос, распознаёт, отвечает голосом. Гейты:
        (1) сейчас играет critical-реплика -> busy сразу, конвейер не запускаем
        (не тратим 5-8с записи+STT+LLM на ответ, который лёг бы в очередь позади
        критики); (2) уже идёт другой вопрос -> busy. Иначе — фоновый поток."""
        if self.voice.is_critical_active:
            return {"ok": False, "busy": True, "reason": "critical"}
        if not self._ui_state.begin_voice_query():
            return {"ok": False, "busy": True, "reason": "in_progress"}
        self._spawn_thread(
            self._run_voice_question, name="voice-question", task=True)
        return {"ok": True}

    def _set_voice_query(self, **updates) -> None:
        self._ui_state.update_voice_query(**updates)
        # Тот же переход — в сессию радио: панель Team Radio читает одно
        # состояние, а не склеивает два независимых.
        status = updates.get("status")
        if status is not None:
            self.radio_session.set_ptt(
                status,
                driver_text=updates.get("question"),
                engineer_text=updates.get("answer"),
                error=updates.get("error"))

    def _run_voice_question(self) -> None:
        """Слушает -> распознаёт -> отвечает. Фоновый поток (см. ask_voice_question);
        каждый статус пишется в state["voice_query"] для UI-поллинга через /api/state.
        Обёрнуто в try/except: неожиданный сбой должен закрыть busy-guard статусом
        error, а не оставить voice_query подвешенным в thinking/recognizing."""
        try:
            if self._stt is None or not self._yandex_healthy:
                self._set_voice_query(status="error", error="Распознавание недоступно")
                return

            self.voice.play_beep()
            audio = self._voice_listener.record(config.VOICE_QUESTION_MAX_SEC)
            if audio is None:
                self._set_voice_query(status="error", error="Микрофон недоступен")
                return

            self._set_voice_query(status="recognizing")
            question = self._stt.recognize(audio)
            if not question:
                self._set_voice_query(status="error", error="Не расслышал вопрос")
                return

            self._set_voice_query(status="thinking", question=question)
            self.radio_session.note_driver_line(question)
            # Решение по висящему предложению разбирается РАНЬШЕ тем, но ПОЗЖЕ
            # команд: «замолчи» остаётся командой в любой обстановке. И только
            # при живом предложении — иначе «да» посреди гонки стало бы
            # согласием неизвестно на что.
            decision_answer = self._resolve_strategy_decision(question)
            command = _radio_answer.classify_command(question)
            topic = None
            if decision_answer is not None:
                answer = decision_answer
            elif command is not None:
                answer = self._execute_voice_command(command)
            else:
                topic = _radio_answer.classify_topic(question)
                total_laps = getattr(self, "_total_laps", None)
                laps_remaining = (
                    total_laps - self._player_lap
                    if total_laps and self._player_lap is not None
                    else None
                )
                ahead_name, behind_name = self._neighbor_names()
                answer = _radio_answer.answer_radio_question(
                    question, weather=self._current_weather,
                    rain_forecast=self._rain_forecast,
                    gap_front_ms=self._player_gap_front,
                    gap_behind_ms=self._player_gap_behind,
                    tyre_wear=self._player_tyre_wear,
                    ahead_name=ahead_name, behind_name=behind_name,
                    position=self._player_pos,
                    penalty_count=self._player_penalty_count,
                    penalty_seconds=self._player_penalty_seconds,
                    damage=self._player_damage, fuel_kg=self._player_fuel,
                    ers_percent=self._player_ers_percent,
                    ers_deploy_mode=self._player_ers_deploy_mode,
                    laps_remaining=laps_remaining,
                    tyre_age=self._player_tyre_age,
                    tyre_compound=self._player_tyre_compound,
                    tyre_sets_available=self._player_tyre_sets_available,
                    teammate_report=self._teammate_report(),
                    strategy=self._ui_state.section("strategy_ai"),
                    safety_car_status=self._safety_car_status,
                    last_lap_ms=self._player_pace_ms)

                # Пилот отвечает на вопрос инженера, а не спрашивает сам.
                # Распознанную тему обрабатываем как обычно — «износ большой» в
                # ответ на «как шины?» вполне заслуживает реальных цифр. А вот
                # нераспознанное («нормально», «плохо, скользят») без этой ветки
                # получило бы OFF_TOPIC_ANSWER: отповедь на вопрос, который
                # инженер сам же и задал.
                if (answer == _radio_answer.OFF_TOPIC_ANSWER
                        and self._ptt_reply_expected(time.time())):
                    answer = radio_phrases.acknowledge(
                        f"{self._radio_session_id}:{question}")
                    self._awaiting_driver_reply_until = 0.0

            voiced = self._should_voice({"event_code": "USER_Q", "priority": "normal"})
            self._ui_state.append_feed({
                "time": datetime.now().strftime("%H:%M:%S"),
                "event_code": "USER_Q",
                "phrase": f"{question} — {answer}",
                "color": "#60A5FA", "driver": "",
                "muted": not voiced, "channel": "commentary"})
            self._ui_state.update_voice_query(status="done", answer=answer)
            if voiced:
                self._say_ptt_answer(answer, topic)
            else:
                self._note_ptt_answer_unvoiced(answer, topic)
        except Exception as exc:  # noqa: BLE001
            _log.warning("voice question pipeline failed: %s", exc)
            self._set_voice_query(status="error", error="Внутренняя ошибка")

    def _talk_more(self) -> str:
        """«Говори чаще» — команда, которая обязана РЕАЛЬНО менять частоту.

        Раньше она включала два тумблера и всегда отвечала «буду чаще». Если оба
        уже были включены — а это обычное состояние — она не меняла ничего и
        врала подтверждением. Теперь она вдобавок укорачивает минимальную паузу
        между некритичными репликами (тот же гейт, что читает
        `_commentary_loop`), и, если укорачивать больше некуда, говорит об этом
        прямо."""
        changed: list[str] = []
        updates: dict[str, object] = {}

        for key in ("engineer_chatter_enabled", "commentary_enabled"):
            if not self.settings.get(key, True):
                updates[key] = True
                changed.append(key)

        current_gap = float(self._get_setting("min_comment_gap",
                                              config.MIN_COMMENT_GAP))
        new_gap = max(_TALK_MORE_GAP_FLOOR, current_gap - _TALK_MORE_GAP_STEP)
        if new_gap < current_gap:
            updates["min_comment_gap"] = new_gap
            changed.append("min_comment_gap")

        if updates:
            self.apply_settings(updates)

        if not changed:
            # Честный ответ вместо подтверждения, за которым ничего не стоит.
            return "Уже на максимальной частоте."
        if "min_comment_gap" in changed:
            return "Понял, буду докладывать чаще."
        return "Понял, снова на связи."

    def _ptt_answer_message(self, answer: str, topic: str | None = None):
        """`RadioMessage` для ответа на запрос пилота.

        Ответ на PTT — такое же инженерское сообщение, как автоматическая
        сводка: он обязан попасть в историю радио тем же способом (ТЗ §13) и
        стать тем, что повторит «повтори» (ТЗ §12). Раньше он уходил прямо в
        `voice.say()` в обход конвейера и потому не существовал ни для истории,
        ни для повтора.

        Код события выбирается по ТЕМЕ вопроса, и это не косметика. Справочный
        ответ («износ 48%», «данных нет») живёт без TTL — пилот спросил сам, и
        опоздавший ответ лучше молчания. А вот ДЕЙСТВЕННЫЙ ответ обязан пройти
        те же проверки актуальности, что автоматическая реплика: «Да, окно
        открыто. Заезжай.» через 15 секунд, когда игрок уже в пит-лейне, —
        вредная неправда, и то, что вопрос задал сам пилот, этого не меняет."""
        draft = {
            "event_code": _PTT_ANSWER_EVENT_CODE.get(topic or "", "USER_Q"),
            "priority": "normal",
            "speaker": SPEAKER_ENGINEER, "driver": "",
            **radio_plumbing(asked_at=time.time()),
        }
        return self._build_radio_message(draft, answer)

    def _say_ptt_answer(self, answer: str, topic: str | None = None) -> None:
        message = self._ptt_answer_message(answer, topic)
        if message is None:
            self.voice.say(answer, priority="normal")
            return
        self.radio_session.note(message)
        self.voice.say(
            answer, priority="normal",
            persona=message.voice_persona,
            urgency=message.urgency, message_id=message.id,
            prepare=self._make_prepare(message),
            still_valid=self._make_playback_gate(message))

    def _note_ptt_answer_unvoiced(self, answer: str,
                                  topic: str | None = None) -> None:
        """Ответ показан, но не озвучен — он всё равно завершён, не потерян."""
        message = self._ptt_answer_message(answer, topic)
        if message is not None:
            self.radio_session.note(message)
            self._note_radio_state(message, STATE_COMPLETED)

    def _execute_voice_command(self, command: str) -> str:
        """Голосовая команда ("замолчи"/"смени персону") поверх уже
        существующих хоткеев (core/hotkeys.py::GlobalHotkeyManager) — тот же
        apply_settings(), не дублирует его логику, второй вызывающий той же
        публичной точки входа. Возвращает готовую фразу-подтверждение
        (действие ИСПОЛНЯЕТСЯ здесь же, до возврата)."""
        if command == "toggle_commentary":
            enabled = not self.settings.get("commentary_enabled", True)
            self.apply_settings({"commentary_enabled": enabled})
            return "Хорошо, снова на связи." if enabled else "Понял, молчу."
        if command == "next_persona":
            current = self.settings.get("persona", "tv")
            idx = (_VOICE_COMMAND_PERSONAS.index(current)
                   if current in _VOICE_COMMAND_PERSONAS else 0)
            new_persona = _VOICE_COMMAND_PERSONAS[(idx + 1) % len(_VOICE_COMMAND_PERSONAS)]
            self.apply_settings({"persona": new_persona})
            label = _VOICE_COMMAND_PERSONA_LABEL.get(new_persona, new_persona)
            return f"Переключаю на {label}."
        if command == "repeat":
            # Повторяем ТОЛЬКО последнюю полностью прозвучавшую реплику
            # инженера. Ни последнее событие, ни текст комментатора, ни
            # прерванную на полуслове, ни отменённую до озвучки: пилот просит
            # повторить то, что он слышал не до конца, а не то, чего не было.
            text = self.radio_session.repeatable_text()
            return text or "Повторять пока нечего."
        if command == "talk_more":
            return self._talk_more()
        return _radio_answer.OFF_TOPIC_ANSWER  # unreachable — classify_command's contract

    def test_mic(self) -> dict:
        """Push-to-talk diagnostics (Settings → Voice, кнопка «Проверить»): запись
        config.MIC_TEST_SEC + воспроизведение обратно текущим self._voice_listener.
        Синхронно (в отличие от ask_voice_question) — нет пересечения с
        critical-гейтом TTS-очереди, действие короткое и явно инициировано кликом."""
        audio = self._voice_listener.record(config.MIC_TEST_SEC)
        if audio is None:
            return {"ok": False, "error": "Микрофон недоступен"}
        try:
            play_back(audio)
        except Exception as exc:  # noqa: BLE001
            _log.warning("mic test playback failed: %s", exc)
            return {"ok": False, "error": "Не удалось воспроизвести"}
        return {"ok": True}

    def _start_f1_benchmark_load(self, track_id: int) -> None:
        """Фоновая загрузка эталона трассы из Jolpica (сеть — только тут, не из потока телеметрии)."""
        def _run() -> None:
            try:
                # Реальный год игровой сессии — приоритет над статичным config.F1_SEASON,
                # иначе эталон трассы никогда не подстраивается под Season Pack/новый регламент.
                self.f1_benchmark.load(track_id, self._game_year or int(config.F1_SEASON))
            except Exception as exc:  # noqa: BLE001
                _log.warning("F1 benchmark load failed: %s", exc)
        self._spawn_thread(_run, name="f1-benchmark-load", task=True)

    def _start_career_memory_load(self, track_id: int) -> None:
        """Фоновая загрузка личной истории трассы из архива (диск, не сеть — но
        всё равно фоновый поток, чтобы не блокировать телеметрию на I/O)."""
        def _run() -> None:
            try:
                self.career_memory.load(track_id)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Career memory load failed: %s", exc)
        self._spawn_thread(_run, name="career-memory-load", task=True)

    def _update_f1_benchmark(self) -> None:
        """Каждый завершённый круг: гэп к эталону → HUD + контекст; на личном рекорде —
        озвучка. Секторы (cmp["sectors"]) — независимая надстройка, может быть None."""
        if not self.f1_benchmark.ready:
            return
        cmp = self.f1_benchmark.compare(self.recorder.laps())
        if cmp is None:
            return
        self._ui_state.set_f1_benchmark({
            "gap_ms": cmp["gap_ms"], "f1_driver": cmp["f1_driver"],
            "f1_time_ms": cmp["f1_time_ms"], "player_best_ms": cmp["player_best_ms"],
            "event": cmp["event"], "year": cmp["year"], "source": cmp["source"],
            "sectors": cmp["sectors"], "sectors_source": cmp["sectors_source"],
            "sectors_blocked": cmp["sectors_blocked"],
            "interpretation": cmp["interpretation"],
            "comparison_disclaimer": cmp["comparison_disclaimer"],
        })
        # Кем управляет игрок в игре — если это тот же пилот, что и реальный эталон
        # (например, игрок выбрал машину Ферстаппена), f1_benchmark не должен
        # называть его в третьем лице (см. core/f1_benchmark._is_player_reference).
        player_name = (self.race_state.driver(self._player_car_index)["name"]
                       if self._player_car_index < 22 else None)
        self._f1_context_line = self.f1_benchmark.context_line(cmp, player_name)
        self._refresh_analytics_context()
        milestones = self._f1_comparison_progress.observe(cmp)
        if milestones.lap_improved:
            self._commentary_events.publish({
                "event_code": "F1_BENCH", "priority": "normal",
                "phrase": self.f1_benchmark.pb_line(cmp, player_name),
                "color": "#34D399", "driver": ""})
        if milestones.sector_improved is not None:
            best_n = milestones.sector_improved
            self._commentary_events.publish({
                "event_code": "F1_SECTOR_BENCH", "priority": "normal",
                "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
                "color": "#34D399", "driver": ""})

    def _update_career_memory(self) -> None:
        """Каждый завершённый круг: гэп к ЛИЧНОМУ рекорду трассы → HUD; на новом
        личном рекорде (полный круг ИЛИ сектор) — озвучка. Независимая надстройка
        от _update_f1_benchmark — разные эталоны (свой архив vs реальный F1),
        разные события (CAREER_PB/CAREER_SECTOR_PB vs F1_BENCH/F1_SECTOR_BENCH)."""
        if not self.career_memory.ready:
            return
        cmp = self.career_memory.compare(self.recorder.laps())
        if cmp is None:
            return
        self._ui_state.set_career_memory({
            "gap_ms": cmp["gap_ms"], "player_best_ms": cmp["player_best_ms"],
            "best_ever_ms": cmp["best_ever_ms"], "best_ever_date": cmp["best_ever_date"],
            "sectors": cmp["sectors"],
        })
        self._career_context_line = self.career_memory.context_line(cmp)
        self._refresh_analytics_context()
        milestones = self._career_comparison_progress.observe(cmp)
        if milestones.lap_improved:
            self._career_pb_this_race = True
            self._commentary_events.publish({
                "event_code": "CAREER_PB", "priority": "normal",
                "phrase": self.career_memory.pb_line(cmp),
                "color": "#60A5FA", "driver": "",
                "vehicle_idx": self._player_car_index,
                "gap_ms": cmp["gap_ms"], "player_best_ms": cmp["player_best_ms"],
                "best_ever_ms": cmp["best_ever_ms"], "best_ever_date": cmp["best_ever_date"]})
        if milestones.sector_improved is not None:
            best_n = milestones.sector_improved
            self._career_pb_this_race = True
            self._commentary_events.publish({
                "event_code": "CAREER_SECTOR_PB", "priority": "normal",
                "phrase": self.career_memory.sector_pb_line(best_n, cmp["sectors"][best_n]),
                "color": "#60A5FA", "driver": "",
                "vehicle_idx": self._player_car_index,
                "sector": best_n, "sector_gap_ms": cmp["sectors"][best_n]["gap_ms"],
                "sector_player_ms": cmp["sectors"][best_n]["player_ms"]})

    def _publish_career_recap(self, vs_last_visit: dict | None, career_stats: dict,
                               final_pos: int | None) -> None:
        """Race-finish career recap for RaceFeed (player_progression category,
        Player's Garage reporter) — reuses facts already computed for Post-Race
        Story (see _generate_story), adding an importance score so the Editor
        can decide whether this finish is actually worth a post. Signs per
        core/career_memory.py::story_facts(): position_delta > 0 = better
        finish than last visit; laptime_delta_ms < 0 = faster than last visit.
        Routed to CHANNEL_OVERLAY (silent) by commentator/channel_router.py —
        this event has no "phrase" and must never be voiced, since Post-Race
        Story already narrates the finish out loud.
        Can fire more than once for the same finish if generate_story_now() is
        manually re-triggered after final classification arrives late —
        RaceFeed's fact-based dedup handles this as a legitimate story
        "update", not a bug, since the underlying facts genuinely changed."""
        is_podium = final_pos is not None and final_pos <= 3
        improved = self._career_pb_this_race or (
            vs_last_visit is not None
            and (vs_last_visit["position_delta"] > 0 or vs_last_visit["laptime_delta_ms"] < 0)
        )
        if is_podium:
            importance = 90
        elif improved:
            importance = 70
        else:
            importance = 40
        self._commentary_events.publish({
            "event_code": "CAREER_RECAP", "priority": "normal",
            "driver": self._player_driver_name(), "color": "#60A5FA",
            "vehicle_idx": self._player_car_index,
            "importance": importance,
            "vs_last_visit": vs_last_visit,
            "career_stats": career_stats,
        })

    def _build_telemetry_adapter(self):
        if self._telemetry_source == "iracing":
            return IRacingTelemetryAdapter(transport_factory=IRacingTelemetry)
        return F1TelemetryAdapter(
            config.UDP_IP,
            config.UDP_PORT,
            transport_factory=Telemetry,
        )

    def _telemetry_loop(self) -> None:
        """Consume one source-neutral stream from the selected telemetry adapter."""
        adapter = self._build_telemetry_adapter()
        self._telemetry_instance = adapter
        self._total_laps = None
        try:
            for message in adapter.listen(self._stop_event):
                if self._stop_event.is_set():
                    break
                self._consume_telemetry_message(message)
        finally:
            adapter.close()
            if self._telemetry_instance is adapter:
                self._telemetry_instance = None

    def _consume_telemetry_message(self, message) -> None:
        """Consume one canonical message emitted by any telemetry adapter."""
        if isinstance(message, SourceStatus):
            self._telemetry_source_status = {
                "code": message.code, "detail": message.detail}
            if message.code != "ok":
                # Источник не открылся — пакетов заведомо нет. Гасим «связь
                # есть» явно, иначе UI унаследует состояние прошлой сессии.
                self._telemetry_connected = False
                self._ui_state.set_connected(False)
                _log.warning("Источник телеметрии недоступен: %s (%s)",
                             message.code, message.detail)
        elif isinstance(message, ConnectionChanged):
            self._telemetry_connected = message.connected
            self._ui_state.set_connected(message.connected)
            if message.connected:
                self._telemetry_last_packet_at = time.time()
        elif isinstance(message, TelemetryDelta):
            self._consume_telemetry_delta(message)
        elif isinstance(message, TelemetryRaceEvent):
            self._handle_race_event(message.event)

    def _consume_telemetry_delta(self, delta: TelemetryDelta) -> None:
        if delta.kind in {
            "session", "lap_data", "car_telemetry", "car_status", "car_damage",
        }:
            self._apply_telemetry_delta(delta)
            return

        self._apply_telemetry_identity(delta)
        if delta.kind == "motion":
            self._spotter_tick(delta.payload)
        elif delta.kind == "tyre_sets":
            self._update_tyre_sets(delta.payload)
        elif delta.kind == "final_classification":
            self._update_final_classification(delta.payload)
        elif delta.kind == "final_classification_grid":
            self._update_final_classification_grid(delta.payload)
        elif delta.kind == "session_history":
            self._update_session_history(delta.payload)
        elif delta.kind == "participants":
            if _DIAG and not getattr(self, "_diag_hdr_logged", False):
                self._diag_hdr_logged = True
                _log.warning(
                    "DIAG header: game_year=%s player_car_index=%s",
                    delta.game_year,
                    delta.player_car_index,
                )
            drivers = delta.payload
            # F1 metadata must not be projected onto iRacing identities.
            if self._telemetry_source == "f1":
                drivers = self.metadata.enrich_drivers(drivers)
            self.race_state.update_drivers(drivers)
            self._ui_state.set_metadata_loaded(
                self.metadata.loaded if self._telemetry_source == "f1" else False)

    def _handle_race_event(self, event: dict) -> None:
        """Apply an event already decoded by a telemetry adapter."""

        # Track DRS state for race_ai threat detection
        _ec = event.get("event_code")
        if _ec == "DRSE":
            self._player_drs_active = True
        elif _ec == "DRSD":
            self._player_drs_active = False

        # Phase B (Safety Car/VSC/красный флаг): подменяем raw SCAR на
        # синтетический event_code ДО enrich()/record_event(), чтобы весь
        # остальной пайплайн (таймлайн, importance, channel routing, LLM-
        # контекст, шаблоны) видел его как обычное major-событие — тот же
        # трюк, что и с DRSE/DRSD выше, просто в другую сторону (не флаг,
        # а подмена самого event). Formation Lap SC и переходное "Returned"
        # не announcement-worthy — derive_safety_car_event() возвращает
        # None, событие тихо отбрасывается (RDFL отдельной проводки не
        # требует, идёт как есть, см. docs/superpowers/plans/
        # 2026-07-19-safety-car-vsc-red-flag.md).
        if _ec == "SCAR":
            derived = derive_safety_car_event(
                event.get("safety_car_type", 0), event.get("event_reason", 0))
            if derived is None:
                return
            # Личность ОДНОЙ фазы Safety Car (ТЗ §9). Три кода (выехал / уходит
            # / чисто) — стадии одной ситуации, поэтому эпизод считается только
            # на деплое. Дедуп при этом различает стадии по dedupe_key, иначе
            # «трасса чистая» проглотилось бы как повтор (см.
            # core/radio/situations.py).
            if derived["event_code"] == "SAFETY_CAR_DEPLOYED":
                self._sc_episode += 1
            event = {**event, **derived,
                     **radio_plumbing(sc_episode=self._sc_episode)}

        # Flashback: игрок перемотал момент — гасим очередь до-флэшбековых событий
        # и сбрасываем состояние, иначе комментатор спамит уже неактуальным.
        if _ec == "FLBK":
            self._handle_flashback()
            self._ui_state.append_feed({
                "time": datetime.now().strftime("%H:%M:%S"),
                "event_code": "FLBK",
                "phrase": "Перемотка — переигрываем эпизод.",
                "color": "#9CA3AF",
                "driver": "",
                "muted": True,
                "channel": "overlay",
            })
            return

        enriched = self.race_state.enrich(event)
        # COLL тоже двухмашинное событие (vehicle1_idx/vehicle2_idx), но стиль
        # соперника сознательно ограничен OVTK (design spec 2026-07-05-race-memory)
        # — не забыто, не техническое ограничение get_style().
        if enriched.get("event_code") == "OVTK":
            overtaking_idx = enriched.get("overtaking_idx")
            being_overtaken_idx = enriched.get("being_overtaken_idx")
            now = time.time()
            if self._session_type == "race" and isinstance(overtaking_idx, int):
                self._race_overtakes_by_driver[overtaking_idx] = (
                    self._race_overtakes_by_driver.get(overtaking_idx, 0) + 1
                )
            if self._player_car_index in (overtaking_idx, being_overtaken_idx):
                self._race_engineer.note_overtake(now)
            if being_overtaken_idx == self._player_car_index:
                # Defense-tracker suppression (docs/superpowers/plans/2026-07-20-
                # defense-event-damage-phrase-variety.md) — позиция реально
                # потеряна, не защищена, не объявлять "удержал позицию".
                self._last_overtaken_t = now
            enriched["driver_style"] = self.rival_tracker.get_style(overtaking_idx)
            enriched["target_style"] = self.rival_tracker.get_style(being_overtaken_idx)
            enriched["driver_recent_mistake"] = self.rival_tracker.get_recent_mistake(overtaking_idx, now)
            enriched["target_recent_mistake"] = self.rival_tracker.get_recent_mistake(being_overtaken_idx, now)
            enriched["driver_tyre_age"] = self.rival_tracker.get_tyre_age(overtaking_idx)
            enriched["target_tyre_age"] = self.rival_tracker.get_tyre_age(being_overtaken_idx)
            # Хвалим только за СВОЙ обгон: направление здесь несёт смысл, и
            # перепутать его значит поздравить пилота с потерей позиции.
            # Только гонка — в практике машины обгоняют друг друга непрерывно,
            # и похвала там превратилась бы в фон (та же причина, по которой
            # гонкой ограничены _leader_change_tick и _maybe_announce_pit_exit).
            if (overtaking_idx == self._player_car_index
                    and self._session_type == "race"):
                self._publish_engineer_line("PRAISE_OVERTAKE", "praise.overtake")
        elif (enriched.get("event_code") == "FTLP"
                and self._event_involves(enriched, self._player_car_index)):
            # Быстрейший круг вне гонки не глушим: в квалификации и практике он
            # и есть смысл заезда.
            self._publish_engineer_line("PRAISE_FASTEST_LAP", "praise.fastest_lap")
        self.race_state.record_event(event)
        self._note_story_event(event, enriched)
        with self._engine_lock:
            self.timeline.record_event(enriched)

        # Analytics: session lifecycle hooks
        code = event.get("event_code")
        if code == "SSTA":
            self._session_active = True
            # Start every race with freshly shuffled commentary/radio decks.
            # Pools still contain familiar vocabulary, but their delivery arc
            # and first lines change from one start to the next.
            reset_phrase_cycles()
            # Тот же смысл для банка инженера: анти-повтор помнит, что уже
            # прозвучало, и новый заезд обязан начинаться с чистого листа
            # (иначе первая реплика гонки сдвигается из-за прошлой).
            radio_variety.reset()
            self._engineer_topic_dedup.reset()
            # Новый заезд — соперники впереди другие, а те же самые машины к
            # этому моменту в другом состоянии. Без сброса инженер молчал бы про
            # свежую резину, потому что «уже говорил» — в прошлой гонке.
            self._rival_intel.reset("session_started")
            # Договорённости прошлого заезда к новому отношения не имеют.
            self._strategy_agreement.reset()
            self.commentator.reset_session()
            self.recorder.reset()
            with self._engine_lock:
                self.timeline.reset()
            self._session_events = []
            self._prev_lap = 0
            self._current_lap_pit = False
            self._last_completed_lap_was_pit = False
            self._damage_announced = {
                "wing": False, "floor": False, "gearbox": False, "engine": False,
            }
            self._strategy_module.reset("session_started")
            self._ui_state.reset_session_view()
            self._race_engineer.reset("session_started")
            # Known limitation (see Task 10/14 review history): reset() runs on
            # this thread but races (narrow window) with RaceFeedEngine's own
            # worker thread touching StoryMemory concurrently — accepted for
            # Phase 1 (worst case: one dropped/misfiled event right at a
            # session boundary, not a crash or cross-session corruption).
            if self._race_feed is not None:
                self._race_feed.reset(session_type=self._session_type)
            self._session_history.clear()
            self._grid_tyre_compounds.clear()
            self._last_overtaken_t = 0.0
            self._safety_car_status = 0
            self._sc_episode = 0
            self._rain_seen_this_race = False
            # Новый заезд — новая идентичность радио-ситуаций. Счётчики трекеров
            # начинают нумерацию заново, и без этого первая ситуация нового
            # заезда совпала бы с первой ситуацией прошлого.
            self._radio_session_id = self._new_radio_session_id()
            self._cancel_pending_radio(RadioCancelReason.SESSION_RESET)
            self.radio_session.reset()
            self._radio_lifecycle.clear()
            self._radio_newest.clear()
            self._timeline_revision = 0
            self._player_penalty_count = 0
            self._player_penalty_seconds = 0
            self._player_tyre_sets_available = None
            self._player_tyre_sets_fitted = None
            self._final_classification = None
            self._final_classification_grid = []
            self._reality_result_sent = False
            self.story_collector.reset()
            self._story_fired = False
            self._session_result_fired = False
            self._f1_comparison_progress.reset()
            self._f1_context_line = None
            self._career_comparison_progress.reset()
            self._career_context_line = None
            self._career_pb_this_race = False
            self._championship_recorded = False
            self._race_overtakes_by_driver.clear()
            # В отличие от _career_context_line (трековый), _career_stats_context_line
            # — кросс-трековый агрегат: сбрасывается только тут, на новой гонке, а не
            # при смене трассы (см. комментарий в блоке смены трассы выше по файлу).
            self._career_stats_context_line = None
            self._refresh_analytics_context()
            self._ui_state.set_safety_car_status(0)
        elif code == "STLG":
            self._session_events.append(code)
            if self._race_feed is not None:
                try:
                    self._race_feed.lock_prediction()
                except Exception:
                    _log.warning("RaceFeed prediction lock failed", exc_info=True)
        elif code in ("CHQF", "SEND"):
            self._session_active = False
            self._session_events.append(code)
            self._strategy_module.reset("session_ended")
            self._ui_state.set_strategy(self._strategy_module.analyzer.get_state())
            self._race_engineer.reset("session_ended")
            self._session_history.clear()
            track_name = TRACK_ID_TO_GP.get(self._track_id, ("Unknown", "Unknown"))[0]
            pidx = self._player_car_index
            pos = self._positions.get(pidx)
            saved_path = self.recorder.finalize(
                track_id=self._track_id, track_name=track_name,
                session_type=self._session_type, final_position=pos,
                events=list(self._session_events),
                game_year=self._game_year,
            )
            # Итог заезда голосом инженера. Едж-триггер по _session_result_fired:
            # CHQF — событие СЕССИИ без vehicle_idx, но повтор пакета (или
            # перезаезд) не должен давать второй итог. Позиция берётся из
            # live-снимка _positions; её отсутствие (зритель, потерянный
            # LapData) означает молчание — банк откажет на required-поле, и
            # _publish_engineer_line не опубликует пустую фразу.
            if code == "CHQF" and not self._session_result_fired:
                self._session_result_fired = True
                if pos is not None:
                    self._publish_engineer_line(
                        "SESSION_RESULT", "session.result",
                        {"position": radio_resolver.position_word(pos)})
            if (code == "CHQF"
                    and self._session_type in ("race", "qualifying", "practice")
                    and not self._story_fired):
                self._story_fired = True
                self._spawn_thread(
                    self._generate_story, args=(saved_path,),
                    name="race-story", task=True)
        else:
            self._session_events.append(code)

        # Компаньон-реплика к трек-лимитному PENA игрока — короткая фраза
        # голосом инженера рядом с уже существующей (не изменяемой!) драмой
        # комментатора про штраф. note_penalty() вызывается БЕЗУСЛОВНО (даже
        # если тумблер выключен) — она обновляет единое окно подавления
        # (симметричное: работает в обе стороны порядка пакетов LapData/Event,
        # см. TrackLimitsTracker), это подавление не должно ломаться от
        # переключения тумблера посреди гонки. Возврат note_penalty() —
        # False, если живое предупреждение по тому же инциденту уже
        # прозвучало только что (обратный порядок пакетов, найдено финальным
        # сквозным ревью) — тогда компаньон-реплика не дублирует его.
        # См. spec 2026-07-11-track-limits-engineer-toggle-design.md.
        if code == "PENA":
            # ВРЕМЕННАЯ диагностика (см. чат): реальный infringement_type/
            # vehicle_idx с байтов игры, чтобы сверить с TRACK_LIMITS_INFRINGEMENT_TYPES.
            _log.info(
                "DIAG PENA vehicle_idx=%s player_car_index=%s infringement_type=%s "
                "in_track_limits_set=%s",
                enriched.get("vehicle_idx"), self._player_car_index,
                enriched.get("infringement_type"),
                enriched.get("infringement_type") in TRACK_LIMITS_INFRINGEMENT_TYPES)
        if code == "PENA" and enriched.get("vehicle_idx") == self._player_car_index:
            # Voice Q&A "штрафы" (docs/superpowers/plans/2026-07-19-voice-qa-expansion.md)
            # — считаем ЛЮБОЙ штраф игрока, не только трек-лимитный ниже.
            self._player_penalty_count += 1
            self._player_penalty_seconds += enriched.get("time_seconds", 0) or 0
            if enriched.get("infringement_type") in TRACK_LIMITS_INFRINGEMENT_TYPES:
                should_announce = self._race_engineer.note_track_limits_penalty(time.time())
                _log.info("DIAG PENA track-limits companion: should_announce=%s "
                          "chatter_enabled=%s", should_announce,
                          self._get_setting("engineer_chatter_enabled", True))
                if should_announce and self._get_setting("engineer_chatter_enabled", True):
                    self._commentary_events.publish({
                        "event_code": "ENGINEER_PENA_TRACK_LIMITS",
                        "priority": "normal",
                        "phrase": "Это за трек-лимиты — аккуратнее на выходе из поворота.",
                        "speaker": SPEAKER_ENGINEER, "driver": "", "color": "#38BDF8",
                        "bypass_speak_threshold": True,
                    })

        if self._is_paused() or not self._should_commentate(enriched):
            self._ui_state.append_feed({
                "time": datetime.now().strftime("%H:%M:%S"),
                "event_code": event["event_code"],
                "phrase": enriched.get("description", event["event_code"]),
                "color": enriched.get("color", "#9CA3AF"),
                "driver": enriched.get("driver", ""),
                "muted": True,
                "channel": "commentary",
            })
            return

        # Адаптивность/cooldown ambient: значимое событие двигает оба механизма.
        if self._commentary_runtime.is_significant_event(enriched):
            self._commentary_runtime.note_event_activity(time.time())
        self._commentary_events.publish(enriched)

    # ------------------------------------------------------------
    # Поток генерации и озвучки комментариев
    # ------------------------------------------------------------

    def _commentary_loop(self):
        last_speak_time = 0.0

        while not self._stop_event.is_set():
            try:
                event = self._commentary_events.next(timeout=0.2)
            except queue.Empty:
                continue
            event = event.to_dict()

            if self._is_paused():
                continue

            # Не озвучиваем бэклог, накопившийся до выхода из активной сессии
            # (например, игрок вернулся в карьерное лобби/главное меню) — иначе
            # комментатор договаривает события так, будто гонка ещё идёт.
            # Симметрично уже существующей проверке в _ambient_loop.
            if not self._telemetry_connected:
                continue

            now = time.time()

            # ── Порог "говорить/молчать" по важности: ниже порога вообще не
            # вызываем LLM (экономия Yandex API), только помечаем в ленте как
            # muted.
            if self._commentary_runtime.muted_by_threshold(
                    event, now,
                    mode=self._get_setting("commentary_mode", "live")):
                self._ui_state.append_feed({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event.get("event_code", ""),
                    "phrase": event.get("description", event.get("event_code", "")),
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": True,
                    "channel": "commentary",
                })
                continue

            # ── Backlog drop: событие недостаточно важно и заждалось в очереди —
            # не проговариваем весь накопившийся бэклог подряд без пауз, а сразу
            # переходим к самому свежему. Важные события никогда не вытесняются.
            if self._commentary_runtime.is_stale_backlog_event(event, now):
                continue

            # ── Entity resolution: replace "#N" placeholders and generic labels ──
            _drv = str(event.get("driver") or "")
            if not _drv or _drv.startswith("#") or _drv in ("гонщик", "пилот"):
                event["driver"] = resolve_driver_name(event, self._game_year)
            _tgt = str(event.get("target") or "")
            if "target" in event and (not _tgt or _tgt.startswith("#") or _tgt in ("соперник", "пилот")):
                event["target"] = resolve_opponent_name(event)

            # ── Session-aware spam guard ─────────────────────────────────────
            if not self._session_guard.should_emit(event):
                continue

            # ── Flashback silence: после перемотки коротко молчим (кроме critical) ──
            if (event.get("priority") != "critical"
                    and time.time() < self._flashback_until):
                continue

            # ── Semantic situation dedup: не пересказываем одну и ту же погоню ──
            if event.get("priority") != "critical":
                _ahead, _behind = self._neighbor_names()
                _sig = self._situation_dedup.signature(
                    event,
                    gap_front_ms=self._player_gap_front,
                    gap_behind_ms=self._player_gap_behind,
                    gap_leader_ms=self._player_gap_leader,
                    ahead_name=_ahead, behind_name=_behind,
                    leader_name=self._leader_name,
                )
                if not self._situation_dedup.should_emit(_sig, time.time()):
                    continue
                # ── Дедуп по ТЕМЕ: одна новость — один раз, каким бы кодом
                # инженера она ни пришла. Блок выше этого не ловит: он смотрит
                # только проксимити-коды игры (OVTK/ATTACK/BATTLE), а спеки
                # инженера приходят своими кодами от девяти независимых
                # трекеров, которые друг про друга не знают.
                if not self._engineer_topic_allows(event, time.time()):
                    continue

            # ── Channel routing ──────────────────────────────────────────────
            channel = route_event(event, self._session_type)

            if channel == CHANNEL_OVERLAY:
                self._ui_state.append_feed({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event["event_code"],
                    "phrase": event.get("description", event["event_code"]),
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": True,
                    "channel": "overlay",
                })
                continue

            # ── Phrase generation ────────────────────────────────────────────
            phrase = event.get("phrase") or ""    # preset (напр. F1_BENCH) — короткозамыкает
            if not phrase and channel == CHANNEL_RADIO:
                phrase = get_radio_line(
                    event["event_code"], self._phrase_selector(event)) or ""

            if not phrase:
                broadcast_on = self._get_setting("broadcast_mode_enabled", False)
                if event.get("strategy_ai_type"):
                    from commentator import strategist
                    phrase = strategist.get_message(
                        event.get("strategy_ai_type", "stable"),
                        event.get("strategy_ai_data"),
                        selector_key=self._phrase_selector(event),
                    )
                elif broadcast_on and event.get("race_ai_type"):
                    phrase = self.commentator.create_broadcast(
                        event, ai_ok=self._yandex_healthy)
                else:
                    try:
                        plan = build_plan(event, event.get("importance", 50),
                                           self.commentator.persona,
                                           mode=self._get_setting("commentary_mode", "live"))
                    except Exception:
                        _log.warning("build_plan failed for %s",
                                     event.get("event_code"), exc_info=True)
                        plan = None
                    phrase = self.commentator.create(
                        event, self._build_ai_context(event), ai_ok=self._yandex_healthy,
                        plan=plan)

            if not phrase:
                continue

            # ── Доменная модель радиообмена ──────────────────────────────────
            # Сообщение собирается ЗДЕСЬ, как только текст получен: дальше по
            # потоку начинаются задержки (пауза MIN_COMMENT_GAP, очередь
            # синтеза, сеть), и именно там понадобятся его канал, срочность,
            # срок жизни и ключи ситуации.
            #
            # try/except обязателен: у этого цикла нет внешнего обработчика, и
            # исключение здесь убило бы поток комментария целиком — приложение
            # молчало бы до перезапуска.
            message = self._build_radio_message(event, phrase)
            if message is not None:
                # Регистрируем ДО паузы: если за эти 9 секунд придёт tier 2 того
                # же box-call, он станет новейшим и вытеснит это сообщение.
                self._note_radio_newest(message)
                _log.debug(
                    "radio message %s: channel=%s urgency=%s policy=%s ttl=%s "
                    "situation=%s dedupe=%s",
                    message.id, message.channel, message.urgency,
                    message.interrupt_policy, message.ttl,
                    message.situation_id, message.dedupe_key)

            # ── Стиль радио: сколько говорит инженер (ТЗ §17) ────────────────
            # Три эффекта сразу — глушение аналитики, надбавка к порогу и
            # масштаб паузы. Ни один из них не касается critical и споттера.
            if self._muted_by_style(message):
                self._note_radio_cancel(message, RadioCancelReason.SUPERSEDED,
                                        "radio style: minimal")
                continue
            _style_offset = self._style_threshold_offset(message)
            if _style_offset and event.get("importance", 50) < (
                    config.PLAN_BASE_THRESHOLD + _style_offset):
                self._ui_state.append_feed({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event.get("event_code", ""),
                    "phrase": event.get("description", event.get("event_code", "")),
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": True,
                    "channel": channel,
                })
                continue

            should_voice = self._should_voice(event)
            importance = event.get("importance", 50)

            if should_voice and importance < config.PLAN_GAP_SKIP_THRESHOLD:
                min_gap = self._get_setting("min_comment_gap", config.MIN_COMMENT_GAP)
                min_gap *= float(self._radio_style_profile()["gap_scale"])
                if importance >= config.PLAN_GAP_HALF_THRESHOLD:
                    min_gap = min_gap / 2
                wait = min_gap - (time.time() - last_speak_time)
                if wait > 0 and self._stop_event.wait(wait):
                    break
                # Проверка ПОСЛЕ паузы: за 9 секунд ситуация могла закрыться.
                if message is not None and message.is_expired(time.monotonic()):
                    self._note_radio_cancel(message, RadioCancelReason.EXPIRED)
                    continue

            # На игровой HUD и в ленту пишем текст, каким он известен СЕЙЧАС.
            # Волатильные токены для показа раскрываются по текущему снимку —
            # это только субтитр, к решению об озвучке он отношения не имеет.
            display = self._display_text(message, phrase)
            self._ui_state.set_radio_message(display, voiced=should_voice)
            self._ui_state.append_feed({
                "time": datetime.now().strftime("%H:%M:%S"),
                "event_code": event["event_code"],
                "phrase": display,
                "color": event.get("color", "#9CA3AF"),
                "driver": event.get("driver", ""),
                "muted": not should_voice,
                "channel": channel,
            })

            if should_voice:
                voice_priority = ("critical" if importance >= config.PLAN_INTERRUPT_THRESHOLD
                                  else "normal")
                self.voice.say(
                    display, priority=voice_priority,
                    persona=self._voice_slot_for(event, message),
                    urgency=None if message is None else message.urgency,
                    message_id=None if message is None else message.id,
                    # Финальный резолв уезжает в воркер очереди: только там
                    # позади ВСЕ значимые ожидания, а впереди cache key и сеть.
                    prepare=None if message is None
                    else self._make_prepare(message),
                    still_valid=None if message is None
                    else self._make_playback_gate(message))
                self._commentary_runtime.note_spoken(time.time())
            else:
                # Не озвучиваем — сообщение всё равно не должно остаться в
                # неизвестном состоянии.
                if message is not None:
                    self._note_radio_state(message, STATE_COMPLETED)

            last_speak_time = time.time()

    def _ambient_loop(self):
        """Адаптивный «тик» гибридного режима: периодически просим ИИ оценить общую
        ситуацию и прокомментировать, если есть что (иначе он молчит). Работает только
        при активном+здоровом Yandex; кладёт AMBIENT-событие в общую очередь —
        переиспользуем сериализацию и min_comment_gap из _commentary_loop.

        Task #14: интервал адаптивный (активность гонки), после значимого события —
        cooldown, и «лёгкий» throttle не даёт ambient-LLM-запросам идти слишком часто."""
        while not self._stop_event.is_set():
            if self._stop_event.wait(
                    self._commentary_runtime.ambient_interval(time.time())):
                break
            now = time.time()
            if (self._is_paused()
                    or not self._get_setting("ambient_enabled", True)
                    or not self.ai.available or not self._yandex_healthy):
                continue
            if not self._telemetry_connected or not self._session_active:
                continue
            # Не лезем поверх свежей драмы и не частим запросами к Yandex.
            if (self._commentary_runtime.in_event_cooldown(now)
                    or self._commentary_runtime.ambient_throttled(now)):
                continue
            self._commentary_runtime.note_ambient_request(now)
            self._commentary_events.publish({
                "event_code": "AMBIENT", "priority": "normal",
                "color": "#9CA3AF", "driver": "", "ambient": True,
            })

    # ── Радио: позднее связывание и жизненный цикл ───────────────────────────

    def _display_text(self, message, fallback: str) -> str:
        """Текст для субтитра и ленты: волатильные токены раскрыты по текущему
        снимку. Если раскрыть нельзя — показываем то, что есть, без скобок."""
        if message is None:
            return fallback
        resolved = radio_resolver.resolve_for_playback(
            message, self._volatile_snapshot(), time.monotonic())
        if isinstance(resolved, radio_resolver.Cancellation):
            return _strip_tokens(message.phrase or fallback)
        return resolved.text

    def _note_radio_newest(self, message) -> None:
        """Запомнить сообщение как самое свежее по своей ситуации."""
        if message is None or not message.situation_id:
            return
        with self._radio_lifecycle_lock:
            self._radio_newest[message.situation_id] = message.id
            # Ограничиваем рост: за длинную гонку ситуаций накапливается много,
            # а нужна только последняя по каждой.
            if len(self._radio_newest) > _RADIO_SITUATION_LIMIT:
                for key in list(self._radio_newest)[:len(self._radio_newest) // 2]:
                    del self._radio_newest[key]

    def _is_superseded(self, message) -> bool:
        """Есть ли по этой ситуации сообщение новее.

        Так tier 2 box-call делает ожидающий tier 1 неактуальным: оба несут один
        `situation_id`, и старый не должен прозвучать после нового."""
        if not message.situation_id:
            return False
        with self._radio_lifecycle_lock:
            newest = self._radio_newest.get(message.situation_id)
        return newest is not None and newest != message.id

    def _make_prepare(self, message):
        """Колбэк финального резолва для воркера очереди воспроизведения.

        Вызывается за миг до синтеза. Возвращает готовый текст либо None —
        «неактуально, не озвучивать»; во втором случае сообщение получает
        terminal state и структурированную причину, а не исчезает бесследно."""
        def prepare() -> str | None:
            if self._is_superseded(message):
                self._note_radio_cancel(message, RadioCancelReason.SUPERSEDED,
                                        message.situation_id or "")
                return None
            resolved = radio_resolver.resolve_for_playback(
                message, self._volatile_snapshot(), time.monotonic())
            if isinstance(resolved, radio_resolver.Cancellation):
                self._note_radio_cancel(message, resolved.reason, resolved.detail)
                return None
            self._note_radio_state(message, STATE_SYNTHESIZING)
            return resolved.text
        return prepare

    def _make_playback_gate(self, message):
        """Повторная проверка перед playback — после сетевого синтеза.

        TTL даёт право НАЧАТЬ воспроизведение. Уже звучащую фразу истечение TTL
        не обрывает: обрыв на полуслове хуже устаревшей на секунду реплики."""
        def still_valid() -> bool:
            if message.is_expired(time.monotonic()):
                self._note_radio_cancel(message, RadioCancelReason.EXPIRED,
                                        "expired after synthesis")
                return False
            return True
        return still_valid

    def _note_radio_state(self, message, state: str) -> None:
        """Запомнить переход состояния радио-сообщения.

        Пока это диагностический журнал и seam для Task 5 (история радио и UI).
        Терминальное состояние повторно не меняется — переходы валидирует сама
        модель, а здесь гасим уже закрытые сообщения."""
        with self._radio_lifecycle_lock:
            current = self._radio_lifecycle.get(message.id, message)
            if current.is_terminal:
                return
            try:
                updated = current.with_state(state, now=time.time())
            except ValueError:
                _log.debug("radio lifecycle: %s -> %s rejected for %s",
                           current.state, state, message.id)
                return
            self._radio_lifecycle[message.id] = updated
        self.radio_session.note(updated)

    def _note_radio_cancel(self, message, reason: RadioCancelReason,
                           detail: str = "") -> None:
        with self._radio_lifecycle_lock:
            current = self._radio_lifecycle.get(message.id, message)
            if current.is_terminal:
                return
            try:
                updated = current.cancelled(reason, now=time.time())
            except ValueError:
                _log.debug("radio cancel rejected for %s in state %s",
                           message.id, current.state)
                return
            self._radio_lifecycle[message.id] = updated
        self.radio_session.note(updated)
        _log.info("radio %s cancelled: %s%s", message.id, reason.value,
                  f" ({detail})" if detail else "")

    def _on_playback_event(self, event: str, message_id: str | None) -> None:
        """Реальные события воспроизведения из `voice/tts.py`.

        Здесь и только здесь поднимается флаг «говорит»: прежний паттерн
        `set_speaking(True) / say() / set_speaking(False)` держал его
        микросекунды, потому что `say()` лишь ставит в очередь (дефект Task 1)."""
        if event == "playing":
            with self._radio_lifecycle_lock:
                message = self._radio_lifecycle.get(message_id or "")
            text = (message.phrase if message is not None else "") or ""
            self._ui_state.set_speaking(text, True)
            if message is not None:
                self._note_radio_state(message, STATE_PLAYING)
        elif event == "completed":
            self._ui_state.set_speaking("", False)
            with self._radio_lifecycle_lock:
                message = self._radio_lifecycle.get(message_id or "")
            if message is not None:
                self._note_radio_state(message, STATE_COMPLETED)

    def _render_engineer_phrase(self, draft: dict, phrase_code: str,
                                fields: dict | None = None) -> str:
        """Формулировка из банка (`core/radio/phrases.py`) для этого события.

        Вариант закрепляется за СИТУАЦИЕЙ: селектор — `dedupe_key` события,
        поэтому повторная телеметрия по той же ситуации даёт ту же формулировку,
        а не переписывает уже произнесённую. Случайности нет вовсе — выбор
        детерминирован и воспроизводим (см. `phrases.select_variant`).

        Отказ банка (недостающее поле, неизвестный код) не должен стоить события:
        возвращаем пустую строку, и обычный путь генерации фразы в
        `_commentary_loop` подхватит шаблон или LLM, как раньше."""
        selector = self._phrase_selector(draft)
        character = self._get_setting(
            "engineer_character", voice_cast.DEFAULT_CHARACTER)
        try:
            phrase = radio_phrases.render(
                phrase_code, fields, selector_key=selector,
                # «Коротко» смещает выбор к самому лаконичному варианту той же
                # ситуации — не обрезает текст и не заводит второй банк.
                shortest=self._get_setting("phrase_length", "standard") == "short",
                # Персонаж смещает пул формулировок там, где характер слышен.
                # Боевые команды он не трогает по контракту банка.
                character=character)
        except PhraseError:
            _log.warning("phrase bank refused %s for %s",
                         phrase_code, draft.get("event_code"), exc_info=True)
            return ""
        return radio_address.apply(
            phrase,
            first_name_of(self._player_driver_name()),
            character,
            selector,
            allowed=self._address_allowed(draft, phrase_code),
        )

    def _address_allowed(self, draft: dict, phrase_code: str) -> bool:
        """Можно ли навесить обращение по имени на эту реплику.

        Нельзя в двух случаях, и оба — про время, а не про вежливость:

        * канал споттера — там счёт на доли секунды;
        * ЛЮБАЯ critical-реплика инженера. «Макс, бокс! Бокс!» стоит пилоту
          лишнего слога ровно тогда, когда слог дороже всего, а узнаваемость
          команды важнее личного тона. Тот же принцип, что держит критические
          команды вне характера.

        Изначально план исключал только споттера; критическую срочность добавил
        разбор остатков — аргумент «счёт на доли секунды» применим к ней в
        точности так же."""
        if radio_policy.channel_for(draft) == radio_policy.CHANNEL_SPOTTER:
            return False
        try:
            return (radio_phrases.spec_for(phrase_code).urgency
                    != radio_policy.URGENCY_CRITICAL)
        except PhraseError:
            # Кода нет в банке — обращение не навешиваем: судить не по чему,
            # а промолчать безопаснее, чем угадать.
            return False

    def _phrase_selector(self, draft: dict) -> str:
        """Стабильный ключ выбора варианта для банка.

        `dedupe_key` события, если ситуация опознана: тогда повторная телеметрия
        по ней даёт ТУ ЖЕ формулировку, а не переписывает уже произнесённую.
        Иначе — сессия плюс код события."""
        return (
            situation_dedupe_key(draft, lap=self._player_lap,
                                 session_id=self._radio_session_id,
                                 timeline_revision=self._timeline_revision)
            or f"{self._radio_session_id}:{draft.get('event_code', '')}"
        )

    @staticmethod
    def _new_radio_session_id() -> str:
        """Идентификатор заезда для радио-ситуаций.

        Секундной метки достаточно: два заезда не начинаются в одну секунду, а
        читаемость в логе и в истории радио важнее гарантий uuid."""
        return time.strftime("%Y%m%d_%H%M%S")

    def _build_radio_message(self, event: dict, phrase: str):
        """Собрать `RadioMessage`, либо None если сборка не удалась.

        Отдельный метод ради этого try/except. `_commentary_loop` — бесконечный
        поток без внешнего обработчика: необработанное исключение внутри него
        убивает поток, и приложение молчит до перезапуска. Пока сообщение ничего
        не решает (Task 2), его отказ обязан быть бесплатным для пользователя;
        когда решения переедут на него (Task 4/5), эта граница станет местом, где
        принимается решение о деградации, а не просто «пропустить»."""
        try:
            return build_radio_message(
                event,
                phrase=phrase,
                now=time.time(),
                now_mono=time.monotonic(),
                telemetry=self._volatile_snapshot(),
                lap=self._player_lap,
                session_id=self._radio_session_id,
                timeline_revision=self._timeline_revision,
            )
        except Exception:  # noqa: BLE001
            _log.warning("radio message build failed for %s",
                         event.get("event_code"), exc_info=True)
            return None

    def _voice_slot_for(self, event: dict, message) -> str | None:
        """Слот голоса для реплики: из КАНАЛА сообщения, не из маркера speaker.

        Отдельный метод, а не выражение внутри `say(...)`: это центральная
        проводка всей работы по разделению голосов, и внутри бесконечного цикла
        `_commentary_loop` её нельзя покрыть тестом. Здесь — можно.

        Маркер `speaker` для выбора голоса не годится: споттер публикуется с
        тем же `speaker="engineer"`, что и инженер (`_spotter_tick`), поэтому
        различает их только канал. Фолбэк на маркер остаётся лишь для случая,
        когда `RadioMessage` не собрался — лучше инженерский голос, чем None.
        """
        if message is not None:
            return message.voice_persona
        if event.get("speaker") == SPEAKER_ENGINEER:
            return SLOT_ENGINEER
        return None

    def _radio_style_profile(self) -> dict:
        style = self._get_setting("radio_style", config.RADIO_STYLE_DEFAULT)
        return config.RADIO_STYLE_PROFILE.get(
            style, config.RADIO_STYLE_PROFILE[config.RADIO_STYLE_DEFAULT])

    def _muted_by_style(self, message) -> bool:
        """Глушит ли стиль радио это сообщение.

        ИНВАРИАНТ ТЗ §17: «Critical и Spotter не должны отключаться настройкой
        частоты». Проверка стоит первой и выходит раньше любых порогов —
        безопасность не обсуждается ни в одном профиле.

        Гасятся только АНАЛИТИЧЕСКИЕ категории инженерского канала: сводки по
        разрывам, DRS, оборона, позиционный статус. Команды, повреждения,
        флаги, штрафы и погода звучат всегда."""
        if message is None:
            return False
        if message.is_critical or message.channel == radio_policy.CHANNEL_SPOTTER:
            return False
        if message.category not in config.RADIO_ANALYTIC_CATEGORIES:
            return False
        return not self._radio_style_profile()["analytics"]

    def _style_threshold_offset(self, message) -> int:
        """Надбавка к порогу важности от стиля радио.

        К споттеру и critical не применяется по тому же инварианту."""
        if message is None:
            return 0
        if message.is_critical or message.channel == radio_policy.CHANNEL_SPOTTER:
            return 0
        return int(self._radio_style_profile()["threshold_offset"])

    def _volatile_snapshot(self) -> dict:
        """Снимок быстроменяющихся величин на момент сборки сообщения.

        Едет в `RadioMessage.source_snapshot` и служит точкой сравнения: перед
        озвучкой те же поля читаются заново, и по расхождению видно, устарело ли
        число (ТЗ §8). Здесь только то, что реально успевает измениться за время
        очереди и синтеза — гэпы, заряд, топливо, износ, позиция."""
        return {
            "ers_percent": self._player_ers_percent,
            "ers_deploy_mode": self._player_ers_deploy_mode,
            "gap_front_ms": self._player_gap_front,
            "gap_behind_ms": self._player_gap_behind,
            "fuel_kg": self._player_fuel,
            "tyre_wear": self._player_tyre_wear,
            "position": self._player_pos,
            "lap": self._player_lap,
            "rain_minutes": (self._rain_forecast or {}).get("minutes"),
            # Признаки «ситуация ещё та же» — по ним резолвер отменяет реплику,
            # ставшую неверной не из-за устаревшего числа, а из-за смены самой
            # ситуации (см. core/radio/resolver.py, guards).
            "pit_status": self._player_pit_status,
            "safety_car_status": self._safety_car_status,
            # Цель гэп-реплики: свежий разрыв до ДРУГОГО пилота — не обновление,
            # а ложь, поэтому смена цели отменяет сообщение.
            "gap_target_idx": self._nearest_rival_idx(),
            # Идентичность комплекта шин: возраст в кругах меняется вместе с
            # заездом в боксы, поэтому годится как маркер «резина та же».
            "tyre_set_id": self._player_tyre_age,
        }

    def _maybe_emit_gap_digest(self, now: float) -> bool:
        """Один тик _engineer_digest_loop: строит и ставит в очередь сводку
        по гэпам, если есть что сказать. Возвращает True, если поставил
        событие (для тестов — сам бесконечный цикл не тестируется напрямую,
        как _ambient_loop)."""
        # ВРЕМЕННАЯ диагностика (см. чат): какой из гейтов реально блокирует
        # (или нет) на каждом тике цикла (раз в ENGINEER_DIGEST_INTERVAL_S).
        _log.info(
            "DIAG gap_digest gate: paused=%s session_type=%s session_active=%s "
            "in_cooldown=%s chatter_enabled=%s gap_front=%s gap_behind=%s",
            self._is_paused(), self._session_type, self._session_active,
            self._commentary_runtime.in_event_cooldown(now),
            self._get_setting("engineer_chatter_enabled", True),
            self._player_gap_front, self._player_gap_behind)
        if (self._is_paused() or self._session_type != "race"
                or not self._session_active
                or self._commentary_runtime.in_event_cooldown(now)
                or not self._get_setting("engineer_chatter_enabled", True)):
            return False
        if not self._telemetry_connected:
            return False
        sector_comparison = None
        rival_idx = self._nearest_rival_idx()
        if rival_idx is not None:
            player_hist = self._session_history.get(self._player_car_index)
            rival_hist = self._session_history.get(rival_idx)
            if player_hist and rival_hist:
                rival_name = self.race_state.driver(rival_idx)["name"]
                sector_comparison = compare_best_sectors(
                    player_hist["best_sector_ms"], rival_hist["best_sector_ms"],
                    rival_name)
        codes = self._race_engineer.gap_digest(
            self._player_gap_front, self._player_gap_behind,
            ers_percent=self._player_ers_percent,
            sector_comparison=sector_comparison)
        if not codes:
            return False
        # bypass_speak_threshold: тот же приём, что уже применён к PIT_CALL_NOTICE
        # (см. _muted_by_threshold) — без него рутинная сводка (importance по
        # умолчанию 50) систематически глохла бы именно в загруженной гонке,
        # где голосовая болтовня чаще держит спайк порога (65, до 85 в
        # calm/story) — ровно обратное тому, что задумано («не подстраиваться
        # под драму гонки»). Поднять importance константой в _BASE_IMPORTANCE
        # не решило бы это для всех режимов сразу: любое фиксированное число
        # ниже 90 может не перекрыть спайк в calm/story, а >=90 переключило бы
        # приоритет на critical (PLAN_INTERRUPT_THRESHOLD) — неверно для
        # рутинной сводки.
        draft = {
            "event_code": "ENGINEER_GAP_DIGEST", "priority": "normal",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        }
        # Сводка СКЛЕИВАЕТСЯ из фрагментов банка. Сравнение секторов приходит
        # свободной строкой из другого модуля и добавляется как есть — банк
        # такие тексты не порождает.
        draft["phrase"] = radio_phrases.compose(
            codes, selector_key=self._phrase_selector(draft),
            shortest=self._get_setting("phrase_length", "standard") == "short",
            extra=(sector_comparison,) if sector_comparison else ())
        if not draft["phrase"]:
            return False
        self._commentary_events.publish(draft)
        return True

    def _engineer_digest_loop(self) -> None:
        """Периодическая (фиксированный интервал, НЕ адаптивный) сводка
        инженера по гэпам. См. spec 2026-07-10-engineer-gap-digest-design.md."""
        while not self._stop_event.is_set():
            if self._stop_event.wait(config.ENGINEER_DIGEST_INTERVAL_S):
                break
            self._maybe_emit_gap_digest(time.time())

    # ------------------------------------------------------------
    # Для UI
    # ------------------------------------------------------------

    def get_state(self) -> dict:
        return self._ui_state.snapshot({
            # Секция радио собирается на каждый запрос, а не хранится в
            # проекции: её владелец — RadioSession, и держать вторую копию
            # значило бы дать им разойтись.
            "radio": self.radio_session.to_ui_dict(),
            # Экран «Настройки» раньше рисовал 127.0.0.1/20777 литералами в JSX
            # и вообще не знал про telemetry_source="iracing" — при другом
            # источнике телеметрии панель показывала неправду.
            "telemetry_source": self._telemetry_source,
            "udp_ip": config.UDP_IP,
            "udp_port": config.UDP_PORT,
            "tts_engine": self.voice.engine_name,
            "tts_active": self.voice.last_engine,
            "tts_fallback": self.voice.last_fallback,
            "speaker": self.voice.active_speaker,
            "voice_status": self.voice.status_message,
            "voice_available": self.voice.is_available,
            "metadata_loaded": (
                self.metadata.loaded if self._telemetry_source == "f1" else False
            ),
        })

    def get_race_ai_state(self) -> dict:
        return self._ui_state.section("race_ai")

    def get_strategy_ai_state(self) -> dict:
        return self._ui_state.section("strategy_ai")

    def get_coach_ai_state(self) -> dict:
        return self._ui_state.section("coach_ai")

    def get_rivals_state(self) -> dict:
        return self._ui_state.section("rivals")

    def get_track_ai_state(self) -> dict:
        return self._ui_state.section("track_ai")

    def get_overlay_state(self) -> dict:
        """Build consolidated Broadcast Overlay HUD dict for /api/overlay."""
        weather = self._current_weather or {}
        return self._ui_state.overlay(OverlayTelemetry(
            **{key: value for key, value in self._player_hud.items()
               if key != "drs_allowed"},
            drs_allowed=bool(self._player_hud.get("drs_allowed", False)),
            air_temp_c=weather.get("air_temp"),
            track_temp_c=weather.get("track_temp"),
            position=self._player_pos,
            lap_current=self._player_lap,
            lap_total=getattr(self, "_total_laps", None),
            speed_kmh=self._player_speed_kmh,
            drs_active=self._player_drs_active,
            gap_leader_ms=self._player_gap_leader,
            gap_front_ms=self._player_gap_front,
            gap_behind_ms=self._player_gap_behind,
            tyre_compound=self._player_tyre_compound,
            tyre_age=self._player_tyre_age,
            tyre_wear=self._player_tyre_wear,
            radar=self._radar,
            fuel_kg=self._player_fuel,
            ers_percent=self._player_ers_percent,
            ers_deploy_mode=self._player_ers_deploy_mode,
            last_lap_ms=self._player_pace_ms,
        ))

    def clear_feed(self):
        self._ui_state.clear_feed()

    def test_voice(self) -> dict:
        """Queue the UI voice test as an owned short-lived task."""
        if not self.voice.is_available:
            return {"ok": False, "error": self.voice.status_message}
        thread = self._spawn_thread(
            self.voice.test_say,
            args=("Проверка радио. Голос работает, поехали!",),
            name="voice-test",
            task=True,
        )
        if thread is None:
            return {"ok": False, "error": "Приложение завершает работу"}
        return {"ok": True, "engine": self.voice.engine_name}

    def fire_highlight(self) -> bool:
        """One-shot ambient comment: bypass cooldown/throttle, fire immediately.
        Отвечает False если ИИ недоступен или нет связи с игрой."""
        if not self.ai.available or not self._yandex_healthy:
            return False
        if not self._telemetry_connected:
            return False
        self._commentary_runtime.note_ambient_request(time.time())
        self._commentary_events.publish({
            "event_code": "AMBIENT", "priority": "normal",
            "color": "#9CA3AF", "driver": "", "ambient": True,
        })
        return True

    def set_analytics_context(self, context: str | None) -> None:
        self.commentator.analytics_context = context

    def _refresh_analytics_context(self) -> None:
        """F1 Benchmark, Career Memory и Career Stats — независимые источники
        контекста для LLM, но `analytics_context` — одна строка. Собираем все
        непустые части вместе, чтобы каждое новое сравнение не затирало
        предыдущее."""
        parts = [p for p in (self._f1_context_line, self._career_context_line,
                             self._career_stats_context_line) if p]
        self.set_analytics_context(" ".join(parts) if parts else None)
