"use client"

import { useEffect, useState } from "react"
import { PageHeader, Panel } from "../ui"
import { Button } from "@/components/ui/button"
import { getSessions, compareOwn, type CompareResult, type SessionItem } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Flag } from "lucide-react"

// Фильтр списка сохранённых сессий по типу. Значения — ровно те, что отдаёт
// analytics/archive.py::_SESSION_TYPE_NORMALIZE (race/qualifying/practice/sprint);
// «Спринт» бэкенд различал с самого начала, а кнопки для него тут не было.
type TypeFilterId = "all" | "race" | "qualifying" | "practice" | "sprint"
const TYPE_FILTERS: { id: TypeFilterId; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "race", label: "Гонки" },
  { id: "qualifying", label: "Квалиф." },
  { id: "sprint", label: "Спринт" },
  { id: "practice", label: "Практика" },
]

/** Ошибки /api/compare_own (analytics/loader.py, web_server.py) человеческим
 *  языком. `retry` отделяет «попробуйте позже» от «так не получится в
 *  принципе» — раньше и то и другое приходило сырым кодом.
 *
 *  Коды источников реальной F1 (no_fastf1_data, openf1_live_session,
 *  rate_limit и прочие) ушли вместе с самими источниками 2026-08-08: сети в
 *  сравнении больше нет, а значит нет ни лимитов запросов, ни «гонка ещё
 *  идёт». Осталась одна настоящая причина отказа — сравнивать не с чем. */
const ERROR_TEXT: Record<string, { text: string; retry: boolean }> = {
  no_own_sessions_for_track: {
    text: "На этой трассе записан только один заезд — сравнить пока не с чем. Проедьте ещё одну сессию здесь же.",
    retry: false,
  },
  unknown_track: {
    text: "Трасса этого заезда не опознана — сопоставить не с чем.",
    retry: false,
  },
}

function describeError(raw: string): { text: string; retry: boolean } {
  const known = ERROR_TEXT[raw]
  if (known) return known
  // bad_request: — префиксный код с хвостом исключения; показываем
  // человеческую часть, хвост оставляем в title.
  if (raw.startsWith("bad_request"))
    return { text: "Некорректный запрос сравнения.", retry: false }
  return { text: "Не удалось выполнить сравнение.", retry: true }
}

// ms -> "m:ss.mmm"
function fmtMs(ms?: number | null): string {
  if (ms == null) return "—"
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, "0")
  return `${m}:${s}`
}

function fallbackInterpretation(gapMs?: number | null): string {
  if (gapMs == null) return "Разница времён недоступна."
  const value = `${(Math.abs(gapMs) / 1000).toFixed(3)} с`
  if (gapMs < 0) return `Твоё время на ${value} меньше ориентира.`
  if (gapMs > 0) return `Твоё время на ${value} больше ориентира.`
  return "Твоё время совпало с ориентиром."
}

