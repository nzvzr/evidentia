# Evidentia — Project State

_Concise snapshot. Update after meaningful changes. Last updated: 2026-07-18._

## Summary

Persona-aware documentation agent. Next.js frontend + Python FastAPI backend.
Deterministic-first pipeline; optional LLM refinement layered on top.
**Authenticated and multi-tenant**: every resource belongs to an organization,
and every query is tenant-scoped.

## M3 implemented + blocker-corrected (verified 2026-07-18, diff uncommitted)

Everything in the §12 M3 gate, honoring the binding M2→M3 lifecycle contract
(transitional versions immutable; finalization = re-ingestion into a NEW
successor version). A first review returned BLOCK with seven blockers, a
second focused review returned two blockers, and a final pass returned four
narrow commit-blocking corrections; all are corrected in place (M3 never
shipped, so the frozen algorithms/migration/fixtures stay coherent). Full
decisions text + per-blocker detail: `DECISIONS.md` 2026-07-17 ("M3
pre-release blocker corrections") and the two 2026-07-18 entries ("M3 final
blocker corrections", "M3 final four narrow commit-blocking corrections").

**Final four corrections (2026-07-18, round 3):** (1) the M3→M2 downgrade
REFUSES when a successor's source version has zero `document_blobs` rows
(was: silently skipped → byte-unresolvable successor); every successor needs
exactly one safely resolvable source blob (lineage, DB-backed data, size +
`content_sha256` proven). (2) Successors that already own a blob are
preflighted, not excluded: accepted only as an exact safe equivalent of the
source binding (then idempotent), never overwritten or deleted; the whole
materialization plan is built globally before any insert. (3) `downgrade()`
is exactly `_preflight_downgrade` → `_materialize_successor_blobs` →
`_apply_m2_schema_downgrade`, proven by executing the REAL `downgrade()` with
a sentinel preflight + interception of both phases, all `op.*` mutation entry
points and all SQL (zero mutating statements on refusal), plus an AST
supplement. (4) `validate_anchor_provenance` now receives the row's CURRENT
`anchor_id` and enforces the frozen decision SEMANTICS (self-lineage equality
for unchanged/heading-kept/reattached/inherited-*; similarity exactly 1.0 for
inherited-exact; finite 0.8 ≤ s ≤ 1.0 for inherited-similar;
`{parent}.p1` structure for split-lineage; typed reasons for every
violation); eligibility passes the anchor and still requires exact manifest
reconstruction in addition. Goldens validate unchanged — no manifest identity
change, `cft1` untouched.

**Final correction (2026-07-18): canonical anchor grammar, strict.** One
parser (`ANCHOR_GRAMMAR_RE`/`is_canonical_anchor`) now defines
permanent-anchor structure everywhere: slug 12..31 lowercase ASCII base36,
duplicate suffix >= 2 in canonical decimal (no `-0`/`-1`/leading zeros — the
first occurrence is always the bare slug), split part >= 1 canonical. The old
`-\d+`/`\.p\d+` laxness let split-lineage provenance accept malformed parents
(`slug-1`, `slug-01`); a follow-up strictness pass replaced `\d` with ASCII
`[0-9]` (Python `\d` admitted Unicode digits, int()-converted: `-2٢`→22) and
`$` with `\A…\Z` + `fullmatch()` (`$` admitted a trailing newline that the
parser silently discarded) — the parser validates a stored identifier and
never repairs one. Malformed forms map to the never-matching sentinel and
reject before the split relationship comparison; eligibility's divergent
private regex was replaced by the shared predicate; a parametrized test pins
predicate/parser agreement over the full valid+malformed corpus. Generation
already emitted only canonical forms (untouched); `ANCHOR_ALGO_VERSION`
unchanged; goldens byte-for-byte stable. Focused suites 249 passed; full
SQLite 754 passed / 11 skipped.

**Two final corrections (2026-07-18):** (1) **eligibility binds
`engine_versions` to the ONE pinned complete target** — a hybrid assembled from
two supported targets (Markdown pinned + supported TXT parser fields) is now
rejected: the persisted projection is reconstructed via
`target_from_engine_versions`, its digest must equal the pinned digest, and it
must deep-equal the registered projection with type-sensitive `canonical_json`
(thresholds/weights bound); **anchor provenance is validated against the frozen
decision contract AND hashed into the manifest** (`anchorProvenance`), so a
post-manifest tamper fails `manifest_mismatch`. (2) **The downgrade is
PREFLIGHT-FIRST** — every refusal check runs as pure SELECTs before any DDL,
then successor blobs are materialized while lineage exists, then the M2 DDL, so
a refusal leaves the complete M3 schema untouched regardless of DDL rollback.
Manifest identity changed → goldens regenerated (only `manifestSha256` +
`anchorProvenance`; all other identity surfaces byte-identical).

- **Anchor algorithm `heading-path-v1`** (`app/ingestion/anchors.py`):
  identity is the FULL canonical heading path (`heading_path_digest`, full
  sha1); the DISPLAY slug is **12 base36 chars** (corrected from an unsafe
  5-char slug that collided and silently mis-transferred anchors), extended
  deterministically in 4-char steps from each heading's own digest only when
  distinct canonical paths collide, and never reusing a retired prior anchor
  base of a different heading. Duplicate suffixes (`slug-2`, document order),
  split parts (`slug.p1`), constants frozen with the version.
  **Inheritance `content-match-v1`**: exact re-attachment inside duplicate
  groups (grouped by full digest) before renumbering; disappeared anchors
  matched exact-hash first then token-set Jaccard ≥ 0.8 under the §7.3
  tie-break; one-to-one both directions; ambiguous/unsafe ⇒ mint; guarded
  pass deterministically capped at 250k pairs. Pure functions, no DB/clock
  input; provenance (`anchor_provenance`) persisted per section. ~62-bit
  slug; per-document birthday risk ≈ n(n−1)/2^63.04.
- **Citation identity**: prefix minted at first finalization from the title's
  significant initials (3–5 chars, consonant-padded), tenant-unique via the
  existing unique index (SAVEPOINT retry, race-verified); immutable
  thereafter; `citation_id = {prefix}-{anchor}`. Final ids are still
  **internal** — no API exposes citation ids, section text or manifests.
- **Domain module framework** (`app/modules/loader.py` +
  `modules/compliance/1.0.0/*.json`): validated, digested, fail-closed data
  packs. Module #1 `compliance@1.0.0`: the frozen 8-category taxonomy +
  `General` fallback, 28 topics, 4 market facets, 7 persona needle sets,
  weighted category signatures with exclusions. Classifier engine `m3.1`
  executes packs generically (a test pins that engine sources contain no
  taxonomy label literals), full-text scoring, matched rule ids, injection
  flags, canonical per-section + version-level signatures.
- **Final manifest `m3.1`** (`app/ingestion/manifest.py`): canonical JSON
  (engine/module versions + ordered sections with anchors, citation ids,
  hashes, classification outputs, signatures) → `manifest_sha256`;
  `engine_versions` persisted on the version row. M2 manifests untouched.
- **CompleteFinalizationTarget** (`app/ingestion/finalization_target.py`):
  `finalization_engine` is now the COMPLETE target digest `cft1:<sha256>`
  over parser/normalizer/sectionizer/anchor/inheritance/classifier/
  section-signature/module(id+version+digest+signatureVersion)/manifest/
  thresholds/weights (corrected from a bare anchor-version label). Captured
  at trigger; the worker recomputes and REFUSES a pinned target it cannot
  reproduce (`unsupported_finalization_target`, fail closed); one builder
  serves trigger/CLI/worker/eligibility. Column widened 40→80.
- **Finalization** (`services/document_finalize.py` + pipeline
  `process_finalization`): eligible = ready `pre-m3-transitional` current
  versions only. Successor row (version N+1, same `content_sha256`,
  `source_version_id`, `finalization_engine`=complete target) reuses the
  retained blob (no copy) and runs `pending → extracting → sectioning →
  anchoring → classifying → ready` with per-stage heartbeats (`OwnershipLost`
  abort). One successor per (source, COMPLETE target) is DB-unique — changing
  ANY load-bearing component creates a distinct successor; one live job per
  version; failed successors retry into the SAME row. Sections + identity +
  signatures + manifest + ready + pointer flip commit atomically; the flip
  site never moves to a lower version_no (race-verified). Schema (AMENDED
  migration `a9d2e4c7b1f3`): `document_versions.{source_version_id,
  finalization_engine, engine_versions, classification_signature}`, the
  one-successor unique index, a composite self-FK
  `(source_version_id, document_id, company_id) → (id, document_id,
  company_id)` (+ parent unique key) enforcing same-document/same-tenant
  sources and delete-restriction in the DATABASE, plus a data-preserving
  downgrade (materializes successor blobs / refuses rather than stranding
  bytes or truncating prefixes); `document_sections.{anchor_provenance,
  matched_rules, classification_signature}`, `ingestion_jobs.operation`.
- **M4 eligibility predicate** (`services/generation_eligibility.py`, takes a
  `Session`, NOT yet consumed): fails closed against an explicit
  supported-target REGISTRY — the pinned complete target must be registered
  AND every stored component match a supported value (each rejected
  independently) — then validates PERSISTED sections (count vs manifest,
  ordinals, final anchors/citation ids, per-section signature + anchor-algo
  provenance, exact manifest reconstruction, version signature). Transitional
  always rejected even when current; malformed ⇒ ineligible, never raises.
- **API** (tenant-scoped, flag-gated): `POST /api/documents/{id}/finalize`
  (202 create / 200 adopt / 409 typed incl. already-final / cross-tenant 404
  — docstring pins the tested contract),
  `GET /api/documents/{id}/versions` (transitional-vs-final identity, safe
  metadata only), ingestion payload gains `identity`/`finalized`/`stageKind`.
  **CLI** `scripts/finalize_documents.py`: dry-run, per-tenant/per-document,
  bounded batches (`--limit` rejects ≤0 and >1000), resumable/idempotent
  discovery, `--process` inline mode SCOPED to that run's successors (never
  the global queue), count summaries, no document text in logs; refuses
  flag-off.
