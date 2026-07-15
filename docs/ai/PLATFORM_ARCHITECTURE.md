# Evidentia — Platform Architecture (Constitution)

_Architectural source of truth. Status: **approved**, 2026-07-14, consolidating the
ingestion design (`DOCUMENT_INGESTION_ARCHITECTURE.md`) and the Staff Engineer
architecture review. Amend only when implementation reveals a concrete
contradiction; record every amendment in `DECISIONS.md`._

Evidentia is a **domain-independent evidence reasoning platform**, not a
compliance tool with an ingestion feature. The product vision this document
serves:

```
Any organization provides documents or connected knowledge sources
        ↓
Evidentia ingests and structures the source material
        ↓
A domain-independent evidence engine retrieves and validates evidence
        ↓
Versioned domain modules propose claims, analyses and recommendations
        ↓
A canonical analysis representation is produced
        ↓
Independent renderers generate professional deliverables
(DOCX, PDF, PowerPoint, Excel, HTML, Markdown, JSON/API,
 dashboards, Notion, Confluence, Jira, ServiceNow, …)
```

The initial product focuses on professional reports — editable DOCX and
polished PDF first — but **neither the reasoning engine nor the canonical model
may depend on any output format.**

## Settled foundations (not to be relitigated)

These decisions are accepted, recorded in `DECISIONS.md`, and are the premises
of everything below:

1. **Deterministic-first**, not generic retrieve-then-generate RAG.
2. **Evidence-first claim acceptance** — claims exist only after passing the
   deterministic evidence-support gate.
3. **Claims as data**: a pattern library produces candidate claims; the
   deterministic gate remains the sole grounding authority.
4. **Immutable document versions** with atomic `current_version_id` flips.
5. **Staged retrieval**: scoped lexical → PostgreSQL FTS → optional
   hybrid/embeddings, each stage behind an explicit measured trigger.
6. **Embeddings may widen candidate retrieval; they never decide that evidence
   is valid.**
7. **Protocol seams** for providers, retrievers, blob storage, job queues and
   rate-limit stores.
8. **The demo corpus remains** the benchmark bed and the public sample corpus.
9. **Authentication, multi-tenancy and the evaluation framework are not
   redesigned** (see `ARCHITECTURE.md` for the auth/tenancy design).

---

## 1. Platform boundaries — the eleven layers

The platform is eleven layers. Each layer's **forbidden responsibilities** are
as binding as its responsibilities: business logic must never leak into
connectors, parsers, renderers or UI components.

### L1 — Connectors and raw-document acquisition

- **Responsibility:** obtain bytes from a source (upload, API, sync) and emit
  `RawDocument`s plus change events. Fetch-and-sync only.
- **Inputs:** external systems (browser multipart upload, JSON API, later
  SharePoint / Google Drive / OneDrive / Confluence / GitHub / Slack / S3 /
  email), sync cursors.
- **Outputs:** `RawDocument v1` (bytes, declared MIME, origin metadata),
  change events (created / updated / removed).
- **Owned data:** `connector_accounts`, sync cursors, external references,
  `documents.source_type` / `origin_uri` linkage.
- **Forbidden:** parsing content, sectioning, classification, any knowledge of
  claims, taxonomies or output formats. A connector never interprets what it
  fetches.
- **Stable interface:** `RawDocument v1` (§5); external edit → new document
  version through the standard ingestion path.
- **Future implementations:** the connector list above; each is additive tables
  plus a fetch loop — no core change.

### L2 — Ingestion and parsing

- **Responsibility:** accept a `RawDocument`, enforce limits and safety
  (magic-byte sniffing, size/zip caps, dedupe by hash), run the per-format
  parser, and drive the job state machine.
- **Inputs:** `RawDocument v1`; `ingestion_jobs` rows.
- **Outputs:** `DocIR v1` block streams; typed terminal failure states
  (`parse_failed`, `needs_ocr`, `encrypted_unsupported`, `too_large`,
  `invalid_file`).
- **Owned data:** `documents`, `document_versions`, `document_blobs`,
  `ingestion_jobs`; parser name/version per version.
- **Forbidden:** classification, retrieval, claims, tenancy decisions beyond
  carrying `company_id`, silent content invention (OCR-less scans fail
  honestly; omitted content is marked, never fabricated).
- **Stable interfaces:** `BlobStore` Protocol, `JobQueue` Protocol, parser →
  `DocIR v1`. Parsers are the only format-aware code in the platform.
- **Future implementations:** OCR extractor, XLSX/PPTX parsers, hosted parsing —
  all behind the same DocIR contract.

### L3 — Document intermediate representation (DocIR)

- **Responsibility:** the single format-neutral representation of extracted
  content: an ordered block stream with heading hierarchy.
- **Inputs:** parser output.
- **Outputs:** normalized blocks
  `{kind: heading|paragraph|table|list|omitted, level?, text, meta}`.
- **Owned data:** none persisted — DocIR is transient between parse and
  sectionize.
- **Forbidden:** format-specific fields leaking downstream; semantic
  interpretation of content.
- **Stable interface:** `DocIR v1` (§5).
- **Future implementations:** versioned DocIR extensions (e.g. provenance
  spans for OCR confidence) as additive block `meta`.

### L4 — Sections, anchors and evidence records

- **Responsibility:** sectionize DocIR, assign stable identity (anchors,
  citation ids), hash for change detection, classify deterministically using
  module-supplied signatures.
- **Inputs:** DocIR; module signature packs (via registry); previous version's
  sections (for diff/inheritance).
- **Outputs:** immutable `document_sections` rows; `SectionRecord v1` at load
  time.
