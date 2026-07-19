"""M5a declarative claim engine, provenance, metrics and feedback.

Revision ID: f5a6c7d8e9b0
Revises: e4b7c9d2a610

All changes are additive. Existing reports receive no fabricated candidates or
decisions. Downgrade drops only M5a data and restores the exact M4 shape.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6c7d8e9b0"
down_revision: Union[str, None] = "e4b7c9d2a610"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def upgrade() -> None:
    with op.batch_alter_table("report_evidence_bindings") as batch:
        batch.create_unique_constraint(
            "uq_report_evidence_id_report_company", ["id", "report_id", "company_id"]
        )

    op.create_table(
        "claim_pattern_versions",
        _id(),
        sa.Column("claim_pack_id", sa.String(160), nullable=False),
        sa.Column("claim_pack_version", sa.String(40), nullable=False),
        sa.Column("module_id", sa.String(120), nullable=False),
        sa.Column("module_version", sa.String(40), nullable=False),
        sa.Column("claim_spec_id", sa.String(160), nullable=False),
        sa.Column("pattern_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("release_version", sa.String(40), nullable=False),
        sa.Column("release_digest", sa.String(64), nullable=False),
        sa.Column("pattern_digest", sa.String(64), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "claim_pack_id", "claim_spec_id", "pattern_version",
            name="uq_claim_pattern_versions_identity",
        ),
    )
    op.create_index(
        "ix_claim_pattern_versions_release", "claim_pattern_versions", ["claim_pack_id", "release_digest"]
    )

    op.create_table(
        "report_claim_candidates",
        _id(),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("claim_pattern_version_id", sa.String(36), nullable=True),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("claim_spec_id", sa.String(160), nullable=False),
        sa.Column("pattern_version", sa.String(40), nullable=False),
        sa.Column("candidate_source", sa.String(32), nullable=False),
        sa.Column("proposed_statement", sa.Text(), nullable=False),
        sa.Column("source_snapshot_digest", sa.String(80), nullable=False),
        sa.Column("matcher_observations", sa.JSON(), nullable=False),
        sa.Column("deterministic_features", sa.JSON(), nullable=False),
        sa.Column("proposer_metadata", sa.JSON(), nullable=True),
        sa.Column("status_before_gate", sa.String(24), nullable=False),
        sa.Column("appeared_in_final", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("report_id", "candidate_id", name="uq_report_claim_candidates_candidate"),
        sa.UniqueConstraint("id", "report_id", "company_id", name="uq_report_claim_candidates_id_report_company"),
        sa.ForeignKeyConstraint(
            ["report_id", "company_id"], ["reports.id", "reports.company_id"],
            name="fk_report_claim_candidates_report_company", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_pattern_version_id"], ["claim_pattern_versions.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_report_claim_candidates_company_report", "report_claim_candidates", ["company_id", "report_id"]
    )

    op.create_table(
        "report_claim_decisions",
        _id(),
        sa.Column("report_claim_candidate_id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("support_score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("matched_requirements", sa.JSON(), nullable=False),
        sa.Column("missing_requirements", sa.JSON(), nullable=False),
        sa.Column("conflicting_evidence", sa.JSON(), nullable=False),
        sa.Column("accepted_binding_ids", sa.JSON(), nullable=False),
        sa.Column("gate_policy_id", sa.String(120), nullable=False),
        sa.Column("gate_policy_version", sa.String(40), nullable=False),
        sa.Column("gate_engine_version", sa.String(80), nullable=False),
        sa.Column("deterministic_features", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("report_claim_candidate_id", name="uq_report_claim_decisions_candidate"),
        sa.ForeignKeyConstraint(
            ["report_claim_candidate_id", "report_id", "company_id"],
            ["report_claim_candidates.id", "report_claim_candidates.report_id", "report_claim_candidates.company_id"],
            name="fk_report_claim_decisions_candidate_company", ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_report_claim_decisions_company_report", "report_claim_decisions", ["company_id", "report_id"]
    )

    op.create_table(
        "report_claim_evidence",
        _id(),
        sa.Column("report_claim_candidate_id", sa.String(36), nullable=False),
        sa.Column("report_evidence_binding_id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("proposed", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "report_claim_candidate_id", "report_evidence_binding_id",
            name="uq_report_claim_evidence_candidate_binding",
        ),
        sa.ForeignKeyConstraint(
            ["report_claim_candidate_id", "report_id", "company_id"],
            ["report_claim_candidates.id", "report_claim_candidates.report_id", "report_claim_candidates.company_id"],
            name="fk_report_claim_evidence_candidate_company", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_evidence_binding_id", "report_id", "company_id"],
            ["report_evidence_bindings.id", "report_evidence_bindings.report_id", "report_evidence_bindings.company_id"],
            name="fk_report_claim_evidence_binding_company", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_report_claim_evidence_company_report", "report_claim_evidence", ["company_id", "report_id"])

    op.create_table(
        "pattern_metrics",
        _id(),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("claim_pattern_version_id", sa.String(36), nullable=False),
        sa.Column("evaluated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("binding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insufficient_evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_report_inclusion_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_proposed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "claim_pattern_version_id", name="uq_pattern_metrics_scope"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_pattern_version_id"], ["claim_pattern_versions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_pattern_metrics_company_pattern", "pattern_metrics", ["company_id", "claim_pattern_version_id"])

    op.create_table(
        "report_feedback",
        _id(), sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("private_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("report_id", "user_id", name="uq_report_feedback_user"),
        sa.ForeignKeyConstraint(["report_id", "company_id"], ["reports.id", "reports.company_id"], name="fk_report_feedback_report_company", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_report_feedback_company_report", "report_feedback", ["company_id", "report_id"])

    op.create_table(
        "item_feedback",
        _id(), sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("item_path", sa.String(300), nullable=False),
        sa.Column("item_type", sa.String(40), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("report_id", "user_id", "item_path", name="uq_item_feedback_user_path"),
        sa.ForeignKeyConstraint(["report_id", "company_id"], ["reports.id", "reports.company_id"], name="fk_item_feedback_report_company", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_item_feedback_company_report", "item_feedback", ["company_id", "report_id"])

    op.create_table(
        "citation_feedback",
        _id(), sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("report_evidence_binding_id", sa.String(36), nullable=False),
        sa.Column("item_path", sa.String(300), nullable=False),
        sa.Column("citation_id", sa.String(120), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("corrected_report_evidence_binding_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("report_id", "user_id", "item_path", "citation_id", name="uq_citation_feedback_user_item"),
        sa.ForeignKeyConstraint(["report_id", "company_id"], ["reports.id", "reports.company_id"], name="fk_citation_feedback_report_company", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_evidence_binding_id", "report_id", "company_id"], ["report_evidence_bindings.id", "report_evidence_bindings.report_id", "report_evidence_bindings.company_id"], name="fk_citation_feedback_binding_company", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["corrected_report_evidence_binding_id", "report_id", "company_id"], ["report_evidence_bindings.id", "report_evidence_bindings.report_id", "report_evidence_bindings.company_id"], name="fk_citation_feedback_corrected_binding_company"),
        sa.CheckConstraint("verdict != 'incorrect_source' OR corrected_report_evidence_binding_id IS NOT NULL", name="ck_citation_feedback_incorrect_source_binding"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_citation_feedback_company_report", "citation_feedback", ["company_id", "report_id"])

    op.create_table(
        "retrieval_misses",
        _id(), sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("report_claim_candidate_id", sa.String(36), nullable=False),
        sa.Column("claim_spec_id", sa.String(160), nullable=False),
        sa.Column("pattern_version", sa.String(40), nullable=False),
        sa.Column("evidence_need_id", sa.String(120), nullable=False),
        sa.Column("corrected_section_id", sa.String(36), nullable=False),
        sa.Column("corrected_version_id", sa.String(36), nullable=False),
        sa.Column("corrected_document_id", sa.String(36), nullable=False),
        sa.Column("corrected_anchor_id", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "report_id", "user_id", "report_claim_candidate_id", "evidence_need_id",
            name="uq_retrieval_misses_user_claim_need",
        ),
        sa.ForeignKeyConstraint(["report_id", "company_id"], ["reports.id", "reports.company_id"], name="fk_retrieval_misses_report_company", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_claim_candidate_id", "report_id", "company_id"], ["report_claim_candidates.id", "report_claim_candidates.report_id", "report_claim_candidates.company_id"], name="fk_retrieval_misses_candidate_company", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["corrected_section_id", "corrected_version_id", "corrected_document_id", "company_id"], ["document_sections.id", "document_sections.version_id", "document_sections.document_id", "document_sections.company_id"], name="fk_retrieval_misses_section_company"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_retrieval_misses_company_report", "retrieval_misses", ["company_id", "report_id"])


def downgrade() -> None:
    for table, index in (
        ("retrieval_misses", "ix_retrieval_misses_company_report"),
        ("citation_feedback", "ix_citation_feedback_company_report"),
        ("item_feedback", "ix_item_feedback_company_report"),
        ("report_feedback", "ix_report_feedback_company_report"),
        ("pattern_metrics", "ix_pattern_metrics_company_pattern"),
        ("report_claim_evidence", "ix_report_claim_evidence_company_report"),
        ("report_claim_decisions", "ix_report_claim_decisions_company_report"),
        ("report_claim_candidates", "ix_report_claim_candidates_company_report"),
        ("claim_pattern_versions", "ix_claim_pattern_versions_release"),
    ):
        op.drop_index(index, table_name=table)
        op.drop_table(table)
    with op.batch_alter_table("report_evidence_bindings") as batch:
        batch.drop_constraint("uq_report_evidence_id_report_company", type_="unique")
