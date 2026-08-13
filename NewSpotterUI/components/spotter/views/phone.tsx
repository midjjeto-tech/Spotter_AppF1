"use client"

/**
 * Второй экран — телефон рядом с рулём (`/phone.html?token=…`).
 *
 * Отдельный экран, а НЕ десктопный UI на узком стекле. Замер живого DOM при
 * 375px показал, почему: сайдбар `w-60` не сжимается, и на контент оставалось
 * 87 пикселей. Но дело не только в вёрстке — за рулём не нужны «Настройки»,
 * «Логи», хоткеи и разметка оверлея. Нужны позиция, гэпы, шины, топливо и то,
 * что сказал инженер.
 *
 * Данные — существующие ручки `/api/overlay` и `/api/state`, новых не заводим:
 * `core/overlay.py::build_overlay_state` уже собирает ровно этот срез, включая
 * `relative` с НАКОПЛЕННЫМ гэпом до каждой машины (а не гэпом до соседа).
 */

import { useEffect, useState } from "react"
import { getOverlay, getState, type OverlayState, type SpotterState } from "@/lib/api"
import { cn } from "@/lib/utils"

/** Опрос: 500 мс.
 *
 *  Игровой оверлей на той же машине ходит раз в 250 мс, но здесь между
 *  клиентом и сервером Wi-Fi и телефонная батарея, а взгляд на второй экран
 *  бросают между поворотами, а не покадрово. Цепочка `setTimeout`, а не
 *  `setInterval` — чтобы запросы не накладывались, когда сеть подвисла
 *  (тот же приём, что в `lib/use-spotter-state.ts`). */
const POLL_MS = 500

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

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <Header overlay={overlay} online={online} connected={connected} />

      <main className="flex flex-col gap-3 px-3 pb-8 pt-3">
        {!online && <Notice tone="bad" text="Нет связи с приложением на ПК" />}
        {online && !connected && (
          <Notice tone="warn" text="Телеметрия не идёт — запусти заезд в игре" />
        )}

        <Tower rows={overlay?.relative ?? []} />
        <CarStrip overlay={overlay} />
        <Engineer state={state} />
        <Events state={state} />

        <p className="px-1 pt-1 text-[11px] leading-relaxed text-muted-foreground">
          Экран телефона будет гаснуть сам: запрет на засыпание браузер даёт
          только по HTTPS, а второй экран работает по HTTP в локальной сети.
          Отключается в настройках телефона.
        </p>
      </main>
    </div>
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
    <header className="sticky top-0 z-10 flex items-center gap-4 border-b border-border bg-card px-4 py-3">
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

// ── Машина ───────────────────────────────────────────────────────────────────

function CarStrip({ overlay }: { overlay: OverlayState | null }) {
  const tyre = overlay?.tyre
  const car = overlay?.car
  const fuel = car?.fuel_delta_laps

  return (
    <Card label="Машина">
      <div className="grid grid-cols-2 gap-px bg-border/60">
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
        </Tile>

        <Tile label="ИЗНОС">
          <Value
            text={tyre?.wear_pct != null ? `${Math.round(tyre.wear_pct)}%` : "—"}
            tone={tyre?.wear_pct != null && tyre.wear_pct >= 70 ? "warn" : "plain"}
          />
        </Tile>

        <Tile label="ТОПЛИВО">
          {/* Не килограммы, а запас в КРУГАХ относительно дистанции: за рулём
              решение принимают по нему, а перевод из кг в круги в уме —
              лишняя работа. Минус = не хватает. */}
          <Value
            text={fuel != null ? `${fuel > 0 ? "+" : ""}${fuel.toFixed(1)} кр.` : "—"}
            tone={fuel != null && fuel < 0 ? "bad" : "plain"}
          />
        </Tile>

        <Tile label="ERS">
          <Value
            text={car?.ers_percent != null ? `${Math.round(car.ers_percent)}%` : "—"}
            tone={car?.ers_percent != null && car.ers_percent <= 15 ? "warn" : "plain"}
          />
        </Tile>

        <Tile label="ПОСЛЕДНИЙ КРУГ" wide>
          <Value text={car?.last_lap_str && car.last_lap_str !== "—" ? car.last_lap_str : "—"} />
        </Tile>
      </div>
    </Card>
  )
}

function Tile({ label, wide, children }: {
  label: string
  wide?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={cn("flex min-h-[68px] flex-col justify-center gap-1 bg-card px-3 py-2.5",
      wide && "col-span-2")}
    >
      <span className="label-mono text-[11px] text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}

function Value({ text, tone = "plain" }: { text: string; tone?: "plain" | "warn" | "bad" }) {
  return (
    <span className={cn("font-mono text-2xl leading-none tabular",
      tone === "bad" ? "text-destructive" : tone === "warn" ? "text-warning" : "text-foreground")}
    >
      {text}
    </span>
  )
}

// ── Инженер ──────────────────────────────────────────────────────────────────

function Engineer({ state }: { state: SpotterState | null }) {
  const last = state?.radio_message?.text?.trim()
  return (
    <Card label="Инженер">
      {last ? (
        <p className="px-3 py-3 text-base leading-relaxed text-foreground">{last}</p>
      ) : (
        <Empty text="Пока молчит" />
      )}
    </Card>
  )
}

// ── Лента событий ────────────────────────────────────────────────────────────

/** Сколько событий показываем.
 *
 *  Лента приходит целиком в `/api/state` (новые сверху, `core/ui_state.py`
 *  вставляет через `insert(0, …)`), но телефон у руля — не место для истории
 *  заезда: нужно то, что случилось только что. Вся лента остаётся на десктопе
 *  во вкладке «События». */
const FEED_LIMIT = 6

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
