# Evidentia — Customer Document Ingestion Architecture

_Design document. Nothing here is implemented. Status: **approved with
corrections**, 2026-07-14 — conditionally approved by the Staff Engineer
architecture review; the corrections are incorporated below and marked
`[REVIEW]`. Platform-level concepts (layers, CAD, domain modules, typed
contracts, provenance, learning loops) live in `PLATFORM_ARCHITECTURE.md`,
which is the architectural source of truth; where the two disagree, the
platform document wins._

Replaces the bundled demo corpus with real customer documents while preserving
Evidentia's deterministic-first, evidence-first architecture. This is **not** a
generic RAG design: the goal is to feed the existing grounded-claim pipeline
(evidence support → source-constrained generation → repair → gates) with
tenant-owned sections instead of the eight hardcoded demo documents.

Out of scope, by explicit constraint: the evaluation framework, authentication,
and the public `EvidentiaReport` schema are not redesigned. Everything below is
additive to them.

---

## 0. The single highest-risk architectural decision

**Where do claims come from for a corpus nobody at Evidentia has ever seen?**

Today a risk exists because a human wrote it into `RISK_TEMPLATES`
(`backend/app/agents/risk_analyzer.py`) with a hardcoded `sourceDocId`,
hand-picked `signals`/`phrases`, and a `resolvedIf` contradiction contract.
The evidence-support scorer then *verifies* the claim against selected
sections. Workflow steps likewise come from hand-written persona templates with
a `prefer` citation prefix. **None of this transfers to a customer corpus**:
there is no known `sourceDocId`, no hand-picked signal list, and no citation
prefix convention.

Two ways to close that gap:

- **(A) Retrieve-then-generate (RAG):** rank sections, let the LLM write risks
  and steps with citations, then repair/gate the output.
- **(B) Keep the claim contract; make claims data:** a deterministic,
  category-keyed **claim pattern library** produces candidate claims from
  section evidence; `sourceDocId` is *resolved by retrieval* instead of
  hardcoded; the existing evidence-support gate stays the sole grounding
  authority. In full mode, the LLM may additionally *propose* claims — but each
  proposal is compiled into the same claim contract and must pass the same
  deterministic gate before it exists.

**Recommendation: (B).** Justification — what breaks if (A) is chosen and later
proves wrong:

1. **`off` mode dies.** The product promise "generation works with no key"
   (deterministic mode, $0, ~1 ms) becomes an empty report on customer docs.
   That is not a degradation; it removes a documented mode.
2. **The structural gate loses its baseline.** `reconcile_and_gate` compares an
   LLM candidate against a deterministic analytical baseline. With RAG there is
   no baseline — the gate's "preserve strong deterministic items, accept only
   strictly-better" semantics have nothing to stand on, and the entire
   pass-3/pass-4 quality machinery becomes dead code.
3. **The calibration verdict inverts silently.** The benchmark showed full mode
   is Pareto-dominated *because* the deterministic baseline is strong. RAG makes
   every generation an LLM generation: cost floor jumps from $0/0.0078 to
   ~$0.03, latency from 5 s to 25 s, and the router has nothing to route.
4. **Hallucination containment weakens.** Today the LLM can only *refine* items
   that already passed evidence gating. Under RAG the LLM *originates* every
   analytical item, and repair/gates become the only defence instead of the
   second layer.

Rewriting from (A) back to (B) after launch means rebuilding the analytical
core (risk analyzer, workflow builder, gate wiring), re-authoring the benchmark
expectations, and re-calibrating — several weeks of rework plus a product-visible
quality regression in the interim. Rewriting from (B) toward more LLM
involvement, if pattern recall proves too low, is *incremental*: add the LLM
claim-proposer (already designed into full mode below) without touching the
contract, the gates, or the deterministic mode. (B) is the choice that keeps
both doors open. Decision details in §6-claims and §9.

A close second is section identity / citation stability (§4): rendered citation
ids are frozen into persisted reports forever, so the anchor scheme must be
chosen before the first customer report is generated. It is second, not first,
because reports are self-contained JSON snapshots — a wrong anchor scheme is a
painful re-ingestion and a mapping table, not a rewrite of the analytical core.

---

## 1. Ingestion pipeline — end to end

```
 browser ──multipart──▶ BFF /api/documents/upload ──▶ FastAPI /api/documents/upload
                                                            │ (auth + tenancy + quota + size caps,
                                                            │  magic-byte sniff, sha256, dedupe)
                                                            ▼
                                              documents + document_versions row
                                              (status=pending) + blob stored
                                                            │
                                                   ingestion job enqueued
                                                            ▼
                        ┌─────────────── ingestion worker (background, in-process v1) ─────────────┐
                        │ 1. EXTRACT    format parser → DocIR (block stream with heading hierarchy) │
                        │ 2. NORMALIZE  whitespace/unicode cleanup, table/list flattening,          │
                        │               omitted-content markers                                     │
                        │ 3. SECTIONIZE heading-based grouping, size bounds, split/merge            │
                        │ 4. ANCHOR     stable anchor ids + rendered citation ids + section hashes  │
                        │ 5. CLASSIFY   category, topics, keywords, market flags, persona affinity  │
                        │               (deterministic signature scoring — no LLM)                  │
                        │ 6. PERSIST    document_sections rows (immutable), version → ready         │
                        └───────────────────────────────────────────────────────────────────────────┘
                                                            │
                                                            ▼
                                    workspace picker ──▶ generation (SectionProvider)
```

Stage-by-stage:

1. **Accept.** New `POST /api/documents/upload` (multipart) beside the existing
   JSON `POST /api/documents` (which remains, now internally routed through the
   same pipeline as a pre-extracted TXT/MD source). Auth, tenancy, per-tenant
   quotas, and rate limits reuse the existing `deps.py` / `limits.py` patterns.
   Compute `sha256` while streaming to enforce the byte cap without buffering
   unbounded input (the `body_limit` middleware precedent). Detect format from
   **magic bytes**, not the extension. Duplicate handling per §11.
2. **Record.** Create/locate the `documents` row, create a `document_versions`
   row in `pending`, store the original bytes via the `BlobStore` seam (§3),
   enqueue an `ingestion_jobs` row. The API returns `202` with the document +
   version id + status; the UI polls the list endpoint (already fetched by
   `lib/uploads.ts`).
3. **Extract** (worker). Per-format parser (§2) emits a common intermediate
   representation, **DocIR**: an ordered stream of blocks
   `{kind: heading|paragraph|table|list|omitted, level?, text, meta}`. Parsers
   are the only format-aware code; everything downstream consumes DocIR.
