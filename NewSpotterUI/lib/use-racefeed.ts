"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  getRaceFeed, getRaceFeedArchive, getSeasonStandings,
  type RaceFeedArchiveResponse, type RaceFeedResponse, type RacePredictionRow,
  type SeasonStandingsResponse,
} from "./api"

const LAST_SEEN_KEY = "racefeed:lastSeen"

export type RaceFeedHubSummary = {
  loaded: boolean
  enabled: boolean | null
  livePostCount: number
  liveFinished: boolean
  latestLiveText: string
  prediction: RacePredictionRow | null
  latestArchive: {
    trackName: string
    postCount: number
    startedAt: number
  } | null
}

// Отдельный опрос /api/racefeed раз в 3с (не 1с, как useSpotterState) — посты
// публикуются с задержкой в 2-35с по дизайну, чаще опрашивать бессмысленно.
// Тот же паттерн self-rescheduling setTimeout, что и useSpotterState — см.
// комментарий там про накладывающиеся запросы при подвисании.
export function useRaceFeed(intervalMs = 3000) {
  const [data, setData] = useState<RaceFeedResponse | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const d = await getRaceFeed()
        if (!alive) return
        setData(d)
        setError(false)
      } catch {
        if (alive) setError(true)
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }

    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return { data, error }
}

// Ленты прошлых гонок (/api/racefeed/archive). Раз в минуту, а не раз в 3с, как
// живая лента: набор архивных гонок меняется только когда закончилась очередная
// сессия. Сами файлы неизменяемы и кэшируются на бэкенде (ui_bridge), поэтому
// повторный запрос почти бесплатен.
export function useRaceFeedArchive(intervalMs = 60000) {
  const [data, setData] = useState<RaceFeedArchiveResponse | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const d = await getRaceFeedArchive()
        // Ответ большой (8 гонок ≈ 1 МБ) и меняется только когда закончилась
        // очередная сессия. Без этой проверки каждый опрос подсовывал бы новый
        // объект — и React перерисовывал бы все сотни архивных постов, ради
        // которых мемоизация в RaceFeedChannel и делалась.
        if (alive) setData((prev) => (signature(prev) === signature(d) ? prev : d))
      } catch {
        /* keep the last-known archive on a transient error */
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return data
}

/** Дёшево отличает «архив тот же» от «появилась новая гонка»: состав сессий и
 *  число постов в каждой. Архивные файлы неизменяемы, поэтому этого хватает. */
function signature(response: RaceFeedArchiveResponse | null): string {
  if (!response) return ""
  return response.sessions.map((s) =>
    `${s.session_id}:${s.post_count}:${s.prediction?.status ?? ""}:${s.prediction?.resolved_at ?? 0}`,
  ).join("|")
}

// Сезонная таблица чемпионата (/api/racefeed/standings). Отдельный опрос раз в
// 5с — таблица меняется только на финише гонки, чаще незачем.
export function useSeasonStandings(intervalMs = 5000) {
  const [data, setData] = useState<SeasonStandingsResponse | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const d = await getSeasonStandings()
        if (alive) setData(d)
      } catch {
        /* leave last-known standings on a transient error */
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return data
}

// Счётчик непрочитанных постов RaceFeed для бейджа в сайдбаре. Опрашивает ленту
// на уровне страницы (работает даже когда вкладка «Репортаж» не открыта). Что
// «прочитано» — храним как последний виденный published_at в localStorage;
// markSeen() вызывается, когда пользователь на вкладке RaceFeed, и обнуляет
// бейдж. Опрос совпадает по кадансу с useRaceFeed (3с).
export function useRaceFeedUnread(intervalMs = 3000) {
  const [lastSeen, setLastSeen] = useState<number>(() =>
    typeof window === "undefined"
      ? 0
      : Number(window.localStorage.getItem(LAST_SEEN_KEY) ?? 0))
  const [liveData, setLiveData] = useState<RaceFeedResponse | null>(null)
  const [archiveData, setArchiveData] = useState<RaceFeedArchiveResponse | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const d = await getRaceFeed()
        if (alive) setLiveData(d)
      } catch {
        /* transient error — keep the last-known set */
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  // A finished session immediately moves out of /api/racefeed. Keep its final
  // posts in the badge through the archive too, otherwise the very DOTD and
  // interview meant to bring the reader back disappear from unread state.
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const d = await getRaceFeedArchive()
        if (alive) setArchiveData(d)
      } catch {
        /* transient error — keep the last-known archive set */
      } finally {
        if (alive) timer = setTimeout(tick, 60000)
      }
    }
    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [])

  const timestamps = useMemo(() => [...new Set([
    ...(liveData?.posts ?? []).map((post) => post.published_at),
    ...(archiveData?.sessions ?? []).flatMap((session) =>
      session.posts.map((post) => post.published_at)),
  ])], [liveData, archiveData])

  const markSeen = useCallback(() => {
    const newest = timestamps.length ? Math.max(...timestamps) : lastSeen
    setLastSeen(newest)
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LAST_SEEN_KEY, String(newest))
    }
  }, [timestamps, lastSeen])

  const unread = timestamps.filter((t) => t > lastSeen).length
  const latestLive = (liveData?.posts ?? []).reduce((latest, post) =>
    !latest || post.published_at > latest.published_at ? post : latest,
  undefined as RaceFeedResponse["posts"][number] | undefined)
  const latestArchive = archiveData?.sessions[0]
  const finalCategories = new Set([
    "race_recap", "championship", "driver_of_the_day", "post_race_interview",
  ])
  const hub: RaceFeedHubSummary = {
    loaded: liveData !== null || archiveData !== null,
    enabled: liveData?.enabled ?? archiveData?.enabled ?? null,
    livePostCount: liveData?.posts.length ?? 0,
    liveFinished: Boolean(liveData?.posts.some((post) => finalCategories.has(post.category))),
    latestLiveText: latestLive?.text ?? "",
    prediction: liveData?.prediction ?? null,
    latestArchive: latestArchive ? {
      trackName: latestArchive.track_name,
      postCount: latestArchive.post_count,
      startedAt: latestArchive.started_at,
    } : null,
  }
  return { unread, lastSeen, markSeen, hub }
}
