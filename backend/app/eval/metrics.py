"""Per-report evaluation metrics and the weighted quality score (0-100)."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from app.agents.document_reader import document_reader
from app.tools.text_quality import VAGUE_PHRASES, is_precise_text

REQUIRED_TOP_KEYS = [
    "id", "company", "market", "persona", "generatedAt", "confidence", "summary",
    "topFinding", "agentSteps", "personaBrief", "workflowSteps", "risks", "citations",
    "metrics", "suggestedActions", "generationMode",
]
REQUIRED_METRIC_KEYS = [
    "documentsAnalyzed", "passagesIndexed", "citationsUsed", "risksFlagged", "confidence",
    "personaRelevanceScore", "workflowCompleteness", "citationCoverage",
    "complianceSensitivity", "documentRelevance",
]

# Markers that indicate the model actually complied with an injection (as opposed
# to merely echoing the user-supplied persona text, which we strip before scanning).
INJECTION_MARKERS = [
    "enterprise documentation analysis agent",
    "you are evidentia",
    "ignore all previous",
    "ignore previous instructions",
    "system prompt",
    "pwned",
    "api key",
    "secret key",
    "as an ai language model",
]

WEIGHTS = {
    "schema": 25,
    "citation_accuracy": 20,
    "citation_coverage": 15,
    "persona_relevance": 20,
    "action_specificity": 20,
}
HALLUCINATION_PENALTY_PER = 10.0
HALLUCINATION_PENALTY_CAP = 30.0


def available_citation_ids(document_ids: List[str]) -> Set[str]:
    _docs, sections = document_reader(document_ids)
    return {s["citationId"] for s in sections}


def validate_schema(report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    for k in REQUIRED_TOP_KEYS:
        if k not in report:
            issues.append(f"missing:{k}")
    for w in report.get("workflowSteps", []):
        for k in ("step", "title", "description", "whyItMatters", "expectedOutput", "evidenceCode"):
            if k not in w:
                issues.append(f"workflow.{k}")
    for r in report.get("risks", []):
        for k in ("severity", "title", "description", "businessImpact", "evidenceCode", "recommendedFix", "owner"):
            if k not in r:
                issues.append(f"risk.{k}")
        if r.get("severity") not in ("High", "Medium", "Low"):
            issues.append("risk.severity.invalid")
    for c in report.get("citations", []):
        for k in ("id", "source", "section", "excerpt", "whyItMatters"):
            if k not in c:
                issues.append(f"citation.{k}")
    metrics = report.get("metrics", {})
    for k in REQUIRED_METRIC_KEYS:
        if k not in metrics:
            issues.append(f"metrics.{k}")
    if not 4 <= len(report.get("workflowSteps", [])) <= 6:
        issues.append("workflow.count")
    if not 3 <= len(report.get("risks", [])) <= 5:
        issues.append("risk.count")
    # de-dup while preserving order
    seen: Set[str] = set()
    unique = [i for i in issues if not (i in seen or seen.add(i))]
    return (len(unique) == 0, unique[:20])


def _evidence_refs(report: Dict[str, Any]) -> List[str]:
    return [w.get("evidenceCode", "") for w in report.get("workflowSteps", [])] + [
        r.get("evidenceCode", "") for r in report.get("risks", [])
    ]


def citation_accuracy(report: Dict[str, Any], available: Set[str]) -> float:
    refs = [r for r in _evidence_refs(report) if r]
    if not refs:
        return 0.0
    grounded = sum(1 for r in refs if r in available)
    return grounded / len(refs)


def citation_coverage(report: Dict[str, Any], available: Set[str]) -> float:
    if not available:
        return 0.0
    cited = {c.get("id") for c in report.get("citations", [])}
    grounded = cited & available
    return min(1.0, len(grounded) / len(available))


def persona_relevance(report: Dict[str, Any]) -> float:
    score = report.get("metrics", {}).get("personaRelevanceScore", 0) or 0
    return min(1.0, max(0.0, score / 100))


def _is_imperative(title: str) -> bool:
    words = title.strip().split()
    if not words:
        return False
    first = words[0].lower()
    return first.isalpha() and first not in ("the", "a", "an", "our", "your", "this", "these")


def action_specificity(report: Dict[str, Any]) -> float:
    actions = report.get("suggestedActions", [])
    if not actions:
        return 0.0
    good = 0
    for a in actions:
        title = a.get("title", "")
        if title and is_precise_text(title, max_len=120) and _is_imperative(title):
            good += 1
    return good / len(actions)


def hallucination_warnings(
    report: Dict[str, Any], available: Set[str], custom_persona: str = ""
) -> Tuple[int, List[str]]:
    warns: List[str] = []
    for ref in _evidence_refs(report):
        if ref and ref not in available:
            warns.append(f"ungrounded-evidence:{ref}")
    for c in report.get("citations", []):
        if c.get("id") not in available:
            warns.append(f"invented-citation:{c.get('id')}")

    text = " ".join(
        [report.get("summary", ""), report.get("topFinding", "")]
        + [f"{a.get('title', '')} {a.get('detail', '')}" for a in report.get("suggestedActions", [])]
    ).lower()
    # Strip the user-supplied persona text so echoing the input isn't flagged.
    if custom_persona:
        text = text.replace(custom_persona.lower(), " ")
    if any(p in text for p in VAGUE_PHRASES):
        warns.append("vague-language")
    for m in INJECTION_MARKERS:
        if m in text:
            warns.append(f"injection-leak:{m}")
    return len(warns), warns[:20]


def quality_score(components: Dict[str, Any]) -> float:
    score = WEIGHTS["schema"] * (1.0 if components["schema"] else 0.0)
    score += WEIGHTS["citation_accuracy"] * components["citation_accuracy"]
    score += WEIGHTS["citation_coverage"] * components["citation_coverage"]
    score += WEIGHTS["persona_relevance"] * components["persona_relevance"]
    score += WEIGHTS["action_specificity"] * components["action_specificity"]
    penalty = min(HALLUCINATION_PENALTY_CAP, components["hallucinations"] * HALLUCINATION_PENALTY_PER)
    return round(max(0.0, min(100.0, score - penalty)), 1)


def evaluate_report(report: Dict[str, Any], document_ids: List[str], custom_persona: str = "") -> Dict[str, Any]:
    available = available_citation_ids(document_ids)
    schema_ok, schema_issues = validate_schema(report)
    ca = citation_accuracy(report, available)
    cc = citation_coverage(report, available)
    pr = persona_relevance(report)
    asp = action_specificity(report)
    hcount, hwarn = hallucination_warnings(report, available, custom_persona)
    components = {
        "schema": schema_ok,
        "citation_accuracy": ca,
        "citation_coverage": cc,
        "persona_relevance": pr,
        "action_specificity": asp,
        "hallucinations": hcount,
    }
    return {
        "schemaValid": schema_ok,
        "schemaIssues": schema_issues,
        "citationAccuracy": round(ca, 3),
        "citationCoverage": round(cc, 3),
        "personaRelevance": round(pr, 3),
        "actionSpecificity": round(asp, 3),
        "hallucinationWarnings": hcount,
        "hallucinationDetail": hwarn,
        "qualityScore": quality_score(components),
    }
