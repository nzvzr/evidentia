# Evidentia — Project State

_Concise snapshot. Update after meaningful changes. Last updated: 2026-07-13._

## Summary

Persona-aware documentation agent. Next.js frontend + Python FastAPI backend.
Deterministic-first pipeline; optional LLM refinement layered on top.

## Components

- **Frontend** (`app/`, `components/`, `lib/`, `data/`): landing, `/workspace`,
  `/running`, `/reports` + `/reports/[id]`, `/playbooks`, `/documents`,
  `/playbook/[id]/print`. Reads reports from the backend with `localStorage` fallback.
  The `/running` loader shows honest pipeline stages (no fake %), gates completion
  on the real result, and has timeout/slow/fallback/error states. The report UI and
  print playbook render insufficient-evidence (`N/A`) items as a distinct
  "INSUFFICIENT EVIDENCE" marker, use a 3-colour severity scale, and handle empty
  risk/workflow/citation states. The PDF flows long sections across pages
  (no clipping).
- **Next.js API** (`app/api/generate-workflow`, `app/api/reports[...]`): proxies to
  the Python backend when `EVIDENTIA_BACKEND_URL` is set; otherwise runs the
  TypeScript deterministic pipeline (`lib/agents/*`).
- **Python backend** (`backend/app/`): FastAPI multi-agent pipeline + PostgreSQL/
  SQLite persistence (SQLAlchemy 2.x + Alembic) + LLM evaluation framework (`app/eval/`).

## LLM modes (`EVIDENTIA_LLM_INTENSITY`)

- `off` — deterministic only, 0 LLM calls (`generationMode: deterministic`).
- `summary` — deterministic + 1 LLM call to polish narrative (`llm-summary`). Default.
- `full` — deterministic + ≤3 LLM calls (`llm-assisted`).
- `auto` — **calibrated conservative router** (`agents/mode_router.py`). Routes from
  pre-LLM deterministic signals only. Summary is the default; `off` only when the
  baseline is already strong; `full` requires BOTH a clear deterministic analytical
  weakness AND sufficient selected-document evidence AND ≥2 independent
  opportunity signals AND predicted incremental gain > `EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD`.
  A custom persona, a single contradiction, a large corpus, or a slightly-low
  confidence never force full. On the v1 benchmark this resolves every scenario to
  summary (see calibration below); full stays a manual mode.

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

| mode | overall (±std) | grounding | narrative | structural | latency | cost |
|------|----------------|-----------|-----------|------------|---------|------|
| deterministic | 93.8 (4.15) | 93.9 | 93.8 | — | ~1 ms | $0 |
| summary | 95.4 (3.10) | 93.9 | 96.9 | — | 5.4 s | $0.0078 |
| full | 94.8 (3.29) | 93.9 | 95.7 | 77.0 | 24.1 s | $0.0295 |
| auto | 94.9 (3.76) | 93.9 | 96.0 | — | 5.2 s | $0.0077 |

Schema-valid 1.0 and 0 hallucination warnings in every mode. `auto` routes all 22
scenarios to summary (its numbers differ from the summary row only by LLM run-to-run
variance).

- **Structural gate (full):** baseline structural 67.5 → pure candidate ~80.9 →
  **final 77.0** (guardrails held back non-improving/regressing gains).
  **Structural regressions 0 after gate** (1 → 0 in a prior run); 0 grounding
  regressions; schema 1.0. Accepted 27/66 components (59 items); rest reverted to
  deterministic. 0 analytical fallbacks.
- **Full vs deterministic:** win/tie/loss **5/15/2** (0 grounding losses).
  **Full vs summary:** **2/8/12**, incremental gain **−0.54** at ~3.8× cost
  ($0.0295 vs $0.0078; cost/accepted-item $0.0005). → Full mode's analytical
  changes are safe but rarely beat summary; **summary remains the default sweet
  spot** and auto-routing should stay conservative about full.
- **Ground-truth match:** exact-citation **0.833**, family **1.0**, document
  **1.0**, risk-concept recall **0.889** (identical across modes — generation is
  deterministic).

## Router calibration (oracle + policy search, v1)

`scripts/calibrate_router.py` (offline) computes an oracle upper bound and compares
policies before tuning any threshold. Verified on the 4-mode benchmark:

