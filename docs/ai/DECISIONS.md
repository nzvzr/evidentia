# Evidentia — Decision Log

Append-only. Newest at the bottom. Do not edit or remove past entries; supersede
them with a new entry instead.

---

### 2026-07 · Deterministic-first pipeline
Reports are generated deterministically (rule-based agents over a local demo
corpus) with no LLM required. Rationale: reliable hackathon demo, reproducible
evaluation, zero cost by default. LLM is strictly an optional refinement layer.

### 2026-07 · Frontend + backend with proxy and fallback
Kept the Next.js deterministic pipeline and added a Python FastAPI backend. The
Next.js API route proxies to the backend when `EVIDENTIA_BACKEND_URL` is set and
falls back to the TypeScript pipeline otherwise. Rationale: real backend without
breaking the existing demo or coupling the frontend to Python.

### 2026-07 · Backend owns LLM keys
API keys live only in `backend/.env` (git-ignored). The frontend never sees keys;
`NEXT_PUBLIC_*` is never used for secrets. Rationale: security.

### 2026-07 · LLM intensity modes off/summary/full + auto
`EVIDENTIA_LLM_INTENSITY` controls cost/quality. `summary` (1 call) is the default
and recommended mode; `full` (≤3 calls) is for demos; `auto` routes per request
from deterministic-baseline signals. Rationale: control cost while allowing
higher-effort refinement where it helps. Benchmarked model: gpt-4o-mini.

### 2026-07 · Compact evidence pack + output validation
LLM prompts receive a compact, grounded evidence pack (not full documents),
token-capped, with an enterprise-analyst system prompt. Outputs are validated for
precision (no vague/marketing language); failing fields keep the deterministic
baseline. Rationale: cheaper, more precise, grounded output.

### 2026-07 · Separate grounding vs narrative scoring
Evaluation splits `groundingScore` (schema, citations, hallucination/injection)
from `narrativeUtilityScore` (the fields summary mode rewrites), blended into
`overallQualityScore`. Rationale: deterministic and summary modes previously
scored identically because metrics only measured grounding.

### 2026-07 · Field-level narrative quality gate
LLM polish is accepted per field only if strictly better and non-regressing on
factual consistency, grounding, and warnings; ties preserve deterministic.
Rationale: prevent LLM regressions (observed e.g. custom-dpo-emea) while keeping
genuine improvements.

### 2026-07 · Deterministic grounding repair
Before assembly, invalid `evidenceCode`s are replaced with a semantically relevant
valid citation or marked `N/A` (insufficient evidence) — never invented — then
citations are re-bound. Metrics treat the `N/A` sentinel as honest, not ungrounded.
Rationale: deterministic reports contained ungrounded evidence codes (31 → 0).
Open follow-up: relevance selection is keyword-based and coarse (see PROJECT_STATE).

### 2026-07-13 · Hardened grounding-repair relevance scorer
Replaced the one-token-overlap repair heuristic (which accepted any positive
lexical overlap) with a deterministic **IDF-weighted scorer**: generic terms
downweighted, exact multi-word phrases rewarded, section-title matches weighted
above excerpt, a configurable minimum-relevance threshold
(`EVIDENTIA_REPAIR_MIN_RELEVANCE`), and a ≥2-meaningful-terms rule unless a strong
phrase matches. Below threshold → `N/A` (insufficient evidence), never the
least-bad citation. Added a per-repair audit trail (matched terms/phrases,
relevance score, top-3 candidates, decision) exported in benchmark JSON/CSV only.
Result: of 31 invalid deterministic codes, 2 are replaced with relevant citations
and 29 are honestly marked insufficient (previously all 31 were force-mapped).
Rationale: a valid citation ID must actually support its item; no LLM/embeddings
yet. Known residual: scorer is lexical, so rare cross-topic matches remain (audit
surfaces them); consider category/persona affinity or embeddings next.

### 2026-07-13 · Source-constrained (evidence-first) risk & workflow generation
Fixed the upstream cause of the 29 `N/A` markers. Previously `risk_analyzer` chose
generic risks from a static pool and attached evidence afterward, so most risks
had no supporting *selected* document and were later marked insufficient by repair.
Now generation is evidence-first: a new deterministic **evidence-support scorer**
(`tools/evidence_support.py`, separate from repair) scores a candidate section by
selected-document ownership, risk/workflow-specific vocabulary, exact domain
phrases, document-category affinity, persona relevance, market relevance, and
negation/contradiction markers. A risk is emitted grounded only when a section it
*owns* clears `EVIDENTIA_MIN_EVIDENCE_SUPPORT` (≥2 signals or a domain phrase);
unsupported risks are dropped, never filler-filled to a count. One explicit
evidence-gap risk (`N/A`) is emitted only when the missing documentation is itself
operationally relevant to the persona. `workflow_builder` applies the same
principle (preferred/topical section, else evidence-gap step). Both agents now
return `(items, gen_info)` carrying internal provenance (`sourceDocumentId`,
`sourceCitationId`, `matchedSignals`, `generationReason`) and a drop/transform
audit — provenance stays in telemetry and never enters the public report schema.
`metrics.validate_schema` was relaxed (risks ≤6, workflow 1–6) so honest low
counts pass; this is backward compatible with existing 3–5 / 4–6 reports. Result
(gpt-4o-mini, v1): repair now sees **0 invalid codes** (was 31); 80 risks proposed
→ 44 grounded, 36 dropped at source; expected-risk recall 0.833; grounding 93.9,
overall deterministic 93.8 / summary 95.0. Rationale: a grounded risk must be
derived from evidence the report actually cites, not patched after the fact; kept
fully deterministic (no LLM/embeddings). Residual: matching is still lexical.

### 2026-07-13 · Full-mode structural quality gate + item reconciliation
Summary mode had a field-level narrative gate, but full mode replaced the
deterministic persona brief, workflow steps and risks outright, with grounding
repair only validating citation ids afterward — no proof the analytical changes
were actually better. Added a deterministic structural gate (`agents/
structural_gate.py`) that (1) preserves the complete deterministic analytical
baseline, (2) builds the LLM output as a separate candidate, (3) scores persona,
workflow and risks with dedicated deterministic structural scorers (persona:
persona/market/source-topic relevance + precision; workflow/risks: evidence
support, citation validity, source-document ownership, operational completeness /
risk specificity, duplicates, contradiction awareness, severity consistency,
unsupported/N-A counts), (4) reconciles workflow/risk items one by one (preserve
strong deterministic items, accept genuinely better or newly-discovered grounded
items, reject unsupported/weaker/duplicate/generic, never force a count), and (5)
accepts each component only when its structural score is strictly higher AND
grounding, citation accuracy, hallucination/injection warnings, source-document
mismatch, insufficient-evidence count, and schema validity do not regress — ties
preserve deterministic. The gate runs *before* grounding repair; repair →
re-bind → recompute metrics → narrative polish/gate follow unchanged. Public
report schema unchanged; all gate data is telemetry-only. Also split the benchmark
`expectedRiskRecall` into four metrics — `expectedRiskConceptRecall`,
`expectedSourceDocumentMatchRate`, `expectedCitationFamilyMatchRate`,
`expectedCitationExactMatchRate` — to distinguish correct-risk/correct-document/
different-section from wrong-document and from exact matches (exact matching kept,
not replaced by prefix). Runner gained `--runs`, `--scenario`/`--category` filters,
mean/std, win/tie/loss vs deterministic & summary, structural regressions before/
after gate, incremental gain vs summary, and cost per accepted improvement.
Verified (gpt-4o-mini, v1, 22 scenarios): structural regressions 1 → 0 after the
gate; 0 grounding regressions; full structural 67.5 → 76.5; full vs deterministic
6/14/2, full vs summary 1/11/10 (−0.48 at ~3.8× cost). Rationale: full-mode
analytical changes must be provably better and non-regressing before we calibrate
or enable auto-routing to full; the data shows summary remains the sweet spot.
Deterministic (no LLM/embeddings) so it is explainable and unit-testable.

### 2026-07-13 · Auto-router calibration — auto defaults to summary, full stays manual
Before tuning any thresholds, ran an oracle analysis (`scripts/calibrate_router.py`)
to decide whether auto-routing has enough theoretical value to justify its
complexity. On the v1 benchmark (gpt-4o-mini, 22 scenarios, deterministic/summary/
full): the **oracle** (best per-scenario mode, ε=0.2 ties preferring the cheaper
mode) averages 95.47 overall vs always-summary 95.36 — a **gain of only +0.12**,
below the 0.2 bar. Full is the best choice in just 2/22 scenarios and is
**Pareto-dominated** (frontier = {deterministic, summary}) once cost (~4×) and
latency (~5×) are considered. A threshold grid search (full-gain ∈ {0.0…1.0}) and
leave-one-category-out validation found **no interpretable policy that beats
always-summary by ≥0.2 within the hard constraints** (no avg regression vs summary,
no scenario worse than summary by >0.5, cost ≤125% of summary, latency ≤150% of
summary). The previous aggressive router (contradiction/custom-persona/large-corpus/
low-confidence → full) actually scored *below* summary (95.02) at 3.3× cost and
violated the constraints (routed 18/22 to full).

Decision: rewrote `agents/mode_router.py` as a conservative, interpretable,
deterministic router driven by **pre-LLM deterministic signals only** (deterministic
structural + narrative scores, doc complexity, contradictions, persona complexity,
confidence, citation coverage, grounded risk/step counts, dropped risks,
insufficient-evidence items, source mismatch, evidence-support avg/min). Summary is
the default; `off` only when the baseline is already strong; **full requires the
conjunction of a clear deterministic analytical weakness AND sufficient
selected-document evidence AND ≥2 independent opportunity signals AND predicted
incremental gain > `EVIDENTIA_ROUTER_FULL_GAIN_THRESHOLD`**. A custom persona alone,
a single contradiction, a high document count, or a slightly-low confidence never
force full; ties prefer the cheaper/faster mode. On the current corpus this
conjunction never fires, so **auto resolves to summary everywhere**; full is retained
as an explicit manual mode. Routing telemetry (`routingReason`, `routingSignals`,
`routingConfidence`, `predictedIncrementalGain`, `selectedMode`, `alternativeMode`,
`fullEligibilityChecks`) is emitted for every run. Rationale: benchmark evidence does
not justify automatic full routing today; the mechanism is unit-tested and will
select full if a future corpus/model makes it genuinely and cheaply better. Public
report schema unchanged.

### 2026-07 · AI memory/handoff docs
Added `AGENTS.md`, `.cursor/rules/evidentia-context.mdc`, and `docs/ai/*` so future
conversations can continue without chat history. Docs are the handoff source of
truth; agents read PROJECT_STATE + SESSION_HANDOFF before work and update them after.

### 2026-07 · Production authentication & multi-tenant foundation
Replaced all demo/mock auth. **Passwords**: bcrypt (cost 12) with a SHA-256
pre-hash so bcrypt's 72-byte truncation is unreachable; min length 12.
**Tokens**: short-lived JWT access tokens (`typ=access`, so an opaque refresh
token can never be presented as a bearer credential) + rotating opaque refresh
tokens persisted only as SHA-256 digests; replaying a spent refresh token revokes
the entire rotation **family** (stolen-token reuse detection). `JWT_SECRET` is
mandatory under `EVIDENTIA_ENV=production`.

