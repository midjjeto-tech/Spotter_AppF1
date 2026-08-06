"use client"

/**
 * Визард первого запуска.
 *
 * Принцип, из-за которого он выглядит именно так: каждый шаг проверяет ФАКТ, а
 * не показывает инструкцию и кнопку «Далее». Пользователь не должен решать сам,
 * получилось ли у него — на это отвечает /api/diagnostics.
 *
 * Второй принцип — не врать про бесплатный режим. Без ключей приложение
 * работает: реплики берутся из банка формулировок, озвучивает офлайн-Piper.
 * Поэтому шаг с ключами необязательный и прямо говорит, ЧТО именно изменится,
 * а не пугает неготовностью.
 */

import type React from "react"
import { useCallback, useEffect, useState } from "react"
import { Panel, Dot, Input } from "../ui"
import { Button } from "@/components/ui/button"
import {
  getDiagnostics,
  saveGigachat,
  saveSettings,
  saveYandex,
  testVoice,
  type Diagnostics,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { AlertTriangle, Check, Gamepad2, KeyRound, Loader2, Volume2 } from "lucide-react"

const STEPS = ["Игра", "Голос", "Ключи"] as const

/** Пока визард открыт, опрашиваем чаще обычного: пользователь прямо сейчас
 *  щёлкает тумблером телеметрии в игре и ждёт реакции. */
const POLL_MS = 2000

export function OnboardingView({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0)
  const [diag, setDiag] = useState<Diagnostics | null>(null)
  const [unreachable, setUnreachable] = useState(false)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const next = await getDiagnostics()
        if (!alive) return
        setDiag(next)
        setUnreachable(false)
      } catch {
        if (alive) setUnreachable(true)
      }
    }
    tick()
    const id = setInterval(tick, POLL_MS)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [])

  const finish = useCallback(
    async (done: boolean) => {
      // Пропуск закрывает визард навсегда так же, как прохождение: держать
      // пользователя экраном, который он осознанно закрыл, нельзя. Вернуться
      // можно кнопкой в Настройках.
      if (done) await saveSettings({ onboarding_done: true }).catch(() => undefined)
      onClose()
    },
    [onClose],
  )

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <p className="label-mono text-[11px] text-muted-foreground">Первый запуск</p>
        <h1 className="mt-1 font-heading text-2xl font-bold tracking-wide text-foreground">
          Три шага до первой гонки
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Ничего не нужно решать на глаз: каждый шаг проверяет, что всё работает
          на самом деле.
        </p>
      </header>

      <ol className="flex items-center gap-2">
        {STEPS.map((name, index) => (
          <li key={name} className="flex flex-1 items-center gap-2">
            <span
              className={cn(
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-[11px]",
                index === step
                  ? "border-primary bg-primary text-primary-foreground"
                  : index < step
                    ? "border-success text-success"
                    : "border-border text-muted-foreground",
              )}
            >
              {index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}
            </span>
            <span
              className={cn(
                "text-sm",
                index === step ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {name}
            </span>
            {index < STEPS.length - 1 && <span className="h-px flex-1 bg-border" />}
          </li>
        ))}
      </ol>

      {unreachable && (
        <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          Локальный сервер приложения не отвечает. Проверки временно недоступны.
        </p>
      )}

      {step === 0 && <GameStep diag={diag} />}
      {step === 1 && <VoiceStep diag={diag} />}
      {step === 2 && <KeysStep diag={diag} />}

      <footer className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-5">
        <button
          onClick={() => finish(true)}
          className="text-xs text-muted-foreground underline-offset-4 hover:underline"
        >
          Пропустить настройку
        </button>
        <div className="flex items-center gap-2">
          {step > 0 && (
            <Button
              onClick={() => setStep((s) => s - 1)}
              className="bg-secondary text-foreground hover:bg-elevated"
            >
              Назад
            </Button>
          )}
          {step < STEPS.length - 1 ? (
            <Button onClick={() => setStep((s) => s + 1)}>Дальше</Button>
          ) : (
            <Button onClick={() => finish(true)}>Готово</Button>
          )}
        </div>
      </footer>
    </div>
  )
}

/* ── Шаг 1: телеметрия из игры ─────────────────────────────────────────────
   Единственный шаг, без которого приложение бесполезно. Поэтому здесь же
   разбираются причины, которые раньше выглядели одинаковым «нет связи». */

