"use client"

// Broadcast Radio Card — телевизионная карточка радиопереговоров поверх игры.
//
// Компонент СТРОГО презентационный: он не знает ни про поллинг, ни про
// lifecycle сообщения, ни про таймеры показа. Всё это решает вызывающий и
// передаёт готовую view-модель. Причина в том, что ровно эта логика — «когда
// карточка видна» — и есть самое хрупкое место фичи (критерии готовности 1, 7,
// 8), и держать её в одном месте важнее, чем сэкономить на пропсах.
//
// Ни одного имени персонажа и ни одной роли здесь нет: они приходят из
// `core/radio/speakers.py`. Захардкодить их в компоненте прямо запрещено
// (ТЗ §5) — персонажей меняют конфигурацией, а не пересборкой UI.

import { useEffect, useRef, useState } from "react"
import { Headphones, Mic } from "lucide-react"
import type { RadioSource, RadioUrgency } from "@/lib/api"
import {
  CARD,
  MOTION,
  RADIO_SURFACE,
  URGENCY_LABEL,
  URGENCY_MARK,
  accentFor,
} from "@/lib/radio-ui"
import { cn } from "@/lib/utils"

export type RadioCardView = {
  channel: RadioSource
  urgency: RadioUrgency
  speakerName: string
  speakerRole: string
  initials: string
  portraitUrl: string | null
  /** Акцент от бэкенда; критическая срочность его перебивает. */
  accent: string | null
  text: string
  /** Идёт реальное воспроизведение: бейдж LIVE и работающая осциллограмма.
   *  На `synthesizing` и на PTT-ожидании ДОЛЖЕН быть false — ложный LIVE
   *  говорит пилоту, что он что-то пропустил (ТЗ §8). */
  live: boolean
  /** Подпись вместо LIVE: «ПРОВЕРЯЮ ДАННЫЕ», «СЛУШАЮ», «РАСПОЗНАЮ». */
  status?: string | null
  /** Реплика пилота мелкой строкой над ответом (ТЗ §14). */
  question?: string | null
  /** Компактный однострочный вариант споттера (ТЗ §13). */
  compact?: boolean
  /** Карточка уходит: включает выездную анимацию. */
  exiting?: boolean
  /** Прерванная реплика убирается заметно быстрее обычной. */
  interrupted?: boolean
  showPortrait?: boolean
  textPx: number
  scale: number
  /** Переопределение ширины. В игровом оверлее карточка живёт в НАТИВНОМ окне
   *  фиксированного размера (`core/overlay_window.py::HUD_WIDGETS`), и `vw`
   *  там считался бы от окна, а не от экрана — то есть clamp дал бы минимум.
   *  Поэтому в оверлее передаётся "100%", а clamp из `CARD.width` работает
   *  там, где вьюпорт настоящий: в одностраничном preview и на экране
   *  «Рация». */
  width?: string
}

