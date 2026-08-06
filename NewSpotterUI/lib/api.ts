// Типизированный клиент к локальному API (web_server.py, Bottle, порт 8765).
// UI отдаётся тем же сервером (статический экспорт Next), поэтому пути относительные —
// в браузере webview это http://127.0.0.1:8765/api/*.

export type Telemetry = {
  lap: string
  position: string
  speed: string
  gear: string
  fuel: string
}

// Бэкенд (core/engine.py::_ui_state.append_feed) кладёт в каждый элемент ленты
// ещё driver/muted/channel — раньше этот тип их не объявлял, и UI не мог
// отличить прозвучавшую реплику от молча залогированной.
export type FeedItem = {
  time: string
  event_code: string
  phrase: string
  color: string
  driver?: string
  /** true — событие попало в ленту, но НЕ было озвучено. */
  muted?: boolean
  /** commentary | radio | overlay — commentator/channel_router.py */
  channel?: string
}

/** Что с постом сделал читатель. Пишется в БД той же гонки (core/racefeed/reader.py),
 *  поэтому переживает перезапуск и остаётся при переезде гонки в архив. */
export type RaceFeedReaderState = {
  reaction?: string
  vote?: string
}

export type RaceFeedPostRow = {
  id: string
  /** Нужен, чтобы записать действие в файл именно этой гонки. */
  session_id: string
  reader?: RaceFeedReaderState
  story_id: string
  reporter_id: string
  category: string
  text: string
  created_at: number
  published_at: number
  driver: string | null
  is_player_story: number
  story_stage: number
  format_id: string
  angle_id: string
  claim_fingerprint: string
  image?: string
  metadata?: RaceFeedPostMetadata
  comments: RaceFeedCommentRow[]
}

// Послегоночные интерактивы и факт-карды — структурные данные поста, которые
// UI рисует сам, а не пытается восстановить из журналистского текста.
export type PollCandidateRow = {
  driver: string
  vote_pct: number
  overtakes: number
  positions_gained: number
  position: number
  fastest_lap: boolean
  penalties: number
  is_player: boolean
}

export type InterviewQuoteRow = {
  driver: string
  role: string
  quote: string
  position: number
  overtakes: number
  positions_gained: number
  is_player: boolean
}

export type RaceRecapRow = {
  driver: string
  finish_position: number
  grid_position: number
  positions_gained: number
  overtakes: number
  points: number
  pit_stops: number
  fastest_lap: boolean
  penalties: number
}

export type ChampionshipComparisonRow = {
  driver?: string
  player_position?: number
  player_points?: number
  rival?: string
  rival_position?: number
  rival_points?: number
  gap_to_rival?: number
  player_race_position?: number
  rival_race_position?: number
  rival_ahead?: boolean
}

export type SeasonStorylineRow = {
  id: string
  title: string
  value: string
  detail: string
  tone: "amber" | "red" | "violet" | "green" | "sky"
}

export type ReturnHookRow = {
  title: string
  detail: string
}

export type WeekendDuelDriverRow = {
  driver: string
  start_position: number
  finish_position: number
  best_lap_time_ms: number
  points: number
}

export type WeekendDuelRow = {
  team: string
  player: WeekendDuelDriverRow
  teammate: WeekendDuelDriverRow
  player_score: number
  teammate_score: number
  winner: "player" | "teammate" | "draw"
}

export type RaceFeedPostMetadata = {
  poll?: PollCandidateRow[]
  interview?: InterviewQuoteRow[]
  recap?: RaceRecapRow
  comparison?: ChampionshipComparisonRow
  storylines?: SeasonStorylineRow[]
  return_hook?: ReturnHookRow
  weekend_duel?: WeekendDuelRow
}

export type RaceFeedCommentRow = {
  id: string
  post_id: string
  parent_id: string | null
  author_id: string
  author_name: string
  author_badge: string
  avatar: string
  text: string
  created_at: number
  likes: number
}

