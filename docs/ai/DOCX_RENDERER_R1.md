# Renderer Track R1 — Editable DOCX renderer

_Status: implemented and verified, with a post-review correction pass applied
(frozen binding-excerpt provenance, BFF export route tests, export config in
`.env.example`). Uncommitted for independent review. This is **R1 only** — the
first renderer on the track, not the whole renderer track. PDF, PPTX, XLSX,
HTML/Markdown and JSON/API renderers remain deferred._

## 1. What this is

The first independent **output renderer** (L9, `PLATFORM_ARCHITECTURE.md` §2.2 /
§2.3): a pure, deterministic transformation of a **persisted** analysis snapshot
into an editable Microsoft Word (`.docx`) deliverable.

```
persisted completed EvidentiaReport JSON
        + persisted report-local M4 source audit          render(snapshot, options)
        + authenticated tenant display info      ───────▶ editable .docx bytes
```

It is DOCX **output** only. There is no DOCX parser, no PDF/PPTX/XLSX renderer,
no background export queue, and no persisted artifact store — R1 renders on
demand, in memory.

## 2. The rendering boundary (invariant)

The renderer is a pure function of its persisted inputs. It **must not**, and
does not:

- perform retrieval, evidence scoring, or any domain reasoning;
- call an LLM or open any network socket;
- create, modify, or re-bind claims/evidence/citations;
- re-run generation;
- read live/current document versions or the global citation registry;
- follow `documents.current_version_id` (a live-smoke check mutates that pointer
  to `NULL` after generation and confirms the export is byte-identical).

The only inputs are the persisted report JSON, the persisted source audit, the
membership-derived tenant display name, and deterministic renderer options.
`EvidentiaReport`'s public 20-key schema is **unchanged**; no renderer field was
added to it (renderer concerns stay in the renderer — §2 of the architecture).

## 3. Input snapshot

`app/renderers/snapshot.py` assembles a defensively-typed, immutable
`ReportSnapshot` from persisted data — the renderer never walks the raw loosely
typed dict:

- `ReportView` — typed projection of the completed `EvidentiaReport` JSON
  (summary, top finding, persona brief, workflow steps, risks, citations,
  metrics, suggested actions, agent steps, generation mode/provider/model).
- `SourceAuditView` — typed projection of `GET /api/reports/{id}/sources`
  (corpus mode, snapshot digest, retrieval/orchestrator versions, execution
  mode, frozen `sourceVersions`, and per-citation `evidenceBindings` with exact
  version id, section ordinal, heading path, and bounded excerpt). `present` is
  `False` when no audit exists, so the document says so honestly.
- `TenantDisplay` — the authenticated company display name (the report's own
  `company` field is a pipeline constant, so the cover uses the real tenant name
  from `CompanyContext`).

Absent fields become empty/`None` and are surfaced honestly — never fabricated.
Every list is bounded (`MAX_WORKFLOW_STEPS`, `MAX_CITATIONS`, …) so a pathological
row cannot request an unbounded document.

## 4. Output contract

`app/renderers/protocol.py` is the **format-independent** renderer contract that
PDF/PPTX/… will implement later:

```
Renderer.render(snapshot: ReportSnapshot, options: RendererOptions) -> RenderedArtifact
```

`RenderedArtifact` carries: `data` (bytes), `filename`, `content_type`,
`renderer_id`, `renderer_version`, `content_hash` (sha256 of the bytes),
`semantic_digest`, `byte_size`, and `telemetry`. `RendererOptions` are the only
non-snapshot inputs (page size, TOC/appendix/excerpt toggles, size cap) and carry
no content and no wall-clock.

## 5. DOCX structure (`app/renderers/docx_renderer.py`)

`DocxRenderer` (`renderer_id="docx-renderer"`, `renderer_version="docx-renderer-v1"`)
produces, in order:

1. **Cover page** — Evidentia brand (text), report title, tenant + market,
   generated date (from persisted data), corpus mode, generation mode,
   confidence, renderer version, report id.
2. **Table of contents** — a real Word `TOC` field (Word offers to update it;
   an honest, editable placeholder line stands in until then). Optional.
3. **Executive summary** — summary, top finding, headline metrics.
4. **Analysis overview** — persona brief, priorities/goals, scope & methodology,
   deterministic/LLM disclosure.
5. **Recommended workflow** — ordered steps with why-it-matters, expected output,
   and the bound evidence line.
6. **Risk register** — a real Word table (severity, risk, impact, mitigation,
   owner, evidence), severity-shaded, with a repeating header row.
