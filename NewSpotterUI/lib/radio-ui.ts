// Оформление и тайминги радио-карточки — один источник для игрового оверлея и
// экрана «Рация».
//
// Почему отдельный файл. Значения ниже подбираются на реальной гонке, а не
// выводятся из кода: сколько секунд держать реплику споттера, за сколько
// миллисекунд она уходит, какой ширины акцентная полоса. Пока они лежали
// инлайном в JSX, каждая калибровка требовала вычитывать компонент целиком, и
// два места показа успели разойтись. ТЗ §9 прямо требует вынести интервалы в
// разделяемые константы.
//
// Цвета каналов дублируют `core/radio/speakers.py`: бэкенд отдаёт `accent`
// вместе с сообщением и он главнее, а эти значения — фолбэк для preview и для
// строк истории, пришедших без профиля.

import type { RadioSource, RadioUrgency } from "@/lib/api"

// ── Поверхность карточки (ТЗ §7) ────────────────────────────────────────────
// Панель почти непрозрачная и без glassmorphism намеренно: карточка лежит
// поверх движущейся картинки гонки, и полупрозрачный фон делает текст
// нечитаемым ровно тогда, когда он нужен — на светлой трассе в повороте.
// Значения — `var()` с фолбэком, а не голые токены темы, и это существенно:
// карточку показывает не только игровой оверлей, но и экран «Рация», где
// никакого `[data-ov-theme]` над ней нет. Фолбэк — ровно прежние цвета, поэтому
// вне оверлея карточка выглядит как раньше, а внутри следует за темой.
export const RADIO_SURFACE = {
  bg: "var(--ov-card-bg, rgba(18, 20, 24, 0.96))",
  bgSecondary: "var(--ov-card-bg-2, rgba(29, 32, 37, 0.96))",
  border: "var(--ov-card-border, rgba(255, 255, 255, 0.10))",
  text: "rgba(255, 255, 255, 0.96)",
  muted: "rgba(255, 255, 255, 0.62)",
  /** Тень только чтобы отделить панель от картинки, не для объёма. */
  shadow: "0 6px 24px rgba(0, 0, 0, 0.45)",
  /** Строка, а не число: значение уходит в `borderRadius` как есть, и приборной
   *  теме нужен почти прямой угол — прибор не скругляют. */
  radius: "var(--ov-card-radius, 10px)",
} as const

// ── Акценты каналов (ТЗ §7) ─────────────────────────────────────────────────
export const CHANNEL_ACCENT: Record<RadioSource, string> = {
  engineer: "#e32636",
  spotter: "#f4b942",
  commentator: "#39c5d4",
  driver: "#c8ced6",
}

/** Критическая срочность перебивает акцент канала: красный здесь означает
 *  «требуется действие сейчас», а не «говорит инженер». */
export const CRITICAL_ACCENT = "#ff2b3d"

export function accentFor(
  channel: RadioSource | undefined,
  urgency: RadioUrgency | undefined,
  fromBackend?: string | null,
): string {
  if (urgency === "critical") return CRITICAL_ACCENT
  if (fromBackend) return fromBackend
  return CHANNEL_ACCENT[channel ?? "engineer"] ?? CHANNEL_ACCENT.engineer
}

// ── Срочность ───────────────────────────────────────────────────────────────
// ТЗ §19: на цвет полагаться нельзя. У high и critical есть текстовая метка,
// поэтому карточка остаётся читаемой и при дальтонизме, и на скриншоте в
// оттенках серого.
export const URGENCY_MARK: Record<RadioUrgency, string | null> = {
  critical: "!",
  high: "•",
  normal: null,
  low: null,
}

export const URGENCY_LABEL: Record<RadioUrgency, string> = {
  critical: "СРОЧНО",
  high: "ВАЖНО",
  normal: "",
  low: "",
}

