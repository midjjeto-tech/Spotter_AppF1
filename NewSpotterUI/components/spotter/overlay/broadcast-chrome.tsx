"use client"

// Визуальный язык игрового оверлея.
//
// Здесь живут ТОЛЬКО примитивы и токены: ни одного обращения к состоянию, ни
// одного знания о виджетах. Причина — виджеты сидят в восьми независимых
// нативных окнах (`core/overlay_window.py::HUD_WIDGETS`), и единственный способ
// удержать их похожими друг на друга — общий набор деталей, а не копипаста
// цветов по файлу.
//
// Цвета приезжают из CSS-переменных `--ov-*`, объявленных блоками
// `[data-ov-theme="..."]` в app/globals.css. Константы ниже — их имена, а не
// значения: так тема меняется одним атрибутом на корне оверлея, без
// прокидывания токенов пропсом в тридцать мест. Структурные отличия тем
// (шапка, фаска, полоса rev-lights) — в lib/overlay-theme.ts.
//
// Про срезанные углы. Раньше их здесь запрещал комментарий: окна оверлея
// непрозрачны (pywebview заливает их `OVERLAY_BACKGROUND` = #0c0c10,
// core/overlay_window.py:115), и в срезе оказалась бы не трасса, а тот же
// тёмный прямоугольник. Запрет снят тем, что заливка панели (`--ov-panel`)
// разведена с заливкой окна на пару шагов: срез показывает фон окна и читается
// как фаска. `backdrop-blur` по-прежнему бессмысленен — за окном нечего
// размывать.

import type { ReactNode } from "react"
import { displayClass, useOverlayTheme } from "@/lib/overlay-theme"

// ─── Токены оформления ─────────────────────────────────────────────────────
// Меняются темой. Значения — в app/globals.css.

export const PANEL = "var(--ov-panel)"
export const PANEL_RAISED = "var(--ov-panel-raised)"
export const ROW_ALT = "var(--ov-row-alt)"
export const DIVIDER = "var(--ov-divider)"
export const LABEL_CLR = "var(--ov-label)"
export const TEXT = "var(--ov-text)"
export const TEXT_BRIGHT = "var(--ov-text-bright)"

/** Акцент оформления: красный у трансляции, янтарь у приборки, цвет канала у
 *  радиочастоты. Это НЕ «опасно» — для опасности есть `DANGER`. */
export const RED = "var(--ov-accent)"
export const ACCENT_INK = "var(--ov-accent-ink)"
export const POS_BG = "var(--ov-pos-bg)"
export const PLAYER_ROW = "var(--ov-player-row)"

// Приборная таблетка (hud) держит свой, более холодный набор — она рисует
// форму, а не панель, и делит палитру с игровым рулевым дисплеем.
export const PILL_BORDER = "var(--ov-pill-border)"
export const PILL_MUTED = "var(--ov-pill-muted)"
export const PILL_INNER = "var(--ov-pill-inner)"
export const RING_BG = "var(--ov-ring-bg)"

/** Кромка панели. Заливки шапки рядом больше нет: с 2026-08-27 подпись живёт
 *  на самой панели, а цвет ушёл в короткий флаг у ведущего края. Токен
 *  `--ov-header-fill` в globals.css оставлен темам, но отсюда не читается —
 *  сплошная цветная плашка на каждом из восьми виджетов и была тем, что
 *  спорило с функциональными цветами в кадре. */
export const HAIRLINE = "var(--ov-hairline)"

// ─── Функциональные цвета ──────────────────────────────────────────────────
// НЕ темизируются НИКОГДА. Это не оформление, а информация: зелёный — газ,
// малиновый — тормоз, фиолетовый — верх шкалы оборотов. Тема, которая их
// перекрашивает, врёт пилоту о состоянии машины.

export const CRIMSON = "#ff1744"
export const GREEN = "#00e676"
export const CYAN = "#00d9ff"
export const AMBER = "#ffca52"
export const PURPLE = "#9b30ff"
export const MGUK = "#41bff3"

/** «Опасно сейчас»: машина борт о борт, заезд в боксы, зона атаки. Красный во
 *  всех темах, включая приборную, где красный больше нигде не встречается —
 *  именно поэтому там он и читается мгновенно. */
export const DANGER = "#e10600"

/** Оттенок отрыва темизируется, смысл — нет: синий отыгрывается, красный
 *  догоняет (см. TimingTower). */
export const GAP_AHEAD = "var(--ov-gap-ahead)"
export const GAP_BEHIND = "var(--ov-gap-behind)"

/** Резервные цвета составов на случай, если бэкенд не прислал `compound_color`
 *  (он приходит из игры и может быть пустым до первого круга). Литералы: это
 *  цвета Pirelli, а не оформление. */