function GameStep({ diag }: { diag: Diagnostics | null }) {
  const t = diag?.telemetry
  const status = t?.status ?? "waiting"
  const iracing = t?.source === "iracing"

  return (
    <Panel label="Шаг 1 — телеметрия из игры">
      <div className="flex items-start gap-3">
        <Gamepad2 className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <CheckLine
            state={status === "ok" ? "on" : status === "waiting" ? "warn" : "off"}
            title={
              status === "ok"
                ? "Пакеты идут — игра на связи"
                : status === "waiting"
                  ? "Жду пакеты от игры…"
                  : "Источник не открылся"
            }
          />

          {status === "port_busy" && (
            <Fault>
              {/* {" "} обязателен: JSX срезает пробел между выражением и
                  следующей строкой текста, и получалось «Порт 20777уже». */}
              Порт <span className="font-mono">{t?.udp_port}</span>{" "}
              уже занят другим приложением. Его используют SimHub, Pits n&rsquo;&nbsp;Giggles,
              Telemetry Tool и другие телеметрийные утилиты — а ещё вторая копия
              Spotter. Закройте её, и приложение подхватит порт само, перезапуск
              не нужен.
            </Fault>
          )}

          {status === "bind_failed" && (
            <Fault>
              Не удалось открыть {t?.udp_ip}:{t?.udp_port}. Обычно виноват
              брандмауэр или занятый другим процессом адрес. Подробности: {t?.detail}
            </Fault>
          )}

          {status === "iracing_no_lib" && (
            <Fault>
              Источник переключён на iRacing, но библиотека pyirsdk не установлена —
              данных не будет. Верните <code>telemetry_source</code> в <code>f1</code>{" "}
              или установите зависимость.
            </Fault>
          )}

          {status === "waiting" && !iracing && (
            <div className="mt-3 rounded-md border border-border bg-secondary/45 px-3 py-3 text-xs leading-relaxed text-muted-foreground">
              <p className="mb-2 font-medium text-foreground">Включите телеметрию в F1:</p>
              <ol className="list-inside list-decimal space-y-1">
                <li>Настройки игры → Телеметрия</li>
                <li>UDP-телеметрия — Вкл.</li>
                <li>
                  IP-адрес — <span className="font-mono">{t?.udp_ip ?? "127.0.0.1"}</span>,
                  порт — <span className="font-mono">{t?.udp_port ?? 20777}</span>
                </li>
                <li>Частота отправки — 30–60 Гц</li>
              </ol>
              <p className="mt-2">
                Экран обновится сам, как только пойдут пакеты. Игра при этом должна быть
                запущена — в меню телеметрия уже идёт, заезжать никуда не нужно.
              </p>
            </div>
          )}
        </div>
      </div>
    </Panel>
  )
}

/* ── Шаг 2: слышно ли ─────────────────────────────────────────────────────── */

function VoiceStep({ diag }: { diag: Diagnostics | null }) {
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const voice = diag?.voice

  const runTest = async () => {
    setTesting(true)
    setResult(null)
    try {
      const r = await testVoice()
      setResult(r.ok ? `Прозвучала фраза (${r.engine ?? "движок неизвестен"})` : r.error ?? "Не удалось")
    } catch {
      setResult("Не удалось — приложение не ответило")
    } finally {
      setTesting(false)
    }
  }

  return (
    <Panel label="Шаг 2 — звук">
      <div className="flex items-start gap-3">
        <Volume2 className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <CheckLine
            state={voice?.status === "none" ? "off" : "on"}
            title={
              voice?.status === "yandex"
                ? "Нейросетевой голос Yandex"
                : voice?.status === "piper"
                  ? "Офлайн-голос Piper (работает без ключей)"
                  : "Озвучка недоступна"
            }
          />
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            Нажмите «Проверить» — приложение произнесёт короткую фразу. Если тихо:
            проверьте устройство вывода Windows и громкость на экране «Голос».
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button
              onClick={runTest}
              disabled={testing}
              className="bg-secondary text-foreground hover:bg-elevated disabled:opacity-40"
            >
              {testing ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Проверяю…
                </span>
              ) : (
                "Проверить"
              )}
            </Button>
            {result && <span className="font-mono text-xs text-muted-foreground">{result}</span>}
          </div>
        </div>
      </div>
    </Panel>
  )
}

/* ── Шаг 3: ключи, необязательно ───────────────────────────────────────────── */

