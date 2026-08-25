"use client"

/**
 * Радиопульт — телефон рядом с рулём (`/phone.html?token=…`).
 *
 * Отдельный экран, а НЕ десктопный UI на узком стекле. Замер живого DOM при
 * 375px показал, почему: сайдбар `w-60` не сжимается, и на контент оставалось
 * 87 пикселей. Но дело не только в вёрстке — за рулём не нужны «Настройки»,
 * «Логи», хоткеи и разметка оверлея. Телефон решает другую задачу: даёт
 * большую кнопку вызова инженера без клавиатуры, показывает одну команду на
 * текущий круг и только те факты, по которым пилот принимает решение.
 *
 * Данные — существующие ручки `/api/overlay` и `/api/state`, новых не заводим:
 * `core/overlay.py::build_overlay_state` уже собирает ровно этот срез, включая
 * `relative` с НАКОПЛЕННЫМ гэпом до каждой машины (а не гэпом до соседа).
 */

import { useEffect, useState } from "react"
import { Gauge, Mic, Rows3 } from "lucide-react"
import {
  askVoice,
  getOverlay,
  getState,
  type OverlayState,
  type SpotterState,
  type VoiceQuery,
} from "@/lib/api"
import { cn } from "@/lib/utils"

/** Опрос: 500 мс.
 *
 *  Игровой оверлей на той же машине ходит раз в 250 мс, но здесь между
 *  клиентом и сервером Wi-Fi и телефонная батарея, а взгляд на второй экран
 *  бросают между поворотами, а не покадрово. Цепочка `setTimeout`, а не
 *  `setInterval` — чтобы запросы не накладывались, когда сеть подвисла
 *  (тот же приём, что в `lib/use-spotter-state.ts`). */
const POLL_MS = 500
type PhoneSection = "race" | "radio" | "timing"

function usePhoneFeed() {
  const [overlay, setOverlay] = useState<OverlayState | null>(null)
  const [state, setState] = useState<SpotterState | null>(null)
  const [online, setOnline] = useState(false)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const [nextState, nextOverlay] = await Promise.all([getState(), getOverlay()])
        if (!alive) return
        setState(nextState)
        setOverlay(nextOverlay)
        setOnline(true)
      } catch {
        // Приложение закрыли, Wi-Fi отвалился, токен протух — для телефона это
        // одно и то же: связи нет. Молча показывать прошлый снимок нельзя, за
        // рулём его примут за живой.
        if (alive) setOnline(false)
      } finally {
        if (alive) timer = setTimeout(tick, POLL_MS)
      }
    }

    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [])

  return { overlay, state, online }
}

export function PhoneView() {
  const { overlay, state, online } = usePhoneFeed()
  const connected = Boolean(state?.connected)
  const [section, setSection] = useState<PhoneSection>("race")

  const openSection = (next: PhoneSection) => {
    setSection(next)
    window.scrollTo(0, 0)
  }

  return (
    <div className="min-h-dvh overscroll-y-contain bg-background text-foreground">
      <Header overlay={overlay} online={online} connected={connected} />

      <main
        className="flex flex-col gap-3 px-3 pt-3"
        style={{ paddingBottom: "calc(5.75rem + env(safe-area-inset-bottom))" }}
      >
        {!online && <Notice tone="bad" text="Нет связи с приложением на ПК" />}
        {online && !connected && (
          <Notice tone="warn" text="Телеметрия не идёт — запусти заезд в игре" />
        )}

        {section === "race" && (
          <section role="tabpanel" aria-label="Гонка" className="flex flex-col gap-3">
            <RaceCall overlay={overlay} connected={connected} />
            <DecisionStrip overlay={overlay} />
            <EngineerPulse state={state} onOpenRadio={() => openSection("radio")} />
          </section>
        )}

        {section === "radio" && (
          <section role="tabpanel" aria-label="Рация" className="flex flex-col gap-3">
            <RadioRemote state={state} online={online} connected={connected} />
            <Events state={state} />
            <PhoneNote />
          </section>
        )}

        {section === "timing" && (
          <section role="tabpanel" aria-label="Тайминг" className="flex flex-col gap-3">
            <Tower rows={overlay?.relative ?? []} />
          </section>
        )}
      </main>

      <PhoneNav active={section} onChange={openSection} />
    </div>
  )
}

