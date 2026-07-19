# Evidentia — Session Handoff

_Last updated: 2026-07-19. Keep under 100 lines._

## Status

Focused post-review corrections are implemented and intentionally uncommitted on
`tmp/m5a`, starting from M4 HEAD
`e4703882b5f1aa85164a18ffdb1c7fabd228823c`. No branch, commit, push or PR was
created.

## Corrections

- Moved the claim release to
  `modules/compliance/claim-patterns/1.0.0`; exact pack id/version/digest is loaded,
  persisted and included in report engine provenance. Restored
  `modules/compliance/1.0.0` and all 17 M3 goldens to exact HEAD content.
- LLM proposals and deterministic candidates now run identical matchers over the
  complete frozen M4 evidence set. Citation hints cannot hide conflicts or create
  support. Gate scoring and accepted bindings use successful support-observation
  attribution only; unrelated padding is excluded.
- Added one accepted-only analytical projection. Claim mode no longer calls the
  raw-section workflow builder or static action path. Zero accepted claims emit no
  workflow, risks or actions and use an honest schema-compatible narrative.
- Full-mode exceptions restore the complete deterministic analytical and claim
  baseline atomically, including inclusion flags and truthful generation mode.
- Rejected nested `evidence_count` and the unwired `comparison` primitive at
  atomic schema load. Added depth/node/evidence/text/primitive-evaluation budgets,
  safe relative-path validation and deterministic Decimal conversion.
- Canonicalized feedback item indexes and replaced corrected-citation section
  references with exact report-local binding references protected by composite
  report/company SQL foreign keys and an `incorrect_source` check constraint.
- Added regressions for selective citation, support attribution/dedup/diversity,
  rollback, zero-accepted projection, immutable M3 bytes/goldens, independent
  claim-pack digest/selection, matcher budgets, comparison rejection, canonical
  paths, API snapshot rejection and hostile SQL writes.

## Verification

- Corrected M5a focused matrix: **70 passed** SQLite; **71 passed** when the
  PostgreSQL migration variant is included; PostgreSQL live smoke **3 passed**.
- Full SQLite: **833 passed, 11 skipped, 17 failed** (237.26s). Full PostgreSQL 16
  with confirmed `dialect=postgresql`: **864 passed, 0 skipped, 17 failed**
  (656.00s). All failures are exactly the deferred 17 goldens; all PostgreSQL
  concurrency tests ran.
- Data-bearing migration cycles and hostile corrected-binding constraints pass on
  both engines. Fresh Alembic checks show only four known legacy auth nullability
  differences and zero M5a drift.
- Frontend: **56 passed**; TypeScript, lint and build pass (0 lint errors / 6
  pre-existing warnings). Backend compileall passes.
- The 17 committed expected files and the M3 compliance release are exact HEAD
  bytes and were not regenerated.

## Deferred repository issue

Fresh M3 golden computation currently differs from committed HEAD only in
`manifestSha256` (`base`: computed `ac9c70e8…`, committed `aac8aaf6…`). This is a
pre-existing golden infrastructure issue, not fixed or attributed to M5a.

## Final handoff

Run final `git diff --check`, status/stat and immutable-path checks before handing
the uncommitted worktree to the next adversarial reviewer.
