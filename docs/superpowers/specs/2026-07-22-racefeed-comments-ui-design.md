# RaceFeed — Comments-in-UI (design)

> **Update 2026-07-22, same day, later:** while this spec was being reviewed,
> Codex built a full Telegram-style RaceFeed channel UI concurrently
> (`components/spotter/views/race-feed-channel.tsx`, plus matching types in
> `lib/api.ts`/`lib/spotter-data.ts` and a working `toRaceFeedPosts()` in
> `lib/racefeed.ts`) — comments are already wired end to end with a slide-out
> panel, avatars, badges, and nested reply indentation. Everything below this
> point describes the ORIGINAL plan, most of which is now moot. **Actual
> remaining scope, confirmed with the user: progressive reveal only** — see
> the "Revised scope" section at the end of this document.

## Context

RaceFeed (built across an earlier 19-task plan, see
`docs/superpowers/plans/2026-07-20-racefeed-phase1.md` and
`docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md`) has since been
extended concurrently by another session (Codex — see
`CODEX_CLAUDE_HANDOFF.md`), which added a full fake-community comment
generator (`core/racefeed/comments.py::generate_comments()`) and persistence
(`comments` table, `Post.comments`, `storage.get_posts()` already returns each
post's comments nested). None of this is wired into the frontend yet — the
`RaceFeedView` component built in the original plan's Task 17 never reads
`post.comments` at all. This spec covers making comments visible and feel
"alive," and nothing else.

This is the first of four follow-up pieces (comments-in-UI → post variety →
career stories → screenshots), each getting its own spec/plan/build cycle per
user direction — the other three are out of scope here.

## Goal

Surface the backend's already-generated comment threads under each RaceFeed
post, revealed progressively over time (matching each comment's staggered
`created_at`, which the backend computes specifically so comments feel like
they're arriving live rather than all dumped at once).

## Data flow

No backend or API changes. `GET /api/racefeed` already returns
`post.comments: Comment[]` (id, post_id, parent_id, author_id, author_name,
author_badge, avatar, text, created_at, likes) via `storage.get_posts()`'s
existing join. Progressive reveal is a pure client-side filter re-evaluated
on each of `useRaceFeed`'s existing 3s poll ticks: `comment.created_at <=
Date.now() / 1000`. No new timers, no new endpoints — the existing poll
cadence already re-renders the component often enough (comments are spaced
~11-18s apart) for reveal to feel smooth without any dedicated animation
infrastructure.

## Components

- **`NewSpotterUI/lib/api.ts`** — add `CommentRow` type mirroring the backend
  row shape; extend `RaceFeedPostRow` with `comments: CommentRow[]`.
- **`NewSpotterUI/lib/spotter-data.ts`** — add `RaceFeedComment` (UI-ready:
  `author`, `badge`, `avatar`, `text`, `likes`, `revealAt` — raw seconds for
  the reveal comparison, `time` — formatted for display once revealed,
  `isReply` — `parent_id !== null`); add `comments: RaceFeedComment[]` to
  `RaceFeedPost`.
- **`NewSpotterUI/lib/racefeed.ts`** — extend `toRaceFeedPosts()` to map each
  post's raw `comments` into the UI shape. Comments stay in their existing
  chronological order (already sorted by `created_at ASC` from the backend
  query) — no re-sorting needed, since flat-chronological was the chosen
  display order.
- **`NewSpotterUI/components/spotter/views/race-feed.tsx`** — under each
  post's text, render `post.comments.filter(c => c.revealAt <= Date.now() /
  1000)`. Each visible comment: a small avatar circle (2-letter `avatar`
  initials), `author` (bold, small), `badge` (muted small tag), `text`, and
  `likes` (small count). A comment with `isReply` true gets a small
  "→ ответ" prefix tag before its text. Flat list, no visual nesting/
  indentation (chosen over threaded nesting so display order stays purely
  time-based, matching the progressive-reveal design).

## Error handling

Nothing new — reuses the existing poll/error path already built (Task 16's
`{ data, error }` hook contract). A post with an empty `comments` array (the
backend always generates 3+, but the type stays defensive rather than
assuming) simply renders no comment block under that post.

## Testing

This frontend has no automated test infrastructure (established during the
original RaceFeed plan's frontend tasks — `pnpm lint`'s `eslint` binary isn't
even installed). Verification is `pnpm tsc --noEmit` + `pnpm build`, then a
manual visual check once F1 25 is running with RaceFeed enabled — same
verification level as every other frontend piece built so far.

## Out of scope (explicitly deferred to later specs)

Post format/angle variety (the `format_id`/`angle_id` fields already exist on
`Candidate`/`Post` but are never populated with real variety — separate,
next spec). Career-story content. Race screenshots. Any change to comment
*generation* (`core/racefeed/comments.py`) — this spec only makes existing
generated comments visible, it doesn't change what gets generated or how.

## Revised scope (2026-07-22, post-Codex-overlap)

Confirmed with the user: keep Codex's existing UI (slide-out comment panel,
avatars, nested replies in `race-feed-channel.tsx`) as-is — it's more
polished than what this spec originally proposed. Add only progressive
reveal on top of it, as a pure pre-filter that the existing display
components never need to know about:

- **`NewSpotterUI/lib/spotter-data.ts`** — add `revealAt: number` (raw
  epoch seconds) to the existing `RaceFeedComment` type, alongside the
  already-present formatted `time: string`.
- **`NewSpotterUI/lib/racefeed.ts`** — in `toRaceFeedPosts()`'s existing
  comment-mapping, add `revealAt: comment.created_at` (the raw value is
  already available — `comment.created_at` is currently only used to
  compute `time`, never kept raw).
- **`NewSpotterUI/components/spotter/views/race-feed.tsx`** — after
  `toRaceFeedPosts()`, filter each post's `comments` down to
  `comments.filter(c => c.revealAt <= Date.now() / 1000)` before passing
  posts to `RaceFeedChannel`. This is the only behavioral change; `
  race-feed-channel.tsx` (`RaceFeedChannel`/`TelegramPost`/`CommentThread`/
  `CommentList`) needs NO changes — it already renders whatever `comments`
  array it's given, so pre-filtering upstream makes reveal transparent to
  it, including the comment-count numbers shown on the feed card and panel
  header (both read `post.comments.length`, which will now reflect only the
  revealed count).
- No timer/animation infrastructure needed — `useRaceFeed`'s existing 3s
  poll already re-renders the tree regularly, and the filter re-evaluates
  against `Date.now()` fresh on every render.
