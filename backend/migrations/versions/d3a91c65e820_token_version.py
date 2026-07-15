"""access-token revocation via users.token_version

Adds the counter that makes a stateless access token revocable: password reset
and logout-all bump it, and any access token carrying an older `tv` claim is
rejected immediately instead of surviving for the rest of its TTL.

Revision ID: d3a91c65e820
Revises: b2f4c8e91d07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3a91c65e820"
down_revision: Union[str, None] = "b2f4c8e91d07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
