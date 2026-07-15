"""Evidentia FastAPI backend entrypoint."""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.orm import Session

from app.agents.orchestrator import run_pipeline
from app.api import auth, companies, documents, personas, reports
from app.api.deps import CompanyContext, get_company_context
from app.api.limits import enforce_generation
from app.core.config import get_settings
from app.core.ratelimit import RATE_LIMITED_CODE, RateLimitExceeded
from app.db.session import get_db
from app.middleware.bff_guard import BFFGuardMiddleware
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.models.schemas import GenerateRequest
from app.repositories import reports as reports_repo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("evidentia.app")

app = FastAPI(title="Evidentia Backend", version="3.1.0")

_settings = get_settings()
_cors_origins = _settings.cors_origins()
# Credentialed cross-origin requests cannot be combined with a "*" origin. The
# browser never talks to this API directly (the Next.js BFF holds the tokens and
# calls it server-side), so wildcard + no credentials is the correct default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reject oversized bodies before any parsing/validation work is done.
app.add_middleware(BodySizeLimitMiddleware)

# Reject requests that bypassed the BFF (only active when a BFF secret is set).
# Added last ⇒ runs first, so a direct caller never reaches a handler.
app.add_middleware(BFFGuardMiddleware)


@app.exception_handler(StarletteHTTPException)
def _http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Flatten `detail={"code": ..., "message": ...}` into a top-level `code`.

    Handlers raise structured details for machine-readable failures (e.g. a
    persistence failure the BFF must distinguish from a generation failure). Keep
    plain-string details exactly as they were, so existing clients/tests are
    unaffected.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"code": detail["code"], "detail": detail.get("message", "")}
    else:
        body = {"detail": detail}
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.exception_handler(RateLimitExceeded)
def _rate_limited(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 with a stable machine-readable code and Retry-After.

    The body carries no limit, no remaining count and no window boundary — a
    throttled caller learns only that they must wait, never the policy shape.
    """
    return JSONResponse(
        status_code=429,
        content={
            "code": RATE_LIMITED_CODE,
            "detail": "Too many requests. Please try again later.",
        },
        headers={"Retry-After": str(exc.retry_after)},
    )

# CRUD routers
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(documents.router)
app.include_router(personas.router)
app.include_router(reports.router)


def validate_production_config(settings) -> None:
    """Refuse to start a production process that is not safe to expose.

    Every check here is a control that silently fails open if misconfigured, so
    the only safe behaviour is to not boot at all.
    """
    problems: list[str] = []

    # 1. A weak/default/short signing key forfeits every other control.
    try:
        settings.effective_jwt_secret()
    except RuntimeError as exc:
        problems.append(str(exc))

    # 2. Trusting X-Forwarded-For while directly reachable = forgeable IP identity.
    if settings.evidentia_trusted_proxy_count > 0 and not settings.evidentia_bff_secret.strip():
        problems.append(
            "EVIDENTIA_TRUSTED_PROXY_COUNT > 0 requires EVIDENTIA_BFF_SECRET, or a directly "
            "reachable backend would trust a forged X-Forwarded-For. Set the secret (and the "
            "same value in the frontend) or isolate the backend and set the hop count to 0."
        )

    # 3. Password reset and email verification are only real if mail is really
    #    delivered. `console` writes single-use links to the logs and `noop` drops
    #    them silently — both make the feature *look* like it works.
    email_problem = settings.email_config_problem()
    if email_problem:
        problems.append(email_problem)

    # 3b. A guessable BFF secret is equivalent to no BFF secret.
    try:
        settings.validate_bff_secret()
    except RuntimeError as exc:
        problems.append(str(exc))

    # 4. Authentication and tenancy both require the database — there is no
    #    degraded mode, and generation cannot keep its 200-means-saved promise.
    if not settings.is_db_enabled():
        problems.append(
            "EVIDENTIA_DB_ENABLED=false is not permitted in production: authentication, "
            "tenancy and report persistence all require the database."
        )

    # 5. A wildcard CORS origin on a credentialed API.
    if settings.cors_origins() == ["*"]:
        problems.append(
            "EVIDENTIA_CORS_ORIGINS=* is not permitted in production; list explicit origins."
        )

    if problems:
        raise RuntimeError(
            "Refusing to start in production with an unsafe configuration:\n  - "
            + "\n  - ".join(problems)
        )


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    if settings.is_production():
        validate_production_config(settings)
    elif settings.evidentia_rate_limit_enabled and settings.evidentia_trusted_proxy_count == 0:
        logger.warning(
            "EVIDENTIA_TRUSTED_PROXY_COUNT=0: per-IP rate limits key on the TCP peer. "
            "Behind the Next.js BFF this collapses every user onto one IP budget."
        )
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
def generate_workflow(
    request: Request,
    body: GenerateRequest,
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
):
    """Generate a report for the caller's tenant. Requires authentication.

    The report is persisted against the authenticated user's company — there is
    no shared demo company to fall back into.
    """
    # This endpoint spends LLM budget, so it carries its own (much tighter)
    # limits: per user, per tenant, and per IP. Enforced after authentication so
    # an anonymous flood is rejected by the 401 first, and the budget is only
    # ever consumed by a caller we can attribute.
    enforce_generation(request, user_id=ctx.user_id, company_id=ctx.company_id)

    # A 200 from this endpoint is a promise: the report exists, has an id, and can
    # be fetched back. Persistence is therefore NOT best-effort — if it fails, the
    # request failed. Returning an unsaved report with 200 sent the client to a
    # report id that did not exist, and billed an LLM call for nothing.
    settings = get_settings()
    if not settings.is_db_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "persistence_unavailable",
                "message": "Report storage is unavailable; no report was generated.",
            },
        )

    # Deterministic (optionally LLM-assisted) generation; never raises for LLM issues.
    report = run_pipeline(
        market=body.market,
        persona=body.persona,
        custom_persona=body.customPersona,
        selected_document_ids=body.selectedDocumentIds,
    )

    try:
        row = reports_repo.create_report(db, ctx.company_id, report, user_id=ctx.user_id)
    except Exception as exc:  # noqa: BLE001 - surfaced as a failure, never as success
        logger.error("Report persistence failed: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "persistence_failed",
                "message": "The report could not be saved. Nothing was stored; please retry.",
            },
        )

    return row.report_json  # includes the DB id
