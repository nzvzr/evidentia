"""SectionProvider — the seam the pipeline loads its evidence through (M1).

`run_pipeline` today calls `document_reader` directly, which hardwires the
bundled demo corpus into generation. This Protocol is the M1 seam that breaks
that coupling without changing behaviour:

    SectionProvider.load(selected_document_ids) -> (documents, sections)

returning exactly the two lists `agents/document_reader.py` returns today —
document metadata dicts and the pipeline currency section dicts
(`{documentId, source, sectionTitle, excerpt, category, citationId}`, the
strict projection of `SectionRecord v1`; see `app/contracts.py`). Because the
currency is unchanged, every scorer, gate and binder downstream is
provider-agnostic by construction.

Implementations:

* `DemoCorpusProvider` (here, M1) — delegates to the existing demo
  `document_reader`. Byte-for-byte identical output; the demo corpus keeps its
  three jobs (public demo route, benchmark bed, empty-tenant experience).
* `TenantCorpusProvider` (M4) — tenant-scoped load of `ready`
  `document_sections` for the selected ids, plus the orchestrator injection
  that chooses between the two. Not part of M1: nothing calls this seam yet,
  which is exactly what keeps M1 behaviour-neutral with
  EVIDENTIA_TENANT_CORPUS_ENABLED off.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, Tuple

from app.agents.document_reader import document_reader


class SectionProvider(Protocol):
    """Load the documents + sections a generation runs against."""

    def load(
        self, selected_document_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:  # pragma: no cover
        """(document metadata dicts, pipeline-currency section dicts) for the
        selection. Unknown ids are dropped silently (absence-shaped, consistent
        with the tenancy doctrine); an empty resolution falls back to the
        provider's default corpus."""
        ...


class DemoCorpusProvider:
    """The bundled demo corpus behind the seam. Output is byte-for-byte what
    `document_reader(...)` returns today."""

    def load(
        self, selected_document_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        return document_reader(selected_document_ids)