const TYRE_FALLBACK: Record<string, string> = {
  S: "#e10600",
  M: "#f5c518",
  H: "#e8e8e8",
  I: "#43b02a",
  W: "#1e6fd9",
}

/** Последний рубеж — тоже литерал, а не токен: результат склеивается с альфой
 *  в `TyreDisc` (`${color}66`), и `var(--ov-text)66` был бы невалидным CSS,
 *  который браузер молча выбросит. */
const TYRE_UNKNOWN = "#c4c4d4"

export function tyreColor(compound: string | null | undefined, given?: string | null): string {
  return given || TYRE_FALLBACK[(compound ?? "").toUpperCase()] || TYRE_UNKNOWN
}

// ─── Примитивы ─────────────────────────────────────────────────────────────

export function Label({ children, color = LABEL_CLR }: { children: ReactNode; color?: string }) {
  return (
    <span className="font-mono text-[8px] font-semibold uppercase tracking-[.18em]" style={{ color }}>
      {children}
    </span>
  )
}

/**
 * Шапка панели: 2 px цветной кромки + 16 px строки заголовка = ровно 18 px.
 *
 * Высота — согласованный бюджет, а не вкус: окна оверлея фиксированы
 * (`HUD_WIDGETS`), и каждый лишний пиксель шапки отнимается у данных. Полная
 * 28-пиксельная шапка макета съела бы у башни 264×288 десятую часть высоты.
 * Все три темы обязаны укладываться в те же 18 px — меняется рисунок, не бюджет.
 */
export function PanelHeader({
  title,
  right,
  accent = RED,
  variant = "dark",
}: {
  title: string
  right?: ReactNode
  /** Цвет кромки и косого таба. Акцент темы по умолчанию. */
  accent?: string
  /** `red` — заливка акцентом (панель-герой), `dark` — приглушённая. */
  variant?: "dark" | "red"
}) {
  const theme = useOverlayTheme()
  const isHero = variant === "red"

  // Приборка: вместо цветной кромки — тонкая линейка безеля. Заголовок узким
  // гротеском с разрядкой, акцент отдан точке слева. Панель-герой отличается
  // только яркостью подписи: заливать шапку цветом здесь нечем — янтарь в
  // приборной теме означает «внимание», и постоянная янтарная плашка сожгла бы
  // этот сигнал.
  if (theme.header === "bezel") {
    return (
      <header className="shrink-0">
        <div className="h-[2px] w-full" style={{ background: HAIRLINE }} aria-hidden />
        <div
          className="flex h-4 items-center gap-1.5 px-1.5"
          style={{ background: PANEL, borderBottom: `1px solid ${DIVIDER}` }}
        >
          <span
            className="block h-[5px] w-[5px] shrink-0 rounded-full"
            style={{ backgroundColor: isHero ? accent : LABEL_CLR }}
            aria-hidden
          />
          <h2
            className={`${displayClass(theme)} truncate text-[9px] leading-none`}
            style={{ color: isHero ? TEXT_BRIGHT : TEXT }}
          >
            {title}
          </h2>
          {right && <div className="ml-auto flex shrink-0 items-center gap-1.5">{right}</div>}
        </div>
      </header>
    )
  }

  // Радиочастота: шапка — полоса канала. Трёхбуквенный код слева опознаёт
  // виджет так же, как позывной опознаёт говорящего, а кромка ссылается на
  // `--ov-accent`, который на время реплики перебивается цветом канала.
  if (theme.header === "channel") {
    return (
      <header className="shrink-0">
        <div className="h-[2px] w-full" style={{ background: HAIRLINE }} aria-hidden />
        <div className="flex h-4 items-center gap-1.5 px-1.5" style={{ background: PANEL }}>
          <span
            className="shrink-0 px-[3px] font-mono text-[8px] font-bold leading-[10px] tracking-[.1em]"
            style={{ backgroundColor: accent, color: ACCENT_INK }}
          >
            {title.slice(0, 3).toUpperCase()}
          </span>
          <h2
            className={`${displayClass(theme)} truncate text-[9px] leading-none`}
            style={{ color: isHero ? TEXT_BRIGHT : TEXT }}
          >
            {title}
          </h2>
          {right && <div className="ml-auto flex shrink-0 items-center gap-1.5">{right}</div>}
        </div>
      </header>
    )
  }

  // Трансляция: подпись на самой панели, цвет — в КОРОТКОМ флаге у ведущего
  // края, а не в сплошной плашке.
  //
  // Раньше здесь были две заливки во всю ширину: акцентная линейка сверху и
  // `PANEL_RAISED`/`HEADER_FILL` под заголовком. Восемь виджетов давали восемь
  // красных полос поверх трассы, и они спорили с функциональными цветами,
  // которым и положено быть единственными яркими пятнами в кадре
  // (живой заезд 2026-08-27: «выглядит как шляпа из Paint»).
  //
  // Флаг длиной 26 px повторяет форму блока позиции — тот же параллелограмм,
  // только крупнее. Во всю высоту панели его ставить нельзя: `skewX(-13deg)`
  // уводит верхний край на h·tan13°, и на трёхсотпиксельном виджете это
  // семьдесят пикселей поперёк содержимого.
  return (
    <header className="shrink-0">
      <div className="flex h-[2px] w-full" aria-hidden>
        <span className="block w-[26px] shrink-0" style={{ background: accent }} />
        <span className="block flex-1" style={{ background: DIVIDER }} />
      </div>
      <div
        className="flex h-4 items-center gap-1.5 px-1.5"
        style={{ background: PANEL }}
      >
        <span
          className="f1-skew block h-[10px] w-[5px] shrink-0"
          style={{
            backgroundColor: isHero
              ? `color-mix(in srgb, ${ACCENT_INK} 92%, transparent)`
              : accent,
            // Свечение вполсилы: сплошной цвет превращает тонкий таб в кляксу.
            boxShadow: `0 0 6px color-mix(in srgb, ${isHero ? ACCENT_INK : accent} 45%, transparent)`,
          }}
          aria-hidden
        />
        <h2
          className={`${displayClass(theme)} truncate text-[9px] leading-none`}
          style={{ color: isHero ? ACCENT_INK : TEXT }}
        >
          {title}
        </h2>
        {right && <div className="ml-auto flex shrink-0 items-center gap-1.5">{right}</div>}
      </div>
    </header>
  )
}

