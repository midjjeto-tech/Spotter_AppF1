"use client"

import type { ViewId } from "@/lib/spotter-data"
import { cn } from "@/lib/utils"
import {
  LayoutDashboard,
  Flag,
  Mic,
  Zap,
  Settings,
  FileText,
  Keyboard,
  BarChart3,
  Flag as FlagIcon,
  BookOpen,
  MonitorPlay,
  Rss,
  Radio,
} from "lucide-react"

const navSections: { label: string; items: { id: ViewId; label: string; icon: typeof LayoutDashboard }[] }[] = [
  {
    label: "Гонка",
    items: [
      { id: "dashboard", label: "Обзор", icon: LayoutDashboard },
      { id: "race", label: "Тайминг", icon: Flag },
      { id: "race-feed", label: "Репортаж", icon: Rss },
      { id: "events", label: "События", icon: Zap },
      { id: "team-radio", label: "Рация", icon: Radio },
    ],
  },
  {
    label: "Аналитика",
    items: [
      { id: "debrief", label: "Итоги", icon: BookOpen },
      { id: "archive", label: "Архив", icon: BarChart3 },
    ],
  },
  {
    label: "Управление",
    items: [
      { id: "voice", label: "Голос", icon: Mic },
      { id: "hotkeys", label: "Горячие клавиши", icon: Keyboard },
      { id: "settings", label: "Настройки", icon: Settings },
    ],
  },
  {
    label: "Диагностика",
    items: [
      { id: "logs", label: "Журнал", icon: FileText },
      { id: "broadcast-overlay", label: "Оверлей", icon: MonitorPlay },
    ],
  },
]

export function Sidebar({
  active,
  onNavigate,
  cpu,
  ram,
  ramLabel,
  badges,
}: {
  active: ViewId
  onNavigate: (v: ViewId) => void
  cpu: number | null
  ram: number | null
  ramLabel?: string
  badges?: Partial<Record<ViewId, number>>
}) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-card">
      {/* Brand */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary">
          <FlagIcon className="h-5 w-5 text-primary-foreground" strokeWidth={2.5} />
        </div>
        <div className="flex flex-col leading-none">
          <span className="font-heading text-base font-bold tracking-wide text-foreground">
            SPOTTER<span className="ml-1 text-primary">APP</span>
          </span>
          <span className="label-mono mt-1 text-[11px] text-muted-foreground">RACE ENGINEER AI</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <div className="flex flex-col gap-4">
          {navSections.map((section) => (
            <section key={section.label}>
              <p className="label-mono px-2 pb-1.5 text-[11px] text-muted-foreground/70">{section.label}</p>
              <ul className="flex flex-col gap-0.5">
                {section.items.map(({ id, label, icon: Icon }) => {
                  const isActive = active === id
                  const badge = badges?.[id] ?? 0
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        onClick={() => onNavigate(id)}
                        aria-current={isActive ? "page" : undefined}
                        className={cn(
                          "group relative flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                          isActive
                            ? "bg-primary/12 text-foreground"
                            : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                        )}
                      >
                        {isActive && (
                          <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary" />
                        )}
                        <Icon className={cn("h-4.5 w-4.5", isActive && "text-primary")} strokeWidth={2} />
                        <span className="flex-1 text-left">{label}</span>
                        {!isActive && badge > 0 && (
                          <span className="min-w-5 rounded-full bg-primary px-1.5 py-0.5 text-center text-[11px] font-semibold leading-none text-primary-foreground">
                            {badge > 99 ? "99+" : badge}
                          </span>
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </div>
      </nav>

      {/* System monitor */}
      <div className="border-t border-border px-5 py-4">
        <p className="label-mono pb-3 text-[11px] text-muted-foreground/70">Система</p>
        <Meter label="CPU" value={cpu} suffix={cpu == null ? "—" : `${cpu}%`} />
        <Meter label="RAM" value={ram} suffix={ram == null ? "—" : (ramLabel ?? `${ram}%`)} />
      </div>
    </aside>
  )
}

function Meter({ label, value, suffix }: { label: string; value: number | null; suffix: string }) {
  return (
    <div className="mb-3">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="label-mono text-[11px] text-muted-foreground">{label}</span>
        <span className="font-mono text-[11px] text-muted-foreground tabular">{suffix}</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-secondary">
        <div
          className={cn("h-full rounded-full transition-all", value != null && value > 80 ? "bg-warning" : "bg-primary")}
          style={{ width: `${value ?? 0}%` }}
        />
      </div>
    </div>
  )
}
