"""Test harness for the API: an isolated in-memory database per test, a
TestClient with the DB dependency overridden, and an in-process email outbox so
the verification/reset flows can be driven end-to-end without a mail provider.
"""

from __future__ import annotations

import os
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api import limits as limits_module
from app.core.ratelimit import FakeClock, RateLimiter
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import db_models  # noqa: F401  (register metadata)
from app.services import email as email_service

VALID_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def rate_limiter(monkeypatch) -> RateLimiter:
    """A fresh, deterministic rate limiter per test.

    The production limiter is a process-wide singleton, which would otherwise
    leak counts between tests (and trip the register limit partway through the
    suite). Tests drive a FakeClock, so window expiry is exact rather than
    wall-clock dependent.

    `limits.py` imports `get_rate_limiter` by name, so the patch has to land on
    that module's binding, not on `core.ratelimit`.
    """
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, enabled=True)
    limiter.clock = clock  # type: ignore[attr-defined]  (test convenience)
    monkeypatch.setattr(limits_module, "get_rate_limiter", lambda: limiter)
    # Local .env is intentionally developer-owned and may have rollout/LLM
    # flags enabled. Tests start from product defaults and opt in explicitly.
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_tenant_corpus_enabled", False)
    monkeypatch.setattr(settings, "evidentia_tenant_generation_enabled", False)
    monkeypatch.setattr(settings, "evidentia_claim_engine_enabled", False)
    monkeypatch.setattr(settings, "evidentia_use_llm", False)
    return limiter


# Opt-in PostgreSQL profile. Production runs on managed PostgreSQL, whose locking
# semantics (`SELECT ... FOR UPDATE` row locks) are NOT the same as SQLite's
# (whole-database write locks). The default run therefore proves the *application*
# serialization logic, not PostgreSQL's row-lock behaviour — see the note at the
# top of tests/test_concurrency.py.
#
#   EVIDENTIA_TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/evidentia_test \
#       python -m pytest tests/test_concurrency.py
TEST_DATABASE_URL = os.getenv("EVIDENTIA_TEST_DATABASE_URL", "").strip()


@pytest.fixture
def engine(tmp_path):
    """A real database, one per test — PostgreSQL if configured, else file SQLite.

    Deliberately NOT an in-memory StaticPool database. StaticPool hands every
    session the *same* connection, which makes genuine concurrency untestable:
    two threads would share one transaction, so a race we are trying to prove
    could never occur. A real DB gives each session its own connection, real
    transactions, and real lock contention.

    SQLite gets WAL + a busy timeout so concurrent writers block briefly instead
    of failing with "database is locked".
    """
    if TEST_DATABASE_URL:
        eng = create_engine(TEST_DATABASE_URL, future=True)
        Base.metadata.drop_all(bind=eng)
        Base.metadata.create_all(bind=eng)
        try:
            yield eng
        finally:
            Base.metadata.drop_all(bind=eng)
            eng.dispose()
        return

    db_path = tmp_path / "test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - setup
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session_factory(engine):
    """Create a NEW Session per caller. Every thread must use its own."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def db_session(session_factory):
    """A session for test assertions only. Never share it with a worker thread."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def outbox(monkeypatch) -> List[email_service.OutboundEmail]:
    """Capture emails the app sends (verification / reset links)."""
    sender = email_service.MemoryEmailSender()
    monkeypatch.setattr(email_service, "get_email_sender", lambda: sender)
    return sender.outbox


@pytest.fixture
def client(session_factory, outbox) -> TestClient:
    """TestClient whose requests each get their OWN database session.

    Previously every request shared one Session object, so concurrent requests
    shared a transaction — which both hid real races and produced flaky failures.
    """

    def _get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Account:
    """A registered user with a live session, plus helpers to call the API as them."""

    def __init__(self, client: TestClient, payload: Dict):
        self._client = client
        self.email: str = payload["user"]["email"]
        self.user_id: str = payload["user"]["id"]
        self.access: str = payload["accessToken"]
        self.refresh: str = payload["refreshToken"]
        self.companies = payload.get("companies", [])
        self.company_id: str = self.companies[0]["id"] if self.companies else ""

    @property
    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"}

    def _merge(self, kw: Dict) -> Dict:
        """Let callers add headers (e.g. a forged X-Company-Id) without dropping auth."""
        return {**kw, "headers": {**self.headers, **kw.get("headers", {})}}

    def get(self, url, **kw):
        return self._client.get(url, **self._merge(kw))

    def post(self, url, **kw):
        return self._client.post(url, **self._merge(kw))

    def patch(self, url, **kw):
        return self._client.patch(url, **self._merge(kw))

    def delete(self, url, **kw):
        return self._client.delete(url, **self._merge(kw))


def register(client: TestClient, email: str, company: str = "Acme", password: str = VALID_PASSWORD) -> Account:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": email.split("@")[0], "company": company},
    )
    assert res.status_code == 201, res.text
    return Account(client, res.json())


@pytest.fixture
def alice(client) -> Account:
    return register(client, "alice@acme.co", company="Acme")


@pytest.fixture
def bob(client) -> Account:
    """A user in a *different* tenant — the cross-tenant attacker in IDOR tests."""
    return register(client, "bob@globex.co", company="Globex")


GEN_INPUT = {"market": "EMEA", "persona": "Support Agent"}

TENANT_POLICY = b"""# Access Control Policy

## Administrative access

Administrative access requires multi-factor authentication. Emergency access
must be reviewed within 24 hours. Unique marker: ZORBLAX-999-A.

## Incident escalation

Severity one incidents require immediate on-call escalation and a review.
"""


def seed_finalized_document(
    account: Account,
    session_factory,
    monkeypatch,
    *,
    body: bytes = TENANT_POLICY,
    filename: str = "tenant-policy.md",
) -> str:
    """Create one real M3-eligible current version for generation tests."""
    from app.core.config import get_settings
    from app.ingestion.worker import IngestionWorker

    settings = get_settings()
    monkeypatch.setattr(settings, "evidentia_tenant_corpus_enabled", True)
    monkeypatch.setattr(settings, "evidentia_tenant_generation_enabled", True)
    monkeypatch.setattr(settings, "evidentia_use_llm", False)
    uploaded = account.post(
        "/api/documents/upload",
        files={"file": (filename, body, "text/markdown")},
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["documentId"]
    worker = IngestionWorker(session_factory, poll_seconds=0.01, max_attempts=3)
    while worker.process_one():
        pass
    finalized = account.post(f"/api/documents/{document_id}/finalize")
    assert finalized.status_code in (200, 202), finalized.text
    while worker.process_one():
        pass
    return document_id


@pytest.fixture
def tenant_generation(alice, session_factory, monkeypatch) -> str:
    return seed_finalized_document(alice, session_factory, monkeypatch)


def create_report(account, headers=None) -> str:
    """Create a report the ONLY way that is now supported: authenticated
    generation. POST /api/reports was removed (it accepted an arbitrary blob and
    let a client fabricate generation metadata)."""
    kwargs = {"json": GEN_INPUT}
    if headers:
        kwargs["headers"] = headers
    res = account._client.post("/api/generate-workflow", **{
        **kwargs,
        "headers": {**account.headers, **(headers or {})},
    })
    assert res.status_code == 200, res.text
    return res.json()["id"]