export type RaceFeedResponse = {
  enabled: boolean
  posts: RaceFeedPostRow[]
  prediction?: RacePredictionRow | null
}

export type PredictionFinishChoice = "podium" | "points" | "outside_points"
export type PredictionTeammateChoice = "player" | "teammate" | "draw"
export type PredictionRiskChoice = "safety_car" | "rain" | "penalty"

export type RacePredictionTicket = {
  finish?: PredictionFinishChoice
  teammate?: PredictionTeammateChoice
  risk?: PredictionRiskChoice
}

export type PredictionForecastChoice = {
  choice: string
  confidence: number
  basis: string
}

export type RacePredictionResult = {
  actual: {
    finish: PredictionFinishChoice
    teammate: PredictionTeammateChoice
    risks: Record<PredictionRiskChoice, boolean>
  }
  reader_hits: Partial<Record<keyof RacePredictionTicket, boolean>>
  model_hits: Record<keyof RacePredictionTicket, boolean>
  reader_score: number | null
  model_score: number
}

export type TrackReturnRow = {
  track_name: string
  last_visit_date: string | null
  finish_position: number | null
  last_visit_best_lap_ms: number | null
  personal_best_lap_ms: number | null
  main_setback: { code: string; label: string } | null
  goal: { kind: string; label: string; target_position?: number }
  visits: number
}

export type RacePredictionRow = {
  session_id: string
  track_name: string
  status: "open" | "locked" | "resolved"
  model_forecast: {
    participants: { player: string; teammate: string }
    finish: PredictionForecastChoice
    teammate: PredictionForecastChoice
    risk: PredictionForecastChoice
  }
  reader_ticket: RacePredictionTicket
  result: Partial<RacePredictionResult>
  track_return: Partial<TrackReturnRow>
  created_at: number
  locked_at: number
  resolved_at: number
  scoreboard?: { reader: number; model: number; races: number }
}

export type StandingsRow = {
  driver: string
  team: string | null
  color: string | null
  points: number
  position: number
  is_player: boolean
  is_rival?: boolean
}

export type CareerStats = {
  total_races: number
  wins: number
  podiums: number
  avg_position: number
}

export type ProfileInfo = {
  championship_position: number | null
  championship_points: number | null
  best_result: number | null
  career: CareerStats | null
}

export type SeasonStandingsResponse = {
  enabled: boolean
  standings: StandingsRow[]
  races_counted: number
  profile: ProfileInfo | null
}

export type GridEntry = {
  vehicle_idx: number
  position: number
  driver: string
  team: string
  color: string
  lap: number
  /** "S"|"M"|"H"|"I"|"W" из Car Status; "" — пакет по этой машине ещё не пришёл. */
  tyre_compound?: string
}

export type RaceData = {
  leader: string
  leader_idx: number | null
  grid: GridEntry[]
  last_update: string | null
}

export type PttHotkey = { ctrl: boolean; alt: boolean; shift: boolean; key: string }