4. **Normalize.** Unicode NFC, control-char stripping, whitespace collapse,
   hyphenation repair (PDF line-break artifacts), table → pipe-text, list →
   `-`-prefixed lines, images/charts → `omitted` markers (never invented text).
5. **Sectionize.** Group blocks under headings; enforce size bounds
   (§4); heading-less documents fall back to heuristic/paragraph chunking.
6. **Anchor + hash.** Stable `anchor_id` per section, rendered `citation_id`,
   `text_sha256` per section, manifest hash per version (§4).
7. **Classify.** Deterministic signature scoring (§6) fills `category`,
   `topics`, `keywords`, `market_flags`, `persona_affinity`.
8. **Persist + flip.** Write all sections in one transaction, set the version
   `ready`, and atomically swap `documents.current_version_id`. Generation only
   ever sees `ready` versions — a version is visible completely or not at all
   (same promise shape as "200 means persisted").

The worker is an in-process `ThreadPoolExecutor(1–2)` fed by the
`ingestion_jobs` table — consistent with the documented single-backend-instance
shape. A `JobQueue` Protocol (mirroring `RateLimitStore`) is the seam for
Redis/RQ when the backend scales out. Jobs are idempotent per stage and
restart-safe (§11). **[REVIEW] Job claims are tenant-fair, not pure FIFO**:
the claim query round-robins across tenants (e.g. `DISTINCT ON (company_id)` /
window function over queued jobs), so one tenant bulk-uploading 500 PDFs at
seconds each cannot starve every other tenant's single upload for an hour.
This is a noisy-neighbor problem *within* the supported single-instance shape,
so it ships with the worker (M2), not with scale-out.

## 2. Parsing, per format

All parsers emit DocIR. Library choices favour permissive licenses (a
commercial SaaS should not take AGPL deps like PyMuPDF into the core path) and
pure-Python installs (current image has no build toolchain).

| Format | Parser | Notes |
|---|---|---|
| Markdown | `markdown-it-py` token stream (CommonMark) | Replaces the regex-only `## `-scanner. All heading levels (`#`–`######`) become hierarchy; fenced code blocks kept verbatim as paragraph blocks; MD tables → table blocks; images → `omitted` marker with alt text preserved as a caption line. |
| TXT | built-in heuristics | Heading candidates: numbered lines (`3.`, `3.2`, `III.`), short ALL-CAPS lines, underlined (`====`/`----`) titles. If < 2 candidates, fall back to paragraph chunking (blank-line boundaries, packed to the size bounds in §4) with synthesized titles from the first sentence. |
| HTML | `selectolax` (fast, MIT) or `BeautifulSoup+lxml` | Strip `script/style/nav/header/footer/aside/form`; boilerplate suppression by link-density heuristic. `h1–h6` → hierarchy. `<table>` → pipe-text (cap rows, mark truncation). `<img>` → `omitted` + alt text. Inline formatting flattened to plain text. |
| DOCX | `python-docx` | Paragraph style `Heading 1–6` → hierarchy; outline-level fallback when styles are custom. Tables → pipe-text. Numbered/bulleted paragraphs → list blocks. Embedded images/OLE objects → `omitted`. DOCX is a zip: enforce decompressed-size and entry-count caps before parsing (zip-bomb defence, §12). Reject `.docm` (macros) at sniff time. |
| PDF | `pdfplumber` (MIT; text + tables) | Text-layer extraction with layout ordering; hyphenation repair; header/footer suppression (repeating first/last lines across pages). Headings: font-size/weight clustering when metadata exists, else TXT-style numbering heuristics. `pdfplumber` table extraction for ruled tables → pipe-text; unruled tables degrade to text (acceptable). Encrypted: try the empty user password, else fail `encrypted_unsupported`. Page cap (default 500) and object-count sanity checks. |

