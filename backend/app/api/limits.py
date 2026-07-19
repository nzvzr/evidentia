"""Rate-limit policies for the auth and generation endpoints.

Every policy is enforced on a combination of identities so that neither axis
alone is a bypass:

* **account** — the *submitted* email, normalized. Counted before the user is
  looked up, so a nonexistent address consumes budget exactly like a real one.
  That is what keeps throttling from becoming an account-existence oracle.
* **client IP** — resolved through the trusted-proxy chain (core/client_ip.py),
  so rotating `X-Forwarded-For` does not reset the counter.
* **user / tenant** — for authenticated generation, which costs LLM spend.

Rules are rebuilt from settings on each call (cheap) so limits can be tuned via
env without a code change.
"""

from __future__ import annotations

from fastapi import Request

from app.core import security
from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.ratelimit import RateLimitRule, get_rate_limiter
from app.repositories.users import normalize_email


def _rule(name: str, limit: int, window: int) -> RateLimitRule:
    return RateLimitRule(name=name, limit=limit, window_seconds=window)


def enforce_login(request: Request, email: str) -> None:
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (_rule("login_ip", s.rl_login_ip_limit, s.rl_login_ip_window), get_client_ip(request)),
            (
                _rule("login_account", s.rl_login_account_limit, s.rl_login_account_window),
                normalize_email(email),
            ),
        ]
    )


def enforce_register(request: Request, email: str) -> None:
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (_rule("register_ip", s.rl_register_ip_limit, s.rl_register_ip_window), get_client_ip(request)),
            (
                _rule("register_account", s.rl_register_account_limit, s.rl_register_account_window),
                normalize_email(email),
            ),
        ]
    )


def enforce_refresh(request: Request, refresh_token: str) -> None:
    """Limited per IP and per *token* — a stolen token cannot be ground against
    the rotation machinery. The token is keyed by digest, never in plaintext."""
    s = get_settings()
    digest = security.hash_opaque_token(refresh_token) if refresh_token else ""
    get_rate_limiter().check_all(
        [
            (_rule("refresh_ip", s.rl_refresh_ip_limit, s.rl_refresh_ip_window), get_client_ip(request)),
            (_rule("refresh_token", s.rl_refresh_token_limit, s.rl_refresh_token_window), digest),
        ]
    )


def enforce_password_reset_request(request: Request, email: str) -> None:
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (
                _rule("pwreset_ip", s.rl_password_reset_ip_limit, s.rl_password_reset_ip_window),
                get_client_ip(request),
            ),
            (
                _rule(
                    "pwreset_account",
                    s.rl_password_reset_account_limit,
                    s.rl_password_reset_account_window,
                ),
                normalize_email(email),
            ),
        ]
    )


def enforce_company_create(request: Request, user_id: str) -> None:
    """Quota on organization creation (P1) — one user cannot spam tenants."""
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (
                _rule("company_create_ip", s.rl_register_ip_limit, s.rl_register_ip_window),
                get_client_ip(request),
            ),
            (
                _rule(
                    "company_create_user",
                    s.rl_company_create_user_limit,
                    s.rl_company_create_user_window,
                ),
                user_id,
            ),
        ]
    )


def enforce_password_reset_confirm(request: Request) -> None:
    """Keyed on IP only: the token is the secret, and keying on it would let an
    attacker enumerate which guesses were 'interesting' by watching for 429s."""
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (
                _rule("pwreset_confirm_ip", s.rl_reset_confirm_ip_limit, s.rl_reset_confirm_ip_window),
                get_client_ip(request),
            )
        ]
    )


def enforce_verify_email(request: Request) -> None:
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (
                _rule("verify_ip", s.rl_verify_email_ip_limit, s.rl_verify_email_ip_window),
                get_client_ip(request),
            )
        ]
    )


def enforce_generation(request: Request, user_id: str, company_id: str) -> None:
    """The LLM-spending budget: per IP, per user, and per tenant.

    The tenant budget is what stops one organization burning the shared API
    quota by fanning work out across its own members.
    """
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (_rule("gen_ip", s.rl_generate_ip_limit, s.rl_generate_ip_window), get_client_ip(request)),
            (_rule("gen_user", s.rl_generate_user_limit, s.rl_generate_user_window), user_id),
            (_rule("gen_tenant", s.rl_generate_tenant_limit, s.rl_generate_tenant_window), company_id),
        ]
    )


def enforce_export(request: Request, user_id: str, company_id: str) -> None:
    """The rendering budget: per IP, per user, and per tenant.

    Export is CPU-only (no LLM spend), so the limits are looser than generation,
    but still bounded so one caller cannot pin a worker rendering large documents
    in a tight loop. Enforced after authentication, so an anonymous flood is
    rejected by the 401 first and the budget is only spent by an attributable
    caller.
    """
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (_rule("export_ip", s.rl_export_ip_limit, s.rl_export_ip_window), get_client_ip(request)),
            (_rule("export_user", s.rl_export_user_limit, s.rl_export_user_window), user_id),
            (
                _rule("export_tenant", s.rl_export_tenant_limit, s.rl_export_tenant_window),
                company_id,
            ),
        ]
    )


def enforce_upload(request: Request, user_id: str, company_id: str) -> None:
    """The ingestion budget: per IP, per user, and per tenant — counted before
    any multipart parsing or file reading happens, so a throttled caller costs
    nothing beyond the check itself."""
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (_rule("upload_ip", s.rl_upload_ip_limit, s.rl_upload_ip_window), get_client_ip(request)),
            (_rule("upload_user", s.rl_upload_user_limit, s.rl_upload_user_window), user_id),
            (
                _rule("upload_tenant", s.rl_upload_tenant_limit, s.rl_upload_tenant_window),
                company_id,
            ),
        ]
    )


def enforce_verify_email_account(request: Request, email: str) -> None:
    """Verification-link requests, capped per address as well as per IP, so a
    single mailbox cannot be flooded with confirmation mail."""
    s = get_settings()
    get_rate_limiter().check_all(
        [
            (
                _rule("verify_ip", s.rl_verify_email_ip_limit, s.rl_verify_email_ip_window),
                get_client_ip(request),
            ),
            (
                _rule(
                    "verify_account",
                    s.rl_verify_email_account_limit,
                    s.rl_verify_email_account_window,
                ),
                normalize_email(email),
            ),
        ]
    )