/** Уважать системную настройку «меньше движения» (ТЗ §19).
 *
 *  Слушаем изменение, а не читаем один раз: пользователь может включить режим,
 *  не перезапуская игру, и карточка обязана перестать ездить сразу. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const query = window.matchMedia("(prefers-reduced-motion: reduce)")
    const apply = () => setReduced(query.matches)
    apply()
    query.addEventListener("change", apply)
    return () => query.removeEventListener("change", apply)
  }, [])
  return reduced
}

function Portrait({
  url,
  initials,
  accent,
  size,
}: {
  url: string | null
  initials: string
  accent: string
  size: number
}) {
  // Портрет необязателен (ТЗ §5). Файла может не быть вовсе — тогда 404 и
  // инициалы. Ошибку загрузки держим в состоянии, иначе React пытался бы
  // показать битую картинку на каждом ререндере.
  const [broken, setBroken] = useState(false)
  useEffect(() => setBroken(false), [url])

  const showImage = Boolean(url) && !broken
  return (
    <div
      className="relative shrink-0 overflow-hidden"
      style={{ width: size, height: size, backgroundColor: RADIO_SURFACE.bgSecondary }}
    >
      {showImage ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- локальный
              файл с фиксированным размером; next/image здесь дал бы лишний
              рантайм в оверлее и ничего не оптимизировал. */}
          <img
            src={url as string}
            alt=""
            width={size}
            height={size}
            onError={() => setBroken(true)}
            className="h-full w-full object-cover"
          />
          {/* Нижний градиент вживляет портрет в панель — иначе он выглядит
              наклейкой поверх карточки. */}
          <span
            aria-hidden
            className="absolute inset-x-0 bottom-0 h-1/3"
            style={{ background: `linear-gradient(to top, ${RADIO_SURFACE.bg}, transparent)` }}
          />
        </>
      ) : (
        <span
          className="flex h-full w-full items-center justify-center font-heading font-black"
          style={{ color: accent, fontSize: Math.round(size / 2.6) }}
        >
          {initials || "?"}
        </span>
      )}
    </div>
  )
}

function Waveform({ live, accent, reduced }: { live: boolean; accent: string; reduced: boolean }) {
  // Осциллограмма — индикатор, а не анализ звука: FFT в React запрещён (§20),
  // и он ничего не добавил бы. Псевдослучайные высоты со сдвигом фазы читаются
  // как речь, стоят один CSS-класс и не трогают состояние бэкенда.
  if (!live) return null
  return (
    <div className="flex h-5 items-center gap-[2px]" aria-hidden="true">
      {Array.from({ length: 5 }, (_, index) => (
        <span
          key={index}
          className={cn("w-[2px] rounded-full", !reduced && "overlay-wave-bar")}
          style={{
            height: `${8 + ((index * 7) % 11)}px`,
            backgroundColor: accent,
            animationDelay: `${index * -90}ms`,
          }}
        />
      ))}
    </div>
  )
}