- **Owned data:** `document_sections`, anchor algorithm versions, section
  hashes, manifests, classification results + classifier provenance.
- **Forbidden:** knowing what a taxonomy label *means* (it executes signatures,
  it never branches on labels); retrieval; claims.
- **Stable interfaces:** `SectionRecord v1`; the anchor identity algorithm
  (§7) — versioned, never tuned in place.
- **Future implementations:** new anchor algorithm versions coexisting with old
  ones; entity annotations as additive columns (§11).

### L5 — Retrieval

- **Responsibility:** produce **candidate** sections for an evidence need.
  Recall machinery only.
- **Inputs:** `EvidenceNeed` (derived from claim triggers or a search query),
  section scope (tenant selection or corpus), tenant glossary expansions.
- **Outputs:** scored candidate lists.
- **Owned data:** FTS indexes, `section_embeddings` (Stage 3), retrieval
  strategy version, `retrieval_metrics`.
- **Forbidden:** **deciding that evidence supports a claim** — acceptance
  belongs exclusively to L7. Retrieval may rank; it may never validate.
- **Stable interface:** `CandidateRetriever` Protocol (§8).
- **Future implementations:** Stage-2 FTS, Stage-3 pgvector hybrid, per-tenant
  glossary expansion, graph-assisted candidates (§11).

### L6 — Claim generation

- **Responsibility:** produce **candidate claims** from module-owned claim
  patterns (deterministic path) and, in full mode, compile LLM proposals into
  the same claim contract. Candidates are proposals, never conclusions.
- **Inputs:** module claim patterns (`ClaimSpec v1`), candidate sections from
  L5, persona/facet context.
- **Outputs:** `ClaimCandidate v1` bound to proposed evidence.
- **Owned data:** runtime `claim_pattern_versions` (immutable imports of
  released pattern files).
- **Forbidden:** accepting its own candidates; emitting anything that bypasses
  L7; containing domain vocabulary in engine code (vocabulary lives in
  patterns).
- **Stable interfaces:** `ClaimSource` Protocol; matcher primitives (§4-A);
  declarative pattern schema (§4-B).
- **Future implementations:** new modules' pattern sets; LLM claim-proposer as
  an additional candidate source behind the same contract.

### L7 — Evidence validation and gates

- **Responsibility:** the grounding authority. Deterministic evidence-support
  scoring, grounding repair, the structural gate, the narrative gate. Accept,
  reject, or mark `INSUFFICIENT_EVIDENCE` — never fill.
- **Inputs:** `ClaimCandidate`s + their candidate sections (full bounded text /
  token sets — not excerpts, §5); LLM candidate outputs for gating.
- **Outputs:** accepted claims with `EvidenceBinding v1`; drop/repair audit
  records; `N/A` sentinels.
- **Owned data:** thresholds (versioned threshold policies), gate telemetry,
  repair audits.
- **Forbidden:** LLM calls deciding acceptance; retrieval; rendering concerns;
  softening thresholds per tenant silently (tenant adaptation is versioned
  config, §9).
- **Stable interfaces:** evidence-support scorer contract; gate decision
  records in telemetry.
- **Future implementations:** refined scorers — always deterministic,
  explainable, versioned.

### L8 — Canonical analysis assembly

- **Responsibility:** compose validated claims into findings, contradictions,
  gaps, recommendations, actions, metrics, confidence and narrative blocks —
  the **Canonical Analysis Document (CAD)** (§2). Narrative refinement (LLM,
  gated) happens here, upstream of all rendering.
- **Inputs:** accepted claims + bindings, module templates, persona context,
  gated narrative.
- **Outputs:** `CanonicalAnalysisDocument v1`; today, its `EvidentiaReport`
  projection.
- **Owned data:** persisted report snapshots + full provenance
  (`source_versions`, `engine_versions`, §6).
- **Forbidden:** format awareness (page breaks, slide counts, cell layouts);
  any renderer-specific field beyond neutral `rendererHints`.
- **Stable interfaces:** CAD schema; the deterministic CAD → `EvidentiaReport`
  projection.
- **Future implementations:** module-typed CAD extensions; additional
  projections.

### L9 — Output rendering

- **Responsibility:** transform an immutable analysis snapshot into a
  deliverable. Pure transformation.
- **Inputs:** a persisted CAD/report snapshot (+ renderer options).
- **Outputs:** DOCX, PDF, PPTX, XLSX, HTML, Markdown, JSON/API payloads,
  dashboard views, push payloads (Jira/ServiceNow/Notion/Confluence).
- **Owned data:** renderer profiles/templates; for push renderers, delivery
  state (§2) — never analysis content.
- **Forbidden (the rendering invariant, §2):** LLM calls, document retrieval,
  evidence scoring, creating or changing claims, any business reasoning.
- **Stable interface:** `render(snapshot, options) -> artifact` — deterministic,
  side-effect-free; push delivery separated behind a delivery service.
- **Future implementations:** the full renderer list; each is independent.

### L10 — Feedback and deterministic learning

- **Responsibility:** capture human feedback and usage telemetry; turn them
  into **versioned data releases**, never online behavior change.
- **Inputs:** user feedback (report/item/citation), retrieval-miss reports,
  glossary approvals, pattern metrics.
- **Outputs:** tenant-scoped feedback rows; aggregate metrics; inputs to
  human-mediated pattern/signature/threshold releases (§9).
- **Owned data:** `report_feedback`, `item_feedback`, `citation_feedback`,
  `retrieval_misses`, `tenant_glossary`, `pattern_metrics`,
  `retrieval_metrics`, release version tables.
- **Forbidden:** automatic model training; cross-tenant movement of tenant
  text; silent threshold drift; any production behavior change that is not a
  named, benchmarked release.
