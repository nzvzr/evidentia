"""Organization ownership, membership, and the owner > admin > member hierarchy."""

from __future__ import annotations

import pytest

from tests.conftest import VALID_PASSWORD, register


@pytest.fixture
def team(client, alice):
    """Alice (owner of Acme) plus an admin and a member in the same tenant."""
    admin = register(client, "admin@acme.co", company="Admin Personal Org")
    member = register(client, "member@acme.co", company="Member Personal Org")

    assert alice.post(
        "/api/companies/members", json={"email": admin.email, "role": "admin"}
    ).status_code == 201
    assert alice.post(
        "/api/companies/members", json={"email": member.email, "role": "member"}
    ).status_code == 201

    # They now belong to two companies each, so they must name the tenant.
    admin.headers_for_acme = {**admin.headers, "X-Company-Id": alice.company_id}
    member.headers_for_acme = {**member.headers, "X-Company-Id": alice.company_id}
    return {"owner": alice, "admin": admin, "member": member, "company_id": alice.company_id}


def test_membership_grants_access_to_the_shared_tenant(client, team):
    alice, member = team["owner"], team["member"]
    report_id = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Support Agent"}
    ).json()["id"]

    res = client.get(f"/api/reports/{report_id}", headers=member.headers_for_acme)
    assert res.status_code == 200, "a member of the tenant can read its reports"


def test_member_cannot_delete_reports(client, team):
    alice, member = team["owner"], team["member"]
    report_id = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Support Agent"}
    ).json()["id"]

    res = client.delete(f"/api/reports/{report_id}", headers=member.headers_for_acme)
    assert res.status_code == 403
    assert alice.get(f"/api/reports/{report_id}").status_code == 200


def test_admin_can_delete_reports(client, team):
    alice, admin = team["owner"], team["admin"]
    report_id = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Support Agent"}
    ).json()["id"]

    assert client.delete(f"/api/reports/{report_id}", headers=admin.headers_for_acme).status_code == 200


def test_member_cannot_add_members(client, team):
    member = team["member"]
    res = client.post(
        "/api/companies/members",
        headers=member.headers_for_acme,
        json={"email": "outsider@x.co", "role": "member"},
    )
    assert res.status_code == 403


def test_admin_cannot_grant_owner_role(client, team):
    """Privilege escalation: an admin must not be able to mint an owner."""
    admin = team["admin"]
    outsider = register(client, "outsider@x.co", company="Outsider Org")
    res = client.post(
        "/api/companies/members",
        headers=admin.headers_for_acme,
        json={"email": outsider.email, "role": "owner"},
    )
    assert res.status_code == 403


def test_admin_cannot_promote_themselves_to_owner(client, team):
    admin = team["admin"]
    res = client.patch(
        f"/api/companies/members/{admin.user_id}",
        headers=admin.headers_for_acme,
        json={"role": "owner"},
    )
    assert res.status_code == 403


def test_admin_cannot_demote_or_remove_the_owner(client, team):
    admin, alice = team["admin"], team["owner"]
    assert client.patch(
        f"/api/companies/members/{alice.user_id}",
        headers=admin.headers_for_acme,
        json={"role": "member"},
    ).status_code == 403
    assert client.delete(
        f"/api/companies/members/{alice.user_id}", headers=admin.headers_for_acme
    ).status_code == 403


def test_owner_can_promote_and_demote(client, team):
    alice, member = team["owner"], team["member"]
    assert alice.patch(
        f"/api/companies/members/{member.user_id}", json={"role": "admin"}
    ).json()["role"] == "admin"
    assert alice.patch(
        f"/api/companies/members/{member.user_id}", json={"role": "member"}
    ).json()["role"] == "member"


def test_owner_cannot_be_demoted_while_they_are_the_last_owner(client, team):
    alice = team["owner"]
    res = alice.patch(f"/api/companies/members/{alice.user_id}", json={"role": "admin"})
    assert res.status_code == 409, "a company must always retain an owner"


def test_last_owner_cannot_be_removed(client, team):
    alice = team["owner"]
    assert alice.delete(f"/api/companies/members/{alice.user_id}").status_code == 409


def test_ownership_transfer(client, team, db_session):
    from app.models.db_models import Company

    alice, admin = team["owner"], team["admin"]
    res = alice.post("/api/companies/transfer-ownership", json={"userId": admin.user_id})
    assert res.status_code == 200

    company = db_session.get(Company, team["company_id"])
    assert company.owner_id == admin.user_id

    # The former owner is demoted to admin, the new owner has owner rights.
    members = {m["userId"]: m["role"] for m in alice.get("/api/companies/members").json()["members"]}
    assert members[admin.user_id] == "owner"
    assert members[alice.user_id] == "admin"


def test_only_an_owner_can_transfer_ownership(client, team):
    admin, member = team["admin"], team["member"]
    assert client.post(
        "/api/companies/transfer-ownership",
        headers=admin.headers_for_acme,
        json={"userId": member.user_id},
    ).status_code == 403


def test_removed_member_loses_access_immediately(client, team):
    alice, member = team["owner"], team["member"]
    report_id = alice.post(
        "/api/generate-workflow", json={"market": "EMEA", "persona": "Support Agent"}
    ).json()["id"]
    assert client.get(f"/api/reports/{report_id}", headers=member.headers_for_acme).status_code == 200

    assert alice.delete(f"/api/companies/members/{member.user_id}").status_code == 200

    res = client.get(f"/api/reports/{report_id}", headers=member.headers_for_acme)
    assert res.status_code == 404, "revoked membership must revoke data access"


def test_creating_a_company_makes_you_its_owner(client, alice):
    res = alice.post("/api/companies", json={"name": "Second Org"})
    assert res.status_code == 201
    assert res.json()["role"] == "owner"
    assert res.json()["ownerId"] == alice.user_id


def test_belonging_to_multiple_companies_requires_choosing_one(client, alice):
    alice.post("/api/companies", json={"name": "Second Org"})
    res = alice.get("/api/reports")
    assert res.status_code == 400
    assert "company_id" in res.json()["detail"]
