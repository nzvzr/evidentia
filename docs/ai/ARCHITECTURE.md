# Evidentia — Architecture

_Stable design. Update only when the design itself changes._

## Overview

The product is **authenticated and multi-tenant**, and the Python backend owns
authentication, tenancy and persistence. The product has one runtime request
path:

```
Browser ─▶ Next.js BFF ─▶ Python FastAPI backend ─▶ PostgreSQL
             /api/generate-workflow, /api/reports, /api/documents, /api/auth/*
             backend unreachable or unset ──▶ 503. There is NO fallback.
```

The backend emits the `EvidentiaReport` compatibility JSON (camelCase), and the
frontend renders persisted tenant reports and export views.

**No authenticated route has a fallback of any kind.** A report on an
authenticated route belongs to a real account and is persisted to that tenant, so
it may only be produced by a session the backend actually validated:

- Backend unreachable or `EVIDENTIA_BACKEND_URL` unset → **503**, never a locally
  generated report. Cookie *presence* is never treated as proof of a session.
- Authenticated reports and documents live **only in the database**. Nothing
  authenticated is cached in `localStorage`; a backend 404 never falls back to a
  local report. Browser storage holds only versioned, session-scoped workspace
  input and pending-run nonces, and is purged on session changes.
- `EVIDENTIA_DB_ENABLED=false` is **refused at startup in production** — without
  the database there is no authentication, no tenancy, and generation cannot keep
  its "200 means saved" promise.

## Authenticated frontend generation lifecycle

One workspace click creates a session-scoped, non-secret run nonce alongside its
input. `/running` uses that nonce plus the input as the key for an in-memory
single-flight request that exists only while the POST is pending. This lets React
Strict Mode's development setup/cleanup/setup replay subscribe to one request;
settled entries are removed immediately, and a real unmount aborts after a
zero-delay replay grace period. The nonce is purged on login/logout/session loss,
so a flight cannot be reused across sessions; report content is never cached.

The backend does not stream stage or agent progress, so `/running` uses an honest
indeterminate state plus a slow-request notice. It never marks an internal stage
complete without backend data. A successful response already represents a
persisted report; the page navigates once to that report id. Retry creates a fresh
nonce and therefore a fresh logical request.

## Deterministic-first principle

Within a *single* generation, the deterministic agents produce a complete, grounded
report with no LLM and no network; LLM usage only *refines* that baseline, and each
LLM step falls back to its deterministic output on failure. This is a property of
the pipeline's internals — it keeps generation cheap and evaluation reproducible.

It is **not** a system-level fallback: it does not mean an authenticated request
can be served without the backend, and it never has authority to invent a session.

## Backend pipeline (`backend/app/agents/orchestrator.py`)

The orchestrator receives one explicit `SectionProvider` for the whole run.
`DemoCorpusProvider` reads only the bundled sample corpus. Authenticated FastAPI
generation selects `TenantCorpusProvider` only, using membership-derived company
context; it never accepts company/source/citation identity from the browser and
never falls back to demo. `EVIDENTIA_TENANT_GENERATION_ENABLED` is an independent,
default-off rollout gate.

The tenant provider resolves each non-deleted document's exact current version
and delegates acceptance to the M3 `check_generation_eligibility` predicate. It
then freezes exact versions and sections before generation. Retrieval
`tenant-lexical-v1` is deterministic lexical scoring over title, heading,
classification and full canonical text. Each exact version is streamed in
canonical section order and scored before a bounded per-document top-k is
retained; scored lists are then truncated globally in deterministic document-rank
rounds and re-sorted by score plus stable identity tie-breaks. This keeps deep
sections eligible without unbounded application memory or allowing one document
to consume the candidate budget. Document/candidate/selection/character/
per-document/excerpt limits remain explicit. The `tcs1` digest binds company
scope, sorted version ids, manifests, retrieval version and configuration. No
transaction is held over an LLM call.