export type SettingsState = {
  persona: string
  /** Персонаж инженера: "volkov" | "sokolova" | "grom". НЕЗАВИСИМАЯ ось от
   *  persona (та — характер КОММЕНТАТОРА). Голос выбирается по персонажу, но
   *  может смениться на запасной, если выбранная персона комментатора уже
   *  заняла его основной голос (core/radio/voice_cast.py). */
  engineer_character: string
  commentary_enabled: boolean
  autovoice_enabled: boolean
  critical_events_enabled: boolean
  ambient_enabled: boolean
  engineer_chatter_enabled: boolean
  radio_fx: boolean
  commentator_position: string
  min_comment_gap: number
  broadcast_mode_enabled: boolean
  racefeed_enabled: boolean
  volume: number
  volume_tv: number
  volume_hype: number
  volume_calm: number
  volume_toxic: number
  /** Громкость РОЛЕЙ. Отдельно от volume_* персон комментатора: инженер и
   *  споттер озвучиваются слотами ролей, а не персоной (voice_cast.py). */
  volume_engineer: number
  volume_spotter: number
  yandex_tts_version: "v1" | "v3"
  commentary_mode: "live" | "calm" | "story"
  mic_device: string | null
  ptt_hotkey: PttHotkey
  /** Сколько говорит ИНЖЕНЕР. Независимая ось от commentary_mode (тот про
   *  темп КОММЕНТАТОРА). Меняет порог важности, разрешённость аналитики и
   *  минимальный интервал сразу — это не таймер «раз в N секунд». */
  radio_style: "minimal" | "standard" | "verbose"
  /** "short" — самый лаконичный вариант из банка. Режима длинных монологов нет. */
  phrase_length: "short" | "standard"
  subtitles_enabled: boolean
  subtitle_seconds: number
  subtitle_size: "s" | "m" | "l"
  /** Представление радио-карточки. НИ ОДИН из ключей ниже не отключает звук:
   *  споттера и критическую реплику инженера можно убрать с экрана, но они всё
   *  равно прозвучат (core/settings.py, ТЗ §18). */
  show_broadcast_radio_card: boolean
  show_spotter_card: boolean
  show_commentary_card: boolean
  show_portraits: boolean
  /** 0.8–1.4, клипуется в lib/radio-ui.ts. */
  radio_card_scale: number
  /** 0.5–2.0 — множитель времени показа после завершения реплики. */
  radio_card_duration: number
  remember_overlay_position: boolean
  /** Визуальный язык оверлея. Меняет ТОЛЬКО оформление: ни один виджет не
   *  появляется и не исчезает, габариты окон остаются прежними. Наборы
   *  токенов — lib/overlay-theme.ts, список значений продублирован в
   *  core/settings.py::_OVERLAY_THEMES. */
  overlay_theme: OverlayThemeId
}

/** Три визуальных языка оверлея. Живёт здесь, а не в lib/overlay-theme.ts,
 *  чтобы модуль оформления импортировал типы из api, а не наоборот — тем же
 *  правилом уже живёт lib/radio-ui.ts. */
export type OverlayThemeId = "broadcast" | "cockpit" | "radio"

export type TrackAIState = {
  track_name: string | null
  corner: string | null
  corner_id: number | null
  corner_type: string | null
  phase: string
  sector: number
  attack_zone: boolean
  defense_advice: string
  advice_reason: string
}

export type StrategyAIState = {
  action: string
  confidence: number
  reason: string
  advice: string | null
  mode: string
  tyre_status: string
  fuel_mode?: string
  pace_trend?: string
  current_event: {
    type: string
    priority: string
    confidence: number
    action: string
    reason: string
    data: Record<string, unknown>
  } | null
}

export type CoachAIState = {
  weak_sector: number | null
  lost_time_ms: number | null
  consistency_score: number
  pace_delta_ms: number | null
  tyre_advice: string
  lap_count: number
  advice: string | null
}

export type RivalEntry = {
  driver: string
  team: string
  position: number
  lap: number
  pit_count: number
  style: string
  nearby: boolean
}

export type RivalsState = {
  rivals: RivalEntry[]
  rival_count: number
  nearby_count: number
}

// Последняя реплика инженера для ЧТЕНИЯ. Живёт и тогда, когда её не озвучили
// (авто-озвучка выключена, отвал TTS) — `now_speaking` в этом случае пуст.
export type RadioMessage = {
  text: string
  voiced: boolean
  /** UNIX-секунды, по ним HUD решает, не пора ли убрать сообщение. */
  ts: number
}

// ── Секция `radio` ──────────────────────────────────────────────────────────
// Полное состояние радиообмена (core/radio/session.py). Поля `speaking`,
// `now_speaking`, `radio_message` и `voice_query` ниже СОХРАНЕНЫ рядом: их
// читают «Обзор» и игровой оверлей, и заменять их этой секцией нельзя.

