"use client"

import { useEffect, useState } from "react"
import type { ViewId } from "@/lib/spotter-data"
import { useSpotterState } from "@/lib/use-spotter-state"
import { useRaceFeedUnread } from "@/lib/use-racefeed"
import { Sidebar } from "@/components/spotter/sidebar"
import { Topbar } from "@/components/spotter/topbar"
import { StatusBar } from "@/components/spotter/statusbar"
import { DashboardView } from "@/components/spotter/views/dashboard"
import { RaceView } from "@/components/spotter/views/race"
import { VoiceView } from "@/components/spotter/views/voice"
import { EventsView } from "@/components/spotter/views/events"
import { TeamRadioView } from "@/components/spotter/views/team-radio"
import { RaceFeedView } from "@/components/spotter/views/race-feed"
import { SettingsView } from "@/components/spotter/views/settings"
import { LogsView } from "@/components/spotter/views/logs"
import { HotkeysView } from "@/components/spotter/views/hotkeys"
import { ArchiveView } from "@/components/spotter/views/archive"
import { DebriefView } from "@/components/spotter/views/debrief"
import { BroadcastOverlayView } from "@/components/spotter/views/broadcast-overlay"
import { OnboardingView } from "@/components/spotter/views/onboarding"

// "14%" -> 14, "29% (9.1 GB)" -> 29
function pct(v: string | undefined): number | null {
  if (!v) return null
  const m = v.match(/(\d+(?:\.\d+)?)/)
  return m ? Math.round(parseFloat(m[1])) : null
}

export default function Page() {
  const [view, setView] = useState<ViewId>("dashboard")
  const { state, online } = useSpotterState()
  // Визард первого запуска. Показываем только по ЯВНОМУ false: пока настройки
  // не приехали, поле undefined — и экран мигал бы у тех, кто визард уже прошёл.
  const [wizardClosed, setWizardClosed] = useState(false)
  const [wizardManual, setWizardManual] = useState(false)
  const wizardOpen = wizardManual || (!wizardClosed && state?.settings?.onboarding_done === false)
  const { unread, lastSeen, markSeen, hub: raceFeedHub } = useRaceFeedUnread()
  const [raceFeedVisitCutoff, setRaceFeedVisitCutoff] = useState(0)

  const navigate = (next: ViewId) => {
    if (next === "race-feed" && view !== "race-feed") {
      setRaceFeedVisitCutoff(lastSeen)
    }
    setView(next)
  }

  // Открыта вкладка «Репортаж» — считаем всё прочитанным (в т.ч. новые посты,
  // приходящие пока пользователь смотрит), поэтому бейдж на ней всегда 0.
  useEffect(() => {
    if (view === "race-feed") markSeen()
  }, [view, unread, markSeen])

  const connected = state?.connected ?? false
  const signal = {
    udp: connected,
    voice: state?.voice_available ?? false,
    ai: (state?.llm_engine ?? "") === "YandexGPT",
    ses: online && state != null,
  }

  // Визард занимает экран целиком: на первом запуске выбирать в боковом меню
  // ещё нечего, а вернуться к нему можно кнопкой в Настройках.
  if (wizardOpen) {
    return (
      <div className="h-screen w-full overflow-hidden bg-background text-foreground">
        <OnboardingView
          onClose={() => {
            setWizardManual(false)
            setWizardClosed(true)
          }}
        />
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      <Sidebar active={view} onNavigate={navigate} cpu={pct(state?.cpu)} ram={pct(state?.ram)} ramLabel={state?.ram} badges={{ "race-feed": unread }} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          connected={connected}
          signal={signal}
          voiceQuery={state?.voice_query ?? null}
          lastUpdate={state?.race?.last_update ?? null}
        />

        <main className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto max-w-6xl">
            {view === "dashboard" && (
              <DashboardView
                state={state}
                raceFeed={raceFeedHub}
                unreadRaceFeed={unread}
                onOpenRaceFeed={() => navigate("race-feed")}
                onOpenSettings={() => navigate("settings")}
              />
            )}
            {view === "race" && <RaceView state={state} />}
            {view === "voice" && <VoiceView state={state} />}
            {view === "events" && <EventsView state={state} />}
            {view === "team-radio" && <TeamRadioView state={state} online={online} />}
            {view === "race-feed" && (
              <RaceFeedView
                lastSeen={raceFeedVisitCutoff}
                onOpenSettings={() => navigate("settings")}
              />
            )}
            {view === "settings" && (
              <SettingsView state={state} onOpenOnboarding={() => setWizardManual(true)} />
            )}
            {view === "logs" && <LogsView state={state} />}
            {view === "hotkeys" && <HotkeysView state={state} />}
            {view === "archive" && <ArchiveView />}
            {view === "debrief" && <DebriefView state={state} />}
            {view === "broadcast-overlay" && <BroadcastOverlayView state={state} />}
          </div>
        </main>

        <StatusBar
          persona={state?.settings?.persona}
          speaker={state?.speaker}
        />
      </div>
    </div>
  )
}
