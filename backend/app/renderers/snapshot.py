"""The typed, renderer-facing snapshot (Phase 1 + Phase 2).

A renderer must not consume the raw persisted ``report_json`` dict directly: that
dict is the public compatibility projection, its fields are loosely typed, and an
old/migrated/hostile row may be missing keys or carry wrong types. This module
assembles those persisted inputs — the completed ``EvidentiaReport`` JSON and its
report-local M4 source audit — into an immutable, defensively-typed view that a
renderer can walk without guessing.

Boundaries this module enforces (the renderer invariant, `PLATFORM_ARCHITECTURE`
§2.2):

* **Persisted-only inputs.** The only inputs are the stored report JSON, the
  stored source-audit projection, tenant *display* information from the
  authenticated context, and renderer options. Nothing here reads a live
  document, a current version pointer, or a global citation registry.
* **No fabrication.** Absent fields become empty/``None`` and are surfaced
  honestly; they are never invented. Numbers are coerced, never defaulted to a
  plausible-looking value.
* **Bounded.** Every list is capped, so a pathological row cannot ask the
  renderer to emit an unbounded document.

The dataclasses hold raw text; XML/length sanitization happens at write time in
the DOCX renderer via ``sanitize.clean_text`` so the same snapshot can feed a
future PDF/HTML renderer with its own escaping rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# --- structural caps -------------------------------------------------------
# Generous but finite: real reports are far smaller. These bound the projection,
# not the content, so a hostile/huge row cannot inflate the rendered artifact.
MAX_WORKFLOW_STEPS = 100
MAX_RISKS = 200
MAX_CITATIONS = 500
MAX_AGENT_STEPS = 60
MAX_ACTIONS = 60
MAX_PRIORITIES = 60
MAX_DOC_RELEVANCE = 120
MAX_SOURCE_VERSIONS = 300
MAX_EVIDENCE_BINDINGS = 1500
MAX_HEADING_PATH = 24

_VALID_SEVERITIES = {"High", "Medium", "Low"}
INSUFFICIENT_EVIDENCE = "N/A"


# --- coercion helpers ------------------------------------------------------


def _s(value: Any) -> str:
    """Coerce to a plain string; ``None`` and non-scalars → ``""``."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _i(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _list(value: Any, cap: int) -> List[Any]:
    if not isinstance(value, list):
        return []
    return value[:cap]


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


# --- report projection views ----------------------------------------------


@dataclass(frozen=True)
class WorkflowStepView:
    step: int
    title: str
    description: str
    why_it_matters: str
    expected_output: str
    evidence_code: str

    @property
    def is_insufficient(self) -> bool:
        return self.evidence_code.strip().upper() == INSUFFICIENT_EVIDENCE


@dataclass(frozen=True)
class RiskView:
    severity: str  # normalized to High | Medium | Low | "" (unknown surfaced honestly)
    title: str
    description: str
    business_impact: str
    recommended_fix: str
    owner: str
    evidence_code: str

    @property
    def is_insufficient(self) -> bool:
        return self.evidence_code.strip().upper() == INSUFFICIENT_EVIDENCE


@dataclass(frozen=True)
class CitationView:
    id: str
    source: str
    section: str
    excerpt: str
    why_it_matters: str


@dataclass(frozen=True)
class SuggestedActionView:
    title: str
    detail: str


@dataclass(frozen=True)
class AgentStepView:
    agent: str
    status: str
    detail: str
    duration: str


@dataclass(frozen=True)
class DocumentRelevanceView:
    document: str
    score: int


@dataclass(frozen=True)
class PersonaBriefView:
    title: str
    description: str
    goals: Tuple[str, ...]
    priorities: Tuple[str, ...]
    relevant_topics: Tuple[str, ...]
    risk_focus: Tuple[str, ...]
    output_style: str
    is_custom: bool


@dataclass(frozen=True)
class MetricsView:
    documents_analyzed: int
    passages_indexed: int
    citations_used: int
    risks_flagged: int
    confidence: int
    persona_relevance_score: int
    workflow_completeness: int
    citation_coverage: int
    compliance_sensitivity: str
    document_relevance: Tuple[DocumentRelevanceView, ...]
    present: bool  # False when the report carried no metrics block at all