- **Stable interfaces:** feedback intake API; release provenance recorded in
  `engine_versions`.
- **Future implementations:** feedback-driven benchmark scenario generation;
  Stage-3 justification analytics.

### L11 — Operations, telemetry and version provenance

- **Responsibility:** observability (job states, stage timings, per-pattern
  counters), migrations (additive-only during this plan), quotas, retention,
  backup/restore, caches, and the provenance spine (§6).
- **Inputs:** everything; **outputs:** metrics, logs, provenance records.
- **Owned data:** job/queue telemetry, cache state, quota counters, version
  registries.
- **Forbidden:** business logic; provenance fields leaking into the public
  report schema.
- **Stable interfaces:** `JobQueue` / `BlobStore` / `RateLimitStore` Protocols
  (single-instance implementations now, shared implementations later with zero
  call-site changes).

---

## 2. Canonical Analysis Document (CAD)

**The CAD is the true output of the reasoning engine.** It is internal,
domain-independent, and format-independent. The public `EvidentiaReport`
schema **remains unchanged** and becomes the CAD's first deterministic
projection:

```
CAD ──deterministic projection──▶ EvidentiaReport ──▶ current web report,
                                                       PDF/playbook UI
    ──future projections────────▶ DOCX model, slide model, dashboard model, …
```

**Migration stance:** the application is **not** migrated to CAD in M1–M5;
`EvidentiaReport` remains the runtime output. CAD is recorded now as the
direction that stops the public schema from accumulating domain-specific
fields — every proposed addition to `EvidentiaReport` must instead be asked:
"is this a CAD concept, a module extension, or a renderer concern?" CAD
introduction becomes its own milestone when the first non-report renderer
(editable DOCX with structure beyond the current report, or the JSON/API
export) needs it.

### 2.1 CAD v1 shape (domain-independent)

```
CanonicalAnalysisDocument v1
├─ meta            cadVersion, tenantRef, generatedAt, subjectRef
├─ provenance      sourceVersions[], engineVersions{}          (§6)
├─ sources         [SourceRef]        documents/versions/sections cited
├─ evidence        [EvidenceBinding]  (§5) — every citation used anywhere below
├─ claims          [ClaimResult]      validated claims: status ∈
│                                     supported | contradicted | insufficient,
│                                     claim family ∈ gap | contradiction |
│                                     staleness | assertion, evidence refs,
│                                     confidence, module+pattern provenance
├─ findings        [Finding]          claims composed into analytical
│                                     statements with severity policy applied
│                                     ("risk" is a module's finding rendering,
│                                      not a core concept)
├─ contradictions  [ClaimResult refs] cross-source conflicts surfaced
├─ gaps            [ClaimResult refs] honest missing-evidence results
├─ recommendations [Recommendation]   grounded, evidence-linked
├─ actions         [Action]           ordered, assignable steps
├─ narrative       [NarrativeBlock]   gate-approved refined text; provenance
│                                     tag: deterministic | llm(model, promptV)
├─ metrics         {…}                deterministic metrics + confidence
├─ extensions      {moduleId: {…}}    module-typed, schema-declared by module
└─ rendererHints   {…}                ordering/emphasis/grouping preferences
                                      ONLY — a renderer may ignore all of them;
                                      no reasoning, no content
```

`EvidentiaReport` projects from this: risks ← findings (module severity
mapping), workflow ← actions, citations ← evidence bindings, summary/top
finding ← narrative blocks, metrics ← metrics. The projection is pure,
deterministic, and versioned.

### 2.2 The rendering invariant

**Rendering is a deterministic pure transformation of an immutable snapshot.**

- Renderers do **not** call LLMs. Narrative refinement happens upstream in L8
  and is stored in the snapshot — otherwise DOCX and PDF of the same report
  would diverge and the audit story dies.
- Renderers do **not** retrieve documents, score evidence, or create/change
  claims.
- Renderers contain **no business logic** — severity coloring and layout are
  presentation; deciding severity is not.
- The same CAD must produce **logically equivalent** outputs across formats:
  every claim, citation, `N/A` marker and confidence statement present in one
  rendering is present (or deliberately, statically elided by the renderer
  profile) in every other.
- Citation resolution ("view source" deep links) is an *enhancement* renderers
  may layer on; rendering never depends on resolution succeeding.

### 2.3 Renderer interfaces

Pull renderers — `render(snapshot, options) -> artifact`:

| Renderer | Notes |
|---|---|
| Editable DOCX | First commercial priority. Structured styles (headings, tables, citation fields) so the deliverable is editable, not a print image. |
| PDF | Exists today via the print page; remains a projection consumer. |
| PowerPoint | Slide model from findings/recommendations; renderer profile decides density. |
| Excel | Tabular projections: findings register, evidence index, metrics. |
| HTML / Markdown | Static export of the same content model. |
| JSON / REST API | The CAD (or its projection) itself, versioned — the "renderer" is a schema filter. |
| Dashboards | Read-model projections over many snapshots; still no reasoning. |

Push renderers (Jira, ServiceNow, Notion, Confluence) are **renderer + delivery
service**, strictly separated:

- The *renderer* part is pure: snapshot → payloads (e.g. one Jira issue per
  finding).
- The *delivery* part owns delivery state: idempotency keys (snapshot id +
  target + payload hash — re-pushing a report must not duplicate tickets),
  retries with backoff, external references (`external_deliveries`: target
  system, external id, status, last attempt), and partial-delivery recovery.
- Delivery state never flows back into the snapshot; external refs live beside
  it.

---

## 3. Domain-independent core and domain modules

### 3.1 The rule

> **Engine code must never branch or string-match on a specific taxonomy
> label.**