function PhoneNav({ active, onChange }: {
  active: PhoneSection
  onChange: (section: PhoneSection) => void
}) {
  const items = [
    { id: "race" as const, label: "Гонка", Icon: Gauge },
    { id: "radio" as const, label: "Рация", Icon: Mic },
    { id: "timing" as const, label: "Тайминг", Icon: Rows3 },
  ]

  return (
    <nav
      aria-label="Разделы радиопульта"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-card/95 px-2 pt-2 shadow-[0_-12px_32px_rgba(0,0,0,0.35)] backdrop-blur"
      style={{ paddingBottom: "max(.5rem, env(safe-area-inset-bottom))" }}
    >
      <div role="tablist" className="mx-auto grid max-w-lg grid-cols-3 gap-2">
        {items.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active === id}
            onClick={() => onChange(id)}
            className={cn(
              "flex min-h-14 touch-manipulation flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-semibold transition-colors",
              active === id
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground active:bg-secondary active:text-foreground",
            )}
          >
            <Icon className="h-5 w-5" aria-hidden />
            {label}
          </button>
        ))}
      </div>
    </nav>
  )
}

// ── Команда на круг ─────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  pit: "БОКСЫ ЭТОТ КРУГ",
  push: "АТАКУЙ",
  save: "ЭКОНОМЬ",
  hold: "ДЕРЖИ ТЕМП",
}

function RaceCall({ overlay, connected }: { overlay: OverlayState | null; connected: boolean }) {
  const action = overlay?.strategy.action ?? "hold"
  const isPit = action === "pit"
  const label = connected ? (ACTION_LABELS[action] ?? action.toUpperCase()) : "ЖДЁМ ЗАЕЗД"
  const advice = overlay?.strategy.advice ?? overlay?.situation.advice
  const confidence = overlay?.strategy.confidence ?? 0

  return (
    <section className={cn(
      "overflow-hidden rounded-xl border",
      isPit
        ? "border-destructive/70 bg-destructive/15"
        : "border-primary/50 bg-primary/10",
    )}>
      <div className="flex items-center justify-between border-b border-current/15 px-3 py-2">
        <span className="label-mono text-[11px] text-muted-foreground">КОМАНДА НА КРУГ</span>
        {confidence > 0 && (
          <span className="font-mono text-[11px] text-muted-foreground tabular">
            {Math.round(confidence * 100)}%
          </span>
        )}
      </div>
      <div className="px-4 py-4">
        <p className={cn(
          "font-heading text-3xl font-black uppercase leading-none tracking-tight",
          isPit ? "text-destructive" : "text-primary",
        )}>
          {label}
        </p>
        <p className="mt-2 text-base font-medium leading-snug text-foreground">
          {connected
            ? (advice || "Инженер следит за темпом и ждёт достоверных данных")
            : "Команда появится после подключения телеметрии"}
        </p>
        {overlay?.situation.threat && (
          <p className="mt-3 border-l-2 border-warning pl-3 text-sm leading-snug text-warning">
            {overlay.situation.threat}
          </p>
        )}
      </div>
    </section>
  )
}

// ── Радиопульт ──────────────────────────────────────────────────────────────

const VOICE_PROGRESS: Partial<Record<VoiceQuery["status"], string>> = {
  listening: "ГОВОРИ — МИКРОФОН НА ПК СЛУШАЕТ",
  recognizing: "РАСПОЗНАЮ…",
  thinking: "ИНЖЕНЕР ПРОВЕРЯЕТ ДАННЫЕ…",
}

