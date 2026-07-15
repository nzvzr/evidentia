"""production auth and multi-tenant foundation

Adds:
  * users.email_verified_at, users.is_active
  * companies.owner_id (organization ownership)
  * unique (company_id, user_id) on company_members
  * refresh_tokens / email_verification_tokens / password_reset_tokens

Data note: the previously seeded shared demo company ("northreach-cloud") is not
removed here — dropping it would delete the reports that reference it. It is now
an ordinary, ownerless company that no user is a member of, so it is unreachable
through the API. Delete it explicitly if the demo data is not wanted.

Revision ID: b2f4c8e91d07
Revises: c1a7ade159da
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2f4c8e91d07"
down_revision: Union[str, None] = "c1a7ade159da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    # --- companies: organization ownership ---
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("owner_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_companies_owner_id", ["owner_id"])
        batch.create_foreign_key(
            "fk_companies_owner_id_users", "users", ["owner_id"], ["id"], ondelete="RESTRICT"
        )

    # --- company_members: one role per (company, user) ---
    with op.batch_alter_table("company_members") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.create_unique_constraint(
            "uq_company_members_company_user", ["company_id", "user_id"]
        )

    # --- refresh tokens (rotating, family-based reuse detection) ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    # --- one-time tokens ---
    for table in ("email_verification_tokens", "password_reset_tokens"):
        op.create_table(
            table,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
        op.create_index(f"ix_{table}_token_hash", table, ["token_hash"], unique=True)


def downgrade() -> None:
    for table in ("password_reset_tokens", "email_verification_tokens"):
        op.drop_index(f"ix_{table}_token_hash", table_name=table)
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_table(table)

    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    with op.batch_alter_table("company_members") as batch:
        batch.drop_constraint("uq_company_members_company_user", type_="unique")
        batch.drop_column("updated_at")

    with op.batch_alter_table("companies") as batch:
        batch.drop_constraint("fk_companies_owner_id_users", type_="foreignkey")
        batch.drop_index("ix_companies_owner_id")
        batch.drop_column("owner_id")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_active")
        batch.drop_column("email_verified_at")
