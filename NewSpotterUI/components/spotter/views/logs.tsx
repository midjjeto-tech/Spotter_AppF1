"use client"

import { useEffect, useState } from "react"
import { PageHeader, Panel } from "../ui"
import { Button } from "@/components/ui/button"
import { feedToLog } from "@/lib/feed"
import {
  clearLogs,
  getRaceFeedStats,
  type RaceFeedStatsResponse,
  type SpotterState,
} from "@/lib/api"
import type { LogEntry } from "@/lib/spotter-data"
import { cn } from "@/lib/utils"
import { Trash2 } from "lucide-react"

// Раньше здесь стоял фильтр ALL/INFO/WARN/ERR, но у бэкенда нет уровней журнала
// — feedToLog() хардкодил всем INFO, и две кнопки из трёх всегда давали пустой
// список. Фильтруем по признаку, который бэкенд реально сообщает: прозвучала
// реплика вслух или осталась молча в ленте (FeedItem.muted).
const filters = [
  { id: "ALL", label: "ВСЁ" },
  { id: "SPOKEN", label: "ОЗВУЧЕНО" },
  { id: "SILENT", label: "БЕЗ ОЗВУЧКИ" },
] as const
type Filter = (typeof filters)[number]["id"]

const badge: Record<LogEntry["type"], string> = {
  SPOKEN: "bg-success/15 text-success",
  SILENT: "bg-secondary text-muted-foreground",
}

const badgeLabel: Record<LogEntry["type"], string> = {
  SPOKEN: "ГОЛОС",
  SILENT: "ТИХО",
}

/** Порядок и подписи счётчиков конвейера — сверху вниз по пути события:
 *  пришло → отобрал редактор → опубликовано → экспертные заметки. */
const pipelineRows: { key: keyof NonNullable<RaceFeedStatsResponse["stats"]>; label: string }[] = [
  { key: "events_ingested", label: "События приняты" },
  { key: "candidates_proposed", label: "Предложено репортёрами" },
  { key: "candidates_suppressed", label: "Отклонено редактором" },
  { key: "candidates_deferred", label: "Отложено (ждут последствия)" },
  { key: "posts_published", label: "Опубликовано постов" },
  { key: "renders_fallback", label: "Из них по шаблону (без ИИ)" },
  { key: "renders_failed", label: "Не отрисовано" },
  { key: "comments_generated", label: "Постов с AI-разбором" },
  { key: "comments_skipped", label: "Разбор не требовался" },
  { key: "events_dropped_full", label: "Потеряно (очередь полна)" },
]

function RaceFeedPipelinePanel() {
  const [data, setData] = useState<RaceFeedStatsResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = () =>
      getRaceFeedStats()
        .then((response) => {
          if (cancelled) return
          setData(response)
          setFailed(false)
        })
        .catch(() => {
          if (!cancelled) setFailed(true)
        })
    load()
    const timer = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  // Ноли вместо честного «выключено» — ровно то враньё UI про бэкенд, которое
  // мы вычищаем: пустая лента при выключенном тумблере и при мёртвом LLM
  // выглядела бы одинаково.
  let status = "Загрузка…"
  if (failed) status = "Нет связи с приложением"
  else if (data && !data.enabled) status = "Репортаж выключен"
  else if (data) status = data.session_active ? "Сессия идёт" : "Сессия не открыта"

  return (
    <Panel bodyClassName="p-0">
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <span className="label-mono text-[10px] text-muted-foreground">Конвейер репортажа</span>
        <span className="label-mono text-[10px] text-foreground/70">{status}</span>
      </div>
      {data?.enabled && !failed ? (
        <ul className="grid grid-cols-1 sm:grid-cols-2">
          {pipelineRows.map(({ key, label }) => (
            <li
              key={key}
              className="flex items-center justify-between border-b border-border px-5 py-2 last:border-0 sm:even:border-l"
            >
              <span className="text-sm text-foreground/90">{label}</span>
              <span className="font-mono text-xs text-muted-foreground tabular">
                {data.stats?.[key] ?? 0}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="px-5 py-8 text-center text-sm text-muted-foreground">
          {failed
            ? "Счётчики недоступны — приложение не отвечает"
            : "Счётчики появятся, когда репортаж включён в настройках"}
        </div>
      )}
    </Panel>
  )
}

export function LogsView({ state }: { state: SpotterState | null }) {
  const [filter, setFilter] = useState<Filter>("ALL")
  // «Очистить» стирает одну общую ленту бэкенда (state.feed), а её же читают
  // экран «События» и панель недавних событий в «Разборе» — без подтверждения
  // кнопка молча выносила все три. Двухшаговое подтверждение вместо диалога:
  // в pywebview window.confirm() не всегда доступен.
  const [confirmClear, setConfirmClear] = useState(false)
  const logs = (state?.feed ?? []).map(feedToLog)
  const filtered = filter === "ALL" ? logs : logs.filter((l) => l.type === filter)

  return (
    <div>
      <PageHeader
        title="Logs"
        subtitle="Системный журнал в реальном времени"
        action={
          confirmClear ? (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted-foreground">
                Очистит и «События», и «Разбор»
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  clearLogs()
                  setConfirmClear(false)
                }}
                className="border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
              >
                Подтвердить
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmClear(false)}
                className="border-border bg-secondary text-foreground hover:bg-elevated"
              >
                Отмена
              </Button>
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmClear(true)}
              className="border-border bg-secondary text-foreground hover:bg-elevated"
            >
              <Trash2 className="h-3.5 w-3.5" /> Очистить
            </Button>
          )
        }
      />

      <div className="mb-4">
        <RaceFeedPipelinePanel />
      </div>

      <div className="mb-4 flex items-center gap-1.5">
        {filters.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            className={cn(
              "label-mono rounded-md px-3 py-1.5 text-[10px] font-medium transition-colors",
              filter === f.id
                ? "bg-primary/15 text-primary"
                : "bg-secondary text-muted-foreground hover:text-foreground",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <Panel bodyClassName="p-0">
        <div className="grid grid-cols-[92px_84px_170px_1fr] border-b border-border px-5 py-3">
          <span className="label-mono text-[10px] text-muted-foreground">Время</span>
          <span className="label-mono text-[10px] text-muted-foreground">Голос</span>
          <span className="label-mono text-[10px] text-muted-foreground">Событие</span>
          <span className="label-mono text-[10px] text-muted-foreground">Реплика</span>
        </div>
        {filtered.length > 0 ? (
          <ul>
            {filtered.map((l, i) => (
              <li
                key={i}
                className="grid grid-cols-[92px_84px_170px_1fr] items-center border-b border-border px-5 py-3 last:border-0 hover:bg-secondary/40"
              >
                <span className="font-mono text-xs text-muted-foreground tabular">{l.time}</span>
                <span>
                  <span className={cn("label-mono rounded px-1.5 py-0.5 text-[9px] font-bold", badge[l.type])}>
                    {badgeLabel[l.type]}
                  </span>
                </span>
                <span className="label-mono truncate text-[10px] text-muted-foreground" title={l.code}>
                  {l.title}
                </span>
                <span className="text-sm text-foreground/90">{l.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="px-5 py-16 text-center text-sm text-muted-foreground">Журнал пуст</div>
        )}
      </Panel>
    </div>
  )
}
