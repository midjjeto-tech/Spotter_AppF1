"use client"

import type React from "react"
import { useEffect, useState } from "react"
import { PageHeader, Panel, Dot, Input, Toggle } from "../ui"
import { Button } from "@/components/ui/button"
import { getGigachatStatus, getYandexStatus, resetSettings, saveGigachat, saveSettings, saveYandex, type GigachatStatus, type SpotterState, type YandexStatus } from "@/lib/api"
import { cn } from "@/lib/utils"
import { AlertTriangle, MessageSquare, Mic, Radio, Rss, Volume2, Waves } from "lucide-react"

export function SettingsView({
  state,
  onOpenOnboarding,
}: {
  state: SpotterState | null
  /** Открыть визард первого запуска повторно. Он же — «диагностика»: живые
   *  проверки телеметрии, звука и ключей в одном месте. */
  onOpenOnboarding?: () => void
}) {
  const settings = state?.settings
  const [controls, setControls] = useState({
    commentary: false,
    voice: false,
    critical: false,
    ambient: false,
    engineer: false,
    broadcast: false,
    racefeed: false,
    position: "auto",
  })
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle")

  useEffect(() => {
    if (!settings) return
    setControls({
      commentary: settings.commentary_enabled,
      voice: settings.autovoice_enabled,
      critical: settings.critical_events_enabled,
      ambient: settings.ambient_enabled,
      engineer: settings.engineer_chatter_enabled,
      broadcast: settings.broadcast_mode_enabled,
      racefeed: settings.racefeed_enabled,
      position: settings.commentator_position,
    })
  }, [settings])

  const saveControl = (key: keyof Omit<typeof controls, "position">, apiKey: string) => async (value: boolean) => {
    const previous = controls[key]
    setControls((current) => ({ ...current, [key]: value }))
    setSaveState("saving")
    try {
      const result = await saveSettings({ [apiKey]: value })
      if (!result.ok) throw new Error("settings rejected")
      setSaveState("saved")
    } catch {
      setControls((current) => ({ ...current, [key]: previous }))
      setSaveState("error")
    }
  }

  const savePosition = async (position: string) => {
    const previous = controls.position
    setControls((current) => ({ ...current, position }))
    setSaveState("saving")
    try {
      const result = await saveSettings({ commentator_position: position })
      if (!result.ok) throw new Error("settings rejected")
      setSaveState("saved")
    } catch {
      setControls((current) => ({ ...current, position: previous }))
      setSaveState("error")
    }
  }

  const [gap, setGap] = useState("")
  useEffect(() => {
    if (state?.settings?.min_comment_gap != null) setGap(String(state.settings.min_comment_gap))
  }, [state?.settings?.min_comment_gap])

  const saveGap = async () => {
    const n = Number.parseFloat(gap)
    if (Number.isNaN(n)) return
    setSaveState("saving")
    try {
      const result = await saveSettings({ min_comment_gap: n })
      if (!result.ok) throw new Error("settings rejected")
      setSaveState("saved")
    } catch {
      setSaveState("error")
    }
  }

  const [yandex, setYandex] = useState({ api_key: "", folder_id: "", auth_mode: "api_key" })
  const [yStatus, setYStatus] = useState<YandexStatus | null>(null)
  const [ySaving, setYSaving] = useState(false)

  const [giga, setGiga] = useState({ authorization_key: "" })
  const [gStatus, setGStatus] = useState<GigachatStatus | null>(null)
  const [gSaving, setGSaving] = useState(false)

  const [resetting, setResetting] = useState(false)

  const handleReset = async () => {
    // Не всё применяется на лету: ptt_hotkey регистрируется один раз в потоке
    // хоткеев при старте, telemetry_source выбирает адаптер при инициализации
    // движка. Раньше кнопка обещала полный сброс без оговорок.
    if (!confirm(
      "Сбросить все настройки к значениям по умолчанию?\n\n" +
      "Хоткей push-to-talk и источник телеметрии применятся только после " +
      "перезапуска Spotter App."
    )) return
    setResetting(true)
    try {
      await resetSettings()
      window.location.reload()
    } finally {
      setResetting(false)
    }
  }

  useEffect(() => {
    getYandexStatus()
      .then(setYStatus)
      .catch(() => {})
    getGigachatStatus()
      .then(setGStatus)
      .catch(() => {})
  }, [])

  const saveY = async () => {
    setYSaving(true)
    try {
      const r = await saveYandex(yandex)
      setYStatus({ connected: r.ok, code: r.code, message: r.message })
    } catch {
      setYStatus({ connected: false, code: "ERROR", message: "Ошибка сети" })
    } finally {
      setYSaving(false)
    }
  }

  const saveG = async () => {
    setGSaving(true)
    try {
      const r = await saveGigachat(giga)
      setGStatus({ connected: r.ok, code: r.code, message: r.message })
    } catch {
      setGStatus({ connected: false, code: "ERROR", message: "Ошибка сети" })
    } finally {
      setGSaving(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Настройки"
        subtitle="Управление комментариями, телеметрией и AI-сервисами"
        action={
          onOpenOnboarding && (
            <Button
              onClick={onOpenOnboarding}
              className="bg-secondary text-foreground hover:bg-elevated"
            >
              Мастер настройки
            </Button>
          )
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel
          label="Режимы комментатора"
          className="lg:col-span-2"
          action={<SaveFeedback state={saveState} />}
        >
          <div className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
            <SettingToggle
              icon={MessageSquare}
              title="Комментарий"
              description="Создавать реплики о событиях гонки"
              checked={controls.commentary}
              disabled={!settings}
              onChange={saveControl("commentary", "commentary_enabled")}
            />
            <SettingToggle
              icon={Volume2}
              title="Авто-озвучка"
              description="Автоматически проигрывать созданные реплики"
              checked={controls.voice}
              disabled={!settings}
              onChange={saveControl("voice", "autovoice_enabled")}
            />
            <SettingToggle
              icon={AlertTriangle}
              title="Критические события"
              description="Штрафы, флаги, споттер и обязательный вызов в боксы"
              checked={controls.critical}
              disabled={!settings}
              onChange={saveControl("critical", "critical_events_enabled")}
            />
            <SettingToggle
              icon={Waves}
              title="Авто-анализ"
              description="Периодически оценивать общую ситуацию через AI"
              checked={controls.ambient}
              disabled={!settings}
              onChange={saveControl("ambient", "ambient_enabled")}
            />
            <SettingToggle
              icon={Mic}
              title="Тактика инженера"
              description="Гэпы, DRS, ERS, пит-окно, дождь и трек-лимиты"
              checked={controls.engineer}
              disabled={!settings}
              onChange={saveControl("engineer", "engineer_chatter_enabled")}
            />
            {/* Тумблер влияет ровно на 4 типа событий Race AI
                (core/engine.py::_code_map: ATTACK/BATTLE/TYRE_WARN/FINAL_LAP),
                а не на весь комментарий; при недоступном текстовом AI
                BroadcastDirector.generate() возвращает None и фраза собирается
                тем же шаблоном, что и с выключенным тумблером. */}
            <SettingToggle
              icon={Radio}
              title="Broadcast Director"
              description="Атака, борьба, износ резины и последний круг — в стиле трансляции F1"
              checked={controls.broadcast}
              disabled={!settings}
              onChange={saveControl("broadcast", "broadcast_mode_enabled")}
            />
            <SettingToggle
              icon={Rss}
              title="RaceFeed — канал карьеры"
              description="Создать AI-канал; публикации начнутся с первого Гран-при"
              checked={controls.racefeed}
              disabled={!settings}
              onChange={saveControl("racefeed", "racefeed_enabled")}
            />
            <div className="flex items-center justify-between gap-4 border-b border-border py-4">
              <div>
                <p className="text-sm font-medium text-foreground">Фокус событий</p>
                <p className="text-xs text-muted-foreground">Какие машины включать в комментарий</p>
              </div>
              <select
                value={controls.position}
                disabled={!settings}
                onChange={(event) => void savePosition(event.target.value)}
                className="h-9 rounded-md border border-input bg-secondary px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-40"
              >
                <option value="auto">Авто</option>
                <option value="player">Только игрок</option>
                <option value="all">Вся гонка</option>
              </select>
            </div>
          </div>
          <p className="mt-4 rounded-md border border-border bg-secondary/45 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            Споттер «машина слева/справа» относится к безопасности: его отключает только режим
            «Критические события», а не «Тактика инженера».
          </p>
          {/* Оба режима без модели не выключаются, а тихо вырождаются в
              шаблоны: BroadcastDirector.generate() возвращает None и фразу
              собирает engineer.get_message(), а create_ambient() подставляет
              заготовку из templates.render_ambient(). Со стороны это выглядит
              как «тумблер включён, но ничего не изменилось». */}
          {state?.yandex_ok === false && (controls.broadcast || controls.ambient) && (
            <p className="mt-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs leading-relaxed text-warning">
              Сейчас нет связи с текстовым AI: «Broadcast Director» и «Авто-анализ» не
              выключаются, а переходят на заготовленные фразы — включённый тумблер при
              этом ничего не меняет.
            </p>
          )}
        </Panel>

        <Panel label="Телеметрия">
          {/* Значения приходят из /api/state (config.UDP_IP/UDP_PORT) — раньше
              были литералами в разметке и не менялись вместе с config.py. */}
          <Field label="Источник" hint="Что слушает движок">
            <span className="font-mono text-sm text-foreground">
              {state?.telemetry_source === "iracing"
                ? "iRacing SDK"
                : state?.telemetry_source === "f1"
                  ? "F1 25 · UDP"
                  : "—"}
            </span>
          </Field>
          <Field label="UDP IP" hint="Меняется в config.py">
            <Input value={state?.udp_ip ?? "—"} readOnly />
          </Field>
          <Field label="UDP Port" hint="Меняется в config.py">
            <Input value={state?.udp_port != null ? String(state.udp_port) : "—"} readOnly className="w-28" />
          </Field>
          {state?.telemetry_source === "iracing" && (
            <p className="mt-3 rounded-md border border-border bg-secondary/45 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
              Источник переключён на iRacing — UDP-порт F1 не используется, а справочник
              пилотов F1 не загружается.
            </p>
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
            Источник телеметрии задаётся ключом <span className="font-mono">telemetry_source</span>
            {" "}в settings.json (<span className="font-mono">f1</span> или{" "}
            <span className="font-mono">iracing</span>) и применяется после перезапуска —
            переключателя в интерфейсе нет.
          </p>
        </Panel>

        <Panel label="Текстовый AI">
          <Field label="Движок" hint="Активный текстовый движок">
            <span className="font-mono text-sm text-foreground">{state?.llm_engine ?? "—"}</span>
          </Field>
          {state?.llm_engine === "Шаблоны" && (
            <p className="mb-3 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1.5 text-xs text-warning">
              Yandex недоступен — комментарий идёт по заготовленным фразам, не от AI.
            </p>
          )}
          <Field label="Ключ" hint="Задаётся в блоке Yandex Cloud">
            <span className="font-mono text-sm text-muted-foreground">см. ниже</span>
          </Field>
        </Panel>

        <Panel label="Комментатор">
          <Field label="Мин. пауза" hint="Между обычными фразами, сек">
            <Input
              value={gap}
              onChange={(e) => setGap(e.target.value)}
              onBlur={saveGap}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur()
              }}
              className="w-20"
            />
          </Field>
          {/* Гейт паузы — по важности события (core/engine.py::_commentary_loop
              + config.PLAN_GAP_SKIP_THRESHOLD / PLAN_GAP_HALF_THRESHOLD), а не
              единый throttle: подпись «между фразами» это скрывала. */}
          <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground">
            Пауза действует не на все реплики. Критичные события — авария, сход, штраф,
            сейфти-кар, «машина слева/справа», вызов в бокс — звучат сразу, без паузы.
            Важные (обгон в борьбе, последние круги) ждут половину заданного времени.
          </p>
          <Field label="Персона" hint="Меняется на экране Voice">
            <span className="font-mono text-sm text-foreground">{state?.settings?.persona ?? "—"}</span>
          </Field>
          <div className="flex justify-end border-t border-border pt-4">
            <Button
              onClick={handleReset}
              disabled={resetting}
              className="bg-destructive/12 text-destructive hover:bg-destructive/20"
            >
              {resetting ? "Сбрасываю…" : "Сбросить к дефолтам"}
            </Button>
          </div>
        </Panel>

        <Panel label="Голос">
          <Field label="TTS-движок" hint="Активный синтезатор">
            <span className="font-mono text-sm text-foreground">{state?.tts_engine ?? "—"}</span>
          </Field>
          <Field label="Статус" hint="Готовность озвучки">
            <span
              className={cn("font-mono text-sm", state?.voice_available ? "text-success" : "text-muted-foreground")}
            >
              {state?.voice_available ? "готов" : "не готов"}
            </span>
          </Field>
        </Panel>

        <Panel label="Yandex Cloud" className="lg:col-span-2">
          {/* Одна пара ключ+каталог обслуживает несколько подсистем сразу
              (yandex_ai/speech.py, yandex_ai/stt.py и — если LLM_PROVIDER
              переключён на yandex — ещё и текст). Отвал ключа гасит их все
              одновременно, а UI об этой связке нигде не говорил. */}
          <p className="mb-4 rounded-md border border-border bg-secondary/45 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            Один ключ — несколько подсистем: озвучка (SpeechKit) и распознавание вопросов
            push-to-talk. Если выбран текстовый движок Yandex — ещё и генерация реплик.
            Проблема с ключом или квотой выключит всё это разом: голос уйдёт на офлайн-Piper,
            push-to-talk замолчит.
          </p>
          <div className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
            <Field
              label="API ключ"
              hint={yandex.auth_mode === "iam" ? "OAuth-токен Yandex ID" : "API Key"}
            >
              <Input
                value={yandex.api_key}
                onChange={(e) => setYandex((y) => ({ ...y, api_key: e.target.value }))}
                placeholder="AQVN…"
                type="password"
                className="w-full max-w-xs"
              />
            </Field>
            <Field label="Folder ID" hint="Идентификатор каталога">
              <Input
                value={yandex.folder_id}
                onChange={(e) => setYandex((y) => ({ ...y, folder_id: e.target.value }))}
                placeholder="b1g…"
                className="w-full max-w-xs"
              />
            </Field>
            <Field label="Авторизация" hint="Тип ключа">
              <select
                value={yandex.auth_mode}
                onChange={(e) => setYandex((y) => ({ ...y, auth_mode: e.target.value }))}
                className="h-9 w-44 rounded-md border border-input bg-secondary px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="api_key">API Key</option>
                <option value="iam">OAuth (авто-IAM)</option>
              </select>
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button onClick={saveY} disabled={ySaving || !state} className="bg-secondary text-foreground hover:bg-elevated disabled:opacity-40">
              {ySaving ? "Проверка…" : "Проверить и сохранить"}
            </Button>
            {yStatus && (
              <span
                className={cn(
                  "flex items-center gap-2 font-mono text-xs",
                  yStatus.connected ? "text-success" : "text-muted-foreground",
                )}
              >
                <Dot state={yStatus.connected ? "on" : "off"} /> {yStatus.message}
              </span>
            )}
          </div>
        </Panel>

        <Panel label="GigaChat (Сбер) — «мозг»" className="lg:col-span-2">
          <p className="mb-3 text-xs text-muted-foreground">
            Текст комментария генерирует GigaChat, голос остаётся Yandex. Ключ бесплатный:
            developers.sber.ru → GigaChat API → «для физических лиц» → Authorization key.
          </p>
          <div className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
            <Field label="Authorization key" hint="base64 client_id:client_secret">
              <Input
                value={giga.authorization_key}
                onChange={(e) => setGiga({ authorization_key: e.target.value })}
                placeholder="ODc…=="
                type="password"
                className="w-full max-w-xs"
              />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button onClick={saveG} disabled={gSaving || !state} className="bg-secondary text-foreground hover:bg-elevated disabled:opacity-40">
              {gSaving ? "Проверка…" : "Проверить и сохранить"}
            </Button>
            {gStatus && (
              <span
                className={cn(
                  "flex items-center gap-2 font-mono text-xs",
                  gStatus.connected ? "text-success" : "text-muted-foreground",
                )}
              >
                <Dot state={gStatus.connected ? "on" : "off"} /> {gStatus.message}
              </span>
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border py-4 last:border-0">
      <div>
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      {children}
    </div>
  )
}

function SettingToggle({
  icon: Icon,
  title,
  description,
  checked,
  disabled,
  onChange,
}: {
  icon: typeof MessageSquare
  title: string
  description: string
  checked: boolean
  disabled: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border py-4">
      <div className="flex min-w-0 items-center gap-3">
        <span className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-md",
          checked ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground",
        )}>
          <Icon className="h-4.5 w-4.5" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
        </div>
      </div>
      <Toggle checked={checked} disabled={disabled} onChange={onChange} label={title} />
    </div>
  )
}

function SaveFeedback({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  if (state === "idle") return null
  return (
    <span
      role="status"
      className={cn(
        "label-mono text-[11px]",
        state === "error" ? "text-destructive" : state === "saved" ? "text-success" : "text-muted-foreground",
      )}
    >
      {state === "saving" ? "Сохраняю…" : state === "saved" ? "Сохранено" : "Ошибка сохранения"}
    </span>
  )
}

