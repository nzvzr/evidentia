"""Rate limiting, trusted-proxy IP resolution, and request/field size limits."""

from __future__ import annotations

import pytest

from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.ratelimit import (
    FakeClock,
    RateLimitExceeded,
    RateLimiter,
    RateLimitRule,
)
from tests.conftest import VALID_PASSWORD, register, seed_finalized_document

RATE_LIMITED = 429


def _login(client, email="nobody@acme.co", password="wrong-password-x", **kw):
    return client.post("/api/auth/login", json={"email": email, "password": password}, **kw)


# --------------------------------------------------------------------------
# The limiter itself
# --------------------------------------------------------------------------


def test_fixed_window_allows_up_to_the_limit_then_blocks():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    rule = RateLimitRule("t", limit=3, window_seconds=60)

    for _ in range(3):
        limiter.check(rule, "ip-1")  # at the limit, still allowed

    with pytest.raises(RateLimitExceeded):
        limiter.check(rule, "ip-1")  # one over


def test_window_expiry_restores_budget():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    rule = RateLimitRule("t", limit=2, window_seconds=60)

    limiter.check(rule, "k")
    limiter.check(rule, "k")
    with pytest.raises(RateLimitExceeded):
        limiter.check(rule, "k")

    clock.advance(60)
    limiter.check(rule, "k")  # new window


def test_retry_after_is_the_time_to_window_end():
    clock = FakeClock(start=1000.0)
    limiter = RateLimiter(clock=clock)
    rule = RateLimitRule("t", limit=1, window_seconds=100)

    limiter.check(rule, "k")
    with pytest.raises(RateLimitExceeded) as exc:
        limiter.check(rule, "k")
    assert 1 <= exc.value.retry_after <= 100


def test_identities_and_rules_have_independent_budgets():
    limiter = RateLimiter(clock=FakeClock())
    rule_a = RateLimitRule("a", limit=1, window_seconds=60)
    rule_b = RateLimitRule("b", limit=1, window_seconds=60)

    limiter.check(rule_a, "x")
    limiter.check(rule_a, "y")  # different identity
    limiter.check(rule_b, "x")  # different rule


def test_check_all_short_circuits_on_the_primary_rule():
    """The FIRST rule is the primary (client IP), whose key space an attacker
    cannot inflate. Once it is blocked, no further keys are created — that is what
    stops a unique-email flood from growing the store unboundedly."""
    limiter = RateLimiter(clock=FakeClock())
    ip_rule = RateLimitRule("ip", limit=1, window_seconds=60)
    acct_rule = RateLimitRule("acct", limit=5, window_seconds=60)

    limiter.check_all([(ip_rule, "1.1.1.1"), (acct_rule, "a@b.co")])
    size_after_first = limiter.size()

    # IP budget is now exhausted; a flood of unique accounts must mint no keys.
    for i in range(50):
        with pytest.raises(RateLimitExceeded):
            limiter.check_all([(ip_rule, "1.1.1.1"), (acct_rule, f"flood{i}@spam.co")])

    assert limiter.size() == size_after_first, "blocked IP still created account buckets"


def test_secondary_rules_are_all_counted_when_the_primary_passes():
    """Among the non-primary rules, tripping one must not let a caller dodge
    another — they are all counted."""
    limiter = RateLimiter(clock=FakeClock())
    ip_rule = RateLimitRule("ip", limit=100, window_seconds=60)
    a_rule = RateLimitRule("a", limit=1, window_seconds=60)
    b_rule = RateLimitRule("b", limit=3, window_seconds=60)

    limiter.check_all([(ip_rule, "1.1.1.1"), (a_rule, "x"), (b_rule, "y")])
    for _ in range(2):
        with pytest.raises(RateLimitExceeded):
            limiter.check_all([(ip_rule, "1.1.1.1"), (a_rule, "x"), (b_rule, "y")])

    # `b` was counted on all three calls even though `a` raised each time.
    with pytest.raises(RateLimitExceeded):
        limiter.check(b_rule, "y")


# --------------------------------------------------------------------------
# Login brute force
# --------------------------------------------------------------------------


