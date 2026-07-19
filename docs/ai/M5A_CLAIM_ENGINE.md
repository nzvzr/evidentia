# Evidentia M5a — bounded claim engine

M5a inserts a declarative, deterministic claim-validation layer between the M4
tenant snapshot and the existing `EvidentiaReport` projection. It is a rollout-
gated bridge toward the platform CAD; it is not the CAD runtime and it does not
expand the public 20-key report schema.

## Execution boundary

For authenticated tenant generation with `EVIDENTIA_CLAIM_ENGINE_ENABLED=true`:

```
M4 frozen versions + report-local EvidenceBindings
  -> claim-pattern-engine-v1
  -> ClaimCandidate v1 (deterministic and optional LLM proposals)
  -> typed-matchers-v1 observations over bounded full canonical section text
  -> deterministic-support-gate-v1
  -> accepted | rejected | insufficient_evidence
  -> one accepted-only projection for workflow, risks, actions and narrative
```

The flag defaults off. Off preserves the M4 path. It is active only with
`TenantCorpusProvider`; demo generation does not run tenant claims. A claim-
enabled generation bypasses the report cache because every persisted report owns
an independent claim graph. Claim-engine failure fails the generation; it never
falls back to the pre-gate risk path.

## Contracts

The pre-existing `ClaimSpec` and `ClaimCandidate` stubs in `app/contracts.py`
were firmed in place; no parallel types were introduced.

- `ClaimSpec` identifies the module-owned specification and pattern version,
  evidence needs and weights, matcher tree, gate policy id/version, output
  metadata, enablement and immutable pattern digest/provenance.
- `ClaimCandidate` identifies the proposal, exact `tcs1` source snapshot,
  proposed report-local citation/binding references, matcher observations,
  deterministic features, proposer metadata, source
  (`deterministic_pattern`/`llm_proposal`) and pre-gate status.
- `ClaimDecision` records the sole authoritative status, rounded support score,
  threshold, stable reason codes, matched/missing needs, conflicting evidence,
  accepted binding ids and gate policy/engine versions.

These are audit contracts. Database ids and claims are never inserted into
`EvidentiaReport`.

## Declarative release format

The active claim pack lives at
`modules/compliance/claim-patterns/1.0.0/claim-patterns.json`, schema
`claim-patterns-v1`. It is independently identified and digested as
`compliance.claim-patterns@1.0.0` while targeting the unchanged
`compliance@1.0.0` classification module. The root contains canonical pack,
module and release identity,
versioned gate policies, patterns and release provenance. Every pattern contains
a namespaced id, semantic version, claim metadata, typed evidence needs, matcher
tree, gate reference, output projection metadata and provenance.

Loading is atomic and strict: unknown fields/primitives, duplicate ids, invalid
semver/thresholds, oversized/deep matcher trees, malformed parameter ranges,
external/network/file references and executable/template markers are rejected.
Pattern content is JSON data only—there is no regex primitive, `eval`, dynamic
import, expression evaluation or template execution. Canonical JSON SHA-256
digests identify both the release and each pattern. Persisted pattern identities
are immutable; changed content under an existing identity is refused.

The small `claim-fixtures.json` pack contains seven demonstration patterns with
35 positive, negative, negated, ambiguous and boundary cases: administrative
MFA, privileged review, emergency review deadline, incident notification,
critical-supplier assessment, backup testing and policy ownership. It is
regression infrastructure, not production compliance coverage.

The released M3 directory `modules/compliance/1.0.0/` remains byte-for-byte and
layout identical to HEAD: it contains only `module.json`, `taxonomy.json` and
`signatures.json`. Claim-pack additions or changes therefore do not alter the M3
module digest, classification signatures, finalization target, section identities
or any of the 17 committed M3 golden outputs.

## Typed primitive registry

`typed-matchers-v1` supports:

- `token_any`, `token_all`, `exact_phrase`, `proximity`, `heading_match`;
- `classification_match`, `obligation_term`, `prohibition_term`, `negation`;
- `numeric_value`, `duration_deadline`, `evidence_count`;
- `all_of`, `any_of`, `not`, `minimum_should_match`.

`comparison` is deliberately rejected by `claim-patterns-v1`; typed feature and
unit plumbing is deferred to a future schema version rather than exposing a dead
primitive. Text normalization is explicit NFKC + Unicode casefold + canonical whitespace.
Evidence and outputs are stably sorted. Proximity is directional and token-
bounded. Numeric/duration parsing uses fixed safe engine regexes, not pattern-
provided regex. Matcher observations retain matched binding ids, terms, spans,
numeric values and child observations. Evidence is capped at 500 items, each
canonical text at 80,000 characters; schema depth is capped at 12 and each tree
at 128 nodes. Nested `evidence_count` is rejected at atomic release load, and a
candidate-wide budget caps execution at 4,096 primitive evaluations. Every
primitive sees at most the 500-item frozen set.
Engine code contains no branches on domain labels or compliance vocabulary.

## Deterministic support gate

`deterministic-support-gate-v1` is the only component that can accept a claim.
Every deterministic and LLM candidate is evaluated against the same complete,
bounded frozen evidence set. Conflict and required-support matchers always see
that full set. The supplied policy computes an explainable weighted score from required-need
coverage, leaf matcher support, binding count, source diversity and explicit
obligation/prohibition language, then applies the versioned contradiction
penalty. Only bindings attributed to successful support-requirement observations
can contribute binding count, document diversity or accepted provenance.
Duplicate citations are deduplicated, document diversity counts supporting
documents, and conflict bindings remain conflict observations rather than
accepted support. Values are clamped to `[0,1]` and decimal-rounded to six places.