function RadioRemote({ state, online, connected }: {
  state: SpotterState | null
  online: boolean
  connected: boolean
}) {
  const query = state?.voice_query ?? null
  const busy = query?.status === "listening"
    || query?.status === "recognizing"
    || query?.status === "thinking"
  const unavailable = !online || !connected
  const disabled = unavailable || busy
  const [requestError, setRequestError] = useState<string | null>(null)

  const requestEngineer = async () => {
    if (disabled) return
    setRequestError(null)
    try {
      const result = await askVoice()
      if (!result.ok) {
        setRequestError(result.busy
          ? "Инженер уже обрабатывает запрос"
          : "Не удалось включить микрофон на ПК")
      }
    } catch {
      setRequestError("Радиопульт потерял связь с приложением")
    }
  }

  const buttonLabel = unavailable
    ? "ЖДЁМ ЗАЕЗД"
    : busy && query
      ? VOICE_PROGRESS[query.status]
      : "СПРОСИТЬ ИНЖЕНЕРА"
  const lastEngineerLine = state?.radio?.active_message?.text?.trim()
    || state?.radio_message?.text?.trim()

  return (
    <Card label="Радиопульт">
      <div className="p-3">
        <button
          type="button"
          onClick={() => { void requestEngineer() }}
          disabled={disabled}
          className={cn(
            "flex min-h-20 w-full touch-manipulation select-none items-center justify-center rounded-xl px-4 text-center font-heading text-lg font-black tracking-wide transition-colors",
            unavailable
              ? "cursor-not-allowed bg-secondary/60 text-muted-foreground"
              : busy
                ? "cursor-wait bg-warning/15 text-warning"
                : "bg-primary text-primary-foreground active:bg-primary/75",
          )}
        >
          {buttonLabel}
        </button>
        <p className="mt-2 text-center text-[11px] leading-snug text-muted-foreground">
          Нажми один раз и говори в микрофон компьютера
        </p>

        {(requestError || query?.status === "error") && (
          <p className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {requestError || query?.error || "Запрос не выполнен"}
          </p>
        )}

        {query?.question && (
          <div className="mt-3 rounded-lg bg-secondary/50 px-3 py-2.5">
            <p className="label-mono text-[10px] text-muted-foreground">ТЫ СПРОСИЛ</p>
            <p className="mt-1 text-sm leading-snug text-foreground">{query.question}</p>
            {query.answer && (
              <>
                <p className="mt-3 label-mono text-[10px] text-primary">ОТВЕТ ИНЖЕНЕРА</p>
                <p className="mt-1 text-base font-medium leading-snug text-foreground">
                  {query.answer}
                </p>
              </>
            )}
          </div>
        )}

        {!query?.question && lastEngineerLine && (
          <div className="mt-3 border-l-2 border-primary pl-3">
            <p className="label-mono text-[10px] text-muted-foreground">ПОСЛЕДНЯЯ КОМАНДА</p>
            <p className="mt-1 text-sm leading-snug text-foreground">{lastEngineerLine}</p>
          </div>
        )}
      </div>
    </Card>
  )
}

function EngineerPulse({ state, onOpenRadio }: {
  state: SpotterState | null
  onOpenRadio: () => void
}) {
  const last = state?.radio?.active_message?.text?.trim()
    || state?.radio_message?.text?.trim()

  return (
    <button
      type="button"
      onClick={onOpenRadio}
      className="flex min-h-20 w-full touch-manipulation items-center gap-3 rounded-xl border border-border bg-card px-3 py-3 text-left active:bg-secondary/60"
    >
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
        <Mic className="h-5 w-5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="label-mono block text-[10px] text-muted-foreground">
          ПОСЛЕДНЯЯ КОМАНДА · ОТКРЫТЬ РАЦИЮ
        </span>
        <span className="mt-1 line-clamp-2 block text-sm font-medium leading-snug text-foreground">
          {last || "Инженер пока молчит"}
        </span>
      </span>
      <span className="text-xl text-muted-foreground" aria-hidden>›</span>
    </button>
  )
}

function PhoneNote() {
  return (
    <p className="px-1 pt-1 text-[11px] leading-relaxed text-muted-foreground">
      Кнопка включает микрофон на ПК, где запущен Spotter. Экран телефона
      может гаснуть сам: запрет на засыпание браузер даёт только по HTTPS,
      а радиопульт работает по HTTP в локальной сети.
    </p>
  )
}

// ── Шапка ────────────────────────────────────────────────────────────────────

