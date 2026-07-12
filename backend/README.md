# Evidentia Python Backend

A FastAPI implementation of the Evidentia multi-agent pipeline. It mirrors the
TypeScript deterministic pipeline and returns the same `EvidentiaReport` JSON the
Next.js frontend consumes. It works fully offline with **no API key**, and can
optionally use an LLM (OpenAI) for refinement.

The Next.js API route (`app/api/generate-workflow/route.ts`) proxies to this
backend when `EVIDENTIA_BACKEND_URL` is set, and falls back to the built-in
TypeScript pipeline if the backend is unavailable.

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

- **SQLite (default, zero setup)** — if `DATABASE_URL` is empty, a local file
  `backend/evidentia.db` is used. Tables are created automatically on startup.
- **PostgreSQL** — set `DATABASE_URL` and run migrations:

```bash
# .env
DATABASE_URL=postgresql://user:password@localhost:5432/evidentia
EVIDENTIA_DB_ENABLED=true
```

Set `EVIDENTIA_DB_ENABLED=false` to disable persistence entirely (the API still
generates and returns reports; the frontend falls back to localStorage).

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

### Auto mode

Set `EVIDENTIA_LLM_INTENSITY=auto` to let the pipeline pick `off`/`summary`/`full`
per request from deterministic-baseline signals:

- **document complexity** (number of selected documents)
- **contradictions** (documented conflicts/gaps in the corpus)
- **citation coverage** and **deterministic confidence** (from the baseline metrics)
- **persona complexity** (custom/free-text roles)

Routing (`app/agents/mode_router.py`): insufficient evidence (≤1 doc) → `summary`;
contradictions, custom persona, large corpus, or low confidence → `full`; simple,
well-covered, high-confidence cases → `off`; otherwise `summary`. The existing
`off`/`summary`/`full` modes are unchanged.

## LLM evaluation & calibration benchmark

A versioned benchmark (`app/eval/`) runs the pipeline across intensity modes over
a dataset of representative scenarios (`app/eval/dataset.py`, `BENCHMARK_VERSION`)
covering standard personas, custom personas, conflicting documents, insufficient
evidence, prompt-injection attempts, and high-risk compliance cases.

For every scenario × mode it records schema validity, citation accuracy, citation
coverage, persona relevance, action specificity, hallucination warnings, latency,
token usage, estimated cost, provider, model, prompt version, and cache status,
plus a **weighted quality score (0–100)**.

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
(or if the backend is offline), the frontend uses the TypeScript pipeline.
