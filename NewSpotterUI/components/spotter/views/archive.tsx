"use client"

import { useEffect, useState } from "react"
import { PageHeader, Panel } from "../ui"
import { Button } from "@/components/ui/button"
import { getSessions, loadF1, type CompareResult, type SessionItem } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Flag } from "lucide-react"

const STYPE: Record<string, string> = { Гонка: "R", Квалификация: "Q", Спринт: "S" }

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

/** Ошибки /api/load_f1 (analytics/loader.py, analytics/openf1_loader.py,
 *  web_server.py) человеческим языком. `retry` отделяет «попробуйте позже» от
 *  «эта сессия не поддерживается в принципе» — раньше и то и другое приходило
 *  сырым кодом вида `no_data_for_session`. */
const ERROR_TEXT: Record<string, { text: string; retry: boolean }> = {
  no_fastf1_data: {
    text: "Для этой трассы нет данных реального Гран-при — сопоставить не с чем.",
    retry: false,
  },
  fastf1_not_installed: {
    text: "Библиотека FastF1 не установлена — сравнение для сезонов до 2023 недоступно.",
    retry: false,
  },
  no_data_for_session: {
    text: "Такой сессии нет в данных выбранного года — проверьте год и тип сессии.",
    retry: false,
  },
  openf1_live_session: {
    text: "Гран-при ещё идёт или только что закончился — итоговые данные появятся позже.",
    retry: true,
  },
  rate_limit: {
    text: "Источник данных временно ограничил запросы — попробуйте через несколько минут.",
    retry: true,
  },
}

function describeError(raw: string): { text: string; retry: boolean } {
  const known = ERROR_TEXT[raw]
  if (known) return known
  // session_not_found: / load_error: / bad_request: — префиксные коды с хвостом
  // исключения; показываем человеческую часть, хвост оставляем в title.
  if (raw.startsWith("session_not_found"))
    return { text: "Сессия не найдена в источнике данных — проверьте год и тип сессии.", retry: false }
  if (raw.startsWith("load_error"))
    return { text: "Не удалось загрузить данные Гран-при.", retry: true }
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
  if (gapMs < 0) return `Игровое время на ${value} меньше реального ориентира.`
  if (gapMs > 0) return `Игровое время на ${value} больше реального ориентира.`
  return "Игровое время совпало с реальным ориентиром."
}

export function ArchiveView() {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [year, setYear] = useState<"2025" | "2026">("2025")
  const [stypeLabel, setStypeLabel] = useState("Гонка")
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
    setStatus("Загрузка данных реального Гран-при… (~30с при первом запросе)")
    setStatusTitle("")
    setStatusKind("busy")
    setResult(null)
    try {
      const data = await loadF1({ year: Number.parseInt(year, 10), stype: STYPE[stypeLabel] ?? "R", game_session_path: selected })
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
      <PageHeader title="Archive" subtitle="Сохранённые сессии и справочное сопоставление с реальным Гран-при" />

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
                      onClick={() => {
                        setSelected(r.path)
                        if (r.game_year) setYear(String(r.game_year).startsWith("2026") ? "2026" : "2025")
                      }}
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

        <Panel label="Сопоставить с реальным GP">
          <p className="mb-3 text-xs text-muted-foreground">
            Сравните записанные времена как ориентир. Это не рейтинг мастерства относительно реального пилота.
          </p>
          {/* Побочный эффект, который раньше нигде не был виден: web_server.py
              после сравнения зовёт engine.set_analytics_context(qwen_context) —
              строка «КОНТЕКСТ GP» внизу уходит в живой комментарий и «Разбор»
              до конца сессии, перезаписывая карьерный контекст. */}
          <p className="mb-4 rounded-md border border-border bg-secondary/50 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            Сравнение не только показывает таблицу: его строка «Контекст GP» подставляется
            комментатору и в «Разбор» до конца текущей сессии.
          </p>

          <p className="label-mono mb-2 text-[10px] text-muted-foreground">Год</p>
          <div className="mb-5 flex gap-2">
            {(["2025", "2026"] as const).map((y) => (
              <button
                key={y}
                type="button"
                onClick={() => setYear(y)}
                className={cn(
                  "flex-1 rounded-md border px-4 py-2 font-heading text-sm font-bold transition-colors",
                  year === y
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-secondary text-muted-foreground hover:text-foreground",
                )}
              >
                {y}
              </button>
            ))}
          </div>

          <p className="label-mono mb-2 text-[10px] text-muted-foreground">Тип сессии</p>
          <select
            value={stypeLabel}
            onChange={(e) => setStypeLabel(e.target.value)}
            className="mb-5 h-10 w-full rounded-md border border-input bg-secondary px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option>Гонка</option>
            <option>Квалификация</option>
            <option>Спринт</option>
          </select>

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
  const { f1_meta, compare } = data
  const sectors = compare.sectors
  const interpretation = compare.interpretation ?? fallbackInterpretation(compare.gap_ms)
  const disclaimer = compare.comparison_disclaimer
    ?? "F1 25 и реальный Гран-при используют разные физику и условия. Разница времён не показывает, кто быстрее как пилот."
  return (
    <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Panel label={`${f1_meta.event || "Гран-при"} ${f1_meta.year || ""}`} bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-4 py-2.5 label-mono text-[10px] font-medium text-muted-foreground">#</th>
              <th className="px-2 py-2.5 label-mono text-[10px] font-medium text-muted-foreground">Пилот</th>
              <th className="px-2 py-2.5 label-mono text-[10px] font-medium text-muted-foreground">Команда</th>
              <th className="px-4 py-2.5 text-right label-mono text-[10px] font-medium text-muted-foreground">Отрыв</th>
            </tr>
          </thead>
          <tbody>
            {(f1_meta.results_top10 || []).map((r) => (
              <tr key={r.pos} className="border-b border-border last:border-0">
                <td className={cn("px-4 py-2 tabular", r.pos === 1 && "font-bold text-primary")}>{r.pos}</td>
                <td className="px-2 py-2 text-foreground">{r.driver}</td>
                <td className="px-2 py-2 text-muted-foreground">{r.team}</td>
                <td className="px-4 py-2 text-right font-mono text-muted-foreground tabular">
                  {r.gap_s != null ? `+${r.gap_s}s` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel label="Игровой круг и реальный ориентир">
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
            <p className="label-mono text-[9px] text-muted-foreground">F1 25 · ЛУЧШИЙ КРУГ</p>
            <p className="font-mono text-xl font-bold text-foreground">{fmtMs(compare.player_best_lap_ms)}</p>
            <p className="text-[10px] text-muted-foreground">круг {compare.player_best_lap_lap_number ?? "?"}</p>
          </div>
          <div>
            <p className="label-mono text-[9px] text-muted-foreground">РЕАЛЬНЫЙ GP · ОРИЕНТИР</p>
            <p className="font-mono text-xl font-bold text-foreground">{fmtMs(compare.f1_fastest_ms)}</p>
            <p className="text-[10px] text-muted-foreground">быстрейший круг · {compare.f1_best_lap_driver ?? "?"}</p>
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
            <span className="label-mono mr-2 text-[9px]">КОНТЕКСТ GP</span>
            {compare.qwen_context}
          </p>
        )}
      </Panel>
    </div>
  )
}
