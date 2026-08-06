"use client"

import { memo, useCallback, useEffect, useRef, useState } from "react"
import {
  ArrowRight, BarChart3, Bell, Bookmark, CheckCheck, ChevronDown, ChevronUp,
  BrainCircuit, Flag, Gauge, History, LockKeyhole, MessageCircle,
  Mic, MoreVertical, Radio, Scale, Sparkles, Swords, Target, Trophy, Vote, X,
} from "lucide-react"

import { getRaceFeedAvatar } from "@/lib/racefeed-avatars"
import { toRaceFeedComment, type RaceFeedArchiveGroup } from "@/lib/racefeed"
import {
  sendRaceFeedComment, sendRaceFeedPrediction, sendRaceFeedReaction, sendRaceFeedVote,
} from "@/lib/api"
import type {
  ChampionshipComparisonRow, InterviewQuoteRow, PollCandidateRow, ProfileInfo,
  PredictionFinishChoice, PredictionRiskChoice, PredictionTeammateChoice,
  RacePredictionRow, RacePredictionTicket, RaceRecapRow, ReturnHookRow,
  SeasonStorylineRow, StandingsRow, TrackReturnRow, WeekendDuelRow,
} from "@/lib/api"
import type { RaceFeedComment, RaceFeedPost } from "@/lib/spotter-data"

export type RaceFeedChannelStatus =
  | "loading"
  | "disabled"
  | "waiting"
  | "ready"
  | "error"

// 1s ticker lets staged expert notes reveal smoothly between 3s feed polls.
function useNowSeconds(): number {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

const REACTION_EMOJI = ["🔥", "👏", "😮", "💪"]

function ruPlural(value: number, one: string, few: string, many: string): string {
  const n = Math.abs(value) % 100
  const last = n % 10
  if (n > 10 && n < 20) return many
  if (last === 1) return one
  if (last >= 2 && last <= 4) return few
  return many
}

function revealState(comments: RaceFeedComment[], nowSec: number) {
  return comments.filter((comment) => comment.revealAt <= nowSec)
}

const ArchivedRace = memo(function ArchivedRace({
  group, onOpenComments, onReact, onVote, withMyActions,
}: {
  group: RaceFeedArchiveGroup
  onOpenComments: (postId: string) => void
  onReact: (postId: string, emoji: string) => void
  onVote: (postId: string, driver: string) => void
  /** Наложение подтверждённых действий читателя: архив опрашивается раз в
   *  минуту и по сигнатуре, которая от реакции не меняется. */
  withMyActions: (post: RaceFeedPost) => RaceFeedPost
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <section className="mt-3 overflow-hidden rounded-2xl border border-white/[0.06] bg-black/15">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.025]"
        aria-expanded={expanded}
      >
        <Flag className="h-4 w-4 shrink-0 text-sky-400" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] font-semibold text-zinc-200">{group.title}</span>
          <span className="text-[10px] text-zinc-500">
            {[group.subtitle, `${group.posts.length} публикаций`].filter(Boolean).join(" · ")}
          </span>
        </span>
        {expanded ? <ChevronUp className="h-4 w-4 text-zinc-500" /> : <ChevronDown className="h-4 w-4 text-zinc-500" />}
      </button>
      {expanded && (
        <div className="space-y-3 border-t border-white/[0.05] p-3">
          <PredictionResultCard prediction={group.prediction} />
          {group.posts.map((post) => (
            <TelegramPost
              key={post.id}
              post={withMyActions(post)}
              comments={post.comments}
              onOpenComments={() => onOpenComments(post.id)}
              onReact={onReact}
              onVote={onVote}
            />
          ))}
        </div>
      )}
    </section>
  )
})

function ChannelAvatar({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`${compact ? "h-10 w-10" : "h-14 w-14"} relative grid shrink-0 place-items-center overflow-hidden rounded-full bg-[conic-gradient(from_210deg,#ff3158,#7c3aed,#0ea5e9,#ff3158)] shadow-lg shadow-red-500/20`}>
      <div className="absolute inset-[2px] rounded-full bg-zinc-950" />
      <span className={`${compact ? "text-xs" : "text-sm"} relative font-black italic tracking-tighter text-white`}>RF</span>
      <span className="absolute bottom-0.5 right-0.5 h-3 w-3 rounded-full border-2 border-zinc-950 bg-emerald-400" />
    </div>
  )
}

function EditorialTeam() {
  const reporters = [
    { id: "race_control", name: "Дирекция гонки" },
    { id: "spotter_analytics", name: "Аналитика Spotter" },
    { id: "players_garage", name: "Боксы игрока" },
    { id: "paddock", name: "Паддок" },
    { id: "qualifying_control", name: "Квалификация" },
    { id: "championship_desk", name: "Чемпионат" },
    { id: "achievements", name: "Достижения" },
  ]
  return (
    <div className="flex items-center gap-2 text-[10px] text-zinc-400">
      <div className="flex -space-x-2">
        {reporters.slice(0, 4).map((reporter) => (
          <img
            key={reporter.id}
            src={getRaceFeedAvatar(reporter.id)}
            alt={reporter.name}
            title={reporter.name}
            className="h-7 w-7 rounded-full border-2 border-[#17212b] bg-zinc-800 object-cover"
          />
        ))}
      </div>
      <span>{reporters.length} AI-корреспондентов</span>
    </div>
  )
}

function CommentCard({ comment, nested = false }: { comment: RaceFeedComment; nested?: boolean }) {
  return (
    <div className={`flex gap-3 ${nested ? "ml-10 border-l border-sky-400/20 pl-3" : ""}`}>
      <img
        src={getRaceFeedAvatar(comment.authorId)}
        alt={comment.authorName}
        className="h-9 w-9 shrink-0 rounded-full border border-white/10 bg-zinc-800 object-cover"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[11px] font-semibold text-zinc-100">{comment.authorName}</span>
          <span className="rounded bg-white/[0.055] px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-zinc-500">{comment.authorBadge}</span>
          {comment.authorId !== "player" && (
            <span className="rounded bg-sky-400/10 px-1.5 py-0.5 text-[8px] uppercase tracking-wider text-sky-300">AI-эксперт</span>
          )}
          <span className="text-[9px] text-zinc-600">{comment.time}</span>
        </div>
        <p className="mt-1 text-[11px] leading-[17px] text-zinc-400">{comment.text}</p>
        {nested && <div className="mt-1.5 text-[9px] text-sky-400">ответ в ветке</div>}
      </div>
    </div>
  )
}

function CommentList({ comments }: { comments: RaceFeedComment[] }) {
  const roots = comments.filter((comment) => !comment.parentId)
  if (comments.length === 0) {
    return (
      <div className="px-4 py-10 text-center">
        <p className="text-xs text-zinc-500">Экспертного разбора пока нет. Можно задать свой вопрос.</p>
      </div>
    )
  }
  return (
    <div className="space-y-5">
      {roots.map((comment) => {
        const replies = comments.filter((reply) => reply.parentId === comment.id)
        return (
          <div key={comment.id} className="space-y-4">
            <CommentCard comment={comment} />
            {replies.map((reply) => <CommentCard key={reply.id} comment={reply} nested />)}
          </div>
        )
      })}
    </div>
  )
}

/** Поле ответа читателя. Реплика уходит в БД той гонки и остаётся там навсегда;
 *  ответы персонажей генерирует воркер и приносит следующий опрос. */
