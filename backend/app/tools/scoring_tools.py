"""Deterministic scoring tools for report metrics."""

from __future__ import annotations

from typing import Any, Dict, List

HIGH_COMPLIANCE_MARKETS = {
    "Public Sector (GovCloud)",
    "Financial Services",
    "Healthcare",
}


def _clamp(v: float, lo: float, hi: float) -> int:
    return int(max(lo, min(hi, v)))


def compute_confidence(documents_count: int) -> int:
    coverage_ratio = documents_count / 8
    return _clamp(round(82 + coverage_ratio * 14), 82, 96)


def compute_persona_relevance(documents_count: int) -> int:
    return _clamp(76 + documents_count * 2 + 4, 70, 95)


def compute_workflow_completeness(step_count: int) -> int:
    return _clamp(80 + step_count * 4, 80, 100)


def compute_citation_coverage(documents_count: int) -> int:
    return _clamp(70 + documents_count * 3, 70, 95)


def compute_compliance_sensitivity(market: str, persona_key: str) -> str:
    if market in HIGH_COMPLIANCE_MARKETS or market == "EMEA":
        return "High"
    if persona_key == "compliance":
        return "High"
    return "Moderate"


def compute_document_relevance(documents: List[Dict[str, Any]], persona_title: str) -> List[Dict[str, Any]]:
    rows = []
    for i, d in enumerate(documents):
        match = persona_title in d.get("usedByPersonas", [])
        score = _clamp(72 + (20 if match else 6) - i * 2, 60, 98)
        rows.append({"document": d["short"], "score": score})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:6]
