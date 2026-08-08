"use client"

import { useState } from "react"
import { Panel, Readout, SectionLabel } from "../ui"
import type { SpotterState } from "@/lib/api"
import { generateStory, replayStory } from "@/lib/api"
import { feedToEvent } from "@/lib/feed"
import { RaceMapPanel } from "./race-map-panel"
import { Trophy, TrendingUp, Target, Users, Radio, BookOpen, Gauge, Wrench } from "lucide-react"

/** «12 / 58» → [12, 58]. Формат строит core/ui_state.py::update_telemetry;
 *  тотал бывает «—», когда игра ещё не сообщила дистанцию. */
function parseLap(lap: string | undefined): [number | null, number | null] {
  const match = /^\s*(\d+)\s*\/\s*(\d+|—)\s*$/.exec(lap ?? "")
  if (!match) return [null, null]
  return [Number(match[1]), match[2] === "—" ? null : Number(match[2])]
}

const _TYRE_ADVICE_LABELS: Record<string, string> = {
  ok:    "Норма",
  save:  "Беречь",
  cliff: "Обрыв",
  push:  "Давить",
}

// Внимание: у Коуча и у Стратегии РАЗНЫЕ словари про резину. Коуч отдаёт совет
// (core/race_ai — ok/save/cliff/push), Стратегия — стадию износа
// (core/strategy_ai/tyres.py::tyre_status — fresh/worn/critical/cliff/unknown).
// Совпадает только слово "cliff", и раньше оно переводилось лишь в одной панели,
// а во второй показывалось как сырое "CLIFF".
const _TYRE_STATUS_LABELS: Record<string, string> = {
  fresh:    "Свежие",
  worn:     "Изношены",
  critical: "Критично",
  cliff:    "Обрыв",
  unknown:  "—",
}

const _FUEL_LABELS: Record<string, string> = {
  attack: "Атака",
  normal: "Норма",
  save:   "Экономия",
}

const _TREND_LABELS: Record<string, string> = {
  rising:  "↑ замедл.",
  falling: "↓ ускор.",
  stable:  "Стабильно",
}

// Виды ошибок пилотажа (core/coach_ai/slip.py). Отдельный словарь от советов
// про резину выше: там совет, здесь причина потери времени.
const _MISTAKE_LABELS: Record<string, string> = {
  lockup:     "блокировка",
  wheelspin:  "пробуксовка",
  understeer: "снос",
  oversteer:  "занос",
  offtrack:   "выезд",
}

// Колёса в порядке пакетов F1 — RL, RR, FL, FR. Женский род намеренно: речь
// о шине, а не о колесе («передняя левая изношена»).
const _WHEEL_RU: Record<string, string> = {
  rl: "Задняя левая",
  rr: "Задняя правая",
  fl: "Передняя левая",
  fr: "Передняя правая",
}

const _STYLE_LABELS: Record<string, string> = {
  consistent: "стабильный",
  aggressive:  "агрессивный",
  charging:    "↑ прогресс",
  fading:      "↓ спад",
}

