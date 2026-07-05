"""Database initialization.

Creates tables (safety net for SQLite dev; Alembic is preferred for Postgres)
and seeds the demo company. Safe to call on every startup.
"""

from __future__ import annotations

import logging

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import db_models  # noqa: F401  (register models on metadata)
from app.repositories import companies

logger = logging.getLogger("evidentia.db")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        companies.get_or_create_demo_company(db)
        db.commit()
    finally:
        db.close()
    logger.info("Database initialized (%s)", engine.url.render_as_string(hide_password=True))
