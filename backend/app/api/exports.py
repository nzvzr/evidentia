"""Authenticated, tenant-scoped report export endpoints (Phase 7).

    GET /api/reports/{report_id}/export/docx

Renders a persisted, completed report to an editable DOCX **on demand and in
memory** (R1 preference — no artifact persistence, no temp files, no local paths
exposed). Everything the renderer needs is loaded server-side from the caller's
own tenant:

* the exact persisted ``EvidentiaReport`` JSON (completed rows only), and
* its report-local M4 source audit.

Authorization is identical to the rest of the report API: the report id alone is
never sufficient — ``reports_repo.get_report`` requires the membership-derived
``company_id``, so another tenant's report id resolves to an enumeration-safe
404, exactly as if it did not exist. Browser-supplied company authority is
ignored (the tenant comes from ``CompanyContext``).

The renderer is pure: this endpoint performs no retrieval, no LLM call, and never
follows a live/current document version — it reads only what was persisted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import CompanyContext, get_company_context
from app.api.limits import enforce_export
from app.core.config import get_settings
from app.db.session import get_db
from app.renderers.docx_renderer import DocxRenderer
from app.renderers.protocol import RendererError, RendererOptions
from app.renderers.snapshot import ReportSnapshot, TenantDisplay
from app.repositories import reports as reports_repo

router = APIRouter(prefix="/api/reports", tags=["exports"])

_DOCX_RENDERER = DocxRenderer()


def _content_disposition(filename: str) -> str:
    """A safe ``attachment`` disposition. ``filename`` is already an ASCII slug
    from ``sanitize.safe_filename`` (no quotes, spaces, or path separators), so a
    plain quoted form is unambiguous; the RFC 5987 form is added for good
    measure."""
    return f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}'


@router.get("/{report_id}/export/docx")
def export_report_docx(
    report_id: str,
    request: Request,
    page: str = Query(default="A4"),
    ctx: CompanyContext = Depends(get_company_context),
    db: Session = Depends(get_db),
) -> Response:
    settings = get_settings()
    if not settings.is_db_enabled():
        # Without the database there is no tenant report to export.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    # CPU budget, keyed per IP/user/tenant. Enforced after auth so an anonymous
    # flood is stopped by the 401 first.
    enforce_export(request, user_id=ctx.user_id, company_id=ctx.company_id)

    # Tenant-scoped, completed-only. Another tenant's id — or a running/failed
    # report — resolves to None here and is reported as an enumeration-safe 404.
    row = reports_repo.get_report(db, report_id, ctx.company_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    # The report-local source audit (same tenant scope). Absent for very old
    # rows; the renderer surfaces that honestly rather than inventing sources.
    source_audit = reports_repo.get_report_sources(db, report_id, ctx.company_id)

    snapshot = ReportSnapshot.from_persisted(
        row.report_json or {},
        source_audit,
        TenantDisplay(company_name=ctx.company.name, company_id=ctx.company_id),
    )
    options = RendererOptions(
        page_size=page,
        max_output_bytes=settings.evidentia_export_max_bytes,
    )

    try:
        artifact = _DOCX_RENDERER.render(snapshot, options)
    except RendererError as exc:
        # A safe, typed renderer failure (e.g. output-size cap). No tenant text
        # is ever placed in the error surface or logs.
        code_status = {
            "export_too_large": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        }.get(exc.code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        raise HTTPException(
            status_code=code_status, detail={"code": exc.code, "message": exc.message}
        ) from None

    return Response(
        content=artifact.data,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": _content_disposition(artifact.filename),
            "Content-Length": str(artifact.byte_size),
            "Cache-Control": "no-store",
            "X-Evidentia-Renderer": artifact.renderer_id,
            "X-Evidentia-Renderer-Version": artifact.renderer_version,
            "X-Evidentia-Content-Hash": artifact.content_hash,
            "X-Evidentia-Semantic-Digest": artifact.semantic_digest,
        },
    )
