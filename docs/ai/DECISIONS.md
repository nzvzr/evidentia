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
