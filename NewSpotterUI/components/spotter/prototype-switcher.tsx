"use client"

import { useEffect } from "react"
import { ChevronLeft, ChevronRight, FlaskConical } from "lucide-react"

type Variant = { key: string; name: string }

export function PrototypeSwitcher({
  variants,
  current,
  onChange,
}: {
  variants: Variant[]
  current: string
  onChange: (key: string) => void
}) {
  const currentIndex = Math.max(0, variants.findIndex((variant) => variant.key === current))
  const cycle = (direction: -1 | 1) => {
    const next = (currentIndex + direction + variants.length) % variants.length
    onChange(variants[next].key)
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.matches("input, textarea, [contenteditable='true']")) return
      if (event.key === "ArrowLeft") cycle(-1)
      if (event.key === "ArrowRight") cycle(1)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  })

  if (process.env.NODE_ENV === "production") return null

  return (
    <div className="fixed bottom-5 left-1/2 z-[100] flex -translate-x-1/2 items-center gap-1 rounded-full border border-white/10 bg-zinc-950/95 p-1.5 text-white shadow-2xl shadow-black/50 backdrop-blur-xl">
      <button
        type="button"
        aria-label="Предыдущий вариант"
        onClick={() => cycle(-1)}
        className="grid h-9 w-9 place-items-center rounded-full text-zinc-400 transition hover:bg-white/10 hover:text-white"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <div className="flex min-w-52 items-center justify-center gap-2 px-3">
        <FlaskConical className="h-3.5 w-3.5 text-cyan-400" />
        <span className="font-mono text-[11px] font-semibold">
          {variants[currentIndex].key} — {variants[currentIndex].name}
        </span>
      </div>
      <button
        type="button"
        aria-label="Следующий вариант"
        onClick={() => cycle(1)}
        className="grid h-9 w-9 place-items-center rounded-full text-zinc-400 transition hover:bg-white/10 hover:text-white"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}