**Tenancy**: `api/deps.py::get_company_context` is the single source of a
`company_id` inside a request handler, and it is always derived from a membership
row — `company_id` is no longer accepted from a request body or an unchecked
query param (that was the tenant-forgery hole). Repository single-row lookups
(`get_report`/`get_document`/`get_persona`) now *require* a `company_id`, making
fetch-by-id-alone impossible **by construction** rather than by remembering to add
a check. Cross-tenant access returns **404, not 403**: a 403 confirms the id
exists and is itself an enumeration leak. Roles are owner > admin > member, and a
company can never lose its last owner.

The shared demo company is **removed** (`init_db` seeds nothing;
`get_or_create_demo_company` and `resolve_company_id` deleted). Every company is
created by a registering user who owns it.

**Frontend**: tokens live in httpOnly cookies held by the Next.js BFF, so the
browser never receives one and XSS cannot exfiltrate a session; the BFF attaches
the bearer server-side and silently rotates an expired access token mid-request.
`lib/useMockAuth.ts` deleted.

Accepted trade-off: **authentication now requires the Python backend** (no
backend ⇒ login 503). The keyless/backendless "always works" demo mode is gone by
design — that mode *was* the shared-tenant behaviour. The deterministic
TypeScript pipeline is retained as a generation fallback only: public demo corpus,
persists nothing, exposes no tenant data. Not yet addressed: rate limiting on
login / password-reset request. Public report schema unchanged (verified).

### 2026-07 · Auth hardening: fallback ambiguity, rate limiting, input caps
**Removed the authentication ambiguity in the TypeScript fallback.** The previous
build let `POST /api/generate-workflow` fall back to the local pipeline when the
backend was unreachable, gated only on a session cookie being *present*. Presence
of a cookie is not evidence of a session, so that path served an
authenticated-looking report to a caller nobody had authenticated. The
authenticated route now has **no fallback**: if the backend cannot validate the
session, it returns **503 `backend_unavailable`** and generates nothing. The
`/running` page lost its local-pipeline fallback for the same reason.

The TypeScript pipeline is retained at exactly one place, `POST
/api/demo/generate-workflow`: explicitly anonymous (it never reads the session
cookies, so it cannot be mistaken for an authenticated request), fixed showcase
input (not a free open-ended LLM endpoint), public demo corpus, **persists
nothing**, and IP-rate-limited. Public demo and authenticated product flows are now
different routes with different trust, rather than one route with an ambiguous one.

**Rate limiting** is deterministic fixed-window (`core/ratelimit.py`) rather than a
token bucket, because reproducibility is what makes the limits testable. Auth and
LLM-spend budgets are deliberately separate: generation is capped per **user** and
per **tenant** (10/h, 30/h) so one organization cannot burn the shared API quota by
fanning work across its own members. Every auth limit is counted on the *submitted*
email **before** the user lookup, so a nonexistent address consumes budget exactly
like a real one — otherwise 429-vs-401 would itself become an account-existence
oracle. Throttled responses carry `Retry-After` and `{"code":"rate_limited"}` and
deliberately expose no limit/remaining/window: a caller learns that they must wait,
never the shape of the policy.

**Proxy trust** is explicit (`EVIDENTIA_TRUSTED_PROXY_COUNT`). `X-Forwarded-For` is
ignored entirely at 0 hops; with N trusted hops only the Nth-from-the-right entry
(written by the innermost trusted proxy) is believed, so a client-injected prefix
cannot rotate the rate-limit key. The BFF forwards a single resolved client IP
rather than passing the caller's chain through.

Accepted limitations: counters are **per-process and in-memory**, so N replicas
multiply every limit by N and a restart clears them (single-process is the supported
shape; `RateLimitStore` is a Protocol so Redis drops in without touching call sites).
No CAPTCHA/proof-of-work/lockout: a distributed attacker gets a fresh per-IP budget
per host, and the per-account cap (5 logins / 15 min) is the real bound. Public
report schema unchanged; repository-level tenant enforcement, refresh-token family
rotation, and httpOnly BFF cookies preserved as-is.

### 2026-07 · Independent security review remediation (8 release blockers)
An external review found 8 blockers. Each was **reproduced with a failing test before
being fixed** (`backend/tests/test_exploits.py`; 19 of 27 failed pre-fix). Notes on the
choices that were not obvious:

**Owner invariants are a cross-row constraint, so they need a lock, not a check.**
`POST /members` upserted, which meant an admin could re-POST the *owner* with
`role=member` and silently demote them. Creation now 409s on an existing membership,
and every role mutation — promote, demote, remove, transfer — funnels through a single
`memberships.change_role` gate that takes a company row lock (`SELECT..FOR UPDATE` on
Postgres; SQLite serializes anyway). Two concurrent demotions of two different owners
would each have seen one *other* owner remaining and both succeeded, leaving none; the
lock makes the check and the write one critical section.

**Refresh rotation is now decided by the database, not the application.** The old
read-then-write let two concurrent refreshes both pass `is_usable()` and mint two valid
children. `consume_refresh_token` is a conditional UPDATE (`SET revoked_at WHERE
revoked_at IS NULL AND expires_at > now`); exactly one caller sees `rowcount == 1`.
Verified live: 1 of 12 concurrent refreshes succeeds. Because rotation is strict, a
legitimate user's parallel page requests would each try to refresh the same parent and
trip family revocation — so the BFF adds **single-flight** refresh. That is a legitimacy
fix, not a weakening: a genuine reuse *after* the flight completes still burns the family.

**Rate-limit eviction is a deliberate trade.** Every unique email minted a permanent map
entry (memory DoS) and each write swept the whole map (cost grew with the attack). The
store is now a bounded LRU with an amortized fixed-slice sweep. Evicting a counter can
hand budget back to an attacker — that is strictly better than exhausting the host. The
stronger mitigation is ordering: `check_all` enforces the **IP rule first and
short-circuits**, so once an IP is blocked it mints no further account/token keys at all.

**`X-Real-IP` cannot be made safe.** It is a single client-writable value with no chain
to validate against, so there is no hop count at which it becomes trustworthy; it is now
never read. Trusting `X-Forwarded-For` is only sound if the header can *only* come from
the proxy, so `EVIDENTIA_BFF_SECRET` lets the backend refuse any request that did not
arrive via the BFF, and production refuses `trusted_proxy_count > 0` without it. Network
isolation is still the primary control; this is defence in depth.

**`POST /api/reports` was deleted rather than validated.** It accepted an arbitrary blob,
so a client could persist a report claiming `generationMode: "llm-assisted"` with 100%
confidence and invented citations — indistinguishable downstream from a grounded report.
Schema-validating it would have kept an endpoint with no legitimate caller (the frontend
never used it; the backend persists during generation), so it is a 405 and authenticated
generation is the only path that creates a report. `personaId` association went with it.

**Production is fail-fast.** A weak `JWT_SECRET`, a console email sender (which logs
single-use reset links), wildcard CORS, or a trusted proxy without a BFF secret each fail
*open* if misconfigured — so the process refuses to boot rather than run unsafely.
Access tokens gained a `tv` (token_version) claim: password reset and logout-all bump the
user's counter, stranding outstanding access tokens immediately instead of leaving them
valid for the rest of their TTL.

**Next.js 14 → 16.** The advisory range covered all of 14.x *and* 15.x, so patching within
14 would have left known vulnerabilities; upgraded to Next 16 + React 19 (async
`cookies()`/`params`, ESLint 9 flat config). `npm audit` is clean. Next 16 promotes
`react-hooks/set-state-in-effect` to an error; it fires on correct mount-time hydration
effects, and is kept as a warning rather than rewriting six components' data loading
inside a security pass.

Public report schema unchanged. Repository-level tenant enforcement, refresh-token family
rotation, and httpOnly BFF cookies all preserved.


### 2026-07 · Release-gate review remediation (4 High + 3 Medium)

Notes on the choices that were not obvious:

**A 200 is a promise.** `/api/generate-workflow` used to catch persistence failures,
log them, and return the *unsaved* report with 200. The client then navigated to a
report id that did not exist, and an LLM call had been billed for nothing. Persistence
is no longer best-effort: DB disabled gives 503 `persistence_unavailable`, a commit
failure gives rollback + 503 `persistence_failed`, and production refuses
`EVIDENTIA_DB_ENABLED=false` outright (auth and tenancy need the database anyway, so
there was never a coherent degraded mode). The BFF distinguishes a persistence failure
from a transport failure, so the UI can say "not created" rather than "try again later".

**Authorization must be read inside the critical section.** `change_role` took a company
lock but then authorized using the actor role captured when the request was
authenticated. A mutation queued behind the lock could therefore act with authority its
actor no longer had. Both memberships are now re-read under the lock. The same class of
bug hit `company.owner_id`: a concurrent demotion left the designated-owner pointer aimed
at a user who was by then an *admin*, so the column silently stopped meaning what it
claimed. It is now atomically reassigned to another active owner, or the change is
rejected.

**token_version had to become an atomic UPDATE, and issuance had to be serialized.**
An ORM read/modify/write loses bumps under concurrency, and the counter still *moves*, so
the bug is invisible unless you count it. Worse, nothing serialized *issuing* a session
against *revoking* one: a refresh could commit its child token after the logout-all sweep
had already run, producing a fully valid session that outlived the user's own "sign out
everywhere". Login, refresh, logout-all and password reset now each take a user row lock
for the whole transaction, so a racing refresh either commits before the lock (and is
swept) or waits and observes the new token_version.

**The demo limiter's key space belongs to the attacker.** It guards an *anonymous* route,
so every source IP was a free permanent map entry, and the old sweep walked the whole map
on every request — each additional attacker made every request more expensive. Now a
bounded LRU with a fixed-slice sweep. Eviction can return budget to an attacker; that is
strictly better than exhausting the Next process's memory.

**Concurrency tests that share a Session are worse than no tests.** The harness gave every
request and every thread the same SQLAlchemy Session (StaticPool, one connection), so the
races we were trying to prove could not occur inside a single transaction — the tests
passed by construction. They now run against a file-backed SQLite database (WAL + busy
timeout) with a fresh Session per request and per worker, worker exceptions collected and
asserted empty, and `PytestUnhandledThreadExceptionWarning` promoted to an error (verified
to actually fail a test when a thread dies).

**A fake email sender is not a feature.** `console` writes a single-use account-takeover
link into the application log and `noop` silently discards it — both make password reset
*look* like it works. Rather than document the gap, we implemented a real
`SMTPEmailSender` (stdlib `smtplib`, no new dependency) and made production refuse
anything else. It has not been exercised against a live provider; that is recorded as a
known limitation.

Public report schema unchanged. Repository-level tenant enforcement, refresh-token family
rotation, and httpOnly BFF cookies all preserved.

## 2026-07-14 — Targeted re-review remediation (pass 4)

