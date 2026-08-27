"use client"

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Radio } from "lucide-react"
import {
  getOverlay,
  getOverlayLayout,
  getState,
  setOverlayScale,
  type OverlayRadarContact,
  type OverlayRelativeRow,
  type OverlayState,
  type RadioSource,
  type RadioSpeakerProfile,
  type SpotterState,
  type VoiceQuery,
} from "@/lib/api"
import {
  BroadcastRadioCard,
  type RadioCardView,
} from "@/components/spotter/overlay/broadcast-radio-card"
import {
  CHANNEL_ACCENT,
  PTT_BUSY_STATES,
  RADIO_SURFACE,
  VISIBLE_STATES,
  accentFor,
  clampScale,
  lingerMs,
  textSizePx,
} from "@/lib/radio-ui"
import {
  AMBER,
  CRIMSON,
  CYAN,
  DANGER,
  DIVIDER,
  GAP_AHEAD,
  GAP_BEHIND,
  GREEN,
  Label,
  LABEL_CLR,
  MGUK,
  OverlayPanel,
  PANEL,
  PANEL_RAISED,
  PILL_BORDER,
  PILL_INNER,
  PILL_MUTED,
  PLAYER_ROW,
  PURPLE,
  PosBlock,
  RED,
  RING_BG,
  ROW_ALT,
  RevSpine,
  TEXT,
  TEXT_BRIGHT,
  TeamEdge,
  TyreDisc,
  tyreColor,
} from "@/components/spotter/overlay/broadcast-chrome"
import {
  OverlayThemeProvider,
  THEMES,
  resolveThemeId,
  useOverlayTheme,
} from "@/lib/overlay-theme"
import { cn } from "@/lib/utils"

// Раскладка и геометрия виджетов — из pits-n-giggles 4.2.0 (MIT), см.
// .scratch/pits-n-giggles-4.2.0-analysis/apps/hud/ui/overlays/*.qml. Внешний
// вид с тех пор переведён на трансляционный язык: шапки, наклонные позиции,
// цвета команд, диски составов. Все токены и примитивы — в
// ./broadcast-chrome.tsx, здесь их не объявляют заново.
type WidgetId = "hud" | "lap" | "tower" | "inputs" | "radar" | "pu" | "engineer" | "radio"
type Point = { x: number; y: number }
type Layout = Record<WidgetId, Point>

declare global {
  interface WindowEventMap {
    "spotter-overlay-edit": CustomEvent<boolean>
  }
}

const STORAGE_KEY = "spotter-overlay-layout-png-v3"

// Границы масштаба виджета. ДОЛЖНЫ совпадать с MIN_SCALE/MAX_SCALE в
// core/overlay_layout.py: бэкенд клипует независимо, и разойдись они — ползунок
// уезжал бы туда, откуда сервер молча возвращает другое значение.
const MIN_SCALE = 0.6
const MAX_SCALE = 2.0

function clampWidgetScale(value: number): number {
  if (!Number.isFinite(value)) return 1
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, value))
}

// Must match core/overlay_window.py::HUD_WIDGETS — each widget is its own
// native window and Python owns the window size.
const WIDGET_SIZE: Record<WidgetId, { width: number; height: number }> = {
  hud: { width: 470, height: 116 },
  lap: { width: 280, height: 180 },
  tower: { width: 264, height: 288 },
  inputs: { width: 450, height: 120 },
  radar: { width: 300, height: 300 },
  pu: { width: 220, height: 106 },
  engineer: { width: 304, height: 154 },
  radio: { width: 430, height: 108 },
}

const DEFAULT_LAYOUT: Layout = {
  hud: { x: 725, y: 940 },
  lap: { x: 20, y: 60 },
  tower: { x: 20, y: 260 },
  inputs: { x: 735, y: 800 },
  radar: { x: 1600, y: 560 },
  pu: { x: 1680, y: 60 },
  engineer: { x: 1596, y: 200 },
  // Снизу по центру, но НАД нижним кластером (hud + inputs) — см. причину в
  // core/overlay_window.py::place_over, ветка "radio". Обе стороны обязаны
  // держать одинаковый отступ 290, иначе позиция в оконном режиме и в
  // одностраничном preview разойдутся.
  radio: { x: 745, y: 612 },
}

// Ширина фаски нижнего-левого угла. Одно число на два применения: срез рисует
// `clipPath` панели, и он же вырезается из ОКНА — иначе в срезе была бы не
// трасса, а чёрный фон окна, ради которого весь этот механизм и заведён.
const BEVEL_PX = 11

/** Примитив формы окна в БАЗОВЫХ координатах виджета (core/overlay_shape.py). */
type ShapePrimitive =
  | { kind: "rect" | "ellipse"; x: number; y: number; w: number; h: number }
  | { kind: "round-rect"; x: number; y: number; w: number; h: number; r: number }
  | { kind: "polygon"; points: [number, number][] }

/**
 * Форма окна собирается ИЗМЕРЕНИЕМ вёрстки, а не повтором её чисел.
 *
 * Окна оверлея непрозрачны (`OVERLAY_BACKGROUND`), поэтому всё, что виджет не
 * закрасил, было чёрным прямоугольником поверх трассы: круглый радар таскал
 * квадрат, таблетка приборов — углы. Python обрезает окно по этой форме
 * (`SetWindowRgn`), но знать её он не может — она зависит от темы (фаска,
 * радиус карточки) и от состояния. Список чисел на стороне Python молча
 * разошёлся бы с CSS; измерение расходиться не умеет.
 */
function measureShape(host: HTMLElement, scale: number): ShapePrimitive[] {
  const base = host.getBoundingClientRect()
  const shapes: ShapePrimitive[] = []
  const nodes = host.querySelectorAll<HTMLElement>("[data-overlay-shape]")
  for (const node of Array.from(nodes)) {
    const box = node.getBoundingClientRect()
    const x = (box.left - base.left) / scale
    const y = (box.top - base.top) / scale
    const w = box.width / scale
    const h = box.height / scale
    if (w <= 0 || h <= 0) continue
    if (node.dataset.overlayShape === "ellipse") {
      shapes.push({ kind: "ellipse", x, y, w, h })
      continue
    }
    // Радиус берётся из вычисленного стиля: `rounded-full` даёт 9999px, и
    // Python сам подрежет его до половины стороны.
    const raw = window.getComputedStyle(node).borderTopLeftRadius
    const parsed = Number.parseFloat(raw) || 0
    const radius = raw.endsWith("%") ? (parsed / 100) * Math.min(w, h) : parsed
    shapes.push(radius > 0
      ? { kind: "round-rect", x, y, w, h, r: radius }
      : { kind: "rect", x, y, w, h })
  }
  return shapes
}

function fittedDefaultLayout(): Layout {
  if (typeof window === "undefined") return DEFAULT_LAYOUT
  const center = (width: number) => Math.max(12, Math.round((window.innerWidth - width) / 2))
  const fromRight = (width: number, margin: number) =>
    Math.max(12, window.innerWidth - width - margin)
  const fromBottom = (height: number, margin: number) =>
    Math.max(60, window.innerHeight - height - margin)
  return {
    hud: { x: center(WIDGET_SIZE.hud.width), y: fromBottom(WIDGET_SIZE.hud.height, 24) },
    lap: { x: 18, y: 54 },
    tower: { x: 18, y: 254 },
    inputs: {
      x: center(WIDGET_SIZE.inputs.width),
      y: fromBottom(WIDGET_SIZE.inputs.height, 150),
    },
    radar: {
      x: fromRight(WIDGET_SIZE.radar.width, 34),
      y: fromBottom(WIDGET_SIZE.radar.height, 220),
    },
    pu: { x: fromRight(WIDGET_SIZE.pu.width, 18), y: 54 },
    engineer: { x: fromRight(WIDGET_SIZE.engineer.width, 18), y: 176 },
    radio: {
      x: center(WIDGET_SIZE.radio.width),
      y: fromBottom(WIDGET_SIZE.radio.height, 290),
    },
  }
}

const PREVIEW_OVERLAY = {
  position: 4,
  lap_current: 18,
  lap_total: 57,
  speed_kmh: 297,
  drs_active: true,
  gaps: {
    to_leader_ms: 6840,
    to_front_ms: 742,
    to_behind_ms: 1106,
    to_leader_str: "+6.840",
    to_front_str: "+0.742",
    to_behind_str: "+1.106",
  },
  tyre: {
    compound: "M",
    age_laps: 11,
    wear_pct: 37,
    status: "fresh",
    compound_color: "#fff200",
  },
  car: {
    fuel_kg: 31.45,
    fuel_delta_laps: 0.42,
    ers_percent: 68,
    ers_deploy_mode: 3,
    ers_harvested_pct: 46,
    ers_deployed_pct: 61,
    power_ice_kw: 545.5,
    power_mguk_kw: 118.2,
    last_lap_ms: 83_456,
    last_lap_str: "1:23.456",
    // Личный лучший — этот же круг, круг поля быстрее: в превью видно
    // «зелёный», среднюю ступень шкалы, а не крайнюю.
    last_lap_tone: "green" as const,
    personal_best_lap_ms: 83_456,
    session_best_lap_ms: 82_100,
  },
  inputs: {
    throttle_pct: 92,
    brake_pct: 0,
    steer: -0.28,
    rpm: 11_850,
    rev_lights_pct: 88,
  },
  session: {
    air_temp_c: 27,
    track_temp_c: 41,
    track_limit_warnings: 2,
    drs_distance_m: 120,
    drs_allowed: true,
  },
  corner: {
    name: "Turn 11",
    type: "medium",
    phase: "entry",
    sector: 2,
    attack_zone: true,
    defense_advice: "none",
  },
  situation: {
    intensity: 74,
    mode: "BATTLE",
    mode_label: "Борьба",
    threat: "Соперник в зоне DRS",
    advice: "Подготовь выход — атака на следующей прямой",
  },
  strategy: {
    action: "push",
    confidence: 0.86,
    advice: "Два круга в этом темпе",
    tyre_status: "fresh",
  },
  grid_top5: [],
  leader: "VERSTAPPEN",
  radar: [
    { vehicle_idx: 55, side: "left", lateral_m: 2.1, longitudinal_m: -4.5 },
    { vehicle_idx: 63, side: "right", lateral_m: 1.6, longitudinal_m: 8.0 },
  ],
  relative: [
    { vehicle_idx: 33, position: 1, driver: "VERSTAPPEN", team: "Red Bull Racing", color: "#3671C6", gap_to_player_ms: 24500, gap_to_player_str: "+24.500", ahead: true },
    { vehicle_idx: 16, position: 2, driver: "LECLERC", team: "Ferrari", color: "#E8002D", gap_to_player_ms: 12100, gap_to_player_str: "+12.100", ahead: true },
    { vehicle_idx: 4, position: 3, driver: "NORRIS", team: "McLaren", color: "#FF8000", gap_to_player_ms: 6840, gap_to_player_str: "+6.840", ahead: true },
    { vehicle_idx: 44, position: 4, driver: "HAMILTON", team: "Mercedes", color: "#27F4D2", gap_to_player_ms: null, gap_to_player_str: "—", ahead: null },
    { vehicle_idx: 63, position: 5, driver: "RUSSELL", team: "Mercedes", color: "#27F4D2", gap_to_player_ms: 742, gap_to_player_str: "+0.742", ahead: false },
    { vehicle_idx: 55, position: 6, driver: "SAINZ", team: "Ferrari", color: "#E8002D", gap_to_player_ms: 1848, gap_to_player_str: "+1.848", ahead: false },
  ],
} satisfies OverlayState

