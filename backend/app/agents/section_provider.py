"""Explicit demo/tenant evidence providers used by the generation pipeline.

The provider is selected once at request start.  A tenant provider freezes the
exact eligible M3 versions and their selected sections in memory before any LLM
call; it never re-follows ``documents.current_version_id`` and never reads the
bundled demo corpus.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Protocol, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.document_reader import document_reader
from app.models.db_models import Document, DocumentSection, DocumentVersion
from app.services.generation_eligibility import check_generation_eligibility

RETRIEVAL_ENGINE_VERSION = "tenant-lexical-v1"
RETRIEVAL_CONFIG_VERSION = "trc1"
SNAPSHOT_DIGEST_VERSION = "tcs1"
GENERATION_ENGINE_VERSION = "evidentia-orchestrator-v1"

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.ASCII)
_UNTRUSTED_CITATION_REQUEST_RE = re.compile(
    r"\b[A-Z][A-Z0-9]{1,11}-[A-Za-z0-9.-]*[0-9][A-Za-z0-9.-]*\b"
)
_UNTRUSTED_EVIDENCE_CLOSE_RE = re.compile(r"</untrusted-evidence>", re.IGNORECASE)
_STOP = frozenset(
    {"the", "and", "for", "with", "that", "this", "from", "into", "your", "are", "you"}
)


class CorpusMode(str, Enum):
    DEMO = "demo"
    TENANT = "tenant"


class TenantCorpusError(RuntimeError):
    """A safe, typed provider failure.  ``message`` never contains source text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TenantRetrievalConfig:
    max_documents: int
    max_candidate_sections: int
    max_selected_sections: int
    max_total_chars: int
    per_document_cap: int
    excerpt_chars: int
    config_version: str = RETRIEVAL_CONFIG_VERSION

    def validate(self) -> None:
        values = (
            self.max_documents,
            self.max_candidate_sections,
            self.max_selected_sections,
            self.max_total_chars,
            self.per_document_cap,
            self.excerpt_chars,
        )
        if any(not isinstance(value, int) or value <= 0 for value in values):
            raise TenantCorpusError(
                "tenant_retrieval_failed", "Tenant retrieval configuration is invalid."
            )


@dataclass(frozen=True)
class SourceVersionSnapshot:
    document_id: str
    document_version_id: str
    version_no: int
    document_title: str
    original_filename: str | None
    manifest_sha256: str
    finalization_target_digest: str
    parser_version: str | None
    anchor_algo_version: str
    position: int


@dataclass(frozen=True)
class RetrievedEvidence:
    company_id: str
    document_id: str
    document_version_id: str
    document_title: str
    original_filename: str | None
    version_no: int
    section_id: str
    section_ordinal: int
    heading_path: tuple[str, ...]
    section_title: str
    text: str
    text_sha256: str
    excerpt: str
    anchor_id: str
    citation_id: str
    category: str | None
    topics: tuple[str, ...]
    market_flags: tuple[str, ...]
    persona_affinity: Dict[str, Any]
    injection_flags: tuple[str, ...]
    section_signature: str
    document_manifest_sha256: str
    finalization_target_digest: str
    anchor_algo_version: str
    retrieval_score: float
    retrieval_rank: int
    matched_terms: tuple[str, ...]


class SectionProvider(Protocol):
    """Load the documents + sections a generation runs against."""

    corpus_mode: CorpusMode
    cache_identity: str

    def load(
        self, selected_document_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:  # pragma: no cover
        ...


class DemoCorpusProvider:
    """The bundled, public sample corpus.  It never opens a database session."""

    corpus_mode = CorpusMode.DEMO
    cache_identity = "demo-corpus-v1"

    def load(
        self, selected_document_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        return document_reader(selected_document_ids)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token for token in _TOKEN_RE.findall((value or "").lower()) if len(token) >= 3 and token not in _STOP
    )


def _bounded_excerpt(value: str, limit: int) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"


def _score(row: DocumentSection, doc: Document, query_terms: frozenset[str]) -> tuple[float, tuple[str, ...]]:
    if not query_terms:
        return 0.0, ()
    title_terms = _tokens(" ".join([*(row.heading_path or []), row.title or ""]))
    document_terms = _tokens(doc.title or "")
    classification_terms = _tokens(
        " ".join(
            [
                row.category or "",
                *(str(v) for v in (row.topics or [])),
                *(str(v) for v in (row.market_flags or [])),
                *(str(v) for v in (row.keywords or [])),
            ]
        )
    )
    text_terms = frozenset(str(v).lower() for v in (row.token_set or [])) or _tokens(row.text)
    matched = query_terms & (title_terms | document_terms | classification_terms | text_terms)
    score = (
        5 * len(query_terms & title_terms)
        + 3 * len(query_terms & document_terms)
        + 2 * len(query_terms & classification_terms)
        + len(query_terms & text_terms)
    )
    return float(score), tuple(sorted(matched))


def _candidate_sort_key(
    item: tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]],
) -> tuple[Any, ...]:
    doc, version, row, score, _matched = item
    return (-score, doc.id, version.version_no, version.id, row.ordinal, row.anchor_id)


