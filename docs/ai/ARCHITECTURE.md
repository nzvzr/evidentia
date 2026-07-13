# Evidentia — Architecture

_Stable design. Update only when the design itself changes._

## Overview

```
Browser ─▶ Next.js (App Router UI + API routes)
                │
                ├─ EVIDENTIA_BACKEND_URL set ─▶ Python FastAPI backend ─▶ report (+ DB persist)
                │                                        │
                └─ else / on failure ─▶ TypeScript deterministic pipeline (lib/agents/*)
```

Both pipelines emit the same `EvidentiaReport` JSON (camelCase). The frontend
renders it and can print a 6-page A4 playbook. Reports are read from the backend
with a `localStorage` fallback.

## Deterministic-first principle

The deterministic pipeline always produces a complete, grounded report with no
LLM and no network. LLM usage only *refines* that baseline and every LLM step
falls back to deterministic output on any failure. This keeps the demo reliable
and cheap, and makes evaluation reproducible.

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
`personas`, `reports`) with Alembic migrations. `DATABASE_URL` selects PostgreSQL;
unset → local SQLite (`backend/evidentia.db`). Reports store the full report JSON.

## Configuration (backend/.env, never committed)

`OPENAI_API_KEY`, `EVIDENTIA_USE_LLM`, `EVIDENTIA_LLM_PROVIDER`,
`EVIDENTIA_LLM_MODEL`, `EVIDENTIA_LLM_INTENSITY`, `EVIDENTIA_MAX_CONTEXT_CHARS`,
`EVIDENTIA_MAX_OUTPUT_TOKENS`, `EVIDENTIA_ENABLE_CACHE`, `DATABASE_URL`,
`EVIDENTIA_DB_ENABLED`. Frontend uses `EVIDENTIA_BACKEND_URL` (server-only).
