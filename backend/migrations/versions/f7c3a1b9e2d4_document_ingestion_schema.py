"""document ingestion schema (M1: schema + seams)

Additive only — no existing column is altered or dropped, no data is rewritten,
and nothing reads the new tables while EVIDENTIA_TENANT_CORPUS_ENABLED is off
(the default). Design: docs/ai/PLATFORM_ARCHITECTURE.md §12 (M1 gate) and
docs/ai/DOCUMENT_INGESTION_ARCHITECTURE.md §3.

Adds:
  * documents.{source_type, origin_uri, original_filename, mime_type,
    content_sha256, size_bytes, citation_prefix, current_version_id, status,
    deleted_at, created_by}
  * document_versions   — immutable ingested revisions (status state machine)
  * document_blobs      — original bytes, 1–1 per version, behind the BlobStore seam
  * document_sections   — immutable extracted sections (SectionRecord v1 persisted)
  * ingestion_jobs      — durable job rows for the M2 worker

`documents.current_version_id` is deliberately NOT a DB-level foreign key:
documents and document_versions would reference each other circularly, and
SQLite (the dev database, where the test schema is created via
Base.metadata.create_all) cannot add the second constraint of such a pair.
The single atomic flip site enforces integrity in application code.

`documents.content_text` is deprecated from this migration onward: it is kept
for backfill/back-compat and gets an explicit removal milestone once backfill
is verified (debt watch, PLATFORM_ARCHITECTURE.md §12).

Crash-safe blob/row write order (binding contract for every writer, including
scripts/backfill_documents.py and the M2 ingestion worker):

    1. INSERT document_versions row with status='pending'
    2. BlobStore.put(...)  ->  INSERT document_blobs row referencing the version
    3. only then: enqueue/perform work; the version may advance toward 'ready'
    4. documents.current_version_id flips atomically, only ever to a 'ready'
       version

A crash between steps 1 and 2 leaves an inert 'pending' version row (harmless:
never referenced by current_version_id, retried or expired by the worker). With
the v1 DB-backed BlobStore both steps commit in one transaction, so no
intermediate state is observable at all. When BlobStore moves to object
storage, a crash between the object upload and the row commit leaves an
orphaned blob object — reconciliation strategy, designed now because it becomes
acute exactly then:

    * a periodic sweep lists stored blobs and deletes any blob that no
      document_blobs row references and whose age exceeds a grace window
      (grace >> the longest plausible ingestion transaction, e.g. 24h, so an
      in-flight upload is never swept);
    * the sweep is safe to run at any time because writers follow the order
      above: a referenced blob is always referenced *before* any state that
      matters depends on it, and an unreferenced-but-young blob is left alone.

Revision ID: f7c3a1b9e2d4
Revises: d3a91c65e820
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7c3a1b9e2d4"
down_revision: Union[str, None] = "d3a91c65e820"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- documents: additive ingestion columns ---
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("source_type", sa.String(40), nullable=False, server_default="api"))
        batch.add_column(sa.Column("origin_uri", sa.String(1000), nullable=True))
        batch.add_column(sa.Column("original_filename", sa.String(400), nullable=True))
        batch.add_column(sa.Column("mime_type", sa.String(120), nullable=True))
        batch.add_column(sa.Column("content_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("citation_prefix", sa.String(8), nullable=True))
        batch.add_column(sa.Column("current_version_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="empty"))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "created_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_documents_created_by_users"),
                nullable=True,
            )
        )

    # citation_prefix is identity, unique per tenant (minted at M3); the
    # database enforces it so minting can never race itself into two documents
    # sharing a citation family. NULLs are distinct under both PostgreSQL and
    # SQLite, so pre-M3 documents (all NULL) coexist freely.
    op.create_index(
        "uq_documents_company_citation_prefix",
        "documents",
        ["company_id", "citation_prefix"],
        unique=True,
    )

    # --- document_versions ---
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("extracted_sha256", sa.String(64), nullable=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("parser_name", sa.String(80), nullable=True),
        sa.Column("parser_version", sa.String(40), nullable=True),
        sa.Column("anchor_algo_version", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("section_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_no"),
    )
    # No single-column document_id index: the unique (document_id, version_no)
    # constraint's leftmost column already serves that access path.
    op.create_index("ix_document_versions_company_id", "document_versions", ["company_id"])

    # --- document_blobs ---
    op.create_table(
        "document_blobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("version_id", name="uq_document_blobs_version"),
        sa.UniqueConstraint("storage_key", name="uq_document_blobs_storage_key"),
    )
    op.create_index("ix_document_blobs_company_id", "document_blobs", ["company_id"])

    # --- document_sections ---
    op.create_table(
        "document_sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("anchor_id", sa.String(120), nullable=False),
        sa.Column("citation_id", sa.String(120), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("heading_path", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.String(64), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("has_tables", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("has_omitted_content", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("token_set", sa.JSON(), nullable=True),
        sa.Column("category", sa.String(80), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("market_flags", sa.JSON(), nullable=True),
        sa.Column("persona_affinity", sa.JSON(), nullable=True),
        sa.Column("injection_flags", sa.JSON(), nullable=True),
        sa.Column("classifier_version", sa.String(40), nullable=True),
        sa.Column("signature_pack_version", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("version_id", "anchor_id", name="uq_document_sections_version_anchor"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_document_sections_version_ordinal"),
    )
    op.create_index("ix_document_sections_document_id", "document_sections", ["document_id"])
    op.create_index("ix_document_sections_version_id", "document_sections", ["version_id"])
    # Also the company_id access path via its leftmost column, so no separate
    # single-column company_id index exists.
    op.create_index(
        "ix_document_sections_company_document", "document_sections", ["company_id", "document_id"]
    )

    # --- ingestion_jobs ---
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ingestion_jobs_company_id", "ingestion_jobs", ["company_id"])
    op.create_index("ix_ingestion_jobs_document_id", "ingestion_jobs", ["document_id"])
    op.create_index("ix_ingestion_jobs_version_id", "ingestion_jobs", ["version_id"])
    op.create_index("ix_ingestion_jobs_state_heartbeat", "ingestion_jobs", ["state", "heartbeat_at"])
    # At most ONE live (queued/running) job per version, enforced by the
    # database — enqueue's check-then-insert alone cannot survive two
    # concurrent sessions both seeing "no live job". Terminal states fall
    # outside the partial index, so re-ingestion history accumulates freely.
    op.create_index(
        "uq_ingestion_jobs_live_version",
        "ingestion_jobs",
        ["version_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
        sqlite_where=sa.text("state IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_jobs")
    op.drop_table("document_sections")
    op.drop_table("document_blobs")
    op.drop_table("document_versions")
    op.drop_index("uq_documents_company_citation_prefix", table_name="documents")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("created_by")
        batch.drop_column("deleted_at")
        batch.drop_column("status")
        batch.drop_column("current_version_id")
        batch.drop_column("citation_prefix")
        batch.drop_column("size_bytes")
        batch.drop_column("content_sha256")
        batch.drop_column("mime_type")
        batch.drop_column("original_filename")
        batch.drop_column("origin_uri")
        batch.drop_column("source_type")
