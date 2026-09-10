"""User account entity for authentication and multi-tenant scoping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from tars.domains.chat.models import ChatSession
    from tars.domains.knowledge.models import UserWikiIndex
    from tars.domains.persona.models import TARSSettings


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
    sessions: Mapped[list[ChatSession]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} username={self.username!r} email={self.email!r} active={self.is_active}>"


__all__ = ["User"]
