"""Metrics agent — deterministic, input-driven report metrics."""

from __future__ import annotations

from typing import Any, Dict, List

from app.tools.scoring_tools import (
    compute_citation_coverage,
    compute_compliance_sensitivity,
    compute_confidence,
    compute_document_relevance,
    compute_persona_relevance,
    compute_workflow_completeness,
)


def metrics_agent(
    documents: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    risks: List[Dict[str, Any]],
    workflow_steps: List[Dict[str, Any]],
    market: str,
    persona_key: str,
    persona_title: str,
) -> Dict[str, Any]:
    documents_analyzed = len(documents)
    return {
        "documentsAnalyzed": documents_analyzed,
        "passagesIndexed": len(sections) * 41,
        "citationsUsed": len(citations),
        "risksFlagged": len(risks),
        "confidence": compute_confidence(documents_analyzed),
        "personaRelevanceScore": compute_persona_relevance(documents_analyzed),
        "workflowCompleteness": compute_workflow_completeness(len(workflow_steps)),
        "citationCoverage": compute_citation_coverage(documents_analyzed),
        "complianceSensitivity": compute_compliance_sensitivity(market, persona_key),
        "documentRelevance": compute_document_relevance(documents, persona_title),
    }
