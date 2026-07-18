"""M4 tenant generation provenance and evidence bindings.

Revision ID: e4b7c9d2a610
Revises: a9d2e4c7b1f3

The public report JSON is unchanged. Existing rows are backfilled as completed
demo reports with empty source metadata; no fake tenant bindings are created.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c9d2a610"
down_revision: Union[str, None] = "a9d2e4c7b1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.create_unique_constraint("uq_documents_id_company", ["id", "company_id"])

    with op.batch_alter_table("document_sections") as batch:
        batch.create_unique_constraint(
            "uq_document_sections_id_version_doc_company",
            ["id", "version_id", "document_id", "company_id"],
        )

    with op.batch_alter_table("reports") as batch:
        batch.create_unique_constraint("uq_reports_id_company", ["id", "company_id"])
        batch.add_column(sa.Column("source_versions", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("engine_versions", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("corpus_mode", sa.String(16), nullable=False, server_default="demo")
        )
        batch.add_column(sa.Column("corpus_snapshot_digest", sa.String(80), nullable=True))
        batch.add_column(sa.Column("retrieval_engine_version", sa.String(80), nullable=True))
        batch.add_column(sa.Column("orchestrator_version", sa.String(80), nullable=True))
        batch.add_column(sa.Column("execution_mode", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column("generation_status", sa.String(20), nullable=False, server_default="completed")
        )
        batch.add_column(sa.Column("generation_error_code", sa.String(80), nullable=True))
        batch.add_column(
            sa.Column("source_version_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("evidence_section_count", sa.Integer(), nullable=False, server_default="0")
        )

    op.create_table(
        "report_source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("finalization_target_digest", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("report_id", "position", name="uq_report_source_versions_position"),
        sa.UniqueConstraint(
            "report_id", "document_version_id", name="uq_report_source_versions_version"
        ),
        sa.UniqueConstraint(
            "id", "report_id", "company_id", name="uq_report_source_versions_id_report_company"
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "company_id"],
            ["reports.id", "reports.company_id"],
            name="fk_report_source_versions_report_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "document_id", "company_id"],
            ["document_versions.id", "document_versions.document_id", "document_versions.company_id"],
            name="fk_report_source_versions_version_company",
        ),
    )
    op.create_index(
        "ix_report_source_versions_company_report",
        "report_source_versions",
        ["company_id", "report_id"],
    )

    op.create_table(
        "report_evidence_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("report_source_version_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False),
        sa.Column("section_id", sa.String(36), nullable=False),
        sa.Column("anchor_id", sa.String(120), nullable=False),
        sa.Column("citation_id", sa.String(120), nullable=False),
        sa.Column("section_ordinal", sa.Integer(), nullable=False),
        sa.Column("section_signature", sa.String(64), nullable=False),
        sa.Column("retrieval_rank", sa.Integer(), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=False),
        sa.Column("selected_for_prompt", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("cited_in_final", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=True),
        sa.Column("document_title", sa.String(300), nullable=False),
        sa.Column("original_filename", sa.String(400), nullable=True),
        sa.Column("section_title", sa.String(500), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=True),
        sa.UniqueConstraint("report_id", "citation_id", name="uq_report_evidence_citation"),
        sa.UniqueConstraint("report_id", "retrieval_rank", name="uq_report_evidence_rank"),
        sa.ForeignKeyConstraint(
            ["report_id", "company_id"],
            ["reports.id", "reports.company_id"],
            name="fk_report_evidence_report_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_source_version_id", "report_id", "company_id"],
            ["report_source_versions.id", "report_source_versions.report_id", "report_source_versions.company_id"],
            name="fk_report_evidence_source_report_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id", "document_version_id", "document_id", "company_id"],
            ["document_sections.id", "document_sections.version_id", "document_sections.document_id", "document_sections.company_id"],
            name="fk_report_evidence_section_company",
        ),
    )
    op.create_index(
        "ix_report_evidence_company_report",
        "report_evidence_bindings",
        ["company_id", "report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_evidence_company_report", table_name="report_evidence_bindings")
    op.drop_table("report_evidence_bindings")
    op.drop_index("ix_report_source_versions_company_report", table_name="report_source_versions")
    op.drop_table("report_source_versions")

    with op.batch_alter_table("reports") as batch:
        batch.drop_column("evidence_section_count")
        batch.drop_column("source_version_count")
        batch.drop_column("generation_error_code")
        batch.drop_column("generation_status")
        batch.drop_column("execution_mode")
        batch.drop_column("orchestrator_version")
        batch.drop_column("retrieval_engine_version")
        batch.drop_column("corpus_snapshot_digest")
        batch.drop_column("corpus_mode")
        batch.drop_column("engine_versions")
        batch.drop_column("source_versions")
        batch.drop_constraint("uq_reports_id_company", type_="unique")

    with op.batch_alter_table("document_sections") as batch:
        batch.drop_constraint("uq_document_sections_id_version_doc_company", type_="unique")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_documents_id_company", type_="unique")

