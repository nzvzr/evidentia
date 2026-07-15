"""Production startup validation, BFF guard, and access-token revocation."""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.config import DEFAULT_JWT_SECRET, Settings, bff_secret_problem, jwt_secret_problem
from app.main import app, validate_production_config
from tests.conftest import VALID_PASSWORD, register

# A real generated JWT key, exactly what the documented command produces. The
# previous hand-typed constant happened to pass the generated-secret gate, but a
# hand-typed value passing a statistical gate is luck, not a guarantee.
STRONG_SECRET = secrets.token_urlsafe(48)

# A real generated secret: the base64url encoding of 32 random bytes, exactly what
# the documented command produces. The previous value here ("Zx4Qm9Lp2Rv7...", 35
# chars) only *looked* strong — it decodes to 26 bytes and would now be refused.
STRONG_BFF_SECRET = secrets.token_urlsafe(32)


def _prod(**kw) -> Settings:
    base = dict(
        evidentia_env="production",
        jwt_secret=STRONG_SECRET,
        evidentia_email_backend="smtp",
        evidentia_smtp_host="smtp.example.com",
        evidentia_cors_origins="https://app.example.com",
        evidentia_trusted_proxy_count=0,
        evidentia_db_enabled=True,
    )
    base.update(kw)
    return Settings(**base)


# --- production startup ---------------------------------------------------


def test_a_correctly_configured_production_process_starts():
    validate_production_config(_prod())  # no raise


def test_production_refuses_the_default_jwt_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_config(_prod(jwt_secret=DEFAULT_JWT_SECRET))


def test_production_refuses_trusting_a_proxy_without_a_bff_secret():
    """Trusting X-Forwarded-For while directly reachable = forgeable client IP."""
    with pytest.raises(RuntimeError, match="EVIDENTIA_BFF_SECRET"):
        validate_production_config(_prod(evidentia_trusted_proxy_count=1, evidentia_bff_secret=""))


def test_production_accepts_a_trusted_proxy_with_a_strong_bff_secret():
    validate_production_config(
        _prod(evidentia_trusted_proxy_count=1, evidentia_bff_secret=STRONG_BFF_SECRET)
    )


def test_production_refuses_the_console_email_backend():
    """It writes single-use reset links into the logs."""
    with pytest.raises(RuntimeError, match="EVIDENTIA_EMAIL_BACKEND"):
        validate_production_config(_prod(evidentia_email_backend="console"))


def test_production_refuses_the_noop_email_backend():
    """It silently discards reset/verification mail, so the feature only *looks*
    like it works — nobody ever receives a link."""
    with pytest.raises(RuntimeError, match="EVIDENTIA_EMAIL_BACKEND"):
        validate_production_config(_prod(evidentia_email_backend="noop"))


def test_production_refuses_smtp_without_a_host():
    with pytest.raises(RuntimeError, match="EVIDENTIA_SMTP_HOST"):
        validate_production_config(_prod(evidentia_email_backend="smtp", evidentia_smtp_host=""))


def test_production_accepts_a_configured_smtp_sender():
    validate_production_config(
        _prod(evidentia_email_backend="smtp", evidentia_smtp_host="smtp.example.com")
    )


# --- BFF secret strength (H3) ---------------------------------------------
#
# The old gate was "32 characters and 8 distinct characters", which happily
# accepted `abcd1234abcd1234abcd1234abcd1234`. Length is not unpredictability, and
# a guessable BFF secret is worth exactly as much as no BFF secret: the attacker
# reaches the backend directly, forges X-Forwarded-For, and every per-IP limit in
# the system stops working. Production now requires a *generated* secret.


# Weak shapes shared by both gated secrets (the BFF shared secret and the JWT
# signing key): each of these defeats a naive length-plus-variety check.
WEAK_SECRET_SHAPES = {
    # The value that defeated the previous gate: 32 chars, 8 distinct chars.
    "old_gate_passer": "abcd1234abcd1234abcd1234abcd1234",
    "repeated_block_long": "abcd1234" * 8,
    "repeated_block_pair": "a1b2" * 16,
    "single_char_repeat": "a" * 40,
    "sequential_run": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ",
    "sequential_digits": "01234567890123456789012345678901234567890",
    "dictionary_like": "supersecretproductionvaluefortheevidentiabff",
    "words_only": "correcthorsebatterystaplemountainriverclouds",
    "low_entropy_32_char": "aaaaaaaabbbbbbbbccccccccdddddddd",
    "known_weak": "changeme",
    "too_short": "short",
    "thirty_one_chars": "Zx4Qm9Lp2Rv7Yb3Nc8Hd1Jf6Sg0Aq5U",
    "only_16_random_bytes": secrets.token_urlsafe(16),
    "not_an_encoding": "Zx4Qm9Lp!2Rv7Yb3Nc8Hd1Jf6Sg0Aq5Ue2Ir$%^&*()_+",
}