/** Канал: кто говорит. `driver` бывает только у строк истории. */
export type RadioSource = "spotter" | "engineer" | "commentator" | "driver"

export type RadioUrgency = "critical" | "high" | "normal" | "low"

export type RadioMessageState =
  | "queued"
  | "synthesizing"
  | "playing"
  | "completed"
  | "cancelled"
  | "interrupted"

/** Профиль говорящего (core/radio/speakers.py). Имя и роль — конфигурация
 *  бэкенда: персонажей меняют без пересборки UI. */
export type RadioSpeakerProfile = {
  speaker_id: string
  speaker_name: string
  speaker_role: string
  speaker_initials: string
  portrait_url: string | null
  accent: string
}

export type RadioActiveMessage = {
  id: string
  channel: RadioSource
  category: string
  urgency: RadioUrgency
  /** Короткая подпись канала — «Инженер», «Споттер». */
  speaker: string
  /** Профиль говорящего (core/radio/speakers.py). Имя и роль — конфигурация
   *  бэкенда, а не константы компонента: персонажей меняют без правки UI. */
  speaker_id: string
  speaker_name: string
  speaker_role: string
  speaker_initials: string
  /** Может указывать на отсутствующий файл — тогда 404 и фолбэк на инициалы.
   *  Это штатный путь, портрет необязателен. */
  portrait_url: string | null
  accent: string
  text: string
  /** Человеческий заголовок ситуации. Сырой код показывать нельзя. */
  ui_title: string
  ui_summary: string | null
  created_at: number
  started_at: number | null
  ended_at: number | null
  expires_at: number | null
  state: RadioMessageState
  situation_id: string | null
  /** Только для диагностики — не для показа пользователю. */
  debug_event_code: string
}

export type RadioHistoryEntry = {
  id: string
  source: RadioSource
  speaker: string
  /** Профиль заморожен на момент реплики: смена персоны комментатора не
   *  переименовывает задним числом того, кто уже отговорил. */
  speaker_id: string
  speaker_name: string
  speaker_role: string
  accent: string
  urgency: RadioUrgency
  title: string
  text: string
  state: RadioMessageState
  /** Почему не прозвучало: `expired`, `superseded`, `target_changed`, … */
  cancel_reason: string | null
  created_at: number
  started_at: number | null
  ended_at: number | null
}

export type RadioPtt = {
  state: "idle" | "listening" | "recognizing" | "thinking" | "done" | "error"
  driver_text: string | null
  engineer_text: string | null
  error: string | null
  updated_at: number
  /** id инженерского сообщения, отвечающего на текущий запрос. Связь берётся
   *  отсюда, а не угадывается по времени: между вопросом и ответом успевает
   *  пройти автоматическая реплика. */
  answer_message_id: string | null
}

export type RadioSection = {
  /** Монотонный счётчик изменений. Растёт только когда состояние реально
   *  поменялось — по нему клиент пропускает и пересылку истории, и
   *  перерисовку. */
  revision: number
  /** Профили по каналам. Нужны до появления активного сообщения — на «слушаю»
   *  и «проверяю данные» карточка уже подписана инженером. Имена приходят
   *  отсюда, а не из констант компонента (ТЗ §5). */
  speakers: Partial<Record<RadioSource, RadioSpeakerProfile>>
  /** Состояние канала: состояние активной передачи либо фаза PTT. */
  status: string
  active_message: RadioActiveMessage | null
  /** `null` означает «не менялась с присланной ревизии» (запрос с
   *  `?radio_since=`), а не «пустая». Пустая история — `[]`. */
  history: RadioHistoryEntry[] | null
  history_unchanged?: boolean
  ptt: RadioPtt
  /** Что произнесёт команда «повтори», null — повторять нечего. */
  repeatable: string | null
}

