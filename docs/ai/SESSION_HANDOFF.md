# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-13 (deployment readiness)._

## Where things stand

Backend calibration is complete, verified, and **frozen** (do not extend the eval
framework without a concrete regression). Latest work prepared a **stable public
demo deployment** (no new features). Pipeline is deterministic-first with optional
LLM refinement (off/summary/full/auto), a field-level narrative gate, a full-mode
structural quality gate, source-constrained generation, deterministic grounding
repair, and a calibrated conservative `auto` router (resolves to summary; full manual).

- **68 backend unit tests pass**; **frontend `next lint`/`tsc`/`next build` clean.**
- App works with no key (deterministic) and no backend (TS fallback). Keys are
  backend-only; `.env`/`.env.local`/`evidentia.db` git-ignored.
- Benchmarked model: **gpt-4o-mini**. Public report schema unchanged.

## Just completed — deployment readiness

- `backend/Dockerfile` (+ `.dockerignore` that keeps the `*.md` corpus), listens on
  `$PORT`, container healthcheck; pinned `requirements.txt`.
- Enriched backend `/health`; new frontend `/api/health` (backend reachability).
- Env-driven CORS (`EVIDENTIA_CORS_ORIGINS`); proxy timeouts
  (`EVIDENTIA_BACKEND_TIMEOUT_MS` 45s, `EVIDENTIA_BACKEND_READ_TIMEOUT_MS` 8s);
  `next.config` `output:"standalone"` + `poweredByHeader:false`; `DATABASE_URL`
  empty → SQLite default.
- `DEPLOYMENT.md`: topology, env matrix, deploy + rollback checklists, demo reset,
  smoke test.
- **Verified locally (prod build)**: health OK; showcase generate 200 (~6s) and
  **persisted to SQLite + re-fetched by id**; insufficient corpus → `N/A` markers;
  all routes 200; **backend-down → deterministic fallback ~6ms**. **Cloud deploy
  NOT performed** (no hosting credentials/URLs) — local verification only.

## Earlier — demo release-readiness (frontend/PDF)

Honest `/running` loader (no fake %, timeout/fallback/error states); `N/A` rendered
as "INSUFFICIENT EVIDENCE" (web + PDF); 3-colour severity; citation `section`; empty
states; PDF sections flow across pages (no clipping); `showcase-residency-emea`
scenario; uploads labelled demo-only.

## Verified backend results (v1, gpt-4o-mini, 22 scenarios)

| mode | overall (±std) | grounding | narrative | latency | cost |
|------|----------------|-----------|-----------|---------|------|
| deterministic | 93.8 (4.15) | 93.9 | 93.8 | ~1 ms | $0 |
| summary | 95.4 (3.10) | 93.9 | 96.9 | 5.4 s | $0.0078 |
| full | 94.8 (3.29) | 93.9 | 95.7 | 24.1 s | $0.0295 |
| auto | 94.9 (3.76) | 93.9 | 96.0 | 5.2 s | $0.0077 |

## Earlier (backend, frozen)

- **Auto-router calibration** (`agents/mode_router.py`, `scripts/calibrate_router.py`):
  routes from pre-LLM deterministic signals; full requires analytical weakness +
  evidence + ≥2 opportunity signals + gain > `EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD`.
  Oracle gain over always-summary only +0.12 → **auto = summary; full is manual**
  (full is Pareto-dominated). Routing telemetry emitted per run.
- **Full-mode structural gate** + **source-constrained (evidence-first) generation**:
  invalid-code count 31 → 0 upstream; structural gate keeps full safe (0 regressions).
- **Grounding repair** (IDF scorer) + **narrative gate**; provenance/audit telemetry-only.

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
