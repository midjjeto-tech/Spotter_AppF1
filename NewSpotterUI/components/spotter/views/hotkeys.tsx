"use client"

import { Fragment, useEffect, useState } from "react"
import { PageHeader, Panel, KeyCap } from "../ui"
import { Button } from "@/components/ui/button"
import {
  getHotkeyStatus,
  saveSettings,
  type HotkeyStatusResponse,
  type HotkeyStatusRow,
  type PttHotkey,
  type SpotterState,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const FIXED_KEYS = new Set(["C", "P", "T", "X", "S", "O"])

/** id push-to-talk в core/hotkeys.py (_PTT_HOTKEY_ID) — эта строка рисуется
 *  отдельно, с редактором комбинации, поэтому из общего списка исключается. */
const PTT_HOTKEY_ID = 6

/** Подписи кодов core/hotkeys.py::STATUS_*. `taken` — единственный случай, где
 *  пользователь ничего не настраивал неправильно: комбинацию просто держит
 *  другая программа, и Windows отказала в регистрации. */
const STATUS_TEXT: Record<string, { label: string; tone: "ok" | "warn" | "off" }> = {
  ok: { label: "РАБОТАЕТ", tone: "ok" },
  taken: { label: "ЗАНЯТА ДРУГОЙ ПРОГРАММОЙ", tone: "warn" },
  conflict: { label: "ДУБЛИРУЕТ ХОТКЕЙ ВЫШЕ", tone: "warn" },
  not_configured: { label: "НЕ ЗАДАНО", tone: "off" },
}

function StatusBadge({ row }: { row: HotkeyStatusRow | undefined }) {
  if (!row) return null
  const meta = STATUS_TEXT[row.status] ?? { label: "НЕИЗВЕСТНО", tone: "off" as const }
  return (
    <span
      title={row.status}
      className={cn(
        "label-mono shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold",
        meta.tone === "ok" && "bg-success/15 text-success",
        meta.tone === "warn" && "bg-warning/15 text-warning",
        meta.tone === "off" && "bg-secondary text-muted-foreground",
      )}
    >
      {meta.label}
    </span>
  )
}

const CODE_TO_KEY: Record<string, string> = {
  Space: "SPACE",
  Enter: "ENTER",
  NumpadEnter: "ENTER",
  Escape: "ESCAPE",
  Tab: "TAB",
  Backspace: "BACKSPACE",
  Pause: "PAUSE",
  CapsLock: "CAPSLOCK",
  PageUp: "PAGE_UP",
  PageDown: "PAGE_DOWN",
  End: "END",
  Home: "HOME",
  ArrowLeft: "ARROW_LEFT",
  ArrowUp: "ARROW_UP",
  ArrowRight: "ARROW_RIGHT",
  ArrowDown: "ARROW_DOWN",
  PrintScreen: "PRINT_SCREEN",
  Insert: "INSERT",
  Delete: "DELETE",
  ContextMenu: "CONTEXT_MENU",
  NumpadMultiply: "NUM_MULTIPLY",
  NumpadAdd: "NUM_ADD",
  NumpadSubtract: "NUM_SUBTRACT",
  NumpadDecimal: "NUM_DECIMAL",
  NumpadDivide: "NUM_DIVIDE",
  NumLock: "NUMLOCK",
  ScrollLock: "SCROLLLOCK",
  BrowserBack: "BROWSER_BACK",
  BrowserForward: "BROWSER_FORWARD",
  BrowserRefresh: "BROWSER_REFRESH",
  BrowserStop: "BROWSER_STOP",
  BrowserSearch: "BROWSER_SEARCH",
  BrowserFavorites: "BROWSER_FAVORITES",
  BrowserHome: "BROWSER_HOME",
  AudioVolumeMute: "VOLUME_MUTE",
  AudioVolumeDown: "VOLUME_DOWN",
  AudioVolumeUp: "VOLUME_UP",
  MediaTrackNext: "MEDIA_NEXT",
  MediaTrackPrevious: "MEDIA_PREVIOUS",
  MediaStop: "MEDIA_STOP",
  MediaPlayPause: "MEDIA_PLAY_PAUSE",
  LaunchMail: "LAUNCH_MAIL",
  Semicolon: "SEMICOLON",
  Equal: "EQUAL",
  Comma: "COMMA",
  Minus: "MINUS",
  Period: "PERIOD",
  Slash: "SLASH",
  Backquote: "BACKQUOTE",
  BracketLeft: "BRACKET_LEFT",
  Backslash: "BACKSLASH",
  BracketRight: "BRACKET_RIGHT",
  Quote: "QUOTE",
  IntlBackslash: "OEM_102",
}

const KEY_LABELS: Record<string, string> = {
  SPACE: "Space",
  ESCAPE: "Esc",
  BACKSPACE: "Backspace",
  PAGE_UP: "Page Up",
  PAGE_DOWN: "Page Down",
  ARROW_LEFT: "←",
  ARROW_UP: "↑",
  ARROW_RIGHT: "→",
  ARROW_DOWN: "↓",
  PRINT_SCREEN: "Print Screen",
  CONTEXT_MENU: "Menu",
  NUM_MULTIPLY: "Num *",
  NUM_ADD: "Num +",
  NUM_SUBTRACT: "Num −",
  NUM_DECIMAL: "Num .",
  NUM_DIVIDE: "Num /",
  MEDIA_PLAY_PAUSE: "Play / Pause",
  MEDIA_PREVIOUS: "Previous Track",
  MEDIA_NEXT: "Next Track",
  VOLUME_MUTE: "Mute",
  VOLUME_DOWN: "Volume −",
  VOLUME_UP: "Volume +",
  SEMICOLON: ";",
  EQUAL: "=",
  COMMA: ",",
  MINUS: "−",
  PERIOD: ".",
  SLASH: "/",
  BACKQUOTE: "`",
  BRACKET_LEFT: "[",
  BACKSLASH: "\\",
  BRACKET_RIGHT: "]",
  QUOTE: "'",
}

function keyFromEvent(event: KeyboardEvent): string | null {
  if (/^Key[A-Z]$/.test(event.code)) return event.code.slice(3)
  if (/^Digit[0-9]$/.test(event.code)) return event.code.slice(5)
  if (/^Numpad[0-9]$/.test(event.code)) return `NUM${event.code.slice(6)}`
  if (/^F(?:[1-9]|1[0-9]|2[0-4])$/.test(event.code)) return event.code
  return CODE_TO_KEY[event.code] ?? null
}

const keyLabel = (key: string) => KEY_LABELS[key] ?? (key.startsWith("NUM") ? key.replace("NUM", "Num ") : key.replaceAll("_", " "))

export function HotkeysView({ state }: { state: SpotterState | null }) {
  const [ptt, setPtt] = useState<PttHotkey | null>(null)
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState("")
  const [status, setStatus] = useState<HotkeyStatusResponse | null>(null)

  useEffect(() => {
    if (state?.settings?.ptt_hotkey) setPtt(state.settings.ptt_hotkey)
  }, [state?.settings?.ptt_hotkey])

  // Статус регистрации перечитываем редко: он меняется только при старте
  // приложения (RegisterHotKey зовётся один раз в потоке хоткеев).
  useEffect(() => {
    let cancelled = false
    const load = () =>
      getHotkeyStatus()
        .then((r) => !cancelled && setStatus(r))
        .catch(() => !cancelled && setStatus(null))
    load()
    const timer = setInterval(load, 10000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const statusById = new Map((status?.hotkeys ?? []).map((r) => [r.id, r]))
  // Источник списка — бэкенд (core/hotkeys.py::_HOTKEY_LABELS). Пока статус не
  // загружен, показываем то, что бэкенд отдал в прошлый раз, а не свой хардкод.
  const rows = (status?.hotkeys ?? []).filter((r) => r.id !== PTT_HOTKEY_ID)
  const pttRow = statusById.get(PTT_HOTKEY_ID)
  const anyBroken = (status?.hotkeys ?? []).some(
    (r) => r.status === "taken" || r.status === "conflict",
  )

  useEffect(() => {
    if (!recording) return
    const onKeyDown = (e: KeyboardEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (e.key === "Control" || e.key === "Alt" || e.key === "Shift") return
      const key = keyFromEvent(e)
      if (!key) {
        setError("Эту системную клавишу Windows нельзя зарегистрировать")
        return
      }
      const candidate: PttHotkey = { ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, key }
      const collidesWithFixed =
        candidate.ctrl && candidate.alt && !candidate.shift && FIXED_KEYS.has(candidate.key)
      if (collidesWithFixed) {
        setError("Эта комбинация уже занята одним из хоткеев выше")
        return
      }
      setRecording(false)
      setError("")
      const previous = ptt
      setPtt(candidate)
      void saveSettings({ ptt_hotkey: candidate })
        .then((result) => {
          if (result.ok !== true) throw new Error("save_failed")
        })
        .catch(() => {
          setPtt(previous)
          setError("Не удалось сохранить бинд")
        })
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [ptt, recording])

  // Комбинацию берём из настроек, а если /api/state ещё не доехал — из статуса
  // регистрации: он собран из тех же настроек на бэкенде, и показать «Не
  // задано» рядом с бейджем «РАБОТАЕТ» было бы противоречием.
  const pttParts: string[] = ptt
    ? [ptt.ctrl && "Ctrl", ptt.alt && "Alt", ptt.shift && "Shift", keyLabel(ptt.key)].filter(
        (v): v is string => Boolean(v),
      )
    : (pttRow?.keys ?? []).map(keyLabel)

  return (
    <div>
      <PageHeader
        title="Hotkeys"
        subtitle="PTT можно назначить на одну клавишу или сочетание — работает независимо от фокуса окна"
      />

      {status && !status.available && (
        <p className="mb-4 rounded-md border border-warning/30 bg-warning/10 px-4 py-2.5 text-[11px] text-warning">
          Глобальные хоткеи не запущены — комбинации ниже не сработают.
        </p>
      )}
      {anyBroken && (
        <p className="mb-4 rounded-md border border-warning/30 bg-warning/10 px-4 py-2.5 text-[11px] leading-relaxed text-warning">
          Windows отказала в регистрации части комбинаций: их уже держит другая программа
          (Discord, GeForce Experience, Steam и т.п.). Такой хоткей выглядит настроенным,
          но не работает — освободите комбинацию в той программе и перезапустите Spotter App.
        </p>
      )}

      <Panel bodyClassName="p-0">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <span className="label-mono text-[10px] text-muted-foreground">Действие</span>
          <span className="label-mono text-[10px] text-muted-foreground">Клавиши</span>
        </div>
        <ul>
          {rows.map((h) => (
            <li
              key={h.id}
              className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 hover:bg-secondary/40"
            >
              <span className="text-sm font-medium text-foreground">{h.action}</span>
              <div className="flex items-center gap-2.5">
                <StatusBadge row={h} />
                <div className="flex items-center gap-1.5">
                  {h.keys.map((k, i) => (
                    <Fragment key={k}>
                      {i > 0 && <span className="text-xs text-muted-foreground">+</span>}
                      <KeyCap>{k}</KeyCap>
                    </Fragment>
                  ))}
                </div>
              </div>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-5 py-6 text-center text-sm text-muted-foreground">
              {status ? "Хоткеи не зарегистрированы" : "Загрузка статуса хоткеев…"}
            </li>
          )}
          <li className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 last:border-0 hover:bg-secondary/40">
            <div>
              <span className="text-sm font-medium text-foreground">
                Спросить голосом (push-to-talk)
              </span>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Нажмите любую клавишу или сочетание. Применится после перезапуска Spotter App.
              </p>
              <p className="mt-1 text-[11px] text-warning/80">
                Одиночная клавиша становится глобальной — не выбирайте кнопку управления болидом.
              </p>
              {/* Что это на самом деле: закрытый список тем по ключевым словам
                  (commentator/radio_answer.py::_TOPIC_STEMS + _COMMAND_STEMS),
                  а не свободный диалог с ИИ. Раньше UI об этом молчал, и
                  «непонятый» вопрос выглядел как поломка распознавания. */}
              <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                Инженер отвечает на 11 тем: погода, разрыв и соперники, шины, комплекты
                резины, позиция, штрафы, повреждения, топливо, ERS, кругов до финиша,
                окно пит-стопа. Плюс две команды голосом — «замолчи» и «смени персону»
                (то же, что Ctrl+Alt+C и Ctrl+Alt+P). Вопрос вне этого списка останется
                без ответа — это не сбой распознавания.
              </p>
              {state?.yandex_ok === false && (
                <p className="mt-2 text-[11px] leading-relaxed text-warning">
                  Сейчас нет связи с Yandex — распознавание речи не работает, push-to-talk
                  промолчит даже на правильный вопрос.
                </p>
              )}
              {error && <p className="mt-1 text-[11px] text-destructive">{error}</p>}
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge row={pttRow} />
              {recording ? (
                <span className="text-xs text-muted-foreground">Нажмите комбинацию…</span>
              ) : pttParts.length > 0 ? (
                <div className="flex items-center gap-1.5">
                  {pttParts.map((k, i) => (
                    <Fragment key={`${k}-${i}`}>
                      {i > 0 && <span className="text-xs text-muted-foreground">+</span>}
                      <KeyCap>{k}</KeyCap>
                    </Fragment>
                  ))}
                </div>
              ) : (
                <span className="text-xs text-muted-foreground">Не задано</span>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setError("")
                  setRecording((value) => !value)
                }}
              >
                {recording ? "Отмена" : "Изменить"}
              </Button>
            </div>
          </li>
        </ul>
      </Panel>
    </div>
  )
}
