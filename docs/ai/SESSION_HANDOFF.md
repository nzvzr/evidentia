# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-15 (M1 implemented + independent-review corrections applied)._

## Where things stand

**M1 is implemented and verified** (details in `PROJECT_STATE.md`; decisions
appended to `DECISIONS.md` 2026-07-15). Everything in the
`PLATFORM_ARCHITECTURE.md` §12 M1 gate, additive only, zero behavior change:

1. **`backend/app/contracts.py`** — `RawDocument v1`, `DocIR v1`,
   `SectionRecord v1`, `ClaimSpec v1` (+ `EvidenceBinding v1` and stubs for
   `ClaimCandidate`/`Finding`/`Recommendation`/`CanonicalAnalysisDocument`).
   `SectionRecord.to_pipeline_section(source_title)` is the strict projection
   to the pipeline currency dict, test-pinned against `document_reader`.
2. **Seams** — `BlobStore` + `DatabaseBlobStore`
   (`app/services/blob_store.py`), `JobQueue` + `DatabaseJobQueue.enqueue`
   (`app/services/job_queue.py`; claim/worker is M2), `SectionProvider` +
   `DemoCorpusProvider` (`app/agents/section_provider.py`; byte-identical to
   `document_reader`, orchestrator injection is M4).
3. **Migration `f7c3a1b9e2d4`** — `document_versions`, `document_blobs`,
   `document_sections`, `ingestion_jobs` + 11 additive `documents` columns.
   Crash-safe blob/row write order + orphaned-blob reconciliation documented
   in its docstring (the "schema PR" documentation gate). Verified: upgrade /
   downgrade / re-upgrade; schema column-identical to `create_all`.
   `documents.current_version_id` has **no DB-level FK** (circular pair on
   SQLite) — integrity lives at the single atomic flip site.
4. **Flag** `EVIDENTIA_TENANT_CORPUS_ENABLED` (default **off** = byte-for-byte
   today; in settings + `.env.example`).
5. **Backfill** `scripts/backfill_documents.py` — version 1 (`pending`) +
   blob + queued job per `content_text` doc; idempotent; one doc per commit;
   `--company-id` / `--dry-run`; verified via CLI on a migrated scratch DB.
   `content_text` is now deprecated (removal milestone still unscheduled).

**Independent review corrections applied (2026-07-15, all verified):**

1. The application engine (`app/db/session.py`, via `create_application_engine`)
   now sets `PRAGMA foreign_keys=ON` on every SQLite connection — previously
   only the test engine did, so a real document delete stranded orphaned
   versions/blobs/jobs (reproduced, now cascade-tested through the app path).
2. Partial unique index `uq_ingestion_jobs_live_version` (one row per
   `version_id` while state is queued/running; `postgresql_where`+`sqlite_where`,
   in migration + ORM). `DatabaseJobQueue.enqueue` inserts inside a SAVEPOINT:
   the losing racer swallows the IntegrityError, keeps the caller's outer
   transaction, and re-selects/returns the surviving job. Genuine two-session
   race verified on PostgreSQL 16 (5 consecutive runs).
3. Unique index `uq_documents_company_citation_prefix` on
   `(company_id, citation_prefix)` (migration + ORM); still nullable, NULLs
   remain distinct — pre-M3 documents coexist.
4. Redundant indexes removed from the uncommitted migration + ORM:
   `ix_document_sections_company_id` (leftmost prefix of
   `ix_document_sections_company_document`) and
   `ix_document_versions_document_id` (leftmost prefix of the unique
   `(document_id, version_no)` constraint).

Tests: **311 passed, 3 skipped** (PostgreSQL-only) — 274 pre-existing,
all untouched, +38 new (`test_contracts.py` 13,
`test_ingestion_schema_and_seams.py` 24, one PostgreSQL enqueue-race test in
`test_concurrency.py`). Concurrency suite verified 16/16 on PostgreSQL 16;
migration upgrade/downgrade/re-upgrade verified on SQLite **and** PostgreSQL;
metadata↔migration drift check clean for every M1 table. Frontend untouched;
public `EvidentiaReport` schema untouched; documents API response key set
pinned unchanged by test.

## Next step: M2 — upload + ingestion spine (MD/TXT)

Per `DOCUMENT_INGESTION_ARCHITECTURE.md` §15: multipart upload endpoint
(magic-byte sniffing, caps, dedupe, quotas, rate limits), the job worker +
state machine (**tenant-fair claims, claim-time `attempts` increments, stale
`running` requeue via `heartbeat_at`** — requirements recorded on the
`IngestionJob` model), MD (`markdown-it-py`) + TXT parsers → DocIR →
sectionizer, status surfaced in the documents UI/serialization. The backfilled
`pending` versions + `queued` jobs are sitting in the queue waiting for
exactly this worker.

## Unresolved (decide later, recorded where noted)

1. CAD migration milestone — triggered by the first renderer needing more than
   `EvidentiaReport` (platform doc §2).
2. `report.company` = tenant name — behind the corpus flag, product sign-off
   at M4 (`DECISIONS.md`).
3. M9 FTS `tsvector` column: early nullable column vs. maintenance-window
   rewrite — decide at M9 entry (NOT added in the M1 migration).
4. `documents.content_text` removal milestone after backfill verification.
5. DOCX renderer library choice (R-track); OCR timing; retention defaults;
   Stage-3 embedding model (deferred until `retrieval_misses` data).
6. Review notes deferred by the M1 correction pass (implement only when their
   milestone arrives): windowed backfill iteration if real corpus size requires
   it; optionally catch concurrent-backfill uniqueness conflicts cleanly;
   revisit `SectionRecord` hashing + nullable `category` before it becomes a
   live M2/M4 production contract; `TenantCorpusProvider` carries
   tenancy/version scope via its constructor or a future typed context.

## How to verify this session

```bash
cd backend && python -m pytest -q        # 311 passed, 3 skipped (SQLite)
python -m pytest tests/test_contracts.py tests/test_ingestion_schema_and_seams.py -q
DATABASE_URL=sqlite:///./_scratch.db python -m alembic upgrade head   # then downgrade -1 / upgrade head
DATABASE_URL=sqlite:///./_scratch.db python scripts/backfill_documents.py --dry-run
```

## Reminders

- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the public `EvidentiaReport` schema — and don't casually *add*
  fields either: every proposed field must answer "CAD concept, module
  extension, or renderer concern?" (platform doc §2).
- Engine code must never branch or string-match on a taxonomy label.
- Retrieval proposes; the deterministic gate disposes.
- Renderers: pure transformation of an immutable snapshot.
- Crash-safe write order is binding: version row (`pending`) → blob put →
  work; `current_version_id` flips only to `ready` versions.
- A version is visible to generation completely or not at all; backfilled
  versions stay `pending` until the M2 worker sectionizes them.
- Reports must carry `source_versions` + `engine_versions` from the first
  customer report (M4); provenance cannot be added retroactively.
- `company_id` never comes from client input — only from `CompanyContext`.
- Authenticated routes never fall back to the TypeScript pipeline.
- A 200 from generation means **persisted** — never return an unsaved report.
- **Take the lock, then re-read with `populate_existing`, then decide.**
- **Timing proofs need `time.perf_counter()`**, not `time.monotonic()`.
- **Never unset `EVIDENTIA_BACKEND_URL` as a rollback** — it disables auth.
