# Evidentia — Project State

_Concise snapshot. Last updated: 2026-07-18. M4 diff is uncommitted._

## Current milestone

M4 tenant-corpus report generation is implemented and live-smoke verified on
PostgreSQL 16. Authenticated generation now consumes only the active company's
eligible finalized M3 versions. Anonymous `/api/demo/generate-workflow` remains
sample-only, anonymous and non-persistent. There is no tenant/demo fallback or
mixing.

The public 20-key `EvidentiaReport` JSON is unchanged. Tenant audit provenance
is persisted separately and returned from tenant-scoped
`GET /api/reports/{id}/sources`.

## M4 architecture

- Explicit `DemoCorpusProvider` and `TenantCorpusProvider`; the provider is
  injected once into the existing orchestrator. The authenticated route always
  selects tenant; the public Next route always selects demo.
- `EVIDENTIA_TENANT_GENERATION_ENABLED=false` is a dedicated safe rollout flag.
  Disabled, empty, ineligible, retrieval and evidence failures are typed; none
  can substitute sample evidence.
- Tenant selection starts at each non-deleted document's exact
  `current_version_id` and calls the committed M3
  `check_generation_eligibility` predicate. Transitional, unsupported or
  malformed versions fail closed.
- Retrieval is deterministic `tenant-lexical-v1`: normalized lexical weighting,
  stable score/identity tie-breaks, and exact full-text scoring before global
  candidate truncation. Canonically streamed per-document top-k accumulation
  keeps late sections eligible with bounded memory and diversity; explicit
  document/candidate/section/character/excerpt limits remain. Snapshot digest
  `tcs1` binds tenant, sorted version ids, manifests, retrieval version and
  configuration.
- Exact version/section objects are frozen and the report/source/evidence plan is
  committed before optional LLM work; generation never re-follows the current
  pointer and holds no transaction across an LLM call.
- Tenant source text is untrusted quoted evidence. LLM evidence is delimited,
  case-insensitive closing sentinels are encoded only in the prompt view,
  instruction-following is prohibited, prompt input is bounded, and final
  citation ids/display data must match the report-local allow-list exactly.
  Narrative citation checks are scoped to active tenant and reserved demo
  namespaces, leaving ordinary standards/version tokens untouched.
- LLM-off produces a deterministic tenant-grounded report. LLM metadata records
  actual execution. Any per-step LLM fallback stays grounded in the same frozen
  tenant evidence.
- Migration `e4b7c9d2a610` adds report provenance columns,
  `report_source_versions`, `report_evidence_bindings`, and tenant-safe composite
  keys/FKs/uniqueness/indexes. Existing reports become completed demo rows with
  no fabricated bindings.
- Document deletion is soft deletion: future retrieval excludes the document,
  while completed report provenance remains auditable with bounded excerpts.

## User-facing behavior

- Authenticated Next BFF generation proxies FastAPI only and forwards M4 typed
  errors. `/running` labels `Tenant corpus`, provides the finalization action for
  empty/ineligible corpora, and never calls the demo endpoint.
- Documents distinguish `Awaiting finalization`, `Citation-ready`, and
  `Finalized · unavailable`, using the backend's exact eligibility result.
- Reports show deterministic/LLM truthfully, tenant/sample corpus, exact citation
  version/section data, bounded excerpts and compact retrieval/snapshot audit.
  Old demo reports remain readable.

## Verification

- Post-review focused SQLite M4 + persistence: **30 passed**, including exact
  delimiter injection, ISO-27001/SOC-2/PCI-DSS-4.0, ordinal >500, 50 documents,
  insertion-order/hash-seed determinism, limits/diversity and split error codes.
- PostgreSQL 16 required target: **197 passed**. Complete PostgreSQL backend:
  **810 passed**, including real concurrency/worker locking and the dual-backend
  migration matrix.
- Live PostgreSQL API/worker smoke: A and B uploaded/finalized real documents;
  deterministic tenant reports persisted 2 source snapshots and 2 bindings;
  `ZORBLAX-999-A/B` remained isolated; cross-tenant audit was 404; empty and
  disabled codes were correct.
- Production anonymous Next smoke: 200, `X-Evidentia-Demo: true`, deterministic,
  eight sample citations, neither tenant marker.
- Frontend: Vitest **55 passed**; TypeScript passed; Next production build passed;
  ESLint **0 errors / 6 pre-existing hook warnings**.
- Data-bearing M3→M4→M3→M4 passed SQLite and PostgreSQL. Fresh-head Alembic check
  on both reports only the four documented legacy auth nullable differences;
  zero M4 drift.
- Full backend SQLite: **780 passed, 11 skipped**.

## Preserved invariants

M3 anchors/citation identities, finalization algorithms, manifests and golden
fixtures were not changed. Final versions remain immutable; finalization still
creates a successor. No PDF/DOCX/OCR, embeddings/vector DB, external search,
shared corpora, claims ledger or public-schema extension was introduced.

## Deferred

PDF/DOCX/OCR; embeddings/vector retrieval; worker lease-token fencing for future
long parsers; broader claims/CAD lifecycle; external framework packs; physical
blob-retention optimization and `documents.content_text` removal; four legacy
auth nullable drifts; advanced selection; report regeneration/version comparison.
M4.1: optimize `GET /api/documents` eligibility calculation and consider
immutable-key memoization or batched eligibility evaluation. F7/F8 behavior is
unchanged by the post-review pass.
