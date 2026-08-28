"""0001_initial_schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-27 10:35:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column("hashed_password", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # 2. Create tars_settings table
    op.create_table(
        "tars_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("humor_level", sa.Float(), nullable=False, server_default="0.90"),
        sa.Column("honesty_level", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="companion"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tars_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tars_settings")),
    )
    op.create_index(op.f("ix_tars_settings_user_id"), "tars_settings", ["user_id"], unique=True)

    # 3. Create user_wikis table
    op.create_table(
        "user_wikis",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("okf_id", sa.String(length=128), nullable=False),
        sa.Column("okf_version", sa.String(length=16), nullable=False, server_default="1.0"),
        sa.Column("type", sa.String(length=32), nullable=False, server_default="concept"),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("importance", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("relations", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("file_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_wikis_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_wikis")),
        sa.UniqueConstraint("user_id", "okf_id", name="uq_user_wikis_user_okf_id"),
    )
    op.create_index(op.f("ix_user_wikis_user_id"), "user_wikis", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_wikis_okf_id"), "user_wikis", ["okf_id"], unique=False)
    op.create_index(op.f("ix_user_wikis_type"), "user_wikis", ["type"], unique=False)
    op.create_index(op.f("ix_user_wikis_category"), "user_wikis", ["category"], unique=False)
    op.create_index(op.f("ix_user_wikis_importance"), "user_wikis", ["importance"], unique=False)
    op.create_index("ix_user_wikis_lookup", "user_wikis", ["user_id", "type", "importance"], unique=False)
    op.create_index("ix_user_wikis_user_category", "user_wikis", ["user_id", "category"], unique=False)

    # 4. Create chat_sessions table
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False, server_default="New Dialogue"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("bridge_summary", sa.String(length=1024), nullable=True),
        sa.Column("parent_session_id", sa.String(length=36), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_sessions_parent_session_id_chat_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_chat_sessions_status"), "chat_sessions", ["status"], unique=False)
    op.create_index(op.f("ix_chat_sessions_last_active_at"), "chat_sessions", ["last_active_at"], unique=False)

    # 5. Create chat_messages table
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_messages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index(op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_user_id"), "chat_messages", ["user_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_created_at"), "chat_messages", ["created_at"], unique=False)


def downgrade() -> None:
    # Drop tables in reverse foreign-key dependency order
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("user_wikis")
    op.drop_table("tars_settings")
    op.drop_table("users")