/** Панель целиком: шапка плюс область данных, ровно по размеру окна. */
export function OverlayPanel({
  title,
  right,
  accent,
  variant,
  children,
}: {
  title: string
  right?: ReactNode
  accent?: string
  variant?: "dark" | "red"
  children: ReactNode
}) {
  return (
    <div className="flex h-full flex-col" style={{ backgroundColor: PANEL }}>
      <PanelHeader title={title} right={right} accent={accent} variant={variant} />
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  )
}

/** Блок номера позиции. У трансляции и радиочастоты — наклонный
 *  параллелограмм, у приборки наклон выключен токеном `--ov-skew`, и блок
 *  вырождается в сегментный номер на прозрачном фоне. */
export function PosBlock({
  pos,
  highlight = false,
}: {
  pos: number | string
  highlight?: boolean
}) {
  return (
    <span
      className="f1-skew flex h-[17px] w-6 shrink-0 items-center justify-center"
      style={{ backgroundColor: highlight ? RED : POS_BG }}
    >
      <span
        className="f1-unskew font-mono text-[11px] font-extrabold tabular-nums"
        style={{ color: highlight ? ACCENT_INK : TEXT_BRIGHT }}
      >
        {pos}
      </span>
    </span>
  )
}

/** Полоса цвета команды со свечением — ею трансляция опознаёт машину быстрее,
 *  чем именем пилота. Цвет приходит из игры, темой не трогается. */
export function TeamEdge({ color, height = 17 }: { color: string; height?: number }) {
  const value = color || "#777"
  return (
    <span
      className="block w-[3px] shrink-0"
      style={{ height, backgroundColor: value, boxShadow: `0 0 6px ${value}aa` }}
      aria-hidden
    />
  )
}

/** Маркер состава в стиле Pirelli: цветное кольцо, тёмный центр, буква. */
export function TyreDisc({
  compound,
  color,
  size = 16,
}: {
  compound: string
  color: string
  size?: number
}) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-mono font-bold leading-none"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.55,
        background: "radial-gradient(circle at 50% 40%, #1a1a1c 0%, #0a0a0b 70%)",
        border: `2px solid ${color}`,
        boxShadow: `inset 0 0 3px ${color}66`,
        color,
      }}
    >
      {compound}
    </span>
  )
}

/** Полоса rev-lights по верхней кромке виджета — сигнатура приборной темы.
 *  Пятнадцать сегментов повторяют шкалу на руле: зелёный, красный, фиолетовый.
 *  Цвета функциональные, темой не трогаются. */
export function RevSpine({ pct }: { pct: number }) {
  const lit = Math.round((Math.max(0, Math.min(100, pct)) / 100) * 15)
  return (
    <div className="flex h-[3px] w-full shrink-0 gap-[1px]" aria-hidden>
      {Array.from({ length: 15 }, (_, index) => (
        <span
          key={index}
          className="h-full flex-1 transition-colors duration-75"
          style={{
            backgroundColor:
              index < lit ? (index < 5 ? "#39d37a" : index < 10 ? CRIMSON : PURPLE) : "#16222e",
          }}
        />
      ))}
    </div>
  )
}
