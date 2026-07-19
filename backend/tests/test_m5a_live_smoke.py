"""End-to-end M5a API/worker smoke; runs on real PostgreSQL in that profile."""

from sqlalchemy import func, select

import app.agents.orchestrator as orchestrator_module
from app.core.config import get_settings
from app.models.db_models import PatternMetric, Report
from app.services.llm import LLMCallResult
from tests.conftest import seed_finalized_document
from tests.test_m5a_feedback import put


SMOKE_POLICY = b"""# Control Evidence

## Administrative access
Administrative access must use MFA.

## Emergency access
Emergency access must be reviewed within 24 hours.

## Supplier assurance
Each critical supplier must be assessed quarterly.

## Backup exception
Backups are not tested.

## Policy accountability
Policy ownership is being considered.
"""


def test_m5a_full_api_worker_smoke(
    alice, bob, session_factory, monkeypatch, db_session
):
    seed_finalized_document(
        alice, session_factory, monkeypatch, body=SMOKE_POLICY, filename="m5a-smoke.md"
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    response = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"}
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert len(report) == 20 and "claims" not in report

    audit_response = alice.get(f"/api/reports/{report['id']}/claims")
    assert audit_response.status_code == 200
    candidates = audit_response.json()["candidates"]
    decisions = {item["claimSpecId"]: item for item in candidates}
    assert decisions["compliance.administrative-access-mfa"]["decision"]["status"] == "accepted"
    assert decisions["compliance.emergency-access-review-deadline"]["decision"]["status"] == "accepted"
    assert decisions["compliance.critical-supplier-periodic-assessment"]["decision"]["status"] == "accepted"
    backup = decisions["compliance.backups-tested"]["decision"]
    assert backup["status"] == "rejected"
    assert "CONTRADICTING_EVIDENCE" in backup["reasonCodes"]
    ambiguous = decisions["compliance.policy-ownership-assigned"]["decision"]
    assert ambiguous["status"] == "insufficient_evidence"
    assert ambiguous["missingRequirements"]
    accepted = [item for item in candidates if item["decision"]["status"] == "accepted"]
    assert all(item["evidenceBindings"] for item in accepted)
    assert all(
        binding["accepted"] and binding["documentVersionId"]
        for item in accepted for binding in item["evidenceBindings"] if binding["accepted"]
    )

    stored = db_session.execute(select(Report).where(Report.id == report["id"])).scalar_one()
    assert stored.engine_versions["patternLibrary"]["id"] == "compliance.claim-patterns"
    assert stored.engine_versions["patternLibrary"]["version"] == "1.0.0"
    assert len(stored.engine_versions["patternLibrary"]["digest"]) == 64
    assert stored.engine_versions["patternLibrary"]["schemaVersion"] == "claim-patterns-v1"
    assert stored.engine_versions["patternLibrary"]["matcherEngineVersion"] == "typed-matchers-v1"
    assert stored.engine_versions["thresholdPolicy"]["gateEngineVersion"] == "deterministic-support-gate-v1"
    assert all(
        policy["policyVersion"] == "1.0.0"
        for policy in stored.engine_versions["thresholdPolicy"]["policies"]
    )
    assert db_session.scalar(select(func.count()).select_from(PatternMetric)) == 7

    assert put(alice, f"/api/reports/{report['id']}/feedback", {
        "verdict": "correct_useful"
    }).status_code == 200
    assert put(alice, f"/api/reports/{report['id']}/feedback/items", {
        "itemPath": "/risks/0", "itemType": "risk", "verdict": "accepted"
    }).status_code == 200
    citation = report["citations"][0]
    assert put(alice, f"/api/reports/{report['id']}/feedback/citations", {
        "itemPath": "/citations/0", "citationId": citation["id"], "verdict": "correct"
    }).status_code == 200
    assert bob.get(f"/api/reports/{report['id']}/claims").status_code == 404
    assert bob.get(f"/api/reports/{report['id']}/feedback").status_code == 404

    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", False)
    off = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"}
    )
    assert off.status_code == 200
    off_audit = alice.get(f"/api/reports/{off.json()['id']}/claims").json()
    assert off_audit == {"claimEngineEnabled": False, "candidates": []}