// ── Preview-фикстуры ────────────────────────────────────────────────────────
// `?preview=<сценарий>` рисует детерминированное состояние без запущенной игры,
// без TTS и без записи в production state. Это единственный способ проверить
// редкие состояния карточки: критическую реплику, прерывание, отсутствующий
// портрет и переполнение текста в живой гонке не воспроизвести по требованию.
// `?preview=1` сохраняет прежнее поведение (полный HUD, карточка инженера).

const PREVIEW_SPEAKERS = {
  engineer: {
    speaker_id: "race_engineer", speaker_name: "ИГОРЬ ВОЛКОВ",
    speaker_role: "RACE ENGINEER", speaker_initials: "ИВ",
    portrait_url: "/assets/radio/engineer.webp", accent: "#e32636",
  },
  spotter: {
    speaker_id: "spotter", speaker_name: "СПОТТЕР",
    speaker_role: "TRACKSIDE SPOTTER", speaker_initials: "С",
    portrait_url: "/assets/radio/spotter.webp", accent: "#f4b942",
  },
  commentator: {
    speaker_id: "analyst_tv", speaker_name: "АНДРЕЙ КОРШУНОВ",
    speaker_role: "RACE ANALYST", speaker_initials: "АК",
    portrait_url: "/assets/radio/analyst_tv.webp", accent: "#39c5d4",
  },
  driver: {
    speaker_id: "driver", speaker_name: "ПИЛОТ", speaker_role: "DRIVER",
    speaker_initials: "П", portrait_url: null, accent: "#c8ced6",
  },
}

type PreviewMessage = {
  channel: RadioSource
  urgency: string
  text: string
  state?: string
  portrait?: string | null
}

function previewRadio(message: PreviewMessage | null, ptt?: Record<string, unknown>) {
  const profile = message
    ? PREVIEW_SPEAKERS[message.channel as keyof typeof PREVIEW_SPEAKERS]
    : null
  return {
    revision: 1,
    speakers: PREVIEW_SPEAKERS,
    status: message?.state ?? "idle",
    active_message: message && profile
      ? {
          id: "radio-preview",
          channel: message.channel,
          category: "preview",
          urgency: message.urgency,
          speaker: "Инженер",
          speaker_id: profile.speaker_id,
          speaker_name: profile.speaker_name,
          speaker_role: profile.speaker_role,
          speaker_initials: profile.speaker_initials,
          portrait_url: message.portrait === undefined ? profile.portrait_url : message.portrait,
          accent: profile.accent,
          text: message.text,
          ui_title: "Предпросмотр", ui_summary: null,
          created_at: 0, started_at: 0, ended_at: null, expires_at: null,
          state: message.state ?? "playing",
          situation_id: null,
          debug_event_code: "PREVIEW", debug_dedupe_key: null,
        }
      : null,
    history: [],
    ptt: {
      state: "idle", driver_text: null, engineer_text: null, error: null,
      updated_at: 0, answer_message_id: null, ...(ptt ?? {}),
    },
    repeatable: null,
  }
}

const PREVIEW_BASE = {
  connected: true,
  speaking: false,
  now_speaking: "",
  telemetry: { lap: "18 / 57", position: "P4 / 22", speed: "297 км/ч", gear: "7", fuel: "31.4 кг" },
  settings: { ptt_hotkey: { ctrl: true, alt: true, shift: false, key: "V" } },
  voice_query: null,
}

function previewState(radio: ReturnType<typeof previewRadio>): SpotterState {
  return { ...PREVIEW_BASE, radio } as unknown as SpotterState
}

const PREVIEW_SCENARIOS: Record<string, SpotterState> = {
  "radio-engineer": previewState(previewRadio({
    channel: "engineer", urgency: "normal",
    text: "Отрыв впереди — одна и три. Держи темп.",
  })),
  "radio-critical": previewState(previewRadio({
    channel: "engineer", urgency: "critical",
    text: "Боксы в конце круга. Бокс, бокс.",
  })),
  // Компактный вариант: короткий текст включает однострочный режим (ТЗ §13).
  "radio-spotter": previewState(previewRadio({
    channel: "spotter", urgency: "critical", text: "Слева.",
  })),
  "radio-commentary": previewState(previewRadio({
    channel: "commentator", urgency: "low",
    text: "Норрис отыграл две позиции за круг — свежая резина работает.",
  })),
  // Проверка переполнения: три строки и аккуратное обрезание, без marquee.
  "radio-long-text": previewState(previewRadio({
    channel: "engineer", urgency: "high",
    text: "Дождь начнётся через три минуты, интенсивность растёт со стороны "
      + "третьего сектора. Готовься к переходу на промежуточную резину — "
      + "окно откроется на следующем круге, решение примем по твоему сигналу.",
  })),
  // Портрета нет — карточка обязана остаться целой и показать инициалы.
  "radio-no-portrait": previewState(previewRadio({
    channel: "engineer", urgency: "normal",
    text: "Проверка связи. Портрет отсутствует.", portrait: null,
  })),
  "radio-ptt": previewState(previewRadio(null, {
    state: "thinking", driver_text: "Какой отрыв до Норриса?",
  })),
  "radio-ptt-listening": previewState(previewRadio(null, { state: "listening" })),
  "radio-ptt-recognizing": previewState(previewRadio(null, { state: "recognizing" })),
  // Ответ инженера: полноценная карточка с LIVE, вопрос — мелкой строкой.
  "radio-ptt-answer": previewState(previewRadio({
    channel: "engineer", urgency: "normal",
    text: "Семь десятых до Норриса. DRS есть — два круга в этом темпе.",
  }, {
    state: "done", driver_text: "Какой отрыв до Норриса?",
    // Связь вопрос→ответ: по ней карточка показывает вопрос мелкой строкой.
    answer_message_id: "radio-preview",
  })),
  // Прерванная реплика: уходит немедленно, текст на экране не задерживается.
  "radio-interrupted": previewState(previewRadio({
    channel: "engineer", urgency: "normal", state: "interrupted",
    text: "Отрыв позади — две секунды…",
  })),
}

// `?preview=1` и любое неизвестное значение — прежний сценарий по умолчанию.
const PREVIEW_STATE = PREVIEW_SCENARIOS["radio-critical"]

function previewStateFor(value: string | null): SpotterState {
  return (value && PREVIEW_SCENARIOS[value]) || PREVIEW_STATE
}

const STRATEGY_LABEL: Record<string, string> = {
  pit: "BOX THIS LAP",
  push: "PUSH",
  save: "LIFT & COAST",
  hold: "HOLD POSITION",
}

// m_ersDeployMode. The reference tints the battery by mode and outlines the
// percentage only in Medium, which we mirror with a dark text shadow.
const ERS_MODE: Record<number, { label: string; color: string }> = {
  0: { label: "NONE", color: "#4a5a6a" },
  1: { label: "MEDIUM", color: AMBER },
  2: { label: "HOTLAP", color: CYAN },
  3: { label: "OVERTAKE", color: GREEN },
}

function readLayout(): Layout {
  const defaults = fittedDefaultLayout()
  if (typeof window === "undefined") return defaults
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<Layout>
    return Object.fromEntries(
      (Object.keys(defaults) as WidgetId[]).map((id) => {
        const point = saved[id] ?? defaults[id]
        const size = WIDGET_SIZE[id]
        return [
          id,
          {
            x: Math.max(6, Math.min(window.innerWidth - size.width - 6, point.x)),
            y: Math.max(6, Math.min(window.innerHeight - size.height - 6, point.y)),
          },
        ]
      }),
    ) as Layout
  } catch {
    return defaults
  }
}

function hotkeyLabel(state: SpotterState | null): string {
  const hotkey = state?.settings?.ptt_hotkey
  if (!hotkey?.key) return "PTT"
  return [hotkey.ctrl && "CTRL", hotkey.alt && "ALT", hotkey.shift && "SHIFT", hotkey.key]
    .filter(Boolean)
    .join("+")
}

/**
 * Edit-mode chrome, ported from OverlayBorder.qml: a red outline plus four
 * solid corner handles. This is the ONLY chrome a widget ever gets — the old
 * always-on title strip just ate screen space over the game, and the reference
 * HUD deliberately has no titles at all.
 */
function EditChrome({ visible }: { visible: boolean }) {
  if (!visible) return null
  const handle = "absolute h-[18px] w-[18px] rounded-[2px]"
  return (
    <div className="pointer-events-none absolute inset-0 z-50">
      <div className="absolute inset-0 border-2" style={{ borderColor: RED, opacity: 0.85 }} />
      <div className={cn(handle, "left-0 top-0")} style={{ backgroundColor: RED, opacity: 0.9 }} />
      <div className={cn(handle, "right-0 top-0")} style={{ backgroundColor: RED, opacity: 0.9 }} />
      <div className={cn(handle, "bottom-0 left-0")} style={{ backgroundColor: RED, opacity: 0.9 }} />
      <div className={cn(handle, "bottom-0 right-0")} style={{ backgroundColor: RED, opacity: 0.9 }} />
    </div>
  )
}

