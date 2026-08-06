# RaceFeed Comments — Progressive Reveal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RaceFeed comments appear progressively over time (matching each
comment's staggered `created_at` from the backend) instead of all showing up
at once, without changing anything about Codex's existing comment-panel UI.

**Architecture:** A single pre-filter applied once, upstream of the existing
display components. `RaceFeedComment` gains a raw `revealAt` timestamp
alongside its existing formatted `time` string; `RaceFeedView` filters each
post's `comments` array down to only-revealed-so-far before handing posts to
`RaceFeedChannel`. No new timers — the existing 3s poll already re-renders
the tree often enough for the filter to feel live.

**Tech Stack:** TypeScript, React (no test infra on this frontend — verified
via `tsc --noEmit` + `pnpm build` + manual check, same as every other
frontend task in this project).

**Note on commits:** This repo has no git — every task ends with a
Checkpoint step (mark done, no commit), not `git commit`.

---

## Task 1: Add `revealAt` to the comment type and its mapping

**Files:**
- Modify: `NewSpotterUI/lib/spotter-data.ts`
- Modify: `NewSpotterUI/lib/racefeed.ts`

- [ ] **Step 1: Add the field to the type**

In `NewSpotterUI/lib/spotter-data.ts`, find:
```ts
export type RaceFeedComment = {
  id: string
  parentId: string | null
  authorId: string
  authorName: string
  authorBadge: string
  avatar: string
  text: string
  time: string
  likes: number
}
```
Replace with:
```ts
export type RaceFeedComment = {
  id: string
  parentId: string | null
  authorId: string
  authorName: string
  authorBadge: string
  avatar: string
  text: string
  time: string
  revealAt: number
  likes: number
}
```

- [ ] **Step 2: Populate it in the transform**

In `NewSpotterUI/lib/racefeed.ts`, find:
```ts
      comments: (p.comments ?? []).map((comment) => ({
        id: comment.id,
        parentId: comment.parent_id,
        authorId: comment.author_id,
        authorName: comment.author_name,
        authorBadge: comment.author_badge,
        avatar: comment.avatar,
        text: comment.text,
        time: new Date(comment.created_at * 1000).toLocaleTimeString("ru-RU", {
          hour: "2-digit",
          minute: "2-digit",
        }),
        likes: comment.likes,
      })),
```
Replace with:
```ts
      comments: (p.comments ?? []).map((comment) => ({
        id: comment.id,
        parentId: comment.parent_id,
        authorId: comment.author_id,
        authorName: comment.author_name,
        authorBadge: comment.author_badge,
        avatar: comment.avatar,
        text: comment.text,
        time: new Date(comment.created_at * 1000).toLocaleTimeString("ru-RU", {
          hour: "2-digit",
          minute: "2-digit",
        }),
        revealAt: comment.created_at,
        likes: comment.likes,
      })),
```

- [ ] **Step 3: Type-check**

Run: `cd NewSpotterUI && pnpm tsc --noEmit`
Expected: no errors. (This step alone doesn't change any runtime behavior yet
— `revealAt` exists but nothing reads it until Task 2 — so there's nothing
meaningful to visually verify at this checkpoint.)

- [ ] **Step 4: Checkpoint** — Task 1 done, no git commit (see note above).

---

## Task 2: Filter comments to only revealed-so-far in `RaceFeedView`

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/race-feed.tsx`

- [ ] **Step 1: Read the current file to confirm the anchor**

`NewSpotterUI/components/spotter/views/race-feed.tsx` currently reads:
```tsx
"use client"

import { useRaceFeed } from "@/lib/use-racefeed"
import { toRaceFeedPosts } from "@/lib/racefeed"
import { RaceFeedChannel, type RaceFeedChannelStatus } from "./race-feed-channel"