The core knows only generic concepts: documents, sections, evidence, claims,
findings, gaps, contradictions, recommendations, actions, confidence,
provenance. Labels such as `Security`, `Compliance`, `Legal`, `HR`,
`Manufacturing`, `Healthcare`, `Pricing`, `Operations` are **module data**. A
lint/CI rule enforces this from M3 onward: no engine module may contain a
taxonomy-label string literal in a branch.

Classification mechanics (signature scoring), persona-affinity mechanics, and
facet mechanics live in the engine; the signatures, personas, critical-category
mappings, facet definitions and claim patterns that feed them are versioned,
namespaced module data.

### 3.2 Domain Modules are versioned data packs, not application forks

```
modules/compliance/1.0.0/
  module.yaml          # metadata, semver, compatible engine version range
  taxonomy.yaml        # namespaced categories + topics (compliance.security, …)
  facets.yaml          # context facets (jurisdictions, regulated markets, …)
  signatures/          # deterministic classification signature packs
  claim-patterns/      # declarative patterns (§4), one file per pattern
  personas/            # stakeholder profiles + critical-category mappings
  templates/           # slot-templated claim/recommendation/action text
  fixtures/            # positive + negative pattern fixture sections
  benchmark/           # module benchmark scenarios (BENCHMARK_VERSION lineage)
  renderer-profiles/   # optional: emphasis/grouping defaults per renderer
```

**Compliance becomes Domain Module #1** — the current eight-category taxonomy,
`HIGH_COMPLIANCE_MARKETS` facets, persona profiles and (in M5) claim patterns
are packaged as `modules/compliance/`, not as engine constants. The demo
corpus, benchmark and current product behavior are preserved byte-for-byte;
only ownership of the data moves. Future modules: Legal, Procurement,
Manufacturing, Quality, Healthcare, Insurance, Finance, HR, Software
Engineering, Due Diligence, Research, Education, Customer Support.

No code plugins in v1: data-pack modules cover the listed verticals. Code
extension points (custom matcher primitives) are added to the *engine* with
tests when a module demonstrably cannot express something — never shipped
inside a module.

### 3.3 Module registry

A registry (table + config) records per tenant:

- enabled module ids;
- pinned module versions (upgrades are explicit, never silent);
- compatible engine version ranges (a module declares them; the registry
  refuses incompatible activation);
- module configuration (which personas/facets are active);
- optional tenant overrides (e.g. tenant-curated persona additions) — versioned
  and recorded in report provenance like everything else.

Tenant isolation is unchanged: module *definitions* are shared platform data;
module *enablement, configuration and overrides* are tenant-scoped rows.

---

## 4. Claim Pattern Library

The accepted claims-as-data decision, formalized as **two layers**. No generic
RAG. No custom DSL before the typed primitives are proven insufficient.

### 4-A. Matcher primitives — implemented and versioned in code

A small, closed, typed set the engine executes:

- weighted signal lists;
- exact phrase matches (multi-word bonus);
- exclusions and negation markers;
- contradiction contracts (`resolvedIf`-style);
- staleness checks (date/version vocabulary);
- missing-evidence / gap checks;
- source-category / source-topic requirements (against module taxonomy);
- slot templates (market/facet, matched section title, …);
- severity rules (module severity policy applied to match strength);
- evidence thresholds (which versioned threshold policy gates acceptance).

New primitive = engine release with tests. Primitives are the vocabulary of
patterns; they are what keeps patterns *data*.

### 4-B. Declarative claim patterns — schema-validated YAML/JSON

Patterns are **not executable code**. Every pattern file contains:

| Field | Purpose |
|---|---|
| `id` | stable, namespaced (`compliance.residency-default-processing`) |
| `module` / `version` | owning module + pattern semver |
| `family` | gap \| contradiction \| staleness \| assertion |
| `triggers` | source-category/topic requirements, signal/phrase lists |
| `evidence` | required support: signals, phrases, thresholds policy ref |
| `exclusions` | negations/contexts that suppress the pattern |
| `templates` | slot-templated claim / finding / recommendation text |
| `severity` | module severity policy inputs |
| `fixtures` | positive sections it MUST bind; negative sections it MUST NOT |
| `changelog` | dated entries; which feedback motivated each change |

### 4-C. Pattern lifecycle

1. Authored/edited as files in Git → **reviewable diffs**.
2. **Schema-validated** in CI (a pattern that doesn't validate doesn't merge).
3. **Fixture-tested** in CI: every pattern's positive/negative fixtures run
   against the real matcher primitives + gate (the detection-rule model — a
   500-pattern library is maintainable only if each pattern carries its own
   tests).
4. Released as a named pattern-library version; **imported into immutable
   `claim_pattern_versions` runtime records**.
5. The active pattern-library version is recorded in every report's
   `engine_versions` (§6).

**Failure economics:** the gate makes false positives into drops/`N/A`s, so the
dominant risk is **silent low recall** — thin reports. Per-pattern telemetry
(fire rate, bind rate, gate-pass rate, `N/A` rate) ships with the first
pattern (§9, §10), so recall problems are observable at design-partner time.

### 4-D. Milestone split

- **M5a — claim-engine plumbing (bounded):** `ClaimSource` wiring,
  owns-by-resolution in evidence support, pattern loader + schema validation,
  fixture harness, pattern metrics, benchmark v2 harness.
- **M5b — pattern authoring (ongoing content work):** authoring and iterating
  domain patterns on design-partner corpora. **Not a fixed two-week task** —
  it is content, paced by feedback, and planning must treat it that way.

---

## 5. Typed platform contracts