@pytest.mark.parametrize("name,weak", sorted(WEAK_SECRET_SHAPES.items()))
def test_production_refuses_a_weak_bff_secret(name, weak):
    assert bff_secret_problem(weak), f"{name}: {weak!r} was accepted"
    with pytest.raises(RuntimeError, match="EVIDENTIA_BFF_SECRET"):
        validate_production_config(
            _prod(evidentia_trusted_proxy_count=1, evidentia_bff_secret=weak)
        )


def test_production_refuses_an_empty_bff_secret_when_trusting_a_proxy():
    with pytest.raises(RuntimeError, match="EVIDENTIA_BFF_SECRET"):
        validate_production_config(
            _prod(evidentia_trusted_proxy_count=1, evidentia_bff_secret="   ")
        )


@pytest.mark.parametrize("generator", [lambda: secrets.token_urlsafe(32), lambda: secrets.token_hex(32)])
def test_production_accepts_a_generated_32_byte_secret(generator):
    """The documented generation command must actually produce an accepted value —
    for both supported encodings, not just the one the author happened to try."""
    for _ in range(50):  # the gate is statistical; it must not reject real output
        generated = generator()
        assert bff_secret_problem(generated) is None, f"rejected a generated secret: {generated}"
    validate_production_config(
        _prod(evidentia_trusted_proxy_count=1, evidentia_bff_secret=generator())
    )


def test_a_generated_secret_survives_surrounding_whitespace():
    """`.env` files routinely leave a trailing newline or space."""
    assert bff_secret_problem(f"  {STRONG_BFF_SECRET}\n") is None


def test_the_error_message_tells_the_operator_how_to_generate_one():
    problem = bff_secret_problem("abcd1234abcd1234abcd1234abcd1234")
    assert "secrets.token_urlsafe(32)" in problem


def test_production_accepts_a_strong_bff_secret():
    validate_production_config(
        _prod(evidentia_trusted_proxy_count=1, evidentia_bff_secret=STRONG_BFF_SECRET)
    )


# --- JWT secret strength (parity with the BFF gate) ------------------------
#
# The JWT signing key kept the older "≥32 chars, ≥8 distinct" check long after the
# BFF secret got the generated-secret gate — so the exact value that motivated H3
# (`abcd1234abcd1234abcd1234abcd1234`) still signed every access token in every
# tenant. Production now requires a generated key for both.


def test_production_refuses_the_previously_accepted_weak_jwt_secret():
    """The regression that motivated this gate: 32 chars + 8 distinct chars
    sailed through the old JWT check while being guessable in seconds."""
    weak = "abcd1234abcd1234abcd1234abcd1234"
    assert jwt_secret_problem(weak), "the old gate-passer was accepted as a JWT key"
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_config(_prod(jwt_secret=weak))


@pytest.mark.parametrize("name,weak", sorted(WEAK_SECRET_SHAPES.items()))
def test_production_refuses_a_weak_jwt_secret(name, weak):
    assert jwt_secret_problem(weak), f"{name}: {weak!r} was accepted as a JWT key"
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_config(_prod(jwt_secret=weak))


@pytest.mark.parametrize(
    "generator",
    [
        lambda: secrets.token_urlsafe(32),
        lambda: secrets.token_urlsafe(48),
        lambda: secrets.token_hex(32),
    ],
)
def test_production_accepts_a_generated_jwt_secret(generator):
    """Both documented encodings of ≥32 random bytes must be accepted — the gate
    is statistical and must not reject real generator output."""
    for _ in range(50):
        generated = generator()
        assert jwt_secret_problem(generated) is None, f"rejected a generated key: {generated}"
    validate_production_config(_prod(jwt_secret=generator()))


def test_the_jwt_error_message_tells_the_operator_how_to_generate_one():
    problem = jwt_secret_problem("abcd1234abcd1234abcd1234abcd1234")
    assert "secrets.token_urlsafe(48)" in problem


def test_development_still_runs_on_the_dev_default_jwt_secret():
    """The gate is production-only; local development stays zero-config."""
    s = Settings(evidentia_env="development", jwt_secret=DEFAULT_JWT_SECRET)
    assert s.effective_jwt_secret() == DEFAULT_JWT_SECRET


