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
  /** Подсказки по ПИЛОТАЖУ (блокировка, пробуксовка, снос, занос, выезд).
   *  Независимая ось от engineer_chatter_enabled: инженера можно держать
   *  тихим, а подсказки по вождению включёнными. Звучат только на
   *  повторяющейся ошибке в одном повороте (core/coach_ai/corner_log.py). */
  driving_coach_enabled: boolean
  /** Приглушать звук игры на время реплики. `game_ducking_level` — до скольких
   *  процентов от ТЕКУЩЕЙ громкости игры; доля, а не абсолютная величина. */
  game_ducking_enabled: boolean
  game_ducking_level: number
  /** Второй экран: открыть UI по локальной сети. Токен в этот тип НЕ входит —
   *  он вырезан из снимка состояния и отдаётся только локальной ручкой
   *  /api/remote-access. */
  remote_access_enabled: boolean
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
  /** Визард первого запуска пройден или пропущен. Отдельный флаг, а не факт
   *  существования settings.json: файл создаётся первым же сохранением любой
   *  галочки. */
  onboarding_done: boolean
}

/** Готовность одной подсистемы. `status` — код, а не текст: формулировки
 *  живут в UI, коды в core/diagnostics.py. */
export type DiagnosticCheck = {
  status: string
  detail: string
}

export type TelemetryDiagnostic = DiagnosticCheck & {
  /** "f1" | "iracing" */
  source: string
  udp_ip: string
  udp_port: number
}

/** Снимок готовности. Отдельно от /api/state намеренно: там «связь есть/нет»
 *  одним булевом, здесь — ПРИЧИНА, по которой её нет. Занятый порт, выключенный
 *  в игре UDP и незапущенная игра требуют противоположных советов. */
