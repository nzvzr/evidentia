# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-13 (source-constrained generation)._

## Where things stand

Backend calibration is complete and green. Pipeline is deterministic-first with
optional LLM refinement (off/summary/full/auto), a field-level narrative quality
gate, **source-constrained (evidence-first) risk/workflow generation**, and a
deterministic grounding-repair stage. Evaluation splits `groundingScore` and
`narrativeUtilityScore`.

- **53 backend unit tests pass.** `backend/.env` is local + git-ignored (no secrets).
- Benchmarked model: **gpt-4o-mini**. App works with no key (deterministic).

## Just completed — source-constrained generation (upstream fix)

Root cause of the 29 `N/A` markers: `risk_analyzer` generated generic risks and
attached evidence afterward, so many risks had no supporting selected document.
Now generation is evidence-first:

- New **evidence-support scorer** (`backend/app/tools/evidence_support.py`),
  separate from repair: selected-document ownership, risk/workflow vocabulary,
  exact domain phrases, category affinity, persona/market relevance, negation.
- `risk_analyzer` (rewritten) proposes risks per persona/market, then only emits
  ones whose *owned* source section clears `EVIDENTIA_MIN_EVIDENCE_SUPPORT` (≥2
  signals or a phrase). No filler to hit a count; one explicit evidence-gap risk
  only when the missing docs are operationally relevant. Returns `(risks, gen_info)`
  with internal provenance + drop/transform audit.
- `workflow_builder` grounds each step to a preferred/topical section or converts
  it to an evidence-gap step; returns `(steps, gen_info)`.
- Provenance (`sourceDocumentId`, `sourceCitationId`, `matchedSignals`,
  `generationReason`) lives in telemetry only, never the public report.
- New telemetry: `risksGeneratedBeforeFiltering`, `groundedRisksKept`,
  `unsupportedRisksDropped`, workflow equivalents, `insufficientEvidenceItemsFinal`,
  `sourceDocumentMismatchCount`, `evidenceSupportScore` avg/min, `expectedRiskRecall`.
- New `*.gen-audit.csv` + `scripts/run_benchmark.py --print-generation`.
- `metrics.validate_schema` relaxed (risks ≤6, workflow 1–6) — backward compatible.

## Verified results (v1, gpt-4o-mini)

| mode | overall | grounding | narrative |
|------|---------|-----------|-----------|
| deterministic | 93.8 | 93.9 | 93.8 |
| summary | 95.0 | 93.9 | 96.1 |

- Insufficient before → after: **repair had 31 invalid codes → now 0**
  (`ungroundedBeforeRepair = 0`, `repairInsufficient = 0`). 80 risks proposed →
  44 grounded, **36 unsupported dropped at source**; 27 deliberate evidence-gap items.
- Expected-risk recall **0.833**; citation accuracy 1.0; schema-valid 1.0;
  0 hallucination warnings; summary cost $0.0076.

## Open concerns / next steps

1. **Matching is lexical, not semantic** (support + repair scorers). Next:
   category/persona affinity refinement or embeddings (no LLM).
2. **Expected-risk recall 0.833**: risks bind to the highest-signal section in the
   right document, which may differ from the ground-truth section id. Consider
   prefix-level ground truth if exact recall is needed.
3. Full-mode LLM risk refinement can still add risks the deterministic scorer
   didn't ground; generation telemetry reflects the deterministic pass. Summary
   (default) and deterministic paths are fully source-constrained.

## How to verify

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                       # expect 53 passed
python scripts/run_benchmark.py --modes deterministic,summary --print-generation
# frontend: npm run build
```

## Reminders

- Update `PROJECT_STATE.md` (concise) and this file (< 100 lines) after changes.
- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the `EvidentiaReport` schema; keep the deterministic fallback.
