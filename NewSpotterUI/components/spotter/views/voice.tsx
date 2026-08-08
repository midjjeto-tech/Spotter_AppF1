"use client"

import { useEffect, useState } from "react"
import { PageHeader, Panel, Toggle, Dot, Slider } from "../ui"
import { Button } from "@/components/ui/button"
import { personas, engineerCharacters } from "@/lib/spotter-data"
import {
  getVoices, saveSettings, testVoice, getMicDevices, testMic,
  type SpotterState, type VoicesResponse, type MicDevice,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { Tv, Flame, Wind, Skull, Play, RotateCw, Radio, Mic, Gauge, Volume2 } from "lucide-react"

const icons: Record<string, typeof Tv> = { tv: Tv, hype: Flame, calm: Wind, toxic: Skull }

export function VoiceView({ state }: { state: SpotterState | null }) {
  const [active, setActive] = useState("tv")
  const [engineer, setEngineer] = useState("volkov")
  const [engineerError, setEngineerError] = useState(false)
  const [radioFx, setRadioFx] = useState(true)
  const [drivingCoach, setDrivingCoach] = useState(false)
  const [ducking, setDucking] = useState(false)
  const [duckingLevel, setDuckingLevel] = useState(35)
  const [ttsVersion, setTtsVersion] = useState<"v1" | "v3">("v1")
  const [commentaryMode, setCommentaryMode] = useState<"live" | "calm" | "story">("live")
  const [voices, setVoices] = useState<VoicesResponse | null>(null)
  const [micDevices, setMicDevices] = useState<MicDevice[]>([])
  const [micDevice, setMicDevice] = useState<string | null>(null)
  const [micTesting, setMicTesting] = useState(false)
  const [micTestResult, setMicTestResult] = useState<{ ok: boolean; error?: string } | null>(null)
  const [globalVol, setGlobalVol] = useState(80)
  const [personaVols, setPersonaVols] = useState<Record<string, number>>({
    tv: 80, hype: 90, calm: 75, toxic: 80,
  })

  useEffect(() => {
    if (state?.settings?.persona) setActive(state.settings.persona)
  }, [state?.settings?.persona])

  useEffect(() => {
    if (state?.settings?.engineer_character) setEngineer(state.settings.engineer_character)
  }, [state?.settings?.engineer_character])

  // Зеркалим реальное значение radio_fx из бэкенда (а не держим хардкод true).
  useEffect(() => {
    if (typeof state?.settings?.radio_fx === "boolean") setRadioFx(state.settings.radio_fx)
  }, [state?.settings?.radio_fx])

  // Тумблер подсказок по пилотажу — тоже зеркало бэкенда, а не локальный
  // хардкод: по умолчанию он выключен, и показать включённым его нельзя.
  useEffect(() => {
    if (typeof state?.settings?.driving_coach_enabled === "boolean") {
      setDrivingCoach(state.settings.driving_coach_enabled)
    }
  }, [state?.settings?.driving_coach_enabled])

  // Приглушение игры — тоже зеркало бэкенда: по умолчанию выключено, и
  // показать включённым его нельзя.
  useEffect(() => {
    if (typeof state?.settings?.game_ducking_enabled === "boolean") {
      setDucking(state.settings.game_ducking_enabled)
    }
    if (typeof state?.settings?.game_ducking_level === "number") {
      setDuckingLevel(state.settings.game_ducking_level)
    }
  }, [state?.settings?.game_ducking_enabled, state?.settings?.game_ducking_level])

  // Sync Yandex TTS version from backend state.
  useEffect(() => {
    const v = state?.settings?.yandex_tts_version
    if (v === "v1" || v === "v3") setTtsVersion(v)
  }, [state?.settings?.yandex_tts_version])

  // Sync commentary mode (live/calm/story) from backend state.
  useEffect(() => {
    const m = state?.settings?.commentary_mode
    if (m === "live" || m === "calm" || m === "story") setCommentaryMode(m)
  }, [state?.settings?.commentary_mode])

  // Синхронизируем громкость из бэкенда.
  useEffect(() => {
    if (!state?.settings) return
    if (typeof state.settings.volume === "number") setGlobalVol(state.settings.volume)
    const pv: Record<string, number> = {}
    for (const p of ["tv", "hype", "calm", "toxic"] as const) {
      const key = `volume_${p}` as keyof typeof state.settings
      if (typeof state.settings[key] === "number") pv[p] = state.settings[key] as number
    }
    if (Object.keys(pv).length) setPersonaVols((prev) => ({ ...prev, ...pv }))
  }, [state?.settings])

  const toggleRadioFx = (v: boolean) => {
    setRadioFx(v)
    saveSettings({ radio_fx: v })
  }

  const toggleDrivingCoach = (v: boolean) => {
    setDrivingCoach(v)
    saveSettings({ driving_coach_enabled: v })
  }

  const toggleDucking = (v: boolean) => {
    setDucking(v)
    saveSettings({ game_ducking_enabled: v })
  }

  const pickDuckingLevel = (v: number) => {
    setDuckingLevel(v)
    saveSettings({ game_ducking_level: v })
  }

  const pickTtsVersion = (v: "v1" | "v3") => {
    setTtsVersion(v)
    saveSettings({ yandex_tts_version: v })
  }

  const pickCommentaryMode = (m: "live" | "calm" | "story") => {
    setCommentaryMode(m)
    saveSettings({ commentary_mode: m })
  }

  const saveGlobalVol = (v: number) => {
    setGlobalVol(v)
    saveSettings({ volume: v })
  }

  const savePersonaVol = (id: string, v: number) => {
    setPersonaVols((prev) => ({ ...prev, [id]: v }))
    saveSettings({ [`volume_${id}`]: v } as Parameters<typeof saveSettings>[0])
  }

  const refresh = () => {
    getVoices()
      .then(setVoices)
      .catch(() => {})
  }
  useEffect(() => {
    refresh()
  }, [])

  useEffect(() => {
    setMicDevice(state?.settings?.mic_device ?? null)
  }, [state?.settings?.mic_device])

  useEffect(() => {
    getMicDevices()
      .then((r) => setMicDevices(r.devices))
      .catch(() => {})
  }, [])

  const pick = (id: string) => {
    setActive(id)
    saveSettings({ persona: id })
  }

  // Оптимистичное переключение с откатом: выбор персонажа меняет ГОЛОС, и
  // молча оставленная подсветка при неудачном сохранении означала бы, что
  // пользователь видит одного инженера, а слышит другого.
  const pickEngineer = (id: string) => {
    const previous = engineer
    setEngineer(id)
    setEngineerError(false)
    saveSettings({ engineer_character: id }).catch(() => {
      setEngineer(previous)
      setEngineerError(true)
    })
  }

  const pickMicDevice = (value: string) => {
    const device = value === "" ? null : value
    setMicDevice(device)
    setMicTestResult(null)
    saveSettings({ mic_device: device })
  }

  const runMicTest = () => {
    setMicTesting(true)
    setMicTestResult(null)
    testMic()
      .then(setMicTestResult)
      .catch(() => setMicTestResult({ ok: false, error: "Ошибка запроса" }))
      .finally(() => setMicTesting(false))
  }

  const voiceReady = state?.voice_available ?? false
  const attached = state?.tts_engine ?? "—" // что прицеплено (основной движок)
  const activeEngine = state?.tts_active || "" // что РЕАЛЬНО выдало последнюю фразу
  const fallback = state?.tts_fallback ?? false

  return (
    <div>
      <PageHeader title="Voice & Engineer" subtitle="Комментатор и инженер — два разных голоса" />

      <div className="flex flex-col gap-5">
        {/* Personas */}
        <Panel label="Характер комментатора">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {personas.map((p) => {
              const Icon = icons[p.id]
              const isActive = active === p.id
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => pick(p.id)}
                  className={cn(
                    "group relative flex flex-col rounded-lg border p-4 text-left transition-all",
                    isActive
                      ? "border-primary/50 bg-primary/8"
                      : "border-border bg-secondary/40 hover:border-border hover:bg-secondary",
                  )}
                >
                  <span className="absolute left-0 top-4 h-7 w-1 rounded-r-full" style={{ backgroundColor: p.color }} />
                  <div className="mb-2 flex items-center gap-2">
                    <Icon className="h-4.5 w-4.5" style={{ color: p.color }} />
                    <span className="font-heading text-base font-bold text-foreground">{p.name}</span>
                    {isActive && <Dot state="on" className="ml-auto" />}
                  </div>
                  <p className="label-mono mb-2 text-[9px] text-muted-foreground">{p.tagline}</p>
                  <p className="text-xs leading-relaxed text-muted-foreground">{p.description}</p>
                </button>
              )
            })}
          </div>
        </Panel>

        {/* Инженер — отдельная ось от персоны комментатора: своя роль, свой голос. */}
        <Panel label="Инженер">
          <p className="mb-4 text-xs text-muted-foreground">
            Инженер говорит своим голосом и через рацию — комментатор идёт чистым
            эфиром. Если выбранный голос уже занят персоной комментатора, инженер
            автоматически берёт запасной: два канала никогда не звучат одинаково.
            Различаются голос, темп и манера: похвала, ритуалы старта и финиша,
            частота обращения по имени. Команды — «бокс», стороны от споттера,
            флаги, повреждения — у всех троих звучат одинаково: их нужно узнавать
            с первого слога, а не разгадывать.
          </p>
          {engineerError && (
            <p className="mb-3 text-xs text-destructive">
              Не удалось сохранить выбор — инженер остался прежним. Проверь, что
              приложение запущено, и попробуй ещё раз.
            </p>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {engineerCharacters.map((c) => {
              const isActive = engineer === c.id
              // Реально звучащий голос известен только для ВЫБРАННОГО персонажа:
              // бэкенд отдаёт действующий каст, а не раскладку по всем троим.
              // Для остальных показываем их основной голос — он и станет
              // действующим, если его не занял комментатор.
              const actualVoice = isActive
                ? (voices?.voices?.engineer?.display ?? c.primaryVoice)
                : c.primaryVoice
              const substituted = isActive && actualVoice !== c.primaryVoice
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => pickEngineer(c.id)}
                  className={cn(
                    "flex flex-col rounded-lg border p-4 text-left transition-all",
                    isActive
                      ? "border-primary/50 bg-primary/8"
                      : "border-border bg-secondary/40 hover:border-border hover:bg-secondary",
                  )}
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-heading text-base font-bold text-foreground">{c.name}</span>
                    {isActive && <Dot state="on" className="ml-auto" />}
                  </div>
                  <p className="label-mono mb-2 text-[9px] text-muted-foreground">{c.tagline}</p>
                  <p className="text-xs leading-relaxed text-muted-foreground">{c.description}</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Голос: <span className="text-foreground">{actualVoice}</span>
                  </p>
                  {substituted && (
                    <p className="mt-1 text-[11px] leading-relaxed text-warning">
                      Основной голос ({c.primaryVoice}) занят выбранной персоной
                      комментатора — звучит запасной.
                    </p>
                  )}
                </button>
              )
            })}
          </div>
        </Panel>

        {/* Commentary Mode — независимая ось от persona: НЕ характер, а темп/стиль */}
        <Panel label="Стиль повествования">
          <p className="mb-4 text-xs text-muted-foreground">
            Это про то, КАК ЧАСТО и КАК ПОДРОБНО говорит комментатор — не про характер.
            Характер (весёлый/спокойный/токсичный) настраивается выше, в панели
            «Характер комментатора».
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(
              [
                { id: "live" as const, name: "Live", tagline: "Как сейчас" },
                { id: "calm" as const, name: "Calm", tagline: "Реже" },
                { id: "story" as const, name: "Story", tagline: "Реже и связнее" },
              ]
            ).map((m) => {
              const isActive = commentaryMode === m.id
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => pickCommentaryMode(m.id)}
                  className={cn(
                    "flex flex-col rounded-lg border px-5 py-3 text-left transition-all",
                    isActive
                      ? "border-primary/50 bg-primary/8"
                      : "border-border bg-secondary/40 hover:bg-secondary",
                  )}
                >
                  <span className="font-heading text-sm font-bold text-foreground">
                    {m.name}
                    {isActive && <span className="ml-2 text-[10px] font-mono text-primary">АКТИВЕН</span>}
                  </span>
                  <span className="mt-0.5 text-xs text-muted-foreground">{m.tagline}</span>
                </button>
              )
            })}
          </div>
        </Panel>

        {/* TTS engine */}
        <Panel
          label="Движок озвучки"
          action={
            <div className="flex items-center gap-3">
              {fallback ? (
                <span className="label-mono flex items-center gap-1.5 rounded-md bg-warning/10 px-2.5 py-1 text-[10px] text-warning">
                  <Dot state="warn" /> YANDEX НЕДОСТУПЕН → PIPER
                </span>
              ) : activeEngine === "Yandex SpeechKit" ? (
                <span className="label-mono flex items-center gap-1.5 rounded-md bg-success/10 px-2.5 py-1 text-[10px] text-success">
                  <Dot state="on" /> YANDEX АКТИВЕН
                </span>
              ) : (
                <span
                  className={cn(
                    "label-mono flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[10px]",
                    voiceReady ? "bg-success/10 text-success" : "bg-secondary text-muted-foreground",
                  )}
                >
                  <Dot state={voiceReady ? "on" : "off"} /> {voiceReady ? "ГОТОВ · РУССКИЙ" : "НЕ ГОТОВ"}
                </span>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => testVoice()}
                className="h-8 border-border bg-secondary text-foreground hover:bg-elevated"
              >
                <Play className="h-3.5 w-3.5" /> Тест
              </Button>
            </div>
          }
        >
          <div>
            <p className="font-heading text-lg font-semibold text-foreground">{activeEngine || attached}</p>
            <p className="font-mono text-xs text-muted-foreground">
              Основной: {attached}
              {fallback
                ? " · сейчас звучит Piper (Yandex недоступен)"
                : activeEngine && activeEngine !== attached
                  ? ` · сейчас звучит: ${activeEngine}`
                  : ""}
            </p>
          </div>
        </Panel>

        {/* Voice per persona — dynamic: Yandex when active, Piper when fallback */}
        {(() => {
          const isYandex = voices?.engine === "Yandex SpeechKit"
          return (
            <Panel
              label={isYandex ? "Голоса · Yandex" : "Голоса · Piper (резерв)"}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={refresh}
                  className="h-8 border-border bg-secondary text-foreground hover:bg-elevated"
                >
                  <RotateCw className="h-3.5 w-3.5" /> Обновить
                </Button>
              }
            >
              {isYandex ? (
                <p className="mb-4 text-xs text-muted-foreground">
                  Yandex SpeechKit — облачный синтез. Каждая персона говорит своим голосом и тоном.
                </p>
              ) : (
                <p className="mb-4 text-xs text-muted-foreground">
                  Piper офлайн-резерв. Подключается автоматически при недоступности Yandex.{" "}
                  <span className="font-mono text-foreground/60">{voices?.voices_dir ?? "models/piper"}</span>
                </p>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {personas.map((p) => {
                  const v = voices?.voices?.[p.id]
                  const ok = isYandex ? !!v : v?.found !== false
                  return (
                    <div key={p.id} className="rounded-lg border border-border bg-secondary/40 p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <Dot state={ok ? "on" : (v ? "off" : "warn")} />
                        <span className="font-heading text-sm font-bold text-foreground">{p.name}</span>
                      </div>
                      <p className="mb-1 font-mono text-[13px] text-foreground">
                        {isYandex ? (v?.display ?? v?.voice ?? "—") : (v?.voice ?? "—")}
                      </p>
                      <p className="font-mono text-[11px] text-muted-foreground">
                        {isYandex
                          ? v ? `${v.emotion} · ${v.speed}x` : "загрузка…"
                          : v?.size_mb ? `${v.size_mb} MB` : v ? "не найден" : "загрузка…"}
                      </p>
                    </div>
                  )
                })}
              </div>
              {/* When Yandex is active, show Piper fallback names as footnote */}
              {isYandex && (
                <p className="mt-3 text-[11px] text-muted-foreground/50">
                  Резерв (Piper): {Object.values(voices?.piper_voices ?? {}).map((v) => v.voice).join(" / ")}
                </p>
              )}
            </Panel>
          )
        })()}

        {/* Radio FX */}
        <Panel label="Radio FX">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                <Radio className="h-4.5 w-4.5" />
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">Эффект рации</p>
                <p className="text-xs text-muted-foreground">Полоса 300–3400 Гц + щелчки сквелча</p>
              </div>
            </div>
            <Toggle checked={radioFx} onChange={toggleRadioFx} label="Radio FX" />
          </div>

          {/* Приглушение игры живёт в той же панели, что эффект рации: обе
              настройки про то, КАК звучит радио на фоне игры, и искать их
              пользователь будет в одном месте. */}
          <div className="mt-4 border-t border-border pt-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                  <Volume2 className="h-4.5 w-4.5" />
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">Приглушать игру во время реплики</p>
                  <p className="text-xs text-muted-foreground">
                    Как настоящий радиоканал: пока говорят, остальное тише
                  </p>
                </div>
              </div>
              <Toggle checked={ducking} onChange={toggleDucking} label="Ducking" />
            </div>

            {ducking && (
              <div className="mt-4">
                {/* Подпись и значение рисует вызывающий: Slider кладёт label
                    только в aria-label и видимого текста не даёт. */}
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm text-foreground">Насколько тише</span>
                  <span className="w-10 text-right font-mono text-sm text-foreground">
                    {duckingLevel}%
                  </span>
                </div>
                <Slider
                  label="Ducking level"
                  value={duckingLevel}
                  onChange={setDuckingLevel}
                  onPointerUp={pickDuckingLevel}
                  min={10}
                  max={90}
                />
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Доля от ТЕКУЩЕЙ громкости игры, а не абсолютная величина: если
                  игра у тебя и так тихая, приглушение не сделает её громче.
                  Затрагивается только звук игры — Discord и музыка не трогаются.
                </p>
              </div>
            )}
          </div>
        </Panel>

        {/* Microphone input device */}
        <Panel
          label="Микрофон"
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={runMicTest}
              disabled={micTesting}
              className="h-8 border-border bg-secondary text-foreground hover:bg-elevated"
            >
              <Mic className="h-3.5 w-3.5" /> {micTesting ? "Проверка…" : "Проверить"}
            </Button>
          }
        >
          <p className="mb-4 text-xs text-muted-foreground">
            Устройство записи для голосовых вопросов (push-to-talk). «Проверить» запишет
            2 секунды и воспроизведёт их обратно через колонки.
          </p>
          {/* Рация двусторонняя, и об этом нужно сказать прямо: инженер сам
              задаёт вопросы и ждёт ответа, а на стратегические предложения
              понимает «да» и «нет». Не написав этого, мы получим функцию,
              о которой никто не узнает. */}
          <p className="mb-4 text-xs text-muted-foreground">
            Рация работает в обе стороны. Инженер иногда спрашивает сам — про шины,
            баланс, тормоза; ответить можно той же кнопкой, он примет ответ, а не
            станет искать в нём вопрос. На предложения по стратегии («попробуем
            андеркат») понимает «да» и «нет»: отказ он запомнит и какое-то время
            повторять не будет. Заехать в боксы за тебя приложение при этом не
            может — оно управляет только тем, что говорит инженер.
          </p>
          <select
            value={micDevice ?? ""}
            onChange={(e) => pickMicDevice(e.target.value)}
            className="h-9 w-full max-w-sm rounded-md border border-input bg-secondary px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Системный микрофон по умолчанию</option>
            {micDevices.map((d) => (
              <option key={d.index} value={d.name}>
                {d.name}
                {d.is_default ? " (по умолчанию)" : ""}
              </option>
            ))}
          </select>
          {micTestResult && (
            <p className={cn("mt-3 text-[11px]", micTestResult.ok ? "text-success" : "text-destructive")}>
              {micTestResult.ok ? "Микрофон работает — запись воспроизведена." : micTestResult.error}
            </p>
          )}
        </Panel>

        {/* Подсказки по пилотажу. Отдельная панель, а не строка в «болтовне
            инженера»: это независимый тумблер, и обещать он должен ровно то,
            что делает — иначе пользователь ждёт разбора каждой ошибки. */}
        <Panel label="Подсказки по пилотажу">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                <Gauge className="h-4.5 w-4.5" />
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">Инженер говорит об ошибках вождения</p>
                <p className="text-xs text-muted-foreground">
                  Блокировка колеса, пробуксовка, снос, занос, выезд за трассу
                </p>
              </div>
            </div>
            <Toggle
              checked={drivingCoach}
              onChange={toggleDrivingCoach}
              label="Коуч"
            />
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Вживую звучит только повторяющаяся ошибка — та же проблема в том же
            повороте на трёх кругах из пяти. Разовый срыв инженер не
            комментирует: его ты и сам почувствовал. Полный разбор по всем
            поворотам всегда доступен в «Дебрифе», независимо от этого
            переключателя.
          </p>
        </Panel>

        {/* Yandex TTS version */}
        <Panel label="Yandex SpeechKit · Версия синтеза">
          <p className="mb-4 text-xs text-muted-foreground">
            Версия API синтеза речи. v3 — современный движок с более высоким качеством.
            v1 — стабильный legacy-режим. При сбое v3 автоматически переключается на v1.
          </p>
          <div className="flex gap-3">
            {(["v1", "v3"] as const).map((ver) => (
              <button
                key={ver}
                type="button"
                onClick={() => pickTtsVersion(ver)}
                className={cn(
                  "flex flex-col rounded-lg border px-5 py-3 text-left transition-all",
                  ttsVersion === ver
                    ? "border-primary/50 bg-primary/8"
                    : "border-border bg-secondary/40 hover:bg-secondary",
                )}
              >
                <span className="font-heading text-sm font-bold text-foreground">
                  {ver.toUpperCase()}{ttsVersion === ver && <span className="ml-2 text-[10px] font-mono text-primary">АКТИВНА</span>}
                </span>
                <span className="mt-0.5 text-xs text-muted-foreground">
                  {ver === "v1" ? "Legacy · стабильный REST" : "Современный API · выше качество"}
                </span>
              </button>
            ))}
          </div>
        </Panel>

        {/* Volume */}
        <Panel label="Громкость">
          <div className="mb-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-foreground">Общая громкость</span>
              <span className="w-10 text-right font-mono text-sm text-foreground">{globalVol}%</span>
            </div>
            <Slider
              value={globalVol}
              onChange={setGlobalVol}
              onPointerUp={saveGlobalVol}
              label="Global volume"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            {personas.map((p) => (
              <div key={p.id}>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-xs font-medium" style={{ color: p.color }}>{p.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{personaVols[p.id] ?? 80}%</span>
                </div>
                <Slider
                  value={personaVols[p.id] ?? 80}
                  onChange={(v) => setPersonaVols((prev) => ({ ...prev, [p.id]: v }))}
                  onPointerUp={(v) => savePersonaVol(p.id, v)}
                  label={`${p.name} volume`}
                />
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  )
}
