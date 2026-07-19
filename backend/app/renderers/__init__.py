"""Output renderers (L9).

A renderer is a **pure, deterministic transformation** of an immutable persisted
analysis snapshot into a deliverable artifact (`PLATFORM_ARCHITECTURE.md` §2.2,
L9). Renderers never call an LLM, never retrieve documents, never score or
mutate evidence, and never perform domain reasoning: they read the persisted
report snapshot plus its report-local source audit and emit bytes.

`Renderer` (protocol.py) is the format-independent contract. `DocxRenderer`
(docx_renderer.py) is the first concrete implementation (Renderer Track R1); the
PDF/PPTX/XLSX renderers named in the architecture are later, independent
implementations behind the same contract.
"""

from app.renderers.protocol import (
    RenderedArtifact,
    Renderer,
    RendererError,
    RendererOptions,
)
from app.renderers.snapshot import ReportSnapshot, TenantDisplay

__all__ = [
    "RenderedArtifact",
    "Renderer",
    "RendererError",
    "RendererOptions",
    "ReportSnapshot",
    "TenantDisplay",
]
