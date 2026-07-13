# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-13._

## Where things stand

Backend calibration is complete and green. Pipeline is deterministic-first with
optional LLM refinement (off/summary/full/auto), a field-level narrative quality
gate, and a hardened deterministic grounding-repair stage. Evaluation splits
`groundingScore` and `narrativeUtilityScore`.

- **44 backend unit tests pass.** `backend/.env` is local + git-ignored (no secrets).
- Benchmarked model: **gpt-4o-mini**. App works with no key (deterministic).

## Just completed — grounding-repair hardening

- Replaced one-token-overlap with an **IDF-weighted relevance scorer**
  (`backend/app/tools/citation_tools.py`): generic-term downweighting, exact
  multi-word phrase bonus, section-title > excerpt weighting, configurable
  `EVIDENTIA_REPAIR_MIN_RELEVANCE` (default 2.0), and a ≥2-meaningful-terms rule
  unless a strong phrase matches.
- Below threshold → `N/A` (insufficient evidence); never the least-bad citation.
- Per-repair **audit** (matched terms/phrases, relevance score, top-3 candidates,
  decision) in telemetry → benchmark JSON + a `*.audit.csv`; never in the public report.
- Benchmark now reports `validReplacementRate`, `expectedEvidenceMatchRate`,
  `insufficientEvidenceRate`, `lowConfidenceRepairRate`, `averageRepairRelevanceScore`.
- `scripts/run_benchmark.py --print-repairs` prints each repair + ground-truth match.

## Verified results (keyless deterministic benchmark, v1)

- overall 94.2 / narrative 94.6 / schema-valid 1.0.
- Repair: 31 ungrounded → 0; **2 replaced** (avg relevance 8.615), **29 insufficient**
  (rate 0.935); validReplacementRate 1.0; expectedEvidenceMatchRate 0.0.

## Open concerns / next steps

1. **Repaired-citation relevance is lexical, not semantic.** Residual cross-topic
   matches remain when two meaningful terms coincide (audit surfaces them, e.g.
   rollback risk → pricing "Plan Tiers" via `deployment`,`plan`). Next: category/
   persona-aware affinity bonus or embeddings (no LLM). Add a test asserting the
   chosen citation's category matches the item's topic.
2. **Most `insufficient` markers come from `risk_analyzer`** selecting risks whose
   source document isn't in the selected corpus. Consider filtering those risks so
   repair has a groundable citation, reducing the 29 insufficient markers.
3. Live gate/regression reporting only fully exercises with an API key set.

## How to verify

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                       # expect 44 passed
python scripts/run_benchmark.py --modes deterministic,summary,full,auto --print-repairs
# frontend: npm run build
```

## Reminders

- Update `PROJECT_STATE.md` (concise) and this file (< 100 lines) after changes.
- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the `EvidentiaReport` schema; keep the deterministic fallback.
