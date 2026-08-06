"use client"

import { useEffect, useState, useCallback } from "react"
import { getOverlay, type OverlayState } from "@/lib/api"
import type { SpotterState } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Panel, SectionLabel } from "../ui"
import { OverlayLayoutPanel } from "./overlay-layout-panel"
import { OverlayThemePanel } from "./overlay-theme-panel"
import { Radio, Gauge, Cpu, Activity, ChevronRight } from "lucide-react"

// ─── Label maps ────────────────────────────────────────────────────────────

const _PHASE_LABELS: Record<string, string> = {
  straight: "Прямая",
  braking:  "Торможение",
  entry:    "Вход",
  apex:     "Апекс",
  exit:     "Выход",
}

const _ADVICE_LABELS: Record<string, string> = {
  cover_inside: "Закрой изнутри",
  hold_line:    "Держи линию",
  late_brake:   "Тормози позже",
  outside:      "Снаружи",
  inside:       "Изнутри",
  none:         "—",
}

const _STRATEGY_LABELS: Record<string, string> = {
  pit:  "Боксы",
  push: "Атака",
  save: "Экономия",
  hold: "Держать",
}

const _MODE_COLORS: Record<string, string> = {
  CALM:   "bg-muted-foreground/30",
  RACE:   "bg-blue-500",
  BATTLE: "bg-orange-500",
  CLIMAX: "bg-primary",
}

const _TYRE_STATUS_LABELS: Record<string, string> = {
  fresh:    "Свежие",
  worn:     "Изношены",
  critical: "Критично",
  cliff:    "Обрыв",
  unknown:  "—",
}

const _TYRE_STATUS_COLORS: Record<string, string> = {
  fresh:    "text-green-400",
  worn:     "text-yellow-400",
  critical: "text-orange-400",
  cliff:    "text-primary",
  unknown:  "text-muted-foreground",
}

// ─── Sub-components ─────────────────────────────────────────────────────────

function DrsLed({ active }: { active: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={cn(
          "h-3 w-3 rounded-full transition-colors",
          active ? "bg-green-400 shadow-[0_0_8px_rgba(74,222,128,0.7)]" : "bg-muted-foreground/30",
        )}
      />
      <span className={cn("label-mono text-xs font-bold", active ? "text-green-400" : "text-muted-foreground")}>
        DRS {active ? "ВКЛ" : "ВЫКЛ"}
      </span>
    </div>
  )
}

function IntensityBar({ intensity, mode }: { intensity: number; mode: string }) {
  const barColor = _MODE_COLORS[mode] ?? "bg-muted-foreground/30"
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="label-mono text-[10px] text-muted-foreground">ИНТЕНСИВНОСТЬ</span>
        <span className="label-mono text-[10px] text-foreground">{intensity}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div
          className={cn("h-full rounded-full transition-all duration-500", barColor)}
          style={{ width: `${intensity}%` }}
        />
      </div>
      {/* Слагаемые и пороги — core/race_ai/intensity.py. Без легенды процент и
          режим выглядели как непрозрачная оценка «на глаз». */}
      <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">
        Сумма: разрыв сзади меньше секунды +20, активный DRS +20, затяжная борьба за
        позицию +20, финальные круги +20, только что показан быстрый круг +10.
        До&nbsp;25% — CALM, до&nbsp;60% — RACE, до&nbsp;85% — BATTLE, выше — CLIMAX.
      </p>
    </div>
  )
}

function TyreChip({ compound, color }: { compound: string; color: string }) {
  return (
    <div
      className="flex h-8 w-8 items-center justify-center rounded-full border-2 font-mono text-sm font-bold"
      style={{ borderColor: color, color }}
    >
      {compound}
    </div>
  )
}

function GapRow({ label, value }: { label: string; value: string }) {
  const unknown = value === "—"
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="label-mono text-[10px] text-muted-foreground">{label}</span>
      <span className={cn("font-mono text-sm tabular", unknown ? "text-muted-foreground" : "text-foreground")}>
        {value}
      </span>
    </div>
  )
}

function GridRow({ pos, driver, team, color }: { pos: number; driver: string; team: string; color: string }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span
        className={cn("w-5 text-right font-mono text-xs font-bold tabular", pos === 1 ? "text-primary" : "text-muted-foreground")}
      >
        P{pos}
      </span>
      <div className="h-3 w-1 rounded-full" style={{ backgroundColor: color }} />
      <span className="flex-1 truncate text-xs text-foreground">{driver}</span>
      <span className="label-mono text-[10px] text-muted-foreground">{team}</span>
    </div>
  )
}

