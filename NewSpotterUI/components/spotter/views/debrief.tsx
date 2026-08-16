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

// Причина потери коротким словом. Два источника в одном словаре: срывы
// (core/coach_ai/slip.py) и отклонения техники от эталона (compare.py). Полная
// формулировка приезжает с бэкенда в `evidence` — здесь только ярлык.
const _CAUSE_LABELS: Record<string, string> = {
  lockup:     "блокировка",
  wheelspin:  "пробуксовка",
  understeer: "снос",
  oversteer:  "занос",
  offtrack:   "выезд",
  brake:      "раннее торможение",
  min_speed:  "медленный апекс",
  throttle:   "поздний газ",
}

/** 92 400 → «1:32,40». Формат тот же, что в core/coach_ai/lesson.py — но там
 *  он для текста вердикта и архива, здесь для чисел на экране. */
function lapTime(ms: number | null | undefined): string {
  if (ms == null || ms <= 0) return "—"
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  const hundredths = Math.floor((ms % 1000) / 10)
  const pad = (n: number) => String(n).padStart(2, "0")
  return minutes > 0
    ? `${minutes}:${pad(seconds)},${pad(hundredths)}`
    : `${seconds},${pad(hundredths)}`
}

/** 420 → «0,42 с», 1000 → «1 с». Без хвостовых нулей: «0,40 с» читается как
 *  точность, которой у замера нет.
 *
 *  Нули снимаются ОДНИМ выражением, вместе с осиротевшей запятой. Прежняя пара
 *  `.replace(/0$/,"").replace(/\.$/,"")` убирала ровно один символ, поэтому
 *  целые секунды давали «1,0 с» — при том что тот же вердикт, отформатированный
 *  на бэкенде (`core/coach_ai/lesson.py::_sec`, там `.rstrip("0").rstrip(".")`),
 *  печатает «1 с». Два разных вида одного числа стояли на экране рядом. */
function seconds(ms: number | null | undefined): string {
  if (ms == null) return "—"
  const text = (Math.abs(ms) / 1000).toFixed(2).replace(/\.?0+$/, "")
  return `${(text || "0").replace(".", ",")} с`
}

