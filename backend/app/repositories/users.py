"""User repository."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db_models import User


def get_user(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


def get_by_email(db: Session, email: str) -> Optional[User]:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def create_user(db: Session, email: str, name: Optional[str] = None, hashed_password: Optional[str] = None) -> User:
    user = User(email=email, name=name, hashed_password=hashed_password)
    db.add(user)
    db.flush()
    return user


def get_or_create_user(db: Session, email: str, name: Optional[str] = None) -> User:
    existing = get_by_email(db, email)
    if existing:
        return existing
    return create_user(db, email=email, name=name)