The section dictionary is the platform's most load-bearing interface and must
not remain an anonymous dict. All contracts are versioned; consumers declare
the version they accept. "Immutable" = never reinterpreted within a version;
new meaning ⇒ new contract version.

| Contract | Role | Key fields (required unless noted) |
|---|---|---|
| `RawDocument v1` | L1→L2 | `bytes`, `declared_mime`, `origin` (source_type, uri?, external_id?), `tenant_ref`, `received_at` |
| `DocIR v1` | L2→L4 | ordered `blocks[{kind, level?, text, meta}]`; kinds: heading, paragraph, table, list, omitted |
| `SectionRecord v1` | L4→L5/L6/L7 currency | identity: `documentId`, `versionId`, `anchorId`, `citationId` (immutable); structure: `headingPath`, `title`, `ordinal`, `depth`; content: `text` (full, bounded 200–4,000 chars), `excerpt` (~1,200 chars, display/prompt only), `textSha256`, `tokenSet`, `charCount`, `hasTables`, `hasOmittedContent`; classification: `category`, `topics`, `facets`, `personaAffinity`, `injectionFlags` + `classifierVersion`, `signaturePackVersion` (optional until M3); provenance: `parserVersion`, `anchorAlgoVersion` |
| `EvidenceBinding v1` | L7 output | `claimRef`, `sectionRef` (document+version+anchor), `citationId`, `matchedSignals`, `matchedPhrases`, `supportScore`, `thresholdPolicyVersion`, `decision` (accepted \| insufficient) |
| `ClaimSpec v1` | pattern → engine | the §4-B pattern fields, compiled: `id`, `module`, `version`, `family`, `triggers`, `evidence`, `exclusions`, `templates`, `severityPolicy` |
| `ClaimCandidate v1` | L6→L7 | `specRef` (pattern id+version) or `proposerRef` (llm, model, promptVersion), `candidateSections[]`, `slots{}`, `proposedSeverity?` |
| `Finding v1` | L8 | `claimRefs[]`, `statement`, `severity`, `confidence`, `evidenceRefs[]`, `moduleRef` |
| `Recommendation v1` | L8 | `findingRefs[]`, `statement`, `evidenceRefs[]`, `actionRefs[]?` |
| `CanonicalAnalysisDocument v1` | L8 output | §2.1 |

**Compatibility:** the current pipeline currency
`{documentId, source, sectionTitle, excerpt, category, citationId}` is a strict
projection of `SectionRecord v1` — existing scorers, gates and binders keep
receiving the shape they receive today. `SectionRecord` distinguishes what the
dict conflated:

- **`text` / `tokenSet`** — what deterministic scoring consumes;
- **`excerpt`** — display and char-budgeted LLM evidence packs only;
- **classification + module provenance** — which signature pack produced the
  labels;
- **parser and anchor versions** — identity provenance.

### 5.1 Corrected design assumption — full-text scoring

> **Deterministic evidence scoring, retrieval support scoring and grounding
> repair inspect the full bounded section `text` / `tokenSet`, not only the
> first ~1,200-character excerpt.**

The previous ingestion draft had every scorer consuming
`sectionTitle + excerpt`. On customer documents that blinds the gate to up to
~70% of a long section, producing false `INSUFFICIENT_EVIDENCE` results
correlated with the customer's writing style — and indistinguishable in
telemetry from genuine gaps, which would poison the Stage-3 trigger signal.
`tokenSet` is built from the **full** section text at ingest, so generation
cost does not move. The excerpt remains a display and prompt-budget field
only. This lands with M4 (first customer generation).

---

## 6. Complete provenance and reproducibility

Document versions alone do not make a report reproducible: output is a
function of documents **and** the analyzer. Two additive report-row fields
(DB metadata — **the public `EvidentiaReport` schema is not changed**):

**`reports.source_versions`** (JSON):
`[{documentId, versionId, versionNo, parserVersion}]`

**`reports.engine_versions`** (JSON):

| Field | Records |
|---|---|
| `engineRelease` | application release identifier |
| `modules` | enabled module ids + pinned versions |
| `patternLibrary` | claim-pattern library version(s) |
| `signaturePacks` | classification signature-pack versions |
| `taxonomies` | taxonomy versions |
| `thresholdPolicy` | threshold-policy version |
| `anchorAlgo` | anchor algorithm version(s) of the versions read |
| `benchmark` | benchmark dataset version current at generation |
| `retrieval` | retrieval strategy + version (stage set, glossary version) |
| `tenantGlossary` | tenant glossary version applied (if any) |
| `llm` | provider, model, prompt version — when any LLM call ran |

**Why this answers "why did this report change?"** — every plausible cause is
now a diffable field:

| Cause | Visible as |
|---|---|
| customer documents changed | `source_versions` versionId/versionNo diff |
| parser changed | `parserVersion` diff |
| anchors changed | `anchorAlgo` diff |
| module / pattern library changed | `modules` / `patternLibrary` diff |
| classification signatures changed | `signaturePacks` diff |
| thresholds changed | `thresholdPolicy` diff |
| retrieval changed | `retrieval` diff |
| tenant glossary changed | `tenantGlossary` diff |
| LLM model or prompt changed | `llm` diff |

