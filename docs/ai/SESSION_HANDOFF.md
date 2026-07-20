# Evidentia — Session Handoff

_Last updated: 2026-07-20. Keep under 100 lines._

## Current branch and worktree

`main` integrates M4 + M5a (deterministic claim engine) + DOCX Renderer R1 and
the tenant-only frontend. `main` and `origin/main` point to `e80e6ba`. The
zero-accepted-claims presentation fix is intentionally uncommitted for review.
No branch, commit, push or PR was created.

The temporary `tmp/m5a` and `tmp/docx-renderer` branches/worktrees still exist for
rollback/reference; do not remove them before the eventual push.

## Zero-accepted-claims presentation

- `lib/reportPresentation.ts` owns the exact state: persisted M5a audit available
  and enabled, accepted decision count zero, workflow empty, risks empty, actions
  empty. Narrative text is never parsed.
- Report detail fetches the tenant-scoped claim audit through a new BFF route,
  collapses to one full-width column, and shows honest status/facts/configured
  persona context while retaining source audit and private feedback. The BFF
  persists refreshed session cookies on both successful and non-OK responses.
- Citation cards use frozen report-local binding title/version/path/excerpt,
  expand beyond a bounded preview, and form two columns only where width permits.
  Report-local excerpt fallback is limited to an explicit demo corpus; tenant,
  unavailable and unknown corpus modes never use it.
- Static seven-agent timing, the `sections × 41` passage count and formula-derived
  relevance/completeness/coverage charts are not presented as telemetry.
- Zero-claim print/PDF is two compact sections: identity/status/facts/context and
  frozen source appendix/audit. Empty analytical pages and invented checklist,
  owner/date and generic follow-up actions are absent.
- DOCX retains pure persisted-snapshot rendering and frozen evidence; it only adds
  empty-section/positive-score guards and an honest configured-context label.
- Mobile report detail hides the persistent sidebar below 760px so content and
  citation cards use the full viewport.

## Verification

- `npx vitest run`: **80 passed** (11 files), including the claims BFF session,
  status/no-fallback matrix and legacy/citation render cases.
- `npx tsc --noEmit`: **passed**.
- `npm run lint`: **0 errors, 6 existing React hook warnings**.
- `npm run build`: **passed**; route manifest includes tenant-scoped `/claims`.
- Focused DOCX renderer: **32 passed**.
- Authenticated persisted-report smoke: passed at 1440/1366/820/390px; no
  horizontal overflow, positive score, empty analytical content or timeline.
  Print has 2 sections; PDF emitted; DOCX returned 200 with the expected MIME.

## Backend integrity

No migration, database model, immutable M3/M4/M5a module data, claim generation,
gate threshold, persistence, retrieval, feedback semantics or golden fixture was
modified. Backend changes are confined to DOCX presentation guards.

## Pending final integration work

1. Review the uncommitted zero-claim presentation diff.
2. Full SQLite backend suite on merged `main`.
3. Full PostgreSQL 16 backend suite on merged `main`.
4. Confirm final migration graph / `alembic check` drift if not re-run.
5. Commit and push only after review; remove temporary worktrees only afterward.
