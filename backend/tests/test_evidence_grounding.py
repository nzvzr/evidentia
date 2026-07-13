"""Tests for source-constrained (evidence-first) risk and workflow generation."""

from app.agents.document_reader import document_reader
from app.agents.persona_mapper import resolve_persona_key
from app.agents.risk_analyzer import risk_analyzer
from app.agents.workflow_builder import workflow_builder
from app.tools.citation_tools import INSUFFICIENT_EVIDENCE
from app.tools.evidence_support import best_supporting_section, score_support

RES = "data-residency-sovereignty-policy"
SEC = "security-compliance-whitepaper"
SLA = "sla-uptime-commitment"
INC = "incident-response-runbook"
PRC = "pricing-packaging-sheet"


def _sections(*doc_ids):
    return document_reader(list(doc_ids))[1]


def _titles(risks):
    return [r["title"] for r in risks]


# 1) A risk whose source document is not selected is never emitted as grounded.
def test_risk_from_unselected_document_not_grounded():
    sections = _sections(PRC)  # residency doc absent
    risks, gen = risk_analyzer("sales", "EMEA", sections)
    assert not any("residency" in r["title"].lower() and r["evidenceCode"] != INSUFFICIENT_EVIDENCE
                   for r in risks)
    assert gen["sourceDocumentMismatch"] >= 1
    # any residency proposal is audited as source-document-not-selected, never grounded
    assert any(a["proposedRiskOrStep"] == "residency" and a["finalDecision"] == "dropped"
               for a in gen["audit"])


# 2) A generic persona risk with no documentary support is rejected.
def test_generic_persona_risk_without_support_rejected():
    # SLA doc present but its section text stripped of SLA signals.
    sections = _sections(SLA)
    for s in sections:
        s["sectionTitle"] = "Overview"
        s["excerpt"] = "General platform information for the reader."
    risks, gen = risk_analyzer("ops", "North America", sections)
    assert not any("sla" in r["title"].lower() and r["evidenceCode"] != INSUFFICIENT_EVIDENCE
                   for r in risks)
    assert any(a["rejectionReason"] == "insufficient-signal-support" for a in gen["audit"])


# 3) A supported risk keeps the correct document and citation provenance.
def test_supported_risk_keeps_provenance():
    sections = _sections(RES, SEC, SLA)
    risks, gen = risk_analyzer("compliance", "Healthcare", sections)
    res = next(r for r in risks if "residency" in r["title"].lower())
    assert res["evidenceCode"].startswith("RES-")
    prov = next(p for p in gen["provenance"] if p["sourceCitationId"] == res["evidenceCode"])
    assert prov["sourceDocumentId"] == RES
    assert prov["generationReason"] == "evidence-derived"
    assert prov["matchedSignals"]  # non-empty evidence of the claim


# 4) A superficially related section does not support an unrelated claim.
def test_superficial_section_does_not_support_claim():
    residency_claim = {
        "sourceDocId": RES, "category": "Compliance",
        "signals": ["residency", "us-east-1", "in-region", "metadata", "sovereign"],
        "phrases": ["in-region processing"], "personas": ["compliance"], "marketSensitive": True,
        "resolvedIf": [],
    }
    superficial = {"documentId": RES, "category": "Compliance", "citationId": "RES-99",
                   "sectionTitle": "Overview", "excerpt": "This policy applies to all customers."}
    det = score_support(residency_claim, superficial, "compliance", "EMEA")
    assert det["strength"] < 2  # not enough claim-specific signal to ground


# 5) Fewer than 3 supported risks do not cause filler risks to be invented.
def test_no_filler_risks_to_hit_a_count():
    sections = _sections(INC)  # only incident doc supports one risk
    risks, gen = risk_analyzer("ops", "North America", sections)
    grounded = [r for r in risks if r["evidenceCode"] != INSUFFICIENT_EVIDENCE]
    # every grounded risk's code resolves to a real selected section
    available = {s["citationId"] for s in sections}
    assert all(r["evidenceCode"] in available for r in grounded)
    # no pricing/api/residency filler appears without its source doc
    assert not any(r["title"].lower().startswith(("pricing", "api", "data residency"))
                   for r in grounded)
    assert gen["groundedKept"] == len(grounded)


# 6) An evidence-gap risk appears only when the missing docs are operationally relevant.
def test_evidence_gap_only_when_relevant():
    # Compliance persona, no Compliance/Security docs and <2 grounded -> gap emitted.
    gap_sections = _sections(PRC)
    risks_gap, gen_gap = risk_analyzer("compliance", "EMEA", gap_sections)
    assert gen_gap["insufficientEmitted"] == 1
    assert any(r["evidenceCode"] == INSUFFICIENT_EVIDENCE for r in risks_gap)

    # Compliance persona WITH the critical docs and >=2 grounded -> no gap.
    ok_sections = _sections(RES, SEC, SLA)
    risks_ok, gen_ok = risk_analyzer("compliance", "Healthcare", ok_sections)
    assert gen_ok["insufficientEmitted"] == 0
    assert all(r["evidenceCode"] != INSUFFICIENT_EVIDENCE for r in risks_ok)


# 7) Valid existing scenarios preserve their expected risks (grounded to the right docs).
def test_valid_scenario_preserves_expected_risks():
    sections = _sections(RES, SEC, SLA)
    risks, _ = risk_analyzer("compliance", "Healthcare", sections)
    prefixes = {r["evidenceCode"].split("-")[0] for r in risks if r["evidenceCode"] != INSUFFICIENT_EVIDENCE}
    assert "RES" in prefixes and "SEC" in prefixes


def test_best_supporting_section_requires_ownership():
    claim = {"sourceDocId": RES, "category": "Compliance", "signals": ["residency"],
             "phrases": [], "personas": [], "resolvedIf": []}
    # only incident sections present -> no owned section -> None
    assert best_supporting_section(claim, _sections(INC), "ops", "EMEA") is None


def test_workflow_steps_are_grounded_or_evidence_gap():
    sections = _sections(INC, SLA, PRC)
    steps, gen = workflow_builder("support", "EMEA", sections)
    available = {s["citationId"] for s in sections} | {INSUFFICIENT_EVIDENCE}
    assert all(s["evidenceCode"] in available for s in steps)
    assert gen["groundedKept"] + gen["unsupportedDropped"] == len(steps)
    assert len(gen["provenance"]) == len(steps)
