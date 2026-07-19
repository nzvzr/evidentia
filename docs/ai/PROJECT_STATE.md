# Evidentia — Project State

_Concise snapshot. Last updated: 2026-07-19. Corrected M5a diff is uncommitted._

## Current milestone

M5a's bounded claim-engine plumbing is implemented on top of M4 behind the
default-off `EVIDENTIA_CLAIM_ENGINE_ENABLED` rollout flag. Flag off remains the
exact M4 path; demo generation is unchanged. The public `EvidentiaReport` remains
exactly 20 keys.

## Corrected M5a architecture

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

## Verification

- Focused corrected M5a engine/feedback/live/migration: **70 passed** on SQLite;
  PostgreSQL-specific live smoke: **3 passed**; the dual-engine focused matrix
  runs **71 passed**.
- Full SQLite: **833 passed, 11 skipped, 17 failed** in 237.26s. Full PostgreSQL
  16, confirmed `dialect=postgresql`: **864 passed, 0 skipped, 17 failed** in
  656.00s. Every failure on both engines is one of the deferred goldens below;
  all concurrency tests ran on PostgreSQL.
- Data-bearing M4→M5a→M4→M5a cycles pass SQLite and PostgreSQL, including hostile
  same-tenant other-report, cross-tenant and missing corrected-binding writes.
- Fresh-head Alembic checks on both engines show only the four documented legacy
  auth nullability differences and zero M5a drift.
- Frontend: **56 passed**; `tsc --noEmit`, production build and lint pass. Lint
  reports 0 errors and 6 pre-existing hook warnings. Backend compileall passes.
- All 17 M3 golden expected files are exact HEAD bytes and remain unmodified.
- The pre-existing golden drift is separate: fresh M3 computation changes only
  `manifestSha256` (for `base`, computed `ac9c70e8…` vs committed `aac8aaf6…`).
  M5a does not fix or mask it.

## Deferred

M5b pattern content/calibration; the pre-existing M3 golden-manifest drift;
full CAD runtime; embeddings/FTS; OCR/PDF/DOCX; external packs/connectors;
automatic or cross-tenant learning; advanced selection and regeneration.
