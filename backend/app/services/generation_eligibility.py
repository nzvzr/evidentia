"""M4 generation-eligibility predicate (M3 deliverable; NOT yet consumed).

The reusable gate M4's TenantCorpusProvider must apply to every candidate
version. It encodes the binding M2→M3 lifecycle contract (DECISIONS.md
2026-07-16): ``status == "ready"`` alone is NEVER generation eligibility — a
`pre-m3-transitional` version is rejected even when
``documents.current_version_id`` points to it.

**Fail closed against an explicit supported-target registry, bound to the ONE
pinned target.** Eligibility accepts a version only when its COMPLETE pinned
finalization target (`finalization_engine`, "cft1:<sha256>") is one the CURRENT
platform can reproduce (`supported_finalization_targets`) AND the persisted
`engine_versions` projection is EXACTLY that pinned target's canonical
projection — not merely a set of components each of which is valid for *some*
supported target. A hybrid artifact assembled from components that belong to
two different supported targets (e.g. the Markdown target pinned but the TXT
parser fields persisted) is rejected: the persisted projection is reconstructed
through the same typed `CompleteFinalizationTarget` machinery used at
enqueue/finalization time, its digest must equal the pinned digest, and it must
deep-equal the registered target's projection field-for-field (thresholds and
weights included). Missing keys, extra keys, altered values and wrong types all
fail closed.

**Persisted sections are validated, not only version metadata**: section
count, ordinal completeness, final (non-transitional) anchors and citation
ids, per-section classification signatures, complete canonical anchor
provenance (algorithm + inheritance versions, a supported decision, lineage
consistency) validated against the resolved pinned target, tenant ownership,
exact manifest reconstruction — which now cryptographically binds the anchor
provenance — against the stored digest, and the version classification
signature over the ordered section signatures. Any missing, malformed or
partially migrated field — including unparseable JSON — makes the version
ineligible; the predicate never raises.

The orchestrator/provider integration is explicitly M4 — nothing in M3 calls
this from the generation path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.anchors import (
    ANCHOR_ALGO_VERSION,
    is_canonical_anchor,
    validate_anchor_provenance,
)
from app.ingestion.classifier import version_signature
from app.ingestion.finalization_target import (
    CompleteFinalizationTarget,
    TargetProjectionError,
    build_finalization_target,
    target_from_engine_versions,
)
from app.ingestion.manifest import (
    build_manifest,
    manifest_sha256,
    section_manifest_entry,
)
from app.ingestion.parsers import FORMAT_MARKDOWN, FORMAT_TEXT
from app.ingestion.sectionizer import ANCHOR_ALGO_TRANSITIONAL
from app.models.db_models import (
    Document,
    DocumentSection,
    DocumentVersion,
    VERSION_STATUS_READY,
)
from app.modules.loader import (
    DomainModule,
    ModuleValidationError,
    canonical_json,
    get_active_module,
)

# Final anchor algorithm versions the platform supports for generation. A
# future anchor_algo v2 is added here; transitional never is.
SUPPORTED_FINAL_ANCHOR_ALGOS = frozenset({ANCHOR_ALGO_VERSION})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Final anchor structure: THE one canonical grammar (`anchors.is_canonical_anchor`
# / `ANCHOR_GRAMMAR_RE`) — 12..31-char base36 slug, optional dup suffix >= 2
# and part suffix >= 1 in canonical decimal (no "-0"/"-1"/leading zeros).
# Transitional ordinal ids ("s0007") are shorter than 12 and can never match.


def supported_finalization_targets() -> Dict[str, CompleteFinalizationTarget]:
    """THE registry: complete-target digest -> target, for every target the
    CURRENT platform can reproduce (each supported source format × the active
    module pack). An invalid or engine-incompatible module yields an EMPTY
    registry — everything then fails closed."""
    targets: Dict[str, CompleteFinalizationTarget] = {}
    try:
        module = get_active_module()
        for source_format in (FORMAT_MARKDOWN, FORMAT_TEXT):
            target = build_finalization_target(source_format, module)
            targets[target.digest] = target
    except ModuleValidationError:
        return {}
    return targets


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str  # stable machine-readable reason; "ok" when eligible


def _check_engine_components(
    engine: dict, targets: Dict[str, CompleteFinalizationTarget]
) -> Optional[str]:
    """Reject each unsupported component independently (stable reasons).
    Returns a reason or None when every component matches a supported value."""
    if not any(
        engine.get("parserName") == t.parser_name and engine.get("parser") == t.parser_version
        for t in targets.values()
    ):
        return "unsupported_parser"
    if not any(engine.get("normalizer") == t.normalizer for t in targets.values()):
        return "unsupported_normalizer"
    if not any(engine.get("sectionizer") == t.sectionizer for t in targets.values()):
        return "unsupported_sectionizer"
    algo = engine.get("anchorAlgo")
    if algo == ANCHOR_ALGO_TRANSITIONAL or algo not in SUPPORTED_FINAL_ANCHOR_ALGOS:
        return "unsupported_anchor_algo"
    if not any(engine.get("anchorInheritance") == t.anchor_inheritance for t in targets.values()):
        return "unsupported_inheritance"
    if not any(engine.get("classifier") == t.classifier for t in targets.values()):
        return "unsupported_classifier"
    if not any(engine.get("sectionSignature") == t.section_signature for t in targets.values()):
        return "unsupported_signature_version"
    if not any(engine.get("manifest") == t.manifest for t in targets.values()):
        return "unsupported_manifest_version"
    module = engine.get("module")
    if not isinstance(module, dict):
        return "missing_module_signature"
    if not any(
        module.get("id") == t.module_id and module.get("version") == t.module_version
        for t in targets.values()
    ):
        return "unknown_module"
    if not any(module.get("digest") == t.module_digest for t in targets.values()):
        return "module_digest_mismatch"
    if not any(
        module.get("signatureVersion") == t.module_signature_version for t in targets.values()
    ):
        return "unsupported_signature_version"
    return None


def _check_target_binding(
    engine: dict, pinned: str, expected_target: CompleteFinalizationTarget
) -> Optional[str]:
    """THE authoritative binding: the persisted projection must be EXACTLY the
    pinned complete target's projection.

    The per-component check above only proves each value is valid for *some*
    supported target; that admits a hybrid artifact assembled from two supported
    targets (the pinned Markdown target with the supported TXT parser fields
    persisted). This closes that gap in one canonical path:

    1. reconstruct the persisted projection through the same typed
       ``CompleteFinalizationTarget`` machinery used at enqueue/finalization;
    2. require its digest to equal the pinned digest — a component altered to a
       *different* supported target's value changes this digest;
    3. require exact deep equality (field-for-field, thresholds and weights
       included, type-sensitive) between the persisted projection and the
       registered target's canonical projection — catching extra keys, missing
       keys and any value the digest reconstruction is not sensitive to.
    """
    expected_projection = expected_target.engine_versions()
    # Exact key set first (so a missing/extra field reports precisely, before
    # reconstruction — which requires the component keys — could mask it).
    if set(expected_projection) - set(engine):
        return "target_projection_missing_field"
    if set(engine) - set(expected_projection):
        return "target_projection_extra_field"
    # Reconstruct through the typed machinery; malformed shapes/types fail here.
    try:
        persisted_target = target_from_engine_versions(engine)
    except TargetProjectionError:
        return "target_projection_invalid"
    # The reconstructed complete-target identity must be the pinned one — a
    # component altered to a DIFFERENT supported target's value changes this.
    if persisted_target.digest != pinned:
        return "target_digest_mismatch"
    # Type-sensitive exact equality (canonical_json distinguishes 2 from 2.0 and
    # is order-independent). A plain ``==`` would treat 2 == 2.0 as equal.
    try:
        if canonical_json(engine) != canonical_json(expected_projection):
            return "target_projection_mismatch"
    except (TypeError, ValueError):
        return "target_projection_invalid"
    return None


def _check_sections(
    db: Session,
    version: DocumentVersion,
    module: DomainModule,
    expected_target: CompleteFinalizationTarget,
    *,
    company_id: str,
) -> Optional[str]:
    """Validate the PERSISTED derived rows, not only version metadata."""
    document = db.execute(
        select(Document).where(
            Document.id == version.document_id, Document.company_id == company_id
        )
    ).scalar_one_or_none()
    if document is None or not document.citation_prefix:
        return "missing_document"

    rows: List[DocumentSection] = list(
        db.execute(
            select(DocumentSection)
            .where(
                DocumentSection.version_id == version.id,
                DocumentSection.company_id == company_id,
            )
            .order_by(DocumentSection.ordinal.asc())
        ).scalars()
    )
    if len(rows) != version.section_count:
        return "section_count_mismatch"
    if [row.ordinal for row in rows] != list(range(len(rows))):
        return "bad_ordinals"

    section_signatures: List[str] = []
    entries = []
    for row in rows:
        if not is_canonical_anchor(row.anchor_id):
            return "non_final_anchor"
        if row.citation_id != f"{document.citation_prefix}-{row.anchor_id}":
            return "non_final_citation"
        if not row.classification_signature or not _SHA256_RE.match(row.classification_signature):
            return "missing_section_signature"
        # Complete canonical anchor provenance, validated against the RESOLVED
        # pinned target's anchor + inheritance versions, the row's CURRENT
        # anchor and the frozen decision SEMANTICS — not merely field shape.
        # Missing lineage, an unsupported decision, a minted anchor carrying
        # inherited-from, an unrelated inheritedFrom, a below-threshold or
        # non-exact similarity, an impossible split parent/child relationship,
        # etc. all fail here.
        provenance_reason = validate_anchor_provenance(
            row.anchor_provenance,
            anchor_id=row.anchor_id,
            algo=expected_target.anchor_algo,
            inheritance=expected_target.anchor_inheritance,
        )
        if provenance_reason is not None:
            return provenance_reason
        # The stamped version algorithm and the row provenance must also agree
        # (defense against a version/row split).
        if row.anchor_provenance.get("algo") != version.anchor_algo_version:
            return "anchor_algo_mismatch"
        section_signatures.append(row.classification_signature)
        entries.append(
            section_manifest_entry(
                ordinal=row.ordinal,
                anchor_id=row.anchor_id,
                citation_id=row.citation_id,
                text_sha256=row.text_sha256,
                heading_path=list(row.heading_path or []),
                depth=row.depth,
                char_count=row.char_count,
                has_tables=row.has_tables,
                has_omitted_content=row.has_omitted_content,
                category=row.category,
                topics=list(row.topics or []),
                market_flags=list(row.market_flags or []),
                injection_flags=list(row.injection_flags or []),
                keywords=list(row.keywords or []),
                persona_affinity=dict(row.persona_affinity or {}),
                matched_rules=list(row.matched_rules or []),
                classification_signature=row.classification_signature,
                # Bind the canonical provenance into the manifest reconstruction:
                # any post-manifest provenance tamper now fails manifest_mismatch.
                anchor_provenance=dict(row.anchor_provenance),
            )
        )

    # The ordered persisted rows must reconstruct EXACTLY the stored manifest.
    manifest = build_manifest(
        content_sha256=version.content_sha256 or "",
        extracted_sha256=version.extracted_sha256 or "",
        citation_prefix=document.citation_prefix,
        engine_versions=dict(version.engine_versions),
        sections=entries,
    )
    if manifest_sha256(manifest) != version.manifest_sha256:
        return "manifest_mismatch"

    # The version signature must equal the signature over the ordered
    # per-section signatures under the (registry-verified) module.
    if version_signature(section_signatures, module) != version.classification_signature:
        return "signature_mismatch"
    return None


def check_generation_eligibility(
    db: Session, version: Optional[DocumentVersion], *, company_id: str
) -> EligibilityResult:
    """Why this version is (not) generation-eligible. Fail closed on anything
    unexpected — a malformed row must never reach a report."""
    try:
        if version is None:
            return EligibilityResult(False, "missing_version")
        if version.company_id != company_id:
            # Cross-tenant is indistinguishable from absent — same doctrine as
            # every repository lookup.
            return EligibilityResult(False, "missing_version")
        if version.status != VERSION_STATUS_READY:
            return EligibilityResult(False, "not_ready")
        if version.error_code:
            return EligibilityResult(False, "terminal_error")
        algo = version.anchor_algo_version
        if algo == ANCHOR_ALGO_TRANSITIONAL:
            return EligibilityResult(False, "transitional_identity")
        if algo not in SUPPORTED_FINAL_ANCHOR_ALGOS:
            return EligibilityResult(False, "unsupported_anchor_algo")

        targets = supported_finalization_targets()
        if not targets:
            return EligibilityResult(False, "no_supported_targets")

        # The pinned COMPLETE target must be explicitly registered, and the
        # stored engine record must agree with it.
        pinned = version.finalization_engine
        if not pinned or pinned not in targets:
            return EligibilityResult(False, "unsupported_target")
        expected_target = targets[pinned]
        engine = version.engine_versions
        if not isinstance(engine, dict):
            return EligibilityResult(False, "missing_engine_versions")
        if engine.get("target") != pinned:
            return EligibilityResult(False, "unsupported_target")

        # Coarse per-component diagnostics for genuinely unknown/future values...
        component_reason = _check_engine_components(engine, targets)
        if component_reason is not None:
            return EligibilityResult(False, component_reason)
        # ...then the AUTHORITATIVE exact binding to the ONE pinned target: a
        # hybrid of two supported targets fails here even though every component
        # is individually supported.
        binding_reason = _check_target_binding(engine, pinned, expected_target)
        if binding_reason is not None:
            return EligibilityResult(False, binding_reason)

        if not version.manifest_sha256 or not _SHA256_RE.match(version.manifest_sha256):
            return EligibilityResult(False, "missing_manifest")
        signature = version.classification_signature
        if not signature or not _SHA256_RE.match(signature):
            return EligibilityResult(False, "missing_classification_signature")
        if not version.section_count or version.section_count <= 0:
            return EligibilityResult(False, "no_sections")

        section_reason = _check_sections(
            db, version, get_active_module(), expected_target, company_id=company_id
        )
        if section_reason is not None:
            return EligibilityResult(False, section_reason)
        return EligibilityResult(True, "ok")
    except Exception:  # noqa: BLE001 - the predicate must fail closed, never raise
        return EligibilityResult(False, "malformed_version")


def is_generation_eligible(
    db: Session, version: Optional[DocumentVersion], *, company_id: str
) -> bool:
    return check_generation_eligibility(db, version, company_id=company_id).eligible