export function BroadcastRadioCard({ view }: { view: RadioCardView }) {
  const reduced = useReducedMotion()
  const accent = accentFor(view.channel, view.urgency, view.accent)
  const critical = view.urgency === "critical"
  const mark = URGENCY_MARK[view.urgency]
  const compact = Boolean(view.compact)

  // Появление: карточка въезжает один раз на монтировании. Второй кадр нужен,
  // чтобы браузер успел зафиксировать начальное состояние — без него переход
  // не проигрывается вовсе.
  const [shown, setShown] = useState(false)
  const frame = useRef<number | undefined>(undefined)
  useEffect(() => {
    frame.current = window.requestAnimationFrame(() => setShown(true))
    return () => {
      if (frame.current !== undefined) window.cancelAnimationFrame(frame.current)
    }
  }, [])

  const visible = shown && !view.exiting
  const exitMs = view.interrupted ? MOTION.interruptedExitMs : MOTION.exitMs
  const shift = view.exiting ? MOTION.exitShiftPx : MOTION.enterShiftPx

  const motionStyle = reduced
    ? { opacity: visible ? 1 : 0, transition: "none" }
    : {
        opacity: visible ? 1 : 0,
        transform: `translateY(${visible ? 0 : shift}px)`,
        transition: `opacity ${view.exiting ? exitMs : MOTION.enterMs}ms ease-out,`
          + ` transform ${view.exiting ? exitMs : MOTION.enterMs}ms ease-out`,
      }

  const portraitSize = Math.round(CARD.portrait * view.scale)
  const showPortrait = view.showPortrait !== false && !compact

  return (
    <div
      // Один короткий pulse на появлении критической реплики и ничего больше:
      // постоянное мигание поверх гонки — это то, что ТЗ §7 прямо запрещает.
      className={cn("flex overflow-hidden", critical && !reduced && "animate-in fade-in")}
      style={{
        width: view.width ?? (compact ? CARD.compactWidth : CARD.width),
        minHeight: (compact ? CARD.compactMinHeight : CARD.minHeight) * view.scale,
        backgroundColor: RADIO_SURFACE.bg,
        border: `1px solid ${critical ? accent : RADIO_SURFACE.border}`,
        borderRadius: RADIO_SURFACE.radius,
        boxShadow: RADIO_SURFACE.shadow,
        ...motionStyle,
      }}
      role="status"
      aria-live={critical ? "assertive" : "polite"}
    >
      {/* Акцентная полоса. Ширина ФИКСИРОВАНА: меняется только цвет, иначе
          критическая реплика сдвигала бы текст (критерий 4 — заметно, но без
          перекомпоновки). */}
      <span
        aria-hidden
        className="shrink-0 transition-colors duration-200"
        style={{
          width: CARD.railWidth,
          backgroundColor: accent,
          boxShadow: critical ? `0 0 10px ${accent}` : undefined,
        }}
      />

      {showPortrait && (
        <Portrait url={view.portraitUrl} initials={view.initials}
                  accent={accent} size={portraitSize} />
      )}

      <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {compact && (
            <Headphones className="h-3.5 w-3.5 shrink-0" style={{ color: accent }} aria-hidden />
          )}
          {view.live ? (
            <span
              className="font-broadcast shrink-0 rounded-[3px] px-1.5 py-[1px] text-[10px] font-black italic tracking-[.14em]"
              style={{ backgroundColor: accent, color: "#0b0d10" }}
            >
              LIVE
            </span>
          ) : view.status ? (
            <span className="font-mono shrink-0 text-[10px] tracking-[.12em]"
                  style={{ color: RADIO_SURFACE.muted }}>
              {view.status}
            </span>
          ) : null}

          <span
            // Роль латиницей приходит из core/radio/speakers.py — курсивный
            // капс роднит карточку с остальными панелями оверлея. Имя ниже
            // остаётся на --font-heading: оно кириллическое, а у Titillium
            // кириллицы нет.
            className="font-broadcast truncate text-[11px] font-bold italic tracking-[.12em]"
            style={{ color: RADIO_SURFACE.muted }}
          >
            {view.speakerRole}
          </span>

          {/* Срочность обозначена НЕ ТОЛЬКО цветом (ТЗ §19): рядом с ролью
              стоит текстовая метка, читаемая и в оттенках серого. */}
          {mark && (
            <span
              className="font-heading shrink-0 text-[10px] font-black tracking-[.1em]"
              style={{ color: accent }}
              title={URGENCY_LABEL[view.urgency]}
            >
              {mark} {URGENCY_LABEL[view.urgency]}
            </span>
          )}

          <span className="ml-auto shrink-0">
            <Waveform live={view.live} accent={accent} reduced={reduced} />
          </span>
        </div>

        {!compact && (
          <div
            className="font-heading truncate text-[13px] font-black uppercase tracking-[.08em]"
            style={{ color: RADIO_SURFACE.text }}
          >
            {view.speakerName}
          </div>
        )}

        {view.question && (
          <p className="truncate font-mono text-[10px]" style={{ color: RADIO_SURFACE.muted }}>
            <Mic className="mr-1 inline h-3 w-3" aria-hidden />
            {view.question}
          </p>
        )}

        {view.text && (
          <p
            className="min-w-0 font-semibold"
            style={{
              color: RADIO_SURFACE.text,
              fontSize: view.textPx,
              lineHeight: 1.25,
              // Ровно три строки и аккуратное обрезание. Marquee запрещён
              // (ТЗ §6): бегущая строка на трассе нечитаема, а уменьшать кегль
              // до нечитаемого нельзя — минимум 14px держит `textSizePx`.
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: compact ? 1 : CARD.maxTextLines,
              overflow: "hidden",
            }}
          >
            {view.text}
          </p>
        )}
      </div>
    </div>
  )
}
