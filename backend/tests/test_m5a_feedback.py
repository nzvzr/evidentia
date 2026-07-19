from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.db_models import (
    CitationFeedback,
    ItemFeedback,
    PatternMetric,
    ReportClaimCandidate,
    ReportClaimDecision,
    ReportClaimEvidence,
    ReportFeedback,
)


def generate_claim_report(alice, tenant_generation, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", True)
    response = alice.post("/api/generate-workflow", json={"market": "EMEA", "persona": "Compliance Officer"})
    assert response.status_code == 200, response.text
    return response.json()


def put(account, path, body):
    return account._client.put(path, json=body, headers=account.headers)


def test_claim_graph_persists_versions_decisions_bindings_metrics_and_public_schema(
    alice, tenant_generation, monkeypatch, db_session
):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    assert len(report) == 20
    assert "claims" not in report
    audit = alice.get(f"/api/reports/{report['id']}/claims")
    assert audit.status_code == 200
    candidates = audit.json()["candidates"]
    assert len(candidates) == 7
    assert any(item["decision"]["status"] == "accepted" for item in candidates)
    assert all(item["decision"]["gateEngineVersion"] == "deterministic-support-gate-v1" for item in candidates)
    assert db_session.scalar(select(func.count()).select_from(ReportClaimCandidate)) == 7
    assert db_session.scalar(select(func.count()).select_from(ReportClaimDecision)) == 7
    assert db_session.scalar(select(func.count()).select_from(ReportClaimEvidence)) >= 1
    assert db_session.scalar(select(func.count()).select_from(PatternMetric)) == 7


def test_feedback_replacement_validation_and_cross_tenant_absence(
    alice, bob, tenant_generation, monkeypatch, db_session
):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    report_id = report["id"]
    assert bob.get(f"/api/reports/{report_id}/feedback").status_code == 404
    assert put(bob, f"/api/reports/{report_id}/feedback", {"verdict": "incorrect"}).status_code == 404

    first = put(alice, f"/api/reports/{report_id}/feedback", {
        "verdict": "partially_correct", "reasonCode": "missing_context", "privateText": "Private tenant note",
    })
    assert first.status_code == 200, first.text
    second = put(alice, f"/api/reports/{report_id}/feedback", {"verdict": "correct_useful"})
    assert second.status_code == 200
    rows = list(db_session.execute(select(ReportFeedback)).scalars())
    assert len(rows) == 1
    assert rows[0].verdict == "correct_useful"
    assert rows[0].private_text is None

    item = put(alice, f"/api/reports/{report_id}/feedback/items", {
        "itemPath": "/risks/0", "itemType": "risk", "verdict": "accepted",
    })
    assert item.status_code == 200, item.text
    replacement = put(alice, f"/api/reports/{report_id}/feedback/items", {
        "itemPath": "/risks/0", "itemType": "risk", "verdict": "edited", "editedText": "Tighter wording",
    })
    assert replacement.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(ItemFeedback)) == 1
    assert db_session.execute(select(ItemFeedback)).scalar_one().edited_text == "Tighter wording"
    invalid = put(alice, f"/api/reports/{report_id}/feedback/items", {
        "itemPath": "/risks/999", "itemType": "risk", "verdict": "accepted",
    })
    assert invalid.status_code == 422
    leading_zero = put(alice, f"/api/reports/{report_id}/feedback/items", {
        "itemPath": "/risks/00", "itemType": "risk", "verdict": "accepted",
    })
    assert leading_zero.status_code == 422
    wrong_shape = put(alice, f"/api/reports/{report_id}/feedback/items", {
        "itemPath": "/workflowSteps/0", "itemType": "risk", "verdict": "accepted",
    })
    assert wrong_shape.status_code == 422

    citation = report["citations"][0]
    source_audit = alice.get(f"/api/reports/{report_id}/sources").json()
    binding = next(value for value in source_audit["evidenceBindings"] if value["citationId"] == citation["id"])
    correct = put(alice, f"/api/reports/{report_id}/feedback/citations", {
        "itemPath": "/citations/0", "citationId": citation["id"], "verdict": "incorrect_source",
        "correctedAnchorId": binding["anchorId"],
    })
    assert correct.status_code == 200, correct.text
    assert db_session.scalar(select(func.count()).select_from(CitationFeedback)) == 1
    wrong = put(alice, f"/api/reports/{report_id}/feedback/citations", {
        "itemPath": "/citations/0", "citationId": "FOREIGN-1", "verdict": "correct",
    })
    assert wrong.status_code == 422
    outside_snapshot = put(alice, f"/api/reports/{report_id}/feedback/citations", {
        "itemPath": "/citations/0", "citationId": citation["id"], "verdict": "incorrect_source",
        "correctedAnchorId": "not-in-this-report",
    })
    assert outside_snapshot.status_code == 422

    current = alice.get(f"/api/reports/{report_id}/feedback")
    assert current.status_code == 200
    assert current.json()["report"]["verdict"] == "correct_useful"
    assert current.json()["items"][0]["verdict"] == "edited"
    assert current.json()["citations"][0]["correctedAnchorId"] == binding["anchorId"]