7. **Recommendations & next actions** — table.
8. **Evidence & citations** — for each citation the **citation id, document
   title, version, section/heading path and the evidence quote all come from the
   same frozen M4 binding** (never from `report_json`, and binding metadata is
   never combined with a `report_json` excerpt). A citation with no exact binding
   is labelled *source audit unavailable* and its quote omitted (tenant corpus),
   or its report-record excerpt is preserved but clearly labelled as such (only
   when the corpus mode is **explicitly** `demo`) — never implied to be frozen
   source-audit evidence. A tabular source appendix lists every frozen version and
   selected section.
9. **Audit appendix** — corpus mode, snapshot digest, retrieval/orchestrator
   versions, execution mode, LLM provider/model, counts, renderer id/version,
   and the frozen source-version list.

Headers/footers repeat on every page; the footer carries `Page X of Y` via real
`PAGE`/`NUMPAGES` fields. Absent data omits the section or labels it honestly —
nothing is invented.

## 6. Styling system (`app/renderers/docx_styles.py`)

Formatting flows from **named styles**, not ad-hoc run formatting, so the
document is editable the way a hand-authored one is. Tuned built-ins (`Title`,
`Subtitle`, `Heading 1–3`, `Normal`) plus custom paragraph styles: `Evidentia
Body`, `Evidence Quote`, `Citation`, `Risk High/Medium/Low`, `Metadata`, `Table
Header`, `Table Cell`, `Cover Label`. Real heading hierarchy, real Word tables
(`Table Grid`) with shaded/repeating headers. No font files are packaged; text is
real text, never a screenshot; no images, no macros.

## 7. Determinism (Phase 6)

Visible content and structure are a pure function of the snapshot and options.
Two sources of container non-determinism are removed:

- **Core-property dates** are pinned to the report's persisted `generatedAt`
  (or a fixed `2001-01-01` epoch when absent) — never `datetime.now()`.
- **ZIP container** is re-packed (`_normalize_container`) with pinned entry
  timestamps (`1980-01-01`), OS-independent attributes, and python-docx's
  deterministic entry order preserved.

Within one python/zlib build this yields **byte-identical** output for identical
inputs (asserted in tests and the live smoke). A container-independent
`semantic_digest` over the canonical input plus the normalized `document.xml` /
`styles.xml` is also emitted, so logical identity is provable even if a future
library/zlib build perturbed the container bytes. `content_hash` is the sha256 of
the delivered bytes and is echoed in the `X-Evidentia-Content-Hash` header.

## 8. Security / sanitization (`app/renderers/sanitize.py`, Phase 5)

Every report field and excerpt is treated as untrusted text:

- **Invalid XML characters** (control chars, lone surrogates, `#xFFFE/#xFFFF`)
  are stripped so the file always opens; python-docx handles entity escaping, so
  hostile markup like `<script>` is escaped, never injected.
- **Per-field length caps** and **bounded list projections** prevent an
  unbounded/zip-bomb-style document; a hard **output-size cap** (`RendererError
  export_too_large` → 413) is the final valve.
- **Filenames** are built from slugified persona/market/id
  (`evidentia-<persona>-<market>-<shortid>.docx`) — no separators, dots, or `..`
  can survive, so a hostile title cannot alter the path.
- No external relationships (no external image/hyperlink targets), no macros, no
  uncontrolled document properties, no tenant text in logs or error surfaces.

## 9. API endpoint (`app/api/exports.py`, Phase 7)

```
GET /api/reports/{report_id}/export/docx        (?page=A4|Letter)
```

- **Authenticated & tenant-scoped** through `CompanyContext`; the report id alone
  is never sufficient. `reports_repo.get_report` requires the membership-derived
  `company_id` and matches **completed** rows only, so another tenant's id — or a
  running/failed report — resolves to an enumeration-safe **404**.
- Loads the exact persisted report JSON + report-local source audit, renders
  **in memory**, and streams bytes with:
  `Content-Type: …wordprocessingml.document`, a safe `Content-Disposition`
  filename, `Cache-Control: no-store`, and `X-Evidentia-Renderer[-Version]`,
  `X-Evidentia-Content-Hash`, `X-Evidentia-Semantic-Digest`.
- **Rate limited** per IP/user/tenant (`enforce_export`); enforced after auth.
- Output-size cap from `EVIDENTIA_EXPORT_MAX_BYTES`. No temp files, no local
  paths exposed, no browser-supplied company authority.

## 10. BFF + UI (Phase 8)

- `app/api/reports/[id]/export/docx/route.ts` — an authenticated Next BFF route
  that uses the httpOnly session, transparently refreshes the access token
  (persisting the rotation), streams the DOCX bytes back with content type and
  filename intact, exposes no backend token, and **never falls back to demo** (a
  failure returns the backend's status honestly — 401/404/413/429 preserved, other
  upstream errors collapsed to a typed 502, network failure to 503). It also
  mirrors the backend's `EVIDENTIA_EXPORT_MAX_BYTES` ceiling (12 MiB) as defense in
  depth, refusing an over-large declared body with a typed 413 before buffering.