M5a adds a second independent default-off rollout gate,
`EVIDENTIA_CLAIM_ENGINE_ENABLED`. For tenant providers only, the existing frozen
snapshot and report-local M4 bindings feed versioned declarative claim patterns,
`typed-matchers-v1`, and `deterministic-support-gate-v1`. The gate alone decides
accepted/rejected/insufficient. Every candidate is matched against the complete
bounded frozen evidence set; LLM citation ids are hints only and cannot hide
conflicts or create support. Accepted bindings come only from successful support-
matcher observations. One accepted-only projection owns workflow, risks, actions,
summary and top finding; zero accepted claims produce empty analytical arrays and
an honest no-accepted-claim narrative. Rejected and insufficient decisions remain
audit provenance. LLM full mode may propose wording plus frozen citation ids but
cannot provide acceptance, bypass projection or survive a failed atomic full-mode
refinement. Claim-engine errors fail the
generation rather than silently returning to the M4 risk path. Flag off preserves
M4 behavior and demo generation does not run tenant claims.

Deterministic agents run in order, then optional LLM refinement, then repair and
assembly:

1. `document_reader` — parse selected markdown docs into sections with citation IDs.
2. `persona_mapper` — persona profile (custom personas inferred from free text).
3. `workflow_builder` — 4–6 evidence-bound steps.
4. `risk_analyzer` — 3–5 risks (≥1 High, ≥1 Medium).
5. `citation_binder` — bind grounded citations.
6. `metrics_agent` — deterministic metrics.
7. `report_composer` — assemble summary, top finding, actions, agent timeline.

LLM refinement (when enabled): `full` uses ≤3 calls (persona+workflow, risks,
report narrative); `summary` uses 1 call (report narrative only). `auto` resolves
the mode from deterministic-baseline signals (`mode_router.py`).

Safeguards before/after refinement:
- **Grounding repair** (`tools/citation_tools.py`): validate + repair every
  `evidenceCode` against selected-document citation IDs; invalid → relevant valid
  citation or `N/A` sentinel (never invented); re-bind citations.
- **Field-level narrative gate** (`agents/narrative_gate.py`): accept an LLM
  candidate field only if strictly better and non-regressing on factual
  consistency, grounding, and warnings; ties keep deterministic.

`run_pipeline_ex` returns `(report, telemetry)`; `run_pipeline` returns the report
(unchanged public contract). Telemetry carries tokens, cost inputs, cache status,
prompt version, gate decisions, and repair counts.

Tenant document text is untrusted evidence. It is never placed in the LLM system
instructions; bounded prompt evidence is wrapped in labelled
`<untrusted-evidence>` blocks with an explicit do-not-follow rule. Every
case-variant of the closing sentinel inside the prompt payload is deterministically
HTML-encoded while stored source text remains unchanged. The final tenant
validator accepts only citation ids in the frozen report-local registry and
requires citation source/section/excerpt display data to match its bound section.
Narrative defence-in-depth recognizes unknown IDs only in the active tenant
citation-prefix families and the reserved opposite-mode `DEMO-*` family, so
standards such as ISO-27001, SOC-2 and PCI-DSS-4.0 remain ordinary text.

## Evaluation framework (`backend/app/eval/`)

- `dataset.py` — versioned scenarios + ground-truth expectations.
- `metrics.py` — grounding + narrative sub-metrics, weighted scores.
- `runner.py` — runs scenarios × modes, computes deltas vs deterministic.
- `export.py` — JSON + CSV.
- `pricing.py` — token-based cost estimate.
- CLI: `scripts/run_benchmark.py`.

## Persistence

SQLAlchemy 2.x models (`users`, `companies`, `company_members`, `documents`,
`personas`, `reports`) with Alembic migrations. Reports store the full report JSON.
The database is the **only** store for authenticated data.

M4 migration `e4b7c9d2a610` keeps the 20-key `EvidentiaReport` compatibility JSON
unchanged and stores operational provenance separately: report-level corpus/
snapshot/retrieval/orchestrator/execution/status/count metadata,
`report_source_versions` for the ordered exact version set, and
`report_evidence_bindings` for report-local section/citation/rank bindings and
bounded display excerpts. Composite report/company, version/document/company and
section/version/document/company foreign keys make cross-tenant bindings invalid
at SQL level. `GET /api/reports/{id}/sources` is the tenant-scoped audit projection.

