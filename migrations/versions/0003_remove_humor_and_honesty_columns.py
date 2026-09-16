"""0003_remove_humor_and_honesty_columns

Revision ID: 0003_remove_humor_honesty
Revises: 0002_tool_settings
Create Date: 2026-09-15 05:45:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_remove_humor_honesty"
down_revision: Union[str, None] = "0002_tool_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tars_settings") as batch_op:
        batch_op.drop_column("humor_level")
        batch_op.drop_column("honesty_level")


def downgrade() -> None:
    with op.batch_alter_table("tars_settings") as batch_op:
        batch_op.add_column(
            sa.Column("humor_level", sa.Float(), nullable=False, server_default="0.90")
        )
        batch_op.add_column(
            sa.Column("honesty_level", sa.Float(), nullable=False, server_default="0.95")
        )
