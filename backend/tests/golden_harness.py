"""Golden-fixture harness for the permanent M3 identity surfaces.

Computes the full deterministic derivation for a fixture document — sections,
final anchors, inheritance decisions, internal citation ids, classifications,
signatures and the final manifest — from **pure inputs only** (no database,
no tenant, fixed citation prefix). The committed ``expected/*.json`` files
are the regression contract: tests compare exact equality and NEVER
regenerate; regeneration is an explicit reviewed command
(``python scripts/regenerate_golden_fixtures.py``).

Prior chains are computed recursively (a fixture's predecessor is derived
with ITS OWN predecessor), so multi-revision scenarios — size-bound
oscillation in particular — exercise the real inheritance history rather
than a flattened approximation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.ingestion.anchors import (
    AnchorAssignment,
    PriorSection,
    assign_anchors,
    render_citation_id,
)
from app.ingestion.classifier import classify_section, version_signature
from app.ingestion.finalization_target import build_finalization_target
from app.ingestion.manifest import (
    build_manifest,
    manifest_sha256,
    section_manifest_entry,
)
from app.ingestion.normalize import decode_and_normalize
from app.ingestion.parsers import get_parser
from app.ingestion.sectionizer import SectionDraft, sectionize
from app.modules.loader import get_active_module

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
FIXTURES_DIR = GOLDEN_DIR / "fixtures"
EXPECTED_DIR = GOLDEN_DIR / "expected"

# Fixed prefix so citation ids are pure-function outputs.
GOLDEN_PREFIX = "GLD"

# fixture name -> (source file, inheritance predecessor fixture or None)
FIXTURE_PLAN: Dict[str, Dict[str, Optional[str]]] = {
    "base": {"file": "base.md", "prior": None},
    "reprocess": {"file": "base.md", "prior": None},  # identical reprocessing
    "inherit-identical": {"file": "base.md", "prior": "base"},
    "insert-section": {"file": "insert-section.md", "prior": "base"},
    "delete-section": {"file": "delete-section.md", "prior": "base"},
    "move-section": {"file": "move-section.md", "prior": "base"},
    "light-edit": {"file": "light-edit.md", "prior": "base"},
    "rewrite": {"file": "rewrite.md", "prior": "base"},
    "merge": {"file": "merge.md", "prior": "base"},
    "rename-split": {"file": "rename-split.md", "prior": "base"},
    "duplicates": {"file": "duplicates.md", "prior": None},
    "duplicates-insert-before": {"file": "duplicates-insert-before.md", "prior": "duplicates"},
    "headingless": {"file": "headingless.txt", "prior": None},
    "split": {"file": "split.md", "prior": None},
    "oscillate-base": {"file": "oscillate-small.md", "prior": None},
    "oscillate-grow": {"file": "oscillate-big.md", "prior": "oscillate-base"},
    "oscillate-shrink": {"file": "oscillate-small.md", "prior": "oscillate-grow"},
}

# The permanent behaviors the corpus MUST pin. Kept as an explicit, reviewed
# set and asserted equal to the registered plan so a future fixture omission
# can never pass silently.
REQUIRED_GOLDEN_CASES = frozenset(
    {
        "base",
        "reprocess",
        "inherit-identical",
        "insert-section",
        "delete-section",
        "move-section",
        "light-edit",
        "rewrite",
        "merge",
        "rename-split",
        "duplicates",
        "duplicates-insert-before",
        "headingless",
        "split",
        "oscillate-base",
        "oscillate-grow",
        "oscillate-shrink",
    }
)


def _drafts_for(name: str):
    plan = FIXTURE_PLAN[name]
    path = FIXTURES_DIR / plan["file"]
    data = path.read_bytes()
    text = decode_and_normalize(data, max_chars=1_000_000)
    source_format = "markdown" if plan["file"].endswith(".md") else "text"
    parser = get_parser(source_format)
    doc_ir = parser.parse(text)
    return data, text, sectionize(doc_ir), parser


def _assignments_for(name: str) -> Tuple[List[SectionDraft], List[AnchorAssignment]]:
    """Drafts + anchor assignments for a fixture, with its FULL prior chain
    (recursive: the predecessor's anchors are themselves inherited)."""
    plan = FIXTURE_PLAN[name]
    _data, _text, drafts, _parser = _drafts_for(name)
    prior: List[PriorSection] = []
    if plan["prior"]:
        prior_drafts, prior_assignments = _assignments_for(plan["prior"])
        prior = [
            PriorSection(
                anchor_id=a.anchor_id,
                text_sha256=d.text_sha256,
                token_set=tuple(d.token_set),
                ordinal=d.ordinal,
                heading_path=tuple(d.heading_path),
            )
            for d, a in zip(prior_drafts, prior_assignments)
        ]
    return drafts, assign_anchors(drafts, prior)


def compute_fixture(name: str) -> Dict[str, Any]:
    """The complete golden output for one fixture (pure, deterministic)."""
    data, text, drafts, parser = _drafts_for(name)
    _same_drafts, assignments = _assignments_for(name)

    module = get_active_module()
    classifications = [
        classify_section(d, module, anchor_id=a.anchor_id) for d, a in zip(drafts, assignments)
    ]

    # The SAME complete-target builder the pipeline persists from — the golden
    # corpus pins the target digest as part of the identity surface.
    source_format = "markdown" if FIXTURE_PLAN[name]["file"].endswith(".md") else "text"
    target = build_finalization_target(source_format, module)
    engine_versions = target.engine_versions()
    manifest_sections = [
        section_manifest_entry(
            ordinal=d.ordinal,
            anchor_id=a.anchor_id,
            citation_id=render_citation_id(GOLDEN_PREFIX, a.anchor_id),
            text_sha256=d.text_sha256,
            heading_path=d.heading_path,
            depth=d.depth,
            char_count=d.char_count,
            has_tables=d.has_tables,
            has_omitted_content=d.has_omitted_content,
            category=c.category,
            topics=c.topics,
            market_flags=c.market_flags,
            injection_flags=c.injection_flags,
            keywords=c.keywords,
            persona_affinity=c.persona_affinity,
            matched_rules=c.matched_rules,
            classification_signature=c.signature,
            anchor_provenance=a.provenance(),
        )
        for d, a, c in zip(drafts, assignments, classifications)
    ]
    manifest = build_manifest(
        content_sha256=hashlib.sha256(data).hexdigest(),
        extracted_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        citation_prefix=GOLDEN_PREFIX,
        engine_versions=engine_versions,
        sections=manifest_sections,
    )

    return {
        "fixture": name,
        "finalizationTarget": target.digest,
        "sections": [
            {
                "ordinal": d.ordinal,
                "title": d.title,
                "headingPath": d.heading_path,
                "anchorId": a.anchor_id,
                "citationId": render_citation_id(GOLDEN_PREFIX, a.anchor_id),
                "decision": a.decision,
                "inheritedFrom": a.inherited_from,
                # The full canonical provenance now bound into the manifest — pin
                # it explicitly so the golden diff shows exactly what is hashed.
                "anchorProvenance": a.provenance(),
                "textSha256": d.text_sha256,
                "hasTables": d.has_tables,
                "hasOmittedContent": d.has_omitted_content,
                "category": c.category,
                "topics": c.topics,
                "marketFlags": c.market_flags,
                "injectionFlags": c.injection_flags,
                "matchedRules": c.matched_rules,
                "classificationSignature": c.signature,
            }
            for d, a, c in zip(drafts, assignments, classifications)
        ],
        "versionClassificationSignature": version_signature(
            [c.signature for c in classifications], module
        ),
        "manifestSha256": manifest_sha256(manifest),
    }


def expected_path(name: str) -> Path:
    return EXPECTED_DIR / f"{name}.json"


def load_expected(name: str) -> Dict[str, Any]:
    return json.loads(expected_path(name).read_text(encoding="utf-8"))


def write_expected(name: str, payload: Dict[str, Any]) -> None:
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    expected_path(name).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
