"use client"

import type React from "react"
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Radio, Mic, AudioLines } from "lucide-react"

import { clearRadioHistory, saveSettings } from "@/lib/api"
import type {
  RadioActiveMessage,
  RadioHistoryEntry,
  RadioSource,
  RadioUrgency,
  SettingsState,
  SpotterState,
} from "@/lib/api"
import { Panel, SectionLabel, Slider, Toggle } from "@/components/spotter/ui"
import { cn } from "@/lib/utils"

/* ────────────────────────────────────────────────────────────────────────────
   Словари отображения.

   Пользователь не должен видеть внутренние коды (критерий готовности №11),
   поэтому канал, срочность и причина отмены переводятся здесь. Коды каналов
   держим трёхбуквенными: в плотной ленте колонка обязана быть одной ширины,
   иначе строки перестают сканироваться взглядом.
   ──────────────────────────────────────────────────────────────────────────── */

const SOURCE_CODE: Record<RadioSource, string> = {
  spotter: "SPT",
  engineer: "ENG",
  commentator: "COM",
  driver: "YOU",
}

const SOURCE_NAME: Record<RadioSource, string> = {
  spotter: "Споттер",
  engineer: "Инженер",
  commentator: "Комментатор",
  driver: "Пилот",
}

const URGENCY_LABEL: Record<RadioUrgency, string> = {
  critical: "CRIT",
  high: "HIGH",
  normal: "NORM",
  low: "LOW",
}

// Красный только для критического, жёлтый для предупреждения, зелёный для
// нормы — палитра из §14 брифа, без собственных цветов.
const URGENCY_TONE: Record<RadioUrgency, string> = {
  critical: "text-destructive",
  high: "text-warning",
  normal: "text-muted-foreground",
  low: "text-muted-foreground/60",
}

const URGENCY_EDGE: Record<RadioUrgency, string> = {
  critical: "bg-destructive",
  high: "bg-warning",
  normal: "bg-primary",
  low: "bg-muted-foreground/40",
}

const STATE_LABEL: Record<string, string> = {
  queued: "в очереди",
  synthesizing: "синтез",
  playing: "звучит",
  completed: "прозвучало",
  cancelled: "отменено",
  interrupted: "прервано",
}

// Причины отмены (core/radio/message.py::RadioCancelReason) — человеческим
// текстом. Без этого в ленте появились бы `situation_ended` и `target_changed`.
const CANCEL_REASON: Record<string, string> = {
  expired: "устарело",
  superseded: "заменено новым",
  situation_ended: "ситуация закончилась",
  target_changed: "соперник сменился",
  data_unavailable: "нет данных",
  invalid_data: "данные недостоверны",
  queue_evicted: "вытеснено",
  session_reset: "новая сессия",
  flashback: "перемотка",
  stopped: "остановлено",
  resolve_failed: "сбой подстановки",
}

const CHANNEL_STATUS: Record<string, string> = {
  idle: "Ожидание",
  listening: "Слушаю пилота",
  recognizing: "Распознаю",
  thinking: "Проверяю данные",
  queued: "В очереди",
  synthesizing: "Синтез",
  playing: "В эфире",
  completed: "Ожидание",
  cancelled: "Ожидание",
  interrupted: "Ожидание",
}

type ChannelFilter = "all" | RadioSource
// «Отменено» и «Прервано» — РАЗНЫЕ исходы, и объединять их нельзя (ТЗ §16):
// отменённое пилот не слышал вовсе, прерванное он услышал наполовину. При
// разборе гонки это ровно та разница, ради которой открывают фильтр.
type OutcomeFilter = "all" | "spoken" | "cancelled" | "interrupted"

const CHANNEL_FILTERS: { id: ChannelFilter; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "engineer", label: "Инженер" },
  { id: "spotter", label: "Споттер" },
  { id: "commentator", label: "Комментатор" },
  { id: "driver", label: "Пилот" },
]

const OUTCOME_FILTERS: { id: OutcomeFilter; label: string }[] = [
  { id: "all", label: "Всё" },
  { id: "spoken", label: "Прозвучало" },
  { id: "cancelled", label: "Отменено" },
  { id: "interrupted", label: "Прервано" },
]

const DROPPED_STATES = new Set(["cancelled", "interrupted"])

