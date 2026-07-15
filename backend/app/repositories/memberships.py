"""Company membership repository — the single source of truth for tenancy.

Every tenant-scoped request must resolve through `get_membership`. If a user has
no membership row for a company, that company does not exist as far as they are
concerned.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.db_models import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_RANK,
    Company,
    CompanyMember,
    User,
)


class MembershipError(Exception):
    """Base class for membership authorization failures."""


class MembershipExists(MembershipError):
    def __init__(self, user_id: str) -> None:
        super().__init__("User is already a member of this company")
        self.user_id = user_id


class MembershipNotFound(MembershipError):
    pass


class InsufficientRole(MembershipError):
    pass


class LastOwnerProtected(MembershipError):
    pass


class InvalidRoleChange(MembershipError):
    pass


def get_membership(db: Session, company_id: str, user_id: str) -> Optional[CompanyMember]:
    return db.execute(
        select(CompanyMember).where(
            CompanyMember.company_id == company_id,
            CompanyMember.user_id == user_id,
        )
    ).scalar_one_or_none()


def _lock_company(db: Session, company_id: str) -> None:
    """Serialize concurrent membership mutations for one company.

    The owner invariant ("at least one owner, always") is a cross-row constraint, so
    it cannot be expressed as a column constraint: two concurrent demotions of two
    different owners would each see one *other* owner remaining and both succeed,
    leaving none. The check and the write must be one critical section.

    PostgreSQL: `SELECT ... FOR UPDATE` takes a real row lock.

    SQLite: there is no `FOR UPDATE`, and a plain `SELECT` acquires only a SHARED
    lock — two transactions can both read, both pass the owner check, and only then
    serialize on their writes. That is exactly the race above, and it is *not*
    hypothetical: it reproduced under load. A no-op `UPDATE` promotes the
    transaction to RESERVED (write) immediately, so the second writer blocks here
    (bounded by `busy_timeout`) rather than after it has already made its decision.
    """
    dialect = db.bind.dialect.name if db.bind is not None else ""

    if dialect == "sqlite":
        db.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(updated_at=Company.updated_at)  # no-op write: takes the lock
            .execution_options(synchronize_session=False)
        )
        return

    db.execute(
        select(Company).where(Company.id == company_id).with_for_update()
    ).scalar_one_or_none()


def count_owners_locked(db: Session, company_id: str) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(CompanyMember)
            .where(CompanyMember.company_id == company_id, CompanyMember.role == ROLE_OWNER)
        ).scalar_one()
    )


def reload_membership(db: Session, company_id: str, user_id: str) -> Optional[CompanyMember]:
    """Read a membership from the DATABASE, bypassing the identity map.

    `populate_existing` is load-bearing, not a style choice. The request has
    already loaded this row (authenticating the caller reads their membership), and
    by default the ORM throws away the freshly-selected row and hands back the
    cached instance. A "re-read under the lock" that returns a pre-lock object is
    not a re-read at all — it just makes the staleness harder to see.

    Today the cached instance is often collected before we get here (the identity
    map holds weak references and nothing keeps the membership alive), so the stale
    value is returned only *sometimes* — which is worse than always, not better.
    Authorization must not depend on garbage-collection timing.
    """
    return db.execute(
        select(CompanyMember)
        .where(
            CompanyMember.company_id == company_id,
            CompanyMember.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def reload_company(db: Session, company_id: str) -> Optional[Company]:
    """Read the company from the DATABASE, bypassing the identity map.

    `db.get(Company, id)` would return the instance the request dependency already
    put in the identity map — and that one is strongly referenced (the request's
    CompanyContext holds it), so its `owner_id` is reliably STALE, not occasionally
    stale. Deciding whether the designated owner needs reassigning from that value
    left `company.owner_id` pointing at a demoted admin.
    """
    return db.execute(
        select(Company)
        .where(Company.id == company_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _authorize_under_lock(
    db: Session, company_id: str, actor_id: str, target_user_id: str
) -> Tuple[CompanyMember, CompanyMember]:
    """Re-read BOTH memberships from the database *after* the lock is held.

    The actor's role travels with the request (it was read when the request was
    authenticated), but by the time this transaction acquires the company lock it
    may be stale: a mutation queued behind the lock would otherwise act with
    authority its actor no longer has — e.g. an admin demoted while their PATCH was
    waiting still completing it as an admin. Authorization must use the state that
    is true *inside* the critical section, never a value captured outside it.

    Returns (actor_membership, target_membership).
    """
    actor = reload_membership(db, company_id, actor_id)
    if actor is None:
        raise InsufficientRole("You are no longer a member of this company")

    target = reload_membership(db, company_id, target_user_id)
    if target is None:
        raise MembershipNotFound("Member not found")

    return actor, target


def _list_owners_locked(db: Session, company_id: str) -> List[CompanyMember]:
    return list(
        db.execute(
            select(CompanyMember)
            .where(
                CompanyMember.company_id == company_id,
                CompanyMember.role == ROLE_OWNER,
            )
            .order_by(CompanyMember.created_at.asc())
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )


def _enforce_owner_pointer(db: Session, company_id: str) -> None:
    """Post-condition of EVERY membership mutation: `company.owner_id` names an
    active owner membership.

    Derived from the owner rows as they actually are under the lock, rather than
    from the previous pointer value. The old version asked "is the demoted user the
    designated owner?" using a stale `owner_id` — when a concurrent transfer had
    already moved the pointer, the answer was wrongly "no", the reassignment was
    skipped, and the company was left designating a demoted admin as its owner.
    """
    company = reload_company(db, company_id)
    if company is None:
        return

    owners = _list_owners_locked(db, company_id)
    if not owners:
        raise LastOwnerProtected(
            "Company must have at least one owner; transfer ownership first"
        )

    if any(o.user_id == company.owner_id for o in owners):
        return  # the pointer already names a real owner

    company.owner_id = owners[0].user_id  # oldest owner inherits the pointer
    db.add(company)
    db.flush()


def change_role(
    db: Session,
    company_id: str,
    actor_id: str,
    target_user_id: str,
    new_role: str,
    actor_role: str | None = None,  # accepted for call-site compatibility; NOT trusted
) -> CompanyMember:
    """THE single authorization gate for every role change.

    Every invariant is evaluated inside one locked transaction, against state read
    *under* the lock:

      * only an owner may create, modify, demote or replace another owner;
      * an admin may never touch a member whose rank is >= their own;
      * an admin may never grant a role at or above their own (no self-escalation);
      * a company always keeps at least one owner;
      * `company.owner_id` always points at an active owner membership.

    `actor_role` is deliberately ignored — see `_authorize_under_lock`.
    """
    if new_role not in ROLE_RANK:
        raise InvalidRoleChange("Invalid role")

    _lock_company(db, company_id)
    actor, target = _authorize_under_lock(db, company_id, actor_id, target_user_id)

    actor_is_owner = actor.role == ROLE_OWNER

    # Only an owner may act on an owner — an admin cannot demote, remove, or
    # otherwise rewrite one.
    if target.role == ROLE_OWNER and not actor_is_owner:
        raise InsufficientRole("Only an owner can modify an owner")

    if not actor_is_owner:
        # An admin may not act on a peer/superior, nor mint a peer/superior.
        if ROLE_RANK[target.role] >= ROLE_RANK[actor.role]:
            raise InsufficientRole("Cannot modify a member at or above your own role")
        if ROLE_RANK[new_role] >= ROLE_RANK[actor.role]:
            raise InsufficientRole("Cannot grant a role at or above your own")

    losing_ownership = target.role == ROLE_OWNER and new_role != ROLE_OWNER
    if losing_ownership and count_owners_locked(db, company_id) <= 1:
        raise LastOwnerProtected(
            "Company must have at least one owner; transfer ownership first"
        )

    target.role = new_role
    db.add(target)
    db.flush()

    _enforce_owner_pointer(db, company_id)
    return target


def remove_member_guarded(
    db: Session,
    company_id: str,
    actor_id: str,
    target_user_id: str,
    actor_role: str | None = None,  # accepted for call-site compatibility; NOT trusted
) -> None:
    """Removal goes through the same invariants, under the same lock."""
    _lock_company(db, company_id)
    actor, target = _authorize_under_lock(db, company_id, actor_id, target_user_id)

    actor_is_owner = actor.role == ROLE_OWNER

    if target.role == ROLE_OWNER and not actor_is_owner:
        raise InsufficientRole("Only an owner can remove an owner")
    if not actor_is_owner and ROLE_RANK[target.role] >= ROLE_RANK[actor.role]:
        raise InsufficientRole("Cannot remove a member at or above your own role")

    losing_ownership = target.role == ROLE_OWNER
    if losing_ownership and count_owners_locked(db, company_id) <= 1:
        raise LastOwnerProtected("Cannot remove the last owner; transfer ownership first")

    db.delete(target)
    db.flush()

    _enforce_owner_pointer(db, company_id)


def add_member_guarded(
    db: Session,
    company_id: str,
    actor_id: str,
    target_user_id: str,
    new_role: str = ROLE_MEMBER,
) -> CompanyMember:
    """Member creation, through the SAME transactional gate as a role change.

    Creation is a role grant: `POST /members {role: admin}` hands out authority
    exactly like `PATCH` does. It used to authorize from `ctx.role` — the actor's
    role as captured when the request was authenticated, outside any lock — and to
    take no lock at all, so an admin whose demotion had already committed could
    still create members (and mint admins) with the authority they no longer held.
    """
    if new_role not in ROLE_RANK:
        raise InvalidRoleChange("Invalid role")

    _lock_company(db, company_id)

    actor = reload_membership(db, company_id, actor_id)
    if actor is None:
        raise InsufficientRole("You are no longer a member of this company")
    if not role_at_least(actor.role, ROLE_ADMIN):
        raise InsufficientRole("Requires admin role")

    # An admin may not mint a peer or a superior; only an owner may mint an owner.
    if actor.role != ROLE_OWNER and ROLE_RANK[new_role] >= ROLE_RANK[actor.role]:
        raise InsufficientRole("Cannot grant a role at or above your own")

    if reload_membership(db, company_id, target_user_id) is not None:
        raise MembershipExists(target_user_id)

    member = CompanyMember(company_id=company_id, user_id=target_user_id, role=new_role)
    db.add(member)
    db.flush()

    _enforce_owner_pointer(db, company_id)
    return member


def add_member(db: Session, company_id: str, user_id: str, role: str = ROLE_MEMBER) -> CompanyMember:
    """Create a membership with NO authorization check.

    Only for callers that are creating the company itself (registration, company
    creation), where there is no actor to authorize against yet. Every
    request-driven creation must go through `add_member_guarded`.

    This deliberately does NOT upsert. The old upsert meant `POST /members` could
    silently *rewrite an existing role* — including the owner's — which let an
    admin demote the owner by re-POSTing them as a member.
    """
    if get_membership(db, company_id, user_id) is not None:
        raise MembershipExists(user_id)
    member = CompanyMember(company_id=company_id, user_id=user_id, role=role)
    db.add(member)
    db.flush()
    return member


def remove_member(db: Session, company_id: str, user_id: str) -> bool:
    member = get_membership(db, company_id, user_id)
    if not member:
        return False
    db.delete(member)
    db.flush()
    return True


def set_role(db: Session, company_id: str, user_id: str, role: str) -> Optional[CompanyMember]:
    member = get_membership(db, company_id, user_id)
    if not member:
        return None
    member.role = role
    db.add(member)
    db.flush()
    return member


def list_members(db: Session, company_id: str) -> List[Tuple[CompanyMember, User]]:
    rows = db.execute(
        select(CompanyMember, User)
        .join(User, User.id == CompanyMember.user_id)
        .where(CompanyMember.company_id == company_id)
        .order_by(CompanyMember.created_at.asc())
    ).all()
    return [(m, u) for m, u in rows]


def list_companies_for_user(db: Session, user_id: str) -> List[Tuple[Company, CompanyMember]]:
    """Only the companies this user actually belongs to — never all companies."""
    rows = db.execute(
        select(Company, CompanyMember)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .where(CompanyMember.user_id == user_id)
        .order_by(Company.created_at.asc())
    ).all()
    return [(c, m) for c, m in rows]


def count_owners(db: Session, company_id: str) -> int:
    from app.models.db_models import ROLE_OWNER

    return len(
        db.execute(
            select(CompanyMember).where(
                CompanyMember.company_id == company_id,
                CompanyMember.role == ROLE_OWNER,
            )
        )
        .scalars()
        .all()
    )


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(minimum, 99)
