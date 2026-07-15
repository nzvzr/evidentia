# Evidentia — Agent Guide

Entry point for AI agents (Cursor or otherwise) working on this repository. It
lets a fresh conversation continue without relying on prior chat history.

## What Evidentia is

A persona-aware documentation agent that turns static enterprise documentation
into role-specific, cited playbooks (workflows, risks, metrics, exportable PDF).

- **Frontend**: Next.js (App Router) + TypeScript + Tailwind, in `app/`, `components/`, `lib/`, `data/`.
- **Backend**: Python FastAPI multi-agent pipeline in `backend/`.
- **Deterministic-first**: the pipeline always produces a complete report with no
  LLM. LLM usage is optional and only *refines* the deterministic baseline.

## Read before substantial work

1. `docs/ai/PROJECT_STATE.md` — current status, modes, latest benchmark, tests.
2. `docs/ai/SESSION_HANDOFF.md` — what changed last, open concerns, next steps.

Also useful: `docs/ai/PLATFORM_ARCHITECTURE.md` (**the platform-level
architectural source of truth** — layers, CAD, domain modules, typed
contracts, provenance, milestone gates), `docs/ai/ARCHITECTURE.md` (the
currently implemented system) and `docs/ai/DECISIONS.md` (append-only
rationale). Product overview: `README.md` and `backend/README.md`.

## Update after meaningful implementation

After a non-trivial change, update:
- `docs/ai/PROJECT_STATE.md` (keep it concise) and `docs/ai/SESSION_HANDOFF.md` (< 100 lines).
- `docs/ai/DECISIONS.md` — append a new entry (never rewrite past entries).
- `docs/ai/ARCHITECTURE.md` — only when the stable design changes.

## Commands

```bash
# frontend
npm install && npm run dev          # http://localhost:3000
npm run build

# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
python -m pytest -q                 # unit tests (39 passing)
python scripts/run_benchmark.py --modes deterministic,summary,full,auto
```

## Guardrails

- **No secrets in the repo.** `backend/.env` is local and git-ignored; use
  `backend/.env.example`. Never commit API keys or `*.db`.
- **Do not break the public report schema** (`EvidentiaReport`) — and do not
  casually extend it either. Every proposed new field must first answer: is
  this a CAD concept, a domain-module extension, or a renderer concern?
  (`docs/ai/PLATFORM_ARCHITECTURE.md` §2). `EvidentiaReport` is the CAD's
  compatibility projection; unreviewed additions deepen the eventual
  projection. Provenance and telemetry belong in DB metadata
  (`source_versions`, `engine_versions`), never in the public schema.
- **Engine code must never branch or string-match on a specific taxonomy
  label** (e.g. `Security`, `Compliance`, `Pricing`). Taxonomies, signatures,
  personas and claim patterns are versioned domain-module data
  (`docs/ai/PLATFORM_ARCHITECTURE.md` §3).
- **Authenticated routes require the backend — never add a fallback to one.** A
  report on an authenticated route belongs to a real account and is persisted to
  that tenant, so it may only come from a session the backend validated. Backend
  unreachable or unset → **503**. Never serve a locally generated report, never
  read authenticated data from `localStorage`, and never treat cookie *presence*
  as proof of a session.
- **The deterministic fallback is a property of the pipeline, not of the system.**
  Within one generation, each LLM step falls back to its deterministic output. That
  is all it means. The TypeScript pipeline is reachable **only** at
  `/api/demo/generate-workflow` (anonymous, fixed input, public corpus, persists
  nothing) and must stay that way.
- Prefer small, verifiable changes; run `pytest -q` (backend) and `npm run build`
  (frontend) before finishing.
