# Evidentia Python Backend

A FastAPI implementation of the Evidentia multi-agent pipeline. It mirrors the
TypeScript deterministic pipeline and returns the same `EvidentiaReport` JSON the
Next.js frontend consumes. It runs deterministically with **no API key**, and can
optionally use an LLM (OpenAI) for refinement.

The Next.js API route (`app/api/generate-workflow/route.ts`) is an authenticated
proxy to this backend. It has **no fallback**: if the backend cannot validate the
session, it returns 503 and nothing is generated or saved. The TypeScript pipeline
is reachable only at the anonymous `/api/demo/generate-workflow` (public corpus,
persists nothing).

## Endpoints

- `GET /health` → `{ "status": "ok" }`
- `POST /api/generate-workflow` → an `EvidentiaReport` (persisted to the DB when enabled)
- `GET /api/reports` · `GET /api/reports/{id}` · `POST /api/reports` · `DELETE /api/reports/{id}`
- `GET /api/documents` · `POST /api/documents` (DB documents, else demo corpus)
- `GET /api/personas` · `POST /api/personas` (company + default personas)
- `GET /api/companies` · `POST /api/companies`
- `POST /api/auth/register` · `POST /api/auth/token` (minimal)

Request body:

```json
{
  "market": "EMEA",
  "persona": "Support Agent",
  "customPersona": "",
  "selectedDocumentIds": ["security-compliance-whitepaper", "sla-uptime-commitment"]
}
```

## Run locally (macOS / Linux)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run locally (Windows)

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Database

The backend persists generated reports (and supports documents, personas,
companies, users) via SQLAlchemy 2.x.

The database is the **only** store for authenticated data. Authentication, tenancy
and report persistence all require it — there is no degraded mode and no
`localStorage` fallback.

- **PostgreSQL — required in production.** Set `DATABASE_URL` and run migrations:

```bash
# .env
DATABASE_URL=postgresql://user:password@localhost:5432/evidentia
EVIDENTIA_DB_ENABLED=true
```

- **SQLite (empty `DATABASE_URL`) — local development ONLY.** A local file
  `backend/evidentia.db` is used and tables are created on startup. **Do not run a
  public beta on it:** container filesystems are usually ephemeral, so a redeploy
  silently destroys every user and report. Its concurrency model also differs from
  PostgreSQL's (a whole-database write lock rather than `SELECT … FOR UPDATE` row
  locks).

`EVIDENTIA_DB_ENABLED=false` disables persistence and is **refused at startup in
production**. With it set in development, authenticated generation returns **503
`persistence_unavailable`** rather than an unsaved report — a 200 from
`/api/generate-workflow` always means the report was committed.

### Migrations (Alembic)

```bash
cd backend
source .venv/bin/activate

# create a new migration from model changes
alembic revision --autogenerate -m "your message"

# apply migrations
alembic upgrade head

# roll back one step
alembic downgrade -1
```

The initial migration (`migrations/versions/*_initial_schema.py`) creates the
`users`, `companies`, `company_members`, `documents`, `personas`, and `reports`
tables. For SQLite dev, startup `create_all` also ensures the tables exist.

### Test report persistence

```bash
# generate + save a report
curl -s -X POST http://localhost:8000/api/generate-workflow \
  -H "Content-Type: application/json" \
  -d '{"market":"EMEA","persona":"Support Agent","selectedDocumentIds":["incident-response-runbook"]}' | python -m json.tool

# list saved reports (auto-uses/creates the demo company)
curl -s http://localhost:8000/api/reports | python -m json.tool

# fetch one, then delete it
curl -s http://localhost:8000/api/reports/<id>
curl -s -X DELETE http://localhost:8000/api/reports/<id>
```

## Enable LLM mode (optional)

```bash
cp .env.example .env
# then edit .env:
#   OPENAI_API_KEY=sk-...
#   EVIDENTIA_USE_LLM=true
#   EVIDENTIA_LLM_INTENSITY=summary
```

The backend owns the API keys. They are never returned in responses and never
exposed to the browser. If the LLM call fails, each step falls back to
deterministic output and the request still succeeds.

### LLM intensity (cost control)

`EVIDENTIA_LLM_INTENSITY` controls how much the LLM is used:

| Mode | LLM calls | generationMode | When |
|------|-----------|----------------|------|
| `off` | 0 | `deterministic` | Free, reproducible. Also used whenever no key is set. |
| `summary` | **1** | `llm-summary` | **Recommended.** Deterministic pipeline runs, then one call polishes the summary, top finding, suggested actions, and (optionally) the persona brief. |
| `full` | ≤ 3 | `llm-assisted` | Demos/testing. One call for persona + workflow, one for risks, one for the final narrative. |

Cost controls:

- The LLM receives a compact **evidence pack** (top risks, workflow titles, top 5 citations, metrics) — never the full documents in summary mode. Full mode sends only ranked top sections, capped by `EVIDENTIA_MAX_CONTEXT_CHARS`.
- Output is bounded by `EVIDENTIA_MAX_OUTPUT_TOKENS` (summary mode is capped to 500).
- Repeated identical requests are served from an in-memory cache (`EVIDENTIA_ENABLE_CACHE=true`) — no extra LLM calls.
- Outputs are validated for precision (no vague/marketing phrasing, no corruption); failing fields keep the deterministic baseline. Citations are always grounded in the local corpus.

