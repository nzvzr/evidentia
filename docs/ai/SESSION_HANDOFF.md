# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-15 (review corrections applied to the stabilization diff)._

## Where things stand

**M1 remains implemented and verified.** Typed contracts, blob/job/provider seams,
the additive ingestion schema/migration, tenant-corpus flag, and backfill are all
unchanged. See `PROJECT_STATE.md` and the 2026-07-15 M1 entry in `DECISIONS.md`.

**The pre-M2 `/running` stabilization passed independent review; its two approved
non-blocking corrections are applied and verified.** The diff is intentionally
still uncommitted. Remaining external steps: commit and push; only then may M2
begin.

## Frontend fix

1. `app/running/page.tsx` now keeps request result, animation completion, phase,
   active attempt, and navigation guards explicit. Stage updates contain no side
   effects. Successful navigation lives in its own effect and happens once after
   both animation and persisted report id are ready.
2. `lib/pendingRun.ts` stores a session-scoped, non-secret nonce with the existing
   run input. Login/logout/session-loss purge already covers this key. Retry creates
   a new nonce and clean state; legacy raw-input values remain readable once.
3. `lib/workflowGeneration.ts` holds only live single-flight requests keyed by
   nonce + exact input. Strict Mode replay shares one POST; real unmount aborts
   after a zero-delay replay grace period; timeout remains 60s; settled entries are
   deleted immediately. No report content is cached.
4. Stale effect subscriptions/timers cannot update or navigate the active run.
   Cleanup AbortError is ignored; timeout/network/503 remain unavailable; 429 is
   limited; 401 redirects once; other non-OK responses are failed.
5. Review correction A (hydration): header persona/market labels render the
   prerendered defaults until hydration completes (`useSyncExternalStore` gate);
   the run itself is still read from storage on the first client render, so the
   generation effect POSTs the stored input immediately and the label re-render
   starts no second request.
6. Review correction B (malformed success): a 200 whose body is unparseable, not
   an object, or lacks a non-empty string `report.id` returns the generic error
   result (`Generation failed`) — never success, finalizing, or unavailable. Only
   this minimum persistence/navigation contract is validated (no full schema
   validator). See the 2026-07-15 `DECISIONS.md` entry, which also records the
   client single-flight scope limit (one tab/mount only; cross-tab, back-nav, and
   server-side replay dedupe belong to a later backend idempotency milestone).
7. `app/running/page.test.tsx` holds 22 behavioral React/Strict Mode tests
   (six malformed-200 cases + two hydration-label tests added). Vitest supports
   jsdom component tests; React Testing Library is a dev dependency.

## Verification (re-run after the review corrections)

- Focused: `npx vitest run app/running/page.test.tsx --reporter=verbose` — 22/22.
- Full: `npm test` — 28/28 across 2 files.
- Two shuffled runs (`--sequence.shuffle.tests`) — 22/22 both times.
- `npm run lint` — pass, 0 errors; the same 6 pre-existing set-state-in-effect
  warnings (the hydration gate uses `useSyncExternalStore`, adding none).
- `npx tsc --noEmit` — pass.
- `npm run build` — pass (Next 16.2.10 production build; `/running` static).
- `git diff --check` — pass.
- Authenticated headless-Chrome smoke against live FastAPI + `next start` (prod):
  fresh registered user, **non-default** selection (Support Agent / US), hard load
  of `/running`: **zero hydration warnings and zero console errors**, header showed
  the stored labels, exactly one POST `/api/generate-workflow`, automatic redirect
  to `/reports/{uuid}`, persisted report count 0→1.
- Earlier same-day smoke (initial diff): dev-restart run and backend-down run
  (one POST/503, honest `Generation unavailable`, no report route) still stand.

## Scope and next step

- Backend generation/persistence, report page, auth, public report schema, and M1
  ingestion foundations were untouched.
- No M2 upload, parsing, sectionization, worker, or customer-corpus behavior exists
  in this diff.
- Next action: commit and push the reviewed, corrected stabilization diff; only
  then may M2 begin.

## M2 reminder (still blocked)

M2 is the MD/TXT upload + ingestion spine: multipart validation/caps/dedupe/quotas,
tenant-fair worker claims, heartbeat/stale-running recovery, parsers → DocIR →
sectionizer, and document status UI. Preserve the platform invariants in
`PLATFORM_ARCHITECTURE.md` and `DOCUMENT_INGESTION_ARCHITECTURE.md`.
