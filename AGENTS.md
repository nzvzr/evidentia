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

Also useful: `docs/ai/ARCHITECTURE.md` (stable design) and
`docs/ai/DECISIONS.md` (append-only rationale). Product overview: `README.md`
and `backend/README.md`.

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
- **Do not break the public report schema** (`EvidentiaReport`). Add optional
  fields only.
- **Deterministic fallback must always work** with no key and no backend.
- Prefer small, verifiable changes; run `pytest -q` (backend) and `npm run build`
  (frontend) before finishing.