def test_retrieval_miss_requires_a_missing_need_and_snapshot_anchor(
    alice, tenant_generation, monkeypatch
):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    claims = alice.get(f"/api/reports/{report['id']}/claims").json()["candidates"]
    candidate = next(item for item in claims if item["decision"]["missingRequirements"])
    anchor = alice.get(f"/api/reports/{report['id']}/sources").json()["evidenceBindings"][0]["anchorId"]
    body = {
        "candidateId": candidate["candidateId"],
        "evidenceNeedId": candidate["decision"]["missingRequirements"][0],
        "correctedAnchorId": anchor,
    }
    assert put(alice, f"/api/reports/{report['id']}/retrieval-misses", body).status_code == 200
    assert put(alice, f"/api/reports/{report['id']}/retrieval-misses", body).status_code == 200
    bad = {**body, "evidenceNeedId": "not-missing"}
    assert put(alice, f"/api/reports/{report['id']}/retrieval-misses", bad).status_code == 422


def test_deleted_report_feedback_is_not_addressable(alice, tenant_generation, monkeypatch):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    assert alice.delete(f"/api/reports/{report['id']}").status_code == 200
    assert alice.get(f"/api/reports/{report['id']}/feedback").status_code == 404
    assert put(alice, f"/api/reports/{report['id']}/feedback", {"verdict": "incorrect"}).status_code == 404


def test_feedback_payloads_are_bounded(alice, tenant_generation, monkeypatch):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    response = put(alice, f"/api/reports/{report['id']}/feedback", {
        "verdict": "incorrect", "privateText": "x" * 2001,
    })
    assert response.status_code == 422


def test_duplicate_generations_have_independent_graphs_and_add_metrics(
    alice, tenant_generation, monkeypatch, db_session
):
    first = generate_claim_report(alice, tenant_generation, monkeypatch)
    second = generate_claim_report(alice, tenant_generation, monkeypatch)
    assert first["id"] != second["id"]
    assert alice.get(f"/api/reports/{first['id']}/claims").status_code == 200
    assert alice.get(f"/api/reports/{second['id']}/claims").status_code == 200
    assert db_session.scalar(select(func.count()).select_from(ReportClaimCandidate)) == 14
    metrics = list(db_session.execute(select(PatternMetric)).scalars())
    assert len(metrics) == 7
    assert all(row.evaluated_count == 2 and row.candidate_count == 2 for row in metrics)


def test_concurrent_feedback_replaces_one_row_without_corruption(
    alice, tenant_generation, monkeypatch, db_session
):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    path = f"/api/reports/{report['id']}/feedback"

    def submit(verdict: str):
        return put(alice, path, {"verdict": verdict})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ["correct_useful", "incorrect"]))
    assert all(response.status_code == 200 for response in responses)
    rows = list(db_session.execute(select(ReportFeedback)).scalars())
    assert len(rows) == 1
    assert rows[0].verdict in {"correct_useful", "incorrect"}


def test_feedback_writes_are_rate_limited(
    alice, tenant_generation, monkeypatch
):
    report = generate_claim_report(alice, tenant_generation, monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_feedback_user_limit", 1)
    monkeypatch.setattr(settings, "rl_feedback_tenant_limit", 10)
    monkeypatch.setattr(settings, "rl_feedback_ip_limit", 10)
    first = put(alice, f"/api/reports/{report['id']}/feedback", {"verdict": "correct_useful"})
    second = put(alice, f"/api/reports/{report['id']}/feedback/items", {
        "itemPath": "/risks/0", "itemType": "risk", "verdict": "accepted",
    })
    assert first.status_code == 200
    assert second.status_code == 429