export function DebriefView({ state }: { state: SpotterState | null }) {
  const t = state?.telemetry
  const coach = state?.coach_ai
  const topCorners = coach?.top_corners ?? []
  const referenceDeltas = coach?.reference_deltas ?? []
  const garage = coach?.garage
  const health = coach?.health ?? null
  const fieldPace = state?.field_pace ?? null
  const lesson = coach?.lesson ?? null
  // Работа берётся из разбора, а не из соседнего поля: в архиве живёт только
  // `lesson`, и экран, читающий файл заезда, обязан показать то же самое.
  const focus = lesson?.focus ?? coach?.focus ?? null
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

      {/* Урок (фаза 4) — вердикт сессии, а не таблица.
          Стоит первым и на всю ширину сознательно: до него дебриф показывал
          цифры (консистентность, слабый сектор, счётчик ошибок), из которых
          пилот сам должен был сделать вывод. Три вопроса, на которые он
          отвечает: сколько осталось в круге, где именно и что делать дальше.
          Блок отсутствует целиком, пока данных нет — прочерк читается как
          поломка. */}
      {lesson && (
        <Panel label="Урок" action={
          <div className="flex items-center gap-1.5">
            <Target className="h-3 w-3 text-muted-foreground" />
            <span className="label-mono text-[10px] text-muted-foreground">
              {focus ? `в работе: поворот ${focus.corner_id}` : "разбор сессии"}
            </span>
          </div>
        }>
          <div className="grid grid-cols-3 gap-5">
            <Readout label="ЛУЧШИЙ КРУГ" value={lapTime(lesson.best_lap_ms)} />
            <Readout
              label="ПОТЕНЦИАЛ"
              value={lapTime(lesson.potential_ms)}
              accent={lesson.potential_ms != null}
            />
            <Readout label="ЗАПАС" value={seconds(lesson.gain_ms)} />
          </div>

          <p className="mt-3 text-xs leading-relaxed text-foreground/90">
            {lesson.headline}
          </p>

          {/* Куда ушло время — в миллисекундах и долях, а не по счётчику
              срывов: три блокировки в медленной шпильке могут стоить меньше
              одной ошибки на быстром выходе. */}
          {lesson.losses.length > 0 && (
            <div className="mt-4 flex flex-col gap-2">
              {lesson.losses.map((loss) => (
                <div key={loss.corner_id} className="rounded-md bg-secondary/60 px-3 py-2.5">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-xs font-medium text-foreground">
                      Поворот {loss.corner_id}
                      {loss.cause && (
                        <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                          {_CAUSE_LABELS[loss.cause] ?? loss.cause}
                        </span>
                      )}
                    </span>
                    <span className="label-mono text-[11px] text-foreground/90">
                      {seconds(loss.cost_ms)}
                      <span className="ml-2 text-muted-foreground">
                        {Math.round(loss.share * 100)}%
                      </span>
                    </span>
                  </div>
                  {/* Доля — полоской: три числа в столбик сравнивать глазами
                      дольше, чем три полоски. */}
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-background/60">
                    <div
                      className="h-full rounded-full bg-primary/70"
                      style={{ width: `${Math.min(100, Math.round(loss.share * 100))}%` }}
                    />
                  </div>
                  {loss.evidence && (
                    <p className="mt-1.5 text-[11px] text-muted-foreground">{loss.evidence}</p>
                  )}
                </div>
              ))}
              {lesson.concentration < 0.99 && (
                <p className="text-[11px] text-muted-foreground">
                  Остальное — {seconds(Math.round(lesson.total_loss_ms * (1 - lesson.concentration)))}
                  {" — размазано по кругу."}
                </p>
              )}
            </div>
          )}

          {/* Работа сессии: видно, помогает ли то, что пилот меняет. Без этого
              он не знает, работает ли изменение, и через два заезда перестаёт
              слушать. */}
          {focus && (
            <div className="mt-4 rounded-md border border-primary/30 bg-primary/5 px-3 py-2.5">
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-xs font-medium text-foreground">
                  В работе: поворот {focus.corner_id}
                  <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                    {focus.status === "improving" ? "получается" : "работаем"}
                  </span>
                </span>
                <span className="label-mono text-[11px] text-foreground/90">
                  {seconds(focus.baseline_ms)} → {seconds(focus.current_ms)}
                  {focus.gain_ms > 0 && (
                    <span className="ml-2 text-primary">−{seconds(focus.gain_ms)}</span>
                  )}
                </span>
              </div>
              {focus.evidence && (
                <p className="mt-1 text-[11px] text-muted-foreground">{focus.evidence}</p>
              )}
            </div>
          )}

          {/* Одна вещь на следующий раз. Не список из семи пунктов, который
              никто не выполнит. */}
          {lesson.next_step && (
            <p className="mt-4 rounded-md bg-secondary/60 px-3 py-2.5 text-xs leading-relaxed text-foreground/90">
              {lesson.next_step}
            </p>
          )}

          {/* Прогресс с прошлого визита — единственное, ради чего пилот вообще
              тренируется. Появляется только на знакомой трассе. */}
          {lesson.progress && (
            <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
              {lesson.progress.text}
            </p>
          )}

          {/* Та же потеря в разрезе типов поворотов. Появляется только когда
              типов больше одного: «100% в медленных» на трассе из одних
              медленных — не вывод, а описание трассы. */}
          {(lesson.by_type?.length ?? 0) > 1 && (
            <div className="mt-4">
              <SectionLabel>Куда по характеру поворотов</SectionLabel>
              <div className="mt-2 flex flex-col gap-1.5">
                {lesson.by_type!.map((t) => (
                  <div
                    key={t.corner_type}
                    className="flex items-baseline justify-between gap-4 text-xs"
                  >
                    <span className="text-foreground">
                      {t.label}
                      <span className="ml-2 text-[11px] text-muted-foreground">
                        {t.corners} шт.
                      </span>
                    </span>
                    <span className="label-mono text-[11px] text-muted-foreground">
                      {seconds(t.cost_ms)} · {Math.round(t.share * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {lesson.potential_clamped && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              В одном из поворотов запас ограничен двумя секундами: разница с
              собственным лучшим проездом там слишком велика, чтобы обещать её
              на круге.
            </p>
          )}
        </Panel>
      )}

      {/* В поле — где пилот относительно ВСЕГО пелотона по секторам.
          Соседний вопрос к «Уроку», а не тот же: коуч меряет пилота против
          него самого и доходит до поворота и причины, здесь — против них, и
          разрешение грубее. Первое лечится техникой, второе бывает и вопросом
          машины, поэтому блоки раздельные. */}
      {fieldPace && fieldPace.sectors.length > 0 && (
        <Panel label="В поле" action={
          <div className="flex items-center gap-1.5">
            <Users className="h-3 w-3 text-muted-foreground" />
            <span className="label-mono text-[10px] text-muted-foreground">
              {fieldPace.lap_rank != null
                ? `по кругу ${fieldPace.lap_rank} из ${fieldPace.lap_field_size}`
                : "по секторам"}
            </span>
          </div>
        }>
          <div className="flex flex-col gap-2">
            {fieldPace.sectors.map((s) => {
              const worst = fieldPace.weakest?.sector === s.sector
              return (
                <div
                  key={s.sector}
                  className={`rounded-md px-3 py-2.5 ${
                    worst ? "border border-primary/30 bg-primary/5" : "bg-secondary/60"
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-xs font-medium text-foreground">
                      Сектор {s.sector}
                      <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                        {s.rank} из {s.field_size}
                      </span>
                    </span>
                    <span className="label-mono text-[11px] text-foreground/90">
                      {s.gap_ms > 0 ? `+${seconds(s.gap_ms)}` : "лучший в поле"}
                    </span>
                  </div>
                  {/* Кто держит лучший сектор — только на экране: в эфире имя
                      потребовало бы падежа, а падеж свободной строкой банк
                      фраз не выражает. */}
                  {s.best_holder && s.gap_ms > 0 && (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Лучший — {s.best_holder}: {lapTime(s.best_ms)}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
          {fieldPace.weakest ? (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Больше всего до поля уходит в {fieldPace.weakest.sector}-м секторе —
              {" "}{seconds(fieldPace.weakest.gap_ms)} за круг.
            </p>
          ) : (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Ни в одном секторе отрыв до поля не превышает десятой доли секунды.
            </p>
          )}
        </Panel>
      )}

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

          {/* Почему коуч молчит.
              Молчащий коуч выглядит одинаково при выключенном тумблере,
              неповторяющейся ошибке, не доехавшей телеметрии движения и
              завышенном пороге — четыре разных диагноза с четырьмя разными
              действиями, и раньше различить их можно было только чтением кода.
              Блок появляется, только когда есть что объяснить: у говорящего
              коуча `reason` пуст, и сеять сомнение в работающей функции
              незачем. */}
          {health?.reason && (
            <div className={`mt-3 rounded-md px-3 py-2.5 ${
              health.signal === "ok" || health.signal === "warming_up"
                ? "bg-secondary/60"
                : "border border-amber-500/40 bg-amber-500/5"
            }`}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="label-mono text-[10px] text-muted-foreground">
                  ПОЧЕМУ МОЛЧИТ
                </span>
                <span className="label-mono text-[10px] text-muted-foreground">
                  срывов {health.mistakes} · сказано {health.spoken}
                </span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-foreground/90">
                {health.reason}
              </p>
            </div>
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
          || (garage?.hints?.length ?? 0) > 0 || garage?.balance) && (
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
              {/* Подпись баланса: снос на медленных и снос на быстрых имеют
                  РАЗНЫЕ причины — прижимная сила растёт с квадратом скорости.
                  Числа здесь не называются намеренно: величина зависит от
                  трассы и от того, что уже стоит в сетапе. */}
              {garage?.balance && (
                <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2.5">
                  <p className="text-xs font-medium text-foreground">
                    {garage.balance.advice}
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {garage.balance.evidence}
                  </p>
                </div>
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
