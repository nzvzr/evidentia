"""Minimal auth endpoints (register / token).

This is intentionally lightweight — the demo does not require real auth. Users
can be created and an optional JWT issued for future use. Passwords, when
provided, are bcrypt-hashed; they are never returned.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.schemas import RegisterRequest
from app.repositories import users as users_repo

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _hash_password(password: str) -> str:
    from passlib.context import CryptContext

    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return ctx.hash(password)


def _issue_token(user_id: str, email: str) -> str:
    from jose import jwt

    settings = get_settings()
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _serialize(user) -> Dict[str, Any]:
    return {"id": user.id, "email": user.email, "name": user.name}


@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    existing = users_repo.get_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = _hash_password(body.password) if body.password else None
    user = users_repo.create_user(db, email=body.email, name=body.name, hashed_password=hashed)
    db.commit()
    db.refresh(user)
    token = _issue_token(user.id, user.email)
    return {"user": _serialize(user), "token": token}


@router.post("/token")
def token(body: RegisterRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    # Demo token issuance: creates the user on first use if needed.
    user = users_repo.get_or_create_user(db, email=body.email, name=body.name)
    db.commit()
    db.refresh(user)
    return {"token": _issue_token(user.id, user.email), "user": _serialize(user)}
