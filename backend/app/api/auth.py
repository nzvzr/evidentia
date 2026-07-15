"""Authentication endpoints.

Flow summary
------------
register  -> creates the user, their organization, and an owner membership;
             issues an email-verification token.
login     -> password check -> access JWT (short) + refresh token (rotating).
refresh   -> rotates the refresh token; reuse of a spent token burns the family.
logout    -> revokes the presented refresh token. logout-all revokes every one.

Enumeration safety: login always answers with the same 401 regardless of whether
the email exists, and the password-reset request always answers 202 — neither
reveals whether an account is registered.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.limits import (
    enforce_login,
    enforce_verify_email_account,
    enforce_password_reset_confirm,
    enforce_password_reset_request,
    enforce_refresh,
    enforce_register,
    enforce_verify_email,
)
from app.core import security
from app.core.config import get_settings
from app.db.session import get_db
from app.models.db_models import ROLE_OWNER, User
from app.models.schemas import (
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    VerifyEmailConfirm,
    VerifyEmailRequest,
)
from app.repositories import companies as companies_repo
from app.repositories import memberships as memberships_repo
from app.repositories import tokens as tokens_repo
from app.repositories import users as users_repo
from app.services import email as email_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "org"


def _unique_slug(db: Session, base: str) -> str:
    slug = _slugify(base)
    candidate, n = slug, 2
    while companies_repo.get_by_slug(db, candidate):
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def _serialize_user(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "emailVerified": user.is_verified,
    }


def _session_payload(db: Session, user: User) -> Dict[str, Any]:
    """Issue a fresh token pair plus the user's memberships."""
    access = security.create_access_token(user.id, user.email, token_version=user.token_version or 0)
    refresh, _ = tokens_repo.issue_refresh_token(db, user.id)
    memberships = [
        {"id": c.id, "name": c.name, "slug": c.slug, "role": m.role}
        for c, m in memberships_repo.list_companies_for_user(db, user.id)
    ]
    return {
        "user": _serialize_user(user),
        "accessToken": access,
        "refreshToken": refresh,
        "tokenType": "bearer",
        "expiresIn": get_settings().access_token_ttl_minutes * 60,
        "companies": memberships,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Create a user, their organization, and their owner membership."""
    # Throttled before the DB is touched, and keyed on the submitted address
    # whether or not it exists — so 429 is never an account-existence signal.
    enforce_register(request, body.email)

    email = users_repo.normalize_email(body.email)
    if users_repo.get_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = users_repo.create_user(
        db,
        email=email,
        name=body.name,
        hashed_password=security.hash_password(body.password),
    )

    # Organization ownership: the registrant owns the company they create.
    company_name = (body.company or "").strip() or f"{body.name or email.split('@')[0]}'s organization"
    company = companies_repo.create_company(
        db,
        name=company_name,
        slug=_unique_slug(db, company_name),
        owner_id=user.id,
    )
    memberships_repo.add_member(db, company.id, user.id, role=ROLE_OWNER)

    verification_token = tokens_repo.issue_email_verification(db, user.id)
    payload = _session_payload(db, user)
    db.commit()

    # Email-verification hook. Delivery failure must not roll back registration.
    try:
        email_service.send_verification_email(user.email, verification_token)
    except Exception:  # noqa: BLE001 - never fail signup on mail delivery
        pass

    return payload


@router.post("/login")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    # Brute-force protection. Counted on the submitted email before lookup, so a
    # nonexistent address burns budget identically to a real one.
    enforce_login(request, body.email)

    candidate = users_repo.get_by_email(db, body.email)
    if candidate is None:
        # Spend the same work as a real verification so response time does not
        # disclose whether the account exists.
        security.dummy_verify()
        raise _INVALID_CREDENTIALS

    # The lock is taken BEFORE the password is checked, and the row is re-read
    # under it — the password decision and the session issuance are then one
    # critical section, serialized against every revocation.
    #
    # Verifying first and locking afterwards was exploitable: a login could
    # approve the OLD password, pause, let a concurrent password reset change the
    # password and revoke every session, and then resume under the lock and mint a
    # brand-new session carrying the *new* token_version. The reset appeared to
    # succeed while the pre-reset password had just handed out a live credential.
    user = users_repo.lock_user(db, candidate.id)
    if user is None:
        security.dummy_verify()
        raise _INVALID_CREDENTIALS
    if not user.is_active or not security.verify_password(body.password, user.hashed_password):
        raise _INVALID_CREDENTIALS

    payload = _session_payload(db, user)
    db.commit()
    return payload


@router.post("/refresh")
def refresh(request: Request, body: RefreshRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    # Per-IP and per-token budgets: a stolen refresh token cannot be ground
    # against the rotation machinery, and a bot cannot mint access tokens freely.
    enforce_refresh(request, body.refreshToken)

    # Identify the owner of the token, then take the user lock BEFORE rotating.
    # Rotation issues a *new* session; it must serialize with revocation, or the
    # child token could be written after a logout-all sweep and survive it.
    existing = tokens_repo.get_refresh_token(db, body.refreshToken)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    # The locked row is the authoritative one: token_version is read from inside
    # the critical section, so a revocation that committed while this request was
    # queued is already visible here.
    user = users_repo.lock_user(db, existing.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    new_refresh, user_id = tokens_repo.rotate_refresh_token(db, body.refreshToken)
    if not new_refresh or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    access = security.create_access_token(user.id, user.email, token_version=user.token_version or 0)
    db.commit()
    return {
        "user": _serialize_user(user),
        "accessToken": access,
        "refreshToken": new_refresh,
        "tokenType": "bearer",
        "expiresIn": get_settings().access_token_ttl_minutes * 60,
    }


@router.post("/logout")
def logout(body: LogoutRequest, db: Session = Depends(get_db)) -> Dict[str, bool]:
    """Revoke the presented refresh token. Idempotent: always reports ok, so a
    logout never leaks whether the token was valid."""
    if body.refreshToken:
        row = tokens_repo.get_refresh_token(db, body.refreshToken)
        if row is not None:
            tokens_repo.revoke_token(db, row)
            db.commit()
    return {"ok": True}


@router.post("/logout-all")
def logout_all(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Dict[str, bool]:
    """Revoke every session for the current user (all devices).

    Refresh tokens are revoked in the store; the token_version bump is what also
    strands every outstanding *access* token, which is otherwise stateless and
    would stay valid for its full TTL.
    """
    # One transaction: lock the user, revoke every refresh token, bump the access
    # token version. A refresh racing this either commits before the lock (and is
    # then swept by revoke_all) or waits and sees the new token_version.
    users_repo.lock_user(db, user.id)
    tokens_repo.revoke_all_for_user(db, user.id)
    users_repo.bump_token_version_by_id(db, user.id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {
        "user": _serialize_user(user),
        "companies": [
            {"id": c.id, "name": c.name, "slug": c.slug, "role": m.role}
            for c, m in memberships_repo.list_companies_for_user(db, user.id)
        ],
    }


# --------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------


@router.post("/verify-email/request", status_code=status.HTTP_202_ACCEPTED)
def request_verification(
    request: Request, body: VerifyEmailRequest, db: Session = Depends(get_db)
) -> Dict[str, bool]:
    """Re-send a verification link. Always 202 (no account enumeration)."""
    # Capped per address as well as per IP, so one mailbox cannot be flooded.
    enforce_verify_email_account(request, body.email)

    user = users_repo.get_by_email(db, body.email)
    if user is not None and not user.is_verified:
        token = tokens_repo.issue_email_verification(db, user.id)
        db.commit()
        try:
            email_service.send_verification_email(user.email, token)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


@router.post("/verify-email/confirm")
def confirm_verification(
    request: Request, body: VerifyEmailConfirm, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    enforce_verify_email(request)

    user_id = tokens_repo.consume_email_verification(db, body.token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    user = users_repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token")
    users_repo.mark_verified(db, user)
    db.commit()
    return {"ok": True, "user": _serialize_user(user)}


# --------------------------------------------------------------------------
# Password reset
# --------------------------------------------------------------------------


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    request: Request, body: PasswordResetRequest, db: Session = Depends(get_db)
) -> Dict[str, bool]:
    """Always 202, whether or not the address is registered."""
    # Anti-flooding: caps how many reset emails a single address (or IP) can be
    # made to receive. Keyed on the submitted address regardless of existence.
    enforce_password_reset_request(request, body.email)

    user = users_repo.get_by_email(db, body.email)
    if user is not None and user.is_active:
        token = tokens_repo.issue_password_reset(db, user.id)
        db.commit()
        try:
            email_service.send_password_reset_email(user.email, token)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


@router.post("/password-reset/confirm")
def confirm_password_reset(
    request: Request, body: PasswordResetConfirm, db: Session = Depends(get_db)
) -> Dict[str, bool]:
    # Caps guessing at the reset token itself.
    enforce_password_reset_confirm(request)

    # Identify the owner of the token, then take the user lock BEFORE burning it.
    # Everything that follows — the single-use check, the password change, the
    # revocation sweep and the token_version bump — happens inside that critical
    # section, so it serializes against every *issuer* of a session (login and
    # refresh both take the same lock). Without that, a login could verify the old
    # password just before the reset and mint its session just after.
    owner_id = tokens_repo.peek_password_reset(db, body.token)
    if not owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    user = users_repo.lock_user(db, owner_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")

    # Re-validated under the lock: two concurrent confirms of the same token
    # serialize here, so only the first one burns it.
    user_id = tokens_repo.consume_password_reset(db, body.token)
    if not user_id or user_id != user.id:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    users_repo.set_password(db, user, security.hash_password(body.password))
    users_repo.mark_verified(db, user)
    tokens_repo.revoke_all_for_user(db, user.id)
    users_repo.bump_token_version_by_id(db, user.id)
    db.commit()
    return {"ok": True}
