"""SQLAlchemy ORM models.

UUID primary keys are stored as 36-char strings for cross-database portability
(SQLite in dev, PostgreSQL in production). JSON columns use SQLAlchemy's generic
JSON type, which maps to JSONB-compatible storage on Postgres and TEXT on SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Role hierarchy for company membership. Higher rank implies every capability of
# the ranks below it.
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_RANK = {ROLE_MEMBER: 1, ROLE_ADMIN: 2, ROLE_OWNER: 3}

# Document ingestion states (design: docs/ai/DOCUMENT_INGESTION_ARCHITECTURE.md §3).
# `documents.status` is the coarse per-document view; `document_versions.status`
# is the per-version pipeline state. A version is visible to generation only
# when `ready` — completely or not at all.
DOCUMENT_STATUS_EMPTY = "empty"
DOCUMENT_STATUS_PROCESSING = "processing"
DOCUMENT_STATUS_READY = "ready"
DOCUMENT_STATUS_FAILED = "failed"

VERSION_STATUS_PENDING = "pending"
VERSION_STATUS_EXTRACTING = "extracting"
VERSION_STATUS_SECTIONING = "sectioning"
VERSION_STATUS_ANCHORING = "anchoring"
VERSION_STATUS_CLASSIFYING = "classifying"
VERSION_STATUS_READY = "ready"
VERSION_STATUS_FAILED = "failed"

JOB_STATE_QUEUED = "queued"
JOB_STATE_RUNNING = "running"
JOB_STATE_SUCCEEDED = "succeeded"
JOB_STATE_FAILED = "failed"

# Ingestion job operations (M3). `ingest` is the M2 semantics (extract ->
# sectionize -> transitional-ready); `finalize` is the M3 successor-version
# path (re-ingest the retained source blob with final anchors, citation
# identities, deterministic classification and a final manifest). Explicit and
# typed so the two kinds of work are never conflated in the job table.
JOB_OPERATION_INGEST = "ingest"
JOB_OPERATION_FINALIZE = "finalize"


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Null until the user confirms an email-verification token.
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bumped on password reset and logout-all. Access tokens carry the version they
    # were minted with (`tv`); a mismatch invalidates them immediately, which is
    # what makes a stateless JWT revocable before its TTL runs out.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    # The single accountable owner. Membership rows still carry roles; this is
    # the authoritative pointer for ownership transfer and deletion.
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyMember(Base):
    __tablename__ = "company_members"
    # A user holds exactly one role per company.
    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_company_members_company_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_MEMBER)  # owner | admin | member
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RefreshToken(Base):
    """A rotating refresh token.

    Only the SHA-256 digest is stored. Rotation chains share a `family_id`: if a
    token that was already rotated (or revoked) is presented again, the whole
    family is revoked — that is the standard stolen-token reuse detection.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # citation_prefix is identity, unique per tenant (minted at M3). The
        # database enforces it so minting can never race itself into two
        # documents sharing a citation family. Nullable stays nullable: NULLs
        # are distinct under both PostgreSQL and SQLite unique-index semantics,
        # so pre-M3 documents (all NULL) coexist freely.
        Index("uq_documents_company_citation_prefix", "company_id", "citation_prefix", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(300), index=True)
    type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # DEPRECATED after M1: retained for backfill/back-compat only. The ingestion
    # pipeline stores original bytes in document_blobs and extracted sections in
    # document_sections; an explicit removal milestone follows backfill
    # verification (debt watch, PLATFORM_ARCHITECTURE.md §12).
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # --- ingestion (M1, additive; unused while EVIDENTIA_TENANT_CORPUS_ENABLED
    # is off — which is the default) ---
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="api")
    origin_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)  # connector seam
    original_filename: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # latest original bytes
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 3–5 uppercase base chars + numeric collision suffix, unique per tenant;
    # minted by the anchor/citation scheme (M3) and immutable thereafter — the
    # prefix is identity, not description. Nullable until M3 assigns them.
    # Width 12 = 5-char base + up to 7 suffix digits: capacity beyond any
    # configured tenant document quota (candidates are minted through quota+1).
    citation_prefix: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    # Pointer to the version generation reads. Flipped atomically, only to
    # `ready` versions. Deliberately NOT a DB-level foreign key: documents and
    # document_versions would then reference each other, and SQLite (the dev
    # database, where tests create the schema via create_all) cannot add the
    # second constraint of a circular pair. Integrity is application-enforced
    # by the single flip site, the same posture as `company.owner_id` re-derivation.
    current_version_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=DOCUMENT_STATUS_EMPTY)
    # Soft delete: hides the document from listings/picker/generation but keeps
    # rows so existing reports' "view source" can say why a citation no longer
    # resolves. Hard purge is a separate, explicit admin action (later milestone).
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentVersion(Base):
    """One immutable ingested revision of a document.

    Immutable once `ready`: rows are never edited in place, and a failed
    re-upload never degrades a working document (`current_version_id` only ever
    flips to a `ready` version). `company_id` is denormalized deliberately so
    every lookup keeps the "impossible by construction" tenancy shape without
    joins — the same posture as every other tenant-scoped table.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        # Also the document_id access path: its leftmost column serves every
        # document_id-only lookup, so no separate single-column index exists.
        UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_no"),
        # M3: at most ONE finalization successor per (source version, COMPLETE
        # finalization target), enforced by the database — concurrent
        # finalization triggers racing past the application pre-select cannot
        # create two successors. NULLs are distinct on both PostgreSQL and
        # SQLite, so ordinary upload versions (source_version_id NULL) coexist
        # freely.
        Index(
            "uq_document_versions_source_engine",
            "source_version_id",
            "finalization_engine",
            unique=True,
        ),
        # M3: composite parent key for the tenant-safe self-reference below.
        UniqueConstraint(
            "id", "document_id", "company_id",
            name="uq_document_versions_id_doc_company",
        ),
        # M3: the DATABASE enforces that a successor's source version belongs
        # to the SAME document and the SAME tenant — a cross-document or
        # cross-tenant source_version_id is unrepresentable, not merely
        # service-checked. Default (NO ACTION) referential semantics: deleting
        # a source version alone while a successor references it fails at
        # statement end on PostgreSQL and SQLite alike, while a whole-document
        # (or tenant) CASCADE — which removes source and successor together —
        # still passes. Rule (explicit): a successor references ONLY the
        # blob-owning transitional upload version (never another successor);
        # the service layer enforces that direction via the
        # `pre-m3-transitional` eligibility check, and the successor itself
        # carries no blob row — its bytes resolve through this reference.
        ForeignKeyConstraint(
            ["source_version_id", "document_id", "company_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.company_id",
            ],
            name="fk_document_versions_source_same_doc",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE")
    )
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # Hashes: original bytes / normalized extracted text / ordered section
    # anchors+hashes (cheap whole-version equality).
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extracted_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    manifest_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Provenance: which parser produced the extraction (re-ingestion trigger on
    # parser upgrades) and which anchor algorithm minted the section identities
    # (versioned like a public schema — PLATFORM_ARCHITECTURE.md §7; populated
    # from M3).
    parser_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    anchor_algo_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # --- M3 finalization provenance (additive; NULL on ordinary uploads) ---
    # The pre-m3-transitional version this row was re-ingested from. Guarded
    # by the composite self-referential FK in __table_args__: the database
    # itself rejects a source in another document or another tenant and
    # blocks deleting a referenced source, while whole-document CASCADE
    # (removing source + successor together) still works.
    source_version_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # The COMPLETE finalization target digest ("cft1:<sha256>") this successor
    # was produced for — parser/normalizer/sectionizer/anchor/inheritance/
    # classifier/module/manifest/thresholds, never a single component label.
    # Part of the one-successor-per-(source, target) uniqueness above.
    finalization_engine: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Bounded typed dict of every load-bearing derived-processing version
    # (parser, normalizer, sectionizer, anchor algo, inheritance, classifier,
    # module id/version/digest). Written once with the final manifest.
    engine_versions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Version-level deterministic classification signature: sha256 over the
    # ordered per-section signatures + engine/module versions. Proves which
    # deterministic engine produced the classification set.
    classification_signature: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=VERSION_STATUS_PENDING)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DocumentBlob(Base):
    """Original uploaded bytes for one document version (1–1).

    Accessed only through the `BlobStore` seam (`services/blob_store.py`) —
    DB-backed `bytea`/BLOB now, object storage later with zero call-site
    changes. Blobs are never served back for download in v1; they exist for
    re-ingestion after parser upgrades and for support.

    Crash-safe write order (binding; see the M1 migration docstring):
    version row (`pending`) -> blob put -> work proceeds. A crash between steps
    leaves an inert pending row or an orphaned blob, never a version claiming
    bytes that do not exist. Orphaned blobs are removed by a periodic
    reconciliation sweep (blobs unreferenced past a grace window).
    """

    __tablename__ = "document_blobs"
    __table_args__ = (
        # 1–1 with the version: a second blob for the same version is a bug.
        UniqueConstraint("version_id", name="uq_document_blobs_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # Where the bytes live. DB-backed v1 stores them in `data` and records
    # "db:<id>" here; an object-storage implementation records its object key
    # and leaves `data` NULL.
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentSection(Base):
    """One immutable extracted section of a document version.

    The persisted form of `SectionRecord v1` (`app/contracts.py`): identity
    (anchor + rendered citation id), full bounded scoring text with a
    precomputed token set, and deterministic classification with provenance.
    Rows are written in one transaction per version and never edited — a
    version's sections are visible completely or not at all.
    """

    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint("version_id", "anchor_id", name="uq_document_sections_version_anchor"),
        UniqueConstraint("version_id", "ordinal", name="uq_document_sections_version_ordinal"),
        # Also the company_id access path via its leftmost column, so no
        # separate single-column company_id index exists.
        Index("ix_document_sections_company_document", "company_id", "document_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE")
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )

    # identity (immutable; minted by the versioned anchor algorithm from M3)
    anchor_id: Mapped[str] = mapped_column(String(120))
    citation_id: Mapped[str] = mapped_column(String(120))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    # structure
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    heading_path: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    title: Mapped[str] = mapped_column(String(500))

    # content — `text` (full, bounded) + `token_set` are what deterministic
    # scoring consumes; `excerpt` is display/prompt-budget ONLY (§5.1).
    text: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    char_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    has_tables: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    has_omitted_content: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    token_set: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    # classification (deterministic signature scoring; populated from M3, with
    # the provenance that gives signature upgrades a re-classify trigger)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    topics: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    keywords: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    market_flags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    persona_affinity: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    injection_flags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    classifier_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    signature_pack_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # --- M3 identity + classification provenance (additive) ---
    # How this section's anchor was decided (bounded typed metadata: decision
    # kind, inherited-from anchor, similarity) — enough to reproduce the
    # inheritance decision from stored inputs.
    anchor_provenance: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # The deterministic rule ids (module-namespaced) that supported this
    # section's classification. Bounded list; display/audit only.
    matched_rules: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    # Per-section deterministic classification signature (sha256 hex).
    classification_signature: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IngestionJob(Base):
    """Durable ingestion work item driving the version state machine.

    M1 creates the table and the enqueue seam; the worker that claims jobs
    lands in M2 with tenant-fair claiming (round-robin across tenants, never
    pure FIFO) and claim-time `attempts` increments — a job that kills the
    worker process must still hit the attempts cap instead of being requeued
    forever by the startup sweep of stale `running` rows.
    """

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        # The M2 worker sweeps stale `running` rows and claims `queued` ones.
        Index("ix_ingestion_jobs_state_heartbeat", "state", "heartbeat_at"),
        # At most ONE live (queued/running) job per version, enforced by the
        # database — enqueue's check-then-insert alone cannot survive two
        # concurrent sessions both seeing "no live job". Terminal states
        # (succeeded/failed) fall outside the partial index, so re-ingestion
        # history accumulates freely.
        Index(
            "uq_ingestion_jobs_live_version",
            "version_id",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
            sqlite_where=text("state IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default=JOB_STATE_QUEUED)
    # M3: explicit typed operation discriminator — "ingest" (M2 semantics,
    # the default so existing rows keep their meaning) or "finalize" (M3
    # successor processing). Never inferred from context.
    operation: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=JOB_OPERATION_INGEST
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    persona_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    market: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    persona_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    custom_persona: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    generation_mode: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    llm_provider: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
