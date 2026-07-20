# Evidentia — Project State

_Concise snapshot. Last updated: 2026-07-20. `main` integrates M4 + M5a + DOCX
Renderer R1. The worktree also contains an uncommitted tenant-only frontend
conversion for review. `main` and `origin/main` both point to `7c8fe47`._

## Current milestone

`main` integrates M4 + M5a (deterministic claim engine) + DOCX Renderer R1. Both
tracks were developed in parallel worktrees and are now merged into `main`. The
M5a claim engine sits behind the default-off `EVIDENTIA_CLAIM_ENGINE_ENABLED`
rollout flag (flag off remains the exact M4 path),
and the DOCX renderer is a pure transformation of persisted report snapshots. The
public `EvidentiaReport` remains exactly 20 keys; neither M5a nor R1 changed the
schema. The uncommitted frontend is now tenant-only: bundled runtime documents,
local TypeScript agents, anonymous generation, local upload/report stores and
seeded activity were removed. `main` and `origin/main` are synchronized before
these uncommitted changes.

## M5a integrated (deterministic claim engine)

Merged into `main` via merge commit `d7cc4b6` (feature `17406c6`, still on
`tmp/m5a` for rollback). Migration `f5a6c7d8e9b0` follows M4 revision
`e4b7c9d2a610`. The deterministic gate is the sole acceptance authority; accepted
claims exclusively drive the analytical projection.

- Declarative `compliance.claim-patterns@1.0.0` lives independently under
  `backend/app/modules/compliance/claim-patterns/1.0.0/`. The released M3
  `compliance/1.0.0` directory remains its exact three-file HEAD layout and digest.
- Every deterministic and LLM candidate is evaluated against the complete bounded
  frozen M4 evidence set. LLM citations are hints only; conflict and required-
  support matchers always see the full set.
- Gate score, binding count, source diversity and accepted provenance use only
  bindings attributed to successful support observations. Conflict bindings stay
  visible in audit observations and are never accepted support.
- `claim-patterns-v1` rejects nested `evidence_count` and the unwired `comparison`
  primitive. Matcher trees and execution have depth, node, evidence/text and
  candidate-wide primitive-evaluation budgets. Decimal conversion is string-
  canonical and release loading remains strict and atomic.
- Claim-engine mode has one accepted-only projection for workflow, risks,
  recommendations, summary and top finding. Rejected/insufficient claims are
  audit-only. Zero accepted claims produce empty analytical arrays and an honest
  no-accepted-claim narrative.
- Full-mode analytical refinement is atomic: any exception restores persona,
  workflow, risks, actions, narrative, claim run and inclusion intent to the
  deterministic baseline and reports deterministic mode.

## Persistence and feedback

- Migration `f5a6c7d8e9b0` records exact claim-pack id/version/digest separately
  from the target M3 module, plus report-local candidates, decisions, evidence,
  metrics and feedback.
- Feedback paths use canonical indexes (`0|[1-9][0-9]*`) and validate item type and
  persisted report shape.
- Corrected citation anchors resolve to exact report-local evidence bindings.
  Composite report/company SQL foreign keys reject another report, another source
  version outside the frozen binding set and cross-tenant direct writes.

## DOCX Renderer R1 integrated

Merged into `main` via merge commit `ae4f1b7` (feature `112d947`, still on
`tmp/docx-renderer` for rollback). R1 is the first output renderer on the
format-independent renderer protocol; PDF/PPTX and others remain deferred.

- The renderer (`docx-renderer-v1`) is a pure transformation of the persisted
  report snapshot + report-local M4 source audit. It performs no retrieval, no
  LLM call and no current-version lookup, and opens no socket.
- Each citation's id, title, version, section/heading path and evidence excerpt
  come from the exact frozen M4 source-audit binding. A tenant report with no
  binding omits the evidence quote and labels the audit unavailable; only an
  explicit `demo` report keeps its report-record excerpt under the documented
  honest compatibility fallback — never implied to be frozen evidence.
