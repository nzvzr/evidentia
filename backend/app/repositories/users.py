"""User repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.db_models import User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    """Emails are matched case-insensitively; store the canonical lowercase form
    so `A@x.com` cannot register a second account alongside `a@x.com`."""
    return (email or "").strip().lower()


def get_user(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> Optional[User]:
    return db.execute(
        select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()


def create_user(
    db: Session,
    email: str,
    name: Optional[str] = None,
    hashed_password: Optional[str] = None,
) -> User:
    user = User(email=normalize_email(email), name=name, hashed_password=hashed_password)
    db.add(user)
    db.flush()
    return user


def set_password(db: Session, user: User, hashed_password: str) -> User:
    user.hashed_password = hashed_password
    db.add(user)
    db.flush()
    return user


def lock_user(db: Session, user_id: str) -> Optional[User]:
    """Take a row lock on the user and return the row as it is *under* the lock.

    This is the serialization point between *session issuance* (login, refresh)
    and *session revocation* (logout-all, password reset). Without it, a refresh
    can commit a new child token after a revocation sweep has already run, leaving
    a fully valid session that outlived the user's own "sign out everywhere".

    PostgreSQL: `SELECT ... FOR UPDATE` takes a real row lock.

    SQLite: there is no `FOR UPDATE`, and a plain `SELECT` takes only a SHARED lock —
    two transactions could both read the user, both decide, and only serialize on
    their writes, which is too late. A no-op `UPDATE` promotes the transaction to
    RESERVED (write) immediately, so a concurrent session-issuing transaction blocks
    here rather than after it has already committed a token.

    `populate_existing` is not optional. The Session's identity map already holds
    this User (the caller looked it up by email to find its id), and by default the
    ORM *discards* the freshly selected row and hands back the cached instance. The
    lock would then protect a decision made against pre-lock state — the exact bug
    the lock exists to prevent. This forces the attributes to be overwritten from
    the row read inside the critical section.
    """
    dialect = db.bind.dialect.name if db.bind is not None else ""

    if dialect == "sqlite":
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(updated_at=User.updated_at)  # no-op write: takes the lock
            .execution_options(synchronize_session=False)
        )
        stmt = select(User).where(User.id == user_id)
    else:
        stmt = select(User).where(User.id == user_id).with_for_update()

    return db.execute(
        stmt.execution_options(populate_existing=True)
    ).scalar_one_or_none()


def bump_token_version_by_id(db: Session, user_id: str) -> int:
    """Atomically invalidate every outstanding *access* token for this user.

    Expressed as `SET token_version = token_version + 1` in the database, NOT as an
    ORM read/modify/write: two concurrent bumps would both read N and both write
    N+1, losing an update. The counter still moves, so the bug is invisible unless
    you count — and a lost bump means an access token an attacker holds stays valid.

    Refresh tokens are revoked in the token store; access tokens are stateless, so
    this counter is the only way to kill one before its TTL expires.
    """
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(token_version=User.token_version + 1)
        .execution_options(synchronize_session=False)
    )
    db.flush()
    return int(
        db.execute(select(User.token_version).where(User.id == user_id)).scalar_one()
    )


def bump_token_version(db: Session, user: User) -> User:
    """Convenience wrapper around the atomic bump; refreshes the ORM object."""
    bump_token_version_by_id(db, user.id)
    db.refresh(user)
    return user


def mark_verified(db: Session, user: User) -> User:
    if user.email_verified_at is None:
        user.email_verified_at = _now()
        db.add(user)
        db.flush()
    return user