**OCR strategy: deliberately not in v1.** After extraction, compute text-layer
coverage (chars per page). Below a threshold (~50 chars/page average) the
version fails with `needs_ocr` and an honest UI message ("this looks like a
scanned document; OCR is not yet supported"). Rationale: OCR output is noisy,
and noisy excerpts poison the *evidence* a compliance product shows customers —
a wrong excerpt is worse than a clear refusal, the same philosophy as marking
`N/A` instead of the least-bad citation. When OCR ships (Tesseract in the
worker, or a hosted API), it is one more extractor behind the same DocIR
interface and a per-section `ocr: true` provenance flag; nothing downstream
changes.

**Unsupported content** (images, charts, embedded spreadsheets, forms) is never
silently dropped: the section gets `has_omitted_content = true` and an inline
`[content omitted: image "Q3 architecture diagram"]` marker so a human reading
the excerpt knows evidence may be incomplete. XLSX/PPTX/CSV are rejected with a
clear message in v1 (the demo "Pricing Sheet" being XLSX is demo fiction — its
content is a markdown file); they are future extractors, not parser edge cases.

## 3. Document model (database)

Additive Alembic migrations; the existing `documents` table is extended, not
replaced, and existing JSON-upload rows are backfilled (§14).

```
companies 1─n documents 1─n document_versions 1─n document_sections
                              │ 1─1
                              └──── document_blobs        (via BlobStore seam)
          1─n ingestion_jobs  (company_id, document_id, version_id)
reports.report_json  (snapshot — unchanged)  + reports.source_versions
                                             + reports.engine_versions  (new JSON columns, §5)
```

**`documents`** (extended)
- existing: `id, company_id FK, title, slug, type, category, content_text, metadata_json, created_at, updated_at`
- add: `source_type` (`upload` | `api` | future `connector:*`), `origin_uri`
  (nullable; connector seam), `original_filename`, `mime_type`,
  `content_sha256` (of the latest original), `size_bytes`,
  `citation_prefix` (3–5 uppercase chars, unique per tenant, §4),
  `current_version_id` (nullable FK), `status`
  (`empty|processing|ready|failed`), `deleted_at` (nullable — soft delete),
  `created_by` (user FK, nullable).
- `content_text` is retained for backfill/back-compat and deprecated after M1.

**`document_versions`** — immutable once `ready`
- `id, document_id FK, company_id (denormalized), version_no (1..n)`,
- `content_sha256` (original bytes), `extracted_sha256` (normalized text),
  `manifest_sha256` (ordered section anchors+hashes — cheap whole-version equality),
- `parser_name, parser_version` (re-ingestion trigger on parser upgrades),
- `status` (`pending|extracting|sectioning|classifying|ready|failed`),
  `error_code, error_detail`, `page_count, char_count, section_count`,
- `created_at, created_by`.

**`document_blobs`**
- `id, version_id FK, company_id, storage_key, byte_size, created_at`, plus the
  bytes themselves in v1 (Postgres `bytea` behind the seam).
- Accessed only through a **`BlobStore` Protocol** (`put/get/delete`) —
  DB-backed implementation now, S3-compatible later, zero call-site changes
  (the `RateLimitStore` precedent). Blobs are never served back for download in
  v1 (§12); they exist for re-ingestion after parser upgrades and support.

**`document_sections`** — immutable rows (see §4 for field semantics)
- identity: `id, company_id, document_id, version_id, anchor_id, citation_id, ordinal`
- structure: `depth, heading_path JSON, title`
- content: `text` (bounded), `excerpt` (bounded, derived), `text_sha256`,
  `char_count, has_tables, has_omitted_content, token_set JSON` (precomputed
  scoring tokens)
- classification: `category, topics JSON, keywords JSON, market_flags JSON,
  persona_affinity JSON, injection_flags JSON`
- `created_at`
- Uniqueness: `(version_id, anchor_id)` and `(version_id, ordinal)`.
  Tenant-scoped queries always filter `company_id` (denormalized deliberately:
  every repository lookup keeps the "impossible by construction" tenancy shape
  without joins).

**`ingestion_jobs`**
- `id, company_id, document_id, version_id, state, attempts, last_error,
  heartbeat_at, created_at, updated_at`. Worker requeues stale `running` rows
  at startup (§11).

**Versioning.** A new upload targeted at an existing document (explicit
"upload new version" in the UI, or the API called with a `documentId`) creates
`version_no = n+1`. `current_version_id` flips atomically only when the new
version is `ready`; a failed re-upload never degrades a working document.
Old versions and their sections are retained (reports may pin them, §8);
a retention policy (keep last N versions) is a later knob.

**Soft delete.** `deleted_at` on `documents` hides the document from listings,
the picker, and generation, but retains rows so existing reports' "view source"
resolution can say *why* a citation no longer resolves. Hard purge (compliance/
GDPR) is an explicit admin action that deletes blobs, sections, and versions —
with the documented caveat that persisted report snapshots still contain
excerpts, so a true right-to-erasure request must also delete or redact the
tenant's affected reports (surfaced in the purge UX, never silent).

**Tenant isolation.** Identical to the existing pattern: `company_id` on every
row, mandatory in every repository lookup, cross-tenant reads return 404-shape
absence. Sections inherit the document's tenancy and are only ever loaded
through the tenant-scoped provider (§9).

## 4. Section model — identity, citation ids, change detection

**Size bounds.** Target section text 200–4,000 chars. Oversized sections are
split at paragraph boundaries into parts (`anchor.p1, anchor.p2`, ordinal
preserved); undersized trailing fragments merge into the previous section.
`excerpt` is a bounded derivation (first ~1,200 normalized chars, cut at a
sentence boundary).

**[REVIEW] Corrected scoring input — full text, not excerpt.** The original
draft had every scorer (`evidence_support`, `citation_tools`,
`document_search`) consuming `sectionTitle + excerpt`. That blinds the
grounding gate to up to ~70% of a long section: evidence past char ~1,200 can
never support a claim, producing false `INSUFFICIENT_EVIDENCE` results
correlated with the customer's writing style and indistinguishable in
telemetry from genuine gaps (which would also poison the Stage-3 trigger
signal in §7). Corrected contract:

- **Deterministic scoring (evidence support, repair, candidate scoring)
  consumes the full bounded `text` via the precomputed `token_set`**, which is
  built from the full section text at ingest — so generation cost does not
  move (the bounds above keep every scorer input capped regardless of how
  customers write documents).
- **`excerpt` is a display and prompt-budget field only**: the library UI, the
  report's cited-section view, and the char-budgeted LLM evidence pack.

This lands with M4 (first customer generation), not later.

**Stable anchors — the citation identity scheme.** Requirements: (a) rendered
ids are frozen into immutable report snapshots, so they must stay meaningful;
(b) a section edited in place should keep its id across versions (so a
regenerated report cites "the same section"); (c) ids must be unique within the
tenant corpus at generation time; (d) ids appear as UI chips (`RES-14`) —
short and stable beats semantic.

Scheme:
- `documents.citation_prefix`: derived at creation from the title's significant
  initials/consonants (e.g. "Data Handling Policy" → `DHP`), tenant-unique with
  numeric suffixing on collision (`DHP2`). Immutable thereafter — the prefix is
  identity, not description. (Demo corpus prefixes SEC/RES/… already follow
  this convention, so report UX is unchanged.)
- `anchor_id`: derived from the **normalized heading path**, not the content:
  `slug-hash = base36(sha1(normalized_heading_path))[:5]`, with a deterministic
  ordinal suffix among same-heading duplicates. Content edits under an
  unchanged heading keep the anchor (requirement b). A renamed heading gets a
  new anchor — mitigated by **anchor inheritance**: during version diff, a new
  anchor whose `text_sha256` matches a disappeared anchor exactly (cheap pass),
  or whose token-set Jaccard similarity ≥ 0.8 (guarded pass), inherits the old
  `anchor_id`. Split sections inherit into `.p1`.
- `citation_id` (rendered) = `{prefix}-{anchor_id}` — e.g. `DHP-k3f9x`. Stable
  across versions for logically-same sections, unique per tenant, and shaped
  exactly like the demo ids the report UI, repair scorer, and PDF already
  handle (opaque strings throughout the pipeline; nothing parses their
  internals except the demo workflow builder's `prefer` prefix, which is being
  retired in §9).

**[REVIEW] The anchor scheme is a versioned identity algorithm.** Rendered
citation ids are frozen into immutable report snapshots forever, so the
algorithm is governed like a public schema (full spec:
`PLATFORM_ARCHITECTURE.md` §7):

- `anchor_algo_version` is stored on every `document_versions` row.
- **Constants are part of the version**: the 200–4,000 size bounds, the
  excerpt bound, `base36(sha1)[:5]`, the 0.8 Jaccard threshold, and the
  normalization rules. Changing any of them ⇒ a new algorithm version; **no
  in-place tuning of an existing version, ever**.
- **Deterministic tie-breaking** when multiple new sections compete to inherit
  one disappeared anchor (rename+split): (1) highest token-set Jaccard,
  (2) exact `text_sha256` match preferred over any similarity score,
  (3) nearest document order, (4) lowest candidate anchor id — exactly one
  inherits.
- **Golden fixture corpus in CI**: fixture documents + expected anchors for
  rename, edit, split, merge, duplicate headings, insertion before duplicates,
  rename+split, and size-boundary oscillation. The corpus is the algorithm's
  regression contract; this is an explicit M3 deliverable.
- A future algorithm version coexists with prior versions: persisted reports
  never re-resolve, old versions are never re-anchored in place, and
  cross-boundary inheritance runs over content (hashes/token sets), not
  algorithm internals.

**Hashes / change detection.**
- `text_sha256` per section: the change-detection unit.
- `manifest_sha256` per version (ordered `(anchor, text_sha256)` pairs):
  instant "did anything change at all".
- `documents.content_sha256`: byte-identical re-upload dedupe (§11).

## 5. Incremental updates (new version upload)

Parse the new upload **fully** — parsing is cheap relative to correctness, and
partial parses are how corpora drift. Incrementality applies to *derived* work:

1. Extract → sectionize → anchor the new version completely.
2. Diff against the previous version by anchor:
   - **unchanged** (same anchor, same `text_sha256`): copy the previous
     section's classification, token_set, and injection flags verbatim — no
     recompute. (Sections are per-version rows; "reuse" copies derived fields,
     not row identity. Content-addressed section sharing across versions was
     considered and rejected for v1: an M:N `version_sections` join buys
     storage — trivial at these sizes, §10 — at the cost of complicating every
     tenant-scoped query and the immutability story.)
   - **changed** (same anchor, new hash): re-classify that section only.
   - **new / removed**: classify new; removed simply don't exist in the new
     version. Anchor inheritance (§4) runs before this bucketing so renames
     don't masquerade as remove+add.
3. Flip `current_version_id` atomically when `ready`.

**Index invalidation is naturally scoped** because Stage-1 retrieval builds its
IDF over the *selected sections at generation time* (§7) — there is no global
index to invalidate. The only global artifact is the in-process report cache:
its key (`orchestrator._cache_key`) must gain the **version ids** of the
selected documents (today it hashes bare doc ids — a re-upload would serve a
stale cached report; this is a required day-one change, §9). **[REVIEW] The
cache must also become bounded (LRU eviction)**: `orchestrator._CACHE` is an
unbounded module-level dict whose key space becomes customer-controlled the
moment tenant selections and version ids enter it — the same defect class as
the rate-limit store fixed in hardening pass 2. Both cache changes land in M4.
Postgres FTS (Stage 2) updates row-wise on section insert — no rebuild.

**Report reproducibility across updates:**
- Persisted reports are full JSON snapshots — untouched by any re-upload, ever.
- New column `reports.source_versions` (JSON: `[{documentId, versionId,
  versionNo, parserVersion}]`) records exactly what a report was generated
  against. This is additive metadata in the DB row, **not** in the public
  `EvidentiaReport` schema.
- **[REVIEW] Document versions alone are insufficient for reproducibility** —
  the output is also a function of the analyzer. A second additive column,
  `reports.engine_versions` (JSON), records: engine release, enabled module
  ids + versions, claim-pattern library versions, signature-pack versions,
  taxonomy versions, threshold-policy version, anchor algorithm version,
  benchmark version, retrieval strategy/version, tenant glossary version, and
  LLM provider/model/prompt version when used. This is what makes "why did
  this report change?" diffable (documents vs parser vs patterns vs thresholds
  vs model — see `PLATFORM_ARCHITECTURE.md` §6).