export function RaceFeedView() {
  const { data, error } = useRaceFeed()
  const posts = data ? toRaceFeedPosts(data) : []
  let status: RaceFeedChannelStatus = "loading"
  if (error) status = "error"
  else if (data && !data.enabled) status = "disabled"
  else if (data && posts.length === 0) status = "waiting"
  else if (posts.length > 0) status = "ready"

  return <RaceFeedChannel posts={posts} status={status} />
}
```
Confirm this matches before editing (Codex owns this file per
`CODEX_CLAUDE_HANDOFF.md` and may have touched it again — if it doesn't
match, stop and report back what you find instead of guessing).

- [ ] **Step 2: Add the reveal filter**

Replace the file's content with:
```tsx
"use client"

import { useRaceFeed } from "@/lib/use-racefeed"
import { toRaceFeedPosts } from "@/lib/racefeed"
import { RaceFeedChannel, type RaceFeedChannelStatus } from "./race-feed-channel"

export function RaceFeedView() {
  const { data, error } = useRaceFeed()
  const rawPosts = data ? toRaceFeedPosts(data) : []
  // Comments carry a staggered created_at (backend spaces them ~11-18s apart
  // specifically so a thread feels like it's still forming) — only show the
  // ones whose time has actually passed. useRaceFeed's 3s poll re-renders
  // this component regularly, so the revealed set grows naturally without
  // any dedicated timer here.
  const now = Date.now() / 1000
  const posts = rawPosts.map((post) => ({
    ...post,
    comments: post.comments.filter((comment) => comment.revealAt <= now),
  }))
  let status: RaceFeedChannelStatus = "loading"
  if (error) status = "error"
  else if (data && !data.enabled) status = "disabled"
  else if (data && posts.length === 0) status = "waiting"
  else if (posts.length > 0) status = "ready"

  return <RaceFeedChannel posts={posts} status={status} />
}
```

- [ ] **Step 3: Type-check**

Run: `cd NewSpotterUI && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Full build**

Run: `cd NewSpotterUI && pnpm build`
Expected: build succeeds, produces fresh `NewSpotterUI/out/`.

- [ ] **Step 5: Checkpoint** — Task 2 done, no git commit.

---

## Task 3: Manual verification

**Files:** none — this is a live check, not a code change.

- [ ] **Step 1: Confirm the count display stays consistent**

Read `NewSpotterUI/components/spotter/views/race-feed-channel.tsx`'s
`TelegramPost` (feed-card "N комментариев" button) and `CommentThread`
(panel header "N сообщений") — both read `post.comments.length`. Since
Task 2 filters `comments` before `RaceFeedChannel` ever sees them, both
counts will already reflect only the revealed comments — confirm this by
reading the code, no change needed here if Task 2 was applied correctly.

- [ ] **Step 2: Live check with F1 25 running (requires RaceFeed enabled)**

With telemetry flowing and a post published, open its comment panel shortly
after it appears (before ~18s have passed) and confirm the comment count is
0 or low, then reopen a minute later and confirm more comments have appeared
— proving the reveal is actually progressive, not an instant dump.

- [ ] **Step 3: Update `CODEX_CLAUDE_HANDOFF.md`**

Per this project's coordination protocol, update the "Активная работа"
section: mark this task complete, note the 3 files touched, and mark them
unlocked for Codex again (`Файлы разблокированы`).

- [ ] **Step 4: Checkpoint** — Task 3 done. Feature complete.

---

## Self-review notes

**Spec coverage:** The spec's "Revised scope" section maps 1:1 to Task 1
(type + transform) and Task 2 (the filter itself) — Task 3 covers the spec's
testing section (manual verification, since this frontend has no automated
tests) plus the coordination-protocol requirement from
`CODEX_CLAUDE_HANDOFF.md`.

**Placeholder scan:** No TBD/TODO; every step has complete, verbatim code
grounded in the actual current file contents (read fresh immediately before
writing this plan, given how recently these files changed).

**Type consistency:** `revealAt: number` (Task 1) is populated as
`comment.created_at` (already a `number` per the existing `RaceFeedCommentRow`
type in `lib/api.ts`) and consumed as `comment.revealAt <= now` (Task 2,
`now` also a `number` via `Date.now() / 1000`) — consistent throughout.
