"""Authentication and tenancy dependencies.

Every tenant-scoped endpoint depends on `get_company_context`, which is the only
way to obtain a `company_id` inside a request handler. A `company_id` can never
originate from the request body or an unchecked query parameter — it is always
derived from a membership row belonging to the authenticated user.

The old `resolve_company_id` (which fell back to a shared demo company for any
anonymous caller) is deliberately gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.db_models import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER, Company, User
from app.repositories import companies as companies_repo
from app.repositories import memberships as memberships_repo
from app.repositories import users as users_repo

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "not_authenticated", "message": "Not authenticated"},
    headers={"WWW-Authenticate": "Bearer"},
)

# Cross-tenant access is reported as 404, not 403: a 403 would confirm that the
# id exists, which is itself an information leak (resource enumeration).
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer access token to an active user, or 401."""
    token = _bearer(authorization)
    if not token:
        raise _UNAUTHENTICATED

    claims = decode_access_token(token)
    if not claims:
        raise _UNAUTHENTICATED

    user = users_repo.get_user(db, claims["sub"])
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    # Stateless-token revocation: a password reset or logout-all bumps the user's
    # token_version, which strands every access token minted before it — including
    # one an attacker may already hold.
    if int(claims.get("tv", -1)) != int(user.token_version or 0):
        raise _UNAUTHENTICATED

    return user


def get_verified_user(user: User = Depends(get_current_user)) -> User:
    """A user who has confirmed their email address.

    Only enforced when EVIDENTIA_REQUIRE_EMAIL_VERIFICATION is on, so the demo
    stays usable out of the box while production can require confirmation.
    """
    if get_settings().requires_email_verification() and not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address not verified",
        )
    return user


@dataclass
class CompanyContext:
    """An authenticated user *proven* to be a member of a specific company.

    Holding one of these is the authorisation to touch that company's rows —
    `company_id` here is always membership-derived.
    """

    user: User
    company: Company
    role: str

    @property
    def company_id(self) -> str:
        return self.company.id

    @property
    def user_id(self) -> str:
        return self.user.id

    def has_role(self, minimum: str) -> bool:
        return memberships_repo.role_at_least(self.role, minimum)


def get_company_context(
    company_id: Optional[str] = Query(default=None, alias="company_id"),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
) -> CompanyContext:
    """Resolve the active tenant for this request.

    The caller may *name* a company (query param or `X-Company-Id` header), but
    naming one grants nothing: it is only accepted if the user holds a
    membership in it. With no company named, the user's own single company is
    used; if they belong to several, they must choose one explicitly.
    """
    requested = company_id or x_company_id

    if requested:
        membership = memberships_repo.get_membership(db, requested, user.id)
        if membership is None:
            # Not a member → the company does not exist, as far as this user goes.
            raise _NOT_FOUND
        company = companies_repo.get_company(db, requested)
        if company is None:
            raise _NOT_FOUND
        return CompanyContext(user=user, company=company, role=membership.role)

    owned = memberships_repo.list_companies_for_user(db, user.id)
    if not owned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "company_membership_required",
                "message": "User does not belong to any organization",
            },
        )
    if len(owned) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multiple organizations available; specify company_id",
        )
    company, membership = owned[0]
    return CompanyContext(user=user, company=company, role=membership.role)


def require_role(minimum: str):
    """Dependency factory enforcing the owner > admin > member hierarchy."""

    def _guard(ctx: CompanyContext = Depends(get_company_context)) -> CompanyContext:
        if not ctx.has_role(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum} role",
            )
        return ctx

    return _guard


require_member = require_role(ROLE_MEMBER)
require_admin = require_role(ROLE_ADMIN)
require_owner = require_role(ROLE_OWNER)
