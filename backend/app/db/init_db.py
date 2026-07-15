"""Database initialization.

Creates tables (safety net for SQLite dev; Alembic is preferred for Postgres).

No seeding: there is deliberately no demo/default company. Every company is
created by a registering user, who becomes its owner. A shared tenant that any
anonymous caller lands in is exactly the multi-tenancy hole this replaces.
"""

from __future__ import annotations

import logging

from app.db.base import Base
from app.db.session import engine
from app.models import db_models  # noqa: F401  (register models on metadata)

logger = logging.getLogger("evidentia.db")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized (%s)", engine.url.render_as_string(hide_password=True))