function Header({ overlay, online, connected }: {
  overlay: OverlayState | null
  online: boolean
  connected: boolean
}) {
  const lap = overlay?.lap_current
  const total = overlay?.lap_total
  return (
    <header
      className="sticky top-0 z-10 flex items-center gap-4 border-b border-border bg-card px-4 pb-3"
      style={{ paddingTop: "calc(.75rem + env(safe-area-inset-top))" }}
    >
      <div className="flex items-baseline gap-1.5">
        <span className="label-mono text-xs text-muted-foreground">P</span>
        <span className="font-heading text-4xl font-bold leading-none tabular">
          {overlay?.position ?? "—"}
        </span>
      </div>

      <div className="flex flex-col leading-tight">
        <span className="label-mono text-[11px] text-muted-foreground">КРУГ</span>
        <span className="font-mono text-lg leading-none tabular">
          {lap ?? "—"}
          {total ? <span className="text-muted-foreground">/{total}</span> : null}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span
          className={cn("h-2.5 w-2.5 rounded-full",
            !online ? "bg-destructive" : connected ? "bg-success" : "bg-warning")}
        />
        <span className="label-mono text-[11px] text-muted-foreground">
          {!online ? "НЕТ СВЯЗИ" : connected ? "ЭФИР" : "ЖДЁМ"}
        </span>
      </div>
    </header>
  )
}

function Notice({ tone, text }: { tone: "bad" | "warn"; text: string }) {
  return (
    <p className={cn(
      "rounded-lg border px-3 py-2.5 text-sm leading-snug",
      tone === "bad"
        ? "border-destructive/40 bg-destructive/10 text-destructive"
        : "border-warning/40 bg-warning/10 text-warning")}
    >
      {text}
    </p>
  )
}

// ── Таймингборд ──────────────────────────────────────────────────────────────

