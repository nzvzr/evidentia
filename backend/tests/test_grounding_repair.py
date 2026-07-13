"""Tests for the deterministic citation grounding repair + relevance scorer."""

from app.tools.citation_tools import (
    INSUFFICIENT_EVIDENCE,
    count_ungrounded,
    repair_grounding,
)

# Synthetic corpus with clear domain content per section for controlled scoring.
SECTIONS = [
    {"documentId": "d", "source": "Data Residency Policy", "sectionTitle": "EMEA Processing",
     "excerpt": "Default control-plane metadata is processed in us-east-1 unless in-region processing is provisioned.",
     "category": "Compliance", "citationId": "RES-14"},
    {"documentId": "d", "source": "Incident Runbook", "sectionTitle": "Deprecated Tool Notice",
     "excerpt": "PagerTree references are deprecated and must be replaced with the current on-call routing system.",
     "category": "Operations", "citationId": "INC-9"},
    {"documentId": "d", "source": "Pricing Sheet", "sectionTitle": "Overage",
     "excerpt": "Egress overage tiers require finance approval and must be documented in the order.",
     "category": "Pricing", "citationId": "PRC-3"},
    {"documentId": "d", "source": "Onboarding", "sectionTitle": "Kickoff",
     "excerpt": "Customer kickoff confirms success criteria, stakeholders, and target launch date.",
     "category": "Enablement", "citationId": "ONB-1"},
]
AVAILABLE = {s["citationId"] for s in SECTIONS}


def _risk(title, code="FAKE-0", description="", business_impact=""):
    return {"severity": "Medium", "title": title, "description": description,
            "businessImpact": business_impact, "evidenceCode": code,
            "recommendedFix": "", "owner": "o"}


def test_single_generic_shared_term_is_insufficient():
    risks = [_risk("Review customer records")]  # only the generic 'customer' overlaps ONB
    info = repair_grounding([], risks, SECTIONS)
    assert risks[0]["evidenceCode"] == INSUFFICIENT_EVIDENCE
    assert info["audit"][0]["repairDecision"] == "insufficient-evidence"


def test_two_domain_terms_pass_without_phrase():
    risks = [_risk("Replace deprecated routing references")]
    info = repair_grounding([], risks, SECTIONS)
    assert risks[0]["evidenceCode"] == "INC-9"
    rec = info["audit"][0]
    assert rec["repairDecision"] == "replaced"
    assert rec["matchedPhrases"] == []          # accepted on >=2 meaningful terms, not a phrase
    assert len(rec["matchedTerms"]) >= 2


def test_exact_phrase_is_strongly_rewarded():
    risks = [_risk("Handle the deprecated tool notice")]  # matches INC-9 section title verbatim
    info = repair_grounding([], risks, SECTIONS)
    assert risks[0]["evidenceCode"] == "INC-9"
    assert "deprecated tool notice" in info["audit"][0]["matchedPhrases"]


def test_unrelated_valid_citation_rejected_as_insufficient():
    risks = [_risk("Quarterly synergy alignment offsite")]
    info = repair_grounding([], risks, SECTIONS)
    assert risks[0]["evidenceCode"] == INSUFFICIENT_EVIDENCE


def test_relevant_selected_over_superficial():
    # 'customer' superficially matches ONB (generic); egress/overage/finance match PRC strongly.
    risks = [_risk("Confirm customer egress overage finance approval")]
    info = repair_grounding([], risks, SECTIONS)
    assert risks[0]["evidenceCode"] == "PRC-3"
    top = info["audit"][0]["candidateCitationScores"][0]
    assert top["citationId"] == "PRC-3"


def test_valid_codes_unchanged():
    workflow = [{"step": 1, "title": "Confirm severity", "description": "d", "evidenceCode": "INC-9"}]
    info = repair_grounding(workflow, [], SECTIONS)
    assert workflow[0]["evidenceCode"] == "INC-9"
    assert info["repairs"] == 0
    assert info["audit"] == []


def test_audit_record_has_required_fields():
    risks = [_risk("Replace deprecated routing references")]
    rec = repair_grounding([], risks, SECTIONS)["audit"][0]
    for key in ("itemType", "itemTitle", "originalEvidenceCode", "replacementEvidenceCode",
                "relevanceScore", "matchedTerms", "matchedPhrases", "repairDecision",
                "candidateCitationScores"):
        assert key in rec
    assert rec["itemType"] == "risk"
    assert len(rec["candidateCitationScores"]) <= 3


def test_count_ungrounded_ignores_sentinel_and_empty():
    assert count_ungrounded(["INC-9", INSUFFICIENT_EVIDENCE, "", "FAKE-1"], AVAILABLE) == 1


def test_before_after_counts():
    risks = [_risk("Replace deprecated routing references", code="RES-99"),  # invalid -> repaired
             _risk("Quarterly synergy alignment offsite", code="ZZZ-1")]     # invalid -> insufficient
    info = repair_grounding([], risks, SECTIONS)
    assert info["before"] == 2
    assert info["after"] == 0  # one replaced (valid), one sentinel (not counted)
    assert info["repairs"] == 1