function ReplyBox({ onSend }: { onSend: (text: string) => Promise<boolean> }) {
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  const submit = async () => {
    const body = text.trim()
    if (!body || busy) return
    setBusy(true)
    const ok = await onSend(body)
    setBusy(false)
    setFailed(!ok)
    if (ok) setText("")
  }

  return (
    <div>
      <div className="flex items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.035] p-2">
        <Sparkles className="h-4 w-4 shrink-0 text-violet-400" />
        <input
          value={text}
          onChange={(e) => { setText(e.target.value); setFailed(false) }}
          onKeyDown={(e) => { if (e.key === "Enter") void submit() }}
          maxLength={500}
          placeholder="Задать вопрос по публикации…"
          aria-label="Ваш комментарий"
          className="min-w-0 flex-1 bg-transparent text-[12px] text-zinc-100 outline-none placeholder:text-zinc-500"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!text.trim() || busy}
          className="shrink-0 rounded-lg bg-sky-500/20 px-3 py-1 text-[11px] font-medium text-sky-200 transition hover:bg-sky-500/30 disabled:opacity-40"
        >
          {busy ? "…" : "Отправить"}
        </button>
      </div>
      <p className="mt-1.5 text-[9px] text-zinc-500">
        {failed
          ? "Не удалось отправить — репортаж выключен или запись не прошла."
          : "Комментарий сохранится с гонкой; AI-эксперт ответит по фактам публикации."}
      </p>
    </div>
  )
}

function CommentThread({ post, comments, onClose, onSend }: {
  post: RaceFeedPost
  comments: RaceFeedComment[]
  onClose: () => void
  onSend: (text: string) => Promise<boolean>
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/65 backdrop-blur-sm" onClick={onClose}>
      <section
        aria-label={`Комментарии к публикации ${post.reporter}`}
        className="flex h-full w-full max-w-[470px] flex-col border-l border-white/[0.08] bg-[#0b1220] shadow-2xl shadow-black/50"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center gap-3 border-b border-white/[0.07] px-4 py-3">
          <button aria-label="Закрыть разборы" onClick={onClose} className="grid h-9 w-9 place-items-center rounded-full text-zinc-400 transition hover:bg-white/[0.06] hover:text-white">
            <X className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-white">Разборы и ответы</h3>
            <p className="text-[10px] text-zinc-500">AI-эксперты + ты · сохранено с гонкой</p>
          </div>
          <MoreVertical className="h-4 w-4 text-zinc-500" />
        </header>
        <div className="border-b border-white/[0.06] bg-white/[0.025] p-4">
          <p className="text-[10px] font-semibold text-sky-400">{post.reporter} · {post.time}</p>
          <p className="mt-2 line-clamp-4 text-xs leading-5 text-zinc-300">{post.text}</p>
        </div>
        <div className="flex-1 overflow-y-auto p-4"><CommentList comments={comments} /></div>
        <footer className="border-t border-white/[0.07] p-4">
          <ReplyBox onSend={onSend} />
        </footer>
      </section>
    </div>
  )
}

function ReactionBar({ mine, onReact }: {
  mine: string
  onReact: (emoji: string) => void
}) {
  return (
    <div className="flex items-center gap-1.5">
      {REACTION_EMOJI.map((emoji) => {
        const chosen = emoji === mine
        return (
          <button
            key={emoji}
            type="button"
            // Повторный клик по своей реакции снимает её — пустой emoji на бэкенде
            // удаляет строку (storage.save_reader_action).
            onClick={() => onReact(chosen ? "" : emoji)}
            aria-pressed={chosen}
            title={chosen ? "Убрать реакцию" : "Поставить реакцию"}
            className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] transition ${
              chosen
                ? "bg-sky-400/20 text-sky-200 ring-1 ring-sky-400/40"
                : "bg-white/[0.05] text-zinc-300 hover:bg-white/[0.09]"
            }`}
          >
            <span className="leading-none">{emoji}</span>
          </button>
        )
      })}
    </div>
  )
}

// Итоги зрительского голосования «Гонщик дня»: бар с процентом и заслуги, за
// которые голосовали (обгоны/отыгранные позиции/быстрый круг). Данные считает
// core/driver_of_the_day.py — здесь только отрисовка.
function DriverOfTheDayPoll({ candidates, myVote, onVote }: {
  candidates: PollCandidateRow[]
  myVote: string
  onVote: (driver: string) => void
}) {
  if (!candidates || candidates.length === 0) return null
  return (
    <div className="mt-3 rounded-xl border border-violet-400/20 bg-violet-400/[0.05] p-3">
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-violet-300">
        <Trophy className="h-3.5 w-3.5" /> Гонщик дня · голосование
      </div>
      <div className="space-y-2">
        {candidates.map((c, i) => {
          const chosen = c.driver === myVote
          return (
            <button
              key={c.driver}
              type="button"
              onClick={() => onVote(chosen ? "" : c.driver)}
              aria-pressed={chosen}
              className={`w-full rounded-lg px-2 py-1.5 text-left transition ${
                chosen ? "bg-violet-400/[0.14] ring-1 ring-violet-400/40" : "hover:bg-white/[0.04]"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className={c.is_player ? "font-semibold text-amber-200" : "text-zinc-200"}>
                  {i + 1}. {c.driver}
                  {c.fastest_lap && <span className="ml-1.5 text-[9px] text-violet-300">БК</span>}
                  {chosen && (
                    <span className="ml-1.5 rounded-full bg-violet-400/25 px-1.5 py-0.5 text-[9px] text-violet-100">
                      твой голос
                    </span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-[11px] text-zinc-400">{c.vote_pct}%</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                <div
                  className={`h-full rounded-full ${c.is_player ? "bg-amber-400" : "bg-violet-400/70"}`}
                  style={{ width: `${Math.max(2, Math.min(100, c.vote_pct))}%` }}
                />
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 text-[9px] text-zinc-500">
                <span>P{c.position}</span>
                <span>{c.overtakes} {ruPlural(c.overtakes, "обгон", "обгона", "обгонов")}</span>
                {c.positions_gained > 0 && (
                  <span>+{c.positions_gained} {ruPlural(c.positions_gained, "позиция", "позиции", "позиций")}</span>
                )}
                {c.penalties > 0 && (
                  <span className="text-red-300/80">{c.penalties} {ruPlural(c.penalties, "штраф", "штрафа", "штрафов")}</span>
                )}
              </div>
            </button>
          )
        })}
      </div>
      {/* Проценты — доли смоделированного голосования (core/driver_of_the_day.py),
          размера аудитории в них нет. Дорисовывать к ним «+1 голос» было бы
          выдуманной арифметикой, поэтому отмечаем выбор и честно говорим, что
          итог он не меняет. */}
      <p className="mt-2 text-[9px] leading-4 text-zinc-500">
        {myVote
          ? `Твой голос за ${myVote} сохранён. Итог зрительского голосования он не меняет.`
          : "Можно отметить своего кандидата — итог голосования при этом не меняется."}
      </p>
    </div>
  )
}

// Флэш-интервью после финиша — реконструкция по данным гонки (см.
// core/post_race_interview.py), подаётся как цитаты в стиле трансляции F1.
function InterviewQuotes({ quotes }: { quotes: InterviewQuoteRow[] }) {
  if (!quotes || quotes.length === 0) return null
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-sky-300/90">
        <Mic className="h-3.5 w-3.5" /> Флэш-интервью
      </div>
      {quotes.map((q) => (
        <blockquote
          key={q.driver}
          className={`rounded-lg border-l-2 py-1.5 pl-3 pr-2 ${
            q.is_player
              ? "border-amber-400/70 bg-amber-400/[0.07]"
              : "border-sky-400/40 bg-white/[0.03]"
          }`}
        >
          <div className="flex items-baseline gap-2">
            <span className={`text-[11px] font-semibold ${q.is_player ? "text-amber-200" : "text-zinc-200"}`}>
              {q.driver}
            </span>
            <span className="text-[9px] uppercase tracking-wider text-zinc-500">
              P{q.position} · {q.role}
            </span>
          </div>
          <p className="mt-0.5 text-[11px] italic leading-[17px] text-zinc-300">«{q.quote}»</p>
        </blockquote>
      ))}
    </div>
  )
}

function RaceNumbers({ recap }: { recap: RaceRecapRow | null }) {
  if (!recap) return null
  const change = recap.positions_gained > 0
    ? `+${recap.positions_gained}`
    : String(recap.positions_gained)
  return (
    <div className="mt-3 rounded-xl border border-sky-400/20 bg-sky-400/[0.05] p-3">
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-sky-300">
        <BarChart3 className="h-3.5 w-3.5" /> Гонка в цифрах
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-lg bg-black/20 px-2 py-2 text-center">
          <div className="text-[19px] font-semibold tabular-nums text-white">P{recap.finish_position}</div>
          <div className="text-[9px] text-zinc-500">старт P{recap.grid_position || "—"}</div>
        </div>
        <div className="rounded-lg bg-black/20 px-2 py-2 text-center">
          <div className={`text-[19px] font-semibold tabular-nums ${recap.positions_gained >= 0 ? "text-emerald-300" : "text-red-300"}`}>
            {change}
          </div>
          <div className="text-[9px] text-zinc-500">позиций</div>
        </div>
        <div className="rounded-lg bg-black/20 px-2 py-2 text-center">
          <div className="text-[19px] font-semibold tabular-nums text-sky-200">{recap.overtakes}</div>
          <div className="text-[9px] text-zinc-500">обгонов</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-zinc-500">
        <span>{recap.points} {ruPlural(recap.points, "очко", "очка", "очков")}</span>
        <span>{recap.pit_stops} {ruPlural(recap.pit_stops, "пит-стоп", "пит-стопа", "пит-стопов")}</span>
        {recap.fastest_lap && <span className="text-violet-300">быстрый круг</span>}
        {recap.penalties > 0 && (
          <span className="text-red-300">{recap.penalties} {ruPlural(recap.penalties, "штраф", "штрафа", "штрафов")}</span>
        )}
      </div>
    </div>
  )
}

function ChampionshipDuel({ comparison }: { comparison: ChampionshipComparisonRow | null }) {
  if (!comparison?.rival || comparison.player_points == null || comparison.rival_points == null) return null
  return (
    <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.05] p-3">
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
        <Scale className="h-3.5 w-3.5" /> Дуэль сезона
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div>
          <p className="truncate text-[11px] font-semibold text-amber-100">{comparison.driver || "Ты"}</p>
          <p className="mt-0.5 text-[10px] text-zinc-400">
            {comparison.player_position ? `P${comparison.player_position} · ` : ""}{comparison.player_points} очк.
          </p>
        </div>
        <div className="rounded-full bg-black/25 px-2 py-1 text-[10px] font-semibold tabular-nums text-amber-200">
          {comparison.gap_to_rival ?? Math.abs(comparison.player_points - comparison.rival_points)}
        </div>
        <div className="text-right">
          <p className="truncate text-[11px] font-semibold text-zinc-200">{comparison.rival}</p>
          <p className="mt-0.5 text-[10px] text-zinc-400">
            {comparison.rival_position ? `P${comparison.rival_position} · ` : ""}{comparison.rival_points} очк.
          </p>
        </div>
      </div>
      {comparison.player_race_position && comparison.rival_race_position && (
        <p className="mt-2 border-t border-white/[0.06] pt-2 text-center text-[9px] text-zinc-500">
          В этой гонке: P{comparison.player_race_position} против P{comparison.rival_race_position}
        </p>
      )}
    </div>
  )
}

