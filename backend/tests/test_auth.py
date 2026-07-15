"""Authentication: hashing, login, JWT, refresh rotation, logout, verification,
password reset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core import security
from app.models.db_models import RefreshToken
from app.repositories import tokens as tokens_repo
from tests.conftest import VALID_PASSWORD, register


# --- password hashing ----------------------------------------------------


def test_password_hash_is_bcrypt_salted_and_verifies():
    h1 = security.hash_password("hunter2-hunter2")
    h2 = security.hash_password("hunter2-hunter2")
    assert h1.startswith("$2b$")
    assert h1 != h2, "identical passwords must produce different hashes (salted)"
    assert security.verify_password("hunter2-hunter2", h1)
    assert not security.verify_password("wrong", h1)


def test_password_hash_never_truncates_at_72_bytes():
    """bcrypt truncates at 72 bytes; the SHA-256 pre-hash must prevent two long
    passwords sharing a prefix from being interchangeable."""
    base = "a" * 72
    h = security.hash_password(base + "SUFFIX-ONE")
    assert not security.verify_password(base + "SUFFIX-TWO", h)
    assert security.verify_password(base + "SUFFIX-ONE", h)


def test_verify_password_false_for_user_without_hash():
    assert not security.verify_password("anything", None)
    assert not security.verify_password("anything", "")


# --- registration --------------------------------------------------------


def test_register_creates_owner_of_a_new_company(client):
    acct = register(client, "founder@acme.co", company="Acme Inc")
    assert acct.companies[0]["role"] == "owner"
    assert acct.companies[0]["name"] == "Acme Inc"
    assert acct.access and acct.refresh


def test_register_never_returns_the_password_hash(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "x@acme.co", "password": VALID_PASSWORD, "company": "X"},
    )
    assert "password" not in res.text.lower() or "hashed" not in res.text.lower()
    assert "$2b$" not in res.text


def test_register_rejects_weak_password(client):
    res = client.post("/api/auth/register", json={"email": "weak@acme.co", "password": "short"})
    assert res.status_code == 422


def test_register_requires_a_password(client):
    """The old endpoint allowed password-less accounts."""
    res = client.post("/api/auth/register", json={"email": "nopass@acme.co"})
    assert res.status_code == 422


def test_register_rejects_duplicate_email_case_insensitively(client):
    register(client, "dupe@acme.co")
    res = client.post(
        "/api/auth/register",
        json={"email": "DUPE@ACME.CO", "password": VALID_PASSWORD},
    )
    assert res.status_code == 409


# --- login ---------------------------------------------------------------


def test_login_succeeds_with_correct_password(client, alice):
    res = client.post("/api/auth/login", json={"email": alice.email, "password": VALID_PASSWORD})
    assert res.status_code == 200
    assert res.json()["accessToken"]


def test_login_rejects_wrong_password(client, alice):
    res = client.post("/api/auth/login", json={"email": alice.email, "password": "not-the-password"})
    assert res.status_code == 401


def test_login_rejects_unknown_email_identically(client, alice):
    """No account enumeration: unknown email and wrong password look the same."""
    unknown = client.post(
        "/api/auth/login", json={"email": "ghost@nowhere.co", "password": VALID_PASSWORD}
    )
    wrong = client.post("/api/auth/login", json={"email": alice.email, "password": "bad-password!!"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_there_is_no_passwordless_token_endpoint(client):
    """Regression: /api/auth/token used to mint a JWT for any email, no password."""
    res = client.post("/api/auth/token", json={"email": "attacker@evil.co"})
    assert res.status_code == 404


# --- access tokens -------------------------------------------------------


def test_protected_route_rejects_missing_and_garbage_tokens(client):
    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/reports", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/reports", headers={"Authorization": "Basic abc"}).status_code == 401


def test_access_token_rejected_when_expired(client, alice, monkeypatch):
    expired = security.jwt.encode(
        {
            "sub": alice.user_id,
            "email": alice.email,
            "typ": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        security.get_settings().effective_jwt_secret(),
        algorithm="HS256",
    )
    res = client.get("/api/reports", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


def test_access_token_rejected_when_signed_with_another_key(client, alice):
    forged = security.jwt.encode(
        {
            "sub": alice.user_id,
            "email": alice.email,
            "typ": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "attacker-key",
        algorithm="HS256",
    )
    assert client.get("/api/reports", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_refresh_token_cannot_be_used_as_a_bearer_token(client, alice):
    """A refresh token is opaque and must never authenticate an API call."""
    res = client.get("/api/reports", headers={"Authorization": f"Bearer {alice.refresh}"})
    assert res.status_code == 401


def test_me_returns_the_session_user(client, alice):
    res = alice.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json()["user"]["email"] == alice.email
    assert res.json()["companies"][0]["role"] == "owner"


# --- refresh rotation ----------------------------------------------------


def test_refresh_rotates_and_returns_a_new_pair(client, alice):
    res = client.post("/api/auth/refresh", json={"refreshToken": alice.refresh})
    assert res.status_code == 200
    body = res.json()
    assert body["refreshToken"] != alice.refresh, "refresh token must rotate"
    assert body["accessToken"]
    # The new access token works.
    assert client.get(
        "/api/reports", headers={"Authorization": f"Bearer {body['accessToken']}"}
    ).status_code == 200


def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(client, alice, db_session):
    first = client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).json()
    # Replaying the original (now-spent) token is the theft signal.
    replay = client.post("/api/auth/refresh", json={"refreshToken": alice.refresh})
    assert replay.status_code == 401

    # ...and it invalidates the token the thief/victim rotated into.
    after = client.post("/api/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert after.status_code == 401, "family must be revoked after reuse detection"

    live = db_session.query(RefreshToken).filter(RefreshToken.revoked_at.is_(None)).count()
    assert live == 0


def test_refresh_rejects_unknown_token(client):
    assert client.post("/api/auth/refresh", json={"refreshToken": "made-up"}).status_code == 401


def test_refresh_rejects_expired_token(client, alice, db_session):
    row = tokens_repo.get_refresh_token(db_session, alice.refresh)
    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db_session.add(row)
    db_session.commit()
    assert client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).status_code == 401


# --- logout --------------------------------------------------------------


def test_logout_revokes_the_refresh_token(client, alice):
    assert client.post("/api/auth/logout", json={"refreshToken": alice.refresh}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).status_code == 401


def test_logout_all_revokes_every_session(client, alice):
    second = client.post("/api/auth/login", json={"email": alice.email, "password": VALID_PASSWORD}).json()
    assert alice.post("/api/auth/logout-all").status_code == 200

    assert client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refreshToken": second["refreshToken"]}).status_code == 401


def test_logout_requires_no_auth_and_is_idempotent(client):
    assert client.post("/api/auth/logout", json={"refreshToken": "whatever"}).status_code == 200


# --- email verification --------------------------------------------------


def test_registration_sends_a_verification_email(client, outbox):
    register(client, "verify@acme.co")
    assert len(outbox) == 1
    assert "verify-email?token=" in outbox[0].body


def test_email_verification_confirms_the_user(client, outbox):
    acct = register(client, "verify2@acme.co")
    assert acct.get("/api/auth/me").json()["user"]["emailVerified"] is False

    token = outbox[0].body.split("token=")[1].split()[0]
    assert client.post("/api/auth/verify-email/confirm", json={"token": token}).status_code == 200
    assert acct.get("/api/auth/me").json()["user"]["emailVerified"] is True


def test_verification_token_is_single_use(client, outbox):
    register(client, "verify3@acme.co")
    token = outbox[0].body.split("token=")[1].split()[0]
    assert client.post("/api/auth/verify-email/confirm", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify-email/confirm", json={"token": token}).status_code == 400


def test_verification_rejects_invalid_token(client):
    assert client.post("/api/auth/verify-email/confirm", json={"token": "bogus"}).status_code == 400


def test_verification_request_does_not_leak_account_existence(client, outbox):
    res = client.post("/api/auth/verify-email/request", json={"email": "nobody@nowhere.co"})
    assert res.status_code == 202
    assert outbox == []


def test_write_blocked_for_unverified_user_when_verification_required(client, monkeypatch):
    settings = security.get_settings()
    monkeypatch.setattr(settings, "evidentia_require_email_verification", True)
    acct = register(client, "unverified@acme.co")
    res = acct.get("/api/reports")
    assert res.status_code == 403
    assert "not verified" in res.json()["detail"].lower()


# --- password reset ------------------------------------------------------


def test_password_reset_end_to_end(client, alice, outbox):
    outbox.clear()
    assert client.post("/api/auth/password-reset/request", json={"email": alice.email}).status_code == 202
    token = outbox[0].body.split("token=")[1].split()[0]

    new_password = "an-entirely-new-password"
    assert client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": new_password}
    ).status_code == 200

    # Old password no longer works; new one does.
    assert client.post("/api/auth/login", json={"email": alice.email, "password": VALID_PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": alice.email, "password": new_password}).status_code == 200


def test_password_reset_revokes_existing_sessions(client, alice, outbox):
    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": alice.email})
    token = outbox[0].body.split("token=")[1].split()[0]
    client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "brand-new-password-1"})

    # The pre-reset refresh token is dead.
    assert client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).status_code == 401


def test_password_reset_token_is_single_use(client, alice, outbox):
    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": alice.email})
    token = outbox[0].body.split("token=")[1].split()[0]
    assert client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": "first-new-password-x"}
    ).status_code == 200
    assert client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": "second-new-password"}
    ).status_code == 400


def test_password_reset_request_does_not_leak_account_existence(client, outbox):
    outbox.clear()
    res = client.post("/api/auth/password-reset/request", json={"email": "ghost@nowhere.co"})
    assert res.status_code == 202
    assert res.json() == {"ok": True}
    assert outbox == []


def test_password_reset_enforces_password_strength(client, alice, outbox):
    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": alice.email})
    token = outbox[0].body.split("token=")[1].split()[0]
    assert client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "password": "weak"}
    ).status_code == 422


def test_requesting_a_new_reset_invalidates_the_previous_link(client, alice, outbox):
    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": alice.email})
    old_token = outbox[0].body.split("token=")[1].split()[0]
    client.post("/api/auth/password-reset/request", json={"email": alice.email})

    assert client.post(
        "/api/auth/password-reset/confirm", json={"token": old_token, "password": "should-not-work-1"}
    ).status_code == 400
