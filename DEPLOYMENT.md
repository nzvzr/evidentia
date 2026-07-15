# Evidentia — Deployment Guide

Production deployment for the Next.js frontend (BFF) + FastAPI backend.

**Evidentia is an authenticated, multi-tenant application.** Every product route
requires a session the backend has validated. There is no anonymous mode, and no
"degrade gracefully to a local pipeline" path for authenticated users — read
*Authentication invariants* before changing any of this.

## Topology

```
Browser ──▶ Next.js BFF ──(EVIDENTIA_BACKEND_URL + BFF secret)──▶ FastAPI ──▶ managed PostgreSQL
   │            │  httpOnly cookies hold the tokens;                 │        (SQLite is dev-only)
   │            │  the browser never sees one                        │ owns OPENAI_API_KEY
   │            │                                                    │ owns JWT_SECRET
   └────────────┴─▶ /api/demo/generate-workflow: anonymous, public corpus, persists nothing
```

- **Run exactly ONE backend instance.** Rate-limit counters are per-process and
  in-memory, so N replicas multiply every limit by N (see *Known limitations*).
  Do not enable horizontal autoscaling on the backend service.

- The **frontend never receives API keys or JWTs.** Both live only in the backend
  env; the BFF holds session tokens in httpOnly cookies.
- **The backend should not be publicly reachable.** Put it on a private network. If
  it must be exposed, set `EVIDENTIA_BFF_SECRET` — otherwise anyone can bypass the
  BFF and forge `X-Forwarded-For`, defeating every per-IP rate limit.

## Authentication invariants (do not break these)

1. **Authenticated routes never fall back to the TypeScript pipeline.** If the
   backend cannot validate the session, `POST /api/generate-workflow` returns
   **503**. It does not generate. A cookie's *presence* is not evidence of a session.
2. **The public TS demo exists only at `POST /api/demo/generate-workflow`** — it
   never reads session cookies, runs on the bundled public corpus, and persists
   nothing.
3. **Reports are created only by authenticated generation.** `POST /api/reports` is
   a 405; it previously accepted an arbitrary blob, letting a client fabricate
   `generationMode`, confidence and citations.
4. **Never unset `EVIDENTIA_BACKEND_URL` to recover from an outage.** That does not
   degrade the app — it disables authentication entirely (login/register 503, product
   routes unusable). It is not a rollback lever. See *Rollback*.

## Environment variables

### Backend (`backend/.env` — secret, never committed)

| Var | Purpose | Production value |
|-----|---------|------------------|
| `EVIDENTIA_ENV` | **must be `production`** — enables fail-fast config validation | `production` |
| `JWT_SECRET` | access-token signing key. **Required**; must be a generated secret (base64url/hex of ≥32 random bytes) — same gate as `EVIDENTIA_BFF_SECRET` | generate one (below) |
| `EVIDENTIA_BFF_SECRET` | shared secret proving a request came via the BFF. **Required when `EVIDENTIA_TRUSTED_PROXY_COUNT > 0`**; production refuses weak/short (<32 char)/low-entropy values | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `EVIDENTIA_TRUSTED_PROXY_COUNT` | trusted proxy hops in front of the backend; `1` when it sits behind the BFF | `1` |
| `EVIDENTIA_EMAIL_BACKEND` | **must be `smtp` with `EVIDENTIA_SMTP_HOST` set.** `console` writes single-use reset links to the logs and `noop` discards them — production refuses both, because reset/verification would not actually work | `smtp` + `EVIDENTIA_SMTP_*` |
| `EVIDENTIA_CORS_ORIGINS` | allowed origins. **`*` is refused in production** | the frontend origin |
| `OPENAI_API_KEY` | LLM key (server-only) | your key, or empty for deterministic |
| `EVIDENTIA_USE_LLM` | master LLM switch | `true` / `false` |
| `EVIDENTIA_LLM_INTENSITY` | `off` / `summary` / `full` / `auto` | `summary` |
| `DATABASE_URL` | Postgres URL; empty → SQLite file. **SQLite is dev-only** — on most container hosts the filesystem is ephemeral, so a redeploy destroys all users and reports | **managed PostgreSQL** |
| `EVIDENTIA_REQUIRE_EMAIL_VERIFICATION` | block unverified users from tenant routes | `true` |
| `EVIDENTIA_RATE_LIMIT_MAX_KEYS` | cap on tracked rate-limit buckets (LRU eviction past it) | `100000` |