export function DebriefView({ state }: { state: SpotterState | null }) {
  const t = state?.telemetry
  const coach = state?.coach_ai
  const topCorners = coach?.top_corners ?? []
  const referenceDeltas = coach?.reference_deltas ?? []
  const garage = coach?.garage
  const strategy = state?.strategy_ai
  const rivals = state?.rivals
  const events = (state?.feed ?? []).slice(0, 5).map(feedToEvent)
  const story = state?.race_story ?? null

  // «Сгенерировать итог» зовёт engine.generate_story_now(), у которого нет
  // гейта завершённости: посреди гонки он напишет уверенный текст в прошедшем
  // времени про «итоговый результат». Данных о финише у бэкенда в /api/state
  // нет, поэтому судим по кругу — этого достаточно, чтобы предупредить.
  const [currentLap, totalLaps] = parseLap(t?.lap)
  const raceInProgress =
    Boolean(state?.connected) &&
    currentLap != null &&
    (totalLaps == null || currentLap < totalLaps)
  const [confirmEarly, setConfirmEarly] = useState(false)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        <Trophy className="h-5 w-5 text-primary" />
        <h1 className="font-heading text-xl font-semibold text-foreground">Дебриф гонки</h1>
        <span className="label-mono text-[10px] text-muted-foreground">
          {state?.connected ? "СЕССИЯ АКТИВНА" : "ПОСЛЕ ГОНКИ"}
        </span>
      </div>

      {/* Race Story */}
      <Panel label="История гонки" action={
        <div className="flex items-center gap-1.5">
          <BookOpen className="h-3 w-3 text-muted-foreground" />
          <span className="label-mono text-[10px] text-muted-foreground">
            {story ? "ИТОГ ГОТОВ" : "НЕТ ИТОГА"}
          </span>
        </div>
      }>
        {story ? (
          <div className="flex flex-col gap-3">
            {/* Шаблонный итог читается так же уверенно, как написанный моделью,
                но беднее фактами — без пометки отличить нельзя. */}
            {story.source === "fallback" && (
              <p className="rounded-md border border-border bg-secondary/50 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
                Итог собран по шаблону: в момент финиша текстовый AI был недоступен.
                Факты верные, но без разбора и оценок — можно перегенерировать, когда
                связь вернётся.
              </p>
            )}
            <p className="text-sm leading-relaxed text-foreground/90">{story.text}</p>
            <button
              onClick={() => { void replayStory() }}
              className="self-start rounded-md bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90 hover:bg-secondary"
            >
              Переозвучить
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-start gap-2">
            <p className="text-xs text-muted-foreground">
              Итог появится автоматически после финиша гонки, квалификации или практики.
            </p>
            {raceInProgress && (
              <p className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-[11px] leading-relaxed text-warning">
                Сессия ещё идёт{totalLaps != null ? ` — круг ${currentLap} из ${totalLaps}` : ""}.
                Итог всё равно будет написан в прошедшем времени, как о законченной гонке,
                и озвучен вслух.
              </p>
            )}
            {raceInProgress && confirmEarly ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    void generateStory()
                    setConfirmEarly(false)
                  }}
                  className="rounded-md bg-warning/15 px-3 py-1.5 text-xs text-warning hover:bg-warning/25"
                >
                  Всё равно сгенерировать
                </button>
                <button
                  onClick={() => setConfirmEarly(false)}
                  className="rounded-md bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90 hover:bg-secondary"
                >
                  Отмена
                </button>
              </div>
            ) : (
              <button
                onClick={() => {
                  if (raceInProgress) setConfirmEarly(true)
                  else void generateStory()
                }}
                className="rounded-md bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90 hover:bg-secondary"
              >
                Сгенерировать итог
              </button>
            )}
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Result */}
        <Panel label="Итог сессии" action={
          <div className="flex items-center gap-1.5">
            <Trophy className="h-3 w-3 text-muted-foreground" />
            <span className="label-mono text-[10px] text-muted-foreground">F1 25</span>
          </div>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout
              label="ПОЗИЦИЯ"
              value={t?.position ?? "—"}
              accent={t?.position === "1"}
            />
            <Readout label="КРУГ" value={t?.lap ?? "—"} />
            <Readout label="СКОРОСТЬ" value={t?.speed ?? "—"} unit="км/ч" />
            <Readout label="ТОПЛИВО" value={t?.fuel ?? "—"} />
          </div>
        </Panel>

        {/* Coach Report */}
        <Panel label="Коуч" action={
          <div className="flex items-center gap-1.5">
            <Target className="h-3 w-3 text-muted-foreground" />
            <span className="label-mono text-[10px] text-muted-foreground">
              {coach?.lap_count ? `${coach.lap_count} кр.` : "нет данных"}
            </span>
          </div>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout
              label="КОНСИСТ."
              value={coach?.consistency_score != null
                ? `${Math.round(coach.consistency_score * 100)}%`
                : "—"}
            />
            <Readout
              label="ДЕЛЬТА"
              value={coach?.pace_delta_ms != null
                ? (coach.pace_delta_ms >= 0
                    ? `+${(coach.pace_delta_ms / 1000).toFixed(2)}с`
                    : `${(coach.pace_delta_ms / 1000).toFixed(2)}с`)
                : "—"}
            />
            <Readout
              label="СЛАБ. СЕК."
              value={coach?.weak_sector != null ? `S${coach.weak_sector}` : "—"}
            />
            <Readout
              label="ШИНЫ"
              value={_TYRE_ADVICE_LABELS[coach?.tyre_advice ?? ""] ?? (coach?.tyre_advice?.toUpperCase() ?? "—")}
            />
          </div>
          {coach?.advice && (
            <p className="mt-3 rounded-md bg-secondary/60 px-3 py-2.5 text-xs leading-relaxed text-foreground/90">
              {coach.advice}
            </p>
          )}
          {!coach?.lap_count && (
            <p className="mt-2 text-xs text-muted-foreground">
              Данные коуча появятся после первых 3 кругов.
            </p>
          )}
        </Panel>

        {/* Где теряется время — по поворотам, а не по секторам. Секция
            появляется только при непустом топе: сессия без ошибок не повод
            рисовать пустую таблицу. */}
        {topCorners.length > 0 && (
          <Panel label="Где теряется время" action={
            <div className="flex items-center gap-1.5">
              <Gauge className="h-3 w-3 text-muted-foreground" />
              <span className="label-mono text-[10px] text-muted-foreground">
                {coach?.mistake_count ?? 0} ош.
              </span>
            </div>
          }>
            <div className="flex flex-col gap-2.5">
              {topCorners.map((c) => (
                <div
                  key={c.corner_id ?? "none"}
                  className="flex items-baseline justify-between gap-4 rounded-md bg-secondary/60 px-3 py-2.5"
                >
                  <span className="text-xs font-medium text-foreground">
                    {c.corner_name ?? "Вне поворота"}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {Object.entries(c.kinds)
                      .sort((a, b) => b[1] - a[1])
                      .map(([kind, n]) => `${_MISTAKE_LABELS[kind] ?? kind} ×${n}`)
                      .join(" · ")}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              Считаются все ошибки, включая одиночные. Вживую инженер говорит
              только о повторяющихся.
            </p>
          </Panel>
        )}

        {/* Против эталонного круга. Показываем СЫРЫЕ дельты: инженер вживую
            говорит только про локальные потери, а здесь пилот должен видеть и
            общий сдвиг — по нему понятно, что дело в топливе, а не в руках. */}
        {referenceDeltas.length > 0 && (
          <Panel label="Против эталона" action={
            <span className="label-mono text-[10px] text-muted-foreground">
              {coach?.reference_source === "career" ? "лучший на трассе" : "лучший в сессии"}
            </span>
          }>
            <div className="flex flex-col gap-1.5">
              {referenceDeltas.map((d) => (
                <div
                  key={d.corner_id}
                  className="flex items-baseline justify-between gap-4 text-xs"
                >
                  <span className="text-foreground">
                    {d.corner_name ?? `Поворот ${d.corner_id}`}
                  </span>
                  <span className="label-mono text-[11px] text-muted-foreground">
                    {d.duration_ms == null
                      ? "—"
                      : `${d.duration_ms >= 0 ? "+" : ""}${(d.duration_ms / 1000).toFixed(2)}с`}
                    {d.brake_delta != null &&
                      ` · тормоз ${d.brake_delta >= 0 ? "+" : ""}${Math.round(d.brake_delta)}м`}
                    {d.min_speed_delta != null &&
                      ` · апекс ${d.min_speed_delta >= 0 ? "+" : ""}${Math.round(d.min_speed_delta)}км/ч`}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        )}

        {/* Гараж (фаза 3). Показывается, когда есть что показать: перекос
            резины или советы. Голосом это не звучит нигде — сетап посреди
            заезда не меняется. */}
        {(garage?.tyre_load?.worst_wheel || garage?.tyre_load?.hottest_wheel
          || (garage?.hints?.length ?? 0) > 0) && (
          <Panel label="Гараж" action={
            <div className="flex items-center gap-1.5">
              <Wrench className="h-3 w-3 text-muted-foreground" />
              <span className="label-mono text-[10px] text-muted-foreground">
                {garage?.setup?.brake_bias != null
                  ? `баланс ${String(garage.setup.brake_bias)}%`
                  : "сетап —"}
              </span>
            </div>
          }>
            <div className="flex flex-col gap-2.5">
              {garage?.tyre_load?.worst_wheel && (
                <p className="text-xs leading-relaxed text-foreground/90">
                  {_WHEEL_RU[garage.tyre_load.worst_wheel] ?? garage.tyre_load.worst_wheel}
                  {" изношена на "}
                  {garage.tyre_load.wear_spread_pct.toFixed(0)}
                  {"% сильнее парной по оси."}
                </p>
              )}
              {garage?.tyre_load?.hottest_wheel && (
                <p className="text-xs leading-relaxed text-foreground/90">
                  {_WHEEL_RU[garage.tyre_load.hottest_wheel] ?? garage.tyre_load.hottest_wheel}
                  {" горячее самой холодной на "}
                  {garage.tyre_load.temp_spread_c.toFixed(0)}
                  {"°."}
                </p>
              )}
              {garage?.hints?.map((h) => (
                <div key={h.parameter} className="rounded-md bg-secondary/60 px-3 py-2.5">
                  <p className="text-xs font-medium text-foreground">{h.advice}</p>
                  {/* Основание показывается ВСЕГДА и рядом: пилот должен иметь
                      возможность не согласиться, посмотрев на те же цифры. */}
                  <p className="mt-1 text-[11px] text-muted-foreground">{h.evidence}</p>
                </div>
              ))}
            </div>
          </Panel>
        )}

        {/* Карта гонки — на всю ширину под сеткой панелей: спагетти-график в
            половину экрана нечитаем. Рендерится сам собой пустым, если кругов
            меньше двух. */}
        <div className="lg:col-span-2">
          <RaceMapPanel />
        </div>

        {/* Strategy */}
        <Panel label="Стратегия" action={
          <div className="flex items-center gap-1.5">
            <TrendingUp className="h-3 w-3 text-muted-foreground" />
            <span className="label-mono text-[10px] text-muted-foreground">
              {strategy?.mode ?? "—"}
            </span>
          </div>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout
              label="ДЕЙСТВИЕ"
              value={strategy?.action?.toUpperCase() ?? "—"}
            />
            <Readout
              label="УВЕРЕН."
              value={strategy?.confidence != null
                ? `${Math.round(strategy.confidence * 100)}%`
                : "—"}
            />
            <Readout
              label="ИЗНОС ШИН"
              value={_TYRE_STATUS_LABELS[strategy?.tyre_status ?? ""] ?? "—"}
            />
            <Readout
              label="ТОПЛИВО"
              value={_FUEL_LABELS[strategy?.fuel_mode ?? "normal"] ?? "—"}
            />
            <Readout
              label="ТРЕНД"
              value={_TREND_LABELS[strategy?.pace_trend ?? "stable"] ?? "—"}
            />
            <Readout
              label="СОВЕТ"
              value={strategy?.advice ?? "—"}
            />
          </div>
          {(strategy?.tyre_status === "cliff" || coach?.tyre_advice === "cliff") && (
            <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
              «Обрыв» — резина прошла точку, после которой сцепление падает не плавно,
              а скачком: круги начинают резко проседать даже при том же пилотаже.
            </p>
          )}
        </Panel>

        {/* Rivals */}
        <Panel label="Соперники" action={
          <div className="flex items-center gap-1.5">
            <Users className="h-3 w-3 text-muted-foreground" />
            <span className="label-mono text-[10px] text-muted-foreground">
              {rivals?.rival_count ? `${rivals.rival_count} всего` : "—"}
            </span>
          </div>
        }>
          <div className="grid grid-cols-2 gap-5 mb-4">
            <Readout label="ВСЕГО" value={rivals?.rival_count != null ? String(rivals.rival_count) : "—"} />
            <Readout label="РЯДОМ" value={rivals?.nearby_count != null ? String(rivals.nearby_count) : "—"} />
          </div>
          {rivals?.rivals && rivals.rivals.filter((r) => r.nearby).length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {rivals.rivals
                .filter((r) => r.nearby)
                .slice(0, 3)
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
                    {r.pit_count > 0 && (
                      <span className="label-mono text-[9px] text-primary">
                        PIT ×{r.pit_count}
                      </span>
                    )}
                  </li>
                ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">Нет соперников рядом.</p>
          )}
        </Panel>
      </div>

      {/* Events */}
      <Panel label="Последние события" action={
        <div className="flex items-center gap-1.5">
          <Radio className="h-3 w-3 text-muted-foreground" />
          <span className="label-mono text-[10px] text-muted-foreground">
            {events.length > 0 ? `${events.length} событий` : "—"}
          </span>
        </div>
      }>
        {events.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {events.map((e) => (
              <li key={e.id} className="rounded-md bg-secondary/60 px-3 py-2.5">
                <div className="flex items-center justify-between">
                  <span className="label-mono text-[9px] text-primary">{e.title}</span>
                  <span className="font-mono text-[9px] text-muted-foreground">{e.time}</span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-foreground/90 line-clamp-2">{e.text}</p>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <SectionLabel>Нет событий</SectionLabel>
            <p className="text-xs text-muted-foreground">Появятся во время гонки</p>
          </div>
        )}
      </Panel>
    </div>
  )
}
