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
- Versioned benchmark dataset (`BENCHMARK_VERSION = v1`, 22 scenarios) with
  ground-truth expectations; exports JSON + CSV + repair audit CSV + generation
  audit CSV (dropped/transformed items).

## Latest key-enabled benchmark (gpt-4o-mini, v1, 2026-07-13)

Source-constrained generation now runs upstream of repair.

| mode | overall | grounding | narrative | citation acc | schema valid |
|------|---------|-----------|-----------|--------------|--------------|
| deterministic | 93.8 | 93.9 | 93.8 | 1.0 | 1.0 |
| summary | 95.0 | 93.9 | 96.1 | 1.0 | 1.0 |

Generation (identical across modes — generation is deterministic; summary only
polishes narrative): 80 risks proposed → **44 grounded / 36 unsupported dropped**;
27 final insufficient-evidence items (deliberate evidence-gap risks + unsupported
workflow steps); avg evidence-support 11.57, min 9.0; **expected-risk recall
0.833**; 0 hallucination warnings; summary cost $0.0076.

## Upstream fix impact (insufficient-evidence before vs after)

- **Before (repair-only):** 31 invalid evidence codes reached repair; 2 replaced,
  **29 marked `N/A`** — i.e. unsupported risks were generated then patched.
- **After (evidence-first):** repair has nothing to fix —
  `ungroundedBeforeRepair = 0`, `repairReplaced = 0`, `repairInsufficient = 0`.
  36 unsupported risk proposals are dropped at the source
  (`sourceDocumentMismatchCount` drives most), and remaining `N/A` items are
  intentional evidence-gap markers, not repaired guesses.

## Tests

- **53 passing** backend unit tests: `python -m pytest -q` (from `backend/` with
  the venv active). Cover the mode router, quality/grounding scoring, narrative
  scoring, the narrative gate, the grounding-repair relevance scorer, and the new
  evidence-first generation / evidence-support scorer (`test_evidence_grounding.py`).

## Open concerns

- **Evidence matching is lexical, not semantic** (both the support scorer and the
  repair scorer). Deterministic by design for now; next step is category/persona
  affinity refinement or embeddings (still no LLM call). The generation audit CSV
  surfaces every dropped/transformed item for inspection.
- **Expected-risk recall is 0.833, not 1.0**, because grounding now binds a risk to
  the *highest-signal* section in its source document, which can differ from the
  ground-truth section id (e.g. `INC-9.1` vs expected `INC-2.1`) — the risk is
  still correctly grounded to the right document. Ground-truth section ids could be
  broadened to a prefix match if exact recall is desired.
