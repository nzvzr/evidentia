# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-13 (full-mode structural gate)._

## Where things stand

Backend calibration is complete and green. Pipeline is deterministic-first with
optional LLM refinement (off/summary/full/auto), a field-level narrative quality
gate, a **full-mode structural quality gate**, source-constrained (evidence-first)
risk/workflow generation, and a deterministic grounding-repair stage. Evaluation
splits `groundingScore` and `narrativeUtilityScore`.

- **66 backend unit tests pass.** `backend/.env` is local + git-ignored (no secrets).
- Benchmarked model: **gpt-4o-mini**. App works with no key (deterministic).

## Just completed — full-mode structural quality gate

Full mode used to overwrite the deterministic persona brief / workflow / risks with
no proof the change was better. Now (`agents/structural_gate.py`):

- The deterministic analytical baseline (persona, workflow, risks, citations,
  metrics, evidence-support telemetry, contradictions) is preserved; the LLM output
  is built as a *separate candidate*.
- Deterministic structural scorers grade persona (persona/market/source-topic
  relevance + precision), workflow and risks (evidence support, citation validity,
  source ownership, completeness/specificity, duplicates, contradiction awareness,
  severity consistency, unsupported/N-A counts).
- Item-level reconciliation preserves strong deterministic items, accepts genuinely
  better/new grounded items, rejects unsupported/weaker/duplicate/generic — no filler.
- Each component (personaBrief, workflowSteps, risks) is accepted only when its
  structural score is strictly higher AND grounding, citation accuracy, warnings,
  source-doc mismatch, N/A count, and schema validity don't regress. Ties keep
  deterministic. Then repair → re-bind → recompute metrics → narrative gate.
- Telemetry: deterministic/candidate/final structural score, gate decision,
  accepted/rejected components + item counts, rejection reasons, analytical fallback.
- Runner adds `--runs`, `--scenario`/`--category`, mean/std, win/tie/loss, structural
  regressions before/after gate, incremental gain vs summary, cost per accepted
  improvement. `expectedRiskRecall` split into 4 metrics (exact matching kept).

## Verified results (v1, gpt-4o-mini, 22 scenarios)

| mode | overall (±std) | grounding | narrative | structural |
|------|----------------|-----------|-----------|------------|
| deterministic | 93.8 (4.15) | 93.9 | 93.8 | — |
| summary | 94.9 (3.45) | 93.9 | 95.9 | — |
| full | 94.4 (3.58) | 93.9 | 95.0 | 76.5 |

- Structural gate (full): baseline 67.5 → candidate 80.9 → **final 76.5**;
  **structural regressions 1 → 0**; 0 grounding regressions; accepted 27/66
  components (50 risk + 7 workflow items).
- Full vs deterministic 6/14/2; **full vs summary 1/11/10, −0.48 at ~3.8× cost** →
  summary stays the default; keep auto-routing conservative about full.
- Match metrics: exact 0.833, family 1.0, document 1.0, concept recall 0.889.

## Earlier — source-constrained generation (upstream fix)

`risk_analyzer` + `workflow_builder` are evidence-first: an item is emitted only
when an *owned* source section clears `EVIDENTIA_MIN_EVIDENCE_SUPPORT`; unsupported
items are dropped (no filler), with one evidence-gap risk when missing docs are
relevant. This drove repair's invalid-code count 31 → 0 (all grounded upstream).
Provenance + generation audit are telemetry-only (`*.gen-audit.csv`).

## Open concerns / next steps

1. **Matching is lexical, not semantic** (support/repair/structural scorers). Next:
   category/persona affinity refinement or embeddings (no LLM).
2. **Full mode isn't worth its cost** (−0.48 vs summary, 1/22 wins, ~3.8× cost);
   the structural gate makes it safe (0 regressions) but keep auto-routing rare.
3. **Exact-citation match 0.833** (family/document 1.0): risks bind to the
   highest-signal section in the correct document; the 4 split metrics show this.

## How to verify

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                       # expect 66 passed
python scripts/run_benchmark.py --modes deterministic,summary,full --runs 3 \
  --scenario std-compliance-health,std-support-emea,custom-dpo-emea
# frontend: npm run build
```

## Reminders

- Update `PROJECT_STATE.md` (concise) and this file (< 100 lines) after changes.
- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the `EvidentiaReport` schema; keep the deterministic fallback.