function Tower({ rows }: { rows: OverlayState["relative"] }) {
  if (rows.length === 0) {
    return (
      <Card label="Таймингборд">
        <Empty text="Появится, как только пойдёт круг" />
      </Card>
    )
  }
  return (
    <Card label="Таймингборд">
      <ul className="flex flex-col">
        {rows.map((row) => (
          <li
            key={row.vehicle_idx}
            className={cn(
              // 56px: строка обязана оставаться читаемой боковым зрением и
              // попадаемой пальцем в перчатке.
              "flex h-14 items-center gap-3 border-t border-border/60 px-3 first:border-t-0",
              row.ahead === null && "bg-primary/10")}
          >
            <span className="w-6 shrink-0 font-mono text-sm text-muted-foreground tabular">
              {row.position}
            </span>
            <span
              className="h-7 w-1 shrink-0 rounded-full"
              style={{ backgroundColor: row.color }}
            />
            <span className={cn("min-w-0 flex-1 truncate text-base",
              row.ahead === null ? "font-semibold text-foreground" : "text-foreground/90")}
            >
              {row.driver}
            </span>
            <span className={cn("shrink-0 font-mono text-lg tabular",
              row.ahead === null
                ? "text-primary"
                : row.ahead
                  ? "text-foreground"
                  : "text-muted-foreground")}
            >
              {/* У своей строки гэпа нет — там `—`, а не «0.000»: ноль читался
                  бы как «догнал сам себя». */}
              {row.gap_to_player_str}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ── Факты для решения ───────────────────────────────────────────────────────

function DecisionStrip({ overlay }: { overlay: OverlayState | null }) {
  const tyre = overlay?.tyre
  const car = overlay?.car
  const fuel = car?.fuel_delta_laps
  const ahead = [...(overlay?.relative ?? [])].reverse().find((row) => row.ahead === true)
  const behind = (overlay?.relative ?? []).find((row) => row.ahead === false)

  return (
    <Card label="Что решает круг">
      <div className="grid grid-cols-2 gap-px bg-border/60">
        <Tile label="ЦЕЛЬ ВПЕРЕДИ">
          <Opponent row={ahead} />
        </Tile>

        <Tile label="УГРОЗА СЗАДИ">
          <Opponent row={behind} />
        </Tile>

        <Tile label="ШИНЫ">
          <span className="flex items-baseline gap-2">
            <span
              className="font-heading text-2xl font-bold leading-none"
              style={tyre?.compound_color ? { color: tyre.compound_color } : undefined}
            >
              {tyre?.compound && tyre.compound !== "?" ? tyre.compound : "—"}
            </span>
            {tyre?.age_laps != null && (
              <span className="font-mono text-sm text-muted-foreground tabular">
                {tyre.age_laps} кр.
              </span>
            )}
          </span>
          {tyre?.wear_pct != null && (
            <span className={cn(
              "font-mono text-xs tabular",
              tyre.wear_pct >= 70 ? "text-warning" : "text-muted-foreground",
            )}>
              износ {Math.round(tyre.wear_pct)}%
            </span>
          )}
        </Tile>

        <Tile label="РЕСУРСЫ">
          {/* Не килограммы, а запас в КРУГАХ относительно дистанции: за рулём
              решение принимают по нему, а перевод из кг в круги в уме —
              лишняя работа. Минус = не хватает. */}
          <span className="flex items-baseline justify-between gap-2">
            <Value
              text={fuel != null ? `${fuel > 0 ? "+" : ""}${fuel.toFixed(1)} кр.` : "—"}
              tone={fuel != null && fuel < 0 ? "bad" : "plain"}
            />
            <span className={cn(
              "whitespace-nowrap font-mono text-sm tabular",
              car?.ers_percent != null && car.ers_percent <= 15
                ? "text-warning"
                : "text-muted-foreground",
            )}>
              ERS {car?.ers_percent != null ? `${Math.round(car.ers_percent)}%` : "—"}
            </span>
          </span>
        </Tile>
      </div>
    </Card>
  )
}

function Opponent({ row }: { row: OverlayState["relative"][number] | undefined }) {
  if (!row) return <span className="text-sm text-muted-foreground">Нет данных</span>
  return (
    <span className="flex min-w-0 items-baseline justify-between gap-2">
      <span className="truncate text-sm font-semibold text-foreground">{row.driver}</span>
      <span className="shrink-0 font-mono text-lg text-foreground tabular">
        {row.gap_to_player_str}
      </span>
    </span>
  )
}

function Tile({ label, children }: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-[76px] min-w-0 flex-col justify-center gap-1 bg-card px-3 py-2.5">
      <span className="label-mono text-[11px] text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}

function Value({ text, tone = "plain" }: { text: string; tone?: "plain" | "warn" | "bad" }) {
  return (
    <span className={cn("whitespace-nowrap font-mono text-xl leading-none tabular",
      tone === "bad" ? "text-destructive" : tone === "warn" ? "text-warning" : "text-foreground")}
    >
      {text}
    </span>
  )
}

// ── Лента событий ────────────────────────────────────────────────────────────

/** Сколько событий показываем.
 *
 *  Лента приходит целиком в `/api/state` (новые сверху, `core/ui_state.py`
 *  вставляет через `insert(0, …)`), но телефон у руля — не место для истории
 *  заезда: нужно то, что случилось только что. Вся лента остаётся на десктопе
 *  во вкладке «События». */
const FEED_LIMIT = 4

function Events({ state }: { state: SpotterState | null }) {
  const items = (state?.feed ?? []).slice(0, FEED_LIMIT)
  return (
    <Card label="События">
      {items.length === 0 ? (
        <Empty text="Пока пусто" />
      ) : (
        <ul className="flex flex-col">
          {items.map((item, i) => (
            <li
              key={`${item.time}-${item.event_code}-${i}`}
              className="flex gap-3 border-t border-border/60 px-3 py-3 first:border-t-0"
            >
              <span
                className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-snug text-foreground">{item.phrase}</p>
                <span className="label-mono text-[11px] text-muted-foreground">
                  {item.time}
                  {/* Событие было в ленте, но НЕ прозвучало — на телефоне это
                      единственный способ узнать, что реплику приглушили. */}
                  {item.muted ? " · без голоса" : ""}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// ── Общее ────────────────────────────────────────────────────────────────────

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <h2 className="label-mono border-b border-border px-3 py-2 text-[11px] text-muted-foreground">
        {label}
      </h2>
      {children}
    </section>
  )
}

function Empty({ text }: { text: string }) {
  return <p className="px-3 py-4 text-sm text-muted-foreground">{text}</p>
}