Document deletion is soft deletion. New provider snapshots exclude deleted
documents, while immutable versions/sections and completed report bindings remain
auditable. Full document text is not copied into report bindings.

M5a stores claim packs separately at
`modules/<module>/claim-patterns/<version>/`; adding a claim pack does not alter
the released M3 classification-module directory, digest or finalization identity.
Migration `f5a6c7d8e9b0` adds immutable global pattern identities; normalized
report-local candidates, deterministic decisions and binding links; tenant- and
pattern-version-scoped non-authoritative counters; and tenant feedback/retrieval-
miss records. Composite report/company and claim/binding/company foreign keys
reject cross-tenant references at SQL level. Claims are exposed separately at
`GET /api/reports/{id}/claims`; feedback uses authenticated replacement-semantics
endpoints below the same report resource. Neither changes `EvidentiaReport`.
Corrected citation feedback resolves a submitted anchor to a report-local evidence
binding; a composite report/company foreign key enforces frozen-snapshot
membership even for direct SQL writes.

- **Production requires managed PostgreSQL.** `DATABASE_URL=postgresql://…`
- **SQLite (empty `DATABASE_URL`) is local development only.** Container
  filesystems are typically ephemeral, so a redeploy destroys every user and
  report. Production startup cannot detect an ephemeral disk for you.
- `EVIDENTIA_DB_ENABLED=false` is refused in production.

## Concurrency and locking

Two invariants are cross-row, so they cannot be column constraints and must be
enforced inside a locked critical section:

- **Session issuance vs revocation** (`repositories/users.lock_user`): login,
  refresh, logout-all and password reset all take the **user row lock** *before*
  the security decision, and re-read the row under it. Verifying a password before
  the lock let a login approve the old password, wait for a concurrent reset, and
  then mint a session the reset was supposed to have killed.
- **Role changes and the owner invariant** (`repositories/memberships`): every
  membership mutation — including *creation* — takes the **company row lock** and
  re-reads the actor's membership, the target's membership and the company from the
  database under it. `company.owner_id` always names an active owner afterwards.

Both re-reads use `populate_existing`. Without it the ORM returns the instance the
request dependency already loaded, so a "re-read under the lock" would silently
hand back pre-lock state.

On PostgreSQL these are real `SELECT … FOR UPDATE` row locks. On SQLite there is no
`FOR UPDATE`, so the lock is taken with a no-op `UPDATE` (a whole-database write
lock) — sufficient, but a different mechanism, and dev-only.

## Configuration (backend/.env, never committed)

`OPENAI_API_KEY`, `EVIDENTIA_USE_LLM`, `EVIDENTIA_LLM_PROVIDER`,
`EVIDENTIA_LLM_MODEL`, `EVIDENTIA_LLM_INTENSITY`, `EVIDENTIA_MAX_CONTEXT_CHARS`,
`EVIDENTIA_MAX_OUTPUT_TOKENS`, `EVIDENTIA_ENABLE_CACHE`, `DATABASE_URL`,
`EVIDENTIA_DB_ENABLED`, `JWT_SECRET`, `EVIDENTIA_BFF_SECRET`,
`EVIDENTIA_EMAIL_BACKEND` (+ SMTP settings), `EVIDENTIA_CORS_ORIGINS`,
`EVIDENTIA_TRUSTED_PROXY_COUNT`, `EVIDENTIA_TENANT_CORPUS_ENABLED`,
`EVIDENTIA_TENANT_GENERATION_ENABLED`, `EVIDENTIA_CLAIM_ENGINE_ENABLED`, and
bounded tenant retrieval/feedback settings.
Frontend uses `EVIDENTIA_BACKEND_URL` (server-only).

Production refuses to start on: a missing or non-generated `JWT_SECRET`, a
non-generated `EVIDENTIA_BFF_SECRET` (both must be the base64url/hex encoding of
≥32 random bytes), a trusted proxy count > 0 with no BFF secret, the `console`
or `noop` email backend, wildcard CORS, or `EVIDENTIA_DB_ENABLED=false`.