function formatClock(seconds: number): string {
  if (!seconds) return "--:--:--"
  const date = new Date(seconds * 1000)
  return date.toLocaleTimeString("ru-RU", { hour12: false })
}

/* ────────────────────────────────────────────────────────────────────────────
   Текущая передача — единственный акцентный элемент экрана.

   Всё остальное намеренно тихое: в гонке взгляд ищет одну строку, и она должна
   находиться без чтения. Левая кромка кодирует срочность цветом, поэтому
   критическую реплику видно периферийным зрением.
   ──────────────────────────────────────────────────────────────────────────── */

function Waveform({ live }: { live: boolean }) {
  return (
    <div className="flex h-6 items-center gap-[2px]" aria-hidden>
      {Array.from({ length: 20 }, (_, index) => (
        <span
          key={index}
          className={cn(
            "w-[2px] rounded-full bg-primary/70",
            live && "overlay-wave-bar",
          )}
          style={{
            height: `${6 + ((index * 7) % 16)}px`,
            animationDelay: `${index * -40}ms`,
          }}
        />
      ))}
    </div>
  )
}

function ActiveTransmission({
  message,
  pttState,
  driverText,
}: {
  message: RadioActiveMessage | null
  pttState: string
  driverText: string | null
}) {
  const listening = pttState === "listening"
  const busy = listening || pttState === "recognizing" || pttState === "thinking"
  const live = busy || message?.state === "playing"
  const urgency: RadioUrgency = message?.urgency ?? "normal"

  // Пилот жмёт PTT — показываем его сторону разговора, пока инженер не ответил.
  const showDriver = busy && !message

  // Имя и роль приходят из профиля бэкенда (core/radio/speakers.py) — в
  // компоненте их быть не должно (ТЗ §5). `speaker` (короткая подпись канала)
  // остаётся фолбэком для строк, пришедших без профиля.
  const speaker = showDriver
    ? SOURCE_NAME.driver
    : message
      ? message.speaker_name || message.speaker
      : "Радиоканал"
  const role = showDriver ? "DRIVER" : message?.speaker_role ?? null

  const body = showDriver
    ? driverText || (listening ? "Слушаю…" : "Проверяю данные…")
    : message?.text || "Канал свободен."

  return (
    <div className="flex overflow-hidden rounded-lg border border-border bg-card">
      <span
        className={cn("w-1 shrink-0", live ? URGENCY_EDGE[urgency] : "bg-border")}
        aria-hidden
      />
      <div className="min-w-0 flex-1 p-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-2.5">
            {showDriver ? (
              <Mic className="h-4 w-4 shrink-0 text-primary" />
            ) : (
              <Radio
                className={cn(
                  "h-4 w-4 shrink-0",
                  live ? "text-primary" : "text-muted-foreground",
                )}
              />
            )}
            <span className="label-mono truncate text-[11px] text-foreground">
              {speaker}
            </span>
            {role && (
              <span className="label-mono shrink-0 text-[10px] text-muted-foreground">
                {role}
              </span>
            )}
            {message && (
              <>
                <span className="text-muted-foreground/40" aria-hidden>
                  ·
                </span>
                <span
                  className={cn(
                    "label-mono text-[10px]",
                    URGENCY_TONE[message.urgency],
                  )}
                >
                  {URGENCY_LABEL[message.urgency]}
                </span>
                <span className="label-mono truncate text-[10px] text-muted-foreground">
                  {message.ui_title}
                </span>
              </>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-3">
            {live && <Waveform live />}
            {message && (
              <span className="label-mono tabular text-[10px] text-muted-foreground">
                {formatClock(message.created_at)}
              </span>
            )}
          </div>
        </div>

        <p
          className={cn(
            "mt-3 text-[15px] leading-snug",
            message || showDriver ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {body}
        </p>

        {message && (
          <p className="label-mono mt-2 text-[10px] text-muted-foreground">
            {STATE_LABEL[message.state] ?? message.state}
          </p>
        )}
      </div>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────────────────────
   Лента переговоров.

   React.memo на строке обязателен: /api/state опрашивается раз в секунду и
   отдаёт НОВЫЙ массив истории на каждом тике, даже когда она не менялась.
   Без мемоизации сотня строк перерисовывалась бы каждую секунду (§19 брифа).
   ──────────────────────────────────────────────────────────────────────────── */

function HistoryRow({
  time,
  source,
  urgency,
  text,
  title,
  state,
  cancelReason,
}: {
  time: string
  source: RadioSource
  urgency: RadioUrgency
  text: string
  title: string
  state: string
  cancelReason: string | null
}) {
  const dropped = DROPPED_STATES.has(state)
  const isDriver = source === "driver"

  return (
    <li className="flex items-baseline gap-3 border-b border-border/50 px-4 py-2 last:border-b-0">
      <span className="label-mono tabular shrink-0 text-[10px] text-muted-foreground/70">
        {time}
      </span>
      <span
        className={cn(
          "label-mono w-8 shrink-0 text-[10px]",
          isDriver ? "text-primary" : "text-muted-foreground",
        )}
      >
        {SOURCE_CODE[source]}
      </span>
      {/* У реплики пилота срочности нет — колонка остаётся пустой, чтобы
          сетка не разъезжалась. */}
      <span
        className={cn(
          "label-mono w-9 shrink-0 text-[10px]",
          isDriver ? "text-transparent" : URGENCY_TONE[urgency],
        )}
      >
        {isDriver ? "—" : URGENCY_LABEL[urgency]}
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "text-[13px] leading-snug",
            dropped ? "text-muted-foreground line-through" : "text-foreground",
          )}
        >
          {text}
        </span>
        {state === "interrupted" && (
          <span className="label-mono ml-2 rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[9px] text-warning">
            прервано
          </span>
        )}
        {state === "cancelled" && (
          <span className="label-mono ml-2 rounded border border-border bg-secondary px-1.5 py-0.5 text-[9px] text-muted-foreground">
            {cancelReason ? CANCEL_REASON[cancelReason] ?? "отменено" : "отменено"}
          </span>
        )}
      </span>
      <span className="label-mono hidden shrink-0 text-[9px] text-muted-foreground/50 lg:inline">
        {title}
      </span>
    </li>
  )
}

// Все пропсы — примитивы, поэтому дефолтное поверхностное сравнение memo
// работает: строка перерисуется только когда реально изменится её содержимое, а
// не на каждом секундном опросе /api/state.
const MemoHistoryRow = memo(HistoryRow)

function FilterRow<T extends string>({
  options,
  active,
  onChange,
}: {
  options: { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          className={cn(
            "label-mono rounded border px-2 py-1 text-[10px] transition-colors",
            active === option.id
              ? "border-primary/50 bg-primary/10 text-foreground"
              : "border-border bg-secondary text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

/* ──────────────────────────────────────────────────────────────────────────── */

export function TeamRadioView({
  state,
  online,
}: {
  state: SpotterState | null
  online: boolean
}) {
  const [channel, setChannel] = useState<ChannelFilter>("all")
  const [outcome, setOutcome] = useState<OutcomeFilter>("all")
  const [saveError, setSaveError] = useState(false)
  const [clearing, setClearing] = useState(false)
  // Оптимистичная правка: слайдер должен двигаться сразу, а не ждать опроса
  // /api/state раз в секунду.
  const [draft, setDraft] = useState<Partial<SettingsState>>({})

  const radio = state?.radio ?? null
  const history = radio?.history ?? []

  const settings = state?.settings
    ? ({ ...state.settings, ...draft } as SettingsState)
    : null

  const patch = useCallback(async (change: Partial<SettingsState>) => {
    setDraft((current) => ({ ...current, ...change }))
    try {
      const result = await saveSettings(change)
      // saveSettings возвращает {ok}; ok !== true обязан считаться ошибкой —
      // существующий контракт UI, см. CODEX_CLAUDE_HANDOFF.md.
      setSaveError(result.ok !== true)
      if (result.ok !== true) {
        setDraft((current) => {
          const next = { ...current }
          for (const key of Object.keys(change)) delete next[key as keyof SettingsState]
          return next
        })
      }
    } catch {
      setSaveError(true)
      setDraft((current) => {
        const next = { ...current }
        for (const key of Object.keys(change)) delete next[key as keyof SettingsState]
        return next
      })
    }
  }, [])

  const setDraftSeconds = useCallback(
    (v: number) => setDraft((c) => ({ ...c, subtitle_seconds: v })), [])
  // По сеттеру на канал: общий `setDraftVolume` писал бы обе громкости в один
  // ключ, и перетаскивание одного ползунка дёргало бы второй.
  const setDraftEngineerVolume = useCallback(
    (v: number) => setDraft((c) => ({ ...c, volume_engineer: v })), [])
  const setDraftSpotterVolume = useCallback(
    (v: number) => setDraft((c) => ({ ...c, volume_spotter: v })), [])

  const onClearHistory = useCallback(async () => {
    setClearing(true)
    try {
      await clearRadioHistory()
    } catch {
      setSaveError(true)
    } finally {
      setClearing(false)
    }
  }, [])

  // Сигнатура вместо самого массива: опрос раз в секунду отдаёт новый объект, и
  // без сравнения содержимого useMemo пересчитывался бы каждый тик, а
  // мемоизация строк не давала бы ничего.
  const signature = useMemo(
    () => history.map((entry) => `${entry.id}:${entry.state}`).join("|"),
    [history],
  )

  const rows = useMemo(() => {
    const filtered = history.filter((entry) => {
      if (channel !== "all" && entry.source !== channel) return false
      if (outcome === "spoken" && entry.state !== "completed") return false
      if (outcome === "cancelled" && entry.state !== "cancelled") return false
      if (outcome === "interrupted" && entry.state !== "interrupted") return false
      return true
    })
    // Новое снизу — тот же порядок чтения, что у ленты «События».
    return filtered.map((entry) => ({
      key: entry.id,
      time: formatClock(entry.created_at),
      source: entry.source,
      urgency: entry.urgency,
      text: entry.text,
      title: entry.title,
      state: entry.state,
      cancelReason: entry.cancel_reason,
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, channel, outcome])

  /* Автоскролл только когда пользователь у края списка: иначе ручная прокрутка
     сбрасывалась бы на каждом обновлении (§15 брифа). */
  const listRef = useRef<HTMLDivElement | null>(null)
  const atBottomRef = useRef(true)

  const onScroll = useCallback(() => {
    const node = listRef.current
    if (!node) return
    atBottomRef.current =
      node.scrollHeight - node.scrollTop - node.clientHeight < 48
  }, [])

  useEffect(() => {
    const node = listRef.current
    if (node && atBottomRef.current) {
      node.scrollTop = node.scrollHeight
    }
  }, [rows.length])

  const status = radio?.status ?? "idle"
  const ptt = radio?.ptt ?? null
  const yandexOk = state?.yandex_ok !== false
  const engine = state?.tts_active || state?.tts_engine || "—"
  const radioFx = settings?.radio_fx ?? false
  const hotkey = settings?.ptt_hotkey

  const hotkeyLabel = hotkey
    ? [
        hotkey.ctrl ? "Ctrl" : null,
        hotkey.alt ? "Alt" : null,
        hotkey.shift ? "Shift" : null,
        hotkey.key,
      ]
        .filter(Boolean)
        .join(" + ")
    : "не настроен"

  return (
    <div className="flex flex-col gap-5">
      {/* ── Верхняя строка ────────────────────────────────────────────────── */}
      <Panel
        label="Team Radio"
        action={
          <span className="label-mono text-[11px] text-foreground">
            {CHANNEL_STATUS[status] ?? status}
          </span>
        }
        bodyClassName="p-0"
      >
        <dl className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
          <MetaCell label="Голос" value={state?.speaker || "—"} />
          <MetaCell
            label="Движок"
            value={engine}
            tone={yandexOk ? undefined : "warning"}
            note={yandexOk ? undefined : "Yandex недоступен — играет Piper"}
          />
          <MetaCell label="Радио-эффект" value={radioFx ? "Включён" : "Выключен"} />
          <MetaCell label="Кнопка связи" value={hotkeyLabel} />
        </dl>
      </Panel>

      {/* ── Текущая передача ──────────────────────────────────────────────── */}
      <div>
        <SectionLabel className="mb-2.5">Текущая передача</SectionLabel>
        {!online ? (
          <EmptyState text="Сервер недоступен. Проверьте, запущено ли приложение." />
        ) : !state ? (
          <EmptyState text="Загружаю состояние радио…" />
        ) : (
          <ActiveTransmission
            message={radio?.active_message ?? null}
            pttState={ptt?.state ?? "idle"}
            driverText={ptt?.driver_text ?? null}
          />
        )}
        {ptt?.state === "error" && ptt.error && (
          <p className="mt-2 text-[12px] text-destructive">{ptt.error}</p>
        )}
      </div>

      {/* ── История ───────────────────────────────────────────────────────── */}
      <Panel
        label="Переговоры"
        action={
          radio?.repeatable ? (
            <span className="label-mono text-[10px] text-muted-foreground">
              «повтори» → {radio.repeatable.slice(0, 40)}
              {radio.repeatable.length > 40 ? "…" : ""}
            </span>
          ) : undefined
        }
        bodyClassName="p-0"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
          <FilterRow options={CHANNEL_FILTERS} active={channel} onChange={setChannel} />
          <FilterRow options={OUTCOME_FILTERS} active={outcome} onChange={setOutcome} />
        </div>

        {rows.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <AudioLines className="mx-auto mb-2 h-5 w-5 text-muted-foreground/40" />
            <p className="text-[13px] text-muted-foreground">
              {history.length === 0
                ? "Переговоров пока не было. Инженер выйдет на связь, когда начнётся сессия."
                : "Под выбранные фильтры ничего не попало."}
            </p>
          </div>
        ) : (
          <div
            ref={listRef}
            onScroll={onScroll}
            className="max-h-[420px] overflow-y-auto"
          >
            <ul>
              {rows.map((row) => (
                <MemoHistoryRow
                  key={row.key}
                  time={row.time}
                  source={row.source}
                  urgency={row.urgency}
                  text={row.text}
                  title={row.title}
                  state={row.state}
                  cancelReason={row.cancelReason}
                />
              ))}
            </ul>
          </div>
        )}
      </Panel>

      {/* ── Настройки радио ───────────────────────────────────────────────── */}
      <Panel
        label="Настройки радио"
        action={
          saveError ? (
            <span className="label-mono text-[10px] text-destructive">
              Не сохранилось
            </span>
          ) : undefined
        }
        bodyClassName="p-0"
      >
        <ChoiceRow
          title="Стиль радио"
          hint="Сколько говорит инженер. Меняет порог важности, аналитику и паузу сразу — это не таймер."
          options={RADIO_STYLES}
          value={settings?.radio_style ?? "standard"}
          onChange={(id) => patch({ radio_style: id as never })}
          disabled={!settings}
        />
        <ChoiceRow
          title="Длина фраз"
          hint="Насколько лаконично формулирует инженер."
          options={PHRASE_LENGTHS}
          value={settings?.phrase_length ?? "standard"}
          onChange={(id) => patch({ phrase_length: id as never })}
          disabled={!settings}
        />

        <SettingRow
          title="Безопасность звучит всегда"
          hint="Предупреждения споттера и критические команды не отключаются ни стилем, ни частотой."
          control={
            <span className="label-mono text-[10px] text-success">Всегда</span>
          }
        />

        <SettingRow
          title="Радио-эффект"
          hint="Щелчки рации и полосовой фильтр. Накладываются при воспроизведении, в кэш не пишутся."
          control={
            <Toggle
              checked={settings?.radio_fx ?? false}
              onChange={(v) => patch({ radio_fx: v })}
              label="Радио-эффект"
              disabled={!settings}
            />
          }
        />

        {/* ── Карточка в игре ──────────────────────────────────────────────
            ВСЁ, что ниже, управляет ТОЛЬКО показом. Ни один переключатель не
            выключает звук: споттер и критическая команда инженера прозвучат в
            любом случае. Подписи обязаны говорить это прямо — двусмысленный
            тумблер здесь означал бы, что игрок думает, будто отключил
            предупреждение о машине рядом (ТЗ §18). */}
        <SettingRow
          title="Карточка рации в игре"
          hint="Показывать карточку поверх F1 25 во время передачи. Выключение убирает только картинку — все реплики продолжают звучать."
          control={
            <Toggle
              checked={settings?.show_broadcast_radio_card ?? true}
              onChange={(v) => patch({ show_broadcast_radio_card: v })}
              label="Карточка рации"
              disabled={!settings}
            />
          }
        />

        <SettingRow
          title="Карточка споттера"
          hint="Короткие предупреждения о машине рядом. Скрытие не отключает их звук."
          control={
            <Toggle
              checked={settings?.show_spotter_card ?? true}
              onChange={(v) => patch({ show_spotter_card: v })}
              label="Карточка споттера"
              disabled={!settings || settings.show_broadcast_radio_card === false}
            />
          }
        />

        <SettingRow
          title="Карточка комментатора"
          hint="Аналитика и атмосферные реплики. Инженера и споттера не затрагивает."
          control={
            <Toggle
              checked={settings?.show_commentary_card ?? true}
              onChange={(v) => patch({ show_commentary_card: v })}
              label="Карточка комментатора"
              disabled={!settings || settings.show_broadcast_radio_card === false}
            />
          }
        />

        <SettingRow
          title="Портреты"
          hint="Фотография говорящего в карточке. Без файла портрета показываются инициалы."
          control={
            <Toggle
              checked={settings?.show_portraits ?? true}
              onChange={(v) => patch({ show_portraits: v })}
              label="Портреты"
              disabled={!settings || settings.show_broadcast_radio_card === false}
            />
          }
        />

        <SettingRow
          title="Размер карточки"
          hint={`${Math.round((settings?.radio_card_scale ?? 1) * 100)}% — масштаб карточки в игре.`}
          control={
            <div className="w-40">
              <Slider
                value={Math.round((settings?.radio_card_scale ?? 1) * 100)}
                min={80}
                max={140}
                onChange={() => undefined}
                onPointerUp={(v) => patch({ radio_card_scale: v / 100 })}
                label="Размер карточки"
              />
            </div>
          }
        />

        <SettingRow
          title="Время показа карточки"
          hint={`${Math.round((settings?.radio_card_duration ?? 1) * 100)}% — множитель к базовому времени по каналам. Сама реплика не обрывается никогда.`}
          control={
            <div className="w-40">
              <Slider
                value={Math.round((settings?.radio_card_duration ?? 1) * 100)}
                min={50}
                max={200}
                onChange={() => undefined}
                onPointerUp={(v) => patch({ radio_card_duration: v / 100 })}
                label="Время показа карточки"
              />
            </div>
          }
        />

        <SettingRow
          title="Запоминать позицию карточки"
          hint="Оставлять карточку там, куда её перетащили в редакторе HUD (Ctrl+Alt+O). Выключено — каждый запуск начинается со стандартного места."
          control={
            <Toggle
              checked={settings?.remember_overlay_position ?? true}
              onChange={(v) => patch({ remember_overlay_position: v })}
              label="Запоминать позицию"
              disabled={!settings}
            />
          }
        />

        <SettingRow
          title="Субтитр инженера в игре"
          hint="Показывать реплику текстом на игровом HUD, даже когда она не озвучена."
          control={
            <Toggle
              checked={settings?.subtitles_enabled ?? true}
              onChange={(v) => patch({ subtitles_enabled: v })}
              label="Субтитры"
              disabled={!settings}
            />
          }
        />

        <ChoiceRow
          title="Размер текста"
          hint="Кегль реплики в карточке и в субтитре. Ниже 14 пикселей не опускается."
          options={[
            { id: "s", label: "Мелкий", hint: "15px" },
            { id: "m", label: "Обычный", hint: "17px" },
            { id: "l", label: "Крупный", hint: "19px" },
          ]}
          value={settings?.subtitle_size ?? "m"}
          onChange={(v) => patch({ subtitle_size: v as "s" | "m" | "l" })}
          disabled={!settings}
        />

        <SettingRow
          title="Время показа субтитра"
          hint={`${settings?.subtitle_seconds ?? 12} с — столько реплика висит на HUD после появления.`}
          control={
            <div className="w-40">
              <Slider
                value={settings?.subtitle_seconds ?? 12}
                min={4}
                max={30}
                onChange={(v) => setDraftSeconds(v)}
                onPointerUp={(v) => patch({ subtitle_seconds: v })}
                label="Время показа субтитра"
              />
            </div>
          }
        />

        <SettingRow
          title="Громкость инженера"
          hint="Отдельно от комментатора: у инженера свой голос и своя громкость."
          control={
            <div className="w-40">
              <Slider
                value={settings?.volume_engineer ?? 75}
                min={0}
                max={100}
                onChange={(v) => setDraftEngineerVolume(v)}
                onPointerUp={(v) => patch({ volume_engineer: v })}
                label="Громкость инженера"
              />
            </div>
          }
        />

        <SettingRow
          title="Громкость споттера"
          hint="Споттер предупреждает о машине рядом. Тише остальных его лучше не делать."
          control={
            <div className="w-40">
              <Slider
                value={settings?.volume_spotter ?? 75}
                min={0}
                max={100}
                onChange={(v) => setDraftSpotterVolume(v)}
                onPointerUp={(v) => patch({ volume_spotter: v })}
                label="Громкость споттера"
              />
            </div>
          }
        />

        <SettingRow
          title="Лента переговоров"
          hint="История живёт на бэкенде и переживает переход между экранами. Очистка не трогает активную передачу и «повтори»."
          control={
            <button
              type="button"
              onClick={onClearHistory}
              disabled={clearing || history.length === 0}
              className="label-mono rounded border border-border bg-secondary px-2.5 py-1 text-[10px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
            >
              {clearing ? "Очищаю…" : "Очистить"}
            </button>
          }
        />

        <SettingRow
          title="Голос и кнопка связи"
          hint="Голос инженера настраивается на экране «Голос», кнопка связи — на «Горячие клавиши»."
          control={
            <span className="label-mono text-[10px] text-muted-foreground">
              {hotkeyLabel}
            </span>
          }
        />
      </Panel>
    </div>
  )
}

function SettingRow({
  title,
  hint,
  control,
}: {
  title: string
  hint: string
  control: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 last:border-b-0">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-foreground">{title}</p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>
      </div>
      {control}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────────────────────
   Настройки радио (§17 брифа).

   Каждый переключатель описан тем, что он РЕАЛЬНО делает (критерий готовности
   №12). «Частота инженера» здесь не таймер: она меняет порог важности,
   разрешённость аналитики и паузу сразу — и об этом сказано прямо, потому что
   иначе пользователь ждёт «раз в N секунд».
   ──────────────────────────────────────────────────────────────────────────── */

const RADIO_STYLES: { id: string; label: string; hint: string }[] = [
  {
    id: "minimal",
    label: "Минимум",
    hint: "Только безопасность и команды. Сводки по разрывам, DRS и оборона молчат.",
  },
  {
    id: "standard",
    label: "Стандарт",
    hint: "Рекомендуемый режим: команды плюс регулярные сводки.",
  },
  {
    id: "verbose",
    label: "Подробно",
    hint: "Больше аналитики и сводок, паузы между репликами короче.",
  },
]

const PHRASE_LENGTHS: { id: string; label: string; hint: string }[] = [
  { id: "short", label: "Коротко", hint: "Самая лаконичная формулировка из возможных." },
  { id: "standard", label: "Стандартно", hint: "Обычные формулировки инженера." },
]

function ChoiceRow({
  title,
  hint,
  options,
  value,
  onChange,
  disabled,
}: {
  title: string
  hint: string
  options: { id: string; label: string; hint: string }[]
  value: string
  onChange: (id: string) => void
  disabled: boolean
}) {
  const active = options.find((option) => option.id === value)
  return (
    <div className="border-b border-border px-5 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] text-foreground">{title}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>
        </div>
        <div className="flex gap-1">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              disabled={disabled}
              onClick={() => onChange(option.id)}
              className={cn(
                "label-mono rounded border px-2.5 py-1 text-[10px] transition-colors disabled:opacity-40",
                value === option.id
                  ? "border-primary/50 bg-primary/10 text-foreground"
                  : "border-border bg-secondary text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      {active && (
        <p className="mt-2 text-[11px] text-muted-foreground/80">{active.hint}</p>
      )}
    </div>
  )
}

function MetaCell({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note?: string
  tone?: "warning"
}) {
  return (
    <div className="bg-card px-4 py-3">
      <dt className="label-mono text-[10px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-1 truncate text-[13px]",
          tone === "warning" ? "text-warning" : "text-foreground",
        )}
        title={note ?? value}
      >
        {value}
      </dd>
      {note && <p className="mt-0.5 text-[10px] text-warning/80">{note}</p>}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-5 py-8 text-center">
      <p className="text-[13px] text-muted-foreground">{text}</p>
    </div>
  )
}
