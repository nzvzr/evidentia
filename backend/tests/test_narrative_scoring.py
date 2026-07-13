"""Narrative-utility scoring proofs.

Shows the calibration framework measures the fields summary mode rewrites
(summary, persona brief, suggested actions) independently of grounding.
"""

from app.eval import metrics

DOCS = ["incident-response-runbook", "sla-uptime-commitment"]

_GOOD_SUMMARY = (
    "For Support Agent in EMEA, Evidentia analyzed 2 documents and found 3 risks across 4 "
    "grounded citations. The highest-severity issue is Incident runbook references a deprecated "
    "on-call tool, supported by INC-2.1. The recommended workflow prioritizes Triage against the "
    "severity matrix, Confirm SLA entitlements, and Pull verified remediation steps. Resolve "
    "residency and SLA issues before customer or audit review."
)

_VAGUE_SUMMARY = (
    "This report provides critical insights and actionable recommendations to enhance operational "
    "readiness and drive business value across the organization while we optimize processes."
)

_CONCRETE_ACTIONS = [
    {"title": "Verify SLA entitlement before promising remediation",
     "detail": "Confirm the customer region and tier per SLA-3.", "priority": "High"},
    {"title": "Escalate Severity 1 via the current on-call system",
     "detail": "Do not use the deprecated tool referenced in INC-2.1.", "priority": "High"},
    {"title": "Attach citation INC-2.1 to the incident ticket",
     "detail": "Link the escalation clause to the customer reply.", "priority": "Medium"},
]

_GENERIC_ACTIONS = [
    {"title": "Leverage documentation", "detail": "drive business value"},
    {"title": "Optimize processes", "detail": "enhance operational readiness"},
    {"title": "Unlock synergy", "detail": "holistic approach"},
]


def make_report(summary=_GOOD_SUMMARY, actions=None, description="Resolve incidents fast with cited answers.", **over):
    report = {
        "id": "x", "company": "Northreach Cloud", "market": "EMEA", "persona": "Support Agent",
        "generatedAt": "2026-07-12T00:00:00Z", "confidence": 89, "summary": summary,
        "topFinding": "The main blocker for Support Agent in EMEA is the deprecated on-call tool, supported by INC-2.1.",
        "agentSteps": [{"agent": "Document Ingest", "status": "complete", "detail": "d", "duration": "0.6s"}],
        "personaBrief": {
            "title": "Support Agent", "description": description,
            "goals": ["Resolve tickets fast"], "priorities": ["Time to resolution", "SLA accuracy"],
            "relevantTopics": ["Severity matrix", "SLA entitlements"], "riskFocus": ["Deprecated tooling"],
            "outputStyle": "concise", "isCustom": False,
        },
        "workflowSteps": [
            {"step": 1, "title": "Triage against the severity matrix", "description": "d", "whyItMatters": "w", "expectedOutput": "o", "evidenceCode": "INC-2.1"},
            {"step": 2, "title": "Confirm SLA entitlements", "description": "d", "whyItMatters": "w", "expectedOutput": "o", "evidenceCode": "SLA-3"},
            {"step": 3, "title": "Pull verified remediation steps", "description": "d", "whyItMatters": "w", "expectedOutput": "o", "evidenceCode": "INC-2.1"},
            {"step": 4, "title": "Escalate P1/P2 correctly", "description": "d", "whyItMatters": "w", "expectedOutput": "o", "evidenceCode": "INC-2.1"},
        ],
        "risks": [
            {"severity": "High", "title": "Incident runbook references a deprecated on-call tool", "description": "d",
             "businessImpact": "b", "evidenceCode": "INC-2.1", "recommendedFix": "f", "owner": "SRE On-call"},
            {"severity": "Medium", "title": "SLA credit terms undefined for multi-region outages", "description": "d",
             "businessImpact": "b", "evidenceCode": "SLA-3", "recommendedFix": "f", "owner": "Legal"},
            {"severity": "Low", "title": "Pricing sheet omits egress overage tiers", "description": "d",
             "businessImpact": "b", "evidenceCode": "INC-2.1", "recommendedFix": "f", "owner": "RevOps"},
        ],
        "citations": [
            {"id": "INC-2.1", "source": "Incident Response Runbook · Severity", "section": "Severity", "excerpt": "e", "whyItMatters": "w"},
            {"id": "SLA-3", "source": "SLA & Uptime Commitment · Availability", "section": "Availability", "excerpt": "e", "whyItMatters": "w"},
        ],
        "metrics": {
            "documentsAnalyzed": 2, "passagesIndexed": 82, "citationsUsed": 4, "risksFlagged": 3,
            "confidence": 89, "personaRelevanceScore": 88, "workflowCompleteness": 100,
            "citationCoverage": 82, "complianceSensitivity": "High", "documentRelevance": [],
        },
        "suggestedActions": actions if actions is not None else _CONCRETE_ACTIONS,
        "generationMode": "llm-summary",
    }
    report.update(over)
    return report


