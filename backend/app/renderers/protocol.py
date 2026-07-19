"""The format-independent renderer contract (L9, `PLATFORM_ARCHITECTURE.md` §2.3).

Every renderer — the DOCX renderer here, and the PDF/PPTX/XLSX/HTML renderers
that follow — implements the same shape:

    render(snapshot, options) -> artifact

The transformation is **pure and deterministic**: the same persisted snapshot
and the same options must always produce the same artifact. Nothing in this
module (or any renderer implementing it) may call an LLM, open a network socket,
read a live tenant document pointer, or mutate the snapshot.

This module owns only the neutral contract types. The typed snapshot that is fed
in lives in ``snapshot.py`` so the reasoning engine never has to import a
renderer to describe its own output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, runtime_checkable

from app.renderers.snapshot import ReportSnapshot


class RendererError(RuntimeError):
    """A safe, typed renderer failure.

    ``message`` is caller-safe and never contains tenant source text; ``code`` is
    a stable machine-readable string the API layer maps to a status code.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RendererOptions:
    """Caller-chosen, deterministic rendering options.

    These are the *only* inputs beyond the persisted snapshot. They must not
    smuggle in content: no report text, no citation data, no wall-clock time.
    Two renders with equal options and equal snapshot are byte-identical.
    """

    page_size: str = "A4"  # "A4" | "Letter"
    include_table_of_contents: bool = True
    include_audit_appendix: bool = True
    include_evidence_excerpts: bool = True
    # Absolute ceiling on the produced artifact; the renderer refuses to emit
    # anything larger rather than stream an unbounded document.
    max_output_bytes: int = 12 * 1024 * 1024

    def normalized(self) -> "RendererOptions":
        page = "Letter" if str(self.page_size).strip().lower() in {"letter", "us letter", "us-letter"} else "A4"
        return RendererOptions(
            page_size=page,
            include_table_of_contents=bool(self.include_table_of_contents),
            include_audit_appendix=bool(self.include_audit_appendix),
            include_evidence_excerpts=bool(self.include_evidence_excerpts),
            max_output_bytes=int(self.max_output_bytes),
        )


@dataclass(frozen=True)
class RenderedArtifact:
    """The output of a renderer: bytes plus the metadata the delivery layer needs.

    ``content_hash`` is the SHA-256 of ``data`` (the exact bytes delivered).
    ``semantic_digest`` is a deterministic hash over the normalized *input* +
    rendered document body, independent of the ZIP container — it is what proves
    two renders are logically identical even if a future library made the
    container bytes wobble.
    """

    data: bytes
    filename: str
    content_type: str
    renderer_id: str
    renderer_version: str
    content_hash: str
    semantic_digest: str
    byte_size: int
    telemetry: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Renderer(Protocol):
    """A pull renderer: ``render(snapshot, options) -> artifact``.

    Implementations are stateless and side-effect free. ``renderer_id`` and
    ``renderer_version`` are stable identifiers recorded in artifact metadata and
    the document's own audit appendix.
    """

    renderer_id: str
    renderer_version: str
    content_type: str

    def render(self, snapshot: ReportSnapshot, options: RendererOptions) -> RenderedArtifact:  # pragma: no cover - protocol
        ...
