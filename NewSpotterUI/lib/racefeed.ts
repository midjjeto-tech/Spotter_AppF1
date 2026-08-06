// Преобразование сырых постов бэкенда (/api/racefeed) в RaceFeedPost для UI.
// Отдельно от lib/feed.ts (state.feed) — RaceFeed постит из своей SQLite,
// не из общей телеметрийной ленты.

import type {
  RaceFeedArchiveSession, RaceFeedCommentRow, RaceFeedPostRow, RacePredictionRow,
} from "./api"
import type { RaceFeedComment, RaceFeedPost } from "./spotter-data"

const REPORTER_LABEL: Record<string, string> = {
  race_control: "Дирекция гонки",
  spotter_analytics: "Аналитика Spotter",
  players_garage: "Боксы игрока",
  qualifying_control: "Квалификация",
  championship_desk: "Чемпионат",
  achievements: "Достижения",
  paddock: "Паддок",
}

const FORMAT_LABEL: Record<string, string> = {
  breaking: "Срочно",
  official_update: "Бюллетень",
  live_update: "Live",
  garage_update: "Из боксов",
  tactical_note: "Тактика",
  stat_brief: "Цифра круга",
  trend_watch: "Тренд",
  analysis: "Разбор",
}

/** Одна реплика треда. Вынесено из toRaceFeedPosts, потому что ответ читателя
 *  приходит отдельной строкой из POST /api/racefeed/comment (reader.add_comment
 *  возвращает её именно затем, чтобы показать сразу, не дожидаясь опроса). */
export function toRaceFeedComment(comment: RaceFeedCommentRow): RaceFeedComment {
  return {
    id: comment.id,
    parentId: comment.parent_id,
    authorId: comment.author_id,
    authorName: comment.author_name,
    authorBadge: comment.author_badge,
    avatar: comment.avatar,
    text: comment.text,
    time: new Date(comment.created_at * 1000).toLocaleTimeString("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
    }),
    revealAt: comment.created_at,
    likes: comment.likes,
  }
}

export function toRaceFeedPosts(rows: RaceFeedPostRow[]): RaceFeedPost[] {
  return rows
    .slice()
    .sort((a, b) => b.published_at - a.published_at)
    .map((p) => ({
      id: p.id,
      sessionId: p.session_id ?? "",
      myReaction: p.reader?.reaction ?? "",
      myVote: p.reader?.vote ?? "",
      time: new Date(p.published_at * 1000).toLocaleTimeString("ru-RU"),
      publishedAt: p.published_at,
      reporterId: p.reporter_id,
      reporter: REPORTER_LABEL[p.reporter_id] ?? p.reporter_id,
      category: p.category,
      text: p.text,
      driver: p.driver,
      isPlayerStory: Boolean(p.is_player_story),
      poll: p.metadata?.poll ?? [],
      interview: p.metadata?.interview ?? [],
      recap: p.metadata?.recap ?? null,
      comparison: p.metadata?.comparison ?? null,
      storylines: p.metadata?.storylines ?? [],
      returnHook: p.metadata?.return_hook ?? null,
      weekendDuel: p.metadata?.weekend_duel ?? null,
      format: FORMAT_LABEL[p.format_id] ?? p.format_id,
      image: p.image ?? "",
      comments: (p.comments ?? []).map(toRaceFeedComment),
    }))
}

const SESSION_TYPE_LABEL: Record<string, string> = {
  race: "Гран-при",
  qualifying: "Квалификация",
  sprint: "Спринт",
}

export type RaceFeedArchiveGroup = {
  sessionId: string
  /** «Гран-при · Монца» или «26 июля, 20:23» для файлов без метаданных. */
  title: string
  /** Дата под заголовком разделителя. */
  subtitle: string
  posts: RaceFeedPost[]
  prediction?: RacePredictionRow | null
}

/** Ленты прошлых гонок под разделителями. Метаданные появились позже самих
 *  файлов, поэтому сессия без трассы подписывается своей датой. */
export function toArchiveGroups(sessions: RaceFeedArchiveSession[]): RaceFeedArchiveGroup[] {
  return sessions.map((session) => {
    const date = new Date(session.started_at * 1000)
    const dateLabel = date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" })
    const timeLabel = date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
    // Early session_meta could retain the previous qualifying type when SSTA
    // arrived before the engine snapshot switched to race. Championship and
    // post-race paddock posts are authoritative evidence that this was a race.
    const containsRaceFinish = session.posts.some((post) => [
      "championship", "race_recap", "driver_of_the_day", "post_race_interview",
    ].includes(post.category))
    const sessionType = containsRaceFinish ? "race" : session.session_type
    const kind = SESSION_TYPE_LABEL[sessionType] ?? ""
    const title = session.track_name
      ? [kind, session.track_name].filter(Boolean).join(" · ")
      : `${dateLabel}, ${timeLabel}`
    return {
      sessionId: session.session_id,
      title,
      subtitle: session.track_name ? `${dateLabel}, ${timeLabel}` : "",
      posts: toRaceFeedPosts(session.posts),
      prediction: session.prediction ?? null,
    }
  })
}
