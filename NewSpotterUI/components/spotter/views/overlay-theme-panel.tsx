"use client"

// Выбор визуального языка оверлея.
//
// Живёт на экране «Оверлей», а не в игре, по той же причине, что и пресеты
// раскладки рядом: каждый виджет — своё нативное окно, общей панели поверх игры
// не существует (см. шапку overlay-layout-panel.tsx).
//
// Превью рисуется НАСТОЯЩЕЙ башней таймингов из in-game-overlay.tsx, а не
// отдельным макетом. Нарисованный отдельно, он разошёлся бы с оверлеем на
// первой же правке — и пользователь выбирал бы тему по картинке, которой в игре
// нет.

import { useEffect, useState } from "react"
import { Check } from "lucide-react"
import {
  saveSettings,
  type OverlayRelativeRow,
  type OverlayThemeId,
  type SpotterState,
} from "@/lib/api"
import { OverlayThemeProvider, THEMES, resolveThemeId } from "@/lib/overlay-theme"
import { TimingTower } from "@/components/spotter/overlay/in-game-overlay"
import { cn } from "@/lib/utils"
import { Panel } from "../ui"

// Габариты окна башни (`core/overlay_window.py::HUD_WIDGETS`). Превью
// показывается в том же соотношении, просто мельче.
const TOWER = { width: 264, height: 288 }
const PREVIEW_SCALE = 0.62

/** Три соперника впереди, игрок, двое позади — тот же расклад, который видно в
 *  гонке. Цвета команд настоящие: тема их не трогает, и превью обязано это
 *  показывать. */
const SAMPLE_ROWS: OverlayRelativeRow[] = [
  { vehicle_idx: 1, position: 1, driver: "VER", team: "Red Bull", color: "#3671C6", gap_to_player_ms: 2114, gap_to_player_str: "+2.114", ahead: true },
  { vehicle_idx: 4, position: 2, driver: "NOR", team: "McLaren", color: "#FF8000", gap_to_player_ms: 847, gap_to_player_str: "+0.847", ahead: true },
  { vehicle_idx: 16, position: 3, driver: "LEC", team: "Ferrari", color: "#E8002D", gap_to_player_ms: 312, gap_to_player_str: "+0.312", ahead: true },
  { vehicle_idx: 0, position: 4, driver: "ВЫ", team: "Mercedes", color: "#27F4D2", gap_to_player_ms: null, gap_to_player_str: "—", ahead: null },
  { vehicle_idx: 81, position: 5, driver: "PIA", team: "McLaren", color: "#FF8000", gap_to_player_ms: -406, gap_to_player_str: "-0.406", ahead: false },
  { vehicle_idx: 63, position: 6, driver: "RUS", team: "Mercedes", color: "#27F4D2", gap_to_player_ms: -1220, gap_to_player_str: "-1.220", ahead: false },
]

const PREVIEW_OVERLAY = { lap_current: 34, lap_total: 58 } as never

function ThemeCard({
  id,
  active,
  onPick,
}: {
  id: OverlayThemeId
  active: boolean
  onPick: (id: OverlayThemeId) => void
}) {
  const theme = THEMES[id]
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onPick(id)}
      className={cn(
        "group flex flex-col gap-3 rounded-lg border p-3 text-left transition-colors",
        active ? "border-primary/60 bg-primary/5" : "border-border hover:bg-secondary/50",
      )}
    >
      {/* Превью непрозрачно и лежит на #0c0c10 — ровно на той заливке, которую
          Python даёт окну виджета. Так видно фаску: она показывает фон окна. */}
      <div
        className="overflow-hidden rounded"
        style={{
          width: TOWER.width * PREVIEW_SCALE,
          height: TOWER.height * PREVIEW_SCALE,
          backgroundColor: "#0c0c10",
        }}
      >
        <div
          data-ov-theme={id}
          style={{
            width: TOWER.width,
            height: TOWER.height,
            transform: `scale(${PREVIEW_SCALE})`,
            transformOrigin: "top left",
          }}
        >
          <OverlayThemeProvider theme={id}>
            <TimingTower rows={SAMPLE_ROWS} overlay={PREVIEW_OVERLAY} />
          </OverlayThemeProvider>
        </div>
      </div>

      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {active && <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />}
          {theme.label}
        </p>
        <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{theme.hint}</p>
      </div>
    </button>
  )
}

export function OverlayThemePanel({ state }: { state: SpotterState | null }) {
  const saved = state?.settings?.overlay_theme
  const [picked, setPicked] = useState<OverlayThemeId | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Показываем выбранное сразу, не дожидаясь опроса: между кликом и ответом
  // сервера проходит до секунды, и подсветка, отстающая на секунду, читается
  // как «не нажалось».
  useEffect(() => {
    if (saved) setPicked(null)
  }, [saved])

  const active = resolveThemeId(picked ?? saved)

  const pick = async (id: OverlayThemeId) => {
    setPicked(id)
    try {
      await saveSettings({ overlay_theme: id })
      setError(null)
    } catch {
      setPicked(null)
      setError("Не удалось сохранить тему")
    }
  }

  return (
    <Panel label="Вид оверлея">
      <p className="mb-4 text-xs text-muted-foreground">
        Меняет только оформление: виджеты, их размеры и расположение остаются
        прежними. Применяется в течение секунды, перезапуск не нужен.
      </p>
      <div className="flex flex-wrap gap-3">
        {(Object.keys(THEMES) as OverlayThemeId[]).map((id) => (
          <ThemeCard key={id} id={id} active={active === id} onPick={(next) => void pick(next)} />
        ))}
      </div>
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
    </Panel>
  )
}