**Timing is not negotiable:** both fields land at **M4, the first
customer-report milestone** — not at the later versioning-UX milestone.
Reports generated without provenance can never be repaired retroactively;
every week of delay is audit history permanently lost. (The earlier draft
scheduled `source_versions` at M8 while claiming the data was "recorded from
day one" — that contradiction is resolved in favor of day one.)

---

## 7. Anchor and citation identity

The heading-path anchor approach is kept and **formalized as a versioned
identity algorithm**. Rendered citation ids are frozen into immutable report
snapshots forever; the algorithm that mints them is therefore governed like a
public schema.

### 7.1 Requirements

- `anchor_algo_version` stored on every `document_versions` row.
- **Constants are part of the algorithm version**: section size bounds
  (200–4,000 chars), excerpt bound, hash truncation (`base36(sha1)[:5]`),
  Jaccard inheritance threshold (0.8), normalization rules. Changing any
  constant ⇒ new algorithm version. **No in-place tuning of an existing
  version, ever.**
- **Deterministic tie-breaking**, specified and tested (§7.3).
- **Golden fixture corpus**: fixture documents with expected anchors for every
  case in §7.2, run in CI. The corpus is the algorithm's regression contract;
  a new algorithm version ships with its own expected outputs.

### 7.2 Specified behavior (all cases deterministic and fixture-tested)

| Case | Behavior |
|---|---|
| Content edit under unchanged heading | anchor kept (heading-path identity) |
| Heading rename | new anchor, then **inheritance**: exact `text_sha256` match (cheap pass) or token-set Jaccard ≥ 0.8 (guarded pass) inherits the old anchor |
| Section split (grew past upper bound) | parts `anchor.p1, anchor.p2, …`; `.p1` inherits the original anchor's citation lineage; `.p2+` are new |
| Section merge (undersized fragments) | merged into previous section; the disappearing fragment's anchor is retired (resolvable via pinned versions) |
| Duplicate headings (same normalized path) | deterministic ordinal suffix in document order |
| Insertion before existing duplicates | later duplicates renumber; exact-hash inheritance re-attaches unchanged ones to their old anchors before renumbering is accepted |
| Rename + split in one revision | inheritance candidates computed against **all** disappeared anchors; tie-break per §7.3 |
| Oscillation around a size bound | identity flips between `anchor` and `anchor.p1` are damped by inheritance (`.p1` exact-hash-matches the unsplit text ⇒ inherits); fixture-tested |
| Two new sections competing for one disappeared anchor | tie-break per §7.3 — exactly one inherits |

### 7.3 Tie-breaking (in order)

1. highest content similarity (token-set Jaccard);
2. exact `text_sha256` match preferred over any similarity score;
3. nearest document order (smallest |ordinal delta|);
4. deterministic final key (lowest candidate anchor id lexicographically).

### 7.4 Algorithm evolution

A future `anchor_algo v2` coexists with v1 without rewriting anything
persisted:

- Persisted reports embed rendered citation ids + pinned versions — they never
  re-resolve against a new algorithm. Nothing to migrate.
- New document versions are anchored with the current algorithm; old versions
  keep their recorded `anchor_algo_version` and are never re-anchored in
  place.
- Cross-version anchor inheritance at the v1→v2 boundary runs the **v2**
  inheritance pass against the v1 anchors' text hashes/token sets — inheritance
  is defined over content, not over algorithm internals, so ids can survive
  the upgrade where content survives.
- "View source" resolution uses the pinned version's anchors (whatever
  algorithm minted them); the current-version fallback uses inheritance
  lineage.

---

## 8. Retrieval architecture

Staged, trigger-driven, and **subordinate to the gate**:

> Retrieval proposes candidates. The deterministic evidence gate accepts or
> rejects evidence. Embeddings must never replace grounding acceptance.

| Stage | What | Trigger |
|---|---|---|
| 1 | Selection-scoped lexical scoring over precomputed token sets (no index) | ships with MVP; sufficient while selection-scoped generation is the only consumer |
| 2 | PostgreSQL FTS (`tsvector` + GIN, `ts_rank_cd`, always tenant-filtered) for corpus search + candidate pre-filtering | picker needs search over hundreds+ docs; or Python-side scoring appears in latency; or patterns need corpus-wide pre-filtering |
| 3 | Optional hybrid/embedding candidate generation (pgvector, per-section, incremental by hash) | **measured** synonymy failure only — see the sensor below |

`CandidateRetriever` is a **typed** interface:

```python
class CandidateRetriever(Protocol):
    def candidates(
        self, need: EvidenceNeed, scope: SectionScope
    ) -> list[ScoredCandidate]: ...
# EvidenceNeed: derived from ClaimSpec triggers or a search query
#               (signals, phrases, category/topic requirements, facets)
# SectionScope: tenant + selection or corpus-wide; always company_id-bound
# ScoredCandidate: SectionRecord ref + retrieval score + stage tag
```

The claim engine never knows which stage produced a candidate.

### 8.1 The Stage-3 sensor (previously missing)

Embeddings are adopted on **evidence, not intuition**. Users can report, on any
`N/A` / insufficient-evidence item: **"evidence exists, but Evidentia missed
it"** — pointing at the actual section. This creates a `retrieval_misses` row:
pattern id + version, the evidence need, the human-identified section anchor,
tenant, timestamp. Stage 3 is justified when retrieval-miss telemetry
demonstrates lexical synonymy/vocabulary failure (misses a human could point
at, clustered on vocabulary divergence) — and not before. This intake ships
with M5a, because without it the Stage-3 trigger condition is unobservable.

### 8.2 Tenant glossary and thresholds

Tenant-approved glossary mappings (§9) may **widen retrieval candidates**
(synonym expansion during candidate generation). They must **not** weaken the
evidence-acceptance threshold: the gate scores the section text as written,
under the same versioned threshold policy. Glossary expansion is recall
machinery, recorded in `engine_versions.tenantGlossary`.

---

## 9. Learning without silent model drift

Evidentia improves from usage through **versioned releases**, never through
online self-modification. No automatic retraining. No silent threshold drift.
No shared learning from private tenant text by default.