@dataclass(frozen=True)
class ReportView:
    """Typed projection of the completed ``EvidentiaReport`` JSON."""

    id: str
    company: str
    market: str
    persona: str
    custom_persona: str
    category: str
    generated_at_raw: str
    generated_at: Optional[datetime]
    confidence: int
    summary: str
    top_finding: str
    generation_mode: str
    llm_provider: str
    llm_model: str
    persona_brief: PersonaBriefView
    workflow_steps: Tuple[WorkflowStepView, ...]
    risks: Tuple[RiskView, ...]
    citations: Tuple[CitationView, ...]
    suggested_actions: Tuple[SuggestedActionView, ...]
    agent_steps: Tuple[AgentStepView, ...]
    metrics: MetricsView

    @property
    def is_llm(self) -> bool:
        return self.generation_mode.startswith("llm")

    @property
    def mode_label(self) -> str:
        return {
            "llm-summary": "LLM-refined summary",
            "llm-assisted": "LLM-assisted",
            "deterministic": "Deterministic",
        }.get(self.generation_mode, "Deterministic")


# --- source-audit projection views -----------------------------------------


@dataclass(frozen=True)
class SourceVersionView:
    document_id: str
    document_version_id: str
    version_no: int
    manifest_sha256: str
    finalization_target_digest: str
    position: int


@dataclass(frozen=True)
class EvidenceBindingView:
    document_id: str
    document_version_id: str
    document_title: str
    original_filename: str
    section_ordinal: int
    heading_path: Tuple[str, ...]
    section_title: str
    anchor_id: str
    citation_id: str
    section_signature: str
    retrieval_rank: int
    retrieval_score: float
    selected_for_prompt: bool
    cited_in_final: bool
    excerpt: str


@dataclass(frozen=True)
class SourceAuditView:
    """Typed projection of ``GET /api/reports/{id}/sources`` (report-local M4).

    ``present`` is ``False`` when no audit was supplied at all (e.g. a very old
    demo row), so the renderer can say so honestly instead of inventing sources.
    """

    present: bool
    corpus_mode: str
    corpus_snapshot_digest: str
    retrieval_engine_version: str
    orchestrator_version: str
    execution_mode: str
    llm_provider: str
    llm_model: str
    source_version_count: int
    evidence_section_count: int
    generation_status: str
    source_versions: Tuple[SourceVersionView, ...]
    evidence_bindings: Tuple[EvidenceBindingView, ...]

    def binding_for(self, citation_id: str) -> Optional[EvidenceBindingView]:
        for binding in self.evidence_bindings:
            if binding.citation_id == citation_id:
                return binding
        return None


@dataclass(frozen=True)
class TenantDisplay:
    """Authenticated tenant display info — the *only* input from live context.

    The persisted report's ``company`` field is a pipeline constant, not the real
    organization name, so the cover page uses this membership-derived display
    name instead. It carries no authority (authorization already happened) — it
    is purely what the document should say the report belongs to.
    """

    company_name: str
    company_id: str


@dataclass(frozen=True)
class ReportSnapshot:
    """The complete, immutable renderer input: report + audit + tenant display.

    Built once by :meth:`from_persisted` from persisted data. A renderer receives
    exactly this and nothing else.
    """

    report: ReportView
    audit: SourceAuditView
    tenant: TenantDisplay

    # --- assembly ----------------------------------------------------------

    @classmethod
    def from_persisted(
        cls,
        report_json: Dict[str, Any],
        source_audit: Optional[Dict[str, Any]],
        tenant: TenantDisplay,
    ) -> "ReportSnapshot":
        return cls(
            report=_project_report(_dict(report_json)),
            audit=_project_audit(source_audit),
            tenant=tenant,
        )


