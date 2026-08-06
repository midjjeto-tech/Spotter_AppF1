"use client"

import { useEffect, useState } from "react"
import { getState, type SpotterState } from "./api"

// Опрос /api/state раз в секунду — как старый UI (setInterval(poll, 1000), index.html).
// Цепочка setTimeout вместо setInterval, чтобы запросы не накладывались при подвисании.
export function useSpotterState(intervalMs = 1000) {
  const [state, setState] = useState<SpotterState | null>(null)
  const [online, setOnline] = useState(false)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const s = await getState()
        if (!alive) return
        setState(s)
        setOnline(true)
      } catch {
        if (alive) setOnline(false)
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }

    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return { state, online }
}
