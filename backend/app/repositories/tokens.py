"""Token store: refresh tokens (rotating, with reuse detection) and one-time
email-verification / password-reset tokens.

Every token is stored as a SHA-256 digest only. The plaintext exists exactly
once, in the response (or email) that hands it to the user.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import security
from app.models.db_models import EmailVerificationToken, PasswordResetToken, RefreshToken


def _now() -> datetime:
    # Stored naive-UTC to match the DateTime columns (portable across SQLite/PG).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# --------------------------------------------------------------------------
# Refresh tokens
# --------------------------------------------------------------------------


def issue_refresh_token(db: Session, user_id: str, family_id: Optional[str] = None) -> Tuple[str, RefreshToken]:
    """Create a refresh token. Returns (plaintext, row). Caller commits."""
    plaintext = security.generate_opaque_token()
    row = RefreshToken(
        user_id=user_id,
        token_hash=security.hash_opaque_token(plaintext),
        family_id=family_id or security.new_family_id(),
        expires_at=_naive(security.refresh_expiry()),
    )
    db.add(row)
    db.flush()
    return plaintext, row


def get_refresh_token(db: Session, plaintext: str) -> Optional[RefreshToken]:
    digest = security.hash_opaque_token(plaintext)
    return db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == digest)
    ).scalar_one_or_none()


def is_usable(row: RefreshToken) -> bool:
    return row.revoked_at is None and row.expires_at > _now()


def revoke_token(db: Session, row: RefreshToken) -> None:
    if row.revoked_at is None:
        row.revoked_at = _now()
        db.add(row)


def revoke_family(db: Session, family_id: str) -> None:
    """Revoke every token in a rotation chain (stolen-token reuse response)."""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_all_for_user(db: Session, user_id: str) -> None:
    """Log the user out of every session (logout-all, password change/reset)."""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def consume_refresh_token(db: Session, plaintext: str) -> Optional[RefreshToken]:
    """Atomically claim a refresh token, or return None.

    This is the single-winner primitive. The revocation is a **conditional
    UPDATE** — `SET revoked_at=now WHERE token_hash=? AND revoked_at IS NULL AND
    expires_at > now` — so the database, not the application, decides the race:
    exactly one concurrent caller sees `rowcount == 1` and may rotate.

    The previous read-then-write version could let two concurrent refreshes both
    pass an `is_usable()` check and each mint a valid child, double-spending the
    token and leaving two live chains in one family.
    """
    digest = security.hash_opaque_token(plaintext)
    now = _now()

    result = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == digest,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        return None  # unknown, expired, or someone else won the race

    return db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == digest)
    ).scalar_one_or_none()


def rotate_refresh_token(db: Session, plaintext: str) -> Tuple[Optional[str], Optional[str]]:
    """Exchange a refresh token for a fresh one, in one transaction.

    Returns (new_plaintext, user_id) on success, or (None, None) if the token is
    unknown, expired, or already used. Re-presenting an already-consumed token is
    treated as theft: the entire family is revoked, forcing re-login on every
    device sharing that chain.
    """
    claimed = consume_refresh_token(db, plaintext)

    if claimed is None:
        # Either the token never existed, or it was already consumed/expired.
        # If it exists, this is a reuse attempt (or a lost race) — burn the family.
        existing = get_refresh_token(db, plaintext)
        if existing is not None:
            revoke_family(db, existing.family_id)
        db.commit()
        return None, None

    new_plaintext, _new_row = issue_refresh_token(db, claimed.user_id, family_id=claimed.family_id)
    return new_plaintext, claimed.user_id


# --------------------------------------------------------------------------
# One-time tokens (email verification, password reset)
# --------------------------------------------------------------------------


def issue_email_verification(db: Session, user_id: str) -> str:
    plaintext = security.generate_opaque_token()
    db.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=security.hash_opaque_token(plaintext),
            expires_at=_naive(security.verification_expiry()),
        )
    )
    db.flush()
    return plaintext


def consume_email_verification(db: Session, plaintext: str) -> Optional[str]:
    """Validate + burn a verification token. Returns the user id, else None."""
    digest = security.hash_opaque_token(plaintext)
    row = db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == digest)
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= _now():
        return None
    row.consumed_at = _now()
    db.add(row)
    return row.user_id


def issue_password_reset(db: Session, user_id: str) -> str:
    # Only the newest reset link should work: invalidate outstanding ones.
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.consumed_at.is_(None))
        .values(consumed_at=_now())
    )
    plaintext = security.generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=security.hash_opaque_token(plaintext),
            expires_at=_naive(security.reset_expiry()),
        )
    )
    db.flush()
    return plaintext


def peek_password_reset(db: Session, plaintext: str) -> Optional[str]:
    """Whose reset token is this? Does NOT burn it.

    The caller needs the user id *before* it can take the user lock, and the lock
    has to be held before the password is changed (see `api/auth.confirm_password_reset`).
    Validity is re-checked by `consume_password_reset` under that lock, so peeking
    grants nothing on its own.
    """
    digest = security.hash_opaque_token(plaintext)
    row = db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == digest)
    ).scalar_one_or_none()
    return row.user_id if row is not None else None


def consume_password_reset(db: Session, plaintext: str) -> Optional[str]:
    """Validate + burn a reset token. Returns the user id, else None.

    `populate_existing` because the row may already be cached in this Session's
    identity map from `peek_password_reset`; the consumed/expiry check must be made
    against the row as it is *now*, not as it was before the lock was taken.
    """
    digest = security.hash_opaque_token(plaintext)
    row = db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == digest)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= _now():
        return None
    row.consumed_at = _now()
    db.add(row)
    return row.user_id


def list_active_refresh_tokens(db: Session, user_id: str) -> List[RefreshToken]:
    return list(
        db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > _now(),
            )
        )
        .scalars()
        .all()
    )
