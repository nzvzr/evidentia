"""Evaluation metrics for Evidentia reports.

Two independent axes so narrative improvements from LLM polish are measured
without weakening grounding checks:

- groundingScore      — schema validity, citation accuracy/coverage, hallucination
                        and injection warnings (unchanged in summary mode).
- narrativeUtilityScore — the fields summary mode actually rewrites: the summary,
                        the persona brief description, and the suggested actions.

overallQualityScore blends the two.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.agents.document_reader import document_reader
from app.tools.text_quality import VAGUE_PHRASES, is_precise_text

# --------------------------------------------------------------------------- #
# shared constants
# --------------------------------------------------------------------------- #

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

# Evidence-code prefixes in the demo corpus (avoids matching e.g. AES-256, TLS-1).
_CODE_RE = re.compile(r"\b(?:SEC|API|SLA|DEP|RES|INC|PRC|ONB)-[A-Z0-9.]+\b")

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "our",
    "before", "after", "across", "within", "their", "them", "then", "than",
    "each", "also", "must", "should", "review", "using", "based",
}

OPERATIONAL_VERBS = {
    "verify", "confirm", "draft", "escalate", "attach", "enable", "define", "replace",
    "map", "design", "document", "review", "open", "export", "schedule", "flag",
    "generate", "validate", "list", "model", "refresh", "set", "prepare", "identify",
    "check", "triage", "route", "resolve", "provision", "add", "publish", "reconcile",
    "assess", "build", "create", "run", "update", "remediate", "mitigate", "audit",
    "align", "complete", "study", "bookmark", "meet", "close", "circulate", "pull",
}

DOMAIN_TERMS = {
    "sla", "residency", "in-region", "incident", "severity", "escalation", "on-call",
    "citation", "evidence", "rollback", "failover", "api", "rate", "limit", "encryption",
    "audit", "compliance", "credit", "egress", "onboarding", "deployment", "topology",
    "gdpr", "phi", "multi-region", "attestation", "controls", "secq", "poc", "playbook",
    "runbook", "pricing", "overage", "entitlement", "remediation", "residency", "backoff",
}

GROUNDING_WEIGHTS = {"schema": 40, "citation_accuracy": 35, "citation_coverage": 25}
GROUNDING_PENALTY_PER = 15.0
GROUNDING_PENALTY_CAP = 40.0

NARRATIVE_WEIGHTS = {
    "factual_consistency": 20,
    "completeness": 25,
    "concision": 10,
    "persona_market_relevance": 15,
    "action_usefulness": 20,
    "action_alignment": 10,
}
NARRATIVE_PENALTY_PER = 7.5
NARRATIVE_PENALTY_CAP = 15.0

OVERALL_GROUNDING_WEIGHT = 0.5
OVERALL_NARRATIVE_WEIGHT = 0.5


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def available_citation_ids(document_ids: List[str]) -> Set[str]:
    _docs, sections = document_reader(document_ids)
    return {s["citationId"] for s in sections}


def _tokens(text: str) -> Set[str]:
    return {t for t in re.findall(r"[a-z0-9-]+", (text or "").lower()) if len(t) > 3 and t not in _STOP}


def _top_risk(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    risks = report.get("risks", [])
    for r in risks:
        if r.get("severity") == "High":
            return r
    return risks[0] if risks else None


def _report_codes(report: Dict[str, Any]) -> Set[str]:
    return {c.get("id") for c in report.get("citations", []) if c.get("id")}


def _action_text(a: Dict[str, Any]) -> Tuple[str, str]:
    title = a.get("title", "") or ""
    detail = a.get("detail") or a.get("description") or ""
    return title, detail


# --------------------------------------------------------------------------- #
# grounding
# --------------------------------------------------------------------------- #

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
    return sum(1 for r in refs if r in available) / len(refs)


def citation_coverage(report: Dict[str, Any], available: Set[str]) -> float:
    if not available:
        return 0.0
    cited = {c.get("id") for c in report.get("citations", [])}
    return min(1.0, len(cited & available) / len(available))


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
        + [f"{t} {d}" for t, d in (_action_text(a) for a in report.get("suggestedActions", []))]
    ).lower()
    if custom_persona:
        text = text.replace(custom_persona.lower(), " ")
    if any(p in text for p in VAGUE_PHRASES):
        warns.append("vague-language")
    for m in INJECTION_MARKERS:
        if m in text:
            warns.append(f"injection-leak:{m}")
    return len(warns), warns[:20]


def grounding_score(schema_ok: bool, citation_acc: float, citation_cov: float, hallucinations: int) -> float:
    score = GROUNDING_WEIGHTS["schema"] * (1.0 if schema_ok else 0.0)
    score += GROUNDING_WEIGHTS["citation_accuracy"] * citation_acc
    score += GROUNDING_WEIGHTS["citation_coverage"] * citation_cov
    score -= min(GROUNDING_PENALTY_CAP, hallucinations * GROUNDING_PENALTY_PER)
    return round(max(0.0, min(100.0, score)), 1)


# --------------------------------------------------------------------------- #
# narrative
# --------------------------------------------------------------------------- #

def summary_factual_consistency(report: Dict[str, Any], available: Set[str], expected: Optional[Dict] = None) -> float:
    summary = report.get("summary", "") or ""
    low = summary.lower()
    metrics = report.get("metrics", {})
    nd, nr, nc = metrics.get("documentsAnalyzed"), metrics.get("risksFlagged"), metrics.get("citationsUsed")

    expected = expected or {}
    for phrase in expected.get("forbiddenClaims", []):
        if phrase.lower() in low:
            return 0.0

    checks: List[bool] = []
    for pattern, actual in (
        (r"(\d+)\s+documents?", nd),
        (r"(\d+)\s+risks?", nr),
        (r"(\d+)\s+(?:grounded\s+)?citations?", nc),
    ):
        for m in re.findall(pattern, low):
            checks.append(int(m) == actual)

    report_codes = _report_codes(report) | available
    for code in _CODE_RE.findall(summary):
        checks.append(code in report_codes)

    if not checks:
        return 1.0
    return sum(1 for c in checks if c) / len(checks)


def summary_completeness(report: Dict[str, Any], expected: Optional[Dict] = None) -> float:
    summary = (report.get("summary", "") or "").lower()
    metrics = report.get("metrics", {})
    persona = report.get("persona", "") or ""
    market = report.get("market", "") or ""
    expected = expected or {}

    checks: List[bool] = []
    # persona mentioned
    checks.append(any(t in summary for t in _tokens(persona)) if _tokens(persona) else False)
    # market mentioned
    checks.append(any(t in summary for t in _tokens(market)) if _tokens(market) else False)
    # actual counts
    checks.append(str(metrics.get("documentsAnalyzed")) in summary)
    checks.append(str(metrics.get("risksFlagged")) in summary)
    checks.append(str(metrics.get("citationsUsed")) in summary)
    # highest-severity risk concept
    top = _top_risk(report)
    concept_tokens = _tokens(top["title"]) if top else set()
    concept_tokens |= {c.lower() for c in expected.get("summaryConcepts", [])}
    checks.append(any(t in summary for t in concept_tokens) if concept_tokens else False)
    # its evidence code
    checks.append(bool(top) and top.get("evidenceCode", "") in report.get("summary", ""))
    # >=2 of top-3 workflow steps
    steps = report.get("workflowSteps", [])[:3]
    hit = sum(1 for s in steps if any(t in summary for t in _tokens(s.get("title", ""))))
    checks.append(hit >= 2)

    return sum(1 for c in checks if c) / len(checks)


def concision(report: Dict[str, Any]) -> float:
    summary = report.get("summary", "") or ""
    length = len(summary)
    sentences = [s for s in re.split(r"[.!?]+", summary) if s.strip()]
    n = len(sentences)
    if n == 0:
        return 0.2
    if n <= 4:
        score = 1.0
    elif n == 5:
        score = 0.6
    else:
        score = 0.3
    if length > 600:
        score = min(score, 0.6)
    if length < 40:
        score = min(score, 0.5)
    return score


def persona_market_relevance(report: Dict[str, Any]) -> float:
    persona = report.get("persona", "") or ""
    market = report.get("market", "") or ""
    brief = report.get("personaBrief", {}) or {}
    text = " ".join(
        [report.get("summary", ""), brief.get("description", "")]
        + [f"{t} {d}" for t, d in (_action_text(a) for a in report.get("suggestedActions", []))]
    ).lower()
    priorities = " ".join(brief.get("priorities", []) + brief.get("relevantTopics", []))

    checks = [
        any(t in text for t in _tokens(persona)) if _tokens(persona) else False,
        any(t in text for t in _tokens(market)) if _tokens(market) else False,
        any(t in text for t in _tokens(priorities)) if _tokens(priorities) else True,
    ]
    return sum(1 for c in checks if c) / len(checks)


def action_usefulness(report: Dict[str, Any]) -> float:
    actions = report.get("suggestedActions", [])
    if not actions:
        return 0.0
    total = 0.0
    for a in actions:
        title, detail = _action_text(a)
        if not title.strip():
            continue
        first = title.strip().split()[0].lower().strip(":,")
        verb_ok = first in OPERATIONAL_VERBS
        precise_ok = is_precise_text(title, max_len=120) and (not detail or is_precise_text(detail, max_len=400))
        blob = f"{title} {detail}".lower()
        concrete_ok = any(term in blob for term in DOMAIN_TERMS) or bool(_CODE_RE.search(f"{title} {detail}"))
        total += (int(verb_ok) + int(precise_ok) + int(concrete_ok)) / 3
    return total / len(actions)


def action_alignment(report: Dict[str, Any], expected: Optional[Dict] = None) -> float:
    actions = report.get("suggestedActions", [])
    if not actions:
        return 0.0
    expected = expected or {}
    ref_tokens: Set[str] = set()
    for r in report.get("risks", []):
        ref_tokens |= _tokens(r.get("title", ""))
    for w in report.get("workflowSteps", []):
        ref_tokens |= _tokens(w.get("title", ""))
    ref_tokens |= {c.lower() for c in expected.get("actionConcepts", [])}
    codes = _report_codes(report)

    aligned = 0
    for a in actions:
        title, detail = _action_text(a)
        blob = f"{title} {detail}"
        if _CODE_RE.search(blob) and any(code in blob for code in codes):
            aligned += 1
            continue
        if _tokens(blob) & ref_tokens:
            aligned += 1
    return aligned / len(actions)


def narrative_penalties(report: Dict[str, Any], custom_persona: str = "") -> Tuple[int, List[str]]:
    warns: List[str] = []
    summary = report.get("summary", "") or ""
    text = " ".join(
        [summary] + [f"{t} {d}" for t, d in (_action_text(a) for a in report.get("suggestedActions", []))]
    ).lower()
    if custom_persona:
        text = text.replace(custom_persona.lower(), " ")
    if any(p in text for p in VAGUE_PHRASES):
        warns.append("vague-language")
    # repetitive sentence openings
    sentences = [s.strip() for s in re.split(r"[.!?]+", summary) if s.strip()]
    if len(sentences) >= 3:
        starts = [" ".join(s.split()[:3]).lower() for s in sentences]
        if max((starts.count(s) for s in set(starts)), default=0) > len(sentences) / 2:
            warns.append("repetitive")
    return len(warns), warns


def narrative_utility_score(components: Dict[str, Any]) -> float:
    score = 0.0
    for key, weight in NARRATIVE_WEIGHTS.items():
        score += weight * components[key]
    score -= min(NARRATIVE_PENALTY_CAP, components["penalties"] * NARRATIVE_PENALTY_PER)
    return round(max(0.0, min(100.0, score)), 1)


def overall_quality_score(grounding: float, narrative: float) -> float:
    return round(OVERALL_GROUNDING_WEIGHT * grounding + OVERALL_NARRATIVE_WEIGHT * narrative, 1)


# --------------------------------------------------------------------------- #
# top-level
# --------------------------------------------------------------------------- #

def evaluate_report(
    report: Dict[str, Any],
    document_ids: List[str],
    expected: Optional[Dict] = None,
    custom_persona: str = "",
) -> Dict[str, Any]:
    available = available_citation_ids(document_ids)

    schema_ok, schema_issues = validate_schema(report)
    ca = citation_accuracy(report, available)
    cc = citation_coverage(report, available)
    hcount, hwarn = hallucination_warnings(report, available, custom_persona)
    grounding = grounding_score(schema_ok, ca, cc, hcount)

    fc = summary_factual_consistency(report, available, expected)
    comp = summary_completeness(report, expected)
    con = concision(report)
    pmr = persona_market_relevance(report)
    au = action_usefulness(report)
    aa = action_alignment(report, expected)
    npen, nwarns = narrative_penalties(report, custom_persona)
    narrative = narrative_utility_score({
        "factual_consistency": fc,
        "completeness": comp,
        "concision": con,
        "persona_market_relevance": pmr,
        "action_usefulness": au,
        "action_alignment": aa,
        "penalties": npen,
    })

    overall = overall_quality_score(grounding, narrative)

    return {
        # scores
        "groundingScore": grounding,
        "narrativeUtilityScore": narrative,
        "overallQualityScore": overall,
        "qualityScore": overall,  # backward-compatible alias
        # grounding detail
        "schemaValid": schema_ok,
        "schemaIssues": schema_issues,
        "citationAccuracy": round(ca, 3),
        "citationCoverage": round(cc, 3),
        "hallucinationWarnings": hcount,
        "hallucinationDetail": hwarn,
        # narrative detail
        "factualConsistency": round(fc, 3),
        "summaryCompleteness": round(comp, 3),
        "concision": round(con, 3),
        "personaMarketRelevance": round(pmr, 3),
        "actionUsefulness": round(au, 3),
        "actionAlignment": round(aa, 3),
        "narrativeWarnings": nwarns,
    }