- Authenticated export endpoint `GET /api/reports/{report_id}/export/docx` and
  Next BFF route `/api/reports/[id]/export/docx`. Cross-tenant access is an
  enumeration-safe 404. The BFF preserves rotated sessions on success and error
  paths and bounds the body by both declared Content-Length and actual streamed
  bytes (oversized chunked bodies are cancelled).
- Output is deterministic (pinned container/date strategy, sha256 content hash),
  has no macros and no external relationships. Output-size and rate limits are
  configured (`EVIDENTIA_EXPORT_MAX_BYTES`) and documented in `.env.example`.
- The public `EvidentiaReport` schema is unchanged; no renderer field was added.

## Integration hygiene

- M5a merge: `d7cc4b6` (`merge: integrate deterministic claim engine m5a`).
- R1 merge: `ae4f1b7` (`merge: integrate editable docx renderer r1`).
- Canonical line-ending pin: `1e19b29` (`fix: pin immutable fixtures to canonical
  line endings`) adds the root `.gitattributes` forcing LF on
  `backend/app/modules/**/*.json` and `backend/tests/golden/**/*.{json,md,txt}`.
- Middleware→proxy migration: `a76506b` (`chore: migrate Next middleware to
  proxy`) renames `middleware.ts` → `proxy.ts`. It **is** committed and remains
  in history. The documentation commit `7c8fe47` is the current `main` and
  `origin/main` HEAD; the tenant-only frontend changes are intentionally
  uncommitted for review.
- Deterministic module and golden inputs are pinned to LF through the root
  `.gitattributes`, which is committed (in `1e19b29`).

## Verification

Verified on the integrated `main` (post-merge, post LF pin):

- Immutable M3/golden byte-identity test: **passed**; golden fixture suite:
  **59 passed**.
- Combined focused backend M5a + R1 suite: **113 passed**.
- Frontend Vitest: **86 passed** (M5a feedback controls + R1 DOCX button/BFF route
  tests over the prior 56); `tsc --noEmit`: **passed**; ESLint: **0 errors, 6
  pre-existing hook warnings**; Next production build: **passed**.

Verified on the uncommitted tenant-only frontend conversion:

- Frontend Vitest: **55 passed** across 7 files (removed demo/rate-limit suites;
  added tenant Documents/Workspace/Running and runtime-removal coverage).
- `tsc --noEmit`: **passed**; ESLint: **0 errors, 6 existing hook warnings**;
  Next production build: **passed** and exposes no `/api/demo/*` route.

Pre-integration context (M5a worktree, before the R1 merge and LF pin — **not**
re-run on merged `main`):

- Focused corrected M5a engine/feedback/live/migration: **70 passed** on SQLite;
  PostgreSQL live smoke: **3 passed**; dual-engine focused matrix: **71 passed**.
- Full SQLite: **833 passed, 11 skipped, 17 failed** (237.26s); full PostgreSQL 16
  (`dialect=postgresql`): **864 passed, 0 skipped, 17 failed** (656.00s). Every
  failure was one of the deferred goldens (the line-ending/manifest artifact now
  pinned); all PostgreSQL concurrency tests ran; fresh-head Alembic checks showed
  only the four documented legacy auth nullability differences and zero M5a drift.

The full SQLite and full PostgreSQL 16 suites have **not** been re-run on the
merged `main`; both remain pending final verification (see SESSION_HANDOFF). The
immutable modules and golden fixtures are pinned to LF through the root
`.gitattributes` (`1e19b29`); the previously reported fresh-vs-committed
`manifestSha256` discrepancy was a working-tree line-ending artifact, and the
goldens were not re-recorded.

## Deferred

M5b production pattern content/calibration; PDF/PPTX/XLSX/HTML/JSON and push
renderers; full CAD runtime; embeddings/FTS; OCR/PDF/DOCX ingestion; external
packs/connectors; automatic or cross-tenant learning; advanced selection and
regeneration.
