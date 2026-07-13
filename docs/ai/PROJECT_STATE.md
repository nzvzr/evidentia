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
- **Full-mode structural quality gate** (`agents/structural_gate.py`): full mode no
  longer overwrites the deterministic analytical baseline. It preserves the
  baseline, builds the LLM output as a separate candidate, scores both with
  deterministic structural scorers (persona: persona/market/source-topic
  relevance + precision; workflow: evidence support, citation validity, ownership,
  operational completeness, persona relevance, duplicates, unsupported/N-A; risks:
  evidence support, validity, ownership, specificity, duplicates, contradiction
  awareness, severity consistency, unsupported/N-A), reconciles workflow/risk items
  one by one (preserve strong deterministic items, accept genuinely better/new
  grounded items, reject unsupported/weaker/duplicate/generic, never force a count),
  and accepts a component only when its structural score is strictly higher AND
  grounding, citation accuracy, warnings, source-doc mismatch, N/A count, and schema
  validity do not regress. Ties preserve deterministic. Runs *before* grounding
  repair; repair → re-bind → recompute metrics → narrative polish/gate follow.
- Versioned benchmark dataset (`BENCHMARK_VERSION = v1`, 22 scenarios) with
  ground-truth expectations; exports JSON + CSV + repair audit CSV + generation
  audit CSV. Runner supports `--runs N`, `--scenario`/`--category` filters, mean/std
  for quality/latency/cost, win/tie/loss vs deterministic & summary, structural
  regressions before/after gate, full incremental gain vs summary, and cost per
  accepted analytical improvement. Ground-truth match split into four metrics:
  `expectedRiskConceptRecall`, `expectedSourceDocumentMatchRate`,
  `expectedCitationFamilyMatchRate`, `expectedCitationExactMatchRate` (exact
  citation matching retained, not replaced by prefix matching).

## Latest key-enabled benchmark (gpt-4o-mini, v1, 22 scenarios, 2026-07-13)

Full-mode structural gate now runs before repair.

| mode | overall (±std) | grounding | narrative | structural | schema | halluc |
|------|----------------|-----------|-----------|------------|--------|--------|
| deterministic | 93.8 (4.15) | 93.9 | 93.8 | — | 1.0 | 0 |
| summary | 94.9 (3.45) | 93.9 | 95.9 | — | 1.0 | 0 |
| full | 94.4 (3.58) | 93.9 | 95.0 | 76.5 | 1.0 | 0 |

- **Structural gate (full):** baseline structural 67.5 → pure candidate 80.9 →
  **final 76.5** (guardrails held back non-improving/regressing gains).
  **Structural regressions 1 → 0** after the gate; 0 grounding regressions; schema
  1.0. Accepted 27/66 components (50 risk items, 7 workflow items); 39 components
  reverted to deterministic. 0 analytical fallbacks.
- **Full vs deterministic:** win/tie/loss **6/14/2** (0 grounding losses).
  **Full vs summary:** **1/11/10**, incremental gain **−0.48** at ~3.8× cost
  ($0.029 vs $0.0077; cost/accepted-item $0.00051). → Full mode's analytical
  changes are safe but rarely beat summary; **summary remains the default sweet
  spot** and auto-routing should stay conservative about full.
- **Ground-truth match:** exact-citation **0.833**, family **1.0**, document
  **1.0**, risk-concept recall **0.889** (identical across modes — generation is
  deterministic).

## Upstream fix impact (insufficient-evidence before vs after)

- **Before (repair-only):** 31 invalid evidence codes reached repair; 2 replaced,
  **29 marked `N/A`** — i.e. unsupported risks were generated then patched.
- **After (evidence-first):** repair has nothing to fix —
  `ungroundedBeforeRepair = 0`, `repairReplaced = 0`, `repairInsufficient = 0`.
  36 unsupported risk proposals are dropped at the source
  (`sourceDocumentMismatchCount` drives most), and remaining `N/A` items are
  intentional evidence-gap markers, not repaired guesses.

## Tests

- **66 passing** backend unit tests: `python -m pytest -q` (from `backend/` with
  the venv active). Cover the mode router, quality/grounding scoring, narrative
  scoring, the narrative gate, the grounding-repair relevance scorer, evidence-first
  generation / evidence-support scorer, the **structural gate + item reconciliation**
  (`test_structural_gate.py`), and the **four match metrics**
  (`test_expected_match_metrics.py`).

## Open concerns

- **Evidence/structural matching is lexical, not semantic** (support, repair, and
  structural scorers). Deterministic by design for now; next step is category/persona
  affinity refinement or embeddings (still no LLM call).
- **Full mode is not worth its cost** on the current corpus: −0.48 overall vs
  summary at ~3.8× cost, with only 1/22 wins. The structural gate makes it *safe*
  (0 structural/grounding regressions) but auto-routing should keep it rare.
- **Exact-citation match is 0.833** because a risk binds to the highest-signal
  section in its (correct) source document — `document`/`family` match are 1.0. The
  four split metrics now make this distinction explicit.
