# Evidentia — Architecture

_Stable design. Update only when the design itself changes._

## Overview

The product is **authenticated and multi-tenant**, and the Python backend owns
authentication, tenancy and persistence. There are exactly two request paths, and
they do not overlap:

```
Browser ─▶ Next.js BFF (App Router UI + API routes)
                │
                ├─ AUTHENTICATED  ─▶ Python FastAPI backend ─▶ report ─▶ PostgreSQL
                │   /api/generate-workflow, /api/reports, /api/documents, /api/auth/*
                │   backend unreachable or unset ──▶ 503. There is NO fallback.
                │
                └─ PUBLIC DEMO    ─▶ TypeScript deterministic pipeline (lib/agents/*)
                    /api/demo/generate-workflow only: anonymous, fixed showcase
                    input, public corpus, persists NOTHING.
```

Both pipelines emit the same `EvidentiaReport` JSON (camelCase), and the frontend
renders either and can print a 6-page A4 playbook.

**No authenticated route has a fallback of any kind.** A report on an
authenticated route belongs to a real account and is persisted to that tenant, so
it may only be produced by a session the backend actually validated:

- Backend unreachable or `EVIDENTIA_BACKEND_URL` unset → **503**, never a locally
  generated report. Cookie *presence* is never treated as proof of a session.
- Authenticated reports and documents live **only in the database**. Nothing
  authenticated is cached in `localStorage`; a backend 404 never falls back to a
  local report. Only `evidentia:public-demo:*` keys may persist in the browser.
- `EVIDENTIA_DB_ENABLED=false` is **refused at startup in production** — without
  the database there is no authentication, no tenancy, and generation cannot keep
  its "200 means saved" promise.

The TypeScript pipeline survives **only** behind `POST /api/demo/generate-workflow`,
which is explicitly anonymous (it never reads session cookies), takes a fixed
showcase input (so it is not a free open-ended LLM endpoint), reads only the public
demo corpus, persists nothing, and is IP-rate-limited.

## Authenticated frontend generation lifecycle

One workspace click creates a session-scoped, non-secret run nonce alongside its
input. `/running` uses that nonce plus the input as the key for an in-memory
single-flight request that exists only while the POST is pending. This lets React
Strict Mode's development setup/cleanup/setup replay subscribe to one request;
settled entries are removed immediately, and a real unmount aborts after a
zero-delay replay grace period. The nonce is purged on login/logout/session loss,
so a flight cannot be reused across sessions; report content is never cached.

Request completion and the seven-stage presentational animation are explicit,
independent state. A dedicated effect navigates once, and only once, after both
the persisted report id and animation completion exist. Effect ownership checks
prevent stale timers or async completions from updating or navigating a newer run.
Retry creates a fresh nonce and therefore a fresh logical request.

## Deterministic-first principle

Within a *single* generation, the deterministic agents produce a complete, grounded
report with no LLM and no network; LLM usage only *refines* that baseline, and each
LLM step falls back to its deterministic output on failure. This is a property of
the pipeline's internals — it keeps generation cheap and evaluation reproducible.

It is **not** a system-level fallback: it does not mean an authenticated request
can be served without the backend, and it never has authority to invent a session.

## Backend pipeline (`backend/app/agents/orchestrator.py`)

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
`EVIDENTIA_TRUSTED_PROXY_COUNT`. Frontend uses `EVIDENTIA_BACKEND_URL` (server-only).

Production refuses to start on: a missing or non-generated `JWT_SECRET`, a
non-generated `EVIDENTIA_BFF_SECRET` (both must be the base64url/hex encoding of
≥32 random bytes), a trusted proxy count > 0 with no BFF secret, the `console`
or `noop` email backend, wildcard CORS, or `EVIDENTIA_DB_ENABLED=false`.