export type Diagnostics = {
  telemetry: TelemetryDiagnostic
  voice: DiagnosticCheck
  brain: DiagnosticCheck
  mic: DiagnosticCheck
  hotkeys: DiagnosticCheck
  /** Только телеметрия + хоть какая-то озвучка. Ключи, микрофон и хоткеи сюда
   *  НЕ входят: без них продукт беднее, но работает. */
  ready: boolean
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

/** Самый проблемный поворот сессии: сколько ошибок и каких.
 *  Строится core/coach_ai/corner_log.py::top_corners. */
export type CoachCornerStat = {
  corner_id: number | null
  corner_name: string | null
  count: number
  kinds: Record<string, number>
}

/** Отклонения одного поворота от эталонного круга — СЫРЫЕ, без нормализации:
 *  на экране после сессии видны все столбцы сразу, и пилот сам различает общий
 *  сдвиг и локальную потерю. Строится core/coach_ai/compare.py::corner_deltas. */
export type CoachReferenceDelta = {
  corner_id: number
  corner_name: string | null
  duration_ms: number | null
  brake_delta: number | null
  min_speed_delta: number | null
  throttle_delta: number | null
}

export type CoachAIState = {
  weak_sector: number | null
  lost_time_ms: number | null
  consistency_score: number
  pace_delta_ms: number | null
  tyre_advice: string
  lap_count: number
  advice: string | null
  /** Топ-3 проблемных поворота. Полная карта «поворот × круг» живьём НЕ едет —
   *  она сохраняется в файл сессии (core/session_recorder.py::set_coach_map). */
  top_corners?: CoachCornerStat[]
  mistake_count?: number
  /** Отклонения от эталонного круга по поворотам (фаза 2). Живьём едут первые
   *  восемь; полная таблица сохраняется в файл сессии. */
  reference_deltas?: CoachReferenceDelta[]
  /** Чем является эталон: лучшим кругом на трассе за всю историю или лучшим в
   *  текущей сессии (первый визит). null — эталона ещё нет. */
  reference_source?: "career" | "session" | null
  /** Отчёт «Гараж» (фаза 3): во что стиль обошёлся машине. Компактен по
   *  построению, поэтому едет целиком. */
  garage?: CoachGarageReport
  /** Разбор сессии (фаза 4): потенциал круга, куда ушло время, что дальше.
   *  Пересчитывается РАЗ В КРУГ на бэкенде; null — данных ещё нет, и блок на
   *  экране должен отсутствовать целиком, а не показывать прочерки. */
  lesson?: CoachLesson | null
  /** Работа сессии: один поворот, над которым коуч работает прямо сейчас.
   *  Дублируется внутри `lesson.focus` — здесь для живого экрана, там для
   *  архива, куда разбор уезжает целиком. */
  focus?: CoachFocus | null
  /** Почему коуч молчит. Едет ВСЕГДА, в том числе с выключенным тумблером. */
  health?: CoachHealth
}

/** Положение игрока в ОДНОМ секторе относительно всего поля.
 *  Строится core/sector_standing.py из Session History (пакет 11). */
export type SectorStanding = {
  sector: 1 | 2 | 3
  player_ms: number
  best_ms: number
  /** null — имя ещё не приехало из метаданных пилотов. */
  best_holder: string | null
  rank: number
  field_size: number
  /** Никогда не отрицательный: лидер сектора имеет нулевой отрыв, а не минус. */
  gap_ms: number
}

/** Раскладка по секторам относительно поля.
 *
 *  Отдельная секция, а НЕ поле внутри `coach_ai`, и это не оформление: коуч
 *  отвечает «где ты теряешь относительно СЕБЯ» с разрешением до поворота и
 *  причины, здесь — «относительно НИХ» с разрешением до сектора. Первое лечится
 *  техникой, второе бывает и вопросом машины. */
export type FieldPace = {
  sectors: SectorStanding[]
  /** Наибольший отрыв до лучшего в поле — там, где лежит время. null, когда
   *  все отрывы ниже произносимого порога. */
  weakest: SectorStanding | null
  strongest: SectorStanding | null
  lap_rank: number | null
  lap_field_size: number
  lap_gap_ms: number | null
}

/** Один поворот в разборе: цена в миллисекундах за круг, доля от всей потери и
 *  ПРИЧИНА. Поворот без причины показывается как факт, но заданием не
 *  становится — указание, которое нельзя применить, не отличается от молчания.
 *  Строится core/coach_ai/diagnosis.py. */
export type CoachLoss = {
  corner_id: number
  corner_name: string | null
  cost_ms: number
  share: number
  laps: number
  cause: string | null
  cause_kind: "mistake" | "technique" | null
  occurrences: number
  evidence: string
}

/** Работа сессии (core/coach_ai/focus.py). `baseline_ms` — цена в момент, когда
 *  поворот взяли в работу; по разнице с `current_ms` видно, помогает ли то, что
 *  пилот меняет. */
export type CoachFocus = {
  corner_id: number
  corner_name: string | null
  cause: string | null
  cause_kind: "mistake" | "technique" | null
  evidence: string
  baseline_ms: number
  current_ms: number
  gain_ms: number
  since_lap: number
  status: "working" | "improving"
}

/** Прогресс относительно прошлого визита на эту трассу. Читается из файла
 *  прошлого заезда (core/coach_ai/reference_store.py::load_track_history). */
export type CoachProgress = {
  previous_best_lap_ms: number | null
  best_delta_ms: number | null
  focus_corner_id: number | null
  focus_then_ms: number | null
  focus_now_ms: number | null
  text: string
}

/** Вердикт сессии (core/coach_ai/lesson.py). `potential_ms` — круг, собранный
 *  из СВОИХ ЖЕ лучших поворотов: не чужой темп и не мечта, каждый кусок пилот
 *  уже проехал сам. */
export type CoachLesson = {
  best_lap_ms: number | null
  potential_ms: number | null
  gain_ms: number | null
  potential_clamped: boolean
  total_loss_ms: number
  /** Доля показанных поворотов в общей потере — остальное размазано по кругу. */
  concentration: number
  losses: CoachLoss[]
  headline: string
  next_step: string | null
  focus: CoachFocus | null
  progress?: CoachProgress
  /** Та же потеря в разрезе типов поворотов: «в седьмом» лечится техникой,
   *  «во всех медленных» — машиной. */
  by_type?: CoachTypeLoss[]
}

/** Перекос износа и нагрева резины. Износ сравнивается ВНУТРИ оси, нагрев — по
 *  всем четырём колёсам. */
export type CoachTyreLoad = {
  worst_wheel: string | null
  worst_axle: "front" | "rear" | null
  wear_spread_pct: number
  hottest_wheel: string | null
  temp_spread_c: number
}

/** Совет по гаражу. Только баланс тормозов и дифференциал: причинной модели
 *  крыльев и подвески в F1 25 у нас нет, и догадку пилот не отличит от
 *  обоснованного вывода. `evidence` обязателен — совет без основания это
 *  приказ. */
export type CoachSetupHint = {
  parameter: "brake_bias" | "diff_on_throttle"
  direction: "up" | "down"
  advice: string
  evidence: string
}

/** Подпись машины: одинаковое поведение в непохожих местах трассы.
 *
 *  Прижимная сила растёт с квадратом скорости, поэтому снос на МЕДЛЕННЫХ
 *  поворотах и снос на БЫСТРЫХ имеют разные причины — механику и аэродинамику.
 *  Модуль говорит, куда смотреть, и намеренно не называет чисел: величина
 *  зависит от трассы и от того, что уже стоит в сетапе.
 *  Строится core/coach_ai/corner_types.py::balance_signature. */
export type CoachBalanceSignature = {
  kind: "understeer" | "oversteer"
  domain: "mechanical" | "aero"
  corners_affected: number
  corners_total: number
  evidence: string
  advice: string
}

export type CoachGarageReport = {
  tyre_load: CoachTyreLoad | null
  setup: Record<string, number | Record<string, number>>
  hints: CoachSetupHint[]
  balance?: CoachBalanceSignature | null
}

/** Состояние самого коуча: почему он молчит.
 *
 *  Молчащий коуч выглядит одинаково при выключенном тумблере, неповторяющейся
 *  ошибке, не доехавшей телеметрии движения и завышенном пороге — четыре разных
 *  диагноза с четырьмя разными действиями. `reason` — готовая фраза; null
 *  означает «объяснять нечего», а не «неизвестно».
 *  Строится core/coach_ai/health.py. */
export type CoachHealth = {
  signal: "ok" | "no_frames" | "flat" | "implausible" | "warming_up"
  frames: number
  moving_frames: number
  mistakes: number
  spoken: number
  silence: Record<string, number>
  reason: string | null
  enabled: boolean
  thresholds: Record<string, number>
  peak_slip_ratio: number
  peak_slip_angle: number
}

/** Потеря по всем поворотам одного типа. `label` приходит с бэкенда готовым —
 *  второй копии словаря типов в UI быть не должно. */
export type CoachTypeLoss = {
  corner_type: string
  cost_ms: number
  corners: number
  share: number
  label: string
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
  /** База знаний комментатора: "ok" | "loading" | "no-package" | "no-facts"
   *  | "error" | "no-module". Приезжает всегда — выключенный RAG иначе виден
   *  только в логе, а снаружи неотличим от работающего. */
  rag_status?: string
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
  /** Положение в поле по секторам. null до первого завершённого круга. */
  field_pace?: FieldPace | null
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

// Эталон темпа — быстрейший круг ПОЛЯ текущей сессии (core/f1_benchmark.py).
// До 2026-08-08 здесь лежало сравнение с реальным Гран-при (Jolpica + OpenF1);
// источник удалён как непригодный для продаваемой сборки, см. NOTICE.
export type F1BenchmarkState = {
  gap_ms: number
  // Пилот, чей круг стал эталоном. Пустая строка — участник ещё не приехал
  // в race_state, время уже есть, а имени нет.
  f1_driver: string
  f1_time_ms: number
  player_best_ms: number
  // Всегда null: «событие» и «год» описывали реальный Гран-при. Ключи
  // сохранены, потому что бэкенд отдаёт их безусловно.
  event: string | null
  year: number | null
  source: "field"
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
  // "field" — секторы той же машины, что дала эталонный круг; null — полного
  // набора s1/s2/s3 у неё нет (частичный намеренно не показываем).
  sectors_source: "field" | null
  interpretation: string
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

/** Токен второго экрана.
 *
 *  Локальный UI (webview на той же машине) токена не имеет и не должен —
 *  политика на сервере пускает loopback всегда. Токен нужен ТОЛЬКО телефону:
 *  он приходит один раз в адресе (`/?token=…`), сохраняется и сразу вычищается
 *  из строки браузера, чтобы не оставаться в истории и на скриншотах. */
const TOKEN_KEY = "spotter_remote_token"

function readToken(): string {
  if (typeof window === "undefined") return ""
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("token")
    if (fromUrl) {
      window.localStorage.setItem(TOKEN_KEY, fromUrl)
      // Чистка адреса — ПОСЛЕ гидратации: этот модуль грузится раньше неё, и
      // роутер Next возвращает исходную строку обратно, если переписать её
      // сейчас. Проверено в браузере: без задержки токен оставался в адресе.
      window.setTimeout(() => {
        try {
          const clean = window.location.pathname + window.location.hash
          window.history.replaceState(null, "", clean)
        } catch {
          // Не критично: токен уже сохранён, дальше он берётся из хранилища.
        }
      }, 0)
      return fromUrl
    }
    return window.localStorage.getItem(TOKEN_KEY) ?? ""
  } catch {
    // Приватный режим/заблокированное хранилище — работаем без токена.
    return ""
  }
}

let token = ""
if (typeof window !== "undefined") token = readToken()

/** Единственная точка сетевых вызовов этого модуля.
 *
 *  Явная обёртка, а не патч глобального fetch: скрытый шов здесь означал бы,
 *  что пропущенный вызов ломается ТОЛЬКО на телефоне и только у того, кто
 *  включил второй экран. `grep "fetch("` по этому файлу должен находить лишь
 *  строку ниже. */
function http(input: string, init?: RequestInit): Promise<Response> {
  if (!token) return fetch(input, init)
  const headers = new Headers(init?.headers)
  headers.set("X-Spotter-Token", token)
  return fetch(input, { ...init, headers })
}

async function asJson<T>(r: Response): Promise<T> {
  // 400 от бэкенда несёт полезный JSON ({error: ...}) — пропускаем его дальше.
  if (!r.ok && r.status !== 400) throw new Error("HTTP " + r.status)
  return r.json() as Promise<T>
}

const post = (url: string, body: unknown) =>
  http(url, {
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
  http(radioSince === undefined ? "/api/state" : `/api/state?radio_since=${radioSince}`)
    .then((r) => asJson<SpotterState>(r))

export const saveSettings = (patch: Partial<SettingsState>) =>
  post("/api/settings", patch).then((r) => asJson<{ ok: boolean }>(r))

export const resetSettings = (): Promise<{ ok: boolean; settings: SettingsState }> =>
  http("/api/settings/reset", { method: "POST" }).then((r) => asJson<{ ok: boolean; settings: SettingsState }>(r))

export const clearRadioHistory = () =>
  post("/api/radio/clear_history", {}).then((r) => asJson<{ ok: boolean }>(r))

export const testVoice = () =>
  http("/api/test_voice").then((r) => asJson<{ ok: boolean; error?: string; engine?: string }>(r))

export const clearLogs = () => http("/api/clear_logs").then((r) => asJson<{ ok: boolean }>(r))

export const highlight = () => http("/api/highlight").then((r) => asJson<{ ok: boolean }>(r))

export const generateStory = () =>
  http("/api/story/generate", { method: "POST" }).then((r) => asJson<{ ok: boolean }>(r))

export const replayStory = () =>
  http("/api/story/replay", { method: "POST" }).then((r) => asJson<{ ok: boolean }>(r))

export const askVoice = () =>
  http("/api/voice/ask", { method: "POST" }).then((r) =>
    asJson<{ ok: boolean; busy?: boolean; reason?: string }>(r))

export const getVoices = () => http("/api/voices").then((r) => asJson<VoicesResponse>(r))

/** Адрес второго экрана. Ручка ЛОКАЛЬНАЯ: с телефона она отдаёт 401, потому что
 *  токен показывают только на той машине, где запущено приложение. */
export type RemoteAccessInfo = {
  enabled: boolean
  url: string
  token: string
  host: string
}

export const getRemoteAccess = () =>
  http("/api/remote-access").then((r) => asJson<RemoteAccessInfo>(r))

/** Позиции всех машин по кругам. Снимок берётся в момент, когда линию
 *  пересекает ИГРОК: соперники могут быть на другом круге, и подпись на
 *  графике обязана это говорить. */
export type RaceMapRow = {
  vehicle_idx: number
  name: string | null
  is_player: boolean
  positions: (number | null)[]
}

export type RaceMapSummary = {
  start_position: number
  end_position: number
  net: number
  worst_lap: number | null
  worst_delta: number
}

export type RaceMapResponse = {
  laps: number[]
  pit_laps: number[]
  rows: RaceMapRow[]
  summary: RaceMapSummary | null
}

/** Отдельный эндпоинт, а не поле /api/state: сетка на 22 машины за 60 кругов
 *  весит больше тысячи чисел, а состояние опрашивают восемь окон оверлея
 *  каждые 250 мс. Дебриф читает карту по запросу. */
export const getRaceMap = () =>
  http("/api/race-map").then((r) => asJson<RaceMapResponse>(r))

export const getDiagnostics = () =>
  http("/api/diagnostics").then((r) => asJson<Diagnostics>(r))

export const getMicDevices = () =>
  http("/api/mic_devices").then((r) => asJson<{ devices: MicDevice[] }>(r))

export const testMic = () =>
  http("/api/mic_test", { method: "POST" }).then((r) => asJson<{ ok: boolean; error?: string }>(r))

export const getSessions = () => http("/api/sessions").then((r) => asJson<SessionItem[]>(r))

// Сравнение разбираемого заезда с самым быстрым СВОИМ на той же трассе.
// Раньше здесь грузилась реальная сессия F1 и требовались год и тип сессии —
// выбирать больше не из чего, эталон определяется однозначно (см. NOTICE).
export const compareOwn = (body: { game_session_path: string }) =>
  post("/api/compare_own", body).then((r) => asJson<CompareResult>(r))

export const getYandexStatus = () => http("/api/yandex/status").then((r) => asJson<YandexStatus>(r))

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

export const getGigachatStatus = () => http("/api/gigachat/status").then((r) => asJson<GigachatStatus>(r))

export const saveGigachat = (body: { authorization_key: string }) =>
  post("/api/gigachat/credentials", body).then((r) => asJson<{ ok: boolean; code: string; message: string }>(r))

export const getOverlay = () => http("/api/overlay").then((r) => asJson<OverlayState>(r))

// ── Геометрия оверлея ───────────────────────────────────────────────────────
// Живёт отдельно от /api/settings: раскладку пишут восемь процессов виджетов, а
// сохранение настроек переписывает весь документ целиком (core/overlay_layout.py).

/** Геометрия одного виджета. Смещение отсутствует, пока его не двигали.
 *  `enabled=false` — виджет выключен: его процесс не поднимается вовсе. */
export type OverlayWidgetGeometry = {
  dx?: number
  dy?: number
  scale: number
  enabled?: boolean
}

export type OverlayLayoutState = {
  /** Имя последнего сохранённого или применённого пресета. */
  active: string | null
  names: string[]
  widgets: Record<string, OverlayWidgetGeometry>
  min_scale: number
  max_scale: number
}

export const getOverlayLayout = () =>
  http("/api/overlay/layout").then((r) => asJson<OverlayLayoutState>(r))

export const setOverlayScale = (widget: string, scale: number) =>
  post("/api/overlay/layout", { widget, scale }).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean; error?: string }>(r))

export const setOverlayEnabled = (widget: string, enabled: boolean) =>
  post("/api/overlay/layout", { widget, enabled }).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean; error?: string }>(r))

export const resetOverlayLayout = () =>
  post("/api/overlay/layout/reset", {}).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean }>(r))

export const overlayPreset = (action: "save" | "apply" | "delete", name: string) =>
  post("/api/overlay/presets", { action, name }).then((r) =>
    asJson<OverlayLayoutState & { ok: boolean; error?: string }>(r))

export const getRaceFeed = () => http("/api/racefeed").then((r) => asJson<RaceFeedResponse>(r))

export const getSeasonStandings = () =>
  http("/api/racefeed/standings").then((r) => asJson<SeasonStandingsResponse>(r))

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
  http("/api/hotkeys/status").then((r) => asJson<HotkeyStatusResponse>(r))

export const getRaceFeedStats = () =>
  http("/api/racefeed/stats").then((r) => asJson<RaceFeedStatsResponse>(r))

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
  http("/api/racefeed/archive").then((r) => asJson<RaceFeedArchiveResponse>(r))

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
