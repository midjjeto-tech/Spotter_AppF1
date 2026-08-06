// Типы экранов и статическая UI-метаданные (персоны, хоткеи).
// Живые данные приходят из бэкенда — см. lib/api.ts и lib/use-spotter-state.ts.

import type {
  ChampionshipComparisonRow, InterviewQuoteRow, PollCandidateRow, RaceRecapRow,
  ReturnHookRow, SeasonStorylineRow, WeekendDuelRow,
} from "./api"

export type ViewId =
  | "dashboard"
  | "race"
  | "voice"
  | "events"
  | "settings"
  | "logs"
  | "hotkeys"
  | "archive"
  | "debrief"
  | "broadcast-overlay"
  | "race-feed"
  | "team-radio"

export type Driver = {
  pos: number
  code: string
  name: string
  team: string
  teamColor: string
  gap: string
  tyre: "S" | "M" | "H" | "I" | "W" | "—"
  pit: number
  isPlayer?: boolean
}

export type RaceEvent = {
  id: string
  time: string
  kind:
    | "overtake"
    | "pit"
    | "penalty"
    | "incident"
    | "info"
    | "fastest"
    | "flag"
    | "spotter"
    | "engineer"
    | "strategy"
    | "tyre"
    | "story"
  title: string
  text: string
  driver: string
  /** false — событие только в ленте, вслух не прозвучало (backend: muted). */
  spoken: boolean
  channel: string
  channelLabel: string
}

// У бэкенда нет уровней журнала (см. lib/feed.ts) — то, что он реально знает
// про каждую запись, это прозвучала она или осталась молча в ленте.
export type LogEntry = {
  time: string
  type: "SPOKEN" | "SILENT"
  message: string
  code: string
  title: string
}

export type RaceFeedPost = {
  id: string
  /** Файл гонки, в который пишутся действия читателя. */
  sessionId: string
  /** Реакция читателя на этот пост, "" — не ставил. */
  myReaction: string
  /** Его локальный выбор в опросе этого поста, "" — не голосовал. */
  myVote: string
  time: string
  publishedAt: number
  reporterId: string
  reporter: string
  category: string
  text: string
  driver: string | null
  isPlayerStory: boolean
  poll: PollCandidateRow[]
  interview: InterviewQuoteRow[]
  recap: RaceRecapRow | null
  comparison: ChampionshipComparisonRow | null
  storylines: SeasonStorylineRow[]
  returnHook: ReturnHookRow | null
  weekendDuel: WeekendDuelRow | null
  format: string
  image: string
  comments: RaceFeedComment[]
}

export type RaceFeedComment = {
  id: string
  parentId: string | null
  authorId: string
  authorName: string
  authorBadge: string
  avatar: string
  text: string
  time: string
  revealAt: number
  likes: number
}

// Список хоткеев больше не дублируется здесь: он приходит из
// /api/hotkeys/status (core/hotkeys.py::_HOTKEY_LABELS) вместе с признаком, что
// комбинацию реально удалось зарегистрировать в Windows. Хардкоп на фронте
// показывал бы занятую другой программой клавишу как рабочую.

export type Persona = {
  id: string
  name: string
  tagline: string
  description: string
  color: string
}

// Презентационные метаданные персон. id совпадает с backend (config.PERSONA / core/hotkeys _PERSONAS).
export const personas: Persona[] = [
  {
    id: "tv",
    name: "TV",
    tagline: "Телевизионный",
    description: "Энергичный комментатор как Дэвид Крофт. Профессионально, но эмоционально.",
    color: "#E8002D",
  },
  {
    id: "hype",
    name: "Hype",
    tagline: "Фанат на стриме",
    description: "Комментатор-фанат. Кричит от восторга, использует сленг и восклицания.",
    color: "#FF8000",
  },
  {
    id: "calm",
    name: "Calm",
    tagline: "Аналитик",
    description: "Спокойный аналитик. Объясняет происходящее сдержанно, по делу, без лишних эмоций.",
    color: "#27F4D2",
  },
  {
    id: "toxic",
    name: "Toxic",
    tagline: "Напарник",
    description: "Токсичный напарник. Саркастично комментирует, подшучивает даже над неудачей.",
    color: "#A855F7",
  },
]

// Персонажи инженера. id обязаны совпадать с core/radio/voice_cast.py::CHARACTERS
// — тот же контракт «две копии списка», что и у personas выше.
export type EngineerCharacter = {
  id: string
  name: string
  tagline: string
  description: string
  /** Отображаемое имя ОСНОВНОГО голоса. Нужно, чтобы UI мог сравнить его с
   *  реально звучащим (/api/voices) и честно показать замену, когда основной
   *  занят персоной комментатора. */
  primaryVoice: string
}

export const engineerCharacters: EngineerCharacter[] = [
  // Описания говорят ТОЛЬКО про голос и темп — то, что различается уже сейчас.
  // Манера речи (обращение по имени, похвала, регистр) у всех троих пока
  // одинаковая: банк фраз общий. Обещать здесь характер значит продать то, чего
  // в сборке нет — ровно та ошибка, ради исправления которой из этого экрана
  // убрали блок «инженер всегда говорит голосом calm».
  //
  // Про голос сказано «основной»: если выбранную персону комментатора уже
  // озвучивает этот голос, инженер уходит на запасной (core/radio/voice_cast.py).
  // Поэтому Соколова не описана как «женский голос» — при persona=calm марина
  // занята комментатором, и Соколова звучит мужским запасным.
  {
    id: "volkov",
    name: "Игорь Волков",
    tagline: "Ровный темп",
    description: "Нейтральная скорость речи.",
    primaryVoice: "Александр",
  },
  {
    id: "sokolova",
    name: "Марина Соколова",
    tagline: "Чуть медленнее",
    description: "Речь немного спокойнее обычной.",
    primaryVoice: "Марина",
  },
  {
    id: "grom",
    name: "Виктор Гром",
    tagline: "Быстрее и резче",
    description: "Повышенная скорость речи.",
    primaryVoice: "Антон",
  },
]