def _narrative(report):
    return metrics.evaluate_report(report, DOCS, {}, "")["narrativeUtilityScore"]


# 1. precise, factual summary beats a vague one
def test_precise_summary_beats_vague():
    good = _narrative(make_report(summary=_GOOD_SUMMARY))
    vague = _narrative(make_report(summary=_VAGUE_SUMMARY))
    assert good > vague


# 2a. wrong counts reduce the score
def test_wrong_counts_reduce_score():
    good = _narrative(make_report(summary=_GOOD_SUMMARY))
    wrong = make_report(summary=_GOOD_SUMMARY.replace("3 risks across 4", "9 risks across 12"))
    assert metrics.summary_factual_consistency(wrong, metrics.available_citation_ids(DOCS)) < 1.0
    assert _narrative(wrong) < good


# 2b. invented evidence reduces grounding
def test_invented_evidence_reduces_grounding():
    baseline = metrics.evaluate_report(make_report(), DOCS, {}, "")["groundingScore"]
    bad = make_report()
    bad["risks"][0]["evidenceCode"] = "FAKE-9"
    bad["citations"].append({"id": "FAKE-9", "source": "s", "section": "x", "excerpt": "e", "whyItMatters": "w"})
    lowered = metrics.evaluate_report(bad, DOCS, {}, "")["groundingScore"]
    assert lowered < baseline


# 3. concrete useful actions beat generic imperative titles
def test_concrete_actions_beat_generic():
    concrete = metrics.action_usefulness(make_report(actions=_CONCRETE_ACTIONS))
    generic = metrics.action_usefulness(make_report(actions=_GENERIC_ACTIONS))
    assert concrete > generic


def test_generic_actions_lower_narrative_score():
    concrete = _narrative(make_report(actions=_CONCRETE_ACTIONS))
    generic = _narrative(make_report(actions=_GENERIC_ACTIONS))
    assert concrete > generic


# 4. summary-mode-style and deterministic-style reports can differ in narrative score
def test_llm_and_deterministic_narrative_can_differ():
    # deterministic-style: correct summary but generic static actions and plain description
    deterministic = make_report(
        summary=_GOOD_SUMMARY, actions=_GENERIC_ACTIONS, description="Support Agent brief.",
        generationMode="deterministic",
    )
    # llm-style: concise grounded summary + concrete aligned actions + sharper description
    llm = make_report(
        summary=_GOOD_SUMMARY, actions=_CONCRETE_ACTIONS,
        description="Support Agent resolving incidents with SLA-3 entitlements and INC-2.1 escalation.",
        generationMode="llm-summary",
    )
    assert _narrative(llm) != _narrative(deterministic)
    assert _narrative(llm) > _narrative(deterministic)


# completeness: a summary missing counts/evidence scores lower
def test_completeness_rewards_full_summary():
    full = metrics.summary_completeness(make_report(summary=_GOOD_SUMMARY))
    sparse = metrics.summary_completeness(make_report(summary="A short note about support."))
    assert full > sparse
    assert full >= 0.85
