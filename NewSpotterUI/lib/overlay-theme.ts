"use client"

// Визуальные языки игрового оверлея.
//
// Разделение труда между CSS и TypeScript здесь не косметическое:
//
//   • ЦВЕТА живут в `app/globals.css` блоками `[data-ov-theme="..."]` и
//     приезжают в компоненты через `var(--ov-*)` (см. broadcast-chrome.tsx).
//     Так тема меняется одним атрибутом на корне, без перерисовки дерева и без
//     прокидывания токенов пропсом в тридцать мест.
//   • СТРУКТУРА живёт здесь: полоса rev-lights, вид шапки, фаска угла. Это уже
//     не цвет, а другая разметка, и CSS-переменной её не выразить.
//
// Чего темы НЕ трогают принципиально: цвета составов Pirelli, цвета команд,
// зелёный газ и красный тормоз на трейсах, направление отрыва (синий впереди /
// красный догоняет). Это не оформление, а информация — тема, которая её
// перекрашивает, врёт пилоту. Оттенок отрыва темизируется (`--ov-gap-*`), смысл
// — нет.

import { createContext, createElement, useContext, type ReactNode } from "react"
import type { OverlayThemeId } from "@/lib/api"

export type ThemeChrome = {
  id: OverlayThemeId
  /** Подписи для панели выбора темы на экране «Оверлей». */
  label: string
  hint: string
  /** Вид шапки панели: плашка трансляции, бортовой безель, полоса канала. */
  header: "plate" | "bezel" | "channel"
  /** Шрифт заголовков: трансляционный жирный курсив или узкий гротеск. */
  display: "broadcast" | "condensed"
  /** Фаска нижнего-левого угла панели. Видна потому, что заливка панели и
   *  заливка ОКНА (`OVERLAY_BACKGROUND` = #0c0c10) разведены на пару шагов —
   *  в срезе показывается фон окна и читается как скос, а не как дыра. */
  bevel: boolean
  /** Полоса rev-lights по верхней кромке КАЖДОГО виджета: восемь окон дышат
   *  одним мотором. Питается `overlay.inputs.rev_lights_pct`. */
  revSpine: boolean
  /** Вспышка акцента во всех виджетах разом, когда в эфире новая реплика.
   *  IPC не нужен: все восемь окон опрашивают один `/api/state` с шагом 250 мс
   *  и видят смену `active_message` в одном тике. */
  channelPulse: boolean
}

export const THEMES: Record<OverlayThemeId, ThemeChrome> = {
  broadcast: {
    id: "broadcast",
    label: "Трансляция",
    hint: "Язык телевизионной графики: красная плашка, наклон, зебра строк.",
    header: "plate",
    display: "broadcast",
    bevel: true,
    revSpine: false,
    channelPulse: false,
  },
  cockpit: {
    id: "cockpit",
    label: "Приборка",
    hint: "Не телевизор, а прибор с руля: янтарь и сталь, никакого наклона.",
    header: "bezel",
    display: "condensed",
    bevel: false,
    revSpine: true,
    channelPulse: false,
  },
  radio: {
    id: "radio",
    label: "Радиочастота",
    hint: "Виджеты — каналы одной рации. Акцент вспыхивает, когда идёт эфир.",
    header: "channel",
    display: "broadcast",
    bevel: true,
    revSpine: false,
    channelPulse: true,
  },
}

export const DEFAULT_THEME: OverlayThemeId = "broadcast"

/** Нормализация значения из настроек. Дублирует правило из
 *  `core/settings.py::_OVERLAY_THEMES`: значение приходит через границу
 *  процесса, и неизвестная тема обязана откатить HUD на привычный вид, а не
 *  оставить его без стилей. */
export function resolveThemeId(value: string | null | undefined): OverlayThemeId {
  return value && value in THEMES ? (value as OverlayThemeId) : DEFAULT_THEME
}

/** Класс заголовка. Начертания у двух шрифтов разные настолько, что общий
 *  набор классов с подменой одного семейства дал бы faux-italic у Oswald —
 *  тем же граблям посвящён комментарий в app/layout.tsx. */
export function displayClass(theme: ThemeChrome): string {
  return theme.display === "condensed"
    ? "font-heading font-semibold uppercase tracking-[.22em]"
    : "font-broadcast font-bold uppercase italic tracking-[.16em]"
}

const OverlayThemeContext = createContext<ThemeChrome>(THEMES[DEFAULT_THEME])

export function OverlayThemeProvider({
  theme,
  children,
}: {
  theme: OverlayThemeId
  children: ReactNode
}) {
  return createElement(OverlayThemeContext.Provider, { value: THEMES[theme] }, children)
}

export function useOverlayTheme(): ThemeChrome {
  return useContext(OverlayThemeContext)
}