Generate the two secrets with **exactly** these commands and paste the output:

```bash
# JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"

# EVIDENTIA_BFF_SECRET  (set the SAME value on the frontend)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Both `JWT_SECRET` and `EVIDENTIA_BFF_SECRET` must be **cryptographically
generated** values — the base64url or hex encoding of at least 32 random bytes.
Production refuses anything else: known-weak values, repeated blocks, sequential
runs, dictionary-like strings, narrow alphabets, low estimated entropy, and highly
compressible values are all rejected. **Length is not strength.**
`abcd1234abcd1234abcd1234abcd1234` is 32 characters and is guessed in seconds. A
guessable BFF secret is worth exactly as much as no BFF secret (the attacker
reaches the backend directly, forges `X-Forwarded-For`, and every per-IP limit
stops working), and a guessable JWT key is worse — whoever recovers it can mint an
access token for any user in any tenant.

Production startup **fails** if `JWT_SECRET` or `EVIDENTIA_BFF_SECRET` is weak, the
proxy/BFF pairing is inconsistent, the email backend cannot actually deliver, CORS is
`*`, or `EVIDENTIA_DB_ENABLED=false`. That is deliberate: each of those silently fails
*open* (or silently does nothing) if misconfigured, so refusing to boot is the only
safe behaviour.

**Do not run a public beta on SQLite or with wildcard CORS.** Use managed PostgreSQL
and an explicit origin allowlist. SQLite is local development only: container
filesystems are typically ephemeral, so a redeploy destroys every user and report,
and production cannot detect an ephemeral disk for you.

**Send yourself a real password-reset email before launch.** The SMTP sender has not
been exercised against a live provider; if delivery silently fails, password reset is
unavailable and locked-out users stay locked out.

### Frontend (platform env)

| Var | Purpose | Production value |
|-----|---------|------------------|
| `EVIDENTIA_BACKEND_URL` | backend URL (server-only). **Unsetting this disables auth — never do it as a rollback** | `https://<backend-host>` |
| `EVIDENTIA_BFF_SECRET` | must match the backend's value | the same secret |
| `EVIDENTIA_TRUSTED_PROXY_COUNT` | proxies in front of *Next* (e.g. `1` for a CDN); `0` = trust nothing | `0` or `1` |
| `EVIDENTIA_MAX_BODY_BYTES` | BFF request-body cap | `524288` |
| `EVIDENTIA_BACKEND_TIMEOUT_MS` | generate proxy timeout | `45000` |
| `EVIDENTIA_BACKEND_READ_TIMEOUT_MS` | read/list proxy timeout | `8000` |

Do **not** put `OPENAI_API_KEY` or `JWT_SECRET` in the frontend environment.

### Proxy trust — get this right

`X-Forwarded-For` is client-writable. It is only consulted when
`EVIDENTIA_TRUSTED_PROXY_COUNT > 0`, and then only the Nth-from-the-right entry
(written by the innermost trusted proxy) is believed. `X-Real-IP` is **never**
trusted at any hop count.

- **Too low** (`0` behind the BFF): every user shares one IP budget — a
  self-inflicted denial of service.
- **Too high**, or a publicly reachable backend without `EVIDENTIA_BFF_SECRET`: a
  client can forge the trusted slot and rotate their rate-limit identity at will.

### Rate limiting — single-instance only

Counters are **in-process and in-memory**:

- **N backend replicas multiply every limit by N.** Run a **single backend
  process**, or move limits to a shared store / API gateway before scaling out.
  `RateLimitStore` (`backend/app/core/ratelimit.py`) is a Protocol — a Redis
  implementation is `INCR` + `EXPIRE` and needs no call-site changes.
- **A restart clears all counters**, so an attacker who can trigger restarts
  regains budget.
- The store is bounded (`EVIDENTIA_RATE_LIMIT_MAX_KEYS`, LRU eviction), so a flood
  of unique emails/tokens cannot exhaust memory.

## Deploy

### Backend (container: Render / Fly / Railway)