Decision precedence is fail closed:

1. malformed candidate or evidence outside the frozen registry -> `rejected`;
2. matching contradiction/negation -> `rejected`;
3. no valid binding or a missing required need -> `insufficient_evidence`;
4. score at/above accept threshold -> `accepted` with exact binding ids;
5. score at/below reject threshold -> `rejected`;
6. the middle band -> `insufficient_evidence`.

Reason codes include `SUPPORT_THRESHOLD_MET`, `CONTRADICTING_EVIDENCE`,
`NO_VALID_EVIDENCE`, `EVIDENCE_OUTSIDE_FROZEN_REGISTRY`,
`MISSING_REQUIRED_MATCHER`, `SUPPORT_BELOW_REJECT_THRESHOLD`,
`SUPPORT_BELOW_ACCEPT_THRESHOLD` and `MALFORMED_CANDIDATE`.

## LLM boundary

LLM-off fully runs patterns, matchers, the gate and report projection. In full
LLM mode the model may return only an allowed claim-spec id, proposed wording and
frozen evidence codes. Citation codes are non-authoritative hints: they may narrow
the final attached matcher-attributed support bindings, but never narrow matcher
visibility, hide conflicts or increase support. The prompt/schema exposes no accepted field. Unknown
specifications, malformed proposals and hallucinated citations are rejected;
every valid proposal is re-matched over the complete frozen set and re-gated beside the deterministic
candidate. Failed or rejected proposals never remove deterministic candidates.
The accepted-only projection is the only claim-mode source of workflows, risks,
recommendations, summary and top finding. With zero accepted claims those arrays
are empty and the narrative states that evidence supported no accepted claim;
insufficient evidence is never rendered as a factual negative. Raw sections do
not retain a parallel analytical-output path. Narrative polish cannot bypass the
projection. Full-mode analytical changes are applied atomically; any exception
restores persona, workflow, risks, actions, narrative, claim run and inclusion
intent to the complete deterministic baseline and reports deterministic mode.

## Provenance and persistence

Migration `f5a6c7d8e9b0` follows M4 revision `e4b7c9d2a610` and adds:

- `claim_pattern_versions` — immutable release/pattern definitions and digests;
- `report_claim_candidates`, `report_claim_decisions`,
  `report_claim_evidence` — independent report-local claim graphs;
- `pattern_metrics` — tenant- and pattern-version-scoped aggregates;
- `report_feedback`, `item_feedback`, `citation_feedback`, `retrieval_misses`.

Pattern rows and report engine provenance record the exact claim-pack id, version
and canonical digest independently from the target classification module.
Candidate decisions reference exact M4 report-local bindings; bounded observations
and digests are stored instead of duplicating full tenant text. Report/company
and candidate/binding/company composite foreign keys make hostile cross-tenant
graphs invalid at SQL level. Report provenance records pattern release, matcher,
gate and threshold-policy versions. `GET /api/reports/{id}/claims` exposes the
tenant-scoped audit projection separately from the public report.

Downgrade removes M5a-only data and the added binding composite key, restoring
the exact M4 schema while retaining M4 reports and source provenance. Re-upgrade
does not fabricate claim decisions for older reports.

## Metrics and feedback

Pattern metrics count evaluations, fires, candidates, bindings, accepted,
rejected, insufficient, final-report inclusions and LLM proposals. PostgreSQL and
SQLite use atomic conflict-update addition; immutable pattern import is also
insert-if-absent with digest verification. Metrics are non-authoritative and
never modify policies or thresholds.

Authenticated replacement-semantics endpoints are:

- `GET|PUT /api/reports/{id}/feedback`;
- `PUT /api/reports/{id}/feedback/items`;
- `PUT /api/reports/{id}/feedback/citations`;
- `PUT /api/reports/{id}/retrieval-misses`.

Membership is derived server-side. Reports must be completed and tenant-visible;
item JSON paths use canonical non-negative indexes without leading zeroes. Exact
citations and claim needs are validated, and a browser-submitted corrected anchor
is resolved to an exact report-local `ReportEvidenceBinding` before persistence.
A composite SQL foreign key enforces the same report and company, so another live
or historical source version—or another report from the same tenant—is not
sufficient. Payloads and text are bounded and writes use the
feedback rate limiter. Feedback never changes production behavior. The Next BFF
proxies the same authenticated endpoints. The report page supplies compact report,
risk and citation controls and keys loaded state to user+company so account
switches cannot retain another tenant's feedback.

## Evaluation and deferred M5b work

`eval/claim_metrics.py` adds fixture precision/recall, negative false-positive
rate, insufficient-evidence accuracy, citation validity, accepted-binding
completeness, LLM proposal acceptance/rejection and pattern-version comparison.
The benchmark dataset version is `evidentia-eval-v2`; no statistical quality
claim is made from the tiny fixture set.

M5b remains responsible for broad domain content authoring and calibration.
Embeddings, FTS, OCR/PDF/DOCX, external packs/connectors, automatic learning,
automatic threshold changes, cross-tenant learning and the full CAD runtime are
not part of M5a.
