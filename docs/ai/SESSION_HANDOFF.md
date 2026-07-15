# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-14 (platform architecture consolidated; design closed; no code changed)._

## Where things stand

**Architecture design is closed.** This session produced documents only:

1. **`docs/ai/PLATFORM_ARCHITECTURE.md` (new)** — the platform constitution and
   architectural source of truth: eleven layers with forbidden
   responsibilities, the Canonical Analysis Document (CAD) + rendering
   invariant, domain modules as versioned data packs (compliance = Module #1;
   engine never branches on taxonomy labels), the two-layer claim pattern
   system, typed contracts (`SectionRecord v1`, `ClaimSpec v1`, …), complete
   report provenance (`source_versions` + `engine_versions`), the versioned
   anchor identity algorithm, staged retrieval with the `retrieval_misses`
   Stage-3 sensor, the two learning loops (no silent drift), operational
   corrections, deferred knowledge graph, and the milestone gates.
2. **`docs/ai/DOCUMENT_INGESTION_ARCHITECTURE.md`** — now *approved with
   corrections*; review corrections are inlined and marked `[REVIEW]`
   (full-text scoring, anchor algo versioning, provenance at M4, bounded
   cache, tenant-fair jobs, claim-time attempts, blob/row ordering, classifier
   provenance, M5a/M5b split). Where it disagrees with the platform doc, the
   platform doc wins.
3. **`docs/ai/DECISIONS.md`** — appended "Platform architecture constitution"
   (11 settled decisions with rationale).
4. **`docs/ai/PROJECT_STATE.md`** — consolidation summary added.
5. **`AGENTS.md`** — reading list + schema guardrail reconciled with the
   approved architecture.

All prior release-gate work stands (274 backend tests + 6 vitest green as of
the last verified run; PostgreSQL row locks verified on 16.14). **No
application code, schema or test was touched this session.**

## Next step: M1 (schema + seams) — entry criteria

Do not start M1 without covering (see `PLATFORM_ARCHITECTURE.md` §12):

- typed contracts `RawDocument v1`, `DocIR v1`, `SectionRecord v1`,
  `ClaimSpec v1` (+ stubs for the rest) — the section dict stops being
  anonymous;
- `BlobStore` / `JobQueue` / `SectionProvider` Protocols;
- additive-only migrations (`document_versions`, `document_sections`,
  `document_blobs`, `ingestion_jobs`);
- blob/row crash-safe write order + orphaned-blob reconciliation documented in
  the schema PR;
- feature flag `EVIDENTIA_TENANT_CORPUS_ENABLED` (default off) — off means
  today's behavior byte-for-byte;
- backfill command for existing `content_text` documents.

## Unresolved (decide later, recorded where noted)

1. CAD migration milestone — deliberately unscheduled; triggered by the first
   renderer that needs more than `EvidentiaReport` (platform doc §2).
2. `report.company` = tenant name — direction recorded in `DECISIONS.md`;
   ships behind the corpus flag with product sign-off at M4.
3. M9 FTS `tsvector` column: early nullable column vs. maintenance-window
   rewrite — decide at M9 entry.
4. `documents.content_text` removal milestone after backfill verification.
5. DOCX renderer library choice (R-track); OCR timing; retention defaults;
   Stage-3 embedding model (deferred by design until `retrieval_misses` data).

## How to verify this session

```bash
git status          # only docs/ai/* and AGENTS.md modified/added; no code
cd backend && python -m pytest -q   # unchanged: 274 passed, 2 skipped (SQLite)
```

## Reminders

- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the public `EvidentiaReport` schema — and don't casually *add*
  fields either: every proposed field must answer "CAD concept, module
  extension, or renderer concern?" (platform doc §2).
- Engine code must never branch or string-match on a taxonomy label.
- Retrieval proposes; the deterministic gate disposes. Embeddings/glossaries
  widen candidates only.
- Renderers: pure transformation of an immutable snapshot — no LLM, no
  retrieval, no scoring, no claim changes.
- Reports must carry `source_versions` + `engine_versions` from the first
  customer report (M4); provenance cannot be added retroactively.
- `company_id` never comes from client input — only from `CompanyContext`.
- Authenticated routes never fall back to the TypeScript pipeline.
- A 200 from generation means **persisted** — never return an unsaved report.
- **Take the lock, then re-read with `populate_existing`, then decide.**
- **Timing proofs need `time.perf_counter()`**, not `time.monotonic()`.
- **Never unset `EVIDENTIA_BACKEND_URL` as a rollback** — it disables auth.
