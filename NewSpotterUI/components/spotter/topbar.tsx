"use client"

import { useEffect, useRef, useState } from "react"
import { Mic } from "lucide-react"
import { Dot } from "./ui"
import { cn } from "@/lib/utils"
import { askVoice } from "@/lib/api"
import type { VoiceQuery } from "@/lib/api"

type Signal = { udp: boolean; voice: boolean; ai: boolean; ses: boolean }

export function Topbar({
  connected,
  signal,
  voiceQuery,
  lastUpdate,
}: {
  connected: boolean
  signal: Signal
  voiceQuery: VoiceQuery | null
  lastUpdate: string | null
}) {
  const chips: { key: keyof Signal; label: string; title: string }[] = [
    { key: "udp", label: "ИГРА", title: "UDP-телеметрия F1 25" },
    { key: "voice", label: "ГОЛОС", title: "Готовность синтеза речи" },
    { key: "ai", label: "AI", title: "Доступность YandexGPT" },
    { key: "ses", label: "СЕРВЕР", title: "Связь интерфейса с локальным сервером" },
  ]

  const vqBusy =
    voiceQuery?.status === "listening" ||
    voiceQuery?.status === "recognizing" ||
    voiceQuery?.status === "thinking"
  const vqLabel =
    voiceQuery?.status === "listening" ? "Слушаю…" :
    voiceQuery?.status === "recognizing" ? "Распознаю…" :
    voiceQuery?.status === "thinking" ? "Думаю…" :
    "Спросить"

  const [showPopover, setShowPopover] = useState(false)
  const lastStatus = useRef<string | null>(null)

  useEffect(() => {
    const status = voiceQuery?.status ?? null
    if (status !== lastStatus.current && (status === "done" || status === "error")) {
      setShowPopover(true)
    }
    lastStatus.current = status
  }, [voiceQuery?.status])

  return (
    <header className="relative flex h-12 shrink-0 items-center justify-between border-b border-border bg-card px-6">
      <div className="flex items-center gap-5">
        {chips.map((c) => (
          <div key={c.key} className="flex items-center gap-2" title={c.title}>
            <Dot state={signal[c.key] ? "on" : "off"} />
            <span className="label-mono text-[11px] text-muted-foreground">{c.label}</span>
          </div>
        ))}
        {lastUpdate && connected && (
          <span className="hidden font-mono text-[11px] text-muted-foreground xl:inline">
            данные {lastUpdate}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="relative">
          <button
            onClick={() => {
              if (!connected || vqBusy) return
              setShowPopover(false)
              void askVoice()
            }}
            disabled={!connected || vqBusy}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium",
              !connected || vqBusy
                ? "cursor-not-allowed bg-secondary/40 text-muted-foreground"
                : "bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            <Mic className="h-3.5 w-3.5" />
            {vqLabel}
          </button>
          {showPopover && voiceQuery && (voiceQuery.status === "done" || voiceQuery.status === "error") && (
            <div className="absolute right-0 top-full z-10 mt-2 w-72 rounded-md border border-border bg-card p-3 shadow-lg">
              {voiceQuery.status === "error" ? (
                <p className="text-[11px] text-destructive">{voiceQuery.error}</p>
              ) : (
                <>
                  <p className="text-[11px] text-muted-foreground">«{voiceQuery.question}»</p>
                  <p className="mt-1 text-xs text-foreground/90">{voiceQuery.answer}</p>
                </>
              )}
              <button
                onClick={() => setShowPopover(false)}
                className="mt-2 text-[10px] text-muted-foreground hover:text-foreground"
              >
                Закрыть
              </button>
            </div>
          )}
        </div>

        <div
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-1.5",
            !signal.ses
              ? "border-destructive/35 bg-destructive/10"
              : connected
                ? "border-success/40 bg-success/10"
                : "border-warning/35 bg-warning/10",
          )}
        >
          <Dot state={!signal.ses ? "off" : connected ? "on" : "warn"} />
          <span
            className={cn(
              "label-mono text-[10px] font-medium",
              !signal.ses ? "text-destructive" : connected ? "text-success" : "text-warning",
            )}
          >
            {!signal.ses ? "СЕРВЕР OFFLINE" : connected ? "В ГОНКЕ" : "ОЖИДАНИЕ F1"}
          </span>
        </div>
      </div>
    </header>
  )
}