def _claim_llm(proposals):
    def fake(**kwargs):
        value = {"proposals": proposals} if kwargs["schema_name"] == "ClaimProposals" else {}
        return LLMCallResult(value, True, len(kwargs["user"]))
    return fake


def test_live_llm_selective_citation_conflict_is_rejected(
    alice, session_factory, monkeypatch
):
    seed_finalized_document(
        alice,
        session_factory,
        monkeypatch,
        body=b"""# Access control\n\n## Positive\nAdministrative access must use MFA.\n\n## Exception\nAdministrative access is not required to use MFA.\n""",
        filename="m5a-conflict.md",
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    monkeypatch.setattr(settings, "evidentia_use_llm", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "evidentia_llm_intensity", "full")
    monkeypatch.setattr(orchestrator_module, "generate_structured_object", _claim_llm([{
        "claimSpecId": "compliance.administrative-access-mfa",
        "statement": "MFA protects administrator access.",
        "evidenceCodes": [],
    }]))

    # Resolve the positive citation exactly as a model would see it, then repeat
    # with a proposal citing only that section.
    baseline = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"}
    )
    assert baseline.status_code == 200, baseline.text
    sources = alice.get(f"/api/reports/{baseline.json()['id']}/sources").json()["evidenceBindings"]
    positive = next(row["citationId"] for row in sources if "must use MFA" in row["excerpt"])
    monkeypatch.setattr(orchestrator_module, "generate_structured_object", _claim_llm([{
        "claimSpecId": "compliance.administrative-access-mfa",
        "statement": "MFA protects administrator access.",
        "evidenceCodes": [positive],
    }]))
    response = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"}
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["workflowSteps"] == report["risks"] == report["suggestedActions"] == []
    assert "No accepted claim" in report["topFinding"]
    audit = alice.get(f"/api/reports/{report['id']}/claims").json()["candidates"]
    llm = next(item for item in audit if item["candidateSource"] == "llm_proposal")
    assert llm["decision"]["status"] == "rejected"
    assert "CONTRADICTING_EVIDENCE" in llm["decision"]["reasonCodes"]
    conflicts = [row for row in llm["matcherObservations"] if row["purpose"] == "conflict"]
    assert any(row["bindingIds"] for row in conflicts)
    assert llm["appearedInFinal"] is False


def test_live_llm_unrelated_padding_is_not_accepted_support(
    alice, session_factory, monkeypatch
):
    seed_finalized_document(
        alice,
        session_factory,
        monkeypatch,
        body=b"""# Access control\n\n## MFA\nAdministrative access must use MFA.\n\n## Cafeteria\nThe cafeteria closes at five.\n""",
        filename="m5a-padding.md",
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    monkeypatch.setattr(settings, "evidentia_use_llm", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "evidentia_llm_intensity", "off")
    baseline = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"}
    )
    assert baseline.status_code == 200
    sources = alice.get(f"/api/reports/{baseline.json()['id']}/sources").json()["evidenceBindings"]
    positive = next(row["citationId"] for row in sources if "must use MFA" in row["excerpt"])
    unrelated = next(row["citationId"] for row in sources if "cafeteria" in row["excerpt"])
    monkeypatch.setattr(settings, "evidentia_llm_intensity", "full")
    monkeypatch.setattr(orchestrator_module, "generate_structured_object", _claim_llm([{
        "claimSpecId": "compliance.administrative-access-mfa",
        "statement": "MFA protects administrator access.",
        "evidenceCodes": [positive, unrelated],
    }]))
    response = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"}
    )
    assert response.status_code == 200
    audit = alice.get(f"/api/reports/{response.json()['id']}/claims").json()["candidates"]
    llm = next(item for item in audit if item["candidateSource"] == "llm_proposal")
    accepted = [row["citationId"] for row in llm["evidenceBindings"] if row["accepted"]]
    assert accepted == [positive]
    assert unrelated not in accepted
    assert llm["decision"]["features"]["bindingCount"] == 1.0
