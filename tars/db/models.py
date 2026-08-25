"""SQLAlchemy ORM models: User, TARSSettings, and UserWikiIndex."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User account entity for authentication and multi-tenant scoping."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    settings: Mapped[TARSSettings] = relationship(
        "TARSSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    wikis: Mapped[list[UserWikiIndex]] = relationship(
        "UserWikiIndex",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} username={self.username!r} email={self.email!r} active={self.is_active}>"


class TARSSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Personalized TARS agent settings per user (humor, honesty, mode)."""

    __tablename__ = "tars_settings"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    humor_level: Mapped[float] = mapped_column(
        Float, default=0.90, nullable=False
    )  # 0.0 to 1.0 (Default: 90%)
    honesty_level: Mapped[float] = mapped_column(
        Float, default=0.95, nullable=False
    )  # 0.0 to 1.0 (Default: 95%)
    mode: Mapped[str] = mapped_column(
        String(32), default="companion", nullable=False
    )  # "companion" | "work"

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return (
            f"<TARSSettings user_id={self.user_id!r} humor={self.humor_level} "
            f"honesty={self.honesty_level} mode={self.mode!r}>"
        )


# Backward and test compatibility alias
TarsSettings = TARSSettings


class UserWikiIndex(Base, UUIDPrimaryKeyMixin):
    """Metadata search index for OKF markdown documents stored in file storage."""

    __tablename__ = "user_wikis"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    okf_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    okf_version: Mapped[str] = mapped_column(String(16), default="1.0", nullable=False)
    type: Mapped[str] = mapped_column(
        String(32), default="concept", nullable=False, index=True
    )  # concept, rule, entity, procedure, preference
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tags: Mapped[Any] = mapped_column(
        JSON, default=list, nullable=False
    )  # List of normalized tag strings or JSON
    importance: Mapped[str] = mapped_column(
        String(16), default="medium", nullable=False, index=True
    )  # low, medium, high, critical
    source: Mapped[str] = mapped_column(
        String(32), default="manual", nullable=False
    )  # manual, auto_extracted, system
    relations: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )  # {"depends_on": [...], "related_to": [...]}
    file_path: Mapped[str] = mapped_column(
        String(512), default="", nullable=False
    )  # Path relative to storage root or absolute
    file_hash: Mapped[str] = mapped_column(
        String(64), default="", nullable=False
    )  # SHA-256 hexadecimal hash
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="wikis")

    __table_args__ = (
        UniqueConstraint("user_id", "okf_id", name="uq_user_wikis_user_okf_id"),
        Index("ix_user_wikis_lookup", "user_id", "type", "importance"),
        Index("ix_user_wikis_user_category", "user_id", "category"),
    )

    def __init__(self, **kwargs: Any) -> None:
        if "doc_type" in kwargs and "type" not in kwargs:
            kwargs["type"] = kwargs.pop("doc_type")
        if "tags" in kwargs and isinstance(kwargs["tags"], str):
            try:
                kwargs["tags"] = json.loads(kwargs["tags"])
            except Exception:
                pass
        super().__init__(**kwargs)

    @property
    def doc_type(self) -> str:
        return self.type

    @doc_type.setter
    def doc_type(self, value: str) -> None:
        self.type = value

    def __repr__(self) -> str:
        return (
            f"<UserWikiIndex okf_id={self.okf_id!r} type={self.type!r} "
            f"importance={self.importance!r} user_id={self.user_id!r}>"
        )


# Backward and test compatibility alias
UserWikiMetadata = UserWikiIndex


__all__ = [
    "TARSSettings",
    "TarsSettings",
    "User",
    "UserWikiIndex",
    "UserWikiMetadata",
]
