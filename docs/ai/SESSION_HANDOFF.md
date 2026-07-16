# Evidentia — Session Handoff

_Keep under 100 lines. Rewrite for the current state after meaningful work._
_Last updated: 2026-07-16 (M2 + independent-review fixes; diff uncommitted)._

## Where things stand

**M2 (MD/TXT upload + ingestion spine) is implemented, independently reviewed
("approve with fixes", no commit blockers), and both review fixes are applied
and verified.** The complete working-tree diff remains deliberately
**uncommitted** for one final focused verification. Nothing was committed or
pushed. No M3 functionality was implemented.

Flow (behind `EVIDENTIA_TENANT_CORPUS_ENABLED`, default off = pre-M2 behavior
byte-for-byte): authenticated upload → tenant-scoped document + immutable
version + blob → durable job → tenant-fair worker claim → MD/TXT parser →
DocIR v1 → deterministic sectionizer → atomic persist + single-site
`current_version_id` flip → Documents UI. Report generation still reads ONLY
the demo corpus (M4 does the provider switch) — test- and smoke-verified.

## Review fixes applied this session (full text: DECISIONS.md 2026-07-16)

1. **Binding M2→M3 lifecycle contract pinned** (docs only; M3 entry criterion
   + M4 provider invariant): `anchor_algo_version="pre-m3-transitional"`
   versions are immutable — M3 never mutates the ready version row, its
   sections, transitional anchor/citation ids, or `manifest_sha256`; M3
   finalizes by re-ingesting the retained source blob into a NEW version row
   (final anchors/citations/classification/manifest, ready, controlled flip);
   the old version stays byte-for-byte unchanged. M4's TenantCorpusProvider
   must reject any `pre-m3-transitional` version even if `current_version_id`
   points to it — `status == "ready"` alone is never generation eligibility.
2. **Flag-on JSON create quota bypass closed**: `POST /api/documents` with
   the flag on now pays the same abuse bounds as multipart via shared helpers
   (`document_upload.create_json_document`): `enforce_upload` rate budgets
   first, company row lock, count + stored-byte quotas on the actual UTF-8
   bytes, then document/version/blob/job in ONE transaction. Same typed codes
   (`rate_limited`, `document_quota_exceeded`, `storage_quota_exceeded`);
   a rejection leaves zero rows. Flag-off JSON path byte-for-byte unchanged
   (still test-pinned; no new semantics in disabled mode).

## Deferred debt recorded (do NOT fix before its milestone)

- **Worker ownership fencing** (required before long-running formats
  PDF/DOCX/OCR, M6/M7; not needed at MD/TXT bounds): heartbeats during
  processing, lease/epoch-fenced complete/fail, stale-holder regression test.
- **Flag-off legacy upload detail drawer** (low-priority UX compat; only if
  trivial + isolated — no Documents-page redesign).

## New/changed surface this session

- `backend/app/services/document_upload.py`: +`create_json_document`.
- `backend/app/api/documents.py`: `create_document` split flag-off (pre-M2
  verbatim) vs flag-on (rate limit + shared quota service, typed rejections).
- `backend/tests/test_upload_api.py`: +7 (`TestJsonCreateLimits`: count/byte
  quota + no-rows, UTF-8 byte accounting, shared user/tenant rate budgets,
  success rows+shape, flag-off legacy pinned).
- `backend/tests/test_concurrency.py`: +2 PostgreSQL-only JSON-create quota
  boundary races (count slot / byte slot; one winner, typed loser, within
  quota).
- `docs/ai/DECISIONS.md`, `docs/ai/PROJECT_STATE.md`: lifecycle contract +
  review remediation + updated verified counts.

## Verification (all green, 2026-07-16, after the fixes)

- Backend SQLite: `python -m pytest -q` → **444 passed, 6 skipped**.
- PostgreSQL 16 (Docker, `postgresql+psycopg://…@127.0.0.1:54329/…`):
  upload+ingestion+seams **100 passed**; `test_concurrency.py` **18 passed**
  (incl. both new quota races).
- `alembic check`: only the 4 pre-existing legacy auth nullable drifts, zero
  on ingestion tables; head unchanged `f7c3a1b9e2d4` (no new migration).
- Frontend: `npm test` 45/45; lint 0 errors (6 pre-existing warnings);
  `tsc --noEmit` clean; `npm run build` clean; `git diff --check` clean.
- Live smoke (two uvicorn boots, SQLite scratch DB, flag on): 10-byte quota →
  JSON create **403 `storage_quota_exceeded`, zero rows**; default quota →
  201 → worker → ready, exactly **1 document/version/blob/job**; generation
  200 with 8 citations, all demo-corpus, no tenant text leaked.

## Next steps

1. Final focused verification of this uncommitted diff; then commit + push
   (only when explicitly requested).
2. M3: anchor algorithm (versioned, golden fixtures), citation prefixes,
   deterministic classification as module data, injection flags; honor the
   pinned lifecycle contract (new version row via re-ingestion; never mutate
   `pre-m3-transitional` versions).
3. Debt watch: worker ownership fencing (before M6/M7 formats); legacy
   flag-off upload drawer (only if trivial); `documents.content_text`
   removal milestone; legacy nullable drift on 4 auth timestamp columns.