// ── Габариты (ТЗ §6) ────────────────────────────────────────────────────────
// clamp вместо фиксированных пикселей: одно и то же значение должно работать и
// на 1280×720, где 480px заняли бы треть экрана, и на 2560×1440, где 330px
// выглядели бы подписью.
export const CARD = {
  width: "clamp(330px, 32vw, 480px)",
  /** Компактный вариант споттера — одна строка, портрет скрыт (ТЗ §13). */
  compactWidth: "clamp(220px, 20vw, 320px)",
  minHeight: 96,
  compactMinHeight: 56,
  bottom: "clamp(64px, 8vh, 110px)",
  /** Акцентная полоса. Ширина ФИКСИРОВАНА и не зависит от срочности —
   *  меняется только цвет, иначе critical сдвигал бы текст (ТЗ §7, §23). */
  railWidth: 4,
  portrait: 80,
  maxTextLines: 3,
} as const

// ── Движение (ТЗ §8) ────────────────────────────────────────────────────────
export const MOTION = {
  enterMs: 160,
  exitMs: 200,
  /** Прерванная реплика уходит заметно быстрее обычной: текст, которого пилот
   *  уже не слышит, не должен висеть перед глазами. */
  interruptedExitMs: 130,
  enterShiftPx: 10,
  exitShiftPx: 6,
} as const

// ── Сколько держать карточку после завершения речи (ТЗ §9) ──────────────────
// Реплику ещё дочитывают после того, как звук кончился. Значения — нижняя
// граница вилок ТЗ плюс запас на чтение кириллицы.
export const LINGER_MS = {
  spotter: 1_300,
  engineer: 2_400,
  engineerCritical: 3_500,
  commentator: 2_500,
  pttAnswer: 5_000,
  /** Пока пилот говорит и ждёт ответа — держим, ответ придёт следом. */
  pttBusy: 60_000,
} as const

/** Сколько держать конкретную завершившуюся реплику.
 *
 *  `scale` — пользовательская настройка `radio_card_duration`; клипуется
 *  здесь, а не в вызывающем, чтобы битое значение из settings.json не
 *  оставило карточку на экране навсегда. */
export function lingerMs(
  channel: RadioSource | undefined,
  urgency: RadioUrgency | undefined,
  { isPttAnswer = false, scale = 1 }: { isPttAnswer?: boolean; scale?: number } = {},
): number {
  const base = isPttAnswer
    ? LINGER_MS.pttAnswer
    : channel === "spotter"
      ? LINGER_MS.spotter
      : channel === "commentator"
        ? LINGER_MS.commentator
        : urgency === "critical"
          ? LINGER_MS.engineerCritical
          : LINGER_MS.engineer
  const safe = Number.isFinite(scale) ? Math.min(2, Math.max(0.5, scale)) : 1
  return Math.round(base * safe)
}

// ── Пользовательский масштаб ────────────────────────────────────────────────
export const SCALE_RANGE = { min: 0.8, max: 1.4 } as const

export function clampScale(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value)
  if (!Number.isFinite(n)) return 1
  return Math.min(SCALE_RANGE.max, Math.max(SCALE_RANGE.min, n))
}

/** Кегль основного текста. 16–18px на 1080p по ТЗ §6; ниже 14px не опускаемся
 *  ни при каком масштабе — это требование доступности (§19), а не вкус. */
export const TEXT_SIZE: Record<string, number> = { s: 15, m: 17, l: 19 }

export function textSizePx(size: unknown, scale = 1): number {
  const base = TEXT_SIZE[typeof size === "string" ? size : "m"] ?? TEXT_SIZE.m
  return Math.max(14, Math.round(base * scale))
}

// ── Состояния, при которых карточка вообще видна (ТЗ §9) ────────────────────
// `queued` и `cancelled` здесь отсутствуют СОЗНАТЕЛЬНО: показать сообщение,
// которое ещё не звучит или уже не прозвучит, значит соврать пилоту о том, что
// он слышал. Это критерии готовности 1 и 8.
export const VISIBLE_STATES = new Set(["playing", "completed", "interrupted"])

/** `synthesizing` показывается ТОЛЬКО в PTT-диалоге, где пилот явно ждёт
 *  ответа, и без бейджа LIVE (ТЗ §8). */
export const PTT_BUSY_STATES = new Set(["listening", "recognizing", "thinking"])