export function ArchiveView() {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [result, setResult] = useState<CompareResult | null>(null)
  const [status, setStatus] = useState("")
  const [statusTitle, setStatusTitle] = useState("")
  const [statusKind, setStatusKind] = useState<"idle" | "busy" | "ok" | "retry" | "fail">("idle")
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState<TypeFilterId>("all")

  const filtered = typeFilter === "all"
    ? sessions
    : sessions.filter((s) => s.session_type === typeFilter)

  useEffect(() => {
    getSessions()
      .then(setSessions)
      .catch(() => {})
  }, [])

  const compare = async () => {
    if (!selected) {
      setStatus("Выберите гонку из списка слева")
      setStatusTitle("")
      setStatusKind("fail")
      return
    }
    setLoading(true)
    // Сеть не задействована — эталон читается с диска, ждать нечего.
    setStatus("Поиск вашего лучшего заезда на этой трассе…")
    setStatusTitle("")
    setStatusKind("busy")
    setResult(null)
    try {
      const data = await compareOwn({ game_session_path: selected })
      if (data.error) {
        const described = describeError(data.error)
        setStatus(described.text)
        setStatusTitle(data.error)
        setStatusKind(described.retry ? "retry" : "fail")
      } else {
        setStatus("Готово ✓")
        setStatusTitle("")
        setStatusKind("ok")
        setResult(data)
      }
    } catch (e) {
      setStatus("Приложение не ответило на запрос сравнения.")
      setStatusTitle((e as Error).message)
      setStatusKind("retry")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PageHeader title="Archive" subtitle="Сохранённые сессии и сравнение с вашим лучшим заездом на трассе" />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_minmax(0,380px)]">
        <Panel label="Ваши сессии" bodyClassName="p-0">
          <div className="flex flex-wrap gap-2 border-b border-border px-5 py-3">
            {TYPE_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setTypeFilter(f.id)}
                className={cn(
                  "rounded-md border px-3 py-1 text-xs transition-colors",
                  typeFilter === f.id
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-secondary text-muted-foreground hover:text-foreground",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          {filtered.length > 0 ? (
            <ul>
              {filtered.map((r) => {
                const isSel = selected === r.path
                return (
                  <li key={r.path}>
                    <button
                      type="button"
                      onClick={() => setSelected(r.path)}
                      className={cn(
                        "flex w-full items-center gap-4 border-b border-border px-5 py-4 text-left last:border-0 hover:bg-secondary/40",
                        isSel && "bg-primary/8",
                      )}
                    >
                      <span className="flex h-10 w-10 items-center justify-center rounded-md bg-secondary text-muted-foreground">
                        <Flag className="h-4.5 w-4.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">{r.track_name || "—"}</p>
                        <p className="text-xs text-muted-foreground">
                          {r.timestamp || ""}
                          {r.game_year ? ` · F1 ${String(r.game_year).slice(-2)}` : ""}
                        </p>
                      </div>
                      {r.final_position != null && (
                        <p className="font-heading text-lg font-bold text-primary">P{r.final_position}</p>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : (
            <div className="px-5 py-16 text-center text-sm text-muted-foreground">
              {sessions.length === 0
                ? "Нет записанных сессий — сыграйте в F1 25"
                : "Нет сессий выбранного типа"}
            </div>
          )}
        </Panel>

        <Panel label="Сравнить со своим лучшим">
          <p className="mb-3 text-xs text-muted-foreground">
            Эталон — ваш самый быстрый заезд на этой же трассе. Условия заездов
            различаются: топливо, резина, погода и настройки машины.
          </p>
          {/* Побочный эффект, который раньше нигде не был виден: web_server.py
              после сравнения зовёт engine.set_analytics_context(qwen_context) —
              строка «КОНТЕКСТ СРАВНЕНИЯ» внизу уходит в живой комментарий и «Разбор»
              до конца сессии, перезаписывая карьерный контекст. */}
          <p className="mb-4 rounded-md border border-border bg-secondary/50 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            Сравнение не только показывает таблицу: его строка «Контекст сравнения» подставляется
            комментатору и в «Разбор» до конца текущей сессии.
          </p>

          {/* Селекторы года и типа сессии убраны вместе с источником: они
              выбирали сезон и сессию РЕАЛЬНОГО чемпионата. Эталон теперь
              определяется однозначно — свой лучший заезд на той же трассе, —
              и выбирать пользователю нечего. */}

          <Button
            onClick={compare}
            disabled={loading}
            className="h-10 w-full bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {loading ? "Загрузка…" : "Сравнить"}
          </Button>
          {status && (
            <p
              title={statusTitle}
              className={cn(
                "mt-3 rounded-md px-3 py-2 text-center text-[11px] leading-relaxed",
                statusKind === "ok" && "bg-success/10 text-success",
                statusKind === "retry" && "bg-warning/10 text-warning",
                statusKind === "fail" && "bg-primary/10 text-primary",
                (statusKind === "busy" || statusKind === "idle") && "text-muted-foreground",
              )}
            >
              {status}
              {statusKind === "retry" && (
                <span className="mt-1 block text-[10px] opacity-80">Можно повторить позже</span>
              )}
              {statusKind === "fail" && statusTitle && (
                <span className="mt-1 block text-[10px] opacity-80">Повтор не поможет</span>
              )}
            </p>
          )}
        </Panel>
      </div>

      {result && <CompareResultView data={result} />}
    </div>
  )
}

function CompareResultView({ data }: { data: CompareResult }) {
  const { compare } = data
  const sectors = compare.sectors
  const interpretation = compare.interpretation ?? fallbackInterpretation(compare.gap_ms)
  const disclaimer = compare.comparison_disclaimer
    ?? "Условия заездов различаются: топливо, резина, погода и настройки машины."
  return (
    // Таблица классификации реального Гран-при отсюда убрана вместе с
    // источником: у собственного заезда нет «топ-10», сравнение идёт кругом
    // против круга. Панель осталась одна и занимает всю ширину.
    <div className="mt-5">
      <Panel label="Этот заезд против вашего лучшего">
        {compare.partial && (
          <p className="mb-3 rounded-md bg-warning/10 px-3 py-2 text-[11px] text-warning">
            Нет полного набора секторных данных. Время круга показано только как справочная разница.
          </p>
        )}
        <p className="mb-4 rounded-md bg-secondary/60 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
          {disclaimer}
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="label-mono text-[9px] text-muted-foreground">ЭТОТ ЗАЕЗД · ЛУЧШИЙ КРУГ</p>
            <p className="font-mono text-xl font-bold text-foreground">{fmtMs(compare.player_best_lap_ms)}</p>
            <p className="text-[10px] text-muted-foreground">круг {compare.player_best_lap_lap_number ?? "?"}</p>
          </div>
          <div>
            <p className="label-mono text-[9px] text-muted-foreground">ВАШ ЛУЧШИЙ · ОРИЕНТИР</p>
            <p className="font-mono text-xl font-bold text-foreground">{fmtMs(compare.f1_fastest_ms)}</p>
            <p className="text-[10px] text-muted-foreground">быстрейший круг на этой трассе</p>
          </div>
        </div>
        <p className="mt-4 rounded-md border border-border px-3 py-2 text-sm leading-relaxed text-foreground">
          <span className="label-mono mr-2 text-[9px] text-muted-foreground">РАЗНИЦА ВРЕМЁН</span>
          {interpretation}
        </p>

        {sectors && (
          <div className="mt-4 border-t border-border pt-3">
            {(["s1", "s2", "s3"] as const).map((s) => {
              const sec = sectors[s]
              if (!sec) return null
              const sign = sec.gap_ms >= 0 ? "+" : ""
              return (
                <div key={s} className="flex items-center justify-between border-t border-border/50 py-1.5 text-[11px] first:border-0">
                  <span className="label-mono text-muted-foreground">{s.toUpperCase()}</span>
                  <span className="font-mono">{fmtMs(sec.player_ms)}</span>
                  <span className="font-mono text-muted-foreground">{fmtMs(sec.f1_ms)}</span>
                  <span className={cn("font-mono", sec.gap_ms > 500 && "text-primary")}>
                    {sign}
                    {(sec.gap_ms / 1000).toFixed(3)}s
                  </span>
                </div>
              )
            })}
          </div>
        )}

        {compare.qwen_context && (
          <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
            <span className="label-mono mr-2 text-[9px]">КОНТЕКСТ СРАВНЕНИЯ</span>
            {compare.qwen_context}
          </p>
        )}
      </Panel>
    </div>
  )
}