def test_a_jwt_forged_with_the_old_dev_default_secret_is_rejected(client, alice, monkeypatch):
    """The dev default is public (it is in the source), so any deployment that
    ever verified tokens against it was mintable-by-anyone. Once the deployment
    holds a real generated key, a token signed with the old default must be
    worthless — and so must any session issued under it."""
    from datetime import datetime, timedelta, timezone

    from app.core import security
    from app.core.config import get_settings

    # alice's current token was signed with the dev default. Rotate the
    # deployment onto a real generated key.
    monkeypatch.setattr(get_settings(), "jwt_secret", STRONG_SECRET)

    forged = security.jwt.encode(
        {
            "sub": alice.user_id,
            "email": alice.email,
            "typ": "access",
            "tv": 0,
            "jti": "forged",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        DEFAULT_JWT_SECRET,
        algorithm="HS256",
    )
    assert security.decode_access_token(forged) is None
    assert (
        client.get("/api/reports", headers={"Authorization": f"Bearer {forged}"}).status_code
        == 401
    ), "a token signed with the old dev/default secret was accepted"

    # The session minted under the old key dies with it.
    assert alice.get("/api/reports").status_code == 401


def test_bff_guard_uses_a_constant_time_comparison():
    """Byte-by-byte comparison would let an attacker recover the secret by timing."""
    import inspect

    from app.middleware import bff_guard

    source = inspect.getsource(bff_guard)
    assert "compare_digest" in source
    assert "presented == secret" not in source


def test_production_refuses_wildcard_cors():
    with pytest.raises(RuntimeError, match="CORS"):
        validate_production_config(_prod(evidentia_cors_origins="*"))


def test_all_problems_are_reported_at_once():
    with pytest.raises(RuntimeError) as exc:
        validate_production_config(
            _prod(
                jwt_secret="weak",
                evidentia_email_backend="console",
                evidentia_cors_origins="*",
            )
        )
    message = str(exc.value)
    assert "JWT_SECRET" in message and "console" in message and "CORS" in message


# --- BFF guard (direct-backend access) ------------------------------------


@pytest.fixture
def bff_secret(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "evidentia_bff_secret", "top-secret-bff-value")
    return "top-secret-bff-value"


def test_direct_backend_access_is_refused_when_a_bff_secret_is_set(client, bff_secret):
    """An attacker who reaches the backend directly cannot forge X-Forwarded-For,
    because they cannot present the BFF secret."""
    res = client.post(
        "/api/auth/login",
        json={"email": "a@acme.co", "password": VALID_PASSWORD},
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    assert res.status_code == 403
    assert res.json()["code"] == "direct_access_denied"


def test_requests_carrying_the_bff_secret_are_allowed(client, bff_secret):
    res = client.post(
        "/api/auth/login",
        json={"email": "nobody@acme.co", "password": VALID_PASSWORD},
        headers={"X-Evidentia-BFF": bff_secret},
    )
    assert res.status_code == 401  # reached the handler; bad credentials


def test_a_wrong_bff_secret_is_refused(client, bff_secret):
    res = client.get("/api/reports", headers={"X-Evidentia-BFF": "guess"})
    assert res.status_code == 403


def test_health_is_exempt_so_probes_still_work(client, bff_secret):
    assert client.get("/health").status_code == 200


# --- access-token revocation (token_version) ------------------------------


def test_password_reset_invalidates_outstanding_access_tokens(client, outbox):
    """An access token stolen before a reset must not survive it."""
    acct = register(client, "reset-me@acme.co")
    assert acct.get("/api/reports").status_code == 200  # token works

    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": acct.email})
    token = outbox[0].body.split("token=")[1].split()[0]
    client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "password": "a-brand-new-password"},
    )

    # The *same* access token is now dead, without waiting for its TTL.
    assert acct.get("/api/reports").status_code == 401


def test_logout_all_invalidates_outstanding_access_tokens(client):
    acct = register(client, "logout-all@acme.co")
    assert acct.get("/api/reports").status_code == 200

    assert acct.post("/api/auth/logout-all").status_code == 200
    assert acct.get("/api/reports").status_code == 401


def test_a_fresh_login_after_revocation_works(client):
    acct = register(client, "relogin@acme.co")
    acct.post("/api/auth/logout-all")

    res = client.post("/api/auth/login", json={"email": acct.email, "password": VALID_PASSWORD})
    assert res.status_code == 200
    new_token = res.json()["accessToken"]
    assert client.get(
        "/api/reports", headers={"Authorization": f"Bearer {new_token}"}
    ).status_code == 200
