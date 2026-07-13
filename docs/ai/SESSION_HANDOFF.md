# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-13._

## Where things stand

Backend calibration framework is complete and green. The pipeline is
deterministic-first with optional LLM refinement (off/summary/full/auto), a
field-level narrative quality gate, and a deterministic grounding-repair stage.
Evaluation splits `groundingScore` and `narrativeUtilityScore`.

- **39 backend unit tests pass.** Frontend builds.
- Benchmarked model: **gpt-4o-mini**. App works with no key (deterministic).
- `backend/.env` is local + git-ignored (no secrets committed).

## Latest live benchmark (gpt-4o-mini, v1)

- deterministic: overall 93.9 / grounding 93.9 / narrative 93.9
- summary: overall 95.5 / grounding 93.9 / narrative 97.1
- narrative regressions: 2 before gate → 0 after gate
- field acceptance rate: 25.8%
- ungrounded evidence: 31 before repair → 0 after
- cost: 22 LLM calls, $0.008164

## Just completed

- Field-level narrative gate (`backend/app/agents/narrative_gate.py`).
- Deterministic grounding repair (`backend/app/tools/citation_tools.py`).
- Grounding/narrative scoring split + sub-metrics + gate/repair benchmark reporting.
- This AI memory/handoff system (`AGENTS.md`, `.cursor/rules/`, `docs/ai/*`).

## Open concerns / next steps

1. **Semantic relevance of repaired citations (primary).** Repair currently picks
   a replacement citation via keyword overlap in
   `citation_tools._relevant_citation`. Codes are valid but may not be the most
   relevant source. Consider embedding/semantic ranking or persona-aware
   preference, and add tests asserting the *chosen* citation matches the risk topic.
2. Live gate/regression reporting only exercises fully with an API key set; in
   keyless environments the benchmark runs deterministic-equivalent.
3. Optional: surface `generationMode` / gate outcome more richly in the frontend.

## How to verify

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                       # expect 39 passed
python scripts/run_benchmark.py --modes deterministic,summary,full,auto
# frontend: npm run build
```

## Reminders

- Update `PROJECT_STATE.md` (concise) and this file (< 100 lines) after changes.
- Append to `DECISIONS.md`; never rewrite past entries.
- Don't break the `EvidentiaReport` schema; keep the deterministic fallback.
