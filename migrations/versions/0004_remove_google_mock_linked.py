"""0004_remove_google_mock_linked

Revision ID: 0004_remove_google_mock_linked
Revises: 0003_remove_humor_honesty
Create Date: 2026-09-17 22:25:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_remove_google_mock_linked"
down_revision: Union[str, None] = "0003_remove_humor_honesty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tars_settings") as batch_op:
        batch_op.drop_column("google_mock_linked")


def downgrade() -> None:
    with op.batch_alter_table("tars_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "google_mock_linked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