def _bounded_scored_rows(
    rows: Any,
    *,
    doc: Document,
    version: DocumentVersion,
    query_terms: frozenset[str],
    limit: int,
) -> list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]]:
    """Score a streamed version and retain only its deterministic top ``limit``.

    Merging fixed-size batches bounds application memory independently of a
    document's section count while producing the same result as a full sort.
    """
    batch_size = min(256, limit)
    top: list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]] = []
    batch: list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]] = []
    for row in rows:
        score, matched = _score(row, doc, query_terms)
        batch.append((doc, version, row, score, matched))
        if len(batch) >= batch_size:
            top = sorted([*top, *batch], key=_candidate_sort_key)[:limit]
            batch = []
    if batch:
        top = sorted([*top, *batch], key=_candidate_sort_key)[:limit]
    return top


def _diverse_candidate_truncation(
    row_groups: list[
        tuple[
            Document,
            DocumentVersion,
            list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]],
        ]
    ],
    limit: int,
) -> list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]]:
    """Take scored per-document candidates in deterministic rank rounds."""
    candidates: list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]] = []
    offset = 0
    while len(candidates) < limit:
        progressed = False
        for _doc, _version, rows in row_groups:
            if offset >= len(rows):
                continue
            candidates.append(rows[offset])
            progressed = True
            if len(candidates) >= limit:
                break
        if not progressed:
            break
        offset += 1
    return sorted(candidates, key=_candidate_sort_key)


