"""Database engine and session management.

Uses DATABASE_URL when set (e.g. PostgreSQL), otherwise falls back to a local
SQLite file so the backend works with zero setup in development.
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_application_engine(database_url: str) -> Engine:
    """The one place an application engine is built.

    SQLite ships with foreign-key enforcement OFF per connection; without the
    pragma, ON DELETE CASCADE on document_versions/document_blobs/
    ingestion_jobs silently does nothing and deleting a document strands its
    dependent rows. PostgreSQL enforces foreign keys natively and takes no
    pragma. Same precedent as the test engine in tests/conftest.py.
    """
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    eng = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, future=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _sqlite_foreign_keys(dbapi_conn, _record):  # pragma: no cover - setup
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


_settings = get_settings()
DATABASE_URL = _settings.resolved_database_url()

engine = create_application_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