Each request logs a usage line (no keys), e.g.:

```
[Evidentia LLM] intensity=summary->summary calls=1 model=gpt-4o-mini contextChars=4120 mode=llm-summary
```

### Auto mode (calibrated conservative router)

Set `EVIDENTIA_LLM_INTENSITY=auto` to let the pipeline pick `off`/`summary`/`full`
per request from **pre-LLM deterministic signals only** (`app/agents/mode_router.py`):
deterministic structural & narrative scores, document complexity, contradictions,
persona complexity, deterministic confidence, citation coverage, grounded risk/step
counts, dropped risks, insufficient-evidence items, source-document mismatch, and
evidence-support avg/min.

The router is **calibrated from the benchmark** (see `docs/ai/DECISIONS.md`):

- **summary** is the default (reliable, cheap narrative polish);
- **off** only when the deterministic baseline is already strong;
- **full** only when there is a clear deterministic analytical weakness AND
  sufficient selected-document evidence AND ≥2 independent opportunity signals AND
  predicted incremental gain > `EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD` (default 0.2).

A custom persona, a single contradiction, a large corpus, or a slightly-low
confidence never force full; ties prefer the cheaper/faster mode. On the current v1
corpus the oracle gain of routing over always-summary is only +0.12 and full is
Pareto-dominated, so auto resolves to summary everywhere and full stays a manual
mode. Every run emits routing telemetry (`routingReason`, `routingSignals`,
`routingConfidence`, `predictedIncrementalGain`, `selectedMode`, `alternativeMode`,
`fullEligibilityChecks`). The existing `off`/`summary`/`full` modes are unchanged.

Run `python scripts/calibrate_router.py` to reproduce the oracle analysis, policy
comparison (always-{deterministic,summary,full}, previous auto, proposed, oracle),
threshold grid search, and leave-one-category-out validation.

## LLM evaluation & calibration benchmark

A versioned benchmark (`app/eval/`) runs the pipeline across intensity modes over
a dataset of representative scenarios (`app/eval/dataset.py`, `BENCHMARK_VERSION`)
covering standard personas, custom personas, conflicting documents, insufficient
evidence, prompt-injection attempts, and high-risk compliance cases.

Each scenario carries ground-truth expectations (expected evidence codes, action
concepts, forbidden claims, summary facts). For every scenario × mode it records
two independent score axes plus their blend, so LLM narrative improvements are
measured without weakening grounding:

- **groundingScore** — schema validity, citation accuracy, citation coverage, and
  hallucination/injection warnings (unchanged by summary mode).
- **narrativeUtilityScore** — the fields summary mode rewrites: summary factual
  consistency, summary completeness (persona, market, real doc/risk/citation
  counts, top-risk concept + its evidence code, ≥2 top workflow steps), concision,
  persona/market relevance (evaluated on the actual summary + persona brief +
  actions, not the deterministic pre-polish score), action usefulness (operational
  verb + concrete object + link to a real risk/step/citation), action alignment,
  and a vague/repetition penalty.
- **overallQualityScore** — a 50/50 blend, plus **delta vs deterministic** per
  scenario (overall and narrative).

It also records latency, token usage, estimated cost, provider, model, prompt
version, cache status, and change telemetry (`reportChanged`, whether the summary
/ persona brief changed, number of accepted LLM actions, and whether the LLM
response fell back entirely).

### Calibration safeguards

- **Full-mode structural quality gate** (`agents/structural_gate.py`). Full mode
  keeps the complete deterministic analytical baseline (persona brief, workflow,
  risks, citations, metrics, evidence-support telemetry, contradictions) and builds
  the LLM output as a *separate candidate*. Deterministic structural scorers grade
  persona (persona/market/source-topic relevance + precision), workflow and risks
  (evidence support, citation validity, source-document ownership, operational
  completeness / risk specificity, duplicates, contradiction awareness, severity
  consistency, unsupported/N-A counts). Workflow and risk items are reconciled one
  by one — strong deterministic items are preserved, genuinely better or new
  grounded items accepted, unsupported/weaker/duplicate/generic items rejected, and
  no filler is added to hit a count. A component (personaBrief, workflowSteps,
  risks) is accepted only when its structural score is strictly higher AND
  grounding, citation accuracy, warnings, source-document mismatch, N/A count and
  schema validity do not regress; ties preserve deterministic. The gate runs before
  grounding repair. Telemetry: `deterministic/candidate/finalStructuralScore`,
  `structuralGateDecision`, accepted/rejected components + item counts,
  `structuralRejectionReasons`, `fullModeAnalyticalFallback`. The benchmark reports
  win/tie/loss vs deterministic & summary, structural regressions before/after the
  gate, full incremental gain vs summary, and cost per accepted improvement
  (`--runs N`, `--scenario`/`--category` filters, mean/std for quality/latency/cost).
