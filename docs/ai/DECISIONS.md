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

### 2026-07 · AI memory/handoff docs
Added `AGENTS.md`, `.cursor/rules/evidentia-context.mdc`, and `docs/ai/*` so future
conversations can continue without chat history. Docs are the handoff source of
truth; agents read PROJECT_STATE + SESSION_HANDOFF before work and update them after.
