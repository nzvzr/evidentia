# Evidentia — Session Handoff

_Last updated: 2026-07-20. Keep under 100 lines._

## Current branch and integrated milestones

`main` integrates M4 + M5a (deterministic claim engine) + DOCX Renderer R1. HEAD
is `a76506b`; the worktree is clean (no uncommitted changes). Both feature tracks
are merged:

- M5a: merge `d7cc4b6` (feature `17406c6`), migration `f5a6c7d8e9b0` after M4
  revision `e4b7c9d2a610`.
- R1: merge `ae4f1b7` (feature `112d947`).
- Follow-up commits on `main`: `1e19b29` (LF pin + root `.gitattributes`) and
  `a76506b` (Next `middleware.ts` → `proxy.ts`, committed).

The temporary branches/worktrees `tmp/m5a` and `tmp/docx-renderer` still exist for
rollback/reference until final verification and push; remove them only **after**
the push. `origin/main` is still on M4 (`e470388`) — local `main` is 6 commits
ahead, 0 behind. Distinguish local `main` from `origin/main` from real Git output,
not assumption.

## Verified integration results

Verified on the merged `main` (post LF pin):

- Immutable M3/golden byte test: **passed**.
- Golden fixture suite: **59 passed**.
- Combined focused backend M5a + R1 suite: **113 passed**.
- Frontend Vitest: **86 passed**.
- TypeScript (`tsc --noEmit`): **passed**.
- ESLint: **0 errors, 6 pre-existing warnings**.
- Next production build: **passed**.

The full SQLite and full PostgreSQL 16 backend suites have **not** been re-run on
the merged `main`. Earlier full-suite numbers (833 SQLite / 864 PostgreSQL passed,
17 golden failures each) are from the pre-merge M5a worktree — before the R1 merge
and the LF pin — and do not describe the integrated tree.

## Pending final verification

1. Full SQLite backend suite on merged `main`.
2. Full PostgreSQL 16 backend suite on merged `main`.
3. Confirm the migration graph / `alembic check` drift on the final integrated
   tree if not re-run (expect only the four legacy auth nullability drifts).
4. Inspect `git status` / `git diff`.
5. Push `main` to `origin`.
6. Remove the temporary `tmp/m5a` / `tmp/docx-renderer` worktrees/branches only
   after the push.

## Known non-blocking follow-ups

- Retrieval-miss corrected-section snapshot membership remains application-
  enforced; it is advisory and cannot change claim acceptance.
- Matcher runtime budget exhaustion fails closed as a generation failure rather
  than a typed `ClaimDecision`.
- Six existing React hook lint warnings.
- Python/FastAPI/SQLAlchemy deprecation warnings.
- Broader M5b production pattern authoring remains deferred.
- PDF/PPTX and other renderers remain deferred.
