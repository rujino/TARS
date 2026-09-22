"""Proactive utterance persistence models: messages, schedules, tokens, and settings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tars.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from tars.domains.auth.models import User


class ProactiveMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Proactive utterance message queue and dispatch history."""

    __tablename__ = "proactive_messages"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_id: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    okf_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, index=True
    )  # pending | delivered | read | dismissed
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_proactive_messages_user_status", "user_id", "status"),
        Index("ix_proactive_messages_scheduled_status", "scheduled_at", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProactiveMessage id={self.id!r} user_id={self.user_id!r} "
            f"type={self.schedule_type!r} status={self.status!r}>"
        )


class ProactiveScheduleEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Job registry for scheduler persistence and graceful recovery across reboots."""

    __tablename__ = "proactive_schedule_entries"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    okf_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    schedule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_proactive_schedules_active_run", "is_active", "next_run_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProactiveScheduleEntry id={self.id!r} user_id={self.user_id!r} "
            f"type={self.schedule_type!r} next_run_at={self.next_run_at!r} active={self.is_active}>"
        )


class UserDeviceToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User device push registration tokens for Firebase Cloud Messaging (FCM)."""

    __tablename__ = "user_device_tokens"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(
        String(32), default="web", nullable=False
    )  # web | ios | android
    device_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("user_id", "token", name="uq_user_device_tokens"),
        Index("ix_user_device_tokens_user_active", "user_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserDeviceToken id={self.id!r} user_id={self.user_id!r} "
            f"platform={self.platform!r} active={self.is_active}>"
        )


class ProactiveSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User-specific personalized proactive utterance preferences."""

    __tablename__ = "proactive_settings"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_daily_proactive: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 0-23
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul", nullable=False)
    enabled_types: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: [
            "review_reminder",
            "deadline_alert",
            "context_followup",
            "routine_reinforcement",
        ],
        nullable=False,
    )

    # Relationships
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<ProactiveSettings user_id={self.user_id!r} enabled={self.is_enabled} "
            f"timezone={self.timezone!r}>"
        )


__all__ = [
    "ProactiveMessage",
    "ProactiveScheduleEntry",
    "ProactiveSettings",
    "UserDeviceToken",
]
