"""H4 — authenticated generation must never report success without persisting.

A 200 from `/api/generate-workflow` is a promise: the report exists, has an id, and
can be fetched back. The old handler caught persistence failures, logged them, and
returned the *unsaved* report with 200 — so the client navigated to a report id that
did not exist, and an LLM call was billed for nothing.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.models.db_models import Report
from app.repositories import reports as reports_repo
from app import main as main_module

GEN = {"market": "EMEA", "persona": "Support Agent"}


def test_successful_generation_is_immediately_retrievable(
    client, alice, db_session, tenant_generation
):
    res = alice.post("/api/generate-workflow", json=GEN)
    assert res.status_code == 200
    report_id = res.json()["id"]

    # The promise a 200 makes: it is in the database and fetchable by id.
    assert db_session.get(Report, report_id) is not None
    assert alice.get(f"/api/reports/{report_id}").status_code == 200


def test_persistence_failure_returns_5xx_not_an_unsaved_report(
    client, alice, monkeypatch, tenant_generation
):
    """A commit failure must surface as an error, never as a successful report."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(reports_repo, "create_generation_run", boom)

    res = alice.post("/api/generate-workflow", json=GEN)
    assert res.status_code == 503, "a persistence failure was reported as success"
    assert res.json()["code"] == "persistence_failed"
    # No report body leaked as if it had been saved.
    assert "workflowSteps" not in res.text


def test_no_orphan_report_row_after_a_failed_generation(
    client, alice, monkeypatch, db_session, tenant_generation
):
    before = db_session.query(Report).count()

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(reports_repo, "create_generation_run", boom)
    alice.post("/api/generate-workflow", json=GEN)

    db_session.expire_all()
    assert db_session.query(Report).count() == before, "a partial row survived rollback"


def test_pipeline_failure_returns_generation_failed_and_marks_run_failed(
    client, alice, monkeypatch, db_session, tenant_generation
):
    def boom(*_args, **_kwargs):
        raise RuntimeError("tenant document secret must not leak")

    monkeypatch.setattr(main_module, "run_pipeline_ex", boom)
    res = alice.post("/api/generate-workflow", json=GEN)

    assert res.status_code == 503
    assert res.json()["code"] == "generation_failed"
    assert "tenant document secret" not in res.text
    db_session.expire_all()
    row = db_session.query(Report).order_by(Report.created_at.desc()).first()
    assert row.generation_status == "failed"
    assert row.generation_error_code == "generation_failed"
    assert row.report_json == {}


def test_completion_persistence_failure_returns_persistence_failed_and_marks_run_failed(
    client, alice, monkeypatch, db_session, tenant_generation
):
    def boom(*_args, **_kwargs):
        raise RuntimeError("tenant document secret must not leak")

    monkeypatch.setattr(reports_repo, "complete_generation_run", boom)
    res = alice.post("/api/generate-workflow", json=GEN)

    assert res.status_code == 503
    assert res.json()["code"] == "persistence_failed"
    assert "tenant document secret" not in res.text
    db_session.expire_all()
    row = db_session.query(Report).order_by(Report.created_at.desc()).first()
    assert row.generation_status == "failed"
    assert row.generation_error_code == "persistence_failed"
    assert row.report_json == {}


def test_generation_is_refused_when_the_database_is_disabled(client, alice, monkeypatch):
    """Authenticated generation with persistence off cannot keep its promise."""
    monkeypatch.setattr(get_settings(), "evidentia_db_enabled", False)
    monkeypatch.setattr(get_settings(), "evidentia_tenant_generation_enabled", True)

    res = alice.post("/api/generate-workflow", json=GEN)
    assert res.status_code == 503
    assert res.json()["code"] == "persistence_unavailable"


def test_production_refuses_to_start_with_the_database_disabled():
    """Auth and tenancy both require the database; there is no degraded mode."""
    from app.core.config import Settings
    from app.main import validate_production_config

    import secrets

    settings = Settings(
        evidentia_env="production",
        jwt_secret=secrets.token_urlsafe(48),
        evidentia_email_backend="smtp",
        evidentia_smtp_host="smtp.example.com",
        evidentia_cors_origins="https://app.example.com",
        evidentia_db_enabled=False,
    )
    with pytest.raises(RuntimeError, match="EVIDENTIA_DB_ENABLED"):
        validate_production_config(settings)