export type SpotterState = {
  connected: boolean
  speaking: boolean
  now_speaking: string
  radio_message?: RadioMessage
  radio?: RadioSection
  feed: FeedItem[]
  llm_engine: string
  /** "f1" | "iracing" — какой источник телеметрии реально слушает движок. */
  telemetry_source?: string
  udp_ip?: string
  udp_port?: number
  tts_engine: string
  tts_active?: string
  tts_fallback?: boolean
  speaker?: string
  voice_status: string
  voice_available: boolean
  metadata_loaded: boolean
  persona: string
  telemetry: Telemetry
  race: RaceData
  cpu: string
  ram: string
  settings: SettingsState
  track_ai?: TrackAIState
  strategy_ai?: StrategyAIState
  coach_ai?: CoachAIState
  rivals?: RivalsState
  yandex_ok?: boolean
  race_story?: RaceStory | null
  f1_benchmark?: F1BenchmarkState | null
  career_memory?: CareerMemoryState | null
  damage?: DamageState | null
  voice_query?: VoiceQuery | null
}

export type VoiceInfo = {
  voice: string
  speed?: string | number
  // Piper
  filename?: string
  found?: boolean
  size_mb?: number
  // Yandex
  display?: string
  emotion?: string
  /** Качество голоса признано приемлемым для эфира (yandex_ai/voices.py::
   *  PREMIUM_VOICES). Непремиальные остаются в каталоге и валидны для
   *  SpeechKit, но под эффектом рации звучат заметно «роботнее». */
  premium?: boolean
}

export type VoicesResponse = {
  engine: string
  yandex_attached: boolean
  yandex_healthy: boolean
  voices_dir: string
  voices: Record<string, VoiceInfo>
  piper_voices: Record<string, VoiceInfo>
  yandex_voices: Record<string, VoiceInfo>
}

export type MicDevice = { name: string; index: number; is_default: boolean }

export type OverlayGaps = {
  to_leader_ms: number | null
  to_front_ms: number | null
  to_behind_ms: number | null
  to_leader_str: string
  to_front_str: string
  to_behind_str: string
}

export type OverlayTyre = {
  compound: string
  age_laps: number | null
  wear_pct: number | null
  status: string
  compound_color: string
}

export type OverlayCorner = {
  name: string | null
  type: string | null
  phase: string
  sector: number
  attack_zone: boolean
  defense_advice: string
}

export type OverlaySituation = {
  intensity: number
  mode: string
  mode_label: string
  threat: string | null
  advice: string | null
}

export type OverlayStrategy = {
  action: string
  confidence: number
  advice: string | null
  tyre_status: string
}

export type OverlayRadarContact = {
  vehicle_idx: number
  side: "left" | "right"
  lateral_m: number
  longitudinal_m: number
}

export type OverlayRelativeRow = {
  vehicle_idx: number
  position: number
  driver: string
  team: string
  color: string
  gap_to_player_ms: number | null
  gap_to_player_str: string
  ahead: boolean | null
}

export type OverlayState = {
  position: number | null
  lap_current: number | null
  lap_total: number | null
  speed_kmh: number | null
  drs_active: boolean
  gaps: OverlayGaps
  tyre: OverlayTyre
  corner: OverlayCorner
  situation: OverlaySituation
  strategy: OverlayStrategy
  car: {
    fuel_kg: number | null
    /** Laps of fuel left relative to the race distance; negative = short. */
    fuel_delta_laps: number | null
    ers_percent: number | null
    ers_deploy_mode: number | null
    /** Harvested / deployed so far THIS lap, as % of the 4 MJ store. */
    ers_harvested_pct: number | null
    ers_deployed_pct: number | null
    power_ice_kw: number | null
    power_mguk_kw: number | null
    last_lap_ms: number | null
    last_lap_str: string
  }
  inputs: {
    throttle_pct: number | null
    brake_pct: number | null
    /** -1 = full left, 1 = full right. */
    steer: number | null
    rpm: number | null
    rev_lights_pct: number | null
  }
  session: {
    air_temp_c: number | null
    track_temp_c: number | null
    track_limit_warnings: number | null
    /** Metres to the next DRS zone; 0/null = not approaching one. */
    drs_distance_m: number | null
    drs_allowed: boolean
  }
  grid_top5: Array<{ position: number; driver: string; team: string; color: string }>
  radar: OverlayRadarContact[]
  relative: OverlayRelativeRow[]
  leader: string | null
}