**A lock taken after the decision is not a lock.** Login verified the password *before*
acquiring the user row lock, so a login could approve the old password, pause, let a
concurrent password reset revoke every session, and then resume under the lock and mint a
session carrying the *new* `token_version` — a live credential produced by a password
that had just been reset away. The lock is now taken before the security-sensitive
decision and the row is re-read under it, making verification and session issuance one
critical section. `password-reset/confirm` likewise locks the user before burning the
token, so the single-use check, the password change, the revocation sweep and the version
bump all serialize against every issuer of a session.

**A "re-read under the lock" that goes through the ORM identity map re-reads nothing.**
SQLAlchemy returns the instance already in the Session and discards the row it just
selected. Pass 3 added re-reads to the authorization gate believing they were
authoritative; they were not. `db.get(Company, …)` returned the request's `ctx.company` —
strongly referenced, therefore reliably stale — and a demotion queued behind a concurrent
ownership transfer compared against a stale `owner_id`, skipped the reassignment, and left
`company.owner_id` naming a demoted admin. Every read in the gate now uses
`populate_existing`, and the owner pointer is re-derived from the owner rows under the
lock after every mutation rather than inferred from its previous value.

Worth recording because it was nearly invisible: the *actor role* staleness was masked by
the identity map holding **weak** references — nothing kept the preloaded membership
alive, so it was usually collected before the gate re-read it and the stale value surfaced
only sometimes. Authorization that is correct only when the garbage collector happens to
have run is not correct, and a test that passes for that reason is not evidence.

**Creation is a role grant.** `POST /members` authorized from `ctx.role` (captured when
the request was authenticated, outside any lock) and took no lock at all, so an admin whose
demotion had already committed could still invite — and mint admins. Member creation now
goes through the same locked, re-reading gate as a role change.

**Length is not unpredictability.** The BFF secret gate required 32 characters and 8
distinct characters, which accepts `abcd1234abcd1234abcd1234abcd1234`. Production now
requires a cryptographically generated secret — the base64url or hex encoding of ≥32
random bytes — and additionally rejects known-weak values, repeated blocks, sequential
runs, narrow alphabets (word lists), low estimated entropy and highly compressible values.
Per-character floors are alphabet-relative, because a genuine `token_hex(32)` legitimately
shows lower per-character entropy than a genuine `token_urlsafe(32)`; a single threshold
rejected real output. The gate cannot *prove* randomness — that guarantee comes from the
documented generation command, which the error message carries.

**A concurrency test must prove it was concurrent.** The stale-authority test was
sequential and proved nothing about queueing. The queued tests now assert that the second
writer finished *after* the first released the lock, so two merely-overlapping threads
cannot masquerade as a serialized test, and `token_version` assertions are exact (the
counter must move by exactly the number of accepted calls — `>= 1` also passes with a lost
update). SQLite and PostgreSQL semantics are separated: the default suite proves the
application locks before it decides, on a whole-database write lock; an opt-in
`EVIDENTIA_TEST_DATABASE_URL` profile exercises real `SELECT … FOR UPDATE` row locks, and
those tests skip loudly when it is unset. PostgreSQL locking remains unverified locally
and is recorded as the last open assumption behind these fixes.

`JWT_SECRET` deliberately keeps its older length/variety check: the review scoped the
generated-secret requirement to the BFF secret, and widening it was out of scope. The same
weak value would pass it, and that is recorded as an open concern rather than silently
fixed.

Public report schema unchanged.

## 2026-07-14 — Final release blockers: PostgreSQL locking verified, JWT secret parity

**The last unverified assumption is now verified.** The opt-in concurrency profile ran
against a real PostgreSQL 16.14 (Docker, `postgresql+psycopg://`): all 15 tests in
`test_concurrency.py` — including the two PostgreSQL-only row-lock tests — passed in
**15 consecutive runs** (0 failures). `SELECT … FOR UPDATE` behaved exactly as the
H1/H2 fixes assume: the queued writer blocked until the lock holder committed (proved
by the finished-after-release assertions), stale-authority mutations were re-read and
refused under the lock, refresh rotation minted at most one child, and
`company.owner_id` never left the set of active owners.

**One real difference vs SQLite surfaced, in the harness, not the application.** The
queue-proof compared `time.monotonic()` timestamps, which on Windows CPython 3.12
ticks in ~15.6 ms steps. PostgreSQL hands a released row lock to the queued waiter so
fast that "released" and "finished" landed in the same tick, failing the strict `>` on
equality; SQLite passed only because its busy-wait retry loop made the gap wider than
one tick. The timestamps now use `time.perf_counter()`. A timing proof is only as good
as its clock. (`pytest.ini` also promotes `PytestUnraisableExceptionWarning` to an
error, alongside the existing thread-exception promotion.)

**JWT_SECRET now has parity with the BFF secret gate.** Pass 4 recorded (as an open
concern) that the JWT signing key kept the older "≥32 chars, ≥8 distinct" check, which
accepts `abcd1234abcd1234abcd1234abcd1234` — and that key signs every access token in
every tenant. The shared generated-secret gate (`_generated_secret_problem`) now backs
both `jwt_secret_problem` and `bff_secret_problem`: production requires the base64url
or hex encoding of ≥32 random bytes and rejects known defaults, weak substrings,
repeated blocks, sequential runs, narrow alphabets, low estimated entropy and highly
compressible values. Development and tests still run on the dev default — the gate is
production-only, validated on every sign/verify, not just at startup. Regression tests
prove the old gate-passer is rejected, `token_urlsafe(32)`/`token_urlsafe(48)`/
`token_hex(32)` are accepted (50 samples each, 0 false rejections; 2000 offline), and
a JWT forged with the published dev default is refused once a real key is set — as is
any session issued under the old key. Hand-typed "strong" test constants were replaced
with generated ones: a hand-typed value passing a statistical gate is luck, not a
guarantee.

Public report schema unchanged.

## 2026-07-14 — Platform architecture constitution (design only; no code changed)

The customer-document-ingestion proposal was reviewed by a Staff-Engineer-level
architecture review and **conditionally approved**; the conditions are
incorporated and the consolidated long-term architecture is recorded in
`docs/ai/PLATFORM_ARCHITECTURE.md`, which is now the architectural source of
truth. The following decisions are settled. Foundations reaffirmed and not to
be relitigated: deterministic-first over generic RAG, evidence-first claim
acceptance, immutable document versions with atomic flips, staged retrieval,
Protocol seams, the demo corpus as benchmark/sample corpus, and no redesign of
auth/tenancy/eval.

**Claims-as-data over generic retrieve-then-generate RAG.** Claims come from a
deterministic, category/topic-keyed pattern library; `sourceDocId` is resolved
by retrieval; the evidence-support gate remains the sole grounding authority.
LLMs may *propose* claims in full mode, but every proposal compiles into the
same claim contract and passes the same gate. Rationale: RAG would delete the
`off` mode, orphan the structural gate's deterministic baseline, invert the
calibration verdict, and weaken hallucination containment; moving from
patterns *toward* more LLM involvement is incremental, the reverse is a
rewrite.

**CAD as the eventual internal canonical representation; EvidentiaReport as its
first compatibility projection.** The reasoning engine's true output becomes a
domain-independent Canonical Analysis Document (provenance, evidence bindings,
claims, findings, contradictions, gaps, confidence, recommendations, actions,
narrative blocks, metrics, module extensions, reasoning-free renderer hints).
The public `EvidentiaReport` schema is unchanged and becomes a deterministic
projection of CAD. Not migrated yet; recorded now so the public schema stops
accreting domain-specific fields — every proposed report field must first
answer "CAD concept, module extension, or renderer concern?" The rendering
invariant is binding: rendering is a pure deterministic transformation of an
immutable snapshot; renderers never call LLMs, retrieve, score, or create
claims; push renderers separate rendering from delivery state (idempotency
keys, retries, external refs).

**Domain modules as versioned data packs; the engine never branches on a
taxonomy label.** The core knows only documents, sections, evidence, claims,
findings, gaps, contradictions, recommendations, actions, confidence,
provenance. Taxonomies, topics, facets (including the current market flags),
classification signatures, personas, critical-category mappings, claim
patterns, templates, fixtures and benchmark scenarios are namespaced,
versioned module data (`modules/compliance/…` is Module #1 — the current demo
taxonomy keeps its labels; ownership moves out of engine code). A module
registry pins module versions per tenant. Lint/CI enforces the
no-label-branching rule from M3. No code plugins in v1.

**Claim patterns are declarative rules over typed code primitives.** A small,
closed, versioned set of matcher primitives (signals, phrases, exclusions,
negation, contradiction contracts, staleness, gap checks, source requirements,
slot templates, severity rules, thresholds) is implemented in code; patterns
are schema-validated YAML/JSON with stable namespaced ids, versions, claim
family, triggers, evidence requirements, exclusions, templates, severity
policy, positive AND negative fixtures, and a changelog. Patterns are never
executable code; no custom DSL until the primitives are proven insufficient.
Every pattern's fixtures run in CI (the detection-rule model); releases import
into immutable runtime records and appear in report provenance. M5 is split:
M5a bounded engine plumbing, M5b ongoing content authoring — pattern content
is not a fixed two-week task.

**Full-text deterministic scoring; the excerpt is display/prompt-budget only.**
The prior draft fed scorers `sectionTitle + excerpt` (~1,200 chars); on
customer documents that blinds the gate to up to ~70% of a long section and
produces false insufficient-evidence results correlated with writing style,
indistinguishable from genuine gaps. Deterministic scoring consumes the full
bounded section text via token sets precomputed at ingest (cost unchanged).
Lands at M4.

**Complete engine provenance on every report from the first customer report
(M4).** `reports.source_versions` (document/version/parser) plus
`reports.engine_versions` (engine release, module versions, pattern-library,
signature-pack, taxonomy, threshold-policy, anchor-algorithm, benchmark,
retrieval strategy, tenant glossary, LLM provider/model/prompt when used) —
DB metadata, not public schema. Rationale: document pins alone cannot answer
"why did this report change?"; reports generated without provenance can never
be repaired retroactively. This was moved from the versioning-UX milestone
(M8) to M4 deliberately.

**Versioned anchor algorithms.** The heading-path anchor scheme is formalized
as an identity algorithm with `anchor_algo_version` on document versions;
constants (size bounds, hash truncation, Jaccard threshold, normalization) are
part of the version — no in-place tuning; deterministic tie-breaking
(similarity → exact hash → document order → final key); a golden fixture
corpus in CI covering rename, edit, split, merge, duplicates, insertion before
duplicates, rename+split, and size-bound oscillation. New algorithm versions
coexist with old ones: persisted reports never re-resolve, old versions are
never re-anchored, inheritance runs over content.

**Retrieval is candidate generation only.** Stage 1 scoped lexical → Stage 2
Postgres FTS → Stage 3 optional hybrid/embeddings, each behind an explicit
trigger; the deterministic gate accepts or rejects evidence; embeddings and
tenant-glossary expansion may widen what the gate sees, never what it accepts,
and never weaken thresholds. Stage 3 requires *measured* synonymy failure via
a new sensor: users can report "evidence exists but was missed", creating
`retrieval_misses` rows (pattern id/version + the human-identified anchor) —
shipped with M5a because without it the Stage-3 trigger is unobservable.

