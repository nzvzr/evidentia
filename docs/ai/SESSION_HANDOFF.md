# Evidentia — Session Handoff

_Last updated: 2026-07-18. Keep under 100 lines._

## Status

M4 tenant-corpus report generation plus the narrow post-review hardening pass is
implemented, verified and intentionally uncommitted for final micro-review.
Start remained `main` at `b492eb0f7f5e0ca6c458e0555a07f317e620f947`; no
branch, commit or push was made.

Authenticated generation now always injects a company-scoped
`TenantCorpusProvider`; anonymous demo generation remains exclusively the
sample-backed TypeScript route. `EVIDENTIA_TENANT_GENERATION_ENABLED` defaults
false. Tenant disabled/empty/ineligible/retrieval/evidence failures are typed and
never fall back to demo.

## Implemented

- Provider freezes exact eligible M3 current versions/sections via the existing
  `check_generation_eligibility`; deleted, transitional, unsupported and malformed
  sources fail closed. Full text is used internally; UI excerpts are bounded.
- Deterministic `tenant-lexical-v1` retrieval has stable identity tie-breaks,
  canonically streams and scores the complete frozen corpus before bounded
  per-document top-k/global rank-round truncation, and retains configurable
  document/candidate/selection/character/per-document/excerpt caps, ambiguous-
  citation refusal and the `tcs1` corpus/config digest.
- Existing orchestrator accepts the provider/company explicitly. Cache identity
  includes tenant and snapshot. Tenant evidence is delimited untrusted prompt
  material; embedded closing sentinels are case-insensitively HTML-encoded only
  in the prompt representation. Exact structured citations remain frozen-registry
  checked; narrative unknown-ID checks use active tenant + reserved demo families,
  so ISO-27001, SOC-2 and PCI-DSS-4.0 are accepted. Stored text is unchanged.
- Pipeline/orchestration failures return and persist `generation_failed`; actual
  snapshot/completion persistence failures return `persistence_failed`, with safe
  messages and honest failed report rows.
- Migration `e4b7c9d2a610` adds report provenance metadata plus normalized
  `report_source_versions` and `report_evidence_bindings`, composite tenant-safe
  FKs/unique keys and indexes. Existing reports backfill as completed demo without
  fake bindings. M4 downgrade restores exact M3 shape while retaining base rows.
- Source audit is intentionally outside the unchanged 20-key public report JSON:
  `GET /api/reports/{id}/sources`. Document deletion is soft so completed binding
  provenance survives; deleted documents are excluded from new generations.
- Next BFF forwards typed errors only to FastAPI. Running/Documents/report pages
  label tenant/sample and eligibility honestly; report UI renders exact version,
  section, citation, bounded excerpt and compact audit metadata. Old demo reports
  remain readable.

## Verification

- Focused post-review M4 + persistence SQLite: **30 passed**.
- PostgreSQL 16 target (`evidentia-pg-test`): **197 passed**; complete backend:
  **810 passed** in 524.32s.
- Live PostgreSQL API/worker smoke: two companies uploaded/finalized real MD,
  generated deterministic tenant reports, persisted 2 sources/2 bindings with
  manifests/signatures and correct company ids. `ZORBLAX-999-A` and `-B` never
  crossed; cross-tenant source audit was 404; empty=`tenant_corpus_empty`;
  flag-off=`tenant_generation_disabled`.
- Built Next production demo smoke: HTTP 200, `X-Evidentia-Demo: true`, 8 sample
  citations, deterministic, both tenant markers absent.
- Frontend: **55 passed** (4 files); ESLint **0 errors / 6 existing warnings**;
  `tsc --noEmit` passed; production build passed.
- Data-bearing M3→M4→M3→M4 migration cycle passed SQLite and PostgreSQL; hostile
  cross-tenant FK insert rejected; base reports/documents retained.
- Fresh SQLite/PostgreSQL head `alembic check`: exactly 4 known legacy auth
  nullable differences, zero M4 drift.
- Full SQLite backend: **780 passed, 11 skipped** in 268.1s.

## Review focus

1. Tenant provider query/limit behavior and report-local citation validator.
2. Composite FK portability and intentional loss of M4-only provenance on an
   operator-requested downgrade to exact M3.
3. Separate audit endpoint/public-schema boundary and soft-delete retention.
4. Feature-flag/no-fallback behavior across FastAPI and Next BFF.

## Deferred

M4.1 performance only: optimize `GET /api/documents` eligibility calculation and
consider immutable-key memoization or batched evaluation. No cache/eligibility
redesign was made. F7 remains unchanged; F8 downgrade behavior remains unchanged.
PDF/DOCX/OCR; embeddings/vector search; lease fencing; claims/CAD; external packs;
blob retention/content_text removal; 4 legacy auth drifts; advanced selection and
regeneration/version comparison remain deferred. M3 algorithms/goldens are unchanged.