- **Frontend (minimal)**: BFF `app/api/documents/[id]/finalize`; Documents
  page states Queued/Extracting/Sectioning/Anchoring/Classifying/"Awaiting
  finalization"/"Citation-ready"/"Finalization failed" (+ Finalize button on
  transitional-ready rows, Retry on failures); polling covers the new
  stages; transitional docs are never labelled generation-ready; generation
  picker untouched (demo-only).
- **Classification signature** now covers the canonical `headingInput`
  (folded heading path + title) the classifier scores against, so equal
  outputs with different heading inputs get different signatures
  (`SECTION_SIGNATURE_VERSION = 1`). Module `engineCompatibility` +
  `signatureVersion` are validated by the loader AND enforced
  (`ensure_module_compatible`, part of the complete target + eligibility).
- **Citation prefix capacity**: candidates cover the configured tenant
  document quota (`evidentia_tenant_max_documents`, 500), so even titles that
  all derive `DOC` (empty/punctuation-only/non-Latin) allocate through the
  whole quota; `documents.citation_prefix` widened 8→12.
- **Golden fixtures** (`tests/golden/`): **17** fixtures — added merge,
  rename+split and size-bound oscillation (base/grow/shrink) — pin ordered
  sections, anchors, inheritance decisions, citation ids, labels, rule ids,
  signatures, the complete-target digest and manifests. `REQUIRED_GOLDEN_CASES`
  is asserted set-equal to the plan (no silent omission); a new integration
  golden runs the REAL API/worker/persistence path; regeneration only via the
  explicit reviewed command `scripts/regenerate_golden_fixtures.py`.
- **Verification (all green, 2026-07-18 round 3 — final four corrections)**:
  all four blockers reproduced first; backend SQLite **672 passed, 11
  skipped**; PostgreSQL 16 migration suite (both backends) **37 passed** +
  **23 concurrency**; `test_m3_migration.py` refusal matrix on SQLite AND
  PostgreSQL 16 — zero-source-blob, multiple/ambiguous source blobs, corrupt
  size/storage-key/hash metadata, NULL data, divergent pre-existing successor
  blob (kept untouched), multiple/incomplete successor blobs, and the
  early-valid+later-conflicting global-planning case each leave the complete
  M3 schema, Alembic revision, VARCHAR(12) prefix, `operation`, M3 section
  columns and `source_version_id` intact with zero inserted rows; equivalent
  pre-existing successor blobs accepted idempotently; the two-tenant
  M2→M3→M2→M3 round trip preserves exact source bytes; the real `downgrade()`
  proven preflight-first via sentinel + op/SQL interception and an AST
  supplement; goldens validate semantically UNCHANGED (no regeneration, no
  manifest identity change); `alembic check` on fresh SQLite and PostgreSQL 16
  head DBs = only the 4 pre-existing legacy auth drifts (zero new, none on
  M3); `git diff --check` clean. Frontend NOT re-run (no API response/type
  changed). Prior 2026-07-17/18 verification (seven-blocker + two-blocker
  passes, live PostgreSQL smoke, CLI checks) stands.
- **Explicitly not done (M4+)**: TenantCorpusProvider / generation
  integration, report source_versions/engine_versions, claim patterns, new
  parsers, FTS/embeddings. Report generation still reads ONLY the demo
  corpus.

## M2 implemented — MD/TXT upload + ingestion spine (verified 2026-07-16)

Everything in the M2 milestone (upload → blob → durable job → tenant-fair
worker claim → extract → normalize → sectionize → atomic persist → status UI),
gated on `EVIDENTIA_TENANT_CORPUS_ENABLED` (default **off** = pre-M2 behavior
byte-for-byte; upload endpoints return an explicit 403
`tenant_corpus_disabled`, the worker never starts, queued jobs are not
processed).

- **Upload API** (`POST /api/documents/upload`, multipart): authenticated +
  tenant-scoped, strict `.md`/`.txt` allowlist with content sniffing (binary
  magic/NUL/non-UTF-8 rejected; declared-type mismatch rejected), bounded
  streaming reads with SHA-256 from actual bytes, filename sanitization
  (display-only; storage is content-addressed behind BlobStore), typed
  user-safe errors, 202 on a new job / 200 on explicit duplicate. Also
  `POST /{id}/versions` (immutable version N+1; identical bytes = explicit
  no-op; identical bytes on a FAILED version = retry reusing the row/blob) and
  `POST /{id}/retry` (failed-only, 409 otherwise). Abuse bounds: per-file byte
  cap (streaming-enforced; the body-limit middleware raises the request cap
  only for the upload routes), extracted-char cap, one file per request,
  per-IP/user/tenant upload rate limits, and tenant document-count +
  stored-byte quotas checked under the company row lock (no check-then-write
  race). JSON `POST /api/documents` unchanged with the flag off; with it on it
  routes through the same spine (version 1 + blob + job) **under the same
  abuse bounds as multipart** (review fix 2026-07-16): upload rate budgets
  counted first, company row lock, count + byte quotas on the actual UTF-8
  bytes, one transaction, same typed codes, rejection leaves no rows.
- **Queue** (`DatabaseJobQueue`): tenant-fair claim (one candidate per tenant
  = its oldest queued job; tenants served round-robin, verified A/B
  alternation), claim-time `attempts` increment, atomic conditional-UPDATE
  ownership transitions (two-worker race leaves exactly one owner; verified on
  PostgreSQL 16), heartbeat (running-only), complete, retryable requeue vs
  terminal fail at the attempts cap (3), stale-running recovery (requeue below
  cap / terminal at cap) at startup and periodically.
- **Worker** (`app/ingestion/worker.py`): in-process bounded thread pool
  (default 1) started from app startup ONLY when flag+DB are on; idempotent
  `start()` (no duplicate pools under reload/repeated lifespans); event-based
  interruptible polling (no busy spin); graceful shutdown on app shutdown;
  typed retryable/terminal error classification; poison documents hit the cap
  and stop; tracebacks only in server logs, never document text.
- **Parsers → DocIR v1** (`app/ingestion/parsers.py`): Markdown via
  markdown-it-py (`js-default`, html=False — raw HTML stays literal text,
  never executed; no remote fetches): headings 1–6 with hierarchy, paragraphs,
  ordered/unordered/nested lists, blockquotes, fenced/indented code kept
  verbatim, tables → pipe-text, images → honest
  `[content omitted: image "alt"]` markers, links keep authored text (hrefs in
  meta). Plain text via cautious deterministic heuristics: numbered /
  decimal-nested / short-ALL-CAPS / underline headings, adjacency+depth rules
  so numbered lists never become headings, long sentences never become
  headings, <2 candidates ⇒ paragraph-grouping fallback. Unsupported formats
  fail typed. Deterministic; parser name/version recorded per version.
- **Normalization** (`app/ingestion/normalize.py`): UTF-8 only (BOM stripped;
  NUL ⇒ binary), CRLF/CR → `\n`, Unicode NFC, control chars stripped (tabs and
  newlines kept), extracted-char cap fails typed — never lossy replacement,
  never invented text.
- **Sectionizer** (`app/ingestion/sectionizer.py`, `m2.1`): heading-aware
  grouping preserving hierarchy/order, split at block boundaries at 4,000
  chars (single oversized blocks split at line→sentence boundaries; code/table
  blocks kept whole when they fit), undersized trailing split-fragments (<200)
  merge back, excerpt ≤1,200 chars derived from the full text, token/count
  metadata from the FULL text, omitted-content flags preserved, deterministic
  retries. **Transitional identity**: ordinal-based internal
  `s0007`/`pre-m3:s0007` ids + `anchor_algo_version="pre-m3-transitional"` —
  the M3 anchor algorithm is not pre-empted and no public citation identity is
  minted (see `DECISIONS.md` 2026-07-16).
- **State machine** (`app/ingestion/pipeline.py`): validated transitions
  pending→extracting→sectioning→ready / →failed (retry resets failed→pending;
  `classifying` reserved for M3). Sections are deleted+rewritten and the
  version marked `ready` in ONE transaction — no partial visibility, retries
  never duplicate rows. `current_version_id` flips at exactly one guarded site
  and only to `ready`; a failed new version never degrades a ready document.
  Typed `error_code` + bounded user-safe `error_detail` persisted.
- **Backfill integration**: M1-backfilled `content_text` jobs process safely
  (declared MD/TXT source honored via mime/filename/type resolution), no
  version-1 recreation, re-runs idempotent, `content_text` untouched.
- **APIs**: flag-on serialization adds one `ingestion` object (status, stage,
  versionNo, filename, detectedFormat, byteSize, sectionCount, errorCode/
  errorMessage, updatedAt, sourceType) + a `tenantCorpus` config object on the
  list; flag-off shapes are byte-for-byte pre-M2 (test-pinned). Never exposed:
  blob keys, paths, section text, citation ids, tracebacks, queue leases.
  Cross-tenant ids stay 404-shaped.
- **Frontend**: BFF routes `app/api/documents/upload` + `[id]/versions`
  (bounded multipart passthrough preserving the boundary; 401/413/429/503
  propagated; no client-side fallback) and `[id]/retry`.
  `lib/tenantDocuments.ts` + reworked Documents page: real upload with format/
  size guidance, honest per-stage labels (Queued/Extracting/Sectioning/
  Processed/Failed — "Processed" explicitly means *not yet used for report
  generation*), typed failure messages with Retry, per-document New version,
  bounded polling (2.5 s) only while a document is actively processing with
  stale-response guard + Strict-Mode-safe cleanup, real metadata only (no
  fabricated pages/percentages), demo corpus relabeled "SAMPLE CORPUS (DEMO)"
  when the flag is on. Flag-off UI unchanged (`lib/uploads.ts` superseded by
  the new hook).
