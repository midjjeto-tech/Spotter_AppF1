"use client"

import { useEffect, useState } from "react"
import { Panel, Toggle, Readout, Dot, SectionLabel } from "../ui"
import { Button } from "@/components/ui/button"
import { feedToEvent } from "@/lib/feed"
import { saveSettings, testVoice, clearLogs, highlight, type SpotterState } from "@/lib/api"
import type { RaceFeedHubSummary } from "@/lib/use-racefeed"
import { cn } from "@/lib/utils"
import { ArrowRight, MessageSquare, Volume2, Play, Trash2, Square, Fuel, Mic, MapPin, Flag, RadioTower, Rss } from "lucide-react"

const _MODE_LABELS: Record<string, string> = {
  PIT:  "Пит",
  PUSH: "Атака",
  SAVE: "Экономия",
  HOLD: "Держать",
}

const _FUEL_LABELS: Record<string, string> = {
  attack: "Атака",
  normal: "Норма",
  save:   "Экономия",
}

const _STYLE_LABELS: Record<string, string> = {
  consistent: "стабильный",
  aggressive:  "агрессивный",
  charging:    "↑ прогресс",
  fading:      "↓ спад",
}

const _TREND_LABELS: Record<string, string> = {
  rising:  "↑ замедл.",
  falling: "↓ ускор.",
  stable:  "стабильно",
}

const _TYRE_LABELS: Record<string, string> = {
  fresh:    "свежие",
  worn:     "изношены",
  critical: "критично",
  cliff:    "обрыв",
  unknown:  "—",
}

const _ADVICE_LABELS: Record<string, string> = {
  "cover_inside": "Закрой изнутри",
  "hold_line":    "Держи линию",
  "late_brake":   "Тормози позже",
  "outside":      "Снаружи",
  "inside":       "Изнутри",
  "none":         "—",
}

