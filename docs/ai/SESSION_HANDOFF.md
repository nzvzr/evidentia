# Evidentia — Session Handoff

_Last updated: 2026-07-20. Keep under 100 lines._

## Current branch and worktree

`main` integrates M4 + M5a (deterministic claim engine) + DOCX Renderer R1. Both
`main` and `origin/main` point to `7c8fe47`. The current tenant-only frontend
conversion is intentionally uncommitted for review. No branch, commit, push or PR
was created for this conversion.

The temporary `tmp/m5a` and `tmp/docx-renderer` branches/worktrees still exist for
rollback/reference; do not remove them before the eventual push.

## Tenant-only frontend conversion

- Documents renders only company-owned rows from `/api/documents`; bundled rows
  without `companyId` are discarded. Counts cover real documents,
  generation-eligible current versions, active processing and real section totals.
- Corpus-off/backend-down states are explicit. The legacy JSON/local upload path,
  session upload UI, sample corpus, fake statistics and detail drawer are removed.
- Workspace lists only current versions with `stage=ready`, `finalized=true` and
  `generationEligible=true`. It sends real document ids to the authenticated
  `/api/generate-workflow` path and disables Run when no eligible selection exists.
- Workspace/pending keys are now `evidentia:tenant-workspace:v2` and
  `evidentia:tenant-pending-run:v2`. Old bundled selections and public-demo keys
  are ignored/removed.
- Running uses honest indeterminate progress and a slow-request notice; there is
  no fictional per-agent/stage completion. Success navigates on the persisted id.
- Reports, playbooks and sidebar recents load persisted tenant reports or render
  honest empty states. Landing-page document examples no longer mimic activity or
  claim unsupported formats.
- Removed anonymous/local runtime generation: the `/api/demo/generate-workflow`
  route, bundled corpus/report/scenario data, TypeScript agents/tools/LLM provider,
  browser report store and the orphaned anonymous rate limiter. Removed the unused
  frontend `openai` package dependency.

## Frontend verification

- `npx vitest run`: **55 passed** (7 files).
- `npx tsc --noEmit`: **passed**.
- `npm run lint`: **0 errors, 6 existing React hook warnings**.
- `npm run build`: **passed**; route manifest has no `/api/demo/*` endpoint.

## Backend integrity

No backend code, migration, database model, immutable M3/M4/M5a module data,
claim-engine behavior, DOCX renderer or golden fixture was modified. The earlier
integrated backend verification remains recorded in `PROJECT_STATE.md`.

## Pending final integration work

1. Review the uncommitted tenant-only frontend diff.
2. Full SQLite backend suite on merged `main`.
3. Full PostgreSQL 16 backend suite on merged `main`.
4. Confirm final migration graph / `alembic check` drift if not re-run.
5. Commit and push only after review; remove temporary worktrees only afterward.
