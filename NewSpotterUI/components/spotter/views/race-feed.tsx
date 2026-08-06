"use client"

import { useRaceFeed, useRaceFeedArchive, useSeasonStandings } from "@/lib/use-racefeed"
import { toArchiveGroups, toRaceFeedPosts } from "@/lib/racefeed"
import { RaceFeedChannel, type RaceFeedChannelStatus } from "./race-feed-channel"

export function RaceFeedView({
  lastSeen = 0,
  onOpenSettings,
}: {
  lastSeen?: number
  onOpenSettings?: () => void
}) {
  const { data, error } = useRaceFeed()
  const archiveData = useRaceFeedArchive()
  const standings = useSeasonStandings()
  const posts = data ? toRaceFeedPosts(data.posts) : []
  // Ленты прошлых гонок. Без них канал пуст всё время между сессиями: движок
  // открывает новый SQLite на каждую гонку (RaceFeedEngine.reset), а живой
  // роут читает только текущий файл.
  const archive = archiveData ? toArchiveGroups(archiveData.sessions) : []
  // Экспертные заметки раскрываются по created_at внутри RaceFeedChannel на
  // секундном тикере; статус самой ленты зависит только от постов текущей гонки.
  // Архив остаётся видимым независимо от этого статуса.
  let status: RaceFeedChannelStatus = "loading"
  if (error) status = "error"
  else if (data && !data.enabled) status = "disabled"
  else if (data && posts.length === 0 && !data.prediction) status = "waiting"
  else if (posts.length > 0 || data?.prediction) status = "ready"

  return (
    <RaceFeedChannel
      posts={posts}
      archive={archive}
      prediction={data?.prediction ?? null}
      status={status}
      standings={standings?.standings ?? []}
      profile={standings?.profile ?? null}
      lastSeen={lastSeen}
      onOpenSettings={onOpenSettings}
    />
  )
}
