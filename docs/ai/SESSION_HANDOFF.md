# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-18 (M3 + four narrow corrections + final canonical
anchor-grammar correction; diff uncommitted for last review)._

## Where things stand

**M3 (stable anchors + internal citation identities + deterministic
classification + M2→M3 finalization) is implemented; the seven-blocker review,
the two-blocker focused review AND the final four narrow commit-blocking
corrections are all CORRECTED and verified. The complete working-tree diff is
deliberately UNCOMMITTED for one final review restricted to the four points
below.** Nothing committed or pushed. No M4 functionality; generation remains
demo-corpus-only; Settings untouched.

Final four corrections (full text: `DECISIONS.md` 2026-07-18 round 3):
- **Downgrade blob safety (a)**: a successor whose source version has ZERO
  `document_blobs` rows now REFUSES the downgrade during preflight (was:
  silently skipped → successor byte-unresolvable after lineage removal). Every
  successor needs exactly one safely resolvable source blob — same lineage,
  DB-backed data, size + `content_sha256` consistent; ambiguous/incomplete
  refuse.
- **Downgrade blob safety (b)**: successors that ALREADY own a blob are
  preflighted, not excluded — accepted only as an exact safe equivalent of the
  source binding (identical bytes/size/ownership; then idempotent), otherwise
  refuse without overwriting/deleting. The whole plan is built globally before
  any insert (early-valid + later-conflicting ⇒ zero rows written).
- **Enforced downgrade() ordering**: `downgrade()` is exactly
  `_preflight_downgrade` → `_materialize_successor_blobs` →
  `_apply_m2_schema_downgrade`. Proven by calling the REAL `downgrade()` under
  `Operations.context` with a sentinel-raising preflight + interception of both
  phases, all `op.*` mutation entry points and all SQL (zero mutating
  statements), plus success-path phase/SQL ordering and an AST supplement.
- **Anchor-provenance decision semantics**: `validate_anchor_provenance` now
  receives the row's CURRENT `anchor_id` and enforces the frozen matrix —
  minted: no lineage/similarity; unchanged/heading-kept/reattached-exact:
  `inheritedFrom` == current anchor (else `anchor_lineage_mismatch`);
  inherited-exact: similarity EXACTLY 1.0; inherited-similar: finite
  0.8 ≤ s ≤ 1.0 (frozen Jaccard threshold); split-lineage: anchor ==
  `{parent}.p1`, part-free parent. Eligibility passes `row.anchor_id`;
  manifest reconstruction is still required IN ADDITION (semantically valid
  tampers fail `manifest_mismatch`). Goldens validate UNCHANGED (no manifest
  identity change; `cft1` untouched).
- **Canonical anchor grammar (final correction, incl. strictness pass)**: ONE
  parser (`anchors.ANCHOR_GRAMMAR_RE` / `is_canonical_anchor` /
  `_parse_anchor`) defines permanent-anchor structure everywhere — slug 12..31
  lowercase ASCII base36, dup suffix >= 2 canonical decimal (no
  `-0`/`-1`/leading zeros; first occurrence is the bare slug), part >= 1
  canonical decimal. STRICT ASCII `[0-9]` classes (Python `\d` admitted
  Unicode digits: `-2٢`→22, `.p1٢`→12) and `\A…\Z` + `fullmatch()` (bare `$`
  admitted a trailing newline); the parser never strips/folds/repairs a
  stored identifier. Malformed forms map to the never-matching sentinel;
  split-lineage parses the parent BEFORE the relationship check;
  eligibility's private `_FINAL_ANCHOR_RE` replaced by the shared predicate;
  parametrized predicate/parser agreement test over the full corpus.
  Generation already emitted only canonical forms — untouched;
  `ANCHOR_ALGO_VERSION` unchanged; goldens byte-for-byte stable.
  Verified: focused 249 passed; full SQLite **754 passed, 11 skipped**.

Earlier corrected surfaces remain as documented: 12-char `heading-path-v1`
slugs (full-digest identity), `content-match-v1` inheritance,
`CompleteFinalizationTarget` `cft1:<sha256>` pinned + registry-bound
eligibility (`_check_target_binding` digest + type-sensitive deep equality),
provenance hashed into manifest `m3.1`, citation prefix 8→12 with quota-wide
candidates. Lifecycle: uploads still produce `pre-m3-transitional` versions;
finalize re-ingests the retained blob into an immutable successor; the flip
site never moves `current_version_id` backwards; source→successor integrity is
DB-enforced (composite self-FK). M4 eligibility ships unconsumed, fails closed.

## Verification (all green, 2026-07-18 round 3)

- All four blockers reproduced first (zero-blob `continue`; NOT-EXISTS successor
  exclusion; helper-only ordering test; validator accepting sim 0.2/0.1 and
  unrelated `inheritedFrom`).
- Backend SQLite `python -m pytest tests -q`: **672 passed, 11 skipped**.
  Focused: anchors+golden+manifest **124**, finalization **54**,
  `test_m3_migration.py` **19** (SQLite).
- PostgreSQL 16 (`postgresql+psycopg://…@127.0.0.1:54329/…`, container
  `evidentia-pg-test`): migration suite both backends **37 passed**;
  `test_concurrency.py` **23 passed**.
- Migration refusal matrix (SQLite + PG): zero-source-blob, multiple/ambiguous
  blobs (constraint dropped to seed corruption), corrupt size/storage-key/hash
  metadata, NULL data, divergent pre-existing successor blob (kept untouched),
  multiple/incomplete successor blobs, early-valid+later-conflicting global
  planning — each leaves the complete M3 schema, revision, VARCHAR(12) prefix,
  `operation`, M3 section columns and `source_version_id` intact, zero inserts;
  equivalent pre-existing blob accepted idempotently; two-tenant round trip
  preserves exact source bytes.
- `alembic check` on fresh SQLite AND PostgreSQL 16 head DBs: only the 4
  pre-existing legacy auth nullable drifts (zero new). `git diff --check` clean.
- Frontend NOT re-run: no API response or type changed (previous run valid —
  Documents 22/22, vitest 50/50, tsc/build clean). Goldens NOT regenerated
  (all 17 fixtures' provenance validates semantically as-is).
- Prior rounds' live PostgreSQL smoke + CLI checks remain valid (no runtime
  surface of those flows changed in round 3).

## Deferred debt (unchanged, do NOT fix before its milestone)

- **Worker complete/fail lease fencing** (M6/M7): M3 finalization stays far
  below the 300s stale threshold; stage heartbeats + `OwnershipLost` abort are
  the only hardenings. Full lease/epoch fencing before PDF/DOCX/OCR.
- Flag-off legacy upload detail drawer (if trivial);
  `documents.content_text` removal milestone; 4 legacy auth nullable drifts.
- Blob retention must account for successors referencing the source version's
  blob (`_load_source_bytes` fallback) when a keep-last-N policy arrives (M8+).

## Next steps

1. Final independent review of the uncommitted M3 diff, RESTRICTED to the four
   round-3 corrections; then commit + push (only when explicitly requested).
2. M4: TenantCorpusProvider consuming `generation_eligibility` (pass a Session;
   transitional stays rejected even when current), orchestrator injection,
   `reports.source_versions`/`engine_versions`, full-text scoring,
   version-aware bounded cache, `report.company` behind the flag.
3. Golden outputs change ONLY via the reviewed
   `scripts/regenerate_golden_fixtures.py` — any diff there is a permanent
   identity change and must be explained.
