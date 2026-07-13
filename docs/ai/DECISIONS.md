# Evidentia — Decision Log

Append-only. Newest at the bottom. Do not edit or remove past entries; supersede
them with a new entry instead.

---

### 2026-07 · Deterministic-first pipeline
Reports are generated deterministically (rule-based agents over a local demo
corpus) with no LLM required. Rationale: reliable hackathon demo, reproducible
evaluation, zero cost by default. LLM is strictly an optional refinement layer.

### 2026-07 · Frontend + backend with proxy and fallback
Kept the Next.js deterministic pipeline and added a Python FastAPI backend. The
Next.js API route proxies to the backend when `EVIDENTIA_BACKEND_URL` is set and
falls back to the TypeScript pipeline otherwise. Rationale: real backend without
breaking the existing demo or coupling the frontend to Python.

### 2026-07 · Backend owns LLM keys
API keys live only in `backend/.env` (git-ignored). The frontend never sees keys;
`NEXT_PUBLIC_*` is never used for secrets. Rationale: security.

### 2026-07 · LLM intensity modes off/summary/full + auto
`EVIDENTIA_LLM_INTENSITY` controls cost/quality. `summary` (1 call) is the default
and recommended mode; `full` (≤3 calls) is for demos; `auto` routes per request
from deterministic-baseline signals. Rationale: control cost while allowing
higher-effort refinement where it helps. Benchmarked model: gpt-4o-mini.

### 2026-07 · Compact evidence pack + output validation
LLM prompts receive a compact, grounded evidence pack (not full documents),
token-capped, with an enterprise-analyst system prompt. Outputs are validated for
precision (no vague/marketing language); failing fields keep the deterministic
baseline. Rationale: cheaper, more precise, grounded output.

### 2026-07 · Separate grounding vs narrative scoring
Evaluation splits `groundingScore` (schema, citations, hallucination/injection)
from `narrativeUtilityScore` (the fields summary mode rewrites), blended into
`overallQualityScore`. Rationale: deterministic and summary modes previously
scored identically because metrics only measured grounding.

### 2026-07 · Field-level narrative quality gate
LLM polish is accepted per field only if strictly better and non-regressing on
factual consistency, grounding, and warnings; ties preserve deterministic.
Rationale: prevent LLM regressions (observed e.g. custom-dpo-emea) while keeping
genuine improvements.

### 2026-07 · Deterministic grounding repair
Before assembly, invalid `evidenceCode`s are replaced with a semantically relevant
valid citation or marked `N/A` (insufficient evidence) — never invented — then
citations are re-bound. Metrics treat the `N/A` sentinel as honest, not ungrounded.
Rationale: deterministic reports contained ungrounded evidence codes (31 → 0).
Open follow-up: relevance selection is keyword-based and coarse (see PROJECT_STATE).

### 2026-07-13 · Hardened grounding-repair relevance scorer
Replaced the one-token-overlap repair heuristic (which accepted any positive
lexical overlap) with a deterministic **IDF-weighted scorer**: generic terms
downweighted, exact multi-word phrases rewarded, section-title matches weighted
above excerpt, a configurable minimum-relevance threshold
(`EVIDENTIA_REPAIR_MIN_RELEVANCE`), and a ≥2-meaningful-terms rule unless a strong
phrase matches. Below threshold → `N/A` (insufficient evidence), never the
least-bad citation. Added a per-repair audit trail (matched terms/phrases,
relevance score, top-3 candidates, decision) exported in benchmark JSON/CSV only.
Result: of 31 invalid deterministic codes, 2 are replaced with relevant citations
and 29 are honestly marked insufficient (previously all 31 were force-mapped).
Rationale: a valid citation ID must actually support its item; no LLM/embeddings
yet. Known residual: scorer is lexical, so rare cross-topic matches remain (audit
surfaces them); consider category/persona affinity or embeddings next.

### 2026-07-13 · Source-constrained (evidence-first) risk & workflow generation
Fixed the upstream cause of the 29 `N/A` markers. Previously `risk_analyzer` chose
generic risks from a static pool and attached evidence afterward, so most risks
had no supporting *selected* document and were later marked insufficient by repair.
Now generation is evidence-first: a new deterministic **evidence-support scorer**
(`tools/evidence_support.py`, separate from repair) scores a candidate section by
selected-document ownership, risk/workflow-specific vocabulary, exact domain
phrases, document-category affinity, persona relevance, market relevance, and
negation/contradiction markers. A risk is emitted grounded only when a section it
*owns* clears `EVIDENTIA_MIN_EVIDENCE_SUPPORT` (≥2 signals or a domain phrase);
unsupported risks are dropped, never filler-filled to a count. One explicit
evidence-gap risk (`N/A`) is emitted only when the missing documentation is itself
operationally relevant to the persona. `workflow_builder` applies the same
principle (preferred/topical section, else evidence-gap step). Both agents now
return `(items, gen_info)` carrying internal provenance (`sourceDocumentId`,
`sourceCitationId`, `matchedSignals`, `generationReason`) and a drop/transform
audit — provenance stays in telemetry and never enters the public report schema.
`metrics.validate_schema` was relaxed (risks ≤6, workflow 1–6) so honest low
counts pass; this is backward compatible with existing 3–5 / 4–6 reports. Result
(gpt-4o-mini, v1): repair now sees **0 invalid codes** (was 31); 80 risks proposed
→ 44 grounded, 36 dropped at source; expected-risk recall 0.833; grounding 93.9,
overall deterministic 93.8 / summary 95.0. Rationale: a grounded risk must be
derived from evidence the report actually cites, not patched after the fact; kept
fully deterministic (no LLM/embeddings). Residual: matching is still lexical.

