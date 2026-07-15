"""Company (organization) and membership endpoints.

`GET /api/companies` returns only the companies the caller is a member of — the
previous global listing enumerated every tenant in the system.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    CompanyContext,
    get_company_context,
    get_verified_user,
    require_admin,
    require_owner,
)
from app.api.limits import enforce_company_create
from app.core.security import hash_password  # noqa: F401  (kept for parity with auth)
from app.db.session import get_db
from app.models.db_models import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER, User
from app.models.schemas import CompanyCreate, MemberInvite, MemberRoleUpdate, OwnershipTransfer
from app.repositories import companies as companies_repo
from app.repositories import memberships as memberships_repo
from app.repositories import users as users_repo
from app.api.deps import get_current_user

router = APIRouter(prefix="/api/companies", tags=["companies"])

_ASSIGNABLE_ROLES = {ROLE_OWNER, ROLE_ADMIN, ROLE_MEMBER}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "company"


def _serialize(company, role: str | None = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": company.id,
        "name": company.name,
        "slug": company.slug,
        "ownerId": company.owner_id,
        "createdAt": company.created_at.isoformat() if company.created_at else None,
    }
    if role is not None:
        data["role"] = role
    return data


def _serialize_member(member, user: User) -> Dict[str, Any]:
    return {
        "userId": user.id,
        "email": user.email,
        "name": user.name,
        "role": member.role,
        "emailVerified": user.is_verified,
        "joinedAt": member.created_at.isoformat() if member.created_at else None,
    }


@router.get("")
def list_companies(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Dict[str, List[Dict[str, Any]]]:
    """Only the caller's own memberships — never the full tenant list."""
    rows = memberships_repo.list_companies_for_user(db, user.id)
    return {"companies": [_serialize(c, m.role) for c, m in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_company(
    request: Request,
    body: CompanyCreate,
    user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create an organization. The creator becomes its owner.

    Requires a verified user (when verification is enforced) and is quota'd, so a
    single account cannot spam tenants into existence.
    """
    enforce_company_create(request, user.id)

    slug = body.slug or _slugify(body.name)
    if companies_repo.get_by_slug(db, slug):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Company slug already exists")
    company = companies_repo.create_company(db, name=body.name, slug=slug, owner_id=user.id)
    memberships_repo.add_member(db, company.id, user.id, role=ROLE_OWNER)
    db.commit()
    db.refresh(company)
    return _serialize(company, ROLE_OWNER)


@router.get("/current")
def get_current_company(ctx: CompanyContext = Depends(get_company_context)) -> Dict[str, Any]:
    return _serialize(ctx.company, ctx.role)


# --------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------


@router.get("/members")
def list_members(
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    rows = memberships_repo.list_members(db, ctx.company_id)
    return {"members": [_serialize_member(m, u) for m, u in rows]}


@router.post("/members", status_code=status.HTTP_201_CREATED)
def add_member(
    body: MemberInvite,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Add a NEW member. This endpoint only ever creates.

    It used to upsert, which meant an admin could re-POST the *owner* with
    role=member and silently demote them. An existing membership is now a 409;
    role changes go through PATCH, which enforces the owner invariants.

    Creating a member is a role grant, so it runs through the same locked
    authorization gate as PATCH. `ctx.role` is NOT consulted: it was captured when
    the request was authenticated, and an actor demoted in the meantime must not
    still be able to invite (or mint admins) on the strength of it.
    """
    role = (body.role or ROLE_MEMBER).lower()
    if role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    user = users_repo.get_by_email(db, body.email)
    if user is None:
        # No enumeration concern here: the caller is an authenticated admin of
        # this tenant, and they need to know the invite could not be applied.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")

    try:
        member = memberships_repo.add_member_guarded(
            db,
            company_id=ctx.company_id,
            actor_id=ctx.user_id,
            target_user_id=user.id,
            new_role=role,
        )
    except memberships_repo.MembershipExists:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member; use PATCH to change their role",
        )
    except memberships_repo.MembershipError as exc:
        db.rollback()
        raise _membership_error(exc)

    db.commit()
    return _serialize_member(member, user)


def _membership_error(exc: Exception) -> HTTPException:
    """Map the authorization gate's errors onto HTTP without leaking internals."""
    if isinstance(exc, memberships_repo.MembershipNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, memberships_repo.InsufficientRole):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, memberships_repo.LastOwnerProtected):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/members/{user_id}")
def update_member_role(
    user_id: str,
    body: MemberRoleUpdate,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Change a role. Every invariant is enforced inside `change_role`, in one
    locked transaction — this handler adds no authorization logic of its own."""
    role = (body.role or "").lower()
    if role not in _ASSIGNABLE_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    try:
        # ctx.role is NOT passed: authorization is re-derived from the actor's
        # membership read under the company lock (see memberships._authorize_under_lock).
        member = memberships_repo.change_role(
            db,
            company_id=ctx.company_id,
            actor_id=ctx.user_id,
            target_user_id=user_id,
            new_role=role,
        )
    except memberships_repo.MembershipError as exc:
        db.rollback()
        raise _membership_error(exc)

    db.commit()
    user = users_repo.get_user(db, user_id)
    return _serialize_member(member, user)


@router.delete("/members/{user_id}")
def remove_member(
    user_id: str,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Dict[str, bool]:
    try:
        memberships_repo.remove_member_guarded(
            db,
            company_id=ctx.company_id,
            actor_id=ctx.user_id,
            target_user_id=user_id,
        )
    except memberships_repo.MembershipError as exc:
        db.rollback()
        raise _membership_error(exc)

    db.commit()
    return {"ok": True}


@router.post("/transfer-ownership")
def transfer_ownership(
    body: OwnershipTransfer,
    ctx: CompanyContext = Depends(require_owner),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Hand the company to another member. Owner only.

    Transferring to yourself is rejected: the old code would set owner_id to self
    and then demote self to admin, leaving a company whose owner_id pointed at a
    non-owner.
    """
    if body.userId == ctx.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already own this company",
        )

    try:
        # Promote first, so the company is never momentarily ownerless; both
        # writes and the invariant checks happen under the same company lock.
        memberships_repo.change_role(
            db,
            company_id=ctx.company_id,
            actor_id=ctx.user_id,
            target_user_id=body.userId,
            new_role=ROLE_OWNER,
        )
        # Move the designated-owner pointer BEFORE demoting self, so the company
        # is never momentarily pointing at a non-owner. Addressed by id, not
        # through `ctx.company` — that object's owner_id was read before the lock.
        companies_repo.set_owner_by_id(db, ctx.company_id, body.userId)
        memberships_repo.change_role(
            db,
            company_id=ctx.company_id,
            actor_id=ctx.user_id,
            target_user_id=ctx.user_id,
            new_role=ROLE_ADMIN,
        )
    except memberships_repo.MembershipError as exc:
        db.rollback()
        raise _membership_error(exc)

    db.commit()
    db.refresh(ctx.company)
    return _serialize(ctx.company, ROLE_ADMIN)