- **Report generation untouched**: tenant ids in a selection resolve against
  the demo corpus only (unknown ⇒ demo fallback); test + live smoke prove no
  tenant text can appear in a report and no tenant/demo mixing occurs. Tenant
  documents never appear in the workspace generation picker (static demo
  corpus).
- **Verification (all green, re-run after the 2026-07-16 review fixes)**:
  backend **444 passed, 6 skipped** on SQLite (M2 tests: 38
  parsers/normalization, 20 sectionizer, 31 queue/worker/pipeline/backfill,
  45 upload API incl. 7 new JSON-create limit/quota tests); PostgreSQL 16
  profile: 100 ingestion/upload/seam tests + 18 concurrency tests all green
  (claim race, enqueue race, row locks, and the two new JSON-create quota
  boundary races). Alembic upgrade→downgrade base→upgrade head cycled
  on SQLite AND PostgreSQL 16 (no new migration needed — M1 schema was
  sufficient; `alembic check` shows only pre-existing legacy nullable drift,
  none on ingestion tables). Frontend: 45 vitest (17 new Documents tests),
  ESLint 0 errors (same 6 pre-existing warning class), `tsc` clean, production
  build clean. Live smoke (PostgreSQL + `next start` + real session): MD
  upload 202 → pending → ready (3 sections), duplicate 200 explicit (no new
  rows), TXT 202 → ready, `.pdf` → 415 typed, generation 200 with demo-only
  citations, exactly 1 persisted report, backend restart → both documents
  visible + a crash-simulated stale running job requeued and reprocessed
  without duplicate sections, flag-off restart → upload 403
  `tenant_corpus_disabled`, pre-M2 list shape, generation still 200.
- **Deferred to M3+**: anchors/citation prefixes/classification/injection
  flags (M3), TenantCorpusProvider + provenance + full-text scoring +
  version-aware cache + `report.company` (M4), claim patterns (M5),
  HTML/DOCX/PDF parsers (M6/M7), soft delete + versioning UX (M8), FTS (M9).

## M2 independent review remediation (2026-07-16)

The complete M2 diff was independently reviewed: **approve with fixes**, no
commit blockers (437 SQLite tests, PostgreSQL 16 profiles, 45 frontend tests,
Alembic cycles, tenant isolation, dedupe/quota concurrency, queue claim
correctness, parser/sectionizer determinism, and demo-corpus-only generation
all verified by the reviewer). Both fixes are applied; full text in
`DECISIONS.md` 2026-07-16 (review remediation entry).

- **Binding M2→M3 lifecycle contract** (M3 entry criterion + M4 provider
  invariant): versions stamped `anchor_algo_version="pre-m3-transitional"`
  are **immutable** — M3 never mutates the ready version row, its sections,
  its transitional anchor/citation ids, or its `manifest_sha256`. M3
  finalization = re-ingestion of the retained source blob into a **new**
  version row (final anchor algorithm, final citation identities,
  deterministic classification, new manifest, ready, controlled
  `current_version_id` flip); the old version stays byte-for-byte unchanged.
  M4's TenantCorpusProvider must **reject any `pre-m3-transitional` version
  even if `current_version_id` points to it** — `status == "ready"` alone is
  never generation eligibility.
- **Flag-on JSON create quota bypass closed**: `POST /api/documents` with the
  corpus flag on now pays the same abuse bounds as multipart via the shared
  service helpers (rate limit → company row lock → count/byte quotas on
  actual UTF-8 bytes → rows, one transaction, typed codes, no rows on
  rejection). Flag-off behavior byte-for-byte unchanged.

### Deferred debt (recorded, deliberately NOT fixed in this pass)

- **Worker ownership fencing** (blocker only for long-running formats, i.e.
  before PDF/DOCX/OCR in M6/M7 — not required at current MD/TXT bounds):
  `complete`/`fail` carry no lease/ownership epoch, so a stale holder whose
  job was reclaimed after stale-recovery could complete/fail the new holder's
  attempt. Needed: periodic heartbeats *during* processing, a lease token or
  claimed-attempt epoch, complete/fail conditional on current ownership, and
  a regression test (A goes stale → B reclaims → A can no longer
  complete/fail B's lease).
- **Flag-off legacy upload detail drawer** (low-priority UX compat): the
  pre-M2 session-upload detail drawer went away when `lib/uploads.ts` was
  superseded by the ingestion UI. Restore only if it turns out to be a
  trivial isolated change; not a reason to redesign the Documents page.

## Pre-M2 frontend generation stabilization (2026-07-15)

- Fixed the confirmed `/running` render-phase update: stage state updates are
  pure, and successful navigation now occurs once in a dedicated effect after
  both the persisted report id and the seven-stage animation are complete.
- Confirmed React Strict Mode previously started two generation fetches. A
  session-scoped run nonce and live-request-only single-flight registry now share
  one POST across setup/cleanup/setup replay, abort on a real unmount, delete
  settled entries immediately, and give retry a fresh logical attempt.
- Active-run ownership prevents stale success, failure, slow timer, or cleanup
  aborts from changing the current run. 401/429/503/timeout/network/other-error
  semantics remain explicit; authenticated report content is never put in
  `localStorage`.
- Independent review approved the diff with two non-blocking corrections, both
  applied: (1) `/running` header labels render the prerendered defaults until
  hydration completes (`useSyncExternalStore` hydration gate), so a hard refresh
  with a non-default stored persona/market produces no hydration mismatch while
  the generation effect still POSTs the stored input immediately; (2) a 200
  response whose body is unparseable, not an object, or lacks a non-empty string
  `report.id` now maps to the generic failure state (`Generation failed`) instead
  of waiting in finalizing forever.
- Regression coverage: 22 behavioral React tests under Strict Mode (six
  malformed-200 cases and two hydration-label tests added). Full frontend
  verification is recorded in `SESSION_HANDOFF.md`.
- Authenticated Chrome smoke, including a Next dev restart: each click observed
  exactly **1 POST /api/generate-workflow**, HTTP 200, exactly **1** new persisted
  report, one UUID redirect, zero Next error overlays, and report refresh success.
  Backend-down smoke observed one POST/503, honest `Generation unavailable`, and
  no report navigation; backend was restored afterward.
- No backend generation/persistence code and no M2 functionality changed. M2
  remains blocked until this uncommitted diff is independently reviewed, committed,
  and pushed.

## Platform architecture consolidated (2026-07-14, design only — no code changed)

The long-term architecture is closed and recorded in
**`docs/ai/PLATFORM_ARCHITECTURE.md`** (the architectural source of truth),
consolidating the ingestion proposal (`DOCUMENT_INGESTION_ARCHITECTURE.md`,
now *approved with corrections*) and the Staff Engineer review's conditional
approval. Key outcomes:

- Evidentia is a **domain-independent evidence reasoning platform**; the
  compliance vertical becomes **Domain Module #1** (versioned data pack, not
  engine code). Engine code never branches on a taxonomy label (lint-enforced
  from M3).
- A **Canonical Analysis Document (CAD)** is the eventual internal engine
  output; the public `EvidentiaReport` schema is unchanged and becomes CAD's
  first deterministic projection. Rendering is a pure transformation of an
  immutable snapshot (no LLM/retrieval/scoring in renderers).
- **Claims stay data** (declarative schema-validated patterns over typed
  matcher primitives, per-pattern fixtures in CI); the deterministic
  evidence gate remains the sole grounding authority; retrieval (incl. future
  FTS/embeddings and tenant glossaries) only widens candidates.
- **Review corrections adopted**: full-text (not excerpt) deterministic
  scoring; `reports.source_versions` + `reports.engine_versions` at **M4**
  (first customer report); versioned anchor algorithm with golden fixtures
  (M3); bounded version-aware report cache; tenant-fair job claims;
  claim-time attempt increments; blob/row crash-safe ordering; classifier
  provenance; M5 split into M5a (plumbing) / M5b (ongoing pattern authoring);
  `retrieval_misses` feedback as the Stage-3 embedding trigger sensor.
- **Learning without drift**: tenant-scoped feedback tables; improvements ship
  only as named, benchmark-gated data releases; tenant text never leaves the
  tenant automatically. Knowledge graph explicitly deferred.
- Milestone entry gates (M1/M3/M4/M5) are defined in
  `PLATFORM_ARCHITECTURE.md` §12. Eleven decisions appended to `DECISIONS.md`.
  **M1 is implemented (2026-07-15, see below); M2+ have not started.**

## M1 implemented — schema + seams + typed contracts (verified 2026-07-15)

Everything in the §12 M1 gate, additive only, zero behavior change (the flag
is off by default and nothing reads the new tables yet):

- **Typed contracts** (`backend/app/contracts.py`): `RawDocument v1`,
  `DocIR v1`, `SectionRecord v1`, `ClaimSpec v1` fully typed (frozen
  dataclasses, closed vocabularies validated, `contract_version` markers);
  `EvidenceBinding v1` and stubs for `ClaimCandidate`/`Finding`/
  `Recommendation`/`CanonicalAnalysisDocument v1`.
  `SectionRecord.to_pipeline_section(source_title)` is the strict projection
  to the pipeline currency dict, test-pinned against `document_reader`'s
  actual output key set (`source` = document title, supplied by the provider —
  see `DECISIONS.md` 2026-07-15).
- **Protocol seams**: `BlobStore` (`services/blob_store.py`) with a DB-backed
  `DatabaseBlobStore` (bytes in `document_blobs.data`, `storage_key`
  `db:<id>`, tenant-scoped reads); `JobQueue` (`services/job_queue.py`) with
  `DatabaseJobQueue.enqueue` (idempotent per live version; claim/worker is
  M2); `SectionProvider` (`agents/section_provider.py`) with
  `DemoCorpusProvider` verified byte-identical to `document_reader`. The
  orchestrator is NOT yet injected — that is M4.