### 9.1 Data model (all tenant-scoped, standard `company_id` tenancy)

| Entity | Contents |
|---|---|
| `report_feedback` | report id, user, verdict, structured reason codes, freetext (tenant-private) |
| `item_feedback` | report id, item path + type, accepted / rejected / edited, reason code, edited text (tenant-private) |
| `citation_feedback` | item ref, offered citation id, corrected section anchor |
| `retrieval_misses` | §8.1 — pattern id+version, evidence need, human-identified anchor |
| `tenant_glossary` | tenant term ↔ canonical term, provenance (mined/curated), approved_by, per-tenant version |
| `claim_pattern_versions` | immutable pattern releases + changelog + motivating feedback classes |
| `signature_pack_versions` | immutable signature releases |
| `threshold_policy_versions` | immutable threshold releases (calibrated offline) |
| `retrieval_metrics` | aggregate counters per strategy/version |
| `pattern_metrics` | per pattern+version: fire rate, bind rate, gate-pass rate, `N/A` rate |

**Stored:** identifiers, anchors, citation ids, pattern/module versions,
decision states, structured reason codes, approved glossary mappings,
aggregate counters, release provenance.

**Never stored in any global/cross-tenant artifact:** tenant document text,
excerpts, prompts containing tenant content, or private feedback freetext.
The rule that keeps isolation auditable: **tenant text crosses the tenant
boundary only through a human, under an explicit agreement, into a
code-reviewed release.**

### 9.2 Loop A — tenant-local deterministic adaptation

Approved glossary/alias/terminology mappings, module configuration, pinned
versions. Applied deterministically, scoped to the tenant, versioned per
tenant, and recorded in every affected report's provenance. Safe to apply
without a global release because it is tenant-owned configuration, not shared
behavior.

### 9.3 Loop B — global human-mediated releases

Feedback clusters (rejected items, retrieval misses, citation corrections,
insufficient-evidence patterns) inform: claim-pattern vocabulary, classification
signatures, repair weights, thresholds, new benchmark scenarios, and the
Stage-3 decision. Every change ships as a **named deterministic release**
(pattern library vN / signature pack vN / threshold policy vN) that must pass
benchmark regression checks before deployment, and is visible in
`engine_versions`. "Why did the report change?" always has a diffable answer
(§6).

---

## 10. Operations and scale

Corrections that are binding on implementation milestones:

- **Report cache**: version-aware key (document version ids in the cache key)
  **and** bounded with LRU eviction. The current `orchestrator._CACHE` is an
  unbounded dict whose key space becomes customer-controlled the moment tenant
  selections enter it — same defect class as the rate-limit store fixed in
  hardening pass 2. Lands in M4.
- **Tenant-fair ingestion scheduling**: job claims are round-robin across
  tenants (e.g. `DISTINCT ON (company_id)` / window-function claim query), not
  pure FIFO — one tenant's 500-PDF bulk upload must not starve every other
  tenant's single upload. Lands with the worker (M2).
- **`attempts` increments at claim time**, not after handled failure — a job
  that kills the worker process must still hit the attempts cap instead of
  being requeued forever by the startup sweep.
- **Stale-job recovery**: `heartbeat_at` + startup requeue of stale `running`
  rows (single-instance now); the recovery logic lives behind the `JobQueue`
  seam so a shared queue replaces it without call-site changes.
- **Blob/row crash-safe ordering**: version row (`pending`) → blob `put` → row
  references blob → work proceeds. A crash between steps leaves either an
  inert pending row or an orphaned blob — **orphaned-blob reconciliation** is a
  periodic sweep (blobs unreferenced past a grace window are deleted), designed
  now because it becomes acute when `BlobStore` moves to object storage.
- **Classifier provenance**: sections record `classifier_version` /
  `signature_pack_version`, so signature upgrades have a defined re-classify
  trigger (the analog of `parser_version` re-ingestion).
- **FTS migration cost**: adding a stored generated `tsvector` column to a
  by-then-large sections table rewrites the table. Either add the nullable
  column early (M1 schema) and populate lazily, or schedule the rewrite as an
  explicit maintenance window in M9 — decided at M9 entry, recorded here so it
  is not a surprise.

**Scale honesty:** the platform must not claim readiness for millions of
sections until it has: listing pagination; the index set on sections/jobs
(tenant-scoped lookups, `(version_id, anchor_id)` / `(version_id, ordinal)`
uniqueness, job state+heartbeat); background-job observability (states, stage
timings, queue depth); storage metrics; per-tenant quotas (documents count +
total bytes); retention policies (keep-last-N versions knob exists in schema
from day one); backup/restore procedures for blobs + rows; and shared
queue/rate-limit implementations when scaling past one instance. The
single-instance posture is the supported v1 shape; every seam it hides behind
(`JobQueue`, `BlobStore`, `RateLimitStore`) is already Protocol-typed.

---

## 11. Knowledge graph — future option, explicitly not v1

A future evidence/knowledge graph layer
(Documents → Sections → Entities → Relations → Evidence → Claims) could add:
cross-document entity resolution ("ACME Corp" = "the Customer"), relationship-
aware evidence, contradictions across many documents, temporal reasoning, and
shared-concept discovery across sources.

**It is not implemented now, and it is not on the v1 roadmap.** Its governing
constraints, recorded so future work stays additive:

- **Justifying evidence:** recurring, telemetry-visible failures that section-
  scoped reasoning cannot express — contradiction patterns that require
  entity resolution across documents, retrieval misses caused by entity
  aliasing rather than synonymy, or module demand for relation-conditioned
  claims (e.g. "obligation X belongs to party Y"). The `retrieval_misses` and
  pattern-metrics telemetry (§9) is what would surface this.