- **Oracle** (best per-scenario mode, ε=0.2 ties preferring cheaper): avg overall
  **95.47** vs always-summary **95.36** → **gain only +0.12** (< 0.2). Oracle picks
  full in just **2/22** scenarios; **full is Pareto-dominated** (frontier =
  {deterministic, summary}).
- **Policy comparison:** always-summary 95.36 (cost $0.0078, worst-regression 0.0,
  constraints ✓); **previous aggressive auto 95.02** (worse than summary, cost
  $0.0259, worst-regression 2.8, routed 18/22 to full, constraints ✗);
  **proposed calibrated router = always-summary** (routes 22/22 → summary,
  constraints ✓). No `full_gain_threshold` in {0.0…1.0} beats summary by 0.2.
- **Leave-one-category-out:** every held-out category picks threshold 0.0, gain 0.0
  — the router generalizes (not overfit to scenario IDs).
- **Verdict:** benchmark evidence does **not** justify automatic full routing. Auto
  resolves to summary by default; full is kept as an explicit manual mode. The
  conservative full-eligibility mechanism exists and is unit-tested, but its
  conjunction never fires on the current corpus.

## Upstream fix impact (insufficient-evidence before vs after)

- **Before (repair-only):** 31 invalid evidence codes reached repair; 2 replaced,
  **29 marked `N/A`** — i.e. unsupported risks were generated then patched.
- **After (evidence-first):** repair has nothing to fix —
  `ungroundedBeforeRepair = 0`, `repairReplaced = 0`, `repairInsufficient = 0`.
  36 unsupported risk proposals are dropped at the source
  (`sourceDocumentMismatchCount` drives most), and remaining `N/A` items are
  intentional evidence-gap markers, not repaired guesses.

## Demo release-readiness (frontend/PDF pass, verified 2026-07-13)

Product-facing pass over the generation flow (schema, deterministic fallback,
summary-as-default, full-as-manual, and all backend safeguards preserved):

- **Loading** (`app/running/page.tsx`): honest stage-segmented progress (removed the
  fake percentage and fabricated per-agent counts), completion gated on the real
  report, plus slow-notice (22s), local-fallback + hard-timeout (60s), and an error
  state with retry.
- **Insufficient evidence**: `evidenceCode === "N/A"` now renders as a distinct
  dashed "INSUFFICIENT EVIDENCE" marker (web report + PDF risk register + workflow),
  not a normal citation chip.
- **Report UI**: 3-colour severity scale (High/Med/Low), citation `section` shown,
  empty states for risks/workflow/citations.
- **PDF**: variable-length sections (`.print-flow`) flow across pages instead of
  clipping at a fixed 297 mm; metadata footer per section; dynamic agent count +
  next-review date (no stale hardcoded values).
- **Showcase scenario** `showcase-residency-emea` (Compliance · EMEA, 4 docs) seeds
  the library end-to-end.
- **Verified E2E** (Next `/api/generate-workflow` → Python backend, gpt-4o-mini
  summary): showcase → 3 risks (RES-14/SEC-4.2 High, SLA-5 Med), 5 steps, 8 cited
  sections, HTTP 200 ~7.5 s; insufficient corpus (support · pricing-only) → 1
  evidence-gap risk + 3 `N/A` steps rendered as insufficient-evidence. `next lint`,
  `next build`, `tsc --noEmit` clean; all report/print/workspace/documents pages 200.

## Tests

- **68 passing** backend unit tests: `python -m pytest -q` (from `backend/` with
  the venv active). Cover the **calibrated conservative router** (`test_mode_router.py`),
  quality/grounding scoring, narrative scoring, the narrative gate, the
  grounding-repair relevance scorer, evidence-first generation / evidence-support
  scorer, the structural gate + item reconciliation, and the four match metrics.

## Open concerns

- **Evidence/structural matching is lexical, not semantic** (support, repair, and
  structural scorers). Deterministic by design for now; next step is category/persona
  affinity refinement or embeddings (still no LLM call).
- **Auto never routes to full on the current corpus** (calibration verdict: full is
  Pareto-dominated, oracle gain only +0.12). This is intentional; full stays a manual
  mode. Re-run `scripts/calibrate_router.py` if the corpus/model changes — the
  conservative full-eligibility mechanism will start selecting full when the evidence
  justifies it.
- **Exact-citation match is 0.833** because a risk binds to the highest-signal
  section in its (correct) source document — `document`/`family` match are 1.0. The
  four split metrics now make this distinction explicit.