export type YandexStatus = { connected: boolean; code: string; message: string }

export type F1SectorGap = { player_ms: number; gap_ms: number }

export type F1BenchmarkState = {
  gap_ms: number
  f1_driver: string
  f1_time_ms: number
  player_best_ms: number
  event: string | null
  year: number | null
  source: "fastest_lap" | "pole"
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
  // "api" — живые/кэшированные данные OpenF1; "seed" — зашитый статический
  // фолбэк (см. core/openf1_seed.py), не свежие данные текущего сезона; null —
  // секторов нет вообще.
  sectors_source: "api" | "seed" | null
  // true — секторов нет ИМЕННО из-за 401 (идёт live-сессия F1, OpenF1 блокирует
  // анонимный доступ) — отличать от «трассы нет в данных»/обычного сбоя сети.
  sectors_blocked: boolean
  interpretation: string
  comparison_disclaimer: string
}

export type CareerMemoryState = {
  gap_ms: number
  player_best_ms: number
  best_ever_ms: number
  best_ever_date: string | null
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
}

export type DamageState = {
  wing_damage: number
  floor_damage: number
  gearbox_damage: number
  engine_damage: number
}

export type RaceStory = {
  text: string
  track: string | null
  final_position: number | null
  /** "llm" — написано моделью, "fallback" — шаблон (commentator/story.py). */
  source?: string
  ts: number
}

export type VoiceQuery = {
  status: "listening" | "recognizing" | "thinking" | "done" | "error"
  question: string | null
  answer: string | null
  error: string | null
}

export type SessionItem = {
  path: string
  track_name: string | null
  timestamp: string | null
  final_position: number | null
  game_year: number | null
  session_type: string
}

export type CompareResult = {
  f1_meta: {
    event?: string
    year?: number
    results_top10?: { pos: number; driver: string; team: string; gap_s: number | null }[]
  }
  compare: {
    partial?: boolean
    player_best_lap_ms?: number | null
    player_best_lap_lap_number?: number | null
    f1_fastest_ms?: number | null
    f1_best_lap_driver?: string | null
    gap_ms?: number | null
    interpretation?: string
    comparison_disclaimer?: string
    sectors?: Record<"s1" | "s2" | "s3", { player_ms: number | null; f1_ms: number | null; gap_ms: number }>
    qwen_context?: string
  }
  compare_id?: string
  error?: string
}

async function asJson<T>(r: Response): Promise<T> {
  // 400 от бэкенда несёт полезный JSON ({error: ...}) — пропускаем его дальше.
  if (!r.ok && r.status !== 400) throw new Error("HTTP " + r.status)
  return r.json() as Promise<T>
}

const post = (url: string, body: unknown) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

/** Снимок состояния.
 *
 *  `radioSince` — известная клиенту ревизия радио. Если она совпала, сервер
 *  присылает `radio.history: null` и `history_unchanged: true` вместо ленты до
 *  150 строк. Нужно тем, кто опрашивает часто: оверлей делает это 4 раза в
 *  секунду и историю вообще не рисует. Без аргумента поведение прежнее. */
export const getState = (radioSince?: number) =>
  fetch(radioSince === undefined ? "/api/state" : `/api/state?radio_since=${radioSince}`)
    .then((r) => asJson<SpotterState>(r))

export const saveSettings = (patch: Partial<SettingsState>) =>
  post("/api/settings", patch).then((r) => asJson<{ ok: boolean }>(r))