**Learning through versioned releases, never online drift.** Tenant-scoped
feedback entities (`report_feedback`, `item_feedback`, `citation_feedback`,
`retrieval_misses`, `tenant_glossary`, pattern/signature/threshold version
tables, retrieval/pattern metrics). Tenant text never enters a global dataset
automatically — it crosses the tenant boundary only through a human, under an
explicit agreement, into a code-reviewed release. Loop A: tenant-local
deterministic adaptation (glossary, config, pins), versioned and recorded in
provenance. Loop B: global human-mediated releases gated on benchmark
regression. No online self-modification; no silent threshold drift.

**Operational corrections adopted as milestone gates.** Version-aware AND
LRU-bounded report cache (the unbounded `_CACHE` becomes customer-keyed the
moment tenant selections enter it — same defect class as the rate-limit store
fixed in pass 2); tenant-fair job claims instead of pure FIFO; claim-time
attempt increments; explicit blob/row crash-safe write order plus orphaned-blob
reconciliation; `classifier_version`/`signature_pack_version` provenance on
sections; the M9 FTS-column table-rewrite cost decided at M9 entry.
`report.company` carries the tenant's company name for tenant-corpus reports —
a value change within the existing schema shape, shipped behind the corpus
flag.

**Knowledge graph deferred.** A future entity/relation layer may assist
candidate retrieval and context assembly (entities/relations as additive
annotations referencing section anchors), justified only by telemetry
(entity-aliasing retrieval misses, cross-document contradiction demand). It
must never become a grounding authority: claims cite sections; the gate scores
section text; a graph edge is never itself evidence.

Public report schema unchanged. No application code was changed by this
consolidation — documents only.

## 2026-07-15 — M1 implementation decisions (schema + seams + typed contracts)

M1 implemented per the `PLATFORM_ARCHITECTURE.md` §12 gate. Three
implementation-level decisions made where the design left latitude:

**`documents.current_version_id` carries no DB-level foreign key.** A real FK
would make `documents` and `document_versions` reference each other circularly;
SQLite (the dev database, where the test schema is created via
`Base.metadata.create_all`) cannot add the second constraint of a circular
pair. Integrity is application-enforced at the single atomic flip site (only
ever to a `ready` version) — the same posture as `company.owner_id`
re-derivation. Recorded in the migration docstring
(`f7c3a1b9e2d4_document_ingestion_schema.py`).

**The M1 backfill creates `pending` versions, not `ready` ones.** The
sectionizer does not exist until M2, and a version must never be visible to
generation before its sections are complete. `scripts/backfill_documents.py`
therefore synthesizes version 1 + blob + a `queued` ingestion job per
`content_text` document and leaves `current_version_id` NULL; the M2 worker
takes it from there. Idempotent (any-version ⇒ skip); one document per commit.

**`SectionRecord.to_pipeline_section(source_title)` takes the document title
as a parameter.** The pipeline currency's `source` field is the owning
document's display title — document-level state the §5 field list deliberately
does not duplicate onto every section — so the provider (which holds the
document row) supplies it at projection time. Every other currency field is a
strict field-for-field projection, pinned by test against the demo reader's
actual output shape.

## 2026-07-15 — `/running` lifecycle and Strict Mode request ownership

**Successful report navigation is a dedicated effect.** Request completion stores
only the persisted report id; the presentational animation stores its own completion
state. Navigation occurs once after both exist, with its guard set before
`router.push`. Functional state updaters remain pure and contain no navigation,
timers, networking, or cross-state writes.

**One workspace click carries a session-scoped run nonce.** React Strict Mode
replays effects as setup → cleanup → setup, which previously started two POSTs and
let the cleanup-aborted subscription surface a false unavailable state. A
module-scoped registry now shares only the live request keyed by nonce + exact
input. Its zero-delay idle abort lets the synchronous replay re-subscribe, while a
real unmount still cancels. Settled entries are removed immediately; retry writes a
fresh nonce. The pending input/nonce remains session-scoped and is purged on session
change; authenticated report content is never stored in browser storage.

**Every callback proves active-run ownership.** Stale request results, slow timers,
and cleanup cancellations cannot update or navigate a newer run. The backend's
generation and persistence behavior, authenticated no-fallback rule, and public
`EvidentiaReport` schema are unchanged.

**A 200 must carry a persisted report id.** `/running` can only complete by
navigating to `/reports/{id}`, so a 200 whose body is unparseable, not an object,
or lacks a non-empty string `id` is a malformed success: it maps to the generic
failure state rather than success (never to unavailable, which promises "nothing
was generated"). Only this minimum persistence/navigation contract is validated
client-side; a full `EvidentiaReport` runtime validator is deliberately out of
scope.

**Rendered header labels wait for mount.** `/running` is statically prerendered,
so its server HTML always shows the default persona/market. The stored selection
is rendered only after mount to keep hydration consistent; the run input itself
is still read from storage during the first client render, so the generation
effect POSTs the real selection immediately and the label re-render starts no
second request.

**Client single-flight scope (recorded limit).** The nonce-keyed registry
guarantees one request per logical run within one tab/mount lifecycle. It does
**not** deduplicate across browser tabs, after navigating back to `/running`, or
against server-side replay. True end-to-end idempotency (e.g. a backend-honored
`Idempotency-Key`) belongs to a later backend/API milestone.

## 2026-07-16 — M2 implementation decisions (MD/TXT upload + ingestion spine)

M2 implemented per the roadmap (multipart upload, validation/caps/dedupe/
quotas/rate limits, DatabaseJobQueue worker operations, in-process worker,
MD/TXT parsers → DocIR v1 → sectionizer, atomic persistence, documents UI).
Five implementation-level decisions made where the design left latitude:

**Transitional section identity — the M3 anchor algorithm is NOT pre-empted.**
`document_sections.anchor_id`/`citation_id` are NOT NULL, but the heading-path
anchor algorithm is a frozen-forever M3 surface (versioned constants, golden
fixtures, tie-breaking) that M2 must not freeze by accident. M2 therefore
writes ordinal-based *internal* identifiers (`s0007` / `pre-m3:s0007`) and
stamps `anchor_algo_version = "pre-m3-transitional"` on every version it
completes. These ids are never exposed through any API, UI or report:
generation cannot read tenant sections until M4, which depends on M3, so no
public citation identity exists yet. M3 re-anchors `pre-m3-transitional`
versions through the same defined re-processing trigger as a parser upgrade —
no report-frozen id can be affected because none has been minted.

**`ready` in M2 means "parsed and sectionized", and M2 does flip
`current_version_id`.** The design (§1 step 8) makes the flip part of
ingestion completion, and the M1 rule (single controlled flip site, only ever
to a `ready` version) is enforced in exactly one function
(`pipeline._flip_current_version`). The pre-M3 meaning is machine-readable via
the transitional `anchor_algo_version`, and the UI words it honestly
("Processed … not yet used for report generation"). The `classifying` state is
reserved for M3 and never entered in M2.

**JSON document creation routes through the ingestion spine only when the
corpus flag is on.** With the flag off, `POST /api/documents` stays
byte-for-byte the pre-M2 behavior (response key set is test-pinned). With the
flag on it additionally synthesizes version 1 + blob + queued job (the
backfill shape), which is the §9 "existing JSON create routed through the same
pipeline" requirement without any silent behavior change for existing callers.

**Duplicate/retry semantics on the version level.** Tenant-scoped dedupe keys
on the actual uploaded bytes (`documents.content_sha256`); an identical
new-document upload returns the existing document explicitly (200,
`duplicate: true`) and stores nothing. A byte-identical new *version* is an
explicit no-op (200, `noop: true`) — except when the latest version FAILED, in
which case the same bytes are a retry: the immutable version row and blob are
reused and only a new job is enqueued. Cross-tenant dedupe deliberately does
not exist (identical bytes in two tenants are two blobs) — blob-level physical
dedupe would be a cross-tenant information channel and was not approved.

**Soft delete stays deferred.** `DELETE /api/documents/{id}` remains the hard,
cascading delete (versions/blobs/sections/jobs go with the document, verified
by the M1 FK-cascade test). The §3 soft-delete semantics exist to keep
"view source" resolvable for persisted reports — impossible before M4 reports
cite tenant sections — so wiring it now would change existing API behavior for
no reachable benefit. Lands with the versioning UX milestone.

Also recorded: the sectionizer's documented bounds (200 min-fragment /
4,000 max / 1,200-char excerpt) are M2 sectionizer behavior
(`SECTIONIZER_VERSION = m2.1`), not yet the frozen M3 anchor-algorithm
constants; `alembic check` reports pre-existing nullable drift on four legacy
auth-table timestamp columns (`company_members.updated_at`,
`refresh_tokens/email_verification_tokens/password_reset_tokens.created_at`) —
present on main before M2, untouched by M2 (no model or migration changed),
zero drift on ingestion tables. Public report schema unchanged; report
generation still reads only the demo corpus (verified by test and smoke).

## 2026-07-16 — M2 independent review remediation (lifecycle contract pinned + JSON create abuse bounds)

The complete M2 diff was independently reviewed: **approve with fixes**, no
commit blockers. Two fixes applied; two findings deliberately deferred and
recorded as debt (see PROJECT_STATE "Deferred debt").

### Binding constraint — the M2→M3 version lifecycle contract

This is a **binding architecture constraint**: an explicit **M3 entry
criterion** and an explicit **M4 TenantCorpusProvider invariant**. It pins how
the transitional M2 identity is retired, so that "immutable versions" survives
the M3 re-anchoring rather than being quietly violated by it.

1. **M2-ready versions stamped `anchor_algo_version = "pre-m3-transitional"`
   are immutable.** M3 must never mutate the ready `document_versions` row,
   its existing `document_sections`, its transitional `anchor_id` values, its
   transitional `citation_id` values, or its `manifest_sha256`.
2. **M3 finalization happens by re-ingestion into a NEW `document_versions`
   row**, re-processed from the retained source blob — the same defined
   trigger shape as a parser upgrade. The old M2-ready version and every one
   of its sections must remain **byte-for-byte unchanged** after M3
   re-ingestion.
3. **The new version receives**: the final versioned anchor algorithm, final
   internal citation identities, deterministic classification, a new manifest,
   `ready` status, and the controlled single-site `current_version_id` flip.
4. **M4's TenantCorpusProvider must explicitly reject/filter any version whose
   `anchor_algo_version == "pre-m3-transitional"` — even if
   `current_version_id` points to it.** `status == "ready"` alone is NOT
   sufficient evidence of generation eligibility; eligibility requires a
   final (non-transitional) anchor algorithm version. Rationale: `ready` in M2
   means only "parsed and sectionized", and a tenant who uploaded documents in
   M2 but never triggers re-ingestion would otherwise have transitional,
   never-frozen ids minted into persisted reports.

Nothing about the current M2 state machine or `current_version_id` behavior
changes now; the contract constrains *future* M3/M4 code only.

