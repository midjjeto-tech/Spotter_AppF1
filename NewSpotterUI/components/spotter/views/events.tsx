"use client"

import { PageHeader, Panel } from "../ui"
import { feedToEvent } from "@/lib/feed"
import type { SpotterState } from "@/lib/api"
import type { RaceEvent } from "@/lib/spotter-data"
import { cn } from "@/lib/utils"
import {
  ArrowUpRight,
  Wrench,
  AlertTriangle,
  AlertOctagon,
  Info,
  Timer,
  Zap,
  Flag,
  Radar,
  Headset,
  Route,
  CircleDot,
  BookOpen,
} from "lucide-react"

const meta: Record<RaceEvent["kind"], { icon: typeof Info; color: string; bg: string }> = {
  overtake: { icon: ArrowUpRight, color: "text-success", bg: "bg-success/12" },
  pit: { icon: Wrench, color: "text-[#5b8fe0]", bg: "bg-[#3671C6]/15" },
  penalty: { icon: AlertOctagon, color: "text-primary", bg: "bg-primary/12" },
  incident: { icon: AlertTriangle, color: "text-warning", bg: "bg-warning/12" },
  info: { icon: Info, color: "text-muted-foreground", bg: "bg-secondary" },
  fastest: { icon: Timer, color: "text-[#b97aff]", bg: "bg-[#A855F7]/15" },
  flag: { icon: Flag, color: "text-primary", bg: "bg-primary/12" },
  spotter: { icon: Radar, color: "text-warning", bg: "bg-warning/12" },
  engineer: { icon: Headset, color: "text-[#38BDF8]", bg: "bg-[#38BDF8]/15" },
  strategy: { icon: Route, color: "text-[#27F4D2]", bg: "bg-[#27F4D2]/12" },
  tyre: { icon: CircleDot, color: "text-[#FF8000]", bg: "bg-[#FF8000]/12" },
  story: { icon: BookOpen, color: "text-[#b97aff]", bg: "bg-[#A855F7]/15" },
}

export function EventsView({ state }: { state: SpotterState | null }) {
  const connected = state?.connected ?? false
  const events = (state?.feed ?? []).map(feedToEvent)
  const playerLap = state?.telemetry?.lap

  return (
    <div>
      <PageHeader title="Race Radio Feed" subtitle="Полная лента событий текущей сессии" />

      {events.length > 0 ? (
        <Panel
          label="Лента событий"
          action={
            <span className="font-mono text-[10px] text-muted-foreground">
              {events.length} событий{playerLap ? ` · ${playerLap}` : ""}
            </span>
          }
          bodyClassName="p-0"
        >
          <ul>
            {events.map((e) => {
              const m = meta[e.kind]
              const Icon = m.icon
              return (
                <li
                  key={e.id}
                  className="flex gap-4 border-b border-border px-5 py-4 last:border-0 hover:bg-secondary/40"
                >
                  <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-md", m.bg)}>
                    <Icon className={cn("h-4.5 w-4.5", m.color)} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("label-mono text-[10px] font-medium", m.color)}>{e.title}</span>
                      <span className="font-mono text-[10px] text-muted-foreground">· {e.time}</span>
                      {e.driver && (
                        <span className="font-mono text-[10px] text-muted-foreground">· {e.driver}</span>
                      )}
                      {/* Бэкенд помечает событие muted, когда оно попало в ленту,
                          но озвучено не было (порог важности, пауза, канал
                          overlay, выключенный голос) — раньше лента этого не
                          показывала и молчание выглядело как баг озвучки. */}
                      {!e.spoken && (
                        <span className="label-mono rounded border border-border bg-secondary px-1.5 py-0.5 text-[9px] text-muted-foreground">
                          БЕЗ ОЗВУЧКИ
                        </span>
                      )}
                      {e.spoken && e.channelLabel && (
                        <span className="label-mono text-[9px] text-muted-foreground/70">
                          {e.channelLabel}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm leading-relaxed text-foreground/90">{e.text}</p>
                  </div>
                </li>
              )
            })}
          </ul>
        </Panel>
      ) : (
        <Panel label="Лента событий">
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
              <Zap className="h-6 w-6" />
            </span>
            <h3 className="font-heading text-lg font-semibold text-foreground">Нет событий</h3>
            <p className="max-w-sm text-sm text-muted-foreground">
              {connected
                ? "Жду событий гонки — они появятся здесь в реальном времени."
                : "События появятся автоматически, как только начнётся сессия в F1 25."}
            </p>
            <ol className="mt-2 flex flex-col gap-1.5 text-left text-sm text-muted-foreground">
              <li>
                <span className="font-mono text-primary">01</span> Запустите F1 25
              </li>
              <li>
                <span className="font-mono text-primary">02</span> Включите UDP-телеметрию · порт 20777
              </li>
              <li>
                <span className="font-mono text-primary">03</span> Выберите гонку или квалификацию
              </li>
            </ol>
          </div>
        </Panel>
      )}
    </div>
  )
}