export const resetSettings = (): Promise<{ ok: boolean; settings: SettingsState }> =>
  fetch("/api/settings/reset", { method: "POST" }).then((r) => asJson<{ ok: boolean; settings: SettingsState }>(r))

export const clearRadioHistory = () =>
  post("/api/radio/clear_history", {}).then((r) => asJson<{ ok: boolean }>(r))

export const testVoice = () =>
  fetch("/api/test_voice").then((r) => asJson<{ ok: boolean; error?: string; engine?: string }>(r))

export const clearLogs = () => fetch("/api/clear_logs").then((r) => asJson<{ ok: boolean }>(r))

export const highlight = () => fetch("/api/highlight").then((r) => asJson<{ ok: boolean }>(r))

export const generateStory = () =>
  fetch("/api/story/generate", { method: "POST" }).then((r) => asJson<{ ok: boolean }>(r))

export const replayStory = () =>
  fetch("/api/story/replay", { method: "POST" }).then((r) => asJson<{ ok: boolean }>(r))

export const askVoice = () =>
  fetch("/api/voice/ask", { method: "POST" }).then((r) =>
    asJson<{ ok: boolean; busy?: boolean; reason?: string }>(r))

export const getVoices = () => fetch("/api/voices").then((r) => asJson<VoicesResponse>(r))

export const getMicDevices = () =>
  fetch("/api/mic_devices").then((r) => asJson<{ devices: MicDevice[] }>(r))

export const testMic = () =>
  fetch("/api/mic_test", { method: "POST" }).then((r) => asJson<{ ok: boolean; error?: string }>(r))

export const getSessions = () => fetch("/api/sessions").then((r) => asJson<SessionItem[]>(r))

export const loadF1 = (body: { year: number; stype: string; game_session_path: string }) =>
  post("/api/load_f1", body).then((r) => asJson<CompareResult>(r))

export const getYandexStatus = () => fetch("/api/yandex/status").then((r) => asJson<YandexStatus>(r))

export const saveYandex = (body: { api_key: string; folder_id: string; auth_mode: string }) =>
  post("/api/yandex/credentials", body).then((r) => asJson<{ ok: boolean; code: string; message: string }>(r))

export type GigachatStatus = {
  connected: boolean
  code: string
  message: string
  masked_key?: string
  model?: string
  active?: boolean
}

export const getGigachatStatus = () => fetch("/api/gigachat/status").then((r) => asJson<GigachatStatus>(r))

export const saveGigachat = (body: { authorization_key: string }) =>
  post("/api/gigachat/credentials", body).then((r) => asJson<{ ok: boolean; code: string; message: string }>(r))

export const getOverlay = () => fetch("/api/overlay").then((r) => asJson<OverlayState>(r))

// ── Геометрия оверлея ───────────────────────────────────────────────────────
// Живёт отдельно от /api/settings: раскладку пишут восемь процессов виджетов, а
// сохранение настроек переписывает весь документ целиком (core/overlay_layout.py).

/** Геометрия одного виджета. Смещение отсутствует, пока его не двигали. */
export type OverlayWidgetGeometry = { dx?: number; dy?: number; scale: number }

export type OverlayLayoutState = {
  /** Имя последнего сохранённого или применённого пресета. */
  active: string | null
  names: string[]
  widgets: Record<string, OverlayWidgetGeometry>
  min_scale: number
  max_scale: number
}

export const getOverlayLayout = () =>
  fetch("/api/overlay/layout").then((r) => asJson<OverlayLayoutState>(r))

export const setOverlayScale = (widget: string, scale: number) =>
  post("/api/overlay/layout", { widget, scale }).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean; error?: string }>(r))

export const resetOverlayLayout = () =>
  post("/api/overlay/layout/reset", {}).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean }>(r))

export const overlayPreset = (action: "save" | "apply" | "delete", name: string) =>
  post("/api/overlay/presets", { action, name }).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean; error?: string }>(r))

