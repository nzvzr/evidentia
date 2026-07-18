"""The COMPLETE finalization target (M3): every load-bearing input pinned.

``document_versions.finalization_engine`` is not an anchor-algorithm label —
it is the digest of the *complete* engine target a successor version was
produced for: parser, normalizer, sectionizer, anchor algorithm, anchor
inheritance, classifier, section-signature format, module identity
(id/version/digest/signatureVersion), manifest version and the module's
classification thresholds/weights. Anything that changes a persisted M3
artifact changes this digest.

Consequences (all DB- or worker-enforced, tested):

* the uniqueness ``(source_version_id, finalization_engine)`` means one
  successor per source and COMPLETE target — changing only the classifier,
  only the module version, only the module digest, only a threshold, etc.
  produces a DIFFERENT target and therefore a distinct successor;
* the target is captured at enqueue/trigger time and pinned on the successor
  row; a worker only processes a queued finalization when it can reproduce
  EXACTLY that pinned target from its own code + module pack — a worker
  running newer code refuses an old pinned target with a stable typed error
  (``unsupported_finalization_target``) instead of silently generating a
  different artifact;
* retrying/adopting an identical complete target converges on the same
  successor row (the digest string is deterministic);
* API trigger, CLI discovery/backfill, worker verification and idempotency
  all go through this ONE builder.

The digest string is ``cft1:<sha256 hex>`` over the canonical JSON payload
(sorted keys, no whitespace, ASCII) — versioned so a future payload-schema
change coexists rather than colliding.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from app.ingestion import anchors as anchors_module
from app.ingestion import classifier as classifier_module
from app.ingestion import manifest as manifest_module
from app.ingestion import normalize as normalize_module
from app.ingestion import sectionizer as sectionizer_module
from app.ingestion.parsers import get_parser
from app.modules.loader import DomainModule, canonical_json

TARGET_SCHEMA_VERSION = "cft1"


class TargetProjectionError(ValueError):
    """A persisted ``engine_versions`` projection is not a well-formed complete
    finalization-target projection (missing/malformed field or type). Eligibility
    maps this to a stable ineligible reason — it is never allowed to escape."""


@dataclass(frozen=True)
class CompleteFinalizationTarget:
    """A typed, canonical, complete finalization target. Frozen: build one
    through `build_finalization_target`, never mutate."""

    parser_name: str
    parser_version: str
    normalizer: str
    sectionizer: str
    anchor_algo: str
    anchor_inheritance: str
    classifier: str
    section_signature: int
    module_id: str
    module_version: str
    module_digest: str
    module_signature_version: str
    manifest: str
    thresholds: Tuple[Tuple[str, float], ...]
    weights: Tuple[Tuple[str, float], ...]

    def payload(self) -> Dict[str, Any]:
        """The canonical JSON-serializable form (deterministic ordering comes
        from canonical_json's sorted keys)."""
        return {
            "v": TARGET_SCHEMA_VERSION,
            "parserName": self.parser_name,
            "parser": self.parser_version,
            "normalizer": self.normalizer,
            "sectionizer": self.sectionizer,
            "anchorAlgo": self.anchor_algo,
            "anchorInheritance": self.anchor_inheritance,
            "classifier": self.classifier,
            "sectionSignature": self.section_signature,
            "module": {
                "id": self.module_id,
                "version": self.module_version,
                "digest": self.module_digest,
                "signatureVersion": self.module_signature_version,
            },
            "manifest": self.manifest,
            "thresholds": dict(self.thresholds),
            "weights": dict(self.weights),
        }

    @property
    def digest(self) -> str:
        """The stable persisted identity: ``cft1:<sha256 hex>`` of the
        canonical payload. This is what `finalization_engine` stores and what
        the one-successor-per-(source, target) uniqueness arbitrates."""
        raw = hashlib.sha256(canonical_json(self.payload()).encode("utf-8")).hexdigest()
        return f"{TARGET_SCHEMA_VERSION}:{raw}"

    def engine_versions(self) -> Dict[str, Any]:
        """The persisted `document_versions.engine_versions` projection: the
        complete target payload plus its own digest, so a stored version is
        self-describing and eligibility can verify the pinned target."""
        data = self.payload()
        data.pop("v", None)
        data["target"] = self.digest
        return data


def build_finalization_target(
    source_format: str, module: DomainModule
) -> CompleteFinalizationTarget:
    """THE single builder (trigger, CLI, worker, eligibility). Reads every
    version constant at call time and refuses (fail closed, via
    `ensure_module_compatible`) a module pack the current engine cannot
    execute — an incompatible pack can never even form a target."""
    classifier_module.ensure_module_compatible(module)
    parser = get_parser(source_format)
    return CompleteFinalizationTarget(
        parser_name=parser.name,
        parser_version=parser.version,
        normalizer=normalize_module.NORMALIZER_VERSION,
        sectionizer=sectionizer_module.SECTIONIZER_VERSION,
        anchor_algo=anchors_module.ANCHOR_ALGO_VERSION,
        anchor_inheritance=anchors_module.ANCHOR_INHERITANCE_VERSION,
        classifier=classifier_module.CLASSIFIER_VERSION,
        section_signature=classifier_module.SECTION_SIGNATURE_VERSION,
        module_id=module.module_id,
        module_version=module.version,
        module_digest=module.digest,
        module_signature_version=module.signature_version,
        manifest=manifest_module.MANIFEST_VERSION,
        thresholds=tuple(sorted(module.thresholds.items())),
        weights=tuple(sorted(module.weights.items())),
    )


def _require_str(engine: Mapping[str, Any], key: str) -> str:
    value = engine.get(key)
    if not isinstance(value, str) or not value:
        raise TargetProjectionError(f"engine_versions.{key} must be a non-empty string")
    return value


def _require_number_map(value: Any, where: str) -> Tuple[Tuple[str, float], ...]:
    if not isinstance(value, Mapping):
        raise TargetProjectionError(f"{where} must be an object")
    items = []
    for key, raw in value.items():
        if not isinstance(key, str):
            raise TargetProjectionError(f"{where} keys must be strings")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TargetProjectionError(f"{where}.{key} must be a number")
        # Preserve the persisted numeric value verbatim (no int->float coercion)
        # so the reconstructed digest reflects EXACTLY what is stored — a stored
        # int where a float is expected changes the canonical digest and is
        # therefore rejected downstream rather than silently normalized.
        items.append((key, raw))
    return tuple(sorted(items))


def target_from_engine_versions(engine: Mapping[str, Any]) -> CompleteFinalizationTarget:
    """Reconstruct the typed :class:`CompleteFinalizationTarget` a persisted
    ``document_versions.engine_versions`` projection encodes, using the SAME
    canonical machinery the enqueue/finalization path builds targets with.

    Raises :class:`TargetProjectionError` on any missing or malformed field or
    type. Extra top-level keys are ignored here (the exact-key check lives in
    eligibility's deep-equality step); the value of this reconstruction is that
    its ``.digest`` recomputes the complete-target identity from the persisted
    component values, so a component that was altered to a DIFFERENT supported
    target's value yields a different digest — not a silent pass.
    """
    if not isinstance(engine, Mapping):
        raise TargetProjectionError("engine_versions must be an object")
    module = engine.get("module")
    if not isinstance(module, Mapping):
        raise TargetProjectionError("engine_versions.module must be an object")
    section_signature = engine.get("sectionSignature")
    if isinstance(section_signature, bool) or not isinstance(section_signature, int):
        raise TargetProjectionError("engine_versions.sectionSignature must be an integer")
    return CompleteFinalizationTarget(
        parser_name=_require_str(engine, "parserName"),
        parser_version=_require_str(engine, "parser"),
        normalizer=_require_str(engine, "normalizer"),
        sectionizer=_require_str(engine, "sectionizer"),
        anchor_algo=_require_str(engine, "anchorAlgo"),
        anchor_inheritance=_require_str(engine, "anchorInheritance"),
        classifier=_require_str(engine, "classifier"),
        section_signature=section_signature,
        module_id=_require_str(module, "id"),
        module_version=_require_str(module, "version"),
        module_digest=_require_str(module, "digest"),
        module_signature_version=_require_str(module, "signatureVersion"),
        manifest=_require_str(engine, "manifest"),
        thresholds=_require_number_map(engine.get("thresholds"), "engine_versions.thresholds"),
        weights=_require_number_map(engine.get("weights"), "engine_versions.weights"),
    )
