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
- `GET /api/documents` → demo document metadata
- `POST /api/generate-workflow` → an `EvidentiaReport`

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

## Enable LLM mode (optional)

```bash
cp .env.example .env
# then edit .env:
#   OPENAI_API_KEY=sk-...
#   EVIDENTIA_USE_LLM=true
```

The backend owns the API keys. They are never returned in responses and never
exposed to the browser. If the LLM call fails, each step falls back to
deterministic output and the request still succeeds.

## Wire the frontend to the backend

In the repo root, create `.env.local`:

```
EVIDENTIA_BACKEND_URL=http://localhost:8000
```

With that set, the Next.js route forwards requests to this backend. Without it
(or if the backend is offline), the frontend uses the TypeScript pipeline.
