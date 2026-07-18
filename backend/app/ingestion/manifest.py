"""The final deterministic version manifest (M3): ``MANIFEST_VERSION``.

One canonical JSON document covering every immutable generation-relevant
derived artifact of an M3-final document version: engine/module versions,
ordered final sections with anchors, internal citation identities,
deterministic classification outputs and their signatures, and the content
hashes. Its sha256 is persisted as ``document_versions.manifest_sha256``.

Properties (pinned by tests):

* identical input + identical engine/module versions => identical manifest;
* changing any load-bearing version, any section, any anchor or any
  classification changes the manifest;
* serialization is canonical (sorted keys, no whitespace, ASCII) and
  ordering-stable (sections in ordinal order);
* **no timestamps and no database ids** enter the digest — anchors and
  citation ids are algorithm-derived identities, not row ids;
* the old M2 transitional manifest (`sectionizer.manifest_sha256`) is a
  different, coexisting format and is never recomputed or touched.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Sequence

from app.modules.loader import canonical_json

MANIFEST_VERSION = "m3.1"


def build_manifest(
    *,
    content_sha256: str,
    extracted_sha256: str,
    citation_prefix: str,
    engine_versions: Mapping[str, Any],
    sections: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Assemble the manifest dict. ``sections`` entries must already be the
    bounded serializable projection built by the pipeline (ordinal order)."""
    return {
        "manifestVersion": MANIFEST_VERSION,
        "contentSha256": content_sha256,
        "extractedSha256": extracted_sha256,
        "citationPrefix": citation_prefix,
        "engineVersions": dict(engine_versions),
        "sections": list(sections),
    }


def section_manifest_entry(
    *,
    ordinal: int,
    anchor_id: str,
    citation_id: str,
    text_sha256: str,
    heading_path: Sequence[str],
    depth: int,
    char_count: int,
    has_tables: bool,
    has_omitted_content: bool,
    category: str,
    topics: Sequence[str],
    market_flags: Sequence[str],
    injection_flags: Sequence[str],
    keywords: Sequence[str],
    persona_affinity: Mapping[str, float],
    matched_rules: Sequence[str],
    classification_signature: str,
    anchor_provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    """Assemble one section entry. ``anchor_provenance`` is REQUIRED and enters
    the digest: the canonical anchor-provenance blob (algo, inheritance,
    decision, inherited-from lineage, similarity) is part of the immutable M3
    artifact, so it is cryptographically bound here rather than persisted as
    unhashed side metadata. It carries no database ids, timestamps or worker
    metadata."""
    return {
        "ordinal": ordinal,
        "anchorId": anchor_id,
        "citationId": citation_id,
        "textSha256": text_sha256,
        "headingPath": list(heading_path),
        "depth": depth,
        "charCount": char_count,
        "hasTables": has_tables,
        "hasOmittedContent": has_omitted_content,
        "category": category,
        "topics": list(topics),
        "marketFlags": list(market_flags),
        "injectionFlags": list(injection_flags),
        "keywords": list(keywords),
        "personaAffinity": dict(persona_affinity),
        "matchedRules": list(matched_rules),
        "classificationSignature": classification_signature,
        "anchorProvenance": dict(anchor_provenance),
    }


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
