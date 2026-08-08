"use client"

import { useEffect, useState } from "react"
import { Panel } from "../ui"
import { getRaceMap, type RaceMapResponse } from "@/lib/api"
import { Map as MapIcon } from "lucide-react"

/** Карта гонки: позиция каждой машины по кругам.
 *
 *  Живёт отдельным файлом, а не внутри debrief.tsx: тот и без графика на
 *  четыреста строк, а здесь своя загрузка данных и геометрия SVG.
 *
 *  Данные приходят СВОИМ эндпоинтом по запросу, а не из /api/state — сетка на
 *  22 машины за 60 кругов весит больше тысячи чисел, и слать её каждые 250 мс
 *  восьми окнам оверлея незачем. */

const WIDTH = 720
const HEIGHT = 300
const PAD_LEFT = 34
const PAD_RIGHT = 12
const PAD_TOP = 12
const PAD_BOTTOM = 26

export function RaceMapPanel() {
  const [map, setMap] = useState<RaceMapResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    getRaceMap()
      .then((data) => { if (alive) setMap(data) })
      .catch(() => { if (alive) setFailed(true) })
    return () => { alive = false }
  }, [])

  if (failed || !map || map.laps.length < 2) return null

  const laps = map.laps
  const maxPos = Math.max(
    2,
    ...map.rows.flatMap((r) => r.positions.filter((p): p is number => p != null)),
  )
  const x = (i: number) =>
    PAD_LEFT + (i * (WIDTH - PAD_LEFT - PAD_RIGHT)) / Math.max(1, laps.length - 1)
  // Первая позиция сверху — так же, как в любом протоколе.
  const y = (pos: number) =>
    PAD_TOP + ((pos - 1) * (HEIGHT - PAD_TOP - PAD_BOTTOM)) / Math.max(1, maxPos - 1)

  /** Разрывы (сход, отсутствие данных) рвут линию, а не соединяются напрямую:
   *  прямая через пропуск нарисовала бы обгон, которого не было. */
  const path = (positions: (number | null)[]) => {
    const parts: string[] = []
    let pen = "M"
    positions.forEach((pos, i) => {
      if (pos == null) { pen = "M"; return }
      parts.push(`${pen}${x(i).toFixed(1)},${y(pos).toFixed(1)}`)
      pen = "L"
    })
    return parts.join(" ")
  }

  const player = map.rows.find((r) => r.is_player)
  const summary = map.summary
  const worstIndex =
    summary?.worst_lap != null ? laps.indexOf(summary.worst_lap) : -1

  return (
    <Panel label="Карта гонки" action={
      <div className="flex items-center gap-1.5">
        <MapIcon className="h-3 w-3 text-muted-foreground" />
        <span className="label-mono text-[10px] text-muted-foreground">
          {laps.length} кр.
        </span>
      </div>
    }>
      {summary && (
        <p className="mb-3 text-xs leading-relaxed text-foreground/90">
          Старт {summary.start_position} → финиш {summary.end_position}
          {summary.net !== 0 && (
            <span className={summary.net > 0 ? "text-success" : "text-destructive"}>
              {" "}({summary.net > 0 ? "+" : ""}{summary.net})
            </span>
          )}
          {summary.worst_lap != null && (
            <> · худший круг {summary.worst_lap}: {summary.worst_delta} поз.</>
          )}
        </p>
      )}

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto w-full min-w-[520px]"
          role="img"
          aria-label="Позиции по кругам"
        >
          {/* Пит-круги — вертикальные метки под всеми линиями: без них провал
              на графике читается как проигранная борьба. */}
          {map.pit_laps.map((lap) => {
            const i = laps.indexOf(lap)
            if (i < 0) return null
            return (
              <line
                key={`pit-${lap}`}
                x1={x(i)} x2={x(i)} y1={PAD_TOP} y2={HEIGHT - PAD_BOTTOM}
                stroke="var(--warning)" strokeWidth={1} strokeDasharray="3 3"
                opacity={0.5}
              />
            )
          })}

          {worstIndex >= 0 && (
            <line
              x1={x(worstIndex)} x2={x(worstIndex)}
              y1={PAD_TOP} y2={HEIGHT - PAD_BOTTOM}
              stroke="var(--destructive)" strokeWidth={1.5} opacity={0.55}
            />
          )}

          {[1, Math.ceil(maxPos / 2), maxPos].map((pos) => (
            <g key={`axis-${pos}`}>
              <line
                x1={PAD_LEFT} x2={WIDTH - PAD_RIGHT} y1={y(pos)} y2={y(pos)}
                stroke="var(--border)" strokeWidth={1}
              />
              <text
                x={PAD_LEFT - 8} y={y(pos) + 3}
                textAnchor="end" fontSize={9} fill="var(--muted-foreground)"
              >
                P{pos}
              </text>
            </g>
          ))}

          {map.rows.filter((r) => !r.is_player).map((r) => (
            <path
              key={r.vehicle_idx}
              d={path(r.positions)}
              fill="none" stroke="var(--muted-foreground)"
              strokeWidth={1} opacity={0.28}
            />
          ))}

          {player && (
            <path
              d={path(player.positions)}
              fill="none" stroke="var(--primary)" strokeWidth={2.5}
              strokeLinejoin="round"
            />
          )}

          <text
            x={PAD_LEFT} y={HEIGHT - 8}
            fontSize={9} fill="var(--muted-foreground)"
          >
            круг {laps[0]}
          </text>
          <text
            x={WIDTH - PAD_RIGHT} y={HEIGHT - 8} textAnchor="end"
            fontSize={9} fill="var(--muted-foreground)"
          >
            круг {laps[laps.length - 1]}
          </text>
        </svg>
      </div>

      <p className="mt-2 text-[11px] text-muted-foreground">
        Позиции сняты в момент, когда линию пересекал ты — соперники в этот
        момент могли быть на другом круге. Жёлтым отмечены твои пит-стопы.
      </p>
    </Panel>
  )
}