- **Source-constrained (evidence-first) generation** runs upstream of repair.
  `risk_analyzer` and `workflow_builder` derive each risk/step from a *selected*
  source section rather than picking a generic item and citing it afterward. A
  deterministic **evidence-support scorer** (`tools/evidence_support.py`, separate
  from repair) scores a candidate section by selected-document ownership,
  risk/workflow vocabulary, exact domain phrases, category affinity, persona and
  market relevance, and negation/contradiction markers. A risk is grounded only
  when a section it *owns* clears `EVIDENTIA_MIN_EVIDENCE_SUPPORT` (default 2 — i.e.
  ≥2 signal terms or a domain phrase); unsupported risks are dropped (never
  filler-filled), and one explicit evidence-gap risk is emitted only when the
  missing documentation is itself operationally relevant. Internal provenance
  (`sourceDocumentId`, `sourceCitationId`, `matchedSignals`, `generationReason`)
  is exported in telemetry/`*.gen-audit.csv` only — never in the public report.
  The benchmark reports `risksGeneratedBeforeFiltering`, `groundedRisksKept`,
  `unsupportedRisksDropped`, workflow equivalents, `insufficientEvidenceItemsFinal`,
  `sourceDocumentMismatchCount`, `evidenceSupportScore` avg/min, and
  `expectedRiskRecall`. Use `python scripts/run_benchmark.py --print-generation`
  to inspect every dropped/transformed item.
- **Deterministic grounding repair** runs before report assembly (both deterministic
  and LLM paths): every workflow/risk `evidenceCode` is validated against the
  citation IDs of the selected documents; invalid codes are replaced using an
  **IDF-weighted relevance scorer** (generic terms downweighted; exact multi-word
  phrase bonus; section-title matches weighted above excerpt; configurable
  `EVIDENTIA_REPAIR_MIN_RELEVANCE`, default 2.0; requires ≥2 meaningful matched
  terms unless a strong phrase matches). If nothing clears the threshold the item
  is marked `N/A` (insufficient evidence) — never the least-bad citation. Citations
  are re-bound afterward. Every repair emits an audit record (matched terms/phrases,
  relevance score, top-3 candidates, decision) exported in benchmark JSON and a
  `*.audit.csv` — never in the public report. The benchmark reports
  `ungroundedBeforeRepair`/`ungroundedAfterRepair`, `validReplacementRate`,
  `expectedEvidenceMatchRate`, `insufficientEvidenceRate`, `lowConfidenceRepairRate`,
  and `averageRepairRelevanceScore`. Use
  `python scripts/run_benchmark.py --print-repairs` to inspect every repair.
- **Field-level narrative gate**: LLM polish is applied per field (summary,
  persona-brief description, suggested actions). A candidate field is accepted only
  if its field-level narrative score is *strictly* better AND factual consistency
  does not drop AND grounding does not drop AND hallucination/injection warnings do
  not increase; ties preserve the deterministic field. Telemetry: `acceptedFields`,
  `rejectedFields`, `rejectionReasons`, `deterministicNarrativeScore`,
  `candidateNarrativeScore`, `finalNarrativeScore`, `narrativeGateDecision`. The
  benchmark reports narrative regressions before vs after the gate and the field
  acceptance rate.

Exported narrative sub-metrics: `summaryFactualConsistency`, `summaryCompleteness`,
`summaryConcision`, `personaMarketRelevance`, `actionUsefulness`,
`actionEvidenceAlignment`, `vagueLanguagePenalty`, `repetitionPenalty`.

Run it and export JSON + CSV:

```bash
cd backend
source .venv/bin/activate

# default: deterministic, summary, full
python scripts/run_benchmark.py

# include the auto router and choose an output directory
python scripts/run_benchmark.py --modes deterministic,summary,full,auto --out-dir benchmark_results
```

- With **no key / `EVIDENTIA_USE_LLM=false`**, all modes produce deterministic
  output (0 tokens, $0) — useful to validate the harness for free.
- With a key + `EVIDENTIA_USE_LLM=true`, `summary`/`full` make real calls and the
  report shows token usage, cost, and quality differences between modes.

**Comparing configurations:** run the benchmark under each config (e.g. different
`EVIDENTIA_LLM_MODEL`, `EVIDENTIA_MAX_CONTEXT_CHARS`, or prompt version), then diff
the per-mode `summary` block in the JSON (avg quality score, schema-valid rate,
avg hallucination warnings, total tokens, total estimated cost, avg latency). The
CSV has one row per scenario × mode for spreadsheet pivots.

Benchmark outputs are written to `--out-dir` (git-ignored) as
`benchmark_<version>_<timestamp>.json` and `.csv`.

### Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest -q          # includes mode-router and quality-scoring unit tests
```

## Wire the frontend to the backend

In the repo root, create `.env.local`:

```
EVIDENTIA_BACKEND_URL=http://localhost:8000
```

With that set, the Next.js route forwards requests to this backend. Without it
the frontend returns 503 for authenticated generation — there is no fallback. The
TypeScript pipeline is reachable only at the anonymous `/api/demo/generate-workflow`.