### Fix — flag-on JSON create shares the multipart abuse bounds

The review found that with `EVIDENTIA_TENANT_CORPUS_ENABLED=true`, the legacy
JSON `POST /api/documents` routed through the ingestion spine (version 1 +
blob + queued job) while bypassing every abuse bound the multipart path pays:
upload rate limits, the tenant document-count quota, the stored-byte quota,
and the company-row lock — a quota bypass reachable by any authenticated
member the moment the flag turns on.

The flag-on JSON path now goes through
`document_upload.create_json_document`, which reuses the *same* internals as
multipart (`enforce_upload` first — counted before any row is touched — then
`_lock_company`, then `_enforce_quotas_locked` on the **actual UTF-8 byte
size** of `contentText`, then document + version + blob + job in **one
transaction**). Same typed codes (`rate_limited`, `document_quota_exceeded`,
`storage_quota_exceeded`); a rejection leaves no document, version, blob or
job. There is deliberately **no second quota policy** — the JSON path calls
the multipart helpers, it does not reimplement them. The flag-off JSON path
is untouched (byte-for-byte pre-M2, still test-pinned; no new rate/quota
semantics were introduced to disabled mode). Verified by 7 new API tests plus
two PostgreSQL two-writer boundary races (count-quota and byte-quota: exactly
one winner, typed loser, persisted rows/bytes within quota).

## 2026-07-17 — M3 implementation decisions (anchors, citation identities, deterministic classification)

M3 implemented per the PLATFORM_ARCHITECTURE.md §12 gate and the binding
M2→M3 lifecycle contract above. The frozen identity surfaces and the
implementation-level decisions made where the design left latitude:

**The final anchor algorithm is `heading-path-v1`; inheritance is
`content-match-v1`.** Anchor = `base36(sha1(normalized heading path))[:5]`
with document-order duplicate suffixes (`slug-2`) and split-part suffixes
(`slug.p1`); normalization is per-element NFC → casefold → whitespace
collapse. Every constant is part of the version (slug length 5, Jaccard
inheritance threshold 0.8, the §7.3 tie-break order, the 250,000-pair
guarded-pass budget, the sectionizer bounds it composes with) — no in-place
tuning, ever. Inheritance is defined over content (text_sha256, token sets),
never algorithm internals: exact re-attachment inside duplicate groups runs
BEFORE renumbering is accepted; disappeared anchors are matched exact-first,
then Jaccard ≥ 0.8, with the §7.3 tie-break making every match one-to-one
and deterministic; unsafe candidates mint fresh. The guarded pass skips
deterministically (minting instead) past the pair budget — bounded cost,
never a wrong inheritance. Transitional (`pre-m3:*`) ids never participate:
the first final version of a document mints everything fresh, exactly as the
lifecycle contract requires.

**Regular M2 ingest stays transitional; finalization is an explicit
operation.** Uploads keep producing `pre-m3-transitional` versions; M3
finalization re-ingests the retained blob into a NEW successor version
through the full path `pending → extracting → sectioning → anchoring →
classifying → ready`. This keeps every committed M2 behavior and test intact
and makes the upgrade controlled rather than ambient. The job discriminator
is explicit and migrated: `ingestion_jobs.operation` ("ingest" default |
"finalize"), never inferred. `document_versions.source_version_id` +
`finalization_engine` (= the anchor algorithm target) record successor
provenance, and the unique index `uq_document_versions_source_engine` makes
one-successor-per-(source, engine) a database guarantee — concurrent
triggers converge on one successor (PostgreSQL-verified). Successors carry
**no blob copy**: the pipeline resolves bytes through `source_version_id` to
the retained source blob (the M1 one-blob-per-version constraint holds; no
byte duplication).

**The flip site became a guarded conditional UPDATE.** The single
`current_version_id` flip site now only moves the pointer when the current
version is NULL or strictly lower — a stale or lower finalizer can never
move the pointer backwards under any interleaving (PostgreSQL race test with
repeated runs). A failed successor never touches the pointer.

**Citation prefixes are minted at first finalization, DB-arbitrated.**
3–5 uppercase chars from the document title's significant initials
(consonant-padded), deterministic candidate sequence base/base2/base3…, and
the tenant-scoped unique index is the allocation authority (SAVEPOINT +
conditional UPDATE per candidate; the loser adopts or takes the next
suffix). Once set the prefix is immutable and reused by every later
finalization; `citation_id = {prefix}-{anchor}`. All final identities remain
**internal** in M3: no citation id, section text or manifest crosses any API.

**Domain modules are JSON data packs; the compliance module is
`compliance@1.0.0`.** `app/modules/compliance/1.0.0/{module,taxonomy,
signatures}.json` carries the frozen eight-category taxonomy + `General` as
the explicit below-threshold fallback, ~28 topic rules, four market-facet
rules (the existing `HIGH_COMPLIANCE_MARKETS` + EMEA vocabulary), seven
persona needle sets (from the documented persona profiles), per-category
weighted signatures with heading/body/phrase weights, thresholds, and
exclusion rules (each with its own rule id). The loader validates the full
schema and fails closed (`ModuleValidationError`); the pack digest
(sha256 over canonical JSON) participates in every signature and manifest.
JSON was chosen over YAML to avoid a new dependency; the format is loader
detail, not contract. The classifier engine (`CLASSIFIER_VERSION = m3.1`)
executes module data generically and **never branches on a taxonomy label**
(pinned by a test that scans the engine sources for label literals);
injection screening (instruction-override / role-marker / prompt-reference /
jailbreak-vocabulary flags) is engine security data versioned with the
classifier, not domain vocabulary. Classification consumes the FULL bounded
section text (test-pinned against excerpt-only), records matched rule ids,
and emits a canonical per-section signature (sha256 over inputs/outputs +
classifier/module/threshold identity — no timestamps, no row ids) plus a
version-level signature over the ordered section signatures.

**The final manifest is canonical JSON, `MANIFEST_VERSION = m3.1`.**
manifestVersion, content/extracted hashes, citation prefix, the full
engine-version dict (parser, normalizer `m2.1`, sectionizer `m2.1`, anchor
algo, inheritance, classifier, manifest, module id/version/digest), and the
ordered sections (anchor, citation id, text hash, heading path, structure
flags, classification outputs, matched rules, per-section signature).
sha256 over sorted-keys/no-whitespace/ASCII serialization →
`document_versions.manifest_sha256`; the dict itself persists in
`engine_versions` + per-section columns. The M2 transitional manifest format
coexists untouched.

**The M4 eligibility predicate ships now, unconsumed**
(`services/generation_eligibility.py`): ready + supported final anchor algo
(never `pre-m3-transitional`, even when current) + well-formed manifest
sha + complete engine_versions incl. module signature + version-level
classification signature + section count + no terminal error + same tenant;
anything malformed fails closed. The orchestrator does NOT consume it — that
is M4.

**Worker ownership debt: assessed, bounded, deliberately kept.** M3
finalization stays MD/TXT-bounded (≤1M chars, guarded-pass pair budget,
regex classification over ≤4,000-char sections); the smoke finalizes real
documents in well under a second, orders of magnitude below the 300s stale
threshold, so the M2 lease/epoch debt remains safe and stays scheduled for
M6/M7. Two small hardenings landed anyway: the finalize pipeline heartbeats
between stages via a worker callback and aborts (`OwnershipLost`) without
failing the version when the stale sweep has reclaimed the job.

**Golden fixtures are the identity regression contract.** 12 fixtures
(identical reprocessing, insert/delete/move, light edit, rename+rewrite,
duplicate sections, insertion before duplicates, heading-less text, split
oversized section, plus base coverage of code blocks/tables/omission
markers/compliance-positive/exclusion-negative/unclassified/injection) pin
ordered sections, anchors, decisions, citation ids, labels, rule ids,
signatures and manifests in `tests/golden/expected/*.json`. Tests compare
exact equality; regeneration is only the explicit reviewed command
`scripts/regenerate_golden_fixtures.py`.

**Verified 2026-07-17**: backend SQLite **539 passed / 9 skipped** (95 new
M3 tests: 24 anchors, 23 classifier/module, 9 manifest, 14 golden, 24
finalization/API/backfill + concurrency skips); PostgreSQL 16: 195
M3+ingestion tests and **21 concurrency tests** (3 new: one-successor race,
prefix-allocation race, pointer-never-backwards ×5 interleavings); Alembic
`a9d2e4c7b1f3` cycled base→head→−1→head on SQLite AND PostgreSQL;
`alembic check` still shows only the 4 pre-existing legacy auth nullable
drifts (zero on M3 columns); frontend 50/50 vitest (5 new M3 state tests),
ESLint 0 errors, tsc clean, production build clean; CLI dry-run/execute/
re-run smoke on a migrated scratch DB (flag-off refusal included); 26-step
live smoke on PostgreSQL 16 through the production BFF: transitional v1
byte-for-byte unchanged, `classifying` stage observed live, anchors equal to
the golden values across environments, repeat-finalize 409, v2→v4 anchor +
citation inheritance, kill-and-restart recovery with no duplicates,
generation demo-only (no tenant text/ids in the report), flag-off restart
disables M3 while generation still returns 200. Public `EvidentiaReport`
schema unchanged; no M4 functionality implemented.

### 2026-07-17 · M3 pre-release blocker corrections (independent review BLOCK)
An independent review of the still-uncommitted M3 diff returned BLOCK with
seven commit blockers. M3 had not shipped and no permanent identity had been
released, so the frozen algorithms/migration/fixtures were corrected in place
(a coherent first released version) rather than versioned-around. All seven
plus the related hardening are fixed; the whole diff stays uncommitted for a
final review.