/**
 * Уголок изменения размера. Виден только в режиме редактирования и только он
 * умеет менять масштаб — потянуть за край окна нельзя: окно у виджета нативное,
 * его габариты считает Python из сохранённого множителя
 * (`core/overlay_window.py::HudWidgetSpec.place_over`).
 */
function ResizeHandle({
  scale,
  base,
  onScale,
  onCommit,
}: {
  scale: number
  base: { width: number; height: number }
  onScale: (next: number) => void
  onCommit: (next: number) => void
}) {
  const drag = useRef<{ pointerId: number; x: number; y: number; scale: number } | null>(null)

  const begin = (event: React.PointerEvent<HTMLButtonElement>) => {
    // Тянут именно уголок, а не виджет: иначе жест ушёл бы в перетаскивание.
    event.stopPropagation()
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, scale }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const move = (event: React.PointerEvent<HTMLButtonElement>) => {
    const start = drag.current
    if (!start || start.pointerId !== event.pointerId) return
    event.stopPropagation()
    const width = base.width * start.scale + (event.clientX - start.x)
    const height = base.height * start.scale + (event.clientY - start.y)
    // Среднее по осям, а не одна из них: у башни высота втрое больше ширины, и
    // масштаб «по ширине» заставлял бы тащить уголок через пол-экрана.
    onScale(clampWidgetScale((width / base.width + height / base.height) / 2))
  }

  const end = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!drag.current) return
    event.stopPropagation()
    drag.current = null
    onCommit(scale)
  }

  return (
    <button
      type="button"
      aria-label="Изменить размер виджета"
      className="absolute -bottom-px -right-px z-[60] h-[18px] w-[18px] cursor-nwse-resize"
      style={{ backgroundColor: RED, opacity: 0.9 }}
      onPointerDown={begin}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
    >
      {/* Две насечки — тот же знак «тяни отсюда», что у нативных окон. */}
      <span className="pointer-events-none absolute bottom-[3px] right-[3px] block h-[2px] w-[9px] bg-white/85" />
      <span className="pointer-events-none absolute bottom-[3px] right-[3px] block h-[9px] w-[2px] bg-white/85" />
    </button>
  )
}