### 2026-07-13 · Full-mode structural quality gate + item reconciliation
Summary mode had a field-level narrative gate, but full mode replaced the
deterministic persona brief, workflow steps and risks outright, with grounding
repair only validating citation ids afterward — no proof the analytical changes
were actually better. Added a deterministic structural gate (`agents/
structural_gate.py`) that (1) preserves the complete deterministic analytical
baseline, (2) builds the LLM output as a separate candidate, (3) scores persona,
workflow and risks with dedicated deterministic structural scorers (persona:
persona/market/source-topic relevance + precision; workflow/risks: evidence
support, citation validity, source-document ownership, operational completeness /
risk specificity, duplicates, contradiction awareness, severity consistency,
unsupported/N-A counts), (4) reconciles workflow/risk items one by one (preserve
strong deterministic items, accept genuinely better or newly-discovered grounded
items, reject unsupported/weaker/duplicate/generic, never force a count), and (5)
accepts each component only when its structural score is strictly higher AND
grounding, citation accuracy, hallucination/injection warnings, source-document
mismatch, insufficient-evidence count, and schema validity do not regress — ties
preserve deterministic. The gate runs *before* grounding repair; repair →
re-bind → recompute metrics → narrative polish/gate follow unchanged. Public
report schema unchanged; all gate data is telemetry-only. Also split the benchmark
`expectedRiskRecall` into four metrics — `expectedRiskConceptRecall`,
`expectedSourceDocumentMatchRate`, `expectedCitationFamilyMatchRate`,
`expectedCitationExactMatchRate` — to distinguish correct-risk/correct-document/
different-section from wrong-document and from exact matches (exact matching kept,
not replaced by prefix). Runner gained `--runs`, `--scenario`/`--category` filters,
mean/std, win/tie/loss vs deterministic & summary, structural regressions before/
after gate, incremental gain vs summary, and cost per accepted improvement.
Verified (gpt-4o-mini, v1, 22 scenarios): structural regressions 1 → 0 after the
gate; 0 grounding regressions; full structural 67.5 → 76.5; full vs deterministic
6/14/2, full vs summary 1/11/10 (−0.48 at ~3.8× cost). Rationale: full-mode
analytical changes must be provably better and non-regressing before we calibrate
or enable auto-routing to full; the data shows summary remains the sweet spot.
Deterministic (no LLM/embeddings) so it is explainable and unit-testable.

### 2026-07-13 · Auto-router calibration — auto defaults to summary, full stays manual
Before tuning any thresholds, ran an oracle analysis (`scripts/calibrate_router.py`)
to decide whether auto-routing has enough theoretical value to justify its
complexity. On the v1 benchmark (gpt-4o-mini, 22 scenarios, deterministic/summary/
full): the **oracle** (best per-scenario mode, ε=0.2 ties preferring the cheaper
mode) averages 95.47 overall vs always-summary 95.36 — a **gain of only +0.12**,
below the 0.2 bar. Full is the best choice in just 2/22 scenarios and is
**Pareto-dominated** (frontier = {deterministic, summary}) once cost (~4×) and
latency (~5×) are considered. A threshold grid search (full-gain ∈ {0.0…1.0}) and
leave-one-category-out validation found **no interpretable policy that beats
always-summary by ≥0.2 within the hard constraints** (no avg regression vs summary,
no scenario worse than summary by >0.5, cost ≤125% of summary, latency ≤150% of
summary). The previous aggressive router (contradiction/custom-persona/large-corpus/
low-confidence → full) actually scored *below* summary (95.02) at 3.3× cost and
violated the constraints (routed 18/22 to full).

Decision: rewrote `agents/mode_router.py` as a conservative, interpretable,
deterministic router driven by **pre-LLM deterministic signals only** (deterministic
structural + narrative scores, doc complexity, contradictions, persona complexity,
confidence, citation coverage, grounded risk/step counts, dropped risks,
insufficient-evidence items, source mismatch, evidence-support avg/min). Summary is
the default; `off` only when the baseline is already strong; **full requires the
conjunction of a clear deterministic analytical weakness AND sufficient
selected-document evidence AND ≥2 independent opportunity signals AND predicted
incremental gain > `EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD`**. A custom persona alone,
a single contradiction, a high document count, or a slightly-low confidence never
force full; ties prefer the cheaper/faster mode. On the current corpus this
conjunction never fires, so **auto resolves to summary everywhere**; full is retained
as an explicit manual mode. Routing telemetry (`routingReason`, `routingSignals`,
`routingConfidence`, `predictedIncrementalGain`, `selectedMode`, `alternativeMode`,
`fullEligibilityChecks`) is emitted for every run. Rationale: benchmark evidence does
not justify automatic full routing today; the mechanism is unit-tested and will
select full if a future corpus/model makes it genuinely and cheaply better. Public
report schema unchanged.

### 2026-07 · AI memory/handoff docs
Added `AGENTS.md`, `.cursor/rules/evidentia-context.mdc`, and `docs/ai/*` so future
conversations can continue without chat history. Docs are the handoff source of
truth; agents read PROJECT_STATE + SESSION_HANDOFF before work and update them after.