# --- projection functions --------------------------------------------------


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 stamp to an aware UTC datetime, else ``None``.

    Used only to pin the document's core-property dates to a *persisted* value;
    never to synthesize a wall-clock time.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_severity(value: Any) -> str:
    text = _s(value).strip()
    lowered = text.lower()
    for canonical in _VALID_SEVERITIES:
        if canonical.lower() == lowered:
            return canonical
    # Common short forms seen in legacy data.
    return {"med": "Medium", "hi": "High"}.get(lowered, text)


def _strings(value: Any, cap: int) -> Tuple[str, ...]:
    return tuple(_s(item) for item in _list(value, cap) if _s(item))


def _project_persona_brief(value: Any) -> PersonaBriefView:
    data = _dict(value)
    return PersonaBriefView(
        title=_s(data.get("title")),
        description=_s(data.get("description")),
        goals=_strings(data.get("goals"), MAX_PRIORITIES),
        priorities=_strings(data.get("priorities"), MAX_PRIORITIES),
        relevant_topics=_strings(data.get("relevantTopics"), MAX_PRIORITIES),
        risk_focus=_strings(data.get("riskFocus"), MAX_PRIORITIES),
        output_style=_s(data.get("outputStyle")),
        is_custom=bool(data.get("isCustom")),
    )


def _project_metrics(value: Any) -> MetricsView:
    present = isinstance(value, dict)
    data = _dict(value)
    relevance = tuple(
        DocumentRelevanceView(document=_s(item.get("document")), score=_i(item.get("score")))
        for item in _list(data.get("documentRelevance"), MAX_DOC_RELEVANCE)
        if isinstance(item, dict)
    )
    sensitivity = _s(data.get("complianceSensitivity"))
    return MetricsView(
        documents_analyzed=_i(data.get("documentsAnalyzed")),
        passages_indexed=_i(data.get("passagesIndexed")),
        citations_used=_i(data.get("citationsUsed")),
        risks_flagged=_i(data.get("risksFlagged")),
        confidence=_i(data.get("confidence")),
        persona_relevance_score=_i(data.get("personaRelevanceScore")),
        workflow_completeness=_i(data.get("workflowCompleteness")),
        citation_coverage=_i(data.get("citationCoverage")),
        compliance_sensitivity=sensitivity,
        document_relevance=relevance,
        present=present,
    )


def _project_report(data: Dict[str, Any]) -> ReportView:
    generated_raw = _s(data.get("generatedAt"))
    workflow = tuple(
        WorkflowStepView(
            step=_i(item.get("step"), default=index + 1),
            title=_s(item.get("title")),
            description=_s(item.get("description")),
            why_it_matters=_s(item.get("whyItMatters")),
            expected_output=_s(item.get("expectedOutput")),
            evidence_code=_s(item.get("evidenceCode")),
        )
        for index, item in enumerate(_list(data.get("workflowSteps"), MAX_WORKFLOW_STEPS))
        if isinstance(item, dict)
    )
    risks = tuple(
        RiskView(
            severity=_normalize_severity(item.get("severity")),
            title=_s(item.get("title")),
            description=_s(item.get("description")),
            business_impact=_s(item.get("businessImpact")),
            recommended_fix=_s(item.get("recommendedFix")),
            owner=_s(item.get("owner")),
            evidence_code=_s(item.get("evidenceCode")),
        )
        for item in _list(data.get("risks"), MAX_RISKS)
        if isinstance(item, dict)
    )
    citations = tuple(
        CitationView(
            id=_s(item.get("id")),
            source=_s(item.get("source")),
            section=_s(item.get("section")),
            excerpt=_s(item.get("excerpt")),
            why_it_matters=_s(item.get("whyItMatters")),
        )
        for item in _list(data.get("citations"), MAX_CITATIONS)
        if isinstance(item, dict)
    )
    actions = tuple(
        SuggestedActionView(title=_s(item.get("title")), detail=_s(item.get("detail")))
        for item in _list(data.get("suggestedActions"), MAX_ACTIONS)
        if isinstance(item, dict)
    )
    agents = tuple(
        AgentStepView(
            agent=_s(item.get("agent")),
            status=_s(item.get("status")),
            detail=_s(item.get("detail")),
            duration=_s(item.get("duration")),
        )
        for item in _list(data.get("agentSteps"), MAX_AGENT_STEPS)
        if isinstance(item, dict)
    )
    return ReportView(
        id=_s(data.get("id")),
        company=_s(data.get("company")),
        market=_s(data.get("market")),
        persona=_s(data.get("persona")),
        custom_persona=_s(data.get("customPersona")),
        category=_s(data.get("category")),
        generated_at_raw=generated_raw,
        generated_at=_parse_iso(generated_raw),
        confidence=_i(data.get("confidence")),
        summary=_s(data.get("summary")),
        top_finding=_s(data.get("topFinding")),
        generation_mode=_s(data.get("generationMode")) or "deterministic",
        llm_provider=_s(data.get("llmProvider")),
        llm_model=_s(data.get("llmModel")),
        persona_brief=_project_persona_brief(data.get("personaBrief")),
        workflow_steps=workflow,
        risks=risks,
        citations=citations,
        suggested_actions=actions,
        agent_steps=agents,
        metrics=_project_metrics(data.get("metrics")),
    )


