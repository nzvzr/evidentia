"""Password hashing, JWT access tokens, and opaque refresh/one-time tokens.

Design notes
------------
* **Passwords** are hashed with bcrypt (cost 12). bcrypt silently truncates
  input at 72 bytes, so the password is SHA-256 pre-hashed to a fixed 64-char
  hex digest first. This makes the effective password length unbounded and the
  truncation boundary unreachable.
* **Access tokens** are short-lived signed JWTs (stateless, never stored).
* **Refresh / verification / reset tokens** are opaque 256-bit random strings.
  Only their SHA-256 digest is stored, so a database leak cannot be replayed
  against the API. They are looked up by digest, never by plaintext.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

# --- token type discriminators (a refresh token must never pass as access) ---
TOKEN_TYPE_ACCESS = "access"

_BCRYPT_ROUNDS = 12


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def _prehash(password: str) -> bytes:
    """SHA-256 pre-hash so bcrypt's 72-byte truncation is never reachable."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, hashed: Optional[str]) -> bool:
    """Constant-time-ish verification. Returns False for users without a hash
    (rather than raising), so callers cannot distinguish 'no password set' from
    'wrong password'."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def dummy_verify() -> None:
    """Burn a bcrypt verification against a throwaway hash.

    Called on the login path when the email does not exist, so that response
    timing does not reveal whether an account is registered.
    """
    bcrypt.checkpw(_prehash("timing-equalizer"), _DUMMY_HASH)


_DUMMY_HASH = bcrypt.hashpw(_prehash("timing-equalizer"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))


# --------------------------------------------------------------------------
# Opaque tokens (refresh, email verification, password reset)
# --------------------------------------------------------------------------


def generate_opaque_token() -> str:
    """A 256-bit URL-safe random token. Returned to the client exactly once."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """SHA-256 digest used as the database lookup key.

    Plain SHA-256 (not bcrypt) is correct here: these tokens are high-entropy
    random values, not human-chosen secrets, so they are not brute-forceable
    and the store must support O(1) lookup by digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_family_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# JWT access tokens
# --------------------------------------------------------------------------


def create_access_token(user_id: str, email: str, token_version: int = 0) -> str:
    """Mint an access token.

    `tv` (token version) is what makes a *stateless* access token revocable: it is
    compared against the user's current `token_version` on every request, and a
    password reset or logout-all bumps that counter. Without it, an access token
    stolen before a reset would stay valid for its full TTL afterwards.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "typ": TOKEN_TYPE_ACCESS,
        "tv": token_version,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.effective_jwt_secret(), algorithm=settings.jwt_algorithm)


# Every claim below must be present. `exp` is the critical one: python-jose only
# validates expiry *when the claim exists*, so a token that simply omits `exp` was
# previously accepted as a credential that never expires.
REQUIRED_CLAIMS = ("sub", "typ", "exp", "iat", "jti")


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Return the claims of a valid, unexpired *access* token, else None.

    Strict by construction: the algorithm is pinned (so `alg: none` and
    HMAC/RSA confusion are impossible), and every required claim must be present
    and non-empty — a missing claim is a rejection, never a default.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.effective_jwt_secret(),
            algorithms=[settings.jwt_algorithm],  # pinned: never read `alg` from the token
            options={
                "require_exp": True,
                "require_iat": True,
                "require_sub": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_signature": True,
            },
        )
    except JWTError:
        return None

    for claim in REQUIRED_CLAIMS:
        if not claims.get(claim):
            return None

    # Reject any token that is not explicitly an access token, so a refresh or
    # other signed artefact can never be presented as a bearer credential.
    if claims.get("typ") != TOKEN_TYPE_ACCESS:
        return None

    return claims


def refresh_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=get_settings().refresh_token_ttl_days)


def verification_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=get_settings().email_verification_ttl_hours)


def reset_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=get_settings().password_reset_ttl_minutes)