**1 · Anchor slug widened 5 → 12 base36 chars; identity is the FULL canonical
heading path, never the slug.** The old `base36(sha1(path))[:5]` collided
(reviewer's "Adversarial heading 8720"/"9588" both hashed to `mfpfz`), and a
truncated-slug match silently transferred an anchor to an unrelated section
through the heading-kept path. Now `heading_path_digest()` (full sha1 of the
normalized path) is the identity used for duplicate grouping, heading-kept
inheritance and part lineage; the 12-char slug is display only. Distinct
canonical paths that share a slug prefix extend deterministically in 4-char
steps from each heading's OWN digest (up to the full 31-char base36 digest),
and a minted slug may never textually reuse a retired prior anchor base of a
different heading (`foreign_bases` guard). `ANCHOR_ALGO_VERSION` stays
`heading-path-v1` (never shipped). **Collision risk:** 12 base36 chars ≈ 62.04
bits; per-document birthday probability ≈ n(n−1)/2^63.04 (n=1,000 → ≈1.1e-13;
n=10,000 → ≈1.1e-11); uniqueness is per-document so corpus size does not
compound it, and even a crafted slug collision cannot corrupt identity (full
digests compared, deterministic extension, final uniqueness guard).

**2 · `finalization_engine` is now a COMPLETE finalization target digest**
(`ingestion/finalization_target.py`, `CompleteFinalizationTarget`,
`cft1:<sha256>` over canonical JSON). It covers parser name+version,
normalizer, sectionizer, anchor algo, anchor inheritance, classifier,
section-signature format, module id/version/digest/signatureVersion, manifest
version and the module thresholds + weights. Captured at trigger/enqueue time
and pinned on the successor; the worker recomputes the target and refuses
(`unsupported_finalization_target`, fail closed) any job whose pinned target
it cannot reproduce, so newer/older code, a different pack or different config
never silently produces a different artifact. Uniqueness
`(source_version_id, finalization_engine)` now means one successor per source
and COMPLETE target — changing ANY component creates a distinct successor.
One builder serves trigger, CLI, worker and eligibility. Column widened
40 → 80.

**3 · Source/successor integrity is DATABASE-enforced.** A composite
self-reference `(source_version_id, document_id, company_id) → (id,
document_id, company_id)` (with the parent unique key
`uq_document_versions_id_doc_company`) makes a cross-document or cross-tenant
source unrepresentable and blocks deleting a referenced source alone, while
whole-document/tenant CASCADE still removes source+successor together. Chain
rule made explicit: a successor references ONLY the blob-owning transitional
upload version (service-enforced direction, DB-enforced ownership). The M3
migration was AMENDED (revision `a9d2e4c7b1f3`), not stacked. **Downgrade is
data-preserving:** it first materializes a `document_blobs` row per successor
by copying the source's DB-backed bytes (so dropping `source_version_id`
cannot strand successor bytes), and REFUSES rather than stranding when a
source blob is not DB-backed, or truncating when a `citation_prefix` exceeds
the M2 width.

**4 · M4 eligibility fails closed against an explicit supported-target
registry.** `supported_finalization_targets()` enumerates the exact complete
targets the current platform can reproduce; a version is eligible only when
its pinned target is registered AND every stored component (parser →
normalizer → sectionizer → anchor algo → inheritance → classifier → section
signature → manifest → module id/version/digest/signatureVersion) matches a
supported value, each rejected independently. It also validates the PERSISTED
sections: count vs manifest, ordinal completeness, final non-transitional
anchors, final citation ids, per-section classification signature, per-section
anchor-algo provenance, exact manifest reconstruction against the stored
digest, and the version signature over the ordered section signatures. Any
malformed/partial metadata returns ineligible, never raises. Still unconsumed
(M4 owns integration). The predicate now takes a `Session` (section reads).

**5 · The classification signature covers the heading input.** The classifier
scores over `classification_heading_input(draft)` (folded heading path +
title); that exact canonical string is now in the section-signature payload
(`headingInput`), so two sections with equal text/anchor/output but different
heading inputs get different signatures. `SECTION_SIGNATURE_VERSION = 1`.

**6 · Citation-prefix candidates cover the configured tenant quota.**
`prefix_candidates(title, limit)` yields `limit+1` candidates and
`ensure_citation_prefix` passes `evidentia_tenant_max_documents` (default 500),
so even when every title derives the same base (empty/punctuation-only/
non-Latin all → `DOC`) a tenant can allocate through its whole quota; genuine
exhaustion raises the typed `citation_prefix_failed`. `documents.citation_prefix`
widened 8 → 12 (5-char base + up to 7 suffix digits).

**7 · Golden corpus completed + integrity-locked.** Added authored fixtures
and static expected outputs for **merge**, **rename+split** and size-bound
**oscillation** (base/grow/shrink, recursive prior chains). `REQUIRED_GOLDEN_CASES`
is asserted set-equal to the registered plan so an omission can never pass
silently; tests never regenerate (explicit reviewed command only); a new
integration golden runs the REAL M2→M3 API/worker/persistence path and
compares persisted anchors/citations/decisions/classifications/rules/
signatures/target/manifest to the corpus. Expected files now also pin the
complete-target digest. 17 fixtures total.

**Hardening:** module `engineCompatibility` + `signatureVersion` are validated
by the loader AND enforced (`ensure_module_compatible`, participating in the
complete target and eligibility); CLI rejects `--limit ≤ 0` and `> 1000` and
`--process` drains ONLY that invocation's successors (never the global queue);
the finalize API docstring pins the tested contract (already-final → 409
`already_final`); a stale `ANCHOR_INHERITANCE_VERSION`/`NORMALIZER_VERSION`/
`MANIFEST_VERSION` import in the pipeline was removed (engine_versions now
comes from the target projection).

**Verified 2026-07-17 (corrections):** backend SQLite **586 passed / 11
skipped**; PostgreSQL 16 targeted M3+ingestion **300 passed**; PostgreSQL
**23 concurrency** (2 new: identical-complete-target → one successor with a
`cft1:` engine; source/successor integrity under real row locks); golden
suite green under `PYTHONHASHSEED` 0 and 12345; data-bearing migration cycle
(M2 seed → M3 → hostile-reference rejection → data-preserving downgrade with
blob materialization → re-upgrade) OK on SQLite AND PostgreSQL 16; `alembic
check` shows only the 4 pre-existing legacy auth nullable drifts (zero on M3);
CLI bounds + scoped `--process` + flag-off refusal smoke OK; frontend
Documents 22, full vitest 50, shuffled (seed 1337) 22, ESLint 0 errors (6
pre-existing warnings), tsc clean, production build clean, `git diff --check`
clean; live PostgreSQL 16 manual smoke (flag on, LLM off): M2 transitional v1
byte-for-byte unchanged through finalization, `cft1:` target persisted,
eligible target accepted / transitional + future target rejected, repeat
finalize idempotent (409), a simulated changed-anchor target created a
DISTINCT successor while the worker refused that mismatched pinned target
closed (`unsupported_finalization_target`) and the pointer stayed on the ready
v2, citation prefix stable, report demo-only (no tenant text/citation ids/
version ids), flag-off restart disables tenant ops (403) while demo generation
still 200. Public `EvidentiaReport` schema unchanged; no M4 implemented;
nothing committed or pushed.

## 2026-07-18 — M3 final blocker corrections (focused independent review, 2 blockers)

A focused independent review of the still-uncommitted M3 diff returned two
final commit blockers. M3 has not shipped, so the manifest/migration were
corrected in place; the whole diff stays uncommitted for one last narrow
review of these two corrections.