function Widget({
  id,
  editMode,
  position,
  onMove,
  scale = 1,
  onScale,
  onScaleCommit,
  standalone = false,
  transparentShell = false,
  visible = true,
  rev = 0,
  children,
}: {
  id: WidgetId
  editMode: boolean
  position: Point
  onMove: (id: WidgetId, point: Point) => void
  /** Множитель габаритов. Окно уже имеет размер base × scale — содержимое
   *  масштабируется целиком, а не перетекает (см. core/overlay_layout.py). */
  scale?: number
  onScale?: (id: WidgetId, next: number) => void
  onScaleCommit?: (id: WidgetId, next: number) => void
  standalone?: boolean
  /** The pill and the radar paint their own shape, so no box around them. */
  transparentShell?: boolean
  /** Есть ли виджету что показать. `false` убирает его окно с экрана целиком:
   *  карточка рации в покое пуста, но её окно всё равно висело поверх игры. */
  visible?: boolean
  /** Обороты в процентах — для полосы rev-lights приборной темы. */
  rev?: number
  children: React.ReactNode
}) {
  const drag = useRef<{ pointerId: number; dx: number; dy: number } | null>(null)
  const base = WIDGET_SIZE[id]
  const theme = useOverlayTheme()
  const shell = useRef<HTMLElement | null>(null)
  const reported = useRef("")
  // Виджеты, рисующие собственную форму (таблетка, радар), из темы берут только
  // цвета: фаска и полоса оборотов относятся к КОРОБКЕ панели, а коробки у них
  // нет — деталь повисла бы в пустоте поверх игры.
  const boxed = !transparentShell

  // Only the in-page (preview) layout drags with the pointer. A standalone
  // widget is a real OS window: pywebview moves it natively through the drag
  // region and core/overlay_window.py persists where it lands.
  const beginDrag = (event: React.PointerEvent<HTMLElement>) => {
    if (!editMode || standalone) return
    const rect = event.currentTarget.getBoundingClientRect()
    drag.current = {
      pointerId: event.pointerId,
      dx: event.clientX - rect.left,
      dy: event.clientY - rect.top,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  // Форма и «есть что показать» уезжают в Python на КАЖДЫЙ рендер, но по каналу
  // — только когда изменились: страница перерисовывается четырежды в секунду от
  // телеметрии, а форма меняется от смены темы и появления карточки.
  useEffect(() => {
    if (!standalone) return
    const node = shell.current
    if (!node) return
    // Мост есть только у окна виджета. В превью главного окна и в браузере
    // его нет — там форма никому не нужна, окно там не нативное.
    const api = (window as unknown as {
      pywebview?: { api?: { set_shape?: (payload: unknown) => Promise<unknown> } }
    }).pywebview?.api
    if (!api?.set_shape) return

    const shapes: ShapePrimitive[] = editMode
      // В режиме редактирования окно прямоугольное: рамка и уголок размера
      // живут по краям коробки, и обрезка по кругу спрятала бы ровно то, за
      // что виджет двигают и тянут. Заодно видно настоящий след виджета.
      ? [{ kind: "rect", x: 0, y: 0, w: base.width, h: base.height }]
      : boxed
      ? theme.bevel
        // Срез угла панели вырезается и из окна — иначе в нём был бы чёрный
        // фон окна, а не трасса.
        ? [{
            kind: "polygon",
            points: [
              [0, 0], [base.width, 0], [base.width, base.height],
              [BEVEL_PX, base.height], [0, base.height - BEVEL_PX],
            ],
          }]
        : [{ kind: "rect", x: 0, y: 0, w: base.width, h: base.height }]
      : measureShape(node, scale)

    const payload = { visible, shapes }
    const encoded = JSON.stringify(payload)
    if (encoded === reported.current) return
    reported.current = encoded
    void api.set_shape(payload)
  })

  const moveDrag = (event: React.PointerEvent<HTMLElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return
    const width = event.currentTarget.offsetWidth
    const height = event.currentTarget.offsetHeight
    onMove(id, {
      x: Math.max(6, Math.min(window.innerWidth - width - 6, event.clientX - drag.current.dx)),
      y: Math.max(6, Math.min(window.innerHeight - height - 6, event.clientY - drag.current.dy)),
    })
  }

  return (
    <section
      ref={shell}
      data-overlay-widget={id}
      data-overlay-scale={scale}
      className={cn(
        "overflow-hidden",
        standalone ? "relative h-full w-full" : "absolute",
        // In edit mode the whole widget is the drag handle — there is no title
        // bar left to grab.
        standalone && editMode && "pywebview-drag-region cursor-move",
        editMode && !standalone && "cursor-move select-none",
      )}
      style={{
        transform: standalone ? undefined : `translate3d(${position.x}px, ${position.y}px, 0)`,
        // В одностраничном превью коробку надо растянуть руками: содержимое
        // внутри масштабируется трансформацией, а она размер родителя не меняет.
        width: standalone ? undefined : base.width * scale,
        height: standalone ? undefined : base.height * scale,
        backgroundColor: transparentShell ? "transparent" : PANEL,
        border: transparentShell ? undefined : `1px solid ${DIVIDER}`,
        // Фаска нижнего-левого угла. Видна только потому, что заливка панели
        // разведена с заливкой ОКНА (#0c0c10): в срезе показывается фон окна.
        // Раньше оба были одним цветом, и срез было бы нечем прочитать.
        clipPath:
          boxed && theme.bevel
            ? `polygon(0 0, 100% 0, 100% 100%, ${BEVEL_PX}px 100%, 0 calc(100% - ${BEVEL_PX}px))`
            : undefined,
      }}
      onPointerDown={beginDrag}
      onPointerMove={moveDrag}
      onPointerUp={() => { drag.current = null }}
      onPointerCancel={() => { drag.current = null }}
    >
      <div
        style={{
          width: base.width,
          height: base.height,
          transform: scale === 1 ? undefined : `scale(${scale})`,
          transformOrigin: "top left",
        }}
      >
        {children}
      </div>
      {/* Полоса оборотов кладётся ПОВЕРХ двухпиксельной кромки шапки, а не над
          ней: высота окна фиксирована (HUD_WIDGETS), и три лишних пикселя в
          потоке срезали бы у таблицы нижнюю строку. */}
      {boxed && theme.revSpine && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-50">
          <RevSpine pct={rev} />
        </div>
      )}
      <EditChrome visible={editMode} />
      {editMode && onScale && onScaleCommit && (
        <>
          <ResizeHandle
            scale={scale}
            base={base}
            onScale={(next) => onScale(id, next)}
            onCommit={(next) => onScaleCommit(id, next)}
          />
          <span
            className="pointer-events-none absolute bottom-[1px] left-[1px] z-[60] px-1 font-mono text-[9px] font-bold tabular-nums text-white"
            style={{ backgroundColor: "rgba(0,0,0,.72)" }}
          >
            {scale.toFixed(2)}×
          </span>
        </>
      )}
    </section>
  )
}

// ─── Dashboard pill (hud_overlay.qml) ──────────────────────────────────────

function RevLights({ pct }: { pct: number }) {
  const lit = Math.round((pct / 100) * 15)
  return (
    <div className="flex h-full w-full gap-[2px] p-[2px]">
      {Array.from({ length: 15 }, (_, index) => (
        <span
          key={index}
          className="h-full flex-1 rounded-[2px] transition-colors"
          style={{
            backgroundColor:
              index < lit ? (index < 5 ? "#39d37a" : index < 10 ? CRIMSON : PURPLE) : "#192531",
          }}
        />
      ))}
    </div>
  )
}

/** Gear dial with brake (left, red) and throttle (right, green) half-arcs. */
function GearDial({ gear, throttle, brake }: { gear: string; throttle: number; brake: number }) {
  const R = 44
  const CIRC = 2 * Math.PI * R
  const arc = (percent: number) => (Math.max(0, Math.min(100, percent)) / 100) * (CIRC / 2)
  return (
    <div className="relative grid h-[96px] w-[96px] shrink-0 place-items-center">
      <svg width="96" height="96" viewBox="0 0 96 96" className="absolute inset-0">
        <circle cx="48" cy="48" r={R} fill="none" stroke={RING_BG} strokeWidth="5" />
        {/* Mirrored so brake sweeps anticlockwise from 12 o'clock. */}
        <circle
          cx="48" cy="48" r={R} fill="none" stroke={CRIMSON} strokeWidth="5" strokeLinecap="round"
          strokeDasharray={`${arc(brake)} ${CIRC}`}
          transform="translate(96 0) scale(-1 1) rotate(-90 48 48)"
        />
        <circle
          cx="48" cy="48" r={R} fill="none" stroke={GREEN} strokeWidth="5" strokeLinecap="round"
          strokeDasharray={`${arc(throttle)} ${CIRC}`}
          transform="rotate(-90 48 48)"
        />
      </svg>
      <div className="grid h-[76px] w-[76px] place-items-center rounded-full" style={{ backgroundColor: PILL_INNER }}>
        <span
          className="font-broadcast text-[42px] font-black italic leading-none"
          style={{ color: TEXT_BRIGHT }}
        >
          {gear}
        </span>
      </div>
    </div>
  )
}

/** Battery ring: harvest arc plus a bottom-up charge fill. */
function ErsDial({ percent, harvested, mode }: { percent: number; harvested: number; mode: number | null }) {
  const R = 44
  const CIRC = 2 * Math.PI * R
  const modeInfo = ERS_MODE[mode ?? 0] ?? ERS_MODE[0]
  const charge = Math.max(0, Math.min(100, percent))
  const INNER = 38
  const fillTop = 48 + INNER - (charge / 100) * (INNER * 2)
  return (
    <div className="relative grid h-[96px] w-[96px] shrink-0 place-items-center">
      <svg width="96" height="96" viewBox="0 0 96 96" className="absolute inset-0">
        <defs>
          <clipPath id="ers-core">
            <circle cx="48" cy="48" r={INNER} />
          </clipPath>
        </defs>
        <circle cx="48" cy="48" r={R} fill="none" stroke={RING_BG} strokeWidth="5" />
        <circle
          cx="48" cy="48" r={R} fill="none" stroke={CRIMSON} strokeWidth="5" strokeLinecap="round"
          strokeDasharray={`${(Math.max(0, Math.min(100, harvested)) / 100) * CIRC} ${CIRC}`}
          transform="translate(96 0) scale(-1 1) rotate(-90 48 48)"
        />
        <circle cx="48" cy="48" r={INNER} fill="#09131f" />
        <rect
          x={48 - INNER} y={fillTop} width={INNER * 2} height={Math.max(0, 48 + INNER - fillTop)}
          fill={modeInfo.color} clipPath="url(#ers-core)" opacity={0.95}
        />
        <circle cx="48" cy="48" r={INNER} fill="none" stroke={PILL_BORDER} strokeWidth="1.5" />
      </svg>
      <span
        className="relative font-broadcast text-[16px] font-black italic"
        style={{
          color: TEXT_BRIGHT,
          textShadow: modeInfo.label === "MEDIUM" ? "0 0 2px #000,0 0 2px #000" : undefined,
        }}
      >
        {Math.round(charge)}%
      </span>
    </div>
  )
}

function DashboardHud({ overlay, state }: { overlay: OverlayState | null; state: SpotterState | null }) {
  const inputs = overlay?.inputs
  const session = overlay?.session
  const drsActive = Boolean(overlay?.drs_active)
  const drsClose = Boolean(session?.drs_allowed) || (session?.drs_distance_m ?? 0) > 0
  const drsColor = drsActive ? GREEN : drsClose ? AMBER : "#3d4f5e"
  const fuelDelta = overlay?.car.fuel_delta_laps
  const drsDistance = session?.drs_distance_m ?? 0
  return (
    <div className="relative h-[116px] w-[470px]">
      {/* Rev-light tab, inset so it meets the pill's shoulders like the original */}
      <div
        data-overlay-shape
        className="absolute left-[49px] right-[49px] top-0 h-3 rounded-t-[4px] border"
        style={{ backgroundColor: "#172130", borderColor: PILL_BORDER }}
      >
        <RevLights pct={inputs?.rev_lights_pct ?? 0} />
      </div>

      <div
        data-overlay-shape
        className="absolute inset-x-0 top-3 flex h-[98px] items-center rounded-full border-2"
        style={{
          borderColor: PILL_BORDER,
          background: "linear-gradient(180deg,#172130 0%,#121b28 50%,#0e1620 100%)",
        }}
      >
        <GearDial
          gear={state?.telemetry.gear ?? "—"}
          throttle={inputs?.throttle_pct ?? 0}
          brake={inputs?.brake_pct ?? 0}
        />

        <div className="flex flex-1 items-stretch px-1 py-3">
          <div className="flex w-[30%] flex-col items-center justify-center">
            <Label color={PILL_MUTED}>km/h</Label>
            <span
              className="font-broadcast text-[20px] font-black italic leading-tight"
              style={{ color: TEXT_BRIGHT }}
            >
              {overlay?.speed_kmh ?? "—"}
            </span>
            <span className="my-[2px] h-px w-full" style={{ backgroundColor: PILL_BORDER }} />
            <span
              className="font-broadcast text-[20px] font-black italic leading-tight"
              style={{ color: TEXT_BRIGHT }}
            >
              {inputs?.rpm ?? "—"}
            </span>
            <Label color={PILL_MUTED}>rpm</Label>
          </div>

          <span className="mx-1 w-px self-stretch" style={{ backgroundColor: PILL_BORDER }} />

          <div className="flex flex-1 flex-col justify-center gap-1">
            <div className="flex items-center justify-around font-mono text-[13px] font-bold" style={{ color: TEXT_BRIGHT }}>
              <span className="flex items-center gap-1" title="Track limit warnings">
                <span style={{ color: AMBER }}>⚑</span>
                {session?.track_limit_warnings ?? 0}
              </span>
              <span className="flex items-center gap-1" title="Air temperature">
                <span className="text-[9px]" style={{ color: PILL_MUTED }}>AIR</span>
                {session?.air_temp_c ?? "—"}°
              </span>
              <span className="flex items-center gap-1" title="Track temperature">
                <span className="text-[9px]" style={{ color: PILL_MUTED }}>TRK</span>
                {session?.track_temp_c ?? "—"}°
              </span>
            </div>

            <div className="flex items-center gap-1">
              <div
                className="relative h-[22px] flex-[2] overflow-hidden rounded-[5px] border"
                style={{
                  borderColor: drsColor,
                  backgroundColor: drsActive
                    ? "rgba(0,230,118,.18)"
                    : drsClose
                      ? "rgba(255,202,82,.10)"
                      : "rgba(41,56,71,.5)",
                }}
              >
                {/* Fills as the car closes on the zone (250 m runway). */}
                {!drsActive && drsClose && (
                  <span
                    className="absolute inset-y-0 left-0 transition-[width] duration-150"
                    style={{
                      width: `${drsDistance === 0 ? 100 : Math.max(0, 1 - drsDistance / 250) * 100}%`,
                      backgroundColor: "rgba(255,202,82,.5)",
                    }}
                  />
                )}
                <span
                  className="absolute inset-0 grid place-items-center font-broadcast text-[9px] font-black italic tracking-[.12em]"
                  style={{ color: drsColor }}
                >
                  DRS
                </span>
              </div>
              <span className="flex flex-1 items-center justify-center gap-1 font-mono text-[12px] font-bold">
                <span className="text-[9px]" style={{ color: PILL_MUTED }}>FUEL</span>
                <span style={{ color: fuelDelta == null ? "#3d4f5e" : fuelDelta >= 0 ? GREEN : CRIMSON }}>
                  {fuelDelta == null ? "---" : `${fuelDelta >= 0 ? "+" : ""}${fuelDelta.toFixed(2)}`}
                </span>
              </span>
            </div>
          </div>
        </div>

        <ErsDial
          percent={overlay?.car.ers_percent ?? 0}
          harvested={overlay?.car.ers_harvested_pct ?? 0}
          mode={overlay?.car.ers_deploy_mode ?? null}
        />
      </div>
    </div>
  )
}

// ─── Lap timer (lap_timer_overlay.qml) ─────────────────────────────────────

function StatCell({
  label, value, color = TEXT, bordered = false,
}: { label: string; value: React.ReactNode; color?: string; bordered?: boolean }) {
  return (
    <div
      className="flex flex-col justify-center gap-[2px] overflow-hidden px-3 py-1"
      style={{
        borderLeft: bordered ? `1px solid ${DIVIDER}` : undefined,
        borderTop: `1px solid ${DIVIDER}`,
      }}
    >
      <Label>{label}</Label>
      <span className="font-mono text-[12px] font-bold tabular-nums" style={{ color }}>{value}</span>
    </div>
  )
}

/** Цвет времени круга по конвенции хронометража F1.
 *
 *  Решение принимает БЭКЕНД (`core/overlay.py::lap_tone`) — здесь только
 *  раскраска. Правило с порогом и тремя эталонами живёт там, где его покрывают
 *  тесты; вторая копия шкалы в вёрстке молча разошлась бы с первой.
 *
 *  `null` означает «сравнивать не с чем» (первый круг сессии): время остаётся
 *  обычного цвета, а не красится наугад. */
const LAP_TONE_COLOR: Record<string, string> = {
  purple: PURPLE,
  green: GREEN,
  yellow: AMBER,
  red: CRIMSON,
}

function LapTimer({ overlay }: { overlay: OverlayState | null }) {
  const sector = overlay?.corner.sector ?? 0
  const compound = overlay?.tyre.compound ?? "?"
  const compoundColor = tyreColor(overlay?.tyre.compound, overlay?.tyre.compound_color)
  const lapColor = LAP_TONE_COLOR[overlay?.car.last_lap_tone ?? ""] ?? TEXT_BRIGHT
  return (
    <OverlayPanel
      title="Lap"
      accent={CYAN}
      right={
        <span className="font-mono text-[9px] font-bold tabular-nums" style={{ color: TEXT_BRIGHT }}>
          {overlay?.lap_current ?? "—"}
          <span style={{ color: LABEL_CLR }}>/{overlay?.lap_total ?? "—"}</span>
        </span>
      }
    >
      <div className="flex h-full flex-col">
        <div className="shrink-0 px-3 pb-1.5 pt-1" style={{ backgroundColor: PANEL_RAISED }}>
          <Label>last lap</Label>
          <div
            className="font-broadcast text-[27px] font-black italic leading-none tabular-nums"
            style={{ color: lapColor }}
          >
            {overlay?.car.last_lap_str ?? "--:--.---"}
          </div>
          {/* Полоски — это ПРОГРЕСС по секторам, а не хронометраж: своих
              времён по секторам в оверлей не приезжает. Раньше они красились
              тем же зелёным, что и хорошее время круга, и читались как оценка
              («зелёный сектор») — отсюда и жалоба «непонятно». Нейтральный
              белый прогресса не обещает ничего лишнего. */}
          <div className="mt-1.5 grid grid-cols-3 gap-1">
            {[1, 2, 3].map((index) => (
              <span
                key={index}
                className="h-[3px]"
                style={{
                  backgroundColor: index === sector
                    ? TEXT_BRIGHT
                    : index < sector ? "#6b7280" : "#303044",
                }}
              />
            ))}
          </div>
        </div>
        <div className="grid flex-1 grid-cols-2">
          <StatCell label="ahead" value={overlay?.gaps.to_front_str ?? "---"} color={CYAN} />
          <StatCell label="behind" value={overlay?.gaps.to_behind_str ?? "---"} bordered />
          <StatCell label="leader" value={overlay?.gaps.to_leader_str ?? "---"} />
          <StatCell
            label="tyre"
            bordered
            value={
              <span className="flex items-center gap-1.5">
                <TyreDisc compound={compound} color={compoundColor} size={15} />
                <span style={{ color: compoundColor }}>{overlay?.tyre.age_laps ?? "—"}L</span>
              </span>
            }
          />
        </div>
      </div>
    </OverlayPanel>
  )
}

// ─── Timing tower (timing_tower.qml) ───────────────────────────────────────

/** Экспортируется ради панели выбора темы на экране «Оверлей»: превью там
 *  рисуется НАСТОЯЩЕЙ башней в уменьшенном масштабе, а не отдельным макетом —
 *  нарисованный отдельно, он разошёлся бы с оверлеем на первой же правке. */
export function TimingTower({
  rows,
  overlay,
}: {
  rows: OverlayRelativeRow[]
  overlay: OverlayState | null
}) {
  // Восемь строк, а не семь: шапка забрала 18 px, но строка колонок ужалась до
  // 14, и в окне 264×288 остаётся место ровно на ещё одного соперника —
  // 18 + 14 + 8×30 = 272. Контекст вокруг игрока дороже пустоты внизу.
  const visible = rows.slice(0, 8)
  return (
    <OverlayPanel
      title="Timing"
      variant="red"
      right={
        <span className="font-mono text-[9px] font-bold tabular-nums text-white/85">
          LAP {overlay?.lap_current ?? "—"}
          <span className="text-white/50">/{overlay?.lap_total ?? "—"}</span>
        </span>
      }
    >
      <div className="flex h-full flex-col">
        <div
          className="flex h-[14px] shrink-0 items-center gap-1.5 pl-1 pr-1.5"
          style={{ borderBottom: `1px solid ${DIVIDER}`, backgroundColor: PANEL_RAISED }}
        >
          <span className="w-[27px] shrink-0 pl-[6px]"><Label>pos</Label></span>
          <Label>driver</Label>
          <span className="ml-auto"><Label>gap</Label></span>
        </div>

        {visible.length === 0 && (
          <div className="grid flex-1 place-items-center font-mono text-[9px]" style={{ color: LABEL_CLR }}>
            WAITING FOR TIMING
          </div>
        )}

        {visible.map((row, index) => {
          const isPlayer = row.ahead === null
          return (
            <div
              key={`${row.vehicle_idx}-${row.position}`}
              className="flex h-[30px] shrink-0 items-center gap-1.5 pl-1 pr-1.5"
              style={{
                borderBottom: `1px solid ${DIVIDER}`,
                // Растушёвка акцентом слева — так трансляция подсвечивает
                // машину, за которую идёт показ, не перекрашивая всю строку.
                // Зебра у приборной темы выключена токеном: там ритм задают
                // линейки, и полосатый фон спорил бы с ними.
                background: isPlayer ? PLAYER_ROW : index % 2 === 1 ? ROW_ALT : PANEL,
              }}
            >
              <TeamEdge color={row.color} />
              <PosBlock pos={row.position} highlight={isPlayer} />
              <span
                className="font-broadcast min-w-0 truncate text-[13px] font-bold uppercase italic tracking-wide"
                style={{ color: isPlayer ? "#fff" : TEXT_BRIGHT }}
              >
                {row.driver}
              </span>
              <span
                className="ml-auto min-w-[52px] shrink-0 rounded-[2px] bg-black/45 px-1.5 py-[2px] text-right font-mono text-[11px] font-bold tabular-nums"
                style={{
                  // Впереди / позади — разные угрозы, и цвет обязан их различать:
                  // синий отыгрывается, красный догоняет. Тема меняет оттенок,
                  // но не смысл — поменять их местами она права не имеет.
                  color: isPlayer ? CYAN : row.ahead ? GAP_AHEAD : GAP_BEHIND,
                }}
              >
                {isPlayer ? "—" : row.gap_to_player_str}
              </span>
            </div>
          )
        })}
      </div>
    </OverlayPanel>
  )
}

// ─── Input traces (input_telemetry.qml) ────────────────────────────────────

const TRACE_LENGTH = 175

function InputTraces({ inputs }: { inputs: OverlayState["inputs"] | undefined }) {
  const [history, setHistory] = useState<{ t: number[]; b: number[]; s: number[] }>({ t: [], b: [], s: [] })
  const throttle = inputs?.throttle_pct ?? 0
  const brake = inputs?.brake_pct ?? 0
  const steer = inputs?.steer ?? 0

  useEffect(() => {
    setHistory((prev) => ({
      t: [...prev.t, throttle].slice(-TRACE_LENGTH),
      b: [...prev.b, brake].slice(-TRACE_LENGTH),
      // Steering is centred: map -1..1 onto 0..100 so one renderer fits all three.
      s: [...prev.s, (steer + 1) * 50].slice(-TRACE_LENGTH),
    }))
  }, [throttle, brake, steer])

  const path = (values: number[]) => {
    if (values.length < 2) return ""
    const step = 100 / (TRACE_LENGTH - 1)
    return values
      .map((value, index) =>
        `${index === 0 ? "M" : "L"}${(index * step).toFixed(2)},${(100 - value).toFixed(2)}`)
      .join(" ")
  }

  return (
    <OverlayPanel
      title="Inputs"
      accent="#76FF03"
      right={
        <span className="font-mono text-[9px] font-bold tabular-nums" style={{ color: LABEL_CLR }}>
          {TRACE_LENGTH} SAMPLES
        </span>
      }
    >
      <div className="flex h-full flex-col">
        <div className="relative min-h-0 flex-1">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
            <line x1="0" y1="50" x2="100" y2="50" stroke={DIVIDER} strokeWidth="0.4" />
            <path d={path(history.s)} fill="none" stroke="#2979FF" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            <path d={path(history.b)} fill="none" stroke={CRIMSON} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
            <path d={path(history.t)} fill="none" stroke="#76FF03" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
        <div
          className="flex shrink-0 items-center justify-around px-3 py-1 font-mono text-[10px] font-bold tabular-nums"
          style={{ borderTop: `1px solid ${DIVIDER}`, backgroundColor: PANEL_RAISED }}
        >
          <span style={{ color: "#76FF03" }}>THR {Math.round(throttle)}%</span>
          <span style={{ color: CRIMSON }}>BRK {Math.round(brake)}%</span>
          <span style={{ color: "#2979FF" }}>
            STR {steer > 0 ? "R" : steer < 0 ? "L" : "—"}{Math.abs(Math.round(steer * 100))}
          </span>
        </div>
      </div>
    </OverlayPanel>
  )
}

// ─── Track radar (track_radar.qml) ─────────────────────────────────────────

function TrackRadar({ contacts }: { contacts: OverlayRadarContact[] }) {
  const SIZE = 300
  const CENTER = SIZE / 2
  const MAX_LAT = 5
  const MAX_LONG = 18
  const limit = CENTER - 28
  // «Борт о борт» выводится из тех же полей, что уже рисуют метки: соперник
  // сбоку и в пределах длины машины. Новых данных бэкенд для этого не отдаёт,
  // и придумывать их нельзя — порог совпадает с шириной коридора на радаре.
  const alongside = contacts.some(
    (contact) => contact.lateral_m <= 1.6 && Math.abs(contact.longitudinal_m) <= 5,
  )
  return (
    <div
      className="relative h-full w-full transition-opacity duration-300"
      style={{ opacity: contacts.length > 0 ? 1 : 0.3 }}
    >
      <div
        // Окно радара обрезается ровно по этому кругу: раньше вокруг него
        // лежал чёрный квадрат 300×300 поверх трассы.
        data-overlay-shape="ellipse"
        className="absolute inset-6 rounded-full border-2 transition-colors"
        style={{
          borderColor: alongside ? DANGER : "#343444",
          backgroundColor: "rgba(12,12,16,.55)",
          boxShadow: alongside ? `inset 0 0 22px rgba(225,6,0,.35)` : undefined,
        }}
      />
      <div className="absolute inset-[70px] rounded-full border" style={{ borderColor: "#292938" }} />
      <div className="absolute left-1/2 top-6 h-[calc(100%-48px)] w-px -translate-x-1/2" style={{ backgroundColor: "#343444" }} />
      <div className="absolute left-6 top-1/2 h-px w-[calc(100%-48px)] -translate-y-1/2" style={{ backgroundColor: "#343444" }} />
      <div
        className="absolute left-1/2 top-1/2 h-[29px] w-[10px] -translate-x-1/2 -translate-y-1/2 rounded-[2px] border border-white"
        style={{ backgroundColor: GREEN, boxShadow: `0 0 10px ${GREEN}88` }}
      />
      {contacts.map((contact) => {
        // side is authoritative; lateral_m is an absolute distance.
        const signedLateral = contact.side === "left" ? -contact.lateral_m : contact.lateral_m
        const rawX = (signedLateral / MAX_LAT) * limit
        const rawY = -(contact.longitudinal_m / MAX_LONG) * limit
        const radius = Math.hypot(rawX, rawY)
        const scale = radius > limit ? limit / radius : 1
        const close = contact.lateral_m <= 1.6 && Math.abs(contact.longitudinal_m) <= 5
        return (
          <div
            key={contact.vehicle_idx}
            className="absolute h-[29px] w-[10px] -translate-x-1/2 -translate-y-1/2 rounded-[2px] border bg-white"
            style={{
              left: CENTER + rawX * scale,
              top: CENTER + rawY * scale,
              borderColor: close ? DANGER : "rgba(255,255,255,.7)",
              boxShadow: close ? `0 0 10px ${DANGER}` : undefined,
            }}
          />
        )
      })}
      {alongside && (
        <span
          // Внутри круга, а не под ним: окно обрезано по кругу, и на прежних
          // 18 px бейдж срезало бы наполовину.
          className="font-broadcast absolute bottom-[34px] left-1/2 -translate-x-1/2 rounded-[2px] px-2 py-[2px] text-[9px] font-black uppercase italic tracking-[.16em] text-white"
          style={{ backgroundColor: DANGER }}
        >
          Alongside
        </span>
      )}
    </div>
  )
}

// ─── Power unit (pu.qml) ───────────────────────────────────────────────────

function PowerUnit({ car }: { car: OverlayState["car"] | undefined }) {
  const ice = car?.power_ice_kw ?? 0
  const mguk = car?.power_mguk_kw ?? 0
  const total = ice + mguk
  const iceFraction = total > 0 ? ice / total : 0
  const mgukFraction = total > 0 ? mguk / total : 0
  return (
    <OverlayPanel title="Power Unit" accent={MGUK}>
      <div className="flex h-full flex-col justify-center gap-1.5 px-3 py-2">
        <div className="flex items-baseline gap-1">
          <span
            className="font-broadcast text-[22px] font-black italic leading-none tabular-nums"
            style={{ color: TEXT_BRIGHT }}
          >
            {Math.round(total)}
          </span>
          <Label>kW</Label>
        </div>
        <div className="flex h-[10px] overflow-hidden rounded-[2px]" style={{ backgroundColor: PANEL_RAISED }}>
          <span className="h-full transition-[width] duration-200" style={{ width: `${iceFraction * 100}%`, backgroundColor: CRIMSON }} />
          <span className="h-full transition-[width] duration-200" style={{ width: `${mgukFraction * 100}%`, backgroundColor: MGUK }} />
        </div>
        <div className="flex items-center justify-between font-mono text-[10px] font-bold tabular-nums">
          <span style={{ color: CRIMSON }}>ICE {Math.round(ice)}</span>
          <span style={{ color: MGUK }}>MGU-K {Math.round(mguk)}</span>
        </div>
      </div>
    </OverlayPanel>
  )
}

// ─── Race engineer + team radio (ours) ─────────────────────────────────────

function EngineerPanel({ overlay }: { overlay: OverlayState | null }) {
  const action = overlay?.strategy.action ?? "hold"
  const actionLabel = STRATEGY_LABEL[action] ?? action.toUpperCase()
  const isPit = action === "pit"
  return (
    <OverlayPanel
      title="Engineer"
      accent={isPit ? DANGER : CYAN}
      right={
        <span className="font-mono text-[9px] font-bold tabular-nums" style={{ color: LABEL_CLR }}>
          {Math.round((overlay?.strategy.confidence ?? 0) * 100)}%
        </span>
      }
    >
      <div className="flex h-full flex-col">
        {/* Команда на круг — единственная строка, ради которой на панель
            смотрят в повороте. Заезд в боксы заливается целиком: его нельзя
            перепутать с обычным советом. */}
        <div
          className="flex h-[30px] shrink-0 items-center gap-2 px-2"
          style={{
            borderBottom: `1px solid ${DIVIDER}`,
            background: isPit ? "linear-gradient(100deg,#e10600 0%,#a70400 100%)" : PANEL_RAISED,
          }}
        >
          <span
            className="f1-skew block h-[14px] w-[4px] shrink-0"
            style={{ backgroundColor: isPit ? "#fff" : CYAN }}
            aria-hidden
          />
          <span
            className="font-broadcast truncate text-[16px] font-black uppercase italic tracking-wide"
            style={{ color: isPit ? "#fff" : CYAN }}
          >
            {actionLabel}
          </span>
        </div>
        <p className="line-clamp-3 min-h-0 flex-1 px-2.5 py-1.5 text-[11px] font-semibold leading-[1.35]" style={{ color: TEXT }}>
          {overlay?.strategy.advice ?? overlay?.situation.advice ?? "Инженер следит за темпом и состоянием машины"}
        </p>
        <div className="grid shrink-0 grid-cols-2" style={{ borderTop: `1px solid ${DIVIDER}` }}>
          <div className="flex flex-col gap-[2px] px-2.5 py-1.5">
            <Label>sector</Label>
            <span className="font-mono text-[9px] font-bold truncate" style={{ color: TEXT }}>
              S{overlay?.corner.sector ?? "—"} · {overlay?.corner.name ?? "TRACK"}
            </span>
          </div>
          <div className="flex flex-col gap-[2px] px-2.5 py-1.5" style={{ borderLeft: `1px solid ${DIVIDER}` }}>
            <Label>mode</Label>
            <span
              className="font-mono text-[9px] font-bold truncate"
              style={{ color: overlay?.corner.attack_zone ? DANGER : TEXT }}
            >
              {overlay?.situation.mode_label || "RACE"}
            </span>
          </div>
        </div>
      </div>
    </OverlayPanel>
  )
}

function Waveform({ live }: { live: boolean }) {
  return (
    <div className="flex h-7 items-center gap-[2px]" aria-hidden="true">
      {Array.from({ length: 18 }, (_, index) => (
        <span
          key={index}
          className={cn("w-[2px]", live && "overlay-wave-bar")}
          style={{
            height: `${7 + ((index * 11) % 18)}px`,
            backgroundColor: RED,
            animationDelay: `${index * -38}ms`,
          }}
        />
      ))}
    </div>
  )
}

// Сколько секунд читать невозвученную реплику, прежде чем убрать её с экрана.
// Заметно дольше типичной фразы вслух: её нужно успеть прочитать боковым
// зрением, не отрываясь от трассы. Значение настраивается («Рация» → «Время
// показа субтитра»); эта константа — фолбэк, пока состояние не пришло.
const RADIO_TEXT_TTL_S = 12

function subtitleTtlSeconds(state: SpotterState | null): number {
  const value = state?.settings?.subtitle_seconds
  return typeof value === "number" && value > 0 ? value : RADIO_TEXT_TTL_S
}

function subtitlesEnabled(state: SpotterState | null): boolean {
  return state?.settings?.subtitles_enabled !== false
}

/* Сколько держать карточку на экране после события (ТЗ §16).

   Вынесено в константы намеренно: значения подбираются на реальной гонке, и
   искать их по коду среди инлайновых чисел — то, чем этот файл болел раньше
   (8_000 / 12_000 / 60_000 прямо в обработчике опроса). */
const SHOW_MS = {
  /** Короткая реплика споттера: 1,5–2,5 с — её читать не нужно, только заметить. */
  spotter: 2_200,
  /** Обычная реплика инженера: длительность речи плюс запас на прочтение. */
  engineer: 3_000,
  /** Критическая: тот же запас, но больше — от неё зависит действие. */
  critical: 4_000,
  /** PTT-диалог: ответ должен успеть быть прочитан целиком. */
  ptt: 6_000,
  /** Пока идёт запрос пилота — держим, ответ придёт следом. */
  pttBusy: 60_000,
} as const

/** Оценка длительности речи по тексту: ~9 знаков в секунду для русской речи.
 *  Точной длительности бэкенд не сообщает, а держать карточку фиксированное
 *  время нельзя — длинная реплика исчезала бы, не дочитанной. */
function speechMs(text: string): number {
  return Math.min(9_000, Math.max(1_200, Math.round((text.length / 9) * 1000)))
}

// Фазы PTT, на которых карточка держится в кадре, живут в lib/radio-ui.ts
// (PTT_BUSY_STATES) — общие с экраном «Рация».

// Подписи фаз PTT. Не «LIVE»: пилот в этот момент никого не слышит, и бейдж
// эфира сказал бы ему неправду (ТЗ §8, §14).
const PTT_STATUS_TEXT: Record<string, string> = {
  listening: "СЛУШАЮ",
  recognizing: "РАСПОЗНАЮ",
  thinking: "ПРОВЕРЯЮ ДАННЫЕ",
}

const FALLBACK_PROFILE: RadioSpeakerProfile = {
  speaker_id: "race_engineer",
  speaker_name: "—",
  speaker_role: "RACE ENGINEER",
  speaker_initials: "—",
  portrait_url: null,
  accent: CHANNEL_ACCENT.engineer,
}

function profileOf(state: SpotterState | null, channel: RadioSource): RadioSpeakerProfile {
  return state?.radio?.speakers?.[channel] ?? FALLBACK_PROFILE
}

/** Разрешена ли карточка этого канала настройками (ТЗ §18).
 *
 *  Скрытие карточки НЕ отключает звук: споттер и критический инженер всё равно
 *  прозвучат. Поэтому здесь только показ, и рядом с этой функцией не должно
 *  появиться ничего, что трогает озвучку. */
function cardAllowed(state: SpotterState | null, channel: RadioSource): boolean {
  const settings = state?.settings
  if (settings?.show_broadcast_radio_card === false) return false
  if (channel === "spotter") return settings?.show_spotter_card !== false
  if (channel === "commentator") return settings?.show_commentary_card !== false
  return true
}

/** Собрать view-модель карточки из состояния радио.
 *
 *  Вся логика «что и когда показывать» живёт ЗДЕСЬ, а не в компоненте. Это
 *  самое хрупкое место фичи — критерии готовности 1, 7 и 8 говорят про
 *  МОМЕНТЫ, а не про пиксели, — и правило должно читаться целиком в одном
 *  месте, а не собираться из десятка условий по JSX.
 *
 *  `null` означает «карточки нет»: это штатный и самый частый случай. */
function radioCardView(
  state: SpotterState | null,
  query: VoiceQuery | null,
): RadioCardView | null {
  const settings = state?.settings
  const scale = clampScale(settings?.radio_card_scale)
  const base = {
    scale,
    textPx: textSizePx(settings?.subtitle_size, scale),
    showPortrait: settings?.show_portraits !== false,
    // В нативном окне вьюпорт — само окно, поэтому clamp из CARD.width дал бы
    // минимум. Ширину задаёт окно (core/overlay_window.py::HUD_WIDGETS).
    width: "100%",
  }

  const radio = state?.radio ?? null
  const ptt = radio?.ptt ?? null
  const pttState = ptt?.state ?? query?.status ?? "idle"
  const active = radio?.active_message ?? null

  // 1. PTT-диалог. Идёт раньше активного сообщения: пока пилот говорит, он
  //    ждёт ответа именно на свой запрос, и автоматическая реплика не должна
  //    подменить собой диалог.
  if (PTT_BUSY_STATES.has(pttState)) {
    const asDriver = pttState === "listening" || pttState === "recognizing"
    const channel: RadioSource = asDriver ? "driver" : "engineer"
    if (!cardAllowed(state, channel)) return null
    const profile = profileOf(state, channel)
    return {
      ...base,
      channel,
      urgency: "normal",
      speakerName: profile.speaker_name,
      speakerRole: asDriver ? "DRIVER RADIO" : profile.speaker_role,
      initials: profile.speaker_initials,
      portraitUrl: profile.portrait_url,
      accent: profile.accent,
      text: "",
      live: false,
      status: PTT_STATUS_TEXT[pttState] ?? null,
      // Вопрос показываем только когда инженер уже думает над ним: во время
      // записи текста ещё нет, а на распознавании он неточен.
      question: pttState === "thinking" ? (ptt?.driver_text ?? query?.question ?? null) : null,
      compact: asDriver,
    }
  }

  // 2. Реальная передача. `queued` и `cancelled` сюда не попадают вовсе —
  //    их нет в VISIBLE_STATES, и это критерии 1 и 8.
  if (active && VISIBLE_STATES.has(active.state) && cardAllowed(state, active.channel)) {
    const isAnswer = active.id === ptt?.answer_message_id
    return {
      ...base,
      channel: active.channel,
      urgency: active.urgency,
      speakerName: active.speaker_name,
      speakerRole: active.speaker_role,
      initials: active.speaker_initials,
      portraitUrl: active.portrait_url,
      accent: active.accent,
      text: active.text,
      live: active.state === "playing",
      status: active.state === "playing" ? null : "ПРИНЯТО",
      // Вопрос остаётся мелкой строкой над ответом, а не превращается в
      // отдельный чат-пузырь (ТЗ §14).
      question: isAnswer ? (ptt?.driver_text ?? null) : null,
      // Короткая реплика споттера — одна строка без портрета (ТЗ §13).
      compact: active.channel === "spotter" && active.text.length <= 24,
      exiting: active.state === "interrupted",
      interrupted: active.state === "interrupted",
    }
  }

  // 3. «System Message»: реплику не озвучили (авто-озвучка выключена, отвал
  //    TTS) — инженер обязан НАПИСАТЬ, иначе он в игре просто исчезает.
  const silent = state?.radio_message
  const textOnly =
    subtitlesEnabled(state) &&
    Boolean(silent?.text) &&
    silent?.voiced === false &&
    Date.now() / 1000 - (silent?.ts ?? 0) < subtitleTtlSeconds(state)
  if (textOnly && cardAllowed(state, "engineer")) {
    const profile = profileOf(state, "engineer")
    return {
      ...base,
      channel: "engineer",
      urgency: "normal",
      speakerName: profile.speaker_name,
      speakerRole: profile.speaker_role,
      initials: profile.speaker_initials,
      portraitUrl: profile.portrait_url,
      accent: profile.accent,
      text: silent?.text ?? "",
      live: false,
      status: "БЕЗ ОЗВУЧКИ",
    }
  }

  return null
}

function RadioPanel({
  state,
  query,
  editMode,
}: {
  state: SpotterState | null
  query: VoiceQuery | null
  editMode: boolean
}) {
  const view = radioCardView(state, query)
  const error = state?.radio?.ptt?.error ?? query?.error ?? null
  const pttState = state?.radio?.ptt?.state ?? query?.status ?? "idle"

  // Ошибка PTT — единственный случай, когда поверх игры показывается неудача,
  // и только потому, что пилот САМ нажал кнопку и ждёт ответа. Автоматические
  // сбои в кадр не выводятся вовсе (ТЗ §9): пилоту нечего с ними делать.
  if (!view && pttState === "error") {
    return (
      <div
        data-overlay-shape
        className="flex items-center gap-2 px-3 py-2"
        style={{
          backgroundColor: RADIO_SURFACE.bg,
          border: `1px solid ${RADIO_SURFACE.border}`,
          borderRadius: RADIO_SURFACE.radius,
        }}
      >
        <Radio className="h-4 w-4 shrink-0" style={{ color: RED }} aria-hidden />
        <span className="text-[11px] font-semibold" style={{ color: RADIO_SURFACE.text }}>
          {error ?? "Радиоканал недоступен"}
        </span>
      </div>
    )
  }

  // В режиме редактирования карточка обязана быть видимой и перетаскиваемой,
  // иначе её нельзя поставить на место: в покое она не показывается вовсе.
  if (!view) {
    if (!editMode) return null
    const profile = profileOf(state, "engineer")
    return (
      <BroadcastRadioCard
        view={{
          channel: "engineer",
          urgency: "normal",
          speakerName: profile.speaker_name,
          speakerRole: profile.speaker_role,
          initials: profile.speaker_initials,
          portraitUrl: profile.portrait_url,
          accent: profile.accent,
          text: `Карточка появляется только во время передачи. ${hotkeyLabel(state)} — связаться с инженером.`,
          live: false,
          status: "РАЗМЕЩЕНИЕ",
          textPx: 14,
          scale: 1,
          width: "100%",
        }}
      />
    )
  }

  return <BroadcastRadioCard view={view} />
}

export function InGameOverlay() {
  const [state, setState] = useState<SpotterState | null>(null)
  const [overlay, setOverlay] = useState<OverlayState | null>(null)
  const [online, setOnline] = useState(true)
  const [editMode, setEditMode] = useState(false)
  const [widgetId, setWidgetId] = useState<WidgetId | null>(null)
  // `?theme=` перебивает настройку — иначе три темы нечем сравнить: в режиме
  // `?preview=` опроса нет вовсе, и `state.settings` туда не приезжает.
  const [themeOverride, setThemeOverride] = useState<string | null>(null)
  const [routeReady, setRouteReady] = useState(false)
  const [layout, setLayout] = useState<Layout>(DEFAULT_LAYOUT)
  const [scales, setScales] = useState<Partial<Record<WidgetId, number>>>({})
  const [disabled, setDisabled] = useState<Set<WidgetId>>(() => new Set())
  const [radioUntil, setRadioUntil] = useState(0)
  const [clockMs, setClockMs] = useState(0)
  const previousQuery = useRef<string | null>(null)
  // ts последней показанной текстовой реплики — чтобы не продлевать показ
  // бесконечно на каждом опросе (250 мс) для одного и того же сообщения.
  const previousSilentTs = useRef<number>(0)
  // id последнего показанного сообщения — чтобы одна реплика продлевала
  // показ один раз, а не на каждом опросе.
  const previousMessageId = useRef<string | null>(null)
  // Известная ревизия радио — уходит в запрос, чтобы сервер не присылал
  // неизменившуюся историю. Ref, а не state: изменение не должно вызывать
  // перерисовку, оно нужно только следующему запросу.
  const knownRadioRevision = useRef<number | undefined>(undefined)
  // Идёт ли прямо сейчас перетаскивание уголка размера — на это время опрос
  // раскладки не имеет права переписывать показанный масштаб.
  const draggingScale = useRef(false)

  useEffect(() => {
    document.documentElement.classList.add("overlay-shell")
    document.body.classList.add("overlay-shell")
    const params = new URLSearchParams(window.location.search)
    const requested = params.get("widget")
    const resolved = requested && requested in WIDGET_SIZE ? (requested as WidgetId) : null
    setWidgetId(resolved)
    setThemeOverride(params.get("theme"))
    if (!resolved) setLayout(readLayout())
    setRouteReady(true)
    const onEdit = (event: WindowEventMap["spotter-overlay-edit"]) => setEditMode(Boolean(event.detail))
    window.addEventListener("spotter-overlay-edit", onEdit)
    return () => {
      window.removeEventListener("spotter-overlay-edit", onEdit)
      document.documentElement.classList.remove("overlay-shell")
      document.body.classList.remove("overlay-shell")
    }
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.has("preview")) {
      setState(previewStateFor(params.get("preview")))
      setOverlay(PREVIEW_OVERLAY)
      // Сценарии радио показывают ОДНУ карточку, а не весь HUD: их смотрят,
      // чтобы оценить саму карточку, и остальные виджеты только мешали бы
      // измерять переполнение и пересечения.
      setEditMode(!String(params.get("preview") ?? "").startsWith("radio-"))
      setRadioUntil(Date.now() + 3_600_000)
      return
    }
    let mounted = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        // Оверлей историю не рисует, поэтому просит её только когда она
        // изменилась. На четырёх опросах в секунду это разница между
        // пересылкой 150 строк и одного булева флага (ТЗ §11, критерий 14).
        const [nextState, nextOverlay] = await Promise.all([
          getState(knownRadioRevision.current), getOverlay(),
        ])
        if (!mounted) return
        knownRadioRevision.current = nextState.radio?.revision
        setState(nextState)
        setOverlay(nextOverlay)
        setOnline(true)
        // Время показа считается от АКТИВНОГО СООБЩЕНИЯ, а не от флага
        // `speaking`. Раньше опрос ловил `speaking` в момент постановки в
        // очередь — флаг жил микросекунды, и карточка для озвученной реплики
        // чаще всего не показывалась вовсе (дефект, найденный в Task 1).
        const active = nextState.radio?.active_message ?? null
        if (active && active.id !== previousMessageId.current) {
          previousMessageId.current = active.id
          // Длительность речи бэкенд не сообщает, а держать карточку
          // фиксированное время нельзя: длинная реплика исчезала бы
          // недочитанной. Поэтому оценка по тексту плюс linger канала.
          const hold = speechMs(active.text) + lingerMs(active.channel, active.urgency, {
            isPttAnswer: active.id === nextState.radio?.ptt?.answer_message_id,
            scale: nextState.settings?.radio_card_duration ?? 1,
          })
          setRadioUntil(Date.now() + hold)
        }

        const ptt = nextState.radio?.ptt ?? null
        const signature = ptt
          ? `${ptt.state}:${ptt.driver_text ?? ""}:${ptt.engineer_text ?? ""}`
          : null
        if (signature && signature !== previousQuery.current) {
          const terminal = ptt?.state === "done" || ptt?.state === "error"
          setRadioUntil(Date.now() + (terminal ? SHOW_MS.ptt : SHOW_MS.pttBusy))
        }

        // Прерванная реплика убирается НЕМЕДЛЕННО: держать на экране текст,
        // которого пилот уже не слышит, — это критерий готовности 7.
        if (active?.state === "interrupted") {
          setRadioUntil(0)
        }

        // Невозвученная реплика тоже должна ПОКАЗАТЬ виджет: иначе «инженер
        // пишет вместо того, чтобы говорить» некуда было бы вывести —
        // виджет рации скрыт, пока никто не говорит.
        const silent = nextState.radio_message
        if (silent?.text && silent.voiced === false && silent.ts !== previousSilentTs.current
            && subtitlesEnabled(nextState)) {
          previousSilentTs.current = silent.ts
          setRadioUntil(Date.now() + subtitleTtlSeconds(nextState) * 1000)
        }
        previousQuery.current = signature
      } catch {
        if (mounted) setOnline(false)
      } finally {
        if (mounted) {
          setClockMs(Date.now())
          timer = setTimeout(poll, 250)
        }
      }
    }
    void poll()
    return () => {
      mounted = false
      if (timer) clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (routeReady && widgetId === null) {
      // «Не запоминать позицию» = не писать её на диск, а не откатывать прямо
      // сейчас: выдёргивать карточку из-под курсора во время перетаскивания
      // было бы хуже, чем оставить её до перезапуска. Сохранённое значение
      // стирается, иначе следующий старт поднял бы позицию из прошлой сессии.
      if (state?.settings?.remember_overlay_position === false) {
        window.localStorage.removeItem(STORAGE_KEY)
        return
      }
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout))
    }
  }, [layout, routeReady, widgetId, state?.settings?.remember_overlay_position])

  const moveWidget = useCallback((id: WidgetId, point: Point) => {
    setLayout((current) => ({ ...current, [id]: point }))
  }, [])

  // Масштаб виджетов живёт на бэкенде, а не в localStorage: нативное окно
  // размером base × scale создаёт Python, и страница обязана показывать ровно
  // тот множитель, из которого посчитано окно. Опрос редкий — раскладку меняет
  // человек, а не гонка; частый нужен только состоянию телеметрии.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("preview")) return
    let mounted = true
    const pull = async () => {
      try {
        const next = await getOverlayLayout()
        if (!mounted) return
        setScales((current) => {
          // Не затирать масштаб, который прямо сейчас тянут за уголок: ответ
          // сервера приходит с задержкой и дёргал бы виджет назад.
          if (draggingScale.current) return current
          const incoming: Partial<Record<WidgetId, number>> = {}
          for (const id of Object.keys(WIDGET_SIZE) as WidgetId[]) {
            incoming[id] = clampWidgetScale(next.widgets?.[id]?.scale ?? 1)
          }
          return incoming
        })
        // Выключенные виджеты не рисуются и в превью: иначе картинка обещала
        // бы то, чего в игре уже нет.
        setDisabled(new Set(
          (Object.keys(WIDGET_SIZE) as WidgetId[])
            .filter((id) => next.widgets?.[id]?.enabled === false),
        ))
      } catch {
        // Раскладка недоступна — виджеты остаются в масштабе 1.0. Это ровно то
        // же поведение, что было до появления масштаба, и падать здесь нечему.
      }
    }
    void pull()
    const timer = setInterval(pull, 2_000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [])

  const previewScale = useCallback((id: WidgetId, next: number) => {
    draggingScale.current = true
    setScales((current) => ({ ...current, [id]: next }))
  }, [])

  const commitScale = useCallback((id: WidgetId, next: number) => {
    draggingScale.current = false
    void setOverlayScale(id, next).catch(() => {
      // Сохранить не удалось — оставляем показанный масштаб до следующего
      // опроса, он вернёт то, что на самом деле лежит на диске.
    })
  }, [])

  const query = state?.voice_query ?? null
  const pttState = state?.radio?.ptt?.state ?? query?.status ?? "idle"
  const radioBusy = PTT_BUSY_STATES.has(pttState)
  const radioActive = state?.radio?.active_message?.state
  const showRadio =
    editMode || radioBusy ||
    radioActive === "playing" || radioActive === "synthesizing" ||
    clockMs < radioUntil
  const towerRows = useMemo(() => overlay?.relative ?? [], [overlay?.relative])
  const radarBusy = Boolean(overlay?.radar.length)

  const themeId = resolveThemeId(themeOverride ?? state?.settings?.overlay_theme)
  // Пока канал в эфире, акцент оформления становится цветом говорящего — и
  // меняется он одновременно во ВСЕХ восьми окнах, потому что каждое опрашивает
  // один и тот же `/api/state` с шагом 250 мс. Отдельного канала связи между
  // окнами для этого не нужно.
  const speaking = state?.radio?.active_message ?? null
  const accentPulse =
    THEMES[themeId].channelPulse && speaking
      ? accentFor(speaking.channel, speaking.urgency, speaking.accent)
      : undefined
  // Тема раздаётся двумя путями сразу: атрибут кормит палитру из globals.css,
  // провайдер — структурные решения (шапка, фаска, полоса оборотов).
  const themeProps = {
    "data-ov-theme": themeId,
    style: accentPulse ? ({ "--ov-accent": accentPulse } as React.CSSProperties) : undefined,
  }

  const renderWidget = (id: WidgetId, standalone = false) => {
    const common = {
      id,
      editMode,
      position: standalone ? { x: 0, y: 0 } : layout[id],
      onMove: moveWidget,
      scale: scales[id] ?? 1,
      onScale: previewScale,
      onScaleCommit: commitScale,
      standalone,
      rev: overlay?.inputs?.rev_lights_pct ?? 0,
    }
    // Содержимое всегда рисуется в коробке БАЗОВОГО размера — её выдаёт сам
    // Widget и он же масштабирует. Раньше здесь стояли width/height, и в
    // нативном окне это давало 100% от уже увеличенного окна, то есть двойное
    // увеличение.
    const full = { width: "100%", height: "100%" } as const
    switch (id) {
      case "hud":
        return (
          <Widget {...common} transparentShell>
            <DashboardHud overlay={overlay} state={state} />
          </Widget>
        )
      case "lap":
        return <Widget {...common}><div style={full}><LapTimer overlay={overlay} /></div></Widget>
      case "tower":
        return <Widget {...common}><div style={full}><TimingTower rows={towerRows} overlay={overlay} /></div></Widget>
      case "inputs":
        return <Widget {...common}><div style={full}><InputTraces inputs={overlay?.inputs} /></div></Widget>
      case "radar":
        return (
          // Радар без соседей — тусклый круг ни о чём: в отдельном окне он
          // просто уходит с экрана, как уже уходил в этом превью.
          <Widget {...common} transparentShell visible={editMode || radarBusy}>
            <div style={full}><TrackRadar contacts={overlay?.radar ?? []} /></div>
          </Widget>
        )
      case "pu":
        return <Widget {...common}><div style={full}><PowerUnit car={overlay?.car} /></div></Widget>
      case "engineer":
        return <Widget {...common}><div style={full}><EngineerPanel overlay={overlay} /></div></Widget>
      case "radio":
        return (
          // Карточка рисует свою поверхность со скруглениями — коробка вокруг
          // неё была бы тёмным прямоугольником поверх игры, ведь карточка ниже
          // окна. В покое окна нет вовсе.
          <Widget {...common} transparentShell visible={showRadio}>
            <div style={full}><RadioPanel state={state} query={query} editMode={editMode} /></div>
          </Widget>
        )
    }
  }

  if (!routeReady) {
    return (
      <main
        id="spotter-overlay-root"
        {...themeProps}
        className="h-screen w-screen bg-transparent"
      />
    )
  }

  // One widget per native window: it fills the window edge to edge, with no
  // chrome of any kind. No <main> background either — the native window is
  // sized to exactly this widget, so any fill that outlives the widget shows up
  // as a grey rectangle over the game.
  if (widgetId) {
    return (
      <OverlayThemeProvider theme={themeId}>
        <main
          id="spotter-overlay-root"
          data-overlay-window={widgetId}
          {...themeProps}
          className={cn(
            "h-screen w-screen overflow-hidden",
            editMode ? "pointer-events-auto" : "pointer-events-none",
          )}
        >
          {renderWidget(widgetId, true)}
        </main>
      </OverlayThemeProvider>
    )
  }

  return (
    <OverlayThemeProvider theme={themeId}>
    <main
      id="spotter-overlay-root"
      {...themeProps}
      className={cn(
        "relative h-screen w-screen overflow-hidden bg-transparent",
        editMode ? "pointer-events-auto" : "pointer-events-none",
      )}
    >
      {!online && (
        <div
          data-overlay-hit
          className="absolute bottom-4 left-1/2 -translate-x-1/2 border px-3 py-1.5 font-mono text-[9px] tracking-[.14em]"
          style={{ backgroundColor: PANEL, borderColor: RED, color: RED }}
        >
          SPOTTER SERVER OFFLINE
        </div>
      )}

      {(["hud", "lap", "tower", "inputs", "pu", "engineer"] as WidgetId[])
        .filter((id) => !disabled.has(id))
        .map((id) => <Fragment key={id}>{renderWidget(id)}</Fragment>)}
      {(editMode || radarBusy) && !disabled.has("radar") && renderWidget("radar")}
      {showRadio && !disabled.has("radio") && renderWidget("radio")}
    </main>
    </OverlayThemeProvider>
  )
}