export const getRaceFeed = () => fetch("/api/racefeed").then((r) => asJson<RaceFeedResponse>(r))

export const getSeasonStandings = () =>
  fetch("/api/racefeed/standings").then((r) => asJson<SeasonStandingsResponse>(r))

/** Счётчики конвейера репортажа за текущую сессию (core/racefeed/engine.py::_STAT_KEYS).
 *  Отвечают на вопрос «почему лента пустая»: нет событий / всё подавил Editor /
 *  отвалился LLM. */
export type RaceFeedStats = {
  events_ingested?: number
  events_dropped_full?: number
  candidates_proposed?: number
  candidates_suppressed?: number
  candidates_deferred?: number
  candidates_scheduled?: number
  posts_published?: number
  renders_failed?: number
  renders_fallback?: number
  comments_generated?: number
  comments_skipped?: number
}

export type RaceFeedStatsResponse = {
  enabled: boolean
  session_active?: boolean
  stats: RaceFeedStats
}

// Что реально удалось зарегистрировать в Windows (core/hotkeys.py). Комбинацию
// может держать другая программа — тогда хоткей выглядит настроенным и молча
// не работает; этот статус для того и нужен.
export type HotkeyStatusRow = {
  id: number
  action: string
  keys: string[]
  registered: boolean
  /** ok | taken | not_configured | conflict — core/hotkeys.py::STATUS_* */
  status: string
}

export type HotkeyStatusResponse = {
  /** false — хоткеи вообще не поднялись (headless-запуск, ошибка старта). */
  available: boolean
  /** false — поток хоткеев ещё не дошёл до регистрации. */
  ready: boolean
  hotkeys: HotkeyStatusRow[]
}

export const getHotkeyStatus = () =>
  fetch("/api/hotkeys/status").then((r) => asJson<HotkeyStatusResponse>(r))

export const getRaceFeedStats = () =>
  fetch("/api/racefeed/stats").then((r) => asJson<RaceFeedStatsResponse>(r))

/** Лента завершившейся гонки. Движок открывает новый SQLite на каждую сессию,
 *  поэтому без архива канал пуст всё время между гонками. */
export type RaceFeedArchiveSession = {
  session_id: string
  /** «Монца». Пусто для файлов, записанных до появления session_meta. */
  track_name: string
  /** race | qualifying | "" */
  session_type: string
  started_at: number
  post_count: number
  posts: RaceFeedPostRow[]
  prediction?: RacePredictionRow | null
}

export type RaceFeedArchiveResponse = {
  enabled: boolean
  sessions: RaceFeedArchiveSession[]
}

export const getRaceFeedArchive = () =>
  fetch("/api/racefeed/archive").then((r) => asJson<RaceFeedArchiveResponse>(r))

export type ReaderActionResult = {
  ok: boolean
  /** disabled | bad session id | no such post | empty comment | write_failed */
  reason?: string
  comment?: RaceFeedCommentRow
}

export type PredictionActionResult = {
  ok: boolean
  reason?: string
  prediction?: RacePredictionRow
}

/** Пустой emoji снимает реакцию — так же трактует это бэкенд. */
export const sendRaceFeedReaction = (
  body: { session_id: string; post_id: string; emoji: string },
) => post("/api/racefeed/react", body).then((r) => asJson<ReaderActionResult>(r))

export const sendRaceFeedVote = (
  body: { session_id: string; post_id: string; driver: string },
) => post("/api/racefeed/vote", body).then((r) => asJson<ReaderActionResult>(r))

export const sendRaceFeedComment = (
  body: { session_id: string; post_id: string; text: string },
) => post("/api/racefeed/comment", body).then((r) => asJson<ReaderActionResult>(r))

export const sendRaceFeedPrediction = (body: RacePredictionTicket) =>
  post("/api/racefeed/prediction", body).then((r) => asJson<PredictionActionResult>(r))