function KeysStep({ diag }: { diag: Diagnostics | null }) {
  const [giga, setGiga] = useState("")
  const [yandex, setYandex] = useState({ api_key: "", folder_id: "", auth_mode: "api_key" })
  const [busy, setBusy] = useState<"" | "giga" | "yandex">("")
  const [message, setMessage] = useState<string | null>(null)

  const saveG = async () => {
    setBusy("giga")
    setMessage(null)
    try {
      const r = await saveGigachat({ authorization_key: giga.trim() })
      setMessage(r.message)
    } catch {
      setMessage("Не удалось сохранить ключ")
    } finally {
      setBusy("")
    }
  }

  const saveY = async () => {
    setBusy("yandex")
    setMessage(null)
    try {
      const r = await saveYandex({
        api_key: yandex.api_key.trim(),
        folder_id: yandex.folder_id.trim(),
        auth_mode: yandex.auth_mode,
      })
      setMessage(r.message)
    } catch {
      setMessage("Не удалось сохранить ключ")
    } finally {
      setBusy("")
    }
  }

  return (
    <Panel label="Шаг 3 — ключи (необязательно)">
      <div className="flex items-start gap-3">
        <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1 space-y-4">
          <div className="rounded-md border border-border bg-secondary/45 px-3 py-3 text-xs leading-relaxed text-muted-foreground">
            <p className="mb-1 font-medium text-foreground">Этот шаг можно пропустить.</p>
            Сейчас приложение уже работает: реплики берутся из заготовленного банка
            формулировок, озвучивает офлайн-голос. Ключи меняют две вещи —{" "}
            <span className="text-foreground">GigaChat</span> пишет реплики под конкретный
            момент гонки вместо заготовок, <span className="text-foreground">Yandex</span>{" "}
            даёт нейросетевой голос и распознаёт ваши вопросы по рации.
          </div>

          <div className="rounded-md border border-border px-3 py-3 text-xs leading-relaxed text-muted-foreground">
            <p className="mb-1 font-medium text-foreground">Что уходит наружу</p>
            С ключом в облако провайдера уходит короткая сводка момента гонки — позиции,
            круг, разрывы, шины — и текст ваших реплик по рации. Ключи хранятся на этом
            компьютере, зашифрованные средствами Windows. Без ключей наружу не уходит
            ничего.
          </div>

          <Row label="GigaChat" status={diag?.brain.status === "gigachat" ? "on" : "off"}>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={giga}
                onChange={(e) => setGiga(e.target.value)}
                placeholder="Authorization key"
                type="password"
                className="w-56"
              />
              <Button
                onClick={saveG}
                disabled={busy !== "" || !giga.trim()}
                className="bg-secondary text-foreground hover:bg-elevated disabled:opacity-40"
              >
                {busy === "giga" ? "Проверяю…" : "Проверить и сохранить"}
              </Button>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Бесплатно: developers.sber.ru → GigaChat API → «для физических лиц».
            </p>
          </Row>

          <Row label="Yandex" status={diag?.voice.status === "yandex" ? "on" : "off"}>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={yandex.api_key}
                onChange={(e) => setYandex((y) => ({ ...y, api_key: e.target.value }))}
                placeholder="API-ключ"
                type="password"
                className="w-44"
              />
              <Input
                value={yandex.folder_id}
                onChange={(e) => setYandex((y) => ({ ...y, folder_id: e.target.value }))}
                placeholder="Folder ID"
                className="w-36"
              />
              <Button
                onClick={saveY}
                disabled={busy !== "" || !yandex.api_key.trim() || !yandex.folder_id.trim()}
                className="bg-secondary text-foreground hover:bg-elevated disabled:opacity-40"
              >
                {busy === "yandex" ? "Проверяю…" : "Проверить и сохранить"}
              </Button>
            </div>
          </Row>

          {message && <p className="font-mono text-xs text-muted-foreground">{message}</p>}
        </div>
      </div>
    </Panel>
  )
}

/* ── Мелочи ────────────────────────────────────────────────────────────────── */

function CheckLine({ state, title }: { state: "on" | "off" | "warn"; title: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-foreground">
      <Dot state={state} /> {title}
    </p>
  )
}

function Fault({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-primary/40 bg-primary/10 px-3 py-3 text-xs leading-relaxed text-foreground">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <div>{children}</div>
    </div>
  )
}

function Row({
  label,
  status,
  children,
}: {
  label: string
  status: "on" | "off"
  children: React.ReactNode
}) {
  return (
    <div className="border-t border-border pt-3 first:border-0 first:pt-0">
      <p className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
        <Dot state={status} /> {label}
      </p>
      {children}
    </div>
  )
}
