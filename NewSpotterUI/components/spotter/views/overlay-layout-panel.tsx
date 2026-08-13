"use client"

// Размер игровых виджетов и именованные пресеты раскладки.
//
// Почему это здесь, а не поверх игры: размер тянется уголком прямо на экране в
// режиме редактирования (Ctrl+Alt+O) — там это и нужно, там видно результат. А
// вот управлению пресетами в оверлее физически негде жить: каждый виджет — своё
// нативное окно в своём процессе (core/overlay_process.py), общей панели поверх
// игры не существует, и заводить ради неё девятый постоянно живущий процесс
// WebView2 на машине, которая одновременно тянет F1 25, — плохой размен.
// Поэтому пресеты живут на экране «Оверлей», а слайдеры продублированы здесь же
// для точной настройки цифрами.

import { useCallback, useEffect, useRef, useState } from "react"
import { Check, RotateCcw, Trash2 } from "lucide-react"
import {
  getOverlayLayout,
  overlayPreset,
  resetOverlayLayout,
  setOverlayEnabled,
  setOverlayScale,
  type OverlayLayoutState,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { Panel, Slider } from "../ui"

/** Порядок и подписи виджетов. Ключи обязаны совпадать с HUD_WIDGETS
 *  (core/overlay_window.py) — по ним же бэкенд проверяет запрос. */
const WIDGETS: { id: string; label: string; hint: string }[] = [
  { id: "hud", label: "Приборы", hint: "Таблетка снизу: передача, скорость, ERS" },
  { id: "lap", label: "Круг", hint: "Время круга, отрывы, секторы" },
  { id: "tower", label: "Таблица", hint: "Соперники вокруг вас" },
  { id: "inputs", label: "Педали", hint: "Газ, тормоз, руль" },
  { id: "radar", label: "Радар", hint: "Машины рядом" },
  { id: "pu", label: "Силовая", hint: "ICE и MGU-K" },
  { id: "engineer", label: "Инженер", hint: "Команда на круг" },
  { id: "radio", label: "Рация", hint: "Карточка переговоров" },
]

export function OverlayLayoutPanel() {
  const [layout, setLayout] = useState<OverlayLayoutState | null>(null)
  const [name, setName] = useState("")
  const [error, setError] = useState<string | null>(null)
  // Пока тянут слайдер, ответы опроса не должны возвращать ползунок назад.
  const editing = useRef(false)

  const pull = useCallback(async () => {
    try {
      const next = await getOverlayLayout()
      if (!editing.current) setLayout(next)
    } catch {
      // Сервер не отвечает — панель просто останется на прошлых значениях.
    }
  }, [])

  useEffect(() => {
    void pull()
    const timer = setInterval(pull, 3_000)
    return () => clearInterval(timer)
  }, [pull])

  const scaleOf = (id: string) => layout?.widgets?.[id]?.scale ?? 1
  const enabledOf = (id: string) => layout?.widgets?.[id]?.enabled !== false

  const toggleWidget = async (id: string, next: boolean) => {
    // Оптимистично: галочка обязана отзываться мгновенно, а окно виджета
    // появится или уйдёт в течение секунды-двух — он читает тот же файл.
    setLayout((current) =>
      current
        ? {
            ...current,
            widgets: {
              ...current.widgets,
              [id]: { ...current.widgets[id], enabled: next },
            },
          }
        : current,
    )
    try {
      setLayout(await setOverlayEnabled(id, next))
      setError(null)
    } catch {
      setError("Не удалось включить или выключить виджет")
      void pull()
    }
  }

  const previewScale = (id: string, percent: number) => {
    editing.current = true
    setLayout((current) =>
      current
        ? {
            ...current,
            widgets: {
              ...current.widgets,
              [id]: { ...current.widgets[id], scale: percent / 100 },
            },
          }
        : current,
    )
  }

  const commitScale = async (id: string, percent: number) => {
    editing.current = false
    try {
      setLayout(await setOverlayScale(id, percent / 100))
      setError(null)
    } catch {
      setError("Не удалось сохранить размер")
    }
  }

  const runPreset = async (action: "save" | "apply" | "delete", preset: string) => {
    try {
      const next = await overlayPreset(action, preset)
      if (!next.ok) {
        setError(next.error ?? "Действие не выполнено")
        return
      }
      setLayout(next)
      setError(null)
      if (action === "save") setName("")
    } catch {
      setError("Сервер не ответил")
    }
  }

  const min = Math.round((layout?.min_scale ?? 0.6) * 100)
  const max = Math.round((layout?.max_scale ?? 2.0) * 100)
  const presets = layout?.names ?? []

  return (
    <div className="space-y-4">
      <Panel
        label="Размер виджетов"
        action={
          <button
            type="button"
            onClick={async () => {
              try {
                setLayout(await resetOverlayLayout())
                setError(null)
              } catch {
                setError("Не удалось сбросить раскладку")
              }
            }}
            className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Сбросить
          </button>
        }
      >
        <p className="mb-4 text-xs text-muted-foreground">
          Ctrl+Alt+O в игре — и виджеты можно двигать и тянуть за красный уголок.
          Здесь то же самое цифрами; окно меняет размер в течение секунды.
        </p>
        <div className="space-y-3">
          {WIDGETS.map((widget) => {
            const percent = Math.round(scaleOf(widget.id) * 100)
            const on = enabledOf(widget.id)
            return (
              <div
                key={widget.id}
                className="grid grid-cols-[28px_110px_1fr_52px] items-center gap-3"
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={(event) => void toggleWidget(widget.id, event.target.checked)}
                  aria-label={`Показывать виджет «${widget.label}»`}
                  className="h-4 w-4 cursor-pointer accent-primary"
                />
                <div className={cn("min-w-0", !on && "opacity-45")}>
                  <p className="truncate text-sm text-foreground">{widget.label}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {on ? widget.hint : "Выключен — окно не запускается"}
                  </p>
                </div>
                <Slider
                  value={percent}
                  min={min}
                  max={max}
                  disabled={!on}
                  label={`Размер: ${widget.label}`}
                  onChange={(value) => previewScale(widget.id, value)}
                  onPointerUp={(value) => void commitScale(widget.id, value)}
                />
                <span
                  className={cn(
                    "text-right font-mono text-sm tabular-nums text-foreground",
                    !on && "opacity-45",
                  )}
                >
                  {(percent / 100).toFixed(2)}×
                </span>
              </div>
            )
          })}
        </div>
      </Panel>

      <Panel label="Пресеты раскладки">
        <p className="mb-3 text-xs text-muted-foreground">
          Пресет запоминает позиции и размеры всех восьми виджетов — например,
          «Гонка» и «Стрим» с разным размером таблицы.
        </p>
        <div className="flex gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim()) void runPreset("save", name)
            }}
            placeholder="Название пресета"
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/60 focus-visible:ring-1 focus-visible:ring-ring"
          />
          <button
            type="button"
            disabled={!name.trim()}
            onClick={() => void runPreset("save", name)}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Сохранить текущую
          </button>
        </div>

        {presets.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Пресетов пока нет. Расставьте виджеты в игре и сохраните раскладку.
          </p>
        ) : (
          <ul className="mt-4 space-y-1.5">
            {presets.map((preset) => {
              const active = layout?.active === preset
              return (
                <li
                  key={preset}
                  className={cn(
                    "flex items-center gap-2 rounded-md border px-3 py-2",
                    active ? "border-primary/50 bg-primary/10" : "border-border",
                  )}
                >
                  {active && <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />}
                  <span className="min-w-0 flex-1 truncate text-sm text-foreground">{preset}</span>
                  <button
                    type="button"
                    onClick={() => void runPreset("apply", preset)}
                    className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    Применить
                  </button>
                  <button
                    type="button"
                    aria-label={`Удалить пресет ${preset}`}
                    onClick={() => void runPreset("delete", preset)}
                    className="rounded-md border border-border p-1.5 text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      </Panel>
    </div>
  )
}