- `components/DownloadDocxButton.tsx` — a `Download DOCX` control shown only on
  completed report pages (the report page renders only completed backend
  reports). It has loading/error states, prevents duplicate in-flight requests,
  saves the blob with the server-chosen filename, keeps no localStorage copy, and
  surfaces failures honestly with a retry.

## 11. Tenant isolation

Identical to the rest of the report API: cross-tenant export is 404 (not 403),
a forged `X-Company-Id` grants nothing, ownership derives from the session, and
the rendered document contains only the caller tenant's own frozen evidence —
verified in unit, API, and live-PostgreSQL tests (another tenant's unique corpus
marker never appears in an export, and never leaks in the 404 body).

## 12. Tests

- `backend/tests/test_docx_renderer.py` — 31 renderer/safety unit tests (valid
  ZIP + required parts, XML parses, sections present/omitted honestly, real
  tables, citations resolve from source audit, invalid-XML/hostile-markup
  handling, filename traversal, output-size cap, byte + semantic determinism,
  pinned core dates, legacy demo report, missing audit). Includes the frozen
  binding-excerpt corrections: a bound citation shows only the binding excerpt
  (never the `report_json` excerpt or stale source/section labels); a tenant
  citation with no binding is labelled *source audit unavailable* with its quote
  omitted; an explicit-demo citation keeps its report-record excerpt but never as
  frozen evidence; and a live "current version" pointer cannot alter the excerpt.
- `backend/tests/test_export_api.py` — 12 API/security tests (valid DOCX, renderer
  headers + content-hash match, byte determinism, Letter option, tenant citation
  present, cross-tenant 404, forged company id, no cross-tenant marker,
  unauthenticated 401, unknown/failed report 404, rate limiting).
- `app/api/reports/[id]/export/docx/route.test.ts` — 12 BFF route tests against the
  real session module (only `next/headers` and `fetch` faked): authenticated
  proxy with Bearer from the httpOnly session, MIME + Content-Disposition + binary
  bytes preserved (with a safe default disposition fallback), token-refresh
  rotation persisted as httpOnly cookies, no backend token leaked to the browser,
  no `/api/demo/generate-workflow` call, 401/404/413/429/500 surfaced honestly,
  backend-unavailable typed 503 (unset URL and network throw), and the bounded
  over-large-body 413 guard.
- `components/DownloadDocxButton.test.tsx` — 4 UI tests (control shown, correct
  BFF endpoint + blob save with server filename, duplicate-click prevention,
  honest error + retry with no fallback).

## 13. Limitations / deferred renderers

- **R1 is DOCX output only.** No DOCX parser, no PDF/PPTX/XLSX/HTML/JSON renderer,
  no push renderers (Jira/ServiceNow/…), no background export queue, no persisted
  artifact store, no anonymous/public export, no user-uploaded templates.
- The `TOC` field renders a placeholder until Word updates it (F9) — standard
  Word behavior, not a limitation of the content.
- Byte-level determinism holds within a fixed python/zlib build; across builds the
  container bytes could differ while the `semantic_digest` and visible content
  stay identical.

## 14. Later renderer path

The next renderers implement the **same** `render(snapshot, options) -> artifact`
contract behind `app/renderers/protocol.py`, each independent (architecture
R-track order): **PDF** (the print page is already a projection consumer), then
**canonical JSON/API**, then **HTML/interactive**, with **PPTX/Excel** and push
integrations following. When a renderer needs structure beyond the current report
projection, that is the trigger to introduce the CAD (`PLATFORM_ARCHITECTURE.md`
§2) — this renderer deliberately does **not** widen `EvidentiaReport` to get
there.

## 15. Integration note (shared docs)

This track (R1) was developed in a parallel worktree alongside M5a, which is
editing the same shared project files. To avoid clobbering M5a, the shared
`PROJECT_STATE.md`, `SESSION_HANDOFF.md` and the final `DECISIONS.md` entry are
**intentionally left untouched here**. They must be updated during integration,
once both tracks merge — recording R1's completion (including this post-review
correction pass: frozen binding-excerpt provenance, the BFF export route tests,
and the export configuration in `.env.example`) and the final renderer-track
decision entry. The repository-wide LF/CRLF pin and any `.gitattributes` change
are likewise deferred to a separate integration/infrastructure commit; golden
fixtures were not modified or re-recorded in this worktree.
