"""Typed platform contracts, v1 (M1 deliverable).

The section dictionary is the platform's most load-bearing interface and must
not remain an anonymous dict (`PLATFORM_ARCHITECTURE.md` §5). This module is
the single home of the versioned contracts the layers exchange:

    RawDocument v1                 L1 → L2   (connector/upload output)
    DocIR v1                       L2 → L4   (parser output; transient)
    SectionRecord v1               L4 → L5/L6/L7 currency
    EvidenceBinding v1             L7 output
    ClaimSpec v1                   pattern → engine (compiled pattern)
    ClaimCandidate v1              L6 → L7                       [stub]
    Finding v1                     L8                            [stub]
    Recommendation v1              L8                            [stub]
    CanonicalAnalysisDocument v1   L8 output                     [stub]

Versioning rules:

* Every contract carries a ``contract_version`` ClassVar. "Immutable" means a
  version is never reinterpreted: new meaning => a new contract version, with
  the old one kept until every consumer has moved.
* Contracts marked ``[stub]`` reserve the shape agreed in the architecture
  documents so later milestones (M4/M5a) implement against a name that already
  exists; their loosely-typed fields are firmed up when their producing layer
  lands. Stubs are still real, constructible types — only their field *types*
  are permissive.

Compatibility (`PLATFORM_ARCHITECTURE.md` §5): the current pipeline currency
``{documentId, source, sectionTitle, excerpt, category, citationId}`` is a
strict projection of `SectionRecord v1` — see
:meth:`SectionRecord.to_pipeline_section`. Existing scorers, gates and binders
keep receiving exactly the dict shape they receive today.

Nothing in this module is consumed by the runtime pipeline yet: M1 introduces
the contracts and seams; M2+ produce and consume them. Behaviour with
``EVIDENTIA_TENANT_CORPUS_ENABLED`` off (the default) is unchanged
byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Mapping, Optional, Tuple

# --------------------------------------------------------------------------- #
# Shared vocabulary
# --------------------------------------------------------------------------- #

# DocIR block kinds — the closed set every parser may emit (L3).
DOC_BLOCK_KINDS = frozenset({"heading", "paragraph", "table", "list", "omitted"})

# Claim families (§4-B): the generic, domain-independent claim categories.
CLAIM_FAMILIES = frozenset({"gap", "contradiction", "staleness", "assertion"})

# Evidence gate decisions (§5, EvidenceBinding v1).
EVIDENCE_DECISIONS = frozenset({"accepted", "insufficient"})
CLAIM_DECISIONS = frozenset({"accepted", "rejected", "insufficient_evidence"})
CLAIM_CANDIDATE_SOURCES = frozenset({"deterministic_pattern", "llm_proposal"})
CLAIM_CANDIDATE_STATUSES = frozenset({"proposed"})

# Raw-document source types (L1). Connectors extend this additively
# ("connector:<name>"), which is why it is validated as a prefix rule, not an enum.
KNOWN_SOURCE_TYPES = frozenset({"upload", "api"})
CONNECTOR_SOURCE_PREFIX = "connector:"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


# --------------------------------------------------------------------------- #
# RawDocument v1 — L1 -> L2
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RawDocumentOrigin:
    """Where the bytes came from. A connector never interprets what it fetches;
    this metadata is the whole of what L1 may say about content."""

    source_type: str  # "upload" | "api" | "connector:<name>"
    uri: Optional[str] = None
    external_id: Optional[str] = None

    def __post_init__(self) -> None:
        _require(
            self.source_type in KNOWN_SOURCE_TYPES
            or self.source_type.startswith(CONNECTOR_SOURCE_PREFIX),
            f"unknown source_type {self.source_type!r}; expected one of "
            f"{sorted(KNOWN_SOURCE_TYPES)} or '{CONNECTOR_SOURCE_PREFIX}<name>'",
        )


@dataclass(frozen=True)
class RawDocument:
    """Bytes plus declared origin — the only thing L1 hands to ingestion.

    ``declared_mime`` is a *claim* by the source; L2 decides the real format by
    magic-byte sniffing (extensions and declared types are hints, never trusted).
    """

    contract_version: ClassVar[int] = 1

    data: bytes
    declared_mime: str
    origin: RawDocumentOrigin
    tenant_ref: str  # company_id — carried, never decided, by ingestion
    received_at: datetime

    def __post_init__(self) -> None:
        _require(isinstance(self.data, bytes), "RawDocument.data must be bytes")
        _require(bool(self.tenant_ref), "RawDocument.tenant_ref is required")


# --------------------------------------------------------------------------- #
# DocIR v1 — L2 -> L4 (transient; never persisted)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DocBlock:
    """One normalized content block. Parsers are the only format-aware code in
    the platform; format-specific detail may ride in ``meta`` but must never be
    required downstream."""

    kind: str  # heading | paragraph | table | list | omitted
    text: str
    level: Optional[int] = None  # heading depth; headings only
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(
            self.kind in DOC_BLOCK_KINDS,
            f"unknown DocIR block kind {self.kind!r}; expected one of {sorted(DOC_BLOCK_KINDS)}",
        )
        if self.level is not None:
            _require(self.level >= 1, "DocBlock.level must be >= 1 when present")


@dataclass(frozen=True)
class DocIR:
    """The single format-neutral representation of extracted content: an
    ordered block stream with heading hierarchy."""

    contract_version: ClassVar[int] = 1

    blocks: Tuple[DocBlock, ...]


# --------------------------------------------------------------------------- #
# SectionRecord v1 — the pipeline currency (L4 -> L5/L6/L7)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SectionRecord:
    """A section with stable identity, full scoring content, classification and
    provenance — what the anonymous section dict conflated, made explicit.

    Field groups (`PLATFORM_ARCHITECTURE.md` §5):

    * identity — immutable within a document version.
    * content — ``text``/``token_set`` are what deterministic scoring consumes
      (full bounded section text; the 200–4,000 char bounds are enforced by the
      sectionizer, which is versioned with the anchor algorithm — M2/M3).
      ``excerpt`` is a display and prompt-budget field ONLY (§5.1): scoring
      against the excerpt blinds the gate to most of a long section.
    * classification — module-supplied signature results plus the versions that
      produced them (optional until M3 lands classifier provenance).
    * provenance — which parser and anchor algorithm minted this row.
    """

    contract_version: ClassVar[int] = 1

    # identity
    document_id: str
    version_id: str
    anchor_id: str
    citation_id: str
    # structure
    heading_path: Tuple[str, ...]
    title: str
    ordinal: int
    depth: int
    # content
    text: str
    excerpt: str
    text_sha256: str
    token_set: frozenset[str]
    char_count: int
    has_tables: bool = False
    has_omitted_content: bool = False
    # classification (optional until M3)
    category: Optional[str] = None
    topics: Tuple[str, ...] = ()
    facets: Mapping[str, Any] = field(default_factory=dict)
    persona_affinity: Mapping[str, float] = field(default_factory=dict)
    injection_flags: Tuple[str, ...] = ()
    classifier_version: Optional[str] = None
    signature_pack_version: Optional[str] = None
    # provenance
    parser_version: Optional[str] = None
    anchor_algo_version: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("document_id", "version_id", "anchor_id", "citation_id"):
            _require(bool(getattr(self, name)), f"SectionRecord.{name} is required")
        _require(self.ordinal >= 0, "SectionRecord.ordinal must be >= 0")

    def to_pipeline_section(self, source_title: str) -> dict[str, Any]:
        """Project into the existing pipeline currency dict.

        ``source`` is the owning document's display title — document-level
        state a SectionRecord deliberately does not duplicate, so the provider
        (which holds the document row) supplies it. Everything else is a strict
        field-for-field projection; existing scorers, gates and binders receive
        exactly the shape `agents/document_reader.py` emits today.
        """
        return {
            "documentId": self.document_id,
            "source": source_title,
            "sectionTitle": self.title,
            "excerpt": self.excerpt,
            "category": self.category,
            "citationId": self.citation_id,
        }


# --------------------------------------------------------------------------- #
# EvidenceBinding v1 — L7 output
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SectionRef:
    """A durable pointer to a section: document + version + anchor. Evidence
    always resolves to a section (the graph-compatibility invariant, §11)."""

    document_id: str
    version_id: str
    anchor_id: str


@dataclass(frozen=True)
class EvidenceBinding:
    """The gate's decision record binding a claim to a section. The
    deterministic evidence gate is the sole grounding authority; retrieval may
    rank candidates but only L7 mints one of these."""

    contract_version: ClassVar[int] = 1

    claim_ref: str
    section_ref: SectionRef
    citation_id: str
    matched_signals: Tuple[str, ...]
    matched_phrases: Tuple[str, ...]
    support_score: float
    threshold_policy_version: Optional[str]
    decision: str  # accepted | insufficient

    def __post_init__(self) -> None:
        _require(
            self.decision in EVIDENCE_DECISIONS,
            f"unknown EvidenceBinding decision {self.decision!r}; "
            f"expected one of {sorted(EVIDENCE_DECISIONS)}",
        )


# --------------------------------------------------------------------------- #
# ClaimSpec v1 — declarative pattern, compiled (pattern file -> engine)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClaimSpec:
    """A compiled declarative claim pattern (§4-B). Patterns are data, never
    executable code; the engine executes typed matcher primitives against these
    fields and never contains domain vocabulary itself.

    The legacy ``triggers`` / ``evidence`` / ``exclusions`` / ``templates`` /
    ``severity_policy`` mappings remain for compatibility with reserved M1
    callers. M5a's loader strictly compiles the fields below from validated
    ``claim-patterns-v1`` data.
    """

    contract_version: ClassVar[int] = 1

    id: str  # stable, namespaced: "<module>.<pattern-name>"
    module: str
    version: str  # pattern semver
    family: str  # gap | contradiction | staleness | assertion
    triggers: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    exclusions: Mapping[str, Any] = field(default_factory=dict)
    templates: Mapping[str, Any] = field(default_factory=dict)
    severity_policy: Mapping[str, Any] = field(default_factory=dict)
    # M5a compiled fields. The original M1 mappings above remain compatible
    # with callers that constructed the reserved contract directly.
    title: str = ""
    claim_type: str = "assertion"
    priority_hint: Optional[str] = None
    evidence_needs: Tuple[Mapping[str, Any], ...] = ()
    matcher: Mapping[str, Any] = field(default_factory=dict)
    gate_policy_id: str = ""
    gate_policy_version: str = ""
    output_metadata: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    provenance: Mapping[str, Any] = field(default_factory=dict)
    pattern_digest: str = ""

    def __post_init__(self) -> None:
        _require(bool(self.id), "ClaimSpec.id is required")
        _require(bool(self.module), "ClaimSpec.module is required")
        _require(
            self.family in CLAIM_FAMILIES,
            f"unknown ClaimSpec family {self.family!r}; expected one of {sorted(CLAIM_FAMILIES)}",
        )

    @property
    def claim_spec_id(self) -> str:
        return self.id

    @property
    def pattern_version(self) -> str:
        return self.version


# --------------------------------------------------------------------------- #
# Claim proposal and decision contracts (M5a); later CAD shapes remain reserved
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClaimCandidate:
    """An L6 proposal, never a conclusion: it must
    pass the L7 gate to exist as a claim. Exactly one of ``spec_ref`` (pattern
    id+version) or ``proposer_ref`` (llm: model, prompt version) identifies the
    candidate source."""

    contract_version: ClassVar[int] = 1

    spec_ref: Optional[str] = None
    proposer_ref: Optional[Mapping[str, str]] = None
    candidate_sections: Tuple[SectionRef, ...] = ()
    slots: Mapping[str, Any] = field(default_factory=dict)
    proposed_severity: Optional[str] = None
    candidate_id: str = ""
    claim_spec_id: str = ""
    pattern_version: str = ""
    proposed_statement: str = ""
    source_snapshot_id: str = ""
    source_snapshot_digest: str = ""
    proposed_binding_ids: Tuple[str, ...] = ()
    matcher_observations: Tuple[Mapping[str, Any], ...] = ()
    deterministic_features: Mapping[str, float] = field(default_factory=dict)
    proposer_metadata: Optional[Mapping[str, str]] = None
    candidate_source: str = "deterministic_pattern"
    status: str = "proposed"

    def __post_init__(self) -> None:
        _require(
            (self.spec_ref is None) != (self.proposer_ref is None),
            "ClaimCandidate requires exactly one of spec_ref or proposer_ref",
        )
        _require(
            self.candidate_source in CLAIM_CANDIDATE_SOURCES,
            f"unknown candidate source {self.candidate_source!r}",
        )
        _require(self.status in CLAIM_CANDIDATE_STATUSES, "candidate status must be proposed")


@dataclass(frozen=True)
class ClaimDecision:
    """Versioned deterministic L7 gate result.

    Only accepted decisions may project into report items. Rejected and
    insufficient decisions remain report-local audit provenance.
    """

    contract_version: ClassVar[int] = 1

    candidate_id: str
    decision: str
    support_score: float
    threshold: float
    reason_codes: Tuple[str, ...]
    matched_requirements: Tuple[str, ...]
    missing_requirements: Tuple[str, ...]
    conflicting_evidence: Tuple[str, ...]
    accepted_binding_ids: Tuple[str, ...]
    gate_policy_id: str
    gate_policy_version: str
    gate_engine_version: str
    deterministic_features: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(self.decision in CLAIM_DECISIONS, f"unknown claim decision {self.decision!r}")
        _require(0.0 <= self.support_score <= 1.0, "support_score must be between 0 and 1")
        _require(0.0 <= self.threshold <= 1.0, "threshold must be between 0 and 1")
        if self.decision == "accepted":
            _require(bool(self.accepted_binding_ids), "accepted claims require an evidence binding")


@dataclass(frozen=True)
class Finding:
    """[stub — produced by L8] Claims composed into an analytical statement with
    the module's severity policy applied ("risk" is a module's finding
    rendering, not a core concept)."""

    contract_version: ClassVar[int] = 1

    claim_refs: Tuple[str, ...]
    statement: str
    severity: str
    confidence: float
    evidence_refs: Tuple[str, ...]
    module_ref: str


@dataclass(frozen=True)
class Recommendation:
    """[stub — produced by L8] Grounded, evidence-linked recommendation."""

    contract_version: ClassVar[int] = 1

    finding_refs: Tuple[str, ...]
    statement: str
    evidence_refs: Tuple[str, ...]
    action_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalAnalysisDocument:
    """[stub — CAD v1, §2.1] The eventual internal engine output. NOT the
    runtime output in M1–M5: the public `EvidentiaReport` schema is unchanged
    and becomes this document's first deterministic projection when the first
    non-report renderer needs it. Reserved so every proposed `EvidentiaReport`
    addition can be answered with "CAD concept, module extension, or renderer
    concern?" against a real type."""

    contract_version: ClassVar[int] = 1

    meta: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    sources: Tuple[Mapping[str, Any], ...] = ()
    evidence: Tuple[EvidenceBinding, ...] = ()
    claims: Tuple[Mapping[str, Any], ...] = ()
    findings: Tuple[Finding, ...] = ()
    contradictions: Tuple[str, ...] = ()
    gaps: Tuple[str, ...] = ()
    recommendations: Tuple[Recommendation, ...] = ()
    actions: Tuple[Mapping[str, Any], ...] = ()
    narrative: Tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    renderer_hints: Mapping[str, Any] = field(default_factory=dict)