// ─── Main view ──────────────────────────────────────────────────────────────

export function BroadcastOverlayView({ state }: { state: SpotterState | null }) {
  const [overlay, setOverlay] = useState<OverlayState | null>(null)

  const fetchOverlay = useCallback(() => {
    getOverlay()
      .then(setOverlay)
      .catch(() => {/* silently ignore — backend may not be running */})
  }, [])

  useEffect(() => {
    fetchOverlay()
    const id = setInterval(fetchOverlay, 500)
    return () => clearInterval(id)
  }, [fetchOverlay])

  const connected = state?.connected ?? false
  const o = overlay

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="font-heading text-xl font-bold text-foreground">Broadcast Overlay</h1>
        <p className="mt-1 text-sm text-muted-foreground">Данные HUD в реальном времени — /api/overlay</p>
      </div>

      {!connected && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Нет подключения к F1 25 — данные будут обновляться автоматически при старте телеметрии.
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* ── Левая колонка: Пилот ── */}
        <div className="space-y-4">
          {/* Позиция и круг */}
          <Panel label="Позиция">
            <div className="flex items-end gap-4">
              <div>
                <p className="label-mono text-[9px] text-muted-foreground/70">ПОЗИЦИЯ</p>
                <p className="font-heading text-4xl font-bold text-foreground">
                  {o?.position != null ? `P${o.position}` : "—"}
                </p>
              </div>
              <div className="pb-1">
                <p className="label-mono text-[9px] text-muted-foreground/70">КРУГ</p>
                <p className="font-mono text-lg text-foreground">
                  {o?.lap_current != null ? `${o.lap_current} / ${o.lap_total ?? "—"}` : "— / —"}
                </p>
              </div>
            </div>
          </Panel>

          {/* Скорость + DRS */}
          <Panel label="Телеметрия">
            <div className="flex items-center justify-between">
              <div>
                <p className="label-mono text-[9px] text-muted-foreground/70">СКОРОСТЬ</p>
                <p className="font-mono text-2xl font-bold text-foreground">
                  {o?.speed_kmh != null ? `${Math.round(o.speed_kmh)}` : "—"}
                  <span className="ml-1 text-xs text-muted-foreground">км/ч</span>
                </p>
              </div>
              <DrsLed active={o?.drs_active ?? false} />
            </div>
          </Panel>

          {/* Лидер */}
          <Panel label="Лидер">
            <p className="truncate text-sm font-medium text-foreground">{o?.leader ?? "—"}</p>
          </Panel>
        </div>

        {/* ── Центральная колонка: Ситуация ── */}
        <div className="space-y-4">
          {/* Гоночная ситуация */}
          <Panel label="Ситуация">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="label-mono text-[10px] text-muted-foreground">РЕЖИМ</span>
                <span
                  className={cn(
                    "rounded px-2 py-0.5 label-mono text-[10px] font-bold",
                    o?.situation.mode === "CLIMAX" ? "bg-primary/20 text-primary" :
                    o?.situation.mode === "BATTLE" ? "bg-orange-500/20 text-orange-400" :
                    o?.situation.mode === "RACE"   ? "bg-blue-500/20 text-blue-400" :
                    "bg-secondary text-muted-foreground",
                  )}
                >
                  {o?.situation.mode_label ?? "—"}
                </span>
              </div>
              <IntensityBar
                intensity={o?.situation.intensity ?? 0}
                mode={o?.situation.mode ?? "CALM"}
              />
              {o?.situation.threat && (
                <div>
                  <p className="label-mono text-[9px] text-muted-foreground/70">УГРОЗА</p>
                  <p className="mt-0.5 text-xs text-foreground">{o.situation.threat}</p>
                </div>
              )}
            </div>
          </Panel>

          {/* Поворот */}
          <Panel label="Трасса">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="label-mono text-[10px] text-muted-foreground">ПОВОРОТ</span>
                <span className="text-xs text-foreground">{o?.corner.name ?? "Прямая"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="label-mono text-[10px] text-muted-foreground">ФАЗА</span>
                <span className="text-xs text-foreground">
                  {_PHASE_LABELS[o?.corner.phase ?? "straight"] ?? o?.corner.phase ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="label-mono text-[10px] text-muted-foreground">СЕКТОР</span>
                <span className="font-mono text-xs text-foreground">S{o?.corner.sector ?? 1}</span>
              </div>
              {o?.corner.attack_zone && (
                <div className="flex items-center gap-1.5 rounded bg-primary/10 px-2 py-1">
                  <div className="h-2 w-2 rounded-full bg-primary" />
                  <span className="label-mono text-[10px] text-primary">ЗОНА АТАКИ</span>
                </div>
              )}
              {o?.situation.advice && o.situation.advice !== "none" && (
                <div className="flex items-center justify-between">
                  <span className="label-mono text-[10px] text-muted-foreground">СОВЕТ</span>
                  <span className="text-xs text-foreground">
                    {_ADVICE_LABELS[o.situation.advice] ?? o.situation.advice}
                  </span>
                </div>
              )}
            </div>
          </Panel>

          {/* Стратегия */}
          <Panel label="Стратегия">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">
                {_STRATEGY_LABELS[o?.strategy.action ?? "hold"] ?? "—"}
              </span>
              <span className="label-mono text-[10px] text-muted-foreground">
                {o?.strategy.confidence != null ? `${Math.round(o.strategy.confidence * 100)}%` : "—"}
              </span>
            </div>
            {o?.strategy.advice && (
              <p className="mt-1.5 text-xs text-muted-foreground">{o.strategy.advice}</p>
            )}
          </Panel>
        </div>

        {/* ── Правая колонка: Шины + Разрывы + Топ-5 ── */}
        <div className="space-y-4">
          {/* Шины */}
          <Panel label="Шины">
            <div className="flex items-start gap-4">
              <TyreChip
                compound={o?.tyre.compound ?? "?"}
                color={o?.tyre.compound_color ?? "#888888"}
              />
              <div className="flex-1 space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="label-mono text-[10px] text-muted-foreground">ВОЗРАСТ</span>
                  <span className="font-mono text-xs text-foreground">
                    {o?.tyre.age_laps != null ? `${o.tyre.age_laps} кр.` : "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="label-mono text-[10px] text-muted-foreground">ИЗНОС</span>
                  <span className="font-mono text-xs text-foreground">
                    {o?.tyre.wear_pct != null ? `${Math.round(o.tyre.wear_pct)}%` : "—"}
                  </span>
                </div>
                {o?.tyre.wear_pct != null && (
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        o.tyre.wear_pct > 75 ? "bg-primary" :
                        o.tyre.wear_pct > 45 ? "bg-orange-400" : "bg-green-400",
                      )}
                      style={{ width: `${Math.min(o.tyre.wear_pct, 100)}%` }}
                    />
                  </div>
                )}
                <div className="flex items-center justify-between">
                  <span className="label-mono text-[10px] text-muted-foreground">СТАТУС</span>
                  <span
                    className={cn(
                      "label-mono text-[10px] font-bold",
                      _TYRE_STATUS_COLORS[o?.tyre.status ?? "unknown"],
                    )}
                  >
                    {_TYRE_STATUS_LABELS[o?.tyre.status ?? "unknown"]}
                  </span>
                </div>
              </div>
            </div>
          </Panel>

          {/* Разрывы */}
          <Panel label="Разрывы">
            <div className="divide-y divide-border">
              <GapRow label="ДО ЛИДЕРА" value={o?.gaps.to_leader_str ?? "—"} />
              <GapRow label="ДО ВПЕРЕДИ" value={o?.gaps.to_front_str ?? "—"} />
              <GapRow label="ОТ СЗАДИ" value={o?.gaps.to_behind_str ?? "—"} />
            </div>
          </Panel>

          {/* Топ-5 */}
          <Panel label="Топ-5">
            {(o?.grid_top5 ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">Ожидание данных гонки…</p>
            ) : (
              <div className="divide-y divide-border/50">
                {(o?.grid_top5 ?? []).map((entry) => (
                  <GridRow
                    key={entry.position}
                    pos={entry.position}
                    driver={entry.driver}
                    team={entry.team}
                    color={entry.color}
                  />
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>

      <OverlayThemePanel state={state} />
      <OverlayLayoutPanel />
    </div>
  )
}