**Blocker 1 · Eligibility now binds `engine_versions` to the ONE pinned
complete target (no hybrid supported-component artifact).** The prior
eligibility validated each component independently ("does this value exist in
*some* supported target"), which accepted a hybrid: the Markdown target pinned
(`cft1:85163b…`) with the supported TXT parser fields persisted — every
component individually supported, yet the reconstructed projection hashes to
the TXT target (`cft1:65f0f3…`). Reproduced exactly. Correction
(`services/generation_eligibility.py`, `_check_target_binding`): after the
coarse per-component diagnostics, the persisted projection is reconstructed
through the SAME typed `CompleteFinalizationTarget` machinery used at
enqueue/finalization (`finalization_target.target_from_engine_versions`,
`TargetProjectionError`), its digest MUST equal the pinned digest
(`target_digest_mismatch`), and it must deep-equal the registered target's
canonical projection field-for-field via `canonical_json` — type-sensitive, so
`2` ≠ `2.0` — with exact key-set checks (`target_projection_missing_field`,
`target_projection_extra_field`, `target_projection_mismatch`,
`target_projection_invalid`). **Thresholds and weights are target-bound**: they
are part of `engine_versions()`, so any altered value/key-set/numeric-type
fails the reconstructed-digest and canonical-equality checks.

**Blocker 1 · Anchor provenance is validated AND cryptographically bound.**
Section validation formerly checked only the anchor `algo` string. Now
`anchors.validate_anchor_provenance(provenance, algo=…, inheritance=…)` (the
frozen contract: `ANCHOR_DECISIONS` vocabulary, lineage decisions require
`inheritedFrom`, minted forbids it, `similarity` only on the similarity-bearing
decisions, no extra keys) is checked against the RESOLVED pinned target's
`anchor_algo`/`anchor_inheritance`. Provenance is now **hashed into the
manifest**: `section_manifest_entry` gained a REQUIRED `anchor_provenance`
field (`anchorProvenance`), written by the pipeline and reconstructed by
eligibility, so a post-manifest provenance tamper — even a structurally valid
one — fails `manifest_mismatch`. This changed the permanent manifest identity;
the golden corpus was regenerated (only `manifestSha256` changed and
`anchorProvenance` was added — anchor ids, decisions, classification and
version signatures and the target digest are byte-identical). `MANIFEST_VERSION`
stays `m3.1` (never shipped).

**Blocker 2 · SQLite downgrade preflights before any schema mutation.** The
prior downgrade narrowed `citation_prefix`, dropped `ingestion_jobs.operation`
and the three M3 `document_sections` columns, and only THEN checked the
NULL-source-blob refusal — so a safe refusal could leave a half-migrated schema
where DDL is not transactional (SQLite/Alembic batch recreation is a
DROP+RENAME). Restructured into three strict phases (revision `a9d2e4c7b1f3`
amended, not stacked): **PHASE 1 preflight** — `_preflight_citation_prefix_width`
and `_plan_successor_materialization` evaluate EVERY refusal condition with
pure SELECTs (source exists, same document+tenant, exactly one DB-backed source
blob with non-NULL data, materialization feasible) and raise before any DDL;
**PHASE 2 materialize** — insert each successor's own `document_blobs` row from
the deterministic (`uuid5`, idempotent) plan while `source_version_id` and all
lineage still exist, reusing the source's content bytes without duplicating the
storage identity; **PHASE 3 schema downgrade** — only now the DDL, in
dependency order, to exactly the committed M2 shape. An intentional refusal now
leaves the COMPLETE M3 schema and Alembic revision untouched regardless of
transactional-DDL rollback.

**Tests added:** `test_finalization.TestTargetBindingRegressions` (markdown↔txt
hybrid both directions; mixed components hashing to another *registered* target;
thresholds/weights value/key-set/type; missing/extra projection field; module
signatureVersion/digest, section-signature, manifest; missing/wrong-inheritance/
invalid-decision/missing-from/minted-with-from provenance; provenance changed
after manifest → `manifest_mismatch`; positive consistent-target eligible);
`test_manifest` provenance-binding + required-field; `test_m3_migration`
(new file: NULL-blob refusal leaves schema intact, overlong-prefix refusal
leaves schema intact, successful M2→M3→M2→M3 cycle materializing successor
blobs, white-box preflight-raises-before-mutation, deterministic plan) on both
SQLite and PostgreSQL 16.

**Verified 2026-07-18 (final corrections):** both blockers reproduced first;
backend SQLite **602 passed / 11 skipped** (+16: 9 target-binding + 2 manifest
+ 5 migration[sqlite]); focused M3 set (manifest/finalization/golden/classifier/
anchors/migration) **158 passed**; PostgreSQL 16 targeted M3+ingestion+migration
**187 passed**; PostgreSQL 16 concurrency **23 passed** (unchanged — the corrections touch no
concurrency path); the two data-bearing
SQLite AND PostgreSQL 16 migration refusals (NULL object-blob, prefix > 8) each
leave the complete M3 schema + Alembic revision unchanged with no partial
materialization row; successful M2→M3→M2→M3 cycle materializes successor blob
metadata and round-trips on both engines; `alembic check` shows only the 4
pre-existing legacy auth nullable drifts (zero new, none on any M3 table/
column); `git diff --check` clean. No API response/type changed, so frontend
was not re-run. Generation remains demo-only; no M4 functionality added; public
`EvidentiaReport` schema unchanged; nothing committed or pushed.

## 2026-07-18 — M3 final four narrow commit-blocking corrections (downgrade blob safety ×2, enforced downgrade() ordering, anchor-provenance decision semantics)

A last review pass on the uncommitted M3 diff returned four narrow blockers.
All previously verified designs (complete-target binding, manifest provenance
binding, thresholds/weights binding, signature contract, citation-prefix
capacity) were NOT reopened. Each blocker was reproduced before fixing.

**Blocker 1 · A source version with ZERO blob rows now refuses the downgrade.**
`_plan_successor_materialization` previously `continue`d past a successor whose
source had no `document_blobs` row — the downgrade then removed
`source_version_id` and left the successor permanently byte-unresolvable (data
loss). The rule is now: **every successor with a non-null `source_version_id`
must have EXACTLY ONE safely resolvable source blob before downgrade** (the M2
schema DB-enforces 1–1 via `uq_document_blobs_version`; zero and multiple both
refuse during preflight, before any insert or DDL). The source blob must belong
to the same document/tenant lineage and prove its metadata: non-empty
`storage_key`, DB-backed non-NULL `data`, `byte_size` equal to the actual byte
length, and SHA-256 agreement with the version-recorded `content_sha256`
(source's AND successor's — the finalize service copies the source digest).
Incomplete, ambiguous or hash-inconsistent source metadata refuses.

**Blocker 2 · Successors that ALREADY own a blob are preflighted, not skipped.**
The successor query previously excluded versions with an existing blob row,
making the conflict check unreachable — a successor bound to bytes B while its
source resolved to bytes A survived the downgrade silently keeping B. Now every
successor is planned: an existing blob is accepted ONLY as an **exact safe
equivalent of the source binding** (identical bytes, matching size, valid
tenant ownership, hash-consistent) and then counts as already materialized
(idempotent re-run, row untouched); divergent content, multiple rows or
unprovable metadata refuse — the conflicting blob is never overwritten and
never deleted. **The whole materialization plan is built globally before any
row is inserted**: a refusal for ANY successor means NO successor blob is
written (regression-tested with an early valid + later conflicting pair).

**Blocker 3 · downgrade() ordering is now enforced, not assumed.** The
migration is restructured into three explicit phases and `downgrade()` is
EXACTLY `plan = _preflight_downgrade(bind)` →
`_materialize_successor_blobs(bind, plan)` → `_apply_m2_schema_downgrade()`.
The ordering proof calls the REAL `downgrade()` (via
`MigrationContext`/`Operations.context`), not just its helpers: (a) a sentinel
`_preflight_downgrade` raises while the materialize/apply phases, every
`op.*` mutation entry point (`batch_alter_table`, `alter_column`,
`drop_column/constraint/index`, `create_*`, `execute`, `bulk_insert`) and every
statement on the live connection are intercepted — preflight must be called,
nothing else, zero mutating SQL, sentinel surfaced; (b) a success-path run
records phase order + all SQL and requires no mutating statement before
preflight completes and blob INSERTs strictly inside phase 2; (c) a refusal-path
run of the real `downgrade()` proves zero mutating statements; (d) a small AST
assertion pins downgrade()'s body to exactly the three phase calls
(supplement only — the runtime interception tests are the invariant). Black-box
SQLite/Alembic + PostgreSQL `command.downgrade` refusal tests remain.

**Blocker 4 · Anchor provenance is validated SEMANTICALLY, against the current
anchor.** `validate_anchor_provenance` previously checked field shape only —
it accepted `inherited-exact` with similarity 0.2, `inherited-similar` with
0.1 (below the frozen 0.8 Jaccard threshold), and `unchanged` naming an
unrelated `inheritedFrom` (it never saw the row's anchor). The validator now
takes the section's **current `anchor_id`** and enforces the decision matrix
`assign_anchors` actually produces, using the frozen constants
(`ANCHOR_DECISIONS`, `JACCARD_INHERIT_THRESHOLD`; no parallel vocabulary):

- `minted`: no `inheritedFrom`, no `similarity` — fresh identity has no lineage;
- `unchanged` / `heading-kept` / `reattached-exact`: `inheritedFrom` required
  and MUST equal the current `anchor_id` verbatim (the retained permanent
  anchor); unrelated predecessor ⇒ `anchor_lineage_mismatch`; any `similarity`
  ⇒ `anchor_similarity_unexpected`;
- `inherited-exact`: `inheritedFrom` == current anchor (the adopted disappeared
  anchor IS the current identity); `similarity` required and EXACTLY 1.0
  (`anchor_similarity_not_exact` otherwise);
- `inherited-similar`: `inheritedFrom` == current anchor; `similarity` required,
  finite, `0.8 ≤ s ≤ 1.0` (`anchor_similarity_below_threshold` /
  `anchor_similarity_invalid` for NaN/±Inf/outside `[0,1]`);
- `split-lineage`: current anchor must be EXACTLY `{inheritedFrom}.p1` with a
  part-free, parseable parent (the only split relationship §7.2 ever persists);
  parent==child, wrong part, unrelated parent, part-suffixed parent all ⇒
  `anchor_split_lineage_invalid`;
- unknown decisions, missing/forbidden fields and extra keys keep failing
  closed with the existing typed reasons.

Callers updated: eligibility (`_check_sections` passes `row.anchor_id`; the
manifest reconstruction binding is unchanged and still required IN ADDITION —
a semantically valid but different provenance still fails `manifest_mismatch`),
`test_anchors` (new `TestProvenanceValidation` matrix + producer/validator
agreement over real `assign_anchors` outputs), `test_finalization` (semantic
rejects through the real eligibility path), `test_golden_fixtures` (every
committed golden section's `anchorProvenance` must validate against its own
`anchorId` — all 17 fixtures pass UNCHANGED; no golden regeneration, no
manifest identity change, `cft1` digest untouched).

**Verified 2026-07-18 (round 3):** all four blockers reproduced first. Backend
SQLite `python -m pytest tests -q`: **672 passed, 11 skipped**. Focused:
anchors+golden+manifest **124 passed**; finalization/eligibility **54 passed**;
`test_m3_migration.py` SQLite **19 passed**. PostgreSQL 16 (container):
migration suite (both backends) **37 passed**; `test_concurrency.py`
**23 passed**. New migration coverage: zero-source-blob, multiple/ambiguous
source blobs (unique constraint dropped on the throwaway DB to seed the corrupt
state), size/storage-key/hash-corrupted source metadata, NULL source data,
divergent pre-existing successor blob (refuses; blob provably untouched), exact
equivalent successor blob (accepted idempotently, no duplicate row), multiple/
incomplete successor blobs, early-valid+later-conflicting global-planning
refusal — every refusal leaves the complete M3 schema, revision `a9d2e4c7b1f3`,
`citation_prefix` VARCHAR(12), `ingestion_jobs.operation`, the M3 section
columns and `source_version_id` intact with zero inserted rows; the round trip
(now two tenants/successors) preserves exact source bytes on both engines.
`alembic check` on fresh SQLite AND PostgreSQL 16 head databases: only the 4
pre-existing legacy auth nullable drifts (zero new). `git diff --check` clean.
No API/frontend/type change (frontend not re-run). cft1 target binding,
registry and signature contracts unchanged; generation remains demo-only; no
M4 code; nothing committed or pushed — the complete corrected M3 diff stays
uncommitted for one final review restricted to these four corrections.

## 2026-07-18 — M3 final single correction: ONE canonical duplicate-suffix anchor grammar

The last remaining blocker: `_parse_anchor`'s regex accepted ANY numeric
duplicate suffix (`-\d+`) and part (`\.p\d+`), so malformed parents like
`slug-0`, `slug-1` (the first occurrence is always the BARE slug — "-1" is
unrepresentable), `slug-01` (zero-padded) and `slug-2.p0` parsed, and the
split-lineage provenance check accepted `parent + ".p1"` built from them.
Eligibility had a second, divergent regex (`_FINAL_ANCHOR_RE`) with the same
laxness.

**Correction — one grammar, everywhere (`anchors.py`):**
`anchor = slug ["-" dup] [".p" part]` with slug = SLUG_CHARS..SLUG_FULL_CHARS
(12..31) lowercase ASCII base36; dup = integer >= 2, canonical decimal, no
leading zeros (`(?:[2-9]|[1-9][0-9]+)`); part = integer >= 1, canonical
decimal, no leading zeros (`[1-9][0-9]*`). STRICT ASCII digit classes only —
Python `\d` matches Unicode decimal digits (`"-2٢"`, `".p1٢"`) which int()
would silently convert — and the pattern is `\A…\Z`-anchored and applied via
`fullmatch()`, never a bare `$` (which can match before a trailing newline:
`"slug\n"` was accepted and silently normalized). The parser validates an
already-canonical STORED identifier — it never strips, folds or repairs one.
Compiled per current slug bounds (`_anchor_grammar_re()`, cached — read at
call time so the collision tests that shrink `SLUG_CHARS` stay valid; frozen
production bounds give a fixed pattern, exported as `ANCHOR_GRAMMAR_RE`).
`_parse_anchor` maps everything non-canonical to the never-matching sentinel
(the old parser read `-1` as bare and `-01` as dup 1); new public
`is_canonical_anchor()` replaces eligibility's private `_FINAL_ANCHOR_RE` —
no special case inside the provenance validator. A parametrized agreement
test pins `is_canonical_anchor(x) == (_parse_anchor(x) is not the sentinel)`
over the whole valid+malformed corpus, including trailing
newline/CR/space/tab and Arabic-Indic/fullwidth/Devanagari digit forms. The
split-lineage check now parses the parent through the canonical grammar
BEFORE the relationship comparison; self-lineage decisions inherit canonicality
transitively (inheritedFrom == current anchor, which the caller checks).
Generation (`_compose`/`_resolve_slugs`) already emitted only canonical forms
— unchanged, as is `ANCHOR_ALGO_VERSION` (unshipped correction).

**Tests:** `TestCanonicalAnchorGrammar` (valid: bare/`-2`/`-10`/`.p1`/`-2.p1`/
extended/31-char; invalid: `-0`/`-1`/`-01`/`-00`/`-002`/`-.p1`/`-0.p1`/
`-1.p1`/`-01.p1`/`-2.p0`/`-2.p01`/`.p0`/`.p01`/11-char/32-char/transitional/
uppercase; parser sentinel + canonical reads; producer/parser agreement over
real `assign_anchors` output incl. duplicates); split-lineage provenance
regressions for every malformed parent/child suffix; golden regressions: every
committed anchor id AND every lineage anchor parses canonically, all golden
provenance still validates, exact-equality fixture tests prove goldens
byte-for-byte unchanged; eligibility rejects a persisted `slug-1` anchor as
`non_final_anchor`.

**Verified 2026-07-18:** defects reproduced first (`-1`/`-01`/`-0` parsed;
split provenance with `-1`/`-01` parents accepted; then in the strictness
pass: `"slug\n"`/`"slug-2.p1\n"` accepted with the newline discarded, and
`"-2٢"` → dup 22 / `".p1٢"` → part 12 via Unicode `\d` + int()). Focused
anchors+golden+finalization after the ASCII/fullmatch correction:
**249 passed**. Full backend SQLite: **754 passed, 11 skipped**. `git diff --check` clean. Migration files, cft1
binding, eligibility target binding, manifest contract, citation-prefix logic,
frontend, API, report schema and generation untouched (PostgreSQL rerun not
required — no shared persistence/database code changed); goldens unchanged;
generation remains demo-only; no M4 code; nothing committed or pushed.

## 2026-07-18 — M4 tenant generation uses frozen report-local evidence bindings

**Decision.** Authenticated generation selects an explicit `tenant` corpus mode
and the anonymous Next.js showcase selects explicit `demo`; neither mode is
inferred from query results and neither may fall back to the other. The new
`EVIDENTIA_TENANT_GENERATION_ENABLED` rollout flag defaults false and is
independent of ingestion. When enabled, the authenticated FastAPI route creates
a `TenantCorpusProvider` from membership-derived company context. Empty,
ineligible, retrieval-invalid and evidence-invalid requests return stable typed
errors and never substitute sample evidence.

`TenantCorpusProvider` reuses `check_generation_eligibility` exactly. It resolves
the active company's non-deleted documents to exact eligible current version
ids, loads exact sections, applies deterministic `tenant-lexical-v1` scoring and
stable identity tie-breaks, enforces configured document/candidate/selection/
character/per-document/excerpt limits, rejects ambiguous citation ids, and
freezes the result before any LLM call. The versioned `tcs1` digest covers company
scope, sorted version ids, manifest hashes, retrieval version and configuration.
The shared orchestrator receives the provider explicitly; demo imports remain
reachable only through `DemoCorpusProvider`. Cache identity includes corpus,
company and snapshot digest.

Tenant text is quoted evidence, not instructions. LLM prompts keep it out of the
system instructions and inside labelled `<untrusted-evidence>` blocks; bounded
derived excerpts neutralize citation-shaped requests only when M3 classified the
section as injection-like. Stored text is unchanged. The final validator uses one
report-local citation registry and rejects unknown/ambiguous ids or citation
display data not copied from the frozen binding. LLM failure may fall back only
to the deterministic baseline over the same frozen tenant evidence; execution
metadata records what actually ran.

**Public-schema boundary.** The 20-key `EvidentiaReport` compatibility JSON is
unchanged. Source provenance is operational/audit metadata, so it lives on the
report row plus normalized `report_source_versions` and
`report_evidence_bindings`, exposed separately at tenant-scoped
`GET /api/reports/{id}/sources`. This avoids deepening the future CAD projection
while preserving exact version/section/anchor/citation/signature identity.
Migration `e4b7c9d2a610` adds tenant-safe composite keys/FKs, report generation
metadata, source ordering and report-local citation/rank uniqueness. Existing
reports backfill as completed demo reports with no fake bindings.

**Retention.** Document deletion is now a soft delete. Providers exclude deleted
documents, while immutable versions/sections and bounded report binding snapshots
remain available to completed reports. This is the smallest safe behavior for M4;
unbounded full source text is not copied into report bindings. An intentional M4
downgrade drops M4-only audit tables/columns to return to the exact M3 schema but
preserves base reports/documents/versions/sections; re-upgrade does not fabricate
lost bindings.

**Frontend.** The authenticated BFF still proxies only FastAPI and forwards typed
M4 errors; it never calls the demo route. Running/Documents/report views label
tenant versus sample evidence honestly. Report citations render exact version and
section binding data, and a compact audit panel shows counts, retrieval/execution
mode and snapshot identity. Old demo reports remain readable.

**Deferred.** Embeddings/vector search, PDF/DOCX/OCR, full claims/CAD lifecycle,
advanced document selection, physical blob retention optimization and report
regeneration/version comparison remain outside M4.

## 2026-07-18 — M4 post-review hardening keeps the tenant-lexical-v1 contract bounded

**Decision.** `tenant-lexical-v1` scores every section in each exact frozen
version before the final global candidate cap. Database rows stream in canonical
ordinal/anchor order; fixed-size batches retain a bounded deterministic
per-document top-k, and the global candidate set is taken in deterministic
per-document rank rounds before the existing score/identity sort and configured
selection, character and per-document caps. Memory is bounded by configured
documents × candidates, deep sections remain eligible, duplicate citation
detection stays database-side, and `tcs1` continues to bind every
output-affecting retrieval setting.

The shared prompt wrapper HTML-encodes `<` and `>` in every case-insensitive
occurrence of `</untrusted-evidence>` inside the prompt payload. This is a
deterministic, reversible prompt representation only; immutable stored source
text is unchanged. Citation-request neutralization remains defence-in-depth for
classified injection or delimiter-closing attempts, not the wrapper boundary.

Structured evidence fields and citation display values remain exact frozen
allow-list checks. Narrative scanning no longer treats every uppercase
hyphenated token as a citation. It recognizes only the active tenant prefix
families plus the reserved opposite-mode `DEMO-*` family, rejecting unknown IDs
in those namespaces while leaving ordinary standards and versions untouched.
Pipeline/orchestration exceptions now return and persist `generation_failed`;
snapshot/completion write exceptions return `persistence_failed`, with no
exception or tenant content in responses.

**Deferred M4.1 performance work.** Optimize `GET /api/documents` eligibility
calculation and consider immutable-key memoization or batched eligibility
evaluation. F7 remains unchanged because no response-derived state correction
was needed; F8 downgrade behavior remains unchanged. No cache or eligibility
redesign is part of this hardening pass.

## 2026-07-18 — M5a claim acceptance is declarative, deterministic and audit-only outside the report projection

**Decision.** The M4 frozen tenant snapshot and report-local evidence registry are
the sole evidence boundary for M5a. Versioned JSON claim patterns owned by the
domain module emit proposals; `typed-matchers-v1` records bounded deterministic
observations; `deterministic-support-gate-v1` alone returns accepted, rejected or
insufficient evidence. LLM output can name an allowed spec, wording and frozen
citations, but those citations are hints only: every LLM proposal is re-matched
against the complete frozen evidence set, including conflicts, and re-gated.
Accepted bindings are the intersection of proposed hints and successful support-
matcher attribution; unrelated citations cannot affect score or provenance.
Unknown evidence fails closed. One projection from accepted decisions exclusively
owns workflows, risks, recommendations, summary and top finding; all other
decisions remain in a separate report-local audit graph so the 20-key
`EvidentiaReport` stays unchanged. Full-mode analytical mutation is atomic and
restores the complete deterministic baseline on any exception.

Claim patterns are released independently under
`modules/compliance/claim-patterns/<version>` and are immutable under
`(claim-pack id, claim spec, pattern version)`. The released M3
`modules/compliance/1.0.0` directory and its 17 goldens are unchanged. Threshold,
matcher and gate versions are report provenance. Nested `evidence_count` and the
unwired `comparison` primitive are rejected by the v1 schema; matcher execution
has explicit depth, node, evidence and primitive-evaluation budgets. Tenant-
scoped metrics are atomic, non-authoritative counters and feedback has explicit
replacement semantics; neither may tune behavior automatically. Migration
`f5a6c7d8e9b0` adds composite tenant-safe claim/evidence/feedback constraints,
including report-local corrected-citation binding integrity, and
downgrades to exact M4 without fabricating old-report decisions. The rollout flag
defaults off; claim-enabled failure never falls back to an unvalidated path.

**Deferred.** The repository has a pre-existing M3 golden harness drift in which
fresh computation changes only `manifestSha256`; M5a neither changes the committed
goldens nor claims to fix that separate infrastructure issue. Production-scale
M5b pattern authorship/calibration, automatic or
cross-tenant learning, embeddings/FTS, external packs and the full CAD runtime.

## 2026-07-20 — M5a + DOCX Renderer R1 integration (grounding, renderer boundary, LF pin, export BFF)

M5a (deterministic claim engine, merge `d7cc4b6`, feature `17406c6`) and DOCX
Renderer R1 (merge `ae4f1b7`, feature `112d947`) are integrated into `main`,
followed by the canonical line-ending pin (`1e19b29`) and the Next
`middleware.ts` → `proxy.ts` migration (`a76506b`, HEAD). `origin/main` is still
on M4 until the final push. The decisions settled during integration:

**M5a grounding authority.** Candidate claims are never accepted because an LLM
selected citations. The complete frozen M4 evidence set is visible to support and
conflict evaluation; LLM citation codes are hints only. Accepted evidence is
matcher-attributed, and only accepted claims may influence analytical report
output (workflow, risks, recommendations, summary, top finding). Pattern packs are
versioned separately (`compliance.claim-patterns@1.0.0`) from the immutable M3
classification-module releases (`compliance@1.0.0`, unchanged).

**Renderer boundary.** Renderers consume the persisted report and report-local
source-audit snapshots only; they do not retrieve, reason, call an LLM or follow
current-document pointers. DOCX (`docx-renderer-v1`) is the first implementation of
the format-independent renderer protocol. A missing tenant binding must never be
represented as frozen evidence. CAD remains deferred until a renderer needs
structure beyond the existing `EvidentiaReport` projection; R1 did not widen the
20-key schema.

**Deterministic fixture line endings.** Immutable modules and golden fixtures are
pinned to LF via the root `.gitattributes` (`1e19b29`). Byte-level identity tests
use the canonical repository representation; the previously reported
fresh-vs-committed `manifestSha256` discrepancy was a working-tree line-ending
artifact. Golden outputs were not re-recorded to conceal an M5a regression.

**Export BFF safety.** Rotated sessions must be persisted on every post-refresh
response path (success and error). Export responses are bounded using both the
declared Content-Length and the actual streamed bytes, and an oversized chunked
body is cancelled.

## 2026-07-20 — Frontend runtime is tenant-only

**Decision.** The Next.js product runtime has one evidence path: authenticated
tenant documents and persisted tenant reports through the FastAPI backend. The
anonymous TypeScript generation route, bundled document corpus, local agents,
seeded report/activity data, local report store and legacy JSON/session upload
path are removed. Backend-unavailable or feature-disabled states are explicit and
never substitute local evidence.

Workspace selection stores only real tenant document ids whose current versions
are ready, finalized and generation-eligible. Versioned workspace and pending-run
keys invalidate hybrid-era bundled ids; session migration also removes old public
demo keys. `/running` uses indeterminate progress because the backend exposes no
stage stream, and navigates only after a persisted report id is returned. Report,
playbook and sidebar libraries load persisted reports or show honest empty states.

**Boundary.** This is a frontend runtime and UX decision. Backend migrations,
models, immutable M3/M4/M5a module data, claim behavior, DOCX rendering and golden
fixtures are unchanged.
