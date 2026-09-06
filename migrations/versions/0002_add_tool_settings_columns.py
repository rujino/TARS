"""0002_add_tool_settings_columns

Revision ID: 0002_tool_settings
Revises: 0001_initial_schema
Create Date: 2026-09-07 03:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_tool_settings"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tool preferences and Google OAuth columns to tars_settings
    op.add_column(
        "tars_settings",
        sa.Column("disabled_tools", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "tars_settings",
        sa.Column("google_refresh_token", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "tars_settings",
        sa.Column("google_access_token", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "tars_settings",
        sa.Column("google_linked_email", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "tars_settings",
        sa.Column("google_mock_linked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tars_settings",
        sa.Column("google_client_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "tars_settings",
        sa.Column("google_client_secret", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tars_settings", "google_client_secret")
    op.drop_column("tars_settings", "google_client_id")
    op.drop_column("tars_settings", "google_mock_linked")
    op.drop_column("tars_settings", "google_linked_email")
    op.drop_column("tars_settings", "google_access_token")
    op.drop_column("tars_settings", "google_refresh_token")
    op.drop_column("tars_settings", "disabled_tools")
