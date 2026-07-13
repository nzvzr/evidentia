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
- **Deterministic grounding repair** (`tools/citation_tools.py`): validates every
  workflow/risk `evidenceCode` against selected-document citation IDs; replaces
  invalid codes using an **IDF-weighted relevance scorer** (generic terms
  downweighted, exact multi-word phrase bonus, section-title matches weighted above
  excerpt, configurable `EVIDENTIA_REPAIR_MIN_RELEVANCE`, ≥2 meaningful matched
  terms unless a strong phrase). If nothing clears the threshold the item is marked
  `N/A` (insufficient evidence) — never the least-bad citation. Every repair emits
  an audit record (matched terms/phrases, relevance score, top-3 candidates); audit
  is exported in benchmark JSON/CSV but never in the public report.
- Versioned benchmark dataset (`BENCHMARK_VERSION = v1`, 22 scenarios) with
  ground-truth expectations; exports JSON + CSV.

## Last key-enabled benchmark (gpt-4o-mini, v1)

| mode | overall | grounding | narrative |
|------|---------|-----------|-----------|
| deterministic | 93.9 | 93.9 | 93.9 |
| summary | 95.5 | 93.9 | 97.1 |

Narrative regressions 2 → 0 after gate; field acceptance 25.8%; ungrounded 31 → 0;
22 LLM calls, $0.008164. (Requires `OPENAI_API_KEY`; not present in fresh VMs.)

## Latest deterministic verification (2026-07-13, keyless)

Repair scorer hardened (IDF + phrases + threshold). Deterministic benchmark (22
scenarios; summary/full degrade to deterministic without a key):

- overall **94.2**, narrative **94.6**, schema-valid rate **1.0**.
- Grounding repair: **31 ungrounded → 0**; **2 replaced** (avg relevance 8.615,
  `validReplacementRate` 1.0), **29 marked insufficient** (`insufficientEvidenceRate`
  0.935); `lowConfidenceRepairRate` 0.0; `expectedEvidenceMatchRate` 0.0.
- The stricter scorer now honestly marks unsupported risks `N/A` instead of
  force-mapping them (the old scorer replaced all 31 with least-bad matches).

## Tests

- **44 passing** backend unit tests: `python -m pytest -q` (from `backend/` with
  the venv active). Cover the mode router, quality/grounding scoring, narrative
  scoring, the narrative gate, and the grounding-repair relevance scorer.

## Open concerns

- **Repaired-citation relevance is lexical, not semantic.** The IDF + phrase scorer
  is much stricter (only 2 of 31 replaced), but a residual cross-topic match is
  still possible when two meaningful terms coincide (e.g. a rollback/migration risk
  matched a pricing "Plan Tiers" section via `deployment`, `plan`). The audit trail
  surfaces these. Next step: category/persona-aware affinity or embeddings (no LLM
  call). Also consider tightening `risk_analyzer` so it doesn't select risks whose
  source document isn't in the selected corpus (drives most `insufficient` markers).
