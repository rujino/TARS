"""Metadata search index for OKF markdown documents stored in file storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.core.database import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from tars.domains.auth.models import User


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
    tags: Mapped[Any] = mapped_column(JSON, default=list, nullable=False)
    importance: Mapped[str] = mapped_column(
        String(16), default="medium", nullable=False, index=True
    )  # low, medium, high, critical
    source: Mapped[str] = mapped_column(
        String(32), default="manual", nullable=False
    )  # manual, auto_extracted, system
    relations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
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


__all__ = ["UserWikiIndex"]