export function DashboardView({
  state,
  raceFeed,
  unreadRaceFeed,
  onOpenRaceFeed,
  onOpenSettings,
}: {
  state: SpotterState | null
  raceFeed: RaceFeedHubSummary
  unreadRaceFeed: number
  onOpenRaceFeed: () => void
  onOpenSettings: () => void
}) {
  const connected = state?.connected ?? false
  const speaking = state?.speaking ?? false
  const s = state?.settings
  const t = state?.telemetry
  const trackAi = state?.track_ai
  const strategyAi = state?.strategy_ai
  const coachAi = state?.coach_ai
  const rivals = state?.rivals

  // Локальное оптимистичное зеркало настроек — отзывчивые тогглы, сверяемся с опросом.
  const [local, setLocal] = useState({ commentary: false, voice: false, critical: true, ambient: true, engineerChatter: true, broadcast: false, racefeed: false, position: "auto" })
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle")
  useEffect(() => {
    if (s) {
      setLocal({
        commentary: s.commentary_enabled,
        voice: s.autovoice_enabled,
        critical: s.critical_events_enabled,
        ambient: s.ambient_enabled ?? true,
        engineerChatter: s.engineer_chatter_enabled ?? true,
        broadcast: s.broadcast_mode_enabled ?? false,
        racefeed: s.racefeed_enabled ?? false,
        position: s.commentator_position,
      })
    }
  }, [s?.commentary_enabled, s?.autovoice_enabled, s?.critical_events_enabled, s?.ambient_enabled, s?.engineer_chatter_enabled, s?.broadcast_mode_enabled, s?.racefeed_enabled, s?.commentator_position])

  const apply = (key: keyof typeof local, apiKey: string) => async (v: boolean) => {
    const previous = local[key]
    setLocal((p) => ({ ...p, [key]: v }))
    setSaveStatus("saving")
    try {
      const result = await saveSettings({ [apiKey]: v })
      if (!result.ok) throw new Error("settings rejected")
      setSaveStatus("saved")
    } catch {
      setLocal((p) => ({ ...p, [key]: previous }))
      setSaveStatus("error")
    }
  }

  const uptime = useUptime()
  const events = (state?.feed ?? []).slice(0, 5).map(feedToEvent)

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_320px]">
      {/* Main column */}
      <div className="flex flex-col gap-5">
        {/* Status banner */}
        <Panel
          label="Сессия"
          action={
            <div className="flex items-center gap-2">
              {state?.yandex_ok === false && (
                <span className="label-mono rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[11px] text-warning">
                  OFFLINE
                </span>
              )}
              <Dot state={connected ? "on" : "warn"} />
              <span className="label-mono text-[11px] text-muted-foreground">
                {connected ? "В ЭФИРЕ" : "ОЖИДАНИЕ"}
              </span>
            </div>
          }
        >
          <div className="flex items-center gap-3">
            <span className="relative flex h-2.5 w-2.5">
              {connected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />}
              <span
                className={cn(
                  "relative inline-flex h-2.5 w-2.5 rounded-full",
                  connected ? "bg-success" : "bg-warning",
                )}
              />
            </span>
            <h2 className="font-heading text-xl font-semibold text-foreground">
              {connected ? (speaking ? "Комментатор говорит" : "Сессия активна") : "Ожидание подключения к игре"}
            </h2>
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2">
            {connected
              ? speaking && state?.now_speaking
                ? state.now_speaking
                : "Телеметрия активна — комментирую события в реальном времени."
              : "Запустите F1 25 и включите UDP-телеметрию (порт 20777)."}
          </p>

          <div className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4">
            <StatCell
              label="Статус"
              value={!state ? "Сервер недоступен" : connected ? (local.commentary ? "Активен" : "Пауза") : "Готов"}
              tone={connected && local.commentary ? "success" : "muted"}
            />
            <StatCell label="Сигнал" value={connected ? "Есть" : "Нет"} tone={connected ? "success" : "muted"} />
            <StatCell label="Сессия" value="F1 25" />
            <StatCell label="Uptime" value={uptime} mono />
          </div>
        </Panel>

        <RaceFeedHubCard
          summary={raceFeed}
          unread={unreadRaceFeed}
          onOpen={onOpenRaceFeed}
          onConfigure={onOpenSettings}
        />

        {/* Only race-time controls live here; detailed switches are in Settings. */}
        <Panel
          label="Быстрое управление"
          action={<SaveState status={saveStatus} />}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <QuickSwitch
              icon={MessageSquare}
              title="Комментарий"
              subtitle="Реплики о событиях гонки"
              checked={local.commentary}
              disabled={!state}
              onChange={apply("commentary", "commentary_enabled")}
            />
            <QuickSwitch
              icon={Volume2}
              title="Авто-озвучка"
              subtitle="Проигрывать реплики через TTS"
              checked={local.voice}
              disabled={!state}
              onChange={apply("voice", "autovoice_enabled")}
            />
          </div>

          <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Button
              variant="outline"
              onClick={() => testVoice()}
              disabled={!state}
              className="h-10 border-border bg-secondary text-foreground hover:bg-elevated disabled:opacity-40"
            >
              <Play className="h-4 w-4" /> Тест рации
            </Button>
            <Button
              variant="outline"
              onClick={() => highlight()}
              disabled={!connected || !local.commentary}
              className="h-10 border-border bg-secondary text-foreground hover:bg-elevated disabled:opacity-40"
            >
              <Mic className="h-4 w-4" /> Говори сейчас
            </Button>
            <Button
              variant="outline"
              onClick={() => clearLogs()}
              disabled={!state}
              className="h-10 border-border bg-secondary text-foreground hover:bg-elevated disabled:opacity-40"
            >
              <Trash2 className="h-4 w-4" /> Очистить ленту
            </Button>
          </div>

          <Button
            onClick={() => apply("commentary", "commentary_enabled")(!local.commentary)}
            disabled={!state}
            className={cn(
              "mt-3 h-11 w-full text-primary-foreground disabled:opacity-40",
              local.commentary ? "bg-destructive hover:bg-destructive/90" : "bg-primary hover:bg-primary/90",
            )}
          >
            <Square className="h-3.5 w-3.5 fill-current" />{" "}
            {local.commentary ? "Остановить комментатора" : "Запустить комментатора"}
          </Button>
        </Panel>
      </div>

      {/* Right rail */}
      <div className="flex flex-col gap-5">
        {!connected ? (
          <Panel label="Данные гонки">
            <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-warning/10 text-warning">
                <RadioTower className="h-5 w-5" />
              </span>
              <div>
                <h3 className="font-heading text-lg font-semibold text-foreground">Ждём телеметрию F1 25</h3>
                <p className="mt-1 max-w-xs text-sm leading-relaxed text-muted-foreground">
                  После подключения здесь появятся позиция, темп, стратегия, трасса и ближайшие соперники.
                </p>
              </div>
              <div className="mt-2 rounded-md border border-border bg-secondary/60 px-3 py-2 font-mono text-xs text-muted-foreground">
                UDP · 127.0.0.1:20777
              </div>
            </div>
          </Panel>
        ) : (
          <>
        <Panel label="Телеметрия">
          <div className="grid grid-cols-2 gap-5">
            <Readout label="Круг" value={t?.lap ?? "—"} />
            <Readout label="Позиция" value={t?.position ?? "—"} accent={connected} />
            <Readout label="Скорость" value={t?.speed ?? "—"} unit="км/ч" />
            <Readout label="Передача" value={t?.gear ?? "—"} />
          </div>
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="label-mono flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Fuel className="h-3 w-3" /> Топливо
              </span>
              <span className="font-mono text-[11px] text-muted-foreground tabular">{t?.fuel ?? "—"}</span>
            </div>
          </div>
        </Panel>

        <Panel label="Трасса" action={
          <span className="label-mono text-[10px] text-muted-foreground flex items-center gap-1">
            <MapPin className="h-3 w-3" />
            {trackAi?.track_name ?? "—"}
          </span>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout label="ПОВОРОТ"  value={trackAi?.corner ?? "—"} />
            <Readout label="ФАЗА"     value={trackAi?.phase  ?? "—"} />
            <Readout label="ЗОНА"     value={trackAi?.attack_zone ? "АТАКА" : "нейтрально"} accent={trackAi?.attack_zone} />
            <Readout label="СОВЕТ"    value={_ADVICE_LABELS[trackAi?.defense_advice ?? "none"] ?? trackAi?.defense_advice ?? "—"} />
          </div>
        </Panel>

        <Panel label="Стратегия" action={
          <span className="label-mono text-[10px] text-muted-foreground flex items-center gap-1">
            <Flag className="h-3 w-3" />
            {_MODE_LABELS[strategyAi?.mode ?? "HOLD"] ?? strategyAi?.mode ?? "—"}
          </span>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout label="ДЕЙСТВИЕ" value={strategyAi?.action?.toUpperCase() ?? "—"} />
            <Readout
              label="УВЕРЕН."
              value={strategyAi?.confidence != null ? `${Math.round(strategyAi.confidence * 100)}%` : "—"}
            />
            <Readout label="ШИНЫ" value={_TYRE_LABELS[strategyAi?.tyre_status ?? "unknown"] ?? "—"} />
            <Readout label="ТРЕНД" value={_TREND_LABELS[strategyAi?.pace_trend ?? "stable"] ?? "—"} />
            <Readout label="ТОПЛИВО" value={_FUEL_LABELS[strategyAi?.fuel_mode ?? "normal"] ?? "—"} />
            <Readout label="СОВЕТ" value={strategyAi?.advice ?? "—"} />
          </div>
        </Panel>

        <Panel label="Коуч" action={
          <span className="label-mono text-[10px] text-muted-foreground">
            {coachAi?.lap_count ? `${coachAi.lap_count} кр.` : "—"}
          </span>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout
              label="КОНСИСТ."
              value={coachAi?.consistency_score != null
                ? `${Math.round(coachAi.consistency_score * 100)}%`
                : "—"}
            />
            <Readout
              label="ДЕЛЬТА"
              value={coachAi?.pace_delta_ms != null
                ? (coachAi.pace_delta_ms >= 0
                    ? `+${(coachAi.pace_delta_ms / 1000).toFixed(2)}с`
                    : `${(coachAi.pace_delta_ms / 1000).toFixed(2)}с`)
                : "—"}
            />
            <Readout
              label="СЛАБ. СЕК."
              value={coachAi?.weak_sector != null ? `S${coachAi.weak_sector}` : "—"}
            />
            <Readout
              label="ШИНЫ"
              value={coachAi?.tyre_advice?.toUpperCase() ?? "—"}
            />
          </div>
          {coachAi?.advice && (
            <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
              {coachAi.advice}
            </p>
          )}
        </Panel>

        <Panel label="Соперники" action={
          <span className="label-mono text-[10px] text-muted-foreground">
            {rivals?.nearby_count ? `${rivals.nearby_count} рядом` : "—"}
          </span>
        }>
          {rivals?.rivals && rivals.rivals.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {rivals.rivals
                .filter((r) => r.nearby)
                .slice(0, 4)
                .map((r) => (
                  <li key={r.driver} className="rounded-md bg-secondary/60 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-foreground">
                        P{r.position} {r.driver}
                      </span>
                      <span className="label-mono text-[9px] text-muted-foreground">
                        {_STYLE_LABELS[r.style] ?? r.style}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="text-[10px] text-muted-foreground">{r.team}</span>
                      {r.pit_count > 0 && (
                        <span className="label-mono text-[9px] text-primary">
                          PIT ×{r.pit_count}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              {rivals.rivals.filter((r) => r.nearby).length === 0 && (
                <li className="py-4 text-center text-xs text-muted-foreground">
                  Нет соперников рядом
                </li>
              )}
            </ul>
          ) : (
            <div className="flex items-center justify-center py-8">
              <p className="text-xs text-muted-foreground">Ожидание данных гонки</p>
            </div>
          )}
        </Panel>

        <Panel label="Live Events" className="flex-1" bodyClassName="p-3">
          {events.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {events.map((e) => (
                <li key={e.id} className="rounded-md bg-secondary/60 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="label-mono truncate text-[9px] text-primary">{e.title}</span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      {/* Тот же признак, что на экране «События»: строка в
                          ленте не означает, что реплика прозвучала. */}
                      {!e.spoken && (
                        <span className="label-mono text-[9px] text-muted-foreground">без озвучки</span>
                      )}
                      <span className="font-mono text-[9px] text-muted-foreground">{e.time}</span>
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-foreground/90 line-clamp-2">{e.text}</p>
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
              <SectionLabel>No events</SectionLabel>
              <p className="text-xs text-muted-foreground">Появятся в реальном времени</p>
            </div>
          )}
        </Panel>
          </>
        )}
      </div>
    </div>
  )
}

function RaceFeedHubCard({
  summary,
  unread,
  onOpen,
  onConfigure,
}: {
  summary: RaceFeedHubSummary
  unread: number
  onOpen: () => void
  onConfigure: () => void
}) {
  const prediction = summary.prediction
  const ticketComplete = Boolean(
    prediction?.reader_ticket.finish
    && prediction.reader_ticket.teammate
    && prediction.reader_ticket.risk,
  )

  let eyebrow = "КАНАЛ КАРЬЕРЫ"
  let title = "Подключаем RaceFeed"
  let text = "Проверяем последнее досье и события текущего уик-энда."
  let cta = "Открыть RaceFeed"
  let configure = false

  if (summary.loaded && summary.enabled === false) {
    eyebrow = "ВЫКЛЮЧЕН"
    title = "RaceFeed ждёт активации"
    text = "Включите канал один раз — он будет собирать историю карьеры только из событий ваших гонок."
    cta = "Настроить RaceFeed"
    configure = true
  } else if (summary.liveFinished) {
    eyebrow = "ДОСЬЕ ГОТОВО"
    title = prediction?.track_name
      ? `Итоги Гран-при · ${prediction.track_name}`
      : "Послегоночное досье готово"
    text = `${summary.livePostCount} ${ruPlural(summary.livePostCount, "ключевая публикация", "ключевые публикации", "ключевых публикаций")}: результат, гонка в цифрах, дуэли и следующая цель.`
    cta = "Открыть досье"
  } else if (prediction?.status === "open") {
    eyebrow = ticketComplete ? "ПРОГНОЗ СОХРАНЁН" : "ДО СТАРТА"
    title = `Ты против Spotter AI · ${prediction.track_name || "следующая гонка"}`
    text = ticketComplete
      ? "Билет готов. Стартовые огни зафиксируют выбор, а результат попадёт в сезонный счёт."
      : "Выберите финиш, исход дуэли с напарником и главный риск гонки."
    cta = ticketComplete ? "Проверить прогноз" : "Сделать прогноз"
  } else if (summary.livePostCount > 0 || prediction?.status === "locked") {
    eyebrow = "В ЭФИРЕ"
    title = prediction?.track_name
      ? `RaceFeed ведёт ${prediction.track_name}`
      : "RaceFeed собирает историю гонки"
    text = summary.livePostCount > 0
      ? `${summary.livePostCount} ключевых моментов уже в хронике. ${summary.latestLiveText}`
      : "Прогноз зафиксирован. Итоги появятся после официальной классификации."
    cta = "Открыть хронику"
  } else if (summary.latestArchive) {
    const date = new Date(summary.latestArchive.startedAt * 1000).toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "long",
    })
    eyebrow = "ПОСЛЕДНИЙ УИК-ЭНД"
    title = summary.latestArchive.trackName
      ? `Досье · ${summary.latestArchive.trackName}`
      : "Последнее досье гонки"
    text = `${date} · ${summary.latestArchive.postCount} ${ruPlural(summary.latestArchive.postCount, "публикация", "публикации", "публикаций")}. Вернитесь к результату и незаконченной истории сезона.`
    cta = "Открыть досье"
  } else if (summary.loaded) {
    eyebrow = "ГОТОВ К ПЕРВОЙ ГОНКЕ"
    title = "Ваша история начнётся с телеметрии"
    text = "Перед стартом появится прогноз, после финиша — досье с фактами, дуэлями и следующей целью."
  }

  return (
    <Panel
      label="Weekend Hub"
      action={unread > 0 ? (
        <span className="label-mono rounded-full bg-primary px-2 py-1 text-[10px] font-semibold text-primary-foreground">
          {unread > 99 ? "99+" : unread} НОВЫХ
        </span>
      ) : (
        <span className="label-mono text-[10px] text-muted-foreground">RACEFEED</span>
      )}
    >
      <div className="rounded-xl border border-primary/20 bg-[linear-gradient(135deg,rgba(239,68,68,0.10),rgba(124,58,237,0.07),transparent_70%)] p-4">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-primary/25 bg-primary/10 text-primary">
            <Rss className="h-4.5 w-4.5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="label-mono text-[10px] text-primary">{eyebrow}</p>
            <h3 className="mt-1 font-heading text-lg font-semibold text-foreground">{title}</h3>
            <p className="mt-1 line-clamp-3 text-xs leading-5 text-muted-foreground">{text}</p>
          </div>
        </div>
        <Button
          type="button"
          onClick={configure ? onConfigure : onOpen}
          disabled={!summary.loaded}
          className="mt-4 h-10 w-full bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
        >
          {cta} <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </Panel>
  )
}

function ruPlural(value: number, one: string, few: string, many: string): string {
  const n = Math.abs(value) % 100
  const last = n % 10
  if (n > 10 && n < 20) return many
  if (last === 1) return one
  if (last >= 2 && last <= 4) return few
  return many
}

// Аптайм окна (≈ время с запуска приложения, т.к. webview грузится на старте).
function useUptime() {
  const [start] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const sec = Math.floor((now - start) / 1000)
  const h = String(Math.floor(sec / 3600)).padStart(2, "0")
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0")
  const ss = String(sec % 60).padStart(2, "0")
  return `${h}:${m}:${ss}`
}

function StatCell({
  label,
  value,
  tone = "default",
  mono,
}: {
  label: string
  value: string
  tone?: "default" | "success" | "muted"
  mono?: boolean
}) {
  return (
    <div className="bg-card px-4 py-3">
      <p className="label-mono text-[11px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-sm font-medium",
          mono && "font-mono tabular",
          tone === "success" && "text-success",
          tone === "muted" && "text-muted-foreground",
          tone === "default" && "text-foreground",
        )}
      >
        {value}
      </p>
    </div>
  )
}

function QuickSwitch({
  icon: Icon,
  title,
  subtitle,
  checked,
  disabled,
  onChange,
}: {
  icon: typeof MessageSquare
  title: string
  subtitle: string
  checked: boolean
  disabled: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-secondary/45 p-4">
      <div className="flex min-w-0 items-center gap-3">
        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-md", checked ? "bg-primary/15 text-primary" : "bg-elevated text-muted-foreground") }>
          <Icon className="h-4.5 w-4.5" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{title}</p>
            <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
      </div>
      <Toggle checked={checked} onChange={onChange} label={title} disabled={disabled} />
    </div>
  )
}

function SaveState({ status }: { status: "idle" | "saving" | "saved" | "error" }) {
  if (status === "idle") return null
  return (
    <span role="status" className={cn(
      "label-mono text-[11px]",
      status === "error" ? "text-destructive" : status === "saved" ? "text-success" : "text-muted-foreground",
    )}>
      {status === "saving" ? "Сохраняю…" : status === "saved" ? "Сохранено" : "Не сохранено"}
    </span>
  )
}
