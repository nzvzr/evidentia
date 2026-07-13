# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-13 (auto-router calibration)._

## Where things stand

Backend calibration is complete and green. Pipeline is deterministic-first with
optional LLM refinement (off/summary/full/auto), a field-level narrative gate, a
full-mode structural quality gate, source-constrained (evidence-first) generation,
and deterministic grounding repair. `auto` is now a **calibrated conservative
router** that resolves to summary on the whole benchmark; full is a manual mode.

- **68 backend unit tests pass.** `backend/.env` is local + git-ignored (no secrets).
- Benchmarked model: **gpt-4o-mini**. App works with no key (deterministic).

## Just completed — auto-router calibration

Rewrote `agents/mode_router.py` to route from **pre-LLM deterministic signals only**
(deterministic structural + narrative scores, doc complexity, contradictions,
persona complexity, confidence, citation coverage, grounded risk/step counts,
dropped risks, insufficient-evidence items, source mismatch, evidence-support avg/min).
Full is eligible ONLY with a clear analytical weakness AND sufficient
selected-document evidence AND ≥2 opportunity signals AND predicted gain >
`EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD`. Custom persona / one contradiction / big
corpus / slightly-low confidence never force full; ties prefer the cheaper mode.
Routing telemetry: `routingReason/Signals/Confidence`, `predictedIncrementalGain`,
`selectedMode`, `alternativeMode`, `fullEligibilityChecks`.

`scripts/calibrate_router.py` (offline, no threshold tuning first): oracle analysis
+ policy comparison (always-{det,summary,full}, previous aggressive auto, proposed,
oracle) under hard cost/latency/regression constraints, threshold grid search, and
leave-one-category-out validation.

## Verified results (v1, gpt-4o-mini, 22 scenarios)

| mode | overall (±std) | grounding | narrative | latency | cost |
|------|----------------|-----------|-----------|---------|------|
| deterministic | 93.8 (4.15) | 93.9 | 93.8 | ~1 ms | $0 |
| summary | 95.4 (3.10) | 93.9 | 96.9 | 5.4 s | $0.0078 |
| full | 94.8 (3.29) | 93.9 | 95.7 | 24.1 s | $0.0295 |
| auto | 94.9 (3.76) | 93.9 | 96.0 | 5.2 s | $0.0077 |

- **Oracle** avg 95.47 vs always-summary 95.36 → **gain +0.12** (< 0.2). Full wins
  in only 2/22; **full is Pareto-dominated** (frontier = {deterministic, summary}).
- Previous aggressive auto: 95.02 (worse than summary), $0.0259, 18/22→full,
  constraints ✗. **Proposed router = always-summary** (22/22→summary), constraints ✓.
  No threshold beats summary by 0.2; LOCO gain 0.0 in every category.
- **Verdict:** evidence does not justify automatic full routing → auto defaults to
  summary; full kept as a manual mode. Structural gate keeps full *safe* (full vs
  summary 2/8/12, −0.54 at ~3.8× cost; 0 structural/grounding regressions).

## Earlier — source-constrained generation (upstream fix)

`risk_analyzer` + `workflow_builder` are evidence-first: an item is emitted only
when an *owned* source section clears `EVIDENTIA_MIN_EVIDENCE_SUPPORT`; unsupported
items are dropped (no filler), with one evidence-gap risk when missing docs are
relevant. This drove repair's invalid-code count 31 → 0 (all grounded upstream).
Provenance + generation audit are telemetry-only (`*.gen-audit.csv`).

## Open concerns / next steps

1. **Matching is lexical, not semantic** (support/repair/structural scorers). Next:
   category/persona affinity refinement or embeddings (no LLM).
2. **Auto never routes to full on this corpus** (intentional; full is Pareto-dominated).
   Re-run `scripts/calibrate_router.py` if the corpus/model changes — the router will
   start selecting full when evidence justifies it.
3. **Exact-citation match 0.833** (family/document 1.0): risks bind to the
   highest-signal section in the correct document; the 4 split metrics show this.

## How to verify

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                       # expect 68 passed
python scripts/run_benchmark.py --modes deterministic,summary,full,auto
python scripts/calibrate_router.py        # oracle + policy comparison + verdict
# frontend: npm run build
```

## Reminders

- Update `PROJECT_STATE.md` (concise) and this file (< 100 lines) after changes.
- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the `EvidentiaReport` schema; keep the deterministic fallback.