- **Contract compatibility:** `SectionRecord` (stable section identity via
  anchors) and `EvidenceBinding` (evidence always resolves to a section) are
  already graph-compatible: entities/relations would be **additive annotations
  referencing section anchors**, not replacements for them.
- **Additive entity extraction:** deterministic extractors (or gated LLM
  proposers) writing `section_entities` / `entity_relations` tables keyed by
  section anchor — nothing existing changes.
- **The hard rule:** the graph may **assist candidate retrieval and context
  assembly** (another `CandidateRetriever` implementation). It must **never
  become a grounding authority**: claims still cite sections, the deterministic
  gate still scores section text, and a graph edge is never itself evidence.

---

## 12. Roadmap

Milestones sized for individual PRs; one senior engineer; tests included
(failing test first for invariants). The ingestion doc (§15 there) holds the
per-milestone detail; this table is the platform-level contract, including the
**entry criteria** the review made binding.

### Gate: before M1 merges

- Typed contracts: `RawDocument v1`, `DocIR v1`, `SectionRecord v1`,
  `ClaimSpec v1` (+ stubs for the rest of §5) — the pipeline currency stops
  being an anonymous dict.
- Protocol seams: `BlobStore`, `JobQueue`, `SectionProvider`
  (+ existing `RateLimitStore`).
- Blob/row crash-safe write order + orphaned-blob reconciliation strategy
  documented in the schema PR.
- Feature-flag plumbing (`EVIDENTIA_TENANT_CORPUS_ENABLED`, default off).

### Gate: before M3 merges (anchor + module identity — frozen-forever surface)

- `anchor_algo_version` on document versions; tie-break specification (§7.3);
  golden anchor fixture corpus covering every §7.2 case.
- Taxonomy, signatures, personas, critical-category mappings and facets as
  **namespaced, versioned module data** (`modules/compliance/…`), not engine
  constants.
- `classifier_version` / `signature_pack_version` provenance on sections.
- Lint/CI rule: engine code never branches on a taxonomy label.

### Gate: before the first customer report (M4)

- `reports.source_versions` **and** `reports.engine_versions` populated (§6).
- Full-text deterministic scoring (§5.1) — token sets from full section text.
- Bounded, version-aware report cache (§10).
- Tenant-fair job claims; claim-time attempt increment (§10).
- `report.company` carries the tenant's company name for tenant-corpus reports
  (value change within the existing schema shape, behind the corpus flag) —
  recorded in `DECISIONS.md`.

### Gate: M5 entry

- Declarative pattern format + schema validation (§4-B).
- Typed matcher primitives (§4-A).
- Positive/negative fixture harness in CI (§4-C).
- Pattern metrics + retrieval-miss feedback + item/citation feedback intake
  (§8.1, §9.1).
- M5a (engine plumbing, bounded) split from M5b (content authoring, ongoing).

### Milestone sequence

| # | Milestone | Notes |
|---|---|---|
| M1 | Schema + seams + typed contracts | additive migrations only |
| M2 | Upload + ingestion spine (MD/TXT) | worker + state machine + tenant-fair claims |
| M3 | Anchors + classification + module data packaging | the frozen-forever review gate |
| M4 | Pipeline integration + **full provenance** | first real generation on customer documents |
| M5a | Claim-engine plumbing + feedback intake | bounded engineering |
| M5b | Pattern authoring on design-partner corpora | ongoing content work |
| M6 | HTML + DOCX **parsers** | parallel to M5 after M2 |
| M7 | PDF (text-layer) parser | parallel to M5 after M2 |
| M8 | Versioning UX ("view source", changed badges) | provenance already recorded since M4 |
| M9 | Stage-2 FTS (picker search, pattern pre-filtering) | FTS column migration cost decided at entry |
| R-track | Renderers, independent of M-track after M4 | 1. editable DOCX → 2. polished PDF → 3. canonical JSON/API → 4. HTML/interactive; PPTX/Excel/push integrations follow as independent renderers |
| Later | OCR, connectors, Stage-3 embeddings, XLSX/PPTX, retention/purge tooling, CAD migration, knowledge graph | each trigger-driven |

Debt watch: `documents.content_text` is deprecated after M1 and needs an
explicit removal milestone once backfill is verified — recorded so it does not
live forever.

---

## 13. Decision index

The following are recorded as append-only entries in `DECISIONS.md`
(2026-07-14 · Platform architecture constitution):

1. Claims-as-data over generic RAG.
2. CAD as the eventual internal canonical representation.
3. `EvidentiaReport` as the first compatibility projection.
4. Domain modules as versioned data packs.
5. Claim patterns as declarative rules over typed code primitives (no DSL, no
   executable patterns).
6. Full-text deterministic scoring (excerpt is display/prompt-budget only).
7. Complete engine provenance on every report from M4.
8. Versioned anchor algorithms (constants included; no in-place tuning).
9. Retrieval as candidate generation only; the gate is the grounding authority.
10. Learning through versioned releases, never online drift.
11. Knowledge graph deferred until justified by telemetry; never a grounding
    authority.

---

## Related documents

- `DOCUMENT_INGESTION_ARCHITECTURE.md` — implementation design for ingestion
  (schema, parsers, anchor scheme detail, failure taxonomy, milestone detail).
  References this document for shared concepts; where the two disagree, this
  document wins and the disagreement is a bug.
- `ARCHITECTURE.md` — the current implemented system (auth, tenancy, pipeline,
  persistence). Describes what exists; this document describes what is being
  built.
- `DECISIONS.md` — append-only rationale log.
- `docs/ai/PROJECT_STATE.md` / `SESSION_HANDOFF.md` — living status.