- **[REVIEW] Both provenance columns land at M4, the first customer-report
  milestone — not at the versioning-UX milestone (M8).** Reports generated
  without provenance can never be repaired retroactively. (The original draft
  scheduled `source_versions` at M8 while claiming the data was "recorded from
  day one"; resolved in favor of day one.)
- Re-running deterministically against the same pinned versions **and pinned
  engine versions** reproduces the same analytical output (LLM narrative
  varies by design; `off` mode is exact). Generation always uses
  `current_version_id` unless a pinned re-run is explicitly requested (a later
  UX feature that costs nothing now because the data is recorded from day one).

## 6. Classification without LLM calls

All classification is deterministic **signature scoring** — the exact idiom the
codebase already trusts (`evidence_support.score_support`,
`citation_tools.score_section`): weighted keyword/phrase lists, explainable
matches, thresholds, tests.

**[REVIEW] Signatures are module data, and classification is versioned.**
Signatures, taxonomy labels, topics, facets ("market flags"), and persona
mappings live in **namespaced, versioned domain-module data packs**
(`modules/compliance/…`, see `PLATFORM_ARCHITECTURE.md` §3), not engine
constants — the engine executes signatures but never branches on a taxonomy
label (lint-enforced from M3). Every section records the
`classifier_version` / `signature_pack_version` that classified it, so a
signature upgrade has a defined re-classification trigger — the exact analog
of `parser_version` re-ingestion.

- **Category.** A signature per category — start with the eight the pipeline
  already understands (`Security, Compliance, API, Reliability, Deployment,
  Operations, Pricing, Enablement`) plus `General` as the below-threshold
  fallback. Score = weighted hits over heading paths (×2, same title-weighting
  precedent as repair) + body, phrase bonuses; document category = argmax over
  section-length-weighted section scores. Keeping the demo taxonomy is
  deliberate: persona `_CRITICAL_CATEGORIES`, evidence-gap risks, and category
  affinity scoring all key on these labels — a new taxonomy would ripple
  through the analytical layer for no customer value. **[REVIEW]** The
  taxonomy itself, and the `_CRITICAL_CATEGORIES`-style mappings that key on
  it, become versioned data owned by the Compliance module (Module #1) in
  M3 — the labels stay, their ownership moves out of engine code.
- **Topics.** Curated topic taxonomy (~40–60 labels, each a signature list,
  e.g. `Encryption`, `Rate limits`, `Escalation`, `Data residency`) matched per
  section, aggregated per document. Bounded vocabulary keeps topics usable as
  UI facets and as claim-pattern triggers (§9) — free-text topics would be
  noise.
- **Keywords.** Top-N TF-IDF terms per document against the tenant corpus
  (IDF machinery exists in `citation_tools.build_idf`), generic terms
  downweighted by the existing `GENERIC_TERMS` list. Display + search boost
  only; nothing analytical depends on them.
- **Market relevance.** Signature lists per market/regulatory regime (region
  names, `GDPR`, `HIPAA`, residency vocabulary…) → `market_flags`. Reuses
  `HIGH_COMPLIANCE_MARKETS` semantics so `market_is_regulated` and
  `marketSensitive` claim logic work unchanged.
- **Persona relevance.** Run the existing `rank_sections_for_persona` needles
  (each profile's `relevantTopics + priorities + riskFocus`) over the
  document's sections at ingest; store normalized per-persona scores as
  `persona_affinity`. Powers the picker's "relevant to: Compliance Officer"
  facet and pre-sorting — generation-time ranking still computes live (cheap,
  and correct for custom personas).

An optional, flagged, *single* cheap LLM call per document (title cleanup +
one-line description for the library UI) may come later; it is cosmetic and
never feeds the analytical pipeline. Correctness never depends on an LLM call —
the deterministic-first invariant extends to ingestion.

## 7. Search architecture — three stages, each with an explicit trigger

**Stage 1 — scoped lexical scoring (ships with MVP).** No index at all.
Generation already operates on the *selected* documents (≤ 50, request-capped),
so retrieval = load `ready` sections for the selection (one indexed query) and
run the existing scorers over them. IDF is built per generation over selected
sections — exactly what `repair_grounding` does today. Precomputed
`token_set` per section removes the tokenization cost. At the worst
allowed case (~50 docs × ~50 sections × ~40 claim patterns ≈ 100k cheap set
intersections) this stays well under typical LLM-call latency — measured in
tens of milliseconds, not seconds. **Sufficient while: selection-scoped
generation is the only consumer of section content.**

**Stage 2 — Postgres FTS / BM25-shaped retrieval.** Trigger, whichever first:
(a) the document picker needs a *search box* over a corpus too large to browse
(hundreds+ documents — searching is a UI need Stage 1 never serves, since
Stage 1 only ranks already-selected docs); (b) tenants routinely select enough
sections that Python-side scoring shows up in generation latency (~thousands of
sections); (c) claim patterns need corpus-wide candidate *pre-filtering* ("find
the 30 sections that could possibly support this pattern, then let
`evidence_support` decide"). Implementation: a generated `tsvector` column +
GIN index on `document_sections`, `ts_rank_cd` ranking, always
`company_id`-filtered. Zero new infrastructure (managed Postgres is already
required). FTS is **recall machinery only** — the deterministic
evidence-support scorer remains the sole grounding authority; FTS never decides
that evidence supports a claim, it only shortlists candidates for the scorer.

**Stage 3 — optional semantic retrieval (pgvector).** Trigger: *measured*
synonymy failure — the telemetry Evidentia already emits makes this concrete:
persistently high `insufficientEvidenceItemsFinal` / `unsupportedDropped` on
real corpora **where a human can point at a supporting section the lexical
pass missed** (i.e., customer vocabulary diverges from signature vocabulary —
"SEV1 paging rotation" vs "on-call escalation"). Implementation:
`section_embeddings (section_id, model_version, vector)` via pgvector; embed at
ingest (per-section, incremental by hash — §5's diff means only changed
sections re-embed). Role: **candidate generator only**, merged with FTS
shortlists ahead of the deterministic gate. The grounding/hallucination
properties are unchanged because acceptance still requires lexical signal
support — embeddings widen what the gate gets to *look at*, never what it
*accepts*. This is the entire reason the design does not jump to embeddings:
in an evidence-first pipeline retrieval is a recall problem, and recall
upgrades are safe, incremental, and justified by telemetry — whereas
building the pipeline *on* embeddings would make grounding itself
non-explainable.

A `CandidateRetriever` Protocol (input: claim profile + section scope; output:
scored candidate sections) wraps whichever stages are active, so the risk
analyzer never knows which stage produced its candidates.

## 8. Citation architecture — stability, deletion, reproducibility

- **Stability across versions** comes from §4: anchors survive content edits
  and (via inheritance) most renames; the rendered `citation_id` in a new
  report therefore matches the previous report's id for the logically-same
  section. Reports never mutate — stability is about *cross-report coherence*
  ("RES-k3f9x means the same clause in last month's and today's report"), not
  about editing history.
- **Persisted reports are already reproducible** — `report_json` embeds every
  excerpt, citation, and metric. No ingestion event (re-upload, delete, purge)
  changes a stored report. This existing property is load-bearing; the design
  adds provenance (`reports.source_versions`) rather than resolution
  dependencies.
- **Resolution, not embedding.** When the report UI wants to deep-link a
  citation chip to the library ("view source"), it resolves
  `(company_id, citationId)` against the *pinned version* from
  `source_versions`, falling back to the current version. Outcomes:
  - resolves in current version → link, live.
  - resolves only in the pinned (older) version → link + "this section has
    since changed" badge.
  - document soft-deleted → "source removed from library" state (row still
    exists to say so).
  - hard-purged → generic "source no longer available"; the report still
    renders fully from its snapshot.
  Rendering never depends on resolution succeeding — deletion can never break
  a report.
- **`N/A` semantics unchanged.** `INSUFFICIENT_EVIDENCE` remains the honest
  sentinel; nothing in ingestion invents citations, and repair still refuses
  the least-bad candidate below threshold.

## 9. Integration — exactly what changes in the existing pipeline

```
TODAY                                          TOMORROW
upload (JSON text) → documents row (inert)     upload (multipart|JSON) → versions → sections (ready)
generate:                                       generate:
  document_reader(ids)                            SectionProvider.load(ctx, ids)
    └ hardcoded DOCUMENTS + bundled .md             ├ TenantCorpusProvider  → document_sections (DB)
  risk_analyzer(RISK_TEMPLATES)                     └ DemoCorpusProvider    → existing document_reader
  workflow_builder(prefer=prefix)                 risk_analyzer(ClaimSource)
  …                                                 ├ DemoTemplates    → existing RISK_TEMPLATES
                                                    └ PatternLibrary   → category/topic-keyed patterns,
                                                                          sourceDoc resolved by retrieval
                                                  workflow_builder(prefer=category)
                                                  …everything else unchanged…
```

**[REVIEW] The pipeline currency becomes a typed, versioned contract.** The
section dict below is the platform's most load-bearing interface; it is
formalized in M1 as **`SectionRecord v1`** (see `PLATFORM_ARCHITECTURE.md` §5),
of which the existing dict shape
(`documentId, source, sectionTitle, excerpt, category, citationId`) is a
strict projection — existing consumers keep receiving exactly what they
receive today. `ClaimSpec v1` likewise types the claim-pattern contract before
M5 authors patterns against it.

Component-by-component (this is the complete change surface):

| Component | Change |
|---|---|
| `agents/document_reader.py` | Becomes the `DemoCorpusProvider` implementation of a new **`SectionProvider`** interface (`load(selection) -> (documents, sections)` returning the exact dict shapes it returns today). Zero behavioral change for demo. |
| **new** `agents/section_provider.py` + `repositories/sections.py` | `TenantCorpusProvider`: tenant-scoped load of `ready` sections for selected ids; emits the same section dict (`documentId, source, sectionTitle, excerpt, category, citationId`) — the pipeline's currency is unchanged, which is what makes the rest of this table short. |
| `agents/orchestrator.py` | `run_pipeline(_ex)` accepts an injected provider/sections (default: demo — the TS demo route and every existing test keep passing). **Cache key gains version ids** (stale-cache fix, §5). `_derive_id` works unchanged on opaque ids. |
| `main.py::generate_workflow` | Resolves selection ownership: selected ids are looked up tenant-scoped; if any resolve to tenant documents, tenant mode (foreign/unknown ids silently dropped — same absence semantics as tenancy); if none, demo corpus (current behavior, preserves the showcase flow). Passes the provider + `db` into the pipeline. |
| `agents/risk_analyzer.py` | Templates become a **`ClaimSource`** input. Demo path: existing `RISK_TEMPLATES`, verbatim. Tenant path: the **claim pattern library** — category/topic-keyed claim patterns (data files) shaped exactly like today's templates minus the hardcoded `sourceDocId`; each pattern instead declares `sourceCategory`/`sourceTopics`, and binding runs pattern → candidate sections (via `CandidateRetriever`) → `score_support` gate → grounded claim with the *resolved* section's document as owner. Text fields become templates with slots (market, matched section title) so emitted risks read specifically, not generically. The scorer, thresholds, drop-don't-fill, evidence-gap fallback, audit records: all unchanged. |
| `tools/evidence_support.py` | One semantic change: `owns` becomes "section belongs to the claim's *resolved* source document" (binding-time property) rather than a hardcoded id equality. Weights, gates, tests preserved; demo path identical because resolution is the identity function there. |
| `agents/workflow_builder.py` | `prefer` changes from citation-prefix to **category** (`"INC"` → `"Operations"` etc. for the demo mapping). The existing topical-match fallback already generalizes. Step template *text* gets the same slot treatment as risk patterns. |
| `agents/citation_binder.py` | `_WHY_BY_ID` demo map kept for demo ids; the generic fallback sentence already handles tenant sections. No structural change. |
| `agents/persona_mapper.py` | Unchanged structurally. The custom-persona description's hardcoded "Northreach Cloud's documentation" becomes the tenant corpus reference. (Related but separate decision: `report.company` — the *value* can become the tenant's company name without touching the schema *shape*; flagged for product sign-off in §14.) |
| `metrics_agent`, `narrative_gate`, `structural_gate`, `citation_tools`, `document_search`, `mode_router` | **No changes.** They consume sections/claims generically. Verified against source; re-verify in the M4 integration PR. |
| `api/documents.py` | Add `POST /upload` (multipart), `POST /{id}/versions`, status/version fields in serialization (additive), soft-delete semantics on DELETE. Existing JSON create routed through the ingestion pipeline as a TXT source. |
| BFF (`app/api/documents/*`) | Multipart passthrough with the existing body-cap pattern (raised for this route only); list proxy unchanged. |
| Frontend | Workspace picker lists tenant documents (status-aware, demo corpus clearly labeled as "Sample corpus" fallback); documents page shows ingestion status/errors and "upload new version". |
| Eval framework | **Untouched**, per constraint. The demo corpus remains the benchmark bed. A *new, additive* scenario set for pattern-library behavior lands as `BENCHMARK_VERSION = v2` (dataset versioning already exists for exactly this). |
| `GenerateRequest` / report schema | **Unchanged.** Ids were already opaque, length-capped strings; the report is already provider-agnostic. |

## 10. Performance

- **Complexity.** Ingestion is O(document size) per stage, off the request
  path. Generation stays O(selected sections × claim patterns) with
  precomputed token sets — at the request-capped worst case (~2,500 sections),
  tens of milliseconds against a 5–25 s LLM budget; profiled, not assumed, in
  M4. Version diff is O(sections) hash comparison.
- **Storage growth.** Text ~1.2× extracted size with JSON overhead: 1,000 docs
  × 100 KB ≈ 120 MB of sections — negligible. Originals dominate: 1,000 PDFs ×
  2–5 MB ≈ 2–5 GB — fine in Postgres for the first customers, and the
  `BlobStore` seam moves originals to object storage without a call-site
  change when it isn't. Versions multiply text, not blobs-per-edit; a
  keep-last-N retention knob exists in the schema from day one.
- **Caching.** Report cache: version-aware key (§5). Section loads: one
  indexed query per generation; per-version section lists are immutable and
  trivially memoizable in-process if measurements ever justify it. IDF/token
  sets: precomputed at ingest.
- **Background jobs.** In-process worker, 1–2 threads (parsing is CPU-light at
  these sizes; PDFs are the ceiling at ~seconds each). The job table gives
  durability, retry, and observability (states + timings) from day one; the
  `JobQueue` Protocol is the scale-out seam, consistent with the single-
  instance backend stance.
- **Large documents.** Hard caps, enforced pre-parse where possible: upload 25
  MB, extracted text 1M chars (beyond → fail with `too_large`, honest, not
  silent truncation), 500 PDF pages, section splitting keeps every scorer
  input bounded regardless of input shape.
- **Thousands of documents.** Listing pagination (additive API params), picker
  search via Stage-2 FTS, per-tenant quotas (documents count + total bytes) as
  both an abuse bound and a future plan-tier lever. Generation cost is bounded
  by the *selection* cap, not corpus size — corpus growth affects browse/search
  only, which is exactly what FTS is for.

## 11. Failure handling

Every failure is a **typed terminal state on the version** (`error_code` +
user-safe message), visible in the documents UI — never a silent empty corpus.
The original blob is always retained on failure for support and for free
re-ingestion after parser fixes.

| Failure | Behavior |
|---|---|
| Corrupted / unparseable file | Parser exception → `parse_failed`. Document stays on its previous `ready` version if one exists (a bad re-upload never breaks a working document). |
| Huge file | Rejected pre-parse at the byte cap (streamed count, `Content-Length` not trusted — the `body_limit` precedent); oversized *extracted* text → `too_large`. |
| Encrypted PDF | Empty-password attempt, else `encrypted_unsupported` with a "remove the password and re-upload" message. |
| Scanned / no text layer | Coverage heuristic → `needs_ocr` (§2). Explicit, honest, retryable when OCR ships. |
| Zip bomb (DOCX) | Decompressed-size and entry-count caps before parse → `invalid_file`. |
| Duplicate upload | Same `content_sha256`, same tenant: as a *new document* → 200 returning the existing document (`duplicateOf` in the response, UI says "already in your library"); as a *new version* of a different document → allowed (legitimate copy). Identical bytes re-uploaded as a new version of the same document → no-op returning the existing version. |
| Interrupted ingestion (crash/restart) | Job states + `heartbeat_at`; startup requeues stale `running` jobs (the init-time hook exists). Stages are idempotent: sections are written in one transaction keyed by `(version_id)`, so a re-run either finds the version already `ready` or rebuilds cleanly; a version is never partially visible. |
| Repeated failure | `attempts` cap (3) → terminal `failed`; surfaced in UI and telemetry, never an infinite retry loop. **[REVIEW] `attempts` increments at claim time, not after a handled failure** — a poison file that kills the worker process outright must still hit the cap instead of being requeued forever by the startup sweep. |
| Crash between blob write and DB commit | **[REVIEW]** Explicit write order: version row (`pending`) → `BlobStore.put` → row references the blob → work proceeds. A crash between steps leaves an inert pending row or an orphaned blob, never a version claiming bytes that don't exist. A periodic **orphaned-blob reconciliation** sweep deletes blobs unreferenced past a grace window — designed now because it becomes acute when `BlobStore` moves to object storage. |

## 12. Security

- **Upload limits.** Per-file byte cap; per-tenant quotas (count + bytes);
  upload rate limits per user and per tenant added to the existing table in
  `core/ratelimit.py` / `api/limits.py` (same fixed-window machinery, counted
  before any parsing work).
- **Content validation.** Magic-byte sniffing decides format (extensions are
  hints only); strict allowlist `pdf|docx|md|html|txt`; explicit rejection of
  macro-enabled formats (`.docm`, `.dotm`), SVG (script-bearing), and archives.
  DOCX zip caps per §11. Parsers only *read* — no renderer, no JS engine, no
  external fetches (HTML parsing must never dereference remote resources).
- **Virus scanning.** v1 posture: blobs are never executed and never served
  back for download (no download endpoint exists), and parsing happens in
  pure-Python readers — the malware risk surface is parser exploits, mitigated
  by the caps above and pinned parser versions. The `BlobStore.put` path is the
  designated scanning hook: when a download/redistribution feature or
  connectors arrive, ClamAV (sidecar) or a hosted scanner slots in there as a
  pre-commit check, quarantining to a `blocked` version state. Documented as a
  deliberate deferral, not an omission.
- **Rendering safety.** Extracted text and excerpts are always rendered as
  text (React auto-escaping; the print page must never `dangerouslySetInnerHTML`
  an excerpt — add a test in M4). Excerpts entering LLM prompts get **prompt-
  injection screening at ingest**: deterministic signature flags
  (`injection_flags`: "ignore previous instructions", role-marker patterns,
  jailbreak vocabulary) that (a) surface as a document warning, and (b) are
  stripped/neutralized in evidence-pack text. Defence in depth on top of the
  existing structure: the deterministic baseline is immune by construction, and
  the narrative/structural gates already reject regressions — an injected
  instruction can waste one LLM call, not fabricate accepted evidence.
- **Tenant isolation.** §3's denormalized `company_id` + mandatory tenant-scoped
  repository lookups; selection resolution silently drops ids the tenant does
  not own (absence-shaped, consistent with the 404-not-403 doctrine); the demo
  corpus is read-only shared reference and never mixes with tenant sections in
  one generation.
- **No new secrets, no new trust boundaries.** Ingestion runs inside the
  existing backend; the BFF guard, body caps, and rate-limit posture carry over
  unchanged.

## 13. Future compatibility

The two seams that make later additions cheap, both established in v1:

1. **`RawDocument` in** — ingestion accepts `(bytes, declared_mime, origin
   metadata)` and doesn't care who produced it. Connectors (SharePoint, Google
   Drive, OneDrive, Confluence, GitHub, Slack) are *fetch-and-sync* layers that
   emit RawDocuments plus change events (external edit → new version through
   the §5 path, which is why version diff/anchor inheritance is built now).
   Their state (`connector_accounts`, sync cursors, external refs) is additive
   tables; `documents.source_type/origin_uri` already reserve the linkage.
   Slack/GitHub content (threads, README trees) maps to documents-with-sections
   the same way — the section model does not assume "file".
2. **`CandidateRetriever` out** — §7's staged retrieval means embeddings and a
   vector store are a new retriever implementation plus a `section_embeddings`
   table (pgvector first; a dedicated vector DB only if pgvector's limits are
   *measured*). Sections are already the embedding unit, hashes already give
   incremental embedding, and the deterministic gate already bounds what
   retrieval can do — so the semantic upgrade is contained by construction.

Also inherited free: per-section `parser_version` re-ingestion (parser
upgrades), OCR as another extractor, XLSX/PPTX as new parsers, and plan-tier
quotas on the ingestion limits.

## 14. Migration strategy — demo corpus to customer documents

Principles: the demo never breaks, every step is additive, and one flag rolls
the whole feature back.

1. **Feature flag** `EVIDENTIA_TENANT_CORPUS_ENABLED` (default off). Off =
   today's behavior, byte for byte. All schema migrations land before the flag
   ever turns on (additive columns/tables only — no destructive migration in
   this entire plan).
2. **The demo corpus keeps three jobs, untouched:** the public
   `/api/demo/generate-workflow` route (bundled TS pipeline — completely
   outside this design); the benchmark/eval bed (constraint: unchanged); and
   the **empty-tenant experience** — a new tenant with no `ready` documents
   sees the clearly-labeled "Sample corpus" and can generate showcase reports
   immediately (the existing `api/documents.py` fallback already implements
   the listing half of this).
3. **Backfill:** existing tenant `documents` rows (JSON `content_text`
   uploads) get a `version 1` synthesized and run through sectionization +
   classification by an idempotent management command. No data loss; the old
   rows simply become real.
4. **Selection semantics:** tenant ids and demo ids never mix in one
   generation (one report = one corpus = one coherent `company` line). Tenant
   docs win when present in the selection; pure-demo selections keep working
   forever.
5. **Rollout:** internal tenant → design-partner tenants (flag per env) →
   default-on. Reports generated during rollout are snapshots — nothing to
   migrate back on rollback; turning the flag off only returns the picker to
   the sample corpus.
6. **Product sign-off item:** `report.company` currently renders the demo
   constant ("Northreach Cloud"). For tenant-corpus reports it should carry the
   tenant's company name — a *value* change within the existing schema shape,
   but it alters visible output, so it ships behind the same flag with an
   explicit decision recorded in `DECISIONS.md`.

## 15. Roadmap — milestones sized for individual PRs

Effort assumes one senior engineer, includes tests (the repo's bar: failing
test first for invariants). Value column = what a customer can newly do.

**[REVIEW]** Milestone **entry criteria** (gates before M1, M3, M4 and M5
merge) are binding and defined in `PLATFORM_ARCHITECTURE.md` §12; the table
below incorporates the review's corrections: provenance moved from M8 to M4,
M5 split into M5a/M5b, and the M4 correctness items (full-text scoring,
bounded cache, tenant-fair jobs) made explicit deliverables.

| # | Milestone | Goal | Effort | Depends on | Risk | Customer value |
|---|---|---|---|---|---|---|
| M1 | **Schema + seams** | `document_versions`, `document_sections`, `document_blobs`, `ingestion_jobs` migrations; `BlobStore` + `SectionProvider` + `JobQueue` Protocols; backfill command; flag plumbing | 3–4 d | — | Low — additive only | None yet (foundation) |
| M2 | **Upload + ingestion spine (MD/TXT)** | Multipart endpoint, sniffing, caps, dedupe, quotas, rate limits; job worker + state machine; MD (`markdown-it-py`) + TXT parsers → DocIR → sectionizer; status in documents UI | 1 wk | M1 | Med — worker restart-safety needs care (§11 tests) | Upload real MD/TXT docs, see them parsed into cited sections in the library |
| M3 | **Anchors + classification** | Anchor scheme + inheritance + hashes; citation prefixes; category/topic/keyword/market/persona signature classifiers + data files; injection flags | 1 wk | M2 | Med — anchor scheme is frozen-forever (§0 runner-up); review it like a schema change | Library shows real categories/topics; docs become selectable evidence |
| M4 | **Pipeline integration + full provenance** | `TenantCorpusProvider`; orchestrator injection + **version-aware, LRU-bounded cache**; selection resolution in `main.py`; workflow `prefer`→category; binder/persona text generalization; workspace picker lists tenant docs; excerpt-escaping test; **`reports.source_versions` + `reports.engine_versions` (§5)**; **full-text deterministic scoring (§4)**; tenant-fair job claims + claim-time attempts verified (M2 items re-checked here); `report.company` = tenant name behind the flag (decision in `DECISIONS.md`) | 1.5–2 wk | M3 | Med — the change surface table in §9 is the review checklist; every existing test must stay green | **First real generation on customer documents** (workflow steps + citations grounded in their docs; risks still sparse) — with complete, permanent provenance from the first report |
| M5a | **Claim-engine plumbing (bounded)** | `ClaimSource` in risk analyzer; `owns`-by-resolution in evidence support; declarative pattern schema + loader + validation; typed matcher primitives; positive/negative fixture harness in CI; per-pattern metrics (fire/bind/gate-pass/N-A rates); **feedback intake: `item_feedback`, `citation_feedback`, `retrieval_misses`** (the Stage-3 sensor); benchmark scenario set v2 (additive) | 1.5–2 wk | M4 | Med — bounded engineering; the gate already refuses weak bindings, so bad patterns produce `N/A`s, not hallucinations | The machinery that makes pattern quality observable and iterable |
| M5b | **Pattern authoring (ongoing)** | Category/topic-keyed claim patterns (gap, contradiction, staleness, unsupported-claim families) with slot-templated text and fixtures, iterated on design-partner corpora and feedback telemetry | **ongoing — content work, not a fixed task** | M5a | **High — this is §0.** Silent low recall (thin reports) is the dominant failure mode; the M5a telemetry is what catches it at design-partner time | Reports on customer docs carry a real, grounded risk register — the core product promise |
| M6 | **HTML + DOCX parsers** | Two more DocIR extractors + format-specific caps/tests | 1 wk | M2 | Low — contained behind DocIR | Most business documentation formats accepted |
| M7 | **PDF (text-layer)** | `pdfplumber` extractor, heading heuristics, header/footer suppression, encrypted/scanned detection, failure taxonomy | 1–1.5 wk | M2 | Med — PDF heading quality varies; §4 fallback chunking bounds the damage | The single most-requested format works, with honest failures |
| M8 | **Versioning UX** | "Upload new version", diff reuse (§5), "view source"/"section changed" resolution states (provenance itself already recorded since M4) | 1 wk | M4 | Low | Docs evolve without breaking anything; the UI surfaces what reports were generated from |
| M9 | **Stage-2 search** | `tsvector` + GIN on sections; picker search; candidate pre-filtering behind `CandidateRetriever` | 3–4 d | M4 | Low | Hundreds+ docs stay navigable; pattern recall improves |
| — | Later, trigger-driven | OCR (§2), connectors (§13), embeddings (§7 Stage 3), XLSX/PPTX, retention/purge tooling | — | above | — | — |

Sequencing notes: M2–M3 can overlap with M4's provider work after M1; M6/M7
are parallel to M5a/M5b. A design-partner can be onboarded after **M4** (real
docs, grounded workflow, sparse risks) and gets the full promise as **M5b**
patterns mature — roughly 4–5 weeks to first value; the complete-v1 estimate
covers M5a's machinery, while M5b is paced by design-partner feedback rather
than a calendar.

**[REVIEW]** Two further roadmap notes from the review: (a) the **renderer
track** (editable DOCX → polished PDF → canonical JSON/API → HTML/interactive;
then PPTX/Excel/push integrations) runs independently after M4 against report
snapshots — see `PLATFORM_ARCHITECTURE.md` §2.3 and §12; (b) **debt watch**:
`documents.content_text` (deprecated after M1) needs an explicit removal
milestone once backfill is verified, or it lives forever; and the M9
`tsvector` column addition rewrites a by-then-large sections table — decide
early-nullable-column vs. maintenance window at M9 entry.

---

## Appendix — verified current-state facts this design builds on

- Section dict `{documentId, source, sectionTitle, excerpt, category,
  citationId}` is the pipeline-wide currency (`document_reader.py`, consumed by
  every scorer/gate/binder) — preserving it is what keeps §9's change table small.
- `RISK_TEMPLATES` hardcode demo `sourceDocId`/signals; workflow templates
  hardcode `prefer` prefixes; `_WHY_BY_ID` hardcodes demo citation ids.
- Reports are full-JSON snapshots (`reports.report_json`) — stored-report
  reproducibility already holds.
- `documents` table exists (tenant-scoped, JSON metadata, `content_text` ≤
  200k chars); upload path is client-side text extraction → JSON POST.
- Report cache key omits any version notion (`orchestrator._cache_key`) —
  must become version-aware the moment documents can change.
- `GenerateRequest.selectedDocumentIds`: ≤ 50 opaque ids, ≤ 200 chars each.
- Retrieval/repair/support scoring is per-generation over selected sections
  (IDF built on the fly) — no global index exists to invalidate.
- Single-backend-instance, in-process-worker posture is the documented
  supported shape; `RateLimitStore` establishes the Protocol-seam precedent.
