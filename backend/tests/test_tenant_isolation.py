"""Tenant isolation and IDOR.

Every test here follows the same shape: Alice (tenant Acme) owns a resource;
Bob (tenant Globex) is fully authenticated but has no membership in Acme. Bob
must never be able to read, modify, delete, or even confirm the existence of
Alice's resources — including when he supplies Alice's company_id explicitly.

Cross-tenant access must answer 404, not 403: a 403 confirms the id exists.
"""

from __future__ import annotations

from app.models.db_models import Company, Report
from tests.conftest import register

REPORT = {
    "id": "client-supplied-id",
    "persona": "Support Agent",
    "market": "EMEA",
    "metrics": {"confidence": 90},
    "workflow": [],
    "risks": [],
    "citations": [],
}


def _create_report(account, body=None):
    """Reports are created only by authenticated generation."""
    res = account.post("/api/generate-workflow", json={"market": "EMEA", "persona": "Support Agent"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


# --- unauthenticated access ---------------------------------------------


def test_every_tenant_endpoint_requires_authentication(client):
    """Regression: all of these were open to anonymous callers."""
    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/reports/any-id").status_code == 401
    assert client.post("/api/reports", json={"report": REPORT}).status_code in (401, 405)
    assert client.delete("/api/reports/any-id").status_code == 401
    assert client.get("/api/documents").status_code == 401
    assert client.post("/api/documents", json={"title": "x"}).status_code == 401
    assert client.get("/api/personas").status_code == 401
    assert client.post("/api/personas", json={"name": "x"}).status_code == 401
    assert client.get("/api/companies").status_code == 401
    assert client.post("/api/generate-workflow", json={"market": "EMEA"}).status_code == 401


# --- report IDOR ---------------------------------------------------------


def test_bob_cannot_read_alices_report_by_id(client, alice, bob):
    report_id = _create_report(alice)
    assert alice.get(f"/api/reports/{report_id}").status_code == 200

    res = bob.get(f"/api/reports/{report_id}")
    assert res.status_code == 404, "cross-tenant read must 404, not leak the report"
    assert "persona" not in res.text


def test_bob_cannot_delete_alices_report(client, alice, bob):
    report_id = _create_report(alice)
    assert bob.delete(f"/api/reports/{report_id}").status_code == 404
    # Still there for its rightful owner.
    assert alice.get(f"/api/reports/{report_id}").status_code == 200


def test_bob_cannot_list_alices_reports_by_passing_her_company_id(client, alice, bob):
    _create_report(alice)
    assert len(alice.get("/api/reports").json()["reports"]) == 1

    # Naming a company you are not a member of must not grant access.
    res = bob.get(f"/api/reports?company_id={alice.company_id}")
    assert res.status_code == 404
    # And Bob's own list stays empty.
    assert bob.get("/api/reports").json()["reports"] == []


def test_company_id_header_cannot_be_forged(client, alice, bob):
    _create_report(alice)
    res = bob.get("/api/reports", headers={**bob.headers, "X-Company-Id": alice.company_id})
    assert res.status_code == 404


def test_report_ownership_is_taken_from_the_session_not_the_body(client, alice, bob, db_session):
    """Generation ignores any client-supplied ownership; the report lands in the
    caller's tenant. (The old POST /api/reports body-ownership hole is gone
    entirely — that endpoint no longer creates anything.)"""
    res = bob.post(
        "/api/generate-workflow",
        json={"market": "EMEA", "persona": "Support Agent",
              "companyId": alice.company_id, "userId": alice.user_id},
    )
    assert res.status_code == 200
    row = db_session.get(Report, res.json()["id"])
    assert row.company_id == bob.company_id, "report must land in the caller's tenant"
    assert row.user_id == bob.user_id
    # Alice sees nothing.
    assert alice.get("/api/reports").json()["reports"] == []


def test_generated_report_is_scoped_to_the_callers_tenant(client, alice, bob, db_session):
    res = alice.post("/api/generate-workflow", json={"market": "EMEA", "persona": "Support Agent"})
    assert res.status_code == 200
    row = db_session.get(Report, res.json()["id"])
    assert row.company_id == alice.company_id
    assert bob.get("/api/reports").json()["reports"] == []


# --- document / persona IDOR --------------------------------------------


def test_bob_cannot_read_or_delete_alices_document(client, alice, bob):
    doc_id = alice.post("/api/documents", json={"title": "Acme residency policy"}).json()["id"]
    assert alice.get(f"/api/documents/{doc_id}").status_code == 200
    assert bob.get(f"/api/documents/{doc_id}").status_code == 404
    assert bob.delete(f"/api/documents/{doc_id}").status_code == 404
    assert alice.get(f"/api/documents/{doc_id}").status_code == 200


def test_documents_written_by_bob_land_in_bobs_tenant(client, alice, bob):
    bob.post("/api/documents", json={"title": "Globex doc"})
    titles = [d["title"] for d in alice.get("/api/documents").json()["documents"]]
    assert "Globex doc" not in titles


def test_bob_cannot_see_alices_custom_persona(client, alice, bob):
    alice.post("/api/personas", json={"name": "Acme Compliance Lead"})
    bob_personas = [p["name"] for p in bob.get("/api/personas").json()["personas"]]
    assert "Acme Compliance Lead" not in bob_personas
    # Alice does see her own, alongside the shared default catalogue.
    alice_personas = [p["name"] for p in alice.get("/api/personas").json()["personas"]]
    assert "Acme Compliance Lead" in alice_personas


def test_bob_cannot_delete_alices_persona(client, alice, bob):
    persona_id = alice.post("/api/personas", json={"name": "Acme Persona"}).json()["id"]
    assert bob.delete(f"/api/personas/{persona_id}").status_code == 404


# --- company enumeration -------------------------------------------------


def test_company_list_shows_only_your_own_memberships(client, alice, bob):
    """Regression: GET /api/companies used to return every tenant in the system."""
    body = bob.get("/api/companies").json()["companies"]
    ids = {c["id"] for c in body}
    assert ids == {bob.company_id}
    assert alice.company_id not in ids


def test_bob_cannot_read_alices_company_members(client, alice, bob):
    res = bob.get(f"/api/companies/members?company_id={alice.company_id}")
    assert res.status_code == 404
    assert alice.email not in res.text


# --- no shared demo company ---------------------------------------------


def test_no_demo_company_is_seeded(client, db_session):
    """Regression: init_db used to seed a shared 'northreach-cloud' company that
    every anonymous request was funnelled into."""
    from app.db.init_db import init_db  # noqa: F401  (import must not seed)

    assert db_session.query(Company).count() == 0


def test_registering_creates_a_distinct_company_per_user(client, db_session):
    a = register(client, "one@a.co", company="Acme")
    b = register(client, "two@b.co", company="Globex")
    assert a.company_id != b.company_id
    assert db_session.query(Company).count() == 2


def test_two_users_registering_the_same_company_name_get_separate_tenants(client):
    """Name collision must not merge tenants."""
    a = register(client, "a@x.co", company="Acme")
    b = register(client, "b@y.co", company="Acme")
    assert a.company_id != b.company_id

    report_id = _create_report(a)
    assert b.get(f"/api/reports/{report_id}").status_code == 404


def test_user_with_no_membership_gets_no_tenant(client, db_session):
    """A user who somehow has no company cannot fall back into a shared one."""
    from app.core import security
    from app.models.db_models import CompanyMember
    from app.repositories import users as users_repo

    orphan = users_repo.create_user(
        db_session, email="orphan@nowhere.co", hashed_password=security.hash_password("x" * 14)
    )
    db_session.query(CompanyMember).filter(CompanyMember.user_id == orphan.id).delete()
    db_session.commit()

    token = security.create_access_token(orphan.id, orphan.email)
    res = client.get("/api/reports", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert "organization" in res.json()["detail"].lower()
