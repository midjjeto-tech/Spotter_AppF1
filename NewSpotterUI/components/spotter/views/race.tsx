"use client"

import { PageHeader, Panel, TyreChip } from "../ui"
import type { SpotterState } from "@/lib/api"
import { cn } from "@/lib/utils"

// 3-буквенный код из имени пилота ("M. Verstappen" -> "VER", "#44" -> "#44").
function driverCode(name: string): string {
  if (!name) return "—"
  if (name.startsWith("#")) return name
  const parts = name.replace(/\./g, "").split(/\s+/).filter(Boolean)
  const last = parts[parts.length - 1] ?? name
  return last.slice(0, 3).toUpperCase()
}

// ms -> "m:ss.mmm" (тот же формат, что на экране «Архив»).
function fmtLap(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms) || ms <= 0) return "—"
  const m = Math.floor(ms / 60000)
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, "0")
  return `${m}:${s}`
}

function posNum(p?: string): number | null {
  if (!p) return null
  const m = p.match(/\d+/)
  return m ? Number.parseInt(m[0], 10) : null
}

export function RaceView({ state }: { state: SpotterState | null }) {
  const connected = state?.connected ?? false
  const grid = state?.race?.grid ?? []
  const leader = state?.race?.leader ?? "—"
  const playerPos = posNum(state?.telemetry?.position)
  const playerLap = state?.telemetry?.lap
  const bench = state?.f1_benchmark ?? null
  const sectors = bench?.sectors ?? null
  const career = state?.career_memory ?? null
  const careerSectors = career?.sectors ?? null
  const damage = state?.damage ?? null

  const hasData = connected && grid.length > 0

  return (
    <div>
      <PageHeader title="Race" subtitle="Живые позиции и визуализация трассы" />

      {hasData ? (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_minmax(0,420px)]">
          <Panel label="Live Standings" bodyClassName="p-0">
            <ul>
              {grid.map((d) => {
                const isPlayer = playerPos != null && d.position === playerPos
                return (
                  <li
                    key={d.vehicle_idx}
                    className={cn(
                      "flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0",
                      isPlayer && "bg-primary/8",
                    )}
                  >
                    <span className="font-heading w-7 text-center text-lg font-bold tabular text-foreground">
                      {d.position}
                    </span>
                    <span className="h-7 w-1 rounded-full" style={{ backgroundColor: d.color }} />
                    <div className="min-w-0 flex-1">
                      <p className={cn("truncate text-sm font-medium", isPlayer ? "text-primary" : "text-foreground")}>
                        <span className="font-mono text-xs text-muted-foreground">{driverCode(d.driver)}</span> ·{" "}
                        {d.driver}
                      </p>
                      <p className="text-[11px] text-muted-foreground">{d.team || "—"}</p>
                    </div>
                    {/* Состав приходит из Car Status по всем машинам
                        (core/engine.py::_grid_tyre_compounds). Пока пакет по
                        этой машине не пришёл — прочерк, но уже временный. */}
                    <TyreChip compound={d.tyre_compound || "—"} />
                    <span className="w-16 text-right font-mono text-xs text-muted-foreground tabular">
                      {d.lap ? `L${d.lap}` : "—"}
                    </span>
                  </li>
                )
              })}
            </ul>
          </Panel>

          <div className="flex flex-col gap-5">
            <Panel
              label="Track Map"
              action={<span className="font-mono text-[10px] text-muted-foreground">{playerLap ?? "—"}</span>}
            >
              <TrackMap />
            </Panel>
            <Panel label="Лидер гонки">
              <div className="flex items-center justify-between rounded-md bg-secondary/60 p-3">
                <div>
                  <p className="font-mono text-[10px] text-muted-foreground">P1</p>
                  <p className="font-heading text-lg font-bold text-foreground">{leader}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-[10px] text-muted-foreground">Ваша позиция</p>
                  <p className="font-heading text-xl font-bold tabular text-primary">
                    {playerPos != null ? `P${playerPos}` : "—"}
                  </p>
                </div>
              </div>
              {bench ? (
                <div className="mt-3 rounded-md bg-secondary/60 p-3">
                  {/* Год и Гран-при ориентира важны: при отсутствии данных
                      текущего сезона бэкенд берёт прошлый (fallback-year), и
                      без подписи было непонятно, с чем вообще сравнение. */}
                  <p className="font-mono text-[10px] text-muted-foreground">
                    СПРАВОЧНЫЙ ОРИЕНТИР GP · {bench.source === "pole" ? "ПОУЛ" : "БЫСТРЕЙШИЙ КРУГ"} · {bench.f1_driver}
                  </p>
                  <p className="font-mono text-[10px] text-muted-foreground">
                    {[bench.event, bench.year].filter(Boolean).join(" · ") || "ГП НЕ ОПРЕДЕЛЁН"}
                    {" · "}
                    {fmtLap(bench.f1_time_ms)} против {fmtLap(bench.player_best_ms)}
                  </p>
                  <p className="mt-1 text-sm font-medium leading-relaxed text-foreground">
                    {bench.interpretation}
                  </p>
                  <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                    Это не означает, что вы быстрее или медленнее реального пилота.
                  </p>
                  {sectors && (
                    <div className="mt-2">
                      {bench.sectors_source === "seed" && (
                        <p className="mb-1 font-mono text-[9px] text-muted-foreground">
                          ИСТОРИЧЕСКИЕ ДАННЫЕ
                        </p>
                      )}
                      <p className="mb-1 font-mono text-[9px] text-muted-foreground">
                        РАЗНИЦА ЗАПИСАННЫХ ВРЕМЁН ПО СЕКТОРАМ
                      </p>
                      <div className="flex gap-1.5">
                        {(["1", "2", "3"] as const).map((n) => {
                          const s = sectors[n]
                          return (
                            <div
                              key={n}
                              className={cn(
                                "flex-1 rounded bg-secondary/60 px-1.5 py-1 text-center text-muted-foreground",
                              )}
                            >
                              <p className="font-mono text-[9px]">S{n}</p>
                              <p className="text-[11px] font-semibold tabular">
                                {s.gap_ms <= 0 ? "−" : "+"}
                                {(Math.abs(s.gap_ms) / 1000).toFixed(2)}
                              </p>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                  {!sectors && bench.sectors_blocked && (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      Секторы недоступны — идёт live-сессия F1.
                    </p>
                  )}
                </div>
              ) : (
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Справочный ориентир реального GP подгрузится после первого круга. Условия игры и реальной гонки напрямую не сопоставимы.
                </p>
              )}
            </Panel>
            <Panel label="Личный рекорд трассы">
              {career ? (
                <div className="rounded-md bg-secondary/60 p-3">
                  <p className="font-mono text-[10px] text-muted-foreground">
                    ЛИЧНЫЙ РЕКОРД ТРАССЫ
                  </p>
                  <p className={cn(
                    "font-heading text-lg font-bold tabular",
                    career.gap_ms <= 0 ? "text-success" : "text-foreground",
                  )}>
                    {career.gap_ms <= 0 ? "−" : "+"}
                    {(Math.abs(career.gap_ms) / 1000).toFixed(1)}с
                  </p>
                  {/* Сама дельта не отвечает на вопрос «а какой рекорд-то?» —
                      бэкенд отдаёт и время, и дату, UI их просто не показывал. */}
                  <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                    {fmtLap(career.best_ever_ms)}
                    {career.best_ever_date ? ` · ${career.best_ever_date}` : ""}
                    {" · сейчас "}
                    {fmtLap(career.player_best_ms)}
                  </p>
                  {careerSectors && (
                    <div className="mt-2 flex gap-1.5">
                      {(["1", "2", "3"] as const).map((n) => {
                        const s = careerSectors[n]
                        return (
                          <div
                            key={n}
                            className={cn(
                              "flex-1 rounded px-1.5 py-1 text-center",
                              s.gap_ms <= 0
                                ? "bg-success/15 text-success"
                                : "bg-secondary/60 text-muted-foreground",
                            )}
                          >
                            <p className="font-mono text-[9px]">S{n}</p>
                            <p className="text-[11px] font-semibold tabular">
                              {s.gap_ms <= 0 ? "−" : "+"}
                              {(Math.abs(s.gap_ms) / 1000).toFixed(2)}
                            </p>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Личный рекорд появится после первого визита на эту трассу.
                </p>
              )}
            </Panel>
            <Panel label="Повреждения">
              {damage ? (
                <div className="grid grid-cols-2 gap-1.5">
                  {(
                    [
                      ["Крылья", damage.wing_damage],
                      ["Днище", damage.floor_damage],
                      ["Коробка", damage.gearbox_damage],
                      ["Двигатель", damage.engine_damage],
                    ] as const
                  ).map(([label, value]) => (
                    <div
                      key={label}
                      className={cn(
                        "rounded px-1.5 py-1 text-center",
                        value >= 20
                          ? "bg-destructive/15 text-destructive"
                          : "bg-secondary/60 text-muted-foreground",
                      )}
                    >
                      <p className="font-mono text-[9px]">{label}</p>
                      <p className="text-[11px] font-semibold tabular">{value}%</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Данные о повреждениях появятся после первого круга.
                </p>
              )}
              {/* 20% — не только цвет плашки: тот же порог
                  (core/engine.py::_DAMAGE_NOTICEABLE_THRESHOLD) поднимает
                  разовую реплику инженера о повреждении. */}
              {damage && (
                <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                  От 20% инженер один раз проговаривает повреждение вслух — красная
                  плашка и реплика в эфире это один и тот же порог.
                </p>
              )}
            </Panel>
          </div>
        </div>
      ) : (
        <Panel label="Live Standings">
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
            <h3 className="font-heading text-lg font-semibold text-foreground">Гонка не началась</h3>
            <p className="max-w-sm text-sm text-muted-foreground">
              Таблица позиций появится автоматически при получении данных телеметрии.
            </p>
            <ol className="mt-2 flex flex-col gap-1.5 text-left text-sm text-muted-foreground">
              <li>
                <span className="font-mono text-primary">01</span> Запустите F1 25
              </li>
              <li>
                <span className="font-mono text-primary">02</span> Настройки → Телеметрия → UDP → порт 20777
              </li>
              <li>
                <span className="font-mono text-primary">03</span> Начните гонку или квалификацию
              </li>
            </ol>
          </div>
        </Panel>
      )}
    </div>
  )
}

// Стилизованная карта трассы (декоративная — точных мировых координат машин в телеметрии нет).
function TrackMap() {
  return (
    <div className="relative aspect-[4/3] w-full">
      <svg viewBox="0 0 400 300" className="h-full w-full" fill="none">
        <path
          d="M60 200 C 40 120, 120 60, 200 70 C 260 78, 250 130, 300 130 C 360 130, 380 80, 350 200 C 330 270, 200 250, 150 240 C 100 232, 80 260, 60 200 Z"
          stroke="oklch(1 0 0 / 12%)"
          strokeWidth="14"
          strokeLinejoin="round"
        />
        <path
          d="M60 200 C 40 120, 120 60, 200 70 C 260 78, 250 130, 300 130 C 360 130, 380 80, 350 200 C 330 270, 200 250, 150 240 C 100 232, 80 260, 60 200 Z"
          stroke="oklch(1 0 0 / 22%)"
          strokeWidth="2"
          strokeDasharray="2 6"
          strokeLinejoin="round"
        />
        <rect x="55" y="194" width="4" height="12" fill="var(--primary)" rx="1" />
      </svg>
    </div>
  )
}