function formatLapTime(ms: number): string {
  if (ms <= 0) return "—"
  const minutes = Math.floor(ms / 60_000)
  const seconds = (ms % 60_000) / 1000
  return `${minutes}:${seconds.toFixed(3).padStart(6, "0")}`
}

function WeekendTeammateDuel({ duel }: { duel: WeekendDuelRow | null }) {
  if (!duel?.player || !duel?.teammate) return null
  const metrics = [
    {
      label: "Старт",
      player: duel.player.start_position > 0 ? `P${duel.player.start_position}` : "—",
      teammate: duel.teammate.start_position > 0 ? `P${duel.teammate.start_position}` : "—",
      playerWon: duel.player.start_position > 0 && duel.teammate.start_position > 0
        && duel.player.start_position < duel.teammate.start_position,
      teammateWon: duel.player.start_position > 0 && duel.teammate.start_position > 0
        && duel.teammate.start_position < duel.player.start_position,
    },
    {
      label: "Финиш",
      player: `P${duel.player.finish_position}`,
      teammate: `P${duel.teammate.finish_position}`,
      playerWon: duel.player.finish_position < duel.teammate.finish_position,
      teammateWon: duel.teammate.finish_position < duel.player.finish_position,
    },
    {
      label: "Лучший круг",
      player: formatLapTime(duel.player.best_lap_time_ms),
      teammate: formatLapTime(duel.teammate.best_lap_time_ms),
      playerWon: duel.player.best_lap_time_ms > 0 && duel.teammate.best_lap_time_ms > 0
        && duel.player.best_lap_time_ms < duel.teammate.best_lap_time_ms,
      teammateWon: duel.player.best_lap_time_ms > 0 && duel.teammate.best_lap_time_ms > 0
        && duel.teammate.best_lap_time_ms < duel.player.best_lap_time_ms,
    },
    {
      label: "Очки",
      player: String(duel.player.points),
      teammate: String(duel.teammate.points),
      playerWon: duel.player.points > duel.teammate.points,
      teammateWon: duel.teammate.points > duel.player.points,
    },
  ]
  return (
    <div className="mt-3 rounded-xl border border-cyan-400/20 bg-cyan-400/[0.045] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-300">
          <Swords className="h-3.5 w-3.5" /> Дуэль напарников
        </p>
        <span className="text-[9px] text-zinc-500">{duel.team}</span>
      </div>
      <div className="mb-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <p className="truncate text-[11px] font-semibold text-amber-200">{duel.player.driver}</p>
        <span className="rounded-full bg-black/25 px-2 py-1 text-[10px] font-semibold tabular-nums text-cyan-200">
          {duel.player_score}:{duel.teammate_score}
        </span>
        <p className="truncate text-right text-[11px] font-semibold text-zinc-200">{duel.teammate.driver}</p>
      </div>
      <div className="space-y-1">
        {metrics.map((metric) => (
          <div key={metric.label} className="grid grid-cols-[1fr_80px_1fr] items-center gap-2 rounded-lg bg-black/15 px-2 py-1.5 text-[10px]">
            <span className={`tabular-nums ${metric.playerWon ? "font-semibold text-emerald-300" : "text-zinc-300"}`}>{metric.player}</span>
            <span className="text-center text-[9px] text-zinc-600">{metric.label}</span>
            <span className={`text-right tabular-nums ${metric.teammateWon ? "font-semibold text-emerald-300" : "text-zinc-300"}`}>{metric.teammate}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const STORYLINE_TONE: Record<SeasonStorylineRow["tone"], string> = {
  amber: "border-amber-400/20 bg-amber-400/[0.06] text-amber-200",
  red: "border-red-400/20 bg-red-400/[0.06] text-red-200",
  violet: "border-violet-400/20 bg-violet-400/[0.06] text-violet-200",
  green: "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-200",
  sky: "border-sky-400/20 bg-sky-400/[0.06] text-sky-200",
}

function SeasonStorylines({ storylines }: { storylines: SeasonStorylineRow[] }) {
  if (!storylines.length) return null
  return (
    <div className="mt-3">
      <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-violet-300">
        <Gauge className="h-3.5 w-3.5" /> Сюжеты сезона
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        {storylines.map((storyline) => (
          <div key={storyline.id} className={`rounded-xl border p-2.5 ${STORYLINE_TONE[storyline.tone]}`}>
            <p className="text-[9px] font-semibold uppercase tracking-wider opacity-75">{storyline.title}</p>
            <p className="mt-1 text-[17px] font-semibold tabular-nums">{storyline.value}</p>
            <p className="mt-0.5 text-[9px] leading-4 text-zinc-500">{storyline.detail}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function ReturnHook({ hook }: { hook: ReturnHookRow | null }) {
  if (!hook?.title) return null
  return (
    <div className="mt-3 rounded-xl border border-rose-400/25 bg-[linear-gradient(120deg,rgba(244,63,94,0.12),rgba(124,58,237,0.08))] p-3">
      <p className="flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.15em] text-rose-300">
        <Bookmark className="h-3.5 w-3.5" /> Незаконченная история
      </p>
      <div className="mt-1.5 flex items-start justify-between gap-3">
        <div>
          <p className="text-[12px] font-semibold text-white">{hook.title}</p>
          <p className="mt-0.5 text-[10px] leading-4 text-zinc-400">{hook.detail}</p>
        </div>
        <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-rose-300" />
      </div>
    </div>
  )
}

function TelegramPost({ post, comments, onOpenComments, onReact, onVote }: {
  post: RaceFeedPost
  comments: RaceFeedComment[]
  onOpenComments: () => void
  onReact: (postId: string, emoji: string) => void
  onVote: (postId: string, driver: string) => void
}) {
  return (
    <article className="relative rounded-2xl rounded-tl-md border border-white/[0.06] bg-[#202b36] px-4 py-3.5 shadow-xl shadow-black/10">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <img
            src={getRaceFeedAvatar(post.reporterId)}
            alt={post.reporter}
            className="h-9 w-9 shrink-0 rounded-full border border-white/10 bg-zinc-800 object-cover"
          />
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold text-[#56b3f3]">{post.reporter}</p>
            <p className="mt-0.5 text-[10px] uppercase tracking-[0.16em] text-zinc-500">{post.format}</p>
          </div>
        </div>
        <MoreVertical className="h-4 w-4 text-zinc-600" />
      </div>
      <p className="text-[13px] leading-5 text-zinc-100">{post.text}</p>
      {post.image ? (
        <img
          src={`/racefeed/media/${post.image}`}
          alt=""
          className="mt-2.5 max-h-72 w-full rounded-xl border border-white/[0.06] object-cover"
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
        />
      ) : null}
      <DriverOfTheDayPoll
        candidates={post.poll}
        myVote={post.myVote}
        onVote={(driver) => onVote(post.id, driver)}
      />
      <RaceNumbers recap={post.recap} />
      <ChampionshipDuel comparison={post.comparison} />
      <WeekendTeammateDuel duel={post.weekendDuel} />
      <SeasonStorylines storylines={post.storylines} />
      <ReturnHook hook={post.returnHook} />
      <InterviewQuotes quotes={post.interview} />
      <div className="mt-3 flex items-center justify-between gap-2">
        <ReactionBar
          mine={post.myReaction}
          onReact={(emoji) => onReact(post.id, emoji)}
        />
        <span className="text-[9px] text-zinc-600">реакция сохраняется локально</span>
      </div>
      <div className="mt-2.5 flex items-center justify-between border-t border-white/[0.055] pt-2.5">
        {comments.length > 0 ? (
          <button onClick={onOpenComments} className="flex items-center gap-1.5 text-[11px] font-medium text-[#56b3f3] transition hover:text-sky-300">
            <MessageCircle className="h-3.5 w-3.5" /> Обсуждение · {comments.length}
          </button>
        ) : (
          <span />
        )}
        <span className="text-[10px] text-zinc-500">{post.time}</span>
      </div>
    </article>
  )
}

const STATUS_COPY: Record<Exclude<RaceFeedChannelStatus, "ready">, { title: string; text: string }> = {
  loading: {
    title: "Подключаем канал",
    text: "Проверяем состояние RaceFeed…",
  },
  disabled: {
    title: "RaceFeed выключен",
    text: "Включите RaceFeed в настройках. До этого момента генерация, фоновые процессы и вызовы ИИ не запускаются.",
  },
  waiting: {
    title: "Канал карьеры готов",
    text: "Публикации появятся по ходу первого Гран-при: только после реальных событий телеметрии и редакционного отбора.",
  },
  error: {
    title: "Канал временно недоступен",
    text: "Не удалось получить RaceFeed. Приложение повторит запрос автоматически.",
  },
}

/** compact — под блоком есть архив прошлых гонок, поэтому пустое состояние не
 *  занимает весь экран и не выглядит так, будто в канале вообще ничего нет. */
function EmptyChannel({ status, compact = false, onOpenSettings }: {
  status: Exclude<RaceFeedChannelStatus, "ready">
  compact?: boolean
  onOpenSettings?: () => void
}) {
  const copy = STATUS_COPY[status]
  if (compact) {
    return (
      <div className="mx-auto flex w-fit items-center gap-3 rounded-full border border-white/[0.06] bg-white/[0.03] px-4 py-2 text-[11px] text-zinc-400">
        <span className="flex items-center gap-2">
          <Radio className={`h-3.5 w-3.5 text-sky-400 ${status === "loading" ? "animate-pulse" : ""}`} />
          {copy.title}
        </span>
        {status === "disabled" && onOpenSettings && (
          <button type="button" onClick={onOpenSettings} className="font-medium text-sky-300 transition hover:text-sky-200">
            Включить
          </button>
        )}
      </div>
    )
  }
  return (
    <div className="grid min-h-[620px] place-items-center px-6 py-16 text-center">
      <div className="max-w-md">
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-full border border-sky-400/15 bg-sky-400/[0.07]">
          <Radio className={`h-7 w-7 text-sky-400 ${status === "loading" ? "animate-pulse" : ""}`} />
        </div>
        <h3 className="mt-5 text-base font-semibold text-white">{copy.title}</h3>
        <p className="mt-2 text-xs leading-5 text-zinc-400">{copy.text}</p>
        {status === "disabled" && onOpenSettings && (
          <button
            type="button"
            onClick={onOpenSettings}
            className="mt-5 rounded-xl bg-sky-500 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-sky-400"
          >
            Открыть настройки RaceFeed
          </button>
        )}
        <div className="mt-6 rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-3 text-left text-[11px] leading-5 text-zinc-500">
          Здесь нет демонстрационных постов. Каждая публикация относится к текущей карьере, а AI-разборы явно подписаны.
        </div>
      </div>
    </div>
  )
}

const FINISH_OPTIONS: { value: PredictionFinishChoice; label: string }[] = [
  { value: "podium", label: "Подиум" },
  { value: "points", label: "P4–P10" },
  { value: "outside_points", label: "Вне топ-10" },
]
const TEAMMATE_OPTIONS: { value: PredictionTeammateChoice; label: string }[] = [
  { value: "player", label: "Ты" },
  { value: "teammate", label: "Напарник" },
  { value: "draw", label: "Ничья" },
]
const RISK_OPTIONS: { value: PredictionRiskChoice; label: string }[] = [
  { value: "safety_car", label: "Safety Car" },
  { value: "rain", label: "Дождь" },
  { value: "penalty", label: "Штраф" },
]

type PredictionKind = "finish" | "teammate" | "risk"

function predictionLabel(kind: PredictionKind, choice: string | undefined, prediction: RacePredictionRow): string {
  if (!choice) return "—"
  if (kind === "finish") return FINISH_OPTIONS.find((item) => item.value === choice)?.label ?? choice
  if (kind === "risk") return RISK_OPTIONS.find((item) => item.value === choice)?.label ?? choice
  if (choice === "player") return prediction.model_forecast.participants.player || "Ты"
  if (choice === "teammate") return prediction.model_forecast.participants.teammate || "Напарник"
  return "Ничья"
}

function TrackReturnCard({ data }: { data: Partial<TrackReturnRow> }) {
  if (!data.goal?.label || !data.finish_position) return null
  const date = data.last_visit_date
    ? new Date(data.last_visit_date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })
    : "прошлый визит"
  return (
    <section className="overflow-hidden rounded-2xl border border-cyan-400/20 bg-[linear-gradient(135deg,rgba(6,182,212,0.10),rgba(9,15,24,0.92)_62%)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300">
            <History className="h-3.5 w-3.5" /> Возвращение на трассу
          </p>
          <h3 className="mt-1 text-[15px] font-semibold text-white">{data.track_name}</h3>
          <p className="mt-0.5 text-[10px] text-zinc-500">{date} · {data.visits} визит(а)</p>
        </div>
        <span className="rounded-lg bg-cyan-400/10 px-2.5 py-1.5 text-[12px] font-bold text-cyan-200">P{data.finish_position}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
        <div className="rounded-xl bg-black/20 p-2.5">
          <p className="text-zinc-500">Лучший круг прошлого визита</p>
          <p className="mt-1 font-semibold text-zinc-200">{data.last_visit_best_lap_ms ? formatLapTime(data.last_visit_best_lap_ms) : "нет данных"}</p>
        </div>
        <div className="rounded-xl bg-black/20 p-2.5">
          <p className="text-zinc-500">Личный рекорд трассы</p>
          <p className="mt-1 font-semibold text-zinc-200">{data.personal_best_lap_ms ? formatLapTime(data.personal_best_lap_ms) : "нет данных"}</p>
        </div>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {data.main_setback && <p className="rounded-lg bg-red-400/[0.06] px-3 py-2 text-[10px] leading-4 text-red-100/75">{data.main_setback.label}</p>}
        <p className="flex items-center gap-1.5 rounded-lg bg-emerald-400/[0.07] px-3 py-2 text-[10px] font-medium text-emerald-200">
          <Target className="h-3.5 w-3.5" /> Цель: {data.goal.label}
        </p>
      </div>
    </section>
  )
}

function PredictionCard({ prediction }: { prediction: RacePredictionRow }) {
  const [current, setCurrent] = useState(prediction)
  const [draft, setDraft] = useState<RacePredictionTicket>(prediction.reader_ticket ?? {})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    setCurrent(prediction)
    setDraft(prediction.reader_ticket ?? {})
  }, [prediction])

  const sections: { kind: PredictionKind; title: string; options: { value: string; label: string }[] }[] = [
    { kind: "finish", title: "Где финишируешь", options: FINISH_OPTIONS },
    { kind: "teammate", title: `Дуэль с ${current.model_forecast.participants.teammate}`, options: TEAMMATE_OPTIONS },
    { kind: "risk", title: "Главный риск гонки", options: RISK_OPTIONS },
  ]
  const complete = Boolean(draft.finish && draft.teammate && draft.risk)
  const locked = current.status !== "open"

  const submit = async () => {
    if (!complete || saving || locked) return
    setSaving(true)
    setError("")
    try {
      const result = await sendRaceFeedPrediction(draft)
      if (!result.ok || !result.prediction) {
        setError(result.reason === "prediction_locked" ? "Старт дан — билет уже закрыт." : "Не удалось сохранить билет.")
      } else {
        setCurrent(result.prediction)
        setDraft(result.prediction.reader_ticket)
      }
    } catch {
      setError("Нет связи с RaceFeed.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-violet-400/25 bg-[linear-gradient(145deg,rgba(124,58,237,0.14),rgba(10,15,24,0.94)_58%)] p-4 shadow-lg shadow-black/10">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-300">
            <BrainCircuit className="h-3.5 w-3.5" /> Ты против Spotter AI
          </p>
          <h3 className="mt-1 text-[15px] font-semibold text-white">Прогноз на {current.track_name || "гонку"}</h3>
        </div>
        {locked && (
          <span className="flex items-center gap-1 rounded-full bg-amber-400/10 px-2 py-1 text-[9px] font-semibold text-amber-200">
            <LockKeyhole className="h-3 w-3" /> закрыт
          </span>
        )}
      </div>

      <div className="mt-4 space-y-3">
        {sections.map(({ kind, title, options }) => {
          const forecast = current.model_forecast[kind]
          return (
            <div key={kind} className="rounded-xl border border-white/[0.06] bg-black/20 p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-1.5">
                <p className="text-[10px] font-semibold text-zinc-300">{title}</p>
                <span className="text-[9px] text-violet-300">
                  AI: {predictionLabel(kind, forecast.choice, current)} · {forecast.confidence}%
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                {options.map((option) => {
                  const chosen = draft[kind] === option.value
                  return (
                    <button
                      key={option.value}
                      type="button"
                      disabled={locked}
                      onClick={() => setDraft((prev) => ({ ...prev, [kind]: option.value }))}
                      className={`rounded-lg px-2 py-2 text-[10px] font-medium transition ${
                        chosen
                          ? "bg-violet-400/20 text-violet-100 ring-1 ring-violet-400/50"
                          : "bg-white/[0.035] text-zinc-500 hover:bg-white/[0.07] hover:text-zinc-300"
                      } disabled:cursor-default`}
                    >
                      {kind === "teammate" ? predictionLabel(kind, option.value, current) : option.label}
                    </button>
                  )
                })}
              </div>
              <p className="mt-2 text-[9px] leading-4 text-zinc-600">{forecast.basis}</p>
            </div>
          )
        })}
      </div>

      {locked ? (
        <p className="mt-3 flex items-center gap-1.5 text-[10px] text-amber-100/70">
          <LockKeyhole className="h-3.5 w-3.5" /> Билет закрыт стартовыми огнями. Итог появится после классификации.
        </p>
      ) : (
        <button
          type="button"
          disabled={!complete || saving}
          onClick={submit}
          className="mt-3 w-full rounded-xl bg-violet-500 px-3 py-2.5 text-[11px] font-semibold text-white transition hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-35"
        >
          {saving ? "Сохраняем…" : Object.keys(current.reader_ticket ?? {}).length ? "Обновить билет" : "Зафиксировать прогноз"}
        </button>
      )}
      {error && <p className="mt-2 text-[10px] text-red-300">{error}</p>}
      <p className="mt-2 text-[9px] text-zinc-600">Прогноз AI детерминирован и сохранён до старта — после гонки он не меняется.</p>
    </section>
  )
}

function PredictionResultCard({ prediction }: { prediction: RacePredictionRow | null | undefined }) {
  if (!prediction || prediction.status !== "resolved" || !prediction.result.actual) return null
  const result = prediction.result
  const rows: { kind: PredictionKind; title: string }[] = [
    { kind: "finish", title: "Финиш" },
    { kind: "teammate", title: "Дуэль" },
    { kind: "risk", title: "Риск" },
  ]
  const readerScore = result.reader_score
  return (
    <div className="mt-3 rounded-xl border border-violet-400/20 bg-violet-400/[0.055] p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-violet-300">
          <BrainCircuit className="h-3.5 w-3.5" /> Ты против Spotter AI
        </p>
        <span className="text-[13px] font-bold text-white">
          {readerScore == null ? `AI ${result.model_score}/3` : `Ты ${readerScore}:${result.model_score} AI`}
        </span>
      </div>
      <div className="mt-3 space-y-1.5">
        {rows.map(({ kind, title }) => {
          const readerPick = prediction.reader_ticket[kind]
          const modelPick = prediction.model_forecast[kind].choice
          const readerHit = result.reader_hits?.[kind]
          const modelHit = result.model_hits?.[kind]
          return (
            <div key={kind} className="grid grid-cols-[62px_1fr_1fr] gap-2 rounded-lg bg-black/15 px-2.5 py-2 text-[9px]">
              <span className="text-zinc-500">{title}</span>
              <span className={readerHit ? "text-emerald-300" : "text-zinc-400"}>Ты: {predictionLabel(kind, readerPick, prediction)} {readerPick ? (readerHit ? "✓" : "×") : ""}</span>
              <span className={modelHit ? "text-emerald-300" : "text-zinc-400"}>AI: {predictionLabel(kind, modelPick, prediction)} {modelHit ? "✓" : "×"}</span>
            </div>
          )
        })}
      </div>
      {prediction.scoreboard && prediction.scoreboard.races > 0 && (
        <p className="mt-2 text-[9px] text-zinc-500">Счёт сезона: ты {prediction.scoreboard.reader}:{prediction.scoreboard.model} Spotter AI · {prediction.scoreboard.races} гонок</p>
      )}
    </div>
  )
}

function ChampionshipStandings({ standings }: { standings: StandingsRow[] }) {
  const [expanded, setExpanded] = useState(false)
  if (standings.length === 0) return null
  const player = standings.find((row) => row.is_player)
  const focus = [
    standings[0],
    player,
    standings.find((row) => row.is_rival && !row.is_player),
  ].filter((row, index, rows): row is StandingsRow =>
    Boolean(row) && rows.findIndex((candidate) => candidate?.driver === row?.driver) === index)
    .sort((a, b) => a.position - b.position)
  const visible = expanded ? standings.slice(0, 10) : focus
  return (
    <div className="mb-1 rounded-2xl border border-amber-400/15 bg-amber-400/[0.04] p-3">
      <div className="mb-2 flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wider text-amber-300/90">
        <span>🏆 Чемпионат сезона</span>
        {standings.length > focus.length && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex items-center gap-1 text-[9px] normal-case tracking-normal text-zinc-500 transition hover:text-zinc-300"
          >
            {expanded ? "Свернуть" : "Топ-10"}
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
        )}
      </div>
      <div className="space-y-1">
        {visible.map((row) => (
          <div
            key={row.driver}
            className={`flex items-center gap-2 rounded-lg px-2 py-1 text-[12px] ${
              row.is_player ? "bg-amber-400/[0.12] font-semibold text-amber-100" : "text-zinc-300"
            }`}
          >
            <span className="w-5 shrink-0 tabular-nums text-zinc-500">{row.position}</span>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: row.color ?? "#9CA3AF" }} />
            <span className="min-w-0 flex-1 truncate">{row.driver}</span>
            {row.is_player && (
              <span className="shrink-0 rounded bg-amber-400/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-200">ты</span>
            )}
            {row.is_rival && !row.is_player && (
              <span className="shrink-0 rounded bg-red-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-red-300">соперник</span>
            )}
            <span className="shrink-0 tabular-nums text-zinc-400">{row.points}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const HIGHLIGHT_CATEGORIES = new Set([
  "player_overtake", "player_fastest_lap", "player_pit_stop", "incident",
  "penalty", "milestone", "player_progression",
])

const MOMENT_LABELS: Record<string, string> = {
  player_overtake: "Обгон",
  player_fastest_lap: "Быстрый круг",
  player_pit_stop: "Пит-стоп",
  incident: "Инцидент",
  penalty: "Штраф",
  milestone: "Достижение",
  player_progression: "Прогресс",
}

function RaceMomentPoll({ candidates, myVote, onVote }: {
  candidates: RaceFeedPost[]
  myVote: string
  onVote: (value: string) => void
}) {
  if (candidates.length === 0) return null
  return (
    <div className="rounded-xl border border-fuchsia-400/20 bg-fuchsia-400/[0.045] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-fuchsia-300">
          <Vote className="h-3.5 w-3.5" /> Момент гонки
        </p>
        <span className="text-[9px] text-zinc-500">выбери один</span>
      </div>
      <div className="space-y-1.5">
        {candidates.map((post, index) => {
          const value = `moment:${post.id}`
          const chosen = myVote === value
          return (
            <button
              key={post.id}
              type="button"
              onClick={() => onVote(chosen ? "" : value)}
              aria-pressed={chosen}
              className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition ${
                chosen
                  ? "bg-fuchsia-400/[0.14] ring-1 ring-fuchsia-400/40"
                  : "bg-black/15 hover:bg-white/[0.05]"
              }`}
            >
              <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold ${
                chosen ? "bg-fuchsia-400 text-black" : "bg-white/[0.06] text-zinc-400"
              }`}>
                {chosen ? "✓" : index + 1}
              </span>
              <span className="min-w-0">
                <span className="block text-[9px] font-semibold uppercase tracking-wider text-fuchsia-300/80">
                  {MOMENT_LABELS[post.category] ?? post.reporter}
                </span>
                <span className="mt-0.5 block line-clamp-2 text-[10px] leading-4 text-zinc-300">{post.text}</span>
              </span>
            </button>
          )
        })}
      </div>
      <p className="mt-2 text-[9px] text-zinc-500">
        {myVote.startsWith("moment:") ? "Твой выбор сохранён локально." : "Это твой реальный выбор — без выдуманной аудитории."}
      </p>
    </div>
  )
}

function WeekendDossier({
  group, standings, lastSeen, onOpenComments, onReact, onVote, withMyActions,
}: {
  group: RaceFeedArchiveGroup
  standings: StandingsRow[]
  lastSeen: number
  onOpenComments: (postId: string) => void
  onReact: (postId: string, emoji: string) => void
  onVote: (postId: string, driver: string) => void
  withMyActions: (post: RaceFeedPost) => RaceFeedPost
}) {
  const [timelineOpen, setTimelineOpen] = useState(false)
  const dotd = group.posts.find((post) => post.category === "driver_of_the_day")
  const interview = group.posts.find((post) => post.category === "post_race_interview")
  const recap = group.posts.find((post) => post.category === "race_recap")
  const championship = group.posts.find((post) => post.category === "championship")
  const result = championship
    ?? group.posts.find((post) => post.category === "flag")
    ?? group.posts[0]
  const highlights = group.posts
    .filter((post) => post.id !== result?.id && HIGHLIGHT_CATEGORIES.has(post.category))
    .filter((post, index, posts) =>
      posts.findIndex((candidate) => candidate.category === post.category) === index)
    .slice(0, 3)
  const newCount = lastSeen > 0
    ? group.posts.filter((post) => post.publishedAt > lastSeen).length
    : group.posts.length
  const player = standings.find((row) => row.is_player)
  const rival = standings.find((row) => row.is_rival && !row.is_player)
  const rivalGap = player && rival ? Math.abs(player.points - rival.points) : null

  return (
    <section className="overflow-hidden rounded-2xl border border-violet-400/20 bg-[linear-gradient(145deg,rgba(124,58,237,0.12),rgba(14,22,33,0.92)_52%)] shadow-xl shadow-black/15">
      <div className="border-b border-white/[0.06] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300">
              <Sparkles className="h-3.5 w-3.5" /> Досье уик-энда
            </div>
            <h3 className="mt-1 text-[16px] font-semibold text-white">{group.title}</h3>
            {group.subtitle && <p className="mt-0.5 text-[10px] text-zinc-500">{group.subtitle}</p>}
          </div>
          {newCount > 0 && (
            <span className="rounded-full bg-sky-400/12 px-2.5 py-1 text-[9px] font-semibold text-sky-300">
              С прошлого визита · {newCount}
            </span>
          )}
        </div>

        {result && (
          <div className="mt-4 rounded-xl border border-white/[0.07] bg-black/20 p-3">
            <p className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">Итог гонки</p>
            <p className="mt-1.5 text-[13px] leading-5 text-zinc-100">{result.text}</p>
          </div>
        )}

        <RaceNumbers recap={recap?.recap ?? null} />
        <ChampionshipDuel comparison={championship?.comparison ?? null} />
        <WeekendTeammateDuel duel={recap?.weekendDuel ?? null} />
        <SeasonStorylines storylines={championship?.storylines ?? []} />
        <ReturnHook hook={championship?.returnHook ?? null} />
        <PredictionResultCard prediction={group.prediction} />

        {!championship?.comparison && player && rival && (
          <p className="mt-3 rounded-lg bg-amber-400/[0.07] px-3 py-2 text-[10px] leading-4 text-amber-100/80">
            Следующая цель: {player.points >= rival.points ? "удержать" : "отыграть"} {rivalGap} очка в борьбе с {rival.driver}.
          </p>
        )}
      </div>

      <div className="space-y-4 p-4">
        {result && (
          <RaceMomentPoll
            candidates={highlights}
            myVote={withMyActions(result).myVote}
            onVote={(value) => onVote(result.id, value)}
          />
        )}

        {dotd && (
          <DriverOfTheDayPoll
            candidates={dotd.poll}
            myVote={withMyActions(dotd).myVote}
            onVote={(driver) => onVote(dotd.id, driver)}
          />
        )}
        {!dotd && (
          <div className="rounded-xl border border-violet-400/15 bg-violet-400/[0.04] px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-violet-300">
              <Trophy className="h-3.5 w-3.5" /> Гонщик дня
            </p>
            <p className="mt-1 text-[10px] leading-4 text-zinc-500">
              В этой старой записи голосование не сохранилось. После следующего финиша карточка появится здесь автоматически.
            </p>
          </div>
        )}
        {interview && <InterviewQuotes quotes={interview.interview} />}

        <button
          type="button"
          onClick={() => setTimelineOpen((value) => !value)}
          className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-[10px] font-medium text-zinc-400 transition hover:bg-white/[0.05] hover:text-zinc-200"
          aria-expanded={timelineOpen}
        >
          {timelineOpen ? "Скрыть хронологию" : `Открыть хронологию · ${group.posts.length}`}
          {timelineOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>

        {timelineOpen && (
          <div className="space-y-3 border-t border-white/[0.06] pt-4">
            {group.posts.map((post) => (
              <TelegramPost
                key={post.id}
                post={withMyActions(post)}
                comments={post.comments}
                onOpenComments={() => onOpenComments(post.id)}
                onReact={onReact}
                onVote={onVote}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function ProfileStrip({ profile }: { profile: ProfileInfo | null }) {
  if (!profile) return null
  const parts: string[] = []
  if (profile.championship_position != null)
    parts.push(`Чемпионат P${profile.championship_position}${profile.championship_points != null ? ` · ${profile.championship_points} очк` : ""}`)
  if (profile.career)
    parts.push(`${profile.career.wins}🏆 ${profile.career.podiums}🥉`)
  if (profile.best_result != null)
    parts.push(`лучший в сезоне P${profile.best_result}`)
  if (parts.length === 0) return null
  return <p className="mt-0.5 truncate text-[10px] text-amber-300/80">{parts.join(" · ")}</p>
}

export function RaceFeedChannel({ posts, archive = [], prediction = null, status, standings = [], profile = null, lastSeen = 0, onOpenSettings }: {
  posts: RaceFeedPost[]
  archive?: RaceFeedArchiveGroup[]
  prediction?: RacePredictionRow | null
  status: RaceFeedChannelStatus
  standings?: StandingsRow[]
  profile?: ProfileInfo | null
  lastSeen?: number
  onOpenSettings?: () => void
}) {
  const nowSec = useNowSeconds()
  const [selectedPostId, setSelectedPostId] = useState<string | null>(null)

  // ── Действия читателя ──────────────────────────────────────────────────────
  // Бэкенд (core/racefeed/reader.py) пишет их в SQLite самой сессии, и обратно
  // они приезжают в post.reader на следующем опросе: 3 с у живой ленты. Но у
  // архива опрос раз в 60 с И сравнение по сигнатуре «сессия:число постов» —
  // реакция сигнатуру не меняет, то есть сама бы никогда не доехала. Поэтому
  // ПОДТВЕРЖДЁННОЕ бэкендом действие держим ещё и локально. Это не
  // оптимистичное обновление: локальная копия появляется только после ok.
  const [myActions, setMyActions] =
    useState<Record<string, { reaction?: string; vote?: string }>>({})
  // Собственные реплики в тредах — reader.add_comment возвращает строку именно
  // затем, чтобы показать её сразу, а не ждать генерации ответов персон.
  const [myComments, setMyComments] =
    useState<Record<string, RaceFeedComment[]>>({})

  // Хендлеры должны быть стабильными (архивные группы мемоизированы), поэтому
  // ищут пост через ref, а не через замыкание по пропсам.
  const lookup = useRef<RaceFeedPost[]>([])
  lookup.current = [...posts, ...archive.flatMap((group) => group.posts)]

  const sessionOf = (postId: string) =>
    lookup.current.find((post) => post.id === postId)?.sessionId ?? ""

  const handleReact = useCallback(async (postId: string, emoji: string) => {
    const session_id = sessionOf(postId)
    if (!session_id) return
    try {
      const result = await sendRaceFeedReaction({ session_id, post_id: postId, emoji })
      if (result.ok) {
        setMyActions((prev) => ({
          ...prev, [postId]: { ...prev[postId], reaction: emoji },
        }))
      }
    } catch {
      /* сеть/бэкенд недоступны — молча оставляем как было */
    }
  }, [])

  const handleVote = useCallback(async (postId: string, driver: string) => {
    const session_id = sessionOf(postId)
    if (!session_id) return
    try {
      const result = await sendRaceFeedVote({ session_id, post_id: postId, driver })
      if (result.ok) {
        setMyActions((prev) => ({
          ...prev, [postId]: { ...prev[postId], vote: driver },
        }))
      }
    } catch {
      /* см. handleReact */
    }
  }, [])

  const handleSend = useCallback(async (postId: string, text: string) => {
    const session_id = sessionOf(postId)
    if (!session_id) return false
    try {
      const result = await sendRaceFeedComment({ session_id, post_id: postId, text })
      if (!result.ok || !result.comment) return false
      const comment = toRaceFeedComment(result.comment)
      setMyComments((prev) => {
        const existing = prev[postId] ?? []
        if (existing.some((item) => item.id === comment.id)) return prev
        return { ...prev, [postId]: [...existing, comment] }
      })
      return true
    } catch {
      return false
    }
  }, [])

  /** Пост с наложенными подтверждёнными действиями читателя. */
  const withMyActions = useCallback((post: RaceFeedPost): RaceFeedPost => {
    const mine = myActions[post.id]
    if (!mine) return post
    return {
      ...post,
      myReaction: mine.reaction ?? post.myReaction,
      myVote: mine.vote ?? post.myVote,
    }
  }, [myActions])

  /** Реплики читателя, которых ещё нет в ответе бэкенда, — в конец треда. */
  const withMyComments = useCallback((postId: string, comments: RaceFeedComment[]) => {
    const mine = myComments[postId]
    if (!mine?.length) return comments
    const known = new Set(comments.map((comment) => comment.id))
    const extra = mine.filter((comment) => !known.has(comment.id))
    return extra.length ? [...comments, ...extra] : comments
  }, [myComments])

  const archivePosts = archive.flatMap((group) => group.posts)
  const selectedPost =
    posts.find((post) => post.id === selectedPostId)
    ?? archivePosts.find((post) => post.id === selectedPostId)
    ?? null
  const selectedReveal = selectedPost ? revealState(selectedPost.comments, nowSec) : null
  // Стабильная ссылка — иначе мемоизация архивных групп бесполезна.
  const openComments = useCallback((postId: string) => setSelectedPostId(postId), [])
  const latestArchive = archive[0]
  const currentFinished = prediction?.status === "resolved" || posts.some((post) => [
    "race_recap", "championship", "driver_of_the_day", "post_race_interview",
  ].includes(post.category))
  const currentDossier: RaceFeedArchiveGroup | null = currentFinished
    ? {
        sessionId: posts[0]?.sessionId ?? prediction?.session_id ?? "current",
        title: "Итоги текущего Гран-при",
        subtitle: "",
        posts,
        prediction,
      }
    : null

  useEffect(() => {
    if (!selectedPostId) return
    const stillThere =
      posts.some((post) => post.id === selectedPostId)
      || archive.some((group) => group.posts.some((post) => post.id === selectedPostId))
    if (!stillThere) setSelectedPostId(null)
  }, [posts, archive, selectedPostId])

  return (
    <>
      <div className="mx-auto max-w-[760px] overflow-hidden rounded-[24px] border border-white/[0.07] bg-[#0e1621] shadow-2xl shadow-black/25">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-white/[0.06] bg-[#17212b]/95 px-4 py-3 backdrop-blur-xl">
          <ChannelAvatar compact />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <h2 className="truncate text-[14px] font-semibold text-white">RaceFeed · канал карьеры</h2>
              <CheckCheck className="h-3.5 w-3.5 text-[#56b3f3]" />
            </div>
            <EditorialTeam />
            <ProfileStrip profile={profile} />
          </div>
          {status === "ready" && (
            <span className="flex items-center gap-1 rounded-full bg-emerald-400/10 px-2 py-1 text-[9px] font-semibold uppercase tracking-wider text-emerald-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" /> в эфире
            </span>
          )}
          <Bell className="h-4 w-4 text-zinc-400" />
          <MoreVertical className="h-5 w-5 text-zinc-400" />
        </header>

        <div className="min-h-[650px] space-y-3 bg-[radial-gradient(circle_at_12px_12px,rgba(85,179,243,0.035)_1px,transparent_1.5px)] bg-[length:24px_24px] p-3 sm:p-5">
          <ChampionshipStandings standings={standings} />
          {prediction && prediction.status !== "resolved" && prediction.track_return && (
            <TrackReturnCard data={prediction.track_return} />
          )}
          {prediction && prediction.status !== "resolved" && (
            <PredictionCard prediction={prediction} />
          )}
          {latestArchive && status !== "ready" && (
            <WeekendDossier
              group={latestArchive}
              standings={standings}
              lastSeen={lastSeen}
              onOpenComments={openComments}
              onReact={handleReact}
              onVote={handleVote}
              withMyActions={withMyActions}
            />
          )}
          {status === "ready" ? (
            currentDossier ? (
              <WeekendDossier
                group={currentDossier}
                standings={standings}
                lastSeen={lastSeen}
                onOpenComments={openComments}
                onReact={handleReact}
                onVote={handleVote}
                withMyActions={withMyActions}
              />
            ) : (
              <>
                <div className="mx-auto w-fit rounded-full bg-black/35 px-3 py-1 text-[10px] text-zinc-400">Текущий Гран-при</div>
                {posts.map((post) => {
                  const revealed = revealState(post.comments, nowSec)
                  return (
                    <TelegramPost
                      key={post.id}
                      post={withMyActions(post)}
                      comments={withMyComments(post.id, revealed)}
                      onOpenComments={() => setSelectedPostId(post.id)}
                      onReact={handleReact}
                      onVote={handleVote}
                    />
                  )
                })}
              </>
            )
          ) : (
            // Статус описывает только текущую гонку — архив ниже показывается
            // и когда живой ленты ещё нет (между гонками это обычное состояние).
            <EmptyChannel status={status} compact={archive.length > 0} onOpenSettings={onOpenSettings} />
          )}
          {latestArchive && status === "ready" && (
            <WeekendDossier
              group={latestArchive}
              standings={standings}
              lastSeen={lastSeen}
              onOpenComments={openComments}
              onReact={handleReact}
              onVote={handleVote}
              withMyActions={withMyActions}
            />
          )}
          {archive.slice(1).map((group) => (
            <ArchivedRace
              key={group.sessionId}
              group={group}
              onOpenComments={openComments}
              onReact={handleReact}
              onVote={handleVote}
              withMyActions={withMyActions}
            />
          ))}
        </div>
      </div>

      {selectedPost && (
        <CommentThread
          post={selectedPost}
          comments={withMyComments(selectedPost.id, selectedReveal ?? [])}
          onClose={() => setSelectedPostId(null)}
          onSend={(text) => handleSend(selectedPost.id, text)}
        />
      )}
    </>
  )
}