def test_login_brute_force_is_blocked_per_account(client, alice, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rl_login_account_limit", 3)

    for _ in range(3):
        assert _login(client, alice.email).status_code == 401

    res = _login(client, alice.email)
    assert res.status_code == RATE_LIMITED
    assert res.json()["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


def test_login_throttling_is_not_an_account_existence_oracle(client, alice, monkeypatch):
    """A nonexistent address must burn budget and throttle exactly like a real one."""
    s = get_settings()
    monkeypatch.setattr(s, "rl_login_account_limit", 2)
    monkeypatch.setattr(s, "rl_login_ip_limit", 1000)

    real = [_login(client, alice.email).status_code for _ in range(3)]
    ghost = [_login(client, "ghost@nowhere.co").status_code for _ in range(3)]
    assert real == ghost == [401, 401, RATE_LIMITED]


def test_login_correct_password_still_blocked_once_throttled(client, alice, monkeypatch):
    """Throttling gates the endpoint, not just wrong guesses — otherwise the
    attacker learns the password by watching the response flip to 200."""
    s = get_settings()
    monkeypatch.setattr(s, "rl_login_account_limit", 2)

    _login(client, alice.email)
    _login(client, alice.email)

    res = client.post("/api/auth/login", json={"email": alice.email, "password": VALID_PASSWORD})
    assert res.status_code == RATE_LIMITED


def test_account_limit_survives_ip_rotation(client, alice, monkeypatch):
    """Rotating the source IP must not reset the per-account budget."""
    s = get_settings()
    monkeypatch.setattr(s, "evidentia_trusted_proxy_count", 1)
    monkeypatch.setattr(s, "rl_login_account_limit", 3)
    monkeypatch.setattr(s, "rl_login_ip_limit", 1000)

    codes = [
        _login(client, alice.email, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, RATE_LIMITED, RATE_LIMITED]


def test_ip_limit_blocks_spraying_across_many_accounts(client, monkeypatch):
    """Password spraying: one IP, many accounts — the per-IP budget catches it."""
    s = get_settings()
    monkeypatch.setattr(s, "rl_login_ip_limit", 3)
    monkeypatch.setattr(s, "rl_login_account_limit", 1000)

    codes = [_login(client, f"user{i}@acme.co").status_code for i in range(5)]
    assert codes == [401, 401, 401, RATE_LIMITED, RATE_LIMITED]


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_registration_is_rate_limited_per_ip(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rl_register_ip_limit", 2)

    assert register(client, "one@acme.co").user_id
    assert register(client, "two@acme.co").user_id
    res = client.post(
        "/api/auth/register", json={"email": "three@acme.co", "password": VALID_PASSWORD}
    )
    assert res.status_code == RATE_LIMITED
    assert res.json()["code"] == "rate_limited"


# --------------------------------------------------------------------------
# Password reset flooding
# --------------------------------------------------------------------------


def test_password_reset_flooding_is_capped_per_account(client, alice, outbox, monkeypatch):
    """An attacker must not be able to mailbomb a user with reset links."""
    s = get_settings()
    monkeypatch.setattr(s, "rl_password_reset_account_limit", 2)
    monkeypatch.setattr(s, "rl_password_reset_ip_limit", 1000)
    outbox.clear()

    codes = [
        client.post("/api/auth/password-reset/request", json={"email": alice.email}).status_code
        for _ in range(4)
    ]
    assert codes == [202, 202, RATE_LIMITED, RATE_LIMITED]
    assert len(outbox) == 2, "no further emails may be sent once throttled"


def test_password_reset_flooding_capped_across_ip_rotation(client, alice, outbox, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "evidentia_trusted_proxy_count", 1)
    monkeypatch.setattr(s, "rl_password_reset_account_limit", 2)
    monkeypatch.setattr(s, "rl_password_reset_ip_limit", 1000)
    outbox.clear()

    for i in range(5):
        client.post(
            "/api/auth/password-reset/request",
            json={"email": alice.email},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
    assert len(outbox) == 2


def test_reset_throttling_does_not_reveal_whether_the_email_exists(client, alice, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rl_password_reset_account_limit", 1)
    monkeypatch.setattr(s, "rl_password_reset_ip_limit", 1000)

    real = [
        client.post("/api/auth/password-reset/request", json={"email": alice.email}).status_code
        for _ in range(2)
    ]
    ghost = [
        client.post(
            "/api/auth/password-reset/request", json={"email": "ghost@nowhere.co"}
        ).status_code
        for _ in range(2)
    ]
    assert real == ghost == [202, RATE_LIMITED]


def test_reset_confirm_token_guessing_is_capped(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rl_reset_confirm_ip_limit", 3)

    codes = [
        client.post(
            "/api/auth/password-reset/confirm",
            json={"token": f"guess-{i}", "password": VALID_PASSWORD},
        ).status_code
        for i in range(5)
    ]
    assert codes == [400, 400, 400, RATE_LIMITED, RATE_LIMITED]


# --------------------------------------------------------------------------
# Refresh abuse
# --------------------------------------------------------------------------


def test_refresh_abuse_is_capped_per_token(client, alice, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rl_refresh_token_limit", 2)
    monkeypatch.setattr(s, "rl_refresh_ip_limit", 1000)

    # First rotation succeeds; the second replays a spent token (401, reuse
    # detection); the third is refused by the limiter before any DB work.
    assert client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refreshToken": alice.refresh}).status_code == 401
    res = client.post("/api/auth/refresh", json={"refreshToken": alice.refresh})
    assert res.status_code == RATE_LIMITED


def test_refresh_abuse_is_capped_per_ip(client, alice, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "rl_refresh_ip_limit", 3)
    monkeypatch.setattr(s, "rl_refresh_token_limit", 1000)

    codes = [
        client.post("/api/auth/refresh", json={"refreshToken": f"bogus-{i}"}).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, RATE_LIMITED, RATE_LIMITED]


# --------------------------------------------------------------------------
# Generation (LLM spend)
# --------------------------------------------------------------------------


GEN = {"market": "EMEA", "persona": "Support Agent"}


def test_generation_is_capped_per_user(client, alice, monkeypatch, tenant_generation):
    s = get_settings()
    monkeypatch.setattr(s, "rl_generate_user_limit", 2)

    assert alice.post("/api/generate-workflow", json=GEN).status_code == 200
    assert alice.post("/api/generate-workflow", json=GEN).status_code == 200

    res = alice.post("/api/generate-workflow", json=GEN)
    assert res.status_code == RATE_LIMITED
    assert res.json()["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


def test_generation_is_capped_per_tenant_across_members(
    client, alice, monkeypatch, tenant_generation
):
    """One organization cannot burn the shared LLM budget by fanning out across
    its own members — the tenant budget is separate from the per-user one."""
    s = get_settings()
    monkeypatch.setattr(s, "rl_generate_tenant_limit", 2)
    monkeypatch.setattr(s, "rl_generate_user_limit", 1000)
    monkeypatch.setattr(s, "rl_generate_ip_limit", 1000)

    teammate = register(client, "teammate@acme.co", company="Teammate Personal")
    alice.post("/api/companies/members", json={"email": teammate.email, "role": "member"})
    team_headers = {**teammate.headers, "X-Company-Id": alice.company_id}

    assert alice.post("/api/generate-workflow", json=GEN).status_code == 200
    assert client.post("/api/generate-workflow", json=GEN, headers=team_headers).status_code == 200

    # Tenant budget exhausted — even though this member has spent nothing.
    res = client.post("/api/generate-workflow", json=GEN, headers=team_headers)
    assert res.status_code == RATE_LIMITED


def test_generation_budget_is_not_shared_between_tenants(
    client, alice, bob, monkeypatch, tenant_generation, session_factory
):
    s = get_settings()
    monkeypatch.setattr(s, "rl_generate_tenant_limit", 1)
    monkeypatch.setattr(s, "rl_generate_user_limit", 1000)
    monkeypatch.setattr(s, "rl_generate_ip_limit", 1000)
    seed_finalized_document(bob, session_factory, monkeypatch, filename="bob.md")

    assert alice.post("/api/generate-workflow", json=GEN).status_code == 200
    assert alice.post("/api/generate-workflow", json=GEN).status_code == RATE_LIMITED
    # Bob's separate organization is unaffected.
    assert bob.post("/api/generate-workflow", json=GEN).status_code == 200


def test_anonymous_generation_is_401_not_429(client, monkeypatch):
    """Auth is checked first: an unauthenticated flood never consumes the
    generation budget of a real user or tenant."""
    monkeypatch.setattr(get_settings(), "rl_generate_ip_limit", 1)
    for _ in range(3):
        assert client.post("/api/generate-workflow", json=GEN).status_code == 401


# --------------------------------------------------------------------------
# Trusted proxy / forged X-Forwarded-For
# --------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, peer: str, xff: str | None = None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


def test_xff_ignored_when_no_proxy_is_trusted(monkeypatch):
    monkeypatch.setattr(get_settings(), "evidentia_trusted_proxy_count", 0)
    req = _FakeRequest(peer="10.0.0.1", xff="1.2.3.4")
    assert get_client_ip(req) == "10.0.0.1", "XFF must be ignored with 0 trusted hops"


def test_forged_xff_prefix_cannot_change_the_key(monkeypatch):
    """With 1 trusted proxy, only the rightmost entry (written by that proxy) is
    trusted. A client prepending its own entries cannot shift the identity."""
    monkeypatch.setattr(get_settings(), "evidentia_trusted_proxy_count", 1)
    forged = _FakeRequest(peer="10.0.0.1", xff="6.6.6.6, 9.9.9.9, 203.0.113.7")
    assert get_client_ip(forged) == "203.0.113.7"


def test_two_trusted_hops_take_the_second_from_the_right(monkeypatch):
    monkeypatch.setattr(get_settings(), "evidentia_trusted_proxy_count", 2)
    req = _FakeRequest(peer="10.0.0.1", xff="6.6.6.6, 203.0.113.7, 172.16.0.9")
    assert get_client_ip(req) == "203.0.113.7"


def test_short_or_garbage_xff_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setattr(get_settings(), "evidentia_trusted_proxy_count", 2)
    assert get_client_ip(_FakeRequest("10.0.0.1", "203.0.113.7")) == "10.0.0.1"
    monkeypatch.setattr(get_settings(), "evidentia_trusted_proxy_count", 1)
    assert get_client_ip(_FakeRequest("10.0.0.1", "not-an-ip")) == "10.0.0.1"


def test_forged_xff_cannot_reset_a_login_budget(client, alice, monkeypatch):
    """End-to-end: with 0 trusted hops, spoofing XFF does not rotate the IP key."""
    s = get_settings()
    monkeypatch.setattr(s, "evidentia_trusted_proxy_count", 0)
    monkeypatch.setattr(s, "rl_login_ip_limit", 3)
    monkeypatch.setattr(s, "rl_login_account_limit", 1000)

    codes = [
        _login(client, f"u{i}@acme.co", headers={"X-Forwarded-For": f"1.2.3.{i}"}).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, RATE_LIMITED, RATE_LIMITED]


# --------------------------------------------------------------------------
# Body and field limits
# --------------------------------------------------------------------------


def test_oversized_body_is_rejected_with_413(client):
    huge = "x" * (get_settings().evidentia_max_body_bytes + 1024)
    res = client.post("/api/auth/login", json={"email": "a@b.co", "password": huge})
    assert res.status_code == 413
    assert res.json()["code"] == "payload_too_large"


def test_overlong_email_is_rejected(client):
    long_email = "a" * 250 + "@acme.co"
    res = client.post("/api/auth/register", json={"email": long_email, "password": VALID_PASSWORD})
    assert res.status_code == 422


def test_overlong_password_is_rejected(client):
    res = client.post(
        "/api/auth/register", json={"email": "p@acme.co", "password": "x" * 500}
    )
    assert res.status_code == 422


def test_login_password_field_is_bounded(client):
    res = client.post("/api/auth/login", json={"email": "a@acme.co", "password": "x" * 500})
    assert res.status_code == 422


def test_too_many_selected_documents_is_rejected(client, alice):
    res = alice.post(
        "/api/generate-workflow",
        json={"market": "EMEA", "persona": "Support Agent", "selectedDocumentIds": [f"d{i}" for i in range(51)]},
    )
    assert res.status_code == 422


def test_overlong_text_fields_are_rejected(client, alice):
    assert alice.post(
        "/api/generate-workflow",
        json={"market": "EMEA", "persona": "Support Agent", "customPersona": "x" * 5000},
    ).status_code == 422
    assert alice.post("/api/documents", json={"title": "x" * 500}).status_code == 422
    assert alice.post(
        "/api/documents", json={"title": "ok", "contentText": "x" * 200_001}
    ).status_code == 422


def test_overlong_refresh_token_is_rejected(client):
    res = client.post("/api/auth/refresh", json={"refreshToken": "x" * 1000})
    assert res.status_code == 422