1. Build from `backend/`: `docker build -t evidentia-backend backend/`
2. Run migrations: `alembic upgrade head`.
3. Set env per the table above. **`EVIDENTIA_ENV=production` and a generated
   `JWT_SECRET` are mandatory** — the process refuses to boot without them.
4. Keep the service **private**. If it must be public, set `EVIDENTIA_BFF_SECRET`.
5. Verify: `curl https://<backend-host>/health` → `{"status":"ok",...}` (the health
   probe is exempt from the BFF guard so orchestrator probes keep working).

### Frontend (Vercel)

1. Import the repo (Next.js 16).
2. Set `EVIDENTIA_BACKEND_URL` and the matching `EVIDENTIA_BFF_SECRET`.
3. Verify: `curl https://<frontend-host>/api/health` → `backendReachable:true`.

## Health checks

- Backend: `GET /health` → `{status, version, llmEnabled, intensity, dbEnabled}`.
- Frontend: `GET /api/health` → `{status, backendConfigured, backendReachable, mode, demoAvailable}`.
  Returns **503** when the backend is unreachable: there is no fallback mode, so an
  instance that cannot reach the backend cannot serve the product and must not be
  reported healthy.

## Smoke test (post-deploy)

Product routes require a session, so the smoke test **must authenticate first**. An
unauthenticated `POST /api/generate-workflow` returning **401 is the control
working**, not an outage.

```bash
FRONT=https://<frontend-host>
curl -s "$FRONT/api/health"

# 1. Anonymous access is refused.
curl -s -o /dev/null -w 'anon generate: %{http_code} (expect 401)\n' \
  -X POST "$FRONT/api/generate-workflow" -H 'Content-Type: application/json' -d '{}'

# 2. Authenticate, then exercise the product route with the session cookies.
curl -s -c cookies.txt -X POST "$FRONT/api/auth/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@example.com","password":"<a strong password>","company":"Smoke"}'

curl -s -b cookies.txt -X POST "$FRONT/api/generate-workflow" \
  -H 'Content-Type: application/json' \
  -d '{"market":"EMEA","persona":"Compliance Officer","selectedDocumentIds":[]}' | head -c 300

# 3. The public demo needs no session and persists nothing.
curl -s -o /dev/null -w 'demo: %{http_code} (expect 200)\n' \
  -X POST "$FRONT/api/demo/generate-workflow"

rm -f cookies.txt
```

Then in a fresh browser: register → Workspace → run → confirm the report renders and
Export playbook (PDF) works. Sign out and confirm `/workspace` redirects to `/login`.

## Demo reset

- **Per browser**: sign out — this purges every authenticated key from localStorage.
  Authenticated reports and documents are **never** cached in the browser; the
  backend is the only source of truth.
- **Backend**: Postgres — truncate `reports`. (SQLite, dev only — delete
  `backend/evidentia.db`.)

## Rollback checklist

**Do not unset `EVIDENTIA_BACKEND_URL`.** It is not a rollback lever: it disables
authentication for the entire app rather than degrading it. There is no
authenticated-mode fallback, by design.

1. Redeploy the previous known-good image/commit (frontend and/or backend).
2. If the **backend** is the problem, fix or roll back the backend. The frontend
   correctly reports 503 while it is down, and no authenticated data is at risk.
3. If the **LLM provider** is the problem, set `EVIDENTIA_USE_LLM=false` (or
   `EVIDENTIA_LLM_INTENSITY=off`) on the backend — deterministic mode, still
   grounded, still authenticated.
4. If **persistence** is the problem, do **not** set `EVIDENTIA_DB_ENABLED=false` in
   production: authentication requires the database. Restore or roll back the
   database instead.
5. If a **migration** is the problem: `alembic downgrade -1`.
6. Confirm both health endpoints return 200 and re-run the authenticated smoke test.

## Notes

- Cold starts: the generate proxy waits up to `EVIDENTIA_BACKEND_TIMEOUT_MS` (45s)
  and the loader shows a "still working" notice. On timeout it reports 503 — it does
  **not** fall back to a local pipeline.
- No temporary server files are produced for PDFs — export is a client-side print of
  `/playbook/[id]/print`, so there are no expiring download URLs.