- **Additive migration** `f7c3a1b9e2d4` (revises `d3a91c65e820`):
  `document_versions` (immutable revisions, status state machine,
  `anchor_algo_version`/parser provenance columns), `document_blobs` (1–1 per
  version), `document_sections` (SectionRecord persisted; unique
  `(version_id, anchor_id)` + `(version_id, ordinal)`; classifier provenance
  columns), `ingestion_jobs` (state/attempts/heartbeat +
  `(state, heartbeat_at)` index), and 11 new `documents` columns
  (`source_type`, `origin_uri`, `original_filename`, `mime_type`,
  `content_sha256`, `size_bytes`, `citation_prefix`, `current_version_id` —
  no DB FK, application-enforced flip, see `DECISIONS.md` — `status`,
  `deleted_at`, `created_by`). Verified: upgrade from empty → head, downgrade,
  re-upgrade on SQLite; migrated schema column-identical to
  `Base.metadata.create_all`. `content_text` is now formally deprecated
  (debt-watch removal milestone still pending).
- **Crash-safe blob/row write order + orphaned-blob reconciliation** are
  documented as a binding contract in the migration docstring and the
  `BlobStore` module docstring: version row (`pending`) → blob put → work;
  periodic sweep deletes blobs unreferenced past a grace window.
- **Feature flag** `EVIDENTIA_TENANT_CORPUS_ENABLED` (settings +
  `.env.example`), default **off** = today's behavior byte-for-byte; a test
  pins the default.
- **Backfill** (`scripts/backfill_documents.py` →
  `services/document_backfill.py`): synthesizes version 1 (`pending`) + blob +
  queued job per `content_text` document; idempotent (re-run skips
  already-versioned docs); one document per commit; `--company-id` and
  `--dry-run`. Verified end-to-end via the CLI against a migrated scratch DB.
- **Tests**: +38 (`tests/test_contracts.py` 13,
  `tests/test_ingestion_schema_and_seams.py` 24, one PostgreSQL enqueue-race
  test in `tests/test_concurrency.py`), including a byte-for-byte guard that
  the documents API response gains no new keys. Full backend suite:
  **311 passed, 3 skipped** (PostgreSQL-only). Frontend untouched.
- **Independent-review corrections applied (2026-07-15, verified)**: the
  application SQLite engine now enables `PRAGMA foreign_keys=ON`
  (`create_application_engine`; document deletes cascade, orphan repro fixed);
  partial unique index `uq_ingestion_jobs_live_version` (one queued/running
  job per version, DB-enforced; enqueue resolves the losing racer via
  SAVEPOINT + re-select, race verified on PostgreSQL 16); unique
  `uq_documents_company_citation_prefix` on `(company_id, citation_prefix)`
  (nullable, NULLs distinct); redundant single-column indexes removed
  (`ix_document_sections_company_id`, `ix_document_versions_document_id` —
  both covered by leftmost prefixes of composite indexes/constraints).
  Migration + ORM stay drift-free (checked on SQLite; migration also cycled on
  PostgreSQL 16).

## Authentication & multi-tenancy (verified 2026-07-13)

Replaces the previous demo auth (which had a password-less token endpoint, a
shared demo company, and unauthenticated CRUD).

- **Passwords**: bcrypt (cost 12) with a SHA-256 pre-hash, so bcrypt's 72-byte
  truncation is unreachable (`core/security.py`). Hashes never leave the server.
  Minimum length 12, enforced on register *and* reset.
- **Tokens**: short-lived JWT access tokens (15 min, `typ=access` — a refresh
  token cannot be presented as a bearer credential) + opaque 256-bit refresh
  tokens stored only as SHA-256 digests. Refresh **rotates on every use**;
  replaying a spent token revokes the whole rotation **family** (stolen-token
  reuse detection). When `EVIDENTIA_ENV=production`, `JWT_SECRET` must be a
  **generated** secret (base64url/hex of ≥32 random bytes; same gate as the BFF
  secret) — the app refuses to start on the dev default or any weak shape.
- **Flows**: register (creates user + organization + owner membership), login,
  refresh, logout (revokes one token), logout-all, `/me`, email verification,
  password reset (single-use, revokes all sessions, marks the address verified).
  Login and reset/verify requests are **non-enumerating** — an unknown address is
  indistinguishable from a wrong password (login burns an equal bcrypt cost).
- **Email**: `services/email.py` — a real `SMTPEmailSender` (stdlib `smtplib`), plus
  console/noop/in-memory senders for development and tests. Production requires
  `EVIDENTIA_EMAIL_BACKEND=smtp` + a host; console and noop are refused at startup.
- **Tenancy**: `api/deps.py::get_company_context` is the *only* source of a
  `company_id` in a request handler; it is always derived from a membership row.
  `company_id` is no longer accepted from a request body or an unchecked query
  param. Repository single-row lookups (`get_report`/`get_document`/`get_persona`)
  **require** a `company_id`, so fetching by id alone is impossible by construction.
  Cross-tenant access returns **404, not 403** (a 403 would confirm the id exists).
- **Roles**: owner > admin > member (`require_role`). Members read; admins delete
  tenant data and manage members; only owners mint owners or transfer ownership.
  A company can never lose its last owner.
- **Demo company removed**: `init_db` seeds nothing; `get_or_create_demo_company`
  and `resolve_company_id` are deleted. Every company is created by a registering
  user who owns it.
- **Frontend session**: tokens live in **httpOnly** cookies held by the Next.js
  BFF (`lib/auth/session.ts`); the browser never receives a token, so XSS cannot
  exfiltrate a session. The BFF attaches the bearer token server-side and silently
  rotates an expired access token mid-request. `middleware.ts` gates protected
  routes. `lib/useMockAuth.ts` is **deleted**.

**Authentication requires the Python backend, with no fallback.** With
`EVIDENTIA_BACKEND_URL` unset, login/register return 503.

## Hardening pass (verified 2026-07-14)

- **No authentication ambiguity in the fallback.** The authenticated route
  `POST /api/generate-workflow` has **no TypeScript fallback**: a report there
  belongs to a real account and is persisted to that tenant, so it may only be
  produced by a session the backend actually validated. Cookie *presence* is
  never trusted. Backend unreachable/unset → **503 `backend_unavailable`**;
  backend 401 → cookies cleared + 401. `/running` no longer generates locally —
  it surfaces unavailable / rate-limited / expired states with a retry.
- **The TypeScript pipeline survives only at `POST /api/demo/generate-workflow`**:
  explicitly anonymous (never reads session cookies), fixed showcase input (so it
  is not a free open-ended LLM endpoint), public demo corpus only, **persists
  nothing**, `X-Evidentia-Demo: true`, and IP-rate-limited in-process.
- **Rate limiting** (`core/ratelimit.py`): deterministic fixed-window counters,
  in-process memory, `RateLimitStore` Protocol for a future shared store. Auth and
  LLM-spend budgets are separate. Every limited endpoint counts **before** the DB
  is touched and keys on the *submitted* email whether or not it exists, so a 429
  is never an account-existence oracle. Throttled responses are **429 + Retry-After
  + `{"code":"rate_limited"}`** and leak no limit/remaining/window state.

  | endpoint | per account | per IP | other |
  |---|---|---|---|
  | login | 5 / 15 min | 20 / 15 min | — |
  | register | 3 / h | 5 / h | — |
  | refresh | — | 60 / 15 min | 10 / 15 min per token digest |
  | password-reset request | 3 / h | 10 / h | — |
  | password-reset confirm | — | 10 / h | — |
  | verify-email | — | 20 / h | — |
  | **generate-workflow** | — | 20 / h | **10 / h per user, 30 / h per tenant** |
  | demo generate (Next) | — | 5 / h | — |

