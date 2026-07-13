# Evidentia — Project State

_Concise snapshot. Update after meaningful changes. Last updated: 2026-07-13._

## Summary

Persona-aware documentation agent. Next.js frontend + Python FastAPI backend.
Deterministic-first pipeline; optional LLM refinement layered on top.

## Components

- **Frontend** (`app/`, `components/`, `lib/`, `data/`): landing, `/workspace`,
  `/running`, `/reports` + `/reports/[id]`, `/playbooks`, `/documents`,
  `/playbook/[id]/print`. Reads reports from the backend with `localStorage` fallback.
- **Next.js API** (`app/api/generate-workflow`, `app/api/reports[...]`): proxies to
  the Python backend when `EVIDENTIA_BACKEND_URL` is set; otherwise runs the
  TypeScript deterministic pipeline (`lib/agents/*`).
- **Python backend** (`backend/app/`): FastAPI multi-agent pipeline + PostgreSQL/
  SQLite persistence (SQLAlchemy 2.x + Alembic) + LLM evaluation framework (`app/eval/`).

## LLM modes (`EVIDENTIA_LLM_INTENSITY`)

- `off` — deterministic only, 0 LLM calls (`generationMode: deterministic`).
- `summary` — deterministic + 1 LLM call to polish narrative (`llm-summary`). Default.
- `full` — deterministic + ≤3 LLM calls (`llm-assisted`).
- `auto` — router picks off/summary/full from document complexity, contradictions,
  citation coverage, persona complexity, deterministic confidence.

Currently benchmarked model: **gpt-4o-mini**. Keys live only in `backend/.env`
(git-ignored); the app works fully offline with no key.

## Calibration framework (`backend/app/eval/`)

- **Two score axes**: `groundingScore` (schema, citation accuracy/coverage,
  hallucination/injection warnings) and `narrativeUtilityScore` (summary factual
  consistency, completeness, concision, persona/market relevance, action
  usefulness, action-evidence alignment, vague/repetition penalties). `overallQualityScore`
  is a 50/50 blend.
- **Field-level narrative gate**: accepts an LLM field (summary / personaBrief.description /
  suggestedActions) only if it is strictly better AND factual consistency and
  grounding do not drop AND warnings do not increase; ties preserve deterministic.
- **Deterministic grounding repair**: validates every workflow/risk `evidenceCode`
  against selected-document citation IDs; replaces invalid codes with a relevant
  citation or marks `N/A` (insufficient evidence) — never invents. Then re-binds.
- Versioned benchmark dataset (`BENCHMARK_VERSION = v1`, 22 scenarios) with
  ground-truth expectations; exports JSON + CSV.

## Latest live benchmark (gpt-4o-mini, v1)

| mode | overall | grounding | narrative |
|------|---------|-----------|-----------|
| deterministic | 93.9 | 93.9 | 93.9 |
| summary | 95.5 | 93.9 | 97.1 |

- Narrative regressions: **2 before gate, 0 after gate**.
- Field acceptance rate: **25.8%**.
- Ungrounded evidence codes: **31 before repair, 0 after**.
- Cost: **22 LLM calls, $0.008164**.

## Tests

- **39 passing** backend unit tests: `python -m pytest -q` (run from `backend/`
  with the venv active). Cover the mode router, quality/grounding scoring,
  narrative scoring, the narrative gate, and grounding repair.

## Open concerns

- **Semantic relevance of repaired citations**: the deterministic grounding repair
  picks a replacement citation by keyword overlap, which is coarse. A repaired
  code is valid but may not be the *most* relevant source. See
  `docs/ai/SESSION_HANDOFF.md` for next steps.