def _project_audit(source_audit: Optional[Dict[str, Any]]) -> SourceAuditView:
    if not isinstance(source_audit, dict):
        return SourceAuditView(
            present=False,
            corpus_mode="",
            corpus_snapshot_digest="",
            retrieval_engine_version="",
            orchestrator_version="",
            execution_mode="",
            llm_provider="",
            llm_model="",
            source_version_count=0,
            evidence_section_count=0,
            generation_status="",
            source_versions=(),
            evidence_bindings=(),
        )
    versions = tuple(
        SourceVersionView(
            document_id=_s(item.get("documentId")),
            document_version_id=_s(item.get("documentVersionId")),
            version_no=_i(item.get("versionNo")),
            manifest_sha256=_s(item.get("manifestSha256")),
            finalization_target_digest=_s(item.get("finalizationTargetDigest")),
            position=_i(item.get("position")),
        )
        for item in _list(source_audit.get("sourceVersions"), MAX_SOURCE_VERSIONS)
        if isinstance(item, dict)
    )
    bindings = tuple(
        EvidenceBindingView(
            document_id=_s(item.get("documentId")),
            document_version_id=_s(item.get("documentVersionId")),
            document_title=_s(item.get("documentTitle")),
            original_filename=_s(item.get("originalFilename")),
            section_ordinal=_i(item.get("sectionOrdinal")),
            heading_path=_strings(item.get("headingPath"), MAX_HEADING_PATH),
            section_title=_s(item.get("sectionTitle")),
            anchor_id=_s(item.get("anchorId")),
            citation_id=_s(item.get("citationId")),
            section_signature=_s(item.get("sectionSignature")),
            retrieval_rank=_i(item.get("retrievalRank")),
            retrieval_score=_float(item.get("retrievalScore")),
            selected_for_prompt=bool(item.get("selectedForPrompt")),
            cited_in_final=bool(item.get("citedInFinal")),
            excerpt=_s(item.get("excerpt")),
        )
        for item in _list(source_audit.get("evidenceBindings"), MAX_EVIDENCE_BINDINGS)
        if isinstance(item, dict)
    )
    return SourceAuditView(
        present=True,
        corpus_mode=_s(source_audit.get("corpusMode")),
        corpus_snapshot_digest=_s(source_audit.get("corpusSnapshotDigest")),
        retrieval_engine_version=_s(source_audit.get("retrievalEngineVersion")),
        orchestrator_version=_s(source_audit.get("orchestratorVersion")),
        execution_mode=_s(source_audit.get("executionMode")),
        llm_provider=_s(source_audit.get("llmProvider")),
        llm_model=_s(source_audit.get("llmModel")),
        source_version_count=_i(source_audit.get("sourceVersionCount")),
        evidence_section_count=_i(source_audit.get("evidenceSectionCount")),
        generation_status=_s(source_audit.get("generationStatus")),
        source_versions=versions,
        evidence_bindings=bindings,
    )


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
