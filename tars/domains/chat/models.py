"""Chat session and message dialogue turn entities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from tars.domains.auth.models import User


class ChatSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Conversation session entity supporting lifecycle, time decay, and bridge summaries."""

    __tablename__ = "chat_sessions"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(256), default="New Dialogue", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False, index=True
    )  # active, archived, closed
    bridge_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parent_session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sessions")
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<ChatSession id={self.id!r} user_id={self.user_id!r} "
            f"status={self.status!r} title={self.title!r}>"
        )


class ChatMessage(Base, UUIDPrimaryKeyMixin):
    """Individual dialogue message turn in a chat session."""

    __tablename__ = "chat_messages"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user, assistant, system
    content: Mapped[str] = mapped_column(String, nullable=False)
    tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Relationships
    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")

    def __init__(self, **kwargs: Any) -> None:
        if "token_count" in kwargs and "tokens" not in kwargs:
            kwargs["tokens"] = kwargs.pop("token_count")
        super().__init__(**kwargs)

    @property
    def token_count(self) -> int:
        return self.tokens

    @token_count.setter
    def token_count(self, value: int) -> None:
        self.tokens = value

    def __repr__(self) -> str:
        return (
            f"<ChatMessage id={self.id!r} session_id={self.session_id!r} "
            f"role={self.role!r} tokens={self.tokens}>"
        )


__all__ = ["ChatMessage", "ChatSession"]
