# Evidentia — Deployment Guide

Stable public-demo deployment for the Next.js frontend + FastAPI backend.
The app is **deterministic-first**: it works with no LLM key and no backend
(TypeScript fallback), so a partial outage degrades gracefully instead of failing.

## Topology

```
Browser ──▶ Next.js frontend ──(EVIDENTIA_BACKEND_URL)──▶ FastAPI backend ──▶ SQLite / PostgreSQL
                │                                              │
                │ no backend configured / unreachable         │ owns OPENAI_API_KEY (never sent to browser)
                ▼                                              ▼
        deterministic TS pipeline                    deterministic + optional LLM (summary default)
```

- The **frontend never receives API keys.** Keys live only in the backend env.
- If `EVIDENTIA_BACKEND_URL` is unset or the backend is unreachable, the Next API
  routes fall back to the built-in TypeScript pipeline.

## Environment variables

### Backend (`backend/.env` — secret, never committed)
| Var | Purpose | Demo value |
|-----|---------|-----------|
| `OPENAI_API_KEY` | LLM key (server-only) | your key, or empty for deterministic |
| `EVIDENTIA_USE_LLM` | master LLM switch | `true` (or `false` for deterministic) |
| `EVIDENTIA_LLM_MODEL` | model | `gpt-4o-mini` |
| `EVIDENTIA_LLM_INTENSITY` | `off\|summary\|full\|auto` | `summary` (effective standard) |
| `DATABASE_URL` | Postgres URL; empty → SQLite file | empty (SQLite) for demo |
| `EVIDENTIA_DB_ENABLED` | enable persistence | `true` |
| `EVIDENTIA_CORS_ORIGINS` | allowed origins (`*` or CSV) | frontend origin, or `*` |

### Frontend (platform env)
| Var | Purpose | Demo value |
|-----|---------|-----------|
| `EVIDENTIA_BACKEND_URL` | backend public URL (server-only) | `https://<backend-host>` |
| `EVIDENTIA_BACKEND_TIMEOUT_MS` | generate proxy timeout (cold starts) | `45000` |
| `EVIDENTIA_BACKEND_READ_TIMEOUT_MS` | report read/list proxy timeout | `8000` |

Do **not** put `OPENAI_API_KEY` in the frontend environment.

## Deploy

### Backend (container: Render / Fly / Railway)
1. Build from `backend/`: `docker build -t evidentia-backend backend/`
2. Set env: `OPENAI_API_KEY`, `EVIDENTIA_USE_LLM=true`, `EVIDENTIA_LLM_INTENSITY=summary`,
   `EVIDENTIA_CORS_ORIGINS=<frontend origin>`, and `DATABASE_URL` (or leave empty for SQLite).
3. The container listens on `$PORT` (default 8000) and exposes `GET /health`.
4. Verify: `curl https://<backend-host>/health` → `{"status":"ok",...}`.

### Frontend (Vercel — recommended)
1. Import the repo; framework auto-detected (Next.js 14).
2. Set env `EVIDENTIA_BACKEND_URL=https://<backend-host>` (Production scope).
3. Deploy. `next.config.mjs` also emits `.next/standalone` for container hosting if
   you prefer Docker over Vercel.
4. Verify: `curl https://<frontend-host>/api/health` → `backendReachable:true`.

## Health checks
- Backend: `GET /health` → `{status, version, llmEnabled, intensity, dbEnabled}`.
- Frontend: `GET /api/health` → `{status, backendConfigured, backendReachable, mode}`.

## Smoke test (post-deploy)
```bash
FRONT=https://<frontend-host>
curl -s "$FRONT/api/health"
curl -s -X POST "$FRONT/api/generate-workflow" -H 'Content-Type: application/json' \
  -d '{"market":"EMEA","persona":"Compliance Officer","customPersona":"","selectedDocumentIds":["data-residency-sovereignty-policy","incident-response-runbook","sla-uptime-commitment","security-compliance-whitepaper"]}' \
  | head -c 400
```
Then in a fresh browser: open `$FRONT` → Workspace → run the showcase → confirm the
report renders, direct-open `/reports/showcase-residency-emea`, and Export playbook (PDF).

## Demo reset (predictable)
- **Per browser**: clear site data / localStorage keys `evidentia:reports` and
  `evidentia:uploaded-documents` (or use a fresh/incognito window). Demo scenarios
  regenerate deterministically, so the library is never empty.
- **Backend**: SQLite — redeploy or delete `backend/evidentia.db` (a fresh file is
  created on next call). Postgres — truncate the reports table. Report generation
  does not depend on stored data.

## Rollback checklist
1. Redeploy the previous known-good image/commit (frontend and/or backend).
2. If the backend is the problem, unset `EVIDENTIA_BACKEND_URL` on the frontend —
   it immediately serves the deterministic TS pipeline (no outage).
3. If the LLM/provider is the problem, set `EVIDENTIA_USE_LLM=false` (or
   `EVIDENTIA_LLM_INTENSITY=off`) on the backend — deterministic mode, still grounded.
4. If persistence is the problem, set `EVIDENTIA_DB_ENABLED=false` — reports are
   still returned (unsaved) and the frontend uses localStorage.
5. Confirm both health endpoints return 200 and re-run the smoke test.

## Notes
- Cold starts: the generate proxy waits up to `EVIDENTIA_BACKEND_TIMEOUT_MS` (45s)
  and the loader shows a "still working" notice, then falls back locally if needed.
- No temporary server files are produced for PDFs — export is client-side print of
  `/playbook/[id]/print`, so there are no expiring download URLs.
