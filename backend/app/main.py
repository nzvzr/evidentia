"""Evidentia FastAPI backend entrypoint."""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.agents.orchestrator import run_pipeline
from app.api import auth, companies, documents, personas, reports
from app.api.deps import resolve_company_id
from app.core.config import get_settings
from app.db.session import get_db
from app.models.schemas import GenerateRequest
from app.repositories import reports as reports_repo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("evidentia.app")

app = FastAPI(title="Evidentia Backend", version="2.0.0")

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CRUD routers
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(documents.router)
app.include_router(personas.router)
app.include_router(reports.router)


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    if settings.is_db_enabled():
        try:
            from app.db.init_db import init_db

            init_db()
        except Exception as exc:  # noqa: BLE001 - never block startup on DB
            logger.warning("Database initialization skipped: %s", exc)


@app.get("/health")
def health():
    """Liveness/readiness probe. Reports capability booleans only — never secrets."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": "evidentia-backend",
        "version": app.version,
        "llmEnabled": settings.is_llm_enabled(),
        "intensity": settings.effective_intensity(),
        "dbEnabled": settings.is_db_enabled(),
    }


@app.post("/api/generate-workflow")
def generate_workflow(body: GenerateRequest, db: Session = Depends(get_db)):
    # Deterministic (optionally LLM-assisted) generation; never raises for LLM issues.
    report = run_pipeline(
        market=body.market,
        persona=body.persona,
        custom_persona=body.customPersona,
        selected_document_ids=body.selectedDocumentIds,
    )

    # Persist to the database when available; fall back to returning the report.
    settings = get_settings()
    if settings.is_db_enabled():
        try:
            company_id = resolve_company_id(db, None)
            row = reports_repo.create_report(db, company_id, report)
            return row.report_json  # includes the DB id
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            logger.warning("Report persistence failed; returning unsaved report: %s", exc)
            db.rollback()

    return report