class TenantCorpusProvider:
    """Frozen, company-scoped M3 evidence snapshot for one generation."""

    corpus_mode = CorpusMode.TENANT

    def __init__(
        self,
        *,
        company_id: str,
        company_name: str,
        user_id: str | None,
        documents: List[Dict[str, Any]],
        sections: List[Dict[str, Any]],
        source_versions: tuple[SourceVersionSnapshot, ...],
        evidence: tuple[RetrievedEvidence, ...],
        snapshot_digest: str,
        config: TenantRetrievalConfig,
    ) -> None:
        self.company_id = company_id
        self.company_name = company_name
        self.user_id = user_id
        self._documents = documents
        self._sections = sections
        self.source_versions = source_versions
        self.evidence = evidence
        self.snapshot_digest = snapshot_digest
        self.config = config
        self.cache_identity = f"tenant:{company_id}:{snapshot_digest}"

    @classmethod
    def prepare(
        cls,
        db: Session,
        *,
        company_id: str,
        company_name: str,
        user_id: str | None,
        selected_document_ids: List[str],
        query: str,
        config: TenantRetrievalConfig,
    ) -> "TenantCorpusProvider":
        """Resolve eligibility and freeze exact rows in one short DB phase."""
        config.validate()
        try:
            active_documents = list(
                db.execute(
                    select(Document)
                    .where(Document.company_id == company_id, Document.deleted_at.is_(None))
                    .order_by(Document.id.asc())
                ).scalars()
            )
            if not active_documents:
                raise TenantCorpusError(
                    "tenant_corpus_empty",
                    "Finalize at least one eligible document before generating a tenant report.",
                )

            # Unknown/foreign ids grant no selection authority.  If at least one
            # owned id was named, use only owned named ids; otherwise use the
            # tenant's bounded eligible corpus (legacy workspace compatibility).
            requested = set(selected_document_ids)
            owned_requested = {doc.id for doc in active_documents if doc.id in requested}
            scoped_documents = (
                [doc for doc in active_documents if doc.id in owned_requested]
                if owned_requested
                else active_documents
            )

            eligible: list[tuple[Document, DocumentVersion]] = []
            for doc in scoped_documents:
                if not doc.current_version_id:
                    continue
                version = db.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.id == doc.current_version_id,
                        DocumentVersion.document_id == doc.id,
                        DocumentVersion.company_id == company_id,
                    )
                ).scalar_one_or_none()
                if check_generation_eligibility(db, version, company_id=company_id).eligible:
                    eligible.append((doc, version))  # exact immutable id, never re-followed
                    if len(eligible) >= config.max_documents:
                        break

            if not eligible:
                raise TenantCorpusError(
                    "tenant_corpus_ineligible",
                    "Finalize at least one eligible document before generating a tenant report.",
                )

            source_versions = tuple(
                SourceVersionSnapshot(
                    document_id=doc.id,
                    document_version_id=version.id,
                    version_no=version.version_no,
                    document_title=doc.title,
                    original_filename=doc.original_filename,
                    manifest_sha256=version.manifest_sha256 or "",
                    finalization_target_digest=version.finalization_engine or "",
                    parser_version=version.parser_version,
                    anchor_algo_version=version.anchor_algo_version or "",
                    position=position,
                )
                for position, (doc, version) in enumerate(eligible)
            )

            query_terms = _tokens(query)
            eligible_version_ids = [version.id for _doc, version in eligible]
            duplicate_citation = db.execute(
                    select(DocumentSection.citation_id)
                    .where(
                        DocumentSection.company_id == company_id,
                        DocumentSection.version_id.in_(eligible_version_ids),
                    )
                    .group_by(DocumentSection.citation_id)
                    .having(func.count(DocumentSection.id) > 1)
                    .limit(1)
                ).scalar_one_or_none()
            if duplicate_citation is not None:
                raise TenantCorpusError(
                    "evidence_validation_failed",
                    "The tenant corpus contains an ambiguous citation identity.",
                )
            row_groups: list[
                tuple[
                    Document,
                    DocumentVersion,
                    list[tuple[Document, DocumentVersion, DocumentSection, float, tuple[str, ...]]],
                ]
            ] = []
            for doc, version in eligible:
                rows = db.execute(
                    select(DocumentSection)
                    .where(
                        DocumentSection.company_id == company_id,
                        DocumentSection.document_id == doc.id,
                        DocumentSection.version_id == version.id,
                    )
                    .order_by(DocumentSection.ordinal.asc(), DocumentSection.anchor_id.asc())
                    .execution_options(yield_per=min(256, config.max_candidate_sections))
                ).scalars()
                top_rows = _bounded_scored_rows(
                    rows,
                    doc=doc,
                    version=version,
                    query_terms=query_terms,
                    limit=config.max_candidate_sections,
                )
                row_groups.append((doc, version, top_rows))

            # Score the full streamed corpus before the final bounded global
            # truncation. Rank rounds preserve document diversity; the final
            # sort and selection retain explicit score/identity tie-breaking.
            candidates = _diverse_candidate_truncation(
                row_groups, config.max_candidate_sections
            )
            chosen = []
            per_document: dict[str, int] = {}
            total_chars = 0
            for item in candidates:
                doc, _version, row, _score_value, _matched = item
                if len(chosen) >= config.max_selected_sections:
                    break
                if per_document.get(doc.id, 0) >= config.per_document_cap:
                    continue
                if total_chars + len(row.text) > config.max_total_chars:
                    continue
                chosen.append(item)
                per_document[doc.id] = per_document.get(doc.id, 0) + 1
                total_chars += len(row.text)

            if not chosen:
                raise TenantCorpusError(
                    "tenant_retrieval_failed", "Tenant retrieval produced no bounded evidence."
                )

            evidence_rows: list[RetrievedEvidence] = []
            pipeline_sections: list[Dict[str, Any]] = []
            for rank, (doc, version, row, score, matched) in enumerate(chosen, start=1):
                excerpt = _bounded_excerpt(row.excerpt or row.text, config.excerpt_chars)
                if row.injection_flags or _UNTRUSTED_EVIDENCE_CLOSE_RE.search(excerpt):
                    # Stored source text remains byte-for-byte untouched. The
                    # prompt/UI excerpt is a derived view and neutralizes only
                    # citation-shaped commands from content classified as
                    # injection or attempting to close the evidence wrapper.
                    excerpt = _UNTRUSTED_CITATION_REQUEST_RE.sub(
                        "[untrusted citation request omitted]", excerpt
                    )
                evidence = RetrievedEvidence(
                    company_id=company_id,
                    document_id=doc.id,
                    document_version_id=version.id,
                    document_title=doc.title,
                    original_filename=doc.original_filename,
                    version_no=version.version_no,
                    section_id=row.id,
                    section_ordinal=row.ordinal,
                    heading_path=tuple(str(v) for v in (row.heading_path or [])),
                    section_title=row.title,
                    text=row.text,
                    text_sha256=row.text_sha256 or "",
                    excerpt=excerpt,
                    anchor_id=row.anchor_id,
                    citation_id=row.citation_id,
                    category=row.category,
                    topics=tuple(str(v) for v in (row.topics or [])),
                    market_flags=tuple(str(v) for v in (row.market_flags or [])),
                    persona_affinity=dict(row.persona_affinity or {}),
                    injection_flags=tuple(str(v) for v in (row.injection_flags or [])),
                    section_signature=row.classification_signature or "",
                    document_manifest_sha256=version.manifest_sha256 or "",
                    finalization_target_digest=version.finalization_engine or "",
                    anchor_algo_version=version.anchor_algo_version or "",
                    retrieval_score=score,
                    retrieval_rank=rank,
                    matched_terms=matched,
                )
                evidence_rows.append(evidence)
                pipeline_sections.append(
                    {
                        "documentId": doc.id,
                        "versionId": version.id,
                        "source": doc.title,
                        "sectionTitle": row.title,
                        "headingPath": list(evidence.heading_path),
                        "ordinal": row.ordinal,
                        "text": row.text,
                        "tokenSet": list(row.token_set or []),
                        "excerpt": excerpt,
                        "category": row.category or "General",
                        "topics": list(evidence.topics),
                        "citationId": row.citation_id,
                        "anchorId": row.anchor_id,
                        "retrievalScore": score,
                        "retrievalRank": rank,
                    }
                )

            selected_document_ids = {e.document_id for e in evidence_rows}
            pipeline_documents = [
                {
                    "id": doc.id,
                    "title": doc.title,
                    "short": doc.title,
                    "type": doc.type or "Document",
                    "category": doc.category or "General",
                    "extent": f"{version.section_count or 0} sections",
                    "lastUpdated": doc.updated_at.isoformat() if doc.updated_at else "",
                    "format": doc.mime_type or "text",
                    "citationPrefix": doc.citation_prefix or "",
                    "citationIds": [e.citation_id for e in evidence_rows if e.document_id == doc.id],
                    "usedByPersonas": [],
                    "topics": sorted({topic for e in evidence_rows if e.document_id == doc.id for topic in e.topics}),
                }
                for doc, version in eligible
                if doc.id in selected_document_ids
            ]

            digest_payload = {
                "version": SNAPSHOT_DIGEST_VERSION,
                "companyId": company_id,
                "sources": [
                    {
                        "documentId": source.document_id,
                        "documentVersionId": source.document_version_id,
                        "manifestSha256": source.manifest_sha256,
                    }
                    for source in sorted(source_versions, key=lambda value: value.document_version_id)
                ],
                "retrievalEngine": RETRIEVAL_ENGINE_VERSION,
                "retrievalConfig": asdict(config),
            }
            snapshot_digest = hashlib.sha256(
                json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest()

            return cls(
                company_id=company_id,
                company_name=company_name,
                user_id=user_id,
                documents=pipeline_documents,
                sections=pipeline_sections,
                source_versions=source_versions,
                evidence=tuple(evidence_rows),
                snapshot_digest=f"{SNAPSHOT_DIGEST_VERSION}:{snapshot_digest}",
                config=config,
            )
        except TenantCorpusError:
            raise
        except Exception as exc:  # fail closed without putting tenant text in the error/log
            raise TenantCorpusError(
                "tenant_retrieval_failed", "Tenant evidence could not be retrieved safely."
            ) from exc

    def load(
        self, _selected_document_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # Defensive copies keep a downstream agent from mutating the frozen
        # provider snapshot or changing what provenance is later persisted.
        return copy.deepcopy(self._documents), copy.deepcopy(self._sections)

    def source_versions_json(self) -> list[dict[str, Any]]:
        return [
            {
                "documentId": source.document_id,
                "versionId": source.document_version_id,
                "versionNo": source.version_no,
                "parserVersion": source.parser_version,
            }
            for source in self.source_versions
        ]