- **Proxy trust** (`core/client_ip.py`): `X-Forwarded-For` is only read when
  `EVIDENTIA_TRUSTED_PROXY_COUNT > 0`, and then only the Nth-from-the-right entry
  (written by the innermost trusted proxy) is believed — a client-prepended prefix
  cannot rotate the rate-limit key. At 0 (default) XFF is ignored entirely. The
  BFF forwards a *single* resolved client IP (never the caller's own chain), so the
  backend can attribute per-IP limits to real users instead of to the BFF.
- **Request limits**: body capped at 512 KiB, enforced pre-parse as raw ASGI
  (`middleware/body_limit.py`) — it rejects an oversized `Content-Length` **and**
  counts streamed bytes, so `Transfer-Encoding: chunked` cannot bypass it (413
  `payload_too_large`). Field caps: email 254, password 12–256, selected documents
  ≤ 50 (id ≤ 200 chars), customPersona ≤ 500, tokens ≤ 512, document text ≤ 200k.

## Security hardening pass 2 (independent review remediation, verified 2026-07-14)

An external review found 8 release blockers. All reproduced with failing tests
(`backend/tests/test_exploits.py`: 19 of 27 failed pre-fix), all now fixed and green.

- **P0-1 JWT** — the dev secret was usable in any non-production env, and
  `decode_access_token` accepted a token with **no `exp`** (python-jose only
  validates expiry when the claim exists), i.e. a forever-valid credential.
  Now: production refuses missing/default/known-weak/<32-char/low-entropy keys
  (fail-fast at startup *and* on every sign/verify); decode requires `sub`, `typ`,
  `exp`, `iat`, `jti` and pins the algorithm (`alg:none` impossible).
- **P0-2 localStorage** — authenticated reports (`evidentia:reports`) and uploaded
  document excerpts (`evidentia:uploaded-documents`) sat in global keys that
  survived logout, so one account's content was readable by the next user of the
  browser. Now: the backend is the **only** source of truth; nothing authenticated
  is cached; a backend 404 **never** falls back to a local/generated report;
  uploads go to the tenant-scoped `POST /api/documents`; legacy keys are purged at
  boot and on every session change. Only `evidentia:public-demo:*` may persist.
- **P0-3 Owner invariants** — `POST /members` **upserted**, so an admin could
  re-POST the owner with `role=member` and silently demote them. Now: creation is
  409 on an existing membership, and every role mutation goes through one
  transactional gate (`memberships.change_role`) holding a company row lock:
  admins can never touch an owner, self-transfer is 400, and the last owner cannot
  be demoted or removed (concurrency-tested).
- **P0-4 Refresh rotation** — read-then-write allowed two concurrent refreshes to
  both pass `is_usable()` and mint two valid children. Now: a **conditional UPDATE**
  (`SET revoked_at WHERE revoked_at IS NULL AND expires_at > now`) makes the DB pick
  a single winner. The BFF adds **single-flight** refresh so parallel page requests
  don't trip family revocation on a legitimate user.
- **P0-5 Rate-limit store** — swept the entire map on every write (cost grew with
  tracked keys), and every unique email/token minted a permanent entry (memory DoS).
  Now: bounded `OrderedDict` with LRU eviction (`EVIDENTIA_RATE_LIMIT_MAX_KEYS`) and
  a fixed-slice amortized sweep; `check_all` enforces the **IP rule first and
  short-circuits**, so a blocked IP mints no further account/token keys.
- **P0-6 Proxy trust** — the BFF forwarded a client-supplied `X-Real-IP` at zero
  trusted hops, letting anyone rotate their rate-limit identity. Now: `X-Real-IP` is
  never trusted at any hop count; only a validated `X-Forwarded-For` chain is used;
  and `EVIDENTIA_BFF_SECRET` lets the backend refuse any request that did not come
  through the BFF (production refuses `trusted_proxy_count > 0` without it).
- **P0-7 Report persistence** — `POST /api/reports` accepted an arbitrary JSON blob,
  so a client could store a report claiming `generationMode: llm-assisted` with 100%
  confidence and invented citations. Now **405**: authenticated generation is the
  only path that creates a report.
- **P0-8 Next.js** — 14.2.5 had a critical advisory. Upgraded to **Next 16 +
  React 19** (14.x and 15.x are both inside the advisory range); ESLint 9 flat
  config; `npm audit` = **0 vulnerabilities** (prod and dev).

**P1 also done**: access-token revocation via `users.token_version` (password reset
and logout-all strand outstanding access tokens immediately — previously they stayed
valid for their full TTL); raw body caps in the BFF *before* `request.json()`;
per-account email-verification limit; console email sender refused in production (it
logged single-use reset links); org-creation quota + verified-user requirement.

## Release-gate hardening pass 3 (verified 2026-07-14)

A second independent review found 4 High + 3 Medium blockers. All reproduced with
failing tests first, then fixed.

- **H1 Demo limiter** — the Next-side limiter for the anonymous demo route was an
  unbounded `Map` swept in full on every request. Its key space is attacker-chosen
  (any IP), so a spray both grew memory without limit and made each request more
  expensive. Now bounded (LRU, `EVIDENTIA_DEMO_RATE_MAX_KEYS`) with a fixed-slice
  amortized sweep. 6 vitest tests, incl. 200k unique IPs staying under the cap and a
  cost regression guard. Demo route stays fixed-input and non-persistent.
- **H2 Session revocation vs issuance** — `token_version` was an ORM
  read/modify/write (concurrent bumps lose updates), and nothing serialized *issuing*
  a session against *revoking* one, so a refresh could commit a child token after a
  logout-all sweep and survive it. Now: `bump_token_version_by_id` is an atomic
  `SET token_version = token_version + 1`, and login / refresh / logout-all /
  password-reset each take a **user row lock** for the whole transaction. A refresh
  racing a revocation either commits before the lock (and is swept) or waits and sees
  the new version.
- **H3 Owner authorization** — `change_role` trusted the actor's role as captured
  *before* the lock, so a mutation queued behind the lock could act with authority its
  actor no longer had. Both memberships are now re-read **under** the lock
  (`_authorize_under_lock`), and `company.owner_id` is atomically reassigned to another
  active owner when the designated owner is demoted or removed (or the change is
  rejected). Previously a concurrent demotion left `owner_id` pointing at an *admin*.
- **H4 Generation persistence** — a persistence failure was caught, logged, and the
  **unsaved** report returned with **200**, so the client navigated to a report id
  that did not exist and an LLM call was billed for nothing. Persistence is no longer
  best-effort: DB disabled → **503 `persistence_unavailable`**; commit failure →
  rollback + **503 `persistence_failed`**; production refuses `EVIDENTIA_DB_ENABLED=false`.
  The BFF distinguishes persistence failure from transport failure.
- **M5 BFF secret** — now length/entropy/known-weak validated in production
  (a guessable shared secret is equivalent to no secret); comparison was and remains
  constant-time (`hmac.compare_digest`), now covered by a test.
- **M6 Concurrency tests** — the harness shared **one** SQLAlchemy Session across all
  requests and threads, which both hid races and caused flakes. Now: a file-backed
  SQLite DB per test (WAL + busy timeout), a fresh Session per request and per worker
  thread, worker exceptions collected and asserted empty, and
  `PytestUnhandledThreadExceptionWarning` promoted to an **error** in `pytest.ini` —
  verified to actually fail a test when a thread dies. Suite is stable across repeated runs.
- **M7 Email + docs** — implemented a real `SMTPEmailSender` (stdlib `smtplib`).
  Production now requires `EVIDENTIA_EMAIL_BACKEND=smtp` + a host: `console` writes
  single-use reset links to the logs and `noop` silently discards them, so both would
  make password reset *look* like it works. `backend/.env.example` documents every
  production/auth variable; README, backend README, health route and DEPLOYMENT.md no
  longer claim an authenticated deterministic fallback; SQLite and wildcard CORS are
  explicitly not recommended for a public beta.

## Release-gate hardening pass 4 (verified 2026-07-14)

A targeted re-review found 3 High + 2 Medium issues that survived pass 3. All three
High findings were reproduced with failing tests first, then fixed.

- **H1 Login survived a concurrent password reset.** The password was verified
  *before* the user lock was taken. A login could approve the OLD password, pause,
  let a concurrent reset change the password and revoke every session, then resume
  under the lock, re-read the user, and mint a fresh session carrying the *new*
  `token_version` — a fully live credential produced by a password that had just
  been reset away. Reproduced end-to-end (reset 200, then the old password returned
  a working session). Now the lock is taken **before** the password decision and the
  row is re-read under it, so the verification and the session issuance are one
  critical section. `password-reset/confirm` also takes the user lock *before*
  burning the token, so the single-use check, the password change, the revocation
  sweep and the version bump all serialize against every issuer.
- **H2 Stale identity-map authorization and owner pointer.** SQLAlchemy returns the
  instance already in the Session's identity map and *discards* the row it just
  selected, so the "re-read under the lock" added in pass 3 was not re-reading
  anything. Two consequences: (a) `db.get(Company, …)` returned the request's
  `ctx.company` — strongly referenced, so reliably stale — and a demotion queued
  behind a concurrent ownership transfer compared against the stale `owner_id`,
  concluded the demoted user was not the designated owner, skipped the reassignment,
  and left **`company.owner_id` pointing at an admin** (reproduced); (b) member
  *creation* authorized from `ctx.role` and took no lock at all, so a demoted admin
  could still invite (reproduced: 201). Now every membership read in the gate uses
  `populate_existing`, member creation goes through the same locked gate
  (`add_member_guarded`), and `_enforce_owner_pointer` re-derives the pointer from
  the owner rows under the lock after **every** mutation.
  Note the actor-role staleness was previously masked by the identity map holding
  *weak* references — the stale object was usually collected first, so the bug
  surfaced only sometimes. Authorization that is correct only when the garbage
  collector happens to have run is not correct.
- **H3 BFF secret strength was ineffective.** "32 characters + 8 distinct
  characters" accepts `abcd1234abcd1234abcd1234abcd1234`. Production now requires a
  **cryptographically generated** secret: the base64url or hex encoding of ≥32
  random bytes, additionally rejecting known-weak values, weak substrings, repeated
  blocks, sequential runs, narrow alphabets (word lists), low estimated entropy and
  highly compressible values. Per-character floors are alphabet-relative, because a
  real `token_hex(32)` legitimately shows lower per-character entropy than a real
  `token_urlsafe(32)`; measured on 400k generated secrets, false rejection is ~1e-5
  (and fails loudly with the generation command). Comparison remains constant-time.
- **M1 Concurrency tests now verify the real properties.** The stale-authority test
  is genuinely queued (the second writer asserts it finished *after* the first
  released the lock, so two merely-overlapping threads cannot masquerade as a
  serialized test). `token_version` assertions are exact — the counter must move by
  exactly the number of *accepted* logout-all calls, not `>= 1`, which a lost update
  also satisfies. `PytestUnhandledThreadExceptionWarning` stays an error. SQLite and
  PostgreSQL semantics are separated: an opt-in PostgreSQL profile
  (`EVIDENTIA_TEST_DATABASE_URL`) runs the suite against real row locks, and the
  PostgreSQL tests **skip loudly** when it is unset — see *Open concerns*.
- **M2 Documentation matches the authenticated architecture.** Removed every claim
  that authenticated routes work without the backend, fall back to the TypeScript
  pipeline, persist through `localStorage`, or succeed with the DB disabled.

## Final release blockers closed (verified 2026-07-14)

- **PostgreSQL row-lock semantics VERIFIED.** The opt-in profile
  (`EVIDENTIA_TEST_DATABASE_URL=postgresql+psycopg://…`) ran against a real
  PostgreSQL **16.14** (Docker): all **15** tests in `test_concurrency.py` —
  login vs password reset, login vs logout-all, refresh rotation (at most one
  child), stale-authority role change / member creation, transfer vs demotion,
  owner-pointer consistency, plus the two PostgreSQL-only row-lock tests — passed
  **15 consecutive runs** (0 failures). `SELECT … FOR UPDATE` behaved exactly as
  the H1/H2 fixes assume: queued writers demonstrably finished after the lock
  holder released (the finished-after-release assertions all held).
  One harness fix was needed: the queue-proof used `time.monotonic()`, which on
  Windows CPython 3.12 ticks in ~15.6 ms steps; PostgreSQL hands off a released
  row lock so fast that "released" and "finished" landed in the same tick and the
  strict `>` failed on equality (SQLite passed only because its busy-wait retry
  made the gap wider than a tick). The proof now uses `time.perf_counter()`. No
  application behaviour differed between SQLite and PostgreSQL.
- **JWT secret strength parity.** `JWT_SECRET` now goes through the same
  generated-secret gate as `EVIDENTIA_BFF_SECRET` (shared
  `_generated_secret_problem`; `jwt_secret_problem`): production requires the
  base64url or hex encoding of ≥32 random bytes and rejects known defaults, weak
  substrings, repeated blocks, sequential runs, dictionary-like values, narrow
  alphabets, low-entropy and highly compressible values. The old gate's
  `abcd1234abcd1234abcd1234abcd1234` (32 chars, 8 distinct) is now refused.
  Development/tests still run on the dev default (the gate is production-only,
  validated on every sign/verify). 21 new regression tests: the 14 weak shapes
  rejected as JWT keys, `token_urlsafe(32)`/`token_urlsafe(48)`/`token_hex(32)`
  accepted (statistical, 50 samples each), the error message carries the
  generation command, and a JWT forged with the published dev default is refused
  once a real key is set — as is any session issued under the old key.
  `pytest.ini` additionally promotes `PytestUnraisableExceptionWarning` to an
  error.

## Components

- **Frontend** (`app/`, `components/`, `lib/`, `data/`): landing, `/login`,
  `/register`, `/forgot-password`, `/reset-password`, `/verify-email`,
  `/workspace`, `/running`, `/reports` + `/reports/[id]`, `/playbooks`,
  `/documents`, `/playbook/[id]/print`. Reads reports **only from the backend** —
  there is no `localStorage` fallback for authenticated data, and a backend 404
  never falls back to a local report.
  The `/running` loader shows honest pipeline stages (no fake %), gates one-time
  navigation on the real persisted id plus animation completion, deduplicates
  Strict Mode effect replay, and has timeout/slow/unavailable/error states. The report UI and
  print playbook render insufficient-evidence (`N/A`) items as a distinct
  "INSUFFICIENT EVIDENCE" marker, use a 3-colour severity scale, and handle empty
  risk/workflow/citation states. The PDF flows long sections across pages
  (no clipping).
- **Next.js BFF** (`app/api/generate-workflow`, `app/api/reports[...]`,
  `app/api/auth/*`, `app/api/documents`): an authenticated **proxy** to the Python
  backend. It has **no fallback** — backend unreachable or `EVIDENTIA_BACKEND_URL`
  unset → **503**. The TypeScript pipeline (`lib/agents/*`) is reachable **only** at
  `POST /api/demo/generate-workflow`: anonymous, fixed showcase input, public corpus,
  persists nothing.
- **Python backend** (`backend/app/`): FastAPI multi-agent pipeline + persistence
  (SQLAlchemy 2.x + Alembic) + LLM evaluation framework (`app/eval/`). **Production
  requires managed PostgreSQL**; SQLite is local development only, and
  `EVIDENTIA_DB_ENABLED=false` is refused at startup in production.

## LLM modes (`EVIDENTIA_LLM_INTENSITY`)

- `off` — deterministic only, 0 LLM calls (`generationMode: deterministic`).
- `summary` — deterministic + 1 LLM call to polish narrative (`llm-summary`). Default.
- `full` — deterministic + ≤3 LLM calls (`llm-assisted`).
- `auto` — **calibrated conservative router** (`agents/mode_router.py`). Routes from
  pre-LLM deterministic signals only. Summary is the default; `off` only when the
  baseline is already strong; `full` requires BOTH a clear deterministic analytical
  weakness AND sufficient selected-document evidence AND ≥2 independent
  opportunity signals AND predicted incremental gain > `EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD`.
  A custom persona, a single contradiction, a large corpus, or a slightly-low
  confidence never force full. On the v1 benchmark this resolves every scenario to
  summary (see calibration below); full stays a manual mode.

Currently benchmarked model: **gpt-4o-mini**. Keys live only in `backend/.env`
(git-ignored). **Generation** works with no key (deterministic mode) — this does
*not* mean the product runs without the backend or the database, which
authentication, tenancy and persistence all require.

## Calibration framework (`backend/app/eval/`)

- **Two score axes**: `groundingScore` (schema, citation accuracy/coverage,
  hallucination/injection warnings) and `narrativeUtilityScore` (summary factual
  consistency, completeness, concision, persona/market relevance, action
  usefulness, action-evidence alignment, vague/repetition penalties). `overallQualityScore`
  is a 50/50 blend.
- **Field-level narrative gate**: accepts an LLM field (summary / personaBrief.description /
  suggestedActions) only if it is strictly better AND factual consistency and
  grounding do not drop AND warnings do not increase; ties preserve deterministic.
- **Deterministic grounding repair** (`tools/citation_tools.py`): validates every
  workflow/risk `evidenceCode` against selected-document citation IDs; replaces
  invalid codes using an **IDF-weighted relevance scorer** (generic terms
  downweighted, exact multi-word phrase bonus, section-title matches weighted above
  excerpt, configurable `EVIDENTIA_REPAIR_MIN_RELEVANCE`, ≥2 meaningful matched
  terms unless a strong phrase). If nothing clears the threshold the item is marked
  `N/A` (insufficient evidence) — never the least-bad citation. Every repair emits
  an audit record (matched terms/phrases, relevance score, top-3 candidates); audit
  is exported in benchmark JSON/CSV but never in the public report.
- **Source-constrained (evidence-first) generation** (`agents/risk_analyzer.py`,
  `agents/workflow_builder.py`, `tools/evidence_support.py`): risks and workflow
  steps are derived from a *selected* source section instead of being chosen
  generically and cited afterward. A deterministic **evidence-support scorer**
  (separate from repair) scores a candidate section by selected-document
  ownership, risk/workflow-specific vocabulary, exact domain phrases, document
  category affinity, persona relevance, market relevance, and negation/
  contradiction markers. A risk is emitted grounded only when a section it *owns*
  clears the configurable signal strength (`EVIDENTIA_MIN_EVIDENCE_SUPPORT`, ≥2
  signals or a domain phrase). Unsupported risks are **dropped, not filler-filled**;
  when too few grounded risks remain and the missing documentation is itself
  operationally relevant, one explicit evidence-gap risk (`N/A`) is emitted.
  Internal provenance (`sourceDocumentId`, `sourceCitationId`, `matchedSignals`,
  `generationReason`) is kept in telemetry only — never in the public report.
- **Full-mode structural quality gate** (`agents/structural_gate.py`): full mode no
  longer overwrites the deterministic analytical baseline. It preserves the
  baseline, builds the LLM output as a separate candidate, scores both with
  deterministic structural scorers (persona: persona/market/source-topic
  relevance + precision; workflow: evidence support, citation validity, ownership,
  operational completeness, persona relevance, duplicates, unsupported/N-A; risks:
  evidence support, validity, ownership, specificity, duplicates, contradiction
  awareness, severity consistency, unsupported/N-A), reconciles workflow/risk items
  one by one (preserve strong deterministic items, accept genuinely better/new
  grounded items, reject unsupported/weaker/duplicate/generic, never force a count),
  and accepts a component only when its structural score is strictly higher AND
  grounding, citation accuracy, warnings, source-doc mismatch, N/A count, and schema
  validity do not regress. Ties preserve deterministic. Runs *before* grounding
  repair; repair → re-bind → recompute metrics → narrative polish/gate follow.
- Versioned benchmark dataset (`BENCHMARK_VERSION = v1`, 22 scenarios) with
  ground-truth expectations; exports JSON + CSV + repair audit CSV + generation
  audit CSV. Runner supports `--runs N`, `--scenario`/`--category` filters, mean/std
  for quality/latency/cost, win/tie/loss vs deterministic & summary, structural
  regressions before/after gate, full incremental gain vs summary, and cost per
  accepted analytical improvement. Ground-truth match split into four metrics:
  `expectedRiskConceptRecall`, `expectedSourceDocumentMatchRate`,
  `expectedCitationFamilyMatchRate`, `expectedCitationExactMatchRate` (exact
  citation matching retained, not replaced by prefix matching).

## Latest key-enabled benchmark (gpt-4o-mini, v1, 22 scenarios, 2026-07-13)

Full-mode structural gate now runs before repair.

| mode | overall (±std) | grounding | narrative | structural | latency | cost |
|------|----------------|-----------|-----------|------------|---------|------|
| deterministic | 93.8 (4.15) | 93.9 | 93.8 | — | ~1 ms | $0 |
| summary | 95.4 (3.10) | 93.9 | 96.9 | — | 5.4 s | $0.0078 |
| full | 94.8 (3.29) | 93.9 | 95.7 | 77.0 | 24.1 s | $0.0295 |
| auto | 94.9 (3.76) | 93.9 | 96.0 | — | 5.2 s | $0.0077 |

Schema-valid 1.0 and 0 hallucination warnings in every mode. `auto` routes all 22
scenarios to summary (its numbers differ from the summary row only by LLM run-to-run
variance).

- **Structural gate (full):** baseline structural 67.5 → pure candidate ~80.9 →
  **final 77.0** (guardrails held back non-improving/regressing gains).
  **Structural regressions 0 after gate** (1 → 0 in a prior run); 0 grounding
  regressions; schema 1.0. Accepted 27/66 components (59 items); rest reverted to
  deterministic. 0 analytical fallbacks.
- **Full vs deterministic:** win/tie/loss **5/15/2** (0 grounding losses).
  **Full vs summary:** **2/8/12**, incremental gain **−0.54** at ~3.8× cost
  ($0.0295 vs $0.0078; cost/accepted-item $0.0005). → Full mode's analytical
  changes are safe but rarely beat summary; **summary remains the default sweet
  spot** and auto-routing should stay conservative about full.
- **Ground-truth match:** exact-citation **0.833**, family **1.0**, document
  **1.0**, risk-concept recall **0.889** (identical across modes — generation is
  deterministic).

## Router calibration (oracle + policy search, v1)

`scripts/calibrate_router.py` (offline) computes an oracle upper bound and compares
policies before tuning any threshold. Verified on the 4-mode benchmark:

- **Oracle** (best per-scenario mode, ε=0.2 ties preferring cheaper): avg overall
  **95.47** vs always-summary **95.36** → **gain only +0.12** (< 0.2). Oracle picks
  full in just **2/22** scenarios; **full is Pareto-dominated** (frontier =
  {deterministic, summary}).
- **Policy comparison:** always-summary 95.36 (cost $0.0078, worst-regression 0.0,
  constraints ✓); **previous aggressive auto 95.02** (worse than summary, cost
  $0.0259, worst-regression 2.8, routed 18/22 to full, constraints ✗);
  **proposed calibrated router = always-summary** (routes 22/22 → summary,
  constraints ✓). No `full_gain_threshold` in {0.0…1.0} beats summary by 0.2.
- **Leave-one-category-out:** every held-out category picks threshold 0.0, gain 0.0
  — the router generalizes (not overfit to scenario IDs).
- **Verdict:** benchmark evidence does **not** justify automatic full routing. Auto
  resolves to summary by default; full is kept as an explicit manual mode. The
  conservative full-eligibility mechanism exists and is unit-tested, but its
  conjunction never fires on the current corpus.

## Upstream fix impact (insufficient-evidence before vs after)

- **Before (repair-only):** 31 invalid evidence codes reached repair; 2 replaced,
  **29 marked `N/A`** — i.e. unsupported risks were generated then patched.
- **After (evidence-first):** repair has nothing to fix —
  `ungroundedBeforeRepair = 0`, `repairReplaced = 0`, `repairInsufficient = 0`.
  36 unsupported risk proposals are dropped at the source
  (`sourceDocumentMismatchCount` drives most), and remaining `N/A` items are
  intentional evidence-gap markers, not repaired guesses.

## Demo release-readiness (frontend/PDF pass, verified 2026-07-13)

Product-facing pass over the generation flow (schema, summary-as-default,
full-as-manual, and all backend safeguards preserved). **Superseded in part by the
hardening passes below**: the local-fallback behaviour described here was removed —
`/running` no longer generates locally and instead surfaces unavailable /
rate-limited / expired states.

- **Loading** (`app/running/page.tsx`): honest stage-segmented progress (removed the
  fake percentage and fabricated per-agent counts), completion gated on the real
  report, plus slow-notice (22s), hard-timeout (60s), and an error state with retry.
- **Insufficient evidence**: `evidenceCode === "N/A"` now renders as a distinct
  dashed "INSUFFICIENT EVIDENCE" marker (web report + PDF risk register + workflow),
  not a normal citation chip.
- **Report UI**: 3-colour severity scale (High/Med/Low), citation `section` shown,
  empty states for risks/workflow/citations.
- **PDF**: variable-length sections (`.print-flow`) flow across pages instead of
  clipping at a fixed 297 mm; metadata footer per section; dynamic agent count +
  next-review date (no stale hardcoded values).
- **Showcase scenario** `showcase-residency-emea` (Compliance · EMEA, 4 docs) seeds
  the library end-to-end.
- **Verified E2E** (Next `/api/generate-workflow` → Python backend, gpt-4o-mini
  summary): showcase → 3 risks (RES-14/SEC-4.2 High, SLA-5 Med), 5 steps, 8 cited
  sections, HTTP 200 ~7.5 s; insufficient corpus (support · pricing-only) → 1
  evidence-gap risk + 3 `N/A` steps rendered as insufficient-evidence. `next lint`,
  `next build`, `tsc --noEmit` clean; all report/print/workspace/documents pages 200.

## Deployment readiness (verified 2026-07-13)

Prepared for a stable public demo (no new features). See `DEPLOYMENT.md`.
**Predates authentication**: the fallback and SQLite-demo behaviour recorded below
has since been removed. Authenticated routes now return 503 with the backend down,
and production requires managed PostgreSQL. Kept as a historical record of the
container/health/config work, which still stands.

- **Backend container**: `backend/Dockerfile` (+ `.dockerignore` that keeps the
  `*.md` corpus), listens on `$PORT`, container `HEALTHCHECK` on `/health`. Pinned
  `requirements.txt`.
- **Health**: backend `GET /health` → `{status, version, llmEnabled, intensity,
  dbEnabled}` (no secrets); new frontend `GET /api/health` → `{status,
  backendConfigured, backendReachable, mode}`.
- **Config**: env-driven CORS (`EVIDENTIA_CORS_ORIGINS`); proxy timeouts
  (`EVIDENTIA_BACKEND_TIMEOUT_MS` 45s for cold starts,
  `EVIDENTIA_BACKEND_READ_TIMEOUT_MS` 8s) so a cold/unreachable backend fails fast
  — now to **503**, not to a fallback; `next.config` `output:"standalone"` +
  `poweredByHeader:false`.
- **No hardcoded localhost** in source; backend URL/keys are server-only.
- **Verified locally (production build)**: `next lint`/`tsc`/`next build` clean;
  backend `pytest` green; prod `next start` + backend E2E — frontend `/api/health`
  `backendReachable:true`; showcase generate HTTP 200 (~6s), report **persisted to
  the DB and re-fetched by id**; insufficient corpus → 4 `N/A` markers; all
  report/print/workspace/documents/library routes 200; **backend-down →
  503 `backend_unavailable`** on authenticated routes (no report in the body).
- **Cloud deploy NOT performed** (no hosting credentials/public URLs available);
  only local production verification was done.

## Tests

- **444 passing** backend tests (+6 skipped on SQLite: the PostgreSQL-only
  tests) + **45 vitest**: `python -m pytest -q` (from `backend/`) and
  `npm test`. The concurrency file verified against real PostgreSQL 16.14
  across **15 consecutive runs** (all 15 auth/tenancy tests, 0 failures) and
  again on 2026-07-16 (18 tests incl. the JSON-create quota races); the M2
  ingestion/queue/upload suites additionally verified against PostgreSQL 16
  (see the M2 section above).
  - **134 M2 tests** (`test_ingestion_parsers.py` 38, `test_sectionizer.py`
    20, `test_ingestion_queue_worker.py` 31, `test_upload_api.py` 45 — incl.
    the 7 review-fix JSON-create limit/quota/rate tests): see the M2 section
    above for coverage.
  - **37 M1 tests** (`test_contracts.py` 13, `test_ingestion_schema_and_seams.py`
    24): SectionRecord→currency projection pinned against the demo reader's
    real output; closed contract vocabularies; schema uniqueness constraints
    (incl. tenant-scoped `citation_prefix` and the live-job partial unique
    index); FK cascade through the real application engine (SQLite pragma);
    blob 1–1 per version; BlobStore roundtrip + tenant-scoped reads; JobQueue
    enqueue idempotency + terminal-state re-enqueue + lost-race survivor
    adoption preserving the outer transaction; DemoCorpusProvider ≡
    document_reader; documents API key-set unchanged; corpus flag default off;
    backfill correctness/idempotency/company-filter/dry-run.
  - **18 concurrency tests** (`test_concurrency.py`) — each worker thread gets its
    own Session; worker exceptions are collected and asserted empty; `pytest.ini`
    promotes `PytestUnhandledThreadExceptionWarning` to an **error**. Covers: a login
    holding the OLD password racing a password reset (the old password must never
    leave a usable session behind, and the new one must work afterwards); login vs
    logout-all; refresh vs logout-all and vs password reset; `token_version` moving by
    **exactly** the number of accepted calls (a `>= 1` assertion would also pass with
    a lost update); concurrent refresh minting at most one child; a **genuinely
    queued** stale-authority role change and member creation (each asserts it finished
    *after* the lock was released, so overlapping-but-unserialized threads cannot fake
    a pass); concurrent ownership transfer vs demotion leaving `company.owner_id` on a
    real owner; and the identity-map staleness that caused H2, isolated from any race.
    Five further tests exercise real PostgreSQL behaviour and **skip loudly** unless
    `EVIDENTIA_TEST_DATABASE_URL` is set: two for row locks, one proving two
    sessions concurrently enqueueing the same document version leave exactly one
    live ingestion job (the loser adopts the survivor via the partial unique
    index + savepoint recovery), and two proving two concurrent flag-on JSON
    creates racing for the last quota slot (document count / stored bytes)
    serialize on the company row lock — exactly one 201, a typed
    `document_quota_exceeded`/`storage_quota_exceeded` loser, and persisted
    rows/bytes within quota.
  - **33 rate-limit / hardening tests** (`test_rate_limit.py`): fixed-window
    correctness + expiry + Retry-After, independent budgets, `check_all` counting
    every rule (so tripping the IP budget cannot dodge the account budget); login
    brute force per account and per IP (password spraying); **throttling is not an
    existence oracle** (real and unknown emails throttle identically) and a correct
    password is still refused once throttled; **account limits survive IP
    rotation**; registration caps; **reset flooding capped per account across
    rotated IPs** (asserts the outbox stops at the cap); reset-token guessing;
    refresh abuse per token and per IP; generation caps per user, per tenant across
    members, and isolation of one tenant's budget from another's; anonymous
    generation is 401 (never consumes a real budget); **forged `X-Forwarded-For`**
    (ignored at 0 hops, prefix-injection defeated at 1 hop, correct entry at 2
    hops, garbage falls back to peer); body 413 and every field cap.
  - **27 adversarial exploit tests** (`test_exploits.py`) — one per review finding.
    **19 of 27 failed against the pre-fix code**; all pass now. Covers: production
    refusing weak/default/short JWT secrets; forged tokens missing `exp`/`iat`/`jti`
    and `alg:none`; an admin demoting the owner via member-creation upsert; 409 on an
    existing membership; ownership transfer to self; the last owner surviving
    concurrent demotions; concurrent refresh yielding at most one valid child;
    rate-limit store cardinality under a 50k unique-key flood; a blocked IP minting no
    secondary keys; fabricated generation metadata via `POST /api/reports`; and
    `X-Real-IP` never being trusted.
  - **59 startup/guard tests** (`test_startup_and_guards.py`) — production config
    fail-fast (weak JWT secret, proxy-without-BFF-secret, console email, wildcard
    CORS), the BFF guard rejecting direct backend access and using a constant-time
    comparison, access-token revocation via `token_version` on password reset and
    logout-all, and the **secret strength gates for BOTH `EVIDENTIA_BFF_SECRET`
    and `JWT_SECRET`**: the same 14 weak shapes rejected for each (including
    `abcd1234abcd1234abcd1234abcd1234`, which defeated both previous gates), the
    documented generation commands accepted (statistically, both encodings), the
    error messages carrying the command to fix it, development still running on
    the dev default, and a JWT forged with the published dev default refused once
    a real key is set.
  - The remaining 136 are unchanged (68 pipeline/eval + 68 auth/tenancy).
  - **68 pipeline/eval tests** (unchanged): the calibrated conservative router
    (`test_mode_router.py`), quality/grounding scoring, narrative scoring, the
    narrative gate, the grounding-repair relevance scorer, evidence-first
    generation / evidence-support scorer, the structural gate + item
    reconciliation, and the four match metrics.
  - **68 new auth/tenancy tests**:
    - `test_auth.py` (35) — bcrypt salting + the 72-byte truncation guard,
      register/login, forged/expired/wrong-key JWT rejection, refresh-token
      rotation and **family revocation on reuse**, logout + logout-all, email
      verification (single-use), password reset (single-use, revokes sessions,
      enforces strength), and non-enumerating responses.
    - `test_tenant_isolation.py` (18) — the IDOR suite. Bob (Globex) is fully
      authenticated and tries to read/delete/list/write Alice's (Acme) reports,
      documents, personas and members by id, by `company_id` query param, and by
      forged `X-Company-Id` header; plus tenant forgery via the request body.
      Also asserts no demo company is seeded and that an orphan user gets no tenant.
    - `test_rbac.py` (15) — the role hierarchy: member cannot delete or invite,
      admin cannot mint/demote an owner or self-promote, last owner cannot be
      removed or demoted, ownership transfer, and that a removed member loses
      data access immediately.

## Verified end-to-end (live backend + Next production build, 2026-07-13)

Driven against a running FastAPI backend (SQLite) + `next start`:

- `POST /api/auth/token` (the old password-less bypass) → **404, gone**.
- All of `/api/reports`, `/api/documents`, `/api/personas`, `/api/companies`,
  `/api/generate-workflow` → **401** when unauthenticated.
- Bob attacking Alice's report by id: GET **404**, DELETE **404**;
  `?company_id=<alice>` **404**; forged `X-Company-Id` **404**; his list stays
  empty; Alice's report is untouched.
- Bob POSTing a report with `companyId=<alice>` in the body → row lands in
  **Bob's** company (ownership comes from the session).
- `GET /api/companies` returns only the caller's own memberships (`['Globex']`).
- Refresh rotates; replaying the old token → 401 **and** burns the new one.
- Password reset + email verification confirmed via the console email hook:
  single-use, old password rejected, new password works.
- RBAC: member read 200 / delete 403 / invite 403 / self-promote 403;
  last-owner demotion 409; owner delete 200.
- Frontend BFF: register/login set **2 httpOnly cookies**; the response body
  carries **no token**; `/workspace` etc. 307-redirect to `/login?next=…` when
  anonymous; logout → `/api/auth/me` 401.
- **Public report schema unchanged**: the live report's 20 top-level keys match
  `EvidentiaReport` exactly (`git diff lib/types.ts` does not touch the
  interface); no tenant or internal provenance field leaks into the report.
- `next lint`, `tsc --noEmit`, `next build` all clean.

## Hardening smoke tests (live, 2026-07-14)

- Login: 5 wrong passwords → 6th is **429** *even though the source IP was rotated
  on every attempt*; `Retry-After: 726`; body `{"code":"rate_limited"}` with no
  limit/remaining/window. An unknown email throttles on exactly the same attempt.
- **Forged XFF**: 24 logins against 24 distinct accounts from one real IP with a
  rotating fake XFF prefix → blocked at exactly 20 (the per-IP cap held).
- Reset flooding: 5 requests across 5 rotated IPs → 3× 202 then 429, and the
  outbox contains **exactly 3** emails.
- Refresh: `200` (rotate) → `401` (reuse detected, family burned) → `429`.
- Generation: 10× 200 then 429 with Retry-After; anonymous flood is 401, never 429.
- Body: 600 KB → **413** with `Content-Length` **and** with `Transfer-Encoding:
  chunked`; normal bodies still reach the handler.
- **Backend down + real session → 503 `backend_unavailable`, no report in the
  body.** A forged cookie on the authenticated route → 401 (not a fallback report).
- Demo route: anonymous 200, `X-Evidentia-Demo: true`, **persists nothing** (the
  tenant's report count is unchanged), still works with the backend down, and is
  capped at 5/h per IP.

## Open concerns

- **Evidence/structural matching is lexical, not semantic** (support, repair, and
  structural scorers). Deterministic by design for now; next step is category/persona
  affinity refinement or embeddings (still no LLM call).
- **Auto never routes to full on the current corpus** (calibration verdict: full is
  Pareto-dominated, oracle gain only +0.12). This is intentional; full stays a manual
  mode. Re-run `scripts/calibrate_router.py` if the corpus/model changes — the
  conservative full-eligibility mechanism will start selecting full when the evidence
  justifies it.
- **Exact-citation match is 0.833** because a risk binds to the highest-signal
  section in its (correct) source document — `document`/`family` match are 1.0. The
  four split metrics now make this distinction explicit.
- **Auth requires the backend.** With `EVIDENTIA_BACKEND_URL` unset there is no
  login at all (503), and authenticated generation returns 503 rather than falling
  back. The keyless/backendless "just works" mode is gone by design.
- **Rate-limit counters are per-process and in-memory.** A second backend replica
  doubles every effective limit, and a restart clears all counters (an attacker who
  can trigger restarts regains budget). The store is now *bounded* (LRU eviction at
  `EVIDENTIA_RATE_LIMIT_MAX_KEYS`), so it cannot exhaust memory — but eviction under
  extreme cardinality can hand back budget. **Single-process backend is the supported
  shape**; for horizontal scale, implement `RateLimitStore` against Redis (the
  Protocol exists; no call site changes) or enforce limits at an API gateway.
- **The BFF single-flight refresh is per-process.** Two Next instances refreshing the
  same parent token concurrently can still trip family revocation. The backend's
  atomic rotation keeps this *safe* (only one child is ever minted); the cost is a
  spurious re-login, not a security hole.
- **PostgreSQL row-lock semantics: VERIFIED (2026-07-14)** against PostgreSQL 16.14
  via the opt-in profile
  (`EVIDENTIA_TEST_DATABASE_URL=postgresql+psycopg://… python -m pytest tests/test_concurrency.py`):
  15/15 tests green across 15 consecutive runs. The default (SQLite) run still only
  proves the application-side serialization, so re-run the profile after any change
  to the locking code and against the *managed* PostgreSQL version you actually
  deploy on, if it differs from 16.x.
- **The BFF-secret gate cannot prove a secret was randomly generated.** It enforces
  ≥32 decoded random bytes and rejects the recognizable weak shapes (known values,
  repeated blocks, sequential runs, word lists, low entropy, compressibility). A
  sufficiently clever hand-made string in the base64url alphabet could still pass.
  The guarantee comes from using the documented generation command; the gate is there
  to catch the operator who does not. False rejection of genuine output is ~1e-5 and
  fails closed with the command in the error message.
- **The demo limiter is per-Next-process.** N frontend instances multiply the demo
  budget by N. Global enforcement needs a shared store or an edge/gateway rule.
- **SQLite is not viable for a public beta.** Ephemeral container filesystems destroy
  all users and reports on redeploy. Use managed PostgreSQL; production refuses
  `EVIDENTIA_DB_ENABLED=false` but cannot detect an ephemeral disk for you.
- **The SMTP sender is unexercised against a real provider.** It is stdlib `smtplib`
  with STARTTLS and is covered by config/startup tests, but no live delivery test has
  been run — verify against your provider before relying on password reset.
- **`EVIDENTIA_BFF_SECRET` is a shared bearer secret, not mTLS.** It proves a request
  came through the BFF, which is what makes trusting `X-Forwarded-For` sound. It is
  defence in depth: the backend should still be network-isolated.
- **`EVIDENTIA_TRUSTED_PROXY_COUNT` must match the real topology.** Too low behind
  the BFF and every user shares one IP budget (a self-inflicted DoS); too high and
  a client can forge the trusted slot and rotate IP keys freely. Production logs a
  warning when it is 0. Per-account and per-user/tenant limits are unaffected either
  way — they are the defence against a genuinely distributed attacker, who does get
  a fresh per-IP budget per host.
- **No CAPTCHA/proof-of-work and no account lockout.** A distributed attacker with
  many IPs is still bounded by the per-account limit (5 logins / 15 min), which is
  low enough to make online guessing impractical but is not a lockout.
- **`report.company` is still the `PIPELINE_COMPANY` constant** ("Northreach
  Cloud") — the demo corpus's subject company, part of the public schema, not the
  tenant's name. Cosmetic; changing it would alter the report schema.
- **The pre-existing seeded demo company is not deleted by the migration**, only
  orphaned (no members ⇒ unreachable through the API). Deleting it would cascade
  to the reports that reference it. Drop it manually if the demo data is unwanted.
